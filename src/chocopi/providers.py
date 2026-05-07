"""Pipecat LLM service factories for each supported provider"""
import logging
import os

logger = logging.getLogger(__name__)


def create_llm_service(
    provider_name,
    provider_config,
    session_instructions,
    transcription_instructions="",
    use_local_vad=False,
):
    """
    Instantiate the Pipecat LLM service for the given provider.
    Returns the configured service instance.
    """
    if provider_name == "openai_realtime":
        return _openai_realtime(provider_config, session_instructions, transcription_instructions)
    elif provider_name == "gemini_live":
        return _gemini_live(provider_config, session_instructions, use_local_vad)
    elif provider_name == "ultravox":
        return _ultravox(provider_config, session_instructions)
    else:
        raise ValueError(f"Unknown provider: {provider_name!r}")


def _openai_realtime(config, session_instructions, transcription_instructions):
    """
    OpenAI Realtime API via Pipecat.

    Extends the base service with three additions:
    1. LLMRunFrame triggers _create_response() — required because create_response=False
       disables server-side auto-response on VAD; ChocoPi triggers manually from
       on_user_turn_stopped so echo/sleep-word detection runs first.
    2. _handle_context is a no-op to prevent LLMContextAggregatorPair's context frame
       from double-triggering a response alongside the manual LLMRunFrame.
    3. send_client_event patches SessionUpdateEvent to include create_response=False and
       interrupt_response=True in server_vad turn_detection (Pipecat's TurnDetection model
       omits these fields, so they must be patched post-serialization).
    4. _truncate_current_audio_response is a no-op to prevent invalid_value server errors
       when Pipecat's byte count exceeds the server's committed bytes on interruption.
    """
    from pipecat.frames.frames import LLMRunFrame
    from pipecat.services.openai.realtime.events import (
        AudioConfiguration,
        AudioInput,
        AudioOutput,
        InputAudioNoiseReduction,
        InputAudioTranscription,
        SessionProperties,
        SessionUpdateEvent,
        TurnDetection,
    )
    from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService as _Base

    class OpenAIRealtimeLLMService(_Base):
        async def process_frame(self, frame, direction):
            if isinstance(frame, LLMRunFrame):
                await self._create_response()
                return
            await super().process_frame(frame, direction)

        async def _handle_context(self, context):
            pass  # Response triggered manually via LLMRunFrame

        async def send_client_event(self, event):
            if isinstance(event, SessionUpdateEvent):
                data = event.model_dump(exclude_none=True)
                try:
                    td = data["session"]["audio"]["input"]["turn_detection"]
                    if isinstance(td, dict) and td.get("type") == "server_vad":
                        td["create_response"] = False
                        td["interrupt_response"] = True
                except (KeyError, TypeError) as e:
                    logger.warning("⚠️  Could not patch turn_detection in session.update: %s", e)
                logger.debug(
                    "📤 session.update turn_detection: %s",
                    data.get("session", {}).get("audio", {}).get("input", {}).get("turn_detection"),
                )
                await self._ws_send(data)
                return
            await super().send_client_event(event)

        async def _truncate_current_audio_response(self):
            self._current_audio_response = None

    pc = config
    td = pc.get("turn_detection", {})
    noise_red = pc.get("noise_reduction")

    return OpenAIRealtimeLLMService(
        api_key=os.getenv(pc["api_key_env"]),
        settings=OpenAIRealtimeLLMService.Settings(
            model=pc["model"],
            system_instruction=session_instructions,
            session_properties=SessionProperties(
                audio=AudioConfiguration(
                    input=AudioInput(
                        transcription=InputAudioTranscription(
                            model=pc.get("transcription_model", "gpt-4o-mini-transcribe"),
                            prompt=transcription_instructions,
                        ),
                        noise_reduction=InputAudioNoiseReduction(type=noise_red) if noise_red else None,
                        turn_detection=TurnDetection(
                            threshold=td.get("threshold", 0.3),
                            prefix_padding_ms=td.get("prefix_padding_ms", 300),
                            silence_duration_ms=td.get("silence_duration_ms", 1200),
                        ) if td else None,
                    ),
                    output=AudioOutput(
                        voice=pc.get("voice", "alloy"),
                        speed=pc.get("output_speed", 1.0),
                    ),
                ),
            ),
        ),
    )


def _gemini_live(config, session_instructions, use_local_vad=False):
    """
    Google Gemini Live API via Pipecat (pipecat-ai[google]).

    Per-response instruction injection is not available in Gemini Live; all rules
    (translation, sleep word, greeting) are baked into session_instructions once at startup.

    Audio gate (server VAD only): mic audio is suppressed while the bot is speaking to
    prevent hardware echo from triggering Gemini's server-side VAD. Disabled when using
    local VAD (SileroVADAnalyzer), which controls ActivityStart/ActivityEnd signals directly.

    _create_initial_response override: base class seeds context with "system" role turns
    which Gemini 3.x cannot convert to valid content, producing a response start with no
    audio. Override sends a blank realtime text input as the trigger instead.

    TODO: with use_local_vad=True, also pass GeminiVADParams(disabled=True) to the service
    settings to fully disable server-side VAD. Verify exact Pipecat API before enabling.
    """
    from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame
    from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService as _GeminiBase

    class GeminiLiveLLMService(_GeminiBase):
        def __init__(self, *args, **kwargs):
            self._use_gate = kwargs.pop("use_audio_gate", True)
            super().__init__(*args, **kwargs)
            self._gate_audio = False

        async def process_frame(self, frame, direction):
            if self._use_gate:
                if isinstance(frame, BotStartedSpeakingFrame):
                    self._gate_audio = True
                elif isinstance(frame, BotStoppedSpeakingFrame):
                    self._gate_audio = False
            await super().process_frame(frame, direction)

        async def _send_user_audio(self, frame):
            if self._gate_audio:
                return
            await super()._send_user_audio(frame)

        async def _create_initial_response(self):
            if not self._session:
                self._run_llm_when_session_ready = True
                return
            try:
                await self._session.send_realtime_input(text=" ")
            except Exception as e:
                await self._handle_send_error(e)
            self._ready_for_realtime_input = True

    return GeminiLiveLLMService(
        api_key=os.getenv(config["api_key_env"]),
        model=config.get("model", "gemini-3.1-flash-live-preview"),
        use_audio_gate=not use_local_vad,
        settings=GeminiLiveLLMService.Settings(
            voice=config.get("voice", "Zephyr"),
            system_instruction=session_instructions,
        ),
    )


def _ultravox(config, session_instructions):
    """
    Ultravox Realtime API via Pipecat (pipecat-ai[ultravox]).

    Per-response instruction injection is not available via Pipecat's current service
    layer. Dynamic per-turn rules should be expressed as standing instructions in
    session_instructions.

    Pipecat bug workaround: UltravoxRealtimeLLMService.__init__ only sets _selected_tools
    when one_shot_selected_tools is passed, but _start_one_shot_call unconditionally
    evaluates `if self._selected_tools`, raising AttributeError before any API call.
    """
    from pipecat.services.ultravox.llm import OneShotInputParams, UltravoxRealtimeLLMService as _UltravoxBase

    class UltravoxRealtimeLLMService(_UltravoxBase):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if not hasattr(self, "_selected_tools"):
                self._selected_tools = None

    return UltravoxRealtimeLLMService(
        params=OneShotInputParams(
            api_key=os.getenv(config["api_key_env"]),
            system_prompt=session_instructions,
            voice=config.get("voice", "ee93bbf5-b47d-4f0d-bc03-f7235ddd8ab1"),
            model=config.get("model", "ultravox-v0.7"),
        )
    )
