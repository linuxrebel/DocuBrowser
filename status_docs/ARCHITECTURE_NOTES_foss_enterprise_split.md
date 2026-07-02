# FOSS / Enterprise Split — Remote Capabilities Architecture

**Date:** 2026-06-29
**Status:** In progress — Phases 1–4 complete, Phase 5 (git history scrub) next
**Author:** James Sparenberg + Claude (architecture session)

---

## Objective

Move all remote-access capabilities out of the FOSS DocuBrowse repo into the
private Enterprise repo (`DocuBrowse-Ent`). After the split:

- **FOSS** = localhost-only document search engine. One command to start,
  serves the person sitting at the machine. No network exposure.
- **Enterprise** = remote-capable deployment behind a customer's existing
  reverse proxy (Nginx, Apache, IIS). Adds TLS, CORS, file streaming,
  branding, SSO, and extended monitoring.

---

## Design Principles

1. **Web-server-agnostic.** The Enterprise Python backend is a plain HTTP API
   on a local socket. It works behind Nginx, Apache, IIS, or any reverse
   proxy. No server-specific features (no `X-Accel-Redirect`, no `.htaccess`
   generation) in the application layer. Config templates ship for all three.

2. **Reverse proxy handles infrastructure.** TLS termination, static file
   serving, rate limiting, connection management, HTTP/2, and gzip are the
   proxy's job — not Python's. The Python process never faces the network
   directly in production.

3. **SSO at the proxy layer.** Authentication is handled by the reverse proxy
   or a sidecar (e.g. `oauth2-proxy` for Nginx, `mod_auth_openidc` for
   Apache, Windows Authentication / OIDC modules for IIS). The Python
   backend receives the authenticated identity as a trusted header
   (`X-Forwarded-User`, `X-Auth-Request-Email`). No OIDC/SAML library
   needed in the Python code for v1.

4. **FOSS stays simple.** `doc_search.py` remains a single-file stdlib HTTP
   server binding to loopback. No imports from Enterprise, no feature flags,
   no `try: import access_enterprise`. The `access_enterprise` import that
   exists today gets removed.

5. **Enterprise extends, never forks.** The Enterprise server subclasses the
   FOSS `DocSearchHandler`. A bug fix in FOSS search logic automatically
   applies to Enterprise via the submodule.

---

## Architecture

### Production deployment (Enterprise)

```
          Internet / Corporate LAN / VPN
                     │
              ┌──────▼──────┐
              │ Reverse Proxy│  Customer's existing web server
              │ (Nginx /     │  ─ TLS termination
              │  Apache /    │  ─ CORS for companion app (tauri://localhost)
              │  IIS)        │  ─ SSO gate (oauth2-proxy / mod_auth_openidc / IIS auth)
              │              │  ─ Rate limiting, access logs, HTTP/2
              └──────┬───────┘
                     │  proxy_pass / ProxyPass / ARR rule
                     │  → http://127.0.0.1:8643  (or Unix socket)
              ┌──────▼──────┐
              │  Enterprise   │  Python API server
              │  Python API   │  ─ Subclassed from FOSS DocSearchHandler
              │               │  ─ /api/download (file streaming)
              │               │  ─ /api/branding
              │               │  ─ Extended /api/status
              │               │  ─ Auth header → role mapping
              └──────┬────────┘
                     │
              ┌──────▼──────┐
              │ Core Engine  │  FOSS (git submodule)
              │              │  ─ scan/embed/index, SQLite + FTS5
              │              │  ─ search/synopsis logic, Ollama
              └──────────────┘
```

### Local deployment (FOSS, unchanged)

```
              ┌──────────────┐
              │ Browser      │  http://localhost:8643
              │ (same machine│
              └──────┬───────┘
                     │
              ┌──────▼──────┐
              │ doc_search.py│  Binds 127.0.0.0/8 only
              │              │  Serves index.html + /api/*
              │              │  No TLS, no CORS, no remote
              └──────┬───────┘
                     │
              ┌──────▼──────┐
              │ Core Engine  │  Same code as Enterprise uses
              └──────────────┘
```

---

## What moves out of FOSS

### From `doc_search.py` — remove these:

