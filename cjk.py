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


# ─── Korean first-letter index ──────────────────────────────────────────────
# 14 basic leading consonants (choseong). Tense consonants fold into their base
# (ㄲ→ㄱ). Each basic consonant covers a contiguous block of Hangul syllables,
# so a title's index letter is a Unicode-range lookup and the search filter is a
# plain `>=`/`<` range.
KO_INDEX_LETTERS = ["ㄱ", "ㄴ", "ㄷ", "ㄹ", "ㅁ", "ㅂ", "ㅅ",
                    "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"]
_HANGUL_BASE = 0xAC00        # '가'
_HANGUL_LAST = 0xD7A3        # '힣'
# choseong-index span [lo, hi) per basic consonant (19-slot choseong ordering)
_KO_CHOSEONG_SPAN = {
    "ㄱ": (0, 2), "ㄴ": (2, 3), "ㄷ": (3, 5), "ㄹ": (5, 6), "ㅁ": (6, 7),
    "ㅂ": (7, 9), "ㅅ": (9, 11), "ㅇ": (11, 12), "ㅈ": (12, 14),
    "ㅊ": (14, 15), "ㅋ": (15, 16), "ㅌ": (16, 17), "ㅍ": (17, 18),
    "ㅎ": (18, 19),
}


def ko_letter_of(text: str):
    """Basic-consonant index letter for a title's first Hangul syllable, or
    None if it doesn't start with a Hangul syllable."""
    if not text:
        return None
    code = ord(text[0])
    if _HANGUL_BASE <= code <= _HANGUL_LAST:
        cho = (code - _HANGUL_BASE) // 588  # 0..18
        for letter, (lo, hi) in _KO_CHOSEONG_SPAN.items():
            if lo <= cho < hi:
                return letter
    return None


def ko_letter_range(letter: str):
    """(lo_char, hi_char) half-open Hangul syllable range for a Korean index
    letter, or None if `letter` isn't one of KO_INDEX_LETTERS."""
    span = _KO_CHOSEONG_SPAN.get(letter)
    if not span:
        return None
    lo, hi = span
    return chr(_HANGUL_BASE + lo * 588), chr(_HANGUL_BASE + hi * 588)
