#!/bin/bash
set -e

# ============================================================================
# Output formatting
# ============================================================================
BOLD='\033[1m'
RESET='\033[0m'

log() { echo -e "${BOLD}$1${RESET}"; }
info() { log "✨ $1"; }
tip() { log "💡 $1"; }
warn() { log "⚠️  $1"; }
error() { log "❌ $1" >&2; }
success() { echo -e "✔️  $1\n"; }

# ============================================================================
# Platform detection
# ============================================================================
case "$(uname -s)" in
    Darwin) PLATFORM=darwin ;;
    Linux)  PLATFORM=linux ;;
    *)      error "Unsupported platform: $(uname -s)"; exit 1 ;;
esac

# ============================================================================
# Configuration
# ============================================================================
PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
GITHUB_REPO="${GITHUB_REPO:-https://github.com/codesmax/choco.git}"

if [[ "$PLATFORM" == "darwin" ]]; then
    INSTALL_DIR="${CHOCOPI_DIR:-$HOME/chocopi}"
else
    CHOCOPI_USER="${CHOCOPI_USER:-chocopi}"
    CHOCOPI_HOME="/home/${CHOCOPI_USER}"
    INSTALL_DIR="${CHOCOPI_INSTALL_DIR:-/opt/chocopi}"

    if [[ ! -f /etc/debian_version ]]; then
        error "This installer requires a Debian-based Linux distribution"
        exit 1
    fi

    if [[ -f /proc/cpuinfo ]] && grep -q "Raspberry Pi" /proc/cpuinfo; then
        if [[ "$(uname -m)" != "aarch64" ]]; then
            warn "Running on Raspberry Pi with '$(uname -m)' architecture. For best performance, use a 64-bit Raspberry Pi OS (aarch64)."
        fi
    fi
fi

# ============================================================================
# Installation summary
# ============================================================================
info "Installing ChocoPi Language Tutor..."
echo

if [[ "$PLATFORM" == "darwin" ]]; then
    echo "This script will:"
    echo "  • Install Homebrew (if needed)"
    echo "  • Install portaudio and uv via Homebrew"
    echo "  • Clone/update ChocoPi to ${INSTALL_DIR}"
    echo "  • Set up Python ${PYTHON_VERSION} virtual environment and dependencies"
    echo "  • Optionally configure API key"
else
    echo "This script will:"
    echo "  • Install system dependencies (pipewire, python3, etc.)"
    echo "  • Create '${CHOCOPI_USER}' user with limited privileges"
    echo "  • Clone/update ChocoPi to ${INSTALL_DIR}"
    echo "  • Set up Python ${PYTHON_VERSION} virtual environment and dependencies"
    echo "  • Configure PipeWire/WirePlumber for Bluetooth audio"
    echo "  • Install and enable systemd service"
fi

echo
read -p "Continue with installation? [Y/n] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]] && [[ -n $REPLY ]]; then
    info "Installation cancelled"
    exit 0
fi

# ============================================================================
# System dependencies
# ============================================================================
if [[ "$PLATFORM" == "darwin" ]]; then
    if ! command -v brew &>/dev/null; then
        info "Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null || \
        eval "$(/usr/local/bin/brew shellenv)" 2>/dev/null || true
    fi
    success "Homebrew ready"

    info "Installing portaudio..."
    brew install portaudio
    success "portaudio installed"

    if ! command -v uv &>/dev/null; then
        info "Installing uv..."
        brew install uv
    fi
    success "uv ready"