| Item | Lines (approx) | Reason |
|------|----------------|--------|
| `--allow-remote` flag parsing in `main()` | 1663–1700 | Remote bind is Enterprise-only |
| `allow_remote` class attribute on `DocSearchHandler` | 357 | No remote mode in FOSS |
| `allowed_hostnames` population (gethostname/fqdn) | 1695–1700 | Only needed for remote Host validation |
| Remote branch in `_host_allowed()` | 395–404 | FOSS allows loopback only; simplify method |
| `_cors_headers()` method + `_CORS_ALLOWED_ORIGINS` | 1567–1598 | CORS only needed for cross-origin (remote) |
| `do_OPTIONS()` preflight handler | 1600–1604 | CORS preflight; no cross-origin in FOSS |
| `handle_download()` | 1020–1088 | File streaming for remote clients; local uses xdg-open |
| `_load_tls_context()` | 1630–1660 | TLS termination moves to reverse proxy |
| `handle_branding()` | 648–680 | Enterprise feature |
| `try: from access_enterprise import branding` | 44–46 | No Enterprise imports in FOSS |
| `enterprise_mode` flag + extended `/api/status` block | 356, 636–646 | FOSS gets minimal status only |
| `DocuBrowseServer.local_only` toggle | 333, 1710 | Hardcode to always-local |
| `/api/download` route in `do_GET` | 468–471 | Endpoint removed |
| `/api/branding` route in `do_GET` | 466–467 | Endpoint removed |
| CORS calls in `json_response` / `error_response` | 1613, 1621 | No CORS in FOSS |

### From `docubrowser.py` — remove these:

| Item | Reason |
|------|--------|
| `allow_remote` config key parsing | No remote config in FOSS |
| `--allow-remote` passthrough to `doc_search.py` in `cmd_start()` | Server is always local |
| `setup-tls` subcommand (if present) | TLS is proxy's job in Enterprise |
| Planned `remote on/off/status` CLI command | Never build in FOSS |

### Files that move to Enterprise repo:

| File | Disposition |
|------|-------------|
| `tls.json` | Enterprise only (proxy handles TLS) |
| `certs/` directory | Enterprise only |
| `branding.json.example` | Enterprise only |
| `access_enterprise/` | Already gitignored; stays Enterprise-only |
| `docubrowse-client/` | Already gitignored; stays Enterprise-only |

---

## What stays in FOSS

Everything not listed above. Specifically:

- **Core engine:** scan_docs, embed_docs, docubrowse_db, all extractors,
  dup_detect, purge_pii, hardware_utils, ensure_ollama
- **Local HTTP server:** doc_search.py (stripped of remote code), binds
  loopback only, serves index.html + all `/api/*` endpoints except
  `/api/download` and `/api/branding`
- **CLI:** docubrowser.py — start, stop, restart, status, rescan, scan-file,
  embed, purge, duplist, dupclean, scan-missing, report, open
- **Frontend:** index.html, settings.html (localhost browser UI)
- **`/api/open`** — stays; it's local-only by design (runs xdg-open on the
  server, which IS the user's machine)
- **Install/uninstall scripts** — FOSS install is local-only
- **systemd unit** — for running as a local service

---

## Enterprise repo structure

```
DocuBrowse-Ent/
├── core/                              # git submodule → FOSS DocuBrowse repo
│   ├── doc_search.py                  #   (the clean, local-only FOSS server)
│   ├── scan_docs.py
│   ├── embed_docs.py
│   ├── docubrowse_db.py
│   ├── index.html
│   └── ...
├── access_enterprise/
│   ├── __init__.py
│   ├── server.py                      # Enterprise HTTP server (see below)
│   ├── branding.py                    # Branding config loader (existing)
│   ├── download.py                    # /api/download handler (moved from FOSS)
│   ├── auth.py                        # Trusted-header auth + role mapping
│   └── admin.py                       # Future: audit log, user management
├── docubrowse-client/                 # Tauri v2 companion app (existing)
│   ├── src/
│   └── src-tauri/
├── deploy/
│   ├── nginx/
│   │   ├── docubrowse.conf.template   # Nginx reverse proxy config
│   │   └── oauth2-proxy.cfg.template  # SSO sidecar config
│   ├── apache/
│   │   └── docubrowse.conf.template   # Apache ProxyPass + mod_auth_openidc
│   ├── iis/
│   │   └── web.config.template        # IIS ARR reverse proxy + Windows Auth
│   └── systemd/
│       ├── docubrowse-api.service     # Python backend unit
│       └── docubrowse-proxy.service   # Optional: bundled Nginx unit
├── docubrowse-ent.py                  # Enterprise CLI (extends FOSS CLI)
├── branding.json.example
├── tls/                               # Cert templates, setup-tls script
├── DECISIONS.md
├── LICENSE                            # Separate from FOSS license
└── README.md
```

