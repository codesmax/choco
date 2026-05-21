# Agent Instructions

This is a voice assistant project called **ChocoPi** — a Raspberry Pi-focused language tutor for kids.
It detects wake words on-device with OpenWakeWord, then runs live voice conversations via a configurable LLM provider (OpenAI Realtime by default; Gemini Live and Ultravox also supported).
Sessions are language-targeted (English, Korean, Spanish, Chinese) and can end via a language-specific sleep word.
Session history is summarized and persisted to memory files for continuity across conversations.

## Running the App

```bash
# Preferred — bash wrapper that sets env vars, activates venv, runs python -m chocopi
./chocopi

# Or directly
python -m chocopi

# With debug logging
CHOCO_LOG_LEVEL=DEBUG python -m chocopi
```

There is no standalone script at the repo root — `./chocopi` is a bash wrapper and the Python package lives under `src/chocopi/`.

## Developer Setup

```bash
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e .
cp .env.example .env   # then add your API key
```

Python 3.11 is required because `tflite-runtime` (subdependency of `openwakeword`) has no wheels for 3.12+.

## Runtime Flow

1. `./chocopi` sets environment defaults, activates `.venv`, and runs `python -m chocopi`.
2. `src/chocopi/chocopi.py` initializes config, wake-word detector, and optional display.
3. App loop waits in `WakeWordDetector.listen()`.
4. On wake word, it maps the detected model to a learning language and starts `ConversationSession`.
5. `ConversationSession.__init__` builds session instructions (profile + memory), creates the LLM service, and seeds an `LLMContext` with a greeting instruction as the first user turn.
6. `ConversationSession.run()` assembles the Pipecat pipeline, registers event handlers on the aggregators, then queues `LLMRunFrame` to trigger the greeting.
7. `on_user_turn_stopped` fires after each user turn: logs transcript, runs echo/sleep-word detection.
8. `on_assistant_turn_stopped` fires after each assistant turn: logs transcript, marks end of greeting phase, queues `EndFrame` on termination.
9. On session end, `chocopi.py` plays the bye sound, calls `session.persist_memory()` to summarize and write memory to disk.

## Key Files

| File | Purpose |
|---|---|
| `chocopi` | Bash wrapper — sets env, activates venv, runs `python -m chocopi` |
| `src/chocopi/__main__.py` | Module entry point — imports and calls `main()` |
| `src/chocopi/chocopi.py` | Top-level orchestrator and graceful shutdown |
| `src/chocopi/wakeword.py` | OpenWakeWord model loading and inference loop |
| `src/chocopi/conversation.py` | Pipecat pipeline setup and `ConversationSession` with event-handler-based turn logic |
| `src/chocopi/pipecat_utils.py` | Pipecat `FrameProcessor` subclasses (`SentSoundProcessor`, `DisplaySync`), `TranscriptObserver`, and `load_sound_frame` |
| `src/chocopi/providers.py` | Pipecat LLM service factories (OpenAI Realtime, Gemini Live, Ultravox) |
| `src/chocopi/audio.py` | Shared input/output audio manager (wakeword + conversation) |
| `src/chocopi/display.py` | Pygame-ce UI (sprites + transcript pane), enabled by `CHOCO_DISPLAY=1` |
| `src/chocopi/memory.py` | Session summary (via gpt-4.1-nano), memory merge, YAML persistence |
| `src/chocopi/language.py` | Stub (no-op) — language detection removed |
| `src/chocopi/config.py` | Global config/env loading, platform detection, path constants |
| `config.yml` | Primary runtime configuration (profiles, languages, prompts, model settings) |

## Configuration

- **Secrets:** Provider API keys in `.env`, loaded by `python-dotenv`.
- **Runtime config:** `config.yml` — read at import time by `config.py`.
- **Active profile:** `profile` key in `config.yml`.
- **Active provider:** `provider` key in `config.yml` (`openai` | `google` | `ultravox`).
- **Wake-word models:** each `languages.<code>.model` must match files in `models/` (`.tflite` on ARM, `.onnx` elsewhere).
- **Session memory:** stored under `data/memory_<profile>.yml`.

## Architecture

### Pipeline

```
LocalAudioTransport.input()
  → user_aggregator       (LLMContextAggregatorPair)
  → LLM service           (provider-specific)
  → _DisplaySync          (FrameProcessor, only when display is enabled)
  → LocalAudioTransport.output()
  → assistant_aggregator  (LLMContextAggregatorPair)
```

- `ConversationSession` owns the pipeline; runs it via `PipelineRunner(handle_sigint=False)`.
- No custom frame processor for turn logic — everything lives in event handlers registered on the aggregators.
- `enable_auto_context_summarization=True` on `LLMAssistantAggregatorParams` (server-side, 8k tokens / 20 messages default).

