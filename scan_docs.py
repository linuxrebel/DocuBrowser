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

# One scanner module by design — file dispatch, DB writes, blacklist
# handling, and the CLI all share tight state; splitting would explode
# the import graph without buying much.
# pylint: disable=too-many-lines
#
# All open() calls in this file target user documents where the OS default
# encoding matches or errors="replace" is set explicitly at the call site.
# pylint: disable=unspecified-encoding
#
# Long print/help lines that would only get worse from mechanical wrapping.
# pylint: disable=line-too-long

import argparse
import contextlib
import html as _html
import io
import itertools
import logging
import os
import re
import signal
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime
from pathlib import Path

try:
    import resource as _resource
except ImportError:
    _resource = None      # Windows: no resource module — RLIMIT guards no-op

from docubrowse_db import get_db, delete_documents
from platform_paths import scan_log_paths

# Per-format extractors — hoisted so ProcessPool workers pay the import cost
# once at process start rather than once per file dispatched.
from pdf_extractor import extract_pdf, generate_keywords
from docx_extractor import extract_docx
from pptx_extractor import extract_pptx
from xlsx_extractor import extract_xlsx
from odf_extractor import extract_odf
from visio_extractor import extract_visio
from markup_extractor import extract_markup
from ebook_extractor import extract_ebook
from eml_extractor import extract_eml
from csv_extractor import extract_csv
from rtf_extractor import extract_rtf
from djvu_extractor import extract_djvu


# HTtrack-mirrored sites save pages as extensionless files (e.g. "index"
# instead of "index.html").  These are picked up by the no-extension
# classifier below (_classify_noext) which detects HTML via tag heuristics
# and routes them through _extract_text_file.
DEFAULT_EXTENSIONS = [".pdf", ".docx", ".pptx", ".xlsx",
                      ".odt", ".ods", ".odp",
                      ".ott", ".ots", ".otp",
                      ".vsdx", ".vsdm", ".vsd", ".vss", ".vst",
                      ".drawio", ".dio",
                      ".epub", ".mobi", ".azw", ".azw3",
                      ".djvu", ".djv",
                      ".eml", ".rtf", ".csv", ".tsv",
                      ".txt", ".md", ".html",
                      ".ini", ".conf", ".cfg", ".log", ".lst",
                      ".puml", ".plantuml", ".mmd",
                      # SGML/XML family + structured plain-text markup
                      ".xml", ".xhtml", ".sgml", ".sgm",
                      ".docbook", ".dbk",
                      ".svg", ".vdx",
                      ".rss", ".atom", ".opml",
                      ".rst", ".adoc", ".asciidoc", ".tex", ".latex",
                      ".json", ".yml", ".yaml",
                      ".py", ".sh", ".js", ".css",
                      ".rs", ".c", ".h", ".cpp", ".hpp", ".cc",
                      ".go", ".java", ".ts", ".tsx", ".jsx",
                      ".rb", ".php", ".toml"]

# Diagram/drawing extensions handled by visio_extractor.
_VISIO_EXTENSIONS = frozenset({
    ".vsdx", ".vsdm", ".vsd", ".vss", ".vst", ".drawio", ".dio",
})

# Text-based diagram sources (PlantUML, Mermaid) — routed through the plain
# text path but still counted as first-class scannable types.
_TEXT_DIAGRAM_EXTENSIONS = frozenset({".puml", ".plantuml", ".mmd"})

_DJVU_EXTENSIONS = frozenset({".djvu", ".djv"})

# XML/SGML markup family — routed through markup_extractor.
_MARKUP_XML_EXTENSIONS = frozenset({
    ".xml", ".xhtml", ".sgml", ".sgm",
    ".docbook", ".dbk",
    ".svg", ".vdx",
    ".rss", ".atom", ".opml",
})

# Structured plain-text markup (reST, AsciiDoc, LaTeX) — same extractor,
# different code path (no tag-stripping).
_MARKUP_TEXT_EXTENSIONS = frozenset({
    ".rst",
    ".adoc", ".asciidoc",
    ".tex", ".latex",
})

