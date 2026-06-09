#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
PDF extractor module for DocuBrowse.
Handles PDF text extraction, metadata parsing, and error handling.
"""

import io
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

# Try importing pdfplumber, fall back to pypdf if unavailable
HAS_PDFPLUMBER = False
HAS_PYPDF = False
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    try:
        import PyPDF2 as pypdf
        HAS_PYPDF = True
    except ImportError:
        pass


MAX_PAGES = 150   # cap per-PDF to bound memory use and extraction time


def extract_pdf(pdf_path: str) -> Dict:
    """
    Extract text and metadata from a PDF file.

    Args:
        pdf_path: Path to PDF file

    Returns:
        Dictionary with keys:
        - title: str (from PDF metadata or filename)
        - author: str or None
        - text: str (extracted text, max 5000 chars)
        - snippet: str (first 500 chars)
        - page_count: int
        - success: bool
        - error: str or None (if success=False)
    """
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        return {
            'title': pdf_path.stem,
            'author': None,
            'text': '',
            'snippet': '',
            'page_count': 0,
            'success': False,
            'error': f'File not found: {pdf_path}'
        }

    result = {
        'title':   pdf_path.stem,
        'author':  None,
        'subject': None,
        'text':    '',
        'snippet': '',
        'page_count': 0,
        'success': False,
        'error':   None
    }

    try:
        if HAS_PDFPLUMBER:
            return _extract_pdfplumber(pdf_path, result)
        elif HAS_PYPDF:
            return _extract_pypdf(pdf_path, result)
        else:
            result['error'] = 'No PDF library available (install pdfplumber or PyPDF2)'
            return result
    except Exception as e:
        result['error'] = f'Extraction failed: {str(e)}'
        return result


def _extract_pdfplumber(pdf_path: Path, result: Dict) -> Dict:
    """Extract using pdfplumber (preferred method)."""
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            result['page_count'] = len(pdf.pages)

            # Extract metadata
            if pdf.metadata:
                result['title']   = pdf.metadata.get('Title')   or result['title']
                result['author']  = pdf.metadata.get('Author')  or None
                result['subject'] = pdf.metadata.get('Subject') or None

            # Extract text — capped at MAX_PAGES to bound memory and time
            text_parts = []
            for page in pdf.pages[:MAX_PAGES]:
                try:
                    text = page.extract_text() or ''
                    if text:
                        text_parts.append(text)
                except Exception:
                    pass

            full_text = '\n'.join(text_parts)
            # Limit to 5000 chars to keep embeddings manageable
            result['text'] = full_text[:5000]
            result['snippet'] = full_text[:500]
            result['success'] = bool(result['text'])
            if not result['success']:
                pages = result['page_count']
                result['error'] = (
                    f"no text extracted from {pages} page(s) "
                    f"— likely scanned/image-only or DRM-protected PDF"
                )

            return result
    except Exception as e:
        result['error'] = f'pdfplumber error: {str(e)}'
        return result


def _extract_pypdf(pdf_path: Path, result: Dict) -> Dict:
    """Fallback extraction using PyPDF2."""
    try:
        with open(pdf_path, 'rb') as f:
            reader = pypdf.PdfReader(f)
            result['page_count'] = len(reader.pages)

            # Extract metadata
            if reader.metadata:
                result['title']   = reader.metadata.get('/Title')   or result['title']
                result['author']  = reader.metadata.get('/Author')  or None
                result['subject'] = reader.metadata.get('/Subject') or None

            # Extract text — capped at MAX_PAGES
            text_parts = []
            for page in reader.pages[:MAX_PAGES]:
                try:
                    text = page.extract_text() or ''
                    if text:
                        text_parts.append(text)
                except Exception:
                    pass

            full_text = '\n'.join(text_parts)
            result['text'] = full_text[:5000]
            result['snippet'] = full_text[:500]
            result['success'] = bool(result['text'])
            if not result['success']:
                pages = result['page_count']
                result['error'] = (
                    f"no text extracted from {pages} page(s) "
                    f"— likely scanned/image-only or DRM-protected PDF"
                )

            return result
    except Exception as e:
        result['error'] = f'PyPDF2 error: {str(e)}'
        return result


def generate_keywords(text: str, title: str = '', max_keywords: int = 10) -> list:
    """
    Generate keywords from PDF text (simple heuristic).

    Args:
        text: Extracted text
        title: Document title
        max_keywords: Maximum keywords to return

    Returns:
        List of keywords (lowercase)
    """
    keywords = set()

    # Extract title words
    if title:
        for word in title.lower().split():
            if len(word) > 3:
                keywords.add(word.strip('.,;:'))

    # Extract common noun-like words (simple heuristic: all-caps words, frequent words)
    if text:
        words = text.lower().split()
        word_freq = {}
        for word in words:
            clean = word.strip('.,;:()[]{}')
            if 3 <= len(clean) <= 20 and clean.isalpha():
                word_freq[clean] = word_freq.get(clean, 0) + 1

        # Get top frequent words
        for word, freq in sorted(word_freq.items(), key=lambda x: x[1], reverse=True):
            if freq >= 3 and word not in ['the', 'and', 'for', 'that', 'with', 'from', 'this']:
                keywords.add(word)
                if len(keywords) >= max_keywords:
                    break

    return sorted(list(keywords))


# Test harness
if __name__ == '__main__':
    # Test with a real PDF if provided as argument
    if len(sys.argv) > 1:
        pdf_file = sys.argv[1]
        print(f"Extracting from: {pdf_file}")
        result = extract_pdf(pdf_file)
        print(f"  Title:   {result['title']}")
        print(f"  Author:  {result['author']}")
        print(f"  Subject: {result['subject']}")
        print(f"  Pages: {result['page_count']}")
        print(f"  Success: {result['success']}")
        if result['error']:
            print(f"  Error: {result['error']}")
        print(f"  Text length: {len(result['text'])} chars")
        print(f"  Snippet (first 200 chars):")
        print(f"    {result['snippet'][:200]}...")
    else:
        print("PDF Extractor module loaded successfully")
        print(f"pdfplumber available: {HAS_PDFPLUMBER}")
        print(f"PyPDF2 available: {HAS_PYPDF}")
        print("\nUsage: python3 pdf_extractor.py <pdf_file>")