---

## Enterprise server design (`access_enterprise/server.py`)

The Enterprise server subclasses the FOSS handler. It does NOT fork or copy
`doc_search.py` — it imports and extends it:

```python
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from doc_search import DocSearchHandler, DocuBrowseServer
from access_enterprise.download import handle_download
from access_enterprise.branding import load_branding
from access_enterprise.auth import get_user_from_headers


class EnterpriseHandler(DocSearchHandler):
    """Extends FOSS handler with remote-access capabilities."""

    enterprise_mode = True

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Enterprise-only routes
        if path == '/api/download':
            handle_download(self, parse_qs(parsed.query))
            return
        elif path == '/api/branding':
            self.handle_branding()
            return

        # Everything else → FOSS handler
        super().do_GET()

    def handle_branding(self):
        """Return branding config for this instance."""
        ...

    def handle_status(self):
        """Extended status with doc counts, model info, config."""
        # Call super for base status, then extend
        ...
```

Key points:

- `super().do_GET()` handles all existing FOSS routes — search, tags, stats,
  config, synopsis, browse, open, letters, ignore-dirs, scan-dirs.
- Enterprise adds `/api/download` and `/api/branding` on top.
- `handle_status` overrides the FOSS version to add extended fields
  (doc/embedded counts, model presence, config details).
- The auth module reads trusted headers from the reverse proxy and maps
  them to roles. No session management in Python — the proxy handles that.

---

## Reverse proxy responsibilities

The reverse proxy handles all infrastructure concerns. The Python backend
is unaware of which proxy is in front of it.

| Responsibility | Nginx | Apache | IIS |
|----------------|-------|--------|-----|
| TLS termination | `ssl_certificate` | `SSLEngine on` | IIS binding |
| Static files | `location /` → root | `DocumentRoot` / `Alias` | Static content handler |
| Reverse proxy | `proxy_pass` | `ProxyPass` / `ProxyPassReverse` | ARR URL Rewrite |
| SSO | `oauth2-proxy` sidecar or `auth_request` | `mod_auth_openidc` | Windows Auth / OIDC module |
| Rate limiting | `limit_req_zone` | `mod_ratelimit` | Dynamic IP Restrictions |
| Access logs | `access_log` | `CustomLog` | IIS Logging |
| CORS headers | `add_header` directives | `mod_headers` | Custom Headers |
| Gzip | `gzip on` | `mod_deflate` | Dynamic Compression |
| HTTP/2 | `http2 on` | `Protocols h2` | HTTP/2 in bindings |

### What the proxy does NOT do

- **Search logic** — always proxied to Python
- **File access validation** — Python checks the document index before
  streaming; the proxy cannot make this decision
- **Synopsis generation** — Ollama interaction stays in Python
- **Database operations** — all SQLite access is in Python

### CORS handling

With a reverse proxy, CORS becomes simpler. The proxy serves both the
static frontend AND proxies the API, so from the browser's perspective
everything is same-origin. **No CORS headers are needed at all** for the
browser UI.

The companion desktop app (Tauri) makes cross-origin requests from
`tauri://localhost`. CORS headers for this are added at the proxy level
(a simple `add_header` / `Header set` directive), not in Python. The
config templates include this.

---

## SSO architecture

### How it works

```
Browser → Proxy (checks auth cookie) → if missing, redirect to IdP
       ← IdP authenticates user, redirects back with token
       → Proxy validates token, sets auth cookie + trusted headers
       → Python backend receives request with X-Auth-Request-User header
```

