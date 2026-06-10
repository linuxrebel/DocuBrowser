#!/usr/bin/env python3
"""
triage_blacklist.py — One-off tool to reclassify existing scan_blacklist.txt entries.

For each PDF in the blacklist:
  - If the file has image pages but no text chars → scanned PDF
    → append to ocr_list_pdfs.txt, remove from blacklist
  - Otherwise → genuinely broken/unreadable
    → keep in blacklist

Each PDF is checked in a subprocess with a 30s timeout — same pathological
PDFs that hang pdfplumber in the main scanner will timeout here instead of
blocking forever.

Usage:
    python3 triage_blacklist.py [--db /path/to/du-docs.db] [--dry-run]
"""

import argparse
import multiprocessing
import signal
import sys
from datetime import datetime
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    print("ERROR: pdfplumber not installed. Run: pip install pdfplumber", file=sys.stderr)
    sys.exit(1)

BLACKLIST_FILENAME = "scan_blacklist.txt"
OCR_LIST_FILENAME  = "ocr_list_pdfs.txt"
CHECK_TIMEOUT_SECS = 30


def _check_worker(path: str, result_queue: multiprocessing.Queue) -> None:
    """Run inside a subprocess — check page 0 for images vs chars."""
    # Ignore SIGINT in worker so Ctrl-C is handled by the parent only
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                result_queue.put((False, "no pages"))
                return
            page   = pdf.pages[0]
            chars  = len(page.chars)
            images = len(page.images)
            if chars == 0 and images > 0:
                result_queue.put((True, f"page 0: 0 chars, {images} image(s)"))
            elif chars == 0:
                result_queue.put((False, "page 0: 0 chars, 0 images — DRM or empty"))
            else:
                result_queue.put((False, f"page 0: {chars} chars — has text (unexpected)"))
    except Exception as e:
        result_queue.put((False, f"open error: {e}"))


def is_scanned_pdf(path: str) -> tuple[bool, str]:
    """
    Returns (is_scanned, reason).
    Runs pdfplumber in a subprocess with a timeout to avoid hangs on
    spread-layout or otherwise pathological PDFs.
    """
    p = Path(path)
    if not p.exists():
        return False, "file not found"
    if p.suffix.lower() != ".pdf":
        return False, "not a PDF"

    result_queue: multiprocessing.Queue = multiprocessing.Queue()
    proc = multiprocessing.Process(
        target=_check_worker,
        args=(path, result_queue),
        daemon=True,
    )
    proc.start()
    proc.join(timeout=CHECK_TIMEOUT_SECS)

    if proc.is_alive():
        proc.kill()
        proc.join()
        return False, f"timeout after {CHECK_TIMEOUT_SECS}s — likely pathological PDF (kept in blacklist)"

    if not result_queue.empty():
        return result_queue.get()

    return False, "worker exited without result"


def load_blacklist(bl_path: Path) -> list[tuple[str, str]]:
    """
    Returns list of (path, comment_block) preserving comment lines above each entry.
    comment_block is the raw comment text (may be empty string).
    """
    entries = []
    pending_comment = []
    for line in bl_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            pending_comment = []
            continue
        if stripped.startswith("#"):
            pending_comment.append(line)
        else:
            entries.append((stripped, "\n".join(pending_comment)))
            pending_comment = []
    return entries


def main():
    parser = argparse.ArgumentParser(
        description="Triage scan_blacklist.txt — separate scanned PDFs from broken ones"
    )
    parser.add_argument("--db", default="/mnt/data/git/AI/DocuBrowse/du-docs.db",
                        help="Path to du-docs.db (used to locate blacklist files)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would happen without making changes")
    args = parser.parse_args()

    db_path  = Path(args.db)
    bl_path  = db_path.parent / BLACKLIST_FILENAME
    ocr_path = db_path.parent / OCR_LIST_FILENAME
    dry_run  = args.dry_run

    if not bl_path.exists():
        print(f"No blacklist found at {bl_path}")
        sys.exit(0)

    entries = load_blacklist(bl_path)
    print(f"Triaging {len(entries)} blacklist entries  (timeout: {CHECK_TIMEOUT_SECS}s per file)")
    if dry_run:
        print("(DRY RUN — no files will be changed)\n")
    else:
        print()

    keep      = []   # (path, comment) — stays in blacklist
    to_ocr    = []   # paths to move to ocr_list_pdfs.txt
    not_found = []   # paths that no longer exist
    width     = len(str(len(entries)))

    try:
        for i, (path, comment) in enumerate(entries, 1):
            p = Path(path)
            print(f"  [{i:>{width}}/{len(entries)}] {p.name}", end="  ", flush=True)

            if not p.exists():
                print("MISSING")
                not_found.append((path, comment))
                continue

            if p.suffix.lower() != ".pdf":
                print(f"KEEP (not a PDF: {p.suffix})")
                keep.append((path, comment))
                continue

            scanned, reason = is_scanned_pdf(path)
            if scanned:
                print(f"SCANNED  ({reason})")
                to_ocr.append(path)
            else:
                print(f"KEEP  ({reason})")
                keep.append((path, comment))

    except KeyboardInterrupt:
        print("\n\nInterrupted — partial results shown.")

    print()
    print("=" * 60)
    print(f"  Total entries:     {len(entries)}")
    print(f"  Scanned (→ OCR):   {len(to_ocr)}")
    print(f"  Keep in blacklist: {len(keep)}")
    print(f"  Missing (dropped): {len(not_found)}")
    print()

    if dry_run:
        print("DRY RUN — no changes made.")
        if to_ocr:
            print(f"\nWould add to {ocr_path.name}:")
            for p in to_ocr:
                print(f"  {p}")
        return

    # Write updated blacklist (keep entries only)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(bl_path, "w", encoding="utf-8") as fh:
        fh.write(f"# scan_blacklist.txt — last triaged {timestamp}\n")
        fh.write(f"# {len(keep)} entries remaining after triage\n\n")
        for path, comment in keep:
            if comment:
                fh.write(comment + "\n")
            fh.write(path + "\n")

    # Append scanned PDFs to ocr_list_pdfs.txt (deduplicated)
    existing_ocr = set()
    if ocr_path.exists():
        for line in ocr_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                existing_ocr.add(line)

    new_ocr = [p for p in to_ocr if p not in existing_ocr]
    if new_ocr:
        with open(ocr_path, "a", encoding="utf-8") as fh:
            fh.write(f"# Added by triage_blacklist.py on {timestamp}\n")
            for p in new_ocr:
                fh.write(p + "\n")

    print(f"Updated {bl_path.name}:  {len(keep)} entries remaining")
    print(f"Added {len(new_ocr)} path(s) to {ocr_path.name}  ({len(to_ocr) - len(new_ocr)} already present)")


if __name__ == "__main__":
    multiprocessing.set_start_method("forkserver")
    main()
