#!/usr/bin/env bash
#
# install.sh — DocuBrowse installer
#
# Usage:
#   ./install.sh              # install
#
# Two cleanly-separated modes:
#   - Run as a normal user  -> USER install under $HOME/.docubrowse,
#                              CLI wrapper in ~/.local/bin, started directly
#                              by `docubrowser start` (NO systemd, NO root).
#   - Run as root (sudo)    -> SYSTEM install under /opt/docubrowse, running
#                              as a dedicated 'docubrowse' system user, managed
#                              by a systemd unit (installed, not auto-enabled),
#                              CLI wrapper in /usr/local/bin.
#
set -euo pipefail

# ─── Resolve source directory (where this script + app files live) ──────────
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─── Detect install mode ───────────────────────────────────────────────────-
if [[ "$EUID" -eq 0 ]]; then
    MODE="system"
    INSTALL_DIR="/opt/docubrowse"
    SERVICE_USER="docubrowse"
    SERVICE_GROUP="docubrowse"
    BIN_DIR="/usr/local/bin"
    BIN_LINK="$BIN_DIR/docubrowser"
    UNIT_PATH="/etc/systemd/system/docubrowser.service"
else
    MODE="user"
    INSTALL_DIR="$HOME/.docubrowse"
    SERVICE_USER="$(id -un)"
    SERVICE_GROUP="$(id -gn)"
    BIN_DIR="$HOME/.local/bin"
    BIN_LINK="$BIN_DIR/docubrowser"
    UNIT_PATH=""   # user installs do NOT use systemd
fi

VENV_DIR="$INSTALL_DIR/venv"
LOCAL_RUN_DIR="$HOME/.local/run"
LOCAL_LOG_DIR="$HOME/.local/var/log"

echo "==> DocuBrowse installer"
echo "    Mode:         $MODE"
echo "    Install dir:  $INSTALL_DIR"
echo "    CLI wrapper:  $BIN_LINK"
if [[ "$MODE" == "system" ]]; then
    echo "    Service user: $SERVICE_USER"
    echo "    systemd unit: $UNIT_PATH"
else
    echo "    Service:      none (run with 'docubrowser start')"
fi
echo

if [[ "$MODE" == "system" ]]; then
    echo "*** Running as root: DocuBrowse will be installed SYSTEM-WIDE at $INSTALL_DIR,"
    echo "*** running as the dedicated '$SERVICE_USER' user, managed by systemd. ***"
    echo
fi

# ─── Pre-flight: verify ALL required tools/libraries up front ───────────────
# Collect every problem first and report them together, before we create or
# modify anything — so a missing tool can never leave a half-finished install.
PROBLEMS=()

# Python 3.9+ (is_relative_to, modern typing, etc.)
PY_MIN_MAJOR=3
PY_MIN_MINOR=9
if ! command -v python3 >/dev/null 2>&1; then
    PROBLEMS+=("python3 is not installed (need >= ${PY_MIN_MAJOR}.${PY_MIN_MINOR}).")
else
    if ! python3 - "$PY_MIN_MAJOR" "$PY_MIN_MINOR" <<'PYEOF' 2>/dev/null
import sys
need = (int(sys.argv[1]), int(sys.argv[2]))
sys.exit(0 if sys.version_info[:2] >= need else 1)
PYEOF
    then
        have="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo '?')"
        PROBLEMS+=("python3 is too old (have $have, need >= ${PY_MIN_MAJOR}.${PY_MIN_MINOR}).")
    fi
    python3 -c 'import venv' >/dev/null 2>&1 || \
        PROBLEMS+=("python3 'venv' module missing — install your distro's python3-venv package.")
    python3 -c 'import ensurepip' >/dev/null 2>&1 || \
        PROBLEMS+=("python3 'ensurepip' missing — install python3-venv / python3-pip.")
fi

# Generic CLI tools the installer itself uses.
for tool in rsync curl tar; do
    command -v "$tool" >/dev/null 2>&1 || \
        PROBLEMS+=("$tool is not installed (required by the installer).")
done

# System-mode-only tools.
if [[ "$MODE" == "system" ]]; then
    for tool in getent useradd groupadd systemctl; do
        command -v "$tool" >/dev/null 2>&1 || \
            PROBLEMS+=("$tool is not installed (required for a system-wide install).")
    done
fi

