# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""Tests for the per-language model/resolver table. Run: python3 -m pytest test_lang_models.py -v"""
from lang_models import LANG_MODELS, SUPPORTED_LANGS, resolve, lang_from_config
from cjk import ko_letter_of, ko_letter_range, KO_INDEX_LETTERS


def test_ko_choseong_index():
    # First-syllable → leading consonant (tense folds into base).
    assert ko_letter_of("한국") == "ㅎ"
    assert ko_letter_of("국가") == "ㄱ"
    assert ko_letter_of("사전") == "ㅅ"
    assert ko_letter_of("까치") == "ㄱ"      # ㄲ folds → ㄱ
    assert ko_letter_of("Report.pdf") is None  # non-Hangul
    # Every consonant's range is non-empty and maps back to itself.
    for L in KO_INDEX_LETTERS:
        lo, hi = ko_letter_range(L)
        assert lo < hi and ko_letter_of(lo) == L


def test_en_ja_ko_present_with_required_fields():
    for lang in ("en", "ja", "ko"):
        m = LANG_MODELS[lang]
        for key in ("label", "embed", "synopsis", "synopsis_prompt", "tokenizer", "stopwords", "has_letter_index"):
            assert key in m, f"{lang} missing {key}"
        assert m["label"].strip(), f"{lang} label empty"


def test_ja_stack_matches_spec():
    ja = LANG_MODELS["ja"]
    assert ja["embed"] == "bge-m3"
    assert ja["synopsis"] == "fuukeidaisuki/nvidia-nemotron-nano-9b-v2-japanese:latest"
    assert ja["tokenizer"] == "unicode61"
    assert ja["has_letter_index"] is False  # CJK: hide A–Z bar
    assert ja["cjk_ngram"] is True


def test_ko_stack_matches_spec():
    ko = LANG_MODELS["ko"]
    assert ko["embed"] == "bge-m3"  # multilingual, reused from ja
    assert ko["synopsis"] == "exaone3.5:latest"
    assert ko["tokenizer"] == "unicode61"
    assert ko["has_letter_index"] is True  # Hangul: leading-consonant index bar
    assert ko["index_letters"] == list("ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ")  # 14 choseong
    assert ko["cjk_ngram"] is True  # Hangul bigram segmentation (agglutinative)
    assert "ko" in SUPPORTED_LANGS


def test_zh_stack_matches_spec():
    zh = LANG_MODELS["zh"]
    assert zh["embed"] == "bge-m3"  # multilingual, reused from ja/ko
    assert zh["synopsis"] == "ornith-1.5:9b"
    assert zh["tokenizer"] == "unicode61"
    assert zh["has_letter_index"] is False  # Chinese is not alphabetic (like ja)
    assert "index_letters" not in zh        # no first-letter index bar
    assert zh["cjk_ngram"] is True           # CJK bigram segmentation
    assert zh["stopwords"] == frozenset()
    assert "zh" in SUPPORTED_LANGS


def test_zh_hant_stack_matches_spec():
    zh = LANG_MODELS["zh-hant"]
    assert zh["embed"] == "bge-m3"
    assert zh["synopsis"] == "ornith-1.5:9b"  # same model, Traditional-forcing prompt
    assert zh["synopsis_prompt"] != LANG_MODELS["zh"]["synopsis_prompt"]
    assert zh["tokenizer"] == "unicode61"
    assert zh["has_letter_index"] is False
    assert "index_letters" not in zh
    assert zh["cjk_ngram"] is True
    assert "zh-hant" in SUPPORTED_LANGS


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
    assert resolve("ZH-Hant") is LANG_MODELS["zh-hant"]  # hyphenated code, lowercased


def test_lang_from_config():
    assert lang_from_config({}) == "en"
    assert lang_from_config({"lang": "JA"}) == "ja"
    assert lang_from_config({"lang": "xx"}) == "en"
