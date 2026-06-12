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


DEFAULT_EXTENSIONS = [".pdf", ".docx", ".pptx", ".xlsx",
                      ".epub", ".mobi", ".azw", ".azw3",
                      ".txt", ".md", ".html",
                      ".json", ".yml", ".yaml",
                      ".py", ".sh", ".js", ".css",
                      ".rs", ".c", ".h", ".cpp", ".hpp", ".cc",
                      ".go", ".java", ".ts", ".tsx", ".jsx",
                      ".rb", ".php", ".toml"]

_CODE_EXTENSIONS = frozenset({
    ".json", ".yml", ".yaml", ".py", ".sh", ".js", ".css",
    ".rs", ".c", ".h", ".cpp", ".hpp", ".cc",
    ".go", ".java", ".ts", ".tsx", ".jsx",
    ".rb", ".php", ".toml",
})

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
OCR_LIST_FILENAME      = "ocr_list_pdfs.txt"
IGNORE_DIRS_FILENAME   = "ignore_dirs.txt"
SCAN_DIRS_FILENAME     = "scan_dirs.txt"


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


def _load_ignore_dirs(db_path: Path) -> set:
    """Load the set of absolute directory paths excluded from scanning.

    Format: one absolute directory path per line; '#' = comment.
    Lives next to the database (ignore_dirs.txt). Paths are resolved so
    relative/symlinked entries match consistently.
    """
    ig_path = db_path.parent / IGNORE_DIRS_FILENAME
    if not ig_path.exists():
        return set()
    dirs = set()
    for line in ig_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            dirs.add(str(Path(line).expanduser().resolve()))
    return dirs


def _load_scan_dirs(db_path: Path) -> set:
    """Load the set of additional absolute directory paths to scan.

    Format: one absolute directory path per line; '#' = comment.
    Lives next to the database (scan_dirs.txt). These are extra top-level
    directories (outside docPath) the user has earmarked for scanning via
    `docubrowser.py scan --doc-dir <DIR>`. Purely informational/bookkeeping
    for the settings UI — does not affect the default scan of docPath.
    """
    sd_path = db_path.parent / SCAN_DIRS_FILENAME
    if not sd_path.exists():
        return set()
    dirs = set()
    for line in sd_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            dirs.add(str(Path(line).expanduser().resolve()))
    return dirs


def _under_any(path: Path, dirs: set) -> bool:
    """True if *path* is equal to or nested under any directory in *dirs*."""
    for d in dirs:
        try:
            path.relative_to(d)
            return True
        except ValueError:
            continue
    return False


def purge_path_prefix(conn, prefix: str) -> int:
    """Remove all indexed documents whose path is *prefix* or under it.

    Deletes from `documents` (cascades to doc_tags/doc_embeddings via FK).
    doc_fts is a contentless FTS5 table — `DELETE ... WHERE rowid IN (...)`
    is not supported on contentless tables (raises "cannot DELETE from
    contentless fts5 table"). As with handle_delete()'s single-document
    delete, the orphaned doc_fts rows are left in place; they're harmless
    because keyword search always JOINs doc_fts results back to
    `documents`, so a deleted document's row never surfaces. Returns the
    number of documents removed.
    """
    prefix = str(Path(prefix).expanduser().resolve())
    like_pattern = prefix.rstrip("/") + "/%"
    rows = conn.execute(
        "SELECT id FROM documents WHERE path = ? OR path LIKE ?",
        (prefix, like_pattern),
    ).fetchall()
    ids = [r[0] for r in rows]
    if not ids:
        return 0
    conn.execute("PRAGMA foreign_keys=ON")
    qmarks = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM documents WHERE id IN ({qmarks})", ids)
    conn.commit()
    return len(ids)


def _blacklist_add(db_path: Path, file_path: str, reason: str) -> None:
    """Append a failed file to the blacklist with a timestamped comment."""
    bl_path = db_path.parent / BLACKLIST_FILENAME
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"# Added {timestamp} — {reason}\n{file_path}\n"
    with open(bl_path, "a", encoding="utf-8") as fh:
        fh.write(entry)


