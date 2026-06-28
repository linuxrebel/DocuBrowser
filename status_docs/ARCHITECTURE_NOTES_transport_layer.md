# Transport/Access-Layer Split — Reading Notes

Context: while debugging the browser-opener extension (2026-06-14), we hit a
hard wall — browsers fundamentally don't let a remote page open a file in the
client's OS default app. That pushed us toward a native companion app
(`app-dev` branch). It also raised the bigger question James wants to think
through: could DocuBrowse fork into a FOSS local-only tool and a paid
remote/hosted tier, without maintaining two divergent codebases?

This doc lays out the general pattern ("separate the engine from the access
layer") and how it could map onto DocuBrowse specifically. It's notes for
thinking, not a plan — nothing here commits to a direction.

---

## The general pattern

Most successful open-core / FOSS+paid split products share one structural
idea: there's a **core engine** that does the actual work, and one or more
**access layers** that decide *who* can reach it and *how*. The engine doesn't
know or care which access layer is in front of it.

```
                    ┌─────────────────────────┐
                    │   Core Engine (FOSS)     │
                    │  - scan/embed/index      │
                    │  - SQLite + FTS5         │
                    │  - search/synopsis logic │
                    │  - file-open via xdg-open│
                    └────────────┬─────────────┘
                                  │ stable internal API
              ┌───────────────────┼───────────────────┐
              │                   │                     │
     ┌────────▼────────┐ ┌────────▼─────────┐ ┌─────────▼─────────┐
     │ Local HTTP API   │ │ Native companion │ │ Remote/hosted relay│
     │ (doc_search.py,  │ │ app (Linux/Win/  │ │ (paid tier — sync, │
     │ today's behavior)│ │ Mac, talks to    │ │ auth, multi-device,│
     │ FOSS             │ │ local API) FOSS  │ │ team sharing) PAID │
     └──────────────────┘ └──────────────────┘ └────────────────────┘
```

**Why this works for FOSS+paid:**
- The thing people most want for free (search *my* docs, on *my* machine,
  open them locally) is entirely the core engine + local access layer. No
  reason to gate it — it's also your best marketing.
- The thing worth paying for (access from anywhere, multiple devices, team
  sharing, no port-forwarding/VPN setup) lives entirely in the *access layer*
  — it's additive infrastructure, not a rewrite of search/scan/embed logic.
- A contributor fixing a search bug touches the core engine once; both tiers
  benefit. You're not maintaining "DocuBrowse Community" and "DocuBrowse Pro"
  as separate trees.

**Where it gets hard:**
- The core engine's internal API has to be genuinely stable and
  access-layer-agnostic from day one, or the "thin layer" stops being thin.
  Watch for access-layer concerns (auth tokens, multi-tenancy, rate limits)
  leaking into core engine code — that's the seam that turns into a fork.
- Licensing: if the paid tier is "the same code plus a hosted relay," you need
  a license that allows that (e.g. AGPL discourages competitors from
  re-hosting your code as a service without sharing changes — relevant if the
  paid differentiator is *convenience of hosting*, not unique code). MIT/Apache
  put no real barrier up, which is fine if the moat is the hosted
  infrastructure/support itself rather than the code.
- "Open core" reputational risk: communities can sour if FOSS features get
  quietly moved behind the paid wall over time. Deciding *up front* which
  category each future feature falls into (and writing it down) avoids
  arguments later.

---

## Mapping onto DocuBrowse today

Current `main` (v0.8.3) is already accidentally close to this shape:

- **Core engine** ≈ `scan_docs.py`, `embed_docs.py`, `docubrowse_db.py`,
  extractors, `dup_detect.py` — all local, all FOSS-shaped already.
- **Local access layer** ≈ `doc_search.py` (HTTP API + served `index.html`),
  bound to `127.0.0.1` by default, opt-in LAN via `--allow-remote`.
- **Native companion app** (the `app-dev` work) would be a *second* access
  layer, talking to the same `doc_search.py` API — this is the piece that
  makes "open file" work correctly regardless of where the client sits.

The thing that *doesn't* exist yet, and is the actual fork-in-the-road, is a
**remote/hosted access layer** — something that lets a client reach a
DocuBrowse index that isn't on the same LAN. That's the natural home for a
paid tier:

- Tunneling/relay so users don't configure port-forwarding or VPNs
  (this alone is a real, defensible value-add — most "remote access to my
  home server" products charge for exactly this).
- Multi-user auth / sharing a single index with a team.
- Optional cloud-hosted index (for people who don't want to run a server at
  all) — bigger lift, different trust model (their docs leave their machine).

None of those require touching `scan_docs.py`, `embed_docs.py`, the DB schema,
or the search ranking — they're all "what sits in front of `doc_search.py`."

---

## Concrete options to weigh later (not decisions)

1. **FOSS = local engine + local API + native app. Paid = relay/tunnel
   service** that exposes a user's local `doc_search.py` to their other
   devices, with auth. Closest to "Tailscale for your document index." Engine
   code never forks.

2. **FOSS = everything as today, including `--allow-remote`. Paid = managed
   convenience** — hosted relay, mobile apps, support, maybe team features.
   The free tier is fully functional but "do it yourself" for remote access;
   paid removes friction. Lowest risk of community backlash since nothing is
   removed.

3. **Two-tier index/sync**: paid tier adds an optional sync of the *index*
   (not the documents) to a hosted service for cross-device search, with
   "open" still resolving to a path on whichever device has the file. More
   complex — touches the DB layer (needs a sync-aware schema), so less clean
   as a pure access-layer split. Probably a v2 idea if at all.

4. **Don't fork — dual-license a thin remote-access module**: keep 100% of
   today's code FOSS (MIT/Apache as now), but the *relay/tunnel* component
   ships under a different license or as a closed-source add-on binary that
   talks to the FOSS `doc_search.py` over its existing HTTP API. Cleanest
   separation, smallest new-code surface, but means writing one piece of
   proprietary code — a real decision point, not just an architecture one.

---

## Questions worth answering before picking a direction

- Who is the paying customer — an individual wanting access to *their own*
  docs from elsewhere, or a small team wanting a shared index?
- Does the paid tier ever need to see document *contents*, or only metadata
  (search results, snippets) and a relay for the "open" action? This hugely
  affects trust/privacy framing and infra cost.
- Is "self-host the relay too" an acceptable FOSS escape hatch (a power user
  runs their own tunnel instead of paying)? If yes, the paid tier is purely
  convenience — easier to justify, harder to monetize aggressively.
- How much of the `app-dev` native-app work is shared between tiers vs.
  paid-only (e.g., does the free native app only talk to LAN/localhost
  `doc_search.py`, while a paid app variant also knows how to reach the relay)?

---

## Suggested next step (when ready)

Before writing the companion app, sketch the `doc_search.py` HTTP API as the
explicit "stable internal API" boundary (it mostly already is one). Treat any
new endpoint added for the native app as something that *either* tier could
call — that discipline is what keeps option 1/2 above open for as long as
possible without committing now.