### Proxy-level SSO options (per web server)

| Web Server | SSO Approach | Supported IdPs |
|------------|-------------|----------------|
| Nginx | `oauth2-proxy` sidecar + `auth_request` | Okta, Azure AD, Google Workspace, any OIDC |
| Apache | `mod_auth_openidc` (native module) | Any OIDC provider; SAML via `mod_auth_mellon` |
| IIS | Windows Authentication (Kerberos/NTLM) | Active Directory (native); OIDC via custom module |

### Python backend auth (`access_enterprise/auth.py`)

The Python backend trusts headers set by the proxy. It does NOT perform
any authentication itself:

```python
def get_user_from_headers(handler) -> dict:
    """Extract authenticated user from proxy-injected headers."""
    return {
        "email": handler.headers.get("X-Auth-Request-Email", ""),
        "user": handler.headers.get("X-Auth-Request-User", ""),
        "groups": handler.headers.get("X-Auth-Request-Groups", "").split(","),
    }

def require_role(handler, role: str) -> bool:
    """Check if authenticated user has the required role."""
    user = get_user_from_headers(handler)
    # Map IdP groups to DocuBrowse roles via config
    ...
```

Security: the proxy MUST strip these headers from incoming requests to
prevent spoofing. All three config templates include this.

---

## `/api/download` — file streaming

Moved from FOSS `doc_search.py` to `access_enterprise/download.py`.
Unchanged logic: validate path against document index, stream 64 KB
chunks, proper Content-Disposition headers.

The reverse proxy passes this through to Python because the index
validation requires database access. Python streams the file bytes
directly through the proxy to the client. This is efficient enough for
document-sized files (typically <100 MB); the proxy handles the TCP
buffering and client-side connection management.

If performance becomes an issue for very large files, a future
optimization is proxy-level file serving with an auth callback:
- Nginx: `X-Accel-Redirect` (internal redirect after Python validates)
- Apache: `X-Sendfile` via `mod_xsendfile`
- IIS: `X-Sendfile` equivalent or TransmitFile

This optimization is NOT in v1. The Python streaming approach works for
all three proxies without any server-specific code.

---

## FOSS simplification

After stripping remote code, `doc_search.py` gets simpler:

### `_host_allowed()` — simplified

```python
def _host_allowed(self) -> bool:
    """Reject requests whose Host header isn't loopback."""
    host = self.headers.get('Host', '')
    if not host:
        return True  # HTTP/1.0 client on loopback
    hostname, _, port = host.rpartition(':')
    if not hostname:
        hostname, port = port, ''
    hostname = hostname.strip('[]').lower()
    if port and port != str(self.server_port):
        return False
    return _is_loopback(hostname)
```

### `DocuBrowseServer` — simplified

```python
class DocuBrowseServer(ThreadingHTTPServer):
    """Always loopback-only. Rejects non-127.x.x.x connections."""

    def verify_request(self, request, client_address):
        try:
            addr = ipaddress.ip_address(client_address[0])
            if addr == ipaddress.ip_address('::1'):
                return True
            return addr in _LOOPBACK_NET
        except (ValueError, TypeError):
            return False
```

### `json_response` / `error_response` — drop CORS

Remove `self._cors_headers()` calls from both methods. No cross-origin
requests exist in the FOSS local-only model.

### `main()` — simplified

Remove: `--allow-remote` parsing, `allowed_hostnames` setup, TLS context
loading, TLS socket wrapping, remote access warning banner. The startup
message becomes simply:

```
DocuBrowse Search Server
  Database: /path/to/du-docs.db
  Listening on http://127.0.0.0/8:8643 (loopback only)
```

---

## Execution plan

### Phase 1: Prepare FOSS for subclassing (FOSS repo) ✅ COMPLETE

**Goal:** Ensure `DocSearchHandler` and `DocuBrowseServer` can be imported
and subclassed cleanly by the Enterprise server.

1. Verify `doc_search.py` doesn't auto-execute on import (already gated
   by `if __name__ == '__main__'` — confirm no side effects at module level
   beyond constants and class definitions).
