# DocuBrowse Project Status

**Version**: v0.9.3  
**Status**: 🟢 **STABLE — daily use, packaged for distribution**  
**Last Updated**: 2026-07-17  
**Repository**: https://github.com/linuxrebel/DocuBrowser

---

## Executive Summary

DocuBrowse indexes a local document corpus (currently `/mnt/data/Documents`, ~10K files)
using PDF/DOCX/EPUB/HTML/TXT/MD extraction, SQLite FTS5 keyword search, and Ollama semantic
embeddings. The CLI is complete and in daily use. v0.6.0 adds format expansion, config UI, delete from UI, and duplicate detection.

**Key Metrics**:
- Supported formats: PDF, DOCX, PPTX, XLSX, ODT, ODS, ODP, EPUB, MOBI, AZW3, AZW, HTML, TXT, Markdown
- Search latency: <150ms typical
- Worker parallelism: physical-core-aware (tested up to 8 workers)
- PDF resilience: pdfplumber primary, pypdf fallback for >8,000-object files, layout=False secondary fallback, scanned PDF detection

---

## v0.6.0 — What's in this release

### Duplicate Detection (2026-06-09)
- **`dup_detect.py`**: New module with exact-duplicate detection (SHA256, size pre-filter) and near-duplicate detection (numpy batched cosine similarity, union-find clustering).
- **`duplist`**: CLI command to list exact and/or near-duplicate groups with recoverable space.
- **`dupclean`**: Interactive TUI — shows labeled [A]/[B] file pairs, prompts "Keep A / Keep B / Keep Both (skip) / Q", confirm before delete. Deletes from disk + DB + FTS index (per-doc commit).
- `--near-dups` flag and `--threshold` (default 0.97) for both commands.

### Config Read/Write (2026-06-09)
- `GET /api/config` — reads real config file (first of `/etc/docubrowse.config`, then `./docubrowse.config`); returns `docPath`, `workDir`, `port`, `installed`, `configSource`.
- `POST /api/config` — writes `./docubrowse.config` with `doc_dir`, `work_dir`, `port`.
- Settings UI: port is now a configurable field; info message uses neutral color (not orange).
- `docubrowse.config` added to `.gitignore`.

### DOCX Support (2026-06-09)
- `docx_extractor.py`: python-docx extracts paragraphs, tables, and core properties (title, author, subject).
- Integrated into `scan_docs.py` and `docubrowse_db.py`.

### Ebook Support (2026-06-09)
- `ebook_extractor.py`: ebooklib for EPUB; mobi package + Calibre fallback for MOBI/AZW3; DRM-encrypted AZW indexed metadata-only.
- Integrated into `scan_docs.py`.

### Delete from UI (2026-06-09)
- `GET /api/delete` endpoint; 🗑 trash icon on each result card; custom confirm modal (Cancel is default); removes from disk and DB (FTS cleaned).

---

## v0.5.0 — What's in this release

### PDF Extraction Hardening (2026-06-09)
- **pypdf pre-check**: Before calling pdfplumber, read trailer `/Size` via pypdf. If >8,000 objects, route to pypdf (lazy-loading) instead — fixes Security_of_Cloud-based_systems.pdf class of hang (root cause: ExifTool metadata appended 22,421 xref objects without GC; pdfminer builds complete object map on open).
- **layout=False fallback**: After default pdfplumber extraction yields no text, retry with `layout=False` to skip spatial analysis on complex/spread-layout PDFs.
- **Scanned PDF detection**: If both passes yield no text, check `pdf.pages[0].images`. Image-only PDFs are indexed as `doc_type='scanned'` with placeholder text; path appended to `ocr_list_pdfs.txt`.
- **Import fix**: `pypdf` imported independently of pdfplumber (both `HAS_*` flags can be True simultaneously). `_extract_file` now forwards `doc_type` in its return dict.

### New Commands (2026-06-09)
- **`scan-file --file PATH`**: Extract and index one file in the main process (no executor). Auto-removes from `scan_blacklist.txt` if listed (explicit retry). Refuses `pii_blacklist.txt` entries. Embeds afterward unless `--no-embed`. `--file` uses `nargs='+'` so paths with spaces work without quoting.
- **`report`**: Walk doc directory, print extension breakdown (count/percent/size/scannable label). No DB changes.
- **`stopall`**: Kill all running scans, embeds, and the server.

### Scan UX (2026-06-09)
- **`--limit N`**: Process at most N unindexed files per run; next run resumes naturally (already-indexed files are skipped before applying limit).
- **Unfiltered scan prompt**: `scan`/`rescan` without a type filter shows file-type breakdown and prompts y/N before proceeding.
- **Report subcommand**: Scannable types listed individually; all others collapsed to single `(unscannable)` line.

### DB rename (2026-06-09)
- Database renamed from `docs.db` → `du-docs.db`. Example file moved to `du-docs.db.example`. All references updated.

### Author/Subject fields (2026-06-09)
- `documents` table: `subject TEXT` column added.
- `doc_fts` virtual table: `author`, `subject` columns added; migration drops/recreates FTS and repopulates if column is missing.
- `pdf_extractor.py`: extracts `Subject` from pdfplumber and pypdf metadata.
- `scan_docs.py`: passes `subject` through `_extract_file` return dict; updated INSERT for both tables.
- `doc_search.py`: both browse and search paths SELECT `d.author, d.subject`; keyword scoring adds 0.7 boost (author phrase), 0.5 (subject phrase), 0.1/0.05 per token.

---

## Session History

### 2026-07-17 — Email, RTF, CSV/TSV, config-ish plain text, .vdx

Audit of `/mnt/data/Documents` (~9,479 files) found DocuBrowse was already
covering 8,258 files (87%). Sweep to close the gap:

- **New `eml_extractor.py`** — stdlib `email` package. Subject → title,
  From → author, To/Cc/Date → subject field. Prefers text/plain body;
  falls back to text/html tag-stripped. Attachment filenames appended so
  name-searches still hit. No new dependency. Verified end-to-end on a
  synthetic RFC 822 fixture.
- **New `csv_extractor.py`** — stdlib `csv` with delimiter auto-sniffing
  (comma / tab / semicolon / pipe). First 500 rows as pipe-delimited text;
  header row lands in the description field so column names weigh into
  keyword search. Handles `.csv` and `.tsv`. Verified on both.
- **New `rtf_extractor.py`** — `striprtf` (pure Python, MIT). Added to
  requirements.txt. Graceful degradation when the module isn't installed:
  file indexed metadata-only, path appended to `rtf_missing_striprtf.txt`
  next to `du-docs.db`, same pattern as `visio_legacy_missing.txt` for
  missing vsd2xml. Verified degradation path works (sidecar written,
  file indexed with filename as title).
- **`.vdx`** — Visio 2003 XML. Routed through `markup_extractor`'s XML
  tag-strip path; also lands in `_MARKUP_DIAGRAM_EXTENSIONS` so it gets
  a `diagram` tag alongside `.vsdx` / `.drawio`. Verified: title extracted
  from `<Title>`, tags `diagram` + `markup` + `vdx`.
- **Plain-text expansions** — `.ini`, `.conf`, `.cfg`, `.log`, `.lst`
  added to `DEFAULT_EXTENSIONS`. They fall through to `_extract_text_file`
  with no new code. Verified each type indexed as expected.
- **CLI** — `_TYPE_MAP` in `docubrowser.py` gets `eml`, `email` (alias),
  `rtf`, `csv`, `tsv`, `ini`, `conf`, `cfg`, `log`, `lst`, `vdx`.
- **Sidecar plumbing** — new `RTF_MISSING_LIST_FILENAME` constant,
  `_rtf_missing_list_add()` helper mirroring `_legacy_visio_list_add()`,
  `_needs_striprtf` flag threaded through the worker return dict and
  both the multi-worker `_index_result` and the single-file
  `cmd_scan_file` logging paths. `.gitignore` extended.
- **Docs** — README (Formats + new bullet block + Prerequisites + Key
  Scripts + File Structure + Blacklist Files), User_Guide (types list),
  Admin_Guide (intro + Python packages table), DECISIONS.md (D-14),
  this file. INSTALL.md unchanged — no new system-level dependency (only
  a pip-level one).
- **HTTrack cruft** — the audit also surfaced ~356 files under a mirror
  directory with query-string extensions (`.htmlc=s;o=d` and siblings)
  and `.ccd` sidecars. Not code work; user-space cleanup via
  `docubrowser ignore add <mirror-root>` recommended.

### 2026-07-17 — SGML/XML markup family + reST/AsciiDoc/LaTeX

