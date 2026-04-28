#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════╗
# ║           smoke-notifier — Uninstall Script                     ║
# ║  Run: sudo bash uninstall.sh                                   ║
# ║  Version: 1.0.0 | Copyright: (c) 2026 BadRush                  ║
# ╚══════════════════════════════════════════════════════════════════╝

set -euo pipefail

# ─── Variables ────────────────────────────────────────────────────
APP_NAME="smoke-notifier"
INSTALL_DIR="/opt/smoke-notifier"
SERVICE_NAME="smoke-notifier"
SERVICE_FILE="/etc/systemd/system/smoke-notifier.service"
GRAPH_DIR="/tmp/smoke-notifier"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ─── Functions ────────────────────────────────────────────────────
info()    { echo -e "  ${GREEN}✓${NC} $1"; }
warn()    { echo -e "  ${YELLOW}⚠${NC} $1"; }
error()   { echo -e "  ${RED}✗${NC} $1"; }
step()    { echo -e "\n${BOLD}[$1]${NC} $2"; }
ask()     { echo -ne "  ${CYAN}?${NC} $1"; }

check_root() {
    if [ "$EUID" -ne 0 ]; then
        error "Script harus dijalankan sebagai root!"
        echo "  → Gunakan: sudo bash uninstall.sh"
        exit 1
    fi
}

# ─── Main ─────────────────────────────────────────────────────────
echo ""
echo -e "${RED}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${RED}║       ${BOLD}smoke-notifier${NC}${RED} — Uninstaller                   ║${NC}"
echo -e "${RED}╚══════════════════════════════════════════════════════╝${NC}"
echo ""

check_root

# ══════════════════════════════════════════════════════════════════
# STEP 1: Confirmation
# ══════════════════════════════════════════════════════════════════
step "1/5" "Konfirmasi"

echo ""
echo -e "  Ini akan menghapus:"
echo -e "    • Systemd service: ${SERVICE_NAME}"
echo -e "    • Install directory: ${INSTALL_DIR}"
echo -e "    • Graph temp directory: ${GRAPH_DIR}"
echo ""

ask "Yakin mau uninstall ${APP_NAME}? [y/N]: "
read -r CONFIRM

if [[ "${CONFIRM,,}" != "y" ]]; then
    echo ""
    info "Uninstall dibatalkan."
    exit 0
fi

# ══════════════════════════════════════════════════════════════════
# STEP 2: Backup Option
# ══════════════════════════════════════════════════════════════════
step "2/5" "Backup"

BACKED_UP=false

if [ -d "$INSTALL_DIR" ]; then
    ask "Backup config & state sebelum hapus? [Y/n]: "
    read -r DO_BACKUP

    if [[ "${DO_BACKUP,,}" != "n" ]]; then
        BACKUP_DIR="/opt/smoke-notifier-backup-$(date +%Y%m%d_%H%M%S)"
        mkdir -p "$BACKUP_DIR"

        # Backup config
        if [ -f "${INSTALL_DIR}/config.yaml" ]; then
            cp "${INSTALL_DIR}/config.yaml" "${BACKUP_DIR}/"
            info "config.yaml → ${BACKUP_DIR}/"
        fi

        # Backup state
        if [ -f "${INSTALL_DIR}/state.json" ]; then
            cp "${INSTALL_DIR}/state.json" "${BACKUP_DIR}/"
            info "state.json → ${BACKUP_DIR}/"
        fi

        # Backup logs
        for logfile in "${INSTALL_DIR}"/smoke-notifier.log*; do
            if [ -f "$logfile" ]; then
                cp "$logfile" "${BACKUP_DIR}/"
            fi
        done
        info "Logs → ${BACKUP_DIR}/"

        BACKED_UP=true
        info "Backup selesai: ${BACKUP_DIR}"
    else
        warn "Skip backup — config & state akan hilang!"
    fi
else
    warn "Install directory tidak ditemukan: ${INSTALL_DIR}"
fi

# ══════════════════════════════════════════════════════════════════
# STEP 3: Stop & Disable Service
# ══════════════════════════════════════════════════════════════════
step "3/5" "Stopping service..."

if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    systemctl stop "$SERVICE_NAME"
    info "Service stopped"
else
    info "Service was not running"
fi

if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
    systemctl disable "$SERVICE_NAME"
    info "Service disabled"
else
    info "Service was not enabled"
fi

# ══════════════════════════════════════════════════════════════════
# STEP 4: Remove Files
# ══════════════════════════════════════════════════════════════════
step "4/5" "Removing files..."

# Service file
if [ -f "$SERVICE_FILE" ]; then
    rm -f "$SERVICE_FILE"
    info "Removed: ${SERVICE_FILE}"
fi

# Install directory
if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
    info "Removed: ${INSTALL_DIR}/"
fi

# Graph temp directory
if [ -d "$GRAPH_DIR" ]; then
    rm -rf "$GRAPH_DIR"
    info "Removed: ${GRAPH_DIR}/"
fi

# Reload systemd
systemctl daemon-reload
info "Systemd daemon reloaded"

# ══════════════════════════════════════════════════════════════════
# STEP 5: Optional Pip Cleanup
# ══════════════════════════════════════════════════════════════════
step "5/5" "Cleanup opsional"

ask "Uninstall pip packages (requests, PyYAML)? [y/N]: "
read -r PIP_CLEAN

if [[ "${PIP_CLEAN,,}" == "y" ]]; then
    pip3 uninstall -y requests PyYAML python-dotenv 2>/dev/null || true
    info "pip packages removed"
else
    info "pip packages tetap terinstall"
fi

# ══════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              ✅ UNINSTALL COMPLETE                   ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Removed:${NC}"
echo -e "    ✗ ${SERVICE_FILE}"
echo -e "    ✗ ${INSTALL_DIR}/"
echo -e "    ✗ ${GRAPH_DIR}/"
echo ""

if [ "$BACKED_UP" = true ]; then
    echo -e "  ${BOLD}Backup saved:${NC}"
    echo -e "    📁 ${BACKUP_DIR}/"
    echo -e "    Untuk restore, copy isi backup ke ${INSTALL_DIR}/"
    echo ""
fi

echo -e "  ${CYAN}Untuk reinstall:${NC} sudo bash setup.sh"
echo ""
