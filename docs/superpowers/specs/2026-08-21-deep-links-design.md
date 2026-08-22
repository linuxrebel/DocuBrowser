# Deep Links — in-document passage search (design)

**Date:** 2026-08-21
**Status:** Approved design; not yet implemented
**Target release:** v1.0.4
**Related:** [[DECISIONS]] D-11 (chunk-level semantic search) — see "Future work"

## Summary

Add a **Deep Links** feature to search results. Today, semantic search is
document-level (one embedding per document) and keyword search (FTS5) is also
document-level — a result tells you *which* document matches, never *where*
inside it. Deep Links lets a user, from any keyword or semantic result, see the
top matching passages *within* that document, jump to one, and read it with the
matching snippet highlighted.

The whole feature is computed **on demand** at click time. There is **no schema
change, no reindex, no new dependency.** It reuses the existing extractors, the
existing `embed_text()` helper, and the existing modal/opener UI patterns.

## User requirements (verbatim intent)

1. On a semantic **or** keyword search result, add a button to the right of
   **Open** called **Deep Links**.
2. Deep Links lists the place(s) in the document related to the search, each
   with an 8–10 word sample.
3. Each sample is clickable to go to that place in the document.
4. If we can't open the exact line, opening/showing the page the snippet came
   from is enough. If we fall back to just the page, give a line number or some
   other indicator.
5. If possible, render the page ourselves and highlight the snippet (yellow),
   so the user just reads the passage without zooming.

## Key UX decisions (agreed in brainstorming)

- **We render extracted text, not the original layout.** The "highlighted page"
  is the document's *extracted text* with the matched snippet wrapped in a
  yellow `<mark>` — not a faithful PDF/Office rendering. This sidesteps in-app
  PDF/Office rendering entirely (no PDF.js, no server-side conversion).
- **Excerpt size:** show the matched section **plus the paragraph it sits in**;
  for non-paragraph documents (e.g. a poem) show ±1–2 lines of context.
- **Loading state:** while the passages are being computed, show
  **"Just a moment as we find your passage…"**.
- **"Open full document"** button in the excerpt view → the existing external
  open (`/api/open`).
- **Prose vs non-prose split:**
  - **Prose formats** (extracted text reads as running text) → render + highlight
    in-app. PDF, TXT, MD, HTML, DOCX, ODT, EPUB/MOBI/AZW*, RTF, EML, LaTeX/reST/
    AsciiDoc, DjVu, and config-ish text.
  - **Non-prose formats** (extracted text is tabular/fragmented) → **do not**
    render. Show: *"Due to the document format and technical limitations, we
    can't display this document outside its reader."* with **[Open in reader]**
    and **[Back]** buttons. Applies to spreadsheets (XLSX/ODS/CSV/TSV),
    presentations (PPTX/ODP), and diagrams (Visio VSDX/VSD*, draw.io, VDX, SVG).

## Chosen approach: on-demand (Approach A)

Nothing is precomputed. When **Deep Links** is clicked, for that one document:

- **Keyword mode** → re-extract the doc's text, find the query terms, rank the
  passages that contain them by frequency/proximity. Instant, no AI.
- **Semantic mode** → re-extract, split into passages, embed the query + all
  passages via Ollama (one batched `/api/embed` call), cosine-rank. The
  "Just a moment…" message covers the few-second wait on the GPU.

**Why on-demand over precomputed (D-11):** no DB migration, no re-embedding
8,300+ documents, no ~30–40× DB growth — so it fits a soon-ish v1.0.4. Passages
are always fresh. The cost is per-click latency for semantic on large documents,
mitigated by the loading message, a batched embed call, an in-memory cache, and
a passage cap. If click latency ever becomes a problem, precomputed chunk
embeddings (D-11) can be added later behind the *same UI and API* as a pure
speed optimization — user-facing behavior is identical.

## Design

### 1. Passage-location engine — new module `deep_links.py`

Pure functions, independently testable, no server/UI dependencies.

