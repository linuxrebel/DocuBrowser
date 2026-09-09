# DocuBrowse Internationalization (i18n) — Design

**Date:** 2026-09-09
**Status:** Design — approved shape, pending spec review
**First target language:** Japanese (`ja`)
**Planned soon:** Spanish, French, German, Dutch, Korean, Chinese (order TBD)

---

## 1. Goal

Make DocuBrowse usable end-to-end in languages other than English: a localized
UI **and** language-appropriate AI (semantic embeddings, keyword tokenization,
document synopsis). First delivery is Japanese; the design must make adding each
further language a data change, not a code change.

## 2. Core assumption

**One DocuBrowse install serves one language, and its corpus is ~99.9% documents
in that language.** This is a deliberate, load-bearing simplification:

- No per-document language detection.
- No mixed-language corpora (a German instance is not expected to search
  Japanese documents well).
- One embedding model, one summary model, one FTS tokenizer, one locale per
  install.

Switching an instance's language changes the UI and the models that
interpret/search the corpus; it does **not** translate the user's documents.

## 3. Key decisions

| Decision | Choice | Rationale |
|---|---|---|
| Language granularity | Per-install single language | §2 assumption; simplest robust model |
| Packaging | **One** package, all locales bundled | Code is identical across languages; models pulled from Ollama at runtime, never bundled. Separate packages = combinatorial build/maintenance for no gain |
| UI strings | Config-driven client `t(key)` + per-language locale JSON | Standard i18n; avoids N localized HTML copies or per-language JS branches |
| Model config | Data-driven `LANG_MODELS` table | Adding a language = one row + one locale file |
| JP embedder | `bge-m3` (multilingual, ~2.2GB, 1024-dim) | Strong multilingual incl. Japanese; well supported on Ollama |
| JP summary | `fuukeidaisuki/nvidia-nemotron-nano-9b-v2-japanese` | Already validated by the user for JP summaries |
| JP keyword tokenizer | FTS5 `trigram` | Japanese has no word spaces; default `unicode61` won't segment it. Built-in, no dependency |
| Model provisioning | Lazy pull on first-run / language-switch | Nothing pre-bundled; pull only the active language's set |

## 4. The per-language table

A single data structure (new `lang_models.py`, or a config block) is the source
of truth. Everything language-specific reads from it by the active `lang`.

```
LANG_MODELS = {
  "en": { embed: "nomic-embed-text",  synopsis: "dolphin3:latest",
          synopsis_prompt: <EN prompt>, tokenizer: "unicode61", stopwords: <EN set> },
  "ja": { embed: "bge-m3",            synopsis: "fuukeidaisuki/nvidia-nemotron-nano-9b-v2-japanese:latest",
          synopsis_prompt: <JA prompt>, tokenizer: "trigram",  stopwords: <JA particles / none> },
  # es/fr/de/nl → unicode61 (+ remove_diacritics); ko/zh → trigram; added later
}
```

Tokenizer split by language family:
- **CJK** (ja, zh, ko) → `trigram`
- **European** (es, fr, de, nl) → `unicode61` with `remove_diacritics`

Each language also owns: an embedder, a summary model, a summary prompt, a
stopword list, and a `locales/<lang>.json`.

## 5. Components

### 5.1 Language selection & config
- New `lang` key in `docubrowse.config` (default `en`).
- **Fresh install / first-run only:** prompt for language, write `lang`, pull
  that language's model set.
- **Upgrade:** read existing `lang`, keep it, pull models only if missing. Never
  re-prompt. (Matches current `/opt` upgrade config-preservation.)

### 5.2 Model resolution (replaces hardcoded constants)
- Today: `EMBEDDING_MODEL="nomic-embed-text"`, `SYNOPSIS_MODEL="dolphin3:latest"`
  are module constants in `doc_search.py` and `embed_docs.py`; required-models
  list is hardcoded in `ensure_ollama.py`.
- Change: all three resolve from `LANG_MODELS[lang]`. `ensure_ollama`'s required
  set becomes the active language's `{embed, synopsis}`.
- The synopsis **prompt** also comes from the table (JP-authored for `ja`).

