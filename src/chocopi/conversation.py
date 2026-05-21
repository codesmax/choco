"""Conversation session powered by Pipecat"""
import asyncio
import re

from loguru import logger
from pipecat.frames.frames import EndFrame, LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    AssistantTurnStoppedMessage,
    LLMAssistantAggregatorParams,
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
    UserTurnStoppedMessage,
)
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from rapidfuzz import fuzz

from chocopi.config import CONFIG, PROVIDER
from chocopi.memory import (
    build_memory_block,
    load_memory,
    save_memory,
    summarize_session,
    update_memory,
)
from chocopi.pipecat_utils import (
    DisplaySyncProcessor,
    SentSoundProcessor,
    TranscriptObserver,
    load_sound_frame,
)
from chocopi.providers import create_llm_service


class ConversationSession:
    """Conversation session backed by a Pipecat voice LLM pipeline."""

    def __init__(self, learning_language, profile, display=None):

        provider_config = CONFIG.providers[PROVIDER]
        self.session_config = CONFIG.session
        self.profile = profile
        self.profile_name = profile.get("name", "default").lower()
        self.memory = load_memory(self.profile_name)
        self.lang_config = CONFIG.languages[learning_language]
        comprehension_age = profile["learning_languages"][learning_language]["comprehension_age"]
        self.display = display

        self.is_greeting = True
        self.is_terminating = False
        self.last_user_transcript = ""
        self.last_assistant_transcript = ""
        self.transcript_log = []
        self._consecutive_echo_turns = 0
        self._use_local_vad = bool(provider_config.vad and provider_config.vad.local)

        native_language = CONFIG.languages[profile["native_language"]].language_name
        params = {
            "user_age": profile["user_age"],
            "native_language": native_language,
            "learning_language": self.lang_config.language_name,
            "comprehension_age": comprehension_age,
            "sleep_word": self.lang_config.sleep_word,
        }

        translations = profile["learning_languages"][learning_language].get("translations", True)
        translation_instruction = (
            f"- Always translate your full response to {native_language}."
            if translations else ""
        )

        memory_block = build_memory_block(self.memory)
        self._session_instructions = CONFIG.prompts.session.format(
            **params,
            memory_block=memory_block,
            translation_instruction=translation_instruction,
        )
        self._greeting_message = CONFIG.prompts.greeting.format(**params)
        logger.debug("⚙️  Session instructions: {}", self._session_instructions)

        transcription_instructions = CONFIG.prompts.transcription.format(**params)

        self._llm_service = create_llm_service(
            PROVIDER,
            provider_config,
            self._session_instructions,
            transcription_instructions,
        )

        self._sent_frame = load_sound_frame(CONFIG.sounds.sent)

    # --- Transcript helpers ---

    def _is_echo(self, transcript: str) -> bool:
        echo_config = self.session_config.echo_detection
        max_words = echo_config.max_words or 4
        threshold = echo_config.overlap_threshold or 80
        if not transcript or not self.last_assistant_transcript:
            return False
        if len(transcript.split()) > max_words:
            return False
        return fuzz.partial_ratio(transcript.lower(), self.last_assistant_transcript.lower()) >= threshold

    def _is_sleep_word(self, text: str, threshold: int = 80) -> bool:
        sleep_word = self.lang_config.sleep_word.lower()
        if not text or not sleep_word:
            return False
        filtered = re.sub(r"[,.!?]", "", text.strip().lower())
        score = fuzz.partial_ratio(sleep_word, filtered)
        if score >= threshold:
            logger.debug("✅ Sleep word matched: '{}' (score: {})", sleep_word, score)
            return True
        return False

    def _record_transcript(self, role: str, transcript: str):
        if role == "user":
            logger.info("🗣️  You said: {}", transcript)
            self.last_user_transcript = transcript
        else:
            logger.info("🤖 Choco says: {}", transcript)
            self.last_assistant_transcript = transcript
        if transcript:
            self.transcript_log.append({"role": role, "text": transcript})
        if self.display:
            self.display.add_transcript("choco" if role == "assistant" else role, transcript)

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

        # Seed the conversation with the greeting instruction as the first user turn.
        context = LLMContext([{"role": "user", "content": self._greeting_message}])
        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            context,
            user_params=vad_params,
            assistant_params=LLMAssistantAggregatorParams(
                enable_auto_context_summarization=True,
            ),
        )

        pipeline_stages = [transport.input(), user_aggregator, SentSoundProcessor(lambda: self.is_greeting, self._sent_frame), self._llm_service]
        if self.display:
            pipeline_stages.append(DisplaySyncProcessor(self.display))
        pipeline_stages.extend([transport.output(), assistant_aggregator])

        pipeline = Pipeline(pipeline_stages)
        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
            idle_timeout_secs=self.session_config.conversation_timeout,
            observers=[TranscriptObserver()],
        )

        @user_aggregator.event_handler("on_user_turn_stopped")
        async def on_user_turn_stopped(aggregator, strategy, message: UserTurnStoppedMessage):
            if not message.content:
                return

            self._record_transcript("user", message.content)

            if self.is_greeting:
                return

            echo_config = self.session_config.echo_detection
            if self._is_echo(message.content):
                self._consecutive_echo_turns += 1
                logger.debug(
                    "🔁 Echo candidate ({}/{}): '{}'",
                    self._consecutive_echo_turns, echo_config.consecutive_limit or 5, message.content,
                )
                if self._consecutive_echo_turns >= (echo_config.consecutive_limit or 5):
                    logger.warning("🔁 Echo loop detected after {} turns", self._consecutive_echo_turns)
                    self.is_terminating = True
            else:
                self._consecutive_echo_turns = 0

            if not self.is_terminating and self._is_sleep_word(
                message.content, self.session_config.sleep_word_threshold
            ):
                logger.info("💤 Sleep word detected: '{}'", message.content)
                self.is_terminating = True

        @assistant_aggregator.event_handler("on_assistant_turn_stopped")
        async def on_assistant_turn_stopped(aggregator, message: AssistantTurnStoppedMessage):
            if not message.content:
                logger.debug("⚠️  Empty assistant turn (interrupted={})", message.interrupted)
                return

            self._record_transcript("assistant", message.content)

            if self.is_greeting:
                self.is_greeting = False
                logger.info("👂 Choco is listening...")
                return

            if self.is_terminating:
                await task.queue_frames([EndFrame()])

        await task.queue_frames([LLMRunFrame()])

        try:
            runner = PipelineRunner(handle_sigint=False)
            await runner.run(task)
        except Exception as e:
            logger.error("⚠️  Error during conversation: {}", e)

    # --- Memory ---

    async def persist_memory(self):
        """Summarize and persist session memory."""
        memory = self.memory
        logger.info("🧠 Updating memory with latest conversation...")
        if self.transcript_log:
            try:
                memory = await asyncio.to_thread(
                    summarize_session,
                    self.profile,
                    self.transcript_log,
                    memory,
                )
            except Exception as exc:
                logger.warning("Memory summarization error: {}", exc)
                update_memory(memory, self.last_user_transcript)
        else:
            update_memory(memory, self.last_user_transcript)

        try:
            await asyncio.to_thread(save_memory, self.profile_name, memory)
            logger.info("💾 Memory saved successfully.")
        except Exception as exc:
            logger.warning("Memory save error: {}", exc)
            return
        self.memory = memory
