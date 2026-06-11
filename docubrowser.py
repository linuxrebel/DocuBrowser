#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
docubrowser.py — DocuBrowse CLI launcher

The main user interaction point for DocuBrowse.

Usage:
  docubrowser.py <command> [options]

Commands:
  start       Start the DocuBrowse server
  stop        Stop the DocuBrowse server
  restart     Restart the DocuBrowse server
  status      Show server status and index stats
  rescan      Scan documents and update the index
  scan-file   Extract and index a single file, then embed it
  embed       Generate/refresh embeddings for unembedded documents
  open        Open the DocuBrowse UI in your browser
  purge       Scan index for PII and remove matching documents
  duplist     List duplicate documents (exact SHA256 + optional near-dup)
  dupclean    Interactively review and remove duplicate documents
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

# ─── Defaults ────────────────────────────────────────────────────────────────

DEFAULT_PORT    = 8643
DEFAULT_DB      = Path(__file__).parent / "du-docs.db"
DEFAULT_DOC_DIR = "/mnt/data/Documents"
CONFIG_PATHS    = [
    Path("/etc/docubrowse.config"),
    Path(__file__).parent / "docubrowse.config",
]


def _pick_runtime_path(preferred: Path, fallback: Path) -> Path:
    """
    Return `preferred` if its parent directory exists (or can be created)
    and is writable; otherwise return `fallback` (creating its parent dir).

    Used so PID/log files land in standard system locations
    (/var/run, /var/log) when the process has permission to create
    them there, while still working for unprivileged/local installs by
    falling back to ~/.local/share/docubrowser/.
    """
    try:
        preferred.parent.mkdir(parents=True, exist_ok=True)
        if os.access(preferred.parent, os.W_OK):
            return preferred
    except (PermissionError, OSError):
        pass
    fallback.parent.mkdir(parents=True, exist_ok=True)
    return fallback


_LOCAL_STATE_DIR = Path.home() / ".local/share/docubrowser"

PID_FILE        = _pick_runtime_path(
    Path("/var/run/docubrowser/docubrowser.pid"),
    _LOCAL_STATE_DIR / "docubrowser.pid",
)
SCAN_PID_FILE   = _pick_runtime_path(
    Path("/var/run/docubrowser/docubrowse_scan.pid"),
    _LOCAL_STATE_DIR / "docubrowse_scan.pid",
)   # PGID of running scan
LOG_FILE        = _pick_runtime_path(
    Path("/var/log/docubrowser/docubrowser.log"),
    _LOCAL_STATE_DIR / "docubrowser.log",
)

# ─── Config loader ────────────────────────────────────────────────────────────

