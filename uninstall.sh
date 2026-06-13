#!/usr/bin/env bash
#
# uninstall.sh — DocuBrowse uninstaller
#
# Behavior mirrors install.sh:
#   - Run as a normal user  -> removes the USER install at $HOME/.docubrowse
#                              (CLI wrapper in ~/.local/bin, no systemd).
#   - Run as root (sudo)    -> removes the SYSTEM install at /opt/docubrowse
#                              (systemd unit, /usr/local/bin wrapper, optional
#                              dedicated service user/group).
#
# It also cleans up *legacy* artifacts from earlier broken installs (e.g. a
# user install that wrongly created a systemd unit and a /usr/local/bin
# wrapper), so upgrading from a half-finished install works.
#
set -euo pipefail

UNIT_PATH="/etc/systemd/system/docubrowser.service"
LOCAL_RUN_DIR="$HOME/.local/run"
LOCAL_LOG_DIR="$HOME/.local/var/log"

if [[ "$EUID" -eq 0 ]]; then
    MODE="system"
    INSTALL_DIR="/opt/docubrowse"
    SERVICE_USER="docubrowse"
    SERVICE_GROUP="docubrowse"
    SUDO=""
else
    MODE="user"
    INSTALL_DIR="$HOME/.docubrowse"
    SUDO="sudo"
fi

# Candidate CLI wrappers to remove (new + legacy names/locations).
WRAPPERS=(
    "$HOME/.local/bin/docubrowser"
    "/usr/local/bin/docubrowser"
    "/usr/local/bin/docubrowse"     # legacy
)

echo "==> DocuBrowse uninstaller"
echo "    Mode:        $MODE"
echo "    Install dir: $INSTALL_DIR"
echo

# Figure out whether there is anything to do.
FOUND=0
[[ -e "$INSTALL_DIR" ]] && FOUND=1
[[ -e "$UNIT_PATH" ]] && FOUND=1
for w in "${WRAPPERS[@]}"; do [[ -e "$w" ]] && FOUND=1; done
if [[ "$FOUND" -eq 0 ]]; then
    echo "Nothing to do — no DocuBrowse install, systemd unit, or CLI wrapper found."
    exit 0
fi

read -rp "Remove DocuBrowse ($INSTALL_DIR, systemd unit, CLI wrapper)? [y/N] " CONFIRM
case "$CONFIRM" in
    [yY]|[yY][eE][sS]) ;;
    *) echo "Aborted."; exit 1 ;;
esac

# ─── Stop and remove the systemd unit (if any) ──────────────────────────────
if [[ -e "$UNIT_PATH" ]]; then
    echo "==> Stopping/disabling docubrowser service"
    $SUDO systemctl stop docubrowser 2>/dev/null || true
    $SUDO systemctl disable docubrowser 2>/dev/null || true
    echo "==> Removing systemd unit $UNIT_PATH"
    $SUDO rm -f "$UNIT_PATH"
    $SUDO systemctl daemon-reload 2>/dev/null || true
fi

# ─── Remove CLI wrapper(s) ──────────────────────────────────────────────────
for w in "${WRAPPERS[@]}"; do
    if [[ -e "$w" ]]; then
        echo "==> Removing CLI wrapper $w"
        if [[ -w "$(dirname "$w")" ]]; then
            rm -f "$w"
        else
            $SUDO rm -f "$w"
        fi
    fi
done

# ─── Remove install directory (includes venv, db, config) ───────────────────
if [[ -e "$INSTALL_DIR" ]]; then
    echo "==> Removing $INSTALL_DIR"
    if [[ "$MODE" == "system" ]]; then
        $SUDO rm -rf "$INSTALL_DIR"
    else
        rm -rf "$INSTALL_DIR"
    fi
fi

# ─── Remove user-mode pid/log files ─────────────────────────────────────────
for f in "$LOCAL_RUN_DIR/docubrowser.pid" "$LOCAL_RUN_DIR/docubrowser-scan.pid" \
         "$LOCAL_LOG_DIR/docubrowser.log"; do
    [[ -e "$f" ]] && { echo "==> Removing $f"; rm -f "$f"; }
done

# ─── Remove system-mode runtime/log dirs ────────────────────────────────────
if [[ "$MODE" == "system" ]]; then
    for d in "/run/docubrowser" "/var/log/docubrowser"; do
        [[ -e "$d" ]] && { echo "==> Removing $d"; $SUDO rm -rf "$d"; }
    done
    if getent passwd "$SERVICE_USER" >/dev/null 2>&1 || getent group "$SERVICE_GROUP" >/dev/null 2>&1; then
        echo
        read -rp "Also remove the dedicated '$SERVICE_USER' system user/group? [y/N] " RM_USER
        case "$RM_USER" in
            [yY]|[yY][eE][sS])
                getent passwd "$SERVICE_USER" >/dev/null 2>&1 && { echo "==> Removing user '$SERVICE_USER'"; userdel "$SERVICE_USER" 2>/dev/null || true; }
                getent group "$SERVICE_GROUP" >/dev/null 2>&1 && { echo "==> Removing group '$SERVICE_GROUP'"; groupdel "$SERVICE_GROUP" 2>/dev/null || true; }
                ;;
            *) echo "Leaving '$SERVICE_USER' user/group in place." ;;
        esac
    fi
fi

echo
echo "==> Uninstall complete."
