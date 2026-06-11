#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
DocuBrowse search server.
HTTP server on port 8643 with merged keyword + semantic search.
"""

import json
import os
import math
import socket
import sqlite3
import struct
import subprocess
import sys
import time
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import URLError

from docubrowse_db import get_db


DEFAULT_PORT = 8643
OLLAMA_HOST = "http://localhost:11434"
EMBEDDING_MODEL = "nomic-embed-text"
SYNOPSIS_MODEL = "dolphin3:latest"
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
            return data.get('embedding')
    except Exception:
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


class DocSearchHandler(BaseHTTPRequestHandler):
    """HTTP request handler for document search."""

    db_path     = None          # Will be set by server
    server_port = DEFAULT_PORT  # Will be set by server

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def do_GET(self):
        """Handle GET requests."""
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
            elif path == '/api/open':
                self.handle_open(query)
            elif path == '/api/config':
                self.handle_config()
            elif path == '/api/delete':
                self.handle_delete(query)
            elif path == '/api/synopsis':
                self.handle_synopsis(query)
            elif path == '/api/ignore-dirs':
                self.handle_ignore_dirs()
            elif path == '/api/scan-dirs':
                self.handle_scan_dirs()
            elif path == '/api/browse':
                self.handle_browse(query)
            else:
                self.error_response(404, "Not found")
        except Exception as e:
            self.error_response(500, str(e))

    def do_POST(self):
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            if path == '/api/config':
                self.handle_config_post()
            elif path == '/api/ignore-dirs':
                self.handle_ignore_dirs_post()
            elif path == '/api/scan-dirs':
                self.handle_scan_dirs_post()
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

        conn = get_db(self.db_path)

        # Prepare query embedding for semantic search
        query_embedding = None
        if mode in ['both', 'semantic']:
            query_embedding = embed_text(q)

        # Get all documents
        all_docs = conn.execute('''
            SELECT d.id, d.name, d.title, d.author, d.subject, d.description, d.path,
                   d.modified_at, GROUP_CONCAT(dt.tag, ',') as tags,
                   de.embedding
            FROM documents d
            LEFT JOIN doc_tags dt ON d.id = dt.doc_id
            LEFT JOIN doc_embeddings de ON d.id = de.doc_id
            GROUP BY d.id
        ''').fetchall()

        results = []
        q_lower = q.lower()

        for doc_row in all_docs:
            doc_id, name, title, author, subject, desc, path, modified_at, tags_str, embedding_blob = doc_row

            fts_score = 0.0
            sem_score = 0.0

            # Keyword/FTS matching
            if mode in ['both', 'keyword']:
                name_lower    = (name    or '').lower()
                title_lower   = (title   or '').lower()
                author_lower  = (author  or '').lower()
                subject_lower = (subject or '').lower()
                desc_lower    = (desc    or '').lower()
                tags_lower    = (tags_str or '').lower()

                # Simple keyword matching with boosts
                if q_lower in title_lower:
                    fts_score += 0.8
                elif q_lower in name_lower:
                    fts_score += 0.6
                if q_lower in author_lower:
                    fts_score += 0.7   # strong — searching by author name is explicit intent
                if q_lower in subject_lower:
                    fts_score += 0.5
                if q_lower in desc_lower:
                    fts_score += 0.3
                if q_lower in tags_lower:
                    fts_score += 0.4

                # Substring/token matching
                for token in q_lower.split():
                    if token in title_lower:
                        fts_score += 0.1
                    if token in author_lower:
                        fts_score += 0.1
                    if token in subject_lower:
                        fts_score += 0.05
                    if token in desc_lower:
                        fts_score += 0.05

            # Semantic matching
            if mode in ['both', 'semantic'] and query_embedding and embedding_blob:
                try:
                    doc_embedding = blob_to_vector(embedding_blob)
                    if doc_embedding:
                        sem_score = cosine_similarity(query_embedding, doc_embedding)
                except Exception:
                    pass

            # Merge scores based on mode
            if mode == 'keyword':
                final_score = min(1.0, fts_score)
            elif mode == 'semantic':
                final_score = sem_score
            else:  # both
                final_score = 0.3 * min(1.0, fts_score) + 0.7 * sem_score

            # Filter noise: semantic-only must exceed threshold
            if mode == 'semantic' and final_score < 0.30:
                continue

            if final_score > 0.01:  # Only include matches with some relevance
                results.append({
                    "id": doc_id,
                    "name": name,
                    "title": title or name,
                    "author": author or "",
                    "subject": subject or "",
                    "description": desc or "",
                    "path": path,
                    "tags": [t.strip() for t in tags_str.split(',') if t.strip()] if tags_str else [],
                    "modified_at": modified_at,
                    "score": round(final_score, 3),
                    "fts_score": round(fts_score, 3),
                    "sem_score": round(sem_score, 3)
                })

        # Sort by score descending
        results.sort(key=lambda x: x['score'], reverse=True)
        total_results = len(results)

        # Paginate: return only 50 per page
        paginated = results[offset:offset + limit]

        conn.close()

        has_more = (offset + limit) < total_results
        self.json_response({
            "documents": paginated,
            "query": q,
            "mode": mode,
            "count": len(paginated),
            "total": total_results,
            "offset": offset,
            "has_more": has_more
        })

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
            self.json_response({"ok": False, "error": f"File not found on disk: {path}"})
            return

        # Check if a default app is registered before firing xdg-open.
        # xdg-mime query default needs a MIME type; fall back to Python's
        # mimetypes module, then to a raw xdg-mime filetype query.
        try:
            import mimetypes
            mime, _ = mimetypes.guess_type(str(p))
            if not mime:
                # Ask xdg-mime directly (handles freedesktop magic bytes)
                r = subprocess.run(
                    ['xdg-mime', 'query', 'filetype', str(p)],
                    capture_output=True, text=True, timeout=5,
                )
                mime = r.stdout.strip() or None

            if mime:
                r2 = subprocess.run(
                    ['xdg-mime', 'query', 'default', mime],
                    capture_output=True, text=True, timeout=5,
                )
                handler = r2.stdout.strip()
                if not handler:
                    self.json_response({
                        "ok": False,
                        "error": f"No default application for this file type ({mime})"
                    })
                    return

            subprocess.Popen(['xdg-open', str(p)],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
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

        # Remove from DB: documents CASCADE deletes doc_tags + doc_embeddings.
        # doc_fts is contentless FTS5 (no cascade); orphaned rows are harmless
        # because keyword search JOINs with documents.
        try:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
            conn.commit()
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
        Settings-modal directory browser (docPath/workDir/ignoreDir)."""
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
        intends to scan with `docubrowser.py scan --doc-dir <DIR>`. No
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
            "docPath":      "/mnt/data/Documents",
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
        if not doc_path or not work_dir:
            self.error_response(400, "docPath and workDir are required")
            return

        cfg_path = Path(__file__).parent / "docubrowse.config"
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
        filepath = Path(__file__).parent / filename

        if not filepath.exists():
            self.error_response(404, f"File not found: {filename}")
            return

        try:
            with open(filepath, 'rb') as f:
                content = f.read()

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
        self.send_header('Access-Control-Allow-Origin', '*')
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
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <database_path> [port]")
        print(f"\nExample:")
        print(f"  {sys.argv[0]} /mnt/data/git/AI/DocuBrowse/du-docs.db")
        print(f"  {sys.argv[0]} /mnt/data/git/AI/DocuBrowse/du-docs.db 8643")
        sys.exit(1)

    db_path = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT

    db_path = Path(db_path)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}")
        sys.exit(1)

    # Set database path and port for handler
    DocSearchHandler.db_path     = str(db_path)
    DocSearchHandler.server_port = port

    server_address = ('localhost', port)
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
    print(f"  Listening on http://localhost:{port}")
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
