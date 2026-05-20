![Image of a friendly robot with a chocolatey treat for a head](https://github.com/user-attachments/assets/d197fcb5-cfa9-4faf-a3ce-9e9b94eb9ee0)

# ChocoPi

A voice-powered language tutor for kids, built for Raspberry Pi.

ChocoPi listens for a wake word, then holds a live conversation to help children practice English, Korean, Spanish, or Chinese. Each language has its own wake word, sleep word, and teaching style — all configurable.

https://github.com/user-attachments/assets/7e72a294-3c8f-48a5-b8f6-ec7416c1d9a8

## How It Works

1. Wake word detection runs on-device using [OpenWakeWord](https://github.com/dscripka/openWakeWord)
2. Once triggered, a live voice conversation starts via a configurable provider (OpenAI Realtime, Gemini Live, or Ultravox)
3. The assistant adapts to the child's age, native language, and comprehension level
4. Sessions end with a language-specific sleep word or timeout
5. Conversation history is summarized and persisted for continuity across sessions

## Features

- **4 languages** — English, Korean, Spanish, and Chinese
- **On-device wake words** — "Hey Choco", "Anyeong Choco", "Hola Choco", "Nihao Choco"
- **Multiple voice providers** — OpenAI Realtime (default), Google Gemini Live, or Ultravox; swap via `config.yml`
- **User profiles** — per-child age, native language, and learning levels
- **Session memory** — remembers jokes, vocab, topics, and progress across conversations
- **Display support** — animated character and live transcript panel (pygame-ce); also works headless!

## Quick Start

### Requirements

- Microphone and speaker (Bluetooth or wired)
- API key for your chosen voice provider (OpenAI by default — see [pricing](https://openai.com/api/pricing/))
- Python 3.11 (required — `tflite-runtime` has no wheels for 3.12+)

### Raspberry Pi Setup

Tested on Raspberry Pi 4+ with 64-bit Raspberry Pi OS Lite (Trixie and Bookworm).

1. Flash Raspberry Pi OS Lite (64-bit) with [rpi-imager](https://rpi.org/imager) (configure user, SSH, WiFi)
2. SSH into your Pi and run:

   ```bash
   bash <(curl -fsSL https://raw.githubusercontent.com/codesmax/chocopi/main/install.sh)
   ```

   Or clone first:
   ```bash
   git clone https://github.com/codesmax/chocopi.git
   cd chocopi
   ./install.sh
   ```

   The installer handles system dependencies, audio stack setup, Python environment, and systemd service creation.

### macOS Setup

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/codesmax/chocopi/main/install.sh)
```

Or clone first and run locally:

```bash
git clone https://github.com/codesmax/chocopi.git
cd chocopi
./install.sh
```

The script auto-detects macOS or Linux/Pi and runs the appropriate setup.

### Manual Setup (Linux / macOS / Windows)

```bash
git clone https://github.com/codesmax/chocopi.git
cd chocopi

# Install uv if needed
pipx install uv

# macOS: also install portaudio
brew install portaudio

# Create venv with Python 3.11 and install
uv venv .venv --python 3.11
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
uv pip install -e .

# Configure
cp .env.example .env       # add your API key
vi config.yml              # set profile, provider, languages, etc.

# Run
./chocopi
```

> **Note:** On Windows, skip the `./chocopi` launcher (it's a bash script) and run directly with `python -m chocopi` instead. WSL is also an option.

## Configuration

All settings live in two files:

| File | Contents |
|---|---|
| `.env` | API key(s) — `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `ULTRAVOX_API_KEY` |
| `config.yml` | Profiles, languages, `provider`, wake/sleep words, prompts, audio settings, display settings |

### Voice Provider

Set `provider` in `config.yml` to switch between backends:

| Provider | `provider` value | Required dep |
|---|---|---|
| OpenAI Realtime | `openai` | `pipecat-ai[openai]` (default) |
| Google Gemini Live | `google` | `pipecat-ai[google]` |
| Ultravox | `ultravox` | `pipecat-ai[ultravox]` |

Each provider has its own section in `config.yml` for API key, model, voice, and turn-detection settings.

### Profiles

Profiles let multiple users share one device. Each profile specifies age, native language, and learning languages with comprehension levels. Set `profile` in `config.yml` to switch.

### Bluetooth Audio

For Bluetooth microphone and speaker support:

```bash
# Pair your device
sudo -u chocopi bluetoothctl
scan on
pair <MAC_ADDRESS>
trust <MAC_ADDRESS>
connect <MAC_ADDRESS>
exit

# Restart WirePlumber and ChocoPi
sudo -u chocopi XDG_RUNTIME_DIR=/var/run/user/$(id -u chocopi) systemctl --user restart wireplumber
sudo systemctl restart chocopi
```

## Service Management

```bash
sudo systemctl start chocopi    # Start
sudo systemctl stop chocopi     # Stop
sudo systemctl status chocopi   # Check status
sudo journalctl -u chocopi -f   # View logs
```

## Development

### Environment flags

```bash
CHOCO_LOG_LEVEL=DEBUG ./chocopi          # verbose logging (default: INFO)
CHOCO_DISPLAY=0 ./chocopi         # disable pygame-ce UI (default: enabled)
CHOCO_LOG_LEVEL=DEBUG CHOCO_DISPLAY=0 ./chocopi
```

### Audio debugging

```bash
python -m sounddevice              # list audio devices
pactl list sinks short             # list output devices (Linux)
pactl list sources short           # list input devices (Linux)
wpctl status                       # PipeWire/WirePlumber status
bluetoothctl                       # manage Bluetooth connections
sudo journalctl -u chocopi -f      # service logs on Pi
```

## Project Structure

```
chocopi                     # Bash entry point
src/chocopi/                # Python package
  chocopi.py                #   Main orchestrator + signal handling
  wakeword.py               #   Wake word detection
  conversation.py           #   Pipecat pipeline + turn logic
  providers.py              #   LLM service factories (OpenAI, Gemini, Ultravox)
  audio.py                  #   Audio I/O
  display.py                #   Optional pygame-ce UI
  memory.py                 #   Session memory persistence
  config.py                 #   Config and env loading
config.yml                  # Runtime configuration
models/                     # Wake word models (.tflite + .onnx)
assets/                     # Sounds, images, fonts
install/                    # Service configs (installers live at repo root)
  systemd/                  #   Systemd service (Pi)
  wireplumber/              #   WirePlumber Bluetooth configs
  pipewire/                 #   PipeWire echo cancel config
data/                       # Per-profile memory files (gitignored)
```

## Known Issues

- **Wake word false activations** - nearby environmental noise can trigger false activations of wake words. Limit supported languages to those being used and keep microphone away from TVs and other sources of loud, continuous audio.
- **Speech comprehension** - issue is variable depending on environment and microphone used. Experiment with VAD and noise reduction settings.
- **Python 3.11 only** — `tflite-runtime` (required by OpenWakeWord) has no wheels for Python 3.12+. This is an upstream limitation with no current workaround.
- **Windows** — works, but the `./chocopi` bash launcher isn't usable; run `python -m chocopi` directly instead (or use WSL).
- **Bluetooth mic dropouts** — if the microphone stops working after a reboot or OS update, the device may have reverted to the A2DP profile. Re-connect and confirm it's using HSP/HFP (`bluetoothctl`).

## Roadmap

- [ ] Support tool calling for image display in instruction
- [ ] Expanded language + wake word support

## Contributing

Contributions are welcome. A few good starting points:

- **Add a language** — add an entry under `languages` in `config.yml` with a wake word, sleep word, and model name. Wake word models (`.onnx` / `.tflite`) come from [OpenWakeWord](https://github.com/dscripka/openWakeWord).
- **Improve tutor prompts** — the `prompts` section in `config.yml` drives all tutor behavior and is easy to iterate on without touching Python.
- **Bug reports / feature requests** — open an issue on GitHub.

See [AGENTS.md](AGENTS.md) for architecture notes, key files, and change guidelines.

## License

MIT
