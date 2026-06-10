# DocuBrowse Project Status

**Version**: v0.5.0  
**Status**: 🟢 **STABLE — daily use, active development**  
**Last Updated**: 2026-06-09  
**Repository**: https://github.com/linuxrebel/DocuBrowser

---

## Executive Summary

DocuBrowse indexes a local document corpus (currently `/mnt/data/Documents`, ~10K files)
using PDF/HTML/TXT/MD extraction, SQLite FTS5 keyword search, and Ollama semantic
embeddings. The CLI is complete and in daily use. v0.5.0 is the first tagged release.

**Key Metrics**:
- Supported formats: PDF, HTML, TXT, Markdown
- Search latency: <150ms typical
- Worker parallelism: physical-core-aware (tested up to 8 workers)
- PDF resilience: pdfplumber primary, pypdf fallback for >8,000-object files, layout=False secondary fallback, scanned PDF detection

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

**Operations**
- [x] PII purge (dry-run + live)
- [x] stopall, auto-kill on rescan
- [x] report subcommand
- [x] Hardware-aware worker count
- [x] Memory pressure pause/resume

### 📋 Pending

**Phase 2b — Format Expansion**
- [ ] DOCX extractor (python-docx)
- [ ] EPUB/MOBI metadata (ebooklib, KindleUnpack)
- [ ] No-extension file classification (magic bytes)
- [ ] File-type filter in search UI (`?type=pdf`)

**Phase 2 — Housekeeping**
- [ ] `duplist` / `dupclean` (content hash deduplication)
- [ ] Sliding window ETA on progress bar
- [ ] ETA display format: `Xh Ym` when >60 min

**Phase 3+**
- [ ] OCR integration for scanned PDFs
- [ ] Config persistence in UI
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
3. **`duplist`/`dupclean` not implemented** — stubs only.
4. **No file-type filter in search UI** — searching "docx" returns semantically similar PDFs. Fix: `?type=` filter (deferred).
5. **ocr_list_pdfs.txt may have duplicate lines** — multiple scan runs of the same image-only PDF append the path again. OCR processing must deduplicate on read.
