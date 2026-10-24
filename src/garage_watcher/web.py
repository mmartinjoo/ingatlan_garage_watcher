"""Framework-free request handling for the cron-triggered scrape endpoint."""

import hmac
from collections.abc import Callable
from dataclasses import asdict

from garage_watcher import db
from garage_watcher.fetch import ScrapingBeeFetcher
from garage_watcher.scrape import DEFAULT_SEARCH_URL, RunResult, ScrapeFailed, budapest_today, run_scrape


def _default_run(database_url: str, scrapingbee_key: str, search_url: str) -> RunResult:
    with db.connect(database_url) as conn:
        return run_scrape(conn, ScrapingBeeFetcher(scrapingbee_key), budapest_today(), search_url=search_url)


def handle_scrape_request(
    auth_header: str | None,
    *,
    secret: str | None,
    database_url: str | None,
    scrapingbee_key: str | None,
    search_url: str = DEFAULT_SEARCH_URL,
    run: Callable[[str, str, str], RunResult] | None = None,
) -> tuple[int, dict]:
    expected = f"Bearer {secret}" if secret else None
    if expected is None or not hmac.compare_digest((auth_header or "").encode(), expected.encode()):
        return 401, {"error": "unauthorized"}
    if not database_url:
        return 500, {"error": "DATABASE_URL not set"}
    if not scrapingbee_key:
        return 500, {"error": "SCRAPINGBEE_API_KEY not set"}

    try:
        result = (run or _default_run)(database_url, scrapingbee_key, search_url)
    except ScrapeFailed as e:
        return 502, {"error": str(e)}

    body = asdict(result)
    body["run_date"] = result.run_date.isoformat()
    return 200, body
