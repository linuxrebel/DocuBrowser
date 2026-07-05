#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
Populate database with 100 test documents.
Run: python3 populate_db.py
"""

from docubrowse_db import get_db
import sys

def main():
    print("=" * 70)
    print("DocuBrowse: Populate Test Database")
    print("=" * 70)
    print()

    db = get_db('./du-docs.db')

    topics = [
        'Database', 'API', 'Cloud', 'Security', 'Testing',
        'DevOps', 'Microservices', 'Machine Learning', 'Storage', 'Networking'
    ]

    descriptions = {
        'Database': 'Comprehensive guide to database design, optimization, and administration. Covers SQL, NoSQL, indexing, and scaling strategies.',
        'API': 'Complete reference for REST API design, authentication, rate limiting, and best practices for building scalable APIs.',
        'Cloud': 'Cloud architecture and deployment strategies. AWS, Azure, GCP comparison and multi-cloud deployment patterns.',
        'Security': 'Security best practices, threat modeling, cryptography, and secure coding guidelines for modern applications.',
        'Testing': 'Testing strategies including unit tests, integration tests, load testing, and test automation frameworks.',
        'DevOps': 'DevOps practices, CI/CD pipelines, infrastructure as code, and containerization with Docker and Kubernetes.',
        'Microservices': 'Microservices architecture patterns, service discovery, circuit breakers, and distributed system design.',
        'Machine Learning': 'Machine learning fundamentals, model training, neural networks, and production ML deployment strategies.',
        'Storage': 'Storage systems, object storage, distributed storage, backup and disaster recovery solutions.',
        'Networking': 'Network fundamentals, protocols, load balancing, DNS, CDN, and network security.'
    }

    print("Creating 100 test documents...")
    print()

    added = 0
    failed = 0

    for i in range(1, 101):
        try:
            topic = topics[(i-1) % 10]
            name = f'doc_{i:03d}_{topic}.pdf'
            path = f'/home/james/git/AI/DocuBrowse/test_docs/{name}'
            title = f'{topic} Guide - Document {i}'
            description = descriptions[topic]
            snippet = description[:200] + "..."

            # Insert document
            db.execute('''
                INSERT INTO documents
                (name, path, size_bytes, file_ext, title, author, description,
                 content_snippet, doc_type, created_at, modified_at, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), datetime('now'))
            ''', (name, path, 5000 + i*100, '.pdf', title, 'Technical Team',
                  description, snippet, 'pdf'))

            # Get the inserted document ID
            doc_id = db.execute(
                'SELECT id FROM documents WHERE name = ?', (name,)
            ).fetchone()[0]

            # Add tags
            tags = ['pdf', topic.lower(), 'test-data']
            for tag in tags:
                db.execute(
                    'INSERT OR IGNORE INTO doc_tags (doc_id, tag, source) VALUES (?, ?, ?)',
                    (doc_id, tag, 'auto')
                )

            added += 1

            # Progress indicator
            if added % 10 == 0:
                print(f"  ✓ Created {added}/100 documents")

        except Exception as e:
            failed += 1
            print(f"  ✗ Error on document {i}: {e}")

    # Commit all changes
    db.commit()

    # Verify population
    doc_count = db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
    tag_count = db.execute('SELECT COUNT(DISTINCT tag) FROM doc_tags').fetchone()[0]

    print()
    print("=" * 70)
    print("Population Complete!")
    print("=" * 70)
    print(f"Documents added: {doc_count}")
    print(f"Unique tags: {tag_count}")
    print(f"Database file: ./du-docs.db")
    print()
    print("Next steps:")
    print("  1. python3 doc_search.py ./du-docs.db 8643")
    print("  2. Open http://localhost:8643 in your browser")
    print("  3. Try searching: 'database', 'api', 'cloud', etc.")
    print()

    return 0 if doc_count > 0 else 1

if __name__ == '__main__':
    sys.exit(main())
