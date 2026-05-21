"""Pipecat LLM service factories for each supported provider"""
import os


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
    # _truncate_current_audio_response no-op: pipecat's byte-count tracking can diverge
    # from the server's committed audio duration, causing invalid_value errors on interruption.
    from pipecat.services.openai.realtime.events import (
        AudioConfiguration,
        AudioInput,
        AudioOutput,
        InputAudioNoiseReduction,
        InputAudioTranscription,
        SemanticTurnDetection,
        SessionProperties,
        TurnDetection,
    )
    from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService as _Base

    class OpenAIRealtimeLLMService(_Base):
        async def _truncate_current_audio_response(self):
            self._current_audio_response = None

    vad_type = config.vad.server.type
    vad_config = config.vad.server[vad_type] or {}
    turn_detection = TurnDetection(**vad_config) if vad_type == "server_vad" else SemanticTurnDetection(**vad_config)
    noise_reduction_type = config.noise_reduction

    return OpenAIRealtimeLLMService(
        api_key=os.getenv(config.api_key_env),
        settings=OpenAIRealtimeLLMService.Settings(
            model=config.model,
            system_instruction=session_instructions,
            session_properties=SessionProperties(
                audio=AudioConfiguration(
                    input=AudioInput(
                        transcription=InputAudioTranscription(
                            model=config.transcription_model or "gpt-4o-mini-transcribe",
                            prompt=transcription_instructions,
                        ),
                        noise_reduction=InputAudioNoiseReduction(type=noise_reduction_type) if noise_reduction_type else None,
                        turn_detection=turn_detection,
                    ),
                    output=AudioOutput(
                        voice=config.voice or "alloy",
                        speed=config.output_speed or 1.0,
                    ),
                ),
            ),
        ),
    )


def _google(config, session_instructions):
    from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService, GeminiVADParams

    if vad_config := config.vad and config.vad.server:
        vad = GeminiVADParams(
            start_sensitivity=vad_config.start_sensitivity,
            end_sensitivity=vad_config.end_sensitivity,
            prefix_padding_ms=vad_config.prefix_padding_ms,
            silence_duration_ms=vad_config.silence_duration_ms,
        )
    else:
        vad = GeminiVADParams(disabled=True)

    return GeminiLiveLLMService(
        api_key=os.getenv(config.api_key_env),
        settings=GeminiLiveLLMService.Settings(
            model=config.model or "gemini-3.1-flash-live-preview",
            voice=config.voice or "Zephyr",
            system_instruction=session_instructions,
            vad=vad,
        ),
    )


def _ultravox(config, session_instructions):
    # _selected_tools guard: pipecat bug — attribute only set when one_shot_selected_tools passed,
    # but _start_one_shot_call evaluates it unconditionally.
    from pipecat.services.ultravox.llm import OneShotInputParams, UltravoxRealtimeLLMService as _Base

    class UltravoxRealtimeLLMService(_Base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if not hasattr(self, "_selected_tools"):
                self._selected_tools = None

    return UltravoxRealtimeLLMService(
        params=OneShotInputParams(
            api_key=os.getenv(config.api_key_env),
            system_prompt=session_instructions,
            voice=config.voice or "ee93bbf5-b47d-4f0d-bc03-f7235ddd8ab1",
            model=config.model or "ultravox-v0.7",
        )
    )
