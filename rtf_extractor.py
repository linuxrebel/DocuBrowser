#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
DocuBrowse RTF extractor.

Uses the ``striprtf`` package (pure Python, MIT, ARM64-safe).  If the
package isn't installed at scan time, the file is indexed metadata-only
(filename as title, empty body) and the path is appended to
``rtf_missing_striprtf.txt`` next to the database so an operator can
``pip install striprtf`` and rescan.  Same convention as
``visio_legacy_missing.txt`` for missing vsd2xml.
"""

from pathlib import Path


_TEXT_LIMIT    = 5000
_SNIPPET_LIMIT = 500


def _empty_result() -> dict:
    return {
        "title":       None,
        "author":      None,
        "subject":     None,
        "description": "",
        "text":        "",
        "snippet":     "",
        "doc_type":    "rtf",
        "success":     False,
        "error":       None,
    }


def extract_rtf(file_path: str) -> dict:
    """Extract plain text from a .rtf file.

    Returns success=False with a specific error string when the
    ``striprtf`` module isn't importable, so scan_docs can route to the
    metadata-only degradation path.
    """
    result = _empty_result()
    try:
        from striprtf.striprtf import rtf_to_text
    except ImportError:
        result["error"] = "striprtf not installed (pip install striprtf)"
        result["title"] = Path(file_path).stem
        return result

    try:
        with open(file_path, encoding="utf-8", errors="replace") as fh:
            raw = fh.read(500_000)      # RTF is bulky; read a generous head
        text = rtf_to_text(raw, errors="ignore").strip()
    except Exception as exc:
        result["error"] = str(exc)
        return result

    result["title"]   = Path(file_path).stem
    result["text"]    = text[:_TEXT_LIMIT]
    result["snippet"] = text[:_SNIPPET_LIMIT]
    result["success"] = True
    return result