else
    info "Installing system dependencies..."
    sudo apt update
    sudo apt install -y git pipx libportaudio2 portaudio19-dev libasound2-dev libegl1 libegl-dev pipewire pipewire-audio pulseaudio-utils
    success "System dependencies installed"

    if ! id "${CHOCOPI_USER}" &>/dev/null; then
        info "Creating ${CHOCOPI_USER} user..."
        sudo useradd -m -s /bin/bash -G audio,video,render,bluetooth "${CHOCOPI_USER}"
        success "User ${CHOCOPI_USER} created"

        info "Enabling systemd linger for ${CHOCOPI_USER}..."
        sudo loginctl enable-linger "${CHOCOPI_USER}"
        success "Systemd linger enabled"
    fi

    if [[ ! -d "${INSTALL_DIR}" ]]; then
        info "Setting up application directory..."
        sudo mkdir -p "${INSTALL_DIR}"
        sudo chown "${CHOCOPI_USER}:${CHOCOPI_USER}" "${INSTALL_DIR}"
        success "Application directory created at ${INSTALL_DIR}"
    fi

    info "Installing uv for ${CHOCOPI_USER}..."
    sudo -u "${CHOCOPI_USER}" pipx install uv
    sudo -u "${CHOCOPI_USER}" pipx ensurepath
    success "uv installed"
fi

# ============================================================================
# Clone or update repository
# ============================================================================
if [[ ! -d "${INSTALL_DIR}/.git" ]]; then
    info "Cloning ChocoPi to ${INSTALL_DIR}..."
    if [[ "$PLATFORM" == "darwin" ]]; then
        git clone "${GITHUB_REPO}" "${INSTALL_DIR}"
    else
        sudo -u "${CHOCOPI_USER}" git clone "${GITHUB_REPO}" "${INSTALL_DIR}"
    fi
    success "Repository cloned"
else
    info "Repository already exists, updating..."
    if [[ "$PLATFORM" == "darwin" ]]; then
        git -C "${INSTALL_DIR}" pull
    else
        sudo -u "${CHOCOPI_USER}" git -C "${INSTALL_DIR}" pull
    fi
    success "Repository updated"
fi

# ============================================================================
# Python environment
# ============================================================================
info "Setting up Python ${PYTHON_VERSION} environment..."

if [[ "$PLATFORM" == "darwin" ]]; then
    (cd "${INSTALL_DIR}" && uv sync --python "${PYTHON_VERSION}")
    chmod +x "${INSTALL_DIR}/pi/chocopi/chocopi"
else
    UV="${CHOCOPI_HOME}/.local/bin/uv"
    sudo -u "${CHOCOPI_USER}" bash -c "cd '${INSTALL_DIR}' && '${UV}' sync --python '${PYTHON_VERSION}'"
    sudo chmod +x "${INSTALL_DIR}/pi/chocopi/chocopi"
fi

success "Python environment configured"

# ============================================================================
# Linux: audio and service setup
# ============================================================================
if [[ "$PLATFORM" == "linux" ]]; then
    info "Configuring PipeWire/WirePlumber for Bluetooth audio..."

    WP_VERSION=$(dpkg-query -W -f='${Version}' wireplumber 2>/dev/null | grep -oP '^\d+\.\d+' || echo "0.5")
    WP_MAJOR=$(echo "$WP_VERSION" | cut -d. -f1)
    WP_MINOR=$(echo "$WP_VERSION" | cut -d. -f2)

    if [[ "$WP_MAJOR" -eq 0 ]] && [[ "$WP_MINOR" -lt 5 ]]; then
        log "🔎 Detected WirePlumber ${WP_VERSION} (Lua config)"
        WP_CONFIG_DIR="${CHOCOPI_HOME}/.config/wireplumber/bluetooth.lua.d"
        WP_CONFIG_FILE="51-bluetooth-audio.lua"
    else
        log "🔎 Detected WirePlumber ${WP_VERSION} (conf format)"
        WP_CONFIG_DIR="${CHOCOPI_HOME}/.config/wireplumber/wireplumber.conf.d"
        WP_CONFIG_FILE="51-bluetooth-audio.conf"
    fi

    if [[ -f "${INSTALL_DIR}/pi/install/wireplumber/${WP_CONFIG_FILE}" ]]; then
        sudo -u "${CHOCOPI_USER}" mkdir -p "${WP_CONFIG_DIR}"
        sudo -u "${CHOCOPI_USER}" cp "${INSTALL_DIR}/pi/install/wireplumber/${WP_CONFIG_FILE}" "${WP_CONFIG_DIR}/"
        success "WirePlumber Bluetooth config installed"
    fi

    PW_EC_SRC="${INSTALL_DIR}/pi/install/pipewire/99-echo-cancel.conf"
    if [[ -f "${PW_EC_SRC}" ]]; then
        PW_CONFIG_DIR="${CHOCOPI_HOME}/.config/pipewire/pipewire.conf.d"
        sudo -u "${CHOCOPI_USER}" mkdir -p "${PW_CONFIG_DIR}"
        sudo -u "${CHOCOPI_USER}" cp "${PW_EC_SRC}" "${PW_CONFIG_DIR}/"
        success "PipeWire echo cancellation config installed"
    fi

    info "Restarting WirePlumber..."
    sudo -u "${CHOCOPI_USER}" XDG_RUNTIME_DIR=/run/user/$(id -u "${CHOCOPI_USER}") systemctl --user restart wireplumber
    success "PipeWire and Bluetooth services configured"

    info "Installing systemd service..."
    sudo cp "${INSTALL_DIR}/pi/install/systemd/chocopi.service" /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable chocopi
    success "Systemd service installed and enabled"
