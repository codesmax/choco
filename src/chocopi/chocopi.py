"""Main orchestrator for ChocoPi voice assistant"""
import asyncio
import signal

from loguru import logger

from chocopi.audio import AUDIO
from chocopi.config import CONFIG, PROFILE
from chocopi.conversation import ConversationSession
from chocopi.display import create_display_manager
from chocopi.wakeword import WakeWordDetector

_SHUTDOWN_SIGNALS = (signal.SIGINT, signal.SIGTERM)


class ChocoPi:
    def __init__(self):
        self.profile = CONFIG.profiles[PROFILE]
        self.wake_word_detector = WakeWordDetector()
        profile_langs = set(self.profile["learning_languages"].keys())
        profile_langs.add(self.profile["native_language"])
        self.wake_words = [
            CONFIG.languages[lang].wake_word.lower()
            for lang in profile_langs
            if lang in CONFIG.languages
        ]
        self.display = create_display_manager(CONFIG)

    def _wake_word_language(self, wake_word):
        """Get language configuration based on detected wake word"""
        for lang, lang_config in CONFIG.languages.items():
            # Native language has no learning session; its wake word falls through to the default below
            if wake_word == lang_config.model and lang != self.profile["native_language"]:
                logger.info("⚙️  Session configured for: {}", lang_config.language_name)
                return lang

        default_lang = next(iter(self.profile["learning_languages"].keys()))
        logger.error("⚠️  Unknown wake word: '{}'. Using default language: {}", wake_word, default_lang)

        return default_lang

    async def run(self):
        """Run the main application loop"""
        loop = asyncio.get_running_loop()
        main_task = asyncio.current_task()
        shutting_down = False

        def _request_shutdown(signum):
            nonlocal shutting_down
            logger.info("\n🛑 Received signal {}, shutting down gracefully...", signum)
            shutting_down = True
            main_task.cancel()

        for sig in _SHUTDOWN_SIGNALS:
            try:
                loop.add_signal_handler(sig, lambda s=sig: _request_shutdown(s))
            except NotImplementedError:
                # Windows: fall back to signal.signal (best-effort)
                signal.signal(sig, lambda s, f, signum=sig: _request_shutdown(signum))

        logger.info("✨ Choco is ready! Say one of '{}' to start or end a conversation.", ', '.join(self.wake_words))

        # Start display task if enabled
        display_task = None
        if self.display:
            display_task = asyncio.create_task(self.display.run())

        try:
            while True:
                # Listen for wake word
                wake_word = await self.wake_word_detector.listen()
                lang = self._wake_word_language(wake_word)

                # Wake up display
                if self.display:
                    self.display.set_active(True)

                AUDIO.start_playing(CONFIG.sounds.awake)

                # Run conversation session
                session = ConversationSession(lang, self.profile, display=self.display)
                await session.run()

                # If a shutdown was requested while the session was running, pipecat
                # may have caught and suppressed the CancelledError internally. Check
                # the flag explicitly so we don't loop back into wake word detection.
                if shutting_down:
                    logger.info("\n👋 Shutting down...")
                    break

                AUDIO.start_playing(CONFIG.sounds.bye)
                logger.info("✅ Session ended.\n")

                # Put display to sleep
                if self.display:
                    self.display.set_active(False)

                await session.persist_memory()

        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            logger.info("\n👋 Shutting down...")
        except Exception as e:
            logger.error("\n❌ Unexpected error: {}", e)
        finally:
            logger.info("🧹 Cleaning up...")

            # Stop all audio streams
            AUDIO.stop_recording()
            AUDIO.stop_playing()

            # Cancel display task
            if display_task:
                self.display.is_running = False
                display_task.cancel()
                try:
                    await display_task
                except asyncio.CancelledError:
                    pass


def main():
    app = ChocoPi()
    asyncio.run(app.run())

if __name__ == '__main__':
    main()
