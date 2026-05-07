# Agent Instructions

This is a voice assistant project called **ChocoPi** — a Raspberry Pi-focused language tutor for kids.
It detects wake words on-device with OpenWakeWord, then runs live voice conversations via the OpenAI Realtime API.
Sessions are language-targeted (English, Korean, Spanish, Chinese) and can end via a language-specific sleep word.
Session history is summarized and persisted to memory files for continuity across conversations.

## Running the App

```bash
# Preferred — bash wrapper that sets env vars, activates venv, runs python -m chocopi
./chocopi

# Or directly
python -m chocopi

# With debug logging
CHOCO_LOG=DEBUG python -m chocopi
```

There is no standalone script at the repo root — `./chocopi` is a bash wrapper and the Python package lives under `src/chocopi/`.

## Developer Setup

```bash
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e .
cp .env.example .env   # then add your OPENAI_API_KEY
```

Python 3.11 is required because `tflite-runtime` (subdependency of `openwakeword`) has no wheels for 3.12+.

## Runtime Flow

1. `./chocopi` sets environment defaults, activates `.venv`, and runs `python -m chocopi`.
2. `src/chocopi/chocopi.py` initializes config, wake-word detector, optional display, and language detector warmup.
3. App loop waits in `WakeWordDetector.listen()`.
4. On wake word, it maps the detected model to a learning language and starts `ConversationSession`.
5. `ConversationSession` opens Realtime websocket, sends `session.update`, requests greeting, then streams mic audio.
6. Server VAD events drive turn taking; transcript completion triggers a response request with dynamic instructions.
7. Response audio is buffered and played locally; display state and transcript panel update in parallel.
8. On sleep word, timeout, or error, session stops, transcripts are summarized, and memory is written to disk.

## Key Files

| File | Purpose |
|---|---|
| `chocopi` | Bash wrapper — sets env, activates venv, runs `python -m chocopi` |
| `src/chocopi/__main__.py` | Module entry point — imports and calls `main()` |
| `src/chocopi/chocopi.py` | Top-level orchestrator and graceful shutdown |
| `src/chocopi/wakeword.py` | OpenWakeWord model loading and inference loop |
| `src/chocopi/conversation.py` | Pipecat pipeline setup, `ChocoPiProcessor`, `ConversationSession` |
| `src/chocopi/providers.py` | Pipecat LLM service factories (OpenAI Realtime, Gemini Live, Ultravox) |
| `src/chocopi/audio.py` | Shared input/output audio manager (wakeword + conversation) |
| `src/chocopi/display.py` | Pygame-ce UI (sprites + transcript pane), enabled by `CHOCO_DISPLAY=1` |
| `src/chocopi/memory.py` | Session summary (via gpt-4.1-nano), memory merge, YAML persistence |
| `src/chocopi/language.py` | Lingua-based language detector for deciding whether translation is needed |
| `src/chocopi/config.py` | Global config/env loading, platform detection, path constants |
| `config.yml` | Primary runtime configuration (profiles, languages, prompts, model settings) |

## Configuration

- **Secrets:** `OPENAI_API_KEY` in `.env`, loaded by `python-dotenv`.
- **Runtime config:** `config.yml` — read at import time by `config.py`.
- **Active profile:** `profile` key in `config.yml`.
- **Wake-word models:** each `languages.<code>.model` must match files in `models/` (`.tflite` on ARM, `.onnx` elsewhere).
- **Realtime model and request schemas:** `openai` section in `config.yml`.
- **Session memory:** stored under `data/memory_<profile>.yml`.

## Architecture

- **Wake Word Detection**: OpenWakeWord with platform-specific model loading (TFLite on ARM, ONNX elsewhere)
- **Conversation**: Pipecat pipeline — `LocalAudioTransport.input() → LLM service → ChocoPiProcessor → LocalAudioTransport.output()`. Provider is selected by `provider` in `config.yml`.
- **Providers** (`providers.py`): factory returns `(service, set_response_instructions_fn)` for each backend:
  - `openai` — per-response instructions injected via `response.create.instructions`
  - `google` — system instruction set once at session start; dynamic per-turn rules go in `session_instructions`
  - `ultravox` — same limitation as Gemini; no per-response override channel via Pipecat's current service layer
