#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
dup_detect.py — Duplicate document detection for DocuBrowse.

Two detection modes:
  find_exact_dups()  — byte-identical files via SHA256
                       Pre-filters by file size to avoid hashing unique-size files.
  find_near_dups()   — semantically similar files via embedding cosine similarity.
                       Requires numpy; uses union-find clustering.

Each function returns a list of groups, where each group is a list of dicts:
    [{'id', 'name', 'path', 'size_bytes', 'title', 'author'}, ...]
"""

# Lazy annotations so `str | None` hints don't crash Python 3.9 (the floor
# advertised by every installer; macOS CLT and RHEL 9 still ship 3.9).
from __future__ import annotations

import hashlib
import math
import struct
from collections import defaultdict
from pathlib import Path

from docubrowse_db import get_db


# ── Exact duplicates ──────────────────────────────────────────────────────────

def _sha256_file(path: str) -> str | None:
    """Compute SHA256 of a file. Returns hex digest or None on read error."""
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def find_exact_dups(db_path: str, progress: bool = True) -> list:
    """
    Find groups of byte-identical files using a two-pass approach:
      Pass 1: group indexed documents by size_bytes (fast, no I/O).
      Pass 2: hash only the files that share a size with another file.

    Returns list of groups (each group = list of doc dicts).
    Files that no longer exist on disk are silently skipped.
    """
    conn = get_db(db_path)
    rows = conn.execute(
        "SELECT id, name, path, size_bytes, title, author "
        "FROM documents ORDER BY size_bytes, path"
    ).fetchall()
    conn.close()

    # Pass 1 — bucket by size; skip NULL or unique sizes
    size_buckets: dict = defaultdict(list)
    for row in rows:
        sz = row['size_bytes']
        if sz is not None:
            size_buckets[sz].append(dict(row))

    candidates = [docs for docs in size_buckets.values() if len(docs) > 1]
    candidate_count = sum(len(g) for g in candidates)

    if progress and candidate_count:
        print(f"  {candidate_count:,} files share a size with at least one other "
              f"— hashing to confirm duplicates...")

    # Pass 2 — hash within each same-size bucket
    hash_groups: dict = defaultdict(list)
    hashed = 0
    for bucket in candidates:
        for doc in bucket:
            h = _sha256_file(doc['path'])
            if h:
                hash_groups[h].append(doc)
            hashed += 1
            if progress and hashed % 50 == 0:
                print(f"\r  Hashed {hashed}/{candidate_count}...", end='', flush=True)

    if progress and candidate_count:
        print(f"\r  Hashed {hashed}/{candidate_count}.   ")

    return [group for group in hash_groups.values() if len(group) > 1]


# ── Near-duplicates (embedding cosine similarity) ─────────────────────────────

def _blob_to_vec(blob: bytes) -> list | None:
    """Unpack a float32 BLOB into a Python list."""
    if not blob or len(blob) < 4:
        return None
    n = len(blob) // 4
    return list(struct.unpack(f'{n}f', blob))


class _UnionFind:
    """Lightweight union-find for clustering near-duplicate pairs."""
    def __init__(self, ids):
        self.parent = {i: i for i in ids}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # path compression
            x = self.parent[x]
        return x

    def union(self, x, y):
        self.parent[self.find(x)] = self.find(y)

    def groups(self, data_by_id: dict) -> list:
        """Return list of groups (each group = list of values from data_by_id)."""
        buckets: dict = defaultdict(list)
        for i in data_by_id:
            buckets[self.find(i)].append(data_by_id[i])
        return [g for g in buckets.values() if len(g) > 1]


def find_near_dups(db_path: str, threshold: float = 0.97,
                   progress: bool = True) -> list:
    """
    Find near-duplicate documents using embedding cosine similarity.

    Uses numpy matrix multiplication for fast batched cosine computation.
    Falls back to a slower scalar loop if numpy is not available.

    threshold: minimum cosine similarity to consider a pair near-duplicate.
               Default 0.97 (~3% content difference).

    Returns list of groups (each group = list of doc dicts with 'similarity' key
    set to the max pairwise similarity observed within the group).
    """
    conn = get_db(db_path)
    rows = conn.execute(
        "SELECT d.id, d.name, d.path, d.size_bytes, d.title, d.author, de.embedding "
        "FROM documents d JOIN doc_embeddings de ON d.id = de.doc_id "
        "WHERE de.embedding IS NOT NULL"
    ).fetchall()
    conn.close()

    docs = []
    vecs = []
    for row in rows:
        vec = _blob_to_vec(row['embedding'])
        if vec:
            docs.append({
                'id':         row['id'],
                'name':       row['name'],
                'path':       row['path'],
                'size_bytes': row['size_bytes'],
                'title':      row['title'],
                'author':     row['author'],
            })
            vecs.append(vec)

    n = len(docs)
    if n < 2:
        return []

    if progress:
        print(f"  Comparing {n:,} embedded documents for near-duplicates...")

    uf = _UnionFind([d['id'] for d in docs])
    max_sim: dict = {}  # doc id → max similarity seen

    try:
        import numpy as np  # type: ignore

        mat = np.array(vecs, dtype=np.float32)                    # (n, dim)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)        # (n, 1)
        norms[norms == 0] = 1.0
        mat /= norms                                               # unit vectors

        # Process in row batches to limit peak memory (~500 rows × n cols)
        batch = 500
        for start in range(0, n, batch):
            end = min(start + batch, n)
            sim_block = mat[start:end] @ mat.T                    # (batch, n)
            rows_idx, cols_idx = (sim_block >= threshold).nonzero()
            for r_local, c_global in zip(rows_idx.tolist(), cols_idx.tolist()):
                r_global = start + r_local
                if r_global >= c_global:
                    continue  # skip self-comparison and lower triangle
                i_id = docs[r_global]['id']
                j_id = docs[c_global]['id']
                sim = float(sim_block[r_local, c_global])
                uf.union(i_id, j_id)
                max_sim[i_id] = max(max_sim.get(i_id, 0.0), sim)
                max_sim[j_id] = max(max_sim.get(j_id, 0.0), sim)
            if progress:
                print(f"\r  Processed {min(end, n):,}/{n:,}...", end='', flush=True)

        if progress:
            print(f"\r  Processed {n:,}/{n:,}.   ")

    except ImportError:
        # Scalar fallback — O(n²), slow for large collections
        if progress:
            print("  (numpy not available — using scalar comparison; may be slow)")

        def _dot(a, b):
            return sum(x * y for x, y in zip(a, b))

        def _norm(a):
            return math.sqrt(sum(x * x for x in a)) or 1.0

        scalar_norms = [_norm(v) for v in vecs]

        for i in range(n):
            if progress and i % 100 == 0:
                print(f"\r  Comparing {i:,}/{n:,}...", end='', flush=True)
            for j in range(i + 1, n):
                sim = _dot(vecs[i], vecs[j]) / (scalar_norms[i] * scalar_norms[j])
                if sim >= threshold:
                    i_id = docs[i]['id']
                    j_id = docs[j]['id']
                    uf.union(i_id, j_id)
                    max_sim[i_id] = max(max_sim.get(i_id, 0.0), sim)
                    max_sim[j_id] = max(max_sim.get(j_id, 0.0), sim)

        if progress:
            print(f"\r  Compared {n:,}/{n:,}.   ")

    data_by_id = {d['id']: d for d in docs}
    groups = uf.groups(data_by_id)

    # Annotate each group member with the max similarity observed in the group
    for group in groups:
        group_max = max(max_sim.get(d['id'], threshold) for d in group)
        for d in group:
            d['similarity'] = group_max

    return groups


# ── Formatting helpers (shared by duplist / dupclean) ─────────────────────────

def fmt_size(n) -> str:
    """Human-readable file size."""
    if n is None:
        return '?'
    n = int(n)
    if n >= 1_073_741_824:
        return f"{n / 1_073_741_824:.1f}GB"
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f}MB"
    if n >= 1024:
        return f"{n / 1024:.0f}KB"
    return f"{n}B"


def group_label(group: list, kind: str = 'exact') -> str:
    """One-line label for a duplicate group."""
    first = group[0]
    title = first.get('title') or first.get('name') or 'Unknown'
    if len(title) > 55:
        title = title[:52] + '…'
    size = fmt_size(first.get('size_bytes'))
    n = len(group)
    if kind == 'exact':
        return f'"{title}"  [{size} × {n} copies]'
    else:
        sim = first.get('similarity', 0.0)
        return f'"{title}"  [similarity {sim * 100:.1f}%  × {n} docs]'
