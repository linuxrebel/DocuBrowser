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
| Multiple top-level doc directories — RESOLVED (2026-06-13) | Originally wanted docPath/General to support specifying multiple top-level document directories. Confirmed already fully implemented: `resolve_doc_dirs()` in docubrowser.py returns the unified ordered list (config docPath + scan_dirs.txt, deduped), and `cmd_rescan`/`cmd_scan` loop over every directory into the single shared DB, running embedding once at the end. Settings UI (General panel) manages the full list via /api/scan-dirs. Updated stale `_load_scan_dirs()` docstring in scan_docs.py (previously said "purely informational, does not affect scan, must rescan manually" — no longer true). No remaining backend work. | 2026-06-11 |
| Remove "embedded" count from header — DONE | Header stats now show "N docs · N tags" (removed "N embedded" portion) in index.html `loadStats()`. | 2026-06-13 |
| Handle moved/missing/deleted documents | Two independent checks, no hash-based move/rename detection (bad data shouldn't be preserved on the chance it's a move; true dupes are caught by dup_detect/dupclean once the new copy is indexed by a normal scan). Shared helper `check_missing_path(path)` in docubrowse_db.py classifies a non-existent path as `missing` (an ancestor dir exists with a different st_dev than `/`, proving its filesystem is mounted and the file is genuinely gone — safe to delete) or `unmounted` (ancestor on root's st_dev and looks like an empty non-mountpoint placeholder — leave DB alone, can't verify). Case 1 (interactive): `/api/open` returns `{ok:false,error:"missing"|"unmounted",message}` instead of a generic 404; index.html's `openFile()` shows a toast for `unmounted`, or for `missing` shows an OK-dismiss modal (`showMissingDocModal`) explaining the doc no longer exists, and on dismiss calls `/api/delete` (cascades doc_tags/doc_embeddings via FK, FTS5 row orphaned harmlessly) and fades out the card. Cases 2/3 (scan-time): new opt-in `scan-missing` CLI command (separate from `scan`/`rescan`, not run automatically) iterates every DB row, classifies via `check_missing_path`, deletes `missing` rows (or reports counts only with `--dry-run`), and reports skipped-unmounted/still-present counts without touching the DB for those. Verified via Playwright: inserted test row, confirmed `/api/open` returns `error:"missing"`, search → click → modal appeared with correct path → OK → card removed from results and DB row deleted (cascade confirmed). `scan-missing --dry-run` against the live 7,957-doc DB: 0 deleted, 0 unmounted, all present. Follow-up verification: created an empty placeholder dir on the root filesystem (`/var/tmp/test_unmounted_dir`, same st_dev as `/`, not a mountpoint) and confirmed `check_missing_path()` classifies a missing file under it as `unmounted`; clicking that doc in the UI showed the toast "Cannot verify — the device for this path does not appear to be mounted" with no DB change. Ran `scan-missing` (non-dry-run, real DB) with one `missing` row and one `unmounted` row present: removed the `missing` row, correctly skipped/reported the `unmounted` row untouched ("1 row(s) removed, 1 skipped (unmounted), 7,957 still present"). Test rows and directories cleaned up afterward. | 2026-06-11 |
| Logo icon (deferred) | Add a logo/icon for DocuBrowse (header, favicon, etc.). Deferred — future cosmetic task. | 2026-06-11 |
| Synopsis cold-start error | After a fresh reboot, the first /api/synopsis request often hit the 30s Ollama timeout because the model wasn't loaded into memory yet, surfacing a generic "Synopsis generation failed or timed out" error even though a retry succeeded. generate_synopsis() now returns (text, reason) — reason is "empty"/"timeout"/"error" — SYNOPSIS_TIMEOUT_SECS raised to 90s, and handle_synopsis returns a reason-specific message (timeout: "AI model is still loading after a recent restart..."). | 2026-06-11 |
| Service-unreachable vs network error | If the doc_search.py server itself is down while a page is already loaded, fetch() throws a generic TypeError ("Failed to fetch"), which previously surfaced as a misleading network/internet error. Added friendlyError(e) helper in index.html: TypeError → "Cannot reach the DocuBrowse service. Make sure it is running, then reload this page." Applied across all fetch catch blocks (search, render, filter by letter, load more/prev, synopsis, open file, delete). Verified via Playwright with the server killed. | 2026-06-11 |
| Synopsis loading reassurance | Synopsis modal's "Generating synopsis..." message now updates to reassuring follow-ups at 6s and 25s ("Still working...", "AI model may still be loading...") so a slow cold-start request doesn't look hung. Timers cleared on completion/error. | 2026-06-11 |
| Index bar persistence + Home button | Clicking a letter wiped the alpha index bar because `meta.innerHTML = ...` reassignment overwrote the appended `.index-bar` div. Refactored `renderIndexBar()` into one reusable async function called after every `meta.innerHTML` reassignment (doSearch, filterByLetter, loadMoreTop, loadMorePrev, renderAll), added a "Home" button (first item, left of "0-9", same `.index-btn` style, `onclick="renderAll()"`) so users can return to All Documents from any view including search results, and added `getActiveLetters()` with a cached `/api/letters` fetch. Verified via Playwright across All Documents, letter filter, search results, and Home navigation — 0 console errors. | 2026-06-11 |
| Ignored Directories UX overhaul | Ignored Directories panel: add row now reads "Browse…"/"Add"/"Clear" buttons; browsing live-syncs the displayed path into the `/path/to/exclude` input (no separate "select this" step). Added description text under "Currently excluded directories" explaining the ✕ removes the dir and a rescan brings docs back. Removing a dir now requires an OK/Cancel confirm before proceeding. | 2026-06-11 |
| Additional Scan Directories — consolidated into General panel | Initially added as its own "Additional Scan Directories" panel; James felt this split one goal (managing which directories get scanned) across two places and was confusing alongside the old docPath/workDir "browse"+"select this" UI. Moved the add/browse/list UI for extra scan directories directly under docPath in the General panel (stored in `scan_dirs.txt` via `_load_scan_dirs()`/`SCAN_DIRS_FILENAME` in scan_docs.py, `/api/scan-dirs` GET/POST in doc_search.py — backend unchanged). Also updated docPath's and workDir's "browse" buttons to the same live-sync style (no "select this" button), matching Ignored Directories/scan-dir UX. Adding a scan directory shows a reminder alert with the exact CLI command: `cd "<workDir>" && python3 docubrowser.py scan --doc-dir "<path>" --limit 100` — re-running resumes with the next 100 unindexed files. Removing an entry requires confirm. Verified via Playwright: 0 console errors, docPath/workDir browse live-sync with no "select this", scan-dir add/remove flow works under General. | 2026-06-11 |
| Documentation sync pass (README/INSTALL/User Guide) for item #8 | README.md and INSTALL.md updated to cover `scan-missing`, the `/api/open` 3-way missing/unmounted response, `scan_dirs.txt`, and the moved/missing-doc UI behavior (CLI tables, examples, API docs, file structure, Known Limitations, Recent Changes). `info_docs/DocuBrowse_User_Guide.docx` fully rewritten from v0.5.0 to the current v0.7.2.1 feature set (formats, settings UI, dup tools, scan-missing, ignore/scan dirs, AI synopsis, moved/missing doc handling) via docx-js. James opted to keep the version at v0.7.2.1 for this doc-only pass (no version bump/tag). Logo design exploration (open book+lens, folder+lens, abstract D/scan-beam, db monogram concepts) was reviewed and rejected by James as "too flat" — logo work remains in the "Logo icon (deferred)" row above, now annotated with this feedback for the next attempt. | 2026-06-11 |


