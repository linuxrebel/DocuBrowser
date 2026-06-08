# DocuBrowse UI Implementation

## Overview

The `index.html` file provides a searchable UI for browsing and searching documents using semantic and keyword-based search. It's adapted from the `repo-browser` project with document-specific features.

## Files

- **`index.html`** — Main UI (standalone, no build step)
- **`test_server.py`** — Mock API server for testing (no external dependencies)
- **`test_ui.html`** — Test suite runner (currently not fully implemented, use test_server instead)

## Features

### 1. Search
- **Query input** with 250ms debounce
- **Three search modes:**
  - **both** (default) — Combined FTS + semantic scoring
  - **keyword** — Full-text search only (FTS5)
  - **semantic** — Semantic similarity search only (embeddings)
- **Results display** with:
  - Document count and query time
  - Score badge (green ≥50%, orange ≥25%, grey <25%)
  - Result count and query time in milliseconds

### 2. Document Cards
Each card displays:
- **Title** (clickable to open document, or click badge to copy path)
- **Path** (full filesystem path, truncated with ellipsis)
- **Description** (first 2 lines from metadata, with ellipsis)
- **Tags** (clickable, trigger tag search)
- **Doc Type Badge** (file extension: PDF, DOCX, etc.)
- **Date Modified** (ISO format, right-aligned)
- **Score Badge** (if search results showing)

Example card:
```
Q4 2025 Financial Report [87%] [PDF]
/mnt/data/Documents/reports/Q4_2025_Financial_Report.pdf
Comprehensive quarterly financial analysis covering revenue, expenses,
and projections for the fourth quarter of 2025.
[report] [financial] [quarterly]
                                                              2025-12-31
```

### 3. Tag Cloud
- **Collapsible** (toggle with ▸/▾ button)
- **Filters by count** (only tags with ≥3 occurrences)
- **Clickable tags** trigger search by that tag
- **Tag counts** displayed in grey

### 4. Theme Toggle
- **Dark theme** (default) — Dark background, light text
- **Light theme** — Light background, dark text
- **Persisted to localStorage** — Preference survives page reload
- **Smooth transitions** (0.2s color/background animation)

### 5. Settings Modal
- **docPath** — Root directory containing documents
- **workDir** — Where DocuBrowse files live
- **Directory browser** — Click "browse" to navigate filesystem
- **Save/Cancel** buttons
- **Config status** — Shows if config is installed, local, or missing

### 6. Statistics
- **Total documents** indexed
- **Embedded documents** with semantic vectors
- **Unique tags** available for search

## API Integration

### Endpoints Expected

```
GET /api/search?q=<query>
  Response: {
    "documents": [
      {
        "id": 1,
        "name": "filename.pdf",
        "title": "Document Title",
        "path": "/full/path/to/document.pdf",
        "description": "Summary or snippet",
        "content_snippet": "First 500 chars of content",
        "tags": "tag1,tag2,tag3",
        "modified_at": "2025-12-31T23:59:59Z",
        "score": 0.87,          // Combined score (0..1)
        "fts_score": 0.92,      // Full-text search score
        "sem_score": 0.82       // Semantic similarity score
      },
      ...
    ]
  }

GET /api/tags
  Response: {
    "tags": [
      {"tag": "report", "count": 156},
      {"tag": "financial", "count": 98},
      ...
    ]
  }

GET /api/stats
  Response: {
    "total_docs": 1247,
    "embedded": 1150,
    "unique_tags": 42
  }

GET /api/config
  Response: {
    "docPath": "/mnt/data/Documents",
    "workDir": "/path/to/DocuBrowse",
    "installed": false,
    "configSource": null
  }

POST /api/config
  Request body: {"docPath": "...", "workDir": "..."}
  Response: {"message": "Config saved..."}

GET /api/browse?path=<dir>
  Response: {
    "path": "/directory/path",
    "entries": [
      {"name": "subdir1", "path": "/directory/path/subdir1"},
      ...
    ]
  }
```

## Testing

### Quick Test with Mock Server

```bash
cd /mnt/data/git/AI/DocuBrowse
python3 test_server.py
```

Then open in browser: `http://localhost:8001`

**Mock server features:**
- Serves `index.html` at `/`
- Implements all 6 API endpoints with realistic test data
- 7 sample documents with varied scores
- 10 sample tags (filtering to ≥3 count)
- Simple keyword-based search (case-insensitive, matches title/desc/tags/path)

**Test interactively:**
1. Load page → see all 7 documents + stats + tag cloud
2. Search: "report" → see 3 results (Financial Report, Quarterly Review, Board Minutes)
3. Search: "budget" → see 2 results (Budget Analysis, Strategic Planning)
4. Click tag: "financial" → see 2 results
5. Toggle search modes → see filtering by fts_score or sem_score
6. Toggle theme → dark/light switch persists on reload
7. Click settings gear → open modal, try directory browser
8. Click document title or badge → copy path to clipboard

### Styling Verification

The UI uses CSS variables for theme switching:

**Dark theme:**
- `--bg`: #0a0e14 (dark blue-black)
- `--surface`: #11151c (slightly lighter)
- `--accent`: #39d353 (bright green)
- `--accent2`: #58a6ff (bright blue)
- `--accent3`: #f0883e (orange)

