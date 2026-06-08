# DocuBrowse Phase 2 — Implementation Plan

**Date:** 2026-06-07  
**Status:** Ready to Start  
**Duration Estimate:** 4-6 weeks

---

## Overview

Build MVP extractors, database, search server, and UI. Target: searchable index of 7,479 documents (73.8% of corpus) with semantic search via Ollama embeddings.

---

## Deliverables

### 1. Database Schema
- `documents` table (id, name, path, size, ext, title, author, description, content_snippet, created_at, modified_at, doc_type, updated_at)
- `doc_tags` table (doc_id, tag, source)
- `doc_embeddings` table (doc_id, embedding BLOB, model, updated_at)
- `doc_binaries` table (id, path, file_type, status, parent_doc_id, confidence) — *defer if needed*
- `doc_fts` virtual table (FTS5: name, title, description, content_snippet, tags)
- `scan_log` table (scan metadata)

### 2. Content Extractors (Python stdlib + pip)
**scan_docs.py:**
- Walk `/mnt/data/Documents` recursively
- Detect file type by extension
- Route to format handler:
  - **HTML:** `html.parser` + regex (extract title, meta, first 2K chars)
  - **PDF:** `pdfplumber` (extract text, metadata)
  - **TXT/Markdown:** Direct read (stdlib)
  - **DOCX:** `python-docx` (extract from XML, handle formatting)
- Extract metadata: title, author, size, dates
- Auto-tag: extension, folder name, keyword matching
- Handle errors: encoding fallback (latin-1), skip corrupted
- Upsert to SQLite (idempotent)

### 3. Embedding Generator
**embed_docs.py:**
- Read documents from DB where `updated_at > embeddings.updated_at`
- For each doc:
  - Build text blob: name + description + tags + content_snippet (first 500 chars)
  - POST to Ollama `/api/embed` with `nomic-embed-text`
  - Pack float32 vector to BLOB
  - Store in `doc_embeddings`
- Batch commits (25 docs per txn)
- Handle network timeouts gracefully

### 4. Search Server
**doc_search.py** (port 8643):
- HTTP server (stdlib `http.server`)
- Initialize DB schema on first request
- **Search endpoints:**
  - `GET /api/search?q=` — merged search (FTS5 + semantic + name + tag)
  - `GET /api/tags` — all tags with counts
  - `GET /api/stats` — doc/embedded/tag counts
  - `GET /api/config` — config values
  - `POST /api/config` — save config
  - `GET /api/browse?path=` — directory browser
  - `GET /` — serve `index.html`
- **Search algorithm** (same as repo-browser):
  - FTS5 keyword search (normalize to 0..1)
  - Semantic search (cosine similarity, threshold 0.30)
  - Name-match boost (exact/substring/token overlap)
  - Tag-match boost (exact/substring)
  - Merge: `0.2×FTS + 0.3×semantic + 0.2×name + 0.3×tag`
  - Filter noise: semantic-only results must exceed 0.65 cosine sim

### 5. Frontend UI
**index.html:**
- Port from repo-browser, adapt for documents
- Search bar with 250ms debounce
- Three search modes: both / keyword / semantic
- Tag cloud (filterable, count ≥3)
- Document cards: title (link to path), path, description, tags, date, score badge
- Settings modal: config editor + directory browser
- Dark/light theme toggle
- Responsive grid layout

### 6. CLI Launcher
**docubrowse.py** (cross-platform Python):
- Commands: `start`, `stop`, `restart`, `status`, `rescan`, `duplist`, `dupclean`
- Load config from `/etc/docubrowse.config` or local
- Manage PID file at `/tmp/docubrowse.pid`
- Kill stale processes on port 8643 before start
- Delegate `duplist`/`dupclean` to subprocess tools

### 7. Duplicate Cleanup (from Phase 1)
**dupe_clean.py** (curses TUI):
- Detect duplicate groups (SHA256 hash-based)
- Show one group at a time
- User selects: keep/delete for each location
- Safe deletion with audit logging
- Respects parent-child binary relationships (if implemented)

### 8. Config Loader
**docubrowse_config.py:**
- Read `/etc/docubrowse.config` or `docubrowse.config`
- Export: `get_doc_root()`, `get_work_dir()`, `get_db_path()`, `get_config_source()`
- Used by all scripts

### 9. Ollama Integration
**ensure_ollama.py** (from repo-browser, reuse):
- Detect platform (Linux/macOS/Windows WSL)
- Check Ollama running on localhost:11434
- Pull `nomic-embed-text` if needed
- Exit with error code if not available

---

## Implementation Order

