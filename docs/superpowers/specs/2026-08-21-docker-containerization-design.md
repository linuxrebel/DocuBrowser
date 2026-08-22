# Docker containerization (design)

**Date:** 2026-08-21
**Status:** Approved design; not yet implemented
**Target release:** TBD (after the v1.0.3 env features it depends on — those are shipped)
**Related:** [[project_status]] (v1.0.3 env features), [[DECISIONS]]

## Summary

Ship DocuBrowse as a container that behaves like an **app, not a mini-VM**:
minimal, single-process, no shell to exec into. Ollama and its models run in a
**separate sidecar container** (not baked into the app image), wired up with the
environment-variable configuration added in v1.0.3 (`OLLAMA_HOST`,
`DOCUBROWSE_*`, trusted-peer CIDRs). Delivered as a two-service Docker Compose
stack.

This is **Approach A** from the brainstorm. The alternatives — a single
all-in-one image with Ollama+models baked in (Approach B), and an
app-only/bring-your-own-Ollama image (Approach C) — were rejected: B fights the
GPU story, needs a supervisor (breaks the no-shell model), and is ~5 GB; the
sidecar split is what the v1.0.3 env work was built for.

## User requirements and how they map

1. **Build from the most minimal base, app-not-VM** → distroless (see below),
   not literal `scratch`.
