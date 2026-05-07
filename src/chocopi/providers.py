"""Pipecat LLM service factories for each supported provider"""
import logging
import os

logger = logging.getLogger(__name__)


def create_llm_service(
    provider_name,
    provider_config,
    session_instructions,
    transcription_instructions="",
    initial_message="",
):
    """
    Instantiate the Pipecat LLM service for the given provider.
    Returns the configured service instance.
    """
    if provider_name == "openai":
        return _openai(provider_config, session_instructions, transcription_instructions)
    elif provider_name == "google":
        return _google(provider_config, session_instructions, initial_message)
    elif provider_name == "ultravox":
        return _ultravox(provider_config, session_instructions)
    else:
        raise ValueError(f"Unknown provider: {provider_name!r}")


def _openai(config, session_instructions, transcription_instructions):
    """
    OpenAI Realtime API via Pipecat.

    Uses SemanticTurnDetection (server-side intelligent turn completion) alongside
    optional SileroVADAnalyzer (local VAD) in the user aggregator. Both can run
    simultaneously — local VAD provides fine-grained activity signals while
    semantic turn detection determines response timing.

    Minimal subclass: _truncate_current_audio_response is a no-op to prevent
    invalid_value server errors on interruption. Pipecat's byte-count tracking
    can diverge from the server's committed audio duration, causing the server to
    reject truncation requests with "Audio content Xms is already shorter than Yms".
    Skipping the truncate event lets the session continue cleanly.
    """
    from pipecat.services.openai.realtime.events import (
        AudioConfiguration,
        AudioInput,
        AudioOutput,
        InputAudioNoiseReduction,
        InputAudioTranscription,
        SemanticTurnDetection,
        SessionProperties,
    )
    from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService as _Base

    class OpenAIRealtimeLLMService(_Base):
        async def _truncate_current_audio_response(self):
            self._current_audio_response = None

    td_params = {k: v for k, v in config.get("turn_detection", {}).items() if k != "type"}
    noise_red = config.get("noise_reduction")

    return OpenAIRealtimeLLMService(
        api_key=os.getenv(config["api_key_env"]),
        settings=OpenAIRealtimeLLMService.Settings(
            model=config["model"],
            system_instruction=session_instructions,
            session_properties=SessionProperties(
                audio=AudioConfiguration(
                    input=AudioInput(
                        transcription=InputAudioTranscription(
                            model=config.get("transcription_model", "gpt-4o-mini-transcribe"),
                            prompt=transcription_instructions,
                        ),
                        noise_reduction=InputAudioNoiseReduction(type=noise_red) if noise_red else None,
                        turn_detection=SemanticTurnDetection(**td_params),
                    ),
                    output=AudioOutput(
                        voice=config.get("voice", "alloy"),
                        speed=config.get("output_speed", 1.0),
                    ),
                ),
            ),
        ),
    )


def _google(config, session_instructions):
    """
    Google Gemini Live API via Pipecat (pipecat-ai[google]).

    All instructions baked into session_instructions at startup; no per-response
    injection available in Gemini Live.

    VAD: when vad=local, server-side VAD is disabled (GeminiVADParams(disabled=True))
    and Silero handles turn detection via LLMUserAggregatorParams. This eliminates
    the echo loop where Gemini's server VAD triggered on speaker output.
    PipeWire AEC (99-echo-cancel.conf) remains the system-level backstop.

    When vad=server, optional sensitivity tuning is available via vad_settings config:
      start_sensitivity: low | medium | high
      end_sensitivity: low | medium | high
      silence_duration_ms: int
      prefix_padding_ms: int
    """
    from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService, GeminiVADParams

    if config.get("vad") == "local":
        vad = GeminiVADParams(disabled=True)
    elif vad_cfg := config.get("vad_settings"):
        vad = GeminiVADParams(
            start_sensitivity=vad_cfg.get("start_sensitivity"),
            end_sensitivity=vad_cfg.get("end_sensitivity"),
            prefix_padding_ms=vad_cfg.get("prefix_padding_ms"),
            silence_duration_ms=vad_cfg.get("silence_duration_ms"),
        )
    else:
        vad = None

    return GeminiLiveLLMService(
        api_key=os.getenv(config["api_key_env"]),
        model=config.get("model", "gemini-3.1-flash-live-preview"),
        settings=GeminiLiveLLMService.Settings(
            voice=config.get("voice", "Zephyr"),
            system_instruction=session_instructions,
            vad=vad,
        ),
    )


def _ultravox(config, session_instructions):
    """
    Ultravox Realtime API via Pipecat (pipecat-ai[ultravox]).

    Pipecat bug workaround: UltravoxRealtimeLLMService.__init__ only sets _selected_tools
    when one_shot_selected_tools is passed, but _start_one_shot_call unconditionally
    evaluates `if self._selected_tools`, raising AttributeError before any API call.
    Minimal subclass retained until fixed upstream.
    """
    from pipecat.services.ultravox.llm import OneShotInputParams, UltravoxRealtimeLLMService as _Base

    class UltravoxRealtimeLLMService(_Base):
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
