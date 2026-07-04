Name:           docubrowser-foss
Version:        0.9.0
Release:        %{release}
Summary:        Self-hosted document search and indexing server
License:        GPL-3.0-or-later
URL:            https://github.com/linuxrebel/DocuBrowser
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

Requires:       python3 >= 3.9
Recommends:     calibre

%description
DocuBrowse is a self-hosted document search and indexing server.
It scans PDF, DOCX, PPTX, XLSX, and EPUB files, extracts text,
generates AI-powered synopses and semantic embeddings via Ollama,
and provides a web UI for full-text and semantic search.

Ollama (https://ollama.com) is required for AI features but is not
packaged as an RPM dependency — install it separately.

%prep
%setup -q

%install
rm -rf %{buildroot}

# ── Application directory ────────────────────────────────────────────────────
install -d -m 755 %{buildroot}/opt/docubrowser
install -d -m 755 %{buildroot}/opt/docubrowser/icons
install -d -m 755 %{buildroot}/opt/docubrowser/EndUser_docs

# Python application files
install -m 644 docubrowser.py       %{buildroot}/opt/docubrowser/
install -m 644 doc_search.py        %{buildroot}/opt/docubrowser/
install -m 644 scan_docs.py         %{buildroot}/opt/docubrowser/
install -m 644 embed_docs.py        %{buildroot}/opt/docubrowser/
install -m 644 pdf_extractor.py     %{buildroot}/opt/docubrowser/
install -m 644 docx_extractor.py    %{buildroot}/opt/docubrowser/
install -m 644 pptx_extractor.py    %{buildroot}/opt/docubrowser/
install -m 644 xlsx_extractor.py    %{buildroot}/opt/docubrowser/
install -m 644 ebook_extractor.py   %{buildroot}/opt/docubrowser/
install -m 644 hardware_utils.py    %{buildroot}/opt/docubrowser/
install -m 644 docubrowse_db.py     %{buildroot}/opt/docubrowser/
install -m 644 purge_pii.py         %{buildroot}/opt/docubrowser/
install -m 755 backup_restore.py    %{buildroot}/opt/docubrowser/
install -m 644 ensure_ollama.py     %{buildroot}/opt/docubrowser/
install -m 644 dup_detect.py        %{buildroot}/opt/docubrowser/

# Web UI
install -m 644 index.html           %{buildroot}/opt/docubrowser/
install -m 644 settings.html        %{buildroot}/opt/docubrowser/

# Icons
install -m 644 icons/*              %{buildroot}/opt/docubrowser/icons/

# Support files
install -m 644 requirements.txt     %{buildroot}/opt/docubrowser/
install -m 644 du-docs.db.example   %{buildroot}/opt/docubrowser/

# Documentation
install -m 644 README.md            %{buildroot}/opt/docubrowser/
install -m 644 LICENSE              %{buildroot}/opt/docubrowser/
install -m 644 INSTALL.md           %{buildroot}/opt/docubrowser/
for f in EndUser_docs/*; do
    [ -f "$f" ] && install -m 644 "$f" %{buildroot}/opt/docubrowser/EndUser_docs/
done

# ── Wrapper scripts in /usr/bin ──────────────────────────────────────────────
install -d -m 755 %{buildroot}/usr/bin

cat > %{buildroot}/usr/bin/docubrowser <<'WRAPPER'
#!/usr/bin/env bash
# DocuBrowse CLI wrapper — installed by docubrowser-foss RPM
exec /opt/docubrowser/venv/bin/python3 /opt/docubrowser/docubrowser.py "$@"
WRAPPER
chmod 755 %{buildroot}/usr/bin/docubrowser

cat > %{buildroot}/usr/bin/docuback <<'WRAPPER'
#!/usr/bin/env bash
# DocuBrowse backup/restore wrapper — installed by docubrowser-foss RPM
exec /opt/docubrowser/venv/bin/python3 /opt/docubrowser/backup_restore.py "$@"
WRAPPER
chmod 755 %{buildroot}/usr/bin/docuback

# ── Desktop menu entry ──────────────────────────────────────────────────────
install -d -m 755 %{buildroot}/usr/share/applications
install -m 644 docubrowser.desktop %{buildroot}/usr/share/applications/


%post
# ── Create virtualenv and install Python dependencies ────────────────────────
if command -v python3 >/dev/null 2>&1; then
    echo "Creating Python virtualenv at /opt/docubrowser/venv/ ..."
    python3 -m venv /opt/docubrowser/venv 2>/dev/null
    if [ -f /opt/docubrowser/venv/bin/pip ]; then
        /opt/docubrowser/venv/bin/pip install --upgrade pip -q 2>/dev/null
        /opt/docubrowser/venv/bin/pip install -r /opt/docubrowser/requirements.txt -q 2>/dev/null
        echo "Python dependencies installed."
    else
        echo "WARNING: venv creation succeeded but pip not found."
        echo "         Run: python3 -m venv /opt/docubrowser/venv"
        echo "              /opt/docubrowser/venv/bin/pip install -r /opt/docubrowser/requirements.txt"
    fi
else
    echo "WARNING: python3 not found. Install Python 3.9+ and then run:"
    echo "         python3 -m venv /opt/docubrowser/venv"
    echo "         /opt/docubrowser/venv/bin/pip install -r /opt/docubrowser/requirements.txt"
fi

# ── Create backup directory ──────────────────────────────────────────────────
mkdir -p /opt/docubrowser/backups

echo ""
echo "══════════════════════════════════════════════════════════════"
echo "  DocuBrowse FOSS %{version} installed"
echo "══════════════════════════════════════════════════════════════"
echo ""
echo "  Runtime data will be stored in ~/.docubrowser/ per user."
echo ""
echo "  Commands:"
echo "    docubrowser start          Start the web server"
echo "    docubrowser stop           Stop the server"
echo "    docubrowser status         Show status and stats"
echo "    docubrowser rescan         Scan and index documents"
echo "    docuback --backup          Back up runtime data"
echo "    docuback --restore         Restore from backup"
echo ""
echo "  Web UI:  http://localhost:8643"
echo ""
echo "  Prerequisites (install separately):"
echo "    Ollama   — https://ollama.com  (required for AI features)"
echo "    Calibre  — dnf/apt install calibre  (optional, for e-books)"
echo ""


%preun
# Stop any running DocuBrowse processes before removal
for pidfile in /var/run/docubrowser/docubrowse_scan.pid \
               /var/run/docubrowser/docubrowser.pid; do
    if [ -f "$pidfile" ] 2>/dev/null; then
        kill "$(cat "$pidfile")" 2>/dev/null || true
    fi
done


%postun
# On full removal (not upgrade), clean up venv and bytecode cache
if [ "$1" = "0" ]; then
    rm -rf /opt/docubrowser/venv
    rm -rf /opt/docubrowser/__pycache__
    echo "DocuBrowse removed.  User data in ~/.docubrowser/ was preserved."
fi


%files
%license /opt/docubrowser/LICENSE
%doc /opt/docubrowser/README.md
%doc /opt/docubrowser/INSTALL.md

# Application
%dir /opt/docubrowser
/opt/docubrowser/*.py
/opt/docubrowser/*.html
/opt/docubrowser/icons/
/opt/docubrowser/EndUser_docs/
/opt/docubrowser/requirements.txt
/opt/docubrowser/du-docs.db.example

# CLI wrappers
/usr/bin/docubrowser
/usr/bin/docuback

# Desktop menu entry
/usr/share/applications/docubrowser.desktop


%changelog
* Fri Jul 03 2026 James Sparenberg <james@sparenbergs.us> - 0.9.0-1
- Initial FOSS package release
- Document search and indexing with AI-powered features
- Web UI with dark/light theme, tag management, synopsis
- Semantic search via Ollama embeddings
- Backup and restore utility
