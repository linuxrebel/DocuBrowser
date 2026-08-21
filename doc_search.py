#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
DocuBrowse search server.
HTTP server on port 8643 with merged keyword + semantic search.
"""

# Splitting doc_search into multiple modules is on the deferred list — the
# HTTP handler, embedding cache, and Ollama client all share so much state
# that a naive split would explode the import surface. Deferred.
# pylint: disable=too-many-lines

import errno
import ipaddress
import json
import logging
import math
import mimetypes
import os
import re
import secrets
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import URLError

# ─── Paths ───────────────────────────────────────────────────────────────────
# APP_DIR  = code directory (scripts, HTML, icons) — always read-only safe.
# USER_DATA = ~/.docubrowser/ — per-user runtime data (DB, config, blacklists).
# _default_data_dir() returns APP_DIR when writable (dev), else USER_DATA.

APP_DIR   = Path(__file__).resolve().parent
USER_DATA = Path.home() / ".docubrowser"

# sys.path insert MUST precede the scan_docs import (module isn't on the
# system path when running from a checkout / installed via tarball).
sys.path.insert(0, str(APP_DIR))

# pylint: disable=wrong-import-position
# These imports live below sys.path.insert on purpose; noqa: E402 covers pyflakes.
from docubrowse_db import get_db, check_missing_path, delete_document   # noqa: E402
from platform_paths import (                                             # noqa: E402
    scan_pid_file as _scan_pid_file,
    pid_exists as _pid_exists,
)
from scan_docs import (                                                  # noqa: E402
    _load_ignore_dirs, _load_scan_dirs, _blacklist_add,
    IGNORE_DIRS_FILENAME, SCAN_DIRS_FILENAME,
    purge_path_prefix,
)
# pylint: enable=wrong-import-position

try:
    import numpy as _np                    # pylint: disable=invalid-name
except ImportError:  # numpy normally present (dup_detect uses it); degrade gracefully
    _np = None       # pylint: disable=invalid-name


def _default_data_dir() -> Path:
    """APP_DIR if writable (dev mode), else ~/.docubrowser/ (packaged)."""
    if os.access(APP_DIR, os.W_OK):
        return APP_DIR
    USER_DATA.mkdir(parents=True, exist_ok=True)
    return USER_DATA


__all__ = [
    'DocSearchHandler', 'DocuBrowseServer',
    'DEFAULT_PORT', 'SERVER_VERSION',
    'embed_text', 'generate_synopsis',
    'cosine_similarity', 'blob_to_vector',
]

DEFAULT_PORT = 8643
_LOOPBACK_NET = ipaddress.ip_network("127.0.0.0/8")
_IPV6_LOOPBACK = ipaddress.ip_address("::1")


def _is_loopback(hostname: str) -> bool:
    """Return True if hostname is a loopback address (127.0.0.0/8 or ::1)."""
    if hostname == 'localhost':
        return True
    try:
        addr = ipaddress.ip_address(hostname)
        return addr == _IPV6_LOOPBACK or addr in _LOOPBACK_NET
    except ValueError:
        return False
def _ollama_host() -> str:
    """Resolve the Ollama base URL from the environment.

    Prefer ``OLLAMA_HOST`` (Ollama ecosystem convention), then
    ``DOCUBROWSE_OLLAMA_HOST``. Defaults to the local Ollama daemon.
    """
    host = (
        os.environ.get("OLLAMA_HOST")
        or os.environ.get("DOCUBROWSE_OLLAMA_HOST")
        or "http://localhost:11434"
    ).rstrip("/")
    # OLLAMA_HOST follows the Ollama convention of a bare host[:port] with no
    # scheme (e.g. "127.0.0.1:11434"); prepend http:// so f"{host}/api/..."
    # stays a valid URL rather than raising "unknown url type".
    if "://" not in host:
        host = "http://" + host
    return host


OLLAMA_HOST = _ollama_host()
EMBEDDING_MODEL = "nomic-embed-text"
SYNOPSIS_MODEL = "dolphin3:latest"
SERVER_VERSION = "1.0.2"

_SERVER_START_TIME = None  # set by main(); used by /api/status
# Cold Ollama starts (e.g. right after a reboot) need to load the model into
# memory before the first generation can begin, which can take well over 30s
# on top of the generation time itself. Use a generous timeout so the first
# request after startup doesn't spuriously fail.
SYNOPSIS_TIMEOUT_SECS = 90

# ── Synopsis model warmup ───────────────────────────────────────────────────
# Ollama loads models on-demand. On 8 GB systems, loading dolphin3 (~4.9 GB)
# into RAM can take long enough that the first synopsis request times out —
# especially for large documents.  A lightweight warmup (num_predict=1) forces
# the model into memory before any user requests it.
#
# To avoid OOM on low-RAM machines, the warmup waits until any running
# scan/embed finishes (the embedding model is unloaded by Ollama once idle,
# freeing RAM for dolphin3).

SYNOPSIS_WARM = False   # set True once warmup succeeds


def _warmup_synopsis_model():
    """Send a trivial prompt to dolphin3 so Ollama loads it into RAM."""
    global SYNOPSIS_WARM   # pylint: disable=global-statement
    try:
        url = f"{OLLAMA_HOST}/api/generate"
        payload = json.dumps({
            "model": SYNOPSIS_MODEL,
            "prompt": "hi",
            "stream": False,
            "options": {"num_predict": 1},
        }).encode("utf-8")
        request = Request(url, data=payload, method="POST")
        request.add_header("Content-Type", "application/json")
        with urlopen(request, timeout=120) as resp:
            resp.read()
        SYNOPSIS_WARM = True
        print("  Synopsis model: OK (dolphin3 loaded)")
    except (URLError, socket.timeout, OSError) as exc:
        print(f"  Synopsis model: ⚠ warmup failed ({exc})")


def _is_scan_running() -> bool:
    """Check if a scan/embed process is currently running."""
    try:
        pidfile = _scan_pid_file()
        if not pidfile.exists():
            return False
        pid = int(pidfile.read_text(encoding="utf-8").strip())
        # Check if the process is actually alive (Windows-safe; a bare
        # os.kill(pid, 0) probe would kill the scan on Windows).
        return _pid_exists(pid)
    except (ValueError, OSError):
        return False


def _deferred_synopsis_warmup():
    """Background thread: wait for scan/embed to finish, then warm up dolphin3."""
    if _is_scan_running():
        print("  Synopsis model: deferring warmup until scan/embed finishes...")
        while _is_scan_running():
            time.sleep(5)
        # Brief pause to let Ollama unload the embedding model
        time.sleep(3)
    _warmup_synopsis_model()


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
    except (URLError, socket.timeout, OSError, json.JSONDecodeError) as e:
        sys.stderr.write(f"[embed_text] embedding request failed: {e}\n")
        return None


def generate_synopsis(title: str, description: str, snippet: str) -> tuple:
    """Ask Ollama for a one-paragraph factual summary of the document.

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
        "Summarize the document excerpt below in one concise paragraph. "
        "Describe only what the document actually contains — its subject matter, "
        "purpose, and key topics. Base the summary entirely on the excerpt text; "
        "do not invent content or draw on the document title alone. "
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
    except (OSError, json.JSONDecodeError):
        return None, "error"


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
    """Build a safe FTS5 MATCH expression.

    Supports two input forms:
    • Quoted phrase  "import fmt"  → passed to FTS5 as a phrase: "import fmt"
      (exact consecutive-word match, case-insensitive).
    • Bare words  import fmt  → prefix-OR over tokens: "import"* OR "fmt"*
      Each token is FTS5-quoted to neutralise operators (AND/OR/NOT/NEAR,
      colons, etc.) so arbitrary user input can't inject FTS5 syntax.

    A query may mix both forms: golang "import fmt" → phrase OR bare tokens.
    """
    parts = []
    # Extract double-quoted phrases first, then remaining bare words.
    phrases = re.findall(r'"([^"]+)"', q)
    remainder = re.sub(r'"[^"]*"', ' ', q)
    bare_tokens = re.findall(r'\w+', remainder.lower())

    for phrase in phrases:
        # Re-quote inner content so FTS5 treats it as a phrase literal.
        inner = phrase.strip().lower()
        if inner:
            parts.append(f'"{inner}"')

    for t in bare_tokens:
        parts.append(f'"{t}"*')

    return ' OR '.join(parts) if parts else None


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


class DocuBrowseServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that enforces loopback-only access.

    Always binds to 0.0.0.0 so all 127.x.x.x addresses are reachable
    (the entire 127.0.0.0/8 subnet is loopback per RFC 5735).
    verify_request() drops any connection whose source IP is outside
    127.0.0.0/8 at the TCP accept level — before a single byte of HTTP
    is read.
    """

    def verify_request(self, request, client_address):
        try:
            addr = ipaddress.ip_address(client_address[0])
            # Accept IPv6 loopback (::1) — localhost often resolves to it
            if addr == ipaddress.ip_address('::1'):
                return True
            # Accept anything in 127.0.0.0/8; reject all other IPs
            if addr not in _LOOPBACK_NET:
                return False
        except (ValueError, TypeError):
            return False
        return True


class DocSearchHandler(BaseHTTPRequestHandler):
    """HTTP request handler for document search.

    Method count intentionally exceeds pylint's 20-method ceiling: each
    ``/api/*`` endpoint gets its own ``handle_*`` method for locality of
    reasoning, and BaseHTTPRequestHandler contributes several inherited
    methods (send_response, log_message, ...).  Splitting into multiple
    handler classes would require per-endpoint routing at a lower layer.
    """
    # pylint: disable=too-many-public-methods

    db_path     = None          # Will be set by server
    server_port = DEFAULT_PORT  # Will be set by server
    csrf_token  = None          # Per-process secret, set by server at startup

    @staticmethod
    def _model_present(configured_name: str, model_list: list) -> bool:
        """Check if *configured_name* appears in *model_list*, ignoring :tag."""
        base = configured_name.split(":")[0]
        return any(base == m.split(":")[0] for m in model_list)

    def log_message(self, format, *args):   # pylint: disable=redefined-builtin
        """Suppress default access logging (framework API — ``format`` name required)."""

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
        # Loopback is always allowed (entire 127.0.0.0/8 subnet + ::1).
        return _is_loopback(hostname)

    def _guard_mutation(self) -> bool:
        """Gate state-changing / sensitive endpoints against CSRF.

        The primary defense is a per-process secret token that is injected
        into the served HTML pages. A cross-origin attacker page cannot read
        that token (the HTML is same-origin protected, and the JSON API no
        longer returns Access-Control-Allow-Origin), so it cannot forge the
        X-CSRF-Token header this requires. As defense in depth, any Origin/
        Referer that isn't same-origin with the addressed Host (or loopback)
        is rejected.

        Sends a 403 and returns False on failure; returns True if allowed.
        """
        host_hdr = self.headers.get('Host', '')
        host_host = host_hdr.rsplit(':', 1)[0].strip('[]').lower() if host_hdr else ''
        for hdr in ('Origin', 'Referer'):
            val = self.headers.get(hdr)
            if val:
                o = urlparse(val).hostname
                o = o.lower() if o else o
                if o != host_host and not _is_loopback(o or ''):
                    self.error_response(403, "Forbidden: cross-origin request rejected")
                    return False
        token = self.headers.get('X-CSRF-Token', '')
        if not self.csrf_token or not secrets.compare_digest(token, self.csrf_token):
            self.error_response(403, "Forbidden: missing or invalid CSRF token")
            return False
        return True

    # ── Route tables — dict dispatch avoids a giant if/elif chain ──────────
    # Routes that take (self)                     → handler bound method
    # Routes that take (self, query)              → handler bound method
    # Populated in __init_subclass__ lazily via property below.

    def _serve_icon(self, path: str) -> None:
        """Serve an icon asset, restricted to known safe extensions."""
        fname = path[len('/icons/'):]
        if '/' in fname or '..' in fname:
            self.error_response(403, "Forbidden")
        elif fname.endswith(('.png', '.svg', '.ico')):
            self.serve_file(f'icons/{fname}')
        else:
            self.error_response(404, "Not found")

    def _dispatch_get(self, path: str, query: dict) -> None:
        """Look up *path* in the GET route table and invoke the handler."""
        no_arg = {
            '/':                lambda: self.serve_file('index.html'),
            '/settings':        lambda: self.serve_file('settings.html'),
            '/favicon.ico':     lambda: self.serve_file('icons/favicon.ico'),
            '/api/stats':       self.handle_stats,
            '/api/tags':        self.handle_tags,
            '/api/letters':     self.handle_letters,
            '/api/config':      self.handle_config,
            '/api/ignore-dirs': self.handle_ignore_dirs,
            '/api/scan-dirs':   self.handle_scan_dirs,
            '/api/status':      self.handle_status,
        }
        with_query = {
            '/api/search':      self.handle_search,
            '/api/synopsis':    self.handle_synopsis_get,
            '/api/browse':      self.handle_browse,
        }
        if path in no_arg:
            no_arg[path]()
        elif path in with_query:
            with_query[path](query)
        elif path.startswith('/icons/'):
            self._serve_icon(path)
        else:
            self.error_response(404, "Not found")

    def _dispatch_post(self, path: str, query: dict) -> None:
        """Look up *path* in the POST route table and invoke the handler."""
        no_arg = {
            '/api/config':      self.handle_config_post,
            '/api/ignore-dirs': self.handle_ignore_dirs_post,
            '/api/scan-dirs':   self.handle_scan_dirs_post,
        }
        with_query = {
            '/api/synopsis':    self.handle_synopsis,
            '/api/delete':      self.handle_delete,
            '/api/add-tags':    self.handle_add_tags,
            '/api/remove-tag':  self.handle_remove_tag,
            '/api/open':        self.handle_open,
        }
        if path in no_arg:
            no_arg[path]()
        elif path in with_query:
            with_query[path](query)
        else:
            self.error_response(404, "Not found")

    # pylint: disable=invalid-name
    # do_GET / do_POST names are mandated by BaseHTTPRequestHandler.
    def do_GET(self):
        """Handle GET requests — dispatch via ``_dispatch_get``."""
        if not self._host_allowed():
            self.error_response(403, "Forbidden: invalid Host header")
            return
        parsed = urlparse(self.path)
        try:
            self._dispatch_get(parsed.path, parse_qs(parsed.query))
        except Exception:  # pylint: disable=broad-exception-caught
            # Top-level handler safety net: any handler crash must produce a
            # 500 rather than take down the server thread.
            logging.exception("Unhandled error in do_GET: %s", self.path)
            self.error_response(500, "Internal server error")

    def do_POST(self):
        """Handle POST requests — dispatch via ``_dispatch_post``."""
        if not self._host_allowed():
            self.error_response(403, "Forbidden: invalid Host header")
            return
        parsed = urlparse(self.path)
        try:
            # All POST routes are state-changing — gate them all against CSRF.
            if not self._guard_mutation():
                return
            self._dispatch_post(parsed.path, parse_qs(parsed.query))
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Unhandled error in do_POST: %s", self.path)
            self.error_response(500, "Internal server error")
    # pylint: enable=invalid-name

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

    def handle_status(self):   # pylint: disable=too-many-locals
        """GET /api/status - Health and readiness check for monitoring systems.

        No CSRF required — monitoring agents must be able to probe this endpoint
        without first-party HTML.

        Returns ok, version, uptime, db.ok, ollama.ok — enough for a simple
        watchdog.  The 'ok' field is True only when both DB and Ollama are
        reachable.  Model presence does not affect 'ok' — keyword search works
        without embeddings.
        """
        uptime = time.time() - (_SERVER_START_TIME or time.time())

        # DB connectivity — use try/finally to guarantee close on any path.
        # We probe documents (round-trip validates the FTS-backing table) and
        # embeddings; only the embedded count is surfaced in the response.
        db_ok = False
        db_error = None
        embedded_count = 0
        try:
            conn = get_db(self.db_path)
            try:
                conn.execute("SELECT COUNT(*) FROM documents").fetchone()
                embedded_count = conn.execute(
                    "SELECT COUNT(*) FROM doc_embeddings"
                ).fetchone()[0]
                db_ok = True
            finally:
                conn.close()
        except sqlite3.Error as e:
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
        except (URLError, socket.timeout, OSError, json.JSONDecodeError) as e:
            ollama_error = str(e)

        # Normalize model names for comparison: strip tag suffix from both sides
        # so "nomic-embed-text:latest" and "nomic-embed-text" both match.

        overall_ok = db_ok and ollama_ok

        # Semantic search is usable when embeddings exist AND Ollama is up
        # (Ollama is needed at query time to embed the search query).
        semantic_ready = (
            db_ok and ollama_ok
            and embedded_count > 0
            and self._model_present(EMBEDDING_MODEL, ollama_models)
        )

        status = {
            "ok": overall_ok,
            "version": SERVER_VERSION,
            "uptime_seconds": round(uptime, 1),
            "timestamp": datetime.now().isoformat(),
            "semantic_ready": semantic_ready,
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

    # pylint: disable-next=too-many-locals,too-many-branches,too-many-statements
    def handle_search(self, query: dict):
        """GET /api/search - Search documents.

        The three complexity metrics come from the two-mode branch (empty-vs
        query), the score-merge logic (keyword-only / semantic-only / both
        with the sem_floor gate), and the paged-metadata fetch. Splitting
        would obscure the tight coupling between the mode branch and the
        SQL it drives.
        """
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
                where_clause = (
                    "WHERE upper(substr(COALESCE(d.title, d.name, ''), 1, 1))"
                    " NOT GLOB '[A-Z]'"
                )
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
            # A document must have EITHER a keyword hit OR a meaningful
            # semantic score (>= 0.30) to appear in combined results.
            # Without this gate, every embedded document leaks in via
            # low-but-nonzero cosine similarity — burying keyword matches.
            sem_floor = 0.30
            all_ids = set(kw_scores) | {
                did for did, s in sem_scores.items() if s >= sem_floor
            }
            for doc_id in all_ids:
                fts = kw_scores.get(doc_id, 0.0)
                sem = sem_scores.get(doc_id, 0.0)
                # Use max rather than weighted average so a strong keyword
                # match isn't diluted by a zero semantic score (no embedding)
                # and vice versa. When both are present, boost slightly.
                if fts > 0 and sem >= sem_floor:
                    final = min(max(fts, sem) + 0.1 * min(fts, sem), 1.0)
                else:
                    final = max(fts, sem)
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
        fails to launch anything even though it exits 0.

        On Windows this is a no-op — ``os.startfile()`` handles file opening
        without any environment setup."""
        env = os.environ.copy()
        if sys.platform == 'win32':
            return env   # Windows: no DBus/XDG setup needed
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

    # pylint: disable-next=too-many-return-statements,too-many-branches,too-many-statements,too-many-locals
    def handle_open(self, query: dict):
        """POST /api/open?path=<encoded-path> — Open a file with the desktop default app.

        Uses an opener chain (gio open → kde-open5 → kde-open → xdg-open) so
        that GNOME, KDE, and hybrid setups all work.  The xdg-mime pre-check is
        intentionally NOT used as a gate: on KDE, `xdg-mime query default` returns
        empty for many MIME types (e.g. text/x-python, text/x-csrc) even when a
        working handler exists.  This affects both Flatpak apps (whose .desktop
        MimeType list may omit specific subtypes) and native apps like GVim.
        See status_docs/DECISIONS.md — "xdg-mime false-negative on KDE".

        Complexity in this function reflects the opener chain × platform
        matrix (Windows fast-path, missing-file / unmounted checks, four
        opener candidates, timeout vs. exit code disambiguation). Splitting
        it further would fragment the control flow across many tiny helpers
        without improving readability.
        """
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
                                     "message": (f"Cannot verify — the device for this path"
                                                 f" does not appear to be mounted: {path}")})
            else:
                self.json_response({"ok": False, "error": "missing",
                                     "message": f"File not found on disk: {path}"})
            return

        env = self._desktop_env()

        # Detect MIME type for diagnostic messages only — NOT a gate for opening.
        mime = None
        try:
            mime, _ = mimetypes.guess_type(str(p))
            if not mime and shutil.which('xdg-mime'):
                r = subprocess.run(
                    ['xdg-mime', 'query', 'filetype', str(p)],
                    capture_output=True, text=True, timeout=5, env=env,
                    check=False,
                )
                mime = r.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            pass

        # Windows: os.startfile() is the native opener — no subprocess needed.
        if sys.platform == 'win32':
            try:
                os.startfile(str(p))
                self.json_response({"ok": True, "path": path})
            except OSError as exc:
                self.json_response({"ok": False, "error": str(exc)})
            return

        # Opener chain: try each available launcher in preference order.
        # We wait up to 1 s; if the process is still running at that point it
        # has successfully handed off to the GUI app and we call it a win.
        # If it exits within 1 s with a non-zero code we capture stderr and
        # move on to the next candidate.
        candidates = [
            ['gio', 'open', str(p)],       # GNOME / Flatpak portals
            ['kde-open5', str(p)],          # KDE Plasma 5
            ['kde-open', str(p)],           # KDE Plasma 4 / fallback
            ['xdg-open', str(p)],           # generic XDG fallback
        ]
        openers = [cmd for cmd in candidates if shutil.which(cmd[0])]

        if not openers:
            self.json_response({
                "ok": False,
                "error": "No file opener found on PATH (tried gio, kde-open5, kde-open, xdg-open)",
            })
            return

        last_err = "all openers failed"
        for opener in openers:
            try:
                # `with subprocess.Popen(...)` would auto-terminate the child
                # on exit — but for the timeout path we intentionally let the
                # GUI opener keep running after this function returns.
                proc = subprocess.Popen(   # pylint: disable=consider-using-with
                    opener,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                    env=env,
                )
                try:
                    rc = proc.wait(timeout=1.0)
                    stderr_txt = proc.stderr.read().decode(errors='replace').strip()
                    proc.stderr.close()
                    if rc != 0:
                        last_err = stderr_txt or f"{opener[0]} exited {rc}"
                        logging.warning("handle_open: %s rc=%d: %s", opener[0], rc, last_err)
                        continue  # try next opener
                    # Exited 0 quickly — success (some launchers do this)
                    self.json_response({"ok": True, "path": path})
                    return
                except subprocess.TimeoutExpired:
                    # Still running after 1 s → GUI app is launching, we're done.
                    proc.stderr.close()
                    threading.Thread(target=proc.wait, daemon=True).start()
                    self.json_response({"ok": True, "path": path})
                    return
            except FileNotFoundError:
                continue  # binary disappeared between which() and Popen()

        # Every opener failed.
        hint = ""
        if mime:
            hint = (f" To fix: run  xdg-mime default <app>.desktop {mime}  "
                    f"or edit ~/.config/mimeapps.list")
        logging.error("handle_open: all openers failed for %s (%s): %s", path, mime, last_err)
        self.json_response({
            "ok": False,
            "error": f"No default application for this file type ({mime or 'unknown'})",
            "detail": last_err,
            "hint": hint.strip(),
        })

    def handle_delete(self, query: dict):
        """POST /api/delete?path=<encoded-path>&mode=<mode>

        Modes (default: ``db_only``):
          db_only     — remove from DB only (document stays on disk)
          blacklist   — remove from DB + add to scan_blacklist.txt
          delete_file — remove from DB + delete file from disk
        """
        path = query.get('path', [''])[0].strip()
        mode = query.get('mode', ['db_only'])[0].strip()
        if not path:
            self.json_response({"ok": False, "error": "Missing path parameter"})
            return
        if mode not in ('db_only', 'blacklist', 'delete_file'):
            self.json_response({"ok": False, "error": f"Invalid mode: {mode}"})
            return

        # Security: path must be in the index (not arbitrary filesystem access)
        conn = get_db(self.db_path)
        row = conn.execute('SELECT id FROM documents WHERE path = ?', (path,)).fetchone()
        if not row:
            conn.close()
            self.json_response({"ok": False, "error": "Path not in document index"})
            return
        doc_id = row[0]

        # Mode: delete_file — remove from disk first
        if mode == 'delete_file':
            try:
                os.remove(path)
            except FileNotFoundError:
                pass  # already gone; still clean up DB
            except OSError as e:
                conn.close()
                self.json_response({"ok": False, "error": f"Could not delete file: {e}"})
                return

        # Remove from DB via the shared helper (CASCADEs to tags/embeddings;
        # leaves the harmless contentless-FTS orphan).
        try:
            delete_document(conn, doc_id)
        except sqlite3.Error as e:
            conn.close()
            self.json_response({"ok": False, "error": f"DB delete failed: {e}"})
            return
        conn.close()

        # Mode: blacklist — add to scan_blacklist.txt so future scans skip it
        if mode == 'blacklist':
            _blacklist_add(Path(self.db_path), path, "removed via UI")

        self.json_response({"ok": True, "deleted": path, "mode": mode})

    def handle_add_tags(self, query: dict):
        """POST /api/add-tags?path=<encoded-path>&tags=<comma-separated>

        Appends tags to a document. Existing tags are preserved (INSERT OR IGNORE).
        Tag names are lowercased and trimmed. Source is set to 'user'.
        """
        path = query.get('path', [''])[0].strip()
        raw_tags = query.get('tags', [''])[0].strip()
        if not path or not raw_tags:
            self.json_response({"ok": False, "error": "Missing path or tags parameter"})
            return

        tags = [t.strip().lower() for t in raw_tags.split(',') if t.strip()]
        if not tags:
            self.json_response({"ok": False, "error": "No valid tags provided"})
            return

        conn = get_db(self.db_path)
        row = conn.execute('SELECT id FROM documents WHERE path = ?', (path,)).fetchone()
        if not row:
            conn.close()
            self.json_response({"ok": False, "error": "Path not in document index"})
            return
        doc_id = row[0]

        added = 0
        for tag in tags:
            cur = conn.execute(
                'INSERT OR IGNORE INTO doc_tags (doc_id, tag, source) VALUES (?, ?, ?)',
                (doc_id, tag, 'user'))
            added += cur.rowcount
        conn.commit()

        # Return the full current tag list for this document
        all_tags = [r[0] for r in conn.execute(
            'SELECT tag FROM doc_tags WHERE doc_id = ? ORDER BY tag', (doc_id,)).fetchall()]
        conn.close()

        self.json_response({"ok": True, "path": path, "added": added, "tags": all_tags})

    def handle_remove_tag(self, query: dict):
        """POST /api/remove-tag?path=<encoded-path>&tag=<tag-name>

        Removes a single tag from a document.
        """
        path = query.get('path', [''])[0].strip()
        tag = query.get('tag', [''])[0].strip().lower()
        if not path or not tag:
            self.json_response({"ok": False, "error": "Missing path or tag parameter"})
            return

        conn = get_db(self.db_path)
        row = conn.execute('SELECT id FROM documents WHERE path = ?', (path,)).fetchone()
        if not row:
            conn.close()
            self.json_response({"ok": False, "error": "Path not in document index"})
            return
        doc_id = row[0]

        cur = conn.execute(
            'DELETE FROM doc_tags WHERE doc_id = ? AND tag = ?', (doc_id, tag))
        conn.commit()

        all_tags = [r[0] for r in conn.execute(
            'SELECT tag FROM doc_tags WHERE doc_id = ? ORDER BY tag', (doc_id,)).fetchall()]
        conn.close()

        self.json_response({"ok": True, "path": path, "removed": cur.rowcount, "tags": all_tags})

    def handle_synopsis_get(self, query: dict):
        """GET /api/synopsis?path=<encoded-path> — read-only, returns cached synopsis.

        Does NOT generate — returns {ok: false, needs_generation: true} if none
        is cached, so the UI can POST to trigger generation with CSRF.
        """
        path = query.get('path', [''])[0].strip()
        if not path:
            self.json_response({"ok": False, "error": "Missing path parameter"})
            return

        conn = get_db(self.db_path)
        row = conn.execute(
            'SELECT synopsis FROM documents WHERE path = ?', (path,)
        ).fetchone()
        conn.close()
        if not row:
            self.json_response({"ok": False, "error": "Path not in document index"})
            return

        synopsis = row[0]
        if synopsis and synopsis.strip():
            self.json_response({"ok": True, "synopsis": synopsis, "cached": True})
        else:
            self.json_response({"ok": False, "needs_generation": True})

    def handle_synopsis(self, query: dict):
        """POST /api/synopsis?path=<encoded-path> — generate + cache synopsis.

        CSRF-protected (via do_POST gate). Generates via Ollama and caches
        the result in the documents table.
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

        # Return cached if already present (idempotent)
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
                "error": ("Couldn't reach the AI model (Ollama)."
                          " Make sure it's running, then try again."),
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
                    # Skip symlinks, hidden dirs, and sensitive system paths
                    if item.is_symlink():
                        continue
                    if item.is_dir() and not item.name.startswith('.'):
                        entries.append({"name": item.name, "path": str(item)})
            except PermissionError:
                pass

            self.json_response({
                "path": str(path_obj),
                "entries": entries[:201],
            })
        except (OSError, ValueError) as e:
            self.json_response({
                "path": path_param,
                "error": str(e),
                "entries": [],
            })

    def handle_ignore_dirs(self):
        """GET /api/ignore-dirs - List directories excluded from scanning."""
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

    @staticmethod
    def _apply_config_line(line: str, config: dict) -> None:
        """Parse one ``key = value`` line and merge into *config* in place."""
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            return
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

    def handle_config(self):
        """GET /api/config - Return current configuration."""
        cfg_paths = [
            USER_DATA / "docubrowse.config",    # packaged install
            APP_DIR   / "docubrowse.config",    # dev / standalone
        ]
        config = {
            "docPath":      "",
            "workDir":      str(_default_data_dir()),
            "port":         DEFAULT_PORT,
            "installed":    False,
            "configSource": None,
        }
        for cfg_path in cfg_paths:
            if not cfg_path.exists():
                continue
            try:
                text = cfg_path.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in text.splitlines():
                self._apply_config_line(line, config)
            config["installed"]    = str(cfg_path) == "/etc/docubrowse.config"
            config["configSource"] = str(cfg_path)
            break   # first readable config wins
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

        data_dir = _default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        cfg_path = data_dir / "docubrowse.config"
        try:
            lines = [
                "# docubrowse.config — written by the Settings UI\n",
                f"doc_dir  = {doc_path}\n",
                f"work_dir = {work_dir}\n",
                f"port     = {port}\n",
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
        filepath = APP_DIR / filename

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
            elif filename.endswith('.png'):
                self.send_header('Content-Type', 'image/png')
            elif filename.endswith('.svg'):
                self.send_header('Content-Type', 'image/svg+xml')
            elif filename.endswith('.ico'):
                self.send_header('Content-Type', 'image/x-icon')
            else:
                self.send_header('Content-Type', 'application/octet-stream')

            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        except (OSError, ValueError) as e:
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


def main():   # pylint: disable=too-many-statements
    """Start the document search server."""
    global _SERVER_START_TIME   # pylint: disable=global-statement
    _SERVER_START_TIME = time.time()

    # Args: <database_path> [port]
    argv = sys.argv[1:]
    if not argv:
        print(f"Usage: {sys.argv[0]} <database_path> [port]")
        print("\nExample:")
        print(f"  {sys.argv[0]} /path/to/du-docs.db")
        print(f"  {sys.argv[0]} /path/to/du-docs.db 8643")
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

    # Always bind 0.0.0.0 so the entire 127.0.0.0/8 loopback subnet is
    # reachable (127.0.0.1, 127.0.1.1, etc.).  DocuBrowseServer.verify_request
    # drops connections from outside 127.0.0.0/8.
    server_address = ('0.0.0.0', port)
    try:
        httpd = DocuBrowseServer(server_address, DocSearchHandler)
    except OSError as e:
        if e.errno == errno.EADDRINUSE:  # Address already in use
            print(f"ERROR: Port {port} is already in use.")
            print("Please check if DocuBrowse is already running or choose another port.")
            print("\nTo stop the running instance:")
            print("  pkill -f 'doc_search.py'")
            sys.exit(1)
        else:
            raise

    print("DocuBrowse Search Server")
    print(f"  Database: {db_path}")
    print(f"  Ollama: {OLLAMA_HOST}")
    print(f"  Model: {EMBEDDING_MODEL}")
    print(f"  Listening on http://127.0.0.0/8:{port}  (loopback subnet only)")
    print("  Any 127.x.x.x address works; all external interfaces rejected.")

    # Self-test: confirm semantic search will actually work. A silent
    # embed failure (e.g. wrong response key, Ollama down) degrades
    # 'both'/'semantic' modes to nothing, so fail loudly here instead.
    probe = embed_text("docubrowse embedding self-test")
    if probe and len(probe) > 0:
        print(f"  Embeddings: OK (dim={len(probe)})")
    else:
        print("  Embeddings: ⚠ FAILED — semantic search will return nothing.")
        print("              Check that Ollama is running and the model is pulled.")

    # Warm up the synopsis model (dolphin3) in the background so the first
    # synopsis request doesn't time out on low-RAM systems.  If a scan/embed
    # is in progress, the warmup waits for it to finish first to avoid OOM.
    warmup_thread = threading.Thread(target=_deferred_synopsis_warmup, daemon=True)
    warmup_thread.start()

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
