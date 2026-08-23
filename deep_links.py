#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
Deep Links — in-document passage locator.

Given a document, a query, and a mode, return the passages inside the document
that best match the query, each with a human location label ("line 3", "p. 12",
"section 4"), a short sample, an excerpt, and the match span for the UI to
highlight. Computed on demand; no DB, no schema change. See the design at
docs/superpowers/specs/2026-08-21-deep-links-design.md.

Pure functions, independently testable — no server or UI dependencies.
"""

import re
from pathlib import Path

try:
    import docx as _docx           # python-docx (imported as ``docx``)
except ImportError:
    _docx = None

try:
    from striprtf.striprtf import rtf_to_text as _rtf_to_text
except ImportError:
    _rtf_to_text = None

try:
    from odf_extractor import extract_odf as _extract_odf
except ImportError:
    _extract_odf = None

try:
    import pdfplumber as _pdfplumber
except ImportError:
    _pdfplumber = None

# Cap pages scanned per PDF to bound latency (mirrors pdf_extractor.MAX_PAGES).
_PDF_MAX_PAGES = 150

# Non-prose formats (by extension): tabular/fragmented extracted text that we
# do not render in-app. Deep Links returns an "unsupported" result for these.
_NON_PROSE_EXT = frozenset({
    "xlsx", "ods", "csv", "tsv",          # spreadsheets
    "pptx", "odp",                        # presentations
    "vsdx", "vsd", "vdx", "svg",          # diagrams
})

_WORD_RE = re.compile(r"[A-Za-z0-9]+")

# Words either side of the best match to build the 8-10 word sample.
_SAMPLE_RADIUS = 5


def _query_tokens(query):
    """Lowercased word tokens of the query."""
    return [t.lower() for t in _WORD_RE.findall(query)]


def _score_and_mark(text, tokens):
    """
    Score *text* against query *tokens* and locate the first match.

    Returns (score, match_start, match_end) where score is the count of token
    occurrences (whole-word, case-insensitive) and the span points at the first
    matched token in *text*. score == 0 means no match.
    """
    if not tokens:
        return 0, None, None
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(t) for t in tokens) + r")\b",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return 0, None, None
    first = matches[0]
    return len(matches), first.start(), first.end()


def _sample_around(text, start, end):
    """8-10 word window of *text* centered on the [start:end] match."""
    before = text[:start].split()
    after = text[end:].split()
    matched = text[start:end]
    left = before[-_SAMPLE_RADIUS:]
    right = after[:_SAMPLE_RADIUS]
    return " ".join([*left, matched, *right]).strip()


def _passage(excerpt, location, score, match_start, match_end):
    """Build a Passage dict, translating the match span into the excerpt."""
    return {
        "sample": _sample_around(excerpt, match_start, match_end),
        "excerpt": excerpt,
        "location": location,
        "score": score,
        "match_start": match_start,
        "match_end": match_end,
    }


def _units_txt(path):
    """Yield (location, text) per line of a plain-text file (1-based lines)."""
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    for i, line in enumerate(lines, start=1):
        if line.strip():
            yield (f"line {i}", line)


def _units_docx(path):
    """Yield (location, text) per body paragraph of a .docx (1-based index)."""
    if _docx is None:
        return
    doc = _docx.Document(path)
    idx = 0
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        idx += 1
        yield (f"section {idx}", text)


def _units_rtf(path):
    """Yield (location, text) per line of a .rtf. RTF has no pages → line-based."""
    if _rtf_to_text is None:
        return
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    text = _rtf_to_text(raw, errors="ignore")
    for i, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            yield (f"line {i}", line.strip())


def _units_odt(path):
    """Yield (location, text) per paragraph of a .odt (1-based index).

    Reuses odf_extractor, which joins paragraphs (and table rows) with '\\n';
    splitting that back on newlines recovers the paragraph structure.
    """
    if _extract_odf is None:
        return
    result = _extract_odf(path)
    if not result.get("success"):
        return
    idx = 0
    for para in result.get("text", "").split("\n"):
        para = para.strip()
        if not para:
            continue
        idx += 1
        yield (f"section {idx}", para)


def _units_pdf(path):
    """Yield (location, text) per paragraph, carrying the page number as 'p. N'.

    Pages that extract to nothing (e.g. scanned/image-only) are skipped.
    """
    if _pdfplumber is None:
        return
    with _pdfplumber.open(path) as pdf:
        for pageno, page in enumerate(pdf.pages[:_PDF_MAX_PAGES], start=1):
            try:
                text = page.extract_text() or ""
            except (ValueError, KeyError, IndexError, TypeError):
                text = ""
            if not text.strip():
                continue
            # Split into paragraphs on blank lines; each carries the page label.
            for para in re.split(r"\n\s*\n", text):
                para = para.strip()
                if para:
                    yield (f"p. {pageno}", para)


# Extension → unit-iterator.
_UNIT_ITERATORS = {
    "txt": _units_txt,
    "docx": _units_docx,
    "rtf": _units_rtf,
    "odt": _units_odt,
    "pdf": _units_pdf,
}


def locate_passages(path, query, mode, *, max_passages=200):
    """
    Locate the passages in *path* that match *query*.

    mode is "keyword" or "semantic". Returns either
    {"unsupported": True, "reason": ...} for non-prose formats, or
    {"passages": [Passage, ...], "truncated": bool}.
    """
    # ponytail: only keyword mode is wired up in Phase 1; semantic ranking
    # (embed + cosine) is added in Step 2 and will branch on `mode` here.
    del mode
    ext = Path(path).suffix.lstrip(".").lower()
    if ext in _NON_PROSE_EXT:
        return {"unsupported": True, "reason": f"non-prose format: .{ext}"}

    iterator = _UNIT_ITERATORS.get(ext)
    if iterator is None:
        # Formats not yet supported behave as an empty (no-passages) result.
        return {"passages": [], "truncated": False}

    tokens = _query_tokens(query)
    scored = []
    for location, text in iterator(path):
        score, ms, me = _score_and_mark(text, tokens)
        if score > 0:
            scored.append(_passage(text, location, score, ms, me))

    scored.sort(key=lambda p: p["score"], reverse=True)
    truncated = len(scored) > max_passages
    return {"passages": scored[:max_passages], "truncated": truncated}
