# DocuBrowse — Claude Instructions

## Communication Style
After reading status docs or context files, do NOT summarize or repeat back what was learned unless James explicitly asks. Just confirm you're up to date and ask what to work on.

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
- docubrowser.py      — CLI launcher (scan, rescan, embed, start, stop, stopall, status)
- scan_docs.py        — PDF/text extraction, ProcessPoolExecutor, progress bar, blacklist
- embed_docs.py       — Ollama embedding, ThreadPoolExecutor
- pdf_extractor.py    — pdfplumber extraction, MAX_PAGES cap
- hardware_utils.py   — CPU/GPU/RAM detection, worker count formula, wait_for_memory
- doc_search.py       — HTTP search server (port 8643)
- docubrowse_db.py    — SQLite schema
- scan_blacklist.txt  — auto-populated list of files that failed extraction (skip on rescan)
- pii_blacklist.txt   — files removed by `purge` command for containing PII (never ingest; separate from scan_blacklist.txt so users can't accidentally re-enable them)
- purge_pii.py        — PII scanner/purger; detects SSN, CC, DOB, MRN, DL, Passport in stored description/snippet; --dry-run flag; all-or-nothing transaction; writes pii_blacklist.txt only after successful commit

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
- Scan stderr is redirected to the log file (in docubrowser.py's Popen call) so
  resource_tracker warnings never appear on the terminal when `stopall` is used.

### Worker Timeouts — SIGALRM Does Not Work in C Extensions
- **SIGALRM is unreliable for pdfplumber/pdfminer** — Python's signal handler only runs
  between bytecodes. If the C extension is in a tight loop (e.g. spatial layout analysis
  on a complex PDF), SIGALRM fires at the OS level but Python never acts on it.
  Confirmed: a worker ran 16+ minutes past its 300s SIGALRM timeout.
- **Use `resource.setrlimit()` instead** — kernel-enforced, bypasses Python entirely:
  - `RLIMIT_AS = 6 GB` — caps virtual address space. Deep C code that exceeds this
    typically crashes the worker with SIGSEGV/SIGBUS (not MemoryError). Executor raises
    `BrokenProcessPool` on the associated future.
  - `RLIMIT_CPU = FILE_TIMEOUT_SECS * 10` — total lifetime CPU budget (NOT per-file).
    Acts as last-resort backstop for a completely runaway worker process.
- Set both limits in `_worker_init()` (module-level, runs inside the worker process).
- **BrokenProcessPool must be caught** — when a worker is killed by resource limits,
  `future.result()` raises `BrokenProcessPool`. Catch it in `_handle_result`, log it,
  auto-blacklist the file, and re-raise so the executor loop can detect a fully broken pool.
- **Capture filename BEFORE `del in_flight[future]`** — use `in_flight.pop(future, "unknown")`
  and pass `fname` explicitly to `_handle_result(future, fname)`. After del, the lookup
  returns "unknown" — a real bug that was caught by QA.

### Scan Blacklist
- `scan_blacklist.txt` lives next to the DB. One absolute path per line; `#` = comment.
- Loaded at scan start; blacklisted files are skipped before queuing.
- **Auto-populated**: any file that fails extraction (BrokenProcessPool, future error, or
  `result['success'] == False`) is automatically appended with a timestamp and reason.
- To retry a file: remove its line from the blacklist. It will be re-scanned on next run.
- Pre-seeded with `Security_of_Cloud-based_systems.pdf` (spread-layout PDF — two logical
  pages side-by-side per PDF page; causes pathological pdfplumber memory use).

### Spread-Layout PDFs
- PDFs with two pages rendered side-by-side on a single wide canvas cause pdfplumber's
  spatial layout analysis to enter a pathological state (8+ GB RAM, infinite runtime).
  The file appears valid in PDF readers — the issue is structural, not corruption.
- Detection: page width > ~850 points (standard = 612). Check with `pdfinfo`.
- Conversion tool: `mutool poster -x 2 input.pdf output.pdf` splits each spread page
  into two standard pages. After conversion, remove from blacklist and rescan.
- Future fix: pre-screen page dimensions with `pdfinfo` before handing to pdfplumber;
  pass `layout=False` to `extract_text()` for spread-layout files as a lightweight fallback.

### Process Management
- `start_new_session=True` in Popen gives the scan its own PGID.
- SCAN_PID_FILE (`/var/run/docubrowser/docubrowse_scan.pid`, falls back to `~/.local/share/docubrowser/` if unwritable) stores the PGID for group kill.
- PID_FILE (`/var/run/docubrowser/docubrowser.pid`) and LOG_FILE (`/var/log/docubrowser/docubrowser.log`) follow the same fallback pattern via `_pick_runtime_path()`.
- `systemd/docubrowser.service` — system unit that runs `doc_search.py` directly (not via `docubrowser.py start`), using `RuntimeDirectory=docubrowser` and `LogsDirectory=docubrowser` so systemd creates `/run/docubrowser` and `/var/log/docubrowser` owned by `User=james`. Install with `sudo cp systemd/docubrowser.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now docubrowser.service`.
- `_stop_running_scans()` uses `os.killpg(pgid, SIGTERM)` to kill parent + all workers.
- `cmd_stopall()` kills scans, embeds, and server in one command.
- Every `rescan` auto-calls `_stop_running_scans()` first — no zombie workers.
