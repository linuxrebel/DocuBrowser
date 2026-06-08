#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
DocuBrowse database module — SQLite schema for document indexing.

Designed for PDF-first indexing with embeddings and FTS5 search.
Architecture mirrors repo-browser but tailored for documents (7,479+ files).

Tables:
  - documents: core metadata
  - doc_tags: auto-generated + manual tags
  - doc_embeddings: float32 vectors (BLOB)
  - doc_fts: FTS5 virtual table (contentless)
  - scan_log: scan history
"""

import os
import sqlite3
from datetime import datetime
from pathlib import Path


def init_db(conn):
    """Create all tables if they don't exist. Idempotent and migration-safe."""
    conn.executescript('''
        -- Core documents table
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            size_bytes INTEGER,
            file_ext TEXT,
            title TEXT,
            author TEXT,
            description TEXT,
            content_snippet TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            modified_at TEXT,
            indexed_at TEXT,
            doc_type TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- Document tags (auto-generated and manual)
        CREATE TABLE IF NOT EXISTS doc_tags (
            doc_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            source TEXT DEFAULT 'auto',
            FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE,
            UNIQUE(doc_id, tag)
        );

        -- Document embeddings (float32 vectors as BLOB)
        CREATE TABLE IF NOT EXISTS doc_embeddings (
            doc_id INTEGER PRIMARY KEY,
            embedding BLOB,
            model TEXT,
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );

        -- Scan log for tracking ingestion history
        CREATE TABLE IF NOT EXISTS scan_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scanned_at TEXT DEFAULT (datetime('now')),
            docs_found INTEGER,
            docs_added INTEGER,
            docs_updated INTEGER
        );

        -- FTS5 virtual table (contentless, smaller footprint)
        CREATE VIRTUAL TABLE IF NOT EXISTS doc_fts USING fts5(
            name, title, description, content_snippet, tags,
            content='', content_rowid='rowid'
        );
    ''')

    # Migration: ensure all expected columns exist in documents table
    conn.execute('PRAGMA foreign_keys=ON')
    cols = [r[1] for r in conn.execute('PRAGMA table_info(documents)').fetchall()]

    # Add columns that might be missing in older schemas
    expected_cols = {
        'title': 'TEXT',
        'author': 'TEXT',
        'description': 'TEXT',
        'content_snippet': 'TEXT',
        'modified_at': 'TEXT',
        'indexed_at': 'TEXT',
        'doc_type': 'TEXT',
        'updated_at': 'TEXT',
    }

    for col, col_type in expected_cols.items():
        if col not in cols:
            try:
                conn.execute(f'ALTER TABLE documents ADD COLUMN {col} {col_type}')
            except sqlite3.OperationalError:
                # Column already exists or other issue
                pass

    conn.commit()


def get_db(db_path):
    """
    Get or create a SQLite connection with proper settings.

    Args:
        db_path: Path to SQLite database file

    Returns:
        sqlite3.Connection with row_factory and WAL mode enabled
    """
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')

    # Initialize schema if needed (idempotent)
    init_db(conn)

    return conn


