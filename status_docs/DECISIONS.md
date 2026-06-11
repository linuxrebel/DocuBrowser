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

### ✅ Security_of_Cloud-based_systems.pdf — RESOLVED
**Full path**: `/mnt/data/Documents/tech-classes/security/Against Security - Self Security/Cloud/Security_of_Cloud-based_systems.pdf`  
**Symptom**: pdfplumber allocated **8.7 GB RAM** and ran for **16+ minutes** without completing or timing out. File opens normally in a PDF reader — it is a valid PDF.  
**Root cause**: The PDF has 22,421 objects for 434 pages (10× normal). Each ExifTool metadata update appended a new xref section with a `/Prev` chain without garbage-collecting old objects. pdfminer (used by pdfplumber) builds a complete object map at `open()` time, traversing the entire chain — this hangs on 22k objects. pypdf lazy-loads and opens in 0.05s.  
**Why SIGALRM didn't save us**: pdfplumber spends the majority of its time in C extensions (pdfminer's C layer). Python's signal handler only runs between bytecodes; it is never called while C code is executing in a tight loop.  
**Fix applied (2026-06-08)**: Switched from SIGALRM to kernel-level `resource.setrlimit()` in `_worker_init`:
- `RLIMIT_AS = 6 GB` — malloc fails with MemoryError when exceeded (works in C code)
- `RLIMIT_CPU = FILE_TIMEOUT_SECS` — SIGXCPU kills the worker on CPU time overrun  
**Root cause identified (2026-06-08)**: The PDF uses a **two-page spread layout** — each PDF "page" renders two logical pages side by side on a single wide canvas (confirmed visually; Kindle also struggles with this file). pdfplumber performs full spatial layout analysis per page: it maps every character's x/y coordinate, detects columns, and infers reading order. On a double-width spread, that's ~2× the layout graph per page, and the column-inference algorithm enters a pathological state trying to reconcile text spanning the gutter between the two logical pages. This is a print-layout PDF, not a reflowable document.

**Fix applied (2026-06-09)**: Added pypdf pre-check in `pdf_extractor.extract_pdf()`:
- Before calling pdfplumber, open the file with pypdf and read `reader.trailer.get('/Size', 0)`.
- If object count > 8,000, skip pdfplumber entirely and use `_extract_pypdf()` instead.
- `layout=False` fallback also added as secondary mitigation for complex-layout PDFs.
- File successfully indexed via `docubrowser.py scan-file`.

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

## Open Issues

### ⚠ gemma4 family too slow on this hardware — synopsis feature using dolphin-uncensored
**Original symptom (resolved)**: `gemma4:latest` (9.6GB Q4_K_M) and `openclaw:latest` (9.6GB)
crashed Ollama's `/api/generate` with `GGML_ASSERT(n_inputs < GGML_SCHED_MAX_SPLIT_INPUTS) failed`.
**2026-06-10**: Ollama upgraded to 0.30.7, and `gemma4:12b` (7.6GB) installed specifically to
fit in 16GB RAM. The crash is gone — `gemma4:12b` completes successfully. However, it's
far too slow on this hardware: warm eval was **68.9s for a 1-sentence response (~1.8 tok/s)**,
vs. ~12s for a full synopsis with `dolphin-uncensored`. The 7.6GB model doesn't fit the
4GB GPU (RTX 3050 Laptop) and runs mostly on CPU. At that rate a synopsis would take
1-2 minutes — well past the 25s `SYNOPSIS_TIMEOUT_SECS`.
**Decision (superseded 2026-06-10)**: `SYNOPSIS_MODEL` stays `uandinotai/dolphin-uncensored:latest`
(2GB, ~12s/synopsis).
**Action**: If a smaller/quantized gemma variant becomes available that fits in ~4GB VRAM
(e.g. a Q4 quant under ~4GB), re-test. Otherwise no further action — dolphin-uncensored
quality has been acceptable in spot checks.

---

