# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""JP FTS uses unicode61 + app-side CJK bigram segmentation (not FTS5 trigram).
Run: python3 -m pytest test_fts_tokenizer.py -v"""
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


def test_ja_uses_unicode61():
    """Task 11 replaced FTS5 trigram with unicode61 + app-side CJK bigram
    segmentation (see cjk.py); ja must no longer request trigram."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "ja.db")
        conn = sqlite3.connect(db_path)
        init_db(conn, lang="ja")
        sql = _fts_sql(conn)
        conn.close()
        assert "unicode61" in sql
        assert "trigram" not in sql


def test_default_lang_is_en_unchanged():
    """Calling init_db(conn) with no lang arg must behave exactly as before (English)."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "default.db")
        conn = sqlite3.connect(db_path)
        init_db(conn)
        sql = _fts_sql(conn)
        conn.close()
        assert "trigram" not in sql


def test_get_db_passes_lang_through_on_first_init():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "getdb_ja.db")
        conn = get_db(db_path, lang="ja")
        sql = _fts_sql(conn)
        conn.close()
        assert "unicode61" in sql
        assert "trigram" not in sql


def test_get_db_default_lang_still_works():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "getdb_default.db")
        conn = get_db(db_path)
        sql = _fts_sql(conn)
        conn.close()
        assert "trigram" not in sql


def test_get_db_resolves_lang_from_config_when_not_passed(monkeypatch):
    """Integration guard: a lang=ja install must get the ja-configured
    tokenizer (unicode61, per Task 11's bigram-segmentation switch) through
    get_db() WITHOUT any caller passing lang. Reproduces the wiring gap
    where all 25 get_db() call sites used the default and JP keyword search
    silently fell back to the wrong tokenizer."""
    import docubrowse_db
    monkeypatch.setenv("DOCUBROWSE_LANG", "ja")  # config_lang() honors this
    docubrowse_db._default_lang = None           # clear the per-process cache
    try:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "config_ja.db")
            conn = get_db(db_path)               # NOTE: no lang argument
            sql = _fts_sql(conn)
            conn.close()
            docubrowse_db._initialized_paths.discard(db_path)
        assert "unicode61" in sql
        assert "trigram" not in sql
    finally:
        docubrowse_db._default_lang = None
