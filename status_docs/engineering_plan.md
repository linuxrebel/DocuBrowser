# DocuBrowse Engineering Plan

**Last Updated**: 2026-06-07  
**Owner**: James (Observability & Troubleshooting)  
**Status**: MVP v0.1.0 Complete ✅

---

## High-Level Goals

1. **Phase 1 (MVP)**: Build document search with full-text + semantic search
   - Status: ✅ **COMPLETE**
   - Outcome: 100 PDFs searchable, responsive UI, dual search modes

2. **Phase 2**: Expand document formats and scale to 10K files
   - Status: Planned for Q3 2026
   - Scope: HTML, TXT, DOCX extractors

3. **Phase 3**: Polish, optimize, and add advanced features
   - Status: Planned for Q4 2026
   - Scope: Persistence, filtering, export, clustering

---

## Phase 1: MVP Architecture (COMPLETE)

### 1.1 Data Layer

**Technology**: SQLite3 + Ollama

**Schema Decisions**:
- ✅ Denormalized documents table (metadata + timestamps)
- ✅ Separate doc_tags for flexible organization
- ✅ FTS5 virtual table for fast keyword search
- ✅ BLOB-based embedding storage (768-dim vectors)

**Why SQLite?**
- Zero-config, single-file database
- FTS5 extension for full-text search
- Sufficient for MVP (<1M documents)
- Easy to migrate to PostgreSQL later if needed

**Why Ollama?**
- Local-first (privacy, no API calls)
- Customizable models
- Good embeddings quality (nomic-embed-text)
- Aligned with offline-first philosophy

### 1.2 Search Engine

**Dual Search Modes**:

1. **Keyword Search (FTS5)**
   - Queries: `title:QUERY`, `description:QUERY`, `tags:QUERY`
   - Boosts: Title (+0.8), Filename (+0.6), Description (+0.3), Tags (+0.4)
   - Speed: <10ms for 100 documents

2. **Semantic Search (Embeddings)**
   - Model: nomic-embed-text (768-dim)
   - Similarity: Cosine distance
   - Threshold: 0.30 (noise filter)
   - Speed: ~50ms with Ollama compute

3. **Hybrid Mode (Default)**
   - Merges both: `0.3 × keyword + 0.7 × semantic`
   - Rationale: Semantic captures intent, keyword ensures recall
   - User-facing: Single unified score (0–100%)

**Decision: Why 70/30 split?**
- Semantic search alone misses exact matches
- Keyword search alone lacks understanding
- 70/30 empirically works well for document retrieval
- Future: Make weights configurable (Phase 3)

### 1.3 HTTP API

**Endpoints**:
- `GET /` — Serve index.html
- `GET /api/search?q=QUERY&offset=0&mode=both` — Main search
- `GET /api/stats` — DB statistics
- `GET /api/tags` — Tag cloud
- `GET /api/config` — Configuration

**Error Handling**:
- 404 for missing documents
- 500 with descriptive messages for failures
- Port conflict detection (errno 98)
- Graceful degradation when Ollama unavailable

**Localhost-only**: Server binds loopback subnet; rejects all non-loopback connections

### 1.4 Frontend UI

**Technology**: Vanilla HTML5 + CSS3 + JavaScript (no framework)

**Key Features**:
- ✅ Dark/Light theme (CSS variables)
- ✅ Responsive grid (1/2/3+ columns)
- ✅ Pagination (Back/Next, 50 docs/page)
- ✅ Alphabetic index (A-Z, 0-9)
- ✅ Tag filtering
- ✅ Score badges (relevance %)
- ✅ Scroll-to-top button
- ✅ Search input with debouncing

**Why Vanilla JS?**
- No build step, no dependencies
- Lightweight (single HTML file)
- Easy to understand and modify
- Sufficient for MVP feature set

**Why No Framework?**
- Reduces complexity for MVP
- Easier testing and debugging
- Lower barrier for contributors
- Can add React/Vue in Phase 2 if needed

---

## Phase 2: Format Expansion (Planned)

### 2.1 HTML Extraction

**Challenge**: Web pages contain boilerplate (navigation, ads, footers)

**Solution Approach**:
- Use BeautifulSoup for DOM parsing
- Remove `<script>`, `<style>`, `<nav>`, `<footer>`, `<header>` tags
- Extract `<h1>`, `<h2>`, `<p>` for content
- Keep `<title>` for document name
- Fallback to full text if extraction fails

**Files to Create**:
- `html_extractor.py` (extract metadata from HTML)
- Update `scan_docs.py` to route `.html` files

**Testing**:
- Sample HTML files (blog posts, docs, etc.)
- Verify boilerplate removed
- Check embedding quality

### 2.2 TXT/Markdown Extraction

**Challenge**: Markdown may have YAML frontmatter or embedded code

**Solution Approach**:
- Read raw text
- Parse optional YAML frontmatter for metadata
- Extract first 300 chars for description
- Tag as "markdown" or "text" based on extension

**Files to Create**:
- `text_extractor.py` (handles .txt, .md, .rst)
- Update `scan_docs.py`

### 2.3 DOCX Extraction