def load_config() -> dict:
    """
    Load configuration from the first config file found.
    Format: simple KEY=VALUE lines; lines starting with # are comments.
    Falls back to built-in defaults if no config file exists.
    """
    config = {
        "doc_dir": DEFAULT_DOC_DIR,
        "db_path": str(DEFAULT_DB),
        "port":    DEFAULT_PORT,
        "work_dir": str(Path(__file__).parent),
    }

    for cfg_path in CONFIG_PATHS:
        if cfg_path.exists():
            config["_config_source"] = str(cfg_path)
            with open(cfg_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, val = line.partition("=")
                        config[key.strip().lower()] = val.strip()
            # Ensure port is int after parsing
            config["port"] = int(config.get("port", DEFAULT_PORT))
            break
    else:
        config["_config_source"] = "(built-in defaults)"

    return config


# ─── PID helpers ─────────────────────────────────────────────────────────────

def read_pid() -> int | None:
    """Return PID from PID file, or None if file missing/stale."""
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        # Check the process actually exists
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        PID_FILE.unlink(missing_ok=True)
        return None


def write_pid(pid: int):
    PID_FILE.write_text(str(pid))


def clear_pid():
    PID_FILE.unlink(missing_ok=True)


# ─── Ollama prerequisite gate ────────────────────────────────────────────────

def ensure_ollama() -> bool:
    """
    Run ensure_ollama.py to verify Ollama is installed, running, and has the
    nomic-embed-text:latest model — installing/starting/pulling as needed.
    Returns True if all prerequisites are met, False otherwise.
    """
    script = Path(__file__).parent / "ensure_ollama.py"
    if not script.exists():
        print(f"ERROR: ensure_ollama.py not found in {Path(__file__).parent}")
        print("Ollama prerequisites cannot be verified.")
        return False
    ret = subprocess.run([sys.executable, str(script)])
    if ret.returncode != 0:
        print("Ollama prerequisites not met — aborting.")
        return False
    return True


# ─── Server health check ──────────────────────────────────────────────────────

def server_stats(port: int, timeout: float = 2.0) -> dict | None:
    """Fetch /api/stats from the running server. Returns dict or None."""
    try:
        url = f"http://localhost:{port}/api/stats"
        with urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def is_server_running(port: int) -> bool:
    return server_stats(port) is not None


# ─── systemd integration ──────────────────────────────────────────────────────

SYSTEMD_UNIT = "docubrowser.service"


def _systemd_unit_loaded() -> bool:
    """True if docubrowser.service is installed/known to systemd."""
    try:
        ret = subprocess.run(
            ["systemctl", "show", "-p", "LoadState", "--value", SYSTEMD_UNIT],
            capture_output=True, text=True, timeout=5,
        )
        return ret.returncode == 0 and ret.stdout.strip() == "loaded"
    except (OSError, subprocess.TimeoutExpired):
        return False


def _systemd_is_active() -> bool:
    try:
        ret = subprocess.run(
            ["systemctl", "is-active", SYSTEMD_UNIT],
            capture_output=True, text=True, timeout=5,
        )
        return ret.stdout.strip() == "active"
    except (OSError, subprocess.TimeoutExpired):
        return False


def _systemd_is_enabled() -> str:
    try:
        ret = subprocess.run(
            ["systemctl", "is-enabled", SYSTEMD_UNIT],
            capture_output=True, text=True, timeout=5,
        )
        return ret.stdout.strip() or "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def _systemctl(action: str) -> bool:
    """Run `systemctl <action> docubrowser.service`. Returns True on success."""
    ret = subprocess.run(["systemctl", action, SYSTEMD_UNIT])
    if ret.returncode != 0:
        print(f"systemctl {action} {SYSTEMD_UNIT} failed (exit {ret.returncode}).")
        print("If this needs elevated privileges, run:")
        print(f"  sudo systemctl {action} {SYSTEMD_UNIT}")
        return False
    return True


# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_start(config: dict, args):
    port    = args.port or config["port"]
    db_path = args.db   or config["db_path"]

    # Check if already running
    pid = read_pid()
    if pid:
        if is_server_running(port):
            print(f"DocuBrowse is already running (PID {pid}) on port {port}.")
            print(f"  UI: http://localhost:{port}")
            return
        else:
            print(f"Stale PID file found (PID {pid}). Cleaning up.")
            clear_pid()

    if is_server_running(port):
        print(f"DocuBrowse is already running on port {port}.")
        print(f"  UI: http://localhost:{port}")
        return

    # Verify Ollama is available before starting (needed for semantic search)
    if not ensure_ollama():
        sys.exit(1)

    # Verify database exists
    if not Path(db_path).exists():
        print(f"ERROR: Database not found: {db_path}")
        print("Run 'docubrowser.py rescan' to create and populate the database.")
        sys.exit(1)

    # If a systemd unit is installed, prefer it — it owns the process,
    # PID file (/run/docubrowser), and log directory (/var/log/docubrowser).
    # The Ollama/DB checks above still run regardless of how it's started.
    if _systemd_unit_loaded():
        print(f"Starting DocuBrowse via systemd ({SYSTEMD_UNIT})...")
        if not _systemctl("start"):
            sys.exit(1)
        for _ in range(10):
            time.sleep(0.5)
            if is_server_running(port):
                print("DocuBrowse is running.")
                print(f"  UI:       http://localhost:{port}")
                print(f"  Database: {db_path}")
                return
        print("WARNING: systemd reports the unit started but it is not responding yet.")
        print(f"  Check: systemctl status {SYSTEMD_UNIT}")
        print(f"         journalctl -u {SYSTEMD_UNIT}")
        return

    # Kill anything already occupying the port (stale process not tracked by PID file)
    _kill_port(port)

    # Launch server as detached subprocess
    server_script = Path(__file__).parent / "doc_search.py"
    if not server_script.exists():
        print(f"ERROR: Server script not found: {server_script}")
        sys.exit(1)

    log_fh = open(LOG_FILE, "a")   # noqa: SIM115 — kept open for proc lifetime
    proc = subprocess.Popen(
        [sys.executable, str(server_script), db_path, str(port)],
        stdout=log_fh,
        stderr=log_fh,
        start_new_session=True,
    )
    write_pid(proc.pid)

    # Wait for server to come up (up to 5 seconds)
    print(f"Starting DocuBrowse server (PID {proc.pid}) on port {port}...")
    for _ in range(10):
        time.sleep(0.5)
        if is_server_running(port):
            print(f"DocuBrowse is running.")
            print(f"  UI:       http://localhost:{port}")
            print(f"  Database: {db_path}")
            return

    print("WARNING: Server started but is not responding yet. Check logs.")
    print(f"  PID: {proc.pid}")


def cmd_stop(config: dict, args):
    port = args.port or config["port"]

    if _systemd_unit_loaded() and _systemd_is_active():
        print(f"Stopping DocuBrowse via systemd ({SYSTEMD_UNIT})...")
        _systemctl("stop")
        clear_pid()
        return

    pid  = read_pid()

    if not pid:
        # Try to find by port anyway
        if _kill_port(port, verbose=True):
            print("Stopped a server that wasn't tracked by PID file.")
        else:
            print("DocuBrowse does not appear to be running.")
        return

    print(f"Stopping DocuBrowse (PID {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
        # Wait for clean shutdown
        for _ in range(10):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)  # Still alive?
            except ProcessLookupError:
                break
        else:
            print(f"Server did not stop gracefully; sending SIGKILL.")
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    except ProcessLookupError:
        pass

    clear_pid()
    print("DocuBrowse stopped.")


def cmd_restart(config: dict, args):
    if _systemd_unit_loaded() and _systemd_is_active():
        port = args.port or config["port"]
        print(f"Restarting DocuBrowse via systemd ({SYSTEMD_UNIT})...")
        if not _systemctl("restart"):
            sys.exit(1)
        for _ in range(10):
            time.sleep(0.5)
            if is_server_running(port):
                print("DocuBrowse is running.")
                print(f"  UI: http://localhost:{port}")
                return
        print("WARNING: systemd reports the unit restarted but it is not responding yet.")
        print(f"  Check: systemctl status {SYSTEMD_UNIT}")
        return

    cmd_stop(config, args)
    time.sleep(1)
    cmd_start(config, args)


def _stop_running_scans(verbose: bool = True) -> bool:
    """
    Kill any running scan process group (scan_docs.py + all its workers).
    Uses the PGID stored in SCAN_PID_FILE.  Falls back to pkill if the
    pidfile is missing.  Returns True if anything was killed.
    """
    killed = False

    if SCAN_PID_FILE.exists():
        try:
            pgid = int(SCAN_PID_FILE.read_text().strip())
            os.killpg(pgid, signal.SIGTERM)
            if verbose:
                print(f"Stopped running scan (process group {pgid}).")
            killed = True
        except (ValueError, ProcessLookupError, PermissionError):
            pass
        finally:
            SCAN_PID_FILE.unlink(missing_ok=True)

    # Belt-and-suspenders: catch any orphaned workers not in the pidfile
    orphan = subprocess.run(
        ["pkill", "-f", "scan_docs.py"],
        capture_output=True,
    )
    if orphan.returncode == 0 and not killed:
        if verbose:
            print("Stopped orphaned scan worker(s).")
        killed = True

    if killed:
        time.sleep(1)   # brief pause for processes to exit and release memory
    return killed


def cmd_stopall(config: dict, args):
    """Stop all running scans, embeds, and the search server."""
    any_killed = False

    # Scans
    if _stop_running_scans(verbose=True):
        any_killed = True

    # Embeds
    orphan = subprocess.run(["pkill", "-f", "embed_docs.py"], capture_output=True)
    if orphan.returncode == 0:
        print("Stopped running embed process.")
        any_killed = True

    # Server
    port = args.port or config["port"]
    pid  = read_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"Stopped DocuBrowse server (PID {pid}).")
            any_killed = True
        except ProcessLookupError:
            pass
        clear_pid()
    elif _kill_port(port):
        print(f"Stopped server on port {port}.")
        any_killed = True

    if not any_killed:
        print("Nothing running to stop.")