2. Make sure the handler's route dispatch (`do_GET`, `do_POST`) calls
   methods that can be overridden cleanly (already the case — each route
   calls `self.handle_*()` which a subclass can override).
3. Extract any inline lambdas or closures in handlers into named methods
   if they block subclassing (audit needed).
4. Add `__all__` export list to `doc_search.py` so Enterprise imports are
   explicit and stable.

**Estimated effort:** 1–2 hours. Low risk — mostly verification.

**Completed:** 2026-06-30. Commit `698aed2` in FOSS repo.

### Phase 2: Build Enterprise server (Enterprise repo) ✅ COMPLETE

1. Set up FOSS repo as git submodule at `core/`.
2. Create `access_enterprise/server.py` — subclass `DocSearchHandler`,
   add `handle_download`, `handle_branding`, extended `handle_status`.
3. Create `access_enterprise/download.py` — move `handle_download` logic
   from FOSS (copy, not move, until Phase 4).
4. Create `access_enterprise/auth.py` — trusted-header reader + role mapper.
5. Create `docubrowse-ent.py` CLI — extends FOSS CLI, adds `--allow-remote`,
   starts `EnterpriseHandler` instead of `DocSearchHandler`.
6. Create `deploy/nginx/docubrowse.conf.template`.
7. Create `deploy/apache/docubrowse.conf.template`.
8. Create `deploy/iis/web.config.template`.
9. Test: Enterprise server behind Nginx on testDebian, verify companion app
   connects and all features work.

**Estimated effort:** 2–3 days. Medium risk — the subclassing and proxy
configs need integration testing.

**Completed:** 2026-06-30. Commit `4372ca2` in Enterprise repo. Git
submodule (`core/`) not yet configured — import paths reference it but
the submodule add is deferred to Phase 3 setup.

### Phase 3: Test companion app against proxy-fronted Enterprise ✅ COMPLETE

1. Verify Tauri companion app works through Nginx reverse proxy (CORS
   headers from proxy, not Python).
2. Verify download-and-open works through proxy.
3. Verify SSO flow end-to-end (oauth2-proxy + a test OIDC provider).
4. Test with Apache as reverse proxy (same Python backend, different config).
5. Document any IIS-specific considerations (test deferred until Windows
   build is available).

**Estimated effort:** 1–2 days.

**Completed:** 2026-06-30. Findings:

- Git submodule configured and working (commit `23e609e`).
- Enterprise server starts, all API endpoints respond correctly on
  testDebian (Debian 13 trixie, Python 3.13, Nginx 1.26).
- **Bug found & fixed:** `server.py` did not add repo root to sys.path,
  causing `from access_enterprise import branding` to fail. Fixed by
  adding `_REPO_ROOT` to sys.path alongside `_CORE_DIR`.
- **Bug found & fixed:** Duplicate CORS headers — proxy AND backend both
  emitted `Access-Control-Allow-Origin`. Fixed by overriding
  `_cors_headers()` in `EnterpriseHandler` to no-op (proxy owns CORS).
- **Bug found & fixed:** Nginx config emitted CORS headers for ALL
  origins, not just `tauri://localhost`. Fixed with `set $cors_origin`
  conditional in both test and production templates.
- Integration test suite created (`tests/integration_test.sh`) — 18
  tests covering direct API, proxy API (HTTPS/443), CORS, host validation,
  spoofed header stripping. All pass.
- **Architecture correction:** Enterprise is client-based (Tauri companion
  app), not browser-based. Removed static file serving from Nginx test
  config, production template, and integration tests. Standard HTTPS
  port 443, not custom ports.
- **CSRF fix:** FOSS embeds CSRF token in HTML `<meta>` tags. Enterprise
  has no HTML pages, so added `GET /api/csrf-token` JSON endpoint to
  Enterprise server. Client `csrf.rs` updated; `scraper` crate removed.
  Tauri companion app connects and authenticates successfully.
- SSO end-to-end testing deferred — requires oauth2-proxy + OIDC provider
  setup. Proxy header stripping verified (spoofed `X-Auth-Request-*`
  headers correctly blocked by Nginx).
