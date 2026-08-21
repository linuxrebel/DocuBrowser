#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# install.sh — DocuBrowse FOSS tarball installer
#
# Installs to /opt/docubrowser/ with CLI wrappers in /usr/bin/.
# Must be run as root (sudo).  User data is stored per-user in
# ~/.docubrowser/ (created automatically on first run).
#
# Usage:
#   sudo ./install.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

INSTALL_DIR="/opt/docubrowser"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Root check ──────────────────────────────────────────────────────────────
if [[ "$EUID" -ne 0 ]]; then
    echo "ERROR: This installer must be run as root." >&2
    echo "       Use:  sudo ./install.sh" >&2
    exit 1
fi

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
        PROBLEMS+=("python3 'venv' module missing — install python3-venv.")
    python3 -c 'import ensurepip' >/dev/null 2>&1 || \
        PROBLEMS+=("python3 'ensurepip' missing — install python3-pip.")
fi

if ! command -v xdg-terminal-exec >/dev/null 2>&1; then
    PROBLEMS+=("xdg-terminal-exec is not installed (needed for desktop menu entry).")
fi

if [[ "${#PROBLEMS[@]}" -gt 0 ]]; then
    echo "ERROR: cannot proceed — please resolve the following first:" >&2
    echo >&2
    for p in "${PROBLEMS[@]}"; do
        echo "  - $p" >&2
    done
    echo >&2
    exit 1
fi

echo "==> DocuBrowse FOSS installer"
echo "    Install dir:  $INSTALL_DIR"
echo "    CLI wrappers: /usr/bin/docubrowser, /usr/bin/docuback"
echo "    User data:    ~/.docubrowser/ (per user, auto-created)"
echo

# ── Check for existing install ──────────────────────────────────────────────
if [[ -d "$INSTALL_DIR" ]]; then
    echo "WARNING: $INSTALL_DIR already exists."
    read -rp "Overwrite? [y/N] " _ans || _ans=""
    case "${_ans,,}" in y|yes) ;; *) echo "Aborted."; exit 0 ;; esac
    echo
fi

# ── Deploy application files ───────────────────────────────────────────────
echo "==> Deploying application files to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/icons"
mkdir -p "$INSTALL_DIR/EndUser_docs"

# Copy all app files from the tarball directory
APP_FILES=(
    docubrowser.py doc_search.py scan_docs.py embed_docs.py
    pdf_extractor.py docx_extractor.py pptx_extractor.py xlsx_extractor.py
    odf_extractor.py ebook_extractor.py visio_extractor.py markup_extractor.py
    eml_extractor.py csv_extractor.py rtf_extractor.py djvu_extractor.py
    hardware_utils.py docubrowse_db.py purge_pii.py
    backup_restore.py ensure_ollama.py dup_detect.py platform_paths.py
    index.html settings.html
    requirements.txt du-docs.db.example
    README.md LICENSE INSTALL.md
)

for f in "${APP_FILES[@]}"; do
    if [[ -f "$SRC_DIR/$f" ]]; then
        install -m 644 "$SRC_DIR/$f" "$INSTALL_DIR/"
    fi
done

# Make backup_restore.py executable
chmod 755 "$INSTALL_DIR/backup_restore.py"

# Icons
if [[ -d "$SRC_DIR/icons" ]]; then
    install -m 644 "$SRC_DIR"/icons/* "$INSTALL_DIR/icons/"
fi

# Documentation
if [[ -d "$SRC_DIR/EndUser_docs" ]]; then
    for f in "$SRC_DIR"/EndUser_docs/*; do
        [[ -f "$f" ]] && install -m 644 "$f" "$INSTALL_DIR/EndUser_docs/"
    done
fi

# ── Create virtualenv + install dependencies ───────────────────────────────
echo "==> Creating Python virtualenv at $INSTALL_DIR/venv/"
python3 -m venv "$INSTALL_DIR/venv"

echo "==> Installing Python dependencies"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q
echo "    Done."

# ── CLI wrapper scripts ────────────────────────────────────────────────────
echo "==> Installing CLI wrappers"

cat > /usr/bin/docubrowser <<'WRAPPER'
#!/usr/bin/env bash
# DocuBrowse CLI wrapper — installed by DocuBrowse tarball installer
exec /opt/docubrowser/venv/bin/python3 /opt/docubrowser/docubrowser.py "$@"
WRAPPER
chmod 755 /usr/bin/docubrowser

cat > /usr/bin/docuback <<'WRAPPER'
#!/usr/bin/env bash
# DocuBrowse backup/restore wrapper — installed by DocuBrowse tarball installer
exec /opt/docubrowser/venv/bin/python3 /opt/docubrowser/backup_restore.py "$@"
WRAPPER
chmod 755 /usr/bin/docuback

# ── Desktop menu entry ─────────────────────────────────────────────────────
if [[ -f "$SRC_DIR/docubrowser.desktop" ]]; then
    echo "==> Installing desktop menu entry"
    install -d -m 755 /usr/share/applications
    install -m 644 "$SRC_DIR/docubrowser.desktop" /usr/share/applications/
fi

# ── Create backup directory ────────────────────────────────────────────────
mkdir -p "$INSTALL_DIR/backups"

# ── Done ───────────────────────────────────────────────────────────────────
echo
echo "══════════════════════════════════════════════════════════════"
echo "  DocuBrowse FOSS installed"
echo "══════════════════════════════════════════════════════════════"
echo
echo "  Runtime data will be stored in ~/.docubrowser/ per user."
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
echo "    Ollama   — https://ollama.com  (required for AI features)"
echo "    Calibre  — dnf/apt install calibre  (optional, for e-books)"
echo
echo "  To uninstall:  sudo ./uninstall.sh"
echo "                 or:  sudo /opt/docubrowser/uninstall.sh"
echo
