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
  embed       Generate/refresh embeddings for unembedded documents
  open        Open the DocuBrowse UI in your browser
  duplist     List duplicate documents         [Not yet implemented]
  dupclean    Clean up duplicate documents     [Not yet implemented]
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
DEFAULT_DB      = Path(__file__).parent / "docs.db"
DEFAULT_DOC_DIR = "/mnt/data/Documents"
PID_FILE        = Path("/tmp/docubrowse.pid")
SCAN_PID_FILE   = Path("/tmp/docubrowse_scan.pid")   # PGID of running scan
CONFIG_PATHS    = [
    Path("/etc/docubrowse.config"),
    Path(__file__).parent / "docubrowse.config",
]

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

    # Verify Ollama is available before starting (needed for semantic search)
    if not ensure_ollama():
        sys.exit(1)

    # Verify database exists
    if not Path(db_path).exists():
        print(f"ERROR: Database not found: {db_path}")
        print("Run 'docubrowser.py rescan' to create and populate the database.")
        sys.exit(1)

    # Kill anything already occupying the port (stale process not tracked by PID file)
    _kill_port(port)

    # Launch server as detached subprocess
    server_script = Path(__file__).parent / "doc_search.py"
    if not server_script.exists():
        print(f"ERROR: Server script not found: {server_script}")
        sys.exit(1)

    proc = subprocess.Popen(
        [sys.executable, str(server_script), db_path, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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

    type_str = ", ".join(scan_extensions) if scan_extensions else "all (pdf txt md html)"
    print(f"Scanning: {doc_dir}")
    print(f"Database: {db_path}")
    print(f"Types:    {type_str}")
    print()

    cmd = [sys.executable, str(scanner), doc_dir, db_path, "--workers", str(workers)]
    if scan_extensions:
        cmd += ["--ext"] + scan_extensions

    # start_new_session=True gives scan_docs.py its own process group (PGID = PID),
    # so we can kill the entire group (main process + all workers) cleanly.
    # stderr is redirected to the log file so that Python's resource_tracker
    # "leaked semaphore" warnings (printed when workers are hard-killed) never
    # appear on the terminal.
    _log_paths = [
        Path("/var/log/docubrowser.log"),
        Path.home() / ".local/share/docubrowser/docubrowser.log",
    ]
    _scan_stderr = subprocess.DEVNULL
    for _lp in _log_paths:
        try:
            _lp.parent.mkdir(parents=True, exist_ok=True)
            _scan_stderr = open(_lp, "a")   # noqa: SIM115 — kept open for proc lifetime
            break
        except (PermissionError, OSError):
            continue
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


# ─── Not-yet-implemented stubs ────────────────────────────────────────────────

def cmd_duplist(config: dict, args):
    print("Not yet implemented: duplist")
    print("  Future: List duplicate documents grouped by content hash.")


def cmd_dupclean(config: dict, args):
    print("Not yet implemented: dupclean")
    print("  Future: Interactive TUI to review and remove duplicate documents.")


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

    # duplist (stub)
    sub.add_parser("duplist", help="List duplicate documents [Not yet implemented]")

    # dupclean (stub)
    sub.add_parser("dupclean", help="Clean up duplicate documents [Not yet implemented]")

    return parser


COMMANDS = {
    "start":    cmd_start,
    "stop":     cmd_stop,
    "stopall":  cmd_stopall,
    "restart":  cmd_restart,
    "status":   cmd_status,
    "scan":     cmd_scan,
    "rescan":   cmd_rescan,
    "embed":    cmd_embed,
    "open":     cmd_open,
    "duplist":  cmd_duplist,
    "dupclean": cmd_dupclean,
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
