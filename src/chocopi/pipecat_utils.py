"""Pipecat FrameProcessors and pipeline observer utilities"""
import wave

from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InterimTranscriptionFrame,
    LLMContextFrame,
    OutputAudioRawFrame,
    TranscriptionFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.processors.frame_processor import FrameProcessor

from chocopi.config import SOUNDS_PATH


def load_sound_frame(filename: str) -> OutputAudioRawFrame | None:
    """Load a WAV file as an OutputAudioRawFrame. File must be 24kHz mono PCM."""
    path = SOUNDS_PATH / filename
    try:
        with wave.open(str(path)) as wf:
            return OutputAudioRawFrame(
                audio=wf.readframes(-1),
                sample_rate=wf.getframerate(),
                num_channels=wf.getnchannels(),
            )
    except Exception as exc:
        logger.warning("Could not preload sound {}: {}", filename, exc)
        return None


class SentSoundProcessor(FrameProcessor):
    """Injects the sent-sound frame before LLMContextFrame reaches the LLM.

    Intercepts LLMContextFrame (emitted by user_aggregator when a user turn
    ends) and pushes the sound first, guaranteeing it plays before the first
    LLM audio frame. skip_fn returns True during the greeting turn (where
    LLMRunFrame also triggers LLMContextFrame and no sound should play).
    """

    def __init__(self, skip_fn, frame: OutputAudioRawFrame | None):
        super().__init__()
        self._skip_fn = skip_fn
        self._frame = frame

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame) and not self._skip_fn() and self._frame:
            await self.push_frame(self._frame)
        await self.push_frame(frame, direction)


class DisplaySyncProcessor(FrameProcessor):
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


class TranscriptObserver(BaseObserver):
    """Logs TranscriptionFrame / InterimTranscriptionFrame from any pipeline source.

    TranscriptionLogObserver (pipecat built-in) filters to STTService only.
    OpenAI Realtime and Gemini Live push these frames as LLM services, so that
    observer produces no output. This one skips the source-type check entirely.
    """

    async def on_push_frame(self, data: FramePushed):
        if isinstance(data.frame, InterimTranscriptionFrame):
            logger.debug("💬 interim: {}", data.frame.text)
        elif isinstance(data.frame, TranscriptionFrame):
            logger.debug("💬 transcript: {}", data.frame.text)
