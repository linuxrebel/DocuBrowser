#!/usr/bin/env bash
#
# install.sh — DocuBrowse installer
#
# Usage:
#   ./install.sh              # install
#
# Behavior:
#   - Run as a normal user  -> installs to $HOME/.docubrowse
#   - Run as root (sudo)    -> installs system-wide to /opt/docubrowse,
#                               under a dedicated 'docubrowse' system user
#
# In both modes a systemd unit is installed and daemon-reload'd so that
# `systemctl start/stop docubrowser` works. The unit is NOT enabled, so
# it will not start automatically at boot.
#
set -euo pipefail

# ─── Resolve source directory (where this script + app files live) ──────────
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─── Detect install mode ──────────────────────────────────────────────────--
if [[ "$EUID" -eq 0 ]]; then
    MODE="system"
    INSTALL_DIR="/opt/docubrowse"
    SERVICE_USER="docubrowse"
    SERVICE_GROUP="docubrowse"
    BIN_LINK="/usr/local/bin/docubrowse"
    UNIT_PATH="/etc/systemd/system/docubrowser.service"
    RUN_AS_ROOT=true
    SUDO=""
else
    MODE="user"
    INSTALL_DIR="$HOME/.docubrowse"
    SERVICE_USER="$(id -un)"
    SERVICE_GROUP="$(id -gn)"
    BIN_LINK="/usr/local/bin/docubrowse"
    UNIT_PATH="/etc/systemd/system/docubrowser.service"
    RUN_AS_ROOT=false
    # systemd registration needs root even for a user-mode install;
    # we shell out to sudo for just those steps.
    SUDO="sudo"
fi

VENV_DIR="$INSTALL_DIR/venv"
LOCAL_RUN_DIR="$HOME/.local/run"
LOCAL_LOG_DIR="$HOME/.local/var/log"

echo "==> DocuBrowse installer"
echo "    Mode:        $MODE"
echo "    Install dir: $INSTALL_DIR"
echo "    Service user: $SERVICE_USER"
echo

if [[ "$MODE" == "system" ]]; then
    echo "*** Running as root: DocuBrowse will be installed SYSTEM-WIDE at $INSTALL_DIR,"
    echo "*** running as the dedicated '$SERVICE_USER' user. ***"
    echo
fi

# ─── Refuse to clobber an existing install ──────────────────────────────────
if [[ -e "$INSTALL_DIR" ]]; then
    echo "ERROR: $INSTALL_DIR already exists." >&2
    echo "This installer only supports a fresh install. Remove or rename the" >&2
    echo "existing directory (and stop/remove its systemd unit) before re-running." >&2
    exit 1
fi

# ─── Check external dependencies (Calibre, Ollama) ──────────────────────────
MISSING_DEPS=0

if ! command -v calibre >/dev/null 2>&1; then
    echo "MISSING: Calibre (provides 'ebook-meta' / 'ebook-convert', needed for ebook indexing)."
    echo "  Install via your distro's package manager, e.g.:"
    echo "    sudo dnf install calibre      # Fedora / RHEL"
    echo "    sudo apt install calibre      # Debian / Ubuntu"
    echo
    MISSING_DEPS=1
fi

if ! command -v ollama >/dev/null 2>&1; then
    echo "MISSING: Ollama (provides local AI models for semantic search + synopsis)."
    echo "  Install with:"
    echo "    curl -fsSL https://ollama.com/install.sh | sh"
    echo
    echo "  After installing Ollama, DocuBrowse will pull the required models"
    echo "  (nomic-embed-text, dolphin3) automatically the first time you run"
    echo "  'docubrowse start'."
    echo
    MISSING_DEPS=1
fi

if [[ "$MISSING_DEPS" -eq 1 ]]; then
    echo "ERROR: Please install the missing dependencies above, then re-run this installer." >&2
    exit 1
fi

# ─── Check python3 ────────────────────────────────────────────────────────--
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is required but not found." >&2
    exit 1
fi

