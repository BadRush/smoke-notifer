#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════╗
# ║           smoke-notifier — Interactive Setup Script             ║
# ║  Run: sudo bash setup.sh                                       ║
# ╚══════════════════════════════════════════════════════════════════╝

set -euo pipefail

# ─── Variables ────────────────────────────────────────────────────
APP_NAME="smoke-notifier"
INSTALL_DIR="/opt/smoke-notifier"
SERVICE_FILE="/etc/systemd/system/smoke-notifier.service"
GRAPH_DIR="/tmp/smoke-notifier"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ─── Functions ────────────────────────────────────────────────────
banner() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║       ${BOLD}smoke-notifier${NC}${CYAN} — Setup Installer              ║${NC}"
    echo -e "${CYAN}║       SmokePing Monitor → Telegram Alert            ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════╝${NC}"
    echo ""
}

info()    { echo -e "  ${GREEN}✓${NC} $1"; }
warn()    { echo -e "  ${YELLOW}⚠${NC} $1"; }
error()   { echo -e "  ${RED}✗${NC} $1"; }
step()    { echo -e "\n${BOLD}[$1]${NC} $2"; }
ask()     { echo -ne "  ${CYAN}?${NC} $1"; }

check_root() {
    if [ "$EUID" -ne 0 ]; then
        error "Script harus dijalankan sebagai root!"
        echo "  → Gunakan: sudo bash setup.sh"
        exit 1
    fi
}

# ─── Main ─────────────────────────────────────────────────────────
banner
check_root

# ══════════════════════════════════════════════════════════════════
# STEP 1: Check & Install Dependencies
# ══════════════════════════════════════════════════════════════════
step "1/7" "Checking dependencies..."

# Python 3
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 --version 2>&1 | cut -d' ' -f2)
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 8 ]; then
        info "Python $PY_VER ✓"
    else
        error "Python >= 3.8 required (found $PY_VER)"
        exit 1
    fi
else
    warn "Python3 not found, installing..."
    apt-get update -qq && apt-get install -y -qq python3 python3-pip
    info "Python3 installed"
fi

# pip3
if ! command -v pip3 &>/dev/null; then
    warn "pip3 not found, installing..."
    apt-get install -y -qq python3-pip
    info "pip3 installed"
else
    info "pip3 ✓"
fi

# rrdtool
if command -v rrdtool &>/dev/null; then
    info "rrdtool ✓"
else
    warn "rrdtool not found, installing..."
    apt-get update -qq && apt-get install -y -qq rrdtool
    info "rrdtool installed"
fi

# ══════════════════════════════════════════════════════════════════
# STEP 2: Install Python packages
# ══════════════════════════════════════════════════════════════════
step "2/7" "Installing Python packages..."

pip3 install -q -r "${SCRIPT_DIR}/requirements.txt"
info "Python packages installed"

# ══════════════════════════════════════════════════════════════════
# STEP 3: Create install directory & copy files
# ══════════════════════════════════════════════════════════════════
step "3/7" "Setting up ${INSTALL_DIR}..."

mkdir -p "$INSTALL_DIR"
mkdir -p "$GRAPH_DIR"

# Copy main script
cp "${SCRIPT_DIR}/smokeping_monitor.py" "${INSTALL_DIR}/smokeping_monitor.py"
chmod +x "${INSTALL_DIR}/smokeping_monitor.py"
info "smokeping_monitor.py → ${INSTALL_DIR}/"

# Copy requirements
cp "${SCRIPT_DIR}/requirements.txt" "${INSTALL_DIR}/requirements.txt"
info "requirements.txt → ${INSTALL_DIR}/"

# ══════════════════════════════════════════════════════════════════
# STEP 4: Configuration Wizard
# ══════════════════════════════════════════════════════════════════
step "4/7" "Configuration..."

CONFIG_FILE="${INSTALL_DIR}/config.yaml"

if [ -f "$CONFIG_FILE" ]; then
    warn "config.yaml sudah ada: ${CONFIG_FILE}"
    ask "Overwrite? (backup lama akan disimpan) [y/N]: "
    read -r OVERWRITE
    if [[ "${OVERWRITE,,}" == "y" ]]; then
        BACKUP="${CONFIG_FILE}.bak.$(date +%Y%m%d_%H%M%S)"
        cp "$CONFIG_FILE" "$BACKUP"
        info "Backup config lama → ${BACKUP}"
        DO_CONFIG=true
    else
        info "Menggunakan config yang sudah ada"
        DO_CONFIG=false
    fi
else
    DO_CONFIG=true
fi

