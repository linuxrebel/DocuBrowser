# DocuBrowse v1.0.3 — Administrator Guide

**Date:** 2026-07-23
**Version:** v1.0.3
**License:** GPL-3.0-or-later

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Requirements](#2-requirements)
3. [Installation](#3-installation)
   - 3.1 [Clone or Download](#31-clone-or-download)
   - 3.2 [Recommended Install via install.sh](#32-recommended-install-via-installsh)
   - 3.3 [Manual Python Dependency Install](#33-manual-python-dependency-install)
   - 3.4 [Install Calibre](#34-install-calibre)
   - 3.5 [Install and Start Ollama](#35-install-and-start-ollama)
   - 3.6 [Pull Required Models](#36-pull-required-models)
   - 3.7 [Initialize the Database](#37-initialize-the-database)
   - 3.8 [First Run Verification](#38-first-run-verification)
   - 3.9 [Making docubrowser Globally Accessible](#39-making-docubrowser-globally-accessible)
   - 3.10 [DRM-Encrypted AZW Files](#310-drm-encrypted-azw-files)
4. [CLI Reference](#4-cli-reference)
   - 4.1 [Global Options](#41-global-options)
   - 4.2 [start](#42-start)
   - 4.3 [stop](#43-stop)
   - 4.4 [restart](#44-restart)
   - 4.5 [status](#45-status)
   - 4.6 [scan](#46-scan)
   - 4.7 [rescan](#47-rescan)
   - 4.8 [scan-file](#48-scan-file)
   - 4.9 [embed](#49-embed)
   - 4.10 [open](#410-open)
   - 4.11 [stopall](#411-stopall)
   - 4.12 [report](#412-report)
   - 4.13 [ignore](#413-ignore)
   - 4.14 [purge](#414-purge)
   - 4.15 [duplist](#415-duplist)
   - 4.16 [dupclean](#416-dupclean)
   - 4.17 [scan-missing](#417-scan-missing)
5. [Configuration Files](#5-configuration-files)
   - 5.1 [docubrowse.config](#51-docubrowseconfig)
   - 5.2 [scan_dirs.txt](#52-scan_dirstxt)
   - 5.3 [ignore_dirs.txt](#53-ignore_dirstxt)
   - 5.4 [scan_blacklist.txt](#54-scan_blacklisttxt)
   - 5.5 [pii_blacklist.txt](#55-pii_blacklisttxt)
6. [Running as a System Service](#6-running-as-a-system-service)
7. [Log Files](#7-log-files)
8. [Hardware Tuning](#8-hardware-tuning)
9. [Spread-Layout PDFs](#9-spread-layout-pdfs)
10. [PII Management](#10-pii-management)
11. [Remote LAN Access](#11-remote-lan-access)
12. [Upgrading](#12-upgrading)
13. [Uninstalling](#13-uninstalling)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. Introduction

This guide is for administrators, power users, and self-hosters responsible for installing, configuring, and maintaining a DocuBrowse instance. It assumes comfort with the Linux command line, package management, and basic systemd concepts.

DocuBrowse turns a local collection of documents — PDFs, ebooks, Word documents, spreadsheets, presentations, OpenDocument files, Visio and draw.io diagrams, PlantUML/Mermaid source, SGML/XML and DocBook, SVG, RSS/Atom/OPML feeds, reStructuredText, AsciiDoc, LaTeX, email (.eml), RTF, CSV/TSV, plain text and Markdown, plus config-ish files (.ini/.conf/.cfg/.log/.lst) — into a searchable index accessible through a web browser at `http://localhost:8643`. It uses SQLite with FTS5 for keyword search and Ollama with local AI models for semantic search and on-demand document synopsis generation.

Everything runs on your own machine. No internet connection is required after initial setup, no accounts, and no per-query costs.

---

## 2. Requirements

### Operating System

Linux (Fedora, RHEL, Debian, Ubuntu, Mint, and derivatives), Windows 10/11, and macOS. Linux installs via RPM, DEB, or tarball; Windows via a zip with a double-click installer; macOS via a dmg with a double-click `Install.command` (installs to `~/Applications/DocuBrowse/`, no sudo required for the app itself).

### Hardware Minimums

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| RAM | 8 GB | 16 GB or more |
| CPU | 4 cores | 8+ physical cores |
| Disk | 2 GB for software + space for your documents | — |
| GPU | Not required | NVIDIA or AMD GPU accelerates embeddings |

### Software Dependencies

| Component | Version | Notes |
|-----------|---------|-------|
| Python | 3.9+ (3.12+ recommended) | Must include `venv` and `ensurepip` |
| SQLite | 3.35+ | Bundled with Python — no separate install needed |
| Ollama | Latest | Local AI inference engine |
| nomic-embed-text | Latest | Embedding model (~274 MB); pulled via Ollama |
| dolphin3 | Latest | Synopsis generation model (~4.9 GB); pulled via Ollama |
| Calibre | Latest | Required for MOBI/AZW3/AZW indexing; provides `ebook-meta` and `ebook-convert` |
| libvisio-tools | Latest | Optional — provides `vsd2xml` for legacy binary Visio (`.vsd`/`.vss`/`.vst`) body-text extraction. Without it, legacy files are indexed metadata-only. |

### Python Packages

| Package | Purpose |
|---------|---------|
| `pdfplumber` | PDF text extraction (primary) |
| `pypdf` | PDF extraction fallback for bloated-object files |
| `python-docx` | Word document (.docx) extraction |
| `python-pptx` | PowerPoint (.pptx) extraction |
| `openpyxl` | Excel (.xlsx) extraction |
| `ebooklib` | EPUB extraction |
| `beautifulsoup4` | HTML stripping for EPUB/MOBI content |
| `mobi` | MOBI and AZW3 extraction |
| `striprtf` | RTF text extraction (pure Python; without it .rtf is indexed metadata-only) |
| `numpy` | Vector math for semantic search |
| `psutil` | Hardware detection, cross-platform process management |

---

## 3. Installation

### 3.1 Recommended Install via Packages

DocuBrowse ships as RPM, DEB, tarball, Windows zip, and macOS dmg packages.
Download the appropriate package from the
[Releases](https://github.com/linuxrebel/DocuBrowser/releases) page.

**Fedora / RHEL:**
```bash
sudo dnf install ./docubrowser-foss-<VERSION>-<RELEASE>.noarch.rpm
```

**Debian / Ubuntu / Mint:**
```bash
sudo apt install ./docubrowser-foss_<VERSION>-<RELEASE>_all.deb
```

**Any Linux (tarball):**
```bash
tar xzf docubrowser-foss-<VERSION>-<RELEASE>.tar.gz
cd docubrowser-foss-<VERSION>-<RELEASE>
sudo ./install.sh
```

All three Linux methods install to `/opt/docubrowser/` with a Python virtualenv.
The RPM and DEB automatically create the virtualenv and install Python
dependencies in a post-install script. The tarball `install.sh` runs
pre-flight checks (python3 >= 3.9, venv, ensurepip, xdg-terminal-exec) and
reports everything missing before making changes.

After Linux installation:

- CLI wrappers: `/usr/bin/docubrowser` and `/usr/bin/docuback`
- Desktop menu entry: appears under Office
- Start with: `docubrowser start`
- Backup/restore: `docuback --backup` / `docuback --restore`

**Windows:**

Prerequisites: install Python 3.9+ (https://www.python.org/downloads/ — check
"Add Python to PATH"; do **not** use the Microsoft Store version) and Ollama
(https://ollama.com) before running the installer.

1. Download the `.zip` from the Releases page
2. Extract and double-click `Install.bat`

Installs to `%USERPROFILE%\DocuBrowse` with a Start Menu shortcut. No admin
required. You may need to log out and back in for the Start Menu shortcut to
appear (a recent Windows behavior change). After install, open a terminal and
run `docubrowser start`.

**macOS:**

Prerequisite: Python 3.9+ (the bundled `python3` works if the Xcode Command
Line Tools are installed: `xcode-select --install`). Ollama is installed
automatically by `docubrowser start` if missing.

1. Download the `.dmg` from the Releases page
2. Open the dmg, then double-click `Install.command` (right-click → Open the
   first time — the scripts are unsigned)

Installs to `~/Applications/DocuBrowse/` with a Python virtualenv. CLI wrappers
are placed at `/usr/local/bin/docubrowser` and `/usr/local/bin/docuback` (sudo
prompted; falls back to `~/bin/` if declined). A `DocuBrowse.app` launcher is
created that starts the server and opens the web UI in Terminal.

After a package install, use the `docubrowser` command (without `./` or `.py`).

### 3.2 Manual / Dev-Checkout Install

Clone the repository for development or manual install:

```bash
git clone https://github.com/linuxrebel/DocuBrowser.git
cd DocuBrowser
```


### 3.3 Manual Python Dependency Install

For a manual or dev-checkout install, install all Python dependencies from `requirements.txt`:

```bash
pip install -r requirements.txt
```

Or install packages explicitly:

```bash
pip install pdfplumber pypdf python-docx python-pptx openpyxl \
            ebooklib beautifulsoup4 mobi numpy
```

Verify:

```bash
python3 -c "import pdfplumber, pypdf, docx, pptx, openpyxl, ebooklib, mobi, numpy; print('OK')"
```

### 3.4 Install Calibre

Calibre is required for ebook metadata extraction and MOBI/AZW3 text extraction. Install it as a system package:

```bash
sudo dnf install calibre          # Fedora / RHEL
sudo apt install calibre          # Debian / Ubuntu
```

On systems without a packaged version (e.g. CentOS Stream):

```bash
sudo -v && wget -nv -O- https://download.calibre-ebook.com/linux-installer.sh | sudo sh /dev/stdin
```

### 3.4a Install libvisio-tools (optional — legacy Visio only)

Modern Visio (`.vsdx`/`.vsdm`) and draw.io (`.drawio`/`.dio`) are handled with
no extra dependency. Legacy binary Visio (`.vsd`/`.vss`/`.vst`) needs the
`vsd2xml` converter from **libvisio-tools** to extract body text:

```bash
sudo dnf install libvisio-tools   # Fedora / RHEL
sudo apt install libvisio-tools   # Debian / Ubuntu
```

Without it, legacy Visio files are still indexed metadata-only (filename
becomes the title, body is empty) and their paths are appended to
`visio_legacy_missing.txt` next to `du-docs.db`. Install libvisio-tools and
run `docubrowser rescan` — the scanner picks the files back up on the next
pass and updates their existing rows with the extracted body text.

### 3.5 Install and Start Ollama

`docubrowser start` will offer to install Ollama automatically. To install manually:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &
```

### 3.6 Pull Required Models

DocuBrowse requires two Ollama models:

- **nomic-embed-text** (~274 MB) — converts document text into 768-dimensional embedding vectors for semantic search
- **dolphin3** (~4.9 GB) — generates Kindle-style document synopses on demand

These two models serve different architectural roles: an embedding model cannot generate text, and a text-generation model cannot produce embedding vectors. Both are confirmed to work without a GPU.

```bash
ollama pull nomic-embed-text:latest
ollama pull dolphin3:latest
ollama list    # verify both appear
```

### 3.7 Initialize the Database

The database is created automatically on first scan. To pre-create an empty schema:

```bash
python3 docubrowse_db.py
```

### 3.8 First Run Verification

```bash
# Index your documents
./docubrowser.py rescan

# Start the server
./docubrowser.py start

# Open the web UI
./docubrowser.py open
```

Check status:

```bash
./docubrowser.py status
```

Expected output when running:

```
DocuBrowse Status
────────────────────────────────────────
  Config:   ./docubrowse.config
  Database: /path/to/du-docs.db
  Port:     8643
  Server:   ● RUNNING  http://localhost:8643
  Documents:  1,234
  Embedded:   1,234
  Tags:       456
```

Verify the API directly:

```bash
curl "http://localhost:8643/api/stats"
curl "http://localhost:8643/api/search?q=test"
```

### 3.9 Making docubrowser Globally Accessible

If you installed via a package (RPM, DEB, or tarball), the CLI wrapper is already in place. For a manual/dev checkout:

```bash
# Option A: symlink
sudo ln -s /path/to/DocuBrowse/docubrowser.py /usr/local/bin/docubrowser

# Option B: add to shell profile
echo 'export PATH="$PATH:/path/to/DocuBrowse"' >> ~/.bashrc
source ~/.bashrc
```

### 3.10 DRM-Encrypted AZW Files

DRM-encrypted AZW files (typical Amazon Kindle purchases) are indexed with metadata only — title and author are searchable but no body text. The description field shows `[DRM-encrypted — text not searchable]`.

To make body text searchable, you need Calibre plus the DeDRM plugin:

1. See: https://deepwiki.com/apprenticeharper/DeDRM_tools/1.1-installation-and-setup
2. Import AZW files into Calibre (DRM is stripped on import)
3. Export as EPUB: `ebook-convert book.azw book.epub`
4. Run `docubrowser rescan` — the EPUB will be picked up automatically

Non-DRM AZW3 files (sideloaded content) work without any extra steps.

---

## 4. CLI Reference

All commands are accessed via `docubrowser <command> [options]`. On a dev/cloned checkout, use `./docubrowser.py <command>` instead.

### 4.1 Global Options

These options can be passed before any subcommand:

| Option | Description |
|--------|-------------|
| `--db PATH` | Path to the SQLite database (overrides config) |
| `--port PORT` | Server port (overrides config) |
| `--config FILE` | Path to config file |

### 4.2 start

Start the DocuBrowse HTTP search server on port 8643.

```bash
docubrowser start
docubrowser start --port 9000
docubrowser start --db /path/to/du-docs.db
```

Before starting, `start` verifies that Ollama is installed, running, and has both required models — installing, starting, or pulling as needed. If a systemd unit (`docubrowser.service`) is installed and loaded, `start` delegates to `systemctl start docubrowser.service` instead of launching a direct subprocess.

The server binds to `127.0.0.1` (localhost only) by default. See [Section 11](#11-remote-lan-access) for LAN access configuration.

### 4.3 stop

Stop the running server.

```bash
docubrowser stop
docubrowser stop --port 9000
```

Sends `SIGTERM` to the server process. If the process does not stop within 5 seconds, sends `SIGKILL`. If a systemd unit is active, delegates to `systemctl stop`.

### 4.4 restart

Stop then start the server.

```bash
docubrowser restart
```

### 4.5 status

Display server status and index statistics.

```bash
docubrowser status
```

Shows: config file in use, database path, port, PID, systemd unit status (if applicable), document count, embedding count, and tag count.

### 4.6 scan

Scan, index, and embed documents. This is identical to `rescan` (kept as an alias for backward compatibility). Use `--no-embed` to skip the embedding step.

```bash
docubrowser scan                        # all supported types, with embedding
docubrowser scan pdf                    # PDFs only
docubrowser scan pdf txt                # PDFs and plain text
docubrowser scan --workers 4            # override worker count
docubrowser scan --limit 100            # index first 100 unindexed files only
docubrowser scan --no-embed             # scan without embedding step
docubrowser scan --doc-dir /data/docs   # scan a specific directory
```

Supported type tokens: `pdf`, `txt`, `md`, `html`. Default (no type specified) scans all supported formats. When no type filter is given, `scan` walks the directory, shows a file-type breakdown, and prompts for confirmation before proceeding.

Scanning runs in the background using `ProcessPoolExecutor`. Worker count is auto-tuned to your hardware. Files are processed smallest-first so the index becomes useful quickly.

### 4.7 rescan

Scan documents and generate embeddings in one step. This is the standard indexing command.

```bash
docubrowser rescan                          # all types, all configured dirs
docubrowser rescan pdf                      # PDFs only
docubrowser rescan pdf txt                  # PDFs and plain text
docubrowser rescan --workers 4              # 4 scan worker processes
docubrowser rescan --embed-workers 8        # 8 Ollama embedding threads
docubrowser rescan --no-embed               # scan without embedding
docubrowser rescan --limit 100              # process at most 100 new files
docubrowser rescan --doc-dir /data/docs     # scan one specific directory
```

`rescan` automatically stops any scan that is currently in progress before starting. After scanning all configured directories, it runs the embedding pass, then prompts whether to run a PII scan.

Worker defaults are hardware-aware: scan workers are based on physical CPU cores and available RAM; embed workers depend on whether an NVIDIA GPU is detected (6 with GPU, 3 without).

### 4.8 scan-file

Extract and index a single file, then generate its embedding. Designed for retrying files that failed and were added to `scan_blacklist.txt`.

```bash
docubrowser scan-file --file /path/to/document.pdf
docubrowser scan-file --file /path/to/document.pdf --no-embed
docubrowser scan-file --file /path with spaces/doc.pdf   # no quoting needed
```

Behavior:
- If the file is in `scan_blacklist.txt`, it is removed from the blacklist before indexing (explicit retry)
- Files in `pii_blacklist.txt` are refused permanently
- Image-only (scanned) PDFs are detected and added to `ocr_list_pdfs.txt`
- Paths with spaces do not need quoting — `--file` accepts multiple tokens and rejoins them


### 4.9 embed

Generate or refresh embeddings for any documents that do not yet have them. Run this after a `scan --no-embed` or if the embedding pass was interrupted.

```bash
docubrowser embed
docubrowser embed --workers 8
docubrowser embed --db /path/to/du-docs.db
```

Embedding uses `ThreadPoolExecutor` (I/O-bound Ollama calls). Default thread count is GPU-aware: 6 with NVIDIA GPU, 3 without.

### 4.10 open

Open the DocuBrowse web UI in your default browser.

```bash
docubrowser open
```

Requires the server to be running. Opens `http://localhost:<port>` in your default browser.

### 4.11 stopall

Stop all running scans, embedding processes, and the search server in one command.

```bash
docubrowser stopall
```

Uses process group signals (`SIGTERM` to the PGID stored in the scan PID file) to ensure scan worker subprocesses are also terminated. Falls back to `/proc`-based process detection for orphaned workers.

### 4.12 report

Walk the configured document directory and print a file-type breakdown. Makes no changes to the database.

```bash
docubrowser report
docubrowser report --doc-dir /data/docs
```

Output shows: extension, file count, percentage of total, total size in MB, and whether the type is supported for indexing. Use this before a scan to understand what will be indexed.

### 4.13 ignore

Manage the list of directories excluded from scanning (`ignore_dirs.txt`).

```bash
docubrowser ignore add /path/to/exclude       # add to ignore list + purge indexed docs under it
docubrowser ignore remove /path/to/exclude    # remove from ignore list (rescan to re-index)
docubrowser ignore list                       # show all currently ignored directories
```

`ignore add` immediately purges any documents already indexed from under the specified directory. `ignore remove` does not re-index — run `rescan` afterward to pick the directory back up.

Ignored directories can also be managed through the Settings page in the web UI (gear icon).

### 4.14 purge

Scan the index for PII patterns and remove matching documents.

```bash
docubrowser purge --dry-run    # preview matches, no changes
docubrowser purge              # interactive — prompts before deleting
```

Checks the stored description and snippet text (approximately 800 characters per document) for:
- Social Security Numbers (validated against SSA allocation rules)
- Credit card numbers (validated by length, issuer prefix, and Luhn algorithm)
- Bank routing numbers (ABA checksum and Federal Reserve prefix validated)
- Bank account numbers (keyword-context gated, 4–17 digits)
- Passport numbers
- Dates of birth
- Medical Record Numbers (MRN)
- Driver license numbers

Documents that match are removed from the database and added to `pii_blacklist.txt`. They will never be re-ingested, even after a rescan.

`purge --dry-run` is always safe to run. After a dry run that finds matches, the tool offers to proceed with a live purge.

After each `rescan`, DocuBrowse prompts whether to run a PII scan automatically.

### 4.15 duplist

List duplicate documents grouped by content hash.

```bash
docubrowser duplist                              # exact duplicates only (SHA256)
docubrowser duplist --near-dups                  # also find near-duplicates (cosine >= 97%)
docubrowser duplist --near-dups --threshold 0.95 # lower similarity threshold
```

Exact duplicates are identified by SHA256 hash (file size pre-filter avoids hashing unique-size files). Near-duplicates use cosine similarity on the stored embedding vectors and require `numpy`.

Output shows duplicate groups, paths, file sizes, and total recoverable disk space.

### 4.16 dupclean

Interactively review and remove duplicate documents found by `duplist`.

```bash
docubrowser dupclean                    # review exact duplicates
docubrowser dupclean --near-dups        # also include near-duplicates
docubrowser dupclean --near-dups --threshold 0.95
```

For each duplicate group, the TUI shows all copies with their paths and sizes, and prompts: `Keep A / Keep B / Keep Both (skip) / Q (quit)`. Deletion removes the file from disk and from the index. Each deletion is committed individually to keep disk and database in sync.

### 4.17 scan-missing

Remove index entries for files that no longer exist on disk. This is an opt-in, non-destructive cleanup pass separate from the normal scan.

```bash
docubrowser scan-missing --dry-run    # preview what would be removed
docubrowser scan-missing              # delete rows for genuinely missing files
```

For every indexed document, checks whether its path still exists:
- **Present** — no action
- **Missing** (filesystem is mounted, file is genuinely gone) — row is deleted (cascades to tags and embeddings)
- **Unmounted** (path looks like it's under an unmounted device) — skipped and reported separately; no DB change

The normal `scan` and `rescan` commands only discover new files — they never check whether existing index entries still have files behind them. Run `scan-missing` periodically if files are frequently moved or deleted.

---

## 5. Configuration Files

All configuration files live next to the database (`du-docs.db`) unless otherwise noted. Lines beginning with `#` are comments.

### 5.1 docubrowse.config

The main configuration file. DocuBrowse reads the first config file it finds from:

1. `/etc/docubrowse.config` (system-wide)
2. `./docubrowse.config` (next to `docubrowser.py`)

If neither exists, built-in defaults apply — except `doc_dir`, which has no default and must be configured.

**Format:**

```ini
# docubrowse.config
doc_dir      = /mnt/data/Documents
db_path      = /home/user/DocuBrowse/du-docs.db
port         = 8643
work_dir     = /home/user/DocuBrowse
allow_remote = false
```

**Keys:**

| Key | Default | Description |
|-----|---------|-------------|
| `doc_dir` | _(none)_ | Primary document directory to index. Must be set before running `scan`, `rescan`, or `report`. Configure via the Settings gear icon or this file. |
| `db_path` | `<script dir>/du-docs.db` | Path to the SQLite database |
| `port` | `8643` | HTTP server port |
| `work_dir` | `<script dir>` | Working directory (where blacklist files are stored) |
| `allow_remote` | `false` | `true` binds to all interfaces for LAN access; `false` binds `127.0.0.1` only |

`doc_dir` is the primary scan directory. Additional scan directories are managed via the Settings page or `scan_dirs.txt` and are unified with `doc_dir` automatically on every `scan`/`rescan`.

**Environment variable overrides (containers).** Every core setting can be
supplied via the environment instead of a config file, which is convenient for
container images that inject paths at runtime. Environment values override the
config file; CLI flags still take precedence. Values are read once at startup —
restart after changing them.

| Variable | Overrides | Description |
|----------|-----------|-------------|
| `DOCUBROWSE_DOC_DIR` | `doc_dir` | Document directory to index |
| `DOCUBROWSE_DB` / `DOCUBROWSE_DB_PATH` | `db_path` | Path to `du-docs.db`. `doc_search.py` can start from this alone when no argv is given. |
| `DOCUBROWSE_PORT` | `port` | HTTP server port |
| `DOCUBROWSE_WORK_DIR` | `work_dir` | Runtime data directory |
| `OLLAMA_HOST` / `DOCUBROWSE_OLLAMA_HOST` | — | Base URL for the Ollama API. A bare `host:port` is accepted (scheme defaults to `http://`). Set for a sidecar Ollama, e.g. `http://ollama:11434`. |

**Private-network access (reverse proxy / BFF).** By default the server is
loopback-only. To let a private-network proxy or backend-for-frontend reach the
API — a Docker/Compose sidecar, for instance — set:

| Variable | Description |
|----------|-------------|
| `DOCUBROWSE_TRUSTED_CIDRS` | Comma-separated private CIDRs/IPs allowed past the loopback gate, e.g. `172.17.0.2/32`. Ranges wider than `/24` (IPv4) or `/120` (IPv6) are refused — a `/32` single host is preferred. |
| `DOCUBROWSE_ALLOWED_HOSTS` | Extra `Host` header names to accept (e.g. a Compose service name). |

This is **not** authentication and **not** public exposure. A non-loopback
trusted peer skips the CSRF check (so a server-side proxy can call mutating
endpoints), which means it has unauthenticated access to the full API — keep the
CIDR list to hosts you fully trust and put login in front of DocuBrowse. Never
list a public range, and never publish the port.

### 5.2 scan_dirs.txt

Lists additional document directories to include in every scan, beyond the primary `doc_dir`. One absolute path per line.

```
/mnt/nas/Documents
/home/james/Books
```

Managed through the Settings page (General panel) in the web UI. `scan` and `rescan` automatically scan every directory in this file along with `doc_dir`, all into the single shared database.

**Location:** next to `du-docs.db`

### 5.3 ignore_dirs.txt

Lists directories to skip during scanning. One absolute path per line.

```
/mnt/data/Documents/WorkConfidential
/mnt/data/Documents/Temp
```

Managed via `docubrowser ignore add|remove|list` or the Settings page (Ignored Directories panel). Adding a directory via the CLI or UI immediately purges any already-indexed documents under it.

**Location:** next to `du-docs.db`

### 5.4 scan_blacklist.txt

Lists files that failed extraction and should be skipped on future scans. Auto-populated — do not edit to add entries manually.

```
# Added 2026-06-10T14:32:01 — BrokenProcessPool
/mnt/data/Documents/problematic_file.pdf
# Added 2026-06-11T09:15:44 — extraction error: No /Root object
/mnt/data/Documents/fake_pdf.pdf
```

Each entry includes a timestamp and reason as a comment on the preceding line.

**To retry a blacklisted file:** Remove its line (and the comment line above it) from the file, then run:

```bash
docubrowser scan-file --file /path/to/the/file.pdf
```

`scan-file` removes the file from the blacklist automatically before attempting extraction.

**Location:** next to `du-docs.db`

### 5.5 pii_blacklist.txt

Lists files removed by the `purge` command for containing PII. This file is permanent — entries are never removed automatically. Files listed here will never be re-ingested by `scan`, `rescan`, or `scan-file`, even if manually removed from the file.

This file is distinct from `scan_blacklist.txt`: `scan_blacklist.txt` covers extraction failures and can be retried; `pii_blacklist.txt` covers deliberate PII removals and cannot be bypassed.

**Location:** next to `du-docs.db`

---

## 6. Running as a System Service

A systemd unit file is included at `systemd/docubrowser.service`. Package installs (RPM, DEB, tarball) place it at `/etc/systemd/system/docubrowser.service` (not auto-enabled).

**Unit file overview:**

```ini
[Unit]
Description=DocuBrowse search server
After=network.target ollama.service
Wants=ollama.service

[Service]
Type=simple
User=james
Group=james
WorkingDirectory=/mnt/data/git/AI/DocuBrowse
ExecStart=/usr/bin/python3 /mnt/data/git/AI/DocuBrowse/doc_search.py \
          /mnt/data/git/AI/DocuBrowse/du-docs.db 8643
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
```

`RuntimeDirectory=docubrowser` tells systemd to create `/run/docubrowser` (symlinked as `/var/run/docubrowser`) owned by the service user. `docubrowser.py` uses this for PID and scan PID files. `LogsDirectory=docubrowser` creates `/var/log/docubrowser` owned by the service user for the log file.

**Install and enable:**

```bash
sudo cp systemd/docubrowser.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now docubrowser.service
```

**Common management commands:**

```bash
systemctl status docubrowser          # show status
systemctl start docubrowser           # start
systemctl stop docubrowser            # stop
systemctl restart docubrowser         # restart
journalctl -u docubrowser -f          # follow logs via journald
journalctl -u docubrowser --since today
```

When the systemd unit is installed and loaded, `docubrowser start`, `docubrowser stop`, and `docubrowser restart` automatically delegate to `systemctl` instead of managing the process directly.

---

## 7. Log Files

DocuBrowse writes all server output (stdout and stderr) to a single log file. The location depends on whether the process has write access to `/var/log/docubrowser/`:

| Location | When used |
|----------|-----------|
| `/var/log/docubrowser/docubrowser.log` | Package install (RPM/DEB/tarball), or when systemd's `LogsDirectory` creates the directory |
| `~/.local/var/log/docubrowser.log` | User install or any unprivileged run |

The active log path is shown by `docubrowser status` and in startup output.

**Follow the log in real time:**

```bash
tail -f /var/log/docubrowser/docubrowser.log
# or
tail -f ~/.local/var/log/docubrowser.log
```

**For systemd installations, journald is also available:**

```bash
journalctl -u docubrowser -f
journalctl -u docubrowser --since "1 hour ago"
```

**Note on log rotation:** The system log at `/var/log/docubrowser/` is managed by the system's logrotate configuration. The user-mode log at `~/.local/var/log/` is not rotated automatically — for long-running user installs, periodically truncate it or set up a user-level logrotate configuration.

**Scan and worker stderr** is redirected to the log file by `docubrowser.py` when launching scan subprocesses. This keeps Python's resource tracker warnings (from forcibly killed workers) and pdfminer color-space warnings out of the terminal.

---

## 8. Hardware Tuning

DocuBrowse auto-tunes worker counts at startup based on detected hardware. Understanding this helps when scanning stalls or consumes too much memory.

### Scan Worker Formula

PDF extraction (pdfplumber) is CPU-bound and memory-intensive. Large technical PDFs can peak at 3–5 GB per worker process.

```
scan_workers = max(1, min(physical_cores, (available_ram_gb - 4.0) / 4.0, cap=8))
```

- **`physical_cores`**: physical (non-hyperthreaded) cores detected via `psutil`
- **`available_ram_gb - 4.0`**: 4 GB is reserved for the OS and non-scan processes
- **`4.0 GB per worker`**: memory budget per worker
- **`cap=8`**: maximum 8 workers regardless of hardware

**Examples:**

| Available RAM | Physical Cores | Scan Workers |
|---------------|---------------|-------------|
| 8 GB | 4 | 1 (only 4 GB usable / 4 GB per worker) |
| 16 GB | 8 | 3 (12 GB usable / 4 GB = 3) |
| 32 GB | 16 | 7 (28 GB usable / 4 GB = 7, capped) |
| 64 GB | 16 | 8 (60 GB usable / 4 GB = 15, capped at 8) |

Override the calculated value:

```bash
docubrowser rescan --workers 4
```

### Embed Worker Formula

Embedding (Ollama API calls) is I/O-bound:

- **With NVIDIA GPU detected:** 6 threads (GPU queues and batches internally)
- **Without GPU (CPU inference):** 3 threads

Override:

```bash
docubrowser rescan --embed-workers 8
docubrowser embed --workers 3
```

### Memory Pressure Thresholds

DocuBrowse monitors available RAM during scans and pauses/resumes submission of new work:

| Threshold | Default | Behavior |
|-----------|---------|---------|
| `MEM_WARN_PCT` | 20% | Log a warning silently; continue scanning |
| `MEM_PAUSE_PCT` | 15% | Stop submitting new work; let in-flight workers drain |
| `MEM_RESUME_PCT` | 25% | Resume after backing off |

These thresholds are deliberately conservative. By the time the pause threshold is reached, workers already running may have active multi-GB PDFs in memory. The pause prevents new work from being submitted until memory recovers.

Memory pause messages appear on stderr (not stdout) so the terminal progress bar is not disrupted.

### PDF Page Cap

`pdf_extractor.py` caps extraction at `MAX_PAGES = 150` pages per PDF. pdfplumber loads all pages into memory even if only a few pages of text are needed; capping at 150 pages gives a large speedup for long documents without significant loss of indexable content.

### Kernel-Enforced Worker Limits

Each scan worker process has two kernel-level resource limits set at startup:

- **`RLIMIT_AS = 6 GB`** — caps the worker's virtual address space. A worker that exceeds 6 GB is killed by the kernel (SIGSEGV/SIGBUS). The parent process catches `BrokenProcessPool`, blacklists the offending file, and continues with remaining files.
- **`RLIMIT_CPU = FILE_TIMEOUT * 10`** — total CPU time budget as a last-resort backstop for completely runaway workers.

These limits are enforced by the kernel and bypass Python's signal handling, which does not work reliably inside C extension code (pdfplumber/pdfminer).

### inotify Watch Limit

Large document collections may trigger:

```
OSError: [Errno 28] inotify watch limit reached
```

This is a Linux kernel limit, not a disk space problem. Raise it for the duration of the scan:

```bash
sudo sh -c "echo fs.inotify.max_user_instances=512 >> /etc/sysctl.conf"
sudo sysctl -p
```

Restore it afterward or leave it raised.

---

## 9. Spread-Layout PDFs

### What They Are

Some PDFs render two logical pages side-by-side on a single wide canvas (a "spread layout"). This is common in scanned books and certain technical publications. The PDF appears completely normal in a PDF viewer, but pdfplumber's spatial layout analysis enters a pathological state when processing these files — consuming 8 GB or more of RAM and potentially running indefinitely.

These files are automatically blacklisted when detected (killed by `RLIMIT_AS`).

### Detection

A spread-layout page has a width significantly greater than the standard 612 points (8.5 inches). Check with `pdfinfo`:

```bash
pdfinfo /path/to/file.pdf | grep -i "page size"
```

A standard-width page shows approximately `612 x 792 pts`. A spread-layout page typically shows `1224 x 792 pts` or similar (roughly double the standard width, i.e., greater than ~850 points).

### Conversion and Re-indexing

Split the spread pages into individual pages using `mutool`:

```bash
mutool poster -x 2 input.pdf output.pdf
```

This splits each wide page into two standard-width pages. After conversion:

1. Remove the original file's entry from `scan_blacklist.txt`
2. Rescan the converted file:

```bash
docubrowser scan-file --file /path/to/output.pdf
```

`mutool` is part of the MuPDF package:

```bash
sudo dnf install mupdf-tools    # Fedora / RHEL
sudo apt install mupdf-tools    # Debian / Ubuntu
```

---

## 10. PII Management

### Overview

DocuBrowse includes a post-ingest PII scanner that detects sensitive personal information in stored document descriptions and snippets. It is not a substitute for access controls or encryption, but it prevents inadvertently indexed PII from appearing in search results.

### PII Types Detected

| Type | Validation |
|------|-----------|
| Social Security Number (SSN) | Pattern match + SSA allocation rules |
| Credit card number | Pattern match + length + issuer prefix + Luhn algorithm |
| Bank routing number | Pattern match + ABA checksum + Federal Reserve prefix |
| Bank account number | Keyword-context gated (4–17 digits near "account"/"acct") |
| Passport number | Pattern match |
| Date of birth (DOB) | Pattern match |
| Medical Record Number (MRN) | Pattern match |
| Driver license number | Pattern match |

Validation is deliberately strict: SSNs are checked against SSA allocation rules, credit cards by length, issuer prefix, and Luhn checksum, bank routing numbers by ABA checksum and Federal Reserve district prefix. This reduces false positives and avoids deleting documents over incidental number groups.

### Running the PII Scanner

```bash
# Preview matches — no changes made (always safe to run)
docubrowser purge --dry-run

# Interactive live purge — prompts before deleting
docubrowser purge
```

After each `rescan`, DocuBrowse automatically prompts:

```
PII Scan — check index for personal information
  [y] Purge now  — remove matching documents
  [n] Skip
  [D] Dry-run    — show matches only, no changes  (default)
```

Press Enter to accept the dry-run default.

### What Happens on a Match

1. The document's text content, description, and snippet are checked
2. Matching documents are deleted from the database (cascades to tags and embeddings)
3. The file path is appended to `pii_blacklist.txt`
4. The file is **not** deleted from disk — only from the index

The operation is all-or-nothing within a transaction: if writing `pii_blacklist.txt` fails, the database transaction is rolled back.

### pii_blacklist.txt vs scan_blacklist.txt

| File | Purpose | Can be retried? |
|------|---------|----------------|
| `scan_blacklist.txt` | Extraction failures | Yes — remove the line and run `scan-file` |
| `pii_blacklist.txt` | Deliberate PII removal | No — permanent block; never re-ingested |

Do not remove entries from `pii_blacklist.txt`. If a file was purged in error, you must manually re-add it to the index using `scan-file` after removing it from the blacklist — but be aware that the file will be re-scanned for PII and purged again if matches are found.

---

## 11. Remote LAN Access

By default, DocuBrowse binds to `127.0.0.1` (localhost only) and is not reachable from other machines. Remote access is strictly opt-in.

**Warning:** DocuBrowse has no authentication. Enabling remote access exposes read and delete operations to anyone on the network. Only enable on trusted private networks.

### Enabling Remote Access

Edit `docubrowse.config`:

```ini
allow_remote = true
```

Open the firewall manually:

```bash
sudo firewall-cmd --permanent --add-port=8643/tcp && sudo firewall-cmd --reload  # firewalld
# or
sudo ufw allow 8643/tcp                                                           # ufw
```

Then restart:

```bash
docubrowser restart
```

To disable remote access, set `allow_remote = false`, close the firewall port, and restart.

### Security Protections That Remain Active

Even with remote access enabled, these protections are still enforced:

- **Host-header allow-list** — blocks DNS-rebinding attacks; permits the server's own hostnames and IP
- **CSRF token on mutations** — `/api/delete`, `/api/open`, and POST config/directory routes require a per-process CSRF token from the served HTML and a same-origin `Origin`/`Referer` header
- **No wildcard CORS** — cross-origin reads are blocked

---

## 12. Upgrading

```bash
cd /path/to/DocuBrowse
git pull origin main
```

Database schema migrations are automatic — the server applies any pending migrations on startup. After pulling:

```bash
docubrowser restart
```

Check the status to confirm the new version is running:

```bash
docubrowser status
curl "http://localhost:8643/api/stats"
```

If Python dependencies have changed (check `requirements.txt`), the virtualenv
in `/opt/docubrowser/` is automatically updated on RPM/DEB upgrade. For tarball
or dev-checkout installs:

```bash
pip install -r requirements.txt
```

For package upgrades, download the new package and install over the existing one:

```bash
sudo dnf install ./docubrowser-foss-<version>.noarch.rpm        # Fedora/RHEL
sudo apt install ./docubrowser-foss_<version>_all.deb            # Debian/Ubuntu/Mint
```

On Windows, extract the new zip and run `Install.bat` again — it overwrites the
previous installation while preserving your data.

On macOS, open the new dmg and run `Install.command` again — it overwrites the
previous installation while preserving your data in `~/.docubrowser/`.

No separate migration commands are needed. The schema auto-migrates at next startup.

---

## 13. Uninstalling

### Package Uninstall

**RPM:**
```bash
sudo dnf remove docubrowser-foss
```

**DEB:**
```bash
sudo apt remove docubrowser-foss
```

**Tarball:**
```bash
sudo ./uninstall.sh
```

**Windows:**
Double-click `Uninstall.bat` in the original extracted zip folder, or navigate
to `%USERPROFILE%\DocuBrowse` and run it from there. Removes the virtualenv,
app files, and Start Menu shortcut.

**macOS:**
Double-click `Uninstall.command` on the dmg or in `~/Applications/DocuBrowse/`.
Removes the install directory, CLI wrappers, and the `.app` bundle.

All methods preserve user data (database, config, blacklists).

### Manual / Dev-Checkout Uninstall

```bash
# Stop everything
docubrowser stopall

# Remove the database, blacklists, and config (irreversible)
rm du-docs.db scan_blacklist.txt pii_blacklist.txt \
   ignore_dirs.txt scan_dirs.txt docubrowse.config

# Remove the directory
cd ..
rm -rf DocuBrowse
```

---

## 14. Troubleshooting

### Scan appears stuck or stalled

Check the log for memory pressure events or worker activity:

```bash
tail -50 /var/log/docubrowser/docubrowser.log
```

If memory is below `MEM_PAUSE_PCT` (15%), the scan has paused and is waiting for RAM to recover above `MEM_RESUME_PCT` (25%). This message appears on stderr:

```
⚠ Memory critical: 12.3% free (1.9 GB) — pausing until ≥25%
```

Wait for the in-flight workers to finish their current files and release memory. If the system remains stuck, stop the scan and reduce workers:

```bash
docubrowser stopall
docubrowser rescan --workers 2
```

### Worker killed — BrokenProcessPool

When a worker exceeds its memory limit (`RLIMIT_AS = 6 GB`) or CPU budget, the kernel kills it. The log records:

```
BrokenProcessPool: <file path>
Auto-blacklisted: /path/to/problematic.pdf
```

The offending file is automatically added to `scan_blacklist.txt`. The scan continues with remaining files. This is expected behavior for pathologically complex PDFs.

To retry the file later:

```bash
# Remove it from the blacklist, then:
docubrowser scan-file --file /path/to/problematic.pdf
```

### Spread-layout PDFs hang

If a specific PDF causes a worker to run for many minutes without completing, it is likely a spread-layout file. See [Section 9](#9-spread-layout-pdfs) for detection and conversion instructions. The file will eventually be killed by `RLIMIT_AS` and blacklisted automatically, but converting it first produces a better-indexed result.

### Ollama not running

```bash
ollama serve                              # start manually
ollama list                               # verify models are present
ollama pull nomic-embed-text:latest       # pull if missing
ollama pull dolphin3:latest               # pull if missing
```

`docubrowser start` runs this check automatically and offers to install/start/pull as needed. If Ollama fails repeatedly, check whether it is already running on a different port or blocked by a firewall.

### Port 8643 already in use

```bash
lsof -i :8643          # identify the process using the port
fuser 8643/tcp         # alternative

# If it is a stale DocuBrowse process:
docubrowser stopall

# If it is another application, change DocuBrowse's port:
# Edit docubrowse.config:  port = 9000
docubrowser start --port 9000
```

### Image-only (scanned) PDFs not searchable

PDFs with no extractable text are detected during scan and added to `ocr_list_pdfs.txt`. They are indexed with a placeholder `[scanned PDF — OCR required]` so they appear in browse but will not match keyword or semantic searches until OCR is applied.

```bash
# Check how many scanned PDFs were found:
wc -l ocr_list_pdfs.txt
cat ocr_list_pdfs.txt
```

OCR integration is on the roadmap but not yet implemented. For now, run an external OCR tool (e.g. `ocrmypdf`) on the files listed in `ocr_list_pdfs.txt`, then rescan.

### Duplicate entries after moving files

DocuBrowse does not detect file moves. When a file is moved, the old path remains in the index and the new path is picked up as a new entry on the next rescan. Use `scan-missing` to clean up the stale old-path entries:

```bash
docubrowser scan-missing --dry-run    # preview
docubrowser scan-missing              # apply
```

Then use `duplist` and `dupclean` to handle any true duplicates that resulted from the move.

### Server returns HTTP 500 on first search after fresh install

This is typically caused by a schema mismatch between the example database (`du-docs.db.example`) and the current code. Reinitialize the database:

```bash
docubrowser stopall
rm du-docs.db
python3 docubrowse_db.py    # creates a fresh, correctly-versioned database
docubrowser rescan
docubrowser start
```

### PDF objects warning (bloated-object PDF)

PDFs with more than 8,000 PDF objects (often caused by repeated ExifTool metadata updates) are automatically routed through `pypdf` instead of `pdfplumber`. If you see this in the log, it is expected behavior — the file is being handled by the fallback extractor.

```bash
# Check object count:
pdfinfo /path/to/file.pdf | grep -i objects
```

---

*DocuBrowse v1.0.3 — Administrator Guide — 2026-07-23*
*Copyright (C) 2026 James Sparenberg — GPL-3.0-or-later*