**Challenge**: DOCX is a ZIP archive; parsing requires libraries

**Solution Approach**:
- Use python-docx for structured extraction
- Extract document properties (author, title, subject)
- Join all paragraph text for content
- Handle embedded images gracefully

**Files to Create**:
- `docx_extractor.py` (uses python-docx)
- Update `scan_docs.py`

### 2.4 Scaling to 10K Documents

**Challenges**:
- Embedding generation: 768-dim × 10K = ~31MB storage
- UI pagination still works (50 at a time)
- Search performance: O(10K) in-memory scoring

**Optimizations**:
- Batch embedding generation (25 docs per commit)
- Add progress indicator
- Pre-compute tag statistics
- Optional: Move to PostgreSQL if SQLite shows limits

**Timeline**: Phase 2b (~2 weeks)

---

## Phase 3: Advanced Features (Planned)

### 3.1 Config Persistence

**Goal**: Save theme preference, search filters

**Implementation**:
- Server-side: JSON config file
- Client-side: GET/POST `/api/config`
- LocalStorage backup if offline

**Timeline**: 1 week

### 3.2 Advanced Filtering

**Features**:
- Date range (modified_at)
- Document type (extension)
- Author (from metadata)
- Tag boolean queries (AND, OR, NOT)

**Implementation**:
- Extend `/api/search` query params
- Add UI filter sidebar
- Validate filter combinations

**Timeline**: 1 week

### 3.3 Result Export

**Formats**:
- CSV (id, title, path, score)
- JSON (full document objects)
- PDF report (with formatting)

**Implementation**:
- New `/api/export` endpoint
- Client-side download trigger
- Progress indicator for large exports

**Timeline**: 1.5 weeks

### 3.4 Duplicate Detection

**Goal**: Find and merge duplicate or near-duplicate documents

**Approach**:
- Semantic similarity clustering (>0.95 cosine)
- Byte-level hash comparison (exact duplicates)
- UI for user review before merge

**Timeline**: 2 weeks

---

## Phase 3+: Long-term Vision

### 3.5 Binary File Relationships

**Goal**: Track which binaries are referenced by documents

**Approach**:
- Parse document content for file paths
- Cross-reference with filesystem
- Build relationship graph
- UI visualization

### 3.6 Document Clustering

**Goal**: Auto-group related documents

**Approach**:
- K-means clustering on embeddings
- Label clusters by semantic analysis
- Suggest tags based on clusters

### 3.7 API Authentication

**Goal**: Protect search API with API keys

**Approach**:
- Bearer token authentication
- Rate limiting per key
- Usage analytics

---

## Testing Strategy

### Unit Tests (Per Phase)

**Phase 1 (MVP)**:
- ✅ PDF extractor (metadata accuracy)
- ✅ Database queries (FTS5, embeddings)
- ✅ Search algorithm (scoring, ranking)
- ✅ API responses (JSON validity)
- ✅ UI rendering (light/dark, responsive)

**Phase 2**:
- [ ] HTML boilerplate removal
- [ ] Markdown YAML parsing
- [ ] DOCX content extraction
- [ ] Embedding generation scaling

### Integration Tests

- Full search flow: Index → Query → Results
- Theme persistence (localStorage)
- Pagination state management
- Error scenarios (404, 500, Ollama down)

### UI/UX Tests

- ✅ Responsive grid on mobile/tablet/desktop
- ✅ Dark/light theme toggle
- ✅ Pagination controls
- ✅ Index bar navigation
- ✅ Tag filtering
- [ ] Accessibility (WCAG 2.1 AA)

### Performance Tests

- Search latency <150ms (100 docs)
- UI load time <1s
- Memory usage <500MB
- Database queries <10ms

---

## Deployment Architecture

### Development Environment
- Python 3.8+ on Fedora Linux
- SQLite3 (in-process)
- Ollama running on localhost:11434
- Browser: Chrome/Firefox/Safari

### Production Deployment (Future)

**Option A: Single-machine (Recommended for MVP)**
```
DocuBrowse Server
├── doc_search.py (HTTP)
├── du-docs.db (SQLite)
└── Ollama service (embeddings)
```

**Option B: Distributed (Phase 3+)**
```
Load Balancer
├── API Instances (doc_search.py, stateless)
├── PostgreSQL (shared database)
└── Embedding Cache (Redis)
```

### Hosting Options

1. **Self-hosted**: VPS or on-premise server
   - Pros: Privacy, control
   - Cons: Operational overhead
   - Cost: $5–50/month

2. **Docker**: Container deployment
   - Pros: Reproducible, portable
   - Cons: Requires orchestration
   - Timeline: Phase 3

3. **Kubernetes**: Cloud-native
   - Pros: Auto-scaling, HA
   - Cons: Overkill for MVP
   - Timeline: Phase 3+

---

## Security Considerations

### Current (MVP)

**Threats**:
- SQL injection: ⚠️ Mitigated via parameterized queries
- XSS: ⚠️ Mitigation via HTML escaping (JavaScript)
- Path traversal: ⚠️ Mitigated via Path validation
- DoS: ⚠️ No rate limiting (local-only)

