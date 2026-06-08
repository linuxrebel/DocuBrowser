# DocuBrowse v0.1.0

A modern, fast document search and browsing application with semantic search capabilities. DocuBrowse indexes and searches documents from your filesystem using a combination of keyword matching and AI-powered semantic similarity.

## Features

### 🔍 Dual Search Modes
- **Keyword Search**: Fast full-text search using SQLite FTS5
- **Semantic Search**: AI-powered similarity matching via Ollama embeddings
- **Hybrid Mode**: Combines both for comprehensive results

### 📚 Document Management
- Indexes 100+ documents (MVP: PDF-first, extensible to HTML, TXT, DOCX)
- Automatic metadata extraction (title, author, description)
- Tag-based organization and filtering
- Responsive grid layout (1/2/3+ columns based on screen size)

### 🎨 User Interface
- **Dark/Light Theme** toggle with persistent preference
- **Pagination Controls**: Back/Next buttons for browsing (50 docs per page)
- **Alphabetic Index Bar**: Quick jump to documents by first letter (A-Z, 0-9)
- **Tag Cloud**: Popular tags with counts for filtering
- **Scroll-to-Top Button**: Smooth scrolling back to navigation
- **Score Badges**: Relevance percentages (0-100%) for search results

### ⚡ Performance
- Search latency: <150ms (typical)
- UI load time: <1s
- Smooth scrolling and transitions
- Efficient grid rendering with 50-doc batches

## Quick Start

### Prerequisites
- Python 3.8+
- Ollama (optional, for semantic search)
- Modern web browser (Chrome, Firefox, Safari, Edge)

### Installation

```bash
cd /mnt/data/git/AI/DocuBrowse
python3 doc_search.py ./docs.db 8643
```

Open http://localhost:8643 in your browser.

### Configuration

Edit doc_search.py to change:
- Port (default: 8643)
- Database path (default: ./docs.db)
- Ollama host (default: localhost:11434)
- Embedding model (default: nomic-embed-text)

## Architecture

```
Browser (index.html)
    ↓ HTTP REST API
Search Server (doc_search.py)
    ↓ SQLite + Ollama
Database (docs.db)
```

### API Endpoints

- `GET /` — Serve index.html
- `GET /api/stats` — Database statistics (doc count, embeddings, tags)
- `GET /api/tags` — Tag list with counts
- `GET /api/search?q=QUERY&offset=0` — Search with pagination
- `GET /api/config` — Current configuration

### Search Algorithm

Relevance score combines:
- **FTS5 Keyword Matching** (30% weight)
  - Title match: +0.8
  - Filename match: +0.6
  - Description match: +0.3
  - Tags match: +0.4
- **Semantic Similarity** (70% weight)
  - Cosine similarity vs. query embedding (0.0–1.0)
  - Threshold: 0.30 for semantic-only mode

## File Structure

```
DocuBrowse/
├── doc_search.py           # HTTP server + search logic
├── docubrowse_db.py        # SQLite schema + migrations
├── pdf_extractor.py        # PDF metadata extraction
├── embed_docs.py           # Embedding generation
├── index.html              # Frontend UI (dark/light theme)
├── docs.db                 # SQLite database
├── .gitignore              # Ignore test files & cache
├── README.md               # This file
└── test_docs/              # Sample PDF documents
```

## Development

### Adding New Document Formats

1. Create extractor in a new file (e.g., `html_extractor.py`)
2. Return dict: `{title, author, description, content_snippet, creation_date, success, error}`
3. Update `scan_docs.py` to route file types to extractors
4. Re-index: `python3 scan_docs.py`

### Testing Search Quality

```bash
# Search for a keyword
curl "http://localhost:8643/api/search?q=database"

# Browse all documents (pagination)
curl "http://localhost:8643/api/search?q=&offset=0"

# Get statistics
curl "http://localhost:8643/api/stats"
```

### Running Embeddings (Semantic Search)

```bash
# Start Ollama service
ollama serve

# In another terminal, generate embeddings
python3 embed_docs.py
```

## Known Limitations

- **PDF-only MVP**: HTML, TXT, DOCX coming in Phase 2b
- **Semantic search disabled**: Requires Ollama service + embeddings
- **No config persistence**: Settings reset on page reload
- **No binary file tracking**: Document relationship detection deferred

## Roadmap

### Phase 2b (Next)
- HTML extractor with boilerplate filtering
- TXT/Markdown extractor
- DOCX extractor
- Expand to all 10K documents

### Phase 3
- Config persistence (load/save from disk)
- Advanced filtering (date range, document type)
- Export results (CSV/JSON)
- Duplicate detection & cleanup

### Phase 3+
- Binary file relationship detection
- Document similarity clustering
- Full-text export of search results
- API key authentication

## Performance Notes

- Database: SQLite3 with FTS5 virtual table
- Embeddings: 768-dimensional vectors (nomic-embed-text) stored as BLOBs
- Batch size: 25 documents per embedding generation commit
- Cache: Query embeddings not cached (inline computation)

## Browser Support

- Chrome/Edge: Full support
- Firefox: Full support
- Safari: Full support
- Mobile browsers: Responsive layout (1-column grid)

## Keyboard Shortcuts

- `Enter`: Search
- `Esc`: Clear search (return to all documents)
- Click tags: Filter by tag
- Click document title: Copy path to clipboard

## License

(Add your license here)

## Contact

Questions? Open an issue on GitHub or contact the maintainer.

---

**DocuBrowse MVP v0.1.0** — Built for fast, intelligent document search.
