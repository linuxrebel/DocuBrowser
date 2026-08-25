# Deep Links — in-document passage search (design)

**Date:** 2026-08-21
**Status:** SHIPPED in v1.2.0 — see "Shipped behavior & post-release tuning" below for how the running code differs from this original design.
**Target release:** ~~v1.0.4~~ shipped v1.2.0
**Related:** [[DECISIONS]] D-11 (chunk-level semantic search), D-18 (semantic tuning), D-19 (search-on-Enter)

## Shipped behavior & post-release tuning (2026-08-25)

The feature shipped in v1.2.0. Behavior differs from the original design in a few
places; the code is authoritative. Current state:

- **Format coverage** is far beyond the phase-1 set: 60+ prose formats via
  `_UNIT_ITERATORS` in `deep_links.py` (txt/code, markup/HTML/XML, docx, rtf,
  odt/ott, eml, pdf, epub, mobi/azw*, djvu). Non-prose → `{unsupported:true}`.
- **Semantic scan cap** `_SEMANTIC_SCAN_CAP=300` bounds the single `/api/embed`
  call. Without it, a 1500+ passage book embedded everything at once and blew the
  60 s socket timeout. (The original "cap at first max_passages" was applied after
  scoring, not before embedding — that was the bug.)
- **No per-passage sentence re-embed.** The design's sub-unit re-rank was removed
  (it was up to 200 extra Ollama calls per request — the dominant latency).
  Highlight now marks the query term when present, else the first sentence.
- **Semantic relevance floor** `_SEMANTIC_MIN_SIM=0.5`: passages below the cosine
  floor are dropped, so a query with no real match returns no passages instead of
  top-N noise. Calibrated on nomic-embed-text (real matches ~0.6-0.7, junk ~0.45).
- **Excerpt modal title** no longer says "Return to the main page…" (there's an
  "Open full document" button).
- **`both` search mode → keyword** Deep Links (no in-modal toggle).
- Related UX: main search fires on **Enter**, not as-you-type (D-19).
- **Open:** user-facing disclaimer copy for semantic search (fuzzy on short/rare
  tokens like names; finds concepts, not exact words).

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
    - **Phase 1 (80/20) — ship these text formats first:** **PDF, TXT, DOCX,
      RTF, ODT.** The remaining prose formats (MD, HTML, EPUB/MOBI/AZW*, EML,
      LaTeX/reST/AsciiDoc, DjVu, config-ish text) are back-burner — added in later
      passes behind the same API/UI. Until then they fall through to the same
      "no results" empty path, not a special message.
  - **Non-prose formats** (extracted text is tabular/fragmented) → **do not**
    render. Show: *"Due to the document format and technical limitations, we
    can't display this document outside its reader."* with **[Open in reader]**
    and **[Back]** buttons. Applies to spreadsheets (XLSX/ODS/CSV/TSV),
    presentations (PPTX/ODP), and diagrams (Visio VSDX/VSD*, draw.io, VDX, SVG).
  - **Prose/non-prose is decided by extension only** — no content sniffing.
    A scanned/image-only PDF still counts as prose by extension; the empty-text
    handling below covers the case where it yields no text.
- **Empty / unextractable text within a prose doc:** skip pages/sections that
  extract to nothing and rank whatever text remains. We do **not** judge document
  quality or show a "can't read this" message — a doc that yields no usable text
  simply produces zero passages, which the UI reports with the same "no results"
  message used for any empty result. (Example: a PDF that is just a photo of a
  face — its page(s) extract to nothing, so it yields no passages; no special
  message.)

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
  - Returns `{"unsupported": True, "reason": ...}` for non-prose formats
    (decided by extension), or `{"passages": [Passage, ...], "truncated": bool}`.
    Pages/sections that extract to nothing are skipped; a doc that yields nothing
    usable simply returns `passages: []` (no special "empty" state).
  - A `Passage` is `{sample, excerpt, location, score}` where:
    - `sample` — 8–10 words around the best match in the passage. In semantic
      mode there is no literal term, so the "best match" is the highest-scoring
      **sub-unit** (sentence/phrase/section) within the passage — see Ranking.
    - `excerpt` — enough of the document for the user to see *why* it was judged
      a match: the matched section + its surrounding paragraph (±1–2 lines for
      non-paragraph docs), with the matched snippet marked for highlight (the API
      returns the excerpt plus the match span; the UI draws the `<mark>`). For
      more, the user opens the full document. The excerpt is a reading view of
      our extracted text — it does **not** navigate the external reader to a
      line/page; `location` is an informational label only.
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
    To pick the highlight span, sub-rank the winning passage's sentences (or
    phrases/sections) by cosine against the query and `<mark>` the top sub-unit —
    i.e. mark the portion that actually sparked the match, not the whole passage.
    The `sample` is drawn from that same sub-unit.

### 2. API endpoint

`GET /api/deep-links?path=<enc>&q=<query>&mode=keyword|semantic`

- Read-only GET, **no CSRF** (same class as `/api/search`).
- Validates `path` is in the document index (same guard as `/api/open` /
  `/api/synopsis`) before touching the file.
- Response: `{"ok": true, "passages": [...], "truncated": bool}` (a doc with no
  usable text just returns `passages: []`), or `{"ok": true, "unsupported": true}`
  for non-prose (by extension), or an error envelope.
- Registered alongside the other GET handlers in `doc_search.py`.

### 3. UI (index.html)

- **Button:** add a `Deep Links` button in the card actions, right of `Open`
  (index.html ~789), rendered only when the current query is non-empty.
- **Modal:** mirror the existing synopsis modal. On open, show
  "Just a moment as we find your passage…", then fetch `/api/deep-links` with
  the card's path, the current query, and the active search mode. **The mode is
  locked to the search that produced the result** — no in-modal toggle. To search
  the other way, the user starts a new search from the top. The modal has a
  simple close control (X in the upper-right / close button).
- **Passage list:** one row per passage — the 8–10 word sample + location label.
- **Excerpt view:** clicking a row reveals the excerpt with the snippet in a
  yellow `<mark>`, plus an **"Open full document"** button (calls `/api/open`).
  - **Title:** *"This passage comes from page (X) of the document. Return to the
    main page to open and read more."* — where the unit is templated off
    `location`: "page 12" for PDF, "line 340" for plain text, "section 3" /
    paragraph index for DOCX/ODT/EPUB.
- **Non-prose / unsupported:** show the fixed message + **[Open in reader]**
  (→ `/api/open`) and **[Back]** (→ result list).
- **No passages found** (empty result, incl. a doc that extracted no text): show
  a single "no results" message. No document-quality judgment or can't-read text.
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

- **Expand format coverage (Phase 2+):** add the deferred prose formats — MD,
  HTML, EPUB/MOBI/AZW*, EML, LaTeX/reST/AsciiDoc, DjVu, config-ish text — behind
  the existing API/UI as extraction paths are added.
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
