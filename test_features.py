#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
DocuBrowse end-to-end feature test — exercises a *running* server over HTTP.

Unlike the unit-style checks, this drives the real API surface (search in all
three modes, the DjVu/ODF-template formats, the security guards, CSRF, and
live synopsis generation via Ollama) against whatever database the server was
started with. It asserts on shape and behavior, not on a specific corpus, so
it works against any populated DB.

Run:
    # start a server against the DB you want to test (see status_docs/TESTING.md)
    DOCUBROWSE_DB=~/.docubrowser/du-docs.db ./docubrowser.py start
    python3 test_features.py                 # or --base http://localhost:8643
    ./docubrowser.py stop

Exit code = number of failed checks (0 = all passed).  --skip-synopsis avoids
the slow dolphin3 generation call when Ollama isn't available.

The API-shape notes this relies on (documents/total/count keys, synopsis path
in the query string, etc.) are documented in status_docs/TESTING.md.
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# This is an HTTP test driver: the urlopen() calls are short-lived localhost
# reads (a `with` per call adds noise), and run() is a flat sequence of
# independent checks by design.
# pylint: disable=consider-using-with,too-many-locals,too-many-statements

TALLY = {"pass": 0, "fail": 0, "skip": 0}


def report(name, ok, extra=""):
    """Record and print one PASS/FAIL check."""
    TALLY["pass" if ok else "fail"] += 1
    print(f'{"PASS" if ok else "FAIL"}  {name:40} {extra}')


def skip(name, why):
    """Record and print one skipped check."""
    TALLY["skip"] += 1
    print(f'SKIP  {name:40} {why}')


def get_json(base, path, headers=None, method="GET", data=None):
    """Return (status_code, parsed_json). Raises on transport errors."""
    req = urllib.request.Request(base + path, headers=headers or {},
                                 method=method, data=data)
    resp = urllib.request.urlopen(req, timeout=150)   # nosec B310 - localhost
    return resp.getcode(), json.load(resp)


def status_code(base, path, headers=None, method="GET", data=None):
    """Return the HTTP status code for a request (HTTPError code included)."""
    try:
        return get_json(base, path, headers, method, data)[0]
    except urllib.error.HTTPError as exc:
        return exc.code


def search_names(base, query, mode="keyword"):
    """Return (list-of-names, full-response) for a search."""
    _, body = get_json(base, f"/api/search?q={urllib.parse.quote(query)}&mode={mode}")
    return [d.get("name", "") for d in body["documents"]], body


def csrf_token(base):
    """Extract the per-process CSRF token injected into the served HTML."""
    html = urllib.request.urlopen(base + "/", timeout=30).read().decode("utf-8", "replace")
    match = (re.search(r'csrf[-_ ]?token["\']?\s*[:=]\s*["\']([A-Za-z0-9_\-]+)', html, re.I)
             or re.search(r'name=["\']csrf-token["\']\s+content=["\']([A-Za-z0-9_\-]+)',
                          html, re.I))
    return match.group(1) if match else None


def check_deep_links(base, embedded):
    """Best-effort Deep Links checks against whatever docs this DB holds."""
    prose_ext = ("pdf", "txt", "docx", "rtf", "odt")
    nonprose_ext = ("xlsx", "ods", "csv", "tsv", "pptx", "odp")
    _, corpus = get_json(base, "/api/search?q=&mode=keyword")
    docs = corpus.get("documents", [])

    def first_by_ext(exts):
        return next(
            (d for d in docs
             if d.get("path", "").rsplit(".", 1)[-1].lower() in exts),
            None,
        )

    prose = first_by_ext(prose_ext)
    if not prose:
        for name in ("deep-links keyword envelope",
                     "deep-links passage has location + span",
                     "deep-links semantic envelope"):
            skip(name, "no prose doc in this DB")
    else:
        # Query a word from the doc's own name so a match is likely; the check
        # still passes on an empty result — it asserts the envelope, not a hit.
        word = next(iter(re.findall(r"[A-Za-z]{4,}", prose.get("name", ""))), "the")
        dl = "/api/deep-links?path=" + urllib.parse.quote(prose["path"])
        _, kw = get_json(base, f"{dl}&q={urllib.parse.quote(word)}&mode=keyword")
        report("deep-links keyword envelope",
               kw.get("ok") is True and ("passages" in kw or kw.get("unsupported")),
               f"{prose['name']!r} q={word!r} passages={len(kw.get('passages', []))}")
        if kw.get("passages"):
            p0 = kw["passages"][0]
            report("deep-links passage has location + span",
                   bool(p0.get("location")) and "match_start" in p0,
                   f"{p0.get('location')!r}")
        else:
            skip("deep-links passage has location + span", "no keyword hit in sample doc")

        if embedded > 0:
            _, sem = get_json(base, f"{dl}&q={urllib.parse.quote(word)}&mode=semantic")
            report("deep-links semantic envelope",
                   sem.get("ok") is True and ("passages" in sem or sem.get("unsupported")),
                   f"passages={len(sem.get('passages', []))}")
        else:
            skip("deep-links semantic envelope", "no embeddings in this DB")

    nonprose = first_by_ext(nonprose_ext)
    if nonprose:
        dl = "/api/deep-links?path=" + urllib.parse.quote(nonprose["path"])
        _, un = get_json(base, f"{dl}&q=data&mode=keyword")
        report("deep-links non-prose -> unsupported",
               un.get("ok") is True and un.get("unsupported") is True,
               nonprose["name"])
    else:
        skip("deep-links non-prose -> unsupported", "no spreadsheet/slide doc in this DB")


