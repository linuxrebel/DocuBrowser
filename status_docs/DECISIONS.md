# DocuBrowse — Decisions & Deferred Work

Tracks open decisions, deferred features, and known issues across both
the FOSS and Enterprise repos. Items are numbered for cross-reference;
resolved items keep their number.

---

# FOSS

## Open

### D-17: Pre-v1.0.4 security audit — deferred low-severity findings
**Status:** Deferred — low severity, no code change for this release
**Priority:** Low
**Added:** 2026-08-24

Whole-product security audit ahead of the v1.0.4 (Deep Links) release found **no
Critical/High issues**. Verified safe: no SQL injection (queries parameterized;
f-string SQL injects only `?` placeholders / fixed clauses), no `eval`/`exec`/
`pickle`, subprocess uses list-args (no shell) except the opt-in Ollama installer,
path traversal blocked by `SELECT id WHERE path = ?` index-validation on every
document endpoint, loopback-only bind via `verify_request()`, Host-header
allowlist, CSRF via `secrets.compare_digest` with a `secrets.token_urlsafe(32)`
token, and `OLLAMA_HOST` operator- (not request-) controlled. The Deep Links
endpoint is secure (index-validated, XSS-safe highlight built from the match span
+ `esc()`).

The following low-severity / defense-in-depth items were **deferred** — no change
this release:

1. **XML entity-expansion hardening.** `xml.etree.ElementTree` in
   `odf_extractor` / `visio_extractor` / `markup_extractor` doesn't resolve
   external entities (no file/SSRF exfil), but isn't hardened against
   billion-laughs expansion DoS. Mitigated today by `RLIMIT_AS` (6 GB) + per-file
   timeouts. Follow-up: switch to `defusedxml.ElementTree` (adds a dependency).
2. **Opener/extractor argument injection (theoretical).** A filename beginning
   with `-` passed as a subprocess arg to openers (`xdg-open`/`gio`) or extractors
   (`vsd2xml`/`djvutxt`/`ebook-convert`) could be misparsed as a flag. Requires an
   attacker-named file to already be indexed. Follow-up: `--` / `./`-prefix the
   path where the tool supports it.
3. **vsd2xml unbounded stdout.** The legacy-Visio converter's stdout is read via
   `subprocess.run(..., capture_output=True)` with no size cap; a hostile/corrupt
   `.vsd` emitting multi-GB output is bounded only by the 90 s timeout +
   `RLIMIT_AS`. Follow-up: bounded `Popen` read (`stdout.read(N)`) or a `head -c`
   wrapper.
4. **Deep Links semantic N+1 embed.** ~~`_semantic_passage` calls the embedder once
   per returned passage (up to `max_passages` = 200 Ollama round-trips per
   request).~~ **Resolved 2026-08-25 (see D-18)** — the per-passage re-embed was
   removed entirely.

Sync this entry into the Enterprise repo's `status_docs/DECISIONS.md`.

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

---

## Resolved

### D-19: Search fires on Enter, not as-you-type
**Status:** Done — 2026-08-25
The main search box used a 250 ms debounce firing on every keystroke, which
searched partial words (`fr`, `fre` before `fred`), hurt responsiveness, and made
the box hard to type in. Search now fires on Enter; clearing the box restores the
full list. `index.html` only (removed the `debounceTimer` + `input` auto-search).

### D-18: Deep Links semantic tuning — scan cap + relevance floor
**Status:** Done — 2026-08-25
Semantic Deep Links had two unbounded costs and a false-positive problem:
1. **Timeout.** It embedded *every* passage in one `/api/embed` call (a 1500+
   passage epub → >60 s socket timeout) and then re-embedded each returned
   passage's sentences (up to 200 more Ollama calls). Fixed with
   `_SEMANTIC_SCAN_CAP=300` (bound the single embed call, per the design's own
   "cap work at first max_passages" intent — the cap had been applied *after*
   scoring, not before embedding) and by removing the per-passage re-embed
   (resolves D-17 item 4). Highlight now marks the query term when present, else
   the first sentence — no more marking whole unpunctuated blocks.
2. **False relevance.** Semantic returned its top-N by cosine even when nothing
   was relevant (e.g. "fred" surfaced 150 "Fedora" passages — subword-similar
   tokens). Added cosine floor `_SEMANTIC_MIN_SIM=0.5`; below it a document
   returns no passages. Calibrated on nomic-embed-text (real topic matches
   ~0.6-0.7, unrelated tokens ~0.45). All in `deep_links.py`.

Follow-up (open): user-facing disclaimer copy explaining semantic search is fuzzy
on short/rare tokens (names) and finds concepts, not exact words.

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

### D-6: Dotfile handling — skip all dotfiles
**Status:** Done — 2026-08-25  
Scanning now skips any file whose path (relative to the scan root) has a
dot-prefixed component — dotfiles like `.env`/`.bashrc` and the contents of
hidden dirs like `.git/`/`.venv/` — via `_is_hidden_relpath` in `scan_docs.py`.
`test_scan_dotfiles.py` covers the predicate and a real scan. Caveat: the skip
is not retroactive — `scan_directory` upserts candidates but doesn't prune
existing rows, and `scan-missing` keeps files that still exist, so dotfiles
indexed by an older version need a full index rebuild to purge (documented in
README Known Limitations).

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
**Status:** Partially shipped — the on-demand variant is **Deep Links** (v1.2.0,
`deep_links.py`); precomputed per-chunk embeddings remain future work  
**Priority:** Medium  
**Added:** 2026-07-13

Each document gets a single embedding vector (the first ~8000 chars of extracted
text sent to `nomic-embed-text`), so semantic search finds *which document*
matches but not *where* inside it. Deep Links (v1.2.0) now answers the "where" on
demand — it re-extracts the clicked document, splits it into passages, embeds
them at click time, and returns the best-matching passages with location labels.
No schema change, no reindex.

The remaining, still-open part of this item is the **precomputed** approach — so
whole-corpus ranking itself becomes chunk-level, not just the in-document view:

1. **Chunking during embed** — split extracted text into overlapping passages
   (~500 tokens, ~100-token overlap). Each chunk stores its `chunk_index`,
   `char_offset`, and **page number** (available from PDF/DOCX/PPTX extractors
   which already track page boundaries).
2. **New DB table** — `doc_chunk_embeddings(doc_id, chunk_index, page_number,
   char_offset, chunk_text, embedding BLOB, model, updated_at)`.
3. **Search refactor** — document-level score becomes best-of or top-N-average
   chunk score. Per-chunk scores are retained for the in-document view.

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
