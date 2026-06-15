#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
DocuBrowse search server.
HTTP server on port 8643 with merged keyword + semantic search.
"""

import ipaddress
import json
import os
import secrets
import shutil
import math
import re
import socket
import sqlite3
import struct
import threading
import subprocess
import sys
import time
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import URLError

from docubrowse_db import get_db, check_missing_path, delete_document

try:
    import numpy as _np
except Exception:  # numpy is normally present (dup_detect uses it); degrade gracefully
    _np = None


DEFAULT_PORT = 8643
OLLAMA_HOST = "http://localhost:11434"
EMBEDDING_MODEL = "nomic-embed-text"
SYNOPSIS_MODEL = "dolphin3:latest"
SERVER_VERSION = "0.8.1"

_SERVER_START_TIME = time.time()  # set at import; used by /api/status
# Cold Ollama starts (e.g. right after a reboot) need to load the model into
# memory before the first generation can begin, which can take well over 30s
# on top of the generation time itself. Use a generous timeout so the first
# request after startup doesn't spuriously fail.
SYNOPSIS_TIMEOUT_SECS = 90


def cosine_similarity(v1: list, v2: list) -> float:
    """Calculate cosine similarity between two vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0

    dot_product = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(b * b for b in v2))

    if mag1 == 0 or mag2 == 0:
        return 0.0

    return dot_product / (mag1 * mag2)


def blob_to_vector(blob: bytes) -> list:
    """Convert embedding blob back to float32 vector."""
    if not blob or len(blob) < 4:
        return None
    vec_len = len(blob) // 4
    return list(struct.unpack(f'{vec_len}f', blob))


def embed_text(text: str) -> list:
    """Get embedding from Ollama."""
    if not text or not text.strip():
        return None

    try:
        url = f"{OLLAMA_HOST}/api/embed"
        payload = json.dumps({
            "model": EMBEDDING_MODEL,
            "input": text[:2000]
        }).encode('utf-8')

        request = Request(url, data=payload, method='POST')
        request.add_header('Content-Type', 'application/json')

        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
            # /api/embed returns {"embeddings": [[...]]} (list of vectors),
            # while the older /api/embeddings returned {"embedding": [...]}.
            # Accept either shape so semantic search keeps working regardless
            # of the Ollama endpoint/version. (Matches embed_docs.py.)
            return data.get('embedding') or (data.get('embeddings') or [None])[0]
    except Exception as e:
        sys.stderr.write(f"[embed_text] embedding request failed: {e}\n")
        return None


def generate_synopsis(title: str, description: str, snippet: str) -> tuple:
    """Ask Ollama for a one-paragraph, back-cover-style synopsis.

    Returns (text, error_reason). On success, text is the generated
    synopsis and error_reason is None. On failure, text is None and
    error_reason is one of: "empty" (no source text to work from),
    "timeout" (Ollama didn't respond in time — often because it's still
    loading the model into memory after a fresh start), or "error" (any
    other failure, e.g. Ollama not running).
    """
    context = "\n\n".join(p for p in [description or "", snippet or ""] if p.strip())
    if not context.strip():
        return None, "empty"

    prompt = (
        "Write a one-paragraph synopsis of the document below, in the style "
        "of a book jacket / Kindle store description — engaging and "
        "informative, written for someone deciding whether to open it. "
        "Do not use markdown, headings, or bullet points. Output only the "
        "paragraph itself, with no preamble.\n\n"
        f"Title: {title or '(untitled)'}\n\n"
        f"Document excerpt:\n{context[:4000]}"
    )

    try:
        url = f"{OLLAMA_HOST}/api/generate"
        payload = json.dumps({
            "model": SYNOPSIS_MODEL,
            "prompt": prompt,
            "stream": False,
        }).encode('utf-8')

        request = Request(url, data=payload, method='POST')
        request.add_header('Content-Type', 'application/json')

        with urlopen(request, timeout=SYNOPSIS_TIMEOUT_SECS) as response:
            data = json.loads(response.read().decode('utf-8'))
            text = (data.get('response') or '').strip()
            return (text, None) if text else (None, "error")
    except socket.timeout:
        return None, "timeout"
    except URLError as e:
        if isinstance(e.reason, socket.timeout):
            return None, "timeout"
        return None, "error"
    except Exception:
        return None, "error"


def normalize_score(score: float, max_val: float = 1.0) -> float:
    """Normalize score to 0..1 range."""
    return min(1.0, max(0.0, score / max_val if max_val > 0 else 0))


# ── Cached embedding matrix for semantic search ───────────────────────────────
# Loading every embedding BLOB and running a Python cosine loop on each request
# was the dominant cost of search. Instead we cache an L2-normalized matrix of
# all embeddings in-process and score a query with a single matrix-vector
# product. The cache is invalidated when the embeddings table's row count or
# latest updated_at changes (covers adds, deletes and re-embeds).
_EMB_CACHE = {"key": None, "ids": None, "matrix": None, "vectors": None}
_EMB_LOCK = threading.Lock()


