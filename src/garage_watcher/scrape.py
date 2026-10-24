"""Scrape orchestration: every page of the search, written all-or-nothing per run."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from garage_watcher.fetch import FetchError
from garage_watcher.parse import PAGE_SIZE, ParsedListing, ParsedPage, ParseError, parse_listing_page
from garage_watcher.repository import finish_run, save_listing, start_run

DEFAULT_SEARCH_URL = "https://ingatlan.com/lista/kiado+garazs+szombathely"
MAX_PAGES = 10

log = logging.getLogger(__name__)


class ScrapeFailed(Exception):
    pass


@dataclass
class RunResult:
    run_id: int
    run_date: date
    pages_ok: int
    pages_failed: int
    listings_seen: int
    total_results: int | None
    credits_used: int
    errors: list[dict]


def budapest_today(now: datetime | None = None) -> date:
    now = now or datetime.now(UTC)
    return now.astimezone(ZoneInfo("Europe/Budapest")).date()


def page_url(search_url: str, page: int) -> str:
    return f"{search_url}?page={page}"


def run_scrape(
    conn,
    fetcher,
    run_date: date,
    *,
    search_url: str = DEFAULT_SEARCH_URL,
    budget_s: float = 240.0,
    monotonic: Callable[[], float] = time.monotonic,
) -> RunResult:
    started = monotonic()
    run_id = start_run(conn, run_date)
    credits = 0
    pages: list[ParsedPage] = []
    total_results: int | None = None

    def fetch_page(n: int) -> ParsedPage:
        nonlocal credits
        url = page_url(search_url, n)
        try:
            result = fetcher.get(url)
            credits += result.cost
            return parse_listing_page(result.html)
        except (FetchError, ParseError) as e:
            log.warning("page %d failed with premium proxy (%s: %s); retrying with stealth", n, type(e).__name__, e)
        result = fetcher.get(url, stealth=True)
        credits += result.cost
        return parse_listing_page(result.html)

    def fail(n: int, message: str, cause: Exception | None = None) -> None:
        log.error("run failed on page %d: %s", n, message)
        finish_run(
            conn, run_id, pages_ok=len(pages), pages_failed=1, listings_seen=0,
            total_results=total_results, credits_used=credits,
            errors=[{"page": n, "error": message}],
        )
        raise ScrapeFailed(message) from cause

    try:
        first = fetch_page(1)
    except (FetchError, ParseError) as e:
        fail(1, f"{type(e).__name__}: {e}", e)
    pages.append(first)
    total_results = first.total_results
    if first.total_pages > MAX_PAGES:
        fail(1, f"too many pages: {first.total_pages} (cap {MAX_PAGES})")

    for n in range(2, first.total_pages + 1):
        if monotonic() - started > budget_s:
            fail(n, "time budget exceeded")
        try:
            pages.append(fetch_page(n))
        except (FetchError, ParseError) as e:
            fail(n, f"{type(e).__name__}: {e}", e)

    errors: list[dict] = []
    by_id: dict[int, ParsedListing] = {}
    for page in pages:
        for w in page.warnings:
            log.warning("page %d: %s", page.page, w)
            errors.append({"page": page.page, "warning": w})
        if page.page < first.total_pages and len(page.listings) < PAGE_SIZE:
            errors.append({"page": page.page, "warning": f"only {len(page.listings)} cards"})
        for listing in page.listings:
            by_id.setdefault(listing.listing_id, listing)
    if len(by_id) != total_results:
        errors.append({"warning": f"collected {len(by_id)} listings but site reports {total_results}"})

    with conn.transaction():
        for listing in by_id.values():
            save_listing(conn, listing, run_date)
    finish_run(
        conn, run_id, pages_ok=len(pages), pages_failed=0, listings_seen=len(by_id),
        total_results=total_results, credits_used=credits, errors=errors,
    )
    return RunResult(run_id, run_date, len(pages), 0, len(by_id), total_results, credits, errors)