# SVG and Visio 2003 XML (.vdx) are technically XML-markup but are really
# diagrams — surface them in the diagram tag pool so users can filter for
# them alongside .drawio / .vsdx.
_MARKUP_DIAGRAM_EXTENSIONS = frozenset({".svg", ".vdx"})

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

    def wait_for_memory(**_kw):
        """No-op fallback when hardware_utils is unavailable."""
        return False

# Per-file timeout: 2 generous seconds per page in the MAX_PAGES cap.
# Keeps a single corrupt/looping PDF from blocking the whole scan.
try:
    from pdf_extractor import MAX_PAGES as _MAX_PAGES  # pylint: disable=ungrouped-imports
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
LEGACY_VISIO_LIST_FILENAME = "visio_legacy_missing.txt"
RTF_MISSING_LIST_FILENAME  = "rtf_missing_striprtf.txt"
DJVU_MISSING_LIST_FILENAME = "djvu_missing_djvulibre.txt"
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
    directories (outside docPath) managed via the Settings UI. They are
    automatically included by `docubrowser scan`/`rescan` (see
    resolve_doc_dirs in docubrowser.py): every configured directory is
    scanned into the single shared database, with embedding run once
    afterward across all of them.
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


# pylint: disable-next=too-many-return-statements,too-many-branches
def _classify_noext(file_path: Path) -> str:
    """Classify a file with no extension by reading its first 8192 bytes.

    Returns a synthetic extension string ('pdf', 'docx', 'html', 'text', etc.)
    or 'skip' if the file is a binary format we don't handle (ELF, images, etc.).

    Must be module-level (not nested) — called inside ProcessPoolExecutor workers
    which require picklable callables.
    """
    try:
        with open(file_path, "rb") as fh:
            head = fh.read(8192)
    except OSError:
        return "skip"

    if not head:
        return "skip"

    # ── Magic-number signatures ──
    if head[:5] == b"%PDF-":
        return "pdf"

    # ZIP-based Office / EPUB containers
    if head[:4] == b"PK\x03\x04":
        # Check for Office XML or EPUB content-type markers in the first 8 KB
        chunk = head[:8192]
        if b"word/" in chunk or b"word\\" in chunk:
            return "docx"
        if b"ppt/" in chunk or b"ppt\\" in chunk:
            return "pptx"
        if b"xl/" in chunk or b"xl\\" in chunk:
            return "xlsx"
        if b"EPUB" in chunk or b"epub" in chunk:
            return "epub"
        return "skip"  # unknown ZIP archive

    # Binary formats we can't extract text from — skip early
    if head[:4] == b"\x7fELF":            # ELF executable
        return "skip"
    if head[:8] == b"\x89PNG\r\n\x1a\n":  # PNG image
        return "skip"
    if head[:2] == b"\xff\xd8":            # JPEG image
        return "skip"
    if head[:6] in (b"GIF87a", b"GIF89a"):  # GIF image
        return "skip"

    # ── HTML heuristics ──
    # Check the first portion for common HTML indicators
    try:
        text_head = head[:4096].decode("utf-8", errors="replace").lower()
    except (UnicodeError, LookupError):
        return "skip"

    html_markers = ("<!doctype html", "<html", "<head", "<body",
                    "<div", "<table", "<meta", "<link", "<script")
    if any(marker in text_head for marker in html_markers):
        return "html"

    # ── Fallback: is it readable text? ──
    try:
        sample = head[:4096].decode("utf-8")
        # If >90% of characters are printable ASCII/whitespace, treat as text
        printable = sum(1 for c in sample if c.isprintable() or c in "\n\r\t")
        if len(sample) > 0 and printable / len(sample) > 0.90:
            return "text"
    except UnicodeDecodeError:
        pass

    return "skip"


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
    like_pattern = prefix.rstrip("/\\") + os.sep + "%"
    rows = conn.execute(
        "SELECT id FROM documents WHERE path = ? OR path LIKE ?",
        (prefix, like_pattern),
    ).fetchall()
    ids = [r[0] for r in rows]
    return delete_documents(conn, ids)


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