def _load_embedding_matrix(conn):
    """Return (ids, matrix, vectors) for all stored embeddings, cached.

    matrix is an L2-normalized float32 ndarray (N, dim) when numpy is
    available, else None — in which case callers fall back to per-vector
    cosine using the parallel python 'vectors' list.
    """
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(MAX(updated_at), '') FROM doc_embeddings"
    ).fetchone()
    key = (row[0], row[1])
    if _EMB_CACHE["key"] == key:
        return _EMB_CACHE["ids"], _EMB_CACHE["matrix"], _EMB_CACHE["vectors"]
    with _EMB_LOCK:
        if _EMB_CACHE["key"] == key:  # another thread rebuilt it while we waited
            return _EMB_CACHE["ids"], _EMB_CACHE["matrix"], _EMB_CACHE["vectors"]
        ids, vectors = [], []
        for doc_id, blob in conn.execute(
            "SELECT doc_id, embedding FROM doc_embeddings"
        ):
            vec = blob_to_vector(blob)
            if vec:
                ids.append(doc_id)
                vectors.append(vec)
        matrix = None
        if _np is not None and vectors:
            matrix = _np.asarray(vectors, dtype=_np.float32)
            norms = _np.linalg.norm(matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            matrix = matrix / norms
        _EMB_CACHE.update({"key": key, "ids": ids, "matrix": matrix,
                           "vectors": vectors})
        return ids, matrix, vectors


def _semantic_scores(conn, query_vec) -> dict:
    """Map doc_id -> cosine similarity for every embedded document."""
    if not query_vec:
        return {}
    ids, matrix, vectors = _load_embedding_matrix(conn)
    if not ids:
        return {}
    if _np is not None and matrix is not None:
        qv = _np.asarray(query_vec, dtype=_np.float32)
        n = _np.linalg.norm(qv)
        if n == 0:
            return {}
        sims = matrix @ (qv / n)  # (N,) cosine similarities, one vectorized pass
        return {doc_id: float(s) for doc_id, s in zip(ids, sims)}
    # numpy unavailable: per-vector cosine on the cached vectors (no blob reload)
    return {doc_id: cosine_similarity(query_vec, vec)
            for doc_id, vec in zip(ids, vectors)}


def _fts_match_expr(q: str):
    """Build a safe FTS5 MATCH expression: prefix-OR over the query's word
    tokens. Quoting each token neutralizes FTS operators (AND/OR/NOT/NEAR,
    quotes, colons, etc.) so arbitrary user input can't break the query."""
    tokens = re.findall(r'\w+', q.lower())
    if not tokens:
        return None
    return ' OR '.join(f'"{t}"*' for t in tokens)


def _keyword_scores(conn, q: str) -> dict:
    """Map doc_id -> normalized BM25 keyword score (0..1) via the FTS5 index.

    Replaces the old full-corpus Python substring scan. Column weights echo
    the previous hand-tuned field boosts (title/author highest)."""
    expr = _fts_match_expr(q)
    if not expr:
        return {}
    try:
        # doc_fts column order: name,title,author,subject,description,
        # content_snippet,tags.
        rows = conn.execute(
            "SELECT rowid, bm25(doc_fts, 6.0, 8.0, 7.0, 5.0, 3.0, 3.0, 4.0) AS rank "
            "FROM doc_fts WHERE doc_fts MATCH ? ORDER BY rank",
            (expr,)
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    if not rows:
        return {}
    # bm25 returns more-negative for better matches; flip then normalize 0..1.
    raw = {rowid: -rank for rowid, rank in rows}
    best = max(raw.values())
    if best <= 0:
        return {}
    return {doc_id: val / best for doc_id, val in raw.items()}


# doc_fts is contentless and has no FK, so it can hold orphan rowids from past
# deletes. Keyword (bm25) hits are pruned against this cached set of live
# document ids so phantom rowids don't inflate result totals or short a page.
# (Semantic hits come from doc_embeddings, which CASCADE-delete with documents,
# so they need no such pruning.)
_DOCID_CACHE = {"key": None, "ids": None}


def _valid_doc_ids(conn) -> set:
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(MAX(updated_at), '') FROM documents"
    ).fetchone()
    key = (row[0], row[1])
    if _DOCID_CACHE["key"] == key:
        return _DOCID_CACHE["ids"]
    ids = {r[0] for r in conn.execute("SELECT id FROM documents")}
    _DOCID_CACHE.update({"key": key, "ids": ids})
    return ids


class DocSearchHandler(BaseHTTPRequestHandler):
    """HTTP request handler for document search."""

    db_path     = None          # Will be set by server
    server_port = DEFAULT_PORT  # Will be set by server
    csrf_token  = None          # Per-process secret, set by server at startup
    allow_remote = False        # True when bound for LAN access (opt-in)
    enterprise_mode = False     # True when enterprise access layer is active;
                                # enables extended /api/status response
    allowed_hostnames = frozenset(('localhost', '127.0.0.1', '::1'))

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def _host_allowed(self) -> bool:
        """Reject requests whose Host header isn't a local loopback name.

        The server binds to localhost only, but a browser tricked by DNS
        rebinding (attacker.com re-resolved to 127.0.0.1) would still send
        requests here with a foreign Host header. Allow only loopback hosts,
        and if a port is present it must match the port we're serving on.
        """
        host = self.headers.get('Host', '')
        if not host:
            # HTTP/1.0 clients may omit Host; only a local client can reach a
            # loopback-bound socket without one.
            return True
        hostname, _, port = host.rpartition(':')
        if not hostname:           # no colon → rpartition put it all in `port`
            hostname, port = port, ''
        hostname = hostname.strip('[]').lower()   # [::1] → ::1
        if port and port != str(self.server_port):
            return False
        # Loopback is always allowed.
        if hostname in ('localhost', '127.0.0.1', '::1'):
            return True
        # Remote (LAN) access is opt-in. When enabled, allow this machine's own
        # hostnames and any IP-literal Host. Requiring a known name or a literal
        # IP still blocks DNS-rebinding, which depends on an attacker-controlled
        # *domain name* resolving to us.
        if self.allow_remote:
            if hostname in self.allowed_hostnames:
                return True
            try:
                ipaddress.ip_address(hostname)
                return True
            except ValueError:
                return False
        return False

    def _guard_mutation(self) -> bool:
        """Gate state-changing / sensitive endpoints against CSRF.

        The primary defense is a per-process secret token that is injected
        into the served HTML pages. A cross-origin attacker page cannot read
        that token (the HTML is same-origin protected, and the JSON API no
        longer returns Access-Control-Allow-Origin), so it cannot forge the
        X-CSRF-Token header this requires. As defense in depth, any Origin/
        Referer that isn't same-origin with the addressed Host (or loopback)
        is rejected — this works whether bound to localhost or the LAN.

        Sends a 403 and returns False on failure; returns True if allowed.
        """
        host_hdr = self.headers.get('Host', '')
        host_host = host_hdr.rsplit(':', 1)[0].strip('[]').lower() if host_hdr else ''
        for hdr in ('Origin', 'Referer'):
            val = self.headers.get(hdr)
            if val:
                o = urlparse(val).hostname
                o = o.lower() if o else o
                if o not in (host_host, 'localhost', '127.0.0.1', '::1'):
                    self.error_response(403, "Forbidden: cross-origin request rejected")
                    return False
        token = self.headers.get('X-CSRF-Token', '')
        if not self.csrf_token or not secrets.compare_digest(token, self.csrf_token):
            self.error_response(403, "Forbidden: missing or invalid CSRF token")
            return False
        return True

    def do_GET(self):
        """Handle GET requests."""
        if not self._host_allowed():
            self.error_response(403, "Forbidden: invalid Host header")
            return
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            if path == '/':
                self.serve_file('index.html')
            elif path == '/settings':
                self.serve_file('settings.html')
            elif path == '/api/stats':
                self.handle_stats()
            elif path == '/api/tags':
                self.handle_tags()
            elif path == '/api/letters':
                self.handle_letters()
            elif path == '/api/search':
                self.handle_search(query)
            elif path == '/api/config':
                self.handle_config()
            elif path == '/api/synopsis':
                self.handle_synopsis(query)
            elif path == '/api/ignore-dirs':
                self.handle_ignore_dirs()
            elif path == '/api/scan-dirs':
                self.handle_scan_dirs()
            elif path == '/api/browse':
                self.handle_browse(query)
            elif path == '/api/status':
                self.handle_status()
            else:
                self.error_response(404, "Not found")
        except Exception as e:
            self.error_response(500, str(e))

    def do_POST(self):
        """Handle POST requests."""
        if not self._host_allowed():
            self.error_response(403, "Forbidden: invalid Host header")
            return
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            # All POST routes are state-changing — gate them all against CSRF.
            if not self._guard_mutation():
                return
            if path == '/api/config':
                self.handle_config_post()
            elif path == '/api/ignore-dirs':
                self.handle_ignore_dirs_post()
            elif path == '/api/scan-dirs':
                self.handle_scan_dirs_post()
            elif path == '/api/delete':
                self.handle_delete(query)
            elif path == '/api/open':
                self.handle_open(query)
            else:
                self.error_response(404, "Not found")
        except Exception as e:
            self.error_response(500, str(e))

    def handle_stats(self):
        """GET /api/stats - Return database statistics."""
        conn = get_db(self.db_path)

        total_docs = conn.execute(
            'SELECT COUNT(*) FROM documents'
        ).fetchone()[0]

        embedded = conn.execute(
            'SELECT COUNT(*) FROM doc_embeddings'
        ).fetchone()[0]

        unique_tags = conn.execute(
            'SELECT COUNT(DISTINCT tag) FROM doc_tags'
        ).fetchone()[0]

        conn.close()

        self.json_response({
            "total_docs": total_docs,
            "embedded": embedded,
            "unique_tags": unique_tags,
            "timestamp": datetime.now().isoformat()
        })

    def handle_status(self):
        """GET /api/status - Health and readiness check for monitoring systems.

        No CSRF required — monitoring agents must be able to probe this endpoint
        without first-party HTML.

        Response depth is tiered by deployment mode:
          FOSS (enterprise_mode=False): minimal — ok, version, uptime, db.ok,
            ollama.ok. Enough for a load-balancer or simple watchdog.
          Enterprise (enterprise_mode=True): full — adds doc/embedded counts,
            model presence, and config details for richer dashboards and alerts.

        The 'ok' field is True only when both DB and Ollama are reachable. Model
        presence does not affect 'ok' — keyword search works without embeddings.
        """
        uptime = time.time() - _SERVER_START_TIME

        # DB connectivity — use try/finally to guarantee close on any path
        db_ok = False
        db_error = None
        doc_count = 0
        embedded_count = 0
        try:
            conn = get_db(self.db_path)
            try:
                doc_count = conn.execute(
                    "SELECT COUNT(*) FROM documents"
                ).fetchone()[0]
                embedded_count = conn.execute(
                    "SELECT COUNT(*) FROM doc_embeddings"
                ).fetchone()[0]
                db_ok = True
            finally:
                conn.close()
        except Exception as e:
            db_error = str(e)

        # Ollama connectivity — lightweight /api/tags hit, 5 s socket timeout
        ollama_ok = False
        ollama_error = None
        ollama_models = []
        try:
            req = Request(f"{OLLAMA_HOST}/api/tags", method="GET")
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                ollama_models = [m.get("name", "") for m in data.get("models", [])]
                ollama_ok = True
        except Exception as e:
            ollama_error = str(e)

        # Normalize model names for comparison: strip tag suffix from both sides
        # so "nomic-embed-text:latest" and "nomic-embed-text" both match.
        def _model_present(configured_name):
            base = configured_name.split(":")[0]
            return any(base == m.split(":")[0] for m in ollama_models)

        overall_ok = db_ok and ollama_ok

        # ── FOSS tier: minimal response ───────────────────────────────────
        status = {
            "ok": overall_ok,
            "version": SERVER_VERSION,
            "uptime_seconds": round(uptime, 1),
            "timestamp": datetime.now().isoformat(),
            "components": {
                "db": {
                    "ok": db_ok,
                    **({"error": db_error} if db_error else {}),
                },
                "ollama": {
                    "ok": ollama_ok,
                    **({"error": ollama_error} if ollama_error else {}),
                },
            },
        }

        # ── Enterprise tier: extended response ────────────────────────────
        # enterprise_mode is set True by the enterprise access layer when it
        # starts doc_search.py; defaults False in the FOSS distribution.
        if self.enterprise_mode:
            status["components"]["db"].update({
                "doc_count": doc_count,
                "embedded_count": embedded_count,
            })
            status["components"]["ollama"].update({
                "embedding_model": {
                    "name": EMBEDDING_MODEL,
                    "present": _model_present(EMBEDDING_MODEL),
                },
                "synopsis_model": {
                    "name": SYNOPSIS_MODEL,
                    "present": _model_present(SYNOPSIS_MODEL),
                },
            })
            status["config"] = {
                "allow_remote": self.allow_remote,
                "port": self.server_port,
            }

        self.json_response(status)

    def handle_tags(self):
        """GET /api/tags - Return all tags with counts."""
        conn = get_db(self.db_path)

        tags_data = conn.execute('''
            SELECT tag, COUNT(*) as count
            FROM doc_tags
            GROUP BY tag
            HAVING count >= 3
            ORDER BY tag COLLATE NOCASE ASC
            LIMIT 200
        ''').fetchall()

        conn.close()

        tags = [{"tag": row[0], "count": row[1]} for row in tags_data]

        self.json_response({"tags": tags})

    def handle_letters(self):
        """GET /api/letters - Return set of first letters present in all doc titles."""
        conn = get_db(self.db_path)
        rows = conn.execute(
            "SELECT DISTINCT upper(substr(COALESCE(title, name, ''), 1, 1)) AS letter "
            "FROM documents WHERE letter != ''"
        ).fetchall()
        conn.close()
        letters = sorted(r[0] for r in rows if r[0])
        self.json_response({"letters": letters})

    def handle_search(self, query: dict):
        """GET /api/search - Search documents."""
        q = query.get('q', [''])[0].strip()
        mode = query.get('mode', ['both'])[0]  # both, keyword, semantic
        offset = int(query.get('offset', ['0'])[0])
        limit = max(1, min(200, int(query.get('limit', ['50'])[0])))

        # Empty query: return documents in alphabetical order with pagination
        if not q:
            # Optional first-letter filter for the alphabetic index bar.
            # 'letter' is a single A-Z character, or '0-9' for digits/symbols.
            letter = query.get('letter', [''])[0].strip().upper()
            where_clause = ''
            where_params = []
            if letter == '0-9':
                where_clause = "WHERE upper(substr(COALESCE(d.title, d.name, ''), 1, 1)) NOT GLOB '[A-Z]'"
            elif len(letter) == 1 and letter.isalpha():
                where_clause = "WHERE upper(substr(COALESCE(d.title, d.name, ''), 1, 1)) = ?"
                where_params.append(letter)

            conn = get_db(self.db_path)

            # Get total count (matching the same filter)
            total_count = conn.execute(
                f'SELECT COUNT(*) FROM documents d {where_clause}', where_params
            ).fetchone()[0]

            # Get paginated results
            all_docs = conn.execute(f'''
                SELECT d.id, d.name, d.title, d.author, d.subject, d.description, d.path,
                       d.modified_at, GROUP_CONCAT(dt.tag, ',') as tags
                FROM documents d
                LEFT JOIN doc_tags dt ON d.id = dt.doc_id
                {where_clause}
                GROUP BY d.id
                ORDER BY d.title COLLATE NOCASE ASC LIMIT ? OFFSET ?
            ''', where_params + [limit, offset]).fetchall()
            conn.close()

            results = []
            for doc_row in all_docs:
                doc_id, name, title, author, subject, desc, path, modified_at, tags_str = doc_row
                results.append({
                    "id": doc_id,
                    "name": name,
                    "title": title,
                    "author": author or "",
                    "subject": subject or "",
                    "description": desc or "",
                    "path": path,
                    "tags": [t.strip() for t in (tags_str or '').split(',') if t.strip()],
                    "date": modified_at or "",
                    "score": 1.0
                })

            has_more = (offset + limit) < total_count
            self.json_response({
                "documents": results,
                "query": "",
                "count": len(results),
                "total": total_count,
                "offset": offset,
                "has_more": has_more,
                "limited": True
            })
            return

        # ── Non-empty query: hybrid keyword (FTS5 BM25, index-backed) +
        #    semantic (cached embedding matrix). Scores are computed over id
        #    maps only; document metadata is fetched for the requested page
        #    alone instead of loading the whole corpus per request. ──────────
        conn = get_db(self.db_path)

        kw_scores = _keyword_scores(conn, q) if mode in ('both', 'keyword') else {}
        if kw_scores:  # drop orphan FTS rowids that no longer map to a document
            valid = _valid_doc_ids(conn)
            kw_scores = {k: v for k, v in kw_scores.items() if k in valid}
        sem_scores = _semantic_scores(conn, embed_text(q)) if mode in ('both', 'semantic') else {}

        # Build the scored candidate set per mode: (doc_id, final, fts, sem)
        scored = []
        if mode == 'keyword':
            for doc_id, fts in kw_scores.items():
                if fts > 0.01:
                    scored.append((doc_id, fts, fts, 0.0))
        elif mode == 'semantic':
            for doc_id, sem in sem_scores.items():
                if sem >= 0.30:  # noise floor for semantic-only results
                    scored.append((doc_id, sem, 0.0, sem))
        else:  # both
            for doc_id in (set(kw_scores) | set(sem_scores)):
                fts = kw_scores.get(doc_id, 0.0)
                sem = sem_scores.get(doc_id, 0.0)
                final = 0.3 * fts + 0.7 * sem
                if final > 0.01:
                    scored.append((doc_id, final, fts, sem))

        scored.sort(key=lambda x: x[1], reverse=True)
        total_results = len(scored)
        page = scored[offset:offset + limit]

        # Fetch metadata only for the page's documents.
        results = []
        if page:
            id_order = [doc_id for doc_id, *_ in page]
            placeholders = ','.join('?' for _ in id_order)
            meta = {}
            for r in conn.execute(f'''
                SELECT d.id, d.name, d.title, d.author, d.subject, d.description,
                       d.path, d.modified_at, GROUP_CONCAT(dt.tag, ',') as tags
                FROM documents d
                LEFT JOIN doc_tags dt ON d.id = dt.doc_id
                WHERE d.id IN ({placeholders})
                GROUP BY d.id
            ''', id_order):
                meta[r[0]] = r
            for doc_id, final, fts, sem in page:
                row = meta.get(doc_id)
                if not row:
                    continue
                _id, name, title, author, subject, desc, path, modified_at, tags_str = row
                results.append({
                    "id": _id,
                    "name": name,
                    "title": title or name,
                    "author": author or "",
                    "subject": subject or "",
                    "description": desc or "",
                    "path": path,
                    "tags": [t.strip() for t in (tags_str or '').split(',') if t.strip()],
                    "modified_at": modified_at,
                    "score": round(final, 3),
                    "fts_score": round(fts, 3),
                    "sem_score": round(sem, 3),
                })

        conn.close()

        has_more = (offset + limit) < total_results
        self.json_response({
            "documents": results,
            "query": q,
            "mode": mode,
            "count": len(results),
            "total": total_results,
            "offset": offset,
            "has_more": has_more
        })

    def _desktop_env(self):
        """Build an environment dict with the vars xdg-open/xdg-mime need to
        reach the user's desktop session bus and launch GUI apps.

        The server process may have been started from a shell/session where
        these are missing or set to bogus values (e.g.
        DBUS_SESSION_BUS_ADDRESS=disabled:), in which case xdg-open silently
        fails to launch anything even though it exits 0."""
        env = os.environ.copy()
        uid = os.getuid()

        runtime_dir = env.get('XDG_RUNTIME_DIR')
        if not runtime_dir or not os.path.isdir(runtime_dir):
            runtime_dir = f'/run/user/{uid}'
        env['XDG_RUNTIME_DIR'] = runtime_dir

        bus_addr = env.get('DBUS_SESSION_BUS_ADDRESS')
        bus_path = os.path.join(runtime_dir, 'bus')
        if not bus_addr or 'disabled' in bus_addr or not os.path.exists(bus_path):
            if os.path.exists(bus_path):
                bus_addr = f'unix:path={bus_path}'
            else:
                bus_addr = None
        if bus_addr:
            env['DBUS_SESSION_BUS_ADDRESS'] = bus_addr

        if not env.get('DISPLAY'):
            env['DISPLAY'] = ':0'

        if not env.get('WAYLAND_DISPLAY'):
            env['WAYLAND_DISPLAY'] = 'wayland-0'

        if not env.get('XAUTHORITY') or not os.path.exists(env['XAUTHORITY']):
            try:
                for name in os.listdir(runtime_dir):
                    if name.startswith('xauth_'):
                        env['XAUTHORITY'] = os.path.join(runtime_dir, name)
                        break
            except OSError:
                pass

        return env

    def handle_open(self, query: dict):
        """GET /api/open?path=<encoded-path> - Open a file with xdg-open."""
        path = query.get('path', [''])[0].strip()
        if not path:
            self.json_response({"ok": False, "error": "Missing path parameter"})
            return

        # Security: path must be in the index (not arbitrary filesystem access)
        conn = get_db(self.db_path)
        row = conn.execute('SELECT id FROM documents WHERE path = ?', (path,)).fetchone()
        conn.close()
        if not row:
            self.json_response({"ok": False, "error": "Path not in document index"})
            return

        p = Path(path)
        if not p.exists():
            status = check_missing_path(path)
            if status == "unmounted":
                self.json_response({"ok": False, "error": "unmounted",
                                     "message": f"Cannot verify — the device for this path does not appear to be mounted: {path}"})
            else:
                self.json_response({"ok": False, "error": "missing",
                                     "message": f"File not found on disk: {path}"})
            return

        # Check if a default app is registered before firing xdg-open.
        # xdg-mime query default needs a MIME type; fall back to Python's
        # mimetypes module, then to a raw xdg-mime filetype query.
        env = self._desktop_env()
        try:
            import mimetypes
            mime, _ = mimetypes.guess_type(str(p))
            if not mime:
                # Ask xdg-mime directly (handles freedesktop magic bytes)
                r = subprocess.run(
                    ['xdg-mime', 'query', 'filetype', str(p)],
                    capture_output=True, text=True, timeout=5, env=env,
                )
                mime = r.stdout.strip() or None

            if mime:
                r2 = subprocess.run(
                    ['xdg-mime', 'query', 'default', mime],
                    capture_output=True, text=True, timeout=5, env=env,
                )
                handler = r2.stdout.strip()
                if not handler:
                    self.json_response({
                        "ok": False,
                        "error": f"No default application for this file type ({mime})"
                    })
                    return

            # Prefer `gio open` - it talks to the desktop session over D-Bus
            # and reliably launches the default app under KDE/GNOME. Fall
            # back to xdg-open if gio isn't available.
            opener = ['gio', 'open', str(p)] if shutil.which('gio') else ['xdg-open', str(p)]
            proc = subprocess.Popen(opener,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    start_new_session=True,
                                    env=env)
            # The gio/xdg-open launcher spawns the real app and exits almost
            # immediately; reap it in a detached thread so it doesn't linger as
            # a zombie in this long-lived server.
            threading.Thread(target=proc.wait, daemon=True).start()
            self.json_response({"ok": True, "path": path})
        except Exception as e:
            self.json_response({"ok": False, "error": f"xdg-open failed: {e}"})

    def handle_delete(self, query: dict):
        """GET /api/delete?path=<encoded-path> - Delete a file from disk and DB."""
        path = query.get('path', [''])[0].strip()
        if not path:
            self.json_response({"ok": False, "error": "Missing path parameter"})
            return

        # Security: path must be in the index (not arbitrary filesystem access)
        conn = get_db(self.db_path)
        row = conn.execute('SELECT id FROM documents WHERE path = ?', (path,)).fetchone()
        if not row:
            conn.close()
            self.json_response({"ok": False, "error": "Path not in document index"})
            return
        doc_id = row[0]

        # Delete file from disk (may already be gone - that is fine)
        disk_error = None
        try:
            os.remove(path)
        except FileNotFoundError:
            pass  # already gone; still clean up DB
        except OSError as e:
            disk_error = str(e)

        if disk_error:
            conn.close()
            self.json_response({"ok": False, "error": f"Could not delete file: {disk_error}"})
            return

        # Remove from DB via the shared helper (CASCADEs to tags/embeddings;
        # leaves the harmless contentless-FTS orphan).
        try:
            delete_document(conn, doc_id)
        except Exception as e:
            conn.close()
            self.json_response({"ok": False, "error": f"DB delete failed: {e}"})
            return
        conn.close()
        self.json_response({"ok": True, "deleted": path})

    def handle_synopsis(self, query: dict):
        """GET /api/synopsis?path=<encoded-path>

        Returns a cached synopsis if one exists; otherwise generates one
        via Ollama, caches it in the documents table, and returns it.
        """
        path = query.get('path', [''])[0].strip()
        if not path:
            self.json_response({"ok": False, "error": "Missing path parameter"})
            return

        conn = get_db(self.db_path)
        row = conn.execute(
            'SELECT id, title, name, description, content_snippet, synopsis '
            'FROM documents WHERE path = ?', (path,)
        ).fetchone()
        if not row:
            conn.close()
            self.json_response({"ok": False, "error": "Path not in document index"})
            return

        doc_id, title, name, description, snippet, synopsis = row

        if synopsis and synopsis.strip():
            conn.close()
            self.json_response({"ok": True, "synopsis": synopsis, "cached": True})
            return

        synopsis, reason = generate_synopsis(title or name, description, snippet)
        if not synopsis:
            conn.close()
            messages = {
                "empty": "No description or text is available for this document to summarize.",
                "timeout": "The AI model is still loading after a recent restart — this can "
                           "take a minute the first time. Please wait a moment and try again.",
                "error": "Couldn't reach the AI model (Ollama). Make sure it's running, then try again.",
            }
            self.json_response({
                "ok": False,
                "error": messages.get(reason, "Synopsis generation failed. Try again.")
            })
            return

        conn.execute('UPDATE documents SET synopsis = ? WHERE id = ?', (synopsis, doc_id))
        conn.commit()
        conn.close()
        self.json_response({"ok": True, "synopsis": synopsis, "cached": False})

    def handle_browse(self, query: dict):
        """GET /api/browse?path=DIR - List subdirectories of DIR for the
        Settings-modal directory browser (docPath/workDir/ignoreDir).

        This exposes the host filesystem, so it is gated behind the same
        CSRF token as the mutating endpoints — only the first-party UI
        (which receives the token) may enumerate directories.
        """
        if not self._guard_mutation():
            return
        path_param = query.get('path', ['/'])[0] or '/'
        try:
            path_obj = Path(path_param).expanduser()
            if not path_obj.exists() or not path_obj.is_dir():
                path_obj = Path('/')

            entries = []
            # Allow navigating up to the parent directory (root has none).
            if path_obj.parent != path_obj:
                entries.append({"name": "..", "path": str(path_obj.parent), "parent": True})
            try:
                for item in sorted(path_obj.iterdir(), key=lambda p: p.name.lower()):
                    if item.is_dir() and not item.name.startswith('.'):
                        entries.append({"name": item.name, "path": str(item)})
            except PermissionError:
                pass

            self.json_response({
                "path": str(path_obj),
                "entries": entries[:201],
            })
        except Exception as e:
            self.json_response({
                "path": path_param,
                "error": str(e),
                "entries": [],
            })

    def handle_ignore_dirs(self):
        """GET /api/ignore-dirs - List directories excluded from scanning."""
        sys.path.insert(0, str(Path(__file__).parent))
        from scan_docs import _load_ignore_dirs
        dirs = sorted(_load_ignore_dirs(Path(self.db_path)))
        self.json_response({"dirs": dirs})

    def handle_ignore_dirs_post(self):
        """POST /api/ignore-dirs - {action: 'add'|'remove', path: str}.

        'add' appends the directory to ignore_dirs.txt and purges any
        already-indexed documents under it. 'remove' drops it from the
        file (caller must rescan to re-index).
        """
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.error_response(400, "Invalid JSON")
            return

        action = data.get("action")
        raw_path = str(data.get("path", "")).strip()
        if action not in ("add", "remove") or not raw_path:
            self.error_response(400, "action ('add'/'remove') and path are required")
            return

        sys.path.insert(0, str(Path(__file__).parent))
        from scan_docs import IGNORE_DIRS_FILENAME, _load_ignore_dirs, purge_path_prefix

        db_path = Path(self.db_path)
        ig_path = db_path.parent / IGNORE_DIRS_FILENAME
        try:
            target = str(Path(raw_path).expanduser().resolve())
        except OSError as e:
            self.error_response(400, f"Invalid path: {e}")
            return

        dirs = _load_ignore_dirs(db_path)

        if action == "add":
            purged = 0
            if target not in dirs:
                dirs.add(target)
                ig_path.parent.mkdir(parents=True, exist_ok=True)
                with open(ig_path, "a", encoding="utf-8") as fh:
                    fh.write(target + "\n")
            if db_path.exists():
                conn = get_db(self.db_path)
                purged = purge_path_prefix(conn, target)
                conn.close()
            self.json_response({"ok": True, "dirs": sorted(dirs), "purged": purged})
        else:  # remove
            if target in dirs:
                dirs.discard(target)
                if dirs:
                    ig_path.write_text("\n".join(sorted(dirs)) + "\n", encoding="utf-8")
                else:
                    ig_path.unlink(missing_ok=True)
            self.json_response({"ok": True, "dirs": sorted(dirs)})

    def handle_scan_dirs(self):
        """GET /api/scan-dirs - List additional directories earmarked for scanning."""
        sys.path.insert(0, str(Path(__file__).parent))
        from scan_docs import _load_scan_dirs
        dirs = sorted(_load_scan_dirs(Path(self.db_path)))
        self.json_response({"dirs": dirs})

    def handle_scan_dirs_post(self):
        """POST /api/scan-dirs - {action: 'add'|'remove', path: str}.

        Purely a bookkeeping list of extra top-level directories the user
        intends to scan with `docubrowser scan --doc-dir <DIR>`. No
        purging or DB changes — scanning itself is run manually via CLI.
        """
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.error_response(400, "Invalid JSON")
            return

        action = data.get("action")
        raw_path = str(data.get("path", "")).strip()
        if action not in ("add", "remove") or not raw_path:
            self.error_response(400, "action ('add'/'remove') and path are required")
            return

        sys.path.insert(0, str(Path(__file__).parent))
        from scan_docs import SCAN_DIRS_FILENAME, _load_scan_dirs

        db_path = Path(self.db_path)
        sd_path = db_path.parent / SCAN_DIRS_FILENAME
        try:
            target = str(Path(raw_path).expanduser().resolve())
        except OSError as e:
            self.error_response(400, f"Invalid path: {e}")
            return

        dirs = _load_scan_dirs(db_path)

        if action == "add":
            if target not in dirs:
                dirs.add(target)
                sd_path.parent.mkdir(parents=True, exist_ok=True)
                with open(sd_path, "a", encoding="utf-8") as fh:
                    fh.write(target + "\n")
            self.json_response({"ok": True, "dirs": sorted(dirs)})
        else:  # remove
            if target in dirs:
                dirs.discard(target)
                if dirs:
                    sd_path.write_text("\n".join(sorted(dirs)) + "\n", encoding="utf-8")
                else:
                    sd_path.unlink(missing_ok=True)
            self.json_response({"ok": True, "dirs": sorted(dirs)})

    def handle_config(self):
        """GET /api/config - Return current configuration."""
        cfg_paths = [
            Path("/etc/docubrowse.config"),
            Path(__file__).parent / "docubrowse.config",
        ]
        config = {
            "docPath":      "",
            "workDir":      str(Path(__file__).parent),
            "port":         DEFAULT_PORT,
            "installed":    False,
            "configSource": None,
        }
        for cfg_path in cfg_paths:
            if cfg_path.exists():
                try:
                    for line in cfg_path.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, _, val = line.partition("=")
                        key, val = key.strip().lower(), val.strip()
                        if key == "doc_dir":
                            config["docPath"] = val
                        elif key == "work_dir":
                            config["workDir"] = val
                        elif key == "port":
                            try:
                                config["port"] = int(val)
                            except ValueError:
                                pass
                    config["installed"]    = str(cfg_path) == "/etc/docubrowse.config"
                    config["configSource"] = str(cfg_path)
                    break   # only advance past this file on success
                except Exception:
                    pass
        self.json_response(config)

    def handle_config_post(self):
        """POST /api/config - Write docubrowse.config next to the server script."""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.error_response(400, "Invalid JSON")
            return

        doc_path = str(data.get("docPath", "")).strip()
        work_dir = str(data.get("workDir", "")).strip()
        try:
            port = int(data.get("port", self.server_port))
        except (ValueError, TypeError):
            port = self.server_port
        # doc_dir is optional now (it's just the first of the unified document
        # directories list, and may be empty when only extra dirs are set, or
        # none yet). workDir is still required.
        if not work_dir:
            self.error_response(400, "workDir is required")
            return

        cfg_path = Path(__file__).parent / "docubrowse.config"
        # Preserve allow_remote (and avoid clobbering it on every settings save).
        allow_remote = "false"
        if cfg_path.exists():
            for line in cfg_path.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s.lower().startswith("allow_remote") and "=" in s:
                    allow_remote = s.split("=", 1)[1].strip()
        try:
            lines = [
                "# docubrowse.config — written by the Settings UI\n",
                f"doc_dir  = {doc_path}\n",
                f"work_dir = {work_dir}\n",
                f"port     = {port}\n",
                f"allow_remote = {allow_remote}\n",
            ]
            cfg_path.write_text("".join(lines), encoding="utf-8")
            self.json_response({
                "message": f"Config saved to {cfg_path}",
                "configSource": str(cfg_path),
            })
        except OSError as e:
            self.error_response(500, f"Could not write config file: {e}")

    def serve_file(self, filename):
        """Serve a file from the current directory."""
        filepath = Path(__file__).parent / filename

        if not filepath.exists():
            self.error_response(404, f"File not found: {filename}")
            return

        try:
            with open(filepath, 'rb') as f:
                content = f.read()

            # Inject the per-process CSRF token into served HTML so the
            # first-party UI can authenticate its mutating requests. A
            # cross-origin page cannot read this token, so it cannot forge
            # the X-CSRF-Token header the mutating endpoints require.
            if filename.endswith('.html') and self.csrf_token:
                meta = f'<meta name="csrf-token" content="{self.csrf_token}">'
                text = content.decode('utf-8')
                if '</head>' in text:
                    text = text.replace('</head>', f'  {meta}\n</head>', 1)
                else:
                    text = meta + text
                content = text.encode('utf-8')

            self.send_response(200)
            if filename.endswith('.html'):
                self.send_header('Content-Type', 'text/html; charset=utf-8')
            elif filename.endswith('.css'):
                self.send_header('Content-Type', 'text/css; charset=utf-8')
            elif filename.endswith('.js'):
                self.send_header('Content-Type', 'application/javascript; charset=utf-8')
            else:
                self.send_header('Content-Type', 'application/octet-stream')

            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.error_response(500, str(e))

    def json_response(self, data: dict):
        """Send a JSON response."""
        content = json.dumps(data).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(content))
        self.end_headers()
        self.wfile.write(content)

    def error_response(self, code: int, message: str):
        """Send an error response."""
        content = f"{code}: {message}".encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', len(content))
        self.end_headers()
        self.wfile.write(content)


