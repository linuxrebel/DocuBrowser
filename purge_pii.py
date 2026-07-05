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

try:
    import colorama
    colorama.init()
except ImportError:
    pass

from docubrowse_db import get_db, delete_document


PII_BLACKLIST_FILENAME = "pii_blacklist.txt"

# ── PII validators ────────────────────────────────────────────────────────────
# Structural identifiers (SSN, credit card) generate many false positives from
# bare digit runs (phone numbers, invoice/part numbers, ISBNs). A regex finds
# candidates; a validator then confirms the number is actually well-formed —
# Luhn for cards, SSA allocation rules for SSNs — before we flag (and, in live
# mode, DELETE) the document. This trades a little recall for much higher
# precision, which matters because the purge is destructive.

def _luhn_ok(digits: str) -> bool:
    """Return True if `digits` passes the Luhn checksum (credit-card check)."""
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = ord(ch) - 48
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _valid_ssn(m) -> bool:
    """Validate a candidate SSN against SSA allocation rules to reject
    invoice/part numbers that merely have the 3-2-4 shape."""
    digits = re.sub(r'\D', '', m.group())
    if len(digits) != 9 or len(set(digits)) == 1:   # e.g. 000000000 / 111111111
        return False
    area, group, serial = digits[:3], digits[3:5], digits[5:]
    # 000, 666 and 900-999 are never assigned; group/serial are never all zeros.
    if area in ("000", "666") or area[0] == "9":
        return False
    if group == "00" or serial == "0000":
        return False
    return True


def _valid_aba(m) -> bool:
    """Validate an ABA routing transit number via the standard checksum.
    Format: 9 digits, weighted sum (3·7·1 repeated) mod 10 == 0.
    Also rejects known test/invalid prefixes."""
    digits = re.sub(r'\D', '', m.group())
    if len(digits) != 9 or len(set(digits)) == 1:
        return False
    # ABA first two digits (Federal Reserve district) must be 00-12, 21-32,
    # 61-72, or 80. Reject anything outside that.
    prefix = int(digits[:2])
    valid_ranges = (
        (1, 12), (21, 32), (61, 72), (80, 80),
    )
    if not any(lo <= prefix <= hi for lo, hi in valid_ranges):
        return False
    # Weighted checksum: 3·d1 + 7·d2 + 1·d3 + 3·d4 + 7·d5 + 1·d6 + 3·d7 + 7·d8 + 1·d9
    weights = (3, 7, 1, 3, 7, 1, 3, 7, 1)
    total = sum(int(d) * w for d, w in zip(digits, weights))
    return total % 10 == 0


def _valid_cc(m) -> bool:
    """Validate a candidate card number: plausible PAN length, a real issuer
    prefix, and Luhn. The IIN check (cards begin 2-6: Amex/Diners/JCB 3,
    Visa 4, MasterCard 2 & 5, Discover/Maestro 6) rejects invoice/part numbers
    that merely have 16 digits and happen to pass Luhn."""
    digits = re.sub(r'\D', '', m.group())
    if len(digits) not in (13, 14, 15, 16, 19):
        return False
    if digits[0] not in "23456":
        return False
    return _luhn_ok(digits)


# ── PII regex patterns ────────────────────────────────────────────────────────
# Checked against description + content_snippet (~800 chars of stored text).
# Each entry: (display_name, compiled_regex, validator_or_None). The regex finds
# candidates; if a validator is present it must also return True for a hit.

