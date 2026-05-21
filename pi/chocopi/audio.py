"""Audio management for playback and recording"""
import os
import numpy as np
import simpleaudio as sa
import sounddevice as sd
from loguru import logger
from chococore.config import SOUNDS_PATH

INT16_MIN = np.iinfo(np.int16).min
INT16_MAX = np.iinfo(np.int16).max


class AudioManager:
    """Audio manager that supports simultaneous playback and recording"""

    def __init__(self):
        self.input_stream = None
        self.play_obj = None

    def start_recording(self, sample_rate, dtype, blocksize, callback, input_gain=1.0):
        """Start recording"""
        # Stop existing stream if present
        if self.input_stream:
            self.input_stream.stop()
            self.input_stream.close()

        # Wrap callback to apply input gain if applicable
        def gain_callback(indata, frames, time, status):
            if input_gain != 1.0:
                # Apply gain
                processed = indata.astype(np.float32) * input_gain

                # Handle clipping
                if dtype == 'int16':
                    max_val = np.max(np.abs(processed))
                    if max_val > INT16_MAX:
                        logger.debug("🔇 Input clipping detected (max: {:.0f})", max_val)
                    processed = np.clip(processed, INT16_MIN, INT16_MAX).astype(np.int16)

                callback(processed, frames, time, status)
            else:
                callback(indata.copy(), frames, time, status)

        self.input_stream = sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype=dtype,
            blocksize=blocksize,
            callback=gain_callback
        )
        self.input_stream.start()

    def stop_recording(self):
        """Stop recording and clean up"""
        if self.input_stream:
            self.input_stream.stop()
            self.input_stream.close()
            self.input_stream = None

    def start_playing(self, data, sample_rate=24000):
        """Play audio file or data (non-blocking)"""
        try:
            self.stop_playing()
            if isinstance(data, str):
                # Play audio file directly
                path = data if data.startswith('/') else os.path.join(SOUNDS_PATH, data)
                wave_obj = sa.WaveObject.from_wave_file(path)
                self.play_obj = wave_obj.play()
            else:
                # Play numpy array (from bytes or direct array)
                audio_np = np.frombuffer(data, dtype=np.int16) if isinstance(data, bytes) else data
                self.play_obj = sa.play_buffer(
                    audio_np,
                    num_channels=1,
                    bytes_per_sample=2,
                    sample_rate=int(sample_rate)
                )
        except Exception as e:
            logger.error("❌ Audio playback error: {}", e)

    def stop_playing(self):
        """Stops playback if active"""
        try:
            if self.play_obj and self.play_obj.is_playing():
                self.play_obj.stop()
            self.play_obj = None
        except Exception as e:
            logger.warning("⚠️  Error stopping playback: {}", e)


# Global audio manager instance
AUDIO = AudioManager()
