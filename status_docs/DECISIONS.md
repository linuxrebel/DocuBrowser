# DocuBrowse — Deferred Decisions & Known Unknowns

**Purpose**: Record explicit decisions to defer work, so compaction doesn't lose them.  
**Rule**: Any time we decide to skip or hold something, it goes here with a reason.

---

## Deferred Agent Investigation Threads

Early in the project, 8 parallel agent tasks were run to investigate the document corpus
at `/mnt/data/Documents` (9,998 files). 7 of 8 were completed. The 8th was explicitly
held for later.

### Corpus inventory (from planning.md)
| Type | Count | % |
|------|-------|---|
| .html | 6,004 | 60.1% |
| .pdf | 1,242 | 12.4% |
| no_ext | 591 | 5.9% |
| .png | 201 | 2.0% |
| .azw3 (Kindle) | 182 | 1.8% |
| .jpg | 104 | 1.0% |
| .ccd (ClickCharts) | 102 | 1.0% |
| .txt | 95 | 0.9% |
| .docx | 93 | 0.9% |
| .mobi (Kindle) | 69 | 0.7% |
| .epub | 63 | 0.6% |

### Known completed threads (7)
Believed to be investigations/samplers for the major file categories.
To be confirmed and filled in as memory allows.

- [ ] Thread 1: *(to recall)*
- [ ] Thread 2: *(to recall)*
- [ ] Thread 3: *(to recall)*
- [ ] Thread 4: *(to recall)*
- [ ] Thread 5: *(to recall)*
- [ ] Thread 6: *(to recall)*
- [ ] Thread 7: *(to recall)*

### ⚠ Deferred Thread 8 — No-Extension / Unknown File Types
**Status**: Held for later  
**Most likely topic**: Investigating the 591 no-extension files to classify them  
**Why deferred**: Unknown content — could be text, binary, misnamed PDFs/HTML, etc.  
**What was planned**: Sample the files, detect MIME type or magic bytes, decide on
extraction strategy (index as text? skip? rename?).  
**Why held**: Adds complexity without clear payoff until the main formats (PDF, HTML) are working.

**Action**: When starting Phase 2b, run a classifier pass over the 591 files:
```bash
file /mnt/data/Documents/<no-ext-file>   # magic byte detection
```
Then decide: index as plaintext, route to appropriate extractor, or skip.

---

## Problem Files Requiring Investigation

### Security_of_Cloud-based_systems.pdf
**Full path**: `/mnt/data/Documents/tech-classes/security/Against Security - Self Security/Cloud/Security_of_Cloud-based_systems.pdf`  
**Symptom**: pdfplumber allocated **8.7 GB RAM** and ran for **16+ minutes** without completing or timing out. File opens normally in a PDF reader — it is a valid PDF.  
**Root cause (theory)**: Complex internal PDF structure (deep cross-reference tables, large font objects, or elaborate content streams) causing pdfplumber/pdfminer to build a pathological in-memory object graph. This is distinct from file size — the issue is structural complexity, not page count.  
**Why SIGALRM didn't save us**: pdfplumber spends the majority of its time in C extensions (pdfminer's C layer). Python's signal handler only runs between bytecodes; it is never called while C code is executing in a tight loop.  
**Fix applied (2026-06-08)**: Switched from SIGALRM to kernel-level `resource.setrlimit()` in `_worker_init`:
- `RLIMIT_AS = 6 GB` — malloc fails with MemoryError when exceeded (works in C code)
- `RLIMIT_CPU = FILE_TIMEOUT_SECS` — SIGXCPU kills the worker on CPU time overrun  
**Root cause identified (2026-06-08)**: The PDF uses a **two-page spread layout** — each PDF "page" renders two logical pages side by side on a single wide canvas (confirmed visually; Kindle also struggles with this file). pdfplumber performs full spatial layout analysis per page: it maps every character's x/y coordinate, detects columns, and infers reading order. On a double-width spread, that's ~2× the layout graph per page, and the column-inference algorithm enters a pathological state trying to reconcile text spanning the gutter between the two logical pages. This is a print-layout PDF, not a reflowable document.

**To investigate / fix**:
- Pre-screen with `pdfinfo` for unusual page dimensions (width > 2× standard = spread layout). Flag these before handing to pdfplumber.
- For spread-layout PDFs: use `pdftotext` (Poppler CLI) as fallback — Poppler's layout engine handles spreads much better than pdfminer.
- Alternatively: pass `layout=False` to pdfplumber's `extract_text()` to skip spatial analysis entirely (much faster/lighter, but text order may be degraded).
- Could also crop each page to left/right halves before extraction using pdfplumber's crop API.
- Check page dimensions: `pdfinfo Security_of_Cloud-based_systems.pdf | grep 'Page size'`

