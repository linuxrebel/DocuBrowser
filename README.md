# DocuBrowse v0.1.0

<a name="top"></a>

A fast document search and browsing application with semantic search. DocuBrowse indexes your filesystem documents using a combination of keyword matching (SQLite FTS5) and AI-powered semantic similarity (Ollama + nomic-embed-text:latest).

---

## Navigation

| | |
|---|---|
| [Features](#features) | [Quick Start](#quick-start) |
| [CLI Reference](#cli-reference) | [Configuration](#configuration) |
| [Architecture](#architecture) | [API Endpoints](#api-endpoints) |
| [Search Algorithm](#search-algorithm) | [File Structure](#file-structure) |
| [Development](#development) | [Known Limitations](#known-limitations) |
| [Roadmap](#roadmap) | [Performance Notes](#performance-notes) |
| [Browser Support](#browser-support) | [Keyboard Shortcuts](#keyboard-shortcuts) |
| [License](#license) | |

---

## Features

[↑ Top](#top)

### 🔍 Dual Search Modes
- **Keyword Search**: Fast full-text search using SQLite FTS5
- **Semantic Search**: AI-powered similarity matching via Ollama embeddings
- **Hybrid Mode** (default): Combines both — 70% semantic + 30% keyword

### 📚 Document Management
- PDF indexing (MVP); HTML, TXT, DOCX coming in Phase 2b
- Automatic metadata extraction (title, author, description)
- Tag-based organization and filtering
- Responsive grid layout (1/2/3+ columns by screen size)

### 🎨 User Interface
- **Dark/Light Theme** toggle
- **Pagination Controls**: Back/Next (50 docs per page)
- **Alphabetic Index Bar**: Jump to documents by first letter (A-Z, 0-9)
- **Tag Cloud**: Popular tags with counts for filtering
- **Score Badges**: Relevance percentages (0–100%) on each result
- **Scroll-to-Top Button**: Smooth return to navigation

### ⚡ Performance
- Search latency: <150ms typical
- UI load time: <1s
- 50-doc paginated batches keep the UI responsive

---

## Quick Start

[↑ Top](#top)

### Prerequisites
- Python 3.8+
- Ollama — `docubrowser.py` will offer to install it automatically if missing
- Modern web browser (Chrome, Firefox, Safari, Edge)

### First Run

```bash
cd /home/james/git/AI/DocuBrowse

# Start the server (checks Ollama, then launches)
./docubrowser.py start

# Open the UI in your browser
./docubrowser.py open
```

`docubrowser.py start` automatically:
1. Verifies the Ollama binary is installed (offers to install if not)
2. Confirms the Ollama service is running (starts it in the background if not)
3. Confirms `nomic-embed-text:latest` is pulled (offers to pull if not)
4. Launches the search server on port 8643

### Indexing Your Documents

```bash
# Scan documents and generate embeddings (targets /mnt/data/Documents by default)
./docubrowser.py rescan

# Or skip embedding for a faster scan
./docubrowser.py rescan --no-embed

# Generate/refresh embeddings separately
./docubrowser.py embed
```

---

## CLI Reference

[↑ Top](#top)

`docubrowser.py` is the main entry point for all DocuBrowse operations.

```
Usage: docubrowser.py <command> [options]
```

| Command | Description |
|---------|-------------|
| `start` | Start the DocuBrowse server (runs Ollama check first) |
| `stop` | Stop the server |
| `restart` | Stop then start |
| `status` | Show server status, document count, embedding count, tag count |
| `rescan` | Scan document directory and update the index; generates embeddings unless `--no-embed` |
| `embed` | Generate/refresh embeddings for documents not yet embedded |
| `open` | Open the DocuBrowse UI in your default browser |
| `duplist` | *(Not yet implemented)* List duplicate documents |
| `dupclean` | *(Not yet implemented)* Interactive TUI to remove duplicates |

### Global Options

```
--db PATH      Path to SQLite database (overrides config)
--port PORT    Server port (overrides config)
--config FILE  Path to config file
```

### Command Examples

```bash
./docubrowser.py start
./docubrowser.py start --port 9000 --db /data/custom.db

./docubrowser.py status
./docubrowser.py rescan --doc-dir /mnt/data/Documents
./docubrowser.py rescan --no-embed
./docubrowser.py stop
```

---

## Configuration

[↑ Top](#top)

DocuBrowse reads from the first config file it finds:

1. `/etc/docubrowse.config` (system-wide)
2. `./docubrowse.config` (local, next to `docubrowser.py`)

If neither exists, built-in defaults are used.

### Config File Format

```ini
# docubrowse.config
doc_dir = /mnt/data/Documents
db_path = /home/james/git/AI/DocuBrowse/docs.db
port    = 8643
work_dir = /home/james/git/AI/DocuBrowse
```

### Defaults

| Key | Default |
|-----|---------|
| `doc_dir` | `/mnt/data/Documents` |
| `db_path` | `<script dir>/docs.db` |
| `port` | `8643` |
| `work_dir` | `<script dir>` |

---

## Architecture

[↑ Top](#top)

```
┌─────────────────────────────────────┐
│  docubrowser.py  (CLI launcher)     │
│  ensure_ollama.py (prereq check)    │
└──────────┬──────────────────────────┘
           │ subprocess
           ↓
┌─────────────────────────────────────┐
│  doc_search.py  (HTTP server :8643) │
│  GET /  GET /api/search             │
│  GET /api/stats  /api/tags          │
└──────────┬──────────────────────────┘
           │ SQLite + Ollama HTTP
           ↓
┌─────────────────────────────────────┐
│  docs.db  (SQLite FTS5 + BLOBs)    │
│  Ollama   (nomic-embed-text:latest) │
└─────────────────────────────────────┘
```

### Key Scripts

| Script | Role |
|--------|------|
| `docubrowser.py` | CLI launcher — start/stop/rescan/status/embed |
| `ensure_ollama.py` | Checks/installs Ollama binary, service, and model |
| `doc_search.py` | HTTP server; serves UI and search API |
| `docubrowse_db.py` | SQLite schema and migrations |
| `scan_docs.py` | Document discovery and metadata extraction |
| `pdf_extractor.py` | PDF-specific metadata extractor |
| `embed_docs.py` | Sends documents to Ollama for embedding; stores in DB |

---

## API Endpoints

[↑ Top](#top)

Base URL: `http://localhost:8643`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serve `index.html` |
| `GET` | `/api/stats` | Total docs, embedded count, unique tag count |
| `GET` | `/api/tags` | Tag list with counts (≥3 occurrences) |
| `GET` | `/api/search` | Search with pagination |
| `GET` | `/api/config` | Current server configuration |
| `POST` | `/api/config` | Save configuration (stub) |

### Search Parameters

```
GET /api/search?q=QUERY&offset=0&mode=both
```

| Param | Values | Default |
|-------|--------|---------|
| `q` | search string | `""` (returns all docs) |
| `mode` | `both` \| `keyword` \| `semantic` | `both` |
| `offset` | integer | `0` |

### Search Response

```json
{
  "documents": [
    {
      "id": 1,
      "name": "doc.pdf",
      "title": "Document Title",
      "description": "First 300 chars of content...",
      "path": "/mnt/data/Documents/doc.pdf",
      "tags": ["tag1", "tag2"],
      "modified_at": "2026-06-07T...",
      "score": 0.95,
      "fts_score": 0.8,
      "sem_score": 0.98
    }
  ],
  "query": "QUERY",
  "count": 50,
  "total": 312,
  "offset": 0,
  "has_more": true,
  "mode": "both"
}
```

### Quick API Test

```bash
curl "http://localhost:8643/api/stats"
curl "http://localhost:8643/api/search?q=database&mode=both"
curl "http://localhost:8643/api/search?q=&offset=50"
```

---

## Search Algorithm

[↑ Top](#top)

Results are ranked by a merged score:

```
final_score = 0.3 × keyword_score + 0.7 × semantic_score
```

### Keyword Scoring

| Match | Boost |
|-------|-------|
| Query in title | +0.8 |
| Query in filename | +0.6 |
| Query in tags | +0.4 |
| Query in description | +0.3 |
| Token in title | +0.1 per token |
| Token in description | +0.05 per token |

### Semantic Scoring

- Cosine similarity between query embedding and document embedding
- Range: 0.0–1.0
- Minimum threshold for semantic-only mode: **0.30**

---

## File Structure

[↑ Top](#top)

```
DocuBrowse/
├── docubrowser.py          # CLI launcher (main entry point)
├── ensure_ollama.py        # Ollama prerequisite checker
├── doc_search.py           # HTTP server + search logic
├── docubrowse_db.py        # SQLite schema + migrations
├── scan_docs.py            # Document scanner + indexer
├── pdf_extractor.py        # PDF metadata extraction
├── embed_docs.py           # Embedding generation pipeline
├── index.html              # Frontend UI (dark/light theme)
├── docs.db                 # SQLite database (gitignored)
├── docubrowse.config       # Local config (optional)
├── README.md               # This file
├── status_docs/            # Project planning documents
├── data_grooming/          # Duplicate detection tools
│   ├── dedup_detector.py
│   └── dupe_clean.py
└── test_pdfs_live/         # 100 sample PDFs for testing
```

---

## Development

[↑ Top](#top)

### Adding New Document Formats (Phase 2b)

1. Create `<format>_extractor.py` returning:
   ```python
   {"title": ..., "author": ..., "description": ..., "success": True}
   ```
2. Update `scan_docs.py` to route the new extension to your extractor
3. Re-index: `./docubrowser.py rescan`

### Testing Search Quality

```bash
# Keyword search
curl "http://localhost:8643/api/search?q=database&mode=keyword"

# Semantic search
curl "http://localhost:8643/api/search?q=data storage&mode=semantic"

# Hybrid (default)
curl "http://localhost:8643/api/search?q=database&mode=both"

# Browse all (paginated)
curl "http://localhost:8643/api/search?q=&offset=0"
```

### Ollama Setup (Manual)

`./docubrowser.py start` handles this automatically, but you can also do it manually:

```bash
# Install Ollama (Linux)
curl -fsSL https://ollama.com/install.sh | sh

# Start the service
ollama serve

# Pull the embedding model
ollama pull nomic-embed-text:latest
```

---

## Known Limitations

[↑ Top](#top)

| Limitation | Status |
|------------|--------|
| PDF-only indexing | HTML, TXT, DOCX coming in Phase 2b |
| No config persistence in UI | Settings reset on page reload (Phase 3) |
| No duplicate detection UI | `duplist`/`dupclean` stubbed, coming in Phase 2 |
| No authentication | Local use only; API auth deferred to Phase 3+ |
| No binary file relationship tracking | Deferred to Phase 3+ |

---

## Roadmap

[↑ Top](#top)

### Phase 2b — Format Expansion
- HTML extractor with boilerplate stripping
- TXT/Markdown extractor
- DOCX extractor
- Scale to 10K documents

### Phase 2 — Housekeeping
- `duplist` — report duplicate documents by content hash
- `dupclean` — interactive TUI to choose which duplicates to remove

### Phase 3 — Polish
- Config persistence (load/save)
- Advanced filtering (date range, document type, author)
- Export results (CSV/JSON)
- Accessibility (WCAG 2.1 AA)

### Phase 3+ — Advanced
- Binary file relationship detection
- Document similarity clustering
- API key authentication
- Docker / containerized deployment

---

## Performance Notes

[↑ Top](#top)

| Metric | 100 docs | 10K docs (projected) |
|--------|----------|----------------------|
| Full-text search | ~8ms | ~15ms |
| Semantic search | ~60ms | ~80ms |
| Hybrid search | ~70ms | ~90ms |
| UI load time | ~500ms | ~500ms |
| DB size | ~122MB | ~500MB |
| Embedding generation | ~5 min | ~1 hour |

- Embeddings: 768-dimensional float32 vectors stored as BLOBs
- Batch size: 25 documents per embedding commit
- Query embeddings computed inline (not cached)

---

## Browser Support

[↑ Top](#top)

| Browser | Support |
|---------|---------|
| Chrome / Edge | ✅ Full |
| Firefox | ✅ Full |
| Safari | ✅ Full |
| Mobile (iOS/Android) | ✅ Responsive (1-column grid) |

---

## Keyboard Shortcuts

[↑ Top](#top)

| Key | Action |
|-----|--------|
| `Enter` | Execute search |
| `Esc` | Clear search (return to all documents) |
| Click tag | Filter by that tag |
| Click document title | Copy file path to clipboard |

---

## License

[↑ Top](#top)

MIT (placeholder — add your license here)

---

**DocuBrowse v0.1.0** — Built for fast, intelligent document search on your local filesystem.
