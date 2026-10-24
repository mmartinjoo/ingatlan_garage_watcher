"""ScrapingBee client: one request per call, no retries (the job decides the retry policy)."""

import logging
from dataclasses import dataclass

import requests

SCRAPINGBEE_URL = "https://app.scrapingbee.com/api/v1/"
WAIT_FOR = "a[data-listing-id]"

log = logging.getLogger(__name__)


class FetchError(Exception):
    pass


@dataclass(frozen=True)
class FetchResult:
    html: str
    cost: int  # from the Spb-cost response header, 0 if absent


class ScrapingBeeFetcher:
    def __init__(
        self,
        api_key: str,
        session: requests.Session | None = None,
        *,
        timeout_s: float = 120.0,
    ):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.timeout_s = timeout_s

    def get(self, url: str, *, stealth: bool = False) -> FetchResult:
        params = {
            "api_key": self.api_key,
            "url": url,
            "render_js": "true",
            "country_code": "hu",
            "wait_for": WAIT_FOR,
            ("stealth_proxy" if stealth else "premium_proxy"): "true",
        }
        try:
            resp = self.session.get(SCRAPINGBEE_URL, params=params, timeout=self.timeout_s)
        except requests.RequestException as e:
            raise FetchError(f"{url}: {e}") from e
        if not 200 <= resp.status_code < 300:
            raise FetchError(f"{url}: HTTP {resp.status_code} {resp.text[:200]}")
        resp.encoding = "utf-8"
        cost = _int(resp.headers.get("Spb-cost"))
        log.info(
            "fetched %s via %s proxy: Spb-cost=%s Spb-resolved-url=%s",
            url, "stealth" if stealth else "premium", cost, resp.headers.get("Spb-resolved-url"),
        )
        return FetchResult(html=resp.text, cost=cost)


def _int(value: str | None) -> int:
    try:
        return int(value) if value else 0
    except ValueError:
        return 0
