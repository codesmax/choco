"""Configuration loading and constants"""
import os
import sys
import platform
import yaml
from pathlib import Path
from box import Box
from dotenv import load_dotenv
from loguru import logger


def _has_display():
    """Check if a display is available"""
    system = platform.system()

    if system == 'Linux':
        return bool(
            os.environ.get('DISPLAY') or
            os.environ.get('WAYLAND_DISPLAY') or
            os.path.exists('/dev/fb0')
        )
    elif system in ('Darwin', 'Windows'):
        return True

    return False


# Project root (../..)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_PATH = PROJECT_ROOT / 'models'
ASSETS_PATH = PROJECT_ROOT / 'assets'
SOUNDS_PATH = ASSETS_PATH / 'sounds'
IMAGES_PATH = ASSETS_PATH / 'images'
FONTS_PATH = ASSETS_PATH / 'fonts'

# Load configuration
try:
    with open(PROJECT_ROOT / 'config.yml', 'r', encoding='utf-8') as file:
        CONFIG = Box(yaml.safe_load(file), default_box=True, default_box_attr=None)
except FileNotFoundError:
    raise SystemExit("config.yml not found. Make sure you're running from the project root.")
except yaml.YAMLError as e:
    raise SystemExit(f"config.yml is invalid: {e}")

# Load environment variables
load_dotenv(PROJECT_ROOT / '.env')

# Environment
IS_PI = platform.machine().lower() in ['aarch64', 'armv7l']
LOG_LEVEL = os.getenv('CHOCO_LOG_LEVEL', 'INFO').upper()
PIPECAT_LOG_LEVEL = os.getenv('PIPECAT_LOG_LEVEL', 'WARNING').upper()
USE_DISPLAY = os.getenv('CHOCO_DISPLAY', '0') == '1' and _has_display()
PROFILE = os.getenv('CHOCO_PROFILE', CONFIG.profile or 'default')
PROVIDER = os.getenv('CHOCO_PROVIDER', CONFIG.provider or 'openai')

# Journald adds its own timestamps — omit them from our format when running under systemd
_in_journald = bool(os.environ.get('JOURNAL_STREAM') or os.environ.get('INVOCATION_ID'))
_fmt = (
    "<level>[{level: <7}]</level> <cyan>{name}</cyan> | {message}"
    if _in_journald else
    "<green>{time:HH:mm:ss}</green> <level>[{level: <7}]</level> <cyan>{name}</cyan> | {message}"
)

_choco_level_no = logger.level(LOG_LEVEL).no
_pipecat_level_no = logger.level(PIPECAT_LOG_LEVEL).no
_warning_no = logger.level("WARNING").no


def _log_filter(record):
    name = record["name"]
    if name.startswith("chocopi"):
        return record["level"].no >= _choco_level_no
    if name.startswith("pipecat"):
        return record["level"].no >= _pipecat_level_no
    return record["level"].no >= _warning_no


logger.remove()
logger.add(
    sys.stderr,
    level=min(_choco_level_no, _pipecat_level_no),
    filter=_log_filter,
    format=_fmt,
    colorize=True,
)
