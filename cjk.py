# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""App-side CJK segmentation: expand runs of CJK characters into overlapping
character bigrams so a whitespace tokenizer (unicode61) can match 2+ char CJK
queries. Used identically at index time and query time."""
import re

# Hiragana/Katakana, CJK Unified (+ Ext A), CJK Compatibility, Hangul syllables.
_CJK_RUN = re.compile(r'[぀-ヿ㐀-鿿豈-﫿가-힣]+')


def _bigrams(run: str) -> str:
    if len(run) < 2:
        return run
    return ' '.join(run[i:i + 2] for i in range(len(run) - 1))


def cjk_segment(text: str) -> str:
    """Return `text` with every CJK run replaced by space-joined bigrams,
    padded with spaces so runs stay separate tokens under unicode61."""
    if not text:
        return text
    return _CJK_RUN.sub(lambda m: ' ' + _bigrams(m.group(0)) + ' ', text).strip()