### Event Handlers

- `user_aggregator.on_user_turn_stopped` — transcript arrives → queues sent-sound `OutputAudioRawFrame` → echo/sleep-word detection
- `assistant_aggregator.on_assistant_turn_stopped` — log transcript, mark greeting end, queue `EndFrame` after termination
- `_DisplaySync.process_frame` — catches upstream `BotStartedSpeakingFrame` / `BotStoppedSpeakingFrame` → `display.set_speaking(True/False)`

### Greeting Flow

- `LLMContext([{"role": "user", "content": greeting_message}])` seeds the context for all providers.
- `task.queue_frames([LLMRunFrame()])` triggers the initial response.
- `on_assistant_turn_stopped` with `is_greeting=True` → sets `is_greeting=False`, starts session timer.

### Termination Flow

- Sleep word or echo loop → `is_terminating = True` in `on_user_turn_stopped`.
- Conversation proceeds naturally (session instructions tell the assistant to say goodbye on sleep word).
- `on_assistant_turn_stopped` with `is_terminating=True` → queues `EndFrame`.

### Providers (`providers.py`)

`create_llm_service(provider_name, provider_config, session_instructions, transcription_instructions="")` returns a configured service instance.

All session instructions are baked in at startup — no per-response injection. Translation is a static flag per profile (`profiles.<name>.learning_languages.<lang>.translations: true/false`), injected into session instructions once.

**`openai`**: Minimal subclass — `_truncate_current_audio_response` is a no-op to prevent `invalid_value` server errors when Pipecat's byte-count tracking diverges from the server's committed audio duration on interruption. Uses `SemanticTurnDetection` for server-side turn completion; optional local `SileroVADAnalyzer` runs simultaneously when `vad: local` is set.

**`google`**: No subclass needed. `GeminiVADParams(disabled=True)` set when `vad: local` to eliminate the echo loop where Gemini's server VAD triggers on speaker output; Silero handles turn detection instead. Optional `vad_settings` keys (`start_sensitivity`, `end_sensitivity`, `silence_duration_ms`, `prefix_padding_ms`) tune server VAD when `vad: server`.

**`ultravox`**: Minimal subclass — `_selected_tools` `hasattr` guard prevents `AttributeError` in `_start_one_shot_call` (upstream Pipecat bug: `_selected_tools` only set when `one_shot_selected_tools` is passed, but unconditionally evaluated).

### Signal Handling

`loop.add_signal_handler()` inside `ChocoPi.run()` cancels the main task on SIGINT/SIGTERM, allowing asyncio and Pipecat to unwind cleanly (single Ctrl-C exits).

### Audio

- Recording: `sounddevice` → PortAudio → ALSA → PipeWire (Linux) or CoreAudio (macOS)
- Playback: `simpleaudio` (runs simultaneously with recording)
- `pipewire-alsa` provides ALSA compatibility layer on Linux
- WirePlumber manages device routing and Bluetooth profiles
- PipeWire echo cancel module (`99-echo-cancel.conf`) provides WebRTC AEC as system-level backstop on Linux
- Echo/feedback loop detection: `_is_echo()` flags user turns ≤ 4 words with high overlap to the last assistant response; session ends after 5 consecutive echo turns

### Display

Optional pygame-ce UI with sprite animations and transcript panel (`CHOCO_DISPLAY=1`). `_DisplaySync` sits between the LLM service and the output transport to intercept upstream speaking frames and drive display state.

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
| `install/pipewire/99-echo-cancel.conf` | PipeWire WebRTC AEC module config |

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

- `pipecat-ai[openai,google,ultravox,local]` — voice pipeline + all providers
- `openwakeword` — wake word detection
- `sounddevice` / `soundfile` — audio recording and file I/O
- `simpleaudio` — audio playback
- `pygame-ce` — optional visual display
- `rapidfuzz` — fuzzy sleep-word matching
- `numpy>=1.26.4,<2.0` — required for tflite-runtime compatibility
- `python-dotenv` — `.env` file loading
- `pyyaml` — config file parsing

## Behavior Notes

- Audio manager is global (`AUDIO`) and shared across wakeword and conversation phases.
- If summarization fails, memory still updates via fallback using last transcript snippets.
- Display is optional; app runs headless without it.
- `CHOCO_PROFILE` and `CHOCO_PROVIDER` env vars override `config.yml` at runtime.

## Change Guidelines

- Provider-specific logic belongs in `providers.py`, not in `conversation.py`.
- Keep audio side effects explicit; avoid introducing competing streams.
- Maintain compatibility between `config.yml` structure and code lookups before renaming keys.
- Do not commit `.env` or profile memory files from `data/`.
- If adding tests, prefer unit tests around wake-word mapping, sleep-word detection, and message handlers.
