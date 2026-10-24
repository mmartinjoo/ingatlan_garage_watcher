"""Vercel Python function: GET /api/scrape (triggered daily by Vercel Cron)."""

import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from garage_watcher.scrape import DEFAULT_SEARCH_URL  # noqa: E402
from garage_watcher.web import handle_scrape_request  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            status, body = handle_scrape_request(
                self.headers.get("Authorization"),
                secret=os.environ.get("CRON_SECRET"),
                database_url=os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL"),
                scrapingbee_key=os.environ.get("SCRAPINGBEE_API_KEY"),
                search_url=os.environ.get("SEARCH_URL") or DEFAULT_SEARCH_URL,
            )
        except Exception:
            traceback.print_exc(file=sys.stderr)
            status, body = 500, {"error": "internal error"}
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
