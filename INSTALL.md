# DocuBrowse — Installation Guide

This guide covers a fresh install on a Linux system (Fedora/RHEL/Debian/Ubuntu).
DocuBrowse runs entirely locally — no cloud accounts or API keys required.

---

## Requirements

| Requirement | Version | Notes |
|------------|---------|-------|
| Python | 3.10+ | 3.12+ recommended |
| pdfplumber | any | PDF extraction (primary) |
| pypdf | 3.x+ | PDF extraction (fallback for bloated-object PDFs) |
| python-docx | any | Word document (.docx) extraction |
| python-pptx | any | PowerPoint (.pptx) extraction |
| openpyxl | any | Excel (.xlsx) extraction |
| numpy | any | semantic search (vector math) |
| ebooklib | any | EPUB extraction |
| beautifulsoup4 | any | HTML stripping for EPUB/MOBI |
| mobi | any | MOBI / AZW3 extraction |
| Ollama | latest | semantic search embeddings + synopsis generation |
| SQLite | 3.35+ | bundled with Python |
| nomic-embed-text | latest | embedding model (pulled automatically) |
| dolphin3 | latest | synopsis generation model (pulled automatically) |

Hardware minimum: 8 GB RAM, 4 CPU cores. Recommended: 16 GB RAM, 8+ cores.
GPU (NVIDIA/AMD) accelerates embedding generation but is not required.

---

## Recommended install — `install.sh`

The easiest way to install DocuBrowse is the bundled `install.sh`, which runs a
full set of pre-flight checks, reports **everything** that's missing at once, and
changes nothing on your system until all checks pass.

Pre-flight checks cover: `python3` >= 3.9 (with working `venv`/`ensurepip`),
`rsync`, `curl`, `tar`, Calibre, and Ollama — plus `getent`, `useradd`,
`groupadd`, and `systemctl` for system-mode installs.

It has two modes:

**User install** (run as a normal user):
```bash
./install.sh
```
- Installs to `~/.docubrowse` with its own virtualenv.
- CLI wrapper at `~/.local/bin/docubrowser` (ensure `~/.local/bin` is on your `PATH`).
- No systemd integration.
- Start it with: `docubrowser start`

**System install** (run with sudo):
```bash
sudo ./install.sh
```
- Installs to `/opt/docubrowse`, running as a dedicated `docubrowse` system user.
- Installs a systemd unit `docubrowser.service` (installed but **not** auto-enabled).
- CLI wrapper at `/usr/local/bin/docubrowser`.
- Manage it with: `systemctl start docubrowser`

An installed system is driven by the `docubrowser` command (not `./docubrowser.py`).

The manual, step-by-step instructions below remain valid as a **manual /
dev-checkout** alternative.

---

## Step 1 — Get the code

```bash
git clone https://github.com/linuxrebel/DocuBrowser.git
cd DocuBrowser
```

Or unpack the release tarball:

```bash
tar xzf docubrowse-v0.8.0.tar.gz
cd docubrowse-v0.8.0
```

---

## Step 2 — Install Python dependencies

**Simplest path — install everything from `requirements.txt`:**
```bash
pip install -r requirements.txt
```

If you prefer to install packages explicitly, the full set is:
```bash
pip install pdfplumber pypdf python-docx python-pptx openpyxl \
            ebooklib beautifulsoup4 mobi numpy
```

- `numpy` is required by semantic search.
- `python-pptx` / `openpyxl` are required by the `.pptx` / `.xlsx` extractors.

Verify:

```bash
python3 -c "import pdfplumber, pypdf, docx, pptx, openpyxl, ebooklib, mobi, numpy; print('OK')"
```

**Calibre** (system package — provides `ebook-meta` and `ebook-convert`):
```bash
sudo dnf install calibre          # Fedora / RHEL
sudo apt install calibre          # Debian / Ubuntu
```

