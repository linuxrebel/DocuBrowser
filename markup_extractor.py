#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
DocuBrowse markup extractor.

Handles the SGML/XML family and structured plain-text markup formats:

  XML-family (tag-strip):
    .xml   .xhtml   .sgml   .sgm
    .docbook   .dbk
    .svg
    .rss   .atom   .opml

  Plain-markup (passthrough with title heuristics):
    .rst           — reStructuredText
    .adoc  .asciidoc — AsciiDoc
    .tex           — LaTeX

The XML-family path is deliberately schema-agnostic: it decodes DOCTYPE,
comments, and CDATA sections, tries a small set of well-known title
elements (``<title>``, ``<dc:title>``, ``<author>``, ...) before stripping,
then removes all remaining tags and unescapes named entities.  The result
is plain text that keyword and semantic search can consume.

The plain-markup path just reads the file verbatim (all markup becomes
searchable text) and sniffs a title from format-specific heuristics.

Returns a dict with the same shape as pdf_extractor.extract_pdf() so
scan_docs._extract_file() can handle it uniformly.
"""

from __future__ import annotations

import html as html_mod
import re
from pathlib import Path


_TEXT_LIMIT    = 5000
_SNIPPET_LIMIT = 500
_READ_LIMIT    = 200_000    # bounded disk read (matches _extract_text_file)


# ─── shared shape ────────────────────────────────────────────────────────────

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


def _finalize(result: dict, text: str) -> dict:
    text = (text or "").strip()
    result["text"]    = text[:_TEXT_LIMIT]
    result["snippet"] = text[:_SNIPPET_LIMIT]
    result["success"] = True
    return result


def _read_bounded(file_path: str) -> str:
    """Bounded UTF-8-tolerant read; matches _extract_text_file in scan_docs."""
    with open(file_path, encoding="utf-8", errors="replace") as fh:
        return fh.read(_READ_LIMIT)


# ─── XML / SGML family ───────────────────────────────────────────────────────

# DOCTYPE / XML decl / processing instruction / comment / CDATA — order matters.
# DOCTYPE first (may contain internal subset with < >) and comments before tags
# so we don't miss balanced-tag-looking content inside a comment.
_DOCTYPE_RE   = re.compile(r"<!DOCTYPE\b[^\[>]*(?:\[[^\]]*\])?[^>]*>",
                           re.IGNORECASE | re.DOTALL)
_XML_DECL_RE  = re.compile(r"<\?xml\b[^?]*\?>",   re.IGNORECASE | re.DOTALL)
_PI_RE        = re.compile(r"<\?[^>]+?\?>",       re.DOTALL)
_COMMENT_RE   = re.compile(r"<!--.*?-->",         re.DOTALL)
_CDATA_RE     = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)
_SCRIPT_RE    = re.compile(r"<script\b[^>]*>.*?</script>",
                           re.DOTALL | re.IGNORECASE)
_STYLE_RE     = re.compile(r"<style\b[^>]*>.*?</style>",
                           re.DOTALL | re.IGNORECASE)
_TAG_RE       = re.compile(r"<[^>]+>", re.DOTALL)
_WS_RE        = re.compile(r"[ \t]*\n\s*")

# Case-insensitive title/author sniffers.  We match by local-name so DocBook's
# `<title>`, Atom's `<title>`, RSS's `<title>`, and SVG's `<title>` all hit.
_TITLE_ELEMS  = ("title", "dc:title", "h1")
_AUTHOR_ELEMS = ("author", "dc:creator", "creator", "byline")
_SUBJECT_ELEMS = ("subject", "dc:subject")


def _sniff_first_elem_text(text: str, local_names) -> str | None:
    """Return the inner text of the first <name>...</name> whose local-name
    matches (namespace-agnostic).  Returns None if not found."""
    for name in local_names:
        # Anchor to `<` then match with optional namespace prefix
        pattern = rf"<(?:\w+:)?{re.escape(name)}(?:\s[^>]*)?>(.*?)</(?:\w+:)?{re.escape(name)}\s*>"
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        inner = m.group(1)
        # Strip nested tags if any, unescape, collapse whitespace.
        inner = _TAG_RE.sub("", inner)
        inner = html_mod.unescape(inner).strip()
        inner = re.sub(r"\s+", " ", inner)
        if inner:
            return inner[:200]      # sanity cap
    return None


def _strip_markup(text: str) -> str:
    """Remove XML/SGML markup and return searchable plain text."""
    text = _DOCTYPE_RE.sub(" ", text)
    text = _XML_DECL_RE.sub(" ", text)
    text = _COMMENT_RE.sub(" ", text)
    # Preserve CDATA content; drop only the wrapper
    text = _CDATA_RE.sub(lambda m: " " + m.group(1) + " ", text)
    text = _SCRIPT_RE.sub(" ", text)
    text = _STYLE_RE.sub(" ", text)
    text = _PI_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    text = html_mod.unescape(text)
    text = _WS_RE.sub("\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _extract_xml_like(file_path: str, ext: str) -> dict:
    """Tag-strip and metadata-sniff an XML/SGML-family file."""
    result = _empty_result(ext.lstrip("."))
    try:
        raw = _read_bounded(file_path)
    except (OSError, UnicodeError) as exc:
        result["error"] = str(exc)
        return result

    # Sniff metadata BEFORE stripping — the tag structure carries the hints.
    result["title"]   = _sniff_first_elem_text(raw, _TITLE_ELEMS)
    result["author"]  = _sniff_first_elem_text(raw, _AUTHOR_ELEMS)
    result["subject"] = _sniff_first_elem_text(raw, _SUBJECT_ELEMS)

    stripped = _strip_markup(raw)

    if not result["title"]:
        # Fall back to the first non-empty line of stripped text (short-ish)
        for line in stripped.splitlines():
            candidate = line.strip()
            if 3 <= len(candidate) <= 200:
                result["title"] = candidate
                break

    return _finalize(result, stripped)


# ─── Plain-text markup (reST, AsciiDoc, LaTeX) ───────────────────────────────

# LaTeX comments — line-leading `%` (but preserve `\%`).  Title/author etc.
# use a balanced-brace helper below so nested `\emph{...}` extracts correctly.
_LATEX_COMMENT_RE = re.compile(r"(?<!\\)%.*")


def _sniff_rst_title(text: str) -> str | None:
    """reST title = line whose length ≤ its underline of === or --- or ~~~ ..."""
    lines = text.splitlines()
    for i in range(len(lines) - 1):
        line = lines[i].strip()
        under = lines[i + 1].strip()
        if not line or not under:
            continue
        # underline must be all one non-alphanumeric punctuation char,
        # length ≥ len(line)
        if len(under) >= len(line) and len(set(under)) == 1 \
                and under[0] in "=-~^*+#\"'`":
            return line[:200]
    return None


def _sniff_asciidoc_title(text: str) -> str | None:
    """AsciiDoc title = first level-0 heading `= Title`.

    Real files often open with a `//` comment block or a `:doctype:` /
    `:author:` attribute block before the title, so those lines are
    skipped rather than treated as end-of-preamble.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Skip comments and attribute-entry preamble
        if stripped.startswith("//") or stripped.startswith(":"):
            continue
        if stripped.startswith("= ") and len(stripped) > 2:
            return stripped[2:].strip()[:200]
        # First real content line and it isn't a title — give up
        return None
    return None


