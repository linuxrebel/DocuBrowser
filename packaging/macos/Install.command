#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Install.command — DocuBrowse FOSS macOS installer
#
# Double-click in Finder (or run from a terminal).  Installs to
# ~/Applications/DocuBrowse/ with a Python virtualenv — no sudo needed for
# the app itself; sudo is only requested for the optional /usr/local/bin
# CLI commands (falls back to ~/bin/ if declined).
#
# User data is stored per-user in ~/.docubrowser/ (created on first run).
#
# NOTE: macOS ships bash 3.2 — keep this script bash-3 compatible
# (no ${var,,}, no associative arrays).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_SRC="$SRC_DIR/app"
INSTALL_DIR="$HOME/Applications/DocuBrowse"
APP_BUNDLE="$INSTALL_DIR/DocuBrowse.app"

if [[ ! -d "$APP_SRC" ]]; then
    echo "ERROR: app/ folder not found next to this installer." >&2
    echo "       Run Install.command from the mounted DocuBrowse dmg." >&2
    exit 1
fi

VERSION="$(sed -n -E 's/^VERSION *= *["'\'']([0-9.]+).*/\1/p' "$APP_SRC/docubrowser.py" | head -1)"
[[ -n "$VERSION" ]] || VERSION="unknown"

# ── Pre-flight ──────────────────────────────────────────────────────────────
PROBLEMS=()

if ! command -v python3 >/dev/null 2>&1; then
    PROBLEMS+=("python3 is not installed (need >= 3.9).")
else
    if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' 2>/dev/null; then
        have="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo '?')"
        PROBLEMS+=("python3 is too old (have $have, need >= 3.9).")
    fi
    python3 -c 'import venv' >/dev/null 2>&1 || \
        PROBLEMS+=("python3 'venv' module missing.")
    python3 -c 'import ensurepip' >/dev/null 2>&1 || \
        PROBLEMS+=("python3 'ensurepip' missing.")
fi

if [[ "${#PROBLEMS[@]}" -gt 0 ]]; then
    echo "ERROR: cannot proceed — please resolve the following first:" >&2
    echo >&2
    for p in "${PROBLEMS[@]}"; do
        echo "  - $p" >&2
    done
    echo >&2
    echo "  Python for macOS: https://www.python.org/downloads/" >&2
    echo >&2
    exit 1
fi

echo "══════════════════════════════════════════════════════════════"
echo "  DocuBrowse FOSS $VERSION — macOS installer"
echo "══════════════════════════════════════════════════════════════"
echo
echo "  Install dir:  $INSTALL_DIR"
echo "  App bundle:   $APP_BUNDLE"
echo "  CLI commands: docubrowser, docuback"
echo "  User data:    ~/.docubrowser/ (auto-created on first run)"
echo

# ── Check for existing install ──────────────────────────────────────────────
if [[ -d "$INSTALL_DIR" ]]; then
    echo "WARNING: $INSTALL_DIR already exists."
    read -r -p "Overwrite? [y/N] " _ans || _ans=""
    case "$_ans" in y|Y|yes|Yes|YES) ;; *) echo "Aborted."; exit 0 ;; esac
    echo
    # Best-effort: stop a running server/scan from the old install so the
    # fresh code is actually what ends up serving.
    if [[ -x "$INSTALL_DIR/venv/bin/python3" && -f "$INSTALL_DIR/docubrowser.py" ]]; then
        "$INSTALL_DIR/venv/bin/python3" "$INSTALL_DIR/docubrowser.py" stopall >/dev/null 2>&1 || true
    fi
fi

# ── Deploy application files ────────────────────────────────────────────────
echo "==> Deploying application files to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp -R "$APP_SRC/." "$INSTALL_DIR/"
chmod 755 "$INSTALL_DIR/backup_restore.py"

# Keep a copy of the uninstaller so it's available after the dmg is ejected.
install -m 755 "$SRC_DIR/Uninstall.command" "$INSTALL_DIR/"

