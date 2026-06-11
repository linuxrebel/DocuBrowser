# DocuBrowse Project Status

**Version**: v0.6.0  
**Status**: 🟢 **STABLE — daily use, active development**  
**Last Updated**: 2026-06-09  
**Repository**: https://github.com/linuxrebel/DocuBrowser

---

## Executive Summary

DocuBrowse indexes a local document corpus (currently `/mnt/data/Documents`, ~10K files)
using PDF/DOCX/EPUB/HTML/TXT/MD extraction, SQLite FTS5 keyword search, and Ollama semantic
embeddings. The CLI is complete and in daily use. v0.6.0 adds format expansion, config UI, delete from UI, and duplicate detection.

**Key Metrics**:
- Supported formats: PDF, DOCX, EPUB, MOBI, AZW3, AZW, HTML, TXT, Markdown
- Search latency: <150ms typical
- Worker parallelism: physical-core-aware (tested up to 8 workers)
- PDF resilience: pdfplumber primary, pypdf fallback for >8,000-object files, layout=False secondary fallback, scanned PDF detection

---

## v0.6.0 — What's in this release

### Duplicate Detection (2026-06-09)
- **`dup_detect.py`**: New module with exact-duplicate detection (SHA256, size pre-filter) and near-duplicate detection (numpy batched cosine similarity, union-find clustering).
- **`duplist`**: CLI command to list exact and/or near-duplicate groups with recoverable space.
- **`dupclean`**: Interactive TUI — shows labeled [A]/[B] file pairs, prompts "Keep A / Keep B / Keep Both (skip) / Q", confirm before delete. Deletes from disk + DB + FTS index (per-doc commit).
- `--near-dups` flag and `--threshold` (default 0.97) for both commands.

### Config Read/Write (2026-06-09)
- `GET /api/config` — reads real config file (first of `/etc/docubrowse.config`, then `./docubrowse.config`); returns `docPath`, `workDir`, `port`, `installed`, `configSource`.
- `POST /api/config` — writes `./docubrowse.config` with `doc_dir`, `work_dir`, `port`.
- Settings UI: port is now a configurable field; info message uses neutral color (not orange).
- `docubrowse.config` added to `.gitignore`.

### DOCX Support (2026-06-09)
- `docx_extractor.py`: python-docx extracts paragraphs, tables, and core properties (title, author, subject).
- Integrated into `scan_docs.py` and `docubrowse_db.py`.

### Ebook Support (2026-06-09)
- `ebook_extractor.py`: ebooklib for EPUB; mobi package + Calibre fallback for MOBI/AZW3; DRM-encrypted AZW indexed metadata-only.
- Integrated into `scan_docs.py`.

### Delete from UI (2026-06-09)
- `GET /api/delete` endpoint; 🗑 trash icon on each result card; custom confirm modal (Cancel is default); removes from disk and DB (FTS cleaned).

---

## v0.5.0 — What's in this release

### PDF Extraction Hardening (2026-06-09)
- **pypdf pre-check**: Before calling pdfplumber, read trailer `/Size` via pypdf. If >8,000 objects, route to pypdf (lazy-loading) instead — fixes Security_of_Cloud-based_systems.pdf class of hang (root cause: ExifTool metadata appended 22,421 xref objects without GC; pdfminer builds complete object map on open).
- **layout=False fallback**: After default pdfplumber extraction yields no text, retry with `layout=False` to skip spatial analysis on complex/spread-layout PDFs.
- **Scanned PDF detection**: If both passes yield no text, check `pdf.pages[0].images`. Image-only PDFs are indexed as `doc_type='scanned'` with placeholder text; path appended to `ocr_list_pdfs.txt`.
- **Import fix**: `pypdf` imported independently of pdfplumber (both `HAS_*` flags can be True simultaneously). `_extract_file` now forwards `doc_type` in its return dict.

### New Commands (2026-06-09)
- **`scan-file --file PATH`**: Extract and index one file in the main process (no executor). Auto-removes from `scan_blacklist.txt` if listed (explicit retry). Refuses `pii_blacklist.txt` entries. Embeds afterward unless `--no-embed`. `--file` uses `nargs='+'` so paths with spaces work without quoting.
- **`report`**: Walk doc directory, print extension breakdown (count/percent/size/scannable label). No DB changes.
- **`stopall`**: Kill all running scans, embeds, and the server.

### Scan UX (2026-06-09)
- **`--limit N`**: Process at most N unindexed files per run; next run resumes naturally (already-indexed files are skipped before applying limit).
- **Unfiltered scan prompt**: `scan`/`rescan` without a type filter shows file-type breakdown and prompts y/N before proceeding.
- **Report subcommand**: Scannable types listed individually; all others collapsed to single `(unscannable)` line.

### DB rename (2026-06-09)
- Database renamed from `docs.db` → `du-docs.db`. Example file moved to `du-docs.db.example`. All references updated.