---

## Observed Bugs / UX Issues (2026-06-08 live scan)

### ✅ FEATURE: PII filtering — IMPLEMENTED (2026-06-08)
See Completed Decisions table.

### BUG: Scanner ingesting non-PDF files despite PDF-only intent
**Observed**: Scan picked up HTML, DOCX, and other formats — not just PDFs.  
**Expected**: MVP scans PDFs only.  
**Likely cause**: `scan_docs.py` probably doesn't filter by extension before queuing files, or the extension filter is too broad.  
**Fix**: Check `scan_docs.py` — ensure extension whitelist is enforced before files enter the processing queue. For now, non-PDF formats will fail extraction gracefully and hit the blacklist, but they waste worker time and pollute the DB.  
**Priority**: Medium — scan still completes, but wastes time.

### BUG: Three document categories in UI (PDF, PDF-Books, Books) with inconsistent data
**Observed**: UI shows three separate categories with different data sets. Unclear how the categorization is being applied or where it comes from.  
**Needs investigation**: Check how `scan_docs.py` or `docubrowse_db.py` assigns tags/categories. Is this coming from directory structure? File metadata? A heuristic?  
**Priority**: Medium — confusing UX, may indicate duplicate indexing or schema issue.

### BUG: Searching "docx" returns PDF results
**Observed**: A DOCX-term search surfaces PDF documents.  
**Likely cause**: Hybrid semantic search is dominant (70%) — "docx" is semantically similar to documents about documentation, file formats, or Microsoft Office, which may describe PDFs in the index. The keyword component (30%) isn't enough to suppress unrelated results.  
**Options to address**:  
1. Add a file-type filter to the search UI (checkbox or dropdown: PDF / DOCX / HTML / All)  
2. Boost FTS exact-match on `name` field (filename contains "docx" → strong keyword signal)  
3. Make type filters available via `/api/search?type=pdf`  
**Priority**: Medium — search quality issue; filter is the cleanest fix.

### ✅ FEATURE: Open files from UI — IMPLEMENTED (2026-06-08)
See Completed Decisions table.

---

## Other Known Deferred Decisions

### Book metadata — author, subject, ISBN search
**Decision**: Deferred to Phase 2b  
**Requirement**: Users need to search by author and subject matter for books in the corpus (EPUB, MOBI, AZW3, PDF books). ISBNs should be extracted and stored but NOT indexed as searchable text (SSN regex false-positive risk — ISBNs match similar patterns).  
**What's needed**:
- Extract book metadata (title, author, subject, ISBN, publisher) from ebook formats via `ebooklib` (EPUB), `KindleUnpack` or `mobi` lib (MOBI/AZW3), and PDF metadata fields
- Store `author` and `subject` as first-class columns in the `documents` table (currently only `title`, `author` exist — verify `author` is actually populated for books)
- Ensure FTS5 index covers `author` and `subject` fields so keyword search hits them
- Add `isbn` column (stored, not FTS-indexed) for dedup and lookup
- Search UI: add author/subject filter or boost exact-match on `author` field  
**When to address**: Phase 2b, alongside ebook extraction work.

### ETA / progress bar accuracy
**Decision**: Current ETA is a simple elapsed-time average; starts low then climbs as
large PDFs are hit after small/failed ones are processed quickly.  
**Deferred**: Fix to use a sliding window average over recent N completions.  
**When to address**: Before running full 10K embed phase; annoying but not blocking.

### ETA display format — hours vs minutes
**Decision**: When ETA exceeds 60 minutes, display as `Xh Ym` instead of `XmYYs`.  
**Current behavior**: Shows e.g. `104m43s` for long scans — hard to read at a glance.  
**Desired**: `1h 44m` once over the 60-minute mark.  
**Where to fix**: `_progress_bar()` in `scan_docs.py` — the `eta` formatting block.

### Worker count formula
**Status**: Tuned to 4 workers (was 8 → OOM).  
**Rationale**: Large technical PDFs peak at ~3 GB/worker; formula now uses 4 GB/worker
estimate + 4 GB OS reserve.  
**Open question**: Should we sample file sizes before choosing workers? Very large PDFs
(>100 MB) need fewer workers than small ones.

### Ebook extraction (EPUB / MOBI / AZW3)
**Decision**: Metadata-only for MVP; full content extraction deferred.  
**Why**: No stdlib support; requires `ebooklib`, `KindleUnpack`, or external tools.  
**When to address**: Phase 2b format expansion.