- `locate_passages(path, query, mode, *, max_passages) -> dict`
  - Returns either `{"unsupported": True, "reason": ...}` for non-prose
    formats, or `{"passages": [Passage, ...], "truncated": bool}`.
  - A `Passage` is `{sample, excerpt, location, score}` where:
    - `sample` — 8–10 words around the best match in the passage.
    - `excerpt` — the matched section + its surrounding paragraph (±1–2 lines
      for non-paragraph docs), with the matched snippet marked for highlight
      (the API returns the excerpt plus the match span; the UI draws the
      `<mark>`).
    - `location` — human label: `"p. 12"` (PDF), `"line 340"` (plain text),
      `"section 3"` / paragraph index (DOCX/ODT/EPUB, which lack real pages).
    - `score` — rank score (term score for keyword, cosine for semantic).
- **Re-extraction with location:** a "locate" extraction path that preserves
  structure rather than the flat 5000-char blob used for indexing:
  - PDF → iterate `pdf.pages`, carry the page number with each passage.
  - Plain text / HTML / MD → split into paragraphs/lines, track line numbers.
  - DOCX / ODT / EPUB → split by paragraph/section, carry the index.
  - Cap work at the first `max_passages` (or first N pages) to bound latency;
    set `truncated=True` when the cap is hit.
- **Ranking:**
  - keyword → passages containing query terms, ranked by term frequency and
    proximity; tokenization consistent with how the UI query is entered.
  - semantic → `embed_text(query)` + one batched embed of all passages; cosine.

### 2. API endpoint

`GET /api/deep-links?path=<enc>&q=<query>&mode=keyword|semantic`

- Read-only GET, **no CSRF** (same class as `/api/search`).
- Validates `path` is in the document index (same guard as `/api/open` /
  `/api/synopsis`) before touching the file.
- Response: `{"ok": true, "passages": [...], "truncated": bool}` or
  `{"ok": true, "unsupported": true}` for non-prose, or an error envelope.
- Registered alongside the other GET handlers in `doc_search.py`.

### 3. UI (index.html)

- **Button:** add a `Deep Links` button in the card actions, right of `Open`
  (index.html ~789), rendered only when the current query is non-empty.
- **Modal:** mirror the existing synopsis modal. On open, show
  "Just a moment as we find your passage…", then fetch `/api/deep-links` with
  the card's path, the current query, and the active search mode.
- **Passage list:** one row per passage — the 8–10 word sample + location label.
- **Excerpt view:** clicking a row reveals the excerpt with the snippet in a
  yellow `<mark>`, plus an **"Open full document"** button (calls `/api/open`).
- **Non-prose / unsupported:** show the fixed message + **[Open in reader]**
  (→ `/api/open`) and **[Back]** (→ result list).
- Escape document text for HTML; build the highlight from the returned match
  span, not by string-injecting the query, to avoid an XSS vector.

### 4. Performance & limits

- One batched `/api/embed` call for all passages of a document.
- In-memory cache keyed by `(path, mtime, query, mode)`; repeat clicks are
  instant. Bounded size; evict oldest.
- `max_passages` cap (tunable; start ~200) so a giant PDF can't hang a request;
  surface `truncated` in the UI.

### 5. Testing

- `test_deep_links.py` (unit, no server): keyword + semantic ranking over a
  small sample PDF and a text doc; non-prose format returns `unsupported`;
  location labels are correct (page for PDF, line for text).
- Extend `test_features.py`: `/api/deep-links` returns passages for a prose doc
  and `unsupported` for an XLSX, against the running server.

## Non-goals / scope guardrails

- No database schema change, no reindex, no new runtime dependency.
- No faithful PDF/Office rendering; we render extracted text only.
- No in-app rendering of spreadsheets, presentations, or diagrams — they get
  the fallback message.
- No change to the primary `/api/search` ranking; Deep Links is additive.

## Future work

- **Precomputed chunk embeddings (D-11):** store per-passage embeddings +
  page/offset in a new table so semantic Deep Links are instant on large
  documents. Slots in behind the same API/UI as a performance optimization;
  costs a full re-embed and ~30–40× embedding storage. Deferred until on-demand
  latency proves insufficient.

## Open items to settle during implementation

- Exact passage/paragraph splitting heuristic per format (paragraph on blank
  line vs. sentence windows); pick during TDD against real sample docs.
- `max_passages` default and cache size — tune against the real corpus.
- Whether to show a small page/line label in the passage-list rows as well as
  the excerpt view (leaning yes).
