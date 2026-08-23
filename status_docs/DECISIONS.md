# DocuBrowse — Decisions & Deferred Work

Tracks open decisions, deferred features, and known issues across both
the FOSS and Enterprise repos. Items are numbered for cross-reference;
resolved items keep their number.

---

# FOSS

## Open

### D-15: Docker deployment (experimental) — tracked on the `docker-experiment` branch
**Status:** Experimental, off mainline — reference only
**Priority:** Low
**Added:** 2026-08-22

A containerized deployment (distroless app + Ollama sidecar) is being tried on
the **`docker-experiment`** branch. It is **not yet viable**: Docker/OS
limitations plus DocuBrowse's security model mean opening a document in a
desktop app does not work from a browser-based container (headless server,
sandboxed browser). Current thinking is that Docker will only be viable as an
**Enterprise** deployment, since a working "open" needs the desktop client.

The full decision record, code, and `docker/README.md` live on that branch —
this is only a pointer. Not recommended for use; for experimentation only.

### D-103: v1.0.1 release ships a stale 1.0.0 .deb (issue #3)
**Status:** Superseded by the v1.0.2 release — all packages (deb included)
rebuilt from the fixed tree. A stopgap `1.0.1-2` deb was also built; the
v1.0.2 release replaces it. Still verify the correct deb is attached to the
release and notify gemlog on issue #3.
**Priority:** High
**Added:** 2026-08-19

Issue #3 (gemlog / Paul Evans, Linux Mint): `docubrowser start` crashes at
import with `ModuleNotFoundError: No module named 'visio_extractor'`
(`scan_docs.py:61`).

Root cause: v1.0.0's `packaging/build_packages.sh` `APP_FILES` list omitted
five extractor modules — `visio_extractor.py`, `markup_extractor.py`,
`eml_extractor.py`, `csv_extractor.py`, `rtf_extractor.py` — while
`scan_docs.py` imports them unconditionally. Source fixed by commit `94d0c44`
("add missing extractors to APP_FILES"), shipped in v1.0.1.

But the `.deb` attached to the **v1.0.1 GitHub release was never rebuilt** — it
is still `docubrowser-foss_1.0.0-1_all.deb`, so Debian/Mint users downloading
the latest release still get the broken package. Verified 2026-08-19: the
v1.0.1 rpm, tarball, Windows zip, and macOS dmg all contain the five
extractors; only the deb is broken, so no full-suite reissue is needed.

**TODO:** rebuild the deb as `1.0.1-1`, delete the stale `1.0.0-1` deb from the
v1.0.1 release, upload the new one, then notify gemlog on issue #3 (James
already replied promising a fixed deb).

**Follow-up (fragility):** `APP_FILES` is a hand-maintained list; a new module
that `scan_docs`/`doc_search` imports but that isn't added to `APP_FILES`
ships a broken package silently. Consider globbing `*_extractor.py` in the
build, or asserting at build time that every top-level import in `scan_docs.py`
resolves to a staged file.

### D-14: Email, RTF, CSV, and config-ish plain text — coverage sweep
**Status:** Decided — new dedicated extractors + trivial extension adds
**Priority:** Low
**Added:** 2026-07-17

An audit of `/mnt/data/Documents` found ~1,171 files across ~40 extensions
that DocuBrowse wasn't scanning. Categorized as:

- **Real content, no extractor** — `.eml` (email), `.rtf`, `.csv`, `.tsv`,
  `.vdx` (Visio 2003 XML).
- **Plain text, just need to be listed** — `.ini`, `.conf`, `.cfg`, `.log`,
  `.lst`.
- **Junk** — images, fonts, TLS material, source maps, `.pyc`, HTTrack mirror
  cruft (~356 files with `?a=b`-style query strings baked into the filename).

**Decision:** ship extractors for the real-content group, add the plain-text
group to `DEFAULT_EXTENSIONS` (they fall through to `_extract_text_file`),
route `.vdx` through `markup_extractor`'s XML tag-strip path and tag it as
`diagram`, and leave the HTTrack cruft to be handled by
`docubrowser ignore add <mirror-root>`.

Component choices:
- `.eml` — stdlib `email` package. Subject → title, From → author, To/Cc/Date
  → subject field, text/plain body preferred (falls back to text/html
  tag-stripped). Attachment filenames appended so name-searches still hit.
- `.csv` / `.tsv` — stdlib `csv` with delimiter auto-sniffing. First 500 rows
  as pipe-delimited text; header row lands in the description field so column
  names weigh into keyword search.
