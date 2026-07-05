#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
DocuBrowse e-book extractor.

Supported formats:
  .epub          — ebooklib + BeautifulSoup (pure Python, fast)
  .mobi / .azw3  — mobi package unpacks embedded EPUB → ebooklib;
                   falls back to ebook-convert (calibre) if mobi fails
  .azw           — same path; DRM-encrypted files are indexed with
                   metadata-only (title/author visible in search,
                   no body text) rather than blacklisted

Metadata strategy:
  All MOBI/AZW* formats run ebook-meta (calibre) first — it reads
  metadata from DRM-encrypted files that mobi.extract() cannot open.
  EPUB metadata comes from ebooklib's Dublin Core fields.

Dependencies (pip):
  ebooklib       pip install ebooklib
  beautifulsoup4 pip install beautifulsoup4
  mobi           pip install mobi

System dependency (already installed on this machine):
  calibre        sudo dnf install calibre   (provides ebook-meta, ebook-convert)
"""

import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import warnings
from pathlib import Path

_TEXT_LIMIT = 5000
_CALIBRE_TIMEOUT = 60   # seconds per file for ebook-convert


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
    """Return the first Dublin Core metadata value, or None."""
    items = book.get_metadata(namespace, tag)
    if items:
        val = items[0][0]
        return val.strip() if isinstance(val, str) else None
    return None


def _normalize_author(author: str) -> str:
    """Normalize 'Surname, Given' → 'Given Surname'. No-op for other forms."""
    if not author or ',' not in author or author.count(',') != 1:
        return author
    surname, _, given = author.partition(',')
    given = given.strip()
    surname = surname.strip()
    return f'{given} {surname}' if given else author


# ── Calibre helpers ───────────────────────────────────────────────────────────

def _calibre_metadata(file_path: str) -> dict:
    """
    Run ebook-meta to extract metadata.  Works even on DRM-encrypted files.
    Returns a partial result dict (title, author, subject, description).
    """
    meta = {'title': None, 'author': None, 'subject': None, 'description': ''}
    try:
        proc = subprocess.run(
            ['ebook-meta', file_path],
            capture_output=True, text=True, timeout=15,
        )
        for line in proc.stdout.splitlines():
            if ':' not in line:
                continue
            key, _, val = line.partition(':')
            key = key.strip().lower()
            val = val.strip()
            if not val:
                continue
            if key == 'title':
                meta['title'] = val
            elif key == 'author(s)':
                # Strip calibre's "[Surname, Given]" bracketed form, then normalize
                author = val.split('[')[0].strip() or val
                meta['author'] = _normalize_author(author)
            elif key in ('tags', 'series'):
                meta['subject'] = val
            elif key == 'publisher':
                meta['description'] = f'Publisher: {val}'
    except Exception:
        pass
    return meta


def _calibre_convert_to_text(file_path: str) -> str:
    """
    Run ebook-convert <file> <tmp>.txt and return the text content.
    Returns empty string on any failure (including DRM).
    """
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix='.txt')
        os.close(fd)
        proc = subprocess.run(
            ['ebook-convert', file_path, tmp_path],
            capture_output=True, text=True, timeout=_CALIBRE_TIMEOUT,
        )
        if proc.returncode == 0 and os.path.exists(tmp_path):
            with open(tmp_path, encoding='utf-8', errors='replace') as f:
                return f.read()
        return ''
    except Exception:
        return ''
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


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
        result['author']  = _normalize_author(_first_meta(book, 'DC', 'creator') or '')  or None
        result['subject'] = _first_meta(book, 'DC', 'subject')

        # Pull text from spine items; stop once we have enough
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
    Extraction pipeline for MOBI/AZW/AZW3:

    1. ebook-meta (calibre) — get metadata; works even for DRM files
    2. mobi.extract()       — unpack embedded EPUB or HTML; fast path
    3. ebook-convert        — fallback if mobi package fails
    4. Metadata-only index  — if text extraction fails (e.g. DRM), still
                              index the file so title/author are searchable
    """
    result = _make_result(doc_type='mobi')

    # Step 1: Metadata via calibre (always; works on DRM files)
    meta = _calibre_metadata(file_path)
    result.update({k: v for k, v in meta.items() if v})

    # Step 2: Text via mobi package
    tempdir = None
    try:
        import mobi
        _sink = io.StringIO()
        with contextlib.redirect_stdout(_sink), contextlib.redirect_stderr(_sink):
            tempdir, main_file = mobi.extract(file_path)

        main_path = Path(main_file)
        ext = main_path.suffix.lower()

        if ext == '.epub':
            inner = _extract_epub(str(main_path), doc_type='mobi')
            # Prefer calibre metadata if ebooklib got nothing
            if not inner.get('title') and result.get('title'):
                inner['title'] = result['title']
            if not inner.get('author') and result.get('author'):
                inner['author'] = result['author']
            inner['doc_type'] = 'mobi'
            return inner

        else:
            # mobi7 raw HTML
            html = main_path.read_text(encoding='utf-8', errors='replace')
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            if not result['title']:
                t = soup.find('title')
                result['title'] = t.get_text(strip=True) if t else None
            body = soup.get_text(' ', strip=True)
            result['text']    = body[:_TEXT_LIMIT]
            result['snippet'] = body[:500]
            result['success'] = bool(body)
            if not result['success']:
                result['error'] = 'No text in mobi7 HTML'
            return result

    except Exception as mobi_err:
        # Step 3: Fallback to ebook-convert
        text = _calibre_convert_to_text(file_path)
        if text.strip():
            result['text']    = text[:_TEXT_LIMIT]
            result['snippet'] = text[:500]
            result['success'] = True
            result['error']   = None
            return result

        # Step 4: Metadata-only index (DRM or unreadable)
        # Mark success=True so the file IS indexed (title/author searchable),
        # but leave text empty so FTS won't match body content.
        drm = 'encrypted' in str(mobi_err).lower() or 'drm' in str(mobi_err).lower()
        result['success']     = True   # index it — metadata is still useful
        result['text']        = ''
        result['snippet']     = ''
        result['description'] = '[DRM-encrypted — text not searchable]' if drm else \
                                f'[Extraction failed: {mobi_err}]'
        return result

    finally:
        if tempdir:
            shutil.rmtree(tempdir, ignore_errors=True)