- **New extractor `markup_extractor.py`** — 280 lines, stdlib-only.
  Handles two families:
  - XML/SGML (`.xml`/`.xhtml`/`.sgml`/`.sgm`), DocBook (`.docbook`/`.dbk`),
    SVG, and feeds (`.rss`/`.atom`/`.opml`) — schema-agnostic tag-strip
    (DOCTYPE + XML decl + PI + comments + CDATA + `<script>`/`<style>`
    stripped; entities unescaped). Title/author/subject sniffed from
    well-known local-names (`<title>`, `<dc:title>`, `<author>`,
    `<dc:creator>`, `<subject>`, `<dc:subject>`) BEFORE stripping.
  - reST (`.rst`), AsciiDoc (`.adoc`/`.asciidoc`), LaTeX (`.tex`/`.latex`)
    — passthrough (all markup becomes searchable text) with per-format
    title heuristics: reST underline lines, AsciiDoc `= Title`, LaTeX
    `\title{}` / `\section{}`. LaTeX also captures `\author{}` and strips
    line-`%` comments.
  See `status_docs/DECISIONS.md` D-13 for the schema-agnostic-vs-per-format
  reasoning.
- **Integration** — `DEFAULT_EXTENSIONS` extended; new
  `_MARKUP_XML_EXTENSIONS` / `_MARKUP_TEXT_EXTENSIONS` frozensets in
  `scan_docs.py`; dispatch branch routes both families through
  `extract_markup`. All markup files get a `markup` browse-filter tag;
  SVG additionally gets a `diagram` tag alongside `.vsdx`/`.drawio`/`.puml`.
  Keyword-generation gate extended so tags are auto-derived from the
  extracted body.
- **CLI** — `_TYPE_MAP` in `docubrowser.py` gets `xml`, `xhtml`, `sgml`,
  `sgm`, `docbook`, `dbk`, `svg`, `rss`, `atom`, `opml`, `rst`, `adoc`,
  `asciidoc`, `tex`, `latex`. Users chain individual types.
- **Docs** — README (Formats + Markup family bullet + Key Scripts + File
  Structure), User_Guide and Admin_Guide (introductions and format list),
  DECISIONS.md (D-13), this file. INSTALL.md unchanged — no new
  runtime dependency.
- **QA** — Isolated Python calls exercised every family (DocBook XML,
  bare XML, SGML with entities, SVG, RSS, reST with underline title,
  AsciiDoc, LaTeX with `\title`/`\author` + `%` comment). All extracted
  cleanly with correct title/author capture. Syntax check green on all
  three edited `.py` files. Next: end-to-end `scan-file` run through the
  real CLI + QA subagent pass.

### 2026-07-17 — Visio, draw.io, PlantUML, Mermaid format support

- **New extractor `visio_extractor.py`** — handles four families of diagram
  formats, all returning the standard extractor result dict so
  `scan_docs._extract_file` treats them like every other type:
  - Modern Visio (`.vsdx`/`.vsdm`) — OOXML zip parsed with stdlib
    (`zipfile` + `xml.etree.ElementTree`). Walks every `<Shape><Text>` on
    every page, prepends the page display name from `pages.xml`, and
    reads `docProps/core.xml` for title/author/subject/keywords. Verified
    on a synthetic fixture (title/author/subject captured, nested-group
    shape text captured).
  - Legacy Visio (`.vsd`/`.vss`/`.vst`) — shells out to `vsd2xml` from
    the optional `libvisio-tools` package (chose (b) in DECISIONS.md
    D-12). When `vsd2xml` is absent, the file is indexed metadata-only
    (filename as title, empty body) and the path is appended to
    `visio_legacy_missing.txt` — same append-only convention as
    `ocr_list_pdfs.txt`. Rescanning after installing libvisio-tools
    updates the existing row in place.
  - draw.io / diagrams.net (`.drawio`/`.dio`) — stdlib-only. Handles
    both plain `<mxfile><diagram><mxGraphModel>...` and the compressed
    variant (raw-deflate → base64 → URL-encode) that draw.io writes by
    default. Extracts every `mxCell.value` and `object.label` (HTML tags
    stripped, `<br>` normalized to newlines) and page names from
    `<diagram name="...">`. Verified on `bus_docs/DocuBrowse_Architecture.drawio`
    and a compressed synthetic fixture.
  - PlantUML (`.puml`/`.plantuml`) and Mermaid (`.mmd`) — routed through
    the existing plain-text path; source is indexed verbatim so keyword
    and semantic search both work. `doc_type` is set to the extension so
    the front-end can style them.
- **Diagram tag** — every diagram result gets a `diagram` tag for easy
  browse/filter alongside per-diagram-type tags.
- **CLI** — new type aliases in `_TYPE_MAP` in `docubrowser.py`:
  `vsdx`, `vsdm`, `vsd`, `vss`, `vst`, `drawio`, `dio`, `puml`,
  `plantuml`, `mmd`. Users can chain them (`scan vsdx drawio puml`).
  The unfiltered-scan file-type prompt picks up the new extensions
  automatically via `DEFAULT_EXTENSIONS`.
- **Docs updated** — README.md (Formats, Prerequisites, Key Scripts,
  File Structure, Blacklist Files), INSTALL.md (new 3.4a-equivalent
  section), Admin Guide (§3.4a and Software Dependencies table), User
  Guide (supported types list), DECISIONS.md (D-12), .gitignore
  (`visio_legacy_missing.txt`).
- **QA:** module-level syntax check passes on `scan_docs.py`,
  `docubrowser.py`, `visio_extractor.py`. Isolated extraction tests
  green on real .drawio, synthetic .vsdx, compressed .drawio, and the
  vsd2xml-missing degradation path. Next up: end-to-end `scan-file` run
  through the real CLI + QA subagent pass.

### 2026-06-28 — v0.8.3.1: Show/Unhide hidden documents

- **Show Hidden toggle** — "Show 🙈" button in the results bar (next to page
  count) toggles visibility of hidden documents. When active, hidden cards
  reappear with a 👀 icon and "hidden" tag chip. Button label flips between
  Show/Hide. Works across All Documents, letter-filtered, and search views.
- **Unhide action** — 👀 icon on hidden cards calls `POST /api/remove-tag`
  to strip the "hidden" tag. Icon swaps back to 🙈 and tag chip is removed
  inline (no page reload).
- **`POST /api/remove-tag`** — new endpoint removes a single tag from a
  document. CSRF-protected. Returns updated tag list.
- Updated dark/light mode screenshots.
- All changes ported to Enterprise client.

### 2026-06-28 — v0.8.3: Tagging, hide/delete icons, dark/light palette refresh

- **`POST /api/add-tags`** — new endpoint adds one or more comma-separated
  tags to a document. CSRF-protected. Deduplicates against existing tags.
- **Tag modal** — 🔖 icon on each card opens a modal to enter tags manually.
- **Hide action** — 🙈 icon adds a "hidden" tag; card fades out.
- **Card icon bar rearranged** — icons now: 📋 copy, 🔖 tag, 🙈 hide, ❌ delete.
  All use emoji instead of Unicode symbols.
- **`DELETE /api/delete`** — migrated from GET to DELETE method. Old GET path
  preserved for backwards compatibility.
- **Dark mode palette** — new deep navy/indigo scheme replacing the old grey.
- **Light mode palette** — new warm cream/white scheme replacing the old stark white.
- All changes ported to Enterprise client.

### 2026-06-27 — v0.8.2: UI polish and button styling

