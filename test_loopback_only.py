# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""FOSS is loopback-only: no remote-access path exists.

Guards the removal of the DOCUBROWSE_TRUSTED_CIDRS / ALLOWED_HOSTS escape
hatch (see DECISIONS D-28). Run: python3 -m pytest test_loopback_only.py -v
"""
import ipaddress
import os

import doc_search


def test_loopback_addrs_accepted():
    for ip in ("127.0.0.1", "127.0.1.1", "127.255.255.254", "::1"):
        assert doc_search._client_loopback(ipaddress.ip_address(ip)), ip


def test_nonloopback_addrs_refused():
    for ip in ("10.0.0.5", "192.168.1.10", "172.17.0.2", "8.8.8.8", "::2"):
        assert not doc_search._client_loopback(ipaddress.ip_address(ip)), ip


def test_is_loopback_hostnames():
    assert doc_search._is_loopback("localhost")
    assert doc_search._is_loopback("127.0.0.1")
    assert doc_search._is_loopback("::1")
    assert not doc_search._is_loopback("docubrowse")
    assert not doc_search._is_loopback("evil.example.com")
    assert not doc_search._is_loopback("192.168.1.1")


def test_trusted_cidr_env_is_inert():
    # The remote escape hatch is gone: setting the old env vars must do
    # nothing. The symbols that implemented it no longer exist.
    os.environ["DOCUBROWSE_TRUSTED_CIDRS"] = "10.0.0.0/24"
    os.environ["DOCUBROWSE_ALLOWED_HOSTS"] = "evil.example.com"
    try:
        for gone in ("_TRUSTED_CIDRS", "_ALLOWED_HOSTS", "_parse_trusted_cidrs",
                     "_parse_allowed_hosts", "_client_trusted",
                     "_is_private_trusted_peer", "_hostname_allowed"):
            assert not hasattr(doc_search, gone), gone
        # A non-loopback peer is still refused regardless of the env vars.
        assert not doc_search._client_loopback(ipaddress.ip_address("10.0.0.5"))
    finally:
        del os.environ["DOCUBROWSE_TRUSTED_CIDRS"]
        del os.environ["DOCUBROWSE_ALLOWED_HOSTS"]