- `.rtf` — `striprtf` (pure Python, MIT, ARM64-safe). Added to
  `requirements.txt`. Graceful degradation when missing: file is indexed
  metadata-only and the path is appended to `rtf_missing_striprtf.txt`, same
  convention as `visio_legacy_missing.txt` for missing vsd2xml.
- `.vdx` — routed to `markup_extractor`. Tagged `markup` + `diagram`.

Consequences:
- One new optional runtime dependency (`striprtf`) in requirements.txt.
- Three new extractor modules (`eml_extractor.py`, `csv_extractor.py`,
  `rtf_extractor.py`) alongside existing `docx/odf/visio/markup/ebook/pdf`.
- One new sidecar file `rtf_missing_striprtf.txt` (gitignored).
- HTTrack mirror cruft is a user-space cleanup — not code work.

**Deferred follow-ups (surfaced by QA review 2026-07-17):**
- `.vdx` title extraction picks the first `<Title>` element anywhere in the
  document.  Real Visio 2003 XML puts `DocumentProperties/Title` first so
  this works today, but a file with a shape-level `<Title>` before the
  document properties would extract the wrong string.  Follow-up: prefer
  `<DocumentProperties><Title>` explicitly in `markup_extractor`.
- CSV extractor sets `description` to whatever the first row is, even when
  `csv.Sniffer.has_header(sample)` says the file has no header.  Follow-up:
  gate the header-→description assignment on `has_header`.
- `csv_extractor` returns `success=False` on genuinely-empty files, so
  empty CSVs land in `scan_blacklist.txt`.  Cosmetic; consider
  `success=True` with empty text so they show up in browse instead.
- `eml_extractor` returns `success=True` on a zero-byte `.eml` (empty text,
  no title).  Inconsistent with `_extract_text_file` which returns
  `success=bool(text)`.  Cosmetic.

---

### D-13: Markup family — schema-agnostic tag-strip vs. per-format parsing
**Status:** Decided — schema-agnostic tag-strip
**Priority:** Low
**Added:** 2026-07-17

The SGML/XML family (`.xml`, `.xhtml`, `.sgml`, `.sgm`, `.docbook`, `.dbk`,
`.svg`, `.rss`, `.atom`, `.opml`) plus structured plain-text markup (`.rst`,
`.adoc`, `.asciidoc`, `.tex`, `.latex`) all needed a first-pass extractor.

Options considered:
- **(a) Schema-aware per format** — dedicated parser per format (DocBook →
  section headings; RSS → item list; Atom → entry summaries; SVG →
  `<text>` and `<title>`; reST/AsciiDoc → structured heading walk). Best
  metadata, most maintenance.
- **(b) Schema-agnostic tag-strip ← chosen** — one XML/SGML tag-stripper
  that decodes DOCTYPE, comments, and CDATA, sniffs title/author from
  well-known local-names (`title`, `dc:title`, `author`, `dc:creator`)
  before stripping, then unescapes entities. reST/AsciiDoc/LaTeX are
  passed through verbatim so all markup becomes searchable text, with a
  per-format title-sniff. LaTeX gets `\title{}`/`\author{}` + line-`%`
  comment stripping.
- **(c) Skip entirely** — leave everything to `_extract_text_file`.

**Decision:** ship path (b). No new dependencies, one 280-line module,
handles unknown schemas gracefully, extracts useful titles/authors for
the formats that follow well-known conventions (DocBook, Atom, RSS, SVG,
LaTeX).

Consequences:
- New extractor `markup_extractor.py`; no new runtime dependency.
- Every markup file gets a `markup` browse/filter tag; SVG additionally
  gets a `diagram` tag alongside `.vsdx` / `.drawio` / `.puml`.
- Deferred to a future session: per-format schema-aware pretty extraction
  (structure preserved instead of flattened), and light heuristic
  cleanup of reST/AsciiDoc/LaTeX punctuation noise from the searchable
  text — the current path leaves the source markup verbatim, which is
  fine for keyword hits but slightly noisy for synopsis generation.

---

### D-12: Legacy Visio (.vsd/.vss/.vst) — external converter choice
**Status:** Decided — libvisio-tools (`vsd2xml`)
**Priority:** Low
**Added:** 2026-07-17

Modern Visio (`.vsdx`/`.vsdm`) is OOXML and parses with the stdlib. Legacy
binary Visio (`.vsd`, and the related stencil `.vss` / template `.vst`) is
Microsoft Compound Document format and needs a real converter.

Options considered:
- **(a) LibreOffice headless** — reliable but pulls in ~1 GB of dependencies,
  slow to spawn, and inconvenient in server contexts.