If your distro doesn't package Calibre (e.g. CentOS Stream), use the official
Linux installer:
```bash
# https://calibre-ebook.com/download_linux
sudo -v && wget -nv -O- https://download.calibre-ebook.com/linux-installer.sh | sudo sh /dev/stdin
```

Calibre is used for ebook metadata extraction and as a text-extraction fallback.
It is required for ebook indexing — install it before running a scan.

### DRM-encrypted AZW files

DRM-encrypted AZW files (typical Amazon Kindle purchases) are indexed with
**metadata only** (title and author are searchable, but no body text).
The description field shows `[DRM-encrypted — text not searchable]`.

To make the body text searchable, Calibre plus the DeDRM plugin are required.
See the installation guide:
**https://deepwiki.com/apprenticeharper/DeDRM_tools/1.1-installation-and-setup**

Once Calibre and DeDRM are set up:

1. Import the AZW files into Calibre (DRM is stripped automatically on import)
2. Export as EPUB: File → Save to disk, or `ebook-convert book.azw book.epub`
3. Rescan — the EPUB will be picked up automatically

Non-DRM AZW3 files (sideloaded content) work without any extra steps.

---

## Step 3 — Install Ollama

`docubrowser.py start` will offer to install Ollama automatically. To do it manually:

```bash
# Linux (amd64 / arm64)
curl -fsSL https://ollama.com/install.sh | sh

# Start the service
ollama serve &

# Pull the embedding model (~274 MB)
ollama pull nomic-embed-text:latest

# Pull the synopsis generation model (~4.9 GB)
ollama pull dolphin3:latest
```

Verify:

```bash
ollama list    # should show nomic-embed-text:latest and dolphin3:latest
```

### Why two models?

Embedding models (used for semantic search) and text-generation models (used for the
Kindle-style document synopsis feature) are architecturally different — an embedding
model cannot generate text, regardless of size or quality. `nomic-embed-text` (274 MB)
handles ingestion/search; `dolphin3` (4.9 GB) handles synopsis generation. Both
are small, fast on CPU, and confirmed to work without GPU. Larger models (e.g.
`gemma4:12b`) were tested but are too slow on modest hardware (~70s per response) — see
`status_docs/DECISIONS.md` for details.

---

## Step 4 — Configure (optional)

Copy the example config and edit it:

```bash
cp docubrowse.config.example docubrowse.config   # if present
# or create from scratch:
cat > docubrowse.config << 'EOF'
doc_dir      = /mnt/data/Documents      # directory to index
db_path      = /path/to/DocuBrowse/du-docs.db
port         = 8643
work_dir     = /path/to/DocuBrowse
allow_remote = false                    # bind 127.0.0.1 only (see below)
EOF
```

`allow_remote` (bool) controls whether the server binds to all interfaces for
LAN access. With `false` (the default) it binds `127.0.0.1` only. See
**Remote (LAN) access** below before enabling it.

If no config file exists, built-in defaults are used (`port = 8643`, database
next to `docubrowser.py`) — except `doc_dir`, which has no default. Until you
configure one (via the Settings gear icon in the web UI, or by setting
`doc_dir` above), the web UI shows a banner prompting you to configure it, and
CLI commands that need a document directory (`rescan`, `report`, `scan`) exit
with an error explaining how to set it.

---

## Remote (LAN) access

During an `install.sh` run the installer asks whether to allow remote (LAN)
access. The default is **No**:

- **No** (default) — the server binds `127.0.0.1` only and the firewall is left
  untouched. Reachable only from the local machine.
