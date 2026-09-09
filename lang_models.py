# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""Single source of truth for per-language models, prompts, tokenizer, and
stopwords. Adding a language = add a row here + a locales/<lang>.json file."""

# The existing English synopsis prompt is moved here verbatim in Task 2; for now
# a compact equivalent keeps behavior identical. Keep the EN text byte-for-byte
# equal to the string currently in doc_search.generate_synopsis when Task 2 runs.
_EN_SYNOPSIS_PROMPT = (
    "Summarize the document excerpt below in one concise paragraph. "
    "Describe only what the document actually contains — its subject matter, "
    "purpose, and key topics. Base the summary entirely on the excerpt text; "
    "do not invent content or draw on the document title alone. "
    "Do not use markdown, headings, or bullet points. Output only the "
    "paragraph itself, with no preamble.\n\n"
    "Title: {title}\n\n"
    "Document excerpt:\n{context}"
)
_JA_SYNOPSIS_PROMPT = (
    "以下の文書抜粋を一段落で簡潔に要約してください。文書が実際に含む内容"
    "(主題、目的、主要なトピック)のみを説明してください。要約は抜粋のテキスト"
    "のみに基づいてください。タイトルだけから内容を推測したり、存在しない内容"
    "を作り出したりしないでください。マークダウン、見出し、箇条書きは使用しな"
    "いでください。出力は前置きなしで段落のみとしてください。\n\n"
    "タイトル: {title}\n\n"
    "文書抜粋:\n{context}"
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


def config_lang(app_dir=None, user_data=None):
    """Read the configured language from docubrowse.config.

    Checks the packaged-install path (user_data/docubrowse.config) before the
    dev/standalone path (app_dir/docubrowse.config) — same precedence as
    doc_search.handle_config. DOCUBROWSE_LANG env var overrides the file.
    Falls back to "en" when no lang key is set or the value is unrecognized.
    """
    import os as _os
    from pathlib import Path as _Path

    if app_dir is None:
        app_dir = _Path(__file__).resolve().parent
    if user_data is None:
        user_data = _Path.home() / ".docubrowser"

    lang = "en"
    for cfg_path in (_Path(user_data) / "docubrowse.config", _Path(app_dir) / "docubrowse.config"):
        if cfg_path.exists():
            try:
                text = cfg_path.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                if key.strip().lower() == "lang":
                    lang = val.strip().lower()
            break  # first existing config file wins (mirrors handle_config)

    env = _os.environ.get("DOCUBROWSE_LANG")
    if env:
        lang = env.strip().lower()

    return lang if lang in LANG_MODELS else "en"
