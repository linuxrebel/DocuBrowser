# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""Single source of truth for per-language models, prompts, tokenizer, and
stopwords. Adding a language = add a row here + a locales/<lang>.json file."""

# The existing English synopsis prompt is moved here verbatim in Task 2; for now
# a compact equivalent keeps behavior identical. Keep the EN text byte-for-byte
# equal to the string currently in doc_search.generate_synopsis when Task 2 runs.
_EN_SYNOPSIS_PROMPT = (
    "Write a short, engaging book-jacket style synopsis (2-4 sentences) of the "
    "following document. Do not add a preamble; return only the synopsis.\n\n{text}"
)
_JA_SYNOPSIS_PROMPT = (
    "次の文書の内容を、本の帯のような魅力的な紹介文として2〜4文で日本語で書いてください。"
    "前置きは不要で、紹介文のみを返してください。\n\n{text}"
)

# English articles + FANBOYS (matches the current strip_stopwords set).
_EN_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "nor", "for", "so", "yet",
})
# Japanese: v1 does not strip particles (segmentation is nontrivial); empty set.
_JA_STOPWORDS = frozenset()

LANG_MODELS = {
    "en": {
        "embed": "nomic-embed-text",
        "synopsis": "dolphin3:latest",
        "synopsis_prompt": _EN_SYNOPSIS_PROMPT,
        "tokenizer": "unicode61",
        "stopwords": _EN_STOPWORDS,
        "has_letter_index": True,
    },
    "ja": {
        "embed": "bge-m3",
        "synopsis": "fuukeidaisuki/nvidia-nemotron-nano-9b-v2-japanese:latest",
        "synopsis_prompt": _JA_SYNOPSIS_PROMPT,
        "tokenizer": "trigram",
        "stopwords": _JA_STOPWORDS,
        "has_letter_index": False,
    },
}

SUPPORTED_LANGS = ("en", "ja")


def resolve(lang):
    """Return the model row for `lang`, falling back to English."""
    if not lang:
        return LANG_MODELS["en"]
    return LANG_MODELS.get(str(lang).lower(), LANG_MODELS["en"])


def lang_from_config(config):
    """Read + normalize the configured language, defaulting to English."""
    lang = str((config or {}).get("lang", "en")).lower()
    return lang if lang in LANG_MODELS else "en"