def _extract_braced(text: str, start: int) -> str | None:
    """From ``text[start] == '{'``, return the substring inside the balanced
    braces (respecting `\\{` and `\\}` escapes).  Returns None on unbalance."""
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            i += 2      # skip escaped character
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
        i += 1
    return None


def _sniff_latex_braced_macro(text: str, macro: str) -> str | None:
    """Find ``\\macro[opt]{arg}`` (opt optional) and return the balanced arg."""
    # macro name followed by optional whitespace and optional [opt]
    pattern = rf"\\{re.escape(macro)}\s*(?:\[[^\]]*\])?\s*\{{"
    m = re.search(pattern, text)
    if not m:
        return None
    body = _extract_braced(text, m.end() - 1)
    if body is None:
        return None
    return body.strip()[:200] or None


def _sniff_latex_meta(text: str):
    """Return (title, author) hints from LaTeX macros.

    Uses balanced-brace extraction so ``\\title{The \\emph{Real} Thing}``
    and ``\\author{Ada Lovelace\\thanks{née Byron}}`` extract fully.
    """
    title = (_sniff_latex_braced_macro(text, "title")
             or _sniff_latex_braced_macro(text, "chapter")
             or _sniff_latex_braced_macro(text, "section"))
    author = _sniff_latex_braced_macro(text, "author")
    return title, author


def _extract_plain_markup(file_path: str, ext: str) -> dict:
    """Passthrough-index a reST / AsciiDoc / LaTeX source file with a title sniff."""
    result = _empty_result(ext.lstrip("."))
    try:
        raw = _read_bounded(file_path)
    except (OSError, UnicodeError) as exc:
        result["error"] = str(exc)
        return result

    ext_lower = ext.lower()

    if ext_lower == ".rst":
        result["title"] = _sniff_rst_title(raw)
        body = raw
    elif ext_lower in (".adoc", ".asciidoc"):
        result["title"] = _sniff_asciidoc_title(raw)
        body = raw
    elif ext_lower in (".tex", ".latex"):
        t, a = _sniff_latex_meta(raw)
        result["title"]  = t
        result["author"] = a
        # Strip LaTeX line comments so search hits real content
        body = _LATEX_COMMENT_RE.sub("", raw)
    else:
        body = raw

    return _finalize(result, body)


# ─── Public dispatcher ───────────────────────────────────────────────────────

_XML_FAMILY_EXTENSIONS = frozenset({
    ".xml", ".xhtml", ".sgml", ".sgm",
    ".docbook", ".dbk",
    ".svg", ".vdx",
    ".rss", ".atom", ".opml",
})

_PLAIN_MARKUP_EXTENSIONS = frozenset({
    ".rst",
    ".adoc", ".asciidoc",
    ".tex", ".latex",
})


def extract_markup(file_path: str) -> dict:
    """Dispatch by extension to the right markup extractor.

    Returns:
        dict with keys: success, title, author, subject, description,
                        text (up to 5000 chars), snippet (up to 500 chars),
                        doc_type, error
    """
    ext = Path(file_path).suffix.lower()
    if ext in _XML_FAMILY_EXTENSIONS:
        return _extract_xml_like(file_path, ext)
    if ext in _PLAIN_MARKUP_EXTENSIONS:
        return _extract_plain_markup(file_path, ext)

    result = _empty_result("markup")
    result["error"] = f"unsupported markup extension: {ext!r}"
    return result
