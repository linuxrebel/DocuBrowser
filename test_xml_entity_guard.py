#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
Tests for the XML entity-declaration guard (D-17 #1): ODF and draw.io inputs
that declare entities are refused; normal files still extract.
Run: python3 test_xml_entity_guard.py
"""

import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from odf_extractor import extract_odf, safe_fromstring
from visio_extractor import extract_visio

_BOMB = ('<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaaaaaaaa">'
         '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>')
_ODT_BODY = ('<office:document-content '
             'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
             'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
             '<office:body><office:text><text:p>{}</text:p></office:text>'
             '</office:body></office:document-content>')
_DRAWIO = ('<mxfile><diagram><mxGraphModel><root>'
           '<mxCell id="2" value="{}"/></root></mxGraphModel></diagram></mxfile>')


def _write_odt(path: Path, content_xml: str):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        zf.writestr("content.xml", content_xml)


def test_safe_fromstring_rejects_entities_any_encoding():
    for data in (_BOMB + "<d>&b;</d>",
                 (_BOMB + "<d>&b;</d>").encode("utf-8"),
                 (_BOMB.replace("1.0\"?>", "1.0\" encoding=\"utf-16\"?>")
                  + "<d>&b;</d>").encode("utf-16")):
        try:
            safe_fromstring(data)
        except ET.ParseError:
            continue
        raise AssertionError(f"entity declaration accepted: {data[:40]!r}")
    assert safe_fromstring("<d>ok &amp; fine</d>").text == "ok & fine"


def test_odt_with_entities_refused_normal_odt_extracts():
    with tempfile.TemporaryDirectory() as tmp:
        good, bad = Path(tmp) / "good.odt", Path(tmp) / "bad.odt"
        _write_odt(good, _ODT_BODY.format("Hello ODF"))
        _write_odt(bad, _BOMB.replace("<!DOCTYPE d", "<!DOCTYPE office:document-content")
                   + _ODT_BODY.format("&b;"))
        g, b = extract_odf(str(good)), extract_odf(str(bad))
    assert g["success"] and "Hello ODF" in g["text"], g
    assert not b["success"] and "entity" in b["error"], b


def test_drawio_with_entities_refused_normal_drawio_extracts():
    with tempfile.TemporaryDirectory() as tmp:
        good, bad = Path(tmp) / "good.drawio", Path(tmp) / "bad.drawio"
        good.write_text(_DRAWIO.format("Hello drawio"), encoding="utf-8")
        bad.write_text(_BOMB.replace("<!DOCTYPE d", "<!DOCTYPE mxfile")
                       + _DRAWIO.format("&b;"), encoding="utf-8")
        g, b = extract_visio(str(good)), extract_visio(str(bad))
    assert "Hello drawio" in g["text"], g
    assert b.get("error") and "entity" in b["error"], b


if __name__ == "__main__":
    for name, f in list(globals().items()):
        if name.startswith("test_"):
            f()
            print(f"ok  {name}")