fi

# ============================================================================
# API key
# ============================================================================
info "Configuring API key..."
read -p "Enter your OpenAI API key (or press Enter to configure later): " API_KEY

if [[ -n "$API_KEY" ]]; then
    if [[ "$PLATFORM" == "darwin" ]]; then
        echo "OPENAI_API_KEY=${API_KEY}" > "${INSTALL_DIR}/.env"
        chmod 600 "${INSTALL_DIR}/.env"
    else
        echo "OPENAI_API_KEY=${API_KEY}" | sudo tee "${INSTALL_DIR}/.env" > /dev/null
        sudo chown "${CHOCOPI_USER}:${CHOCOPI_USER}" "${INSTALL_DIR}/.env"
        sudo chmod 600 "${INSTALL_DIR}/.env"
    fi
    success ".env file created"
else
    tip "To configure later:"
    if [[ "$PLATFORM" == "darwin" ]]; then
        echo "  echo 'OPENAI_API_KEY=your_key_here' > ${INSTALL_DIR}/.env"
        echo "  chmod 600 ${INSTALL_DIR}/.env"
    else
        echo "  echo 'OPENAI_API_KEY=your_key_here' | sudo tee ${INSTALL_DIR}/.env"
        echo "  sudo chown ${CHOCOPI_USER}:${CHOCOPI_USER} ${INSTALL_DIR}/.env"
        echo "  sudo chmod 600 ${INSTALL_DIR}/.env"
    fi
    echo
fi

# ============================================================================
# Done
# ============================================================================
echo
log "🎉 Installation complete!"
echo

if [[ "$PLATFORM" == "linux" ]]; then
    if [[ -n "$API_KEY" ]]; then
        info "Starting ChocoPi service..."
        sudo systemctl start chocopi
        echo
        info "Service status:"
        sudo systemctl status chocopi --no-pager -l
        echo
    else
        tip "Then start the service:"
        echo "  sudo systemctl start chocopi"
        echo
    fi
    tip "Helpful commands:"
    echo "  sudo systemctl status chocopi   # Check status"
    echo "  sudo journalctl -u chocopi -f   # View logs"
    echo
    tip "To pair a Bluetooth audio device:"
    echo "  sudo -u ${CHOCOPI_USER} bluetoothctl"
    echo "  scan on; pair <MAC>; trust <MAC>; connect <MAC>; exit"
    echo
else
    tip "To run ChocoPi:"
    echo "  cd ${INSTALL_DIR} && ./pi/chocopi/chocopi"
    echo
    tip "Audio troubleshooting:"
    echo "  python -m sounddevice    # list audio devices"
    echo
fi

tip "See README.md for configuration and usage."
