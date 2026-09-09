# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""Language switch decides when a rebuild is required. Run: python3 -m pytest test_i18n_language_switch.py -v"""
from doc_search import rebuild_required


def test_en_to_ja_requires_rebuild():
    assert rebuild_required("en", "ja") is True   # embedder + tokenizer change


def test_same_language_no_rebuild():
    assert rebuild_required("ja", "ja") is False


def test_unknown_target_falls_back_no_crash():
    assert rebuild_required("en", "xx") is False   # xx→en, same as en→en


def test_reverse_direction_also_requires_rebuild():
    assert rebuild_required("ja", "en") is True