---

## Code Quality & Security Assessment (2026-06-12)

Two parallel review agents audited the full codebase: (A) backend Python code quality
(all 14 source files read in full), (B) security + frontend robustness (doc_search.py,
index.html, settings.html, purge_pii.py, docubrowse_db.py, config/list files).
Findings recorded here so nothing is lost. **No fixes applied yet** — this is the
findings log; each item should get its own decision/fix entry as it is addressed.

### CRITICAL

**CQ-C1. Server-side semantic search silently broken — wrong Ollama response key**
`doc_search.py` `embed_text()` (~lines 62-83): POSTs to `/api/embed` with `"input"` but
reads `data.get('embedding')`. That endpoint returns `"embeddings"` (list of lists);
`embed_text()` therefore always returns None. Effect: `mode=semantic` returns zero
results (0.30 threshold filters everything); `mode=both` silently degrades to
keyword-only at 0.3 weight. `embed_docs.py:88` already handles both shapes —
`data.get("embedding") or (data.get("embeddings") or [None])[0]` — proving the bug.
Fix: same dual-key extraction in embed_text; add a startup self-test that embeds a
known string and logs loudly instead of `except Exception: return None`.

**CQ-C2. `dupclean` corrupts disk/DB consistency on its main path**
`docubrowser.py` `cmd_dupclean` (~line 1080): after `Path(path).unlink()` it runs
`DELETE FROM documents` then `DELETE FROM doc_fts WHERE rowid=?`. doc_fts is contentless
(`content=''`, no `contentless_delete=1`) so the FTS delete raises; the except handler
does `conn.rollback()`, which also rolls back the documents delete. Net: file gone from
disk, DB row + tags + embedding survive. Fix: drop the doc_fts DELETE (match
handle_delete's behavior), or recreate the table with contentless_delete=1 (SQLite
>= 3.43) and clean orphans consistently everywhere.

