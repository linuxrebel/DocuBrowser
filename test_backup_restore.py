#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
Test the path-traversal guard used by the restore fallback on Python < 3.12.

_reject_unsafe_members() backports tarfile's filter='data' safety: it must
reject members that escape the destination (absolute paths, ../ traversal) and
link members, while letting ordinary files through. Run: python3 test_backup_restore.py
"""

import io
import tarfile
import tempfile
from pathlib import Path

from backup_restore import _reject_unsafe_members


def _tar_with(members):
    """Build an in-memory tar; *members* is a list of (name, is_link)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, is_link in members:
            info = tarfile.TarInfo(name)
            if is_link:
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
            else:
                info.size = 3
            tar.addfile(info, io.BytesIO(b"abc") if not is_link else None)
    buf.seek(0)
    return tarfile.open(fileobj=buf, mode="r:gz")


def _rejects(members):
    with tempfile.TemporaryDirectory() as tmp:
        try:
            _reject_unsafe_members(_tar_with(members), Path(tmp))
            return False
        except ValueError:
            return True


def main():
    """Assert the guard allows safe files and rejects every escape vector."""
    # Safe: ordinary files with simple names must pass.
    assert not _rejects([("du-docs.db", False), ("scan_dirs.txt", False)]), \
        "ordinary files should be allowed"
    # Traversal via ../
    assert _rejects([("../evil", False)]), "../ traversal not rejected"
    assert _rejects([("../../etc/cron.d/x", False)]), "deep ../ not rejected"
    # Absolute path
    assert _rejects([("/etc/passwd", False)]), "absolute path not rejected"
    # Symlink member
    assert _rejects([("link", True)]), "symlink member not rejected"
    print("PASS: safe files allowed; traversal, absolute paths, and links rejected")


if __name__ == "__main__":
    main()
