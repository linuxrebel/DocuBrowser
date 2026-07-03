# DocuBrowse — Decisions & Deferred Work

Tracks open decisions, deferred features, and known issues for the FOSS repo.
Items are numbered for cross-reference; resolved items keep their number.

---

## Open

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
**Status:** Open — decision needed  
**Priority:** Medium  
**Added:** 2026-07-02

Decide on distribution format beyond the current `install.sh`:
- pip-installable package (PyPI)
- `.deb` / `.rpm` packages
- Docker image
- Flatpak / Snap

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

**Enterprise only.** This feature lives entirely in the Enterprise repo.
Customer-provided knowledge bases, role-based access, conversation history,
larger/multilingual model support, and multi-language deployments.
Organizations embed their own internal docs, runbooks, and procedures — the
assistant becomes a domain expert for their specific environment.

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
