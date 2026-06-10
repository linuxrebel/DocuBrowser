#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
DocuBrowse e-book extractor.

Supports:
  .epub          — ebooklib + BeautifulSoup
  .mobi / .azw3  — mobi package unpacks an embedded EPUB → ebooklib
  .azw           — same path; fails gracefully if DRM-encrypted

Dependencies (pip):
  ebooklib       pip install ebooklib
  beautifulsoup4 pip install beautifulsoup4
  mobi           pip install mobi

DRM note: AZW files downloaded from Amazon are often DRM-encrypted.
mobi.extract() will raise "Book is encrypted"; the file is auto-blacklisted.
Strip DRM first (e.g. with DeDRM tools) if you want these indexed.
"""

import shutil
import warnings
from pathlib import Path

_TEXT_LIMIT = 5000


def extract_ebook(file_path: str) -> dict:
    """Dispatch to the appropriate extractor based on file extension."""
    ext = Path(file_path).suffix.lower()
    if ext == '.epub':
        return _extract_epub(file_path)
    elif ext in ('.mobi', '.azw', '.azw3'):
        return _extract_mobi(file_path)
    return _make_result(error=f'Unsupported format: {ext}')


# ── Shared helpers ────────────────────────────────────────────────────────────

def _make_result(doc_type='ebook', error=None):
    return {
        'title':       None,
        'author':      None,
        'subject':     None,
        'description': '',
        'text':        '',
        'snippet':     '',
        'doc_type':    doc_type,
        'success':     False,
        'error':       error,
    }


def _html_to_text(html_bytes_or_str) -> str:
    """Strip HTML tags; return plain text."""
    from bs4 import BeautifulSoup
    if isinstance(html_bytes_or_str, bytes):
        html_bytes_or_str = html_bytes_or_str.decode('utf-8', errors='replace')
    return BeautifulSoup(html_bytes_or_str, 'html.parser').get_text(' ', strip=True)


def _first_meta(book, namespace, tag):
    """Return the first value for a Dublin Core metadata tag, or None."""
    items = book.get_metadata(namespace, tag)
    if items:
        val = items[0][0]
        return val.strip() if isinstance(val, str) else None
    return None


# ── EPUB ──────────────────────────────────────────────────────────────────────

def _extract_epub(file_path: str, doc_type: str = 'epub') -> dict:
    result = _make_result(doc_type=doc_type)
    try:
        import ebooklib
        from ebooklib import epub

        # ebooklib emits a FutureWarning about rootfile XPath — suppress it
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            book = epub.read_epub(file_path, options={'ignore_ncx': True})

        result['title']   = _first_meta(book, 'DC', 'title')
        result['author']  = _first_meta(book, 'DC', 'creator')
        result['subject'] = _first_meta(book, 'DC', 'subject')

        # Pull text from spine items; stop once we have enough chars
        parts = []
        total = 0
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            if total >= _TEXT_LIMIT:
                break
            try:
                t = _html_to_text(item.get_content())
                if t:
                    parts.append(t)
                    total += len(t)
            except Exception:
                pass

        full_text         = '\n'.join(parts)
        result['text']    = full_text[:_TEXT_LIMIT]
        result['snippet'] = full_text[:500]
        result['success'] = True
        return result

    except Exception as exc:
        result['error'] = str(exc)
        return result


# ── MOBI / AZW / AZW3 ────────────────────────────────────────────────────────

def _extract_mobi(file_path: str) -> dict:
    """
    Use the mobi package to unpack the file into a temp directory, then:
    - If it extracted an .epub (KF8 / modern format): process with _extract_epub
    - If it extracted .html (older mobi7 format): parse with BeautifulSoup
    Always clean up the temp directory.
    """
    result = _make_result(doc_type='mobi')
    tempdir = None
    try:
        import mobi
        import contextlib, io

        # mobi.extract() prints EXTH warnings to both stdout and stderr;
        # suppress both so nothing bleeds into the progress bar.
        _sink = io.StringIO()
        with contextlib.redirect_stdout(_sink), contextlib.redirect_stderr(_sink):
            tempdir, main_file = mobi.extract(file_path)

        main_path = Path(main_file)
        ext = main_path.suffix.lower()

        if ext == '.epub':
            # Modern KF8 format: mobi unpacked an embedded EPUB
            inner = _extract_epub(str(main_path), doc_type='mobi')
            return inner

        else:
            # Older mobi7: raw HTML file
            html = main_path.read_text(encoding='utf-8', errors='replace')
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')

            title_tag = soup.find('title')
            result['title'] = title_tag.get_text(strip=True) if title_tag else None

            body_text         = soup.get_text(' ', strip=True)
            result['text']    = body_text[:_TEXT_LIMIT]
            result['snippet'] = body_text[:500]
            result['success'] = bool(body_text)
            if not result['success']:
                result['error'] = 'No text extracted from mobi HTML'
            return result

    except Exception as exc:
        result['error'] = str(exc)
        return result

    finally:
        if tempdir:
            shutil.rmtree(tempdir, ignore_errors=True)