### SYNOPSIS_MODEL swapped: dolphin-uncensored → dolphin3 (2026-06-10)
**Reason**: James flagged the "uncensored" branding on `uandinotai/dolphin-uncensored:latest`
as a liability concern — it could be used against the project ("look, they shipped an
uncensored model"). Investigated alternatives:
- `tinydolphin:latest` (636MB, 1.1B params) — very fast (~4s, 433 tokens, ~107 tok/s) but
  ignores formatting instructions: produced "Title:/Subtitle:/Book Synopsis:" headers and
  5 separate paragraphs despite an explicit "no headings, single paragraph" instruction.
  Too small to follow instructions reliably for this use case.
- `dolphin3:latest` (4.9GB, ~8B params) — ~9s for a 79-token synopsis, single clean
  paragraph, no headers/preamble, followed instructions perfectly. Slightly faster than
  dolphin-uncensored and noticeably better instruction-following, with no "uncensored"
  naming.

**Decision**: `SYNOPSIS_MODEL` = `dolphin3:latest` (4.9GB). Updated `ensure_ollama.py`
REQUIRED_MODELS, `doc_search.py` (SYNOPSIS_MODEL, SYNOPSIS_TIMEOUT_SECS bumped 25→30s as a
margin for the larger model), README.md, and INSTALL.md accordingly.
**Total model footprint**: ~274MB (nomic-embed-text) + ~4.9GB (dolphin3) ≈ 5.2GB.

---

## Settings: modal → standalone page (2026-06-10)
**Decision**: Settings UI moved from `#settingsModal` (`.modal-overlay`/`.modal` in index.html) to a
standalone page `settings.html`, served at new route `GET /settings` in `doc_search.py`. Gear icon
(`#gearBtn`) now does `onclick="window.open('/settings', '_blank')"` instead of opening a modal.
**Why**: As Ignored Directories + dir-browser were added, the modal's nested-scroll layout became
unmanageable (Save/Cancel buttons could be pushed off-screen depending on viewport and dir-browser
state). A full page gives both panels (General config, Ignored Directories) the full viewport with
no nested scrolling.
**What changed**:
- New `settings.html` — self-contained page (own theme toggle/localStorage, own CSS incl.
  `.dir-browser { max-height:45vh }`, `.list-box { max-height:240px }`), "← Back to search" link to `/`.
  Settings JS (loadConfig/saveConfig/dir-browser/ignore-dirs functions) ported in, with `saveConfig()`
  now re-loading config in place instead of closing a modal.
- `doc_search.py`: added `elif path == '/settings': self.serve_file('settings.html')` in `do_GET`,
  right after the `/` route.
- `index.html`: removed `#settingsModal` markup block, removed all settings-related JS functions
  (openSettings, closeSettings, saveConfig, dir-browser/ignore-dir helpers, ~170 lines), removed
  now-dead CSS (`.field-row`, `.browse-btn`, `.btn-primary`, `.config-status`, `.save-msg`,
  `.dir-browser*`, `.list-box*`, `.add-btn*`, `.remove-btn*`). Kept `.modal`/`.modal-actions`/
  `.btn-secondary` (still used by synopsis and delete modals).
- `.dir-browser { max-height: min(320px, 35vh) }` fix (from the prior dir-browser sizing bug) carried
  forward into settings.html's own (larger, 45vh) version since it's now a full page.
**Verified**: Playwright at default viewport — `/` and `/settings` both load with zero console errors;
dir-browser opens correctly (405px height, 59 entries) on the settings page; both panels render without
nested scroll. QA: PASS.
**Commits**: c62231b (refactor), 65b2d1a (cleanup — see below).
**Follow-up (pending, not yet specified)**: James said "a bunch of UI tweaks needed but the functionality
is spot on" for the new settings page — specifics to be gathered in a future session.
**Stale doc**: README.md screenshot `screenshots/screenshot-settings-modal.png` shows the old modal and
needs to be regenerated against `/settings` (and likely renamed).

### Cleanup: accidental test-artifact commit (2026-06-10)
**What happened**: First commit of the settings-page refactor (c62231b) used `git add -A` and
inadvertently included 12 `.playwright-mcp/*.yml` files and 4 PNG screenshots
(settings_1280x720_scrolled.png, settings_after_nav.png, settings_browser_open.png,
settings_page_full.png).
**Fix**: `git rm --cached` on those paths, deleted the local files, added `.playwright-mcp/` and
`*.png` to `.gitignore`, committed as 65b2d1a.
**Note**: `*.png` in `.gitignore` is broad — it only affects untracked files, so existing tracked
README screenshots remain tracked. Future screenshots intended for docs must be added with `git add -f`.

### Dir-browser sizing/reachability fix (2026-06-10)
**What happened**: `.dir-browser` in index.html was `max-height: 400px`, which combined with the
ignore-dirs list and other modal content could push the Save/Cancel buttons below the visible modal
area on smaller viewports.
**Fix**: `.dir-browser { max-height: min(320px, 35vh) }`. Verified at 1280x720 (scrollHeight 1035 vs
clientHeight 646 — fully scrollable, Save/Cancel reachable) and 1440x900 (1098 vs 808).
**Commit**: 3861602.
**Note**: superseded in practice by the settings-page move above (no longer a modal), but the fix is
still present in index.html's CSS (now mostly dead) and was ported into settings.html as a larger
(45vh) variant for the full-page layout.

### ignoreDirs config: live mutation confirmed intentional (2026-06-10)
**What happened**: During testing, `/mnt/data/Documents/Visual Studio 2022` was accidentally added to
the live `ignore_dirs.txt` via the UI.
**Resolution**: Disclosed to James; he confirmed "I do want it added yes" — entry stays.

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
| layout=False fallback root cause | RESOLVED. Security_of_Cloud-based_systems.pdf has 22,421 PDF objects for 434 pages (10× normal). Caused by ExifTool metadata updates — each update appends a new xref table without garbage-collecting old objects (/Prev chain). pdfminer (used by pdfplumber) builds a complete object map upfront on open(), hanging on the 22k object traversal. pypdf lazy-loads and opens in 0.05s. Fix: pre-check /Size from xref via pypdf; if > 8,000 objects skip pdfplumber and use pypdf directly. layout=False fallback also kept as secondary mitigation. | 2026-06-09 |
| Scanned PDF detection (pypdf fallback) | pypdf fallback path does not detect scanned PDFs (PyPDF2 has no .images API — would need /XObject inspection). Acceptable: pdfplumber is always present in production; pypdf path is dead code. If pypdf ever becomes primary, revisit. | 2026-06-09 |
| ocr_list_pdfs.txt deduplication | _ocr_list_add() appends without deduplication — repeated scans could produce duplicate lines. OCR processing must handle duplicates. triage_blacklist.py deduplicates on read. | 2026-06-09 |
| Non-PDF files in DB (root cause) | Files came from unfiltered scan #1, not a filter bug. Extension filter was correct. Fix: confirmation prompt for unfiltered scans now shows file-type breakdown before proceeding. | 2026-06-09 |
| Author/subject fields | Added to documents table, FTS index, pdf_extractor, scan_docs, and doc_search scoring (author +0.7, subject +0.5). ISBN stored but NOT FTS-indexed (SSN regex false-positive risk). | 2026-06-09 |
| Scan --limit N | Processes first N unindexed files; mtime check skips already-indexed files before applying limit, so next run naturally resumes from where last run stopped. | 2026-06-09 |
| report subcommand | Walks doc dir, prints extension breakdown (count/percent/size/scannable). No DB changes. | 2026-06-09 |
| pypdf pre-check for bloated PDFs | pdf_extractor reads trailer /Size via pypdf before calling pdfplumber; if >8,000 objects routes to pypdf directly. Fixes ExifTool-bloated PDFs that hang pdfminer at open(). | 2026-06-09 |
| scan-file subcommand | Single-file scan in main process (no executor). Auto-removes from scan_blacklist.txt. Refuses pii_blacklist.txt. Handles scanned PDFs. | 2026-06-09 |
| --file nargs='+' | argparse positional with spaces in path fails when path contains ' - '; changed to --file nargs='+' with " ".join(args.file) so quoting is not required. | 2026-06-09 |
| DB rename docs.db → du-docs.db | Avoids collision with other projects using generic 'docs.db' name. Example file renamed to du-docs.db.example. | 2026-06-09 |
| Delete from UI | GET /api/delete validates path is in DB, deletes from disk, removes from documents + doc_fts. 🗑 icon on result cards with custom confirm modal (Cancel default). FTS5 contentless table requires manual delete of doc_fts rowid — no FK cascade. | 2026-06-09 |
| DOCX extraction | docx_extractor.py using python-docx; extracts paragraphs, tables, core properties (title, author, subject). Integrated into scan_docs.py. | 2026-06-09 |
| Ebook extraction | ebook_extractor.py: ebooklib for EPUB; mobi package + Calibre fallback for MOBI/AZW3; DRM AZW indexed metadata-only (body not searchable without DeDRM_tools). | 2026-06-09 |
| Config read/write | GET /api/config reads first of /etc/docubrowse.config then ./docubrowse.config; POST writes ./docubrowse.config. Settings UI saves docPath, workDir, port. docubrowse.config gitignored. DocSearchHandler.server_port class variable carries actual running port to POST handler so it writes the real port, not DEFAULT_PORT. | 2026-06-09 |
| duplist / dupclean | dup_detect.py: exact dedup via SHA256 (size pre-filter), near-dup via numpy batched cosine + union-find clustering. dupclean TUI: Keep A/B/Both label-based (not numbered), confirm before delete, per-doc commit for disk/DB consistency. FTS5 cleaned manually on delete. 'b' is always Keep B — never skip. | 2026-06-09 |
| ignore subcommand (excluded directories) | ignore_dirs.txt (next to db, gitignored): one absolute dir per line, '#' comments. scan_docs._load_ignore_dirs() loads + resolves entries; scan_directory() drops any rglob'd file under an ignored dir (resolving each candidate first, since ignore_dirs entries are resolved — avoids symlink-path false negatives). New `ignore add\|remove\|list DIR` command: `add` appends to the file AND calls purge_path_prefix() to delete already-indexed docs (path == prefix or LIKE 'prefix/%') from documents (cascades to doc_tags/doc_embeddings via FK) and doc_fts (contentless, manual cleanup by rowid==doc_id). `remove` rewrites/removes the file; user must rescan to re-index. | 2026-06-10 |
| Settings page UI tweaks (1-6) | Removed leftover modal-era max-width restriction (now full-width). Added header "Done" button that saves config then closes the tab (window.close(), falling back to redirecting to / if the tab wasn't opened via window.open). Ignored Directories panel relabeled with description text, "Add a directory to exclude" input row, and "Currently excluded directories" list; each entry has an inline ✕ remove button. Adding a dir now confirms (OK/Cancel) that it will purge already-indexed docs from that path; removing a dir now alerts that a rescan is required to re-index it. | 2026-06-11 |
| Multiple top-level doc directories (deferred) | James wants docPath/General section to support specifying multiple top-level document directories, not just one. Bigger backend/DB change (scan_docs, config schema, settings UI multi-entry list) — deferred to a future session. | 2026-06-11 |
| Handle moved/missing/deleted documents (deferred) | Need a way to detect and handle documents that were moved, deleted, or are missing on disk but not removed by DocuBrowse from the index. Deferred to a future session. | 2026-06-11 |
| Logo icon (deferred) | Add a logo/icon for DocuBrowse (header, favicon, etc.). Deferred — future cosmetic task. | 2026-06-11 |
| Synopsis cold-start error | After a fresh reboot, the first /api/synopsis request often hit the 30s Ollama timeout because the model wasn't loaded into memory yet, surfacing a generic "Synopsis generation failed or timed out" error even though a retry succeeded. generate_synopsis() now returns (text, reason) — reason is "empty"/"timeout"/"error" — SYNOPSIS_TIMEOUT_SECS raised to 90s, and handle_synopsis returns a reason-specific message (timeout: "AI model is still loading after a recent restart..."). | 2026-06-11 |
| Service-unreachable vs network error | If the doc_search.py server itself is down while a page is already loaded, fetch() throws a generic TypeError ("Failed to fetch"), which previously surfaced as a misleading network/internet error. Added friendlyError(e) helper in index.html: TypeError → "Cannot reach the DocuBrowse service. Make sure it is running, then reload this page." Applied across all fetch catch blocks (search, render, filter by letter, load more/prev, synopsis, open file, delete). Verified via Playwright with the server killed. | 2026-06-11 |
| Synopsis loading reassurance | Synopsis modal's "Generating synopsis..." message now updates to reassuring follow-ups at 6s and 25s ("Still working...", "AI model may still be loading...") so a slow cold-start request doesn't look hung. Timers cleared on completion/error. | 2026-06-11 |