### 5.3 UI i18n layer
- `locales/en.json`, `locales/ja.json` (all bundled; tiny).
- `/api/config` returns the active locale dict alongside existing config.
- `index.html` and `settings.html` gain a small `t(key)` helper; every
  hardcoded label — static HTML (`Keyword`/`Semantic`/`Both`, `Settings`,
  search placeholder) and JS template literals (`All Documents`,
  `Search Results`, `showing … of …`, button titles, toasts) — becomes a key.
- Emoji icons (🙈 📋 🗑 👀) are language-neutral and unchanged.

### 5.4 Search internals
- `doc_fts` is created with the language's tokenizer at DB init
  (`tokenize='trigram'` for CJK). FTS is a contentless derived index; the
  existing drop/recreate/repopulate migration path handles a tokenizer change.
- `strip_stopwords` (currently EN articles + FANBOYS, used for semantic query
  cleaning) becomes locale-aware from the table (JP: particle list or no-op in
  v1).
- The A–Z / 0–9 index bar is **hidden for CJK languages** in v1 (kana/reading-
  or pinyin-based index deferred).

### 5.5 Settings language switcher
Settings gains a Language dropdown (populated from `LANG_MODELS`). On switch:
1. write `lang` to config;
2. `ensure_ollama` pulls that language's model set on demand, with progress;
3. UI strings swap live (locale JSON reloads — instant);
4. because embedder **and** tokenizer change, warn the user and trigger a
   **re-embed + FTS rebuild** of the corpus. UI text is instant; search quality
   follows once the rebuild completes.

First-run and Settings use the **same** provisioning path — first-run is the
switcher invoked once with no prior `lang`.

## 6. Data flows

- **Fresh install:** installer asks language → writes `lang` → pulls
  `{embed, synopsis}` for that language → user scans corpus → embeds with the
  language embedder, FTS built with the language tokenizer.
- **Upgrade:** read `lang` from config → pull only missing models → no re-embed
  unless the language (hence embedder) changed.
- **Language switch (Settings):** write `lang` → pull models → live UI swap →
  re-embed + FTS rebuild.

## 7. Explicitly deferred (out of scope for the Japanese v1)

- Japanese **My Number** (and other locale) PII detection — US patterns remain
  for now.
- Kana / reading-based (and pinyin) index bar for CJK.
- Per-document / mixed-language corpora.
- Languages beyond `en` and `ja` (the table + locale mechanism make these
  additive; each still needs its embedder/summary/prompt/stopwords chosen and a
  locale file).
- RTL languages (none in the planned set).

## 8. Testing

- **Locale key parity:** every key in `en.json` exists in each other locale
  (fail on missing/extra keys).
- **JP keyword:** a Japanese fixture indexed with `trigram` returns the expected
  hit for a substring query that `unicode61` would miss.
- **JP semantic:** bge-m3 embed of a JP fixture + cosine against a JP query
  clears the semantic floor.
- **JP synopsis:** nemotron JP smoke test produces a non-empty JP summary from a
  JP fixture.
- **Model resolution:** `LANG_MODELS[lang]` drives the constants,
  `ensure_ollama` required set, and prompt for `en` and `ja`.
- **Install flow:** fresh install prompts + writes correct `lang` + pulls
  correct models; upgrade preserves `lang` and does not re-prompt.
- **Language switch:** config updated, models pulled, locale served, re-embed +
  FTS rebuild triggered.
- Existing English behavior unchanged when `lang=en` (regression guard).

## 9. Files touched (anticipated)

- New: `lang_models.py`, `locales/en.json`, `locales/ja.json`.
- `docubrowse_db.py` — tokenizer from language at FTS create/migrate.
- `doc_search.py`, `embed_docs.py` — model constants → `LANG_MODELS`;
  `strip_stopwords` locale-aware; `/api/config` returns locale.
- `ensure_ollama.py` — required models from active language.
- `index.html`, `settings.html` — `t()` layer + language dropdown + hide index
  bar for CJK.
- `docubrowser.py` / `install.sh` (+ Windows/macOS installers) — first-run
  language prompt; upgrade reads existing `lang`.
- Docs: README/INSTALL/User+Admin guides note language support; `DECISIONS.md`
  entries (keep FOSS + Enterprise in sync).

## 10. Rollout

Japanese ships first as the reference implementation. Each subsequent language
(es/fr/de/nl/ko/zh) is a follow-on that adds a `LANG_MODELS` row, a locale file,
and its chosen models — no new architecture.
