# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""First-run prompts; upgrade preserves lang. Run: python3 -m pytest test_i18n_firstrun.py -v"""
from docubrowser import resolve_or_prompt_lang


def test_existing_lang_never_prompts():
    # A config that already has lang must be returned untouched, even non-TTY.
    assert resolve_or_prompt_lang({"lang": "ja"}, is_tty=False) == "ja"
    assert resolve_or_prompt_lang({"lang": "ja"}, is_tty=True) == "ja"


def test_fresh_non_tty_defaults_en():
    assert resolve_or_prompt_lang({}, is_tty=False) == "en"


def test_existing_unknown_lang_normalizes_to_en():
    assert resolve_or_prompt_lang({"lang": "xx"}, is_tty=False) == "en"
    assert resolve_or_prompt_lang({"lang": "xx"}, is_tty=True) == "en"


def test_existing_lang_case_insensitive():
    assert resolve_or_prompt_lang({"lang": "JA"}, is_tty=False) == "ja"