def _legacy_visio_list_add(db_path: Path, file_path: str) -> None:
    """Append a legacy .vsd/.vss/.vst path to visio_legacy_missing.txt.

    Populated when a legacy Visio file is encountered but ``vsd2xml`` is not
    installed.  The file is still indexed metadata-only; installing
    libvisio-tools and rescanning will then extract body text.
    """
    lv_path = db_path.parent / LEGACY_VISIO_LIST_FILENAME
    with open(lv_path, "a", encoding="utf-8") as fh:
        fh.write(file_path + "\n")


def _rtf_missing_list_add(db_path: Path, file_path: str) -> None:
    """Append an .rtf path to rtf_missing_striprtf.txt.

    Populated when an .rtf file is encountered but ``striprtf`` is not
    installed.  The file is still indexed metadata-only; installing
    striprtf (``pip install striprtf``) and rescanning will extract body
    text.  Same convention as ``visio_legacy_missing.txt``.
    """
    rm_path = db_path.parent / RTF_MISSING_LIST_FILENAME
    with open(rm_path, "a", encoding="utf-8") as fh:
        fh.write(file_path + "\n")


def _djvu_missing_list_add(db_path: Path, file_path: str) -> None:
    """Append a .djvu/.djv path to djvu_missing_djvulibre.txt.

    Populated when a DjVu file is encountered but DjVuLibre (``djvutxt``) is
    not installed.  The file is still indexed metadata-only; installing
    DjVuLibre and rescanning will extract body text.  Same convention as
    ``visio_legacy_missing.txt``.
    """
    dm_path = db_path.parent / DJVU_MISSING_LIST_FILENAME
    with open(dm_path, "a", encoding="utf-8") as fh:
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

    On Windows: ``resource`` module does not exist, so workers run without
    memory/CPU caps.  Windows has its own OOM management.
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    if _resource is None:
        return   # Windows — no resource limits available

    # 6 GB virtual address space cap per worker.  When pdfplumber/pdfminer's
    # C extensions exceed this, malloc() fails.  Deep C code typically does
    # NOT propagate this as a Python MemoryError — it usually crashes the
    # worker process with SIGSEGV or SIGBUS.  That causes BrokenProcessPool
    # on the associated future, which _handle_result catches.
    six_gb = 6 * 1024 ** 3
    try:
        _resource.setrlimit(_resource.RLIMIT_AS, (six_gb, six_gb))
    except (ValueError, OSError):
        pass   # ignore if already lower or unsupported

    # RLIMIT_CPU is a TOTAL LIFETIME CPU budget for the worker process, not
    # a per-file limit.  We set it generously (10× FILE_TIMEOUT_SECS) as a
    # last-resort backstop for a completely runaway worker, not as a per-file
    # timer.  Per-file timing is handled by SIGALRM in _extract_file (for
    # pure-Python paths) and RLIMIT_AS (for C-extension paths).
    cpu_limit = FILE_TIMEOUT_SECS * 10
    try:
        _resource.setrlimit(_resource.RLIMIT_CPU,
                            (cpu_limit, cpu_limit + 5))
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

    for log_path in scan_log_paths():
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
    filled    = width * completed // total
    bar_glyph = "█" * filled + "░" * (width - filled)
    rate      = completed / elapsed
    remain    = (total - completed) / rate if rate > 0 else 0
    eta       = (f"{int(remain // 60)}m{int(remain % 60):02d}s"
                 if remain > 60 else f"{remain:.0f}s")
    err_str   = f"  \033[91m{errors} err\033[0m" if errors else ""
    return (
        f"\r  [{bar_glyph}] {pct:3d}%  {completed}/{total}"
        f"  {rate:.1f}/s  ETA {eta}{err_str}  "
    )


