#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
DocuBrowse .eml extractor.

Parses RFC 822 / MIME email messages using the Python stdlib ``email``
package.  No third-party dependency.

Field mapping:
    Subject             → title
    From                → author
    To (+ Date + Cc)    → subject   (short one-liner)
    Body (text/plain    → text
      preferred; else
      text/html tag-
      stripped)

Attachments are ignored — only their filenames are appended to the body
so they're keyword-searchable.

Returns a dict with the same shape as pdf_extractor.extract_pdf() so
scan_docs._extract_file() can handle it uniformly.
"""

from __future__ import annotations

import email
import email.policy
import html as html_mod
import re
from email.utils import getaddresses, parseaddr


_TEXT_LIMIT    = 5000
_SNIPPET_LIMIT = 500


def _empty_result() -> dict:
    return {
        "title":       None,
        "author":      None,
        "subject":     None,
        "description": "",
        "text":        "",
        "snippet":     "",
        "doc_type":    "eml",
        "success":     False,
        "error":       None,
    }


def _decode_header(raw) -> str:
    """Turn an email header (possibly None, possibly a Header object with
    RFC 2047 encoded-words) into a plain string."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    try:
        return str(raw).strip()
    except (UnicodeError, ValueError):
        return ""


def _format_addr(raw: str) -> str:
    """Format a From/To address for display: ``Name <addr>`` → ``Name (addr)``."""
    if not raw:
        return ""
    parts = []
    for name, addr in getaddresses([raw]):
        if name and addr:
            parts.append(f"{name} <{addr}>")
        elif addr:
            parts.append(addr)
        elif name:
            parts.append(name)
    return ", ".join(parts)


def _first_addr(raw: str) -> str | None:
    """Return the plain address portion of the first From/To entry."""
    if not raw:
        return None
    name, addr = parseaddr(raw)
    return (name or addr or "").strip() or None


_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)


def _strip_html(text: str) -> str:
    """Best-effort HTML → plain text for text/html body parts."""
    if not text:
        return ""
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ",
                  text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ",
                  text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub(" ", text)
    text = html_mod.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _walk_body(msg) -> tuple[str, list[str]]:
    """Return (body_text, attachment_filenames)."""
    plain_parts: list[str] = []
    html_parts: list[str]  = []
    attachments: list[str] = []

    for part in msg.walk():
        ctype = part.get_content_type()
        disposition = (part.get("Content-Disposition") or "").lower()

        if "attachment" in disposition or part.get_filename():
            fname = part.get_filename()
            if fname:
                attachments.append(fname)
            continue

        if ctype == "text/plain":
            try:
                plain_parts.append(part.get_content())
            except (LookupError, KeyError, UnicodeError, ValueError):
                try:
                    payload = part.get_payload(decode=True) or b""
                    plain_parts.append(payload.decode(
                        part.get_content_charset() or "utf-8",
                        errors="replace"))
                except (LookupError, UnicodeError, ValueError):
                    pass
        elif ctype == "text/html":
            try:
                html_parts.append(part.get_content())
            except (LookupError, KeyError, UnicodeError, ValueError):
                try:
                    payload = part.get_payload(decode=True) or b""
                    html_parts.append(payload.decode(
                        part.get_content_charset() or "utf-8",
                        errors="replace"))
                except (LookupError, UnicodeError, ValueError):
                    pass

    # Prefer plain text; fall back to stripped HTML
    if plain_parts:
        body = "\n\n".join(p.strip() for p in plain_parts if p and p.strip())
    elif html_parts:
        body = "\n\n".join(_strip_html(p) for p in html_parts if p)
    else:
        body = ""

    return body, attachments


def extract_eml(file_path: str) -> dict:
    """Extract text + metadata from an .eml file.

    Returns:
        dict with keys: success, title, author, subject, description,
                        text (up to 5000 chars), snippet (up to 500 chars),
                        doc_type, error
    """
    result = _empty_result()
    try:
        with open(file_path, "rb") as fh:
            msg = email.message_from_binary_file(
                fh, policy=email.policy.default)

        subj = _decode_header(msg.get("Subject"))
        from_hdr = _decode_header(msg.get("From"))
        to_hdr   = _decode_header(msg.get("To"))
        cc_hdr   = _decode_header(msg.get("Cc"))
        date_hdr = _decode_header(msg.get("Date"))

        result["title"]   = subj or None
        result["author"]  = _first_addr(from_hdr)

        # Cram To/Cc/Date into the subject field for a searchable header line
        parts = []
        if to_hdr:
            parts.append(f"To: {_format_addr(to_hdr)}")
        if cc_hdr:
            parts.append(f"Cc: {_format_addr(cc_hdr)}")
        if date_hdr:
            parts.append(f"Date: {date_hdr}")
        result["subject"] = " | ".join(parts) or None

        body, attachments = _walk_body(msg)

        # Prepend a compact header block so search hits on From/To/Subject work
        header_block_lines = []
        if from_hdr:
            header_block_lines.append(f"From: {_format_addr(from_hdr)}")
        if to_hdr:
            header_block_lines.append(f"To: {_format_addr(to_hdr)}")
        if cc_hdr:
            header_block_lines.append(f"Cc: {_format_addr(cc_hdr)}")
        if subj:
            header_block_lines.append(f"Subject: {subj}")
        if date_hdr:
            header_block_lines.append(f"Date: {date_hdr}")

        combined = "\n".join(header_block_lines)
        if body:
            combined += "\n\n" + body
        if attachments:
            combined += "\n\nAttachments: " + ", ".join(attachments)

        # NUL bytes are legal in a MIME body but break FTS5 tokenisation —
        # the tokeniser treats \x00 as end-of-token, silently dropping the
        # rest of the field.  Replace with a space so text stays searchable.
        combined = combined.replace("\x00", " ")

        result["description"] = combined[:500]
        result["text"]    = combined[:_TEXT_LIMIT]
        result["snippet"] = combined[:_SNIPPET_LIMIT]
        result["success"] = True
        return result

    except (OSError, ValueError, LookupError, UnicodeError) as exc:
        result["error"] = str(exc)
        return result