- **(b) libvisio-tools (`vsd2xml`) ← chosen** — packaged in Fedora, Debian,
  and Ubuntu; ~5 MB install; produces ODG-flavoured XML on stdout that the
  same text-walking approach used in `odf_extractor.py` can consume.
- **(c) Metadata-only** — skip body extraction entirely. Cheap, but the
  file's diagram labels never make it into keyword or semantic search.

**Decision:** ship path (b). When `vsd2xml` is missing at scan time,
degrade gracefully to path (c): index the row with the filename as the
title and append the path to `visio_legacy_missing.txt` so an operator can
install libvisio-tools and rescan.

Consequences:
- New optional runtime dependency documented in README, INSTALL.md, and
  the Admin Guide.
- New sidecar file `visio_legacy_missing.txt` (gitignored) alongside the
  existing `ocr_list_pdfs.txt` — same append-only convention.

**Deferred follow-ups (surfaced by QA review 2026-07-17):**
- `vsd2xml` stdout is currently unbounded via `subprocess.run(..., capture_output=True)`.
  A hostile / corrupt file that made the converter emit multi-GB output would
  grow the worker until the existing `RLIMIT_AS` (6 GB) killed it — which then
  routes the whole ProcessPool into its "worker killed" branch and mis-blacklists
  the file. Primary defence today is the 90 s timeout. Follow-up: switch to
  `Popen` + a bounded `stdout.read(N)` cap, or route through a `head -c` wrapper.
- The `.vsdx` extractor only knows the `visio/2012/main` namespace URI. Visio
  2010 and earlier files using older URIs will silently extract zero body text
  (metadata still works). Follow-up: add a fallback namespace list and log a
  warning when pages exist but no `<Text>` was found.

---

### D-1: Multi-language / i18n support
**Status:** Open — design needed  
**Priority:** Medium  
**Added:** 2026-07-02

DocuBrowse currently assumes English content throughout:

- **Keyword search** — FTS5 tokenizer uses Unicode61, which handles most scripts,
  but BM25 weighting and prefix-matching are tuned for English word boundaries.
  CJK and other non-whitespace-delimited languages need a custom tokenizer or
  n-gram fallback.
- **Tag generation** — `generate_keywords()` in `pdf_extractor.py` splits on
  whitespace and filters short/common English words. Non-Latin scripts will
  produce poor or no tags.
- **Synopsis generation** — the Ollama prompt to `dolphin3` is English-only.
  A multilingual model or language-detection + prompt routing would be needed.
- **No-extension classifier** — `_classify_noext()` checks UTF-8 printability,
  which works for most scripts, but the HTML heuristics look for English tag names
  (these are language-neutral by spec, so this is fine).
- **PII patterns** — regex patterns in `purge_pii.py` target US-format identifiers
  (SSN, ABA routing, US driver license). Non-US PII formats are not detected.

Approaches to consider:
1. Language detection at scan time (e.g. `langdetect` or `lingua`) → store in DB
2. Per-language FTS tokenizer selection (or ICU tokenizer for broad coverage)
3. Multilingual embedding model (e.g. `multilingual-e5-large`) as an option
4. Synopsis prompt templates keyed by detected language
5. Locale-aware PII pattern sets

### D-2: Sliding window ETA for progress bar
**Status:** Open  
**Priority:** Low  
**Added:** 2026-06-15

The scan progress bar uses a simple elapsed-time average for ETA, which drifts
high when large PDFs are encountered after many fast failures early on. A sliding
window (last N files) would give a more stable estimate.

### D-3: File-type filter in search UI
**Status:** Open  
**Priority:** Low  
**Added:** 2026-06-15

Add a dropdown or checkbox group to filter search results by file type (PDF, DOCX,
EPUB, etc.). The data is already in the `file_ext` column.

### D-4: OCR integration for scanned PDFs
**Status:** Open  
**Priority:** Medium  
**Added:** 2026-06-15

Scanned (image-only) PDFs are detected and listed in `ocr_list_pdfs.txt` but not
searchable. Integrate Tesseract or similar OCR engine to extract text from these.

### D-5: FOSS server packaging
**Status:** Resolved 2026-07-09  
**Priority:** Medium  
**Added:** 2026-07-02

RPM, DEB, and installable tarball are built via `packaging/build_packages.sh`
since v0.9.0. PyPI, Docker, Flatpak, and Snap remain future options.

### D-8: Windows Unicode console encoding — permanent fix needed
**Status:** ANSI colors resolved 2026-07-04; item 3 (check_missing_path) still open  
**Priority:** Low  
**Added:** 2026-07-04

