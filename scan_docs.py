#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
DocuBrowse document scanner and indexer.

Walks a directory tree, extracts content from each file, and upserts
records into the SQLite database.

Parallelism: ProcessPoolExecutor (CPU-bound — PDF text extraction with
pdfplumber releases the GIL and benefits from true multi-core execution).
Workers return plain dicts; all DB writes happen in the main process.

Default workers: min(os.cpu_count(), 8)
"""

import argparse
import itertools
import logging
import os
import signal
import sys
import time
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime
from pathlib import Path

from docubrowse_db import get_db


DEFAULT_EXTENSIONS = [".pdf", ".txt", ".md", ".html"]

# Physical-core-aware default — hyperthreads don't help pdfplumber
try:
    from hardware_utils import recommended_scan_workers, wait_for_memory
    DEFAULT_WORKERS = recommended_scan_workers()
except ImportError:
    DEFAULT_WORKERS = min(os.cpu_count() or 4, 8)
    def wait_for_memory(**kw): return False

# Per-file timeout: 2 generous seconds per page in the MAX_PAGES cap.
# Keeps a single corrupt/looping PDF from blocking the whole scan.
try:
    from pdf_extractor import MAX_PAGES as _MAX_PAGES
except ImportError:
    _MAX_PAGES = 150
_SECS_PER_PAGE   = 2
FILE_TIMEOUT_SECS = _MAX_PAGES * _SECS_PER_PAGE   # default: 300 s (5 min)

# Progress display: compact bar in TTY, verbose per-file when piped/logged
_IS_TTY = sys.stdout.isatty()

# Blacklist: files that have failed extraction are automatically appended here
# and skipped on future scans.  Lives next to the database.
BLACKLIST_FILENAME     = "scan_blacklist.txt"
PII_BLACKLIST_FILENAME = "pii_blacklist.txt"


def _load_blacklist(db_path: Path, filename: str = BLACKLIST_FILENAME) -> set:
    """Load the set of blacklisted absolute paths from a blacklist file.
    
    Works for both scan_blacklist.txt and pii_blacklist.txt — same format.
    """
    bl_path = db_path.parent / filename
    if not bl_path.exists():
        return set()
    paths = set()
    for line in bl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            paths.add(line)
    return paths


def _blacklist_add(db_path: Path, file_path: str, reason: str) -> None:
    """Append a failed file to the blacklist with a timestamped comment."""
    bl_path = db_path.parent / BLACKLIST_FILENAME
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"# Added {timestamp} — {reason}\n{file_path}\n"
    with open(bl_path, "a", encoding="utf-8") as fh:
        fh.write(entry)


def _worker_init():
    """Module-level so ProcessPoolExecutor can pickle it. Workers ignore
    SIGINT — the parent process handles Ctrl-C and shuts down cleanly.

    Resource limits (kernel-enforced, bypass Python signal handler issues):
      RLIMIT_AS  — virtual address space cap; malloc() fails with MemoryError
                   when pdfplumber tries to exceed it, even inside C extensions.
      RLIMIT_CPU — CPU-time cap; OS sends SIGXCPU → worker dies; executor
                   raises BrokenProcessPool on that future (caught in loop).
    SIGALRM is unreliable for C-heavy workloads (signal deferred until Python
    eval loop regains control, which never happens in tight C loops).
    """
    import resource
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    # 6 GB virtual address space cap per worker.  When pdfplumber/pdfminer's
    # C extensions exceed this, malloc() fails.  Deep C code typically does
    # NOT propagate this as a Python MemoryError — it usually crashes the
    # worker process with SIGSEGV or SIGBUS.  That causes BrokenProcessPool
    # on the associated future, which _handle_result catches.
    _6GB = 6 * 1024 ** 3
    try:
        resource.setrlimit(resource.RLIMIT_AS, (_6GB, _6GB))
    except (ValueError, OSError):
        pass   # ignore if already lower or unsupported

    # RLIMIT_CPU is a TOTAL LIFETIME CPU budget for the worker process, not
    # a per-file limit.  We set it generously (10× FILE_TIMEOUT_SECS) as a
    # last-resort backstop for a completely runaway worker, not as a per-file
    # timer.  Per-file timing is handled by SIGALRM in _extract_file (for
    # pure-Python paths) and RLIMIT_AS (for C-extension paths).
    _cpu_limit = FILE_TIMEOUT_SECS * 10
    try:
        resource.setrlimit(resource.RLIMIT_CPU,
                           (_cpu_limit, _cpu_limit + 5))
    except (ValueError, OSError):
        pass


def _setup_scan_logger() -> tuple:
    """
    Set up a file logger for per-file scan results.
    Tries /var/log/docubrowser.log first (needs root), then
    ~/.local/share/docubrowser/docubrowser.log as fallback.
    Returns (logger, log_path_str).
    """
    logger = logging.getLogger("docubrowse.scan")
    if logger.handlers:
        # Already configured — return the path from the first FileHandler
        for h in logger.handlers:
            if isinstance(h, logging.FileHandler):
                return logger, h.baseFilename
        return logger, None
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    for log_path in [
        Path("/var/log/docubrowser.log"),
        Path.home() / ".local/share/docubrowser/docubrowser.log",
    ]:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(str(log_path), encoding="utf-8")
            fh.setFormatter(logging.Formatter(
                "%(asctime)s  %(levelname)-7s  %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
            logger.addHandler(fh)
            return logger, str(log_path)
        except (PermissionError, OSError):
            continue

    logger.addHandler(logging.NullHandler())
    return logger, None


def _progress_bar(completed: int, total: int, start_time: float, errors: int = 0) -> str:
    """Return a compact \\r progress line for interactive TTY display."""
    elapsed = time.time() - start_time + 0.001
    pct     = completed * 100 // total
    width   = 25
    filled  = width * completed // total
    bar     = "█" * filled + "░" * (width - filled)
    rate    = completed / elapsed
    remain  = (total - completed) / rate if rate > 0 else 0
    eta     = (f"{int(remain // 60)}m{int(remain % 60):02d}s"
               if remain > 60 else f"{remain:.0f}s")
    err_str = f"  \033[91m{errors} err\033[0m" if errors else ""
    return (
        f"\r  [{bar}] {pct:3d}%  {completed}/{total}"
        f"  {rate:.1f}/s  ETA {eta}{err_str}  "
    )


# ── Worker function (runs in subprocess — NO sqlite3 here) ───────────────────

def _extract_file(args: tuple) -> dict:
    """
    Extract text and metadata from one file.
    Runs inside a worker process — must not touch the DB.

    Returns a result dict always; check result['success'] before writing.
    """
    file_path_str, doc_dir_str = args
    file_path = Path(file_path_str)
    doc_dir   = Path(doc_dir_str)

    base = {
        "path":    file_path_str,
        "name":    file_path.name,
        "success": False,
        "error":   None,
    }

    # Per-file SIGALRM timeout — prevents a corrupt/looping PDF from
    # blocking the worker indefinitely.  Scaled to the MAX_PAGES cap.
    def _alarm_handler(signum, frame):
        raise TimeoutError(
            f"timed out after {FILE_TIMEOUT_SECS}s "
            f"(>{_MAX_PAGES}-page budget @ {_SECS_PER_PAGE}s/page)"
        )
    signal.alarm(0)   # defensive cancel of any stale alarm
    signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(FILE_TIMEOUT_SECS)

    try:
        ext = file_path.suffix.lower()

        if ext == ".pdf":
            import contextlib, io
            from pdf_extractor import extract_pdf, generate_keywords
            # pdfminer/pdfplumber emit harmless color-space warnings to stderr;
            # suppress them in the worker process so they never reach the terminal.
            with contextlib.redirect_stderr(io.StringIO()):
                result = extract_pdf(str(file_path))
        else:
            result = _extract_text_file(file_path)

        if not result["success"]:
            base["error"] = result.get("error") or "extraction failed (no detail available)"
            return base

        # Compute file stats
        stat        = file_path.stat()
        size_bytes  = stat.st_size
        modified_at = datetime.fromtimestamp(stat.st_mtime).isoformat()

        # Auto-generate tags
        tags = set()
        tags.add(ext.lstrip("."))                             # extension
        for parent in file_path.parents:                     # folder names
            if parent == doc_dir:
                break
            name = parent.name.lower()
            if len(name) > 2:
                tags.add(name)

        if ext == ".pdf":
            from pdf_extractor import generate_keywords
            keywords = generate_keywords(
                result.get("text", ""), result.get("title", ""), max_keywords=5
            )
            tags.update(keywords)

        return {
            **base,
            "success":     True,
            "size_bytes":  size_bytes,
            "file_ext":    ext,
            "title":       result.get("title") or file_path.stem,
            "author":      result.get("author"),
            "subject":     result.get("subject"),
            "description": result.get("description", ""),
            "snippet":     result.get("snippet", ""),
            "text":        result.get("text", ""),
            "modified_at": modified_at,
            "tags":        sorted(tags),
        }

    except TimeoutError as exc:
        base["error"] = str(exc)
        return base
    except Exception as exc:
        base["error"] = str(exc)
        return base
    finally:
        signal.alarm(0)   # always cancel the alarm


def _extract_text_file(file_path: Path) -> dict:
    """Extract plain text from .txt / .md / .html files."""
    result = {
        "title": file_path.stem,
        "author": None,
        "description": "",
        "text": "",
        "snippet": "",
        "success": False,
        "error": None,
    }
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        if file_path.suffix.lower() == ".html":
            import re, html as html_mod
            text = re.sub(r"<script[^>]*>.*?</script>", "", text,
                          flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<style[^>]*>.*?</style>",  "", text,
                          flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", "", text)
            text = html_mod.unescape(text)
        result["text"]    = text[:5000]
        result["snippet"] = text[:500]
        result["success"] = bool(result["text"])
        return result
    except Exception as exc:
        result["error"] = str(exc)
        return result


# ── DB write helper (main process only) ──────────────────────────────────────

def _write_result(conn, result: dict, doc_dir: Path):
    """Insert or update one document record. Returns doc_id or None."""
    doc_id = None
    try:
        cursor = conn.execute(
            """INSERT OR REPLACE INTO documents
               (name, path, size_bytes, file_ext, title, author, subject,
                description, content_snippet, modified_at, indexed_at, doc_type, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result["name"],
                result["path"],
                result["size_bytes"],
                result["file_ext"],
                result["title"],
                result.get("author"),
                result.get("subject"),
                result.get("description", ""),
                result.get("snippet", ""),
                result["modified_at"],
                datetime.now().isoformat(),
                result["file_ext"].lstrip("."),
                datetime.now().isoformat(),
            ),
        )
        doc_id = cursor.lastrowid

        # Tags
        for tag in result.get("tags", []):
            conn.execute(
                "INSERT OR IGNORE INTO doc_tags (doc_id, tag, source) VALUES (?, ?, 'auto')",
                (doc_id, tag.lower()[:50]),
            )

        # FTS
        tags_str = " ".join(result.get("tags", []))
        conn.execute(
            """INSERT OR REPLACE INTO doc_fts
               (rowid, name, title, author, subject, description, tags, content_snippet)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                doc_id,
                result["name"],
                result.get("title", ""),
                result.get("author") or "",
                result.get("subject") or "",
                result.get("description", ""),
                tags_str,
                result.get("snippet", ""),
            ),
        )
        return doc_id
    except Exception as exc:
        print(f"  DB ERROR for {result['name']}: {exc}", file=sys.stderr)
        return None


# ── Main scan function ────────────────────────────────────────────────────────

def scan_directory(
    doc_dir: str,
    db_path: str,
    extensions: list = None,
    workers: int = DEFAULT_WORKERS,
    limit: int = None,
):
    """
    Scan *doc_dir* for documents and upsert them into *db_path*.

    Args:
        doc_dir:    Root directory to scan recursively
        db_path:    SQLite database path
        extensions: File extensions to process (default: pdf, txt, md, html)
        workers:    Worker processes for extraction (default: cpu_count capped at 8)
        limit:      If set, process at most this many unindexed files; next run resumes
    """
    doc_dir = Path(doc_dir)
    if not doc_dir.exists() or not doc_dir.is_dir():
        print(f"ERROR: Directory not found: {doc_dir}")
        sys.exit(1)

    if extensions is None:
        extensions = DEFAULT_EXTENSIONS
    extensions = [e if e.startswith(".") else f".{e}" for e in extensions]

    db_path = Path(db_path)
    conn = get_db(str(db_path))
    _log, _log_path = _setup_scan_logger()
    if _log_path:
        print(f"Log:      {_log_path}")

    # Load both blacklists — scan failures and PII-flagged files are both skipped.
    # pii_blacklist.txt is permanent; scan_blacklist.txt entries can be removed to retry.
    scan_bl = _load_blacklist(db_path, BLACKLIST_FILENAME)
    pii_bl  = _load_blacklist(db_path, PII_BLACKLIST_FILENAME)
    blacklist = scan_bl | pii_bl
    if scan_bl:
        print(f"Scan blacklist: {len(scan_bl):,} file(s)  ({db_path.parent / BLACKLIST_FILENAME})")
    if pii_bl:
        print(f"PII blacklist:  {len(pii_bl):,} file(s)  ({db_path.parent / PII_BLACKLIST_FILENAME})")

    # Collect candidate files (respects extensions)
    print(f"Scanning  {doc_dir}")
    print(f"Extensions: {', '.join(extensions)}")
    print(f"Workers:  {workers}")
    print()

    all_files = sorted(
        f for f in doc_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in extensions
    )
    print(f"Found {len(all_files):,} files — checking which need indexing...")

    # Fast "already up-to-date?" check in the main process
    existing = {
        row[0]: row[1]
        for row in conn.execute("SELECT path, modified_at FROM documents").fetchall()
    }

    to_process = []
    skipped    = 0
    blacklisted = 0
    for f in all_files:
        if str(f) in blacklist:
            blacklisted += 1
            continue
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime).isoformat()
        except OSError:
            mtime = None
        prev_mtime = existing.get(str(f))
        if prev_mtime and mtime and prev_mtime >= mtime:
            skipped += 1
            continue
        to_process.append(f)

    # Sort smallest-first: quick wins early, memory monsters at the end.
    # Guard with try/except in case a file disappears between scan and sort.
    def _safe_size(f):
        try:
            return f.stat().st_size
        except OSError:
            return 0
    to_process.sort(key=_safe_size)

    # Apply --limit: cap how many files are processed this run.
    # Already-indexed files were skipped above, so the next run naturally
    # resumes from where this one left off.
    total_queued = len(to_process)
    if limit is not None and limit < total_queued:
        to_process = to_process[:limit]

    print(f"  {blacklisted:,} blacklisted (skip — {len(scan_bl)} scan failures, {len(pii_bl)} PII)")
    print(f"  {skipped:,} already up-to-date (skip)")
    if limit is not None and limit < total_queued:
        print(f"  {len(to_process):,} to extract (--limit {limit}; {total_queued - limit:,} deferred to next run)")
    else:
        print(f"  {len(to_process):,} to extract")
    print()

    if not to_process:
        print("Nothing to do.")
        conn.close()
        return

    start_time = time.time()
    extracted  = 0
    failed     = 0
    completed  = 0
    total      = len(to_process)

    work_items = [(str(f), str(doc_dir)) for f in to_process]

    # Sliding-window executor: keep at most `workers` futures in-flight —
    # one per worker slot, no extra queuing.  Memory is checked BEFORE each
    # individual submit so we never hand a new PDF to a worker when RAM is low.
    MAX_IN_FLIGHT = workers   # match exactly to worker count, no pre-queue
    work_iter     = iter(work_items)
    in_flight     = {}   # future -> filename
    width         = len(str(total))

    def _fill_queue(executor):
        """Submit one new future per available worker slot, checking RAM first."""
        slots = MAX_IN_FLIGHT - len(in_flight)
        for item in itertools.islice(work_iter, slots):
            wait_for_memory(is_tty=_IS_TTY, logger=_log)
            f = executor.submit(_extract_file, item)
            in_flight[f] = item[0]

    def _handle_result(future, fname="unknown"):
        nonlocal completed, extracted, failed
        completed += 1

        # Worker killed by RLIMIT_AS (SIGSEGV/SIGBUS) or RLIMIT_CPU (SIGXCPU)
        # raises BrokenProcessPool on the future.  Re-raise after logging so
        # the executor loop can detect a fully broken pool and bail out.
        try:
            result = future.result()
        except BrokenProcessPool:
            failed += 1
            _log.error("KILLED (resource limit)  %s", fname)
            _blacklist_add(db_path, fname, "killed by resource limit (RLIMIT_AS/RLIMIT_CPU)")
            if _IS_TTY:
                print(_progress_bar(completed, total, start_time, failed),
                      end="", flush=True)
            raise   # let executor loop decide whether pool is recoverable
        except Exception as exc:
            failed += 1
            _log.error("FUTURE ERROR  %s  —  %s", fname, exc)
            _blacklist_add(db_path, fname, f"future error: {exc}")
            if _IS_TTY:
                print(_progress_bar(completed, total, start_time, failed),
                      end="", flush=True)
            return

        name   = result["name"]
        label  = f"[{completed:>{width}}/{total}]"

        if result["success"]:
            doc_id = _write_result(conn, result, doc_dir)
            if doc_id is not None:
                extracted += 1
                _log.info("OK  %s  (%d tags)", name, len(result.get("tags", [])))
            else:
                failed += 1
                _log.error("DB ERROR  %s", name)
        else:
            failed += 1
            _log.warning("FAILED  %s  —  %s", name, result["error"])
            _blacklist_add(db_path, result["path"], f"extraction failed: {result['error']}")

        # Terminal output: progress bar only (TTY) or nothing per-file (non-TTY)
        if _IS_TTY:
            print(_progress_bar(completed, total, start_time, failed),
                  end="", flush=True)

        if completed % 50 == 0:
            conn.commit()

    try:
        with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init) as executor:
            _fill_queue(executor)   # prime initial batch

            while in_flight:
                done, _ = wait(list(in_flight.keys()), return_when=FIRST_COMPLETED)
                for future in done:
                    fname = in_flight.pop(future, "unknown")
                    try:
                        _handle_result(future, fname)
                    except BrokenProcessPool:
                        # Worker died (resource limit). Log and commit progress.
                        # If the pool is still alive, _fill_queue will submit
                        # to a replacement worker; if fully broken, executor.submit
                        # will raise BrokenProcessPool and the outer handler fires.
                        _log.error("Executor broken — all workers died. "
                                   "Committing progress and stopping.")
                        conn.commit()
                        raise
                _fill_queue(executor)
    except BrokenProcessPool:
        if _IS_TTY:
            print()
        print(f"\nExecutor broken — {extracted} extracted, {failed} failed. "
              f"Progress saved. Re-run to continue.")
        conn.close()
        sys.exit(1)
    except KeyboardInterrupt:
        if _IS_TTY:
            print()  # move past progress bar
        print(f"\nInterrupted — {extracted} extracted, {failed} failed.")
        conn.commit()
        conn.close()
        sys.exit(0)

    # Clear progress bar line before summary
    if _IS_TTY:
        print()

    conn.commit()

    # Log scan
    try:
        conn.execute(
            "INSERT INTO scan_log (scanned_at, docs_found, docs_added, docs_updated) VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(), total + skipped, extracted, skipped),
        )
        conn.commit()
    except Exception as exc:
        print(f"  WARNING: could not write scan_log: {exc}", file=sys.stderr)

    conn.close()

    elapsed = time.time() - start_time
    print()
    print("=" * 60)
    print("SCAN SUMMARY")
    print("=" * 60)
    print(f"  Workers:    {workers}")
    print(f"  Found:      {len(all_files):,}")
    print(f"  Skipped:    {skipped:,}  (not modified)")
    print(f"  Extracted:  {extracted:,}")
    print(f"  Failed:     {failed:,}")
    print(f"  Time:       {elapsed:.1f}s")
    if extracted > 0:
        print(f"  Speed:      {extracted / elapsed:.1f} docs/sec")


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        description="Scan a directory and index documents into DocuBrowse",
    )
    p.add_argument("doc_dir",  help="Directory containing documents to scan")
    p.add_argument("db_path",  nargs="?",
                   default="/mnt/data/git/AI/DocuBrowse/docs.db",
                   help="Path to SQLite database (default: docs.db in repo)")
    p.add_argument("--ext",    nargs="+", default=None,
                   metavar="EXT",
                   help="Extensions to index (default: pdf txt md html)")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                   help=f"Worker processes for extraction (default: {DEFAULT_WORKERS})")
    p.add_argument("--limit", type=int, default=None, metavar="N",
                   help="Process at most N unindexed files this run; next run resumes from where this left off")
    return p


if __name__ == "__main__":
    # Required for ProcessPoolExecutor on all platforms
    import multiprocessing
    multiprocessing.freeze_support()

    args = build_parser().parse_args()
    try:
        scan_directory(
            args.doc_dir,
            args.db_path,
            extensions=args.ext,
            workers=args.workers,
            limit=args.limit,
        )
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
