# Companion App — Architecture Notes

Tauri v2 native client for accessing a remote DocuBrowse server. Replaces the
abandoned browser-extension approach (see `DECISIONS.md` — Firefox `downloads.open()`
hard wall). The server (`doc_search.py`) remains the single source of truth;
the companion app is a thin client that presents the existing web UI and adds
native file-open capabilities.

## Hard Constraints

- **No VPN / NFS / SMB / FUSE.** All document access is streamed over HTTP(S).
- **API contract locked at v0.8.3.** Non-breaking additions only (see
  `bus_docs/DocuBrowse_API_Contract.docx`). One new endpoint: `/api/download`.
- **Consistent appearance across all OSs and window managers.** Client-side
  decorations (CSD) — no OS-native titlebar.
- **Linux first,** then Windows and Mac.

## Why Tauri v2

| Factor | Tauri | Electron | Flutter |
|---|---|---|---|
| Binary size | ~5 MB | ~150 MB | ~20 MB |
| Runtime | OS WebView + Rust | Bundled Chromium | Dart VM |
| Linux WM compat | WebKitGTK (all DEs) | Chromium (all DEs) | GTK only |
| Native file ops | Rust (xdg-open etc.) | Node (child_process) | Platform channels |
| Memory | ~30 MB | ~150 MB+ | ~80 MB |

Tauri uses the OS WebView (WebKitGTK on Linux, WebView2 on Windows, WebKit on
Mac). The web layer is identical HTML/CSS/JS on all platforms; Rust handles
everything that needs native access.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│  Tauri Shell (Rust)                             │
│  ┌───────────────────────────────────────────┐  │
│  │  Custom Titlebar (HTML/CSS)               │  │
│  │  ─ drag region, min/max/close, branding   │  │
│  ├───────────────────────────────────────────┤  │
│  │  WebView (forked index.html)              │  │
│  │  ─ search, browse, tags, settings UI      │  │
│  │  ─ all API calls go to remote server      │  │
│  │  ─ "Open" button → Tauri IPC, not /api/open│ │
│  └───────────────────────────────────────────┘  │
│                                                 │
│  Rust Backend (IPC commands)                    │
│  ─ download_and_open(server, path, csrf_token)  │
│  ─ get_csrf_token(server_url)                   │
│  ─ connection_test(server_url)                  │
│  ─ save_connection(url, name)                   │
└─────────────────────────────────────────────────┘
         │ HTTPS
         ▼