### ClickCharts files (.ccd — 102 files)
**Decision**: Skip entirely for MVP.  
**Why**: Binary format requiring specialized tooling.  
**When to address**: Probably never unless a use case emerges.

### No-extension files (591 files)
**Decision**: Not yet investigated for MVP.  
**Why**: Unknown content; may be text, binary, or misnamed files.  
**When to address**: Phase 2b — sample and classify before deciding extraction strategy.

### HTML URL-encoded variant filenames
**Decision**: Not yet resolved.  
**Question**: What do patterns like `htmlc=m;o=a`, `htmlc=n;o=d` mean?
Are these duplicates of each other? Web archive variants?  
**When to address**: Phase 2b HTML extractor work.

### Sensitive file indexing (.key, .pem, .p12)
**Decision**: Not addressed in MVP.  
**Question**: Should certs/keys be indexed at all? Redacted?  
**When to address**: Before any network-accessible deployment.

---

## Completed Decisions (for reference)

| Decision | Outcome | Date |
|----------|---------|------|
| DB engine | SQLite FTS5 (no external deps, sufficient for <1M docs) | 2026-06-07 |
| Embedding model | nomic-embed-text:latest via Ollama (local, 768-dim) | 2026-06-07 |
| Hybrid search weights | 70% semantic / 30% keyword | 2026-06-07 |
| PDF extractor | pdfplumber (better text layout than pypdf) | 2026-06-07 |
| Worker parallelism | ProcessPoolExecutor (CPU-bound PDF) + ThreadPoolExecutor (I/O Ollama) | 2026-06-08 |
| OOM protection | 4 workers, 4 GB/worker estimate, 4 GB OS reserve, 15% pause threshold | 2026-06-08 |
| Scan log verbosity | Per-file FAILED/OK → log file only; terminal shows progress bar + summary | 2026-06-08 |
| Log location | Tries /var/log/docubrowser.log; falls back to ~/.local/share/docubrowser/ | 2026-06-08 |
| Per-file timeout | SIGALRM (pure-Python) + RLIMIT_AS 6GB + RLIMIT_CPU 3000s (C-extension backstop) | 2026-06-08 |
| Scan process group | start_new_session=True + SCAN_PID_FILE + os.killpg() for clean kill | 2026-06-08 |
| Semaphore warning suppression | Scan stderr → log file; resource_tracker warnings never reach terminal | 2026-06-08 |
| stopall command | Kills scans + embeds + server; auto-invoked at start of every rescan | 2026-06-08 |
| Open files from UI | GET /api/open validates path against DB index, runs xdg-open; title + path row clickable; 📋 copies path | 2026-06-08 |
| PII purge command | purge_pii.py — regex scan of stored description/snippet; dry-run + live mode; all-or-nothing transaction; writes pii_blacklist.txt after commit | 2026-06-08 |
| Two blacklist files | scan_blacklist.txt (retriable failures) vs pii_blacklist.txt (permanent PII); scan loads both; purge writes only to PII list | 2026-06-08 |
| SSN regex false positive | ISBN substrings (e.g. 978-90-5940-365-9) matched SSN pattern; fixed with negative lookbehind/lookahead for adjacent digits/hyphens | 2026-06-08 |
| Post-scan PII prompt | After every scan/rescan, offer y/n/D (dry-run default); dry-run with hits offers immediate live purge | 2026-06-08 |
| Scanned PDF detection (pypdf fallback) | pypdf fallback path does not detect scanned PDFs (PyPDF2 has no .images API — would need /XObject inspection). Acceptable: pdfplumber is always present in production; pypdf path is dead code. If pypdf ever becomes primary, revisit. | 2026-06-09 |
| ocr_list_pdfs.txt deduplication | _ocr_list_add() appends without deduplication — repeated scans could produce duplicate lines. OCR processing must handle duplicates. triage_blacklist.py deduplicates on read. | 2026-06-09 |
| Non-PDF files in DB (root cause) | Files came from unfiltered scan #1, not a filter bug. Extension filter was correct. Fix: confirmation prompt for unfiltered scans now shows file-type breakdown before proceeding. | 2026-06-09 |
| Author/subject fields | Added to documents table, FTS index, pdf_extractor, scan_docs, and doc_search scoring (author +0.7, subject +0.5). ISBN stored but NOT FTS-indexed (SSN regex false-positive risk). | 2026-06-09 |
| Scan --limit N | Processes first N unindexed files; mtime check skips already-indexed files before applying limit, so next run naturally resumes from where last run stopped. | 2026-06-09 |
| report subcommand | Walks doc dir, prints extension breakdown (count/percent/size/scannable). No DB changes. | 2026-06-09 |
