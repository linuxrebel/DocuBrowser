# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""JP keyword search needs the trigram tokenizer. Run: python3 -m pytest test_fts_tokenizer.py -v"""
import sqlite3
import tempfile
from pathlib import Path

from docubrowse_db import init_db, get_db


def _fts_sql(conn):
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='doc_fts'").fetchone()
    return row[0] if row else ""


def test_en_uses_default_tokenizer():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "en.db")
        conn = sqlite3.connect(db_path)
        init_db(conn, lang="en")
        sql = _fts_sql(conn)
        conn.close()
        assert "trigram" not in sql


def test_ja_uses_trigram():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "ja.db")
        conn = sqlite3.connect(db_path)
        init_db(conn, lang="ja")
        sql = _fts_sql(conn)
        conn.close()
        assert "trigram" in sql


def test_default_lang_is_en_unchanged():
    """Calling init_db(conn) with no lang arg must behave exactly as before (English)."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "default.db")
        conn = sqlite3.connect(db_path)
        init_db(conn)
        sql = _fts_sql(conn)
        conn.close()
        assert "trigram" not in sql


def test_ja_substring_match_on_cjk():
    """A Japanese term embedded in a longer run matches under trigram."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "ja2.db")
        conn = sqlite3.connect(db_path)
        init_db(conn, lang="ja")
        conn.execute(
            "INSERT INTO doc_fts(rowid, name, title, author, subject, description, content_snippet, tags) "
            "VALUES (1, '', '機械学習の入門書です', '', '', '', '', '')"
        )
        hits = conn.execute(
            "SELECT rowid FROM doc_fts WHERE doc_fts MATCH ?", ('"機械学習"',)
        ).fetchall()
        conn.close()
        assert hits == [(1,)]


def test_get_db_passes_lang_through_on_first_init():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "getdb_ja.db")
        conn = get_db(db_path, lang="ja")
        sql = _fts_sql(conn)
        conn.close()
        assert "trigram" in sql


def test_get_db_default_lang_still_works():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "getdb_default.db")
        conn = get_db(db_path)
        sql = _fts_sql(conn)
        conn.close()
        assert "trigram" not in sql