**SEC-C1. CSRF: arbitrary file deletion from any website**
`/api/delete` is a GET with no CSRF token, no Origin/Referer validation, and
`Access-Control-Allow-Origin: *`. Any web page the user visits can fire
`<img src="http://localhost:8643/api/delete?path=...">` — no interaction needed. The
"path must be in DB" check is not a defense: the attacker page can read
`/api/search?q=` cross-origin (thanks to ACAO:*) to enumerate every indexed path first.
Same GET-CSRF vector applies to `/api/open` (spontaneous app launches — exploit-delivery
step) and `/api/config` POST (no Origin check; a text/plain JSON body is a CORS-simple
request that bypasses preflight → port hijack or doc_dir pointed at `/`).
Fix: make all mutating endpoints POST; validate Origin/Referer against
localhost:<port>; add a CSRF token minted into index.html/settings.html.

**SEC-C2. `Access-Control-Allow-Origin: *` on all JSON responses**
`doc_search.py` `json_response`: grants any website JS read access to /api/search,
/api/stats, /api/config — full document index (paths, titles, authors, snippets)
exfiltratable by any page the user visits. Converts CSRF from blind-write to
full-read + targeted-write. Fix: remove the header entirely; the first-party UI is
same-origin and needs no CORS.

### HIGH

**CQ-H1. Search loads the entire corpus per request; FTS5 index is never queried**
`doc_search.py` `handle_search` (~line 300): any non-empty query SELECTs all ~7,500 rows
LEFT JOINed with doc_tags and doc_embeddings (~20+ MB of blobs), then does pure-Python
substring scoring and pure-Python cosine similarity. No query anywhere uses MATCH —
doc_fts is maintained but write-only dead weight; "keyword score" is hand-rolled
substring boosts, not BM25. Fix: keyword path via
`SELECT rowid, bm25(doc_fts) FROM doc_fts WHERE doc_fts MATCH ?`; semantic path via an
in-memory cached embedding matrix + numpy (as dup_detect.find_near_dups already does).
Also fixes the per-tag row explosion from joining doc_tags before GROUP_CONCAT.

**CQ-H2. `INSERT OR REPLACE INTO documents` destroys data on every re-index**
`scan_docs.py` `_write_result` (~line 400): with foreign_keys=ON, OR REPLACE is
delete+insert — new AUTOINCREMENT id, FK cascade silently deletes doc_tags and
doc_embeddings, cached synopsis and created_at lost, old rowid's doc_fts entry becomes a
permanent ghost. A touched-but-unchanged file costs a full re-embed + re-synopsis.
Fix: `INSERT ... ON CONFLICT(path) DO UPDATE SET ...` — preserves id, children,
synopsis, and allows targeting the correct FTS rowid.

**CQ-H3. BrokenProcessPool blacklists the wrong file**
`scan_docs.py` `_handle_result` (~line 540): when a worker dies (RLIMIT_AS/OOM-kill),
ALL in-flight futures raise BrokenProcessPool; the handler blacklists whichever future
it processes first — frequently not the culprit. The real offender stays unblacklisted
and crashes the next run too, blacklisting another innocent file each time.
Fix: on BrokenProcessPool, mark all in-flight files "suspect" without blacklisting;
retry suspects one-at-a-time in a fresh single-worker pool to identify the offender.

