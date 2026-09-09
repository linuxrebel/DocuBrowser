# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""Required Ollama models follow the language. Run: python3 -m pytest test_i18n_ensure_ollama.py -v"""
from ensure_ollama import required_models


def _names(rows):
    return {r[0] for r in rows}


def test_en_required():
    assert _names(required_models("en")) == {"nomic-embed-text:latest", "dolphin3:latest"}


def test_ja_required():
    names = _names(required_models("ja"))
    assert "bge-m3:latest" in names
    assert any("nemotron-nano-9b-v2-japanese" in n for n in names)


def test_unknown_lang_falls_back_to_en():
    assert _names(required_models("xx")) == {"nomic-embed-text:latest", "dolphin3:latest"}


def test_rows_are_three_tuples_with_purpose_text():
    for row in required_models("ja"):
        assert len(row) == 3
        model, size, purpose = row
        assert isinstance(model, str) and model
        assert isinstance(purpose, str) and purpose