### Author/Subject fields (2026-06-09)
- `documents` table: `subject TEXT` column added.
- `doc_fts` virtual table: `author`, `subject` columns added; migration drops/recreates FTS and repopulates if column is missing.
- `pdf_extractor.py`: extracts `Subject` from pdfplumber and pypdf metadata.
- `scan_docs.py`: passes `subject` through `_extract_file` return dict; updated INSERT for both tables.
- `doc_search.py`: both browse and search paths SELECT `d.author, d.subject`; keyword scoring adds 0.7 boost (author phrase), 0.5 (subject phrase), 0.1/0.05 per token.

---

## Session History

### 2026-06-11 — Alpha index bar: global server-side letter filter
- Index bar (0-9, A-Z) now queries `/api/search?letter=X` for ALL matching
  documents, not just the currently-loaded page. Paginated by the existing
  page-size preference; Next/Back and page-size changes work while a letter
  filter is active. Clicking the active letter again returns to All Documents.
- `doc_search.py`: `/api/search` empty-query path accepts `letter=A-Z` or
  `letter=0-9` (digits/symbols bucket via `NOT GLOB '[A-Z]'`), parameterized
  (no injection risk).
- `index.html`: new `currentLetter` state var; `filterByLetter` is now async
  and server-backed; `loadMoreTop`/`loadMorePrev`/`changePageSize` updated to
  branch on `currentLetter`.
- Verified via Playwright (O=53 results across pages, 0-9=613, toggle off,
  page-size change while filtered). QA PASS (added `isLoadingMore` guard to
  `filterByLetter` per QA recommendation).
- Committed a899ff8.

### 2026-06-10 — Settings page refactor, dir-browser fix
- Fixed dir-browser sizing/reachability bug: `.dir-browser { max-height: min(320px, 35vh) }` in
  index.html, verified at 1280x720 and 1440x900 (commit 3861602).
- Confirmed accidental ignoreDirs addition (`/mnt/data/Documents/Visual Studio 2022`) was intentional
  per James.
- Moved Settings UI from a modal (`#settingsModal`) to a standalone page: new `settings.html`,
  new `GET /settings` route in `doc_search.py`, gear icon now opens it via `window.open('/settings',
  '_blank')`. Removed modal markup/JS/CSS from index.html (kept `.modal`/`.btn-secondary` for the
  synopsis/delete modals). Verified via Playwright (zero console errors on `/` and `/settings`,
  dir-browser functional), QA PASS, committed c62231b.
- Cleaned up an accidental commit of Playwright test artifacts and screenshots; added
  `.playwright-mcp/` and `*.png` to `.gitignore` (commit 65b2d1a).
- Updated README.md settings screenshot caption/note (screenshot itself still stale — needs
  regeneration against `/settings`).
- **Pending**: James flagged "a bunch of UI tweaks needed" for the new settings page —
  specifics not yet gathered, to be addressed next session.
- See `status_docs/DECISIONS.md` for full details on all of the above.

### 2026-06-09 (continued) — PDF hardening, scan-file, packaging
- Investigated Security_of_Cloud-based_systems.pdf hang: confirmed pdfminer hangs on 22,421-object xref traversal at `open()` time. pypdf opens in 0.05s (lazy load).
- Implemented pypdf pre-check in `pdf_extractor.py`: trailer `/Size` >8,000 → skip pdfplumber, use pypdf.
- Added `scan_single_file()` to `scan_docs.py` with `_blacklist_remove()`.
- Added `scan-file` subcommand to `docubrowser.py`.
- Fixed `--file` argument to use `nargs='+'` after argparse hyphen-in-path parsing failure.
- Tagged v0.5.0, wrote README/INSTALL/project_status docs, created release tgz.

### 2026-06-09 (morning) — Author/subject, scan UX, DB rename, triage
- Added author/subject as first-class fields in DB, FTS, extractor, scanner, search scoring.
- Added `--limit N`, `report` subcommand, unfiltered scan confirmation prompt.
- Renamed DB to `du-docs.db`.
- Wrote and ran `triage_blacklist.py` one-off script to reclassify existing blacklist: identified scanned PDFs vs truly broken ones, moved scanned to `ocr_list_pdfs.txt`.
- Added `ocr_list_pdfs.txt` to `.gitignore`.
- Added `layout=False` fallback in `_extract_pdfplumber`.
- Added scanned PDF detection (`doc_type='scanned'`) in `_extract_pdfplumber`.

