#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
DocuBrowse PII purge tool.

Scans the document index for PII patterns in stored text (description +
content_snippet fields), removes matching documents from the database, and
records them in pii_blacklist.txt so they are never re-ingested.

Limitation: only the ~800 chars of stored description/snippet are checked.
PII buried deeper in a document is not detected by this pass.  Run rescan
after a corpus cleanup to refresh the stored text, then run purge again.

Usage:
    purge_pii.py [db_path] [--dry-run]
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from docubrowse_db import get_db


PII_BLACKLIST_FILENAME = "pii_blacklist.txt"

# ── PII regex patterns ────────────────────────────────────────────────────────
# Checked against description + content_snippet (~800 chars of stored text).
# Each entry: (display_name, compiled_regex)

_PII_PATTERNS = [
    # Negative lookbehind for digit or hyphen prevents ISBN/phone substring matches.
    # ISBNs have more digits before the SSN-like suffix (e.g. 978-90-5940-365-9).
    ("SSN",
     re.compile(r'(?<![0-9\-])\b\d{3}-\d{2}-\d{4}\b(?![0-9\-])')),

    ("Credit Card",
     re.compile(r'\b(?:\d{4}[\s\-]){3}\d{4}\b')),

    ("Passport Number",
     re.compile(r'\b(?:passport|pass\s*(?:no|number|#))[:\s]+[A-Z]{1,2}\d{7,9}\b',
                re.IGNORECASE)),

    ("Date of Birth",
     re.compile(
         r'\b(?:dob|date\s+of\s+birth|born)[:\s]+\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b',
         re.IGNORECASE,
     )),

    ("Medical Record Number",
     re.compile(
         r'\b(?:mrn|medical\s+record(?:\s+number)?|patient\s+id)[:\s#]+\d{4,12}\b',
         re.IGNORECASE,
     )),

    ("Driver License",
     re.compile(
         r"\b(?:driver'?s?\s+licen[sc]e|dl\s+#?|license\s+#?)[:\s]+[A-Z0-9]{5,15}\b",
         re.IGNORECASE,
     )),
]


def _pii_blacklist_add(db_path: Path, file_path: str, pattern_name: str) -> None:
    """Append a PII-flagged file to pii_blacklist.txt with timestamp and reason."""
    bl_path = db_path.parent / PII_BLACKLIST_FILENAME
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = (
        f"# Added {timestamp} — PII detected: {pattern_name}\n"
        f"{file_path}\n"
    )
    with open(bl_path, "a", encoding="utf-8") as fh:
        fh.write(entry)


def _scan_text(text: str) -> list:
    """Return list of (pattern_name, matched_text) for all PII hits in text."""
    hits = []
    for name, pat in _PII_PATTERNS:
        m = pat.search(text)
        if m:
            hits.append((name, m.group()))
    return hits


def run_purge(db_path: str, dry_run: bool = False) -> int:
    """Run the PII purge.  Returns the number of matching documents found
    (dry-run) or removed (live).  Returns 0 if nothing matched."""
    db_path = Path(db_path)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}")
        sys.exit(1)

    conn = get_db(str(db_path))

    rows = conn.execute("""
        SELECT id, path, name, description, content_snippet
        FROM documents
        ORDER BY name COLLATE NOCASE
    """).fetchall()

    total = len(rows)
    hits  = []   # list of (doc_id, path, name, matches)

    print(f"Scanning {total:,} documents for PII...")
    print(f"Patterns: {', '.join(p[0] for p in _PII_PATTERNS)}")
    print(f"Mode:     "
          f"{'DRY RUN — no changes will be made' if dry_run else 'LIVE — matching docs will be removed'}")
    print()

    for row in rows:
        doc_id   = row["id"]
        path     = row["path"]
        name     = row["name"]
        desc     = row["description"] or ""
        snippet  = row["content_snippet"] or ""
        combined = f"{desc}\n{snippet}"
        matches  = _scan_text(combined)
        if matches:
            hits.append((doc_id, path, name, matches))

    if not hits:
        print("No PII detected in stored document text.")
        print()
        print("NOTE: Only the stored description/snippet (~800 chars) was checked.")
        print("PII buried deeper in a file will not be caught by this pass.")
        conn.close()
        return 0

    print(f"Found {len(hits):,} document(s) with potential PII:\n")
    for doc_id, path, name, matches in hits:
        pattern_names = ", ".join(m[0] for m in matches)
        print(f"  [{doc_id:>6}]  {name}")
        print(f"            Pattern(s): \033[93m{pattern_names}\033[0m")
        print(f"            {path}")
        print()

    if dry_run:
        print(f"DRY RUN complete — {len(hits):,} document(s) would be removed.")
        conn.close()
        return len(hits)

    # Interactive confirmation before any destructive action
    pii_bl = db_path.parent / PII_BLACKLIST_FILENAME
    print(f"About to permanently remove {len(hits):,} document(s) from the index.")
    print(f"They will be added to: {pii_bl}")
    print("They will NEVER be re-ingested (pii_blacklist.txt is permanent).")
    print()
    answer = input("Proceed? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        print("Aborted — no changes made.")
        conn.close()
        return

    # Delete all matches in a single transaction — all-or-nothing.
    # Blacklist is written only AFTER a successful commit so it stays in sync.
    print()
    to_blacklist = []   # (path, pattern_names, name) — populated only on success
    errors = 0

    for doc_id, path, name, matches in hits:
        pattern_names = ", ".join(m[0] for m in matches)
        try:
            # Cascade deletes doc_tags and doc_embeddings via FK ON DELETE CASCADE.
            # doc_fts is a contentless FTS5 virtual table — SQLite does not support
            # direct DELETE on contentless FTS5.  The search handler does not query
            # doc_fts directly (it does Python-side keyword matching), so orphaned
            # FTS entries for deleted documents are harmless.
            conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            to_blacklist.append((path, pattern_names, name))
        except Exception as exc:
            errors += 1
            print(f"  \033[91mERROR\033[0m    {name}: {exc}", file=sys.stderr)

    if errors:
        conn.rollback()
        conn.close()
        print(f"\n{errors} error(s) during delete — rolled back all changes.")
        print("No documents were removed and pii_blacklist.txt was not modified.")
        sys.exit(1)

    # All deletes succeeded — commit to DB, then record in blacklist
    conn.commit()
    conn.close()

    removed = len(to_blacklist)
    for path, pattern_names, name in to_blacklist:
        _pii_blacklist_add(db_path, path, pattern_names)
        print(f"  \033[92mRemoved\033[0m  {name}  ({pattern_names})")

    print()
    print("=" * 60)
    print(f"  Removed:   {removed:,}")
    print(f"  Blacklist: {pii_bl}")
    print("=" * 60)
    print()
    print("NOTE: Only the stored description/snippet (~800 chars) was checked.")
    print("Documents with PII buried deeper may not have been detected.")
    print("After cleaning the source files, run rescan then purge again.")
    return removed


def build_parser():
    p = argparse.ArgumentParser(
        description="Scan the DocuBrowse index for PII and remove matching documents",
    )
    p.add_argument(
        "db_path", nargs="?",
        default="/mnt/data/git/AI/DocuBrowse/du-docs.db",
        help="Path to SQLite database (default: du-docs.db in repo)",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Report matches without removing anything or writing the blacklist",
    )
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    try:
        run_purge(args.db_path, dry_run=args.dry_run)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
