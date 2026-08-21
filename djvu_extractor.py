#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
DocuBrowse DjVu extractor.

Uses the ``djvutxt`` and ``djvused`` command-line tools from DjVuLibre
(external, non-pip — like ``vsd2xml`` for legacy Visio).  If DjVuLibre
isn't installed at scan time, the file is indexed metadata-only (filename
as title, empty body) and the path is appended to
``djvu_missing_djvulibre.txt`` next to the database so an operator can
install DjVuLibre and rescan.  Same convention as
``visio_legacy_missing.txt`` for missing vsd2xml.

A DjVu file with no text layer (image-only, never OCR'd) extracts cleanly
but yields no body text; it is indexed metadata-only.  OCR is out of scope,
mirroring how scanned PDFs are handled.

DjVuLibre install:
  Linux  — ``sudo dnf install djvulibre`` / ``sudo apt install djvulibre-bin``
  macOS  — ``brew install djvulibre``
  Windows— ``choco install djvu-libre`` (or Scoop / the DjVuLibre installer)
"""

import shutil
import subprocess
from pathlib import Path

_TEXT_LIMIT    = 5000
_SNIPPET_LIMIT = 500
_TIMEOUT_SECS  = 120


def _empty_result() -> dict:
    return {
        "title":       None,
        "author":      None,
        "subject":     None,
        "description": "",
        "text":        "",
        "snippet":     "",
        "doc_type":    "djvu",
        "success":     False,
        "error":       None,
    }


def _djvused_meta(file_path: str) -> dict:
    """Return {title, author, subject} from the DjVu metadata annotation.

    Most DjVu files carry no metadata; missing keys come back as None.
    """
    meta = {"title": None, "author": None, "subject": None}
    try:
        out = subprocess.run(
            ["djvused", file_path, "-e", "select 1; print-meta"],
            capture_output=True, text=True, errors="replace",
            timeout=_TIMEOUT_SECS, check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return meta
    # Lines look like:  Title\t"Some title"   /   Author  "Name"
    for line in out.splitlines():
        key, _, val = line.partition("\t")
        key = key.strip().lower()
        val = val.strip().strip('"').strip()
        if not val:
            continue
        if key == "title":
            meta["title"] = val
        elif key in ("author", "creator"):
            meta["author"] = val
        elif key in ("subject", "description"):
            meta["subject"] = val
    return meta


def extract_djvu(file_path: str) -> dict:
    """Extract text and metadata from a .djvu / .djv file via DjVuLibre.

    Returns success=False with a ``djvulibre not found`` error when the
    tools aren't on PATH, so scan_docs can route to the metadata-only
    degradation path (append to djvu_missing_djvulibre.txt).
    """
    result = _empty_result()

    if shutil.which("djvutxt") is None:
        result["error"] = "djvulibre not found (install djvulibre / djvulibre-bin)"
        result["title"] = Path(file_path).stem
        return result

    try:
        proc = subprocess.run(
            ["djvutxt", file_path],
            capture_output=True, text=True, errors="replace",
            timeout=_TIMEOUT_SECS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["error"] = str(exc)
        result["title"] = Path(file_path).stem
        return result

    if proc.returncode != 0:
        result["error"] = (proc.stderr or "djvutxt failed").strip()[:200]
        result["title"] = Path(file_path).stem
        return result

    text = proc.stdout.strip()
    meta = _djvused_meta(file_path)

    result["title"]   = meta["title"] or Path(file_path).stem
    result["author"]  = meta["author"]
    result["subject"] = meta["subject"]
    result["text"]    = text[:_TEXT_LIMIT]
    result["snippet"] = text[:_SNIPPET_LIMIT]
    if not text:
        result["description"] = "[DjVu — no text layer; OCR not performed]"
    result["success"] = True
    return result


if __name__ == "__main__":   # pragma: no cover — manual smoke check
    import sys
    r = extract_djvu(sys.argv[1])
    print(f"success={r['success']} title={r['title']!r} "
          f"author={r['author']!r} chars={len(r['text'])} err={r['error']!r}")
    print("--- snippet ---")
    print(r["snippet"])
