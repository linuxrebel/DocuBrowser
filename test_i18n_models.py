# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""Model + prompt resolution follows the configured language.
Run: python3 -m pytest test_i18n_models.py -v"""
import os
import tempfile
from pathlib import Path

from lang_models import resolve, config_lang


def test_en_models():
    m = resolve("en")
    assert m["embed"] == "nomic-embed-text"
    assert m["synopsis"] == "dolphin3:latest"


def test_ja_models():
    m = resolve("ja")
    assert m["embed"] == "bge-m3"
    assert "nemotron-nano-9b-v2-japanese" in m["synopsis"]



def test_en_synopsis_prompt_matches_original_byte_for_byte():
    expected = (
        "Summarize the document excerpt below in one concise paragraph. "
        "Describe only what the document actually contains — its subject matter, "
        "purpose, and key topics. Base the summary entirely on the excerpt text; "
        "do not invent content or draw on the document title alone. "
        "Do not use markdown, headings, or bullet points. Output only the "
        "paragraph itself, with no preamble.\n\n"
        "Title: My Doc\n\n"
        "Document excerpt:\nsome context"
    )
    actual = resolve("en")["synopsis_prompt"].format(title="My Doc", context="some context")
    assert actual == expected


def test_ja_synopsis_prompt_has_title_and_context_placeholders():
    prompt = resolve("ja")["synopsis_prompt"]
    rendered = prompt.format(title="T", context="C")
    assert "T" in rendered and "C" in rendered


def test_config_lang_defaults_to_en_when_no_config_file():
    with tempfile.TemporaryDirectory() as tmp:
        app_dir = Path(tmp) / "app"
        user_data = Path(tmp) / "user"
        app_dir.mkdir()
        user_data.mkdir()
        assert config_lang(app_dir=app_dir, user_data=user_data) == "en"


def test_config_lang_reads_lang_key():
    with tempfile.TemporaryDirectory() as tmp:
        app_dir = Path(tmp) / "app"
        user_data = Path(tmp) / "user"
        app_dir.mkdir()
        user_data.mkdir()
        (app_dir / "docubrowse.config").write_text("doc_dir=/x\nlang=JA\n", encoding="utf-8")
        assert config_lang(app_dir=app_dir, user_data=user_data) == "ja"


def test_config_lang_user_data_takes_precedence_over_app_dir():
    with tempfile.TemporaryDirectory() as tmp:
        app_dir = Path(tmp) / "app"
        user_data = Path(tmp) / "user"
        app_dir.mkdir()
        user_data.mkdir()
        (app_dir / "docubrowse.config").write_text("lang=ja\n", encoding="utf-8")
        (user_data / "docubrowse.config").write_text("lang=en\n", encoding="utf-8")
        assert config_lang(app_dir=app_dir, user_data=user_data) == "en"


def test_config_lang_unknown_value_falls_back_en():
    with tempfile.TemporaryDirectory() as tmp:
        app_dir = Path(tmp) / "app"
        user_data = Path(tmp) / "user"
        app_dir.mkdir()
        user_data.mkdir()
        (app_dir / "docubrowse.config").write_text("lang=xx\n", encoding="utf-8")
        assert config_lang(app_dir=app_dir, user_data=user_data) == "en"


def test_config_lang_env_override_wins(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        app_dir = Path(tmp) / "app"
        user_data = Path(tmp) / "user"
        app_dir.mkdir()
        user_data.mkdir()
        (user_data / "docubrowse.config").write_text("lang=en\n", encoding="utf-8")
        monkeypatch.setenv("DOCUBROWSE_LANG", "ja")
        assert config_lang(app_dir=app_dir, user_data=user_data) == "ja"
        monkeypatch.delenv("DOCUBROWSE_LANG", raising=False)
