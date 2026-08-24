#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
Regression test for the argparse subparser clobber: global options placed
BEFORE the subcommand (e.g. `docubrowser --db PATH start`) must not be reset to
None by the subparser's own --db/--port defaults. Both positions must yield the
same parsed value. Run: python3 test_docubrowser_args.py
"""

from docubrowser import build_parser


def _db(argv):
    return getattr(build_parser().parse_args(argv), "db", None)


def _port(argv):
    return getattr(build_parser().parse_args(argv), "port", None)


def main():
    """--db/--port must survive in either position for db-taking subcommands."""
    for cmd in ("start", "restart", "status", "scan", "rescan", "embed"):
        # Global position (before the subcommand) — the form that regressed.
        assert _db(["--db", "/REAL/db", cmd]) == "/REAL/db", \
            f"global --db dropped for {cmd!r}"
        # Subcommand position (after) — already worked; must keep working.
        assert _db([cmd, "--db", "/REAL/db"]) == "/REAL/db", \
            f"subcommand --db dropped for {cmd!r}"

    # --port likewise, on a subcommand that takes it.
    assert _port(["--port", "8697", "start"]) == 8697, "global --port dropped for start"
    assert _port(["start", "--port", "8697"]) == 8697, "subcommand --port dropped for start"

    # Neither given → attribute still present and None (cmd_start relies on this).
    assert _db(["start"]) is None, "args.db should default to None when unset"

    print("PASS: --db/--port honored in both global and subcommand position")


if __name__ == "__main__":
    main()
