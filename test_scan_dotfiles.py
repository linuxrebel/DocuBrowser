#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
Tests for the dotfile skip in scan_docs (D-6): hidden files and the contents of
hidden directories are never indexed. Run: python3 test_scan_dotfiles.py
"""

import tempfile
from pathlib import Path

from scan_docs import _is_hidden_relpath, scan_directory
from docubrowse_db import get_db


def test_is_hidden_relpath():
    """Any dot-prefixed path component (file or dir) is hidden; root is exempt."""
    root = Path("/docs")
    assert _is_hidden_relpath(root / ".env", root)
    assert _is_hidden_relpath(root / ".git" / "config", root)          # hidden dir
    assert _is_hidden_relpath(root / "sub" / ".hidden.pdf", root)      # hidden file
    assert not _is_hidden_relpath(root / "normal.pdf", root)
    assert not _is_hidden_relpath(root / "sub" / "file.txt", root)


def test_scan_skips_dotfiles():
    """A real scan indexes visible files and skips dotfiles + hidden-dir contents."""
    with tempfile.TemporaryDirectory() as tmp:
        docs = Path(tmp) / "docs"
        docs.mkdir()
        (docs / "visible.txt").write_text("the quick brown fox", encoding="utf-8")
        (docs / ".secret.txt").write_text("api key here", encoding="utf-8")
        (docs / ".env").write_text("PASSWORD=hunter2", encoding="utf-8")
        (docs / ".git").mkdir()
        (docs / ".git" / "config").write_text("[core]\n", encoding="utf-8")

        db_path = str(Path(tmp) / "t.db")
        scan_directory(str(docs), db_path, extensions=[".txt"], workers=1)

        conn = get_db(db_path)
        names = {r[0] for r in conn.execute("SELECT name FROM documents").fetchall()}
        conn.close()

    assert "visible.txt" in names, f"visible file missing: {names}"
    assert ".secret.txt" not in names, "dotfile was indexed"
    assert ".env" not in names, ".env was indexed"
    assert "config" not in names, ".git/config was indexed"


def main():
    """Run the dotfile-skip checks."""
    test_is_hidden_relpath()
    test_scan_skips_dotfiles()
    print("PASS: dotfiles and hidden-dir contents are skipped at scan time")


if __name__ == "__main__":
    main()
