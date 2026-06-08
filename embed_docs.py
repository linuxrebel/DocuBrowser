#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
Embedding generator for DocuBrowse.
Sends documents to Ollama for embedding and stores results in database.
"""

import json
import sqlite3
import struct
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from docubrowse_db import get_db


OLLAMA_HOST = "http://localhost:11434"
EMBEDDING_MODEL = "nomic-embed-text"
BATCH_SIZE = 25


def embed_text(text: str, timeout: int = 60) -> list:
    """
    Send text to Ollama for embedding.

    Args:
        text: Text to embed
        timeout: Request timeout in seconds

    Returns:
        List of floats (embedding vector) or None if failed
    """
    if not text or not text.strip():
        return None

    try:
        url = f"{OLLAMA_HOST}/api/embed"
        payload = json.dumps({
            "model": EMBEDDING_MODEL,
            "input": text[:2000]  # Limit input size
        }).encode('utf-8')

        request = Request(url, data=payload, method='POST')
        request.add_header('Content-Type', 'application/json')

        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode('utf-8'))
            embedding = data.get('embedding')
            return embedding if embedding else None
    except (URLError, HTTPError, Exception) as e:
        print(f"  WARNING: Embedding failed: {e}", file=sys.stderr)
        return None


def vector_to_blob(vector: list) -> bytes:
    """Convert embedding vector to binary blob (float32)."""
    if not vector:
        return b''
    return struct.pack(f'{len(vector)}f', *vector)


def embed_docs(db_path: str, limit: int = None):
    """
    Embed all documents that need embeddings.

    Args:
        db_path: Path to SQLite database
        limit: Max number of docs to embed (None = all)
    """
    db_path = Path(db_path)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}")
        return

    conn = get_db(str(db_path))

    # Find docs without embeddings or with stale embeddings
    query = '''
        SELECT d.id, d.name, d.title, d.description, d.content_snippet
        FROM documents d
        LEFT JOIN doc_embeddings de ON d.id = de.doc_id
        WHERE de.doc_id IS NULL OR de.updated_at < d.updated_at
        ORDER BY d.id
    '''
    if limit:
        query += f' LIMIT {limit}'

    docs_to_embed = conn.execute(query).fetchall()
    total = len(docs_to_embed)

    if total == 0:
        print("No documents need embedding")
        conn.close()
        return

    print(f"Embedding {total} documents...")
    start_time = time.time()
    embedded = 0
    failed = 0

    for idx, doc_row in enumerate(docs_to_embed, 1):
        doc_id, name, title, description, snippet = doc_row

        # Build embedding text from available fields
        text_parts = [
            title or name,
            description or '',
            snippet or ''
        ]
        text_blob = ' '.join(p for p in text_parts if p).strip()

        if not text_blob:
            print(f"  [{idx}/{total}] {name}: SKIP (no text)")
            continue

        print(f"  [{idx}/{total}] {name}...", end=' ', flush=True)

        # Request embedding
        embedding = embed_text(text_blob)

        if embedding:
            # Store or update embedding
            embedding_blob = vector_to_blob(embedding)
            try:
                conn.execute('''
                    INSERT OR REPLACE INTO doc_embeddings (doc_id, embedding, model, updated_at)
                    VALUES (?, ?, ?, ?)
                ''', (doc_id, embedding_blob, EMBEDDING_MODEL, datetime.now().isoformat()))
                print("OK")
                embedded += 1
            except sqlite3.Error as e:
                print(f"ERROR: {e}")
                failed += 1
        else:
            print("FAILED")
            failed += 1

        # Batch commit every BATCH_SIZE docs
        if idx % BATCH_SIZE == 0:
            conn.commit()
            print(f"    [Committed {idx}/{total}]")

    # Final commit
    conn.commit()
    conn.close()

    elapsed = time.time() - start_time
    avg_time = (elapsed / embedded * 1000) if embedded > 0 else 0

    print(f"\nEmbedding complete:")
    print(f"  Total: {total}")
    print(f"  Embedded: {embedded}")
    print(f"  Failed: {failed}")
    print(f"  Time: {elapsed:.1f}s ({avg_time:.1f}ms per doc)")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <database_path> [limit]")
        print(f"\nExample:")
        print(f"  {sys.argv[0]} /mnt/data/git/AI/DocuBrowse/docs.db")
        print(f"  {sys.argv[0]} /mnt/data/git/AI/DocuBrowse/docs.db 10")
        sys.exit(1)

    db_path = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None

    print(f"Ollama host: {OLLAMA_HOST}")
    print(f"Model: {EMBEDDING_MODEL}")
    print()

    embed_docs(db_path, limit)
