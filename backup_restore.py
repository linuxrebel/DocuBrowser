#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
DocuBrowse backup and restore utility.

Creates timestamped tarballs of all runtime data files (database, config,
blacklists, scan/ignore lists).  Keeps up to 3 backups; oldest is pruned
when a new one is created.

A fresh install + restore from one of these backups yields a fully working
system with the same index, settings, and exclusion lists.

Usage:
    backup_restore.py --backup  [--db PATH] [--backup-dir PATH]
    backup_restore.py --restore [--db PATH] [--backup-dir PATH]
    backup_restore.py           (interactive — asks which operation)
"""

import argparse
import ctypes
import os
import platform
import sys
import tarfile
from datetime import datetime
from pathlib import Path


# ── Privilege check ───────────────────────────────────────────────────────────

def _require_elevated() -> None:
    """Exit with an error if the process lacks root (Linux/macOS/FreeBSD) or
    Administrator (Windows) privileges."""
    if platform.system() == "Windows":
        try:
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
        except AttributeError:
            is_admin = False
        if not is_admin:
            print("ERROR: This script must be run as Administrator.")
            print("       Right-click your terminal and choose 'Run as administrator'.")
            sys.exit(1)
    elif hasattr(os, "geteuid"):
        # Works on Linux, Darwin, FreeBSD, Cygwin, etc.
        if os.geteuid() != 0:
            print("ERROR: This script must be run as root.")
            print("       Use:  sudo ./backup_restore.py ...")
            sys.exit(1)


# ── Defaults ──────────────────────────────────────────────────────────────────

MAX_BACKUPS = 3

# Canonical backup location (root is required, so /opt is always writable).
BACKUP_DIR = Path("/opt/docubrowser/backups")

# Files to back up, relative to the data directory (where du-docs.db lives).
# All are optional — a fresh install may not have all of them yet.
BACKUP_FILES = [
    "du-docs.db",
    "docubrowse.config",
    "scan_dirs.txt",
    "ignore_dirs.txt",
    "scan_blacklist.txt",
    "pii_blacklist.txt",
    "ocr_list_pdfs.txt",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_backup_dir(override: str | None) -> Path:
    """Pick the backup directory: explicit override or /opt/docubrowser/backups."""
    d = Path(override) if override else BACKUP_DIR

    try:
        d.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        print(f"ERROR: Cannot create backup directory: {d}")
        sys.exit(1)

    if not os.access(d, os.W_OK):
        print(f"ERROR: Backup directory is not writable: {d}")
        sys.exit(1)

    return d


def _resolve_data_dir(db_path: str | None) -> Path:
    """Determine the data directory from the --db flag or default location."""
    if db_path:
        p = Path(db_path)
        if p.is_file():
            return p.parent
        if p.is_dir():
            return p
        print(f"ERROR: Path not found: {db_path}")
        sys.exit(1)

    # Default: directory containing this script (where du-docs.db lives)
    return Path(__file__).resolve().parent


def _list_backups(backup_dir: Path) -> list[Path]:
    """Return existing backups sorted oldest-first."""
    pattern = "docubrowser_backup_*.tar.gz"
    backups = sorted(backup_dir.glob(pattern))
    return backups


def _prune_backups(backup_dir: Path) -> None:
    """Remove oldest backups to keep at most MAX_BACKUPS."""
    backups = _list_backups(backup_dir)
    while len(backups) >= MAX_BACKUPS:
        oldest = backups.pop(0)
        oldest.unlink()
        print(f"  Pruned old backup: {oldest.name}")


def _fmt_size(path: Path) -> str:
    """Human-readable file size."""
    try:
        size = path.stat().st_size
    except OSError:
        return "? B"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# ── Backup ────────────────────────────────────────────────────────────────────

def do_backup(data_dir: Path, backup_dir: Path) -> Path:
    """Create a backup tarball.  Returns the path to the new backup."""
    # Check that at least the database exists
    db_file = data_dir / "du-docs.db"
    if not db_file.exists():
        print(f"ERROR: Database not found at {db_file}")
        print("Nothing to back up.  Run a scan first to create the index.")
        sys.exit(1)

    # Collect files that actually exist
    to_backup = []
    for name in BACKUP_FILES:
        p = data_dir / name
        if p.exists():
            to_backup.append((name, p))

    if not to_backup:
        print("ERROR: No data files found to back up.")
        sys.exit(1)

    # Prune before creating
    _prune_backups(backup_dir)

    # Create tarball
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tarball_name = f"docubrowser_backup_{timestamp}.tar.gz"
    tarball_path = backup_dir / tarball_name

    print(f"Creating backup: {tarball_path}")
    print(f"  Data directory: {data_dir}")
    print()

    with tarfile.open(tarball_path, "w:gz") as tar:
        for name, path in to_backup:
            tar.add(str(path), arcname=name)
            print(f"  Added: {name} ({_fmt_size(path)})")

    print()
    print(f"Backup complete: {tarball_path}")
    print(f"  Size: {_fmt_size(tarball_path)}")

    # Show backup inventory
    backups = _list_backups(backup_dir)
    print(f"  Backups on disk: {len(backups)} of {MAX_BACKUPS} max")

    return tarball_path


# ── Server check ──────────────────────────────────────────────────────────────

def _server_is_running() -> bool:
    """Check if the DocuBrowse server appears to be running."""
    pid_candidates = [
        Path("/var/run/docubrowser/docubrowser.pid"),
        Path.home() / ".local/run/docubrowser.pid",
    ]
    for pid_file in pid_candidates:
        if not pid_file.exists():
            continue
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)  # signal 0 = existence check
            return True
        except (ValueError, ProcessLookupError, OSError):
            continue
    return False


# ── Restore ───────────────────────────────────────────────────────────────────

def do_restore(data_dir: Path, backup_dir: Path) -> None:
    """Restore from a backup tarball, chosen interactively."""

    if _server_is_running():
        print("WARNING: The DocuBrowse server appears to be running.")
        print("Restoring while the server is active can cause data loss.")
        print("Stop the server first:  docubrowser stop")
        print()
        try:
            answer = input("Continue anyway? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(0)
        if answer not in ("y", "yes"):
            print("Aborted.")
            sys.exit(0)
        print()

    backups = _list_backups(backup_dir)

    if not backups:
        print(f"No backups found in {backup_dir}")
        sys.exit(1)

    # Present choices — newest last (default)
    print(f"Available backups in {backup_dir}:\n")
    for i, bak in enumerate(backups, 1):
        # Parse timestamp from filename
        stem = bak.stem.replace(".tar", "")  # strip .tar from .tar.gz stem
        ts_part = stem.replace("docubrowser_backup_", "")
        try:
            ts = datetime.strptime(ts_part, "%Y%m%d_%H%M%S")
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            ts_str = ts_part
        default_marker = "  [default]" if i == len(backups) else ""
        print(f"  {i}) {bak.name}  ({_fmt_size(bak)}, {ts_str}){default_marker}")

    print()
    default_choice = len(backups)

    try:
        raw = input(f"Restore which backup? [1-{len(backups)}, default={default_choice}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(0)

    if not raw:
        choice = default_choice
    else:
        try:
            choice = int(raw)
        except ValueError:
            print(f"Invalid choice: {raw}")
            sys.exit(1)

    if choice < 1 or choice > len(backups):
        print(f"Invalid choice: {choice}")
        sys.exit(1)

    selected = backups[choice - 1]
    print(f"\nRestoring from: {selected.name}")
    print(f"  Into: {data_dir}")

    # Safety: show what will be overwritten
    with tarfile.open(selected, "r:gz") as tar:
        members = tar.getnames()

    existing = [m for m in members if (data_dir / m).exists()]
    if existing:
        print(f"\n  Will overwrite {len(existing)} existing file(s):")
        for name in existing:
            print(f"    {name}")

    print()
    try:
        answer = input("Proceed? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(0)

    if answer not in ("y", "yes"):
        print("Aborted — no changes made.")
        sys.exit(0)

    # Extract — filter='data' rejects absolute paths, .., symlinks, and
    # special members (Python 3.12+).  Older Pythons don't have the filter
    # param; fall back to unfiltered extraction (our backups are self-created
    # and contain only plain files with simple names).
    with tarfile.open(selected, "r:gz") as tar:
        try:
            tar.extractall(path=str(data_dir), filter="data")
        except TypeError:
            # Python < 3.12 — no filter parameter
            tar.extractall(path=str(data_dir))

    print()
    for name in members:
        restored = data_dir / name
        if restored.exists():
            print(f"  Restored: {name} ({_fmt_size(restored)})")
        else:
            print(f"  WARNING: {name} — not found after extraction")

    print(f"\nRestore complete.  Data directory: {data_dir}")
    print("Restart the server to pick up the restored data.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Back up and restore DocuBrowse runtime data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Backs up: database, config, scan/ignore lists, blacklists.\n"
            "Keeps up to 3 backups; oldest is pruned automatically.\n"
            "\n"
            "A fresh install + restore yields a fully working system."
        ),
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument("--backup", action="store_true",
                       help="Create a backup of runtime data")
    group.add_argument("--restore", action="store_true",
                       help="Restore runtime data from a backup")
    p.add_argument("--db", metavar="PATH",
                   help="Path to database or data directory "
                        "(default: directory containing this script)")
    p.add_argument("--backup-dir", metavar="PATH",
                   help="Override backup storage directory "
                        f"(default: {BACKUP_DIR})")
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    _require_elevated()

    data_dir   = _resolve_data_dir(args.db)
    backup_dir = _resolve_backup_dir(args.backup_dir)

    if args.backup:
        do_backup(data_dir, backup_dir)
    elif args.restore:
        do_restore(data_dir, backup_dir)
    else:
        # Interactive — ask the user
        print("DocuBrowse Backup & Restore")
        print()
        print(f"  Data directory:   {data_dir}")
        print(f"  Backup directory: {backup_dir}")
        print()
        print("  1) Backup")
        print("  2) Restore")
        print()
        try:
            choice = input("Choose [1/2]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(0)

        if choice == "1":
            do_backup(data_dir, backup_dir)
        elif choice == "2":
            do_restore(data_dir, backup_dir)
        else:
            print(f"Invalid choice: {choice}")
            sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