**Background:** Windows console defaults to cp1252, which cannot encode the Unicode
symbols used throughout DocuBrowse output (─, ●, ✓, ✗, ⚠, █, ░, etc.).  Any
`print()` call with these characters raises `UnicodeEncodeError` and crashes the
process unless `PYTHONUTF8=1` is set in the environment.

**Fixes applied (2026-07-04):**
- `platform_paths.py` — calls `sys.stdout/stderr.reconfigure(encoding='utf-8')`
  at module level on Windows, and sets `os.environ["PYTHONUTF8"] = "1"` so all
  subprocesses inherit it.  Also calls `colorama.init()` unconditionally (no-op
  on Linux/macOS; translates ANSI codes to Win32 console calls on Windows).
- `embed_docs.py` / `purge_pii.py` — same `colorama.init()` added directly since
  they can be run standalone without importing `platform_paths`.
- `colorama` added to `requirements.txt`.

**Remaining open item:**
3. **`check_missing_path()`** uses Unix "unmounted device" detection (`os.stat("/")`,
   device ID comparison) that doesn't apply to Windows drive letters.  The function
   degrades gracefully (returns "missing" on OSError) but won't correctly classify
   disconnected Windows network shares as "unmounted".

### D-6: Dotfile handling in no-extension classifier
**Status:** Open  
**Priority:** Low  
**Added:** 2026-07-02

The no-extension file classifier (`_classify_noext` in `scan_docs.py`) picks up
dotfiles like `.bashrc`, `.env`, `.gitignore` since `Path.suffix` is empty for
them. Most are harmless text files, but `.env` files may contain secrets. Options:
skip all dotfiles, skip known-sensitive names, or rely on `ignore_dirs` / blacklist.

---

## Resolved

### D-100: Fresh install — does embed auto-run after initial scan?
**Status:** Resolved (yes) — 2026-06-27  
`scan` command now embeds by default (same as `rescan`). `--no-embed` flag
available for opt-out.

### D-101: No-extension file classification
**Status:** Done — 2026-07-02  
Added `_classify_noext()` magic-byte classifier in `scan_docs.py`. Handles
PDF, DOCX, XLSX, PPTX, EPUB, HTML, and plain text. Binary formats (ELF, images)
are skipped.

### D-102: PII bank routing/account precision
**Status:** Done — 2026-07-02  
Fixed ABA prefix range (1–12, not 0–12) and restructured bank account regex
so the `no/number/#` qualifier applies to both "account" and "acct".

---

# Enterprise

## Open

### D-7: RAG-powered interactive assistant
**Status:** Open — architecture phase  
**Priority:** High  
**Added:** 2026-07-02

Build a local AI assistant that helps users use, troubleshoot, and understand
DocuBrowse (and, in Enterprise, customer applications) through interactive
conversation grounded in indexed documentation. The human drives the
exploration; the model is a tool for retrieval and synthesis, not an
autonomous agent.

**Why it matters:** The ability to ship a local AI assistant that understands
a commercial application's documentation — in the customer's own environment,
with no cloud dependency — is a major differentiator. For Enterprise, this
turns DocuBrowse from a document search engine into a knowledge assistant
for any product or organization.

**Design approach — interactive tool, not autonomous agent:**

The assistant follows the same pattern as `coding_agent`
(`/home/james/git/AI/agentRW`): a conversational loop where the user asks
questions and the model calls tools to retrieve information. The user stays
in control — the model searches when asked, retrieves when asked, summarizes
when asked. This is not a fire-and-forget RAG pipeline; it is an interactive
session where the human decides what to explore next.

The core loop (from coding_agent) provides: tool-call parsing and execution,
multi-turn context management, token compaction, OOM recovery (auto-halve
GPU layers on CUDA OOM), and graceful Ollama connection handling. The file
and shell tools are replaced with DocuBrowse-specific tools: `search_docs`,
`read_doc`, `list_tags`, `summarize_doc`, etc.

**Why RAG instead of fine-tuning:**

RAG avoids the cost, fragility, and retraining burden of fine-tuning. The
model stays generic; knowledge lives in the document store and is injected
into the context window at query time. When docs change, re-embed them — no
model retraining needed.

**Modular architecture — three swappable layers:**

The RAG stack has three independently replaceable components:

1. **LLM** — generates answers from retrieved context (e.g. dolphin3)
2. **Embedding model** — converts queries and documents to vectors for
   retrieval (e.g. nomic-embed-text)
3. **Document corpus** — the indexed knowledge base (product docs, runbooks,
   customer content)

Changing the "installed language" means swapping all three: a model that
speaks the target language, an embedding model trained on that language, and
translated/localized documents. The conversational loop, search
infrastructure, and Ollama API calls remain untouched.

