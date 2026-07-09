#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
platform_paths — Cross-platform path helpers for DocuBrowse.

Centralises runtime directory selection so every module uses
the same logic:

  Linux/macOS:
    Preferred:  /var/run/docubrowser/, /var/log/docubrowser/
    Fallback:   ~/.local/run/, ~/.local/var/log/

  Windows:
    %LOCALAPPDATA%\\DocuBrowse\\   (e.g. C:\\Users\\<user>\\AppData\\Local\\DocuBrowse)

The module also exposes a small ``IS_WINDOWS`` flag and a portable
``kill_process_tree()`` helper so callers don't need their own
platform branches for process management.
"""

import os
import signal
import sys
from pathlib import Path

try:
    import colorama
    colorama.init()
except ImportError:
    pass

IS_WINDOWS = sys.platform == "win32"

# On Windows the default console encoding (cp1252) cannot encode the Unicode
# symbols used throughout (─, ●, ✓, ✗, ⚠, █, …).  Reconfigure stdout/stderr
# to UTF-8 here so any script that imports platform_paths works without
# PYTHONUTF8=1.  Also propagate to subprocesses (ensure_ollama.py, etc.) via
# the environment variable, which Python reads at interpreter startup.
if IS_WINDOWS:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass  # Python < 3.7; shouldn't be reached in practice
    os.environ.setdefault("PYTHONUTF8", "1")

# ── User data directory ────────────────────────────────────────────────────

def user_data_dir() -> Path:
    """Per-user data directory (~/.docubrowser on Unix, %LOCALAPPDATA%\\DocuBrowse on Windows)."""
    if IS_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        return base / "DocuBrowse"
    return Path.home() / ".docubrowser"


# ── Runtime path picker ────────────────────────────────────────────────────

def _pick_runtime_path(preferred: Path, fallback: Path) -> Path:
    """Return *preferred* if its parent is writable; otherwise *fallback*."""
    try:
        preferred.parent.mkdir(parents=True, exist_ok=True)
        if os.access(preferred.parent, os.W_OK):
            return preferred
    except (PermissionError, OSError):
        pass
    fallback.parent.mkdir(parents=True, exist_ok=True)
    return fallback


def pid_file() -> Path:
    if IS_WINDOWS:
        d = user_data_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d / "docubrowser.pid"
    return _pick_runtime_path(
        Path("/var/run/docubrowser/docubrowser.pid"),
        Path.home() / ".local/run/docubrowser.pid",
    )


def scan_pid_file() -> Path:
    if IS_WINDOWS:
        d = user_data_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d / "docubrowse_scan.pid"
    return _pick_runtime_path(
        Path("/var/run/docubrowser/docubrowse_scan.pid"),
        Path.home() / ".local/run/docubrowse_scan.pid",
    )


def log_file() -> Path:
    if IS_WINDOWS:
        d = user_data_dir() / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d / "docubrowser.log"
    return _pick_runtime_path(
        Path("/var/log/docubrowser/docubrowser.log"),
        Path.home() / ".local/var/log/docubrowser.log",
    )


def backup_dir() -> Path:
    """Default backup directory.  On Windows or when /opt is not writable,
    use the per-user data directory."""
    if IS_WINDOWS:
        d = user_data_dir() / "backups"
        d.mkdir(parents=True, exist_ok=True)
        return d
    d = Path("/opt/docubrowser/backups")
    try:
        d.mkdir(parents=True, exist_ok=True)
        if os.access(d, os.W_OK):
            return d
    except (PermissionError, OSError):
        pass
    d = user_data_dir() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def scan_log_paths() -> list[Path]:
    """Ordered list of candidate log file paths for scan_docs.py."""
    if IS_WINDOWS:
        d = user_data_dir() / "logs"
        return [d / "docubrowser.log"]
    return [
        Path("/var/log/docubrowser.log"),
        Path.home() / ".local/share/docubrowser/docubrowser.log",
    ]


# ── Process management ─────────────────────────────────────────────────────

def kill_process_tree(pid: int, sig=None):
    """Kill a process and all its children.

    On Unix: ``os.killpg(pid, SIGTERM)`` — the PID must be a PGID
    (as stored in SCAN_PID_FILE via ``start_new_session=True``).

    On Windows: uses ``psutil.Process.kill()`` + ``children(recursive=True)``.
    Falls back to ``os.kill(pid, SIGTERM)`` if psutil is unavailable.
    """
    if sig is None:
        sig = signal.SIGTERM

    if not IS_WINDOWS:
        os.killpg(pid, sig)
        return

    # Windows path — no os.killpg; use psutil if available
    try:
        import psutil
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            child.kill()
        parent.kill()
    except ImportError:
        os.kill(pid, sig)
    except Exception:
        pass


def kill_pid(pid: int, force: bool = False):
    """Send SIGTERM (or SIGKILL on Unix / TerminateProcess on Windows).

    On Windows, os.kill(pid, SIGTERM) already calls TerminateProcess
    (equivalent to SIGKILL), so ``force`` has no extra effect.
    """
    if force and not IS_WINDOWS:
        os.kill(pid, signal.SIGKILL)
    else:
        os.kill(pid, signal.SIGTERM)


def find_procs_by_script(script_name: str) -> list[int]:
    """Return PIDs of Python processes running *script_name*.

    Cross-platform via psutil.  Falls back to /proc on Linux if
    psutil is not installed.
    """
    my_pid = os.getpid()
    pids = []

    try:
        import psutil
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.pid == my_pid:
                    continue
                cmdline = proc.info.get('cmdline') or []
                if not cmdline:
                    continue
                is_python = os.path.basename(cmdline[0]).lower().startswith('python')
                runs_script = any(a.endswith(script_name) for a in cmdline[1:])
                if is_python and runs_script:
                    pids.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return pids
    except ImportError:
        pass

    # Fallback: /proc (Linux only)
    if IS_WINDOWS:
        return []
    try:
        entries = os.listdir('/proc')
    except OSError:
        return []
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == my_pid:
            continue
        try:
            with open(f'/proc/{pid}/cmdline', 'rb') as fh:
                argv = [a.decode('utf-8', 'replace')
                        for a in fh.read().split(b'\x00') if a]
        except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
            continue
        if not argv:
            continue
        is_python = os.path.basename(argv[0]).lower().startswith('python')
        runs_script = any(a.endswith(script_name) for a in argv[1:])
        if is_python and runs_script:
            pids.append(pid)
    return pids


def kill_port(port: int, verbose: bool = False) -> bool:
    """Kill any process listening on *port*.  Returns True if killed."""
    try:
        import psutil
    except ImportError:
        psutil = None

    if psutil is not None:
        try:
            killed = False
            for conn in psutil.net_connections(kind='tcp'):
                if conn.laddr.port == port and conn.pid:
                    try:
                        os.kill(conn.pid, signal.SIGTERM)
                        if verbose:
                            print(f"Sent SIGTERM to process {conn.pid} on port {port}.")
                        killed = True
                    except (ProcessLookupError, PermissionError):
                        pass
            return killed
        except (psutil.AccessDenied, PermissionError):
            # System-wide net_connections() needs root on macOS
            # (proc_pidinfo is denied for other users' processes);
            # fall back to lsof below.
            pass

    # Fallback: lsof / fuser (Unix only)
    if IS_WINDOWS:
        return False
    import subprocess
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"],
            capture_output=True, text=True,
        )
        pids = [int(p) for p in result.stdout.split() if p.strip().isdigit()]
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
                if verbose:
                    print(f"Sent SIGTERM to process {pid} on port {port}.")
            except ProcessLookupError:
                pass
        return bool(pids)
    except FileNotFoundError:
        try:
            r = subprocess.run(["fuser", "-k", f"{port}/tcp"],
                               capture_output=True)
            return r.returncode == 0
        except Exception:
            return False
