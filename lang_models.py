# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""Single source of truth for per-language models, prompts, tokenizer, and
stopwords. Adding a language = add a row here + a locales/<lang>.json file."""

import os
from pathlib import Path

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
_KO_SYNOPSIS_PROMPT = (
    "아래의 문서 발췌를 한 단락으로 간결하게 요약하십시오. 문서가 실제로 담고 "
    "있는 내용(주제, 목적, 핵심 토픽)만 설명하십시오. 요약은 전적으로 발췌 "
    "텍스트에만 근거해야 하며, 제목만으로 내용을 추측하거나 존재하지 않는 내용을 "
    "지어내지 마십시오. 마크다운, 제목, 글머리 기호를 사용하지 마십시오. 앞말 없이 "
    "단락 자체만 출력하십시오.\n\n"
    "제목: {title}\n\n"
    "문서 발췌:\n{context}"
)

# English articles + FANBOYS (matches the current strip_stopwords set).
_EN_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "nor", "for", "so", "yet",
})
# Japanese: v1 does not strip particles (segmentation is nontrivial); empty set.
_JA_STOPWORDS = frozenset()
# Korean: agglutinative particles attach to nouns; v1 relies on bigram
# segmentation (cjk.py) rather than a particle list. Empty set, like Japanese.
_KO_STOPWORDS = frozenset()

LANG_MODELS = {
    "en": {
        "embed": "nomic-embed-text",
        "synopsis": "dolphin3:latest",
        "synopsis_prompt": _EN_SYNOPSIS_PROMPT,
        "tokenizer": "unicode61",
        "stopwords": _EN_STOPWORDS,
        "has_letter_index": True,
        "cjk_ngram": False,
    },
    "ja": {
        "embed": "bge-m3",
        "synopsis": "fuukeidaisuki/nvidia-nemotron-nano-9b-v2-japanese:latest",
        "synopsis_prompt": _JA_SYNOPSIS_PROMPT,
        "tokenizer": "unicode61",
        "stopwords": _JA_STOPWORDS,
        "has_letter_index": False,
        "cjk_ngram": True,
    },
    "ko": {
        "embed": "bge-m3",
        "synopsis": "exaone3.5:latest",
        "synopsis_prompt": _KO_SYNOPSIS_PROMPT,
        "tokenizer": "unicode61",
        "stopwords": _KO_STOPWORDS,
        "has_letter_index": False,
        "cjk_ngram": True,
    },
}

SUPPORTED_LANGS = ("en", "ja", "ko")


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
    if app_dir is None:
        app_dir = Path(__file__).resolve().parent
    if user_data is None:
        user_data = Path.home() / ".docubrowser"

    lang = "en"
    for cfg_path in (Path(user_data) / "docubrowse.config", Path(app_dir) / "docubrowse.config"):
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

    env = os.environ.get("DOCUBROWSE_LANG")
    if env:
        lang = env.strip().lower()

    return lang if lang in LANG_MODELS else "en"
