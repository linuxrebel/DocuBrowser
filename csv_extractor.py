#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
DocuBrowse CSV / TSV extractor.

Reads the first N rows of a CSV or TSV file and returns them as
pipe-delimited text (the same convention docx_extractor / odf_extractor
use for table rows).  The first row is captured as the ``description``
so column headers are highly weighted in keyword search.

No third-party dependency — stdlib ``csv``.
"""

import csv
from pathlib import Path


_TEXT_LIMIT    = 5000
_SNIPPET_LIMIT = 500
_MAX_ROWS      = 500     # generous — .csv/.tsv files are usually tabular
_MAX_CELL_LEN  = 200     # per-cell cap so runaway blobs don't dominate


def _empty_result(doc_type: str) -> dict:
    return {
        "title":       None,
        "author":      None,
        "subject":     None,
        "description": "",
        "text":        "",
        "snippet":     "",
        "doc_type":    doc_type,
        "success":     False,
        "error":       None,
    }


def extract_csv(file_path: str) -> dict:
    """Extract text from a .csv or .tsv file.

    Uses csv.Sniffer to auto-detect the delimiter; falls back to comma if
    detection fails (small samples defeat the sniffer).
    """
    ext = Path(file_path).suffix.lower().lstrip(".")
    result = _empty_result(ext if ext in ("csv", "tsv") else "csv")

    try:
        # utf-8-sig transparently strips a leading BOM if present, so a
        # Windows-Excel-saved CSV doesn't index its first column as
        # "﻿name".
        with open(file_path, encoding="utf-8-sig", errors="replace") as fh:
            sample = fh.read(8192)
            fh.seek(0)

            # Sniff the dialect from a sample; fall back to canonical CSV.
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
            except csv.Error:
                dialect = csv.excel   # comma-delimited default

            reader = csv.reader(fh, dialect)

            lines: list[str] = []
            header: list[str] = []
            for i, row in enumerate(reader):
                if i >= _MAX_ROWS:
                    break
                trimmed = [c[:_MAX_CELL_LEN].strip() for c in row]
                if not any(trimmed):
                    continue
                if i == 0:
                    header = trimmed
                lines.append(" | ".join(trimmed))

        if not lines:
            result["error"] = "empty CSV/TSV file"
            return result

        # Use filename stem as title (CSVs rarely embed one)
        result["title"] = Path(file_path).stem
        # Header line into description so column names weigh into keyword search
        if header:
            result["description"] = " | ".join(header)[:500]

        full = "\n".join(lines)
        result["text"]    = full[:_TEXT_LIMIT]
        result["snippet"] = full[:_SNIPPET_LIMIT]
        result["success"] = True
        return result

    except Exception as exc:
        result["error"] = str(exc)
        return result