_PII_PATTERNS = [
    # SSN, separated form — 3-2-4 with hyphen OR space separators. The
    # lookarounds keep it from matching inside a longer digit run (ISBN/phone),
    # and _valid_ssn applies SSA allocation rules.
    ("SSN",
     re.compile(r'(?<![0-9\-])\d{3}[-\s]\d{2}[-\s]\d{4}(?![0-9\-])'),
     _valid_ssn),

    # SSN, unseparated 9-digit run — too false-positive-prone on its own, so
    # only when an explicit SSN label precedes it.
    ("SSN",
     re.compile(r'(?:ssn|social\s+security(?:\s*(?:no|number|#))?)[:#\s]+(?<!\d)\d{9}(?!\d)',
                re.IGNORECASE),
     _valid_ssn),

    # Credit card — 13-19 digits, optionally split into groups by single
    # spaces/hyphens (covers 4-4-4-4, Amex 4-6-5, and contiguous). Luhn +
    # length in _valid_cc reject phone/part/invoice numbers.
    ("Credit Card",
     re.compile(r'(?<![0-9\-])(?:\d[ \-]?){12,18}\d(?![0-9\-])'),
     _valid_cc),

    ("Passport Number",
     re.compile(r'\b(?:passport|pass\s*(?:no|number|#))[:\s]+[A-Z]{1,2}\d{7,9}\b',
                re.IGNORECASE),
     None),

    ("Date of Birth",
     re.compile(
         r'\b(?:dob|date\s+of\s+birth|born)[:\s]+\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b',
         re.IGNORECASE,
     ),
     None),

    ("Medical Record Number",
     re.compile(
         r'\b(?:mrn|medical\s+record(?:\s+number)?|patient\s+id)[:\s#]+\d{4,12}\b',
         re.IGNORECASE,
     ),
     None),

    ("Driver License",
     re.compile(
         r"\b(?:driver'?s?\s+licen[sc]e|dl\s+#?|license\s+#?)[:\s]+[A-Z0-9]{5,15}\b",
         re.IGNORECASE,
     ),
     None),

    # ABA routing number — labeled form (keyword + 9 digits). Checksum-validated.
    ("Bank Routing Number",
     re.compile(
         r'\b(?:routing(?:\s+(?:transit\s+)?number)?|rtn|aba)[:\s#]+(?<!\d)\d{9}(?!\d)',
         re.IGNORECASE),
     _valid_aba),

    # ABA routing number — bare 9-digit form with separators (e.g. on checks).
    # Only flagged when checksum passes AND prefix is valid — keeps precision high.
    ("Bank Routing Number",
     re.compile(r'(?<![0-9\-])\d{9}(?![0-9\-])'),
     _valid_aba),

    # Bank account number — variable length (4-17 digits), requires a nearby
    # keyword to avoid flagging arbitrary digit runs. No checksum exists for
    # account numbers, so context is the only discriminator.
    ("Bank Account Number",
     re.compile(
         r'\b(?:(?:bank\s+)?account|acct)(?:\s+(?:no|number|#))?[:\s#]+(?<!\d)\d{4,17}(?!\d)',
         re.IGNORECASE),
     None),
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
    """Return list of (pattern_name, matched_text) for all PII hits in text.
    A pattern with a validator only counts a match the validator accepts; one
    confirmed hit per pattern is enough to flag the document."""
    hits = []
    for name, pat, validator in _PII_PATTERNS:
        for m in pat.finditer(text):
            if validator is None or validator(m):
                hits.append((name, m.group()))
                break
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
    try:
        answer = input("Proceed? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        # Non-interactive stdin (pipe/cron/systemd) or Ctrl-C: abort safely
        # instead of crashing with an uncaught EOFError.
        print("\nAborted — no interactive confirmation available, no changes made.")
        conn.close()
        return 0
    if answer not in ("y", "yes"):
        print("Aborted — no changes made.")
        conn.close()
        return 0

    # Delete all matches in a single transaction — all-or-nothing.
    # Blacklist is written only AFTER a successful commit so it stays in sync.
    print()
    to_blacklist = []   # (path, pattern_names, name) — populated only on success
    errors = 0

    for doc_id, path, name, matches in hits:
        pattern_names = ", ".join(m[0] for m in matches)
        try:
            # Shared helper: CASCADEs to tags/embeddings, leaves the harmless
            # contentless-FTS orphan. commit=False keeps the whole purge
            # all-or-nothing (committed once below, rolled back on any error).
            delete_document(conn, doc_id, commit=False)
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
        default=str(Path(__file__).resolve().parent / "du-docs.db"),
        help="Path to SQLite database (default: du-docs.db next to this script)",
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