def main():
    """Start the document search server."""
    # Args: <database_path> [port] [--allow-remote]
    argv = sys.argv[1:]
    allow_remote = '--allow-remote' in argv
    argv = [a for a in argv if a != '--allow-remote']
    if not argv:
        print(f"Usage: {sys.argv[0]} <database_path> [port] [--allow-remote]")
        print(f"\nExample:")
        print(f"  {sys.argv[0]} /path/to/du-docs.db")
        print(f"  {sys.argv[0]} /path/to/du-docs.db 8643")
        print(f"  {sys.argv[0]} /path/to/du-docs.db 8643 --allow-remote   # bind 0.0.0.0 (LAN)")
        sys.exit(1)

    db_path = argv[0]
    port = int(argv[1]) if len(argv) > 1 else DEFAULT_PORT

    db_path = Path(db_path)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}")
        sys.exit(1)

    # Set database path and port for handler
    DocSearchHandler.db_path      = str(db_path)
    DocSearchHandler.server_port  = port
    DocSearchHandler.csrf_token   = secrets.token_urlsafe(32)
    DocSearchHandler.allow_remote = allow_remote
    if allow_remote:
        names = {'localhost', '127.0.0.1', '::1'}
        try:
            names.add(socket.gethostname().lower())
            names.add(socket.getfqdn().lower())
        except Exception:
            pass
        DocSearchHandler.allowed_hostnames = frozenset(n for n in names if n)

    # Local-only (default) binds the IPv4 loopback explicitly; remote binds all
    # interfaces. The firewall is only ever opened when remote is chosen.
    bind_addr = '0.0.0.0' if allow_remote else '127.0.0.1'
    server_address = (bind_addr, port)
    try:
        httpd = ThreadingHTTPServer(server_address, DocSearchHandler)
    except OSError as e:
        if e.errno == 98:  # Address already in use
            print(f"ERROR: Port {port} is already in use.")
            print(f"Please check if DocuBrowse is already running or choose another port.")
            print(f"\nTo stop the running instance:")
            print(f"  pkill -f 'doc_search.py'")
            sys.exit(1)
        else:
            raise

    print(f"DocuBrowse Search Server")
    print(f"  Database: {db_path}")
    print(f"  Ollama: {OLLAMA_HOST}")
    print(f"  Model: {EMBEDDING_MODEL}")
    if allow_remote:
        print(f"  Listening on http://0.0.0.0:{port}  (LAN/remote access ENABLED)")
        print(f"  ⚠ Remote access is on and there is NO authentication yet — anyone who")
        print(f"    can reach this host on port {port} can read and delete indexed documents.")
    else:
        print(f"  Listening on http://localhost:{port}  (local only)")

    # Self-test: confirm semantic search will actually work. A silent
    # embed failure (e.g. wrong response key, Ollama down) degrades
    # 'both'/'semantic' modes to nothing, so fail loudly here instead.
    probe = embed_text("docubrowse embedding self-test")
    if probe and len(probe) > 0:
        print(f"  Embeddings: OK (dim={len(probe)})")
    else:
        print("  Embeddings: ⚠ FAILED — semantic search will return nothing.")
        print("              Check that Ollama is running and the model is pulled.")
    print()
    print("Endpoints:")
    print(f"  GET  http://localhost:{port}/               - UI (index.html)")
    print(f"  GET  http://localhost:{port}/api/stats      - Statistics")
    print(f"  GET  http://localhost:{port}/api/tags       - Tags")
    print(f"  GET  http://localhost:{port}/api/search?q=QUERY&mode=both|keyword|semantic")
    print(f"  GET  http://localhost:{port}/api/config     - Configuration")
    print()
    print("Press Ctrl+C to stop")
    print()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        httpd.server_close()


if __name__ == '__main__':
    main()