**CQ-H4. Scanner holds the WAL write lock up to 50 docs per transaction**
`scan_docs.py` commits every 50 completions (embed_docs.py every 25). sqlite3 opens an
implicit transaction at first INSERT and holds the single WAL writer slot until commit —
minutes during large-PDF stretches. Server writes (synopsis UPDATE, /api/delete, and
init_db()'s per-request commit) block and can fail "database is locked" after 10s.
Fix: commit per document or on a time budget (~2s); stop running init_db per request
(see CQ-M1).

**SEC-H1. No Host header validation — DNS rebinding defeats localhost-only binding**
Server binds localhost but never checks Host. Attacker lures user to attacker.com, then
re-resolves it to 127.0.0.1 — browser sends requests to the local server with a foreign
Host, which is served happily. Combined with ACAO:* this makes the tool remotely
exploitable. Fix: reject any request whose Host is not
localhost:<port> / 127.0.0.1:<port> / [::1]:<port>. Single cheapest mitigation.

**SEC-H2. `/api/browse` is an unauthenticated whole-filesystem directory lister**
`handle_browse`: GET + ACAO:* returns subdirectory listings for ANY path
(`Path(p).expanduser().iterdir()`). Any website can walk /home, /etc, /mnt and
exfiltrate the tree. Dotfiles only hidden cosmetically — `path=/home/james/.ssh` still
lists contents. Fix: Origin/Host validation; optionally constrain to docPath/home.

### MEDIUM

**CQ-M1.** `docubrowse_db.py` `get_db()` → `init_db()` runs full schema executescript,
PRAGMA table_info, up to 10 ALTER attempts, FTS probe, and a commit on EVERY HTTP
request. Makes every read endpoint a writer (lock contention, see CQ-H4) and risks a
server/scanner race both detecting a missing FTS column and concurrently
DROP/CREATE/repopulating doc_fts. Fix: init once at server startup; get_db only sets
pragmas/row_factory.

**CQ-M2.** `docubrowser.py` `read_pid()`: `os.kill(pid,0)` raising PermissionError means
the process EXISTS (other user, e.g. root/systemd) but is treated as stale — PID file
unlinked, cmd_start proceeds to _kill_port against a live instance. Fix: on
PermissionError return the pid; only unlink on ValueError/ProcessLookupError.

**CQ-M3.** `pkill -f scan_docs.py` / `pkill -f embed_docs.py` in _stop_running_scans and
cmd_stopall matches ANY process whose cmdline contains the string — `vim scan_docs.py`
in another terminal gets SIGTERM'd. Fix: rely on the PGID file; if a fallback is needed,
verify /proc/<pid>/cmdline contains the interpreter + script path.

**CQ-M4.** Document-deletion logic is independently re-implemented in 5 places
(handle_delete, dupclean, purge_pii, purge_path_prefix, scan_missing) with divergent
FTS-cleanup and commit policies. Orphaned doc_fts rows are only "harmless" because
search never uses FTS (CQ-H1) — the moment that's fixed, or the migration repopulator
runs, ghosts matter. Fix: one shared delete-document-by-id helper in docubrowse_db.

**CQ-M5.** Mixed timestamp formats break embed staleness checks: code writes
`datetime.now().isoformat()` (local, 'T' separator), column DEFAULTs write
`datetime('now')` (UTC, space). String comparison `'...T...' > '... ...'` is always
true; rows with NULL updated_at (post-ALTER backfill) are NEVER selected for re-embed
(`NULL < x` is NULL). Fix: standardize on UTC ISO; add
`OR de.updated_at IS NULL` to the staleness WHERE.

**CQ-M6.** `purge_pii.run_purge`: abort path returns None (callers expect int) and the
nested `input("Proceed? [y/N]")` raises EOFError uncaught when stdin isn't a TTY
(pipe/cron/systemd) — crash instead of safe abort. Fix: try/except
(EOFError, KeyboardInterrupt) → abort, return 0.

**CQ-M7.** `scan_docs.py` `_extract_text_file` reads entire files (`read_text`) before
truncating to 5,000 chars — a multi-GB .txt/.json burns the worker's 6 GB RLIMIT_AS and
gets the file mis-blacklisted as "killed by resource limit" (compounds CQ-H3).
Fix: read only a bounded prefix (`f.read(200_000)`).

**SEC-M1. Stored XSS via inline onclick attributes (wrong escaping context)**
index.html renderDocs/loadTags/searchTag interpolate esc()'d values into inline JS
handler strings, e.g. `onclick="showSynopsis('${esc(d.path)}', ...)"`. esc() turns ' into
&#39;, but the HTML parser decodes that back to a real quote INSIDE the attribute before
the JS runs — a document titled `'),fetch('/api/delete?...'),('` executes on
render/click. HTML-entity escaping is the wrong escaping for a JS-string context.
Bounded by needing a malicious title/path indexed into the corpus, but real.
Fix: no inline onclick built from data — addEventListener + dataset/closures.

**SEC-M2.** TOCTOU/symlink in delete/open: DB membership is an authorization check, not
a path-safety check; no realpath validation between the DB lookup and os.remove/Popen.
Low real risk single-user, becomes moot once SEC-C1 lands. Fix: realpath + confirm
within docPath before destructive ops.

**SEC confirmations (no findings):** serve_file is only ever called with hardcoded
'index.html'/'settings.html' — no traversal path. SQL injection: none — every query
parameter across all endpoints is parameterized; q is matched in Python; offset/limit
int()-clamped (bare int() can 500 on garbage — nit only). No shell=True anywhere.

### LOW

- **CQ-L1.** `cmd_status`: `f"{stats.get('total_docs','?'):,}"` raises ValueError when
  the key is missing (`,` format spec invalid for str). Default to 0.
- **CQ-L2.** `_kill_port` fuser fallback always returns False even on success → caller
  prints "does not appear to be running" after stopping it. Check fuser's return code.
- **CQ-L3.** `scan-file`: `" ".join(args.file)` collapses runs of multiple spaces in a
  filename. Document or revert to a single quoted arg.
- **CQ-L4.** `_extract_file` folder-tag loop never breaks when the file isn't under
  doc_dir (mismatched --doc-dir) → tags like `mnt`, `data`, `home`. Guard with
  `is_relative_to(doc_dir)`.
- **CQ-L5.** Extension check against a list (O(n) per file); rescan pre-count walks the
  whole tree a second time right before scan_directory walks it again. Use a set; share
  one traversal.
- **CQ-L6.** pdf_extractor pypdf pre-probe opens by path and relies on GC to close the
  handle — fd release delayed in long scans. Open via `with open(p,'rb')`.
- **CQ-L7.** `wait_for_memory()` has no max-wait (can block forever);
  nvidia-smi runs at argparse-build time on every CLI invocation incl. status/stop.
  Lazy-evaluate defaults.
- **CQ-L8.** `handle_open` never reaps Popen → gio/xdg-open zombies; magic number
  `entries[:201]` in handle_browse.
- **CQ-L9.** scan_docs/purge_pii build_parser hardcode personal default DB path
  `/mnt/data/git/AI/DocuBrowse/du-docs.db`, which differs from docubrowser.py's
  `<script dir>/du-docs.db` — direct vs CLI invocation can target different DBs.
- **SEC-L1. PII regex false negatives:** only ~800 chars scanned (description+snippet);
  SSN only dashed form (misses spaced + 9-contiguous); CC only 4-4-4-4 grouped (misses
  16-contiguous and 15-digit Amex; no Luhn); DOB/passport/MRN/DL all require labeled
  prefixes — unlabeled values missed entirely.
- **SEC-L2. PII false positives:** any 4-4-4-4 digit group trips the CC pattern (phone
  sequences, part numbers); MRN/SSN patterns can match invoice numbers. Luhn check
  would largely fix CC both ways.
- **SEC-L3. Frontend nits:** loadMorePrev guard hardcodes 50 while pagination uses
  pageSize (Back button logic inconsistent at 25/100); isLoadingMore guard not applied
  in doSearch/renderAll → fast typing during in-flight loadMoreTop can render stale
  results (last-writer-wins on grid.innerHTML); mixed alert/toast/modal error UX;
  json_response always HTTP 200 even for logical failures (frontend must inspect
  data.ok). localStorage usage clean.

### Duplication / consistency summary
Progress bar duplicated verbatim (scan_docs, embed_docs); blob<->vector pack/unpack
triplicated (doc_search, embed_docs/docubrowse_db, dup_detect); config parsing
duplicated (docubrowser.load_config vs doc_search.handle_config); ignore/scan-dirs file
writes duplicated (CLI vs server); deletion logic in 5 copies (CQ-M4). handle_search is
~200 lines doing parsing + two query strategies + scoring + pagination — split after
CQ-H1.

### Overall assessment
Well-commented, genuinely defensive ops engineering (PGID kill groups, RLIMIT
backstops, WAL + busy timeouts). But both flagship features have silent failures —
server semantic search never works (CQ-C1) and dupclean corrupts consistency on its
main path (CQ-C2) — masked by broad `except Exception` swallowing. Security exposure is
architectural, not injection-based: unauthenticated GET mutations + ACAO:* + no Host
validation mean any visited webpage can enumerate the index, browse the filesystem, and
delete files; DNS rebinding makes it remote.

**Recommended fix order (cheapest high-impact first):**
1. Host header allow-list (SEC-H1) — one localized check, kills rebinding.
2. Remove `Access-Control-Allow-Origin: *` (SEC-C2).
3. Fix embed_text response key (CQ-C1).
4. Drop the doc_fts DELETE in dupclean (CQ-C2).
5. Origin/CSRF validation + move mutations to POST (SEC-C1).
6. Constrain /api/browse (SEC-H2).
7. ON CONFLICT upsert (CQ-H2), then real FTS MATCH + cached embedding matrix (CQ-H1).
8. addEventListener/dataset instead of inline onclick (SEC-M1).

---

## Audit Remediation — Session 2026-06-12 (8 of the above fixed)

Worked the recommended fix order. Each item below is implemented, tested
(curl contract tests + isolated throwaway-DB tests + Playwright UI runs, with
a verification subagent for the DB- and UI-level checks), and committed. The
server was restarted after each batch and remains running on :8643.

**SEC-H1 — Host header allow-list** (`doc_search.py`, commit 9bfe578).
`_host_allowed()` rejects any request whose Host is not localhost / 127.0.0.1
/ [::1] (optional :port must match server_port); called at the top of
do_GET/do_POST. Kills DNS rebinding. Verified: loopback 200, evil.com 403,
wrong-port 403.

**SEC-C2 — Remove ACAO:\*** (`doc_search.py`, commit 9bfe578). Dropped
`Access-Control-Allow-Origin: *` from json_response. No website can read the
index cross-origin. Verified header absent.

**CQ-C1 — embed_text response key** (`doc_search.py`, commit 9bfe578).
Now reads `data.get('embedding') or (data.get('embeddings') or [None])[0]`,
logs failures to stderr, and runs a startup embed self-test. Server-side
semantic search works again. Verified: a semantic query that returned 0
results now returns real cosine scores (0.84, 0.77, ...).

**CQ-C2 — dupclean disk/DB corruption** (`docubrowser.py`, commit 9bfe578).
Removed the `DELETE FROM doc_fts` (raises on the contentless table → rollback
left files deleted on disk but alive in the DB). Now matches handle_delete:
`PRAGMA foreign_keys=ON` + `DELETE FROM documents` (FK cascade cleans
tags/embeddings; FTS orphan harmless). Verified on a throwaway DB: fixed path
deletes file + row + cascades cleanly; old path reproduced the split.

**SEC-C1 — CSRF / mutations to POST + token** (`doc_search.py`, `index.html`,
`settings.html`, commit 84a68d5). Per-process token (`secrets.token_urlsafe`)
injected as `<meta name=csrf-token>` into served HTML; `_guard_mutation()`
requires a matching `X-CSRF-Token` header (constant-time compare) and rejects
non-loopback Origin/Referer. `/api/delete` and `/api/open` moved GET→POST
(GET routes removed); all POST routes guarded. Frontend reads the token into
`CSRF` and sends it (index.html `apiPost()`; settings.html on browse +
config/ignore-dirs/scan-dirs POSTs). Verified: 10/10 contract tests (403
without token, 200 with, old GET 404, evil Origin 403, reads still open) +
Playwright (token read, no console errors, no data touched).

**SEC-H2 — Constrain /api/browse** (`doc_search.py`, commit 84a68d5). The
unauthenticated whole-filesystem lister now runs `_guard_mutation()` — only
the first-party UI (which has the token) can enumerate directories. Verified
403 without token / 200 with.

**CQ-H2 — ON CONFLICT upsert** (`scan_docs.py`, commit 1811125). Replaced
`INSERT OR REPLACE INTO documents` (delete+insert → new id, CASCADE-wiped
tags/embeddings, lost synopsis/created_at, orphaned FTS rowid) with
`INSERT ... ON CONFLICT(path) DO UPDATE SET ...`. doc_id looked up by path
(lastrowid unreliable on the update path); stale doc_tags cleared before
regenerated tags re-inserted. Verified on a throwaway DB with the real
_write_result: across re-index id/created_at/synopsis/embeddings preserved,
content updates apply, tags replaced (no dupes); old path reproduced the loss.

**CQ-H1 — FTS5 BM25 + cached embedding matrix** (`doc_search.py`, commit
2369057). Non-empty queries no longer load the whole corpus + every blob.
Keyword = FTS5 MATCH + `bm25()` with per-column weights echoing the old field
boosts, tokens quoted+prefixed so arbitrary input can't break MATCH.
Semantic = in-process L2-normalized numpy matrix scored with one matrix-vector
product (cache invalidates on embeddings count / max(updated_at)). Scores
merged over id-maps; metadata fetched for the page only. Orphan doc_fts
rowids pruned against a cached live-doc-id set so they can't inflate totals.
Empty-query/letter path unchanged. Verified: keyword ~4ms, both ~55ms;
total ≤ 7,957 (was 7,993); full page-walk == total, no short pages, distinct
pages; Playwright: modes produce distinct relevant sets, toggles+pagination
work, 0 console errors. James chose the full BM25 rewrite over a perf-only
change.

**Still open from the audit (not yet done):** SEC-M1 (inline onclick →
addEventListener), CQ-H3 (BrokenProcessPool mis-blacklist), CQ-H4+CQ-M1
(commit cadence + init_db once per startup), and the Medium/Low sweep
(CQ-M2..M7, SEC-M2, CQ-L1..L9, SEC-L1..L3).

---

## Audit Remediation — Session 2026-06-12, batch 2 (SEC-M1, CQ-H3, CQ-H4/M1, M/L sweep)

Continued the fix order. All items below implemented, tested (isolated
throwaway-DB / subprocess tests + Playwright UI + a real worker-death test,
via verification subagents where DB/UI/concurrency behavior needed proving),
and committed. Server restarted after each batch.

**SEC-M1 — inline onclick → delegated listeners** (`index.html`, commit
735ecff). Doc-card/tag-cloud actions moved from data-interpolated inline
onclick (esc() is the wrong escaping for a JS-string attribute context) to
data-* attributes + delegated click listeners on the grid and tag cloud.
Verified via Playwright: a hostile injected title is stored as inert literal
data (window.__xss never fires), no onclick= in the grid, and synopsis/tag/
open/delete still work with zero console errors.

**CQ-H3 — worker-death suspect isolation** (`scan_docs.py`, commit 340a733).
A killed worker breaks the whole pool; the old loop blacklisted whichever
broken future surfaced first (often innocent) and stopped. Now every
in-flight file becomes a 'suspect', the broken pool is torn down, and each
suspect is re-run in its own single-worker pool — only the file that kills its
dedicated worker is blacklisted; innocents are indexed; the scan resumes.
Verified with a real os._exit worker death: only the bomb blacklisted, all 8
innocents indexed; old logic mis-blacklisted + stalled.

**CQ-M1 + CQ-H4 — init once / commit cadence** (`docubrowse_db.py`,
`scan_docs.py`, `embed_docs.py`, commit a217b66). init_db now runs once per
(process, db_path) via a module-level guard instead of on every connection.
Scanner and embedder commit on a ~2s time budget instead of every 50/25 docs,
so the WAL writer isn't held long enough to block server synopsis/delete
writes. Verified: init_db runs once across 5 same-path get_db calls; a real
2-worker scan of 12 files indexed + durably committed all of them.

**Medium/Low sweep** (commits 1679413, b1265fa):
- CQ-M2 read_pid: PermissionError from os.kill(pid,0) now means "running"
  (process owned by another user), not stale.
- CQ-M3 stop fallback: replaced `pkill -f <script>` (kills `vim scan_docs.py`)
  with a /proc cmdline matcher requiring a python argv[0] + the script path.
  Verified it kills a python scan_docs.py but spares `tail scan_docs.py`.
- CQ-M5 embed staleness: added `OR de.updated_at IS NULL` so NULL-timestamp
  embeddings are re-embedded.
- CQ-M6 purge_pii: non-interactive stdin no longer crashes with EOFError; all
  abort paths return 0 (int).
- CQ-M7 text extract: bounded 200 KB read instead of loading whole file
  (a multi-GB file used to burn RLIMIT_AS and get mis-blacklisted).
- CQ-L1 cmd_status: missing stat keys default to 0 (no ValueError on `:,`).
- CQ-L2 _kill_port: fuser fallback returns its real exit code, not always False.
- CQ-L4 folder tags: is_relative_to(doc_dir) guard stops tagging with
  'mnt'/'data'/'home' when a file isn't under doc_dir.
- CQ-L6 pdf probe: opens via `with open(...)` so the fd is released promptly.
- CQ-L8 handle_open: launcher is reaped via start_new_session + a daemon
  thread proc.wait() (no zombies in the long-lived server).
- CQ-L9 default DB path: scan_docs/purge_pii derive du-docs.db next to the
  script instead of a hardcoded personal path.

### Deferred (audit items intentionally NOT done this pass — reasons logged)
- ~~**CQ-M4 — single shared delete-document helper.**~~ **DONE (2026-06-12,
  commit 31baea8).** Added `delete_documents(conn, ids, commit=True)` and
  `delete_document(conn, id, commit=True)` to docubrowse_db — one place that
  enables foreign_keys, CASCADEs to doc_tags/doc_embeddings, chunks large id
  lists under the bound-variable limit, and documents the contentless-FTS
  orphan policy once. All five callers (handle_delete, dupclean, run_purge,
  purge_path_prefix, scan_missing) route through it; purge_pii passes
  commit=False to keep its all-or-nothing transaction. Verified on a temp DB:
  single delete cascades, bulk delete returns the real removed count,
  commit=False + rollback preserves rows. **Follow-up:** the helper was
  unit-tested directly; the 5 callsites haven't each been re-run end-to-end
  through it — quick verification pass owed next session.
- **SEC-M2 — realpath/symlink check before delete/open.** Largely mooted by
  SEC-C1 (mutations are now POST + CSRF-gated, single-user localhost). Low real
  risk; revisit if multi-user/network exposure is ever added.
- **CQ-L3** scan-file `" ".join` collapses runs of multiple spaces in a
  filename — cosmetic edge case; document or switch to a single quoted arg.
- **CQ-L5** extension membership uses a list (O(n)); rescan pre-count walks the
  tree a second time — perf micro-opt only.
- **CQ-L7** wait_for_memory has no max-wait (can block indefinitely under
  sustained pressure); nvidia-smi runs at argparse-build time on every CLI
  invocation — make defaults lazy. Moderate; deferred.
- ~~**SEC-L1 / SEC-L2 — PII regex coverage + Luhn.**~~ **DONE (2026-06-12, commit
  pending).** purge_pii now validates structural identifiers instead of
  matching shape alone. SSN: dashed + spaced 3-2-4 forms plus a label-gated
  9-contiguous form, validated by SSA allocation rules (area not 000/666/
  900-999, group != 00, serial != 0000, not all-same-digit). Credit card:
  13-19 digit runs (grouped or contiguous, covering Amex-15/MC-2-series/
  Discover/13-digit Visa), validated by length + IIN first digit in "23456" +
  Luhn. Restructured _PII_PATTERNS to (name, regex, validator) and _scan_text
  to validate; passport/DOB/MRN/DL label patterns unchanged. Verified on a
  26-string labeled corpus: 1.0 precision/recall; the old detector missed 9
  true positives (spaced/contiguous/Amex/MC/Discover) and false-flagged 6
  negatives (invoice 4-4-4-4 groups, invalid-area SSNs). Known precision-
  favoring edge case: a PAN immediately glued to a digit-bearing token by a
  single space is declined (IIN reject), not mis-flagged.
- ~~**SEC-L3 — frontend nits.**~~ **PARTLY DONE (2026-06-12, commit pending).**
  Fixed the two real bugs: loadMorePrev's Back guard now uses `<= pageSize`
  (was hardcoded `<= 50`, breaking Back at page sizes 25/100), and a
  request-generation token (`renderSeq`) makes doSearch/renderAll/loadMoreTop/
  loadMorePrev/filterByLetter render only if still the latest request, so a
  fast-typed new search can't be overwritten by a slower in-flight page load.
  The two loadMore error paths switched from blocking alert() to a toast
  (keeps current results visible). Verified via Playwright: Back/Next correct
  at page sizes 25 & 100; a newer 'database' search cleanly superseded an
  in-flight 'kubernetes' page load (final grid 100% database, no stale render),
  0 console errors.
  **Intentionally kept:** json_response returns HTTP 200 with `{ok:false,error}`
  on logical failure — a deliberate "request handled, payload reports outcome"
  design the whole frontend relies on (`if(!res.ok) throw` then inspect
  data.ok); changing to 4xx would rewrite every error path for no real gain.

---

## Installer & remote access (2026-06-13)

**Installer user/system split.** Field-testing the install on a CentOS Stream VM
exposed a half-way install (user mode wrongly created a root systemd unit that
203/EXEC'd from $HOME under SELinux; wrapper in /usr/local/bin with wrong
perms). install.sh was rewritten into two clean modes — USER ($HOME/.docubrowse,
~/.local/bin/docubrowser wrapper, no systemd, `docubrowser start`) and SYSTEM
(/opt/docubrowse, dedicated user, systemd unit, /usr/local/bin wrapper) — with
full up-front pre-flight checks (python>=3.9+venv, rsync/curl/tar, calibre,
ollama, +user/group/systemctl in system mode) that report everything missing
before changing anything. CLI is installed as `docubrowser` (not docubrowser.py).
requirements.txt added (it was referenced but missing; also added numpy /
python-pptx / openpyxl which the code needs). Calibre fallback link documented
for distros without a package (CentOS Stream).

**Opt-in remote (LAN) access.** Default remains localhost-only (bind 127.0.0.1,
firewall untouched). Opt-in via the installer prompt or DOCUBROWSE_ALLOW_REMOTE=1
sets allow_remote=true, binds 0.0.0.0, and opens the firewall (firewalld/ufw);
uninstall closes it. Decisions: Host allow-list still blocks DNS-rebinding in
remote mode (loopback always; this host's own names + IP-literal Hosts only —
attacker domains rejected); the mutation guard was changed from loopback-only to
a same-origin check (Origin/Referer host must equal the addressed Host, or
loopback) so the UI works over the LAN while CSRF protection holds. No
authentication yet — remote access is warned as exposing read/delete to the
network; auth is deferred. A `docubrowser remote on|off|status` command to
toggle this (config+firewall+restart) is planned, not yet built.

**Empty example DB.** du-docs.db.example was shipping with ~100 seeded test rows,
so fresh installs opened pre-populated. Emptied to schema-only (rows deleted,
contentless FTS cleared via 'delete-all', AUTOINCREMENT reset, VACUUMed); first
run is now genuinely empty.
