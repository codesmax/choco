"""Pipecat LLM service factories for each supported provider"""
import logging
import os

logger = logging.getLogger(__name__)


def create_llm_service(
    provider_name,
    provider_config,
    session_instructions,
    transcription_instructions="",
):
    """
    Instantiate the Pipecat LLM service for the given provider.
    Returns the configured service instance.
    """
    if provider_name == "openai":
        return _openai(provider_config, session_instructions, transcription_instructions)
    elif provider_name == "google":
        return _google(provider_config, session_instructions)
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

    No subclassing needed: create_response defaults to true with SemanticTurnDetection,
    so the server auto-creates responses on turn end. The session handles all turn
    control through the aggregator event system.
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
    from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService

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

    Audio gating removed: hardware echo is handled at the PipeWire level (AEC in
    99-echo-cancel.conf). With local VAD (vad: local in provider config), Silero
    provides activity signals; Gemini's server-side VAD runs in parallel.
    """
    from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService

    return GeminiLiveLLMService(
        api_key=os.getenv(config["api_key_env"]),
        model=config.get("model", "gemini-3.1-flash-live-preview"),
        settings=GeminiLiveLLMService.Settings(
            voice=config.get("voice", "Zephyr"),
            system_instruction=session_instructions,
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
