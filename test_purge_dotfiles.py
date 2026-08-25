#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""Tests for purge_dotfiles: roots-aware flagging + real DB deletion."""

import tempfile
from pathlib import Path

from purge_dotfiles import is_dotfile, _safe_resolve
from docubrowse_db import get_db, delete_documents


def test_is_dotfile_roots_aware():
    """Hidden files/dir-contents flagged; dot-directory root is exempt."""
    roots = [Path("/docs")]
    assert is_dotfile("/docs/.env", roots)
    assert is_dotfile("/docs/.git/config", roots)          # hidden dir content
    assert not is_dotfile("/docs/visible.txt", roots)
    assert not is_dotfile("/docs/sub/file.md", roots)

    # A deliberately-scanned dot-directory root is exempt for its own files.
    droot = [Path("/home/u/.config")]
    assert not is_dotfile("/home/u/.config/settings.txt", droot)
    assert is_dotfile("/home/u/.config/.hidden", droot)     # still hidden below it

    # Path under no configured root → any-dot-component fallback.
    assert is_dotfile("/elsewhere/.secret", roots)
    assert not is_dotfile("/elsewhere/plain.txt", roots)


def test_purge_deletes_only_dotfiles():
    """A real DB keeps visible docs and removes dotfiles + hidden-dir contents."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "docs"
        (root / "sub").mkdir(parents=True)
        (root / ".git").mkdir()
        db = str(Path(tmp) / "t.db")
        conn = get_db(db)
        docs = {
            "visible.txt": root / "visible.txt",
            "note.md": root / "sub" / "note.md",
            ".env": root / ".env",
            "config": root / ".git" / "config",   # hidden dir content
        }
        for name, p in docs.items():
            conn.execute("INSERT INTO documents (name, path) VALUES (?, ?)",
                         (name, str(p)))
        conn.commit()

        roots = [_safe_resolve(root)]
        rows = conn.execute("SELECT id, path FROM documents").fetchall()
        hits = [(r[0], r[1]) for r in rows if is_dotfile(r[1], roots)]
        flagged = {Path(p).name for _, p in hits}
        assert ".env" in flagged and "config" in flagged, flagged
        assert "visible.txt" not in flagged and "note.md" not in flagged, flagged

        delete_documents(conn, [i for i, _ in hits])
        remaining = {r[0] for r in conn.execute("SELECT name FROM documents").fetchall()}
        conn.close()

    assert remaining == {"visible.txt", "note.md"}, remaining


def main():
    """Run the purge-dotfiles checks."""
    test_is_dotfile_roots_aware()
    test_purge_deletes_only_dotfiles()
    print("PASS: purge_dotfiles flags dotfiles roots-aware and deletes only those")


if __name__ == "__main__":
    main()
