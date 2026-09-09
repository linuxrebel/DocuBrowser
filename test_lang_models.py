# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""Tests for the per-language model/resolver table. Run: python3 -m pytest test_lang_models.py -v"""
from lang_models import LANG_MODELS, SUPPORTED_LANGS, resolve, lang_from_config


def test_en_and_ja_present_with_required_fields():
    for lang in ("en", "ja"):
        m = LANG_MODELS[lang]
        for key in ("embed", "synopsis", "synopsis_prompt", "tokenizer", "stopwords", "has_letter_index"):
            assert key in m, f"{lang} missing {key}"


def test_ja_stack_matches_spec():
    ja = LANG_MODELS["ja"]
    assert ja["embed"] == "bge-m3"
    assert ja["synopsis"] == "fuukeidaisuki/nvidia-nemotron-nano-9b-v2-japanese:latest"
    assert ja["tokenizer"] == "trigram"
    assert ja["has_letter_index"] is False  # CJK: hide A–Z bar


def test_en_stack_unchanged():
    en = LANG_MODELS["en"]
    assert en["embed"] == "nomic-embed-text"
    assert en["synopsis"] == "dolphin3:latest"
    assert en["tokenizer"] == "unicode61"
    assert en["has_letter_index"] is True


def test_resolve_falls_back_to_en():
    assert resolve("kling") is LANG_MODELS["en"]
    assert resolve("") is LANG_MODELS["en"]
    assert resolve("ja") is LANG_MODELS["ja"]


def test_lang_from_config():
    assert lang_from_config({}) == "en"
    assert lang_from_config({"lang": "JA"}) == "ja"
    assert lang_from_config({"lang": "xx"}) == "en"
