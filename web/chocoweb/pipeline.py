"""Build and run the Pipecat pipeline for a single chocoweb WebRTC session."""
from loguru import logger

from pipecat.processors.frameworks.rtvi.processor import RTVIProcessor
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from chococore.config import CONFIG
from chococore.conversation import ConversationSession


async def run_pipeline(transport: SmallWebRTCTransport, profile_name: str, language: str | None):
    profile_config = CONFIG.profiles.get(profile_name)
    if profile_config is None:
        default = CONFIG.profile or "default"
        logger.warning("Unknown profile '{}', falling back to '{}'", profile_name, default)
        profile_config = CONFIG.profiles.get(default)

    if profile_config is None:
        logger.error("No usable profile found, aborting session")
        return

    if not language:
        langs = list((profile_config.learning_languages or {}).keys())
        language = langs[0] if langs else None

    if not language:
        logger.error("No learning language for profile '{}', aborting", profile_name)
        return

    logger.info("Starting session — profile: {}, language: {}", profile_name, language)

    rtvi = RTVIProcessor(transport=transport)
    rtvi_observer = rtvi.create_rtvi_observer()

    async def on_session_ending(reason: str):
        logger.info("Session ending — reason: {}", reason)
        await rtvi.send_server_message({"t": "session-ending", "d": {"reason": reason}})

    session = ConversationSession(
        learning_language=language,
        profile=profile_config,
        on_session_ending=on_session_ending,
        sent_sound=False,
    )

    try:
        await session.run(
            transport,
            extra_processors=[rtvi],
            extra_observers=[rtvi_observer],
        )
    except Exception:
        logger.exception("Session error (profile={}, language={})", profile_name, language)
    finally:
        await session.persist_memory()
        logger.info("Session complete — profile: {}, language: {}", profile_name, language)
