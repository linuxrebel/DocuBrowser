#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
Mock API server for testing the DocuBrowse UI.
Serves index.html with mock /api/search, /api/tags, /api/stats endpoints.
Run: python3 test_server.py
Then open: http://localhost:8001
"""

import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path

# Mock data
MOCK_STATS = {
    "total_docs": 1247,
    "embedded": 1150,
    "unique_tags": 42
}

MOCK_TAGS = {
    "tags": [
        {"tag": "report", "count": 156},
        {"tag": "financial", "count": 98},
        {"tag": "budget", "count": 87},
        {"tag": "analysis", "count": 156},
        {"tag": "quarterly", "count": 65},
        {"tag": "proposal", "count": 52},
        {"tag": "meeting", "count": 48},
        {"tag": "strategic", "count": 42},
        {"tag": "planning", "count": 35},
        {"tag": "review", "count": 28}
    ]
}

MOCK_DOCUMENTS = [
    {
        "id": 1,
        "name": "Q4_2025_Financial_Report.pdf",
        "title": "Q4 2025 Financial Report",
        "path": "/mnt/data/Documents/reports/Q4_2025_Financial_Report.pdf",
        "description": "Comprehensive quarterly financial analysis covering revenue, expenses, and projections for the fourth quarter of 2025.",
        "content_snippet": "This report details the financial performance of Q4 2025, showing strong year-over-year growth...",
        "tags": "report,financial,quarterly",
        "modified_at": "2025-12-31T23:59:59Z",
        "score": 0.87,
        "fts_score": 0.92,
        "sem_score": 0.82
    },
    {
        "id": 2,
        "name": "Strategic_Planning_2026.docx",
        "title": "Strategic Planning for 2026",
        "path": "/mnt/data/Documents/planning/Strategic_Planning_2026.docx",
        "description": "Long-term strategic initiatives and goals for 2026 with detailed implementation roadmap and success metrics.",
        "content_snippet": "Our strategic priorities for 2026 include digital transformation, market expansion, and operational efficiency...",
        "tags": "strategic,planning,proposal",
        "modified_at": "2025-11-15T10:30:00Z",
        "score": 0.76,
        "fts_score": 0.71,
        "sem_score": 0.81
    },
    {
        "id": 3,
        "name": "Budget_Analysis_2026.xlsx",
        "title": "Budget Analysis 2026",
        "path": "/mnt/data/Documents/budget/Budget_Analysis_2026.xlsx",
        "description": "Detailed budget breakdown for 2026 with department allocations, variance analysis, and contingency planning.",
        "content_snippet": "The 2026 budget proposal allocates resources across five major departments with 15% contingency reserves...",
        "tags": "budget,analysis,financial",
        "modified_at": "2025-10-20T14:45:00Z",
        "score": 0.68,
        "fts_score": 0.75,
        "sem_score": 0.61
    },
    {
        "id": 4,
        "name": "Meeting_Minutes_November.md",
        "title": "November Board Meeting Minutes",
        "path": "/mnt/data/Documents/meetings/2025_11_Board_Meeting.md",
        "description": "Summary of key decisions and action items from November board meeting including strategic direction.",
        "content_snippet": "The board met on November 15, 2025 to review Q3 results and approve 2026 strategic initiatives...",
        "tags": "meeting,board,quarterly,review",
        "modified_at": "2025-11-15T16:00:00Z",
        "score": 0.52,
        "fts_score": 0.48,
        "sem_score": 0.56
    },
    {
        "id": 5,
        "name": "employee_handbook.pdf",
        "title": "Employee Handbook",
        "path": "/mnt/data/Documents/policies/employee_handbook.pdf",
        "description": "Complete employee handbook covering HR policies, benefits, workplace guidelines, and code of conduct.",
        "content_snippet": "Welcome to our organization. This handbook outlines the policies and procedures governing employment...",
        "tags": "policies,handbook",
        "modified_at": "2025-06-01T09:00:00Z",
        "score": 0.31,
        "fts_score": 0.28,
        "sem_score": 0.34
    },
    {
        "id": 6,
        "name": "IT_Security_Policy.pdf",
        "title": "IT Security Policy",
        "path": "/mnt/data/Documents/policies/IT_Security_Policy.pdf",
        "description": "Information technology security policies and procedures including access control and data protection.",
        "content_snippet": "This policy establishes the information security governance framework for the organization...",
        "tags": "security,policy,IT",
        "modified_at": "2025-07-15T11:20:00Z",
        "score": 0.44,
        "fts_score": 0.52,
        "sem_score": 0.36
    },
    {
        "id": 7,
        "name": "Quarterly_Review_Q3.xlsx",
        "title": "Quarterly Review Q3 2025",
        "path": "/mnt/data/Documents/reviews/Quarterly_Review_Q3.xlsx",
        "description": "Q3 2025 quarterly review document including performance metrics, departmental reviews, and forward projections.",
        "content_snippet": "Q3 2025 showed solid performance across most departments with revenue up 12% year-over-year...",
        "tags": "quarterly,review,analysis,report",
        "modified_at": "2025-10-01T08:00:00Z",
        "score": 0.79,
        "fts_score": 0.85,
        "sem_score": 0.73
    }
]

class MockAPIHandler(BaseHTTPRequestHandler):
    """Handle HTTP requests with mock API endpoints."""

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # Serve index.html
        if path == '/' or path == '/index.html':
            self.serve_file('index.html')
        # API: /api/stats
        elif path == '/api/stats':
            self.json_response(MOCK_STATS)
        # API: /api/tags
        elif path == '/api/tags':
            self.json_response(MOCK_TAGS)
        # API: /api/search
        elif path == '/api/search':
            q = query.get('q', [''])[0].lower()
            results = self.search_docs(q)
            self.json_response({"documents": results})
        # API: /api/config
        elif path == '/api/config':
            self.json_response({
                "docPath": "/mnt/data/Documents",
                "workDir": "/mnt/data/git/AI/DocuBrowse",
                "installed": False,
                "configSource": None
            })
        # API: /api/browse
        elif path == '/api/browse':
            path_param = query.get('path', ['/'])[0]
            self.browse_response(path_param)
        else:
            self.error_response(404, "Not found")

    def do_POST(self):
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/api/config':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body)
                self.json_response({
                    "message": f"Config saved: docPath={data.get('docPath')}, workDir={data.get('workDir')}"
                })
            except:
                self.error_response(400, "Invalid JSON")
        else:
            self.error_response(404, "Not found")

    def search_docs(self, query):
        """Search documents by query string."""
        if not query:
            return MOCK_DOCUMENTS

        # Simple keyword matching
        results = []
        q_lower = query.lower()

        for doc in MOCK_DOCUMENTS:
            title = (doc.get('title') or '').lower()
            desc = (doc.get('description') or '').lower()
            tags = (doc.get('tags') or '').lower()
            path = (doc.get('path') or '').lower()

            # Boost scores based on match location
            score = 0
            if q_lower in title:
                score += 0.3
            if q_lower in desc:
                score += 0.2
            if q_lower in tags:
                score += 0.25
            if q_lower in path:
                score += 0.1

            if score > 0:
                doc_copy = dict(doc)
                # Simulate search scores
                doc_copy['fts_score'] = min(0.99, 0.5 + score)
                doc_copy['sem_score'] = min(0.99, 0.4 + score * 0.5)
                doc_copy['score'] = (doc_copy['fts_score'] + doc_copy['sem_score']) / 2
                results.append(doc_copy)

        # Sort by combined score
        results.sort(key=lambda d: d['score'], reverse=True)
        return results

    def browse_response(self, path_param):
        """Simulate directory browsing."""
        try:
            path_obj = Path(path_param)
            if not path_obj.exists():
                path_param = '/mnt/data/Documents'
                path_obj = Path(path_param)

            entries = []
            try:
                for item in sorted(path_obj.iterdir()):
                    if item.is_dir():
                        entries.append({
                            "name": item.name,
                            "path": str(item)
                        })
            except PermissionError:
                pass

            self.json_response({
                "path": str(path_obj),
                "entries": entries[:20]  # Limit to 20 entries
            })
        except Exception as e:
            self.json_response({
                "path": path_param,
                "error": str(e),
                "entries": []
            })

    def serve_file(self, filename):
        """Serve a file from the current directory."""
        try:
            filepath = Path(__file__).parent / filename
            if filepath.exists():
                with open(filepath, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', len(content))
                self.end_headers()
                self.wfile.write(content)
            else:
                self.error_response(404, f"File not found: {filename}")
        except Exception as e:
            self.error_response(500, str(e))

    def json_response(self, data):
        """Send a JSON response."""
        content = json.dumps(data).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(content))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(content)

    def error_response(self, code, message):
        """Send an error response."""
        self.send_response(code)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(f"{code}: {message}".encode('utf-8'))


def main():
    """Start the mock API server."""
    port = 8001
    server_address = ('localhost', port)
    httpd = HTTPServer(server_address, MockAPIHandler)

    print(f"DocuBrowse Test Server running on http://localhost:{port}")
    print(f"Open in browser: http://localhost:{port}")
    print("Press Ctrl+C to stop")
    print()
    print("Available endpoints:")
    print("  GET  /               - Serve index.html")
    print("  GET  /api/stats      - Get document statistics")
    print("  GET  /api/tags       - Get all tags with counts")
    print("  GET  /api/search?q=  - Search documents")
    print("  GET  /api/config     - Get current config")
    print("  POST /api/config     - Save config")
    print("  GET  /api/browse     - Browse directories")
    print()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        httpd.server_close()


if __name__ == '__main__':
    main()