def run(base, skip_synopsis):
    """Execute every feature check against the server at *base*."""
    # ── Core endpoints ───────────────────────────────────────────────────────
    _, st = get_json(base, "/api/status")
    report("status ok", st.get("ok") is True, st.get("version"))
    report("semantic_ready", st.get("semantic_ready") is True)
    _, stats = get_json(base, "/api/stats")
    docs, embedded = stats.get("total_docs", 0), stats.get("embedded", 0)
    report("stats has documents", docs > 0, f"{docs} docs / {embedded} embedded")
    _, cfg = get_json(base, "/api/config")
    report("config responds", "port" in cfg,
           f"port={cfg.get('port')} docPath={cfg.get('docPath')!r}")
    report("tags endpoint", len(get_json(base, "/api/tags")[1].get("tags", [])) > 0)
    report("letters endpoint", len(get_json(base, "/api/letters")[1].get("letters", [])) > 0)

    # ── Search: all three modes return a well-formed page ────────────────────
    # Empty query returns the whole corpus, so it works on any DB.
    for mode in ("keyword", "semantic", "both"):
        _, body = get_json(base, f"/api/search?q=&mode={mode}")
        ok = "documents" in body and body.get("total", 0) > 0 and len(body["documents"]) > 0
        report(f"search mode={mode}", ok,
               f"total={body.get('total')} page={len(body.get('documents', []))}")

    if embedded > 0:
        _, sem = get_json(base, "/api/search?q=&mode=semantic")
        report("semantic returns ranked docs", len(sem.get("documents", [])) > 0)
    else:
        skip("semantic returns ranked docs", "no embeddings in this DB")

    # ── New formats (best-effort: only if the sample words are indexed) ──────
    dj, _ = search_names(base, "proclamations")
    if dj:
        report("DjVu body searchable", any("djvu" in n.lower() for n in dj),
               [n for n in dj if "djvu" in n.lower()][:1])
    else:
        skip("DjVu body searchable", "no DjVu sample content in this DB")

    ot, _ = search_names(base, "component")
    if any("ott" in n.lower() for n in ot):
        report("ODF template (.ott) searchable", True, [n for n in ot if "ott" in n.lower()][:1])
    else:
        skip("ODF template (.ott) searchable", "no .ott sample content in this DB")

    check_deep_links(base, embedded)

    # ── Security guards (DB-independent) ─────────────────────────────────────
    report("foreign Host -> 403", status_code(base, "/api/stats", {"Host": "evil.example"}) == 403)
    report("POST /api/delete no CSRF -> 403",
           status_code(base, "/api/delete", method="POST", data=b"{}") == 403)
    report("GET /api/browse no CSRF -> 403", status_code(base, "/api/browse?path=/") == 403)

    token = csrf_token(base)
    report("CSRF token present in HTML", bool(token), (token or "")[:10] + "…")

    # ── Synopsis: GET reads cache, POST generates (path in the QUERY string) ─
    _, first = get_json(base, "/api/search?q=&mode=keyword")
    if not first.get("documents"):
        skip("synopsis generate", "no documents to summarize")
        return
    path = first["documents"][0]["path"]
    _, sg = get_json(base, "/api/synopsis?path=" + urllib.parse.quote(path))
    report("synopsis GET responds", "ok" in sg,
           f"cached={bool(sg.get('synopsis'))} needs_gen={sg.get('needs_generation')}")

    if skip_synopsis:
        skip("synopsis POST generates", "--skip-synopsis")
        return
    if not token:
        skip("synopsis POST generates", "no CSRF token")
        return
    headers = {"X-CSRF-Token": token, "Origin": base}
    url = "/api/synopsis?path=" + urllib.parse.quote(path)
    start = time.time()
    try:
        _, pj = get_json(base, url, headers=headers, method="POST", data=b"")
        text = pj.get("synopsis") or ""
        report("synopsis POST generates (Ollama)", pj.get("ok") and len(text) > 50,
               f"{len(text)}ch in {time.time() - start:.0f}s")
        if text:
            print("   >", text[:180].replace("\n", " "))
    except urllib.error.HTTPError as exc:
        report("synopsis POST generates (Ollama)", False, f"HTTP {exc.code}")


def main():
    """Parse args, confirm a server is up, run the suite, exit with #failures."""
    ap = argparse.ArgumentParser(description="DocuBrowse end-to-end feature test")
    ap.add_argument("--base", default="http://localhost:8643", help="server base URL")
    ap.add_argument("--skip-synopsis", action="store_true",
                    help="skip the slow dolphin3 generation call")
    args = ap.parse_args()

    try:
        urllib.request.urlopen(args.base + "/api/status", timeout=10)
    except OSError as exc:
        sys.exit(f"ERROR: no server at {args.base} ({exc}). Start one first — see "
                 "status_docs/TESTING.md.")

    run(args.base, args.skip_synopsis)
    print(f'\n{TALLY["pass"]} passed, {TALLY["fail"]} failed, {TALLY["skip"]} skipped')
    sys.exit(TALLY["fail"])


if __name__ == "__main__":
    main()