- Apache testing deferred — same Python backend, needs Apache install +
  mod_auth_openidc config.
- IIS testing deferred — requires Windows build environment.

### Phase 4: Codebase cleanup (FOSS repo) ✅ COMPLETE — released as v0.8.4 (2026-07-02)

Removed unused code paths and experimental features from the FOSS codebase.
`doc_search.py` reduced by ~300 lines, `docubrowser.py` by ~240 lines.
Stale development files deleted, `.gitignore` cleaned. Both files pass
`py_compile` with zero stale references. Documentation (README, INSTALL,
architecture notes) updated to reflect current feature set.

### Phase 5: Git history scrub (FOSS repo)

1. Run `git filter-repo` to remove all traces of `access_enterprise/`,
   `docubrowse-client/`, `DECISIONS.md`, and any Enterprise-specific
   commits from the public repo history.
2. Force-push cleaned history.
3. Verify GitHub repo is clean.

**Estimated effort:** 1–2 hours. Must be done before any public release.

---

## Future phases (not part of this split)

These build on the Enterprise architecture but are separate efforts:

- **Gunicorn/uvicorn migration:** Replace `http.server` with a proper
  WSGI/ASGI server for better concurrency under load. Only needed if
  concurrent API requests become a bottleneck (unlikely for <100 users).
- **Relay/tunnel (prosumer tier):** A hosted service that tunnels traffic
  to a user's home DocuBrowse server without VPN. Separate access layer,
  separate product — uses the same core engine.
- **Mobile PWA:** Responsive version of index.html for mobile browsers.
  Served by the reverse proxy as static files; no native app needed.

---

## Key decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Reverse proxy, not standalone Python HTTPS | Enterprise customers have existing web infrastructure; Python's HTTP server isn't production-grade for multi-user; TLS/SSO/rate-limiting are solved problems in Nginx/Apache/IIS |
| 2 | Web-server-agnostic | Companies have expertise and preferences; ship config templates for Nginx, Apache, IIS — no application-level dependency on any one |
| 3 | SSO at proxy layer, not in Python | Avoids building/maintaining OIDC/SAML libraries; leverages mature, audited proxy modules; simplifies the Python backend to a role-reader |
| 4 | Git submodule for FOSS core | Clean dependency; Enterprise always tracks a specific FOSS version; bug fixes flow automatically; no code duplication |
| 5 | Subclass, not fork | `EnterpriseHandler(DocSearchHandler)` extends without duplicating; FOSS search/scan logic maintained in one place |
| 6 | Python streams `/api/download` directly | Simple, works with all proxies, no server-specific features; optimize with X-Accel-Redirect/X-Sendfile later only if needed |
| 7 | CORS at proxy level | Proxy serves both static frontend and proxied API as same-origin; companion app CORS handled by proxy config, not Python |
| 8 | Strip remote from FOSS last | Build and validate Enterprise first, then subtract from FOSS — safer than doing both simultaneously |

---

## Open questions

1. **Submodule pinning strategy:** Should Enterprise track FOSS `main` head,
   or pin to tagged releases (e.g. `v0.8.3`)? Pinned releases are safer;
   tracking head is faster for development. Recommendation: pin to tags for
   production, track head during development.

2. **Config file relationship:** Does Enterprise extend `docubrowse.config`
   (add Enterprise-specific keys) or use a separate `docubrowse-ent.config`?
   Separate file is cleaner — FOSS config stays untouched.

3. ~~**Static file serving:**~~ **RESOLVED (2026-06-30).** Enterprise is
   client-based (Tauri companion app) — neither the proxy nor the Python
   server serves static files. No `root`, `try_files`, or asset caching
   directives in Enterprise Nginx config. The proxy is API-only.

4. ~~**Companion app CSRF:**~~ **RESOLVED (2026-06-30).** Enterprise is
   client-based (Tauri app), not browser-based — there is no HTML page to
   embed a `<meta>` CSRF tag in. Added `GET /api/csrf-token` JSON endpoint
   to Enterprise server. Client `csrf.rs` calls this instead of scraping
   HTML. `scraper` crate removed from client dependencies. Tested and
   working through Nginx proxy on port 443.