- **Signal handling**: `loop.add_signal_handler()` inside `ChocoPi.run()` cancels the main task on SIGINT/SIGTERM, allowing asyncio and Pipecat to unwind cleanly (single Ctrl-C exits)
- **Audio**:
  - Recording: `sounddevice` → PortAudio → ALSA → PipeWire (Linux) or CoreAudio (macOS)
  - Playback: `simpleaudio` (can run simultaneously with recording)
  - `pipewire-alsa` provides ALSA compatibility layer on Linux
  - WirePlumber manages device routing and Bluetooth profiles
- **Bluetooth**: HSP/HFP profile for bidirectional audio (mic + speaker)
- **Interruption**: Server-side VAD detects user speech to interrupt AI responses
- **Sleep word**: Fuzzy matching via `rapidfuzz.partial_ratio` with configurable threshold
- **Language detection**: `lingua-language-detector` identifies user language for translation/correction
- **Display**: Optional pygame-ce UI with sprite animations and transcript panel (`CHOCO_DISPLAY=1`)

## Cross-Platform Notes

**Audio Devices:**
- Linux/RPi: Uses `device='default'` to respect PipeWire routing via ALSA layer
- macOS: Uses sounddevice defaults (CoreAudio handles concurrency)
- Bluetooth devices require HSP/HFP profile (not A2DP) for microphone access

**Model Selection:**
- ARM (RPi): Uses TFLite models for optimal performance
- Other platforms: Uses ONNX models for better compatibility

**User Isolation (Pi deployment):**
- Service runs as `chocopi` user (limited privileges)
- PipeWire/WirePlumber services run per-user (requires `loginctl enable-linger`)
- Bluetooth pairing is system-wide but profile selection is per-user

## Installation Files

| File | Purpose |
|---|---|
| `install.sh` | Cross-platform installer — detects macOS/Linux and runs the appropriate setup |
| `install/systemd/chocopi.service` | Systemd service definition (Pi) |
| `install/wireplumber/51-bluetooth-audio.lua` | WirePlumber Bluetooth HSP/HFP profile config |
| `install/wireplumber/51-bluetooth-audio.conf` | WirePlumber logind integration config |

## Audio Debugging

```bash
python -m sounddevice           # List audio devices
pactl info                      # Check PipeWire server info
pactl list sinks short          # List output devices
pactl list sources short        # List input devices
wpctl status                    # PipeWire/WirePlumber status
aplay -L / arecord -L           # List ALSA devices
bluetoothctl                    # Manage Bluetooth connections
sudo journalctl -u chocopi -f   # Service logs on Pi
```

## Dependencies

Managed via `pyproject.toml` (no `requirements.txt`). Key packages:

- `openwakeword` — wake word detection
- `sounddevice` / `soundfile` — audio recording and file I/O
- `simpleaudio` — audio playback
- `websockets>=13.0` — OpenAI Realtime API connection
- `pygame-ce` — optional visual display
- `rapidfuzz` — fuzzy sleep-word matching
- `lingua-language-detector` — user language identification
- `numpy>=1.26.4,<2.0` — required for tflite-runtime compatibility
- `python-dotenv` — `.env` file loading
- `pyyaml` — config file parsing

## Behavior Notes

- Audio manager is global (`AUDIO`) and shared across wakeword and conversation phases.
- Greeting has a shorter timeout than normal conversation (`session.greeting_timeout` vs `session.conversation_timeout`).
- Sleep-word detection uses fuzzy matching (`rapidfuzz.partial_ratio`) with configurable threshold.
- If summarization fails, memory still updates via fallback using last transcript snippets.
- Display is optional; app runs headless without it.

## Change Guidelines

- Preserve the event contract in `conversation.py` when updating Realtime handling.
- Provider-specific logic belongs in `providers.py`, not in `conversation.py`.
- Keep audio side effects explicit; avoid introducing competing streams.
- Maintain compatibility between `config.yml` structure and code lookups before renaming keys.
- Do not commit `.env` or profile memory files from `data/`.
- If adding tests, prefer unit tests around wake-word mapping, sleep-word detection, and message handlers.