### 2026-06-08 — Scan hardening, PII purge, open from UI
- `hardware_utils.py` — CPU/GPU/RAM detection, `recommended_scan_workers()` (4 GB/worker + 4 GB OS reserve, cap 8), `wait_for_memory()`.
- ProcessPoolExecutor hardening: `forkserver` start method → `fork` (nested function pickling), module-level `_worker_init`, SIGINT ignore, RLIMIT_AS 6 GB, RLIMIT_CPU 3000s.
- SIGALRM replaced with `resource.setrlimit()` after confirming SIGALRM is unreliable in C extensions.
- Sliding window executor pattern (`wait(FIRST_COMPLETED)`, MAX_IN_FLIGHT = workers).
- `stopall`, `cmd_rescan` auto-kills, scan PID file, process group kill.
- `purge_pii.py` — SSN/CC/DOB/MRN/DL/Passport regex scan; all-or-nothing transaction; `pii_blacklist.txt`.
- `GET /api/open` — validates path against DB index, runs xdg-open.
- Post-scan PII prompt — y/n/D (dry-run default).

### 2026-06-07 — MVP (v0.1.0)
- SQLite schema with FTS5, doc_tags, doc_embeddings.
- HTTP search server (port 8643) with hybrid search (70/30 semantic/keyword).
- PDF extraction with pdfplumber.
- Ollama embedding pipeline (nomic-embed-text:latest, 768-dim).
- Single-file frontend (index.html) with dark/light theme, pagination, tag cloud, alphabetic index bar.

---

## Current State

### ✅ Complete

**Indexing**
- [x] PDF extraction (pdfplumber + pypdf fallback)
- [x] HTML extraction (script/style strip, entity decode)
- [x] TXT/Markdown extraction
- [x] Author, subject, title metadata
- [x] Auto-generated tags (extension + directory names + content keywords)
- [x] Scanned PDF detection → ocr_list_pdfs.txt
- [x] Scan blacklist (auto-populated on failure, retriable)
- [x] PII blacklist (permanent, never re-ingest)
- [x] `scan-file` for single-file retry
- [x] `--limit N` for batch scanning

**Search**
- [x] FTS5 keyword search (title, author, subject, tags, snippet)
- [x] Semantic search (cosine similarity, 768-dim vectors)
- [x] Hybrid mode (70% semantic + 30% keyword, merged rank)
- [x] Author/subject scoring boosts

**Server & UI**
- [x] HTTP server port 8643
- [x] Dark/light theme, pagination, tag cloud, alphabetic bar
- [x] Click to open file (xdg-open), copy path to clipboard
- [x] `/api/stats`, `/api/search`, `/api/tags`, `/api/open`
- [x] Delete from UI (🗑 trash icon, confirm modal, `/api/delete`)
- [x] Config read/write UI (Settings modal, `/api/config` GET + POST)

**Format Support**
- [x] PDF (pdfplumber + pypdf fallback)
- [x] DOCX (python-docx)
- [x] EPUB/MOBI/AZW3/AZW (ebooklib + Calibre)
- [x] HTML, TXT, Markdown

**Operations**
- [x] PII purge (dry-run + live)
- [x] stopall, auto-kill on rescan
- [x] report subcommand
- [x] Hardware-aware worker count
- [x] Memory pressure pause/resume
- [x] `duplist` / `dupclean` (exact SHA256 + near-dup cosine similarity)

### 📋 Pending

**Phase 2b — Remaining**
- [ ] No-extension file classification (magic bytes)
- [ ] File-type filter in search UI (`?type=pdf`)

**Phase 2 — Remaining**
- [ ] Sliding window ETA on progress bar
- [ ] ETA display format: `Xh Ym` when >60 min

**Phase 3+**
- [ ] OCR integration for scanned PDFs
- [ ] Result export (CSV/JSON)
- [ ] API key authentication
- [ ] Docker deployment

---

## File Inventory (core source)

| File | Purpose |
|------|---------|
| `docubrowser.py` | CLI entry point — all commands |
| `doc_search.py` | HTTP server, search API |
| `docubrowse_db.py` | SQLite schema and migrations |
| `scan_docs.py` | Document discovery, extraction, DB writes |
| `pdf_extractor.py` | PDF extraction (pdfplumber + pypdf) |
| `docx_extractor.py` | Word document extraction (python-docx) |
| `ebook_extractor.py` | EPUB/MOBI/AZW3/AZW extraction (ebooklib + Calibre) |
| `dup_detect.py` | Exact (SHA256) and near-duplicate (cosine) detection |
| `hardware_utils.py` | CPU/GPU/RAM detection, worker formula |
| `embed_docs.py` | Ollama embedding pipeline |
| `purge_pii.py` | PII scanner and purge |
| `ensure_ollama.py` | Ollama prerequisite checker |
| `index.html` | Frontend UI |

---

## Known Issues

See `status_docs/DECISIONS.md` for full details. Key open items:

1. **ETA drifts high** — progress bar ETA uses simple average; large PDFs hit late inflate it. Fix: sliding window average (deferred).
2. **Scanned PDFs not searchable** — indexed with placeholder; OCR deferred to Phase 3.
3. **No file-type filter in search UI** — searching "docx" returns semantically similar PDFs. Fix: `?type=` filter (deferred).
4. **ocr_list_pdfs.txt may have duplicate lines** — multiple scan runs of the same image-only PDF append the path again. OCR processing must deduplicate on read.
