# i18n / Multi-Language Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make DocuBrowse fully usable in a chosen language (Japanese first) — localized UI plus language-appropriate embeddings, keyword tokenization, and synopsis — with adding further languages being a data change, not a code change.

**Architecture:** One install serves one language (corpus ~99.9% that language). A single data-driven `LANG_MODELS` table is the source of truth for each language's embedder, summary model, synopsis prompt, FTS tokenizer, and stopwords. UI strings move into per-language locale JSON resolved by a client `t(key)`. Models are pulled lazily from Ollama at first-run and on a Settings language switch.

**Tech Stack:** Python 3.9+ (stdlib + existing deps: numpy, psutil), SQLite FTS5, Ollama HTTP API, single-file `index.html`/`settings.html` frontend (vanilla JS), pytest for tests.

**Spec:** `docs/superpowers/specs/2026-09-09-i18n-language-support-design.md`

## Global Constraints

- **Per-install single language.** No per-document detection, no mixed corpora. Verbatim assumption: corpus is ~99.9% documents in the chosen language.
- **One package**, all locale JSON bundled; models pulled from Ollama at runtime, never bundled.
- **Default language is `en`.** When `lang` is unset/unknown, behave exactly as today (regression guard on every backend task).
- **Adding a language = one `LANG_MODELS` row + one `locales/<lang>.json`.** No new code branches per language.
- **Tokenizer by family:** CJK (`ja`, `zh`, `ko`) → FTS5 `trigram`; European (`es`, `fr`, `de`, `nl`) → `unicode61` with `remove_diacritics 2`.
- **JP stack:** embedder `bge-m3`; summary `fuukeidaisuki/nvidia-nemotron-nano-9b-v2-japanese:latest`; tokenizer `trigram`.
- **License header** on every new `.py`: `# SPDX-License-Identifier: GPL-3.0-or-later` then `# Copyright (C) 2026 James Sparenberg`.
- **Commits authored as James** (system gitconfig, never override). Work on `development`.
- Tests are standalone `test_*.py` at repo root; each importable module tested with pytest functions. Run with `python3 -m pytest test_x.py -v`.

---

### Task 1: `lang_models.py` — the per-language table and resolvers

**Files:**
- Create: `lang_models.py`
- Test: `test_lang_models.py`

**Interfaces:**
- Produces:
  - `LANG_MODELS: dict[str, dict]` — keys `en`, `ja`; each value has `embed: str`, `synopsis: str`, `synopsis_prompt: str`, `tokenizer: str`, `stopwords: frozenset[str]`, `has_letter_index: bool`.
  - `SUPPORTED_LANGS: tuple[str, ...]` — ordered langs for UI (`("en", "ja")`).
  - `resolve(lang: str) -> dict` — returns `LANG_MODELS[lang]`, falling back to `LANG_MODELS["en"]` for unknown/empty.
  - `lang_from_config(config: dict) -> str` — returns `config.get("lang", "en")` normalized to lowercase; unknown → `"en"`.

- [ ] **Step 1: Write the failing test**

```python
# test_lang_models.py
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""Tests for the per-language model/resolver table. Run: python3 -m pytest test_lang_models.py -v"""
from lang_models import LANG_MODELS, SUPPORTED_LANGS, resolve, lang_from_config


def test_en_and_ja_present_with_required_fields():
    for lang in ("en", "ja"):
        m = LANG_MODELS[lang]
        for key in ("embed", "synopsis", "synopsis_prompt", "tokenizer", "stopwords", "has_letter_index"):
            assert key in m, f"{lang} missing {key}"


def test_ja_stack_matches_spec():
    ja = LANG_MODELS["ja"]
    assert ja["embed"] == "bge-m3"
    assert ja["synopsis"] == "fuukeidaisuki/nvidia-nemotron-nano-9b-v2-japanese:latest"
    assert ja["tokenizer"] == "trigram"
    assert ja["has_letter_index"] is False  # CJK: hide A–Z bar


def test_en_stack_unchanged():
    en = LANG_MODELS["en"]
    assert en["embed"] == "nomic-embed-text"
    assert en["synopsis"] == "dolphin3:latest"
    assert en["tokenizer"] == "unicode61"
    assert en["has_letter_index"] is True


def test_resolve_falls_back_to_en():
    assert resolve("kling") is LANG_MODELS["en"]
    assert resolve("") is LANG_MODELS["en"]
    assert resolve("ja") is LANG_MODELS["ja"]


def test_lang_from_config():
    assert lang_from_config({}) == "en"
    assert lang_from_config({"lang": "JA"}) == "ja"
    assert lang_from_config({"lang": "xx"}) == "en"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test_lang_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lang_models'`

- [ ] **Step 3: Write minimal implementation**

```python
# lang_models.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest test_lang_models.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add lang_models.py test_lang_models.py
git commit -m "feat(i18n): add per-language LANG_MODELS table + resolvers"
```

---

### Task 2: Resolve embedder + synopsis model/prompt from language

**Files:**
- Modify: `embed_docs.py` (constant `EMBEDDING_MODEL`, ~line 67; embed call ~line 118)
- Modify: `doc_search.py` (constants `EMBEDDING_MODEL`/`SYNOPSIS_MODEL`, ~lines 207-208; `generate_synopsis` prompt ~line 376; `_model_present` checks ~line 838)
- Test: `test_i18n_models.py`