┌─────────────────────────────────────────────────┐
│  DocuBrowse Server (doc_search.py)              │
│  ─ existing API endpoints (v0.8.3)              │
│  ─ NEW: GET /api/download?path=...              │
│  ─ --allow-remote + optional TLS (app-dev)      │
└─────────────────────────────────────────────────┘
```

## 1. Client-Side Decorations (CSD)

Tauri config: `"decorations": false`. The OS-native titlebar is suppressed
entirely. Instead, the app renders a custom HTML titlebar inside the WebView:

- **Drag region:** CSS `app-region: drag` on the titlebar div.
- **Window controls:** Min / Max / Close buttons via Tauri's `appWindow` API
  (`minimize()`, `toggleMaximize()`, `close()`). Styled identically on all
  platforms — no GTK/Qt theming bleed.
- **Branding:** App title + optional logo pulled from server's `branding.json`
  (fetched via `/api/status` enterprise fields, or hardcoded "DocuBrowse" for
  FOSS tier).

**Why this matters on Linux:** WebKitGTK draws a GTK3 window frame. On KDE
Plasma (Qt), XFCE, or tiling WMs (Sway, i3, Hyprland), this frame looks
foreign. CSD eliminates it — the entire visible surface is our HTML, identical
everywhere.

**Tiling WM note:** Tiling WMs ignore the titlebar entirely (windows are
placed by the WM, not dragged). The custom titlebar becomes purely cosmetic
branding — which is fine. The app should also set `"resizable": true` so WMs
can tile it freely.

## 2. Server-Side: New `/api/download` Endpoint

The existing `/api/open` is localhost-only by design (it runs `xdg-open` on the
server). Remote clients need a way to **get the file bytes** instead.

### Specification

```
GET /api/download?path=<absolute-path>
CSRF required: Yes (X-CSRF-Token header)
```

**Behavior:**
1. Validate CSRF token (same as `/api/open`).
2. Verify `path` is in the document index (same check as `/api/open`).
3. Determine MIME type via `mimetypes.guess_type()` or fall back to
   `application/octet-stream`.
4. Stream the file as a binary response with headers:
   - `Content-Type: <mime-type>`
   - `Content-Disposition: attachment; filename="<basename>"`
   - `Content-Length: <file-size>`
5. If file is missing from disk: `{"ok": false, "error": "missing"}` (404).
6. If file's mount is unavailable: `{"ok": false, "error": "unmounted"}` (404).

**Not localhost-restricted.** Unlike `/api/open`, this endpoint is usable from
any allowed remote client. The index check prevents arbitrary filesystem reads.

**Streaming:** Use chunked reads (64 KB blocks) to avoid loading multi-GB files
into memory. Python `http.server` supports this via a generator or
`shutil.copyfileobj`.

## 3. Client-Side: Rust IPC Commands

The Tauri Rust backend exposes these IPC commands to the WebView JS:

### `download_and_open`

```rust
#[tauri::command]
async fn download_and_open(
    server_url: String,
    path: String,
    csrf_token: String,
) -> Result<(), String>
```

1. `GET {server_url}/api/download?path={path}` with `X-CSRF-Token` header.
2. Stream response to a temp file (preserve original extension for MIME
   association: e.g. `docubrowse_XXXX.pdf`).
3. Open with platform opener:
   - Linux: `xdg-open <temp-path>`
   - macOS: `open <temp-path>`
   - Windows: `start "" <temp-path>`
4. Return success to JS. Temp file cleanup: on app exit or after a configurable
   TTL (default 1 hour).

### `get_csrf_token`

```rust
#[tauri::command]
async fn get_csrf_token(server_url: String) -> Result<String, String>
```

1. `GET {server_url}/` — fetch the HTML landing page.
2. Parse `<meta name="csrf-token" content="...">` from the response body.
3. Cache the token in memory (it's per-server-process, so valid until server
   restarts).
4. On 403 from any subsequent call, re-fetch the token automatically.

### `connection_test`

```rust
#[tauri::command]
async fn connection_test(server_url: String) -> Result<ServerInfo, String>
```

1. `GET {server_url}/api/status` — no CSRF needed.
2. Return version, uptime, component health. Used by the connection setup UI.

## 4. WebView Layer (Forked index.html)

The app ships a modified copy of the server's `index.html`. Key changes:

1. **Base URL is configurable.** All `fetch()` calls in the JS use a
   `window.DOCUBROWSE_SERVER` variable instead of relative paths. Set by the
   Rust backend at WebView init via `tauri::webview::WebviewBuilder::initialization_script()`.

2. **"Open" button intercepted.** The original UI calls `POST /api/open` which
   is localhost-only. The forked JS instead calls:
   ```js
   await window.__TAURI__.invoke('download_and_open', {
     serverUrl: window.DOCUBROWSE_SERVER,
     path: doc.path,
     csrfToken: window.DOCUBROWSE_CSRF
   });
   ```

3. **CSRF token injected.** On startup, Rust fetches the token and injects it:
   ```js
   window.DOCUBROWSE_CSRF = "<token>";
   ```
   The forked JS reads this instead of parsing the `<meta>` tag (which only
   exists in server-rendered HTML).

4. **Settings page:** `/api/browse` (filesystem browser) is kept — it browses
   the *server's* filesystem for adding scan dirs. This is intentional; the
   admin is configuring the server.

5. **Dark/light mode:** Preserved as-is (CSS variables, toggle in settings).

## 5. Connection Management

The app needs a "connect to server" UI before showing the main DocuBrowse
interface. This is a Tauri-native screen (not part of the forked index.html).

### Stored connections

Persisted in a local JSON file (`~/.config/docubrowse-client/connections.json`
on Linux, platform-appropriate paths on Win/Mac via Tauri's `app_data_dir()`):

```json
[
  {
    "name": "Home Server",
    "url": "https://192.168.1.50:8643",
    "last_connected": "2026-06-15T14:22:08Z"
  }
]
```

### Connection flow

1. User enters server URL (or picks from saved list).
2. App calls `connection_test` → shows server version, doc count, health.
3. On success, app calls `get_csrf_token` → token cached in memory.
4. WebView loads the forked `index.html` with `DOCUBROWSE_SERVER` and
   `DOCUBROWSE_CSRF` injected.
5. If server restarts (CSRF token changes), any 403 triggers an automatic
   token re-fetch. If re-fetch fails (server down), show a reconnect banner.

### TLS handling

The `app-dev` branch already has TLS support (self-signed cert generation via
`setup-tls` wizard). The Tauri app should:

- Accept self-signed certs after user confirmation (pin the cert fingerprint).
- Store the pinned fingerprint alongside the connection entry.
- Warn (but not block) on certificate changes.

## 6. Branding

The `app-dev` branch has a branding module (`branding.json`). When the app
connects to a server:

1. Fetch branding config from `/api/status` (enterprise tier exposes
   `branding` fields) or from a dedicated endpoint if added later.
2. Apply to the custom titlebar: app title, logo, accent color.
3. Fallback: "DocuBrowse" title, default icon, default blue accent.

For FOSS-tier servers that don't expose branding, the app uses hardcoded
defaults. No branding fetch failure should block the connection.

## 7. Cross-Platform Build Strategy

### Phase 1: Linux (WebKitGTK)

- Build dependency: `libwebkit2gtk-4.1-dev`, `libgtk-3-dev`
- Package formats: `.deb` (Debian/Ubuntu), `.rpm` (Fedora), AppImage (universal)
- Tauri v2 bundles all three via `tauri build`
- Test matrix: GNOME (Wayland), KDE Plasma (Wayland + X11), Sway, i3
- **testDebian** serves as the server-side testbed

### Phase 2: Windows (WebView2)

- WebView2 is pre-installed on Windows 10 1803+ and all Windows 11
- Package: `.msi` installer via Tauri's WiX bundler
- No additional runtime dependencies

### Phase 3: macOS (WebKit)

- WebKit is always present on macOS
- Package: `.dmg` via Tauri bundler
- Universal binary (x86_64 + aarch64) via `--target universal-apple-darwin`

## 8. Project Structure

```
docubrowse-client/
├── src-tauri/
│   ├── Cargo.toml
│   ├── tauri.conf.json          # decorations: false, identifier, window size
│   ├── src/
│   │   ├── main.rs              # Tauri entry, register IPC commands
│   │   ├── commands/
│   │   │   ├── download.rs      # download_and_open
│   │   │   ├── connection.rs    # connection_test, get_csrf_token
│   │   │   └── config.rs        # save_connection, load_connections
│   │   └── lib.rs
│   └── icons/                   # App icons (all sizes)
├── src/
│   ├── index.html               # Forked from server's index.html
│   ├── connect.html             # Connection manager screen
│   ├── titlebar.js              # Custom titlebar logic
│   ├── titlebar.css             # Titlebar styling
│   └── patches.js               # JS overrides (open→IPC, base URL, CSRF)
├── package.json                 # For any JS build tooling (optional)
└── README.md
```

## 9. Security Considerations

- **CSRF token is memory-only.** Never written to disk. Re-fetched on each
  app launch and on 403.
- **Index-validated downloads.** `/api/download` only serves files in the
  document index — same guard as `/api/open`.
- **TLS cert pinning.** Self-signed certs are pinned per-connection to prevent
  MITM after initial trust.
- **No credential storage.** The current FOSS tier has no auth; enterprise SSO
  tokens are handled by the server, not the client (Section 4.1 of the API
  contract notes future enterprise lockdown options).
- **Temp file cleanup.** Downloaded files in temp dir are cleaned on exit and
  on a 1-hour TTL to avoid leaving sensitive documents on disk.

## 10. Implementation Order

1. **Server: `/api/download` endpoint** — add to `doc_search.py` on `app-dev`.
   Small, testable with curl against testDebian.
2. **Scaffold Tauri project** — `cargo create-tauri-app`, set `decorations: false`.
3. **Custom titlebar** — HTML/CSS/JS, drag region, window controls.
4. **Connection manager** — connect.html + Rust IPC for test/save/load.
5. **Fork index.html** — wire `DOCUBROWSE_SERVER`, intercept open→IPC.
6. **download_and_open** — Rust: stream file, temp save, xdg-open.
7. **CSRF auto-refresh** — handle 403 → re-fetch token → retry.
8. **Branding** — pull from server, apply to titlebar.
9. **Packaging** — Linux first (.deb, .rpm, AppImage), then Win/Mac.
10. **Test matrix** — GNOME, KDE, Sway on Linux; Windows 10/11; macOS.

## 11. Open Questions

- **Offline search cache?** Could cache the document index locally for
  offline browsing (no file open, but search/browse). Deferred — adds
  significant complexity for a v1.
- **Multi-server?** The connection manager supports multiple saved servers.
  Should the UI allow switching without restarting? Deferred to v2.
- **Auto-discovery?** mDNS/Avahi to find DocuBrowse servers on the LAN.
  Nice-to-have, not required.
- **Update mechanism?** Tauri has a built-in updater plugin. Worth enabling
  from the start, but the update server infrastructure is out of scope here.

## 12. Implementation Status (2026-06-19)

| Step | Status | Notes |
|---|---|---|
| 1. Server: /api/download | **Done** | Tested against testDebian, md5 verified |
| 2. Scaffold Tauri project | **Done** | Compiles, builds, runs on Fedora/KDE |
| 3. Custom titlebar (CSD) | **Done** | All buttons working (capabilities added) |
| 4. Connection manager | **Done** | Save/load/delete connections, test button |
| 5. Fork index.html | **Done** | Fetch monkey-patch, CSRF injection, all UI working |
| 6. download_and_open | **Done** | Verified end-to-end from UI |
| 7. CSRF auto-refresh | **Done** | apiPost wrapper retries on 403 |
| 8. Branding | Not started | |
| 9. Packaging | Not started | Decisions captured in enterprise DECISIONS.md |
| 10. Test matrix | In progress | KDE/Wayland tested; GNOME, Sway, Win, Mac pending |

### Additions not in original plan

- **CORS support on server.** `_cors_headers()` + `do_OPTIONS()` added to
  `doc_search.py` when `--allow-remote` is active. Required for WebView
  cross-origin fetch to the remote server.
- **CSP disabled.** Tauri v2 blocked inline `onclick` handlers despite
  `'unsafe-inline'` in `script-src`. CSP set to `null` as workaround.
  **Security debt** — must refactor inline handlers to `addEventListener`
  and re-enable strict CSP before enterprise release.
- **Tauri v2 capabilities.** `capabilities/default.json` added with explicit
  permissions for window close/minimize/maximize. Required by Tauri v2
  (silently denied without them).
- **DMABUF renderer fix.** `WEBKIT_DISABLE_DMABUF_RENDERER=1` set in
  `main.rs` before WebKitGTK init. Fixes ~30s UI freeze on NVIDIA+Wayland.
  Ref: tauri-apps/tauri#13498.
- **Process exit on close.** `on_window_event` handler calls
  `std::process::exit(0)` on `CloseRequested` — CSD close button was
  hiding the window without killing the process.
- **`semantic_ready` in `/api/status`.** New FOSS-tier boolean field.
  Clients can check whether semantic search will return results.
- **Server admin controls hidden.** Settings button and `checkConfig()` banner
  disabled in the client — those configure server-side paths.

### Repository structure (decided 2026-06-19)

- **FOSS repo** (`DocuBrowser`, public): server, browser UI, API docs.
- **Enterprise repo** (`DocuBrowse-Ent`, private): `access_enterprise/`,
  `docubrowse-client/`, `DECISIONS.md`.
- Both enterprise directories are in `.gitignore` in the public repo.
  Files remain on disk for development but are not tracked publicly.
- **Git history scrub needed** before public release.

---

*Written for the `app-dev` branch. See enterprise repo `DECISIONS.md` for
the browser-extension abandonment rationale, the pivot to native app, and
all deferred planning items.*