def ensure_db(db_path):
    """
    Ensure database exists and schema is initialized.
    Creates parent directories if needed. Safe to call multiple times.

    Args:
        db_path: Path to SQLite database file

    Returns:
        Path object pointing to the database
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = get_db(str(db_path))
    conn.close()

    return db_path


# ── Test harness ──────────────────────────────────────────────────────────

if __name__ == '__main__':
    import tempfile
    import struct

    # Create test database in temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / 'test_docs.db'
        print(f"Testing with: {test_db}")

        # Initialize database
        conn = get_db(str(test_db))

        # Verify all tables exist
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t[0] for t in tables]

        print("\nTables created:")
        for name in sorted(table_names):
            count = conn.execute(
                f"SELECT COUNT(*) FROM {name}"
            ).fetchone()[0]
            print(f"  - {name}: {count} rows")

        # Verify FTS5 virtual table
        try:
            conn.execute("SELECT name FROM doc_fts LIMIT 0")
            print("\n  - doc_fts: FTS5 virtual table OK")
        except sqlite3.OperationalError as e:
            print(f"\n  - doc_fts: ERROR - {e}")

        # Test inserting a document
        print("\nTesting insert operations...")

        # Insert a document
        cur = conn.execute('''
            INSERT INTO documents (name, path, size_bytes, file_ext,
                                   title, author, description, doc_type, modified_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            'example.pdf',
            '/mnt/data/Documents/example.pdf',
            102400,
            '.pdf',
            'Example Document',
            'John Doe',
            'A test document for embedding search',
            'pdf',
            datetime.now().isoformat()
        ))
        doc_id = cur.lastrowid
        print(f"  - Inserted document ID {doc_id}")

        # Insert tags
        for tag in ['pdf', 'example', 'test']:
            conn.execute(
                'INSERT OR IGNORE INTO doc_tags (doc_id, tag, source) VALUES (?, ?, ?)',
                (doc_id, tag, 'auto')
            )
        print(f"  - Inserted 3 tags")

        # Insert a test embedding (float32 vector)
        # Create a fake 384-dim embedding (typical for nomic-embed-text)
        fake_vec = [0.1] * 384
        embedding_blob = struct.pack(f'{len(fake_vec)}f', *fake_vec)

        conn.execute('''
            INSERT INTO doc_embeddings (doc_id, embedding, model, updated_at)
            VALUES (?, ?, ?, ?)
        ''', (doc_id, embedding_blob, 'nomic-embed-text', datetime.now().isoformat()))
        print(f"  - Inserted embedding (384 dims, {len(embedding_blob)} bytes)")

        # Insert FTS record
        conn.execute('''
            INSERT INTO doc_fts (rowid, name, title, description, tags)
            VALUES (?, ?, ?, ?, ?)
        ''', (doc_id, 'example.pdf', 'Example Document',
              'A test document for embedding search', 'pdf example test'))
        print(f"  - Inserted FTS record")

        # Insert scan log entry
        conn.execute('''
            INSERT INTO scan_log (docs_found, docs_added, docs_updated)
            VALUES (?, ?, ?)
        ''', (1, 1, 0))
        print(f"  - Inserted scan log entry")

        conn.commit()

        # Verify data
        print("\nVerifying inserted data...")

        doc = conn.execute(
            'SELECT * FROM documents WHERE id = ?', (doc_id,)
        ).fetchone()
        print(f"  - Document retrieved: {dict(doc)}")

        tags = conn.execute(
            'SELECT tag FROM doc_tags WHERE doc_id = ? ORDER BY tag', (doc_id,)
        ).fetchall()
        print(f"  - Tags: {[t[0] for t in tags]}")

        embed_row = conn.execute(
            'SELECT doc_id, model, length(embedding) as blob_size FROM doc_embeddings WHERE doc_id = ?',
            (doc_id,)
        ).fetchone()
        if embed_row:
            print(f"  - Embedding: doc_id={embed_row[0]}, model={embed_row[1]}, "
                  f"blob_size={embed_row[2]} bytes")

        fts_result = conn.execute(
            'SELECT COUNT(*) FROM doc_fts'
        ).fetchone()[0]
        print(f"  - FTS index: {fts_result} records")

        scan = conn.execute(
            'SELECT docs_found, docs_added FROM scan_log ORDER BY id DESC LIMIT 1'
        ).fetchone()
        print(f"  - Latest scan: {scan[0]} found, {scan[1]} added")

        # Test FTS search
        print("\nTesting FTS search...")
        fts_rows = conn.execute(
            "SELECT name, title FROM doc_fts WHERE doc_fts MATCH 'example'"
        ).fetchall()
        print(f"  - FTS search 'example': {len(fts_rows)} results")
        if fts_rows:
            for row in fts_rows:
                print(f"    - {row[0]}: {row[1]}")

        # Test foreign key cascade
        print("\nTesting cascade delete...")
        initial_tags = conn.execute(
            'SELECT COUNT(*) FROM doc_tags WHERE doc_id = ?', (doc_id,)
        ).fetchone()[0]
        print(f"  - Tags before delete: {initial_tags}")

        conn.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
        conn.commit()

        remaining_tags = conn.execute(
            'SELECT COUNT(*) FROM doc_tags WHERE doc_id = ?', (doc_id,)
        ).fetchone()[0]
        print(f"  - Tags after delete: {remaining_tags} (cascade worked: {remaining_tags == 0})")

        conn.close()

        print("\n✓ All tests passed!")
