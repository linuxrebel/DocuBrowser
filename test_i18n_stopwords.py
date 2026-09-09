# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""Stopword stripping is language-aware. Run: python3 -m pytest test_i18n_stopwords.py -v"""
from deep_links import strip_stopwords


def test_en_strips_articles_and_conjunctions():
    assert strip_stopwords("man in the middle", "en") == "man in middle"
    assert strip_stopwords("freedom and liberty", "en") == "freedom liberty"


def test_ja_is_noop():
    assert strip_stopwords("機械学習 の 入門", "ja") == "機械学習 の 入門"


def test_default_is_en():
    assert strip_stopwords("the cat") == "cat"


def test_all_stopword_query_returns_original():
    assert strip_stopwords("the a an", "en") == "the a an"


def test_unknown_lang_falls_back_to_en_behavior():
    assert strip_stopwords("the cat", "xx") == "cat"
