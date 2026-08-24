# Deep Links — implementation checklist

**Date:** 2026-08-23
**Design:** [2026-08-21-deep-links-design.md](2026-08-21-deep-links-design.md)
**Target release:** v1.0.4
**Approach:** bottom-up, TDD at each layer. Each step's tests pass before the next starts.

Phase-1 formats: **PDF, TXT, DOCX, RTF, ODT**. Deferred (20%): in-memory cache; remaining prose formats (MD, HTML, EPUB/MOBI/AZW*, EML, LaTeX/reST/AsciiDoc, DjVu, config-ish text).

---

## Step 1 — `deep_links.py`, keyword mode (pure, no server, no AI) — DONE

- [x] "Locate" extraction path preserving structure + location for phase-1 formats:
  - [x] PDF → iterate `pdf.pages`, carry page number → `location = "p. N"` (empty pages skipped)
  - [x] TXT → split lines, track line number → `location = "line N"`
  - [x] DOCX / ODT → split by paragraph, carry index → `location = "section N"`; RTF has no pages → line-based (`location = "line N"`)
- [x] Keyword ranking: passages containing query terms (whole-word, case-insensitive), ranked by match count. (Proximity refinement deferred — see note below.)
- [x] `sample` = 8–10 words around the best match; `excerpt` = the matched passage; match span (`match_start`/`match_end`) returned for the UI to `<mark>`.
- [x] `max_passages` cap (default 200); set `truncated=True` when hit.
- [x] Skip pages/sections that extract to nothing; whole-empty doc → `passages: []`.
- [x] Non-prose (by extension: XLSX/ODS/CSV/TSV, PPTX/ODP, VSDX/VSD*/VDX/SVG) → `{"unsupported": True, "reason": ...}`.
- [x] `test_deep_links.py`: keyword ranking over PDF/TXT/DOCX/RTF/ODT; correct location labels (page vs line vs section); non-prose → `unsupported`; empty doc → `passages: []`; truncation cap.
- [x] Tests pass (8 checks); pylint 10.00/10 on both files.

Notes / small deferrals from Step 1:
- Ranking is match-count only for now; proximity weighting can be added when tuning against the real corpus.
- `excerpt` is the whole passage (paragraph/line/page-paragraph); the ±1–2 lines of surrounding context for line-based docs can be widened during UI tuning.

## Step 2 — `deep_links.py`, semantic mode (needs Ollama) — DONE

- [x] Batched embed of query + all passages via an injected `embed_fn` (list[str] -> list[vector]); cosine rank. `deep_links.py` stays dependency-free — the real Ollama-backed `embed_fn` is wired in from `doc_search` in Step 3 (avoids a circular import).
- [x] Sub-unit (sentence) re-rank of each returned passage to pick the highlight span; `sample` = first ~10 words of that sentence.
- [x] Extend `test_deep_links.py`: semantic ranking with a deterministic fake embedder (no live model), asserts passage selection + nearest-sentence highlight span.
- [x] Tests pass (9 checks); pylint 10.00/10.
- [x] Verified live against Ollama (`nomic-embed-text`): query "nuclear power plant safety" (no literal overlap) ranks the reactor passage top (cos 0.543).

Note: `embed_fn` is dependency-injected so unit tests need no Ollama. Step 3 builds the real batch embedder (POST `/api/embed` with `input` as a list) from `doc_search`'s `OLLAMA_HOST` / `EMBEDDING_MODEL` and passes it in.

## Step 3 — API endpoint `GET /api/deep-links` (in `doc_search.py`) — DONE

- [x] Route: `GET /api/deep-links?path=<enc>&q=<query>&mode=keyword|semantic` (registered in the GET `with_query` table).
- [x] Read-only GET, no CSRF (same class as `/api/search`).
- [x] Validate `path` is in the document index (same guard as `/api/open` / `/api/synopsis`) + on-disk existence check before reading the file.
- [x] Response envelope: `{"ok": true, "passages": [...], "truncated": bool}` / `{"ok": true, "unsupported": true}` / `{"ok": false, "error": ...}`.
- [x] `embed_texts()` added to `doc_search.py` — one batched `/api/embed` call for query + all passages; passed as `embed_fn` only for semantic mode.
- [x] Extend `test_features.py`: `check_deep_links()` — keyword envelope + passage shape, semantic envelope (when embeddings present), `unsupported` for a spreadsheet. Self-skipping, DB-independent.
- [x] Verified: handler exercised through the real code path (get_db guard → locate_passages → live `embed_texts` against Ollama) via a direct-call harness — keyword `line 2`, semantic `line 2` cos 0.537, xlsx `unsupported`, unknown-path rejected. pylint clean on new code (`main()`'s pre-existing R0912 left untouched).

Note: the `test_features.py` HTTP suite is operator-run against a live server + real DB (per `status_docs/TESTING.md`); it was not run in-session because the server tooling wouldn't start in the sandbox. The handler itself was verified directly through its real dependencies.

## Step 4 — UI (`index.html`) — DONE

- [x] `Deep Links` button right of `Open`, rendered only when `currentQuery` is non-empty. Distinct `--accent2` styling.
- [x] Modal mirrors the synopsis modal; loading state "Just a moment as we find your passage…".
- [x] Fetch `/api/deep-links` with the card's path, current query, active search mode. **Mode mapping:** semantic search → `semantic`; keyword **or `both`** → `keyword` (no in-modal toggle). See note below on `both`.
- [x] Passage list: one row per passage — sample + location label (`page N` / `line N` / `section N`); truncation note when `truncated`.
- [x] Excerpt view: excerpt with the match span in yellow `<mark>`; title *"This passage comes from {page N/line N/section N} of the document. Return to the main page to open and read more."*; **Open full document** → `/api/open`.
- [x] Close control (X upper-right + Close button); **Back** returns from excerpt to the passage list.
- [x] No-results message on empty; non-prose message + [Open in reader] / [Back]; error envelope surfaced.
- [x] Highlight built from the returned match span (not query injection); every document-text slice escaped via `esc()`. Footer buttons wired programmatically (no data-in-HTML), so no string-injection surface.
- [x] Verified visually: served `index.html` statically, stubbed `/api/deep-links`, drove the real modal code — passage list, excerpt+highlight, templated title, and the card button (right of Open, gated on query) all render correctly. JS passes `node --check`.

**Decision — `both` mode:** the design specified mode locked to the originating search, but search offers three modes (keyword / semantic / **both**), and `both` isn't a valid Deep Links mode. Chose `both` → `keyword` (instant, no GPU). Revisit if semantic-for-both proves more useful.

## Wrap-up

- [x] QA run (local): pylint 9.99/10 (only pre-existing `main()` R0912), `test_deep_links.py` 9/9, endpoint handler + live Ollama, `index.html` JS `node --check`, `test_backup_restore.py` regression — all pass. The `test_features.py` HTTP suite is operator-run against a live server.
- [x] Committed on `development` (4 commits, dc3d455 → e24a211). **Local only — not pushed, not merged to `main`** (per instruction to keep local).
- [x] `both` search-mode decision recorded in `status_docs/DECISIONS.md` (D-16).

Remaining (operator / when ready to release):
- [ ] Run `python3 test_features.py` against a live server (E2E `check_deep_links`).
- [ ] Push `development` + merge `--ff-only` to `main` when you decide to ship.
- [ ] Sync the D-16 entry into the Enterprise repo's `status_docs/DECISIONS.md`.
