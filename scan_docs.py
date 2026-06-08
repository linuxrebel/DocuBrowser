#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
DocuBrowse document scanner and indexer.
Walks directory, extracts content, generates tags, and upserts to database.
"""

import sys
import time
from datetime import datetime
from pathlib import Path

from docubrowse_db import get_db
from pdf_extractor import extract_pdf, generate_keywords


def scan_directory(doc_dir: str, db_path: str, extensions: list = None):
    """
    Scan directory for documents and index them.

    Args:
        doc_dir: Path to directory containing documents
        db_path: Path to SQLite database
        extensions: List of file extensions to process (e.g., ['.pdf', '.txt'])
    """
    doc_dir = Path(doc_dir)
    if not doc_dir.exists() or not doc_dir.is_dir():
        print(f"ERROR: Directory not found: {doc_dir}")
        return

    if extensions is None:
        extensions = ['.pdf', '.txt', '.md', '.html']

    # Ensure extensions have leading dot
    extensions = [e if e.startswith('.') else f'.{e}' for e in extensions]

    conn = get_db(str(db_path))

    print(f"Scanning {doc_dir}")
    print(f"  Extensions: {', '.join(extensions)}")
    print()

    start_time = time.time()
    found = 0
    extracted = 0
    failed = 0
    skipped = 0

    # Walk directory recursively
    for doc_file in sorted(doc_dir.rglob('*')):
        if not doc_file.is_file():
            continue

        # Check extension
        if doc_file.suffix.lower() not in extensions:
            continue

        found += 1
        print(f"[{found}] {doc_file.relative_to(doc_dir)}...", end=' ', flush=True)

        # Check if already indexed (optimization)
        existing = conn.execute(
            'SELECT id, modified_at FROM documents WHERE path = ?',
            (str(doc_file),)
        ).fetchone()

        # Check if file is modified since last index
        if existing:
            doc_id, indexed_modified = existing
            try:
                file_mtime = datetime.fromtimestamp(doc_file.stat().st_mtime).isoformat()
                if indexed_modified and indexed_modified >= file_mtime:
                    print("SKIP (not modified)")
                    skipped += 1
                    continue
            except OSError:
                pass

        # Extract document
        if doc_file.suffix.lower() == '.pdf':
            result = extract_pdf(str(doc_file))
        else:
            # Simple text extraction for TXT, MD, HTML
            result = extract_text_file(str(doc_file))

        if not result['success']:
            print(f"FAILED: {result.get('error', 'Unknown error')}")
            failed += 1
            continue

        # Upsert to database
        try:
            file_size = doc_file.stat().st_size
            file_mtime = datetime.fromtimestamp(doc_file.stat().st_mtime).isoformat()

            # Insert or update document
            cursor = conn.execute('''
                INSERT OR REPLACE INTO documents
                (name, path, size_bytes, file_ext, title, author, description,
                 content_snippet, modified_at, indexed_at, doc_type, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                doc_file.name,
                str(doc_file),
                file_size,
                doc_file.suffix.lower(),
                result['title'],
                result.get('author'),
                result.get('description'),
                result['snippet'],
                file_mtime,
                datetime.now().isoformat(),
                doc_file.suffix.lower()[1:],  # doc_type without dot
                datetime.now().isoformat()
            ))

            doc_id = cursor.lastrowid

            # Generate and store tags
            tags = set()

            # Auto-tag: extension
            tags.add(doc_file.suffix.lower()[1:])

            # Auto-tag: folder name
            for parent in doc_file.parents:
                if parent != doc_dir:
                    folder_name = parent.name.lower()
                    if len(folder_name) > 2:
                        tags.add(folder_name)

            # Auto-tag: keywords from extracted text
            keywords = generate_keywords(result['text'], result['title'], max_keywords=5)
            tags.update(keywords)

            # Store tags
            for tag in tags:
                conn.execute('''
                    INSERT OR IGNORE INTO doc_tags (doc_id, tag, source)
                    VALUES (?, ?, 'auto')
                ''', (doc_id, tag.lower()[:50]))  # Limit tag length

            # Update FTS index
            tags_str = ' '.join(tags)
            conn.execute('''
                INSERT OR REPLACE INTO doc_fts (rowid, name, title, description, tags, content_snippet)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                doc_id,
                doc_file.name,
                result['title'],
                result.get('description', ''),
                tags_str,
                result['snippet']
            ))

            conn.commit()
            print(f"OK ({len(tags)} tags)")
            extracted += 1

        except Exception as e:
            print(f"DB ERROR: {e}")
            failed += 1
            continue

    # Log scan
    try:
        conn.execute('''
            INSERT INTO scan_log (scanned_at, docs_found, docs_added, docs_updated)
            VALUES (?, ?, ?, ?)
        ''', (datetime.now().isoformat(), found, extracted, skipped))
        conn.commit()
    except Exception:
        pass

    conn.close()

    elapsed = time.time() - start_time

    print()
    print("=" * 60)
    print("SCAN SUMMARY")
    print("=" * 60)
    print(f"Time: {elapsed:.1f}s")
    print(f"Found: {found}")
    print(f"Extracted: {extracted}")
    print(f"Failed: {failed}")
    print(f"Skipped (not modified): {skipped}")
    if found > 0:
        success_rate = (extracted / found) * 100
        print(f"Success rate: {success_rate:.1f}%")


def extract_text_file(file_path: str) -> dict:
    """
    Extract text from TXT, MD, or HTML files.

    Args:
        file_path: Path to file

    Returns:
        Dictionary with extraction result
    """
    file_path = Path(file_path)

    result = {
        'title': file_path.stem,
        'author': None,
        'description': '',
        'text': '',
        'snippet': '',
        'success': False,
        'error': None
    }

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()

        if file_path.suffix.lower() == '.html':
            # Simple HTML text extraction
            import re
            # Remove script and style
            text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            # Remove HTML tags
            text = re.sub(r'<[^>]+>', '', text)
            # Decode HTML entities
            import html
            text = html.unescape(text)

        # Limit text
        result['text'] = text[:5000]
        result['snippet'] = text[:500]
        result['success'] = bool(result['text'])
        return result

    except Exception as e:
        result['error'] = str(e)
        return result


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <document_directory> [database_path]")
        print(f"\nExample:")
        print(f"  {sys.argv[0]} /mnt/data/Documents")
        print(f"  {sys.argv[0]} /mnt/data/Documents /mnt/data/git/AI/DocuBrowse/docs.db")
        sys.exit(1)

    doc_dir = sys.argv[1]
    db_path = sys.argv[2] if len(sys.argv) > 2 else '/mnt/data/git/AI/DocuBrowse/docs.db'

    scan_directory(doc_dir, db_path, extensions=['.pdf'])