2. **Keep the no-shell property (can't exec in)** → distroless has no shell,
   no package manager. Achieved.
3. **Only necessary binaries + a Python env** → multi-stage build; final image
   is distroless + the app venv, nothing else.
4. **Entrypoint is the `docubrowser` command** → `docubrowser start
   --foreground` (new flag; see "Required code changes").
5. **House Ollama + the two models** → **not in the app container.** Ollama runs
   as a sidecar service (GPU-capable, models in a volume). See "Why Ollama is a
   sidecar."

## Base image decision: distroless, not scratch or Alpine

- **`scratch`** is empty — no libc, no shared libraries. CPython + numpy +
  pdfplumber are C extensions linking glibc, libstdc++, libz, libjpeg, libssl,
  etc. Static-building the whole tree onto scratch is brittle and re-breaks on
  every dependency bump. Rejected.
- **Alpine** uses **musl libc**. The scientific wheels (numpy, pdfminer/
  pdfplumber) are glibc **manylinux** wheels; on musl, pip compiles them from
  source (gcc, gfortran, BLAS/LAPACK) — slower, larger, more fragile. Rejected.
- **Distroless** (`gcr.io/distroless/python3-debian12`) — **glibc** (wheels
  install clean, no compiler in the final image), **no shell**, no package
  manager, tiny. Chosen. It is the "as little OS as possible" option that does
  not fight the Python stack.

**Build shape (multi-stage):**
- *Builder stage* — `python:3.12-slim`: create a venv, `pip install -r
  requirements.txt` into it.
- *Final stage* — distroless python3: `COPY` the venv and the app files in.
  No pip, no shell, no build tools in the shipped image.

## Architecture: two-service Compose stack

```
┌─────────────────────────┐        ┌──────────────────────────┐
│  docubrowse (distroless)│  HTTP  │  ollama (ollama/ollama)  │
│  server on :8643        ├───────▶│  :11434, models in vol   │
│  ENTRYPOINT docubrowser │        │  gpus: all (when present)│
│    start --foreground   │        └──────────────────────────┘
└─────────────────────────┘
   docs (ro mount) + db (named vol)     models (named vol)
```

- **docubrowse service** — the distroless app image; foreground server; no
  local Ollama management.
- **ollama service** — the official `ollama/ollama` image. Pulls
  `nomic-embed-text` and `dolphin3` on first start into a named volume (~5 GB,
  once). Gets the GPU when the host has one.

## Why Ollama is a sidecar (not in the app image)

- **GPU:** a bundled Ollama in a scratch/distroless app image can't reach the
  host GPU (needs the NVIDIA container toolkit + drivers the minimal image can't
  carry). The official `ollama/ollama` image + `gpus: all` on *its* service is
  the supported GPU path.
- **Single process:** distroless has no init/supervisor — PID 1 is one process.
  Two services in one minimal container would need a supervisor, breaking the
  no-shell/app-not-VM model.
- **Size:** the two models are ~5.2 GB; baking them in makes a 5 GB+ image.
- The v1.0.3 env features exist precisely to point the app at a separate Ollama.

## The access gotcha (must-handle)

DocuBrowse is loopback-only by default and drops non-loopback peers at the TCP
accept level. When the port is published and a browser hits it, the app sees the
connection from **Docker's bridge gateway** (a `172.x` address), not loopback —
so it would reject the user's own browser.

**Therefore the container must set `DOCUBROWSE_TRUSTED_CIDRS` to the Compose
network.** And the `/24` cap added in PR #7 interacts: Docker's default network
is a `/16`, which the cap **rejects**. So either:
- pin the Compose network to a `/24` subnet (recommended — set it explicitly in
  the Compose `networks:` block), and trust that `/24`; or
- trust just the gateway `/32`.

The Compose file will set an explicit `/24` network and a matching
`DOCUBROWSE_TRUSTED_CIDRS`, documented inline.

## Environment wiring (Compose)

- `DOCUBROWSE_OLLAMA_HOST=http://ollama:11434`
- `DOCUBROWSE_DB=/data/db/du-docs.db` (named volume)
- `DOCUBROWSE_DOC_DIR=/docs` (read-only bind mount of the user's documents)
- `DOCUBROWSE_WORK_DIR=/data` (named volume — blacklists, etc.)
- `DOCUBROWSE_PORT=8643` (published to the host)
- `DOCUBROWSE_TRUSTED_CIDRS=<the /24 of the Compose network>`

## Required code changes (small)

1. **`docubrowser start --foreground`** — run the server in the foreground
   (don't `Popen(start_new_session=True)` + exit) so it can be PID 1. Today
   `cmd_start` always detaches (docubrowser.py ~427).
2. **Skip local Ollama management in container/remote mode** — when
   `OLLAMA_HOST`/`DOCUBROWSE_OLLAMA_HOST` points at a non-local host (or a
   `--foreground`/container flag is set), `start` must not try to install or
   launch a local Ollama; only verify the remote is reachable. (This is the
   `ensure_ollama` remote-gap noted during the PR #5 review.)
3. Both changes are additive and must not alter the desktop `docubrowser start`
   behavior (still detaches, still manages local Ollama).

## Deliverables

- `Dockerfile` (multi-stage: slim builder → distroless final).
- `docker-compose.yml` (docubrowse + ollama services, explicit `/24` network,
  volumes, GPU stanza with a CPU-only note).
- A model-pull step for the ollama service (idempotent, first-start).
- `.dockerignore`.
- Docs: a "Run with Docker" section in INSTALL.md / README, covering the
  volume mounts, the trusted-CIDR value, and GPU vs CPU.
- The two code changes above, with a test that `start --foreground` serves and
  does not fork, and that container mode does not attempt local Ollama install.

## Non-goals / guardrails

- No shell, no package manager, no build tools in the shipped app image.
- Ollama and models are **not** in the app image.
- No attempt to run the desktop `/api/open` (external opener) inside the
  container — it's a headless web deployment; opener-dependent features and the
  shell-out extractors (calibre/djvutxt/vsd2xml) degrade to metadata-only, as
  they already do when those tools are absent.
- Not literal `scratch`; distroless is the chosen minimal base.

## Open items to settle during implementation

- Exact distroless tag and pinned digest; Python minor version alignment with
  the builder stage.
- How the ollama service pulls models on first start (entrypoint wrapper vs a
  one-shot init service) while keeping it idempotent.
- Whether to publish the image(s) to a registry or ship the Compose file + build
  instructions only.
- Confirm the observed source IP for a published port on the target Docker
  setup (gateway `/32` vs the `/24`) and set `DOCUBROWSE_TRUSTED_CIDRS`
  accordingly.
