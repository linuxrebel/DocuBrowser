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

## Other Known Deferred Decisions

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
| Per-file timeout | SIGALRM = MAX_PAGES × 2s (300s default); prevents corrupt PDF hangs | 2026-06-08 |
| Scan process group | start_new_session=True + SCAN_PID_FILE + os.killpg() for clean kill | 2026-06-08 |
| Semaphore warning suppression | Scan stderr → log file; resource_tracker warnings never reach terminal | 2026-06-08 |
| stopall command | Kills scans + embeds + server; auto-invoked at start of every rescan | 2026-06-08 |