# ── Create virtualenv + install dependencies ────────────────────────────────
echo "==> Creating Python virtualenv at $INSTALL_DIR/venv/"
rm -rf "$INSTALL_DIR/venv"
python3 -m venv "$INSTALL_DIR/venv"

echo "==> Installing Python dependencies (may take a minute)"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q
echo "    Done."

# ── CLI wrapper scripts ─────────────────────────────────────────────────────
WRAP_TMP="$(mktemp -d)"
trap 'rm -rf "$WRAP_TMP"' EXIT

cat > "$WRAP_TMP/docubrowser" <<'WRAPPER'
#!/bin/bash
# DocuBrowse CLI wrapper — installed by the DocuBrowse macOS installer
exec "$HOME/Applications/DocuBrowse/venv/bin/python3" "$HOME/Applications/DocuBrowse/docubrowser.py" "$@"
WRAPPER

cat > "$WRAP_TMP/docuback" <<'WRAPPER'
#!/bin/bash
# DocuBrowse backup/restore wrapper — installed by the DocuBrowse macOS installer
exec "$HOME/Applications/DocuBrowse/venv/bin/python3" "$HOME/Applications/DocuBrowse/backup_restore.py" "$@"
WRAPPER

chmod 755 "$WRAP_TMP/docubrowser" "$WRAP_TMP/docuback"

echo
echo "The 'docubrowser' and 'docuback' commands can be installed to"
echo "/usr/local/bin (requires your admin password) or to ~/bin (no sudo)."
read -r -p "Install CLI commands to /usr/local/bin with sudo? [Y/n] " _ans || _ans=""

BIN_DIR="/usr/local/bin"
PATH_NOTE=""
case "$_ans" in
    n|N|no|No|NO) BIN_DIR="$HOME/bin" ;;
esac

if [[ "$BIN_DIR" == "/usr/local/bin" ]]; then
    if sudo mkdir -p /usr/local/bin && \
       sudo install -m 755 "$WRAP_TMP/docubrowser" /usr/local/bin/docubrowser && \
       sudo install -m 755 "$WRAP_TMP/docuback"    /usr/local/bin/docuback; then
        echo "==> CLI commands installed to /usr/local/bin"
    else
        echo "    sudo failed — falling back to ~/bin"
        BIN_DIR="$HOME/bin"
    fi
fi

if [[ "$BIN_DIR" == "$HOME/bin" ]]; then
    mkdir -p "$HOME/bin"
    install -m 755 "$WRAP_TMP/docubrowser" "$HOME/bin/docubrowser"
    install -m 755 "$WRAP_TMP/docuback"    "$HOME/bin/docuback"
    echo "==> CLI commands installed to ~/bin"
    case ":$PATH:" in
        *":$HOME/bin:"*) ;;
        *) PATH_NOTE="yes" ;;
    esac
fi

# ── macOS .app bundle ───────────────────────────────────────────────────────
echo "==> Creating app bundle at $APP_BUNDLE"
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS" "$APP_BUNDLE/Contents/Resources"

# Launcher: opens Terminal and runs "start" then "open".  The command string
# is passed to osascript as an argument so no AppleScript quote-escaping of
# the path is needed.
cat > "$APP_BUNDLE/Contents/MacOS/DocuBrowse" <<'LAUNCHER'
#!/bin/bash
DB_DIR="$HOME/Applications/DocuBrowse"
DB_CMD="\"$DB_DIR/venv/bin/python3\" \"$DB_DIR/docubrowser.py\""
osascript \
    -e 'on run argv' \
    -e 'tell application "Terminal"' \
    -e '    activate' \
    -e '    do script (item 1 of argv)' \
    -e 'end tell' \
    -e 'end run' \
    "$DB_CMD start && $DB_CMD open"
LAUNCHER
chmod 755 "$APP_BUNDLE/Contents/MacOS/DocuBrowse"

