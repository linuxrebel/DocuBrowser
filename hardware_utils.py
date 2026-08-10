#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
hardware_utils.py — Hardware detection helpers for DocuBrowse.

Used to auto-tune worker counts based on available CPU cores and GPU.
All functions are safe to call at module import time (no heavy imports).
"""

# Lazy annotations so `dict | None` hints don't crash Python 3.9 (the floor
# advertised by every installer; macOS CLT and RHEL 9 still ship 3.9).
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

try:
    import psutil
except ImportError:
    psutil = None


# ── CPU ───────────────────────────────────────────────────────────────────────

def physical_cpu_cores() -> int:
    """
    Return physical (non-hyperthreaded) CPU core count.

    Prefers psutil for accuracy; falls back to os.cpu_count().
    On Intel hybrid CPUs (P+E cores), this counts all physical cores,
    which is appropriate for both CPU-bound and I/O-bound work.
    """
    if psutil is not None:
        cores = psutil.cpu_count(logical=False)
        if cores:
            return cores
    return os.cpu_count() or 4


def logical_cpu_cores() -> int:
    """Return logical (hyperthreaded) CPU core count."""
    if psutil is not None:
        cores = psutil.cpu_count(logical=True)
        if cores:
            return cores
    return os.cpu_count() or 4


def recommended_scan_workers(cap: int = 8, mem_gb_per_worker: float = 4.0) -> int:
    """
    Recommend worker count for CPU-bound PDF extraction.

    Considers both physical CPU cores AND available RAM.
    Large technical PDFs (security books, etc.) can peak at 3–5 GB per
    worker in pdfplumber.  Default assumes 4 GB per worker with an
    additional 4 GB reserved for the OS and non-scan processes.

    Formula: min(physical_cores, (available_ram - 4GB) / mem_gb_per_worker, cap)
    Minimum 1 regardless.
    """
    cores = physical_cpu_cores()
    if psutil is not None:
        avail_gb  = psutil.virtual_memory().available / (1024 ** 3)
        usable_gb = max(0.0, avail_gb - 4.0)   # reserve 4 GB for OS/other procs
        mem_limit = max(1, int(usable_gb / mem_gb_per_worker))
    else:
        mem_limit = cap
    return max(1, min(cores, mem_limit, cap))


# ── GPU ───────────────────────────────────────────────────────────────────────

def detect_gpu() -> dict | None:
    """
    Detect primary NVIDIA GPU via nvidia-smi or Intel GPU via xpu-smi.

    Returns dict with keys: name, total_mb, free_mb
    Returns None if no NVIDIA GPU or Intel GPU is found or nvidia-smi / xpu-smi unavailable.
    """
    try:
        if shutil.which("nvidia-smi"):
            smi_cmd = "nvidia-smi"
        elif shutil.which("xpu-smi"):
            smi_cmd = "xpu-smi"
        result = subprocess.run(
            [
                smi_cmd,
                "--query-gpu=name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                try:
                    return {
                        "name": parts[0],
                        "total_mb": int(float(parts[1])),
                        "free_mb": int(float(parts[2])),
                    }
                except ValueError:
                    pass
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def recommended_embed_workers() -> int:
    """
    Recommend worker count for concurrent Ollama embedding requests.

    With GPU (Ollama uses CUDA):  6 workers — GPU queues and batches internally
    Without GPU (CPU inference):  3 workers — avoid overwhelming CPU Ollama
    """
    gpu = detect_gpu()
    return 6 if gpu else 3


# ── Memory pressure ──────────────────────────────────────────────────────────

# Thresholds (% of total RAM that must be *available*)
MEM_WARN_PCT   = 20   # log a warning but keep going
MEM_PAUSE_PCT  = 15   # stop submitting new work; let in-flight drain
MEM_RESUME_PCT = 25   # resume after backing off


def memory_status() -> dict:
    """
    Return current RAM stats.

    Keys: total_gb, available_gb, used_pct, available_pct
    Returns dummy 100% available if psutil is not installed.
    """
    if psutil is None:
        return {"total_gb": 0, "available_gb": 99, "used_pct": 0, "available_pct": 100}
    vm = psutil.virtual_memory()
    avail_pct = vm.available * 100 / vm.total
    return {
        "total_gb":     vm.total     / (1024 ** 3),
        "available_gb": vm.available / (1024 ** 3),
        "used_pct":     vm.percent,
        "available_pct": avail_pct,
    }


# pylint: disable-next=too-many-arguments,too-many-positional-arguments
def wait_for_memory(
    pause_pct:  float = MEM_PAUSE_PCT,
    resume_pct: float = MEM_RESUME_PCT,
    warn_pct:   float = MEM_WARN_PCT,
    poll_secs:  float = 3.0,
    _is_tty:    bool  = True,   # kept for callers; used by future TTY-only branches
    logger=None,
) -> bool:
    """
    Check available RAM.  If below *pause_pct*, block until it recovers
    above *resume_pct*.  If below *warn_pct* but above *pause_pct*, log
    silently and return immediately (no terminal output).

    Returns True if a full pause occurred.
    """
    status = memory_status()
    avail  = status["available_pct"]

    if avail >= warn_pct:
        return False   # plenty of headroom

    if avail < pause_pct:
        # Critical — block.  Print to stderr so the stdout progress bar is undisturbed.
        msg = (
            f"⚠ Memory critical: {avail:.1f}% free "
            f"({status['available_gb']:.1f} GB) — pausing until ≥{resume_pct}%"
        )
        print(f"\n  {msg}", file=sys.stderr, flush=True)
        if logger:
            logger.warning(msg)
        while True:
            time.sleep(poll_secs)
            status = memory_status()
            avail  = status["available_pct"]
            if avail >= resume_pct:
                recovered = (
                    f"Memory recovered: {avail:.1f}% free — resuming"
                )
                print(f"  {recovered}", file=sys.stderr, flush=True)
                if logger:
                    logger.info(recovered)
                return True
    else:
        # Warn zone only — log silently, never interrupt the terminal.
        if logger:
            logger.warning(
                "Memory low: %.1f%% free (%.1f GB)",
                avail, status["available_gb"],
            )
        return False


# ── Summary banner ────────────────────────────────────────────────────────────

def print_hardware_summary(scan_workers: int, embed_workers: int):
    """
    Print a one-time hardware + worker summary before a rescan.
    Called from docubrowser.py cmd_rescan.
    """
    phys    = physical_cpu_cores()
    logical = logical_cpu_cores()
    gpu     = detect_gpu()

    mem = memory_status()
    if mem["total_gb"] > 0:
        ram_str = (
            f"  RAM: {mem['available_gb']:.1f} GB free"
            f" / {mem['total_gb']:.1f} GB total"
            f"  ({mem['available_pct']:.0f}% available)"
        )
    else:
        ram_str = ""

    print("Hardware")
    print(f"  CPU: {phys} physical / {logical} logical cores")
    if ram_str:
        print(f" {ram_str}")
    if gpu:
        pct_used = 100 - (gpu["free_mb"] * 100 // (gpu["total_mb"] or 1))
        print(
            f"  GPU: {gpu['name']}  "
            f"{gpu['total_mb']:,} MB total  "
            f"{gpu['free_mb']:,} MB free  "
            f"({pct_used}% used)"
        )
    else:
        print("  GPU: (none detected — Ollama will use CPU inference)")

    print("Workers")
    print(f"  Scan (PDF extraction):  {scan_workers}  [ProcessPoolExecutor, CPU-bound]")
    print(f"  Embed (Ollama calls):   {embed_workers}  [ThreadPoolExecutor, I/O-bound]")
    print()
