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
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from docubrowse_db import get_db


DEFAULT_EXTENSIONS = [".pdf", ".txt", ".md", ".html"]
DEFAULT_WORKERS    = min(os.cpu_count() or 4, 8)


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

    try:
        ext = file_path.suffix.lower()

        if ext == ".pdf":
            from pdf_extractor import extract_pdf, generate_keywords
            result = extract_pdf(str(file_path))
        else:
            result = _extract_text_file(file_path)

        if not result["success"]:
            base["error"] = result.get("error", "extraction failed")
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
            "description": result.get("description", ""),
            "snippet":     result.get("snippet", ""),
            "text":        result.get("text", ""),
            "modified_at": modified_at,
            "tags":        sorted(tags),
        }

    except Exception as exc:
        base["error"] = str(exc)
        return base


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
               (name, path, size_bytes, file_ext, title, author, description,
                content_snippet, modified_at, indexed_at, doc_type, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result["name"],
                result["path"],
                result["size_bytes"],
                result["file_ext"],
                result["title"],
                result.get("author"),
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
               (rowid, name, title, description, tags, content_snippet)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                doc_id,
                result["name"],
                result.get("title", ""),
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
):
    """
    Scan *doc_dir* for documents and upsert them into *db_path*.

    Args:
        doc_dir:    Root directory to scan recursively
        db_path:    SQLite database path
        extensions: File extensions to process (default: pdf, txt, md, html)
        workers:    Worker processes for extraction (default: cpu_count capped at 8)
    """
    doc_dir = Path(doc_dir)
    if not doc_dir.exists() or not doc_dir.is_dir():
        print(f"ERROR: Directory not found: {doc_dir}")
        sys.exit(1)

    if extensions is None:
        extensions = DEFAULT_EXTENSIONS
    extensions = [e if e.startswith(".") else f".{e}" for e in extensions]

    conn = get_db(str(db_path))

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
    for f in all_files:
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime).isoformat()
        except OSError:
            mtime = None
        prev_mtime = existing.get(str(f))
        if prev_mtime and mtime and prev_mtime >= mtime:
            skipped += 1
            continue
        to_process.append(f)

    print(f"  {skipped:,} already up-to-date (skip)")
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

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_extract_file, item): item[0]
            for item in work_items
        }
        for future in as_completed(futures):
            completed += 1
            result = future.result()
            name   = result["name"]
            label  = f"[{completed:>{len(str(total))}}/{total}]"

            if result["success"]:
                doc_id = _write_result(conn, result, doc_dir)
                if doc_id is not None:
                    print(f"  {label} {name}: OK ({len(result.get('tags',[]))} tags)",
                          flush=True)
                    extracted += 1
                else:
                    print(f"  {label} {name}: DB ERROR", flush=True)
                    failed += 1
            else:
                print(f"  {label} {name}: FAILED — {result['error']}", flush=True)
                failed += 1

            # Commit every batch
            if completed % 50 == 0:
                conn.commit()

    conn.commit()

    # Log scan
    try:
        conn.execute(
            "INSERT INTO scan_log (scanned_at, docs_found, docs_added, docs_updated) VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(), total + skipped, extracted, skipped),
        )
        conn.commit()
    except Exception:
        pass

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
    return p


if __name__ == "__main__":
    # Required for ProcessPoolExecutor on all platforms
    import multiprocessing
    multiprocessing.freeze_support()

    args = build_parser().parse_args()
    scan_directory(
        args.doc_dir,
        args.db_path,
        extensions=args.ext,
        workers=args.workers,
    )