# External runtime dependencies.
if ! command -v calibre >/dev/null 2>&1; then
    PROBLEMS+=("Calibre is not installed (ebook-meta/ebook-convert for ebook indexing).
      Install via your distro, e.g.:
        sudo dnf install calibre        # Fedora / RHEL
        sudo apt install calibre        # Debian / Ubuntu
      If your distro does not package Calibre (e.g. CentOS Stream), use the
      official installer: https://calibre-ebook.com/download_linux")
fi

if ! command -v ollama >/dev/null 2>&1; then
    PROBLEMS+=("Ollama is not installed (local AI models for semantic search + synopsis).
      Install with:
        curl -fsSL https://ollama.com/install.sh | sh
      The required models (nomic-embed-text, dolphin3) are pulled automatically
      the first time you run 'docubrowser start'. Note: dolphin3 is ~4.9 GB, so
      that first pull can take several minutes depending on your connection.")
fi

if [[ "${#PROBLEMS[@]}" -gt 0 ]]; then
    echo "ERROR: cannot proceed — please resolve the following first:" >&2
    echo >&2
    for p in "${PROBLEMS[@]}"; do
        echo "  • $p" >&2
    done
    echo >&2
    echo "Nothing has been installed or modified. Re-run ./install.sh once these are fixed." >&2
    exit 1
fi

echo "==> Pre-flight checks passed."
echo

# ─── Refuse to clobber an existing install ──────────────────────────────────
if [[ -e "$INSTALL_DIR" ]]; then
    echo "ERROR: $INSTALL_DIR already exists." >&2
    echo "Run ./uninstall.sh first (it cleans the install dir, CLI wrapper, and any" >&2
    echo "systemd unit), then re-run this installer." >&2
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

# ─── Deploy application files ───────────────────────────────────────────────
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
    --exclude 'dist/' \
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

# ─── Write a fresh docubrowse.config for this install ───────────────────────
echo "==> Writing $INSTALL_DIR/docubrowse.config"
cat > "$INSTALL_DIR/docubrowse.config" <<EOF
# docubrowse.config — generated by install.sh on $(date -Iseconds)
# Set doc_dir below to a directory readable by the '$SERVICE_USER' user,
# or configure it later via the web UI (Settings / gear icon).
# doc_dir  = /folder/to/be/scanned
work_dir = $INSTALL_DIR
port     = 8643
EOF

# ─── Create venv + install Python dependencies ──────────────────────────────
echo "==> Creating virtualenv at $VENV_DIR"
python3 -m venv "$VENV_DIR"

echo "==> Installing Python dependencies"
"$VENV_DIR/bin/pip" install --upgrade pip
if [[ -f "$INSTALL_DIR/requirements.txt" ]]; then
    "$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
else
    "$VENV_DIR/bin/pip" install pdfplumber pypdf python-docx python-pptx \
        openpyxl ebooklib beautifulsoup4 mobi numpy
fi

# ─── Install the CLI wrapper ────────────────────────────────────────────────
echo "==> Installing CLI wrapper at $BIN_LINK"
mkdir -p "$BIN_DIR"
cat > "$BIN_LINK" <<EOF4
#!/usr/bin/env bash
# DocuBrowse CLI wrapper — generated by install.sh
exec "$VENV_DIR/bin/python3" "$INSTALL_DIR/docubrowser.py" "\$@"
EOF4
chmod 755 "$BIN_LINK"

# ─── Ownership (system mode) ────────────────────────────────────────────────
if [[ "$MODE" == "system" ]]; then
    echo "==> Setting ownership of $INSTALL_DIR to $SERVICE_USER:$SERVICE_GROUP"
    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"
fi

# ─── systemd unit (SYSTEM mode only) ────────────────────────────────────────
if [[ "$MODE" == "system" ]]; then
    echo "==> Installing systemd unit at $UNIT_PATH"
    cat > "$UNIT_PATH" <<EOF
[Unit]
Description=DocuBrowse search server
After=network.target ollama.service
Wants=ollama.service

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python3 $INSTALL_DIR/doc_search.py $INSTALL_DIR/du-docs.db 8643

# Runtime + log dirs managed by systemd (rooted at /run and /var/log).
RuntimeDirectory=docubrowser
RuntimeDirectoryMode=0750
LogsDirectory=docubrowser
LogsDirectoryMode=0750
StandardOutput=append:/var/log/docubrowser/docubrowser.log
StandardError=append:/var/log/docubrowser/docubrowser.log

Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    echo "==> Reloading systemd (unit installed but NOT enabled — no autostart)"
    systemctl daemon-reload
fi

# ─── Create user-mode runtime/log dirs ──────────────────────────────────────
if [[ "$MODE" == "user" ]]; then
    echo "==> Creating $LOCAL_RUN_DIR and $LOCAL_LOG_DIR"
    mkdir -p "$LOCAL_RUN_DIR" "$LOCAL_LOG_DIR"
fi

# ─── Done ───────────────────────────────────────────────────────────────────
echo
echo "==> Install complete."
echo
echo "Installed to:   $INSTALL_DIR"
echo "Config file:    $INSTALL_DIR/docubrowse.config"
echo "CLI wrapper:    $BIN_LINK"

if [[ "$MODE" == "system" ]]; then
    echo "systemd unit:   $UNIT_PATH (installed, NOT enabled — no autostart)"
    echo "Logs:           /var/log/docubrowser/docubrowser.log"
    echo "PID file:       /run/docubrowser/docubrowser.pid"
    echo
    echo "Next steps:"
    echo "  systemctl start docubrowser      # start the server"
    echo "  docubrowser status               # check status / index stats"
    echo "  docubrowser rescan               # index your documents (after configuring doc_dir)"
    echo "  systemctl stop docubrowser       # stop the server"
else
    echo "Logs:           $LOCAL_LOG_DIR/docubrowser.log"
    echo "PID file:       $LOCAL_RUN_DIR/docubrowser.pid"
    echo
    case ":$PATH:" in
        *":$BIN_DIR:"*) : ;;
        *) echo "NOTE: $BIN_DIR is not on your PATH. Add it, e.g.:"
           echo "      echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
           echo ;;
    esac
    echo "Next steps:"
    echo "  docubrowser start                                  # start the server (runs as you)"
    echo "  docubrowser status                                 # check status / index stats"
    echo "  docubrowser scan --doc-dir /folder/to/be/scanned   # index your documents"
    echo "  docubrowser stop                                   # stop the server"
fi

echo
echo "NOTE: No document directory is configured yet. Open the web UI"
echo "      (http://localhost:8643) and click the Settings (gear) icon to set"
echo "      one, or pass --doc-dir to 'docubrowser scan'."
echo
echo "On first start, DocuBrowse pulls the required Ollama models"
echo "(nomic-embed-text, dolphin3 ~4.9 GB) if not already present — the dolphin3"
echo "download can take several minutes the first time."
