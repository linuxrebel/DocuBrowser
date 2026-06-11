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
| ebooklib | any | EPUB extraction |
| beautifulsoup4 | any | HTML stripping for EPUB/MOBI |
| mobi | any | MOBI / AZW3 extraction |
| Ollama | latest | semantic search embeddings + synopsis generation |
| SQLite | 3.35+ | bundled with Python |
| nomic-embed-text | latest | embedding model (pulled automatically) |
| dolphin-uncensored (uandinotai) | latest | synopsis generation model (pulled automatically) |

Hardware minimum: 8 GB RAM, 4 CPU cores. Recommended: 16 GB RAM, 8+ cores.
GPU (NVIDIA/AMD) accelerates embedding generation but is not required.

---

## Step 1 — Get the code

```bash
git clone https://github.com/linuxrebel/DocuBrowser.git
cd DocuBrowser
```

Or unpack the release tarball:

```bash
tar xzf docubrowse-v0.5.0.tar.gz
cd docubrowse-v0.5.0
```

---

## Step 2 — Install Python dependencies

**Core (PDF indexing):**
```bash
pip install pdfplumber pypdf
```

**Word documents (.docx):**
```bash
pip install python-docx
```

**E-books (.epub, .mobi, .azw3):**
```bash
pip install ebooklib beautifulsoup4 mobi
```

**Install everything at once:**
```bash
pip install pdfplumber pypdf python-docx ebooklib beautifulsoup4 mobi
```

Verify:

```bash
python3 -c "import pdfplumber, pypdf, docx, ebooklib, mobi; print('OK')"
```

**Calibre** (system package — provides `ebook-meta` and `ebook-convert`):
```bash
sudo dnf install calibre          # Fedora / RHEL
sudo apt install calibre          # Debian / Ubuntu
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

# Pull the synopsis generation model (~2 GB)
ollama pull uandinotai/dolphin-uncensored:latest
```

Verify:

```bash
ollama list    # should show nomic-embed-text:latest and uandinotai/dolphin-uncensored:latest
```

### Why two models?

Embedding models (used for semantic search) and text-generation models (used for the
Kindle-style document synopsis feature) are architecturally different — an embedding
model cannot generate text, regardless of size or quality. `nomic-embed-text` (274 MB)
handles ingestion/search; `dolphin-uncensored` (2 GB) handles synopsis generation. Both
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
doc_dir  = /mnt/data/Documents      # directory to index
db_path  = /path/to/DocuBrowse/du-docs.db
port     = 8643
work_dir = /path/to/DocuBrowse
EOF
```

If no config file exists, built-in defaults are used (`doc_dir = /mnt/data/Documents`,
`port = 8643`, database next to `docubrowser.py`).

---

## Step 5 — Initialize the database

The database is created automatically on first scan. To initialize it with an empty
schema before scanning:

```bash
python3 docubrowse_db.py
```

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

```bash
# Stop everything
./docubrowser.py stopall

# Remove the database and blacklists (irreversible)
rm du-docs.db scan_blacklist.txt pii_blacklist.txt ocr_list_pdfs.txt

# Remove the directory
cd ..
rm -rf DocuBrowse
```

---

## Support

- Check `status_docs/DECISIONS.md` for known issues and workarounds
- Check the log: `tail -50 /var/log/docubrowser.log`
- Run with verbose output: `./docubrowser.py scan pdf --limit 5` (small test batch)
