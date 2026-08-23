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

## Step 2 — `deep_links.py`, semantic mode (needs Ollama)

- [ ] `embed_text(query)` + one batched embed of all passages; cosine rank.
- [ ] Sub-unit (sentence/phrase) re-rank of the winning passage to pick the highlight span; `sample` drawn from that sub-unit.
- [ ] Extend `test_deep_links.py`: semantic ranking over a small sample.
- [ ] Tests pass.

## Step 3 — API endpoint `GET /api/deep-links` (in `doc_search.py`)

- [ ] Route: `GET /api/deep-links?path=<enc>&q=<query>&mode=keyword|semantic`.
- [ ] Read-only GET, no CSRF (same class as `/api/search`).
- [ ] Validate `path` is in the document index (same guard as `/api/open` / `/api/synopsis`) before touching the file.
- [ ] Response envelope: `{"ok": true, "passages": [...], "truncated": bool}` / `{"ok": true, "unsupported": true}` / error envelope.
- [ ] Register alongside the other GET handlers.
- [ ] Extend `test_features.py`: passages for a prose doc; `unsupported` for an XLSX; against the running server.
- [ ] Tests pass.

## Step 4 — UI (`index.html`)

- [ ] `Deep Links` button right of `Open` (index.html ~789), rendered only when the query is non-empty.
- [ ] Modal mirrors the synopsis modal; loading state "Just a moment as we find your passage…".
- [ ] Fetch `/api/deep-links` with the card's path, current query, active search mode (mode locked to the originating search — no toggle).
- [ ] Passage list: one row per passage — 8–10 word sample + location label.
- [ ] Excerpt view: reveal excerpt with snippet in yellow `<mark>`; title *"This passage comes from page (X) of the document. Return to the main page to open and read more."* with unit templated off `location` (page/line/section); **Open full document** → `/api/open`.
- [ ] Close control (X upper-right / close button).
- [ ] No-results message on empty; non-prose message + [Open in reader] / [Back].
- [ ] Build highlight from the returned match span, not by injecting the query (XSS guard); escape document text for HTML.

## Wrap-up

- [ ] Run the QA agent after code changes, before calling it ready (project rule).
- [ ] Commit on `development`, push; merge `--ff-only` to `main`, push; back to `development`.
