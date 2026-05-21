![Image of a friendly robot with a chocolatey treat for a head](https://github.com/user-attachments/assets/d197fcb5-cfa9-4faf-a3ce-9e9b94eb9ee0)

# Choco

A voice-powered language tutor for kids.

This repo contains two products that share a common core:

| Product | Description | Target |
|---|---|---|
| **chocopi** | Always-on kiosk app with on-device wake word detection | Raspberry Pi (dedicated device) |
| **chocoweb** *(planned)* | Browser-accessible server app with WebRTC audio | Any host, accessed from any browser |

Both apps consume **chococore** — the platform-agnostic package that handles conversation logic, LLM providers, session memory, and prompts.

---

## chocopi — Raspberry Pi Kiosk

ChocoPi listens for a wake word, then holds a live conversation to help children practice English, Korean, Spanish, or Chinese. Each language has its own wake word, sleep word, and teaching style — all configurable.

https://github.com/user-attachments/assets/7e72a294-3c8f-48a5-b8f6-ec7416c1d9a8

### How It Works

1. Wake word detection runs on-device using [OpenWakeWord](https://github.com/dscripka/openWakeWord) (TFLite on ARM, ONNX elsewhere)
2. Once triggered, a live voice conversation starts via a configurable provider (OpenAI Realtime, Gemini Live, or Ultravox)
3. The assistant adapts to the child's age, native language, and comprehension level
4. Sessions end with a language-specific sleep word or timeout
5. Conversation history is summarized and persisted for continuity across sessions

### Features

- **4 languages** — English, Korean, Spanish, and Chinese
- **On-device wake words** — "Hey Choco", "Anyeong Choco", "Hola Choco", "Nihao Choco"
- **Multiple voice providers** — OpenAI Realtime (default), Google Gemini Live, or Ultravox; swap via `config.yml`
- **User profiles** — per-child age, native language, and learning levels
- **Session memory** — remembers jokes, vocab, topics, and progress across conversations
- **Display support** — animated character and live transcript panel (pygame-ce); also works headless!

### Requirements

- Microphone and speaker (Bluetooth or wired)
- API key for your chosen voice provider (OpenAI by default — see [pricing](https://openai.com/api/pricing/))
- Python 3.11 (required — `tflite-runtime` has no wheels for 3.12+)

### Raspberry Pi Setup

Tested on Raspberry Pi 4+ with 64-bit Raspberry Pi OS Lite (Trixie and Bookworm).

1. Flash Raspberry Pi OS Lite (64-bit) with [rpi-imager](https://rpi.org/imager) (configure user, SSH, WiFi)
2. SSH into your Pi and run:

   ```bash
   bash <(curl -fsSL https://raw.githubusercontent.com/codesmax/choco/main/pi/install.sh)
   ```

   Or clone first:
   ```bash
   git clone https://github.com/codesmax/choco.git
   cd choco
   ./pi/install.sh
   ```

   The installer handles system dependencies, audio stack setup, Python environment, and systemd service creation.

### macOS Setup

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/codesmax/choco/main/pi/install.sh)
```

Or clone first and run locally:

```bash
git clone https://github.com/codesmax/choco.git
cd choco
./pi/install.sh
```

### Manual Setup (Linux / macOS / Windows)

```bash
git clone https://github.com/codesmax/choco.git
cd choco

# Install uv if needed
pipx install uv

# macOS: also install portaudio
brew install portaudio

# Set up workspace (creates .venv and installs all packages)
uv sync

# Configure
cp .env.example .env       # add your API key
vi config.yml              # set profile, provider, languages, etc.

# Run
./pi/chocopi/chocopi
```

> **Note:** On Windows, skip the bash launcher and run directly with `python -m chocopi` instead. WSL is also an option.

### Configuration

All settings live in two files:

| File | Contents |
|---|---|
| `.env` | API key(s) — `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `ULTRAVOX_API_KEY` |
| `config.yml` | Profiles, languages, `provider`, wake/sleep words, prompts, audio settings, display settings |

#### Voice Provider

Set `provider` in `config.yml` to switch between backends:

| Provider | `provider` value |
|---|---|
| OpenAI Realtime | `openai` (default) |
| Google Gemini Live | `google` |
| Ultravox | `ultravox` |

#### Profiles

Profiles let multiple users share one device. Each profile specifies age, native language, and learning languages with comprehension levels. Set `profile` in `config.yml` to switch.

#### Bluetooth Audio

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

### Service Management (Pi)

```bash
sudo systemctl start chocopi    # Start
sudo systemctl stop chocopi     # Stop
sudo systemctl status chocopi   # Check status
sudo journalctl -u chocopi -f   # View logs
```

### Development

```bash
CHOCO_LOG_LEVEL=DEBUG ./pi/chocopi/chocopi    # verbose logging
CHOCO_DISPLAY=0 ./pi/chocopi/chocopi          # disable pygame-ce UI
```

### Audio Debugging

```bash
python -m sounddevice              # list audio devices
pactl list sinks short             # list output devices (Linux)
pactl list sources short           # list input devices (Linux)
wpctl status                       # PipeWire/WirePlumber status
bluetoothctl                       # manage Bluetooth connections
sudo journalctl -u chocopi -f      # service logs on Pi
```

---

## Repo Structure

```
choco/                          # uv workspace root
├── pyproject.toml              # workspace definition (members: core, pi)
├── config.yml                  # runtime configuration (shared)
├── assets/
│   ├── models/                 # wake-word models (.tflite + .onnx)
│   ├── images/                 # character sprites, UI elements
│   ├── sounds/                 # SFX and jingles
│   └── fonts/                  # bundled fonts
├── core/
│   └── chococore/              # platform-agnostic package
│       ├── config.py           #   config + env loading, path constants
│       ├── conversation.py     #   Pipecat pipeline + turn logic (transport-injected)
│       ├── providers.py        #   LLM service factories (OpenAI, Gemini, Ultravox)
│       ├── memory.py           #   session memory persistence
│       └── pipecat_utils.py    #   FrameProcessor subclasses + observer
├── pi/
│   ├── chocopi/                # Pi kiosk package
│   │   ├── chocopi             #   bash launcher (entry point)
│   │   ├── chocopi.py          #   orchestrator + signal handling
│   │   ├── wakeword.py         #   OpenWakeWord integration
│   │   ├── audio.py            #   audio I/O (sounddevice + simpleaudio)
│   │   └── display.py          #   optional pygame-ce UI
│   └── install/                # Pi-specific installation
│       ├── install.sh          #   cross-platform installer
│       ├── systemd/            #   systemd service unit
│       ├── wireplumber/        #   Bluetooth audio configs
│       └── pipewire/           #   echo cancellation config
└── data/                       # per-profile memory files (gitignored)
```

---

## Known Issues

- **Wake word false activations** — nearby environmental noise can trigger false activations. Limit supported languages to those in use and keep the mic away from TVs and other continuous audio sources.
- **Python 3.11 only** — `tflite-runtime` (required by OpenWakeWord) has no wheels for Python 3.12+. Upstream limitation with no current workaround.
- **Windows** — works, but the bash launcher isn't usable; run `python -m chocopi` directly or use WSL.
- **Bluetooth mic dropouts** — if the mic stops working after a reboot, the device may have reverted to A2DP. Re-connect and confirm HSP/HFP via `bluetoothctl`.

## Roadmap

- [ ] chocoweb — browser-accessible sibling app (WebRTC, FastAPI, no dedicated hardware required)
- [ ] Support tool calling for image display during instruction
- [ ] Expanded language + wake word support

## Contributing

Contributions are welcome. A few good starting points:

- **Add a language** — add an entry under `languages` in `config.yml` with a wake word, sleep word, and model name. Wake word models (`.onnx` / `.tflite`) come from [OpenWakeWord](https://github.com/dscripka/openWakeWord).
- **Improve tutor prompts** — the `prompts` section in `config.yml` drives all tutor behavior and is easy to iterate on without touching Python.
- **Bug reports / feature requests** — open an issue on GitHub.

See [AGENTS.md](AGENTS.md) for architecture notes, key files, and change guidelines.

## License

MIT
