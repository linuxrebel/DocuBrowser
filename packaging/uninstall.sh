#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# uninstall.sh — Remove DocuBrowse FOSS (tarball install)
#
# Removes /opt/docubrowser/ and /usr/bin/ wrappers.
# User data in ~/.docubrowser/ is preserved.
#
# Usage:
#   sudo ./uninstall.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

INSTALL_DIR="/opt/docubrowser"

# ── Root check ──────────────────────────────────────────────────────────────
if [[ "$EUID" -ne 0 ]]; then
    echo "ERROR: This script must be run as root." >&2
    echo "       Use:  sudo ./uninstall.sh" >&2
    exit 1
fi

echo "==> DocuBrowse FOSS uninstaller"
echo "    Will remove: $INSTALL_DIR"
echo "                 /usr/bin/docubrowser"
echo "                 /usr/bin/docuback"
echo
echo "    User data in ~/.docubrowser/ will be PRESERVED."
echo

read -rp "Proceed? [y/N] " _ans || _ans=""
case "${_ans,,}" in y|yes) ;; *) echo "Aborted."; exit 0 ;; esac
echo

# ── Stop any running processes ──────────────────────────────────────────────
echo "==> Stopping any running DocuBrowse processes"
for pidfile in /var/run/docubrowser/docubrowse_scan.pid \
               /var/run/docubrowser/docubrowser.pid; do
    if [[ -f "$pidfile" ]] 2>/dev/null; then
        kill "$(cat "$pidfile")" 2>/dev/null || true
        rm -f "$pidfile"
    fi
done

# Also check user-local PID files for any logged-in users
for home_dir in /home/*; do
    for pidfile in "$home_dir/.local/run/docubrowser.pid" \
                   "$home_dir/.local/run/docubrowse_scan.pid"; do
        if [[ -f "$pidfile" ]] 2>/dev/null; then
            kill "$(cat "$pidfile")" 2>/dev/null || true
            rm -f "$pidfile"
        fi
    done
done

# ── Remove CLI wrappers ────────────────────────────────────────────────────
echo "==> Removing CLI wrappers"
rm -f /usr/bin/docubrowser /usr/bin/docuback

# ── Remove install directory ───────────────────────────────────────────────
if [[ -d "$INSTALL_DIR" ]]; then
    echo "==> Removing $INSTALL_DIR"
    rm -rf "$INSTALL_DIR"
fi

echo
echo "DocuBrowse removed."
echo "User data in ~/.docubrowser/ was preserved."
echo "To remove all user data:  rm -rf ~/.docubrowser/"
