from datetime import date

from garage_watcher.scrape import RunResult, ScrapeFailed
from garage_watcher.web import handle_scrape_request

AUTH = "Bearer s3cret"
URL = "postgresql://x"


def result():
    return RunResult(run_id=1, run_date=date(2026, 10, 24), pages_ok=2, pages_failed=0,
                     listings_seen=27, total_results=27, credits_used=50, errors=[])


def test_rejects_wrong_or_missing_token_without_running():
    calls = []
    for header in ["Bearer nope", None, "Bearer "]:
        status, body = handle_scrape_request(
            header, secret="s3cret", database_url=URL, scrapingbee_key="SB", run=lambda *a: calls.append(a)
        )
        assert (status, body) == (401, {"error": "unauthorized"})
    assert handle_scrape_request("Bearer ", secret=None, database_url=URL, scrapingbee_key="SB",
                                 run=lambda *a: calls.append(a))[0] == 401
    assert calls == []


def test_missing_config_is_500():
    assert handle_scrape_request(AUTH, secret="s3cret", database_url=None, scrapingbee_key="SB",
                                 run=lambda *a: result()) == (500, {"error": "DATABASE_URL not set"})
    assert handle_scrape_request(AUTH, secret="s3cret", database_url=URL, scrapingbee_key=None,
                                 run=lambda *a: result()) == (500, {"error": "SCRAPINGBEE_API_KEY not set"})


def test_success_returns_200_and_passes_config():
    seen = []

    def run(db, key, url):
        seen.append((db, key, url))
        return result()

    status, body = handle_scrape_request(AUTH, secret="s3cret", database_url=URL, scrapingbee_key="SB",
                                         search_url="https://x/lista", run=run)
    assert status == 200 and seen == [(URL, "SB", "https://x/lista")]
    assert (body["listings_seen"], body["credits_used"], body["run_date"]) == (27, 50, "2026-10-24")


def test_scrape_failed_returns_502():
    def run(*a):
        raise ScrapeFailed("page 2: FetchError: HTTP 502")

    status, body = handle_scrape_request(AUTH, secret="s3cret", database_url=URL, scrapingbee_key="SB", run=run)
    assert status == 502 and "HTTP 502" in body["error"]
