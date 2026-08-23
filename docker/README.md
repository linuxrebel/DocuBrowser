# DocuBrowse in Docker — experimental

**Status: experimental. Not recommended for daily use yet.**

We hit a wall that matters for how most people use DocuBrowse: **clicking a
document to open it in your desktop app does not work in the container.** Search,
AI, and browsing an existing index all work — but if your main workflow is
"find a doc, click it, read it in your PDF/office app," the native install is
still the right tool for now.

We are actively trying to solve the open-in-app problem (see
[The wall](#the-wall-open-in-your-desktop-app) below). Until then, treat this
stack as a preview.

---

## What works

- **Reusing your existing index — no rescan.** `./du-convert.sh` (Linux)
  discovers your document roots from `~/.docubrowser/docubrowse.config` +
  `scan_dirs.txt` and mounts each at its own absolute path, so the paths stored
  in `du-docs.db` resolve unchanged. Your native DB is used **in place**, not
  copied.
- **Full-text and semantic search** over that index.
- **Ollama sidecar** (`ai_sidecar`) for embeddings and document synopsis
  generation. GPU optional (see the commented `deploy:` block in
  `docker-compose.yml`); CPU-only works.
- **Synopsis generation** via the sidecar.
- **Downloading a file** through the download button (streams the file to the
  browser).
- **Security parity with the native install.** CSRF is enforced for every peer
  (not relaxed for the container's network), the app container is immutable
  (read-only root filesystem, `cap_drop: ALL`, `no-new-privileges`, `tmpfs`
  `/tmp`), runs as your non-root user, and your documents are mounted
  **read-only**.

## What does not work

- **Opening a document in a desktop app** (the primary "open" button). You get
  *"No file opener found on PATH."* This is the wall — details below.
- **Opener-dependent / shell-out extractors at view time** (e.g. launching an
  external viewer). Extraction/indexing is unaffected; only desktop *opening*
  is.
- **No-rescan conversion on macOS or Windows.** Docker runs inside a Linux VM
  there, so a native index's absolute paths (`/Users/...`, `C:\...`) cannot be
  mounted 1:1. On those platforms, install fresh and do a **full scan +
  configure your document directories in the web UI**. `du-convert.sh` is Linux
  only and refuses to run elsewhere.

## The wall: open-in-your-desktop-app

The document is already on your disk — so why can't the container open it?

- The **server is headless** (distroless: no `gio`/`xdg-open`, no desktop
  session), so it can't launch an app.
- The **browser can't either** — a web page is sandboxed and cannot open a
  local file path in a desktop application or follow a `file://` link.
- So even though the file sits at, say, `/mnt/data/Documents/x.pdf` on both the
  host and (via the identity mount) inside the container, neither the browser
  nor the container process can hand it to your PDF viewer.

Downloading a second copy to `~/Downloads` makes no sense when the original is
right there, so we have not made "open" fall back to download.

### What we're evaluating

The identity mount gives us a lever: the path inside the container is the *same*
path on the host, so anything in your host desktop session can open it. Under
consideration:

1. **A thin host-side opener bridge** — a small helper running in your session
   that the container asks to `xdg-open <path>`. Keeps the container minimal and
   opens in your real apps. (Current front-runner.)
2. **Sharing the host D-Bus session bus** into the container so `gio open`
   routes to your desktop. Works, but breaks the distroless/no-shell property
   and widens the security surface.
3. **Inline view in a browser tab** — render PDFs/images/text in the browser.
   Not your desktop app, but no saved copy either.

No decision yet. If you need click-to-open-in-app today, **use the native
install.**

---

## Quick start (Linux, converting an existing native install)

```bash
cd docker
./du-convert.sh          # discovers roots, mounts them, brings the stack up
#   --dry-run            # show what it would do, touch nothing
```

Then open the UI:

- **http://localhost:8643**

The stack is two services: `docubrowse` (the distroless app) and `ai_sidecar`
(Ollama + models). See `docker-compose.yml` for the full configuration and
overridable variables (`DOCUBROWSE_DATA_DIR`, `DOCUBROWSE_DOC_DIR`).

Stop it with:

```bash
docker compose --env-file ~/.docubrowser/docker.env down
```

## Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Two-service stack: app + Ollama sidecar |
| `Dockerfile.docubrowse` | Multi-stage distroless app image |
| `Dockerfile.ai_sidecar` | Ollama sidecar (non-root) |
| `ollama-entrypoint.sh` | Sidecar: serve + idempotent model pull |
| `du-convert.sh` | Linux: convert a native install to Docker without a rescan |
| `test_du_convert.sh` | Test for the converter's root discovery |

---

## Path forward: Enterprise (client-based) — where the wall dissolves

The open-in-app wall above is a **browser** limitation, not a container one. The
Enterprise deployment has a **desktop client**, and a client is not sandboxed:
it can write a temp file and invoke the OS opener. With a client in front of it,
the containerized server becomes viable **with all features intact**.

**Open flow (Enterprise):** the client requests the file over
`GET /api/download` (already implemented on this branch) → streams it to a local
temp file → invokes the local opener (`xdg-open` / `gio` / `start`). This is the
"download to temp, then open" step a browser cannot do but a client can — so the
container stays headless *by design*, not by limitation.

### Design forks to settle before building this

1. **Where the file bytes come from.**
   - *Server-authoritative (preferred):* documents live on a share mounted into
     the container; the server reads and streams them via `/api/download`. Works
     even when the client has no direct file access — one index, one file source,
     many thin clients — and it sidesteps the path-identity problem entirely.
   - *Client-local:* the client already has the files; the server holds only the
     index and "open" is a pure client-side path open. Reintroduces the
     indexed-path vs client-mount mismatch, per client.

2. **Multi-user auth + TLS — the real gap.** The current model is single-user
   (loopback + trusted-CIDR, "trusted peers, no auth"). Remote Enterprise clients
   need per-user authentication and TLS. This is now the **largest** problem —
   larger than "open," which the client solves.

3. **Token / credential in the client.** The client carries the CSRF token like
   the web UI does today, or a proper per-user API token under (2). No blocker;
   fold it into the auth design.

**Summary:** everything built on this branch — distroless hardening, the Ollama
sidecar, `/api/download`, CSRF-for-all-peers, no-rescan reuse — is the
foundation. The remaining Enterprise work is **auth + TLS + the file-source
model**, not desktop integration.
