#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Uninstall.command — Remove DocuBrowse FOSS (macOS install)
#
# Removes ~/Applications/DocuBrowse/ (including DocuBrowse.app) and the
# CLI wrappers in /usr/local/bin/ and ~/bin/.
# User data in ~/.docubrowser/ is PRESERVED.
#
# Double-click in Finder, or run from a terminal.
#
# NOTE: macOS ships bash 3.2 — keep this script bash-3 compatible.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

INSTALL_DIR="$HOME/Applications/DocuBrowse"

echo "==> DocuBrowse FOSS uninstaller"
echo "    Will remove: $INSTALL_DIR  (including DocuBrowse.app)"
echo "                 /usr/local/bin/docubrowser, /usr/local/bin/docuback"
echo "                 ~/bin/docubrowser, ~/bin/docuback"
echo
echo "    User data in ~/.docubrowser/ will be PRESERVED."
echo

if [[ ! -d "$INSTALL_DIR" ]]; then
    echo "DocuBrowse does not appear to be installed at $INSTALL_DIR"
fi

read -r -p "Proceed? [y/N] " _ans || _ans=""
case "$_ans" in y|Y|yes|Yes|YES) ;; *) echo "Aborted."; exit 0 ;; esac
echo

# ── Stop any running DocuBrowse processes ───────────────────────────────────
echo "==> Stopping any running DocuBrowse processes"
for pidfile in "$HOME/.local/run/docubrowser.pid" \
               "$HOME/.local/run/docubrowse_scan.pid" \
               /var/run/docubrowser/docubrowser.pid \
               /var/run/docubrowser/docubrowse_scan.pid; do
    if [[ -f "$pidfile" ]]; then
        kill "$(cat "$pidfile")" 2>/dev/null || true
        rm -f "$pidfile" 2>/dev/null || true
    fi
done

# ── Remove CLI wrappers ─────────────────────────────────────────────────────
# Only remove wrappers that actually point at DocuBrowse, and only ask for
# sudo if there is something in /usr/local/bin to remove.
echo "==> Removing CLI wrappers"
for name in docubrowser docuback; do
    f="/usr/local/bin/$name"
    if [[ -f "$f" ]] && grep -q "Applications/DocuBrowse" "$f" 2>/dev/null; then
        if [[ -w "$f" && -w /usr/local/bin ]]; then
            rm -f "$f"
        else
            sudo rm -f "$f" || echo "    WARNING: could not remove $f (sudo declined?)"
        fi
    fi
    f="$HOME/bin/$name"
    if [[ -f "$f" ]] && grep -q "Applications/DocuBrowse" "$f" 2>/dev/null; then
        rm -f "$f"
    fi
done

# ── Remove install directory (includes DocuBrowse.app) ──────────────────────
if [[ -d "$INSTALL_DIR" ]]; then
    echo "==> Removing $INSTALL_DIR"
    rm -rf "$INSTALL_DIR"
fi

echo
echo "DocuBrowse removed."
echo "User data in ~/.docubrowser/ was preserved."
echo "To remove all user data:  rm -rf ~/.docubrowser/"
echo
echo "You may now close this window."
