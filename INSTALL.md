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
| Ollama | latest | semantic search embeddings |
| SQLite | 3.35+ | bundled with Python |
| nomic-embed-text | latest | embedding model (pulled automatically) |

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

### DRM-encrypted AZW files

Amazon AZW files downloaded from the Kindle store are DRM-encrypted.
`mobi.extract()` raises `Book is encrypted` and the file is auto-added
to `scan_blacklist.txt`.

To index these books you must first strip the DRM from your own legally
purchased copies:

1. Install [Calibre](https://calibre-ebook.com/) — `sudo dnf install calibre` on Fedora
2. Install the [DeDRM_tools](https://github.com/noDRM/DeDRM_tools) Calibre plugin
3. Import the AZW files into Calibre (DRM is stripped on import with the plugin active)
4. Export as EPUB from Calibre, or use: `ebook-convert book.azw book.epub`
5. Remove the AZW entry from `scan_blacklist.txt`, then rescan the EPUB

This only affects AZW files. AZW3 files sideloaded without DRM work out of the box.

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
```

Verify:

```bash
ollama list    # should show nomic-embed-text:latest
```

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
