# DocuBrowse — Testing Notes

How to run the end-to-end feature test, plus the API-shape and environment
gotchas that are easy to re-discover the hard way.

## Quick start

`test_features.py` (repo root) drives the live HTTP API of a **running**
server: search in all three modes, DjVu/ODF-template formats, the security
guards, CSRF, and live synopsis generation.

```bash
# 1. Start a server against the DB you want to test (see "Which DB?" below)
DOCUBROWSE_DB=~/.docubrowser/du-docs.db ./docubrowser.py start

# 2. Run the suite (exit code = number of failures)
python3 test_features.py                    # full run
python3 test_features.py --skip-synopsis    # skip the slow dolphin3 call
python3 test_features.py --base http://localhost:8643

# 3. Stop it
./docubrowser.py stop
```

The suite asserts on *shape and behavior*, not on a specific corpus, so it
runs against any populated DB. DjVu/OTT checks self-skip if the sample content
isn't indexed.

## Which DB? (dev vs installed — the #1 gotcha)

`_default_data_dir()` (doc_search.py) returns the **code directory** when it's
writable (dev / running `./docubrowser.py` from a checkout), otherwise
`~/.docubrowser/` (packaged install). So:

- Running `./docubrowser.py …` **from the repo** uses a DB/config/blacklists
  **in the repo dir** — a throwaway dev instance, separate from your real data.
- The **real installed DB** lives at `~/.docubrowser/du-docs.db`.

To test **new repo code against the real installed DB**, inject the path with
the env var (this also exercises the `DOCUBROWSE_DB` feature):

```bash
DOCUBROWSE_DB=~/.docubrowser/du-docs.db ./docubrowser.py start
```

The installed `/opt/docubrowser` copy still runs the *old* code until a
reinstall — so for testing unreleased changes, always drive the repo code.

## Embeddings gotcha

`scan` / `rescan` auto-embed **by default**, but embedding is the **last**
phase — it runs only after all extraction completes (docubrowser.py, the
`if not args.no_embed:` block). A scan interrupted with Ctrl-C never reaches
it, leaving `doc_embeddings` empty and semantic search dead. Backfill without
re-scanning:

```bash
./docubrowser.py embed
```

Check with `/api/stats` → `embedded` vs `total_docs`, or
`SELECT count(*) FROM doc_embeddings;`.

## API-shape reference (what tripped the harness)

- **`GET /api/search?q=…&mode=keyword|semantic|both`** → results are under
  **`documents`** (not `results`); envelope also has `total`, `count`,
  `has_more`, `offset`, `mode`, `query`. An empty `q` returns the whole corpus.
  Result objects carry `name`, `title`, `author`, `description`, `fts_score`,
  `id`, `modified_at`, `path` — **no `doc_type`** (filter by name/path instead).
- **`GET /api/status`** → `ok`, `version`, `semantic_ready`, `components`,
  `uptime_seconds` (no doc counts here).
- **`GET /api/stats`** → `total_docs`, `embedded`, `unique_tags`.
- **`GET /api/config`** → `docPath`, `workDir`, `port`, `installed`,
  `configSource`. Honors `DOCUBROWSE_DOC_DIR` / `DOCUBROWSE_WORK_DIR` /
  `DOCUBROWSE_PORT` (env overrides the file).
- **Synopsis** — `GET /api/synopsis?path=<enc>` reads cache only and returns
  `{ok:false, needs_generation:true}` when none exists. Generation is
  **`POST /api/synopsis?path=<enc>`** — the path goes in the **query string,
  not the body** — and requires an `X-CSRF-Token` header plus a loopback
  `Origin`. First generation for a cold model can take tens of seconds.
- **CSRF** — a per-process token is injected into the served HTML (`GET /`);
  scrape it for POST/mutation tests.

## Security invariants (DB-independent, always testable)

- Foreign `Host` header → **403** (DNS-rebinding defense).
- `POST /api/delete` / `POST /api/config` / `GET /api/browse` without the CSRF
  token → **403**.
- Server binds `0.0.0.0` but `verify_request` drops non-loopback peers at the
  TCP accept level (unless `DOCUBROWSE_TRUSTED_CIDRS` lists private networks —
  that path is a separate opt-in feature).