# ─── Create dedicated service user (system mode only) ───────────────────────
if [[ "$MODE" == "system" ]]; then
    if ! getent group "$SERVICE_GROUP" >/dev/null 2>&1; then
        echo "==> Creating system group '$SERVICE_GROUP'"
        groupadd --system "$SERVICE_GROUP"
    fi
    if ! getent passwd "$SERVICE_USER" >/dev/null 2>&1; then
        echo "==> Creating system user '$SERVICE_USER'"
        useradd --system --no-create-home --gid "$SERVICE_GROUP" \
            --shell /usr/sbin/nologin "$SERVICE_USER"
    fi
fi

# ─── Deploy application files ────────────────────────────────────────────--
echo "==> Deploying application files to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

rsync -a \
    --exclude '.git/' \
    --exclude '.gitignore' \
    --exclude '.claude/' \
    --exclude '.playwright-mcp/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude 'data_grooming/' \
    --exclude 'screenshots/' \
    --exclude 'status_docs/' \
    --exclude 'test_pdfs_live/' \
    --exclude 'test_*.py' \
    --exclude 'test_*.html' \
    --exclude 'generate_test_pdfs.py' \
    --exclude 'populate_db.py' \
    --exclude 'setup_*.py' \
    --exclude 'phase3_*' \
    --exclude 'settings_full.png' \
    --exclude 'systemd/' \
    --exclude 'install.sh' \
    --exclude 'uninstall.sh' \
    --exclude 'du-docs.db' \
    --exclude 'docubrowse.config' \
    "$SRC_DIR"/ "$INSTALL_DIR"/

# ─── Initialize database from the empty example schema ──────────────────────
if [[ -f "$INSTALL_DIR/du-docs.db.example" ]]; then
    echo "==> Initializing database from du-docs.db.example"
    cp "$INSTALL_DIR/du-docs.db.example" "$INSTALL_DIR/du-docs.db"
fi

# ─── Write a fresh docubrowse.config for this install ────────────────────────
echo "==> Writing $INSTALL_DIR/docubrowse.config"

# No default doc_dir — the app treats "unset" as a valid state and will
# prompt (via the web UI) for the user to configure one via Settings (gear
# icon), which must point to a directory readable by '$SERVICE_USER'.
cat > "$INSTALL_DIR/docubrowse.config" <<EOF
# docubrowse.config — generated by install.sh on $(date -Iseconds)
# Set doc_dir below to a directory readable by the '$SERVICE_USER' user,
# or configure it later via the web UI (Settings / gear icon).
# doc_dir  = /path/to/your/documents
work_dir = $INSTALL_DIR
port     = 8643
EOF

# ─── Create venv + install Python dependencies ───────────────────────────--
echo "==> Creating virtualenv at $VENV_DIR"
python3 -m venv "$VENV_DIR"

echo "==> Installing Python dependencies"
"$VENV_DIR/bin/pip" install --upgrade pip
if [[ -f "$INSTALL_DIR/requirements.txt" ]]; then
    "$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
else
    # Fallback if requirements.txt is somehow missing.
    "$VENV_DIR/bin/pip" install pdfplumber pypdf python-docx python-pptx \
        openpyxl ebooklib beautifulsoup4 mobi numpy
fi

# ─── Ownership (system mode) ────────────────────────────────────────────--
if [[ "$MODE" == "system" ]]; then
    echo "==> Setting ownership of $INSTALL_DIR to $SERVICE_USER:$SERVICE_GROUP"
    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"
fi

# ─── Create local run/log dirs (user mode) ──────────────────────────────--
if [[ "$MODE" == "user" ]]; then
    echo "==> Creating $LOCAL_RUN_DIR and $LOCAL_LOG_DIR"
    mkdir -p "$LOCAL_RUN_DIR" "$LOCAL_LOG_DIR"
fi

# ─── Generate systemd unit ────────────────────────────────────────────────--
echo "==> Generating systemd unit"

UNIT_TMP="$(mktemp)"

