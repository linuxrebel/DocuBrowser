# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""Locale files exist with identical keys. Run: python3 -m pytest test_locales.py -v"""
import json
import glob
import os

LOCALE_DIR = os.path.join(os.path.dirname(__file__), "locales")


def _load(name):
    with open(os.path.join(LOCALE_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def test_en_and_ja_exist():
    assert os.path.exists(os.path.join(LOCALE_DIR, "en.json"))
    assert os.path.exists(os.path.join(LOCALE_DIR, "ja.json"))


def test_all_locales_have_identical_keys():
    en_keys = set(_load("en.json").keys())
    assert en_keys, "en.json must define keys"
    for path in glob.glob(os.path.join(LOCALE_DIR, "*.json")):
        keys = set(_load(os.path.basename(path)).keys())
        assert keys == en_keys, f"{os.path.basename(path)} key mismatch: {keys ^ en_keys}"


def test_no_value_is_empty():
    for path in glob.glob(os.path.join(LOCALE_DIR, "*.json")):
        for k, v in _load(os.path.basename(path)).items():
            assert isinstance(v, str) and v.strip(), f"{path}:{k} empty"


def test_minimum_key_set_present():
    required = {
        "search_placeholder", "mode_keyword", "mode_semantic", "mode_both",
        "settings", "all_documents", "search_results", "starting_with",
        "showing", "of", "back", "next", "home", "open", "hide", "unhide",
        "show_hidden", "hide_hidden", "light", "dark", "no_dir_banner",
        "synopsis_generating",
    }
    en_keys = set(_load("en.json").keys())
    missing = required - en_keys
    assert not missing, f"en.json missing required keys: {missing}"