- **File path hidden in local mode** — the `doc-path` line on each card only renders
  when accessing remotely (useful for knowing what you're downloading). Local users
  see a cleaner card without the redundant path.
- **Open/Download buttons restyled** — changed from dim grey (`var(--text-dim)` border
  and text) to accent blue (`var(--accent2)`) with a filled hover state. Buttons now
  look clearly clickable instead of greyed out.
- Merged app-dev to main, pushed.
- Version bumped to v0.8.2.

### 2026-06-22 — Enterprise client: HTTPS proxy, reload, server switcher, download modal

**Enterprise Client (Tauri v2):**
- **API proxy through Rust IPC** — WebKitGTK's JavaScript `fetch()` rejects self-signed
  certs with no override available. Created `api_proxy` Rust IPC command using reqwest
  with `danger_accept_invalid_certs(true)`. The fetch monkey-patch in index.html now
  routes all `/api/` calls through IPC instead of direct HTTP, bypassing WebView TLS
  restrictions entirely.
- **Reload button** added to CSD titlebar (↻ icon, `titlebar-reload`).
- **Server switcher dropdown** — clicking the server name badge in the titlebar shows a
  dropdown of all configured servers (from `connections.json`) with the current server
  marked active (●). Clicking a different server fetches a new CSRF token via IPC,
  updates sessionStorage, and reloads. A "+ New Server" item navigates to `connect.html`.
- **Download complete modal** — compact centered modal showing filename and save
  directory after a successful download, with an OK dismiss button.
- **Download/Open buttons on cards** — Enterprise client shows both Open and Download
  buttons. Open launches via Tauri IPC `download_and_open`; Download saves to user's
  Downloads directory via `download_to_disk`.

**FOSS Server/CLI:**
- **CLI health check fixed for HTTPS** — `server_stats()` now tries HTTPS first with
  `ssl.CERT_NONE`, then falls back to HTTP. `server_url()` helper auto-detects scheme.
- **Open/Download buttons (FOSS)** — replaced the old clickable file path link.
  `isLocal` (localhost/127.x.x.x) shows Open button; remote shows Download button.
- **Self-signed cert generated** — `certs/docubrowse.crt` and `.key` with SANs covering
  localhost, common LAN IPs, and wildcard local domains. Valid 10 years.
- **Test server migrated** from testDebian to test2Debian (10.110.180.74).

### Next session (TODO)
- ~~Build `docubrowser remote on|off|status` CLI command~~ — **N/A as of v0.8.4**
  (FOSS is localhost-only; remote access is a Pro feature).
- Still un-verified on the VM: system-mode (sudo) install, and a real scan of
  ~/Documents + web-UI click-through.
- Installer field-test fixes (user/system split, pre-flight, docubrowser CLI
  rename) are committed (…5ac639c, c1b26ed) but NOT yet pushed — push once
  James confirms the manual UI drive looks good.

### 2026-06-14 — v0.8.1 bugfix: stale example DB schema
- Diagnosed HTTP 500 ("no such column: d.subject") on fresh installs: `du-docs.db.example`
  was built against a pre-author/subject/synopsis schema, causing the lazy migration in
  `init_db` to race against the first search request on a new install.
- Regenerated `du-docs.db.example` using `init_db` directly — full current schema
  (documents + FTS5 with author/subject/synopsis). Fresh installs no longer need migration
  on first request. Bumped to v0.8.1, tagged, pushed, tarball rebuilt.

### 2026-06-13 — Unified multi-directory document list + v0.8.0 release
- Merged the Settings docPath field and the separate "additional directories"
  panel into ONE "Document directories" list (all dirs equal: add/Browse/remove).
  First entry maps to config doc_dir, the rest to scan_dirs; removing the primary
  promotes the next. doc_dir is now optional (handle_config_post allows empty
  docPath and preserves allow_remote).
- rescan/scan now index EVERY configured directory (resolve_doc_dirs = doc_dir +
  scan_dirs); an explicit --doc-dir overrides to one. This delivers the
  long-deferred multi-root scanning.
- Verified locally on Bairn: multi-dir scan indexed files from two dirs into one
  DB (count 3 across dirA+dirB); Playwright drove the unified list end-to-end
  (add→primary, add→scan-dir, remove-primary→promotion, remove-all→empty),
  0 console errors. (The CentOS VM was offline during this, so install-path
  retest on the VM is still owed.)
- Cut **v0.8.0**: version bumped across README/INSTALL/User-Guide/project_status,
  git tag v0.8.0, tarball rebuilt. Not pushed.

### 2026-06-13 — Installer field-test fixes + opt-in remote access (CentOS Stream VM)
- Reworked install.sh/uninstall.sh into a clean user vs system split, added
  full pre-flight dependency checks, renamed the CLI to `docubrowser`, fixed
  wrapper perms/location, and added requirements.txt (numpy/pptx/openpyxl).
  Verified end-to-end on testCent: user-mode installs, starts as the user (no
  systemd), serves on 8643.
- Added opt-in LAN access (#13): install prompt / DOCUBROWSE_ALLOW_REMOTE env;
  doc_search --allow-remote binds 0.0.0.0 (default 127.0.0.1), Host allow-list
  permits the box's own names + IP-literals (still blocks DNS-rebinding),
  mutation guard is now same-origin so the UI works over LAN with CSRF intact;
  installer opens firewalld/ufw, uninstaller closes it. Verified both ways
  cross-network from another host (remote: 200 + evil-Host 403; local-only:
  binds 127.0.0.1, firewall closed, connection refused off-box). Auth still
  deferred by design.

### 2026-06-12 — Audit remediation, batch 3 (PII, frontend, delete-helper) + doc sync
- **SEC-L1/L2** PII detector now validates instead of shape-matching: SSN via
  SSA allocation rules (dashed/spaced/labeled-contiguous forms), credit card
  via length + IIN prefix + Luhn. Verified 1.0 precision/recall on a 26-string
  corpus (old missed 9 TPs, false-flagged 6 TNs) — commit 053ee7f.
- **SEC-L3** frontend: Back/Next guard uses pageSize (was hardcoded 50, broke
  at 25/100); a renderSeq token makes a newer search supersede an in-flight
  page load (no stale grid); loadMore errors use a toast. Verified via
  Playwright — commit 235963e.
- **CQ-M4** consolidated 5 copies of document-deletion into one
  `delete_documents`/`delete_document` helper in docubrowse_db (enables FK,
  cascades, chunks, documents the contentless-FTS orphan policy once); all
  callers routed through it. Verified on a temp DB — commit 31baea8.
- **Docs:** README updated to current status (security model, FTS5 BM25 +
  cached-matrix search algorithm, POST/CSRF API table, Recent Changes);
  version kept at v0.7.3 per James. DECISIONS.md and this file updated.
- **Audit is effectively complete.** Remaining tail is low-stakes only:
  CQ-L7 (wait_for_memory max-wait + lazy nvidia-smi), CQ-L3/L5 (cosmetic/perf).
- **Follow-up for next session:** the CQ-M4 helper was unit-tested directly but
  the 5 callsites (UI delete, dupclean, purge, ignore-dir purge, scan-missing)
  weren't each re-run end-to-end through it — worth a quick verification pass.

### 2026-06-12 — Audit remediation, batch 2 (SEC-M1, CQ-H3, CQ-H4/M1, M/L sweep)
- Completed the remaining audit tracker items. All tested + committed:
  - **SEC-M1** data-derived inline onclick → data-* + delegated listeners
    (XSS closed; verified hostile title stays inert) — 735ecff
  - **CQ-H3** worker-death "suspect isolation": only the true offender is
    blacklisted, innocents indexed, scan resumes — 340a733
  - **CQ-M1 / CQ-H4** init_db once per process; scanner/embedder commit on a
    ~2s time budget (frees the WAL writer for server writes) — a217b66
  - **Medium/Low sweep** — CQ-M2 (read_pid PermissionError), CQ-M3 (precise
    /proc worker kill), CQ-M5 (NULL-timestamp re-embed), CQ-M6 (purge EOF
    abort), CQ-M7 (bounded text read), CQ-L1/L2/L4/L6/L8/L9 — 1679413, b1265fa
- **Intentionally deferred** (rationale in DECISIONS.md → batch 2): CQ-M4
  (shared delete helper refactor), SEC-M2 (realpath — mooted by CSRF), CQ-L3,
  CQ-L5, CQ-L7, SEC-L1/L2 (PII regex + Luhn — behavior change), SEC-L3
  (frontend nits). These want their own focused, separately-tested passes.
- Net: every Critical + High + Medium-security audit finding is fixed; the
  remaining open items are low-severity polish/perf and one refactor.

### 2026-06-12 — Audit remediation, batch 1 (8 of 12 items)
- Worked the 2026-06-12 code-quality & security audit's recommended fix order.
  Fixed and committed, each tested (curl contract tests, isolated throwaway-DB
  tests, and Playwright UI runs, with a verification subagent for DB/UI checks):
  - **SEC-H1** Host-header allow-list (kills DNS rebinding) — 9bfe578
  - **SEC-C2** removed `Access-Control-Allow-Origin: *` — 9bfe578
  - **CQ-C1** fixed `embed_text` response key → server semantic search works
    again (returned 0 results before) — 9bfe578
  - **CQ-C2** dupclean no longer corrupts disk/DB (dropped the throwing
    `DELETE FROM doc_fts`) — 9bfe578
  - **SEC-C1** CSRF: per-process token injected into served HTML;
    `/api/delete` + `/api/open` moved GET→POST; all mutations require
    `X-CSRF-Token` + loopback Origin — 84a68d5
  - **SEC-H2** `/api/browse` gated behind the same token — 84a68d5
  - **CQ-H2** `INSERT ... ON CONFLICT(path) DO UPDATE` replaces
    `INSERT OR REPLACE` (no more wiping tags/embeddings/synopsis on
    re-index) — 1811125
  - **CQ-H1** search now uses FTS5 `bm25()` + a cached numpy embedding matrix
    instead of loading the whole corpus per request (keyword ~4ms, both
    ~55ms; totals corrected) — 2369057
- The server is no longer remotely exploitable (no unauth GET mutations, no
  ACAO:\*, Host-validated, CSRF-gated) and both previously-silent flagship
  failures (server semantic search, dupclean consistency) are fixed.
- **Remaining audit items (deferred to next session):** SEC-M1 (inline
  onclick → addEventListener), CQ-H3 (BrokenProcessPool mis-blacklist),
  CQ-H4+CQ-M1 (commit cadence + init_db once), Medium/Low sweep. See
  `status_docs/DECISIONS.md` → "Audit Remediation — Session 2026-06-12".

### 2026-06-11 (continued) — Synopsis cold-start error after reboot
- Diagnosed: after a fresh reboot, the first synopsis request hit Ollama
  before the model was loaded into memory, exceeding the 30s timeout and
  showing a generic "Synopsis generation failed or timed out" error — even
  though the synopsis generated fine moments later.
- `generate_synopsis()` now returns `(text, reason)` with reason
  `"empty"`/`"timeout"`/`"error"`; `SYNOPSIS_TIMEOUT_SECS` raised 30s → 90s;
  `handle_synopsis` returns a reason-specific message, e.g. for timeout:
  "The AI model is still loading after a recent restart — this can take a
  minute the first time. Please wait a moment and try again."
- Restarted doc_search.py to pick up the change. Committed f94a72a.

### 2026-06-11 (continued) — Service-unreachable errors and synopsis loading reassurance
- Reported: if doc_search.py (and Ollama) are stopped while a page is still
  loaded, clicking a doc title gives a misleading "network error" that
  implies an internet problem, when really the local DocuBrowse service
  itself is down.
- Added `friendlyError(e)` in index.html: detects the generic `TypeError`
  fetch() throws when it can't reach the server at all, and shows "Cannot
  reach the DocuBrowse service. Make sure it is running, then reload this
  page." instead of the raw error. Applied to all fetch catch blocks
  (search, render, filter by letter, load more/prev, synopsis, open file,
  delete).
- Verified by killing doc_search.py with the page already loaded and
  clicking "View synopsis" via Playwright — modal correctly showed the new
  message.
- Also addressed: synopsis modal's "Generating synopsis..." message now
  updates at 6s and 25s with reassuring follow-up text, so a slow cold-start
  Ollama request (up to ~90s) doesn't look hung.
- Restarted doc_search.py. Committed f017e08.

### 2026-06-11 (continued) — Settings page UI tweaks
- Removed leftover modal-era `max-width` restriction; settings page now uses
  full available width.
- Added a "Done" button in the header that saves config and returns to the
  search tab (`window.close()`, falling back to redirecting to `/`).
- Relabeled and redesigned the Ignored Directories panel: added description
  text, "Add a directory to exclude" input row, and a "Currently excluded
  directories" list with inline ✕ remove buttons (replacing the old
  select-then-remove pattern).
- Adding an excluded directory now shows a confirm dialog warning that
  already-indexed documents under that path will be purged. Removing one
  shows an alert that a rescan is needed to re-index it.
- Verified via Playwright: full-width layout, add/remove confirm+alert
  dialogs, and Done button all working correctly with 0 console errors.
- Items 7 (multiple top-level doc directories), 8 (handle moved/missing/
  deleted docs), and 9 (logo icon) logged as deferred future work in
  DECISIONS.md.
- Committed 4adfa59.

### 2026-06-11 — Alpha index bar: global server-side letter filter
- Index bar (0-9, A-Z) now queries `/api/search?letter=X` for ALL matching
  documents, not just the currently-loaded page. Paginated by the existing
  page-size preference; Next/Back and page-size changes work while a letter
  filter is active. Clicking the active letter again returns to All Documents.
- `doc_search.py`: `/api/search` empty-query path accepts `letter=A-Z` or
  `letter=0-9` (digits/symbols bucket via `NOT GLOB '[A-Z]'`), parameterized
  (no injection risk).
- `index.html`: new `currentLetter` state var; `filterByLetter` is now async
  and server-backed; `loadMoreTop`/`loadMorePrev`/`changePageSize` updated to
  branch on `currentLetter`.
- Verified via Playwright (O=53 results across pages, 0-9=613, toggle off,
  page-size change while filtered). QA PASS (added `isLoadingMore` guard to
  `filterByLetter` per QA recommendation).
- Committed a899ff8.

### 2026-06-11 (continued) — Index bar persistence + Home button
- Reported: clicking a letter in the alpha index bar made the bar disappear
  (root cause: `meta.innerHTML = ...` reassignment in `filterByLetter` and
  other render paths wiped out the appended `.index-bar` div).
- Refactored `renderIndexBar()` into a single reusable async function called
  after every `meta.innerHTML` reassignment (`doSearch`, `filterByLetter`,
  `loadMoreTop`, `loadMorePrev`, `renderAll`), so the bar persists across
  All Documents, letter-filtered, search, and paginated views.
- Added a "Home" button as the first item (left of "0-9"), same `.index-btn`
  styling, `onclick="renderAll()"` — lets users return to All Documents from
  any view including search results.

### 2026-06-11 (continued) — Ignored Directories UX overhaul + Additional Scan Directories panel
- Ignored Directories panel: reworked the add row to "Browse…"/"Add"/"Clear"
  buttons; browsing now live-syncs the displayed path straight into the
  `/path/to/exclude` field (no "select this" step). Added description text
  under "Currently excluded directories" and a confirm (OK/Cancel) before
  removing an entry.
- New "Additional Scan Directories" panel (simplified clone of the Ignored
  Directories UX): users can browse/add/clear/remove extra top-level
  directories to scan, persisted to `scan_dirs.txt` via
  `_load_scan_dirs()`/`SCAN_DIRS_FILENAME` in scan_docs.py and new
  `/api/scan-dirs` GET/POST endpoints in doc_search.py.
- Adding a scan directory shows a reminder alert with the exact CLI command:
  `cd "<workDir>" && python3 docubrowser.py scan --doc-dir "<path>" --limit 100`
  — running it again resumes with the next 100 unindexed files.
- Verified via Playwright: 0 console errors, panel renders correctly, browse
  live-sync works, add shows the correct reminder/command and updates the
  list, remove confirms and clears back to the empty-state message.

### 2026-06-11 (continued) — Consolidated scan-directory management into General panel
- James felt the standalone "Additional Scan Directories" panel duplicated
  the goal of the General panel's docPath field and made users jump between
  sections to manage scan locations.
- Moved the "Add an additional directory to scan" controls (Browse…/Add/
  Clear input row, dir browser, and "Additional directories being scanned"
  list) to live directly under docPath in the General panel. Backend
  (`scan_dirs.txt`, `/api/scan-dirs`) unchanged.
- Updated docPath's and workDir's "browse" buttons to the new live-sync
  style (path syncs as you navigate, no "select this" button), matching the
  Ignored Directories / scan-dir browse UX.
- Verified via Playwright: 0 console errors; docPath Browse… opens directly
  under the field with live-sync and no "select this"; scan-dir add/remove
  still works correctly from its new location.
- Added `getActiveLetters()` with a module-level cache of `/api/letters` so
  the active/disabled state of letter buttons doesn't refetch on every
  render.
- Verified via Playwright: fresh load (0 console errors), clicked "M" →
  index bar persisted with Home as first button, clicked "Home" → returned
  to All Documents; searched "linux" → results rendered with index bar
  (incl. Home) intact; clicked Home from search results → returned to All
  Documents. 0 console errors throughout.

### 2026-06-10 — Settings page refactor, dir-browser fix
- Fixed dir-browser sizing/reachability bug: `.dir-browser { max-height: min(320px, 35vh) }` in
  index.html, verified at 1280x720 and 1440x900 (commit 3861602).
- Confirmed accidental ignoreDirs addition (`/mnt/data/Documents/Visual Studio 2022`) was intentional
  per James.
- Moved Settings UI from a modal (`#settingsModal`) to a standalone page: new `settings.html`,
  new `GET /settings` route in `doc_search.py`, gear icon now opens it via `window.open('/settings',
  '_blank')`. Removed modal markup/JS/CSS from index.html (kept `.modal`/`.btn-secondary` for the
  synopsis/delete modals). Verified via Playwright (zero console errors on `/` and `/settings`,
  dir-browser functional), QA PASS, committed c62231b.
- Cleaned up an accidental commit of Playwright test artifacts and screenshots; added
  `.playwright-mcp/` and `*.png` to `.gitignore` (commit 65b2d1a).
- Updated README.md settings screenshot caption/note (screenshot itself still stale — needs
  regeneration against `/settings`).
- **Pending**: James flagged "a bunch of UI tweaks needed" for the new settings page —
  specifics not yet gathered, to be addressed next session.
- See `status_docs/DECISIONS.md` for full details on all of the above.

### 2026-06-09 (continued) — PDF hardening, scan-file, packaging
- Investigated Security_of_Cloud-based_systems.pdf hang: confirmed pdfminer hangs on 22,421-object xref traversal at `open()` time. pypdf opens in 0.05s (lazy load).
- Implemented pypdf pre-check in `pdf_extractor.py`: trailer `/Size` >8,000 → skip pdfplumber, use pypdf.
- Added `scan_single_file()` to `scan_docs.py` with `_blacklist_remove()`.
- Added `scan-file` subcommand to `docubrowser.py`.
- Fixed `--file` argument to use `nargs='+'` after argparse hyphen-in-path parsing failure.
- Tagged v0.5.0, wrote README/INSTALL/project_status docs, created release tgz.

### 2026-06-09 (morning) — Author/subject, scan UX, DB rename, triage
- Added author/subject as first-class fields in DB, FTS, extractor, scanner, search scoring.
- Added `--limit N`, `report` subcommand, unfiltered scan confirmation prompt.
- Renamed DB to `du-docs.db`.
- Wrote and ran `triage_blacklist.py` one-off script to reclassify existing blacklist: identified scanned PDFs vs truly broken ones, moved scanned to `ocr_list_pdfs.txt`.
- Added `ocr_list_pdfs.txt` to `.gitignore`.
- Added `layout=False` fallback in `_extract_pdfplumber`.
- Added scanned PDF detection (`doc_type='scanned'`) in `_extract_pdfplumber`.

### 2026-06-08 — Scan hardening, PII purge, open from UI
- `hardware_utils.py` — CPU/GPU/RAM detection, `recommended_scan_workers()` (4 GB/worker + 4 GB OS reserve, cap 8), `wait_for_memory()`.
- ProcessPoolExecutor hardening: `forkserver` start method → `fork` (nested function pickling), module-level `_worker_init`, SIGINT ignore, RLIMIT_AS 6 GB, RLIMIT_CPU 3000s.
- SIGALRM replaced with `resource.setrlimit()` after confirming SIGALRM is unreliable in C extensions.
- Sliding window executor pattern (`wait(FIRST_COMPLETED)`, MAX_IN_FLIGHT = workers).
- `stopall`, `cmd_rescan` auto-kills, scan PID file, process group kill.
- `purge_pii.py` — SSN/CC/DOB/MRN/DL/Passport regex scan; all-or-nothing transaction; `pii_blacklist.txt`.
- `GET /api/open` — validates path against DB index, runs xdg-open.
- Post-scan PII prompt — y/n/D (dry-run default).

### 2026-06-07 — MVP (v0.1.0)
- SQLite schema with FTS5, doc_tags, doc_embeddings.
- HTTP search server (port 8643) with hybrid search (70/30 semantic/keyword).
- PDF extraction with pdfplumber.
- Ollama embedding pipeline (nomic-embed-text:latest, 768-dim).
- Single-file frontend (index.html) with dark/light theme, pagination, tag cloud, alphabetic index bar.

---

## Current State

### ✅ Complete

**Indexing**
- [x] PDF extraction (pdfplumber + pypdf fallback)
- [x] HTML extraction (script/style strip, entity decode)
- [x] TXT/Markdown extraction
- [x] Author, subject, title metadata
- [x] Auto-generated tags (extension + directory names + content keywords)
- [x] Scanned PDF detection → ocr_list_pdfs.txt
- [x] Scan blacklist (auto-populated on failure, retriable)
- [x] PII blacklist (permanent, never re-ingest)
- [x] `scan-file` for single-file retry
- [x] `--limit N` for batch scanning

**Search**
- [x] FTS5 keyword search (title, author, subject, tags, snippet)
- [x] Semantic search (cosine similarity, 768-dim vectors)
- [x] Hybrid mode (70% semantic + 30% keyword, merged rank)
- [x] Author/subject scoring boosts

**Server & UI**
- [x] HTTP server port 8643
- [x] Dark/light theme, pagination, tag cloud, alphabetic bar
- [x] Click to open file (xdg-open), copy path to clipboard
- [x] `/api/stats`, `/api/search`, `/api/tags`, `/api/open`
- [x] Delete from UI (🗑 trash icon, confirm modal, `/api/delete`)
- [x] Tag from UI (🔖 icon, add-tags modal, `/api/add-tags`)
- [x] Hide/unhide from UI (🙈/👀 icons, `/api/remove-tag`, Show toggle)
- [x] Config read/write UI (Settings modal, `/api/config` GET + POST)

**Format Support**
- [x] PDF (pdfplumber + pypdf fallback)
- [x] DOCX (python-docx)
- [x] EPUB/MOBI/AZW3/AZW (ebooklib + Calibre)
- [x] HTML, TXT, Markdown

**Operations**
- [x] PII purge (dry-run + live)
- [x] stopall, auto-kill on rescan
- [x] report subcommand
- [x] Hardware-aware worker count
- [x] Memory pressure pause/resume
- [x] `duplist` / `dupclean` (exact SHA256 + near-dup cosine similarity)

### 📋 Pending

**Phase 2b — Remaining**
- [ ] No-extension file classification (magic bytes)
- [ ] File-type filter in search UI (`?type=pdf`)

**Phase 2 — Remaining**
- [ ] Sliding window ETA on progress bar
- [ ] ETA display format: `Xh Ym` when >60 min

**Phase 3+**
- [ ] OCR integration for scanned PDFs
- [ ] Result export (CSV/JSON)
- [ ] API key authentication
- [ ] Docker deployment

---

## File Inventory (core source)

| File | Purpose |
|------|---------|
| `docubrowser.py` | CLI entry point — all commands |
| `doc_search.py` | HTTP server, search API |
| `docubrowse_db.py` | SQLite schema and migrations |
| `scan_docs.py` | Document discovery, extraction, DB writes |
| `pdf_extractor.py` | PDF extraction (pdfplumber + pypdf) |
| `docx_extractor.py` | Word document extraction (python-docx) |
| `ebook_extractor.py` | EPUB/MOBI/AZW3/AZW extraction (ebooklib + Calibre) |
| `dup_detect.py` | Exact (SHA256) and near-duplicate (cosine) detection |
| `hardware_utils.py` | CPU/GPU/RAM detection, worker formula |
| `embed_docs.py` | Ollama embedding pipeline |
| `purge_pii.py` | PII scanner and purge |
| `ensure_ollama.py` | Ollama prerequisite checker |
| `index.html` | Frontend UI |

---

## Known Issues

See `status_docs/DECISIONS.md` for full details. Key open items:

1. **ETA drifts high** — progress bar ETA uses simple average; large PDFs hit late inflate it. Fix: sliding window average (deferred).
2. **Scanned PDFs not searchable** — indexed with placeholder; OCR deferred to Phase 3.
3. **No file-type filter in search UI** — searching "docx" returns semantically similar PDFs. Fix: `?type=` filter (deferred).
4. **ocr_list_pdfs.txt may have duplicate lines** — multiple scan runs of the same image-only PDF append the path again. OCR processing must deduplicate on read.

---

### 2026-06-12 — No-default doc_dir + configure banner + uninstall.sh
- Removed the hardcoded `/mnt/data/Documents` default doc_dir/docPath across the
  stack — "unconfigured" (empty string) is now a valid, supported state.
- `docubrowser.py`: `DEFAULT_DOC_DIR = ""`; added `require_doc_dir()` helper
  used by `cmd_rescan`, `cmd_report`, and `cmd_scan_file` — exits with a
  message pointing to the Settings gear, `docubrowse.config`, or `--doc-dir`.
- `doc_search.py`: `/api/config` now returns `"docPath": ""` when unset
  (instead of the old hardcoded default).
- `index.html`: added a `.config-banner` element + `checkConfig()` that fetches
  `/api/config` and shows "No document directory configured yet. Click the
  Settings (gear) icon..." when `docPath` is empty.
- `install.sh`: generated `docubrowse.config` no longer sets `doc_dir`
  (commented-out placeholder + comment pointing to Settings UI); final summary
  now notes that doc_dir must be configured before scanning; added
  `--exclude 'uninstall.sh'` to the rsync exclude list.
- Added `uninstall.sh` — mirrors install.sh's user/system mode detection,
  stops/disables/removes the systemd unit, removes the CLI wrapper and install
  directory, cleans up user-mode pid/log files (or system-mode
  `/run`+`/var/log` dirs), and optionally (separate confirmation) removes the
  dedicated `docubrowse` system user/group in system mode.
- Updated README.md and INSTALL.md: removed references to the old default
  doc_dir, documented the unconfigured state and configure banner, and added
  an "Uninstalling" subsection for `uninstall.sh` (keeping the old manual
  steps as "Manual / dev-checkout uninstall").
- Verified end-to-end: rsync'd a clean repo copy (no docubrowse.config) to a
  sandbox, ran the real `doc_search.py` against the real DB — `/api/config`
  returned `docPath: ""`, the index.html banner rendered correctly via
  Playwright, and `docubrowser.py rescan` exited 1 with the new
  "No document directory configured" message. Both `install.sh` and
  `uninstall.sh` pass `bash -n`; both Python files pass `ast.parse`.

### 2026-06-11 (continued) — v0.7.2 release prep
- Captured a fresh `/settings` screenshot (light mode, 1440x900) showing the consolidated General panel (docPath + additional scan directories + workDir) and Ignored Directories panel; saved as `screenshots/screenshot-settings-page.png`.
- Updated README.md: bumped version to v0.7.2 (title + footer), replaced the stale settings screenshot with the new one and removed the "stale" note, added a "Settings (`/settings`)" feature section, noted index-bar persistence + Home button under User Interface, and reworded the "Multiple top-level doc directories" Known Limitation to reflect the now-available (manual-rescan) Additional Scan Directories feature.
- Updated DECISIONS.md: reworded the "Multiple top-level doc directories" deferred row to "partially superseded" given the scan-dirs feature.
- Updated INSTALL.md tarball example from v0.5.0 to v0.7.2.
- Tagged `v0.7.2` and generated `docubrowse-v0.7.2.tar.gz` release tarball.

### 2026-06-11/12 — Handle moved/missing/deleted documents (item #8)
- Added `check_missing_path(path)` to `docubrowse_db.py`: shared helper classifying a non-existent path as `missing` (mounted, genuinely gone) or `unmounted` (can't verify, leave alone), based on walking up to the first existing ancestor and comparing `st_dev` against `/`.
- `doc_search.py`: `handle_open` now returns `{"ok": false, "error": "missing"|"unmounted", "message": ...}` for non-existent files instead of a generic error string.
- `index.html`: `openFile(path, el)` branches on the 3-way `/api/open` result — `unmounted` shows a toast (no DB change), `missing` shows a new OK-dismiss modal (`showMissingDocModal`) and on dismiss calls `/api/delete` then fades/removes the `.doc-card`.
- `docubrowser.py`: new opt-in `scan-missing [--db PATH] [--dry-run]` command — iterates all DB rows, classifies each via `check_missing_path`, deletes `missing` rows (cascades via FK), leaves `unmounted`/`present` rows untouched, and reports counts. Not part of the normal `scan`/`rescan` flow.
- Verified end-to-end via Playwright (test DB row → search → click → modal → OK → card removed + DB row deleted, cascade confirmed) and `scan-missing --dry-run` against the live 7,957-doc DB (0 deleted, 0 unmounted, all present).
- Follow-up: verified the "unmounted" toast path (test row under an empty root-fs placeholder dir → click → toast shown, no DB change) and `scan-missing` non-dry-run (1 missing row removed, 1 unmounted row correctly skipped, 7,957 still present). Test fixtures cleaned up.

### 2026-06-11 (continued) — Documentation sync (README, INSTALL, User Guide)
- Updated README.md: added `scan-missing [--db PATH] [--dry-run]` to the CLI Reference table and Command Examples, documented the `/api/open` 3-way `missing`/`unmounted` response, added `/api/scan-dirs` to the API Endpoints table, added `scan_dirs.txt` to the File Structure tree, added a "Moved/renamed files" row to Known Limitations, and added an "Unreleased — Handle moved/missing/deleted documents" Recent Changes entry.
- Updated INSTALL.md: Uninstalling section now also removes `ignore_dirs.txt` and `scan_dirs.txt`.
- Fully rewrote `info_docs/DocuBrowse_User_Guide.docx` (previously v0.5.0, 2 versions stale) to match the current v0.7.2.1 feature set: title page, What is DocuBrowse, Key Features, Requirements, Installation, full CLI Reference, Common Workflows, Using the Search UI, Settings, Moved/Missing/Deleted Documents, Troubleshooting, Files Reference, and API Quick Reference. Generated via docx-js (US Letter, branded headings, header/footer with page numbers).
- Version intentionally kept at v0.7.2.1 for this doc-only pass (James: "No, keep v0.7.2.1") — no new tag/tarball.

### 2026-06-14 — Browser opener extension attempt, then pivot to native app
- Built `/api/view` (renamed from `/api/download`, inline-only), restricted
  `/api/open` to localhost, added a `/downloads/` static route, and a
  Manifest V3 "DocuBrowse Opener" extension for Chrome/Edge and Firefox that
  intercepts result clicks and opens the file in the OS default app on the
  client machine.
- Tested end-to-end on a Debian 13 VM (testDebian, 192.168.87.29:8643) against
  real Firefox 151.0.3: Chrome path works fully; Firefox's `downloads.open()`
  user-input-handler restriction proved unworkable (doesn't survive any async
  boundary, and a notifications.onClicked workaround is unreliable on Linux
  desktops — see DECISIONS.md "Browser extension Opener abandoned").
- **Decision:** pivot to a dedicated DocuBrowse client app (talks to the
  existing `doc_search.py` HTTP API, shells out to the OS open-file command
  directly) — also enables future Windows/Mac clients against the Linux
  server.
- **Branching:** all opener-extension work preserved on
  `browser-extension-attempt` (commit `0b1013d`). `main` reset to v0.8.1
  (`d03ac5c`). New `app-dev` branch created from `main` as the working branch
  for the native-app effort going forward.
- Next session: scope the companion app (target platform(s) first — Linux
  desktop, then Windows/Mac; tech stack TBD) against `doc_search.py`'s
  existing JSON API (`/api/search`, `/api/open`, `/api/view`, `/api/synopsis`,
  etc.).


---

## 2026-06-16 — Companion App: Architecture, Scaffold, First Integration Test

### Architecture

- Wrote `status_docs/ARCHITECTURE_NOTES_companion_app.md` (340 lines, 11
  sections) covering the full Tauri v2 companion app design.
- Chose **Tauri v2** (Rust + OS WebView) over Electron and Flutter. ~5 MB
  binary, ~30 MB memory, uses WebKitGTK on Linux / WebView2 on Windows /
  WebKit on macOS.
- **Client-side decorations (CSD):** `decorations: false` + custom HTML
  titlebar. Eliminates GTK-on-KDE theming mismatch — identical appearance on
  GNOME, KDE, Sway, i3, Hyprland, Windows, macOS.
- **Streaming only:** new `GET /api/download` endpoint streams file bytes from
  server; client saves to temp, opens with OS default app. No VPN/NFS/SMB.
- Decisions recorded in `DECISIONS.md`.

### Server Changes (doc_search.py on app-dev)

- **`GET /api/download`** — new endpoint. CSRF-gated, index-validated, 64 KB
  chunked streaming, proper Content-Disposition/MIME headers. Not localhost-
  restricted (unlike `/api/open`). Tested against testDebian with curl —
  all 5 test cases pass, md5 checksum verified byte-perfect.
- **CORS headers** — `_cors_headers()` method, active only when `--allow-remote`.
  Sends `Access-Control-Allow-Origin: *`, allowed headers/methods. `do_OPTIONS`
  handler for preflight. Required for Tauri WebView (`tauri://localhost` origin)
  to reach the server.
- **API Reference updated** — TOC, CSRF table, full section 4.16 for
  `/api/download`. CORS not yet documented (deferred item).

### Client App (docubrowse-client/)

Scaffolded and built successfully on Fedora (Bairn). Project lives at
`/home/james/git/AI/DocuBrowse/docubrowse-client/`.

**Rust backend (src-tauri/):**
- `commands/connection.rs` — `connection_test()`: GET /api/status health check.
- `commands/csrf.rs` — `get_csrf_token()`: fetch + parse `<meta>` tag from
  server HTML.
- `commands/download.rs` — `download_and_open()`: stream file from
  /api/download → temp file (preserving extension) → xdg-open/open/start.
- `commands/config.rs` — `load_connections()`, `save_connection()`,
  `delete_connection()`: persist server list to
  `~/.config/docubrowse-client/connections.json`.
- Deps: tauri 2, reqwest (rustls-tls, json, stream), scraper, tempfile, dirs,
  chrono, urlencoding.

**Frontend (src/):**
- `connect.html` — connection manager: server URL input, test, save, list of
  saved servers. Styled to match DocuBrowse design language.
- `index.html` — forked from server's index.html with:
  - Inline fetch monkey-patch (runs before any API calls) rewrites `/api/*`
    URLs to remote server.
  - Titlebar HTML injected after `<body>`.
  - Settings button hidden (server admin, not client concern).
  - `checkConfig()` disabled (irrelevant for remote client).
- `patches.js` — post-load overrides: `openFile()` → Tauri IPC
  `download_and_open`, `apiPost()` with CSRF auto-refresh on 403.
- `titlebar.js` — CSD window controls (minimize/maximize/close) via Tauri v2
  `getCurrentWindow()` API with defensive fallback.
- `titlebar.css` — fixed 38px titlebar, drag region, hover states, close-red.

**Build:**
- `cargo check` passes, `cargo build` produces 234 MB debug binary (expected;
  release build will be ~5 MB).
- Required system packages: `gtk3-devel`, `webkit2gtk4.1-devel`,
  `cairo-gobject-devel`, `libsoup3-devel`.

### First Integration Test

- Launched app on Bairn (Fedora, KDE Plasma/Wayland).
- Connection screen worked — connected to testDebian (`http://testDebian:8643`),
  CSRF token acquired, navigated to main UI.
- **CSD titlebar rendered correctly** — app title, server badge, window controls.
- **Documents loaded** — 20 docs, 80 tags, cards, pagination, alphabetic index,
  search mode buttons, dark/light toggle all visible.
- **Issues found:**
  1. Click freeze after ~30s — suspected CSP missing `script-src 'unsafe-inline'`.
     Fix deployed, needs retest.
  2. Settings button showed server admin controls — hidden.
  3. Download-and-open not yet tested from UI.
  4. Close button initially non-functional — fixed with defensive Tauri v2 API
     detection.

### Open Items (deferred to next session)

- Client-side settings screen (extend connect.html).
- ~~Verify click-freeze fix (CSP).~~ → Root cause was WebKitGTK DMABUF renderer, not CSP. Fixed 2026-06-19.
- Test download-and-open end-to-end from UI. → Verified working 2026-06-16.
- Document CORS addition in API Reference and API Contract.
- Server-side Settings visibility for remote clients (read-only view?).
- Packaging: .deb, .rpm, AppImage for Linux first pass.

---

## Session: 2026-06-19 — UI Freeze Fix

### UI Freeze Root Cause & Fix

The ~30s UI freeze was caused by WebKitGTK's DMABUF renderer failing GBM
buffer allocation on NVIDIA GPUs under Wayland. This is a known upstream bug
(tauri-apps/tauri#13498) affecting all Tauri/WebKitGTK apps on NVIDIA+Wayland.

**Fix:** `WEBKIT_DISABLE_DMABUF_RENDERER=1` set in `main.rs` before
`tauri::Builder` runs. Guarded with `#[cfg(target_os = "linux")]` and
respects any user-set value. **Confirmed working** — no freeze after 60+ seconds.

### Semantic Search Fix

`doc_embeddings` table was empty on testDebian — `embed_docs.py` had never
been run. Executed manually: 20/20 docs embedded, 0 failures, 17.7s.
Semantic search now returns ranked results by cosine similarity.

### Server: `semantic_ready` added to `/api/status`

New boolean field in the FOSS-tier status response. True when: DB up, Ollama
up, embeddings exist, and embedding model present. Allows clients to disable
the semantic search button when it would return empty results.

### Desktop Client Fixes

1. **Window close not killing process.** `appWindow.close()` hid the window
   but left the process running. Added `on_window_event` handler in `lib.rs`
   to call `std::process::exit(0)` on `CloseRequested`.

2. **Titlebar buttons (minimize/maximize/close) not working.** Tauri v2
   requires explicit capability permissions — no `capabilities/default.json`
   existed. Created it with `core:window:allow-close`, `allow-minimize`,
   `allow-toggle-maximize`, and other required permissions.

3. **Inline onclick handlers not firing** (synopsis close, pagination, letter
   index, scroll-to-top). Tauri v2 was blocking inline event handlers despite
   `'unsafe-inline'` in CSP `script-src`. Fix: set CSP to `null` since this
   is a trusted local desktop app. **Security debt:** must refactor all inline
   handlers to `addEventListener` and re-enable strict CSP before enterprise
   release.

### Repository Restructure

**Product split decided:**
- **FOSS** = server + browser UI (localhost access). Public repo (`DocuBrowser`).
- **Enterprise** = access layer + companion desktop app. Private repo (`DocuBrowse-Ent`).

Actions taken:
- `access_enterprise/` added to `.gitignore`, removed from git tracking.
- `docubrowse-client/` added to `.gitignore`, removed from git tracking.
- Both copied to local enterprise repo at `~/git/AI/DocuBrowse-Ent/`.
- `DECISIONS.md` moved to enterprise repo (contains sensitive planning).
- **Git history scrub still needed** before public release (`git filter-repo`).

### Current Status — All Features Working

As of end of session, the desktop client is fully functional:
- Connection manager with saved servers
- CSD titlebar with working minimize/maximize/close
- Document browsing, pagination, alphabetic index
- Keyword search ✓, Semantic search ✓
- Tag cloud and tag filtering
- Synopsis modal (open and close)
- Download-and-open via Tauri IPC
- Dark/light theme toggle
- No UI freeze

### Open Items (tracked in enterprise DECISIONS.md)

- CSP security debt — refactor inline handlers, re-enable strict CSP
- Regenerate Embeddings button in Settings (FOSS + Enterprise)
- Server-defined instance naming (auto-fill from server API)
- Multi-server switcher UX (beyond connection manager)
- OAuth-gated Server Settings button in desktop client
- Desktop Settings screen (client-local preferences)
- Mobile web app (responsive PWA)
- Packaging: Windows .msi, Linux AppImage, server installers (macOS .dmg done 2026-07-06; .deb/.rpm/Windows zip done in v0.9.0)
- App icon/logo — vibrant multi-color, works favicon through letterhead
- Fresh install flow — verify embeddings auto-generated or prompted
- Git history scrub before public release

---

## Session: 2026-06-30 / 2026-07-02 — FOSS/Enterprise Split: Phases 1–4 → v0.8.4

### Architecture Document Written (2026-06-29)

Created `ARCHITECTURE_NOTES_foss_enterprise_split.md` — complete plan for moving
all remote capabilities out of FOSS into Enterprise:

- **Design**: FOSS = localhost-only, Enterprise = reverse-proxy backend (web-server-agnostic: Nginx/Apache/IIS)
- **SSO at proxy layer**: oauth2-proxy (Nginx), mod_auth_openidc (Apache), Windows Auth (IIS) — Python reads trusted headers only
- **Subclass pattern**: `EnterpriseHandler(DocSearchHandler)` extends without forking; FOSS as git submodule at `core/`
- **5-phase execution plan**: prepare for subclassing → build Enterprise server → test through proxy → strip FOSS → git history scrub

### Phase 1 Complete: Prepare FOSS for Subclassing

**doc_search.py changes (all QA-passed):**
- Added `__all__` export list — stable import contract for Enterprise
- `_SERVER_START_TIME` deferred from import-time to `main()` — no side effects on import
- Extracted nested `_model_present()` closure to `@staticmethod` on `DocSearchHandler`
- Safe uptime calc when imported without main()

**docubrowser.py changes (all QA-passed):**
- Added `SERVER_SCRIPT = "doc_search.py"` module constant — Enterprise overrides to launch its server
- `cmd_start()` uses the constant instead of hardcoded path

### Phase 2 Complete: Build Enterprise Server

**Enterprise repo (`DocuBrowse-Ent/`) — 9 files, 771 lines added:**

`access_enterprise/` package:
- `server.py` — `EnterpriseHandler(DocSearchHandler)` + `EnterpriseServer` + `main()`. Overrides `_host_allowed()` (trusts proxy), `handle_branding()` (Enterprise module). Inherits all FOSS search/status/download logic.
- `download.py` — standalone `handle_download()` for Phase 4 when FOSS removes its copy
- `auth.py` — `get_user_from_headers()`, `require_auth()`, `has_role()` reading proxy-injected X-Auth-Request-* headers
- `branding.py` — copy into package for clean imports
- `__init__.py` — package marker

CLI:
- `docubrowse-ent.py` — extends FOSS CLI, overrides SERVER_SCRIPT

Reverse proxy config templates:
- `deploy/nginx/docubrowse.conf.template` — proxy_pass, oauth2-proxy SSO, Tauri CORS
- `deploy/apache/docubrowse.conf.template` — ProxyPass, mod_auth_openidc, Tauri CORS
- `deploy/iis/web.config.template` — ARR URL Rewrite, Windows Auth, Tauri CORS

### Branch Policy

All work now on `development` branch in both repos. Merge to `main` when ready to release.

### Phase 3 Complete: Integration Testing

**Infrastructure:** testDebian (Debian 13 trixie, Python 3.13, Nginx 1.26.3)

**Git submodule:** FOSS repo configured as `core/` in Enterprise repo (commit `23e609e`).

**Bugs found & fixed:**
- `server.py` missing repo root on sys.path → `from access_enterprise` import failed. Fixed.
- Duplicate CORS headers (proxy + backend). Fixed by overriding `_cors_headers()` to no-op in `EnterpriseHandler`.
- Nginx CORS config too permissive (all origins got `tauri://localhost`). Fixed with conditional `set $cors_origin` in both test and production templates.

**Architecture correction:** Enterprise is client-based (Tauri companion app),
not browser-based. Removed static file serving from Nginx configs and integration
tests. Standard HTTPS port 443.

**CSRF fix:** FOSS embeds CSRF in HTML `<meta>` tags, but Enterprise has no HTML.
Added `GET /api/csrf-token` JSON endpoint to Enterprise server. Client `csrf.rs`
updated to use JSON API; `scraper` crate removed. Companion app connects successfully.

**Test results:** 18/18 pass (integration_test.sh on testDebian):
- Direct API: status, search, branding, download (CSRF check), host validation — all correct
- Nginx proxy (HTTPS/443): all API endpoints proxied, CORS origin-restricted, spoofed auth headers stripped
- SSO end-to-end: deferred (needs oauth2-proxy + OIDC provider)
- Apache proxy: deferred (same backend, needs Apache install)
- IIS: deferred (needs Windows)

### Phase 4 Complete: Codebase Cleanup (released as v0.8.4)

Removed unused code paths and experimental features that were never part of the
FOSS release, leaving a cleaner and more focused codebase.

**doc_search.py** — reduced by ~300 lines. Removed unused network configuration,
protocol negotiation, handler code, and stale imports that accumulated during
development. Server now cleanly enforces loopback-only access at the socket level.

**docubrowser.py** — reduced by ~240 lines. Removed the `setup-tls` command
and related helpers that are not applicable to a localhost application.

**Stale files removed** — deleted `branding.json.example` and other
development-only files. Cleaned `.gitignore` of entries for files that no
longer exist.

**Documentation updated** — README, INSTALL, and all architecture notes cleaned
up to accurately reflect the current feature set. Three early planning documents
(`transport_layer`, `enterprise_paid_tier`, `companion_app`) marked as superseded
by `ARCHITECTURE_NOTES_foss_enterprise_split.md`.

**Validation:** Both files pass `py_compile` with zero stale references.

**Released:** v0.8.4, tagged and published on GitHub (2026-07-02).

### Phase 5 Complete: Git History Scrub (2026-07-02)

Used `git filter-repo` to remove all enterprise artifacts from the FOSS
repo's entire commit history:

**Paths removed from history:**
- `access_enterprise/` — enterprise server code
- `docubrowse-client/` — Tauri companion app
- `browser-extension/` — abandoned browser extension attempt
- `branding.json.example` — enterprise branding
- `tls.json`, `certs/` — TLS configuration

**Branches deleted from GitHub:**
- `app-dev` — companion app development
- `browser-extension-attempt` — abandoned extension work

**Result:** 214 commits rewritten, zero enterprise paths in history.
All tags (v0.1.0 through v0.8.4) force-pushed with new hashes.
Backup preserved at `DocuBrowse-backup-pre-scrub`.

**Note:** GitHub warned about a 73MB `DocuBrowse-v0.8.3.tar.gz` in history —
a release tarball that was accidentally committed. Should be scrubbed in a
follow-up pass.

### All FOSS/Enterprise split phases complete

Phases 1–5 done. Remaining FOSS backlog: logo/icon (design task),
server packaging (decision pending).

---

## Session: 2026-07-06 — macOS .dmg Packaging

macOS is now a first-class install target, completing the v0.9.0 packaging
story (Linux RPM/DEB/tarball, Windows zip, macOS dmg).

**New files** (committed to `development` as "feat: add macOS .dmg packaging"):
- `packaging/macos/build_macos_dmg.sh` — builds
  `dist/docubrowser-foss-<version>-<release>-macos.dmg` with hdiutil.
  Same conventions as the other build scripts: VERSION extracted from
  docubrowser.py, release auto-detected from dist/, canonical APP_FILES list,
  icons/ + EndUser_docs/ included, dist/ pruned to latest 2 macOS dmgs.
  Uses only macOS built-ins (hdiutil; sed -E instead of GNU grep -P).
- `packaging/macos/Install.command` — double-clickable installer. Preflight
  (python3 ≥ 3.9, venv, ensurepip), installs to `~/Applications/DocuBrowse/`
  with a venv (no sudo for the app), CLI wrappers to `/usr/local/bin/`
  (sudo; falls back to `~/bin/` with a PATH hint if declined/failed), and a
  `DocuBrowse.app` bundle that osascript-launches Terminal running
  `start && open`. The .app icon is generated from `icons/icon-512.png` at
  install time via sips + iconutil. bash-3.2 compatible (macOS system bash —
  no `${var,,}`).
- `packaging/macos/Uninstall.command` — removes the install dir (incl. the
  .app) and only those CLI wrappers that reference DocuBrowse; preserves
  `~/.docubrowser/`. Also copied into the install dir so it survives dmg eject.

**Verified**: dmg builds end-to-end on this Mac; icns generation tested 3×;
auto-cd from any cwd; release auto-increment and pruning work. QA agent
review: no critical/high findings; applied its fixes (icon conversion
guarded under `set -e`, repo-root auto-cd, best-effort `stopall` before
overwrite-reinstall, first-run + Terminal-automation notes in post-install
text).

**Python 3.9 compatibility fix** (committed as "fix: Python 3.9
compatibility — make PEP 604 union annotations lazy"): first real install
test on this Mac (CLT Python 3.9.6) crashed at import —
`def read_pid() -> int | None:` raises TypeError below 3.10.
docubrowser.py, dup_detect.py, hardware_utils.py, and backup_restore.py
now start with `from __future__ import annotations`, honoring the 3.9
floor every installer advertises (also affects RHEL 9 / Debian 11).
Verified: all modules py_compile + import + `--help` on 3.9.6; QA agent
review clean (nothing in the codebase introspects annotations at runtime).

**Naming convention settled — dash before release number** (committed as
"fix: dash before release number in Windows/macOS package names"): James's
standing preference is `docubrowser-foss-0.9.0-3-macos.dmg` /
`...-0.9.0-3-windows.zip`, matching the Linux packages (`0.9.0-7.noarch.rpm`).
The 2026-07-04 switch to a dot (d501d40) is reverted; root cause of the
original dash-era prune misbehavior was a wrong sort field (`-k5` instead
of `-k4`), now fixed. Do not switch back to the dot.

**Deferred / known gaps** (from QA review):
- No code signing / notarization — users must right-click → Open the
  .command scripts on a downloaded dmg (Gatekeeper). Documented in
  README/INSTALL; signing would need an Apple Developer ID.
- ~~First double-click of DocuBrowse.app on a fresh install hits
  "ERROR: Database not found"~~ **Fixed** (committed as "fix: create empty
  database on first start instead of erroring"): `cmd_start` now calls
  `ensure_db()` when the DB is missing, prints next-step guidance, and
  starts the server — the web UI's configure-a-directory banner takes it
  from there. Falls back to a clear error if the location is unwritable.
  QA-verified live against an empty DB (stats/search/letters/banner all OK).
  Remaining Linux-only edges (noted by QA, deferred): systemd unit's
  hardcoded db_path can differ from the config's; running `start` as root
  with the User=james unit would create a root-owned DB. Also noted:
  doc_search.py `SERVER_VERSION` is stale ("0.8.1" at v0.9.0).
- Xcode CLT python3 stub on a factory-fresh Mac gives a misleading
  preflight message (three GUI dialogs, "have ?"); fails safely.
- Uninstall kills the scan PID directly rather than the process group
  (parity with uninstall.sh) — orphaned scan workers could survive.
