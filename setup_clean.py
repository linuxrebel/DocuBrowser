#!/usr/bin/env python3
"""Clean setup: Remove old files and create fresh database with 100 documents."""

import os
import sqlite3
from pathlib import Path

# Clean up old files
print("Cleaning up old files...")
for pattern in ['docs.db', 'test_docs.db', 'test_*.db']:
    for f in Path('.').glob(pattern):
        f.unlink()
        print(f"  Removed: {f}")

for dir_name in ['test_pdfs_live', 'test_pdfs', 'test_docs']:
    dir_path = Path(dir_name)
    if dir_path.exists():
        import shutil
        shutil.rmtree(dir_path)
        print(f"  Removed: {dir_name}/")

print("\nCreating fresh database...")

# Create database
db = sqlite3.connect('./docs.db')
db.row_factory = sqlite3.Row

# Create schema
db.executescript('''
    CREATE TABLE documents (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL UNIQUE,
        size_bytes INTEGER, file_ext TEXT, title TEXT, author TEXT,
        description TEXT, content_snippet TEXT, created_at TEXT, modified_at TEXT,
        indexed_at TEXT, doc_type TEXT, updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE doc_tags (
        doc_id INTEGER, tag TEXT, source TEXT DEFAULT 'auto',
        FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE,
        UNIQUE(doc_id, tag)
    );
    CREATE TABLE doc_embeddings (
        doc_id INTEGER PRIMARY KEY, embedding BLOB, model TEXT,
        updated_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
    );
    CREATE VIRTUAL TABLE doc_fts USING fts5(
        name, title, description, content_snippet, tags,
        content='', content_rowid='rowid'
    );
    CREATE TABLE scan_log (
        id INTEGER PRIMARY KEY, scanned_at TEXT, docs_found INTEGER,
        docs_added INTEGER, docs_updated INTEGER
    );
''')

# Populate with 100 documents
topics = ['Database', 'API', 'Cloud', 'Security', 'Testing', 'DevOps', 'Microservices', 'ML', 'Storage', 'Networking']
descriptions = {
    'Database': 'Guide to database design, optimization, and administration. SQL, NoSQL, indexing.',
    'API': 'REST API design, authentication, rate limiting, and best practices.',
    'Cloud': 'Cloud architecture and deployment. AWS, Azure, GCP strategies.',
    'Security': 'Security best practices, threat modeling, cryptography, secure coding.',
    'Testing': 'Testing strategies: unit, integration, load testing, automation.',
    'DevOps': 'CI/CD pipelines, infrastructure as code, Docker, Kubernetes.',
    'Microservices': 'Microservices patterns, service discovery, distributed systems.',
    'ML': 'Machine learning fundamentals, model training, neural networks.',
    'Storage': 'Storage systems, object storage, backup and disaster recovery.',
    'Networking': 'Network protocols, load balancing, DNS, CDN, security.'
}

print("Inserting 100 documents...")
for i in range(1, 101):
    topic = topics[(i-1) % 10]
    name = f'doc_{i:03d}_{topic}.pdf'
    title = f'{topic} Guide #{i}'
    desc = descriptions[topic]
    
    # Insert document
    db.execute('''INSERT INTO documents 
        (name, path, size_bytes, file_ext, title, author, description, 
         content_snippet, doc_type, created_at, modified_at, indexed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), datetime('now'))''',
        (name, f'/docs/{name}', 1000+i*100, '.pdf', title, 'Team',
         desc, desc[:100] + '...', 'pdf'))
    
    # Add tags
    doc_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    for tag in ['pdf', topic.lower()]:
        db.execute('INSERT OR IGNORE INTO doc_tags (doc_id, tag, source) VALUES (?, ?, ?)',
                   (doc_id, tag, 'auto'))

db.commit()

# Verify
doc_count = db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
tag_count = db.execute('SELECT COUNT(DISTINCT tag) FROM doc_tags').fetchone()[0]
print(f"\n✓ Success!")
print(f"  Documents: {doc_count}")
print(f"  Unique tags: {tag_count}")
print(f"  Database: ./docs.db")
print(f"\nReady! Run: python3 doc_search.py ./docs.db 8643")
