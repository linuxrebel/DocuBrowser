#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
Generate synthetic test PDFs for E2E testing.
Creates 100 PDFs with varying content, lengths, and topics.
"""

import sys
from pathlib import Path

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False


# Sample content templates
TOPICS = [
    ("machine learning", "Training neural networks with deep learning frameworks. Discusses gradient descent, backpropagation, and optimization algorithms."),
    ("database systems", "SQL and NoSQL database design patterns. Covers indexing, query optimization, and transaction management."),
    ("cloud computing", "Infrastructure as a service, Platform as a service, Software as a service. AWS, Azure, Google Cloud comparison."),
    ("software architecture", "Design patterns, microservices, monoliths. API design, scalability considerations."),
    ("cybersecurity", "Threat modeling, vulnerability assessment, penetration testing. Security best practices and compliance."),
    ("data science", "Statistical analysis, data visualization, predictive modeling. Python libraries and tools."),
    ("devops", "Continuous integration, continuous deployment, infrastructure automation. Docker, Kubernetes, CI/CD pipelines."),
    ("web development", "Frontend frameworks, backend technologies, full-stack development. HTML, CSS, JavaScript."),
    ("mobile development", "iOS and Android app development. Cross-platform solutions and native development."),
    ("artificial intelligence", "Machine learning, deep learning, natural language processing. AI applications and ethics."),
]

SAMPLE_PARAGRAPHS = {
    "machine learning": [
        "Neural networks are computing systems inspired by biological neural networks. They consist of interconnected nodes called neurons.",
        "Deep learning uses multiple layers of artificial neural networks to learn from data. It has revolutionized computer vision and NLP.",
        "Gradient descent is an optimization algorithm used to train neural networks. It iteratively adjusts weights to minimize loss.",
        "Backpropagation is the primary algorithm for training deep neural networks. It computes gradients of the loss function.",
        "Convolutional neural networks are specialized for processing grid-like data such as images. They use convolutional layers.",
        "Recurrent neural networks are designed for sequential data like time series and natural language. They have memory units.",
    ],
    "database systems": [
        "A database is an organized collection of structured data stored and accessed electronically. It provides efficient data retrieval.",
        "SQL is the standard language for managing relational databases. It supports CREATE, READ, UPDATE, DELETE operations.",
        "Indexing improves query performance by reducing the amount of data to be scanned. B-tree and hash indexes are common.",
        "Database normalization reduces data redundancy and improves data integrity. Normal forms include 1NF, 2NF, 3NF, BCNF.",
        "Transaction management ensures database consistency. ACID properties guarantee reliability of database transactions.",
        "Query optimization analyzes execution plans and uses indexes to execute queries efficiently. Query cost estimation is crucial.",
    ],
    "cloud computing": [
        "Cloud computing delivers computing services over the internet. Infrastructure, platforms, and software are delivered as services.",
        "Infrastructure as a Service provides virtualized computing resources over the internet. Users can rent servers, storage, networking.",
        "Platform as a Service provides a development environment for building and deploying web applications. No infrastructure management needed.",
        "Software as a Service delivers applications over the internet on subscription basis. Users access via web browsers.",
        "Cloud providers include Amazon Web Services, Microsoft Azure, Google Cloud Platform. Each has unique strengths and pricing.",
        "Scalability is a key advantage of cloud computing. Applications can scale up or down based on demand automatically.",
    ],
}


def create_test_pdf(output_path: str, doc_number: int, topic: str, num_pages: int = 1):
    """
    Create a single test PDF.

    Args:
        output_path: Path to save PDF
        doc_number: Document number (1-100)
        topic: Topic name
        num_pages: Number of pages to generate
    """
    if not HAS_REPORTLAB:
        print(f"ERROR: reportlab not installed. Install with: pip install reportlab")
        return False

    try:
        doc = SimpleDocTemplate(output_path, pagesize=letter)
        story = []

        # Add title
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            textColor=colors.HexColor('#157a2b'),
            spaceAfter=30,
        )

        title = f"Document #{doc_number}: {topic.title()}"
        story.append(Paragraph(title, title_style))
        story.append(Spacer(1, 0.2 * inch))

        # Add content
        paragraphs = SAMPLE_PARAGRAPHS.get(topic, SAMPLE_PARAGRAPHS["machine learning"])
        body_style = styles['BodyText']

        for page_num in range(num_pages):
            if page_num > 0:
                story.append(Spacer(1, 0.1 * inch))
                story.append(Paragraph(f"<b>Page {page_num + 1}</b>", styles['Heading2']))
                story.append(Spacer(1, 0.1 * inch))

            # Add 3-5 paragraphs per page
            num_paras = 3 + (doc_number % 3)
            for i in range(num_paras):
                para_text = paragraphs[(page_num * num_paras + i) % len(paragraphs)]
                story.append(Paragraph(para_text, body_style))
                story.append(Spacer(1, 0.1 * inch))

        # Build PDF
        doc.build(story)
        return True

    except Exception as e:
        print(f"ERROR creating PDF: {e}")
        return False


def generate_test_pdfs(output_dir: str, num_pdfs: int = 100):
    """
    Generate a set of test PDFs.

    Args:
        output_dir: Directory to save PDFs
        num_pdfs: Number of PDFs to generate
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating {num_pdfs} test PDFs to {output_dir}")
    print()

    created = 0
    failed = 0

    for i in range(1, num_pdfs + 1):
        # Vary topic and page count
        topic_idx = (i - 1) % len(TOPICS)
        topic, _ = TOPICS[topic_idx]

        # Vary page count: most 1-5 pages, some 10-50 pages
        if i % 10 == 0:
            num_pages = 10 + (i % 20)  # 10-29 pages for every 10th doc
        elif i % 5 == 0:
            num_pages = 5 + (i % 5)  # 5-9 pages
        else:
            num_pages = 1 + (i % 4)  # 1-4 pages

        filename = f"doc_{i:03d}_{topic.replace(' ', '_')}.pdf"
        filepath = output_dir / filename

        print(f"[{i}/{num_pdfs}] {filename} ({num_pages} pages)...", end=' ', flush=True)

        if create_test_pdf(str(filepath), i, topic, num_pages):
            print("OK")
            created += 1
        else:
            print("FAILED")
            failed += 1

    print()
    print("=" * 60)
    print(f"Created: {created}")
    print(f"Failed: {failed}")
    print(f"Output directory: {output_dir}")


if __name__ == '__main__':
    output_dir = sys.argv[1] if len(sys.argv) > 1 else '/mnt/data/git/AI/DocuBrowse/test_pdfs_sample'
    num_pdfs = int(sys.argv[2]) if len(sys.argv) > 2 else 100

    if not HAS_REPORTLAB:
        print("reportlab is required. Install with:")
        print("  pip install reportlab")
        sys.exit(1)

    generate_test_pdfs(output_dir, num_pdfs)
