#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
Embedding generator for DocuBrowse.
Sends documents to Ollama for embedding and stores results in database.

Parallelism: ThreadPoolExecutor (I/O-bound — each thread awaits an HTTP
response from Ollama; the GIL is released during socket I/O, so multiple
threads can be in-flight concurrently).

Default workers: 6  (tune with --workers; Ollama queues internally if
                     the model can't keep up, so higher values are safe)
"""

import argparse
import itertools
import json
import os
import sqlite3
import struct
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen


# embed_docs.py can be run standalone (not via docubrowser.py), so it sets its
# own Windows encoding rather than relying on the platform_paths side-effect.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    os.environ.setdefault("PYTHONUTF8", "1")

try:
    import colorama
    colorama.init()
except ImportError:
    pass

def _ollama_host() -> str:
    """Resolve the Ollama base URL from the environment.

    Prefer ``OLLAMA_HOST`` (Ollama ecosystem convention), then
    ``DOCUBROWSE_OLLAMA_HOST``. Defaults to the local Ollama daemon.
    """
    host = (
        os.environ.get("OLLAMA_HOST")
        or os.environ.get("DOCUBROWSE_OLLAMA_HOST")
        or "http://localhost:11434"
    )
    return host.rstrip("/")


OLLAMA_HOST     = _ollama_host()
EMBEDDING_MODEL = "nomic-embed-text"
BATCH_SIZE      = 25

# GPU-aware default: 6 workers with CUDA, 3 for CPU-only Ollama
try:
    from hardware_utils import recommended_embed_workers, wait_for_memory
    DEFAULT_WORKERS = recommended_embed_workers()
except ImportError:
    DEFAULT_WORKERS = 6

    def wait_for_memory(**_kw):
        """No-op fallback when hardware_utils is unavailable."""
        return False

# Progress display: compact bar in TTY, verbose per-file when piped/logged
_IS_TTY = sys.stdout.isatty()


def _progress_bar(completed: int, total: int, start_time: float, errors: int = 0) -> str:
    """Return a compact \\r progress line for interactive TTY display."""
    elapsed = time.time() - start_time + 0.001
    pct     = completed * 100 // total
    width   = 25
    filled     = width * completed // total
    bar_glyph  = "█" * filled + "░" * (width - filled)
    rate       = completed / elapsed
    remain     = (total - completed) / rate if rate > 0 else 0
    eta        = (f"{int(remain // 60)}m{int(remain % 60):02d}s"
                  if remain > 60 else f"{remain:.0f}s")
    err_str    = f"  \033[91m{errors} err\033[0m" if errors else ""
    return (
        f"\r  [{bar_glyph}] {pct:3d}%  {completed}/{total}"
        f"  {rate:.1f}/s  ETA {eta}{err_str}  "
    )


# ── Embedding call (runs in worker thread) ────────────────────────────────────

def _embed_one(args: tuple) -> tuple:
    """
    Worker: fetch one embedding from Ollama.
    Called from a thread-pool thread — no DB access here.

    Returns: (doc_id, name, embedding_vector_or_None)
    """
    doc_id, name, text_blob = args
    if not text_blob or not text_blob.strip():
        return (doc_id, name, None)
    try:
        url     = f"{OLLAMA_HOST}/api/embed"
        payload = json.dumps({
            "model": EMBEDDING_MODEL,
            "input": text_blob[:8000],   # nomic-embed-text supports up to 8192 tokens
        }).encode("utf-8")
        req = Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=60) as resp:
            data      = json.loads(resp.read().decode("utf-8"))
            embedding = data.get("embedding") or (data.get("embeddings") or [None])[0]
            return (doc_id, name, embedding)
    except (OSError, ValueError, json.JSONDecodeError):
        return (doc_id, name, None)


# ── Vector serialisation ──────────────────────────────────────────────────────

def vector_to_blob(vector: list) -> bytes:
    """float32 list → packed binary blob."""
    return struct.pack(f"{len(vector)}f", *vector)


# ── Main entry point ──────────────────────────────────────────────────────────

# pylint: disable-next=too-many-locals,too-many-statements
def embed_docs(db_path: str, limit: int = None, workers: int = DEFAULT_WORKERS):
    """
    Embed all documents that lack embeddings (or have stale ones).

    Args:
        db_path:  Path to SQLite database
        limit:    Max documents to embed this run (None = all)
        workers:  Concurrent Ollama requests
    """
    db_path = Path(db_path)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}")
        sys.exit(1)

    # Open connection with check_same_thread=False so the write-lock
    # approach below is safe (WAL mode allows concurrent reads anyway).
    conn = sqlite3.connect(str(db_path), timeout=30.0, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Docs that need embedding
    query = """
        SELECT d.id, d.name, d.title, d.description, d.content_snippet
        FROM documents d
        LEFT JOIN doc_embeddings de ON d.id = de.doc_id
        WHERE de.doc_id IS NULL
           OR de.updated_at IS NULL
           OR de.updated_at < d.updated_at
        ORDER BY d.id
    """
    if limit:
        query += f" LIMIT {limit}"

    rows    = conn.execute(query).fetchall()
    total   = len(rows)

    if total == 0:
        print("All documents are already embedded — nothing to do.")
        conn.close()
        return

    # Build work items: (doc_id, name, text_blob)
    work_items = []
    for doc_id, name, title, description, snippet in rows:
        text_blob = " ".join(
            p for p in [title or name, description or "", snippet or ""] if p
        ).strip()
        work_items.append((doc_id, name, text_blob))

    print(f"Embedding {total} documents with {workers} parallel workers")
    print(f"  Model:    {EMBEDDING_MODEL}  @  {OLLAMA_HOST}")
    print(f"  Database: {db_path}")
    print()

    start_time  = time.time()
    last_commit = time.time()
    embedded    = 0
    failed      = 0
    completed   = 0
    write_lock  = threading.Lock()

    def _write(doc_id, embedding, _completed_idx):
        """Serialise DB write; called from main thread via lock."""
        nonlocal last_commit
        blob = vector_to_blob(embedding)
        conn.execute(
            """INSERT OR REPLACE INTO doc_embeddings
               (doc_id, embedding, model, updated_at)
               VALUES (?, ?, ?, ?)""",
            (doc_id, blob, EMBEDDING_MODEL, datetime.now().isoformat()),
        )
        # Commit on a ~2s time budget rather than every BATCH_SIZE docs, so the
        # single WAL writer slot isn't held long enough to block the server's
        # synopsis/delete writes.
        if (time.time() - last_commit) >= 2.0:
            conn.commit()
            last_commit = time.time()

    # Sliding-window: keep workers*3 requests in-flight (HTTP I/O, low memory
    # per item) with memory checks between fills.
    max_in_flight = workers * 3
    work_iter     = iter(work_items)
    in_flight     = {}   # future -> name
    width         = len(str(total))

    def _fill_queue(executor):
        for item in itertools.islice(work_iter, max_in_flight - len(in_flight)):
            wait_for_memory(_is_tty=_IS_TTY)
            f = executor.submit(_embed_one, item)
            in_flight[f] = item[1]

    def _handle_result(future):
        nonlocal completed, embedded, failed
        doc_id, name, embedding = future.result()
        with write_lock:
            completed += 1
            idx = completed
        if embedding:
            with write_lock:
                _write(doc_id, embedding, idx)
            embedded += 1
            if _IS_TTY:
                print(_progress_bar(idx, total, start_time, failed),
                      end="", flush=True)
            else:
                print(f"  [{idx:>{width}}/{total}] {name}: OK", flush=True)
        else:
            failed += 1
            msg = f"  [{idx:>{width}}/{total}] {name}: FAILED"
            if _IS_TTY:
                print(f"\n{msg}", flush=True)
                print(_progress_bar(idx, total, start_time, failed),
                      end="", flush=True)
            else:
                print(msg, flush=True)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        _fill_queue(executor)

        while in_flight:
            done, _ = wait(list(in_flight.keys()), return_when=FIRST_COMPLETED)

            for future in done:
                del in_flight[future]
                _handle_result(future)

            _fill_queue(executor)

    # Clear progress bar line before summary
    if _IS_TTY:
        print()

    # Final commit
    conn.commit()
    conn.close()

    elapsed = time.time() - start_time
    avg_ms  = (elapsed / embedded * 1000) if embedded > 0 else 0

    print()
    print("=" * 60)
    print("EMBEDDING SUMMARY")
    print("=" * 60)
    print(f"  Workers:  {workers}")
    print(f"  Total:    {total}")
    print(f"  Embedded: {embedded}")
    print(f"  Failed:   {failed}")
    print(f"  Time:     {elapsed:.1f}s  ({avg_ms:.0f} ms/doc avg)")
    if embedded > 0:
        print(f"  Speed:    {embedded / elapsed:.1f} docs/sec")


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser():
    """Return the argparse parser for the ``embed_docs`` CLI."""
    p = argparse.ArgumentParser(
        description="Generate Ollama embeddings for DocuBrowse documents",
    )
    p.add_argument("db_path", help="Path to SQLite database (du-docs.db)")
    p.add_argument("--limit",   type=int, default=None,
                   help="Maximum documents to embed this run")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                   help=f"Parallel Ollama requests (default: {DEFAULT_WORKERS})")
    return p


if __name__ == "__main__":
    _cli_args = build_parser().parse_args()
    print(f"Ollama host:  {OLLAMA_HOST}")
    print(f"Model:        {EMBEDDING_MODEL}")
    print(f"Workers:      {_cli_args.workers}")
    print()
    embed_docs(_cli_args.db_path, limit=_cli_args.limit, workers=_cli_args.workers)