# ── Worker function (runs in subprocess — NO sqlite3 here) ───────────────────

# pylint: disable-next=too-many-locals,too-many-branches,too-many-statements
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
    # On Windows, SIGALRM does not exist — workers run without per-file
    # timeouts (RLIMIT_AS doesn't exist either, but the OS handles OOM).
    _has_alarm = hasattr(signal, 'SIGALRM')
    if _has_alarm:
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

        # No-extension files: classify by magic bytes / content heuristics
        detected_ext = ""
        if not ext:
            detected_ext = _classify_noext(file_path)
            if detected_ext == "skip":
                base["error"] = "unrecognised binary format (no extension)"
                return base

        effective_ext = ext or f".{detected_ext}"

        if effective_ext == ".pdf":
            # pdfminer/pdfplumber emit harmless color-space warnings to stderr;
            # suppress them in the worker process so they never reach the terminal.
            with contextlib.redirect_stderr(io.StringIO()):
                result = extract_pdf(str(file_path))
        elif effective_ext == ".docx":
            result = extract_docx(str(file_path))
        elif effective_ext == ".pptx":
            result = extract_pptx(str(file_path))
        elif effective_ext == ".xlsx":
            result = extract_xlsx(str(file_path))
        elif effective_ext in (".odt", ".ods", ".odp",
                               ".ott", ".ots", ".otp"):
            # ODF templates share their base flavor's structure; extract_odf
            # routes them by mimetype prefix (text-template → odt, etc.).
            result = extract_odf(str(file_path))
        elif effective_ext in _VISIO_EXTENSIONS:
            result = extract_visio(str(file_path))
            # Legacy .vsd/.vss/.vst without vsd2xml: index metadata-only
            # rather than blacklist, and signal the missing-converter list
            # to the main process via the result dict.
            if (not result["success"]
                    and (result.get("error") or "").startswith("vsd2xml not found")):
                result["success"]         = True
                result["text"]            = ""
                result["snippet"]         = ""
                result["description"]     = "[legacy Visio — install libvisio-tools to index body]"
                result["title"]           = result.get("title") or file_path.stem
                result["_needs_vsd2xml"]  = True
                result["error"]           = None
        elif effective_ext in _TEXT_DIAGRAM_EXTENSIONS:
            # PlantUML / Mermaid source — plain text, but tag as diagram
            result = _extract_text_file(file_path)
            if result["success"]:
                result["doc_type"] = effective_ext.lstrip(".")
        elif (effective_ext in _MARKUP_XML_EXTENSIONS
              or effective_ext in _MARKUP_TEXT_EXTENSIONS):
            result = extract_markup(str(file_path))
        elif effective_ext in (".epub", ".mobi", ".azw", ".azw3"):
            result = extract_ebook(str(file_path))
        elif effective_ext == ".eml":
            result = extract_eml(str(file_path))
        elif effective_ext in (".csv", ".tsv"):
            result = extract_csv(str(file_path))
        elif effective_ext == ".rtf":
            result = extract_rtf(str(file_path))
            # striprtf missing: degrade to metadata-only and flag for the
            # main process to append to rtf_missing_striprtf.txt.
            if (not result["success"]
                    and (result.get("error") or "").startswith("striprtf not installed")):
                result["success"]           = True
                result["text"]              = ""
                result["snippet"]           = ""
                result["description"]       = "[RTF — install striprtf to index body]"
                result["title"]             = result.get("title") or file_path.stem
                result["_needs_striprtf"]   = True
                result["error"]             = None
        elif effective_ext in _DJVU_EXTENSIONS:
            result = extract_djvu(str(file_path))
            # DjVuLibre missing: degrade to metadata-only and flag for the
            # main process to append to djvu_missing_djvulibre.txt.
            if (not result["success"]
                    and (result.get("error") or "").startswith("djvulibre not found")):
                result["success"]          = True
                result["text"]             = ""
                result["snippet"]          = ""
                result["description"]      = "[DjVu — install djvulibre to index body]"
                result["title"]            = result.get("title") or file_path.stem
                result["_needs_djvulibre"] = True
                result["error"]            = None
        elif detected_ext == "html":
            result = _extract_text_file(file_path, detected_ext="html")
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
        tag_ext = detected_ext if detected_ext else ext.lstrip(".")
        if tag_ext:
            tags.add(tag_ext)                                 # extension
        for parent in file_path.parents:                     # folder names
            # Stop at doc_dir; also stop if the file isn't under doc_dir at all
            # (mismatched --doc-dir) so we don't tag with filesystem-root dir
            # names like 'mnt', 'data', 'home'.
            if parent == doc_dir or not parent.is_relative_to(doc_dir):
                break
            name = parent.name.lower()
            if len(name) > 2:
                tags.add(name)

        if effective_ext in _CODE_EXTENSIONS:
            tags.add("code")

        if effective_ext in (".pdf", ".docx", ".pptx", ".xlsx",
                             ".odt", ".ods", ".odp",
                             ".ott", ".ots", ".otp",
                             ".vsdx", ".vsdm", ".drawio", ".dio",
                             ".xml", ".xhtml", ".sgml", ".sgm",
                             ".docbook", ".dbk",
                             ".svg", ".vdx",
                             ".rss", ".atom", ".opml",
                             ".rst", ".adoc", ".asciidoc", ".tex", ".latex",
                             ".eml", ".rtf", ".csv", ".tsv",
                             ".djvu", ".djv",
                             ".epub", ".mobi", ".azw", ".azw3"):
            keywords = generate_keywords(
                result.get("text", ""), result.get("title", ""), max_keywords=5
            )
            tags.update(keywords)

        # Diagram files get a "diagram" tag for browse/filter convenience.
        if (effective_ext in _VISIO_EXTENSIONS
                or effective_ext in _TEXT_DIAGRAM_EXTENSIONS
                or effective_ext in _MARKUP_DIAGRAM_EXTENSIONS):
            tags.add("diagram")

        # Markup files get a "markup" tag for the same reason.
        if (effective_ext in _MARKUP_XML_EXTENSIONS
                or effective_ext in _MARKUP_TEXT_EXTENSIONS):
            tags.add("markup")

        return {
            **base,
            "success":         True,
            "size_bytes":      size_bytes,
            "file_ext":        effective_ext,
            "doc_type":        result.get("doc_type", effective_ext.lstrip(".")),
            "title":           result.get("title") or file_path.stem,
            "author":          result.get("author"),
            "subject":         result.get("subject"),
            "description":    result.get("description", ""),
            "snippet":         result.get("snippet", ""),
            "text":            result.get("text", ""),
            "modified_at":     modified_at,
            "tags":            sorted(tags),
            "_needs_vsd2xml":  result.get("_needs_vsd2xml", False),
            "_needs_striprtf": result.get("_needs_striprtf", False),
            "_needs_djvulibre": result.get("_needs_djvulibre", False),
        }

    except TimeoutError as exc:
        base["error"] = str(exc)
        return base
    except Exception as exc:   # pylint: disable=broad-exception-caught
        # Worker safety net — any extractor crash must return a failed result
        # so the file gets blacklisted rather than killing the whole scan.
        base["error"] = str(exc)
        return base
    finally:
        if _has_alarm:
            signal.alarm(0)   # always cancel the alarm