if [ "$DO_CONFIG" = true ]; then
    echo ""
    echo -e "  ${BOLD}Telegram Bot Configuration${NC}"
    echo -e "  Buat bot di @BotFather lalu dapatkan token & chat_id"
    echo ""

    # Bot Token
    ask "Telegram Bot Token: "
    read -r TG_TOKEN
    if [ -z "$TG_TOKEN" ]; then
        error "Bot token tidak boleh kosong!"
        exit 1
    fi

    # Chat ID
    ask "Telegram Chat ID: "
    read -r TG_CHAT_ID
    if [ -z "$TG_CHAT_ID" ]; then
        error "Chat ID tidak boleh kosong!"
        exit 1
    fi

    # RRD Base Path
    ask "SmokePing RRD base path [/var/lib/smokeping]: "
    read -r RRD_PATH
    RRD_PATH="${RRD_PATH:-/var/lib/smokeping}"

    if [ ! -d "$RRD_PATH" ]; then
        warn "Path ${RRD_PATH} tidak ditemukan — pastikan benar saat deploy"
    else
        info "RRD path: ${RRD_PATH} ✓"
    fi

    # Generate config from template
    cp "${SCRIPT_DIR}/config.example.yaml" "$CONFIG_FILE"

    # Replace placeholders
    sed -i "s|YOUR_BOT_TOKEN|${TG_TOKEN}|g" "$CONFIG_FILE"
    sed -i "s|YOUR_CHAT_ID|${TG_CHAT_ID}|g" "$CONFIG_FILE"
    sed -i "s|/var/lib/smokeping|${RRD_PATH}|g" "$CONFIG_FILE"

    info "config.yaml generated → ${CONFIG_FILE}"
    warn "PENTING: Edit config.yaml untuk menambahkan link/target yang dipantau!"
fi

# ══════════════════════════════════════════════════════════════════
# STEP 5: Test Telegram Connection
# ══════════════════════════════════════════════════════════════════
step "5/7" "Testing Telegram connection..."

if python3 "${INSTALL_DIR}/smokeping_monitor.py" --config "$CONFIG_FILE" --test 2>/dev/null; then
    info "Telegram connection OK ✓"
else
    warn "Telegram test failed — cek bot_token & chat_id di config"
    ask "Lanjutkan install? [y/N]: "
    read -r CONTINUE
    if [[ "${CONTINUE,,}" != "y" ]]; then
        echo ""
        error "Setup dibatalkan. Fix config lalu jalankan ulang setup.sh"
        exit 1
    fi
fi

# ══════════════════════════════════════════════════════════════════
# STEP 6: Install Systemd Service
# ══════════════════════════════════════════════════════════════════
step "6/7" "Installing systemd service..."

cp "${SCRIPT_DIR}/smoke-notifier.service" "$SERVICE_FILE"

systemctl daemon-reload
systemctl enable smoke-notifier
info "Service enabled: smoke-notifier"

# Start service
ask "Start service sekarang? [Y/n]: "
read -r START_NOW
if [[ "${START_NOW,,}" != "n" ]]; then
    systemctl start smoke-notifier
    sleep 2
    if systemctl is-active --quiet smoke-notifier; then
        info "Service started ✓"
    else
        warn "Service may not have started. Check: journalctl -u smoke-notifier -f"
    fi
else
    info "Service not started. Start manually: systemctl start smoke-notifier"
fi

# ══════════════════════════════════════════════════════════════════
# STEP 7: Summary
# ══════════════════════════════════════════════════════════════════
step "7/7" "Setup complete!"

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              ✅ INSTALLATION COMPLETE                ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Files:${NC}"
echo -e "    Script  : ${INSTALL_DIR}/smokeping_monitor.py"
echo -e "    Config  : ${INSTALL_DIR}/config.yaml"
echo -e "    State   : ${INSTALL_DIR}/state.json"
echo -e "    Log     : ${INSTALL_DIR}/smoke-notifier.log"
echo -e "    Graphs  : ${GRAPH_DIR}/"
echo -e "    Service : ${SERVICE_FILE}"
echo ""
echo -e "  ${BOLD}Commands:${NC}"
echo -e "    Status     : ${CYAN}systemctl status smoke-notifier${NC}"
echo -e "    Logs       : ${CYAN}journalctl -u smoke-notifier -f${NC}"
echo -e "    Restart    : ${CYAN}systemctl restart smoke-notifier${NC}"
echo -e "    Stop       : ${CYAN}systemctl stop smoke-notifier${NC}"
echo -e "    Edit config: ${CYAN}nano ${INSTALL_DIR}/config.yaml${NC}"
echo -e "    Test alert : ${CYAN}python3 ${INSTALL_DIR}/smokeping_monitor.py --test${NC}"
echo -e "    Dry run    : ${CYAN}python3 ${INSTALL_DIR}/smokeping_monitor.py --dry-run${NC}"
echo -e "    Uninstall  : ${CYAN}sudo bash uninstall.sh${NC}"
echo ""
echo -e "  ${YELLOW}⚠ NEXT:${NC} Edit config.yaml dan tambahkan link yang ingin dipantau!"
echo -e "         Lalu restart: ${CYAN}systemctl restart smoke-notifier${NC}"
echo ""
