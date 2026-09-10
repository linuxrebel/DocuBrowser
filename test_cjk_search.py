# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""2-char CJK keyword queries match end-to-end. Run: python3 -m pytest test_cjk_search.py -v"""
import tempfile
from pathlib import Path
import docubrowse_db
from cjk import cjk_segment


def test_two_char_cjk_query_matches(monkeypatch):
    monkeypatch.setenv("DOCUBROWSE_LANG", "ja")
    docubrowse_db._default_lang = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "cjk.db")
            conn = docubrowse_db.get_db(db)          # unicode61 for ja now
            snippet = cjk_segment("リンゴの栽培と品種について")
            conn.execute(
                "INSERT INTO doc_fts(rowid, name, title, author, subject, description, content_snippet, tags) "
                "VALUES (1,'','', '', '', '', ?, '')", (snippet,))
            q = cjk_segment("栽培")
            n = conn.execute(
                "SELECT count(*) FROM doc_fts WHERE doc_fts MATCH ?", (f'"{q}"',)).fetchone()[0]
            conn.close()
            docubrowse_db._initialized_paths.discard(db)
        assert n == 1
    finally:
        docubrowse_db._default_lang = None