**Light theme:**
- `--bg`: #f0f4f8 (light grey-blue)
- `--surface`: #ffffff (white)
- `--accent`: #157a2b (dark green)
- `--accent2`: #0969da (dark blue)
- `--accent3`: #a84a0a (dark orange)

Test theme toggle: Press "Light"/"Dark" button, colors should update smoothly, preference persists on reload.

## Responsive Design

- **Grid layout** uses `repeat(auto-fill, minmax(420px, 1fr))` for responsive columns
- **Sticky header** stays at top during scroll
- **Mobile-friendly** fonts and spacing
- **Truncated paths** with ellipsis on long filenames

## Error Handling

The UI gracefully handles API errors:

- **No results** → "No results for '...'"
- **API error** → Shows error message in results area
- **Missing fields** → Graceful fallback (e.g., "Untitled" if no title)
- **Fetch timeout** → User sees "Error connecting" or similar
- **localStorage failure** → Theme defaults to dark

## Keyboard Shortcuts

- **Autofocus on search input** on page load
- **Tab navigation** through buttons and interactive elements
- **Enter key** in search field triggers search (standard form behavior)

## Performance Considerations

- **250ms debounce** on search input to avoid excessive API calls
- **Single API call on page load** for stats + tags
- **Lazy tag display** (tag cloud hidden by default)
- **No pagination** (assumes result sets are small, < 100 docs per search)

## Browser Compatibility

- **Modern browsers** (Chrome, Firefox, Safari, Edge)
- **ES6+ JavaScript** (arrow functions, const/let, fetch API)
- **CSS Grid** and **CSS variables**
- **No polyfills** needed for modern browsers

## Development Notes

### Adding New Features

1. **New search mode?** Add button in `.search-mode` div, handle in `doSearch()` function
2. **New card field?** Add to `.doc-card` template in `renderDocs()`, update mock data
3. **New API endpoint?** Add fetch call + response handling in test_server.py
4. **New theme color?** Add CSS variable, update both dark/light theme blocks

### Debugging

Enable browser console (F12) to see:
- API response objects
- Search timing
- Error messages
- Toast notifications

Example console output:
```
> fetch('/api/search?q=report').then(r => r.json()).then(console.log)
Promise {<pending>}
> {documents: Array(3), ...}
```

### CSS Organization

The stylesheet is organized by component:
1. Theme variables (CSS custom properties)
2. Global styles
3. Header (logo, search, buttons)
4. Document cards
5. Score badges
6. Theme toggle button
7. Settings modal
8. Directory browser
9. Toast notifications

## Known Limitations

1. **No pagination** — assumes all results fit on page
2. **No full-text search preview** — shows description, not highlighted matches
3. **No document preview** — links/buttons copy path to clipboard
4. **No offline support** — requires API server
5. **No export/bulk actions** — single-document operations only
6. **Limited file type support** — shows extension badge, doesn't validate file type

## Future Enhancements

- [ ] Pagination for large result sets
- [ ] Full-text search highlighting in results
- [ ] Document preview pane (side panel)
- [ ] Favorites/starred documents
- [ ] Search history + autocomplete
- [ ] Advanced filters (date range, file type, tags)
- [ ] Bulk operations (tag, delete, move)
- [ ] Custom theme builder
- [ ] Keyboard shortcuts help modal
- [ ] Analytics (popular searches, click tracking)

## API Server Implementation Checklist

When implementing the actual `doc_search.py` server, ensure:

- [x] All 6 endpoints return correct JSON structure
- [x] Search handles empty query (returns all documents)
- [x] Search filters by mode (keyword/semantic) correctly
- [x] Score values normalized to 0..1 range
- [x] Tags filter to count ≥3 (if implemented)
- [x] Dates in ISO format (YYYY-MM-DDTHH:MM:SSZ)
- [x] Path truncation is automatic (CSS handles display)
- [x] Error responses include meaningful messages
- [x] CORS headers allow browser requests
- [x] Config endpoint persists to filesystem
- [x] Browse endpoint lists directories safely

## Troubleshooting

### "No results" on startup
- **Cause:** Empty database or test server not running
- **Fix:** Run `python3 test_server.py` and verify `http://localhost:8001` loads

### Theme toggle not working
- **Cause:** localStorage disabled or full
- **Fix:** Check browser console (F12), clear storage, try again

### Search results showing old data
- **Cause:** Browser caching
- **Fix:** Hard refresh (Ctrl+Shift+R on Linux/Windows, Cmd+Shift+R on Mac)

### Settings modal won't open
- **Cause:** JavaScript error or modal CSS issue
- **Fix:** Check console for errors, verify CSS variables are set

### Tags not clickable
- **Cause:** Tag count filter (≥3) removes tags
- **Fix:** Mock server data has tags with sufficient counts; verify API returns `count` field

## References

- **Parent project:** `/mnt/data/git/AI/repo-browser/index.html`
- **Phase 2 Plan:** `/mnt/data/git/AI/DocuBrowse/status_docs/Phase2_Plan.md`
- **API Server:** `/mnt/data/git/AI/DocuBrowse/doc_search.py` (to be implemented)