{
    echo "[Unit]"
    echo "Description=DocuBrowse search server"
    echo "After=network.target ollama.service"
    echo "Wants=ollama.service"
    echo
    echo "[Service]"
    echo "Type=simple"
    echo "User=$SERVICE_USER"
    echo "Group=$SERVICE_GROUP"
    echo "WorkingDirectory=$INSTALL_DIR"
    echo "ExecStart=$VENV_DIR/bin/python3 $INSTALL_DIR/doc_search.py $INSTALL_DIR/du-docs.db 8643"
    echo

    if [[ "$MODE" == "system" ]]; then
        cat <<'EOF2'
# Creates /run/docubrowser, used for docubrowser.pid by
# docubrowser.py's _pick_runtime_path()
RuntimeDirectory=docubrowser
RuntimeDirectoryMode=0750

# Creates /var/log/docubrowser for docubrowser.log
LogsDirectory=docubrowser
LogsDirectoryMode=0750

StandardOutput=append:/var/log/docubrowser/docubrowser.log
StandardError=append:/var/log/docubrowser/docubrowser.log
EOF2
    else
        # User-mode install: pid/log live under $HOME/.local (see
        # docubrowser.py _pick_runtime_path fallback paths). systemd
        # cannot use RuntimeDirectory/LogsDirectory here since those are
        # rooted at /run and /var/log.
        echo "StandardOutput=append:$LOCAL_LOG_DIR/docubrowser.log"
        echo "StandardError=append:$LOCAL_LOG_DIR/docubrowser.log"
    fi

    cat <<'EOF3'

Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF3
} > "$UNIT_TMP"

echo "==> Installing unit to $UNIT_PATH (requires root)"
$SUDO cp "$UNIT_TMP" "$UNIT_PATH"
rm -f "$UNIT_TMP"

echo "==> Reloading systemd (unit installed but NOT enabled — no autostart)"
$SUDO systemctl daemon-reload

# ─── Install CLI wrapper ──────────────────────────────────────────────────--
echo "==> Installing CLI wrapper at $BIN_LINK"

WRAPPER_TMP="$(mktemp)"
cat > "$WRAPPER_TMP" <<EOF4
#!/usr/bin/env bash
# DocuBrowse CLI wrapper — generated by install.sh
exec "$VENV_DIR/bin/python3" "$INSTALL_DIR/docubrowser.py" "\$@"
EOF4
chmod +x "$WRAPPER_TMP"
$SUDO cp "$WRAPPER_TMP" "$BIN_LINK"
rm -f "$WRAPPER_TMP"

# ─── Done ──────────────────────────────────────────────────────────────────
echo
echo "==> Install complete."
echo
echo "Installed to:   $INSTALL_DIR"
echo "Config file:    $INSTALL_DIR/docubrowse.config"
echo "CLI wrapper:    $BIN_LINK"
echo "systemd unit:   $UNIT_PATH (installed, NOT enabled — no autostart)"
if [[ "$MODE" == "system" ]]; then
    echo "Logs:           /var/log/docubrowser/docubrowser.log"
    echo "PID file:       /run/docubrowser/docubrowser.pid"
else
    echo "Logs:           $LOCAL_LOG_DIR/docubrowser.log"
    echo "PID file:       $LOCAL_RUN_DIR/docubrowser.pid"
    echo
    echo "NOTE: log rotation for $LOCAL_LOG_DIR/docubrowser.log is not yet"
    echo "      configured — this is a known follow-up item."
fi
echo
echo "NOTE: No document directory is configured yet. Open the web UI and"
echo "      click the Settings (gear) icon to set one before scanning."
echo
echo "Next steps:"
echo "  systemctl start docubrowser     # start the server"
echo "  docubrowse status                # check status / index stats"
echo "  docubrowse rescan                # index your documents (after configuring doc_dir)"
echo "  systemctl stop docubrowser       # stop the server"
echo
echo "On first 'start', DocuBrowse will pull the required Ollama models"
echo "(nomic-embed-text, dolphin3) if not already present."