def _ocr_list_add(db_path: Path, file_path: str) -> None:
    """Append a scanned PDF path to ocr_list_pdfs.txt for future OCR processing."""
    ocr_path = db_path.parent / OCR_LIST_FILENAME
    with open(ocr_path, "a", encoding="utf-8") as fh:
        fh.write(file_path + "\n")


def _blacklist_remove(db_path: Path, file_path: str) -> None:
    """Remove a specific path from scan_blacklist.txt (in-place).
    Removes the path line AND any immediately-preceding comment line that was
    auto-generated by _blacklist_add (the '# Added ...' timestamp comment).
    """
    bl_path = db_path.parent / BLACKLIST_FILENAME
    if not bl_path.exists():
        return
    lines = bl_path.read_text(encoding="utf-8").splitlines(keepends=True)
    out = []
    i = 0
    while i < len(lines):
        # If this line is the blacklisted path, drop it and its preceding comment
        if lines[i].rstrip("\n") == file_path:
            # Remove preceding auto-comment if present
            if out and out[-1].startswith("# Added ") and " — " in out[-1]:
                out.pop()
        else:
            out.append(lines[i])
        i += 1
    bl_path.write_text("".join(out), encoding="utf-8")


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
        elif ext == ".docx":
            from docx_extractor import extract_docx
            result = extract_docx(str(file_path))
        elif ext == ".pptx":
            from pptx_extractor import extract_pptx
            result = extract_pptx(str(file_path))
        elif ext == ".xlsx":
            from xlsx_extractor import extract_xlsx
            result = extract_xlsx(str(file_path))
        elif ext in (".epub", ".mobi", ".azw", ".azw3"):
            from ebook_extractor import extract_ebook
            result = extract_ebook(str(file_path))
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

        if ext in _CODE_EXTENSIONS:
            tags.add("code")

        if ext in (".pdf", ".docx", ".pptx", ".xlsx", ".epub", ".mobi", ".azw", ".azw3"):
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
            "doc_type":    result.get("doc_type", ext.lstrip(".")),
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
        # Upsert on the UNIQUE path. INSERT OR REPLACE would delete+reinsert
        # the row (new id), which under foreign_keys=ON CASCADE-deletes this
        # document's tags and embeddings and discards its cached synopsis and
        # created_at — forcing a needless re-embed/re-synopsis and orphaning
        # the old FTS rowid. ON CONFLICT...DO UPDATE keeps the same id (so the
        # FTS rowid and FK children stay valid) and leaves created_at and
        # synopsis untouched.
        conn.execute(
            """INSERT INTO documents
               (name, path, size_bytes, file_ext, title, author, subject,
                description, content_snippet, modified_at, indexed_at, doc_type, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(path) DO UPDATE SET
                 name=excluded.name,
                 size_bytes=excluded.size_bytes,
                 file_ext=excluded.file_ext,
                 title=excluded.title,
                 author=excluded.author,
                 subject=excluded.subject,
                 description=excluded.description,
                 content_snippet=excluded.content_snippet,
                 modified_at=excluded.modified_at,
                 indexed_at=excluded.indexed_at,
                 doc_type=excluded.doc_type,
                 updated_at=excluded.updated_at""",
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
        # lastrowid is unreliable on the DO UPDATE path — look the id up by path.
        doc_id = conn.execute(
            "SELECT id FROM documents WHERE path = ?", (result["path"],)
        ).fetchone()[0]

        # Tags are fully regenerated each scan; clear stale ones first so the
        # persisted row doesn't accumulate tags that no longer apply.
        conn.execute("DELETE FROM doc_tags WHERE doc_id = ?", (doc_id,))
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

    # Directories excluded entirely from scanning (ignore_dirs.txt)
    ignore_dirs = _load_ignore_dirs(db_path)
    if ignore_dirs:
        print(f"Ignored dirs:   {len(ignore_dirs):,}  ({db_path.parent / IGNORE_DIRS_FILENAME})")

    # Collect candidate files (respects extensions)
    print(f"Scanning  {doc_dir}")
    print(f"Extensions: {', '.join(extensions)}")
    print(f"Workers:  {workers}")
    print()

    all_files = sorted(
        f for f in doc_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in extensions
    )

    # Drop anything under an ignored directory before the indexing check.
    # ignore_dirs entries are fully resolved (symlinks included), so resolve
    # each candidate too — otherwise files reached via a symlinked path
    # component would not match and would slip through unfiltered.
    if ignore_dirs:
        before = len(all_files)
        all_files = [f for f in all_files if not _under_any(f.resolve(), ignore_dirs)]
        ignored_count = before - len(all_files)
        if ignored_count:
            print(f"Skipping {ignored_count:,} file(s) under ignored director(y/ies)")

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
    scanned    = 0
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

    def _progress():
        if _IS_TTY:
            print(_progress_bar(completed, total, start_time, failed),
                  end="", flush=True)

    def _index_result(result):
        """Write one finished extraction result dict to the DB and update
        counters. Shared by the pooled loop and the single-worker retry."""
        nonlocal extracted, scanned, failed
        name = result["name"]
        if result["success"]:
            doc_id = _write_result(conn, result, doc_dir)
            if doc_id is not None:
                if result.get("doc_type") == "scanned":
                    scanned += 1
                    _ocr_list_add(db_path, result["path"])
                    _log.info("SCANNED  %s  (added to ocr_list_pdfs.txt)", name)
                else:
                    extracted += 1
                    _log.info("OK  %s  (%d tags)", name, len(result.get("tags", [])))
            else:
                failed += 1
                _log.error("DB ERROR  %s", name)
        else:
            failed += 1
            _log.warning("FAILED  %s  —  %s", name, result["error"])
            _blacklist_add(db_path, result["path"], f"extraction failed: {result['error']}")

    def _retry_suspects(suspects):
        """A worker was killed (RLIMIT_AS/RLIMIT_CPU) which breaks the *entire*
        pool, so every file that was in flight raises BrokenProcessPool — but
        only one of them is the real culprit. Blindly blacklisting the first
        future to surface frequently punishes an innocent file and leaves the
        true offender to crash the next run too. Instead, re-run each suspect
        on its own in a fresh single-worker pool (same RLIMIT guards): the file
        that kills its dedicated worker is the real offender and is the only one
        blacklisted; the innocent suspects are indexed normally."""
        nonlocal completed, failed
        for fname, ddir in suspects:
            try:
                with ProcessPoolExecutor(max_workers=1,
                                         initializer=_worker_init) as solo:
                    result = solo.submit(_extract_file, (fname, ddir)).result()
            except BrokenProcessPool:
                completed += 1
                failed += 1
                _log.error("KILLED (resource limit, isolated retry)  %s", fname)
                _blacklist_add(db_path, fname,
                               "killed by resource limit (RLIMIT_AS/RLIMIT_CPU)")
                _progress()
                continue
            except Exception as exc:
                completed += 1
                failed += 1
                _log.error("FUTURE ERROR (isolated retry)  %s  —  %s", fname, exc)
                _blacklist_add(db_path, fname, f"future error: {exc}")
                _progress()
                continue
            completed += 1
            _index_result(result)
            _progress()
            if completed % 50 == 0:
                conn.commit()

    suspects_extra = []   # files whose future raised BrokenProcessPool this round
    try:
        while True:
            broke = False
            # A killed worker poisons the whole pool, so we run inside an outer
            # loop and stand up a fresh pool after isolating the suspects.
            with ProcessPoolExecutor(max_workers=workers,
                                     initializer=_worker_init) as executor:
                _fill_queue(executor)   # prime initial batch
                while in_flight:
                    done, _ = wait(list(in_flight.keys()),
                                   return_when=FIRST_COMPLETED)
                    for future in done:
                        fname = in_flight.pop(future, "unknown")
                        try:
                            result = future.result()
                        except BrokenProcessPool:
                            # Don't trust this fname as the culprit — defer it.
                            suspects_extra.append((fname, str(doc_dir)))
                            broke = True
                            continue
                        except Exception as exc:
                            completed += 1
                            failed += 1
                            _log.error("FUTURE ERROR  %s  —  %s", fname, exc)
                            _blacklist_add(db_path, fname, f"future error: {exc}")
                            _progress()
                            continue
                        completed += 1
                        _index_result(result)
                        _progress()
                        if completed % 50 == 0:
                            conn.commit()
                    if broke:
                        break   # leave the `with`, tearing down the broken pool
                    _fill_queue(executor)

            if broke:
                # Everything still in flight, plus any future that surfaced the
                # break, is a suspect. Isolate them one at a time, then resume
                # the main loop with a fresh pool for the remaining work.
                suspects = [(fn, str(doc_dir)) for fn in in_flight.values()] \
                    + suspects_extra
                in_flight.clear()
                suspects_extra = []
                if _IS_TTY:
                    print()  # finish the progress-bar line
                _log.error("Worker died — isolating %d suspect file(s) via "
                           "single-worker retries.", len(suspects))
                conn.commit()
                _retry_suspects(suspects)
                continue   # rebuild the pool and keep going with remaining work
            break          # in_flight drained with no break → all work done
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
    print(f"  Scanned:    {scanned:,}  (image-only — added to ocr_list_pdfs.txt)")
    print(f"  Failed:     {failed:,}")
    print(f"  Time:       {elapsed:.1f}s")
    if (extracted + scanned) > 0:
        print(f"  Speed:      {(extracted + scanned) / elapsed:.1f} docs/sec")


# ── Single-file scan ──────────────────────────────────────────────────────────

def scan_single_file(
    file_path: str,
    db_path: str,
    doc_dir: str = None,
) -> dict:
    """
    Extract and index a single file.

    - If the file is in scan_blacklist.txt, it is removed first (the caller
      is explicitly asking to retry it).
    - If the file is in pii_blacklist.txt, the call is refused (permanent block).
    - Returns a summary dict with keys: success, doc_type, error, doc_id,
      title, tags, removed_from_blacklist.
    """
    file_path = Path(file_path).resolve()
    db_path   = Path(db_path)

    if not file_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    _log, _ = _setup_scan_logger()

    # PII blacklist is permanent — refuse
    pii_bl = _load_blacklist(db_path, PII_BLACKLIST_FILENAME)
    if str(file_path) in pii_bl:
        return {
            "success": False,
            "error": "File is in pii_blacklist.txt (permanent PII block). Cannot re-index.",
        }

    # Remove from scan blacklist if present — caller explicitly wants a retry
    scan_bl = _load_blacklist(db_path, BLACKLIST_FILENAME)
    removed_from_blacklist = False
    if str(file_path) in scan_bl:
        _blacklist_remove(db_path, str(file_path))
        removed_from_blacklist = True

    # Fall back to file's parent if no doc_dir given (tags derive folder names
    # relative to doc_dir; using parent means only extension tag is generated)
    if doc_dir is None:
        doc_dir = str(file_path.parent)

    # Run extraction in the main process (no executor needed for one file)
    result = _extract_file((str(file_path), doc_dir))

    if not result["success"]:
        reason = result.get("error") or "extraction failed (no detail available)"
        _blacklist_add(db_path, str(file_path), reason)
        _log.warning("FAIL  %s  —  %s", file_path.name, reason)
        return {
            "success": False,
            "error": reason,
            "removed_from_blacklist": removed_from_blacklist,
        }

    conn = get_db(str(db_path))
    try:
        doc_id = _write_result(conn, result, Path(doc_dir))
        conn.commit()
    finally:
        conn.close()

    doc_type = result.get("doc_type", "")
    if doc_id is not None:
        if doc_type == "scanned":
            _ocr_list_add(db_path, str(file_path))
            _log.info("SCANNED  %s  (added to ocr_list_pdfs.txt)", file_path.name)
        else:
            _log.info("OK  %s  (%d tags)", file_path.name, len(result.get("tags", [])))

    return {
        "success": True,
        "doc_id": doc_id,
        "doc_type": doc_type,
        "title": result.get("title", ""),
        "tags": result.get("tags", []),
        "removed_from_blacklist": removed_from_blacklist,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        description="Scan a directory and index documents into DocuBrowse",
    )
    p.add_argument("doc_dir",  help="Directory containing documents to scan")
    p.add_argument("db_path",  nargs="?",
                   default="/mnt/data/git/AI/DocuBrowse/du-docs.db",
                   help="Path to SQLite database (default: du-docs.db in repo)")
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