**Language constraint:** RAG provides knowledge but not linguistic
competence. The LLM must already understand the target language — you cannot
RAG your way past a model that doesn't speak Korean. dolphin3 (Llama 3.2 3B)
is primarily English-trained; limited coverage of high-resource European
languages, poor coverage of CJK/Arabic/etc. Non-English deployments require
a model trained on that language. The embedding model has the same
constraint — nomic-embed-text is English-focused; Korean documents need a
multilingual embedding model (e.g. multilingual-e5-large) to produce
meaningful vectors.

This connects directly to D-1 (multi-language support). The modular RAG
architecture makes language a configuration choice rather than a code change.

**Implementation considerations:**
- Embedding infrastructure already exists (nomic-embed-text + vector store)
- Fork/extract coding_agent's conversational core; replace file tools with
  DocuBrowse tools (search_docs, read_doc, list_tags, summarize_doc, etc.)
- Need a "grounded answers only" system prompt — dolphin3 is a ~3B model and
  will hallucinate if the answer isn't in the retrieved chunks. The
  interactive approach mitigates this: the model presents retrieved content
  rather than generating unsupported answers, and the human evaluates.
- UI: could be a chat panel in the sidebar, a `/ask` endpoint, or a dedicated
  page. Decision deferred.
- Chunking strategy for docs: fixed-size with overlap, or section-aware
  splitting on markdown headers.
- Ollama client utility: extract OOM recovery, connection handling, and
  context compaction patterns from coding_agent into a shared module.
- Customer-provided knowledge bases, role-based access, conversation history,
  larger/multilingual model support, and multi-language deployments.

### D-10: Document all files created on the system
**Status:** Open  
**Priority:** Medium  
**Added:** 2026-07-13

Both the FOSS server and the Enterprise Tauri client create files in multiple
locations (databases, logs, config, PID files, blacklists, caches, XDG data
dirs). A comprehensive manifest of every file and directory that DocuBrowse
creates — with paths, permissions, and purpose — is needed so that security
teams can audit, allowlist, and monitor the application's filesystem footprint.
This should cover all platforms (Linux, Windows, macOS) and both install methods
(package vs. manual/dev checkout).

### D-11: Chunk-level semantic search with in-document result locations
**Status:** Open — design needed (an on-demand variant is designed in
[[2026-08-21-deep-links-design]]; precomputed chunks remain future work)  
**Priority:** Medium  
**Added:** 2026-07-13

Currently, each document gets a single embedding vector (the first ~8000 chars
of extracted text sent to `nomic-embed-text`). This means semantic search can
find *which document* matches a query, but cannot show *where* inside the
document the match occurs.

**Goal:** when a user clicks a semantic search result, open a modal showing the
top 5 matching passages within that document, each with its page number and a
text excerpt.

**Required changes:**

1. **Chunking during embed** — split extracted text into overlapping passages
   (~500 tokens, ~100-token overlap). Each chunk stores its `chunk_index`,
   `char_offset`, and **page number** (available from PDF/DOCX/PPTX extractors
   which already track page boundaries).
2. **New DB table** — `doc_chunk_embeddings(doc_id, chunk_index, page_number,
   char_offset, chunk_text, embedding BLOB, model, updated_at)`.
3. **Search refactor** — document-level score becomes best-of or top-N-average
   chunk score. Per-chunk scores are retained for the in-document view.
4. **New API endpoint** — e.g. `GET /api/search-in-doc?doc_id=<id>&q=<query>`
   returning the top 5 matching chunks with page number, excerpt, and score.
5. **UI modal** — triggered from a search result card; displays ranked passages
   with page numbers.

**Tradeoffs:**

- DB size increases ~30-40× for embeddings (still manageable — ~1-2 GB for
  2000 docs).
- Embed time proportionally longer (one Ollama call per chunk).
- Existing embeddings must be regenerated.
- Overall search quality improves (chunk-level matching is more precise than
  whole-document matching).

### D-9: Tauri data directory uses reverse-DNS path
**Status:** By design  
**Priority:** Informational  
**Added:** 2026-07-13

Tauri requires a reverse-DNS bundle identifier (`us.sparenbergs.docubrowse` in
`src-tauri/tauri.conf.json`). On Linux, Tauri automatically creates its app
data directory at `~/.local/share/us.sparenbergs.docubrowse/` rather than
`~/.local/share/docubrowser/` (which is what the FOSS server uses). This is
standard Tauri/XDG behavior and not a bug. The two directories are independent:
the FOSS server stores its database and logs in `docubrowser/`; the Tauri
desktop client stores its own state in `us.sparenbergs.docubrowse/`.

---

## Resolved

_(No resolved Enterprise items yet.)_