def _extract_text_file(file_path: Path, detected_ext: str = "") -> dict:
    """Extract plain text from .txt / .md / .html files.

    *detected_ext* overrides the suffix for no-extension files classified
    by _classify_noext() — e.g. "html" routes an extensionless httrack page
    through the HTML tag-stripping path.
    """
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
        # Bounded read: only the indexed prefix is ever used (text[:5000]),
        # so never load a multi-GB .txt/.json whole — that would burn the
        # worker's 6 GB RLIMIT_AS and get the file mis-blacklisted as
        # "killed by resource limit". 200 KB is ample for the prefix + HTML
        # tag-stripping below.
        with open(file_path, encoding="utf-8", errors="replace") as fh:
            text = fh.read(200_000)
        if file_path.suffix.lower() == ".html" or detected_ext == "html":
            text = re.sub(r"<script[^>]*>.*?</script>", "", text,
                          flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<style[^>]*>.*?</style>",  "", text,
                          flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", "", text)
            text = _html.unescape(text)
        result["text"]    = text[:5000]
        result["snippet"] = text[:500]
        result["success"] = bool(result["text"])
        return result
    except (OSError, UnicodeError, LookupError) as exc:
        result["error"] = str(exc)
        return result


# ── DB write helper (main process only) ──────────────────────────────────────

def _write_result(conn, result: dict, _doc_dir: Path):
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
    except sqlite3.Error as exc:
        print(f"  DB ERROR for {result['name']}: {exc}", file=sys.stderr)
        return None


def _is_hidden_relpath(f: Path, root: Path) -> bool:
    """True if *f* under *root* has any hidden (dot-prefixed) path component.

    Skips dotfiles (``.env``, ``.bashrc``) and the contents of hidden
    directories (``.git/``, ``.venv/``). The *root* itself is exempt, so a scan
    whose root is a dot-directory still indexes its non-hidden files. (D-6.)
    """
    try:
        parts = f.relative_to(root).parts
    except ValueError:
        parts = (f.name,)
    return any(part.startswith(".") for part in parts)


# ── Main scan function ────────────────────────────────────────────────────────

# pylint: disable-next=too-many-locals,too-many-branches,too-many-statements
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

    _walk_skipped = 0
    _walk_hidden = 0
    _walk_candidates = []
    for f in doc_dir.rglob("*"):
        try:
            if not f.is_file():
                continue
            # D-6: never index hidden files or the contents of hidden dirs
            # (.env, .ssh/, .git/, .venv/, …) — skip any dot path component.
            if _is_hidden_relpath(f, doc_dir):
                _walk_hidden += 1
                continue
            if f.suffix.lower() in extensions or not f.suffix:
                _walk_candidates.append(f)
        except OSError as _e:
            _walk_skipped += 1
            logging.warning("Skipping inaccessible path: %s  (%s)", f, _e)
    if _walk_hidden:
        print(f"  Skipped {_walk_hidden:,} hidden dotfile(s)/dir contents")
    if _walk_skipped:
        print(f"  ⚠ Skipped {_walk_skipped:,} inaccessible file(s) "
              "(broken symlinks, permission errors, etc.)")
    all_files = sorted(_walk_candidates)

    # Drop anything under an ignored directory before the indexing check.
    # ignore_dirs entries are fully resolved (symlinks included), so resolve
    # each candidate too — otherwise files reached via a symlinked path
    # component would not match and would slip through unfiltered.
    if ignore_dirs:
        before = len(all_files)
        def _safe_resolve(f):
            try:
                return f.resolve()
            except OSError:
                return f
        all_files = [f for f in all_files if not _under_any(_safe_resolve(f), ignore_dirs)]
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

    start_time  = time.time()
    last_commit = time.time()
    extracted   = 0
    scanned     = 0
    failed      = 0
    completed   = 0
    total       = len(to_process)

    work_items = [(str(f), str(doc_dir)) for f in to_process]

    # Sliding-window executor: keep at most `workers` futures in-flight —
    # one per worker slot, no extra queuing.  Memory is checked BEFORE each
    # individual submit so we never hand a new PDF to a worker when RAM is low.
    max_in_flight = workers   # match exactly to worker count, no pre-queue
    work_iter     = iter(work_items)
    in_flight     = {}   # future -> filename
    _width = len(str(total))

    def _fill_queue(executor):
        """Submit one new future per available worker slot, checking RAM first."""
        slots = max_in_flight - len(in_flight)
        for item in itertools.islice(work_iter, slots):
            wait_for_memory(_is_tty=_IS_TTY, logger=_log)
            f = executor.submit(_extract_file, item)
            in_flight[f] = item[0]

    def _progress():
        if _IS_TTY:
            print(_progress_bar(completed, total, start_time, failed),
                  end="", flush=True)

    def _maybe_commit(force=False):
        """Commit on a ~2s time budget instead of every N documents. The old
        every-50 cadence held the single WAL writer slot for minutes during
        large-PDF stretches, blocking the server's synopsis/delete writes until
        they timed out. A short time budget bounds how long the writer is held
        while still batching enough to keep throughput up."""
        nonlocal last_commit
        if force or (time.time() - last_commit) >= 2.0:
            conn.commit()
            last_commit = time.time()

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
                elif result.get("_needs_vsd2xml"):
                    extracted += 1
                    _legacy_visio_list_add(db_path, result["path"])
                    _log.info("LEGACY-VISIO  %s  (metadata-only; install libvisio-tools to index body)", name)
                elif result.get("_needs_striprtf"):
                    extracted += 1
                    _rtf_missing_list_add(db_path, result["path"])
                    _log.info("RTF-NO-STRIPRTF  %s  (metadata-only; pip install striprtf to index body)", name)
                elif result.get("_needs_djvulibre"):
                    extracted += 1
                    _djvu_missing_list_add(db_path, result["path"])
                    _log.info("DJVU-NO-DJVULIBRE  %s  (metadata-only; install djvulibre to index body)", name)
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
            except Exception as exc:   # pylint: disable=broad-exception-caught
                completed += 1
                failed += 1
                _log.error("FUTURE ERROR (isolated retry)  %s  —  %s", fname, exc)
                _blacklist_add(db_path, fname, f"future error: {exc}")
                _progress()
                continue
            completed += 1
            _index_result(result)
            _progress()
            _maybe_commit()

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
                        except Exception as exc:   # pylint: disable=broad-exception-caught
                            completed += 1
                            failed += 1
                            _log.error("FUTURE ERROR  %s  —  %s", fname, exc)
                            _blacklist_add(db_path, fname, f"future error: {exc}")
                            _progress()
                            continue
                        completed += 1
                        _index_result(result)
                        _progress()
                        _maybe_commit()
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
    except sqlite3.Error as exc:
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
        elif result.get("_needs_vsd2xml"):
            _legacy_visio_list_add(db_path, str(file_path))
            _log.info("LEGACY-VISIO  %s  (metadata-only; install libvisio-tools to index body)", file_path.name)
        elif result.get("_needs_striprtf"):
            _rtf_missing_list_add(db_path, str(file_path))
            _log.info("RTF-NO-STRIPRTF  %s  (metadata-only; pip install striprtf to index body)", file_path.name)
        elif result.get("_needs_djvulibre"):
            _djvu_missing_list_add(db_path, str(file_path))
            _log.info("DJVU-NO-DJVULIBRE  %s  (metadata-only; install djvulibre to index body)", file_path.name)
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
    """Return the argparse parser for the scan_docs CLI."""
    p = argparse.ArgumentParser(
        description="Scan a directory and index documents into DocuBrowse",
    )
    p.add_argument("doc_dir",  help="Directory containing documents to scan")
    p.add_argument("db_path",  nargs="?",
                   default=str(Path(__file__).resolve().parent / "du-docs.db"),
                   help="Path to SQLite database (default: du-docs.db next to this script)")
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
    import multiprocessing   # pylint: disable=import-outside-toplevel
    multiprocessing.freeze_support()

    _cli_args = build_parser().parse_args()
    try:
        scan_directory(
            _cli_args.doc_dir,
            _cli_args.db_path,
            extensions=_cli_args.ext,
            workers=_cli_args.workers,
            limit=_cli_args.limit,
        )
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
