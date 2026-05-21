"""Wake word detection using OpenWakeWord"""
import asyncio
import queue
import openwakeword
from openwakeword.model import Model
from loguru import logger
from chococore.config import CONFIG, IS_PI, MODELS_PATH
from chocopi.audio import AUDIO


class WakeWordDetector:
    """On-device wake word detection using OpenWakeWord"""

    def __init__(self):
        self.config = CONFIG.openwakeword
        self.audio_queue = queue.Queue()
        self.framework = 'tflite' if IS_PI else 'onnx'
        self.model_paths = [
            str(MODELS_PATH / f"{lang.model}.{self.framework}")
            for lang in CONFIG.languages.values()
        ]

        # Download required models once if needed
        openwakeword.utils.download_models()

        self.model = Model(
            inference_framework=self.framework,
            wakeword_models=self.model_paths,
            vad_threshold=self.config.vad_threshold,
        )

    async def listen(self):
        """Listen for wake word and return detected wake word"""

        # Reset prediction/audio buffers and start with fresh audio queue
        self.model.reset()
        self.audio_queue = queue.Queue()
        logger.info("🎙️  Listening for wake word using {} model...", self.framework.upper())

        try:
            blocksize = int(self.config.sample_rate * self.config.chunk_duration_ms / 1000)

            def audio_callback(indata, _frames, _time, status):
                if status:
                    logger.warning("⚠️  Audio device status: {}", status)
                try:
                    self.audio_queue.put_nowait(indata)
                except queue.Full:
                    # Drop frame if queue falls behind
                    logger.warning("⚠️  Audio queue full, dropping frame")

            AUDIO.start_recording(
                sample_rate=self.config.sample_rate,
                dtype='int16',
                blocksize=blocksize,
                callback=audio_callback,
                input_gain=self.config.input_gain
            )

            while True:
                # Poll queue with timeout to yield control
                try:
                    chunk = self.audio_queue.get(timeout=0.01)
                    chunk_flat = chunk[:, 0].flatten()
                    prediction = self.model.predict(chunk_flat)
                    wake_word, score = max(prediction.items(), key=lambda x: x[1])
                    if score > self.config.threshold:
                        logger.info("⏰ Wake word activated: {} (score: {:.2f})", wake_word, score)
                        logger.debug("Prediction items: {}", prediction.items())
                        AUDIO.stop_recording()
                        return wake_word
                    elif score > 0.01:
                        logger.debug("🔍 Wake word score: {} {:.2f}", wake_word, score)
                except queue.Empty:
                    await asyncio.sleep(0.01)  # Yield to event loop
        except Exception as e:
            logger.error("❌ Audio input error: {}", e)
            raise
        finally:
            AUDIO.stop_recording()
