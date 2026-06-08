# DocuBrowse — Planning Document

**Date:** 2026-06-07  
**Goal:** Build searchable index of `/mnt/data/Documents` (9,998 files) with semantic search + tagging, similar architecture to repo-browser.

## Inventory

```
Total files: 9,998

By type:
  6,004 (60.1%)  .html        — web archives, blog downloads, HTML variants
  1,242 (12.4%)  .pdf         — digital text (mostly)
    591 (5.9%)   no_ext       — files without extensions (investigate)
    201 (2.0%)   .png
    182 (1.8%)   .azw3        — Kindle ebooks
    104 (1.0%)   .jpg
    102 (1.0%)   .ccd         — ClickCharts diagrams
     95 (1.0%)   .txt
     93 (0.9%)   .docx
     76 (0.8%)   .sample
     75 (0.8%)   .woff2
     69 (0.7%)   .mobi        — Kindle ebooks
     66 (0.7%)   .rb          — Ruby code
     63 (0.6%)   .epub        — ebooks
     60 (0.6%)   .json
     58 (0.6%)   .yml
    [rest <0.5%]
```

## Challenges vs repo-browser

1. **10x larger** (9,998 vs ~1000 repos) — performance impact on cosine search
2. **Multiple extraction methods** — HTML, PDF, DOCX, EPUB, MOBI, plain text, etc.
3. **HTML mess** — 60% are archives with URL-encoded variant filenames (e.g., `htmlc=m;o=a`)
4. **Metadata varies** — filesystem dates, embedded metadata, file naming conventions
5. **Dedup is harder** — similar titles, identical content across formats, duplicates across folders

## High-Level Strategy

### Phase 1: Foundation (prepare data, format handlers)
- Investigate `.html` variants and URL-encoded filenames
- Determine which files to index (skip templates, samples, fonts?)
- Map document types to extraction strategies
- Build format-specific parsers (PDF, DOCX, EPUB, MOBI, HTML, plain text)
- Design metadata extraction (filesystem + embedded)

### Phase 2: Scanning & Ingestion
- Write `scan_docs.py` — walk `/mnt/data/Documents`, extract content + metadata by type
- Populate SQLite schema (modified for doc-specific fields)
- Auto-tag (similar to repo-browser: extension, keyword, folder, detected language/genre)

### Phase 3: Embedding & Search
- Write `embed_docs.py` — generate embeddings via Ollama (content only, same as repo-browser)
- Tune semantic threshold for 10K docs (may need to increase from 0.65 if noise is high)
- Implement dedup detection (optional Tool later)

### Phase 4: UI & Polish
- Serve web UI at `:8643` (or adjust port)
- Allow filtering by doc type, metadata
- Add sorting (date, title, relevance)

---

## Phase 1: Format Investigation & Strategy

### A. HTML Files (60% of corpus)

**Questions:**
1. Are these web archives (.htm/.mhtml) or raw HTML downloads?
2. What do the URL-encoded variants represent? (htmlc=m;o=a, htmlc=n;o=d, etc.)
3. Should we extract full page content or just title + metadata?

**Action:** Sample 10-20 HTML files, inspect headers/structure.

**Extraction approach:**
- Use `html.parser` (stdlib) or `re` to extract text (avoid full DOM parsing)
- Extract `<title>`, `<meta name="description">`, first `<h1>`, body text
- Strip script/style tags
- May need to handle both `.html` and archived `.mhtml` formats

### B. PDF (12.4%)

**Known:** Mostly digital text, ~1% OCR.

**Extraction:** Use `pypdf` library (if allowed) or extract text with regex/stdlib approach.

### C. Ebooks (EPUB, MOBI, AZW3) — 3.1%

**Challenge:** No stdlib libraries; require `ebooklib`, `KindleUnpack`, etc.

**Options:**
1. Skip for MVP (revisit later)
2. Use online web service for extraction
3. Implement minimal extraction per format
4. Mark as "ebook" type and metadata-only index

**Recommendation:** Phase 1 — metadata-only (title, author, size); Phase 2+ — content extraction.

### D. DOCX, XLSX, PPTX (1.1%)

**Extraction:** Use `zipfile` (stdlib) to read embedded XML, extract text.

### E. Plain Text, Markdown, Code (txt, md, py, rb, etc.) — 1.5%

**Extraction:** Direct read, strip binary artifacts.

### F. Skip/Exclude

- Fonts (.woff2, .ttf, .eot) — 0.6%, no content
- Images (.png, .jpg) — 2%, skip for now
- Config files (.ini, .conf, .key, .pem) — potentially sensitive
- Build artifacts (.pyc, .o, .obj) — skip
- Archive files (.zip, .gz, .7z) — skip (expand separately if needed)
- ClickCharts (.ccd) — 1%, skip (binary format, specialized tool needed)

---

## Metadata Strategy

### Fields to Extract

```
documents (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    size_bytes INTEGER,
    file_ext TEXT,
    title TEXT,              -- from embedded metadata or first heading
    author TEXT,             -- from metadata or directory structure
    description TEXT,        -- first meaningful paragraph
    content_snippet TEXT,    -- first 2000 chars
    created_at TEXT,         -- filesystem mtime
    modified_at TEXT,        -- filesystem ctime
    indexed_at TEXT,
    doc_type TEXT            -- 'pdf', 'docx', 'epub', 'html', 'text', etc.
)

doc_tags (similar to repo-browser)

doc_embeddings (similar to repo-browser)

doc_fts (similar to repo-browser)
```

