#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
Test for the sliding-window scan ETA (D-2). Run: python3 test_scan_eta.py
"""

import collections
import re

import scan_docs


def _eta_seconds(line: str) -> int:
    m = re.search(r"ETA (?:(\d+)m(\d+)s|(\d+)s)", line)
    return int(m[1]) * 60 + int(m[2]) if m[1] else int(m[3])


def test_eta_tracks_recent_rate():
    """1000 fast failures (0.01s each) then 100 slow files (10s each), 500 left
    of 1600: the windowed ETA reflects the slow rate (~5000s); the whole-run
    average is far lower."""
    clock = [0.0]
    real_time = scan_docs.time.time
    scan_docs.time.time = lambda: clock[0]
    try:
        window = collections.deque(maxlen=scan_docs._ETA_WINDOW)
        line = ""
        for done in range(1, 1101):
            clock[0] += 0.01 if done <= 1000 else 10.0
            line = scan_docs._progress_bar(done, 1600, 0.0, 0, window)
        plain = scan_docs._progress_bar(1100, 1600, 0.0, 0)
    finally:
        scan_docs.time.time = real_time
    assert 4900 <= _eta_seconds(line) <= 5100, line
    assert _eta_seconds(plain) < 1000, plain


if __name__ == "__main__":
    test_eta_tracks_recent_rate()
    print("ok  test_eta_tracks_recent_rate")