cat > "$APP_BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>            <string>DocuBrowse</string>
    <key>CFBundleDisplayName</key>     <string>DocuBrowse</string>
    <key>CFBundleIdentifier</key>      <string>org.docubrowse.foss</string>
    <key>CFBundleVersion</key>         <string>${VERSION}</string>
    <key>CFBundleShortVersionString</key> <string>${VERSION}</string>
    <key>CFBundleExecutable</key>      <string>DocuBrowse</string>
    <key>CFBundleIconFile</key>        <string>DocuBrowse</string>
    <key>CFBundlePackageType</key>     <string>APPL</string>
</dict>
</plist>
PLIST

# Icon: convert icons/icon-512.png to .icns with sips + iconutil (macOS built-ins).
SRC_ICON="$INSTALL_DIR/icons/icon-512.png"
if [[ -f "$SRC_ICON" ]] && command -v sips >/dev/null 2>&1 && command -v iconutil >/dev/null 2>&1; then
    ICONSET="$WRAP_TMP/DocuBrowse.iconset"
    mkdir -p "$ICONSET"
    for spec in \
        "icon_16x16.png 16"      "icon_16x16@2x.png 32" \
        "icon_32x32.png 32"      "icon_32x32@2x.png 64" \
        "icon_128x128.png 128"   "icon_128x128@2x.png 256" \
        "icon_256x256.png 256"   "icon_256x256@2x.png 512" \
        "icon_512x512.png 512"
    do
        icon_name="${spec%% *}"
        icon_size="${spec##* }"
        sips -z "$icon_size" "$icon_size" "$SRC_ICON" --out "$ICONSET/$icon_name" >/dev/null || true
    done
    # Icon is cosmetic — a conversion failure must not abort a completed install.
    if iconutil -c icns "$ICONSET" -o "$APP_BUNDLE/Contents/Resources/DocuBrowse.icns" 2>/dev/null; then
        touch "$APP_BUNDLE"   # nudge Finder to refresh the icon
    else
        echo "    WARNING: icon conversion failed — app bundle will use the generic icon."
    fi
else
    echo "    WARNING: icon-512.png or sips/iconutil missing — app bundle will use the generic icon."
fi

# ── Done ────────────────────────────────────────────────────────────────────
echo
echo "══════════════════════════════════════════════════════════════"
echo "  DocuBrowse FOSS $VERSION installed"
echo "══════════════════════════════════════════════════════════════"
echo
echo "  Runtime data will be stored in ~/.docubrowser/"
echo
echo "  First run:  open a terminal and index your documents once:"
echo "    docubrowser rescan --doc-dir /path/to/your/documents"
echo
echo "  Then launch:  double-click DocuBrowse in ~/Applications/DocuBrowse/"
echo "                (starts the server and opens the web UI in Terminal)"
echo "  macOS will ask once to allow DocuBrowse to control Terminal —"
echo "  click Allow, or the launcher will silently do nothing."
echo
echo "  Commands:"
echo "    docubrowser start          Start the web server"
echo "    docubrowser stop           Stop the server"
echo "    docubrowser status         Show status and stats"
echo "    docubrowser rescan         Scan and index documents"
echo "    docuback --backup          Back up runtime data"
echo "    docuback --restore         Restore from backup"
echo
echo "  Web UI:  http://localhost:8643"
echo
echo "  Prerequisites (install separately):"
echo "    Ollama   — https://ollama.com  (required for AI features;"
echo "               'docubrowser start' pulls the models automatically)"
echo "    Calibre  — https://calibre-ebook.com  (optional, for e-books)"
echo
if [[ -n "$PATH_NOTE" ]]; then
    echo "  NOTE: ~/bin is not in your PATH.  Add it with:"
    echo "    echo 'export PATH=\"\$HOME/bin:\$PATH\"' >> ~/.zprofile"
    echo "  then open a new terminal."
    echo
fi
echo "  To uninstall:  double-click Uninstall.command (on this dmg, or in"
echo "                 $INSTALL_DIR)"
echo