- **Yes** — the server binds `0.0.0.0`, the firewall is opened for the port
  (firewalld `8643/tcp`, or `ufw` if that's what you run), and `allow_remote =
  true` is written to `docubrowse.config`.

To answer non-interactively, set the override before running the installer:
```bash
DOCUBROWSE_ALLOW_REMOTE=1 ./install.sh
```

> **WARNING:** DocuBrowse has **no authentication yet**. Only enable remote
> access on trusted networks.

To change this after install (current procedure):

1. Edit `allow_remote` in `docubrowse.config`.
2. Open or close the firewall for the port accordingly.
3. `docubrowser restart`

(A `docubrowser remote on|off` convenience command is planned but not yet
available.)

---

## Step 5 — Initialize the database

The database is created automatically on first scan. To initialize it with an empty
schema before scanning:

```bash
python3 docubrowse_db.py
```

The shipped `du-docs.db.example` is now empty, so a fresh install starts with
zero indexed documents — run a scan (Step 6) to populate it.

---

## Step 6 — Index your documents

```bash
# Scan all supported formats (PDF, HTML, TXT, Markdown)
# Will show a file-type breakdown and prompt before proceeding
./docubrowser.py rescan

# Or start with PDFs only
./docubrowser.py rescan pdf

# Or limit to a batch size for testing
./docubrowser.py rescan pdf --limit 100
```

Scanning runs in the background via `ProcessPoolExecutor`. Worker count is auto-tuned
to your hardware. For a large corpus (thousands of files), this may take minutes to hours.

Monitor progress:

```bash
tail -f /var/log/docubrowser.log
# or
tail -f ~/.local/share/docubrowser/docubrowser.log
```

---

## Step 7 — Start the server and open the UI

```bash
./docubrowser.py start
./docubrowser.py open      # opens http://localhost:8643 in your browser
```

---

## Making docubrowser.py globally accessible

> If you installed via `install.sh`, this is already done for you — the
> `docubrowser` wrapper is installed at `~/.local/bin/docubrowser` (user mode)
> or `/usr/local/bin/docubrowser` (system mode). The steps below are for manual
> / dev checkouts only.

```bash
# Option A: symlink into your PATH
sudo ln -s /path/to/DocuBrowse/docubrowser.py /usr/local/bin/docubrowser

# Option B: add to your shell profile
echo 'export PATH="$PATH:/path/to/DocuBrowse"' >> ~/.bashrc
source ~/.bashrc
```

---

## inotify limit (large collections)

If you see `inotify watch limit reached` during scanning:

```bash
sudo sh -c "echo fs.inotify.max_user_instances=0 >> /etc/sysctl.conf" && sudo sysctl -p
# Restore after scanning:
sudo sh -c "echo fs.inotify.max_user_instances=128 >> /etc/sysctl.conf" && sudo sysctl -p
```

---

## Verify the install

```bash
./docubrowser.py status
```

Expected output:
```
DocuBrowse is running on port 8643
  Documents:  1,234
  Embedded:   1,234
  Tags:       456
```

```bash
curl "http://localhost:8643/api/stats"
curl "http://localhost:8643/api/search?q=test"
```

---

## Upgrading

```bash
cd DocuBrowse
git pull origin main

# The DB schema migrations are automatic — just restart the server
./docubrowser.py restart
```

---

## Uninstalling

If you installed via `install.sh`, use `uninstall.sh` instead — it mirrors
install.sh's mode detection (user vs. system) and removes the install
directory, systemd unit, CLI wrapper, pid/log files, and (optionally, with a
separate confirmation) the dedicated `docubrowse` system user/group:

```bash
cd DocuBrowse
./uninstall.sh
```

It asks for confirmation before removing anything, and is safe to run from
either a user-mode (`$HOME/.docubrowse`) or root/system-mode (`/opt/docubrowse`)
install.

### Manual / dev-checkout uninstall

```bash
# Stop everything
./docubrowser.py stopall

# Remove the database, blacklists, and local config (irreversible)
rm du-docs.db scan_blacklist.txt pii_blacklist.txt ocr_list_pdfs.txt \
   ignore_dirs.txt scan_dirs.txt docubrowse.config

# Remove the directory
cd ..
rm -rf DocuBrowse
```

---

## Support

- Check `status_docs/DECISIONS.md` for known issues and workarounds
- Check the log: `tail -50 /var/log/docubrowser.log`
- Run with verbose output: `./docubrowser.py scan pdf --limit 5` (small test batch)
