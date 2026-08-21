# DocuBrowse v1.0.3 — API Reference

**Date:** 2026-07-23
**Base URL:** `http://127.0.0.1:8643`
**Content-Type:** `application/json` (all API requests and responses)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Authentication and Security](#2-authentication-and-security)
   - 2.1 [CSRF Protection](#21-csrf-protection)
   - 2.2 [Host-Header Allowlist (DNS Rebinding Protection)](#22-host-header-allowlist-dns-rebinding-protection)
   - 2.3 [localhost-only Restriction on /api/open](#23-localhost-only-restriction-on-apiopen)
3. [Common Response Format](#3-common-response-format)
4. [Endpoint Reference](#4-endpoint-reference)
   - 4.1 [GET /api/status](#41-get-apistatus)
   - 4.2 [GET /api/search](#42-get-apisearch)
   - 4.3 [GET /api/synopsis](#43-get-apisynopsis)
   - 4.4 [GET /api/stats](#44-get-apistats)
   - 4.5 [GET /api/tags](#45-get-apitags)
   - 4.6 [GET /api/letters](#46-get-apiletters)
   - 4.7 [GET /api/config](#47-get-apiconfig)
   - 4.8 [GET /api/ignore-dirs](#48-get-apiignore-dirs)
   - 4.9 [GET /api/scan-dirs](#49-get-apiscan-dirs)
   - 4.10 [GET /api/browse](#410-get-apibrowse)
   - 4.11 [POST /api/open](#411-post-apiopen)
   - 4.12 [POST /api/delete](#412-post-apidelete)
   - 4.13 [POST /api/config](#413-post-apiconfig)
   - 4.14 [POST /api/ignore-dirs](#414-post-apiignore-dirs)
   - 4.15 [POST /api/scan-dirs](#415-post-apiscan-dirs)
   - 4.16 [GET /api/download](#416-get-apidownload)
   - 4.17 [POST /api/add-tags](#417-post-apiadd-tags)
   - 4.18 [POST /api/remove-tag](#418-post-apiremove-tag)
5. [Search Modes](#5-search-modes)
6. [Enterprise Tier](#6-enterprise-tier)
7. [Rate Limits and Performance Notes](#7-rate-limits-and-performance-notes)

---

## 1. Overview

DocuBrowse exposes a local HTTP API on port **8643** (default). All endpoints return JSON. By default the server binds to `127.0.0.1` only; it is not reachable from other machines unless the server is started with `--allow-remote`.

**Base URL (default):** `http://127.0.0.1:8643`

All API paths begin with `/api/`. The root path `/` and `/settings` serve the web UI (HTML files with the CSRF token injected). They are not part of the JSON API.

---

## 2. Authentication and Security

### 2.1 CSRF Protection

DocuBrowse uses a **per-process secret token** to protect all state-changing endpoints against Cross-Site Request Forgery (CSRF).

**How the token is distributed:**

When the server starts, it generates a random 32-byte URL-safe token with `secrets.token_urlsafe(32)`. Every HTML page served by the server has this token injected as a `<meta>` tag before the closing `</head>` tag:

```html
<meta name="csrf-token" content="<token>">
```

A cross-origin page cannot read this token because the HTML is protected by the browser's same-origin policy. The JSON API does not include `Access-Control-Allow-Origin` headers, so cross-origin JavaScript cannot read API responses either.

**How to send the token:**

All mutating endpoints (all POST requests, and GET `/api/browse`) require the token in the `X-CSRF-Token` request header:

```
X-CSRF-Token: <token>
```

The server validates the token using `secrets.compare_digest` (constant-time comparison to prevent timing attacks). Requests with a missing or invalid token receive `403 Forbidden`.

**Defense in depth — Origin/Referer check:**

Before checking the token, the server also inspects the `Origin` and `Referer` headers. If either is present and does not originate from the same host as the `Host` header (or from a loopback address), the request is rejected with `403 Forbidden`. This provides a secondary layer of protection independent of the token.

**Endpoints requiring CSRF token:**

| Endpoint | CSRF Required |
|---|---|
| GET /api/status | No |
| GET /api/search | No |
| GET /api/synopsis | No |
| GET /api/stats | No |
| GET /api/tags | No |
| GET /api/letters | No |
| GET /api/config | No |
| GET /api/ignore-dirs | No |
| GET /api/scan-dirs | No |
| **GET /api/browse** | **Yes** |
| **POST /api/open** | **Yes** |
| **POST /api/delete** | **Yes** |
| **POST /api/config** | **Yes** |
| **POST /api/ignore-dirs** | **Yes** |
| **POST /api/scan-dirs** | **Yes** |
| **GET /api/download** | **Yes** |
| **POST /api/add-tags** | **Yes** |
| **POST /api/remove-tag** | **Yes** |

### 2.2 Host-Header Allowlist (DNS Rebinding Protection)

Every request (GET and POST) is validated against an allowlist of permitted `Host` header values before any processing occurs. This prevents DNS rebinding attacks, where a malicious domain is made to resolve to `127.0.0.1` so that a browser can make cross-origin requests to the server.

**Default (local-only) mode:** Only `localhost`, `127.0.0.1`, and `::1` are accepted. If a port is included in the `Host` header, it must match the port the server is listening on. Requests with any other `Host` value receive `403 Forbidden`.

**Remote (--allow-remote) mode:** The server additionally accepts the machine's own hostname and FQDN (resolved at startup), and any IP-literal `Host` header. This still blocks DNS rebinding because rebinding depends on an attacker-controlled *domain name* resolving to the server — a raw IP or the server's own known hostname is safe.

HTTP/1.0 clients that omit the `Host` header entirely are accepted, because only a client on the local loopback interface can reach a loopback-bound socket.

### 2.3 localhost-only Restriction on /api/open

`POST /api/open` checks that the TCP connection originated from `127.0.0.1` or `::1`, even when the server is running with `--allow-remote`. This prevents remote clients from triggering arbitrary file opens on the server's desktop.

### 2.4 CORS (Cross-Origin Resource Sharing)

When the server is started with `--allow-remote`, all API responses include CORS headers to support the DocuBrowse companion app (which runs as a Tauri WebView with origin `tauri://localhost`):

```
Access-Control-Allow-Origin: *
Access-Control-Allow-Headers: X-CSRF-Token, Content-Type
Access-Control-Allow-Methods: GET, POST, OPTIONS
```

The server also responds to `OPTIONS` preflight requests with a `204 No Content` and the same CORS headers.

In local-only mode (default, no `--allow-remote`), CORS headers are **not** sent. This is intentional — localhost-bound servers have no cross-origin clients.

**Security note:** CORS headers do not weaken the existing security model. CSRF tokens still protect all mutating endpoints, and the document index check still gates file access on `/api/download` and `/api/open`.

---

## 3. Common Response Format

All JSON API responses follow a consistent envelope:

```json
{
  "ok": true
}
```

or on failure:

```json
{
  "ok": false,
  "error": "Human-readable error message"
}
```

The `ok` field is always present and is a boolean. Additional fields depend on the endpoint. HTTP status codes for errors at the transport level (403, 404, 500) are returned as plain text, not JSON.

---

## 4. Endpoint Reference

### 4.1 GET /api/status

**CSRF required:** No

Health and readiness check. Returns the server version, uptime, and connectivity status of the database and Ollama. Suitable for use with monitoring agents or load-balancer health checks — no first-party HTML is required to call this endpoint.

The `ok` field is `true` only when both the database and Ollama are reachable. Model availability does not affect `ok` — keyword search works without embeddings.

**Parameters:** None

**Response (FOSS tier):**

| Field | Type | Description |
|---|---|---|
| ok | boolean | true if DB and Ollama are both reachable |
| version | string | Server version string (e.g. "0.8.3") |
| uptime_seconds | number | Seconds since the server process started |
| timestamp | string | ISO 8601 timestamp |
| components.db.ok | boolean | true if the SQLite database is reachable |
| components.db.error | string | Present only if db.ok is false; error message |
| semantic_ready | boolean | true if semantic search is available (DB up, Ollama up, embeddings exist, embedding model present) |
| components.ollama.ok | boolean | true if Ollama responded within 5 seconds |
| components.ollama.error | string | Present only if ollama.ok is false; error message |

**Response (Enterprise tier — additional fields):**

See [Section 6: Enterprise Tier](#6-enterprise-tier).

**Example request:**

```bash
curl http://127.0.0.1:8643/api/status
```

**Example response (FOSS tier, healthy):**

```json
{
  "ok": true,
  "version": "1.0.3",
  "uptime_seconds": 3721.4,
  "timestamp": "2026-06-27T14:22:08.113245",
  "semantic_ready": true,
  "components": {
    "db": {
      "ok": true
    },
    "ollama": {
      "ok": true
    }
  }
}
```

The `semantic_ready` field is `false` when any of these conditions are not met: database reachable, Ollama reachable, at least one document has embeddings, and the configured embedding model is loaded in Ollama. Clients should use this to disable or hide semantic search controls when it would return empty results.

**Example response (Ollama unreachable):**

```json
{
  "ok": false,
  "version": "1.0.3",
  "uptime_seconds": 42.1,
  "timestamp": "2026-06-27T09:00:42.000000",
  "components": {
    "db": { "ok": true },
    "ollama": {
      "ok": false,
      "error": "<urlopen error [Errno 111] Connection refused>"
    }
  }
}
```

---

### 4.2 GET /api/search

**CSRF required:** No

Search the document index. Supports three modes: keyword (FTS5 BM25), semantic (vector cosine similarity), and hybrid (weighted blend of both). See [Section 5: Search Modes](#5-search-modes) for details on scoring.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| q | string | (empty) | Search query. If omitted or empty, returns all documents in alphabetical order. |
| mode | string | `both` | Search mode: `keyword`, `semantic`, or `both` (hybrid). |
| offset | integer | `0` | Zero-based offset into the result set for pagination. |
| limit | integer | `50` | Number of results to return. Clamped to the range [1, 200]. |
| letter | string | (none) | When `q` is empty, filter by first letter of title. Single A-Z character, or `0-9` for titles starting with a digit or symbol. |

**Response fields:**

| Field | Type | Description |
|---|---|---|
| documents | array | Array of document objects (see below). |
| query | string | The query string that was searched. |
| mode | string | The search mode used (omitted for empty-query browse). |
| count | integer | Number of documents in this response page. |
| total | integer | Total number of matching documents. |
| offset | integer | The offset used for this page. |
| has_more | boolean | true if more results exist beyond this page. |

**Document object fields:**

| Field | Type | Description |
|---|---|---|
| id | integer | Internal document ID. |
| name | string | Filename (e.g. "report.pdf"). |
| title | string | Extracted document title, or filename if no title. |
| author | string | Extracted author metadata (may be empty). |
| subject | string | Extracted subject metadata (may be empty). |
| description | string | Extracted description or abstract (may be empty). |
| path | string | Absolute path on the server filesystem. |
| tags | array of strings | Tags associated with this document. |
| score | number | Relevance score in range [0, 1]. 1.0 for empty-query browse. |
| fts_score | number | Keyword sub-score (0..1). Present on non-empty queries in `both` mode. |
| sem_score | number | Semantic sub-score (0..1). Present on non-empty queries in `both` mode. |
| modified_at | string | File modification timestamp (ISO 8601 or empty). |

**Example request (hybrid search):**

```bash
curl "http://127.0.0.1:8643/api/search?q=network+observability&mode=both&limit=5"
```

**Example response:**

```json
{
  "documents": [
    {
      "id": 142,
      "name": "linux_perf_guide.pdf",
      "title": "Linux Performance Observability",
      "author": "Brendan Gregg",
      "subject": "",
      "description": "A guide to eBPF, perf, and tracing tools for Linux system analysis.",
      "path": "/home/james/docs/linux_perf_guide.pdf",
      "tags": ["linux", "performance", "observability"],
      "score": 0.847,
      "fts_score": 0.612,
      "sem_score": 0.921,
      "modified_at": "2025-11-03T10:14:22"
    }
  ],
  "query": "network observability",
  "mode": "both",
  "count": 1,
  "total": 1,
  "offset": 0,
  "has_more": false
}
```

**Example request (browse all, paginated):**

```bash
curl "http://127.0.0.1:8643/api/search?limit=20&offset=40"
```

**Example request (alphabetic filter):**

```bash
curl "http://127.0.0.1:8643/api/search?letter=P&limit=50"
```

**Error cases:**

- Malformed `limit` or `offset` values return a 500 error (Python `int()` conversion failure). Always pass valid integers.

---

### 4.3 GET /api/synopsis

**CSRF required:** No

Generate or retrieve an AI-written synopsis for a document. The synopsis is generated by Ollama using the `dolphin3:latest` model, prompted with the document's title, description, and text snippet. The result is cached in the database; subsequent calls for the same path return immediately.

This endpoint can block for **30–90 seconds** on the first call if Ollama must load the model into memory after a fresh start. Plan for a generous timeout in any client that calls this endpoint.

**Query parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| path | string | Yes | Absolute path of the document (must be in the index). |

**Response fields:**

| Field | Type | Description |
|---|---|---|
| ok | boolean | true on success. |
| synopsis | string | The generated synopsis text (one paragraph, no markdown). Present only on success. |
| cached | boolean | true if the synopsis was retrieved from the database cache; false if freshly generated. |
| error | string | Human-readable failure reason. Present only when ok is false. |

**Error reason messages:**

| Condition | Error message |
|---|---|
| No text available to summarize | "No description or text is available for this document to summarize." |
| Ollama model still loading | "The AI model is still loading after a recent restart — this can take a minute the first time. Please wait a moment and try again." |
| Ollama unreachable | "Couldn't reach the AI model (Ollama). Make sure it's running, then try again." |
| Path not in index | "Path not in document index" |
| Missing path parameter | "Missing path parameter" |

**Example request:**

```bash
curl "http://127.0.0.1:8643/api/synopsis?path=/home/james/docs/linux_perf_guide.pdf"
```

**Example response (freshly generated):**

```json
{
  "ok": true,
  "synopsis": "An authoritative deep dive into the performance tools that power modern Linux observability, this guide walks engineers through eBPF tracing, the perf subsystem, and flame graph visualization with clarity and hands-on precision. Whether you are diagnosing a latency spike in production or building your first tracing pipeline, this text equips you with both the theory and the command-line vocabulary to see inside a running system.",
  "cached": false
}
```

**Example response (cached):**

```json
{
  "ok": true,
  "synopsis": "An authoritative deep dive...",
  "cached": true
}
```

**Example response (failure — Ollama not running):**

```json
{
  "ok": false,
  "error": "Couldn't reach the AI model (Ollama). Make sure it's running, then try again."
}
```

---

### 4.4 GET /api/stats

**CSRF required:** No

Returns aggregate counts from the document index.

**Parameters:** None

**Response fields:**

| Field | Type | Description |
|---|---|---|
| total_docs | integer | Total number of documents in the index. |
| embedded | integer | Number of documents with a stored embedding vector. |
| unique_tags | integer | Number of distinct tags across all documents. |
| timestamp | string | ISO 8601 timestamp. |

**Example request:**

```bash
curl http://127.0.0.1:8643/api/stats
```

**Example response:**

```json
{
  "total_docs": 4812,
  "embedded": 4790,
  "unique_tags": 317,
  "timestamp": "2026-06-15T14:22:08.113245"
}
```

---

### 4.5 GET /api/tags

**CSRF required:** No

Returns all tags that appear on at least 3 documents, sorted case-insensitively. The list is capped at 200 entries.

**Parameters:** None

**Response fields:**

| Field | Type | Description |
|---|---|---|
| tags | array | Array of tag objects, each with `tag` (string) and `count` (integer). |

**Example request:**

```bash
curl http://127.0.0.1:8643/api/tags
```

**Example response:**

```json
{
  "tags": [
    { "tag": "linux", "count": 47 },
    { "tag": "networking", "count": 31 },
    { "tag": "python", "count": 18 }
  ]
}
```

---

### 4.6 GET /api/letters

**CSRF required:** No

Returns the set of distinct first letters (uppercased) present in the indexed document titles or filenames. Used by the web UI to populate the alphabetic index bar. Only non-empty letters are returned.

**Parameters:** None

**Response fields:**

| Field | Type | Description |
|---|---|---|
| letters | array of strings | Sorted list of uppercase letters present in the index. |

**Example request:**

```bash
curl http://127.0.0.1:8643/api/letters
```

**Example response:**

```json
{
  "letters": ["A", "B", "C", "D", "E", "F", "G", "H", "I", "L", "M", "N", "O", "P", "R", "S", "T", "U", "V", "W"]
}
```

---

### 4.7 GET /api/config

**CSRF required:** No

Returns the current server configuration, read from `docubrowse.config`. The server checks `/etc/docubrowse.config` first, then the directory containing `doc_search.py`. If no config file is found, defaults are returned.

The `DOCUBROWSE_DOC_DIR`, `DOCUBROWSE_WORK_DIR`, and `DOCUBROWSE_PORT` environment variables override the corresponding config-file values in this response, so a container that injects settings via the environment (with no config file) still reports them here. See the Administrator Guide, section 5.1, for the full list.

**Parameters:** None

**Response fields:**

| Field | Type | Description |
|---|---|---|
| docPath | string | The primary document directory (`doc_dir` in config), or empty string. |
| workDir | string | The working directory (`work_dir` in config). |
| port | integer | The configured port number. |
| installed | boolean | true if the active config was loaded from `/etc/docubrowse.config`. |
| configSource | string or null | Absolute path of the config file that was loaded, or null if none found. |

**Example request:**

```bash
curl http://127.0.0.1:8643/api/config
```

**Example response:**

```json
{
  "docPath": "/home/james/docs",
  "workDir": "/home/james/git/AI/DocuBrowse",
  "port": 8643,
  "installed": false,
  "configSource": "/home/james/git/AI/DocuBrowse/docubrowse.config"
}
```

---

### 4.8 GET /api/ignore-dirs

**CSRF required:** No

Returns the list of directories that are excluded from scanning. These are loaded from `ignore_dirs.txt` in the database directory.

**Parameters:** None

**Response fields:**

| Field | Type | Description |
|---|---|---|
| dirs | array of strings | Sorted list of absolute directory paths that are ignored during scan. |

**Example request:**

```bash
curl http://127.0.0.1:8643/api/ignore-dirs
```

**Example response:**

```json
{
  "dirs": [
    "/home/james/.cache",
    "/home/james/docs/private",
    "/tmp"
  ]
}
```

---

### 4.9 GET /api/scan-dirs

**CSRF required:** No

Returns the list of additional top-level directories configured for scanning. These are loaded from `scan_dirs.txt` in the database directory. This is a bookkeeping list — actual scanning is triggered via the CLI (`docubrowser scan --doc-dir <DIR>`), not through the API.

**Parameters:** None

**Response fields:**

| Field | Type | Description |
|---|---|---|
| dirs | array of strings | Sorted list of configured scan directory paths. |

**Example request:**

```bash
curl http://127.0.0.1:8643/api/scan-dirs
```

**Example response:**

```json
{
  "dirs": [
    "/home/james/books",
    "/home/james/docs",
    "/mnt/nas/reference"
  ]
}
```

---

### 4.10 GET /api/browse

**CSRF required:** Yes

Browse the server filesystem for directory selection in the Settings UI. Returns the contents of a given directory path (subdirectories only; hidden directories starting with `.` are excluded). If the path does not exist or is not a directory, falls back to `/`.

Results are capped at 201 entries. If the directory has a parent, a `..` entry is included as the first element.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| path | string | `/` | Absolute path of the directory to list. |

**Response fields:**

| Field | Type | Description |
|---|---|---|
| path | string | The resolved absolute path that was listed. |
| entries | array | Array of directory entry objects (see below). |
| error | string | Present only on unexpected errors. |

**Entry object fields:**

| Field | Type | Description |
|---|---|---|
| name | string | Directory name (or `..` for the parent entry). |
| path | string | Absolute path of this entry. |
| parent | boolean | Present and `true` only for the `..` parent entry. |

**Example request:**

```bash
curl -H "X-CSRF-Token: <token>" \
  "http://127.0.0.1:8643/api/browse?path=/home/james"
```

**Example response:**

```json
{
  "path": "/home/james",
  "entries": [
    { "name": "..", "path": "/home", "parent": true },
    { "name": "books", "path": "/home/james/books" },
    { "name": "docs", "path": "/home/james/docs" },
    { "name": "projects", "path": "/home/james/projects" }
  ]
}
```

**Error cases:**

- `403 Forbidden` — missing or invalid CSRF token, or cross-origin request.
- On `PermissionError` reading the directory, the entries array is returned empty (no error key).
- On other exceptions, an `error` key is present and `entries` is an empty array.

---

### 4.11 POST /api/open

**CSRF required:** Yes
**localhost-only:** Yes (connection must originate from 127.0.0.1 or ::1 even with --allow-remote)

Opens a file using the desktop's default application. The path must be present in the document index — arbitrary filesystem paths are not accepted. The server tries an ordered chain of openers: `gio open` (GNOME/Flatpak), `kde-open5` (KDE Plasma 5), `kde-open` (KDE Plasma 4), `xdg-open` (generic XDG fallback). Only tools found on `PATH` are tried.

**How success is determined:** Each opener is launched and waited on for up to 1 second. If it is still running after 1 second, the GUI app is assumed to be launching and the call returns success. If the opener exits within 1 second with exit code 0, it is also a success. If it exits with a non-zero code, the next opener in the chain is tried.

**Parameters (query string):**

| Parameter | Type | Required | Description |
|---|---|---|---|
| path | string | Yes | Absolute path of the document to open (must be in the index). |

**Response fields:**

| Field | Type | Description |
|---|---|---|
| ok | boolean | true if an opener was launched successfully. |
| path | string | The path that was opened. Present only on success. |
| error | string | Error type or message. Present only on failure. |
| message | string | Human-readable detail. Present on `unmounted` and `missing` errors. |
| detail | string | stderr output from the last failed opener. Present when all openers fail. |
| hint | string | Suggested fix command (e.g. how to set a default app with `xdg-mime`). Present when all openers fail and the MIME type is known. |

**Error values for the `error` field:**

| Value | Meaning |
|---|---|
| "Missing path parameter" | `path` query parameter was not provided. |
| "Path not in document index" | The path exists on disk but is not indexed. |
| "unmounted" | The file's storage device does not appear to be mounted. |
| "missing" | The file was in the index but is no longer on disk. |
| "No file opener found on PATH (tried gio, kde-open5, kde-open, xdg-open)" | None of the opener tools are installed. |
| "No default application for this file type (...)" | All openers were tried and all failed. |

**Example request:**

```bash
curl -X POST \
  -H "X-CSRF-Token: <token>" \
  "http://127.0.0.1:8643/api/open?path=/home/james/docs/linux_perf_guide.pdf"
```

**Example response (success):**

```json
{
  "ok": true,
  "path": "/home/james/docs/linux_perf_guide.pdf"
}
```

**Example response (all openers failed, MIME type known):**

```json
{
  "ok": false,
  "error": "No default application for this file type (application/epub+zip)",
  "detail": "xdg-open: no method available for opening '/home/james/docs/book.epub'",
  "hint": "To fix: run  xdg-mime default <app>.desktop application/epub+zip  or edit ~/.config/mimeapps.list"
}
```

**Note on the `hint` field:** The hint is only present when all openers in the chain fail *and* the file's MIME type could be determined. When the MIME type is unknown, the hint is omitted.

---

### 4.12 POST /api/delete

**CSRF required:** Yes

Removes a document from the index, with optional blacklisting or disk deletion. The path must be in the index — arbitrary filesystem deletions are not possible. Database removal cascades to the document's tags and embedding vectors.

**Parameters (query string):**

| Parameter | Type | Required | Description |
|---|---|---|---|
| path | string | Yes | Absolute path of the document to delete. |
| mode | string | No | Deletion mode: `db_only` (remove from index only — default), `blacklist` (remove from index and add to `scan_blacklist.txt` so future scans skip it), or `delete_file` (remove from index and delete the file from disk). |

**Response fields:**

| Field | Type | Description |
|---|---|---|
| ok | boolean | true on success. |
| deleted | string | The path that was deleted. Present only on success. |
| error | string | Error message. Present only on failure. |

**Example request:**

```bash
curl -X POST \
  -H "X-CSRF-Token: <token>" \
  "http://127.0.0.1:8643/api/delete?path=/home/james/docs/old_report.pdf"
```

**Example response (success):**

```json
{
  "ok": true,
  "deleted": "/home/james/docs/old_report.pdf"
}
```

**Error cases:**

- `"Missing path parameter"` — `path` query parameter was not provided.
- `"Path not in document index"` — the path is not tracked; no action taken.
- `"Could not delete file: <OS error>"` — OS refused the deletion (e.g., permissions); the database record is not removed.
- `"DB delete failed: <error>"` — the file was deleted from disk but the database removal failed.

---

### 4.13 POST /api/config

**CSRF required:** Yes

Writes a new `docubrowse.config` file next to `doc_search.py`. `workDir` is required. `docPath` and `port` are optional. The existing `allow_remote` value is preserved from the current config file (it is not settable through this endpoint to prevent accidental remote exposure).

**Request body (JSON):**

| Field | Type | Required | Description |
|---|---|---|---|
| docPath | string | No | Primary document directory path. Can be empty. |
| workDir | string | Yes | Working directory path. |
| port | integer | No | Port number. Defaults to current server port. |

**Response fields:**

| Field | Type | Description |
|---|---|---|
| message | string | Confirmation message including the path written. |
| configSource | string | Absolute path of the config file that was written. |

**Example request:**

```bash
curl -X POST \
  -H "X-CSRF-Token: <token>" \
  -H "Content-Type: application/json" \
  -d '{"docPath": "/home/james/docs", "workDir": "/home/james/git/AI/DocuBrowse", "port": 8643}' \
  http://127.0.0.1:8643/api/config
```

**Example response:**

```json
{
  "message": "Config saved to /home/james/git/AI/DocuBrowse/docubrowse.config",
  "configSource": "/home/james/git/AI/DocuBrowse/docubrowse.config"
}
```

**Error cases:**

- `400 Bad Request` — invalid JSON body, or `workDir` is empty.
- `500 Internal Server Error` — OS refused to write the config file (permissions).

---

### 4.14 POST /api/ignore-dirs

**CSRF required:** Yes

Add or remove a directory from the ignored-directories list (`ignore_dirs.txt`). Adding a directory also immediately purges all already-indexed documents under that path from the database. Removing a directory only updates the list file; the caller must run a rescan to re-index documents under it.

**Request body (JSON):**

| Field | Type | Required | Description |
|---|---|---|---|
| action | string | Yes | `"add"` or `"remove"`. |
| path | string | Yes | Absolute or `~`-prefixed directory path to add or remove. Resolved to absolute before writing. |

**Response fields:**

| Field | Type | Description |
|---|---|---|
| ok | boolean | true on success. |
| dirs | array of strings | Updated sorted list of ignored directories. |
| purged | integer | Number of documents purged from the index (present only for `add`). |

**Example request (add):**

```bash
curl -X POST \
  -H "X-CSRF-Token: <token>" \
  -H "Content-Type: application/json" \
  -d '{"action": "add", "path": "/home/james/docs/private"}' \
  http://127.0.0.1:8643/api/ignore-dirs
```

**Example response (add):**

```json
{
  "ok": true,
  "dirs": ["/home/james/.cache", "/home/james/docs/private"],
  "purged": 12
}
```

**Example request (remove):**

```bash
curl -X POST \
  -H "X-CSRF-Token: <token>" \
  -H "Content-Type: application/json" \
  -d '{"action": "remove", "path": "/home/james/docs/private"}' \
  http://127.0.0.1:8643/api/ignore-dirs
```

**Example response (remove):**

```json
{
  "ok": true,
  "dirs": ["/home/james/.cache"]
}
```

**Error cases:**

- `400 Bad Request` — invalid JSON, missing `action` or `path`, or invalid path.

---

### 4.15 POST /api/scan-dirs

**CSRF required:** Yes

Add or remove a directory from the scan-directories bookkeeping list (`scan_dirs.txt`). This list tracks which top-level directories the user intends to scan. It does not trigger a scan — scans are run via the CLI. No documents are purged from the database on removal.

**Request body (JSON):**

| Field | Type | Required | Description |
|---|---|---|---|
| action | string | Yes | `"add"` or `"remove"`. |
| path | string | Yes | Absolute or `~`-prefixed directory path. Resolved to absolute before writing. |

**Response fields:**

| Field | Type | Description |
|---|---|---|
| ok | boolean | true on success. |
| dirs | array of strings | Updated sorted list of configured scan directories. |

**Example request (add):**

```bash
curl -X POST \
  -H "X-CSRF-Token: <token>" \
  -H "Content-Type: application/json" \
  -d '{"action": "add", "path": "/mnt/nas/reference"}' \
  http://127.0.0.1:8643/api/scan-dirs
```

**Example response:**

```json
{
  "ok": true,
  "dirs": ["/home/james/docs", "/mnt/nas/reference"]
}
```

**Error cases:**

- `400 Bad Request` — invalid JSON, missing `action` or `path`, or invalid path.

---

### 4.16 GET /api/download

**CSRF required:** Yes
**localhost-only:** No (usable from remote clients with `--allow-remote`)

Stream a file's bytes to the client for local saving and opening. This is the remote-client counterpart to `/api/open`: instead of opening the file on the server's desktop, it sends the raw bytes so the client application can save to a temp file and open with the client OS's default app.

The path must be present in the document index — arbitrary filesystem paths are rejected, same as `/api/open`.

**Query parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| path | string | Yes | Absolute path of the document (must be in the index). |

**Success response:**

HTTP 200 with binary body. Headers:

| Header | Value |
|---|---|
| Content-Type | Detected MIME type, or `application/octet-stream` |
| Content-Disposition | `attachment; filename="<basename>"` |
| Content-Length | File size in bytes |
| Cache-Control | `no-store` |

The body is streamed in 64 KB chunks — no full-file buffering.

**Error responses (JSON):**

| Condition | HTTP | Response |
|---|---|---|
| Missing path parameter | 200 | `{"ok": false, "error": "Missing path parameter"}` |
| Path not in index | 200 | `{"ok": false, "error": "Path not in document index"}` |
| File missing from disk | 404 | `{"ok": false, "error": "missing", "message": "..."}` |
| Mount unavailable | 404 | `{"ok": false, "error": "unmounted", "message": "..."}` |
| Invalid CSRF token | 403 | `Forbidden: missing or invalid CSRF token` |

**Example request:**

```bash
curl -H "X-CSRF-Token: <token>" \
  "https://192.168.1.50:8643/api/download?path=/home/james/docs/linux_perf_guide.pdf" \
  -o linux_perf_guide.pdf
```

---

### 4.17 POST /api/add-tags

**CSRF required:** Yes

Append one or more tags to a document. Existing tags are preserved (uses `INSERT OR IGNORE` on the unique constraint). Tag names are lowercased and trimmed. Source is set to `user`.

**Query parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| path | string | Yes | Absolute path of the document (must be in the index). |
| tags | string | Yes | Comma-separated list of tags to add. |

**Response fields:**

| Field | Type | Description |
|---|---|---|
| ok | boolean | `true` on success. |
| path | string | The document path. |
| added | integer | Number of new tags actually inserted (0 if all existed). |
| tags | array | Full current tag list for this document. |

**Example request:**

```bash
curl -X POST -H "X-CSRF-Token: <token>" \
  "https://localhost:8643/api/add-tags?path=/home/james/docs/guide.pdf&tags=security,reference"
```

**Example response:**

```json
{
  "ok": true,
  "path": "/home/james/docs/guide.pdf",
  "added": 2,
  "tags": ["linux", "reference", "security"]
}
```

---

### 4.18 POST /api/remove-tag

**CSRF required:** Yes

Remove a single tag from a document.

**Query parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| path | string | Yes | Absolute path of the document (must be in the index). |
| tag | string | Yes | The tag to remove (case-insensitive). |

**Response fields:**

| Field | Type | Description |
|---|---|---|
| ok | boolean | `true` on success. |
| path | string | The document path. |
| removed | integer | Number of rows deleted (0 if the tag wasn't present). |
| tags | array | Full current tag list for this document after removal. |

**Example request:**

```bash
curl -X POST -H "X-CSRF-Token: <token>" \
  "https://localhost:8643/api/remove-tag?path=/home/james/docs/guide.pdf&tag=hidden"
```

**Example response:**

```json
{
  "ok": true,
  "path": "/home/james/docs/guide.pdf",
  "removed": 1,
  "tags": ["linux", "reference", "security"]
}
```

---

## 5. Search Modes

`GET /api/search` supports three modes, selected with the `mode` parameter.

### keyword

Full-text search using SQLite's FTS5 engine with BM25 ranking. Column weights are tuned to boost title and author matches above body text:

| FTS5 column | BM25 weight |
|---|---|
| name (filename) | 6.0 |
| title | 8.0 |
| author | 7.0 |
| subject | 5.0 |
| description | 3.0 |
| content_snippet | 3.0 |
| tags | 4.0 |

Results with a normalized BM25 score below 0.01 are excluded. BM25 raw scores are negative (more negative = better match); they are sign-flipped and normalized to [0, 1] against the best score in the result set.

**Phrase search:** Wrap terms in double quotes to match an exact consecutive sequence of words: `"import fmt"`. This is passed directly to FTS5 as a phrase expression. Bare words are tokenized and matched with prefix matching (`word*`). Mixed queries are supported: `golang "import fmt"` matches documents containing "golang" and/or the exact phrase "import fmt".

User input is always FTS5-escaped before query construction, preventing injection of FTS5 operators (AND, OR, NOT, NEAR, column filter syntax).

**Noise floor:** Results must have a score above 0.01 to be returned (prevents low-confidence junk results from cluttering pages).

### semantic

Semantic (meaning-based) search using cosine similarity between the query's embedding vector and each stored document embedding. Embeddings are generated by Ollama using the `nomic-embed-text` model (768-dimensional vectors).

The query text is truncated to 2000 characters before embedding. The embedding matrix is cached in-process and recomputed only when the embeddings table changes (row count or latest `updated_at`). When NumPy is available, similarity is computed as a single matrix-vector product; otherwise it falls back to per-vector Python cosine.

**Noise floor:** Results with cosine similarity below 0.30 are excluded.

Documents without stored embeddings are invisible to semantic search. Run `docubrowser embed` to generate embeddings for newly scanned documents.

### both (hybrid — default)

Combines keyword and semantic scores with a weighted blend:

```
final_score = 0.30 × keyword_score + 0.70 × semantic_score
```

The union of all documents matching either mode is scored. Documents that match only one mode receive a zero score for the other component. Results with a final score below 0.01 are excluded.

The 70/30 weighting favors semantic relevance, which handles synonyms and paraphrasing that keyword search misses, while the keyword component anchors results containing exact terminology.

---

## 6. Enterprise Tier

The `enterprise_mode` flag on `DocSearchHandler` defaults to `False` in the standard distribution. When an enterprise access layer is active, it sets `DocSearchHandler.enterprise_mode = True` at startup.

When `enterprise_mode` is `True`, the `GET /api/status` response includes additional fields:

**Additional `components.db` fields:**

| Field | Type | Description |
|---|---|---|
| doc_count | integer | Total number of indexed documents. |
| embedded_count | integer | Number of documents with stored embeddings. |

**Additional `components.ollama` fields:**

| Field | Type | Description |
|---|---|---|
| embedding_model.name | string | Configured embedding model name (e.g. "nomic-embed-text"). |
| embedding_model.present | boolean | Whether the embedding model is loaded in Ollama. |
| synopsis_model.name | string | Configured synopsis model name (e.g. "dolphin3:latest"). |
| synopsis_model.present | boolean | Whether the synopsis model is loaded in Ollama. |

**Additional top-level fields:**

| Field | Type | Description |
|---|---|---|
| config.allow_remote | boolean | Whether the server is accepting remote connections. |
| config.port | integer | The port the server is listening on. |

**Example enterprise status response:**

```json
{
  "ok": true,
  "version": "1.0.3",
  "uptime_seconds": 7200.0,
  "timestamp": "2026-06-27T16:00:00.000000",
  "components": {
    "db": {
      "ok": true,
      "doc_count": 4812,
      "embedded_count": 4790
    },
    "ollama": {
      "ok": true,
      "embedding_model": {
        "name": "nomic-embed-text",
        "present": true
      },
      "synopsis_model": {
        "name": "dolphin3:latest",
        "present": true
      }
    }
  },
  "config": {
    "allow_remote": false,
    "port": 8643
  }
}
```

Model presence is determined by checking Ollama's `/api/tags` endpoint. The comparison strips the `:latest` tag suffix so that `"nomic-embed-text:latest"` and `"nomic-embed-text"` both match the configured name. Model absence does not affect the top-level `ok` field.

---

## 7. Rate Limits and Performance Notes

**Rate limiting:** The server does not implement rate limiting. All endpoints are available without throttling.

**Concurrency:** The server uses Python's `ThreadingHTTPServer`, which spawns a new thread per request. Concurrent requests are handled in parallel, with SQLite connections opened and closed per request.

**Synopsis generation latency:** `GET /api/synopsis` can take **30–90 seconds** on the first call after a server restart. Ollama must load the `dolphin3:latest` model into memory before the first generation can begin. The server uses a 90-second timeout (`SYNOPSIS_TIMEOUT_SECS = 90`) to accommodate this. Subsequent calls on a warm Ollama instance are typically faster. Clients should set their HTTP timeout to at least 120 seconds when calling this endpoint.

**Semantic search latency:** On the first search after a restart, the embedding matrix is loaded from the database into memory. For large indexes this may take a few seconds. After the initial load, the matrix is cached in-process and queries are fast (a single matrix-vector multiply). The cache is automatically invalidated when documents are added or deleted.

**Search embedding latency:** Each non-empty search request embeds the query string via Ollama (`nomic-embed-text`). This round-trip adds roughly 100–500ms depending on hardware. In `keyword`-only mode, this embedding call is skipped.

**Embedding coverage:** Documents without stored embeddings are invisible to `semantic` and `both` mode searches. After scanning new documents, run `docubrowser embed` to generate embeddings before expecting semantic results for those documents.
