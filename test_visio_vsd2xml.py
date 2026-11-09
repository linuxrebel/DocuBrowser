#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
Tests for the bounded vsd2xml run (D-17 #3): a fake vsd2xml on PATH stands in
for libvisio-tools. Run: python3 test_visio_vsd2xml.py
"""

import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest

import visio_extractor as vx

# The fake converter is an extensionless shebang script — POSIX only.
pytestmark = pytest.mark.skipif(os.name == "nt", reason="shebang fake vsd2xml")

_XML = ('<office:document xmlns:office="urn:o" xmlns:text="urn:t">'
        '<text:p>Hello diagram</text:p></office:document>')


def _with_fake_vsd2xml(body: str, fn):
    """Put an executable fake `vsd2xml` (python script) first on PATH, run fn."""
    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / "vsd2xml"
        exe.write_text(f"#!{sys.executable}\nimport sys\n{body}\n", encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
        doc = Path(tmp) / "d.vsd"
        doc.write_bytes(b"x")
        old = os.environ["PATH"]
        os.environ["PATH"] = f"{tmp}{os.pathsep}{old}"
        try:
            return fn(str(doc))
        finally:
            os.environ["PATH"] = old


def test_normal_output_parses():
    r = _with_fake_vsd2xml(f"sys.stdout.write({_XML!r})", vx._extract_vsd_legacy)
    assert not r.get("error"), r.get("error")
    assert "Hello diagram" in r["text"]


def test_oversized_output_is_capped():
    old = vx._VSD2XML_MAX_BYTES
    vx._VSD2XML_MAX_BYTES = 1024
    try:
        r = _with_fake_vsd2xml(
            "while True: sys.stdout.write('A' * 65536)", vx._extract_vsd_legacy)
    finally:
        vx._VSD2XML_MAX_BYTES = old
    assert "exceeded" in r["error"], r["error"]


def test_timeout_kills_process():
    old = vx._VSD2XML_TIMEOUT
    vx._VSD2XML_TIMEOUT = 1
    try:
        r = _with_fake_vsd2xml("import time; time.sleep(30)", vx._extract_vsd_legacy)
    finally:
        vx._VSD2XML_TIMEOUT = old
    assert "timed out" in r["error"], r["error"]


def test_nonzero_exit_reports_stderr():
    r = _with_fake_vsd2xml("sys.stderr.write('boom'); sys.exit(3)",
                           vx._extract_vsd_legacy)
    assert r["error"].startswith("vsd2xml exited 3: boom"), r["error"]


if __name__ == "__main__":
    for name, f in list(globals().items()):
        if name.startswith("test_"):
            f()
            print(f"ok  {name}")
