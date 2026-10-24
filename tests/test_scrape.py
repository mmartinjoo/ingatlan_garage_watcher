from datetime import UTC, date, datetime

import pytest

from conftest import fixture_html
from garage_watcher.fetch import FetchError, FetchResult
from garage_watcher.scrape import DEFAULT_SEARCH_URL, ScrapeFailed, budapest_today, page_url, run_scrape
from test_parse import make_card, make_page

P1 = page_url(DEFAULT_SEARCH_URL, 1)
P2 = page_url(DEFAULT_SEARCH_URL, 2)
DAY = date(2026, 10, 24)


class FakeFetcher:
    def __init__(self, responses: dict[str, list]):
        self.responses = {k: list(v) for k, v in responses.items()}
        self.calls: list[tuple[str, bool]] = []

    def get(self, url, *, stealth=False):
        self.calls.append((url, stealth))
        item = self.responses[url].pop(0)
        if isinstance(item, Exception):
            raise item
        return FetchResult(item, 75 if stealth else 25)


def test_two_pages_recorded_in_full(conn):
    f = FakeFetcher({P1: [fixture_html("page1")], P2: [fixture_html("page2")]})
    r = run_scrape(conn, f, DAY)
    assert (r.pages_ok, r.pages_failed, r.listings_seen, r.total_results, r.credits_used) == (2, 0, 27, 27, 50)
    assert r.errors == []
    assert conn.execute("select count(*) from listings").fetchone()[0] == 27
    assert conn.execute("select count(*) from listing_snapshots where date = %s", (DAY,)).fetchone()[0] == 27
    assert conn.execute("select finished_at is not null, listings_seen from scrape_runs").fetchone() == (True, 27)
    assert f.calls == [(P1, False), (P2, False)]


def test_page_two_failure_writes_nothing(conn):
    f = FakeFetcher({P1: [fixture_html("page1")], P2: [FetchError("HTTP 500"), FetchError("HTTP 502")]})
    with pytest.raises(ScrapeFailed):
        run_scrape(conn, f, DAY)
    assert conn.execute("select count(*) from listing_snapshots").fetchone()[0] == 0
    assert conn.execute("select count(*) from listings").fetchone()[0] == 0
    ok, failed, errors, finished = conn.execute(
        "select pages_ok, pages_failed, errors, finished_at is not null from scrape_runs"
    ).fetchone()
    assert (ok, failed, finished) == (1, 1, True)
    assert errors[0]["page"] == 2 and "HTTP 502" in errors[0]["error"]
    assert f.calls == [(P1, False), (P2, False), (P2, True)]


def test_challenge_page_triggers_stealth_retry_then_succeeds(conn):
    challenge = "<html><title>Csak egy gyors ellenőrzés</title></html>"
    f = FakeFetcher({P1: [challenge, fixture_html("page1")], P2: [fixture_html("page2")]})
    r = run_scrape(conn, f, DAY)
    assert f.calls[:2] == [(P1, False), (P1, True)]
    assert (r.credits_used, r.listings_seen) == (125, 27)  # 25 wasted + 75 stealth + 25 page 2


def test_count_mismatch_is_warning_and_duplicates_are_deduped(conn):
    p1 = make_page([make_card(i) for i in range(1, 21)], total_results=22, page=1, total_pages=2)
    p2 = make_page([make_card(20)], total_results=22, page=2, total_pages=2)  # id 20 repeated, 22nd missing
    r = run_scrape(conn, FakeFetcher({P1: [p1], P2: [p2]}), DAY)
    assert (r.pages_failed, r.listings_seen) == (0, 20)
    assert any("22" in e.get("warning", "") for e in r.errors)
    assert conn.execute("select count(*) from listing_snapshots").fetchone()[0] == 20


def test_same_day_twice_is_idempotent(conn):
    f = FakeFetcher({P1: [fixture_html("page1")] * 2, P2: [fixture_html("page2")] * 2})
    run_scrape(conn, f, DAY)
    run_scrape(conn, f, DAY)
    assert conn.execute("select count(*) from listing_snapshots").fetchone()[0] == 27
    assert conn.execute("select count(*) from scrape_runs where finished_at is not null").fetchone()[0] == 2
    assert conn.execute("select count(distinct first_seen_date) from listings").fetchone()[0] == 1


def test_budget_exceeded_fails_run(conn):
    clock = iter([0.0, 500.0])
    f = FakeFetcher({P1: [fixture_html("page1")], P2: [fixture_html("page2")]})
    with pytest.raises(ScrapeFailed, match="budget"):
        run_scrape(conn, f, DAY, monotonic=lambda: next(clock))
    assert conn.execute("select count(*) from listing_snapshots").fetchone()[0] == 0


def test_budapest_today_rolls_over_at_local_midnight():
    assert budapest_today(datetime(2026, 10, 24, 22, 30, tzinfo=UTC)) == date(2026, 10, 25)