**Interfaces:**
- Consumes: `lang_models.resolve`, `lang_models.lang_from_config` (Task 1).
- Produces: module-level `EMBEDDING_MODEL` / `SYNOPSIS_MODEL` in both files now derived from the active config language via a helper `active_models(config_path=None) -> dict`. The English prompt string moves verbatim into `LANG_MODELS["en"]["synopsis_prompt"]`.

Both files already load config (grep `read_config`/`load_config` in each and reuse it; if a file lacks a loader, add `from lang_models import resolve, lang_from_config` and read the same `docubrowse.config` the CLI reads). The key change: replace the two literal constants with a lookup at process start.

- [ ] **Step 1: Write the failing test**

```python
# test_i18n_models.py
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""Model resolution follows the configured language. Run: python3 -m pytest test_i18n_models.py -v"""
from lang_models import resolve


def test_en_models():
    m = resolve("en")
    assert m["embed"] == "nomic-embed-text"
    assert m["synopsis"] == "dolphin3:latest"


def test_ja_models():
    m = resolve("ja")
    assert m["embed"] == "bge-m3"
    assert "nemotron-nano-9b-v2-japanese" in m["synopsis"]


def test_en_synopsis_prompt_has_text_placeholder():
    assert "{text}" in resolve("en")["synopsis_prompt"]
    assert "{text}" in resolve("ja")["synopsis_prompt"]
```

- [ ] **Step 2: Run test to verify it fails (or passes trivially) then wire the source**

Run: `python3 -m pytest test_i18n_models.py -v`
Expected: PASS for resolve (Task 1), but the wiring below is what this task delivers — verify by the regression run in Step 4.

- [ ] **Step 3: Wire the constants**

In `embed_docs.py`, replace:

```python
EMBEDDING_MODEL = "nomic-embed-text"
```

with:

```python
from lang_models import resolve, lang_from_config
# Resolve the active language's embedder once at import (single-language install).
EMBEDDING_MODEL = resolve(lang_from_config(_read_config())).get("embed", "nomic-embed-text")
```

where `_read_config()` is the existing config-dict loader in the file (reuse it; if the loader lives elsewhere, import it — do NOT add a second config parser).

In `doc_search.py`, replace:

```python
EMBEDDING_MODEL = "nomic-embed-text"
SYNOPSIS_MODEL = "dolphin3:latest"
```

with:

```python
from lang_models import resolve, lang_from_config
_ACTIVE = resolve(lang_from_config(_load_config()))
EMBEDDING_MODEL = _ACTIVE["embed"]
SYNOPSIS_MODEL = _ACTIVE["synopsis"]
```

Then in `generate_synopsis`, replace the inline English prompt string with:

```python
prompt = _ACTIVE["synopsis_prompt"].format(text=text)
```

and **move the current literal prompt text into `lang_models._EN_SYNOPSIS_PROMPT` verbatim** (copy the exact existing wording so English output is byte-identical), updating the Task 1 file if the wording differs.

- [ ] **Step 4: Run regression + module import**

Run:
```bash
python3 -c "import ast; ast.parse(open('doc_search.py').read()); ast.parse(open('embed_docs.py').read()); print('parse OK')"
python3 -m pytest test_i18n_models.py test_lang_models.py -v
```
Expected: parse OK; all tests PASS. With no `lang` in config, `EMBEDDING_MODEL == "nomic-embed-text"` and `SYNOPSIS_MODEL == "dolphin3:latest"` (English unchanged).

- [ ] **Step 5: Commit**

```bash
git add embed_docs.py doc_search.py lang_models.py test_i18n_models.py
git commit -m "feat(i18n): resolve embedder + synopsis model/prompt from configured language"
```

---

### Task 3: FTS tokenizer per language

**Files:**
- Modify: `docubrowse_db.py` (`CREATE VIRTUAL TABLE ... doc_fts` at ~line 138 and the migration recreate at ~line 180)
- Test: `test_fts_tokenizer.py`

**Interfaces:**
- Consumes: `lang_models.resolve` (Task 1).
- Produces: `init_db(db_path, lang="en")` — accepts a language; `doc_fts` is created with that language's tokenizer. Callers that don't pass `lang` default to `"en"` (unchanged behavior).

Japanese needs `trigram` because the default `unicode61` tokenizer keys on whitespace and won't segment 日本語. Trigram indexes 3-char sequences, so substring queries match CJK.

- [ ] **Step 1: Write the failing test**

```python
# test_fts_tokenizer.py
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""JP keyword search needs the trigram tokenizer. Run: python3 -m pytest test_fts_tokenizer.py -v"""
import tempfile, sqlite3
from pathlib import Path
from docubrowse_db import init_db


def _fts_sql(db_path):
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='doc_fts'").fetchone()
    conn.close()
    return row[0] if row else ""


def test_en_uses_default_tokenizer():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "en.db")
        init_db(db, lang="en")
        assert "trigram" not in _fts_sql(db)


def test_ja_uses_trigram():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "ja.db")
        init_db(db, lang="ja")
        assert "trigram" in _fts_sql(db)


def test_ja_substring_match_on_cjk():
    """A Japanese term embedded in a longer run matches under trigram."""
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "ja.db")
        init_db(db, lang="ja")
        conn = sqlite3.connect(db)
        # doc_fts is contentless; insert a row mirroring the real columns.
        conn.execute(
            "INSERT INTO doc_fts(rowid, name, title, author, subject, description, content_snippet, tags) "
            "VALUES (1, '', '機械学習の入門書です', '', '', '', '', '')")
        hits = conn.execute(
            "SELECT rowid FROM doc_fts WHERE doc_fts MATCH ?", ('"機械学習"',)).fetchall()
        conn.close()
        assert hits == [(1,)]
```