def cmd_status(config: dict, args):
    port = args.port or config["port"]
    pid  = read_pid()

    print("DocuBrowse Status")
    print("─" * 40)
    print(f"  Config:   {config.get('_config_source', '(defaults)')}")
    print(f"  Database: {args.db or config['db_path']}")
    print(f"  Port:     {port}")

    if _systemd_unit_loaded():
        active  = "active" if _systemd_is_active() else "inactive"
        enabled = _systemd_is_enabled()
        print(f"  systemd:  {SYSTEMD_UNIT} ({active}, {enabled})")
        print(f"  Logs:     journalctl -u {SYSTEMD_UNIT}")
    else:
        print(f"  PID file: {PID_FILE}")

    if pid:
        print(f"  PID:      {pid}")
    else:
        print(f"  PID:      (none)")

    stats = server_stats(port)
    if stats:
        print()
        print(f"  Server:   \033[92m● RUNNING\033[0m  http://localhost:{port}")
        print(f"  Documents:  {stats.get('total_docs', '?'):,}")
        print(f"  Embedded:   {stats.get('embedded', '?'):,}")
        print(f"  Tags:       {stats.get('unique_tags', '?'):,}")
    else:
        print()
        print(f"  Server:   \033[91m● STOPPED\033[0m")
        print("  Run 'docubrowser.py start' to start the server.")


# Known file types — maps user-friendly names to extensions
_TYPE_MAP = {
    "pdf":  ".pdf",
    "txt":  ".txt",
    "text": ".txt",
    "md":   ".md",
    "markdown": ".md",
    "html": ".html",
    "htm":  ".html",
}