### Metadata Sources

1. **Filesystem:** mtime, ctime, file size, extension
2. **Embedded:** PDF author/title, DOCX core props, EPUB metadata
3. **Heuristic:** First line/heading as title, directory name as category

---

## Content Extraction Pipeline

### Per-format handlers:

| Format | Handler | Challenges | MVP Approach |
|--------|---------|------------|--------------|
| HTML | `html.parser` + regex | Messy DOM, ads, boilerplate | Extract text nodes, skip scripts |
| PDF | `pypdf` or `pdfplumber` | Need external lib; OCR rare | Extract text layer only |
| DOCX | `zipfile` + XML parse | Embedded fonts/images | Extract `<w:t>` nodes |
| XLSX | `zipfile` + XML parse | Structured data; formulas complex | Extract cell text only |
| EPUB | `zipfile` + XML parse, or `ebooklib` | Variable structure | Metadata only (MVP) |
| MOBI | `KindleUnpack` or external | Binary format, DRM | Skip (MVP) |
| AZW3 | `KindleUnpack` or external | Binary format, DRM | Skip (MVP) |
| TXT / Markdown | Direct read | Encoding issues | Read as UTF-8, fallback to latin-1 |
| Code (.py, .rb, .go, etc.) | Direct read | Large files | Read, truncate to 5000 chars |

---

## Deduplication & Binary Integrity

**Challenge:** 10K files → likely duplicate content across formats and folders. Many binaries (images, fonts, archives) may be embedded in documents.

**Strategy:**
1. **Content hash:** SHA256 of first 5000 chars of extracted text
2. **Similarity detection:** Cosine similarity on embeddings (same as repo-browser)
3. **Binary relationship detection:** Use embedding similarity to find parent documents for orphaned binaries (e.g., image that should be attached to a doc)
4. **Cleanup tools:** Interactive TUI (like `dupe_clean.py`) for both document and binary cleanup

**Schema includes:**
- `doc_parent_binaries` — links documents to embedded/referenced binaries
- `binary_status` — 'attached' (has parent), 'orphan' (no parent), 'ambiguous' (multiple possible parents)

**MVP:** Index all docs + binaries; map relationships using embeddings; orphans marked for Phase 3 cleanup tool.

---

## Tagging Strategy

**Auto-tags (regenerated each scan):**

1. **File extension** → `pdf`, `docx`, `html`, etc.
2. **Folder hierarchy** → parent folder name as category (e.g., `Companies/Areotek` → tags: `Companies`, `Areotek`)
3. **Content keywords** — same list as repo-browser (Kubernetes, Docker, AWS, etc.) + domain-specific (e.g., HR, finance, tech)
4. **Detected type** — `ebook`, `invoice`, `handbook`, `blog`, `code`, etc. (heuristic)

**Manual tags:** Schema supports `source='manual'` but no UI yet.

---

## File Structure

```
DocuBrowse/
├── scan_docs.py             # Walk filesystem, extract content + metadata
├── embed_docs.py            # Generate embeddings
├── doc_search.py            # HTTP server + search (similar to repo_search.py)
├── index.html               # Frontend (same design as repo-browser)
├── dupe_detect.py           # Find duplicate docs (content hash + semantic)
├── dupe_clean.py            # Interactive TUI for dedup cleanup
├── ensure_ollama.py         # (reuse from repo-browser)
├── db_config.py             # Config loader
├── docubrowse.py            # CLI launcher (start/stop/rescan/etc.)
├── docubrowse.config.example
├── status_docs/
│   ├── Planning.md          # (this file)
│   └── Project_state.md     # Updated per session
├── info_docs/
│   ├── Format_handlers.md   # Detailed extraction logic per format
│   └── Metadata_strategy.md
├── images/
│   ├── screenshot-dark.png
│   └── screenshot-light.png
├── .gitignore
└── docs.db                  # (gitignored)
```

---

## Implementation Phases

### Phase 1 (This session): Foundation
- Investigate HTML files, determine what to index
- Design DB schema
- Implement basic extractors (text, PDF, DOCX)
- **Skip:** EPUB/MOBI/AZW3 (metadata-only for now)
- **Skip:** Ebooks content extraction

### Phase 2: Scanner & Ingestion
- Write `scan_docs.py` with format handlers
- Populate DB
- Generate auto-tags

### Phase 3: Embeddings & Dedup
- Write `embed_docs.py`
- Build dedup detector
- Tune semantic threshold for 10K corpus

### Phase 4: UI & Refinement
- Serve web UI
- Add filters, sorting
- Performance tuning (caching, pagination)

---

## Open Questions

1. **HTML variants:** What do `htmlc=m;o=a` filename patterns mean? Skip these?
2. **No-extension files (591):** Sample a few—are they text, binary, or misnamed?
3. **ClickCharts files (.ccd):** Worth extracting? (Probably skip MVP.)
4. **Ebooks strategy:** Metadata-only or full content extraction?
5. **Sensitive files:** Should we index .key, .pem, .p12 (certs/keys)? Redact?
6. **Performance:** At 10K docs, embedding + cosine search may be slow. Acceptable?

---

## Next Steps

1. Sample HTML files and no-ext files (investigate)
2. Design & create DB schema
3. Implement text + PDF extractors
4. Start `scan_docs.py`
