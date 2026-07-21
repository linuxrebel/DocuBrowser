#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
DocuBrowse Visio and diagram extractor.

Handles:
  .vsdx / .vsdm       — Modern Visio (OOXML zip + XML)   [stdlib]
  .vsd  / .vss / .vst — Legacy Visio (binary CDF)        [vsd2xml external]
  .drawio / .dio      — draw.io / diagrams.net XML       [stdlib]

Returns a dict with the same shape as pdf_extractor.extract_pdf() so
scan_docs._extract_file() can handle it uniformly.

Legacy .vsd/.vss/.vst requires ``vsd2xml`` from the libvisio-tools package
(``sudo dnf install libvisio-tools`` / ``sudo apt install libvisio-tools``).
Files that need the converter but can't find it are indexed metadata-only
(filename as title, empty body) and appended to ``visio_legacy_missing.txt``
next to the database so an operator can install libvisio-tools and rescan.
"""

import base64
import gzip
import html as html_mod
import re
import shutil
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
import zipfile
from pathlib import Path


_TEXT_LIMIT    = 5000
_SNIPPET_LIMIT = 500

# Modern Visio (OOXML) namespaces
_VSDX_NS = {
    "v":  "http://schemas.microsoft.com/office/visio/2012/main",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
}

# Missing-converter list, mirrors ocr_list_pdfs.txt.  Populated by the
# scanner when legacy Visio is found but vsd2xml is absent.
LEGACY_MISSING_FILENAME = "visio_legacy_missing.txt"


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _iter_text(elem):
    """Recursively yield every text node under *elem* (like odf_extractor)."""
    if elem.text:
        yield elem.text
    for child in elem:
        yield from _iter_text(child)
        if child.tail:
            yield child.tail


def _elem_text(elem):
    """Return the concatenated text of *elem* and all descendants, stripped."""
    return "".join(_iter_text(elem)).strip()


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


def _finalize(result: dict, parts: list) -> dict:
    """Trim body text to the standard limits and mark success."""
    full = "\n".join(p for p in parts if p)
    result["text"]    = full[:_TEXT_LIMIT]
    result["snippet"] = full[:_SNIPPET_LIMIT]
    result["success"] = True
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Modern Visio (.vsdx / .vsdm)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_vsdx_core_props(zf: zipfile.ZipFile, result: dict) -> None:
    """Read docProps/core.xml — same dc:* fields the docx path uses."""
    try:
        with zf.open("docProps/core.xml") as f:
            tree = ET.parse(f)
    except (KeyError, ET.ParseError):
        return

    root = tree.getroot()

    def _find_text(qname: str):
        node = root.find(qname, _VSDX_NS)
        if node is None or not node.text:
            return None
        val = node.text.strip()
        return val or None

    result["title"]   = _find_text("dc:title")
    result["author"]  = _find_text("dc:creator")
    result["subject"] = _find_text("dc:subject")
    desc = _find_text("dc:description")
    keywords = _find_text("cp:keywords")
    result["description"] = desc or keywords or ""


def _parse_vsdx_page_names(zf: zipfile.ZipFile) -> dict:
    """Return {page_href: page_display_name} from visio/pages/pages.xml."""
    names: dict = {}
    try:
        with zf.open("visio/pages/pages.xml") as f:
            tree = ET.parse(f)
    except (KeyError, ET.ParseError):
        return names

    # Also read the rels to map r:id → target filename.
    rels: dict = {}
    try:
        with zf.open("visio/pages/_rels/pages.xml.rels") as f:
            rels_tree = ET.parse(f)
        for rel in rels_tree.getroot():
            rid    = rel.attrib.get("Id")
            target = rel.attrib.get("Target")
            if rid and target:
                rels[rid] = target
    except (KeyError, ET.ParseError):
        pass

    r_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    for page in tree.getroot().findall("v:Page", _VSDX_NS):
        name = page.attrib.get("Name") or page.attrib.get("NameU")
        rel_node = page.find("v:Rel", _VSDX_NS)
        rid = rel_node.attrib.get(f"{r_ns}id") if rel_node is not None else None
        if rid and rid in rels and name:
            names[rels[rid]] = name
    return names


def _extract_vsdx_page(zf: zipfile.ZipFile, member: str) -> list:
    """Return the list of Shape.Text strings on one page."""
    parts: list = []
    try:
        with zf.open(member) as f:
            tree = ET.parse(f)
    except (KeyError, ET.ParseError):
        return parts

    # Every <Text> under any <Shape>.  iter() walks the whole subtree so we
    # pick up grouped shapes without extra logic.
    root = tree.getroot()
    for text_node in root.iter(f"{{{_VSDX_NS['v']}}}Text"):
        t = _elem_text(text_node)
        if t:
            parts.append(t)
    return parts


def _extract_vsdx(file_path: str) -> dict:
    """Extract text + metadata from a modern Visio (.vsdx / .vsdm) file."""
    ext = Path(file_path).suffix.lower().lstrip(".")
    result = _empty_result(ext if ext in ("vsdx", "vsdm") else "vsdx")

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            _parse_vsdx_core_props(zf, result)

            page_names = _parse_vsdx_page_names(zf)

            # Enumerate every visio/pages/page*.xml in a stable order.
            page_members = sorted(
                m for m in zf.namelist()
                if m.startswith("visio/pages/page")
                and m.endswith(".xml")
                and not m.endswith("pages.xml")
            )

            parts: list = []
            for member in page_members:
                # pages.xml.rels stores the target as "page1.xml" (relative)
                short = member.split("/")[-1]
                display = page_names.get(short) or page_names.get(member)
                if display:
                    parts.append(f"[{display}]")
                parts.extend(_extract_vsdx_page(zf, member))

            return _finalize(result, parts)

    except zipfile.BadZipFile:
        result["error"] = "not a valid ZIP/VSDX file"
        return result
    except (OSError, ValueError, KeyError, ET.ParseError) as exc:
        result["error"] = str(exc)
        return result


# ─────────────────────────────────────────────────────────────────────────────
# Legacy Visio (.vsd / .vss / .vst) via libvisio-tools' vsd2xml
# ─────────────────────────────────────────────────────────────────────────────

def _have_vsd2xml() -> bool:
    return shutil.which("vsd2xml") is not None


def _extract_vsd_legacy(file_path: str) -> dict:
    """Extract text from a legacy binary Visio file using vsd2xml.

    vsd2xml prints ODG-flavoured XML to stdout.  We reuse odf_extractor's
    text-walking approach: pull every text node under the drawing:page tree.
    """
    result = _empty_result("visio_legacy")

    if not _have_vsd2xml():
        # Signal the missing converter cleanly.  scan_docs decides whether
        # to index metadata-only or blacklist.
        result["error"] = "vsd2xml not found (install libvisio-tools)"
        result["title"] = Path(file_path).stem
        return result

    try:
        proc = subprocess.run(
            ["vsd2xml", file_path],
            capture_output=True,
            timeout=90,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout:
            err = (proc.stderr or b"").decode("utf-8", "replace").strip()
            result["error"] = f"vsd2xml exited {proc.returncode}: {err[:200]}"
            return result

        try:
            root = ET.fromstring(proc.stdout)
        except ET.ParseError as exc:
            result["error"] = f"vsd2xml output not valid XML: {exc}"
            return result

        # Walk every text-bearing element regardless of namespace — the ODG
        # output from vsd2xml uses the ODF text namespace for paragraphs.
        parts: list = []
        for elem in root.iter():
            local = elem.tag.rsplit("}", 1)[-1]
            if local in ("p", "h", "text-box", "span"):
                t = _elem_text(elem)
                if t and (not parts or parts[-1] != t):
                    parts.append(t)

        result["title"] = Path(file_path).stem
        return _finalize(result, parts)

    except subprocess.TimeoutExpired:
        result["error"] = "vsd2xml timed out after 90s"
        return result
    except (OSError, ValueError, KeyError, ET.ParseError) as exc:
        result["error"] = str(exc)
        return result


# ─────────────────────────────────────────────────────────────────────────────
# draw.io / diagrams.net (.drawio, .dio)
# ─────────────────────────────────────────────────────────────────────────────

# pylint: disable-next=too-many-return-statements
def _decompress_drawio_body(body: str) -> str:
    """Decompress a compressed <diagram> payload.

    draw.io stores compressed diagrams as:
        raw-DEFLATE → base64 → URL-encode.
    Some exports skip URL encoding; some skip compression entirely.
    Try to decode in that order and return the raw XML string.  If nothing
    works, return the original body unchanged.
    """
    body = (body or "").strip()
    if not body:
        return ""

    # Fast path: already looks like XML
    if body.lstrip().startswith("<"):
        return body

    try:
        step1 = urllib.parse.unquote(body)
    except (ValueError, UnicodeError):
        step1 = body

    try:
        raw = base64.b64decode(step1, validate=False)
    except (ValueError, TypeError):
        return body

    try:
        # Raw DEFLATE, no zlib header
        xml_bytes = zlib.decompress(raw, -zlib.MAX_WBITS)
    except zlib.error:
        try:
            xml_bytes = zlib.decompress(raw)
        except zlib.error:
            # Might be plain-base64 XML (some older exports)
            try:
                return raw.decode("utf-8", "replace")
            except (ValueError, KeyError, zlib.error, UnicodeError):
                return body

    try:
        decoded = xml_bytes.decode("utf-8", "replace")
    except (UnicodeError, LookupError):
        return body

    # draw.io wraps the inner XML in a URL-encoded string when compressed
    try:
        return urllib.parse.unquote(decoded)
    except (ValueError, UnicodeError):
        return decoded


def _extract_drawio_cells(inner_xml: str) -> list:
    """Return every mxCell value + object label from an unwrapped diagram."""
    parts: list = []
    if not inner_xml:
        return parts
    try:
        root = ET.fromstring(inner_xml)
    except ET.ParseError:
        return parts

    # mxCell value=... and object label=... hold user-visible text.
    # Values may contain HTML markup — strip tags cheaply.

    def _clean(raw: str) -> str:
        if not raw:
            return ""
        # Break <br/> into newlines so multi-line labels stay readable
        s = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
        s = re.sub(r"<[^>]+>", "", s)
        return html_mod.unescape(s).strip()

    for cell in root.iter():
        local = cell.tag.rsplit("}", 1)[-1]
        if local == "mxCell":
            val = _clean(cell.attrib.get("value", ""))
            if val:
                parts.append(val)
        elif local == "object":
            val = _clean(cell.attrib.get("label", ""))
            if val:
                parts.append(val)
    return parts


def _extract_drawio(file_path: str) -> dict:
    """Extract diagram labels + page names from a .drawio / .dio file."""
    result = _empty_result("drawio")

    try:
        with open(file_path, "rb") as fh:
            head = fh.read(4)
            fh.seek(0)
            raw = fh.read()

        # draw.io sometimes writes gzipped files (rare, but legal)
        if head[:2] == b"\x1f\x8b":
            try:
                raw = gzip.decompress(raw)
            except (ValueError, KeyError, zlib.error, UnicodeError, ET.ParseError):
                pass

        try:
            text = raw.decode("utf-8", "replace")
        except (UnicodeError, LookupError):
            text = ""

        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            result["error"] = f"invalid draw.io XML: {exc}"
            return result

        # Metadata: draw.io files don't have real dc:* fields.  Best we can
        # do is use the file's stem as the title so keyword search still works.
        result["title"] = Path(file_path).stem

        parts: list = []
        diagrams = root.findall(".//diagram")
        if not diagrams:
            # Root itself might be <mxGraphModel> (mxfile-less export)
            parts.extend(_extract_drawio_cells(text))
        else:
            for diag in diagrams:
                name = diag.attrib.get("name")
                if name:
                    parts.append(f"[{name}]")
                # Either the body is inline XML (children) or the .text is
                # a compressed payload.
                child_xml = ""
                if len(diag) > 0:
                    child_xml = ET.tostring(diag[0], encoding="unicode")
                else:
                    child_xml = _decompress_drawio_body(diag.text or "")
                parts.extend(_extract_drawio_cells(child_xml))

        return _finalize(result, parts)

    except (OSError, ValueError, KeyError, ET.ParseError) as exc:
        result["error"] = str(exc)
        return result


# ─────────────────────────────────────────────────────────────────────────────
# Public dispatcher
# ─────────────────────────────────────────────────────────────────────────────

_MODERN_VSDX = frozenset({".vsdx", ".vsdm"})
_LEGACY_VSD  = frozenset({".vsd", ".vss", ".vst"})
_DRAWIO      = frozenset({".drawio", ".dio"})


def extract_visio(file_path: str) -> dict:
    """Dispatch by extension to the right extractor.

    Returns:
        dict with keys: success, title, author, subject, description,
                        text (up to 5000 chars), snippet (up to 500 chars),
                        doc_type, error
    """
    ext = Path(file_path).suffix.lower()
    if ext in _MODERN_VSDX:
        return _extract_vsdx(file_path)
    if ext in _LEGACY_VSD:
        return _extract_vsd_legacy(file_path)
    if ext in _DRAWIO:
        return _extract_drawio(file_path)

    result = _empty_result("visio")
    result["error"] = f"unsupported visio extension: {ext!r}"
    return result
