#!/usr/bin/env bash
#
# uninstall.sh — DocuBrowse uninstaller
#
# Usage:
#   ./uninstall.sh             # uninstall
#
# Behavior mirrors install.sh:
#   - Run as a normal user  -> removes $HOME/.docubrowse install
#   - Run as root (sudo)    -> removes /opt/docubrowse system-wide install
#
# This stops and removes the systemd unit, removes the install directory
# (including the venv), removes the CLI wrapper, and (user mode) removes
# pid/log files under $HOME/.local. In system mode it will optionally
# remove the dedicated 'docubrowse' system user/group (asks first).
#
set -euo pipefail

# ─── Detect mode (mirrors install.sh) ───────────────────────────────────────
if [[ "$EUID" -eq 0 ]]; then
    MODE="system"
    INSTALL_DIR="/opt/docubrowse"
    SERVICE_USER="docubrowse"
    SERVICE_GROUP="docubrowse"
    BIN_LINK="/usr/local/bin/docubrowse"
    UNIT_PATH="/etc/systemd/system/docubrowser.service"
    SUDO=""
else
    MODE="user"
    INSTALL_DIR="$HOME/.docubrowse"
    SERVICE_USER="$(id -un)"
    SERVICE_GROUP="$(id -gn)"
    BIN_LINK="/usr/local/bin/docubrowse"
    UNIT_PATH="/etc/systemd/system/docubrowser.service"
    SUDO="sudo"
fi

LOCAL_RUN_DIR="$HOME/.local/run"
LOCAL_LOG_DIR="$HOME/.local/var/log"

echo "==> DocuBrowse uninstaller"
echo "    Mode:        $MODE"
echo "    Install dir: $INSTALL_DIR"
echo

if [[ ! -e "$INSTALL_DIR" ]] && [[ ! -e "$UNIT_PATH" ]] && [[ ! -e "$BIN_LINK" ]]; then
    echo "Nothing to do — no DocuBrowse install found at $INSTALL_DIR,"
    echo "no $UNIT_PATH, and no $BIN_LINK."
    exit 0
fi

read -rp "This will remove the DocuBrowse install at $INSTALL_DIR, its systemd"$'\n'"unit, and CLI wrapper. Continue? [y/N] " CONFIRM
case "$CONFIRM" in
    [yY]|[yY][eE][sS]) ;;
    *) echo "Aborted."; exit 1 ;;
esac

# ─── Stop and disable the service ───────────────────────────────────────────
if [[ -e "$UNIT_PATH" ]]; then
    echo "==> Stopping docubrowser service (if running)"
    $SUDO systemctl stop docubrowser 2>/dev/null || true
    $SUDO systemctl disable docubrowser 2>/dev/null || true

    echo "==> Removing systemd unit $UNIT_PATH"
    $SUDO rm -f "$UNIT_PATH"

    echo "==> Reloading systemd"
    $SUDO systemctl daemon-reload
else
    echo "==> No systemd unit at $UNIT_PATH — skipping service removal"
fi

# ─── Remove CLI wrapper ──────────────────────────────────────────────────────
if [[ -e "$BIN_LINK" ]]; then
    echo "==> Removing CLI wrapper $BIN_LINK"
    $SUDO rm -f "$BIN_LINK"
fi

# ─── Remove install directory (includes venv, db, config) ──────────────────
if [[ -e "$INSTALL_DIR" ]]; then
    echo "==> Removing $INSTALL_DIR"
    if [[ "$MODE" == "system" ]]; then
        $SUDO rm -rf "$INSTALL_DIR"
    else
        rm -rf "$INSTALL_DIR"
    fi
fi

# ─── Remove user-mode pid/log files ─────────────────────────────────────────
if [[ "$MODE" == "user" ]]; then
    for f in "$LOCAL_RUN_DIR/docubrowser.pid" "$LOCAL_RUN_DIR/docubrowser-scan.pid" \
             "$LOCAL_LOG_DIR/docubrowser.log"; do
        if [[ -e "$f" ]]; then
            echo "==> Removing $f"
            rm -f "$f"
        fi
    done
fi

# ─── Remove system-mode runtime/log directories ─────────────────────────────
if [[ "$MODE" == "system" ]]; then
    for d in "/run/docubrowser" "/var/log/docubrowser"; do
        if [[ -e "$d" ]]; then
            echo "==> Removing $d"
            $SUDO rm -rf "$d"
        fi
    done
fi

# ─── Optionally remove dedicated service user/group (system mode only) ─────
if [[ "$MODE" == "system" ]]; then
    if getent passwd "$SERVICE_USER" >/dev/null 2>&1 || getent group "$SERVICE_GROUP" >/dev/null 2>&1; then
        echo
        read -rp "Also remove the dedicated '$SERVICE_USER' system user/group? [y/N] " RM_USER
        case "$RM_USER" in
            [yY]|[yY][eE][sS])
                if getent passwd "$SERVICE_USER" >/dev/null 2>&1; then
                    echo "==> Removing user '$SERVICE_USER'"
                    userdel "$SERVICE_USER" 2>/dev/null || true
                fi
                if getent group "$SERVICE_GROUP" >/dev/null 2>&1; then
                    echo "==> Removing group '$SERVICE_GROUP'"
                    groupdel "$SERVICE_GROUP" 2>/dev/null || true
                fi
                ;;
            *)
                echo "Leaving '$SERVICE_USER' user/group in place."
                ;;
        esac
    fi
fi

echo
echo "==> Uninstall complete."
