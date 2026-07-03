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
