# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""App-side CJK bigram segmentation. Run: python3 -m pytest test_cjk.py -v"""
from cjk import cjk_segment
from lang_models import LANG_MODELS


def test_two_char_compound_becomes_one_bigram():
    assert cjk_segment("品種") == "品種"


def test_longer_run_overlapping_bigrams():
    assert cjk_segment("機械学習") == "機械 械学 学習"


def test_non_cjk_passes_through():
    assert cjk_segment("hello world") == "hello world"


def test_mixed_text_segments_only_cjk_runs():
    assert cjk_segment("Linux は 機械学習").split() == ["Linux", "は", "機械", "械学", "学習"]


def test_lone_cjk_char_passes_through():
    assert cjk_segment("袋").strip() == "袋"


def test_hangul_and_hanzi_runs():
    assert cjk_segment("机器学习") == "机器 器学 学习"      # Chinese
    assert cjk_segment("기계학습") == "기계 계학 학습"      # Korean


def test_flags_present():
    assert LANG_MODELS["ja"]["cjk_ngram"] is True
    assert LANG_MODELS["ja"]["tokenizer"] == "unicode61"
    assert LANG_MODELS["en"].get("cjk_ngram", False) is False
