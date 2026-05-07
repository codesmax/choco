"""Conversation session powered by Pipecat"""
import asyncio
import logging
import re
import time

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    EndFrame,
    LLMRunFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    AssistantTurnStoppedMessage,
    LLMAssistantAggregatorParams,
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
    UserTurnStoppedMessage,
)
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from rapidfuzz import fuzz

from chocopi.audio import AUDIO
from chocopi.config import CONFIG, PROVIDER
from chocopi.memory import (
    build_memory_block,
    load_memory,
    save_memory,
    summarize_session,
    update_memory,
)
from chocopi.providers import create_llm_service

logger = logging.getLogger(__name__)


class _DisplaySync(FrameProcessor):
    """Syncs display speaking animation to bot audio start/stop."""

    def __init__(self, display):
        super().__init__()
        self._display = display

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, BotStartedSpeakingFrame):
            self._display.set_speaking(True)
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._display.set_speaking(False)
        await self.push_frame(frame, direction)


class ConversationSession:
    """Conversation session backed by a Pipecat voice LLM pipeline."""

    def __init__(self, learning_language="ko", profile=None, display=None):
        if profile is None:
            raise ValueError("ConversationSession requires a profile configuration")

        provider_config = CONFIG["providers"][PROVIDER]
        self.session_config = CONFIG["session"]
        self.profile = profile
        self.profile_name = profile.get("name", "default").lower()
        self.memory = load_memory(self.profile_name)
        self.lang_config = CONFIG["languages"][learning_language]
        self.comprehension_age = profile["learning_languages"][learning_language]["comprehension_age"]
        self.display = display

        self.is_greeting = True
        self.is_terminating = False
        self.last_user_transcript = ""
        self.last_assistant_transcript = ""
        self.transcript_log = []
        self.session_start_time = None
        self._consecutive_echo_turns = 0
        self._use_local_vad = self.session_config.get("vad", "server") == "local"
        # OpenAI uses create_response=False so responses must be triggered manually
        # after on_user_turn_stopped; Gemini/Ultravox use server VAD and auto-respond.
        self._manual_response = PROVIDER == "openai_realtime"

        native_language = CONFIG["languages"][profile["native_language"]]["language_name"]
        self.instruction_params = {
            "user_age": profile["user_age"],
            "native_language": native_language,
            "learning_language": self.lang_config["language_name"],
            "comprehension_age": self.comprehension_age,
            "sleep_word": self.lang_config["sleep_word"],
        }

        translations = profile["learning_languages"][learning_language].get("translations", True)
        translation_instruction = (
            f"- Always translate your full response to {native_language}."
            if translations else ""
        )

        memory_block = build_memory_block(self.memory)
        greeting = CONFIG["prompts"]["greeting"].format(**self.instruction_params)
        session_body = CONFIG["prompts"]["session"].format(
            **self.instruction_params,
            memory_block=memory_block,
            translation_instruction=translation_instruction,
        )
        self._session_instructions = f"# Opening\n{greeting}\n\n{session_body}"
        logger.debug("⚙️  Session instructions: %s", self._session_instructions)

        transcription_instructions = CONFIG["prompts"]["transcription"].format(**self.instruction_params)

        self._llm_service = create_llm_service(
            PROVIDER,
            provider_config,
            self._session_instructions,
            transcription_instructions,
            use_local_vad=self._use_local_vad,
        )

    # --- Transcript helpers ---

    def _is_echo(self, transcript: str) -> bool:
        echo_cfg = self.session_config.get("echo_detection", {})
        max_words = echo_cfg.get("max_words", 4)
        threshold = echo_cfg.get("overlap_threshold", 80)
        if not transcript or not self.last_assistant_transcript:
            return False
        if len(transcript.split()) > max_words:
            return False
        return fuzz.partial_ratio(transcript.lower(), self.last_assistant_transcript.lower()) >= threshold

    def _is_sleep_word(self, text: str, threshold: int = 80) -> bool:
        sleep_word = self.lang_config["sleep_word"].lower()
        if not text or not sleep_word:
            return False
        filtered = re.sub(r"[,.!?]", "", text.strip().lower())
        score = fuzz.partial_ratio(sleep_word, filtered)
        if score >= threshold:
            logger.debug("✅ Sleep word matched: '%s' (score: %d)", sleep_word, score)
            return True
        return False

    def _record_transcript(self, role: str, transcript: str, log_format: str, display_role: str):
        logger.info(log_format, transcript)
        if role == "user":
            self.last_user_transcript = transcript
        else:
            self.last_assistant_transcript = transcript
        if transcript:
            self.transcript_log.append({"role": role, "text": transcript})
        if self.display:
            self.display.add_transcript(display_role, transcript)

    # --- Main loop ---

    async def run(self):
        """Build and run the Pipecat pipeline for this conversation session."""
        transport = LocalAudioTransport(
            LocalAudioTransportParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
            )
        )

        vad_params = None
        if self._use_local_vad:
            from pipecat.audio.vad.silero import SileroVADAnalyzer
            vad_params = LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer())

        context = LLMContext()
        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            context,
            user_params=vad_params,
            assistant_params=LLMAssistantAggregatorParams(
                enable_auto_context_summarization=True,
            ),
        )

        pipeline_stages = [transport.input(), user_aggregator, self._llm_service]
        if self.display:
            pipeline_stages.append(_DisplaySync(self.display))
        pipeline_stages.extend([transport.output(), assistant_aggregator])

        pipeline = Pipeline(pipeline_stages)
        task = PipelineTask(pipeline)

        @user_aggregator.event_handler("on_user_turn_stopped")
        async def on_user_turn_stopped(aggregator, strategy, message: UserTurnStoppedMessage):
            self._record_transcript("user", message.content, "🗣️  You said: %s", "user")

            if self.is_greeting:
                return

            AUDIO.start_playing(CONFIG["sounds"]["sent"])

            echo_cfg = self.session_config.get("echo_detection", {})
            if self._is_echo(message.content):
                self._consecutive_echo_turns += 1
                logger.debug(
                    "🔁 Echo candidate (%d/%d): '%s'",
                    self._consecutive_echo_turns, echo_cfg.get("consecutive_limit", 5), message.content,
                )
                if self._consecutive_echo_turns >= echo_cfg.get("consecutive_limit", 5):
                    logger.warning("🔁 Echo loop detected after %d turns", self._consecutive_echo_turns)
                    self.is_terminating = True
            else:
                self._consecutive_echo_turns = 0

            if not self.is_terminating and self._is_sleep_word(
                message.content, self.session_config["sleep_word_threshold"]
            ):
                logger.info("💤 Sleep word detected: '%s'", message.content)
                self.is_terminating = True

            if self._manual_response:
                await task.queue_frames([LLMRunFrame()])

        @assistant_aggregator.event_handler("on_assistant_turn_stopped")
        async def on_assistant_turn_stopped(aggregator, message: AssistantTurnStoppedMessage):
            self._record_transcript("assistant", message.content, "🤖 Choco says: %s", "choco")

            if self.is_greeting:
                self.is_greeting = False
                self.session_start_time = time.monotonic()
                logger.info("👂 Choco is listening...")
                return

            if self.is_terminating:
                await task.queue_frames([EndFrame()])

        await task.queue_frames([LLMRunFrame()])

        try:
            runner = PipelineRunner(handle_sigint=False)
            await runner.run(task)
        except Exception as e:
            logger.error("⚠️  Error during conversation: %s", e)

    # --- Memory ---

    async def persist_memory(self):
        """Summarize and persist session memory."""
        memory = self.memory
        logger.info("🧠 Updating memory with latest conversation...")
        if self.transcript_log:
            try:
                memory = await asyncio.to_thread(
                    summarize_session,
                    self.profile_name,
                    self.profile,
                    self.transcript_log,
                    memory,
                )
            except Exception as exc:
                logger.warning("Memory summarization error: %s", exc)
                update_memory(memory, self.last_user_transcript, self.last_assistant_transcript)
        else:
            update_memory(memory, self.last_user_transcript, self.last_assistant_transcript)

        try:
            await asyncio.to_thread(save_memory, self.profile_name, memory)
            logger.info("💾 Memory saved successfully.")
        except Exception as exc:
            logger.warning("Memory save error: %s", exc)
            return
        self.memory = memory
