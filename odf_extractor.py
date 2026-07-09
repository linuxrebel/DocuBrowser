#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
DocuBrowse ODF extractor.

Extracts text and metadata from OpenDocument Format files:
  .odt  — text documents   (like .docx)
  .ods  — spreadsheets     (like .xlsx)
  .odp  — presentations    (like .pptx)

ODF files are ZIP archives containing XML.  This extractor reads content.xml
and meta.xml directly with the stdlib — no third-party dependency required.

Returns a dict with the same shape as pdf_extractor.extract_pdf() so
scan_docs._extract_file() can handle it uniformly.
"""

import xml.etree.ElementTree as ET
import zipfile

_TEXT_LIMIT = 5000

# ODF namespaces we care about
_NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text":   "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table":  "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "dc":     "http://purl.org/dc/elements/1.1/",
    "meta":   "urn:oasis:names:tc:opendocument:xmlns:meta:1.0",
    "draw":   "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "pres":   "urn:oasis:names:tc:opendocument:xmlns:presentation:1.0",
}


def _iter_text(elem):
    """Recursively yield all text content under *elem*."""
    if elem.text:
        yield elem.text
    for child in elem:
        yield from _iter_text(child)
        if child.tail:
            yield child.tail


def _elem_text(elem):
    """Return concatenated text of *elem* and all descendants."""
    return "".join(_iter_text(elem)).strip()


def _parse_meta(zf):
    """Extract title, author (creator), subject, description from meta.xml."""
    meta = {"title": None, "author": None, "subject": None, "description": ""}
    try:
        with zf.open("meta.xml") as f:
            tree = ET.parse(f)
    except (KeyError, ET.ParseError):
        return meta

    root = tree.getroot()

    # All metadata lives under <office:meta>
    office_meta = root.find("office:meta", _NS)
    if office_meta is None:
        return meta

    tag_map = {
        f"{{{_NS['dc']}}}title":       "title",
        f"{{{_NS['dc']}}}creator":     "author",
        f"{{{_NS['dc']}}}subject":     "subject",
        f"{{{_NS['dc']}}}description": "description",
        f"{{{_NS['meta']}}}keyword":   "_keyword",
    }

    keywords = []
    for child in office_meta:
        key = tag_map.get(child.tag)
        if key is None:
            continue
        val = (child.text or "").strip()
        if not val:
            continue
        if key == "_keyword":
            keywords.append(val)
        else:
            meta[key] = val

    # Use keywords as description fallback
    if not meta["description"] and keywords:
        meta["description"] = ", ".join(keywords)

    # Normalise empty strings → None for title/author/subject
    for k in ("title", "author", "subject"):
        if not meta[k]:
            meta[k] = None

    return meta


def _extract_odt(zf):
    """Extract body text from an ODT (text document)."""
    with zf.open("content.xml") as f:
        tree = ET.parse(f)
    root = tree.getroot()

    body = root.find("office:body", _NS)
    if body is None:
        return ""
    text_node = body.find("office:text", _NS)
    if text_node is None:
        return ""

    parts = []
    for elem in text_node:
        tag = elem.tag

        # Paragraphs and headings
        if tag in (f"{{{_NS['text']}}}p", f"{{{_NS['text']}}}h"):
            t = _elem_text(elem)
            if t:
                parts.append(t)

        # Lists — extract every list-item paragraph
        elif tag == f"{{{_NS['text']}}}list":
            for item in elem.iter(f"{{{_NS['text']}}}p"):
                t = _elem_text(item)
                if t:
                    parts.append(t)

        # Tables
        elif tag == f"{{{_NS['table']}}}table":
            for row in elem.iter(f"{{{_NS['table']}}}table-row"):
                cells = []
                for cell in row.iter(f"{{{_NS['table']}}}table-cell"):
                    ct = _elem_text(cell)
                    if ct:
                        cells.append(ct)
                if cells:
                    parts.append(" | ".join(cells))

        if len("\n".join(parts)) >= _TEXT_LIMIT:
            break

    return "\n".join(parts)


def _extract_ods(zf):
    """Extract cell text from an ODS (spreadsheet)."""
    with zf.open("content.xml") as f:
        tree = ET.parse(f)
    root = tree.getroot()

    body = root.find("office:body", _NS)
    if body is None:
        return ""
    spreadsheet = body.find("office:spreadsheet", _NS)
    if spreadsheet is None:
        return ""

    parts = []
    total = 0
    for table in spreadsheet.findall(f"{{{_NS['table']}}}table", _NS):
        if total >= _TEXT_LIMIT:
            break
        for row in table.findall(f"{{{_NS['table']}}}table-row", _NS):
            if total >= _TEXT_LIMIT:
                break
            cells = []
            for cell in row.findall(f"{{{_NS['table']}}}table-cell", _NS):
                ct = _elem_text(cell)
                if ct:
                    cells.append(ct)
            if cells:
                line = " | ".join(cells)
                parts.append(line)
                total += len(line)

    return "\n".join(parts)


def _extract_odp(zf):
    """Extract slide text from an ODP (presentation)."""
    with zf.open("content.xml") as f:
        tree = ET.parse(f)
    root = tree.getroot()

    body = root.find("office:body", _NS)
    if body is None:
        return ""
    presentation = body.find("office:presentation", _NS)
    if presentation is None:
        return ""

    parts = []
    for page in presentation.findall(f"{{{_NS['draw']}}}page", _NS):
        for frame in page.iter(f"{{{_NS['draw']}}}frame"):
            text_box = frame.find(f"{{{_NS['draw']}}}text-box")
            if text_box is None:
                continue
            for para in text_box.iter(f"{{{_NS['text']}}}p"):
                t = _elem_text(para)
                if t:
                    parts.append(t)
        # Tables inside slides
        for table in page.iter(f"{{{_NS['table']}}}table"):
            for row in table.iter(f"{{{_NS['table']}}}table-row"):
                cells = []
                for cell in row.iter(f"{{{_NS['table']}}}table-cell"):
                    ct = _elem_text(cell)
                    if ct:
                        cells.append(ct)
                if cells:
                    parts.append(" | ".join(cells))

        if len("\n".join(parts)) >= _TEXT_LIMIT:
            break

    return "\n".join(parts)


# Map mimetype prefix → (extractor function, doc_type label)
_EXTRACTORS = {
    "application/vnd.oasis.opendocument.text":         (_extract_odt, "odt"),
    "application/vnd.oasis.opendocument.spreadsheet":  (_extract_ods, "ods"),
    "application/vnd.oasis.opendocument.presentation": (_extract_odp, "odp"),
}


def extract_odf(file_path: str) -> dict:
    """
    Extract text and metadata from an ODF file (.odt, .ods, .odp).

    Returns:
        dict with keys: success, title, author, subject, description,
                        text (up to 5000 chars), snippet (up to 500 chars),
                        doc_type, error
    """
    # Determine doc_type from extension for the default
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    default_doc_type = ext if ext in ("odt", "ods", "odp") else "odf"

    result = {
        "title":       None,
        "author":      None,
        "subject":     None,
        "description": "",
        "text":        "",
        "snippet":     "",
        "doc_type":    default_doc_type,
        "success":     False,
        "error":       None,
    }

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            # Read mimetype to pick the right extractor
            try:
                mimetype = zf.read("mimetype").decode("utf-8").strip()
            except KeyError:
                mimetype = ""

            # Metadata
            meta = _parse_meta(zf)
            result["title"]       = meta["title"]
            result["author"]      = meta["author"]
            result["subject"]     = meta["subject"]
            result["description"] = meta["description"]

            # Pick extractor; fall back based on file extension
            extractor_fn = None
            doc_type = default_doc_type

            for mime_prefix, (fn, dt) in _EXTRACTORS.items():
                if mimetype.startswith(mime_prefix):
                    extractor_fn = fn
                    doc_type = dt
                    break

            if extractor_fn is None:
                # Fall back by extension
                ext_map = {"odt": _extract_odt, "ods": _extract_ods, "odp": _extract_odp}
                extractor_fn = ext_map.get(ext)

            if extractor_fn is None:
                result["error"] = f"unsupported ODF mimetype: {mimetype!r}"
                return result

            result["doc_type"] = doc_type
            full_text = extractor_fn(zf)

        result["text"]    = full_text[:_TEXT_LIMIT]
        result["snippet"] = full_text[:500]
        result["success"] = True
        return result

    except zipfile.BadZipFile:
        result["error"] = "not a valid ZIP/ODF file"
        return result
    except Exception as exc:
        result["error"] = str(exc)
        return result
