#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
Tests for check_missing_path: a deleted file vs an unmounted drive/share.
"missing" (safe to drop the index row) only when the file's own folder is
reachable and still has other entries; everything else is "unmounted".
Run: python3 test_missing_path.py
"""

import tempfile
from pathlib import Path

from docubrowse_db import check_missing_path


def test_classification():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "present.pdf").write_bytes(b"x")
        (t / "full").mkdir()
        (t / "full" / "other.txt").write_text("x")
        (t / "emptymount").mkdir()
        (t / "media").mkdir()            # e.g. /run/media/user, drive dir removed
        cases = {
            t / "present.pdf": "present",
            t / "full" / "deleted.pdf": "missing",            # deleted file
            t / "emptymount" / "doc.pdf": "unmounted",        # unmounted share
            t / "media" / "MYUSB" / "doc.pdf": "unmounted",   # unplugged USB
            t / "gvfs" / "smb-share:s=nas" / "d.pdf": "unmounted",
        }
        for path, want in cases.items():
            got = check_missing_path(str(path))
            assert got == want, f"{path}: got {got}, want {want}"


def test_unreadable_folder_is_unmounted():
    """An I/O error (e.g. stale network handle) must never read as deleted."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "afile"
        f.write_text("x")
        # a "folder" that is really a file: listing it raises OSError
        assert check_missing_path(str(f / "doc.pdf")) == "unmounted"


if __name__ == "__main__":
    test_classification()
    test_unreadable_folder_is_unmounted()
    print("ok")
