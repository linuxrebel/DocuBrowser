#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
purge_dotfiles.py — one-off migration: remove already-indexed dotfiles from a
DocuBrowse database.

The scanner skips dotfiles and the contents of hidden directories (.git/,
.venv/, …) going forward (D-6), but rows indexed by older versions linger and a
rescan won't prune them. This tool finds and removes them, using the *same*
roots-aware hidden-path check as the scanner (``scan_docs._is_hidden_relpath``),
so a deliberately-scanned dot-directory root is exempt — its non-hidden files
are kept.

Reuses the cascade-safe ``delete_documents()``, so FTS rowids, tags, and
embeddings are cleaned up correctly. Dry-run by default.

Usage:
  python3 purge_dotfiles.py                        # dry-run, default DB
  python3 purge_dotfiles.py --apply                # actually delete
  python3 purge_dotfiles.py --db /path/du.db --roots /docs /extra --apply
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# pylint: disable=wrong-import-position
from scan_docs import _is_hidden_relpath, _load_scan_dirs   # noqa: E402
from docubrowse_db import get_db, delete_documents           # noqa: E402
# pylint: enable=wrong-import-position


def _default_db() -> Path:
    env = os.environ.get("DOCUBROWSE_DB") or os.environ.get("DOCUBROWSE_DB_PATH")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".docubrowser" / "du-docs.db"


def _safe_resolve(p: Path) -> Path:
    try:
        return p.resolve()
    except OSError:
        return p


def _config_doc_dir(db_path: Path):
    """Read doc_dir from the docubrowse.config sitting next to the database."""
    cfg = db_path.parent / "docubrowse.config"
    if cfg.exists():
        for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("doc_dir") and "=" in line:
                return Path(line.split("=", 1)[1].strip())
    return None


def resolve_roots(db_path: Path, override):
    """Scan roots to evaluate against: --roots override, else config + scan_dirs."""
    if override:
        return [_safe_resolve(Path(r).expanduser()) for r in override]
    roots = []
    doc_dir = _config_doc_dir(db_path)
    if doc_dir:
        roots.append(doc_dir)
    roots.extend(Path(p) for p in _load_scan_dirs(db_path))
    return [_safe_resolve(r) for r in roots]


def is_dotfile(path: str, roots) -> bool:
    """True if *path* is a hidden file/dir-content, evaluated relative to its
    longest matching scan root (so a dot-directory root is exempt). Paths under
    no known root fall back to a plain any-dot-component check."""
    p = _safe_resolve(Path(path))
    best = None
    for r in roots:
        try:
            p.relative_to(r)
        except ValueError:
            continue
        if best is None or len(r.parts) > len(best.parts):
            best = r
    if best is not None:
        return _is_hidden_relpath(p, best)
    return any(part.startswith(".") for part in p.parts)


def main():
    """Parse args, report the dotfiles found, and (with --apply) delete them."""
    ap = argparse.ArgumentParser(
        description="Remove already-indexed dotfiles from the DocuBrowse database.")
    ap.add_argument("--db", type=Path, default=None,
                    help="Database path (default: DOCUBROWSE_DB or "
                         "~/.docubrowser/du-docs.db)")
    ap.add_argument("--roots", nargs="+", metavar="DIR",
                    help="Override scan roots (default: config doc_dir + scan_dirs.txt)")
    ap.add_argument("--apply", action="store_true",
                    help="Actually delete (default: dry-run)")
    args = ap.parse_args()

    db_path = _safe_resolve((args.db or _default_db()).expanduser())
    if not db_path.exists():
        sys.exit(f"ERROR: database not found: {db_path}")
    roots = resolve_roots(db_path, args.roots)

    conn = get_db(str(db_path))
    rows = conn.execute("SELECT id, path FROM documents").fetchall()
    hits = [(row[0], row[1]) for row in rows if is_dotfile(row[1], roots)]

    print(f"Database: {db_path}")
    print(f"Roots:    {', '.join(str(r) for r in roots) or '(none — any-dot-component heuristic)'}")
    print(f"Documents: {len(rows):,}   dotfiles found: {len(hits):,}")
    for _id, path in hits[:20]:
        print(f"  {path}")
    if len(hits) > 20:
        print(f"  … and {len(hits) - 20:,} more")

    if not hits:
        print("Nothing to remove.")
        conn.close()
        return
    if not args.apply:
        print("\nDry run — no changes. Re-run with --apply to delete.")
        conn.close()
        return

    removed = delete_documents(conn, [i for i, _ in hits])
    conn.close()
    print(f"\nRemoved {removed:,} dotfile document(s).")


if __name__ == "__main__":
    main()
