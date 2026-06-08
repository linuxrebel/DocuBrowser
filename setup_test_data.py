#!/usr/bin/env python3
"""
Setup script: Generate 100 test PDFs and populate database.
Usage: python3 setup_test_data.py
"""

import os
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from pathlib import Path
from pdf_extractor import extract_pdf
from docubrowse_db import get_db
import sqlite3

def create_test_pdfs():
    """Generate 100 realistic test PDFs."""
    os.makedirs('./test_pdfs_live', exist_ok=True)

    topics = ['Database', 'API', 'Cloud', 'Security', 'Testing',
              'DevOps', 'Microservices', 'Machine Learning', 'Storage', 'Networking']

    print("Creating 100 test PDFs...")
    for i in range(100):
        topic = topics[i % 10]
        filename = f'./test_pdfs_live/test_{i+1:03d}_{topic}.pdf'

        c = canvas.Canvas(filename, pagesize=letter)
        c.drawString(50, 750, f'{topic} Document {i+1}')
        c.drawString(50, 730, f'This is a comprehensive guide to {topic}.')
        c.drawString(50, 710, f'Key concepts, best practices, and implementation details.')
        c.drawString(50, 690, f'Document version {i+1} - {topic} Series')
        c.showPage()
        c.save()

        if (i+1) % 25 == 0:
            print(f"  ✓ Created {i+1}/100 PDFs")

    print("✓ All 100 test PDFs created\n")

def populate_database():
    """Extract metadata from PDFs and populate database."""
    db_path = './docs.db'
    db = get_db(db_path)

    print("Extracting metadata and populating database...")

    pdf_dir = Path('./test_pdfs_live')
    pdf_files = sorted(pdf_dir.glob('*.pdf'))

    added = 0
    failed = 0

    for pdf_file in pdf_files:
        try:
            result = extract_pdf(str(pdf_file))

            if result['success']:
                # Insert into database
                db.execute('''
                    INSERT OR REPLACE INTO documents
                    (name, path, size_bytes, file_ext, title, author, description,
                     content_snippet, doc_type, created_at, modified_at, indexed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), datetime('now'))
                ''', (
                    pdf_file.name,
                    str(pdf_file),
                    pdf_file.stat().st_size,
                    '.pdf',
                    result.get('title', pdf_file.name),
                    result.get('author', ''),
                    result.get('description', ''),
                    result.get('content_snippet', ''),
                    'pdf',
                ))

                # Add auto-tags
                tags = ['pdf', pdf_file.stem.split('_')[-1].lower()]
                for tag in tags:
                    db.execute('''
                        INSERT OR IGNORE INTO doc_tags (doc_id, tag, source)
                        VALUES ((SELECT id FROM documents WHERE path = ?), ?, 'auto')
                    ''', (str(pdf_file), tag))

                added += 1
                if added % 25 == 0:
                    print(f"  ✓ Processed {added}/100 PDFs")
            else:
                failed += 1
        except Exception as e:
            failed += 1
            print(f"  ✗ Error processing {pdf_file.name}: {e}")

    db.commit()
    db.close()

    print(f"✓ Database populated: {added} PDFs added, {failed} failed\n")

def main():
    print("=" * 60)
    print("DocuBrowse Test Data Setup")
    print("=" * 60 + "\n")

    create_test_pdfs()
    populate_database()

    print("=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Start server: python3 doc_search.py ./docs.db 8643")
    print("  2. Open browser: http://localhost:8643")
    print("  3. Search for: 'database', 'api', 'cloud', etc.")
    print("\nDatabase location: ./docs.db")
    print("Test PDFs location: ./test_pdfs_live/")
    print("=" * 60 + "\n")

if __name__ == '__main__':
    main()