def cmd_rescan(config: dict, args):
    # Kill any scan already in progress (including orphaned workers) before starting.
    _stop_running_scans(verbose=True)

    doc_dir = args.doc_dir or config["doc_dir"]
    db_path = args.db      or config["db_path"]
    workers = args.workers

    # Resolve user-supplied type names → extensions
    if args.types:
        unknown = [t for t in args.types if t.lower().lstrip(".") not in _TYPE_MAP]
        if unknown:
            print(f"ERROR: Unknown file type(s): {', '.join(unknown)}")
            print(f"  Supported: {', '.join(sorted(set(_TYPE_MAP.keys())))}")
            sys.exit(1)
        scan_extensions = [_TYPE_MAP[t.lower().lstrip(".")] for t in args.types]
        # Deduplicate while preserving order
        seen = set()
        scan_extensions = [e for e in scan_extensions if not (e in seen or seen.add(e))]
    else:
        scan_extensions = []   # empty = scan_docs.py uses its own default (all types)

    if not args.no_embed:
        if not ensure_ollama():
            sys.exit(1)

    scanner = Path(__file__).parent / "scan_docs.py"
    if not scanner.exists():
        print(f"ERROR: scan_docs.py not found: {scanner}")
        sys.exit(1)

    # Print hardware summary so users know what parallelism is active
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from hardware_utils import print_hardware_summary
        print_hardware_summary(workers, args.embed_workers)
    except Exception:
        print(f"Scan workers:  {workers}")
        print(f"Embed workers: {args.embed_workers}")
        print()

    # ── Confirmation prompt for unfiltered scans ──────────────────────────────
    # When no type filter is given, walk the directory and show a file-type
    # breakdown before proceeding.  Small collections confirm quickly; large
    # mixed ones give the user a chance to add a type filter instead.
    if not scan_extensions:
        from collections import Counter as _Counter
        print(f"No type filter specified — counting files in {doc_dir} ...")
        from scan_docs import DEFAULT_EXTENSIONS as _DEFAULT_EXTENSIONS
        _SUPPORTED = set(_DEFAULT_EXTENSIONS)
        _counts: dict = _Counter()
        try:
            for _f in Path(doc_dir).rglob("*"):
                if _f.is_file():
                    _counts[_f.suffix.lower() or "(no ext)"] += 1
        except KeyboardInterrupt:
            print("\nCancelled.")
            sys.exit(0)

        _total = sum(_counts.values())
        _supported_total = sum(_counts.get(e, 0) for e in _SUPPORTED)
        _unscan_total = _total - _supported_total
        print()
        for _ext in sorted(_SUPPORTED):
            _cnt = _counts.get(_ext, 0)
            if _cnt:
                print(f"  {_ext:<14} {_cnt:>7,}  ◀ will scan")
        if _unscan_total:
            print(f"  {'(unscannable)':<14} {_unscan_total:>7,}")
        print()
        print(f"  Total files:     {_total:,}")
        print(f"  Will be scanned: {_supported_total:,}")
        print()
        try:
            _ans = input(f"Scan all {_supported_total:,} supported files? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            sys.exit(0)
        if _ans not in ("y", "yes"):
            print("Scan cancelled.  Tip: narrow with a type, e.g.  scan pdf")
            sys.exit(0)
        print()

    type_str = ", ".join(scan_extensions) if scan_extensions else "all (pdf txt md html)"
    print(f"Scanning: {doc_dir}")
    print(f"Database: {db_path}")
    print(f"Types:    {type_str}")
    print()

    cmd = [sys.executable, str(scanner), doc_dir, db_path, "--workers", str(workers)]
    if scan_extensions:
        cmd += ["--ext"] + scan_extensions
    if getattr(args, "limit", None):
        cmd += ["--limit", str(args.limit)]

    # start_new_session=True gives scan_docs.py its own process group (PGID = PID),
    # so we can kill the entire group (main process + all workers) cleanly.
    # stderr is redirected to the log file so that Python's resource_tracker
    # "leaked semaphore" warnings (printed when workers are hard-killed) never
    # appear on the terminal.
    try:
        _scan_stderr = open(LOG_FILE, "a")   # noqa: SIM115 — kept open for proc lifetime
    except (PermissionError, OSError):
        _scan_stderr = subprocess.DEVNULL
    proc = subprocess.Popen(cmd, start_new_session=True, stderr=_scan_stderr)
    SCAN_PID_FILE.write_text(str(proc.pid))
    try:
        proc.wait()
    except KeyboardInterrupt:
        _stop_running_scans(verbose=False)
        print("\nScan interrupted.")
        sys.exit(0)
    finally:
        SCAN_PID_FILE.unlink(missing_ok=True)
        if hasattr(_scan_stderr, "close"):
            _scan_stderr.close()

    if proc.returncode != 0:
        print("\nScan failed.")
        sys.exit(proc.returncode)

    if not args.no_embed:
        print()
        _run_embed(db_path, embed_workers=args.embed_workers)

    _offer_purge(db_path)


def cmd_scan(config: dict, args):
    """scan — scan only, no embedding. Equivalent to rescan --no-embed."""
    # Reuse rescan logic by injecting no_embed=True
    args.no_embed = True
    if not hasattr(args, "embed_workers"):
        args.embed_workers = 0
    cmd_rescan(config, args)


def cmd_embed(config: dict, args):
    db_path = args.db or config["db_path"]

    if not ensure_ollama():
        sys.exit(1)

    if not Path(db_path).exists():
        print(f"ERROR: Database not found: {db_path}")
        print("Run 'docubrowser.py rescan' first.")
        sys.exit(1)

    _run_embed(db_path, embed_workers=args.workers)


def cmd_open(config: dict, args):
    port = args.port or config["port"]
    url  = f"http://localhost:{port}"

    if not is_server_running(port):
        print(f"Server is not running on port {port}.")
        print("Start it first with:  docubrowser.py start")
        sys.exit(1)

    import webbrowser
    print(f"Opening {url} ...")
    webbrowser.open(url)


def _offer_purge(db_path: str):
    """Prompt the user to run a PII scan after a completed scan/rescan.

    Choices:
      y        — live purge (remove matching documents immediately)
      n        — skip
      D/Enter  — dry-run (default): show matches, no changes;
                 if matches found, offer to proceed live.
    """
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from purge_pii import run_purge
    except ImportError:
        return  # purge_pii.py missing — silently skip

    print()
    print("─" * 50)
    print("PII Scan — check index for personal information")
    print("  [y] Purge now  — remove matching documents")
    print("  [n] Skip")
    print("  [D] Dry-run    — show matches only, no changes  (default)")
    print()

    try:
        answer = input("Choice [D]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if answer == 'n':
        return

    dry_run = answer not in ('y', 'yes')
    print()
    found = run_purge(db_path, dry_run=dry_run)

    # After a dry-run that found matches, offer to proceed live
    if dry_run and found:
        print()
        try:
            followup = input("Proceed with live purge? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if followup in ('y', 'yes'):
            print()
            run_purge(db_path, dry_run=False)


def cmd_purge(config: dict, args):
    """purge — scan index for PII patterns and remove matching documents."""
    db_path = args.db or config["db_path"]

    if not Path(db_path).exists():
        print(f"ERROR: Database not found: {db_path}")
        print("Run 'docubrowser.py rescan' first.")
        sys.exit(1)

    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from purge_pii import run_purge
    except ImportError as exc:
        print(f"ERROR: Could not load purge_pii.py: {exc}")
        sys.exit(1)

    run_purge(db_path, dry_run=args.dry_run)


def cmd_ignore(config: dict, args):
    """ignore — manage ignore_dirs.txt (directories excluded from scanning).

    Subactions:
      add <dir>     Add a directory to ignore_dirs.txt and purge any
                     already-indexed documents under it from the DB.
      remove <dir>  Remove a directory from ignore_dirs.txt (does not
                     re-index — run 'rescan' afterward to pick it back up).
      list          Show currently-ignored directories.
    """
    db_path = Path(args.db or config["db_path"])

    sys.path.insert(0, str(Path(__file__).parent))
    from scan_docs import IGNORE_DIRS_FILENAME, _load_ignore_dirs, purge_path_prefix

    ig_path = db_path.parent / IGNORE_DIRS_FILENAME

    if args.ignore_action == "list":
        dirs = sorted(_load_ignore_dirs(db_path))
        if not dirs:
            print(f"No ignored directories. ({ig_path})")
        else:
            print(f"Ignored directories ({ig_path}):")
            for d in dirs:
                print(f"  {d}")
        return

    if not args.path:
        print("ERROR: a directory path is required for 'ignore add' / 'ignore remove'")
        sys.exit(1)

    target = str(Path(args.path).expanduser().resolve())

    if args.ignore_action == "add":
        dirs = _load_ignore_dirs(db_path)
        if target in dirs:
            print(f"Already ignored: {target}")
        else:
            dirs.add(target)
            ig_path.parent.mkdir(parents=True, exist_ok=True)
            with open(ig_path, "a", encoding="utf-8") as fh:
                fh.write(target + "\n")
            print(f"Added to ignore list: {target}")

        # Purge any previously-indexed documents under this directory
        if Path(db_path).exists():
            from docubrowse_db import get_db
            conn = get_db(str(db_path))
            removed = purge_path_prefix(conn, target)
            conn.close()
            print(f"Purged {removed:,} previously-indexed document(s) under {target}")
        else:
            print("(No database yet — nothing to purge.)")

    elif args.ignore_action == "remove":
        dirs = _load_ignore_dirs(db_path)
        if target not in dirs:
            print(f"Not in ignore list: {target}")
            return
        dirs.discard(target)
        if dirs:
            ig_path.write_text("\n".join(sorted(dirs)) + "\n", encoding="utf-8")
        else:
            ig_path.unlink(missing_ok=True)
        print(f"Removed from ignore list: {target}")
        print("Run 'rescan' to re-index this directory.")


def cmd_report(config: dict, args):
    """report — walk doc_dir and print a file-type breakdown, no DB changes."""
    from collections import Counter
    doc_dir = args.doc_dir or config["doc_dir"]
    p = Path(doc_dir)
    if not p.exists() or not p.is_dir():
        print(f"ERROR: Directory not found: {doc_dir}")
        sys.exit(1)

    from scan_docs import DEFAULT_EXTENSIONS
    SUPPORTED = set(DEFAULT_EXTENSIONS)

    print(f"File type report: {doc_dir}")
    print("Scanning directory (no changes made)...")
    counts: dict = Counter()
    sizes:  dict = Counter()
    try:
        for f in p.rglob("*"):
            if f.is_file():
                ext = f.suffix.lower() or "(no ext)"
                counts[ext] += 1
                try:
                    sizes[ext] += f.stat().st_size
                except OSError:
                    pass
    except KeyboardInterrupt:
        print("\nInterrupted — partial results shown.")

    total_files = sum(counts.values())
    total_bytes = sum(sizes.values())
    if not total_files:
        print("No files found.")
        return

    # Split into scannable (listed individually) and unscannable (collapsed)
    unscan_count = 0
    unscan_bytes = 0
    scannable_rows = []
    for ext, cnt in sorted(counts.items(), key=lambda x: x[1], reverse=True):
        if ext in SUPPORTED:
            scannable_rows.append((ext, cnt, sizes[ext]))
        else:
            unscan_count += cnt
            unscan_bytes += sizes[ext]

    print()
    print(f"  {'Extension':<14} {'Files':>8}  {'% total':>8}  {'Size':>10}")
    print("  " + "─" * 48)
    for ext, cnt, sz in scannable_rows:
        pct = cnt * 100.0 / total_files
        mb  = sz / (1024 * 1024)
        print(f"  {ext:<14} {cnt:>8,}  {pct:>7.1f}%  {mb:>8.1f}MB")
    if unscan_count:
        pct = unscan_count * 100.0 / total_files
        mb  = unscan_bytes / (1024 * 1024)
        print(f"  {'(unscannable)':<14} {unscan_count:>8,}  {pct:>7.1f}%  {mb:>8.1f}MB")
    print("  " + "─" * 48)
    total_mb = total_bytes / (1024 * 1024)
    supported_count = sum(c for _, c, _ in scannable_rows)
    print(f"  {'TOTAL':<14} {total_files:>8,}  {'100.0%':>8}  {total_mb:>8.1f}MB")
    print()
    print(f"  Scannable: {supported_count:,}   Unscannable: {unscan_count:,}")
    print()
    print(f"  Tip: run 'docubrowser.py scan pdf' to index PDFs only,")
    print(f"       or   'docubrowser.py scan' to index all supported types.")


def cmd_scan_file(config: dict, args):
    """scan-file — extract and index a single file, then embed it."""
    file_path = Path(" ".join(args.file)).resolve()
    db_path   = args.db      or config["db_path"]
    doc_dir   = args.doc_dir or config["doc_dir"]

    if not file_path.exists():
        print(f"ERROR: File not found: {file_path}")
        sys.exit(1)

    print(f"File:     {file_path}")
    print(f"Database: {db_path}")
    print()

    sys.path.insert(0, str(Path(__file__).parent))
    from scan_docs import scan_single_file

    result = scan_single_file(str(file_path), db_path, doc_dir=doc_dir)

    if result.get("removed_from_blacklist"):
        print("  ✓ Removed from scan_blacklist.txt")

    if not result["success"]:
        print(f"  ✗ FAILED: {result['error']}")
        print("  File has been re-added to scan_blacklist.txt.")
        sys.exit(1)

    doc_type = result.get("doc_type", "unknown")
    print(f"  ✓ Indexed: {result.get('title') or file_path.stem}")
    print(f"  doc_type: {doc_type}")
    if result.get("tags"):
        print(f"  Tags:     {', '.join(result['tags'])}")
    if doc_type == "scanned":
        print("  → Image-only PDF added to ocr_list_pdfs.txt")
    print()

    if not args.no_embed:
        _run_embed(db_path, embed_workers=args.embed_workers)
    else:
        print("Skipping embedding (--no-embed).")
        print("Run 'docubrowser.py embed' to generate embeddings later.")


# ─── duplist / dupclean ───────────────────────────────────────────────────────

def cmd_duplist(config: dict, args):
    """List duplicate documents (exact and/or near-duplicate)."""
    db_path = args.db or config['db_path']
    if not Path(db_path).exists():
        print(f"ERROR: Database not found: {db_path}")
        sys.exit(1)

    sys.path.insert(0, str(Path(__file__).parent))
    from dup_detect import find_exact_dups, find_near_dups, fmt_size, group_label

    total_docs = _db_count(db_path)
    print(f"Scanning {total_docs:,} indexed documents for duplicates...")
    print()

    # ── Exact duplicates ──────────────────────────────────────────────────────
    exact_groups = find_exact_dups(db_path, progress=True)

    if exact_groups:
        redundant = sum(len(g) - 1 for g in exact_groups)
        recoverable = sum(
            (len(g) - 1) * (g[0].get('size_bytes') or 0)
            for g in exact_groups
        )
        print(f"Found {len(exact_groups)} exact duplicate group(s) "
              f"({redundant} redundant cop{'y' if redundant == 1 else 'ies'}, "
              f"{fmt_size(recoverable)} recoverable):")
        print()
        for i, group in enumerate(exact_groups, 1):
            print(f"  Group {i} — {group_label(group, 'exact')}")
            for doc in group:
                print(f"    {doc['path']}")
            print()
    else:
        print("No exact duplicates found.")
        print()

    # ── Near-duplicates ───────────────────────────────────────────────────────
    if getattr(args, 'near_dups', False):
        threshold = getattr(args, 'threshold', 0.97)
        near_groups = find_near_dups(db_path, threshold=threshold, progress=True)

        if near_groups:
            print(f"Found {len(near_groups)} near-duplicate group(s) "
                  f"(cosine similarity ≥ {threshold * 100:.0f}%):")
            print()
            for i, group in enumerate(near_groups, 1):
                print(f"  Group {i} — {group_label(group, 'near')}")
                for doc in group:
                    print(f"    {doc['path']}")
                print()
        else:
            print(f"No near-duplicates found (threshold {threshold * 100:.0f}%).")
            print()

    if exact_groups or getattr(args, 'near_dups', False):
        print("Run 'docubrowser.py dupclean' to interactively remove duplicates.")


def cmd_dupclean(config: dict, args):
    """Interactive TUI to review and remove duplicate documents."""
    db_path = args.db or config['db_path']
    if not Path(db_path).exists():
        print(f"ERROR: Database not found: {db_path}")
        sys.exit(1)

    sys.path.insert(0, str(Path(__file__).parent))
    from dup_detect import find_exact_dups, find_near_dups, fmt_size, group_label

    total_docs = _db_count(db_path)
    print(f"Scanning {total_docs:,} indexed documents for duplicates...")
    print()

    all_groups = []
    exact_groups = find_exact_dups(db_path, progress=True)
    for g in exact_groups:
        all_groups.append(('exact', g))

    if getattr(args, 'near_dups', False):
        threshold = getattr(args, 'threshold', 0.97)
        near_groups = find_near_dups(db_path, threshold=threshold, progress=True)
        for g in near_groups:
            all_groups.append(('near', g))

    if not all_groups:
        print("No duplicates found — nothing to clean.")
        return

    total = len(all_groups)
    kind_label = {'exact': 'EXACT', 'near': 'NEAR-DUPLICATE'}
    print(f"Found {total} duplicate group(s). Starting interactive review...")
    print("Commands: Keep A / Keep B / Keep Both (skip) / Q (quit)")
    print()

    deleted_total = 0

    # Build letter labels: A, B, C, … Z, AA, AB, …
    def _labels(n):
        import string
        alpha = string.ascii_uppercase
        if n <= 26:
            return list(alpha[:n])
        return [alpha[i] for i in range(26)] + \
               [alpha[i] + alpha[j] for i in range(26) for j in range(26)][:n - 26]

    for idx, (kind, group) in enumerate(all_groups, 1):
        labels = _labels(len(group))
        print("─" * 60)
        print(f"Group {idx}/{total} [{kind_label[kind]}] — {group_label(group, kind)}")
        print()
        for label, doc in zip(labels, group):
            title = (doc.get('title') or doc.get('name') or 'Untitled')[:50]
            print(f"  [{label}] {doc['path']}")
            print(f"       {title}  ({fmt_size(doc.get('size_bytes'))})")
        print()

        label_map = {lbl.lower(): doc for lbl, doc in zip(labels, group)}
        opts = " / ".join(f"Keep {lbl}" for lbl in labels) + " / Keep Both (skip) / Q (quit)"
        print(f"  {opts}")

        while True:
            try:
                ans = input("  > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.")
                return

            if ans in ('q', 'quit'):
                print(f"\nStopped after reviewing {idx}/{total} groups. "
                      f"{deleted_total} file(s) deleted.")
                return

            if ans in ('both', 'keep both', 's', 'skip', ''):
                print("  Kept both — skipping.")
                break

            # Check for "keep X" or bare letter
            keep_label = None
            if ans.startswith('keep '):
                keep_label = ans[5:].strip()
            elif ans in label_map:
                keep_label = ans

            if keep_label and keep_label in label_map:
                targets = [doc for lbl, doc in zip(labels, group)
                           if lbl.lower() != keep_label]
                print()
                for doc in targets:
                    print(f"  Will delete: {doc['path']}")
                print()
                try:
                    confirm = input("  Confirm deletion? [y/N]: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print("\nAborted.")
                    return
                if confirm not in ('y', 'yes'):
                    print("  Cancelled — skipping.")
                    break
            else:
                print(f"  ✗ Enter {', '.join(f'Keep {l}' for l in labels)}, "
                      f"'Keep Both', or 'Q'.")
                continue

            # Delete from disk and DB (commit per-doc to avoid disk/DB split)
            from docubrowse_db import get_db as _get_db
            conn = _get_db(db_path)
            try:
                for doc in targets:
                    path = doc['path']
                    try:
                        Path(path).unlink()
                    except FileNotFoundError:
                        pass  # already gone — still clean DB
                    except OSError as e:
                        print(f"  ✗ Could not delete {path}: {e}")
                        continue

                    try:
                        conn.execute('DELETE FROM documents WHERE id = ?', (doc['id'],))
                        # doc_fts is a contentless FTS5 table — no FK cascade,
                        # must be cleaned manually to avoid ghost search results.
                        conn.execute('DELETE FROM doc_fts WHERE rowid = ?', (doc['id'],))
                        conn.commit()   # commit per-doc: keeps disk and DB in sync
                        deleted_total += 1
                        print(f"  ✓ Deleted: {path}")
                    except Exception as e:
                        conn.rollback()
                        print(f"  ✗ DB error for {path}: {e}")
            finally:
                conn.close()

            break  # move to next group

    print()
    print(f"Done. {deleted_total} file(s) deleted across {total} group(s) reviewed.")


def _db_count(db_path: str) -> int:
    """Return total document count from the database."""
    try:
        from docubrowse_db import get_db as _get_db
        conn = _get_db(db_path)
        n = conn.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _kill_port(port: int, verbose: bool = False) -> bool:
    """Kill any process listening on the given port. Returns True if killed."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"],
            capture_output=True, text=True
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
        # lsof not available; try fuser
        try:
            subprocess.run(["fuser", "-k", f"{port}/tcp"],
                           capture_output=True)
        except Exception:
            pass
        return False


def _run_embed(db_path: str, embed_workers: int = 6):
    embedder = Path(__file__).parent / "embed_docs.py"
    if not embedder.exists():
        print(f"ERROR: embed_docs.py not found: {embedder}")
        sys.exit(1)

    print(f"Generating embeddings with {embed_workers} parallel workers...")
    print()
    result = subprocess.run(
        [sys.executable, str(embedder), db_path, "--workers", str(embed_workers)]
    )
    if result.returncode != 0:
        print("\nEmbedding generation failed.")
        sys.exit(result.returncode)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docubrowser.py",
        description="DocuBrowse — document search and browsing tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""            Examples:
              docubrowser.py start
              docubrowser.py status
              docubrowser.py scan                           scan all types, no embed
              docubrowser.py scan pdf                       PDFs only, no embed
              docubrowser.py rescan                         scan + embed all types
              docubrowser.py rescan pdf                     scan + embed PDFs only
              docubrowser.py rescan pdf txt                 scan + embed PDFs and text
              docubrowser.py rescan --doc-dir /mnt/data/Documents
              docubrowser.py rescan --workers 4 --embed-workers 8
              docubrowser.py stop
              docubrowser.py stopall                           stop scans, embeds, and server
              docubrowser.py report                            show file-type breakdown (no DB changes)
              docubrowser.py report --doc-dir /mnt/data/Docs
              docubrowser.py purge --dry-run                  preview PII matches
              docubrowser.py purge                             remove PII documents interactively
              docubrowser.py scan-file --file /path/to/file.pdf       index one file + embed
              docubrowser.py scan-file --file /path/to/file.pdf --no-embed

            Tip: run 'docubrowser.py <command> --help' for per-command options.
            """),
    )

    # Global options
    parser.add_argument("--db",   metavar="PATH", help="Path to SQLite database (overrides config)")
    parser.add_argument("--port", metavar="PORT", type=int, help="Server port (overrides config)")
    parser.add_argument("--config", metavar="FILE", help="Config file path")

    sub = parser.add_subparsers(dest="command", metavar="<command>", title="commands")
    sub.required = True

    # start
    p_start = sub.add_parser("start", help="Start the DocuBrowse server")
    p_start.add_argument("--db",   metavar="PATH", help="Database path")
    p_start.add_argument("--port", metavar="PORT", type=int, help="Port to listen on")

    # stop
    p_stop = sub.add_parser("stop", help="Stop the DocuBrowse server")
    p_stop.add_argument("--port", metavar="PORT", type=int, help="Port (used to find process)")

    # restart
    p_restart = sub.add_parser("restart", help="Restart the DocuBrowse server")
    p_restart.add_argument("--db",   metavar="PATH", help="Database path")
    p_restart.add_argument("--port", metavar="PORT", type=int, help="Port")

    # status
    p_status = sub.add_parser("status", help="Show server status and index stats")
    p_status.add_argument("--db",   metavar="PATH", help="Database path")
    p_status.add_argument("--port", metavar="PORT", type=int, help="Port")

    # rescan
    p_rescan = sub.add_parser(
        "rescan",
        help="Scan documents and update the index\n"
             "                          [TYPE: pdf txt md html]  [--workers N]  [--embed-workers N]  [--no-embed]",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            File types: pdf  txt  md  html  (default: all four)

            Examples:
              rescan                        scan all supported types
              rescan pdf                    PDFs only
              rescan pdf txt                PDFs and plain text
              rescan --no-embed             scan without re-embedding
              rescan --workers 4            override CPU worker count
              rescan --embed-workers 8      override Ollama thread count
        """),
    )
    p_rescan.add_argument("types", nargs="*", metavar="TYPE",
                          help="File type(s) to scan: pdf txt md html (default: all)")
    p_rescan.add_argument("--doc-dir", metavar="DIR", dest="doc_dir",
                          help="Document directory to scan")
    p_rescan.add_argument("--db", metavar="PATH", help="Database path")
    p_rescan.add_argument("--no-embed", action="store_true",
                          help="Skip embedding generation after scan")
    # Hardware-aware defaults
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from hardware_utils import recommended_scan_workers, recommended_embed_workers
        _default_scan_workers  = recommended_scan_workers()
        _default_embed_workers = recommended_embed_workers()
    except Exception:
        _default_scan_workers  = min(os.cpu_count() or 4, 8)
        _default_embed_workers = 6

    p_rescan.add_argument("--workers", metavar="N", type=int,
                          default=_default_scan_workers,
                          help=f"Parallel worker processes for PDF extraction (default: {_default_scan_workers}, based on physical CPU cores)")
    p_rescan.add_argument("--embed-workers", metavar="N", type=int,
                          default=_default_embed_workers, dest="embed_workers",
                          help=f"Parallel threads for Ollama embedding (default: {_default_embed_workers}, GPU-aware)")
    p_rescan.add_argument("--limit", metavar="N", type=int, default=None,
                          help="Process at most N unindexed files this run; next run resumes where this left off")

    # scan (scan-only alias — no embedding step)
    p_scan = sub.add_parser(
        "scan",
        help="Scan documents only (no embedding)  [TYPE: pdf txt md html | --workers N]",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            File types: pdf  txt  md  html  (default: all four)
            Same as:    rescan --no-embed [TYPE ...]

            Examples:
              scan                  scan all supported types
              scan pdf              PDFs only
              scan pdf txt          PDFs and plain text
              scan --workers 4      override CPU worker count
        """),
    )
    p_scan.add_argument("types", nargs="*", metavar="TYPE",
                        help="File type(s) to scan: pdf txt md html (default: all)")
    p_scan.add_argument("--doc-dir", metavar="DIR", dest="doc_dir",
                        help="Document directory to scan")
    p_scan.add_argument("--db", metavar="PATH", help="Database path")
    p_scan.add_argument("--workers", metavar="N", type=int,
                        default=_default_scan_workers,
                        help=f"Parallel worker processes (default: {_default_scan_workers})")
    p_scan.add_argument("--limit", metavar="N", type=int, default=None,
                        help="Process at most N unindexed files this run; next run resumes where this left off")

    # embed
    p_embed = sub.add_parser("embed", help="Generate/refresh embeddings for unembedded documents")
    p_embed.add_argument("--db", metavar="PATH", help="Database path")
    p_embed.add_argument("--workers", metavar="N", type=int, default=_default_embed_workers,
                         help=f"Parallel threads for Ollama embedding (default: {_default_embed_workers}, GPU-aware)")

    # open
    p_open = sub.add_parser("open", help="Open the DocuBrowse UI in your browser")
    p_open.add_argument("--port", metavar="PORT", type=int, help="Port")

    # stopall
    p_stopall = sub.add_parser("stopall", help="Stop all running scans, embeds, and the server")
    p_stopall.add_argument("--port", metavar="PORT", type=int, help="Port (used to find server)")

    # purge
    p_purge = sub.add_parser(
        "purge",
        help="Scan index for PII patterns and remove matching documents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Checks stored description/snippet text (~800 chars) for:
              SSN, Credit Card, Passport Number, Date of Birth,
              Medical Record Number, Driver License

            Removed documents are added to pii_blacklist.txt and will
            never be re-ingested, even after a rescan.

            Examples:
              purge               interactive — prompts before deleting
              purge --dry-run     show matches, make no changes
        """),
    )
    p_purge.add_argument("--db", metavar="PATH", help="Database path")
    p_purge.add_argument("--dry-run", action="store_true",
                         help="Report matches without removing anything")

    # ignore
    p_ignore = sub.add_parser(
        "ignore",
        help="Manage directories excluded from scanning (ignore_dirs.txt)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Maintains ignore_dirs.txt (next to the database) — directories
            that 'rescan' will skip entirely.

            'add' immediately purges any documents already indexed from
            under that directory. 'remove' lets the directory be picked
            up again on the next rescan.

            Examples:
              ignore add /mnt/data/Documents/myWorkDocs
              ignore remove /mnt/data/Documents/myWorkDocs
              ignore list
        """),
    )
    p_ignore.add_argument("ignore_action", choices=["add", "remove", "list"],
                          help="Action to perform")
    p_ignore.add_argument("path", nargs="?", metavar="DIR",
                          help="Directory path (required for add/remove)")
    p_ignore.add_argument("--db", metavar="PATH", help="Database path")

    # report
    p_report = sub.add_parser(
        "report",
        help="Scan directory and report file-type counts (no DB changes)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Walks the document directory and prints a breakdown of every file
            type found — count, percentage, total size, and whether each type
            is currently supported for indexing.  No database is touched.

            Example:
              report
              report --doc-dir /mnt/data/Documents
        """),
    )
    p_report.add_argument("--doc-dir", metavar="DIR", dest="doc_dir",
                          help="Directory to report on (overrides config)")
    p_report.add_argument("--db", metavar="PATH",
                          help="Ignored (report does not use the database; accepted for CLI consistency)")

    # scan-file
    p_scan_file = sub.add_parser(
        "scan-file",
        help="Extract and index a single file, then embed it",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Extracts and indexes one file. If the file is in scan_blacklist.txt
            it is removed first (treating this as an explicit retry).
            PII-blacklisted files are refused.

            Examples:
              scan-file --file /mnt/data/Documents/report.pdf
              scan-file --file /mnt/data/Documents/report.pdf --no-embed
              scan-file --file "/path/with spaces/doc.html" --doc-dir /mnt/data/Documents
        """),
    )
    p_scan_file.add_argument("--file", nargs='+', metavar="PATH", required=True,
                             help="Path to the file to index (quoting optional — spaces are rejoined)")
    p_scan_file.add_argument("--db", metavar="PATH", help="Database path")
    p_scan_file.add_argument("--doc-dir", metavar="DIR", dest="doc_dir",
                             help="Document root (used for tag derivation; defaults to configured doc_dir)")
    p_scan_file.add_argument("--no-embed", action="store_true",
                             help="Skip embedding after indexing")
    p_scan_file.add_argument("--embed-workers", metavar="N", type=int,
                             default=_default_embed_workers, dest="embed_workers",
                             help=f"Parallel threads for Ollama embedding (default: {_default_embed_workers})")

    # duplist
    p_duplist = sub.add_parser(
        "duplist",
        help="List duplicate documents grouped by content hash",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Finds byte-identical files via SHA256 (size pre-filter avoids hashing
            unique-size files).  Add --near-dups to also surface semantically
            similar documents using embedding cosine similarity (requires numpy).

            Examples:
              duplist                       exact duplicates only
              duplist --near-dups           exact + near-duplicates
              duplist --near-dups --threshold 0.95   lower similarity bar
        """),
    )
    p_duplist.add_argument("--db", metavar="PATH", help="Database path")
    p_duplist.add_argument("--near-dups", action="store_true", dest="near_dups",
                           help="Also find near-duplicates via embedding similarity")
    p_duplist.add_argument("--threshold", metavar="FLOAT", type=float, default=0.97,
                           dest="threshold",
                           help="Cosine similarity threshold for near-dups (default: 0.97)")

    # dupclean
    p_dupclean = sub.add_parser(
        "dupclean",
        help="Interactively review and remove duplicate documents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            For each duplicate group, shows all copies and prompts you to pick
            which to delete.  Deletes from disk and removes from the index.

            Examples:
              dupclean                      review exact duplicates
              dupclean --near-dups          also include near-duplicates
        """),
    )
    p_dupclean.add_argument("--db", metavar="PATH", help="Database path")
    p_dupclean.add_argument("--near-dups", action="store_true", dest="near_dups",
                            help="Also include near-duplicates")
    p_dupclean.add_argument("--threshold", metavar="FLOAT", type=float, default=0.97,
                            dest="threshold",
                            help="Cosine similarity threshold for near-dups (default: 0.97)")

    return parser


COMMANDS = {
    "start":     cmd_start,
    "stop":      cmd_stop,
    "stopall":   cmd_stopall,
    "restart":   cmd_restart,
    "status":    cmd_status,
    "scan":      cmd_scan,
    "scan-file": cmd_scan_file,
    "rescan":    cmd_rescan,
    "embed":     cmd_embed,
    "open":      cmd_open,
    "purge":     cmd_purge,
    "ignore":    cmd_ignore,
    "report":    cmd_report,
    "duplist":   cmd_duplist,
    "dupclean":  cmd_dupclean,
}


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Load config (override path if --config given at top level)
    if hasattr(args, "config") and args.config:
        CONFIG_PATHS.insert(0, Path(args.config))
    config = load_config()

    # Dispatch
    handler = COMMANDS.get(args.command)
    if handler:
        handler(config, args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
