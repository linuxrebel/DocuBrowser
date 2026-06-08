# DocuBrowse — Claude Instructions

## QA Requirement
**Always run the QA agent after making code changes, before telling the user the code is ready to run.**

Spawn it as a general-purpose subagent with:
- The files that were changed
- A summary of what changed and why
- Specific things to verify (picklability, race conditions, API compatibility, etc.)

The QA agent has caught real bugs (e.g. unpicklable nested function passed to ProcessPoolExecutor,
unguarded stat() call in sort key, NameError from conditionally-defined variable). Don't skip it.

## Project Context
- Repo: /home/james/git/AI/DocuBrowse
- Main entry point: docubrowser.py
- Decisions log: status_docs/DECISIONS.md  ← write deferred decisions here
- Status doc: status_docs/project_status.md

## Key Files
- docubrowser.py      — CLI launcher (scan, rescan, embed, start, stop, status)
- scan_docs.py        — PDF/text extraction, ProcessPoolExecutor, progress bar
- embed_docs.py       — Ollama embedding, ThreadPoolExecutor
- pdf_extractor.py    — pdfplumber extraction, MAX_PAGES cap
- hardware_utils.py   — CPU/GPU/RAM detection, worker count formula, wait_for_memory
- doc_search.py       — HTTP search server (port 8643)
- docubrowse_db.py    — SQLite schema

## Development Rules
- Any deferred decision or skipped feature → add to status_docs/DECISIONS.md
- Run QA agent after every set of code changes
- Log file: /var/log/docubrowser.log (falls back to ~/.local/share/docubrowser/docubrowser.log)

## Known Pitfalls & Hard-Won Lessons

### ProcessPoolExecutor
- **Initializer functions must be at module level** — nested functions (defined inside
  another function) cannot be pickled and will raise PicklingError at executor startup.
  `_worker_init` in scan_docs.py must stay at module level for this reason.
- **Workers should ignore SIGINT** — install `signal.signal(signal.SIGINT, signal.SIG_IGN)`
  in the initializer. Without this, Ctrl-C causes every worker to print its own traceback
  before the parent can shut down cleanly.
- **Sliding window pattern** — use `wait(FIRST_COMPLETED)` with `MAX_IN_FLIGHT = workers`
  rather than submitting all futures at once. Bulk-submitting thousands of futures queues
  them all in memory and defeats memory pressure checks.

### Memory Management
- pdfplumber peaks at 3–5 GB per worker for large technical PDFs (not 1.5 GB as initially
  estimated). Formula: `max(1, min(cores, (avail_gb - 4.0) / 4.0, cap=8))`.
  The 4 GB OS reserve prevents the system from being fully consumed.
- Pause/resume thresholds: MEM_PAUSE_PCT=15, MEM_RESUME_PCT=25. These are deliberately
  conservative — by the time we pause, in-flight workers still have active PDFs running.
- `wait_for_memory()` must never print to stdout in the warn zone — it breaks the \r
  progress bar. Warn-zone messages go to the log file only; critical pause goes to stderr.

### PDF Extraction
- MAX_PAGES = 150 in pdf_extractor.py — pdfplumber loads all pages into memory even if
  we only need text up to 5000 chars. Capping at 150 pages gave a large speedup.
- pdfplumber/pdfminer emit harmless color-space warnings to stderr ("Cannot set non-stroke
  color: 2 components..."). Suppress with `contextlib.redirect_stderr(io.StringIO())`
  wrapping the `extract_pdf()` call in the worker.
- Many files with .pdf extension are actually EPUBs or other formats — they fail fast
  with "No /Root object". This is expected; log it and move on.

### Progress Bar
- Use `\r` overwrite mode (not newlines) in TTY. Nothing else should print to stdout
  while the bar is running — failures, warnings, and memory events all go to log/stderr.
- ETA is a simple elapsed-time average. It drifts high as large PDFs are hit after
  fast failures early on. TODO: use a sliding window average (noted in DECISIONS.md).
- ETA display format: switch from `XmYYs` to `Xh Ym` when ETA exceeds 60 min
  (noted in DECISIONS.md, not yet implemented).

### Sort Order
- `to_process.sort(key=_safe_size)` — sort ascending by file size so small/fast PDFs
  complete first. This makes the index useful sooner and the rate display more stable.
- Use a `_safe_size` function with try/except OSError rather than a bare lambda —
  files can disappear between the scan walk and the sort.

### Ctrl-C / KeyboardInterrupt
- Catch KeyboardInterrupt in the executor loop AND in `__main__` as a safety net.
- Workers ignore SIGINT (via initializer). Parent catches it, commits progress, closes
  the DB, and exits cleanly.
- Forcibly killed workers (e.g. `kill <pid>`) leave leaked semaphores behind. Python's
  resource_tracker will print a UserWarning at shutdown and clean them up — harmless.