**Status**: Acceptable for local/internal use. Requires hardening for public deployment.

### Future Hardening (Phase 3)

- [ ] Input validation framework
- [ ] Rate limiting per client
- [ ] API authentication (Bearer tokens)
- [ ] HTTPS/TLS support
- [ ] CSRF protection
- [ ] Security audit

---

## Performance Benchmarks

### Current (100 PDFs)

| Operation | Time | Notes |
|-----------|------|-------|
| Index all PDFs | 15s | Sequential |
| Generate embeddings | 5m | ~3 docs/sec with Ollama |
| Full-text search | 8ms | Keyword-only, 50 results |
| Semantic search | 60ms | With embedding lookup |
| Hybrid search | 70ms | Combined 70/30 |
| UI load time | 500ms | Initial page render |
| Pagination | <10ms | Database query only |

### Projected (10K Documents)

| Operation | Estimate | Notes |
|-----------|----------|-------|
| Generate embeddings | ~1 hour | Batch processing |
| Full-text search | 15ms | FTS5 scales well |
| Semantic search | 80ms | O(n) scoring, cached |
| Hybrid search | 90ms | Combined |
| Database size | ~500MB | 50MB per 1K documents |
| Memory (server) | 200MB | With indices |

**Optimization**: Phase 2/3 may require indexing or caching strategies.

---

## Knowledge Transfer

### Key Files & Responsibilities

| File | Owner | Purpose |
|------|-------|---------|
| `doc_search.py` | James | HTTP server, API routing |
| `docubrowse_db.py` | James | Database schema, migrations |
| `pdf_extractor.py` | James | PDF metadata extraction |
| `embed_docs.py` | James | Embedding generation pipeline |
| `index.html` | James | Frontend UI (HTML/CSS/JS) |
| `README.md` | James | User documentation |
| `PROJECT_STATUS.md` | James | Project state & metrics |
| `ENGINEERING_PLAN.md` | James | This file (long-term vision) |

### Onboarding for New Contributors

1. Read `README.md` (user perspective)
2. Read `ENGINEERING_PLAN.md` (this file, architectural perspective)
3. Clone repo and run `doc_search.py` locally
4. Review `doc_search.py` for API endpoint patterns
5. Review `index.html` for UI structure
6. Review `docubrowse_db.py` for data model
7. Run tests and explore edge cases
8. Check GitHub issues for contribution opportunities

---

## Decision Log

| Date | Decision | Rationale | Impact |
|------|----------|-----------|--------|
| 2026-06-01 | Use SQLite (not PostgreSQL) | Simplicity, zero-config | Easy MVP, may migrate later |
| 2026-06-02 | Ollama local embeddings | Privacy, offline capability | Requires local Ollama, ~60ms latency |
| 2026-06-03 | 70/30 hybrid scoring | Empirical testing | Good recall + precision balance |
| 2026-06-04 | Vanilla JS UI (no framework) | Reduce complexity | Fast MVP, can add React in Phase 2 |
| 2026-06-05 | Pagination (50 docs/page) | UI responsiveness | Users must navigate large result sets |
| 2026-06-07 | Defer HTML/TXT/DOCX to Phase 2 | MVP scope control | Enables faster release, clear roadmap |

---

## Risk Register

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Ollama not installed | Medium | High | Document setup, fallback to keyword-only |
| Large databases (10K+) | Low | Medium | Optimize in Phase 2, consider PostgreSQL |
| Browser compatibility | Low | Low | Test in modern browsers (Chrome, Firefox) |
| Semantic search drift | Medium | Low | Validate embeddings, add manual tuning |
| Single-point-of-failure (one server) | Low | High | Add load balancer + replication (Phase 3) |

---

## Success Metrics

### MVP (Phase 1) ✅
- [x] Search 100 documents <150ms
- [x] Support keyword + semantic modes
- [x] Responsive UI (desktop/mobile/tablet)
- [x] Dark/light theme
- [x] Pagination working
- [x] README + documentation complete

### Phase 2b (Target: 2 weeks)
- [ ] Support 10K documents
- [ ] Add HTML extractor (with boilerplate removal)
- [ ] Add TXT/Markdown extractor
- [ ] Add DOCX extractor
- [ ] Same performance profile <200ms search

### Phase 3 (Target: 4 weeks)
- [ ] Config persistence
- [ ] Advanced filtering (date, type, author)
- [ ] Result export (CSV/JSON)
- [ ] Duplicate detection UI
- [ ] API authentication
- [ ] Accessibility testing (WCAG 2.1 AA)

---

## Conclusion

DocuBrowse MVP (v0.1.0) is complete and production-ready for internal use. The architecture is clean, extensible, and documented. Phase 2 (format expansion) is well-defined and can begin immediately. Long-term vision (clustering, relationships, API) is captured for future roadmapping.

**Next Action**: Push to GitHub, set up CI/CD, prepare Phase 2 implementation plan.

---

**Engineering Owner**: James  
**Last Review**: 2026-06-07  
**Next Review**: 2026-06-21 (post-Phase 2b)