(Adjust the `INSERT` column list in the test to the actual `doc_fts` columns in `docubrowse_db.py`; read them before writing the test.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test_fts_tokenizer.py -v`
Expected: FAIL — `test_ja_uses_trigram` (no tokenize clause) and likely `test_ja_substring_match_on_cjk` (no match under unicode61).

- [ ] **Step 3: Implement tokenizer selection**

Add a `lang="en"` parameter to `init_db` (and any internal `_create_fts`/migration helper). Compute the tokenizer clause:

```python
from lang_models import resolve
_tok = resolve(lang)["tokenizer"]
_tok_clause = {
    "trigram": ", tokenize='trigram'",
    "unicode61": ", tokenize=\"unicode61 remove_diacritics 2\"",
}.get(_tok, "")
```

Append `{_tok_clause}` inside the `CREATE VIRTUAL TABLE ... doc_fts USING fts5(... {_tok_clause})` at both the create site and the migration recreate site. Keep the column list unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest test_fts_tokenizer.py test_lang_models.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add docubrowse_db.py test_fts_tokenizer.py
git commit -m "feat(i18n): select FTS5 tokenizer per language (trigram for CJK)"
```

---

### Task 4: `ensure_ollama` pulls the active language's models

**Files:**
- Modify: `ensure_ollama.py` (`REQUIRED_MODELS` list, ~lines 39-40)
- Test: `test_i18n_ensure_ollama.py`

**Interfaces:**
- Consumes: `lang_models.resolve`, `lang_from_config` (Task 1).
- Produces: `required_models(lang: str) -> list[tuple]` — the `(model, size_hint, purpose)` rows for that language's embed + synopsis models. The module's top-level provisioning uses `required_models(lang_from_config(config))`.

- [ ] **Step 1: Write the failing test**

```python
# test_i18n_ensure_ollama.py
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""Required Ollama models follow the language. Run: python3 -m pytest test_i18n_ensure_ollama.py -v"""
from ensure_ollama import required_models


def _names(rows):
    return {r[0] for r in rows}


def test_en_required():
    assert _names(required_models("en")) == {"nomic-embed-text:latest", "dolphin3:latest"}


def test_ja_required():
    names = _names(required_models("ja"))
    assert "bge-m3:latest" in names
    assert any("nemotron-nano-9b-v2-japanese" in n for n in names)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test_i18n_ensure_ollama.py -v`
Expected: FAIL — `required_models` not defined.

- [ ] **Step 3: Implement**

Replace the hardcoded `REQUIRED_MODELS` usage with:

```python
from lang_models import resolve, lang_from_config

def required_models(lang):
    m = resolve(lang)
    embed = m["embed"] if ":" in m["embed"] else m["embed"] + ":latest"
    synopsis = m["synopsis"] if ":" in m["synopsis"] else m["synopsis"] + ":latest"
    return [
        (embed, "", "semantic search embeddings (ingestion)"),
        (synopsis, "", "document synopsis generation (operational AI)"),
    ]
```

Update the module's provisioning entry point to iterate `required_models(lang_from_config(_config()))` instead of the old constant. Keep the existing pull/verify logic; only the source list changes.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest test_i18n_ensure_ollama.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add ensure_ollama.py test_i18n_ensure_ollama.py
git commit -m "feat(i18n): ensure_ollama provisions the active language's model set"
```

---

### Task 5: Locale files + `/api/config` returns `lang` and locale

**Files:**
- Create: `locales/en.json`, `locales/ja.json`
- Modify: `doc_search.py` (`handle_config` / `/api/config` response builder)
- Test: `test_locales.py`

**Interfaces:**
- Produces:
  - `locales/en.json`, `locales/ja.json` — flat `{ "key": "string" }` maps with identical key sets.
  - `/api/config` JSON gains `"lang": "<active>"` and `"locale": { ...active locale map... }`.
  - Helper `load_locale(lang: str) -> dict` in `doc_search.py` (reads `locales/<lang>.json`, falls back to `en`).

Enumerate keys from the strings identified in Task 7 (the UI audit). Minimum key set (extend as Task 7 finds more): `search_placeholder`, `mode_keyword`, `mode_semantic`, `mode_both`, `settings`, `all_documents`, `search_results`, `starting_with`, `showing`, `of`, `back`, `next`, `home`, `open`, `hide`, `unhide`, `show_hidden`, `hide_hidden`, `docs_label`, `tags_label`, `light`, `dark`, `no_dir_banner`, `synopsis_generating`.

- [ ] **Step 1: Write the failing test**

```python
# test_locales.py
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""Locale files exist with identical keys. Run: python3 -m pytest test_locales.py -v"""
import json, glob, os

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test_locales.py -v`
Expected: FAIL — locale files missing.

- [ ] **Step 3: Create locale files + wire `/api/config`**

Create `locales/en.json` (English strings, taken verbatim from the current UI) and `locales/ja.json` (Japanese translations), identical keys. Example (extend to the full key set):

```json
{
  "mode_keyword": "Keyword",
  "mode_semantic": "Semantic",
  "mode_both": "Both",
  "settings": "Settings",
  "all_documents": "All Documents",
  "showing": "showing",
  "of": "of",
  "back": "Back",
  "next": "Next"
}
```

```json
{
  "mode_keyword": "キーワード",
  "mode_semantic": "セマンティック",
  "mode_both": "両方",
  "settings": "設定",
  "all_documents": "すべての文書",
  "showing": "表示中",
  "of": "／",
  "back": "戻る",
  "next": "次へ"
}
```

In `doc_search.py`, add `load_locale(lang)` and include `"lang"` + `"locale"` in the `/api/config` response, using the active `lang` (from `lang_from_config` on the loaded config).

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest test_locales.py -v`
Expected: PASS. Also manually: start a server and confirm `/api/config` includes `lang` and `locale` (curl via `python3 -c` urllib, not curl — the sandbox blocks curl).

- [ ] **Step 5: Commit**

```bash
git add locales/en.json locales/ja.json doc_search.py test_locales.py
git commit -m "feat(i18n): add en/ja locale files and serve lang+locale via /api/config"
```

---

### Task 6: `strip_stopwords` becomes language-aware

**Files:**
- Modify: `deep_links.py` (`strip_stopwords`) and its use in `doc_search.py` semantic path
- Test: `test_i18n_stopwords.py`

**Interfaces:**
- Consumes: `lang_models.resolve` (Task 1).
- Produces: `strip_stopwords(text: str, lang: str = "en") -> str` — strips the language's stopword set. `en` behaves exactly as today; `ja` (empty set) is a no-op.

- [ ] **Step 1: Write the failing test**

```python
# test_i18n_stopwords.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test_i18n_stopwords.py -v`
Expected: FAIL — `strip_stopwords` doesn't accept a `lang` argument.

- [ ] **Step 3: Implement**

Change `strip_stopwords(text, lang="en")` to pull the set from `resolve(lang)["stopwords"]` instead of a hardcoded English set. Update the caller in `doc_search.py` to pass the active `lang` (`strip_stopwords(q, _ACTIVE_LANG)`), where `_ACTIVE_LANG = lang_from_config(_load_config())` is computed once (add it next to `_ACTIVE` from Task 2).

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest test_i18n_stopwords.py test_lang_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add deep_links.py doc_search.py test_i18n_stopwords.py
git commit -m "feat(i18n): make strip_stopwords language-aware (en unchanged, ja no-op)"
```

---

### Task 7: UI locale layer — `t(key)` in `index.html` (and hide A–Z bar for CJK)

**Files:**
- Modify: `index.html` (add `t()`, load locale from `/api/config`, replace hardcoded labels; gate the index bar on `has_letter_index`)
- Test: browser-driven (no JS unit harness in this repo)

**Interfaces:**
- Consumes: `/api/config` `lang` + `locale` (Task 5).
- Produces: a global `t(key)` returning `LOCALE[key] || key`; `LOCALE` populated from `/api/config` at startup before first render.

This task is the UI audit: every user-facing English literal in `index.html` (static HTML: `Keyword`/`Semantic`/`Both`, `Settings`, the search `placeholder`, the no-dir banner; JS template literals: `All Documents`, `Search Results`, `Starting with`, `showing`, `of`, `Back`, `Next`, `Home`, `Open`, toasts, titles `Hide`/`Unhide`/`Show Hidden Cards`) becomes `t('key')`. Add any missing keys to BOTH locale files (re-run `test_locales.py`).

- [ ] **Step 1: Add locale bootstrap + `t()`**

Near the top of the main `<script>`, before the first `renderAll()`:

```javascript
let LOCALE = {};
function t(key) { return LOCALE[key] || key; }
async function loadLocale() {
  try {
    const cfg = await (await fetch('/api/config')).json();
    LOCALE = cfg.locale || {};
    document.documentElement.lang = cfg.lang || 'en';
    HAS_LETTER_INDEX = cfg.lang !== 'ja';  // extended by has_letter_index in Task 5 payload if present
  } catch (e) { LOCALE = {}; }
}
```

Change the init at the bottom from `renderAll();` to:

```javascript
loadLocale().then(renderAll);
```

- [ ] **Step 2: Replace static-HTML labels**

Static HTML strings can't call `t()` at parse time; set them in `loadLocale()` after fetch, e.g.:

```javascript
document.querySelector('[data-mode="keyword"]').textContent = t('mode_keyword');
document.querySelector('[data-mode="semantic"]').textContent = t('mode_semantic');
document.querySelector('[data-mode="both"]').textContent = t('mode_both');
document.getElementById('searchInput').placeholder = t('search_placeholder');
// ...gear/settings label, banner text, Light/Dark toggle
```

- [ ] **Step 3: Replace JS-generated labels**

In `renderAll`/`loadMoreTop`/`loadMorePrev`/`reloadCurrentPage`/`filterByLetter`/`doSearch`, swap literals for `t()`:

```javascript
const title = currentQuery ? t('search_results')
  : (currentLetter ? `${t('starting_with')} "${esc(currentLetter)}"` : t('all_documents'));
// showing X of Y:
`${t('showing')} <b>${startIdx}-${endIdx}</b> ${t('of')} <b>${currentTotal}</b>`
```

Also `Back`/`Next`/`Home`/`Open`/`Hide`/`Unhide`/`Show Hidden Cards` titles and toasts.

- [ ] **Step 4: Gate the index bar for CJK**

In `renderIndexBar()`, return early (render nothing) when the language has no letter index:

```javascript
if (!HAS_LETTER_INDEX) { const b = document.querySelector('.index-bar'); if (b) b.remove(); return; }
```

- [ ] **Step 5: Verify in the browser**

Start a dev server against a copy DB with `lang=ja` in its config (never the live DB), open it in the Browser pane, and confirm: mode buttons/labels render Japanese, `showing … of …` is localized, and the A–Z bar is absent. Then set `lang=en` and confirm English is byte-identical to today (regression). Add any newly-found strings as keys and re-run `python3 -m pytest test_locales.py -v`.

- [ ] **Step 6: Commit**

```bash
git add index.html locales/en.json locales/ja.json
git commit -m "feat(i18n): localize index.html via t() and hide A–Z bar for CJK"
```

---

### Task 8: Settings language switcher + provisioning endpoint

**Files:**
- Modify: `settings.html` (Language dropdown + switch handler)
- Modify: `doc_search.py` (new `POST /api/language` — CSRF-gated — writes `lang`, pulls models, signals rebuild)
- Test: `test_i18n_language_switch.py`

**Interfaces:**
- Consumes: `SUPPORTED_LANGS` (Task 1), `ensure_ollama.required_models` (Task 4), the config writer used by `POST /api/config`.
- Produces: `POST /api/language?lang=<code>` returning `{"ok": true, "lang": "<code>", "rebuild_required": true|false}`. `rebuild_required` is true when the embedder or tokenizer differs from the previous language. The handler writes `lang` to `docubrowse.config` and kicks the model pull (reusing `ensure_ollama`).

- [ ] **Step 1: Write the failing test**

```python
# test_i18n_language_switch.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test_i18n_language_switch.py -v`
Expected: FAIL — `rebuild_required` not defined.

- [ ] **Step 3: Implement the decision + endpoint**

Add to `doc_search.py`:

```python
from lang_models import resolve

def rebuild_required(old_lang, new_lang):
    a, b = resolve(old_lang), resolve(new_lang)
    return a["embed"] != b["embed"] or a["tokenizer"] != b["tokenizer"]
```

Add `POST /api/language` (register it in the same CSRF-gated router as `POST /api/config`): read `lang`, validate against `SUPPORTED_LANGS`, compute `rebuild_required(current, lang)`, write `lang` into config via the existing config writer, trigger `ensure_ollama` provisioning for the new language (background thread, same pattern as the synopsis warm-up), and return the JSON above.

- [ ] **Step 4: Add the dropdown in `settings.html`**

A `<select id="langSelect">` populated from `SUPPORTED_LANGS` (hardcode the two options for now: English / 日本語). On change: `POST /api/language`, then if `rebuild_required` show a confirm explaining a re-embed + FTS rebuild is needed and, on accept, POST to the existing rescan/embed trigger (or instruct the CLI command in a toast, matching how scan-dirs already surfaces the CLI command). Reload the page so the new locale applies.

- [ ] **Step 5: Run test + browser check**

Run: `python3 -m pytest test_i18n_language_switch.py -v` → PASS.
Browser: on the copy DB, switch English→日本語 in Settings, confirm config updated and the rebuild warning appears; switch back.

- [ ] **Step 6: Commit**

```bash
git add settings.html doc_search.py test_i18n_language_switch.py
git commit -m "feat(i18n): Settings language switcher + /api/language provisioning endpoint"
```

---

### Task 9: First-run language prompt + upgrade preserves language

**Files:**
- Modify: `docubrowser.py` (first-run/no-`lang` prompt path)
- Modify: `install.sh` (+ `packaging/windows/install.ps1`, `packaging/macos/Install.command`) — language question on fresh install only
- Test: `test_i18n_firstrun.py`

**Interfaces:**
- Consumes: `SUPPORTED_LANGS`, `lang_from_config`, `ensure_ollama.required_models`.
- Produces: `resolve_or_prompt_lang(config: dict, is_tty: bool) -> str` in `docubrowser.py` — returns existing `lang` if present (no prompt); on a fresh config with a TTY, prompts and returns the choice; non-TTY fresh install defaults to `en`.

- [ ] **Step 1: Write the failing test**

```python
# test_i18n_firstrun.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test_i18n_firstrun.py -v`
Expected: FAIL — `resolve_or_prompt_lang` not defined.

- [ ] **Step 3: Implement**

```python
def resolve_or_prompt_lang(config, is_tty):
    from lang_models import LANG_MODELS, lang_from_config
    if "lang" in (config or {}):
        return lang_from_config(config)          # upgrade: keep existing, no prompt
    if not is_tty:
        return "en"                              # non-interactive fresh install
    print("Choose interface + document language:")
    opts = list(LANG_MODELS.keys())
    for i, code in enumerate(opts, 1):
        print(f"  {i}) {code}")
    choice = input(f"[1-{len(opts)}] (default 1=en): ").strip()
    try:
        return opts[int(choice) - 1]
    except (ValueError, IndexError):
        return "en"
```

Call it on first run (where the CLI first needs the language), and **write the chosen `lang` into `docubrowse.config`**. In `install.sh`, add the language question ONLY when generating a fresh config (skip entirely if a config with `lang` already exists — upgrade path), then pass it through to the generated config; the model pull is handled by `ensure_ollama` on first `start`.

- [ ] **Step 4: Run test + shell lint**

Run:
```bash
python3 -m pytest test_i18n_firstrun.py -v
bash -n install.sh
```
Expected: tests PASS; `bash -n` clean.

- [ ] **Step 5: Commit**

```bash
git add docubrowser.py install.sh packaging/windows/install.ps1 packaging/macos/Install.command test_i18n_firstrun.py
git commit -m "feat(i18n): first-run language prompt; upgrade preserves existing lang"
```

---

### Task 10: Docs, DECISIONS, packaging manifest, version note

**Files:**
- Modify: `README.md`, `INSTALL.md`, `EndUser_docs/User_Guide.md`, `EndUser_docs/Admin_Guide.md`
- Modify: `status_docs/DECISIONS.md` (add i18n decision entries; keep FOSS + Enterprise copies in sync)
- Modify: packaging manifests (`packaging/docubrowser-foss.spec`, DEB control/manifest, `install.sh` file list, Windows/macOS build scripts) to include `lang_models.py` + `locales/`
- Modify: `status_docs/project_status.md`

**Interfaces:** none (documentation + packaging).

- [ ] **Step 1: Update the packaging manifests**

Add `lang_models.py` and the `locales/` directory (both JSON files) to every packaging file list (`APP_FILES` in `install.sh`, the `.spec` `%files`, the DEB manifest, and the Windows/macOS build copy lists). Verify none are missed:

```bash
grep -rn "embed_docs.py" packaging install.sh | sed 's/embed_docs.py/lang_models.py/' # sanity: each should have a lang_models.py sibling after editing
```

- [ ] **Step 2: Update user-facing docs**

README: add a "Languages" section describing per-install single-language, the first-run prompt, the Settings switcher (with the re-embed warning), and the supported set (en, ja). INSTALL: note the install-time language question. User/Admin guides: language selection + switching. Remove/soften the "English only" Known Limitation.

- [ ] **Step 3: Record decisions**

Add DECISIONS.md entries: per-install single-language (D-nn), bge-m3 + trigram for JP (D-nn), one-package-not-per-language (D-nn), deferred My Number PII / kana index (D-nn). Mirror into the Enterprise `status_docs/DECISIONS.md`.

- [ ] **Step 4: Verify docs build/links**

```bash
grep -rn "English only" README.md   # expect: none, or clearly scoped to deferred items
python3 -m pytest test_locales.py test_lang_models.py -v   # final green gate
```

- [ ] **Step 5: Commit**

```bash
git add README.md INSTALL.md EndUser_docs/ status_docs/DECISIONS.md status_docs/project_status.md packaging/ install.sh
git commit -m "docs(i18n): document language support; add lang_models.py + locales to packaging"
```

---

---

## How we got here — post-implementation findings (2026-09-09)

Tasks 1–10 were implemented (a cowork subagent-driven session, commits
`5713085..7e1c3f8`) and merged to `main`. A live Japanese test run against real
docs then exposed two integration gaps the unit tests missed (they exercised
`resolve()`/`init_db()` directly; nothing wired **config → runtime**). Both
fixed and committed as `84a668b` (the clean baseline these follow-on tasks build
on):

1. **Tokenizer never threaded into `get_db`.** `get_db(db_path, lang="en")` and
   *no* call site passed `lang`, so a `lang=ja` install built `doc_fts` with the
   English tokenizer and JP keyword search returned nothing. Fixed: `get_db`
   resolves the language from `config_lang()` once per process
   (`_process_lang()` cache in `docubrowse_db.py`).
2. **JP synopsis came back blank.** `nemotron-nano-9b-v2-japanese` is a hybrid
   **reasoning** model; `generate_synopsis` spent the whole budget "thinking".
   Fixed: `"think": false` in the synopsis payload (ignored by non-reasoning
   models) + `SYNOPSIS_TIMEOUT_SECS` 90→180 for cold 9B loads.

The same run surfaced the design flaw addressed below: **`trigram` can't match
1–2 character CJK queries**, and 2-char kanji compounds are the common case.
Tasks 11–13 implement the app-side bigram approach (spec **Addendum A**),
replacing the trigram tokenizer for CJK — done now, before Chinese/Korean
inherit the flaw.

---

## Global Constraints (Addendum A — supersedes the trigram constraint)

- **CJK tokenization is app-side character bigrams**, not FTS5 `trigram`. CJK
  languages (`ja`, `zh`, `ko`) use `tokenizer: "unicode61"` + a `cjk_ngram: True`
  flag; text is bigram-expanded before indexing and queries bigram-expanded the
  same way. European (`es`/`fr`/`de`/`nl`) stay `unicode61` + `remove_diacritics`,
  `cjk_ngram` False.
- **Bigram floor: 2+ CJK chars match**; single-char CJK queries do not exact-match
  in Keyword mode (they surface via Both/semantic). Deliberate.
- Zero new dependencies; changing CJK installs requires a **reindex** (only
  Japanese exists, with test data).

---

### Task 11: CJK bigram segmentation helper + `cjk_ngram` flag

**Files:**
- Create: `cjk.py`
- Modify: `lang_models.py` (`ja` entry: `tokenizer` → `"unicode61"`, add `cjk_ngram: True`; `en` and future European entries: `cjk_ngram: False`)
- Test: `test_cjk.py`

**Interfaces:**
- Produces:
  - `cjk.cjk_segment(text: str) -> str` — replaces each run of ≥2 CJK characters with space-joined overlapping bigrams; non-CJK spans and lone CJK chars pass through; CJK runs are space-delimited from neighbours. Used identically at index and query time.
  - `LANG_MODELS[...]["cjk_ngram"]: bool` — True for CJK languages.

- [ ] **Step 1: Write the failing test**

```python
# test_cjk.py
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
    # ASCII untouched; CJK run expanded; boundary whitespace collapses on split
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test_cjk.py -v`
Expected: FAIL — `No module named 'cjk'` / missing `cjk_ngram`.

- [ ] **Step 3: Implement**

```python
# cjk.py
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""App-side CJK segmentation: expand runs of CJK characters into overlapping
character bigrams so a whitespace tokenizer (unicode61) can match 2+ char CJK
queries. Used identically at index time and query time."""
import re

# Hiragana/Katakana, CJK Unified (+ Ext A), CJK Compatibility, Hangul syllables.
_CJK_RUN = re.compile(r'[぀-ヿ㐀-鿿豈-﫿가-힣]+')


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
```

In `lang_models.py`, set `ja`'s `tokenizer` to `"unicode61"`, add `"cjk_ngram": True`; add `"cjk_ngram": False` to `en` (and document that European rows also set False).

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest test_cjk.py test_lang_models.py -v`
Expected: PASS. (Update `test_lang_models.py::test_ja_stack_matches_spec` which currently asserts `tokenizer == "trigram"` → `"unicode61"` and add `cjk_ngram is True`.)

- [ ] **Step 5: Commit**

```bash
git add cjk.py lang_models.py test_cjk.py test_lang_models.py
git commit -m "feat(i18n): app-side CJK bigram segmentation + cjk_ngram flag"
```

---

### Task 12: Wire bigram segmentation into index + query paths

**Files:**
- Modify: `docubrowse_db.py` (`init_db` tokenizer clause: CJK now → `unicode61`, driven by `resolve(lang)["tokenizer"]` which Task 11 changed; no trigram branch needed for CJK)
- Modify: `scan_docs.py` (before the `doc_fts` insert at ~820: segment the FTS field values when the active language has `cjk_ngram`)
- Modify: `doc_search.py` (`_keyword_scores` / FTS `MATCH` builder: segment the query when `cjk_ngram`)
- Test: `test_cjk_search.py`

**Interfaces:**
- Consumes: `cjk.cjk_segment` (Task 11), `resolve`/`config_lang` (existing), `_process_lang()` (existing).
- Produces: index-time and query-time segmentation gated on `resolve(active_lang)["cjk_ngram"]`. A module-level `_CJK = resolve(_process_lang()).get("cjk_ngram", False)` in `scan_docs.py`/`doc_search.py` mirrors how `_ACTIVE_LANG` is resolved.

Segment the **text-bearing** FTS columns only (`title`, `subject`, `description`, `content_snippet`, `tags`) — not `name`/`author` (filenames/names shouldn't be bigrammed). Do it in a small local helper so index and query use the exact same transform.

- [ ] **Step 1: Write the failing test (end-to-end via get_db + a real MATCH)**

```python
# test_cjk_search.py
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""2-char CJK keyword queries match end-to-end. Run: python3 -m pytest test_cjk_search.py -v"""
import tempfile, sqlite3
from pathlib import Path
import docubrowse_db
from cjk import cjk_segment


def test_two_char_cjk_query_matches(monkeypatch):
    monkeypatch.setenv("DOCUBROWSE_LANG", "ja")
    docubrowse_db._default_lang = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "cjk.db")
            conn = docubrowse_db.get_db(db)          # unicode61 for ja now
            # Index a segmented snippet, exactly as the scanner will:
            snippet = cjk_segment("リンゴの栽培と品種について")
            conn.execute(
                "INSERT INTO doc_fts(rowid, name, title, author, subject, description, content_snippet, tags) "
                "VALUES (1,'','', '', '', '', ?, '')", (snippet,))
            # Query '栽培' (2-char) segmented the same way must hit:
            q = cjk_segment("栽培")
            n = conn.execute(
                "SELECT count(*) FROM doc_fts WHERE doc_fts MATCH ?", (f'"{q}"',)).fetchone()[0]
            conn.close()
            docubrowse_db._initialized_paths.discard(db)
        assert n == 1
    finally:
        docubrowse_db._default_lang = None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test_cjk_search.py -v`
Expected: FAIL until the tokenizer is `unicode61` for ja (Task 11) AND the snippet is segmented (this test segments inline; the wiring in scan/search is what Steps 3–4 deliver for the real paths).

- [ ] **Step 3: Segment at index time**

In `scan_docs.py`, just before building the `doc_fts` insert (~line 820), when the active language has `cjk_ngram`, replace each text-bearing field value `v` with `cjk_segment(v)`. Compute the flag once at module load (mirror `_ACTIVE_LANG`). Leave `name`/`author` unsegmented.

- [ ] **Step 4: Segment at query time**

In `doc_search.py`'s keyword path (`_keyword_scores`, where the FTS `MATCH` string is built from the user query), when `cjk_ngram` is active, run the query through `cjk_segment` **before** the existing tokenize/quote/prefix logic, so each bigram becomes a matched term. Non-CJK queries are unaffected (segment is a no-op on ASCII).

- [ ] **Step 5: Confirm tokenizer clause**

`docubrowse_db.py` already derives the clause from `resolve(lang)["tokenizer"]`. Since Task 11 set `ja`'s tokenizer to `"unicode61"`, CJK installs now create `doc_fts` with `unicode61 remove_diacritics 2` — no trigram branch. Remove the now-dead `"trigram"` mapping only if nothing else references it (grep first).

- [ ] **Step 6: Run tests + live check**

Run: `python3 -m pytest test_cjk_search.py test_cjk.py test_fts_tokenizer.py test_lang_models.py -v`
Then live: rebuild a `lang=ja` scratch DB from a JP fixture and confirm Keyword search on `栽培`/`品種` (2-char) now returns the doc, English keyword search unchanged.

- [ ] **Step 7: Commit**

```bash
git add docubrowse_db.py scan_docs.py doc_search.py test_cjk_search.py
git commit -m "feat(i18n): index + query CJK text via bigram segmentation"
```

---

### Task 13: Docs, DECISIONS, reindex note

**Files:**
- Modify: `README.md` / `EndUser_docs/Admin_Guide.md` (note CJK keyword uses bigram segmentation; 2-char minimum; single-char via Both/semantic)
- Modify: `status_docs/DECISIONS.md` (+ Enterprise copy) — record the trigram→bigram supersession and rationale
- Modify: `test_fts_tokenizer.py` — drop/adjust the trigram assertions that Task 11/12 obsolete (JP is now `unicode61`, not `trigram`)

- [ ] **Step 1: Reconcile the obsolete trigram tests**

`test_fts_tokenizer.py::test_ja_uses_trigram` and `test_ja_substring_match_on_cjk` assert `trigram`. Replace them with the `unicode61`-for-ja expectation and let `test_cjk_search.py` own the JP-match assertion. Run `python3 -m pytest test_fts_tokenizer.py test_cjk_search.py -v` → PASS.

- [ ] **Step 2: DECISIONS + docs**

Add a DECISIONS.md entry: "CJK keyword search = app-side character bigrams (not trigram, not a morphological segmenter); 2-char floor; rationale = 2-char 熟語 dominance + zero-dependency + uniform ja/zh/ko." Mirror to the Enterprise copy. Note the reindex requirement for existing CJK installs in the Admin Guide.

- [ ] **Step 3: Commit**

```bash
git add README.md EndUser_docs/Admin_Guide.md status_docs/DECISIONS.md test_fts_tokenizer.py
git commit -m "docs(i18n): CJK bigram segmentation supersedes trigram (DECISIONS + guides)"
```

---

## Self-Review

**Spec coverage:**
- §3 per-install single language → Global Constraints + Task 1 (fallback), Task 9 (config).
- §3 one package / bundled locales → Task 10 packaging.
- §3 UI `t()` locale JSON → Tasks 5, 7.
- §4 `LANG_MODELS` table (embed/synopsis/prompt/tokenizer/stopwords) → Task 1; consumed by Tasks 2, 3, 4, 6, 8.
- §5.1 config `lang` + first-run/upgrade → Task 9.
- §5.2 model resolution + prompt from table → Task 2.
- §5.3 UI i18n layer → Tasks 5, 7.
- §5.4 tokenizer per lang → Task 3; stopwords → Task 6; hide index bar for CJK → Task 7.
- §5.5 Settings switcher + provisioning + rebuild → Task 8.
- §6 data flows (fresh/upgrade/switch) → Tasks 9, 8.
- §7 deferred (My Number, kana index, mixed corpora, extra langs) → not implemented by design; noted in Task 10 docs.
- §8 testing → each task carries its tests; locale parity (Task 5), JP keyword (Task 3), JP semantic/synopsis are exercised via the browser/live checks in Task 7 + manual Ollama runs (bge-m3/nemotron pulls happen at provisioning).

**Note on JP semantic + synopsis live tests:** Task 3 proves trigram keyword; bge-m3 embedding quality and nemotron JP synopsis are validated by live smoke checks during Task 7/Task 8 browser verification against a `lang=ja` copy DB (they require the models pulled locally — nemotron is already installed; bge-m3 pulls on first `ja` provisioning). No automated unit test asserts embedding quality (nondeterministic); this matches how the repo already treats semantic/synopsis (behavior/shape, not exact output).

**Placeholder scan:** no TBD/TODO; every code step has real code. The `_EN_SYNOPSIS_PROMPT` in Task 1 is explicitly reconciled byte-for-byte with the existing prompt in Task 2 Step 3.

**Type consistency:** `resolve()`, `lang_from_config()`, `required_models()`, `rebuild_required()`, `strip_stopwords(text, lang)`, `init_db(db_path, lang)`, `resolve_or_prompt_lang(config, is_tty)`, `load_locale()`/`load_locale`+`/api/config` `lang`/`locale`, `t(key)`, `HAS_LETTER_INDEX` — names used consistently across tasks.

---

## Execution Handoff

(Placed after user reviews the plan.)
