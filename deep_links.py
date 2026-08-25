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

import contextlib
import html as _html
import io
import math
import re
import shutil
import subprocess
import warnings
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

try:
    import ebooklib as _ebooklib
    from ebooklib import epub as _epub
except ImportError:
    _ebooklib = None
    _epub = None

try:
    import mobi as _mobi
except ImportError:
    _mobi = None

try:
    from eml_extractor import extract_eml as _extract_eml
except ImportError:
    _extract_eml = None

# Cap pages scanned per PDF to bound latency (mirrors pdf_extractor.MAX_PAGES).
_PDF_MAX_PAGES = 150

# Cap passages embedded per document in semantic mode, before ranking. One
# /api/embed call must stay under the socket timeout: a large book yields
# thousands of passages, and embedding all of them times out. Keyword mode
# still scans the whole document, so exact terms are found everywhere.
_SEMANTIC_SCAN_CAP = 300

# Minimum cosine similarity for a passage to count as relevant. Below this the
# passage is dropped, so a query with no real match in the document returns no
# passages instead of the top-N noise. Calibrated on nomic-embed-text: genuine
# topic matches score ~0.6-0.7, unrelated tokens ~0.45.
_SEMANTIC_MIN_SIM = 0.5

# Non-prose formats (by extension): tabular/fragmented extracted text that we
# do not render in-app. Deep Links returns an "unsupported" result for these.
_NON_PROSE_EXT = frozenset({
    "xlsx", "ods", "ots", "csv", "tsv",           # spreadsheets (+ template)
    "pptx", "odp", "otp",                         # presentations (+ template)
    "vsdx", "vsdm", "vsd", "vss", "vst", "vdx",   # Visio
    "drawio", "dio", "svg",                       # other diagrams
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


# Block-level tags (HTML + common XML/DocBook/RSS/Atom containers) whose
# boundaries become passage breaks. Mirrors the indexer's tag-strip
# (scan_docs._extract_text_file), plus newline insertion at blocks so
# paragraphs/headings/items become separate passages instead of one blob.
_MARKUP_BLOCK_RE = re.compile(
    r"</(?:p|div|h[1-6]|li|tr|section|article|header|footer|blockquote|pre|"
    r"td|th|figcaption|dd|dt|"                             # HTML
    r"para|item|entry|description|abstract|note|"          # XML/DocBook/RSS/Atom
    r"sect\d|chapter|listitem|term|outline)>|<br\s*/?>",   # (title/summary left in-block)
    re.IGNORECASE,
)
_MARKUP_READ_LIMIT = 200_000   # bounded read, matches _extract_text_file


def _markup_blocks(raw):
    """Yield non-empty text blocks from an HTML/XML string (tags stripped)."""
    raw = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"<style[^>]*>.*?</style>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = _MARKUP_BLOCK_RE.sub("\n", raw)        # block boundaries → newlines
    text = _html.unescape(re.sub(r"<[^>]+>", "", raw))   # strip remaining tags
    for block in text.split("\n"):
        block = " ".join(block.split())          # collapse whitespace runs
        if block:
            yield block


def _units_markup(path):
    """Yield (location, text) per block of an HTML/XML/SGML file, 'section N'."""
    raw = Path(path).read_text(encoding="utf-8", errors="replace")[:_MARKUP_READ_LIMIT]
    for idx, block in enumerate(_markup_blocks(raw), start=1):
        yield (f"section {idx}", block)


def _units_epub(path):
    """Yield (location, text) per block of an EPUB, labelled by chapter.

    Iterates the spine documents (chapters) via ebooklib and block-splits each
    chapter's XHTML — full-book coverage, not the 5000-char index cap.
    """
    if _ebooklib is None:
        return
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")          # ebooklib's rootfile-XPath noise
        book = _epub.read_epub(path, options={"ignore_ncx": True})
    chapter = 0
    for item in book.get_items_of_type(_ebooklib.ITEM_DOCUMENT):
        html = item.get_content().decode("utf-8", "replace")
        blocks = list(_markup_blocks(html))
        if not blocks:
            continue
        chapter += 1
        for block in blocks:
            yield (f"chapter {chapter}", block)


def _units_mobi(path):
    """Yield blocks for MOBI/AZW3/AZW by unpacking to EPUB/HTML via the mobi pkg.

    The mobi package wraps most files as EPUB (→ chapter labels) or raw HTML
    (→ 'section N'). DRM-encrypted files (typical .azw) can't be unpacked and
    yield nothing — consistent with their metadata-only index entry.
    """
    if _mobi is None:
        return
    tempdir = None
    try:
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            tempdir, main_file = _mobi.extract(path)
        main = Path(main_file)
        if main.suffix.lower() == ".epub":
            yield from _units_epub(str(main))
        else:
            raw = main.read_text(encoding="utf-8", errors="replace")
            for idx, block in enumerate(_markup_blocks(raw), start=1):
                yield (f"section {idx}", block)
    except Exception:  # pylint: disable=broad-exception-caught
        return          # corrupt / DRM / unsupported → no passages (graceful)
    finally:
        if tempdir:
            shutil.rmtree(tempdir, ignore_errors=True)


def _units_djvu(path):
    """Yield (location, text) per paragraph of a DjVu, carrying the page as 'p. N'.

    djvutxt (DjVuLibre) prints the whole document with pages separated by a
    form-feed; split on that, then paragraph-split each page like the PDF path.
    """
    if shutil.which("djvutxt") is None:
        return
    try:
        proc = subprocess.run(["djvutxt", path], capture_output=True, text=True,
                               errors="replace", timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return
    if proc.returncode != 0:
        return
    for pageno, page in enumerate(proc.stdout.split("\f"), start=1):
        for para in re.split(r"\n\s*\n", page):
            para = " ".join(para.split())
            if para:
                yield (f"p. {pageno}", para)


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


def _units_eml(path):
    """Yield (location, text) per line of an email's extracted text."""
    if _extract_eml is None:
        return
    result = _extract_eml(path)
    if not result.get("success"):
        return
    for i, line in enumerate(result.get("text", "").splitlines(), start=1):
        line = line.strip()
        if line:
            yield (f"line {i}", line)


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
# Plain-text formats (line-based) and markup formats (tag-stripped) that share
# the txt / markup iterators. svg and vdx stay in _NON_PROSE_EXT (diagrams).
_TEXT_EXTS = ("txt", "text", "md", "markdown",
              "ini", "conf", "cfg", "log", "lst",
              "rst", "adoc", "asciidoc", "tex", "latex",
              # text diagram sources
              "puml", "plantuml", "mmd",
              # data / config
              "json", "yml", "yaml", "toml",
              # source code
              "py", "sh", "js", "css", "rb", "php",
              "c", "cc", "cpp", "h", "hpp",
              "rs", "go", "java", "ts", "tsx", "jsx")
_MARKUP_EXTS = ("html", "htm", "xhtml", "xml", "sgml", "sgm",
                "docbook", "dbk", "rss", "atom", "opml")

_UNIT_ITERATORS = {
    **{e: _units_txt for e in _TEXT_EXTS},
    **{e: _units_markup for e in _MARKUP_EXTS},
    "docx": _units_docx,
    "rtf": _units_rtf,
    "odt": _units_odt,
    "ott": _units_odt,     # ODF text template — same path as .odt
    "eml": _units_eml,
    "pdf": _units_pdf,
    "epub": _units_epub,
    "mobi": _units_mobi,
    "azw3": _units_mobi,
    "azw": _units_mobi,
    "djvu": _units_djvu,
    "djv": _units_djvu,
}


def _cosine(a, b):
    """Cosine similarity of two equal-length vectors; 0 if either is zero."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _sentence_spans(text):
    """Yield (start, end, sentence) spans over *text*. Whole text if no breaks."""
    spans = []
    for m in re.finditer(r"[^.!?]*[.!?]+|[^.!?]+$", text):
        s = m.group().strip()
        if not s:
            continue
        start = text.index(s, m.start())
        spans.append((start, start + len(s), s))
    return spans or [(0, len(text), text)]


def _keyword_passages(units, query, max_passages):
    """Rank passages by whole-word query-term match count."""
    tokens = _query_tokens(query)
    scored = []
    for location, text in units:
        score, ms, me = _score_and_mark(text, tokens)
        if score > 0:
            scored.append(_passage(text, location, score, ms, me))
    scored.sort(key=lambda p: p["score"], reverse=True)
    truncated = len(scored) > max_passages
    return {"passages": scored[:max_passages], "truncated": truncated}


def _semantic_passage(text, location, score, tokens):
    """Build a Passage; highlight query terms if present, else the first sentence.

    No per-passage embedding: passages are short and the whole-document embed
    already ranked them. Re-embedding every passage's sentences was the dominant
    latency cost, so the highlight span is found cheaply here.
    """
    _, ms, me = _score_and_mark(text, tokens)
    if ms is None:
        ms = me = 0            # semantic match without the exact term → no highlight
    sample = _sample_around(text, ms, me) if me > ms else " ".join(text.split()[:12])
    return {
        "sample": sample,
        "excerpt": text,
        "location": location,
        "score": score,
        "match_start": ms,
        "match_end": me,
    }


def _semantic_passages(units, query, embed_fn, max_passages):
    """Rank passages by cosine similarity of their embeddings to the query.

    Only the first ``_SEMANTIC_SCAN_CAP`` passages are embedded, to keep the
    single /api/embed call under its socket timeout on large documents.
    """
    if embed_fn is None:
        raise ValueError("semantic mode requires embed_fn")
    if not units:
        return {"passages": [], "truncated": False}

    scanned = units[:_SEMANTIC_SCAN_CAP]
    vecs = embed_fn([query, *(text for _, text in scanned)])
    qvec = vecs[0]

    scored = []
    for (location, text), pvec in zip(scanned, vecs[1:]):
        sim = _cosine(qvec, pvec)
        if sim >= _SEMANTIC_MIN_SIM:
            scored.append((sim, location, text))
    scored.sort(key=lambda t: t[0], reverse=True)

    tokens = _query_tokens(query)
    passages = [
        _semantic_passage(text, location, sim, tokens)
        for sim, location, text in scored[:max_passages]
    ]
    truncated = len(units) > _SEMANTIC_SCAN_CAP or len(scored) > max_passages
    return {"passages": passages, "truncated": truncated}


def locate_passages(path, query, mode, *, max_passages=200, embed_fn=None):
    """
    Locate the passages in *path* that match *query*.

    mode is "keyword" or "semantic". Semantic mode requires *embed_fn*, a
    batch embedder (list[str] -> list[vector]); the caller supplies the real
    Ollama-backed one. Returns either
    {"unsupported": True, "reason": ...} for non-prose formats, or
    {"passages": [Passage, ...], "truncated": bool}.
    """
    ext = Path(path).suffix.lstrip(".").lower()
    if ext in _NON_PROSE_EXT:
        return {"unsupported": True, "reason": f"non-prose format: .{ext}"}

    iterator = _UNIT_ITERATORS.get(ext)
    if iterator is None:
        # Formats not yet supported behave as an empty (no-passages) result.
        return {"passages": [], "truncated": False}

    units = list(iterator(path))
    if mode == "semantic":
        return _semantic_passages(units, query, embed_fn, max_passages)
    return _keyword_passages(units, query, max_passages)