### Phase 2a: Foundation (Week 1)
1. [ ] Database schema + migration logic
2. [ ] Config loader (`docubrowse_config.py`)
3. [ ] Ensure Ollama helper (reuse from repo-browser)
4. [ ] Basic CLI launcher (`docubrowse.py`)

### Phase 2b: Extraction (Week 2-3)
5. [ ] HTML extractor
6. [ ] PDF extractor (`pdfplumber`)
7. [ ] TXT/Markdown extractor
8. [ ] DOCX extractor
9. [ ] `scan_docs.py` orchestrator + tag generation + error handling
10. [ ] Test on 100-file sample

### Phase 2c: Embedding & Search (Week 3-4)
11. [ ] `embed_docs.py` (Ollama integration)
12. [ ] Search algorithm (merged ranking logic)
13. [ ] `doc_search.py` HTTP server
14. [ ] Test search quality on 100-doc sample

### Phase 2d: UI & Polish (Week 4-5)
15. [ ] Port `index.html` from repo-browser
16. [ ] Adapt styling for documents (not repos)
17. [ ] Test dark/light theme
18. [ ] Settings modal + config persistence

### Phase 2e: E2E & Deploy (Week 5-6)
19. [ ] Full 7,479-doc scan + embed (2-4 hours runtime)
20. [ ] Performance tuning (caching, pagination if needed)
21. [ ] User testing: search quality, UX
22. [ ] Documentation (README, config examples)

---

## Success Criteria

- [ ] All 4 extractors working (HTML, PDF, TXT, DOCX)
- [ ] 7,479 documents indexed + embedded
- [ ] Search server returns results in <500ms
- [ ] Semantic search quality acceptable (user feedback)
- [ ] UI dark/light modes working
- [ ] Config saved/loaded correctly
- [ ] `docubrowse.py start|stop|rescan` working
- [ ] No crashes during 10,000-query load test
- [ ] README + example config created

---

## Architecture Decisions

✓ **SQLite + RAG:** Store data + embeddings, external Ollama for inference  
✓ **Stdlib-first:** Python standard library for core logic, pip only for format handlers  
✓ **FTS5 + semantic merge:** Keyword + embedding-based ranking  
✓ **Metadata-first extraction:** Title, author, snippet before full content  
✓ **Optional binary tracking:** Task 8 deferred; implement in Phase 3 if needed  
✓ **Pluggable extractors:** Easy to add new formats (XLSX, PPTX, ebooks later)  
✓ **Port UI from repo-browser:** Reuse proven design, adapt for documents  

---

## File Structure (Final)

```
DocuBrowse/
├── docubrowse.py              # CLI launcher
├── scan_docs.py               # Scanner + extractors
├── embed_docs.py              # Embedding generator
├── doc_search.py              # HTTP server + search
├── dupe_clean.py              # Duplicate cleanup TUI
├── ensure_ollama.py           # (from repo-browser)
├── docubrowse_config.py       # Config loader
├── index.html                 # Frontend UI
├── docubrowse.config.example  # Config template
├── README.md
├── status_docs/
│   ├── Planning.md
│   ├── Discovery_Findings.md
│   ├── Phase2_Plan.md
│   └── Project_state.md       # Updated per session
├── info_docs/
│   ├── discovery_tasks.docx
│   └── extraction_formats.md  # (new, Phase 2)
├── data_grooming/
│   ├── discovery_tasks.md
│   ├── reports/               # (7 discovery reports)
│   └── dedup_detector.py      # (from Phase 1)
├── images/
│   ├── screenshot-dark.png
│   └── screenshot-light.png
├── .gitignore
└── docs.db                    # (gitignored)
```

---

## Questions for Phase 2 Kickoff

1. **Extraction priority?** Start with HTML (60%, most complex) or PDF (easier, 12%)?
2. **Semantic threshold:** Use same 0.65 as repo-browser, or adjust?
3. **Binary relationships:** Implement now or defer to Phase 3?
4. **Config location:** `/etc/docubrowse.config` (system-wide) or local only?
5. **Port:** Use 8643 (repo-browser+1) or user preference?

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Ollama timeout during embedding | Retry logic + batch commit every 25 docs |
| PDF extraction complexity | Start with simple text extraction, defer layout/tables |
| HTML boilerplate noise | Heuristic: skip script/style, extract largest text block |
| Encoding errors | Try UTF-8, fallback latin-1, log failures |
| 7,479 docs too slow to embed | Batch Ollama API, consider GPU acceleration |
| Search latency | Cache query embeddings, limit result set to 100 |

---

## Next Action

Ready to begin Phase 2a (database schema + config loader)?
