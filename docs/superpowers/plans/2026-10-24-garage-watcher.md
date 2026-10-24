# Garage Watcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daily Vercel cron job that fetches the ingatlan.com "kiadó garázs Szombathely" list through ScrapingBee and records every ad (id, price, address, area) into Postgres so the owner can answer market questions in SQL.

**Architecture:** Thin Vercel adapter in `api/scrape.py`; framework-free modules under `src/garage_watcher/` split by responsibility (fetch, parse, repository, scrape, web, db, cli); plain-SQL migrations tracked in `schema_migrations`; two SQL views are the product. Mirrors the sibling project `/Users/joomartin/code/dokkinger/store_watcher` file for file, with the fetcher swapped for a ScrapingBee client and all-or-nothing writes per run.

**Tech Stack:** Python 3.12, uv (`uv_build`), requests, beautifulsoup4 (html.parser), psycopg 3 (`psycopg[binary]`), tzdata, pytest, Postgres 16 (Docker locally, Vercel Marketplace in prod), Vercel Python functions + Cron.

**Spec:** `docs/superpowers/specs/2026-10-24-garage-watcher-design.md`

## Global Constraints

- Python `>=3.12`; `.python-version` = `3.12`.
- Dependencies exactly: `beautifulsoup4>=4.15.0`, `psycopg[binary]>=3.3.6`, `requests>=2.34.2`, `tzdata>=2026.5`; dev: `pytest>=9.1.1`. No ScrapingBee SDK, no ORM, no mock library.
- Package name `garage_watcher`, project name `garage-watcher`, CLI script `garage-watcher`.
- Env vars: `DATABASE_URL` (fallback `POSTGRES_URL`), `TEST_DATABASE_URL`, `CRON_SECRET`, `SCRAPINGBEE_API_KEY`, optional `SEARCH_URL`. Default search URL `https://ingatlan.com/lista/kiado+garazs+szombathely`. Secrets never in the repo.
- Local Postgres: `postgres:16`, host port **5434**, user/password/db `garage_watcher`, test db `garage_watcher_test`.
- ScrapingBee: `GET https://app.scrapingbee.com/api/v1/` with `render_js=true`, `country_code=hu`, `wait_for=a[data-listing-id]`; first attempt `premium_proxy=true`, retry `stealth_proxy=true`. Timeout 120 s per request.
- Run: date = Budapest local date; cron `0 4 * * *`; region `fra1`; `maxDuration` 300; time budget 240 s; max 10 pages; 20 cards per page.
- All-or-nothing: no `listings`/`listing_snapshots` rows unless every page fetched and parsed. Count mismatches are warnings, not failures.
- Encoding forced to UTF-8 on fetched HTML.
- Commit after every task; conventional-commit style messages as in the steps.

## Review Focus

1. Price text that is not `N NNN Ft/hó` (e.g. `Ár nélkül`, `100 €/hó`): the ad is still recorded, `price_huf` is `None`, a warning is attached. → Task 2.
2. Address without a comma (`Szombathely`): `city` is the whole address, no crash. → Task 2.
3. The same ad id on two pages (ordering shifted between fetches): one listing, one snapshot, run succeeds. → Task 6.
4. The job runs twice on the same day: second run changes nothing (same `first_seen_date`, one snapshot per ad, two run rows). → Task 4 and Task 6.
5. ScrapingBee returns 200 with a Cloudflare challenge body (no total-results attribute): parse error → stealth retry → if that also fails, the run fails with no data written. → Task 2 (ParseError) and Task 6 (retry + no writes).

---

### Task 1: Project scaffold and test fixtures

**Files:**
- Create: `pyproject.toml`, `.python-version`, `.gitignore`, `.vercelignore`, `.env.example`, `docker-compose.yml`, `docker/initdb/01-test-db.sql`, `vercel.json`
- Create: `src/garage_watcher/__init__.py` (empty), `src/garage_watcher/migrations/__init__.py` (empty)
- Create: `tests/conftest.py`, `tests/fixtures/page1.html`, `tests/fixtures/page2.html`

**Interfaces:**
- Produces: `tests/conftest.py` with `fixture_html(name: str) -> str` and the `conn` pytest fixture (fresh migrated schema per test; refuses unless the db name ends in `_test`); `TEST_DATABASE_URL` default `postgresql://garage_watcher:garage_watcher@localhost:5434/garage_watcher_test`.

- [ ] **Step 1: Copy config files from store_watcher and rename**

Copy these from `/Users/joomartin/code/dokkinger/store_watcher/` and replace `store_watcher`→`garage_watcher`, `store-watcher`→`garage-watcher`, `5433`→`5434`: `pyproject.toml` (description: "Daily scraper for ingatlan.com garage-for-rent listings in Szombathely, stored in Postgres"), `.python-version`, `.gitignore`, `.vercelignore`, `docker-compose.yml`, `docker/initdb/01-test-db.sql`, `vercel.json` (unchanged content). `.env.example`:

```
DATABASE_URL=postgresql://garage_watcher:garage_watcher@localhost:5434/garage_watcher
TEST_DATABASE_URL=postgresql://garage_watcher:garage_watcher@localhost:5434/garage_watcher_test
CRON_SECRET=change-me
SCRAPINGBEE_API_KEY=change-me
SEARCH_URL=https://ingatlan.com/lista/kiado+garazs+szombathely
```

- [ ] **Step 2: Create the package skeleton and conftest**

Create empty `src/garage_watcher/__init__.py` and `src/garage_watcher/migrations/__init__.py`. Copy `tests/conftest.py` from store_watcher with the import changed to `from garage_watcher.db import connect, migrate` and the default `TEST_DATABASE_URL` above. (`db.py` arrives in Task 3; until then only `fixture_html` is importable, which is all Task 2 needs — so comment out the `conn` fixture and its import in this task and restore them in Task 3.)

- [ ] **Step 3: Install and start Postgres**

Run: `uv sync && docker compose up -d && cp .env.example .env`
Expected: `.venv` created with pytest; `docker compose ps` shows `db` running on 5434.

- [ ] **Step 4: Copy and shrink the fixtures**

Source files (session scratchpad; if missing, re-capture page 1 and 2 once with the ScrapingBee premium call from Task 5):
`/private/tmp/claude-501/-Users-joomartin-code-dokkinger-ingatlan-garage-watcher/a3dd56db-73bd-4b78-8697-8f394dcb30e7/scratchpad/sb_stealth.html` → `tests/fixtures/page1.html`,
`.../sb_prem.html` → `tests/fixtures/page2.html`.

Run for each: `sed -E 's#data:image/[a-z]+;base64,[A-Za-z0-9+/=]+#data:,#g' <src> > tests/fixtures/pageN.html`

- [ ] **Step 5: Verify fixtures**

Run: `grep -c 'data-listing-id=' tests/fixtures/page1.html tests/fixtures/page2.html; du -h tests/fixtures/*.html`
Expected: `page1.html:20`, `page2.html:7`, each file under 1 MB.

- [ ] **Step 6: Verify pytest runs**

Run: `uv run --env-file .env pytest`
Expected: `no tests ran`, exit code 5, no import errors.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: scaffold garage-watcher project and add listing-page fixtures"
```

---

### Task 2: HTML parsing

**Files:**
- Create: `src/garage_watcher/parse.py`
- Test: `tests/test_parse.py`

**Interfaces:**
- Produces:
  ```python
  BASE_URL = "https://ingatlan.com"
  PAGE_SIZE = 20
  class ParseError(Exception)
  @dataclass(frozen=True)
  class ParsedListing: listing_id: int; url: str; address: str; city: str; price_huf: int | None; area_m2: Decimal | None
  @dataclass(frozen=True)
  class ParsedPage: listings: list[ParsedListing]; page: int; total_pages: int; total_results: int; warnings: list[str]
  def parse_listing_page(html: str) -> ParsedPage
  ```

- [ ] **Step 1: Write the failing fixture tests**

```python
from decimal import Decimal
import pytest
from conftest import fixture_html
from garage_watcher.parse import ParseError, parse_listing_page

def test_page1_counts_and_pagination():
    page = parse_listing_page(fixture_html("page1"))
    assert len(page.listings) == 20
    assert (page.page, page.total_pages, page.total_results) == (1, 2, 27)
    assert page.warnings == []

def test_page1_first_listing_fields():
    first = parse_listing_page(fixture_html("page1")).listings[0]
    assert first.listing_id == 35639715
    assert first.url == "https://ingatlan.com/35639715"
    assert first.price_huf == 30000
    assert first.address == "Szombathely, Jászai Mari utca"
    assert first.city == "Szombathely"
    assert first.area_m2 == Decimal("15")

def test_page1_other_listings():
    by_id = {l.listing_id: l for l in parse_listing_page(fixture_html("page1")).listings}
    assert (by_id[35458325].price_huf, by_id[35458325].area_m2) == (25000, Decimal("8"))
    assert (by_id[35435655].price_huf, by_id[35435655].area_m2) == (65000, Decimal("22"))
    assert by_id[35610330].address == "Szombathely, Szent István király utca 58/A"

def test_page2_is_last_page_and_disjoint():
    p1 = parse_listing_page(fixture_html("page1"))
    p2 = parse_listing_page(fixture_html("page2"))
    assert len(p2.listings) == 7
    assert (p2.page, p2.total_pages, p2.total_results) == (2, 2, 27)
    assert {l.listing_id for l in p1.listings}.isdisjoint({l.listing_id for l in p2.listings})
    assert all(l.price_huf and l.price_huf > 0 for l in p2.listings)
```

- [ ] **Step 2: Write the failing synthetic-HTML tests**

Add helpers `make_card(listing_id, price="30 000  Ft/hó", address="Szombathely, X utca", area="15 m<sup>2</sup>")` returning one `<a class="listing-card" data-listing-id=... href="/<id>">` with the three spans in the real structure (`span.fw-bold.fs-5` price, `span.d-block.fs-7` address, a `span.fs-7` with text `Alapterület` followed by `span.fs-6.fw-bold` area; pass `None` to omit a span), and `make_page(cards, total_results=27, page=1, total_pages=2, with_pagination=True, with_total_attr=True)` wrapping them in a div carrying `data-listings-page--main-total-number-of-results-value` and the `span.text-gray-500` / `span.text-gray-200` pagination pair.

```python
def test_missing_price_is_none_with_warning():
    page = parse_listing_page(make_page([make_card(1, price=None)]))
    assert page.listings[0].price_huf is None
    assert any("1" in w and "price" in w for w in page.warnings)

def test_non_huf_price_is_none_with_warning():
    page = parse_listing_page(make_page([make_card(1, price="100 €/hó")]))
    assert page.listings[0].price_huf is None
    assert len(page.warnings) == 1

def test_missing_area_is_none_with_warning():
    page = parse_listing_page(make_page([make_card(1, area=None)]))
    assert page.listings[0].area_m2 is None
    assert any("area" in w for w in page.warnings)

def test_comma_decimal_area():
    assert parse_listing_page(make_page([make_card(1, area="15,5 m<sup>2</sup>")])).listings[0].area_m2 == Decimal("15.5")

def test_address_without_comma_city_is_whole_address():
    l = parse_listing_page(make_page([make_card(1, address="Szombathely")])).listings[0]
    assert (l.address, l.city) == ("Szombathely", "Szombathely")

def test_zero_cards_with_results_is_error():
    with pytest.raises(ParseError):
        parse_listing_page(make_page([], total_results=27))

def test_zero_cards_zero_results_is_empty_page():
    page = parse_listing_page(make_page([], total_results=0, with_pagination=False))
    assert page.listings == [] and page.total_results == 0 and page.total_pages == 1

def test_missing_total_attribute_is_error():
    with pytest.raises(ParseError):
        parse_listing_page(make_page([make_card(1)], with_total_attr=False))

def test_total_pages_falls_back_to_ceil_of_results():
    page = parse_listing_page(make_page([make_card(1)], total_results=27, with_pagination=False))
    assert (page.page, page.total_pages) == (1, 2)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --env-file .env pytest tests/test_parse.py -v`
Expected: all FAIL with `ModuleNotFoundError: garage_watcher.parse`.

- [ ] **Step 4: Implement `parse.py`**

Reuse the `_norm`, `_text`, `_decimal`, `_int` helpers from store_watcher's `parse.py`. Rules:
- cards: `soup.select("a.listing-card[data-listing-id]")`; id from the attribute; url `f"{BASE_URL}/{id}"`.
- price: text of `span.fw-bold.fs-5` in the card; if it contains `Ft`, keep digits only → `int`; otherwise `None` + warning `f"listing {id}: unparseable price {text!r}"`.
- address: `_text(card.select_one("span.d-block.fs-7"))`; `city` = part before the first comma, stripped, or the whole address.
- area: find the `span` in the card whose text is `Alapterület`, take `find_next_sibling("span")`, regex `(\d+(?:[.,]\d+)?)\s*m` → `Decimal` with `,`→`.`; missing → `None` + warning `f"listing {id}: missing area"`.
- `total_results`: `int` of the attribute on `[data-listings-page--main-total-number-of-results-value]`; missing → `ParseError("no total-results attribute; not a listing page")`.
- zero cards and `total_results > 0` → `ParseError`.
- pagination: `span.text-gray-500 + span.text-gray-200` whose text matches `/\s*(\d+)`; page = int of the preceding span; missing → `page=1`, `total_pages=max(1, ceil(total_results / PAGE_SIZE))`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --env-file .env pytest tests/test_parse.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/garage_watcher/parse.py tests/test_parse.py
git commit -m "feat: parse ingatlan.com listing pages"
```

---

### Task 3: Database connection, migrations, views

**Files:**
- Create: `src/garage_watcher/db.py`, `src/garage_watcher/migrations/001_schema.sql`, `src/garage_watcher/migrations/002_views.sql`
- Modify: `tests/conftest.py` (restore the `conn` fixture)
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `connect(url: str) -> psycopg.Connection` (with `prepare_threshold=None`), `migrate(conn) -> list[str]` (newly applied file names). Tables `listings`, `listing_snapshots`, `scrape_runs`; views `listing_durations`, `daily_availability` exactly as in spec §4.

- [ ] **Step 1: Write the failing tests**

```python
from garage_watcher.db import migrate

def test_migrate_applies_all_then_nothing(conn):
    assert migrate(conn) == []          # conftest already migrated
    names = [r[0] for r in conn.execute("select name from schema_migrations order by name")]
    assert names == ["001_schema.sql", "002_views.sql"]

def test_tables_and_views_exist(conn):
    tables = {r[0] for r in conn.execute("select table_name from information_schema.tables where table_schema='public'")}
    assert {"listings", "listing_snapshots", "scrape_runs", "listing_durations", "daily_availability"} <= tables

def test_duration_views_on_two_runs(conn):
    conn.execute("insert into scrape_runs (date, finished_at) values ('2026-10-01', now()), ('2026-10-03', now())")
    conn.execute("""insert into listings (id, url, address, first_seen_date, last_seen_date, last_price_huf, last_area_m2) values
        (1, 'u', 'a', '2026-10-01', '2026-10-03', 30000, 15),   -- censored, still listed
        (2, 'u', 'b', '2026-10-02', '2026-10-02', 40000, 20)""")  # not censored, gone
    rows = {r[0]: r for r in conn.execute("select id, days_listed, is_gone, left_censored from listing_durations")}
    assert rows[1][1:] == (3, False, True)
    assert rows[2][1:] == (1, True, False)

def test_daily_availability_aggregates(conn):
    conn.execute("insert into listings (id, url, address, first_seen_date, last_seen_date) values (1,'u','a','2026-10-01','2026-10-01'), (2,'u','b','2026-10-01','2026-10-01')")
    conn.execute("insert into listing_snapshots (listing_id, date, price_huf, area_m2) values (1,'2026-10-01',30000,15), (2,'2026-10-01',50000,20)")
    units, price, area = conn.execute("select units, avg_price_huf, avg_area_m2 from daily_availability").fetchone()
    assert (units, price, float(area)) == (2, 40000, 17.5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --env-file .env pytest tests/test_db.py -v`
Expected: FAIL (`garage_watcher.db` missing / conftest import error).

- [ ] **Step 3: Implement**

`db.py`: copy store_watcher's `db.py`, replacing `store_watcher.migrations` with `garage_watcher.migrations`. `001_schema.sql` and `002_views.sql`: the SQL from spec §4 verbatim. Restore the `conn` fixture in `conftest.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --env-file .env pytest tests/test_db.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/garage_watcher/db.py src/garage_watcher/migrations tests/conftest.py tests/test_db.py
git commit -m "feat: schema, migrations runner and reporting views"
```

---

### Task 4: Repository (upserts and run bookkeeping)

**Files:**
- Create: `src/garage_watcher/repository.py`
- Test: `tests/test_repository.py`

**Interfaces:**
- Consumes: `ParsedListing` (Task 2).
- Produces:
  ```python
  def start_run(conn, run_date: date) -> int                      # inserts scrape_runs row, commits
  def finish_run(conn, run_id: int, *, pages_ok: int, pages_failed: int, listings_seen: int,
                 total_results: int | None, credits_used: int, errors: list[dict]) -> None   # sets finished_at, commits
  def save_listing(conn, listing: ParsedListing, run_date: date) -> None   # upsert listings + listing_snapshots; caller owns the transaction
  ```

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date
from decimal import Decimal
from garage_watcher.parse import ParsedListing
from garage_watcher.repository import finish_run, save_listing, start_run

def listing(id=1, price=30000, area=Decimal("15"), address="Szombathely, X utca"):
    return ParsedListing(id, f"https://ingatlan.com/{id}", address, "Szombathely", price, area)

def test_save_listing_inserts_listing_and_snapshot(conn):
    save_listing(conn, listing(), date(2026, 10, 1)); conn.commit()
    row = conn.execute("select url, address, city, first_seen_date, last_seen_date, last_price_huf, last_area_m2 from listings").fetchone()
    assert row == ("https://ingatlan.com/1", "Szombathely, X utca", "Szombathely", date(2026,10,1), date(2026,10,1), 30000, Decimal("15.00"))
    assert conn.execute("select listing_id, date, price_huf from listing_snapshots").fetchone() == (1, date(2026,10,1), 30000)

def test_second_day_advances_last_seen_and_keeps_first_seen(conn):
    save_listing(conn, listing(), date(2026, 10, 1))
    save_listing(conn, listing(price=35000), date(2026, 10, 2)); conn.commit()
    assert conn.execute("select first_seen_date, last_seen_date, last_price_huf from listings").fetchone() == (date(2026,10,1), date(2026,10,2), 35000)
    assert conn.execute("select count(*) from listing_snapshots").fetchone()[0] == 2

def test_same_day_twice_is_idempotent(conn):
    save_listing(conn, listing(), date(2026, 10, 1))
    save_listing(conn, listing(price=31000), date(2026, 10, 1)); conn.commit()
    assert conn.execute("select count(*) from listing_snapshots").fetchone()[0] == 1
    assert conn.execute("select price_huf from listing_snapshots").fetchone()[0] == 31000

def test_start_and_finish_run(conn):
    run_id = start_run(conn, date(2026, 10, 1))
    assert conn.execute("select finished_at from scrape_runs where id=%s", (run_id,)).fetchone()[0] is None
    finish_run(conn, run_id, pages_ok=2, pages_failed=0, listings_seen=27, total_results=27, credits_used=50, errors=[{"warning": "x"}])
    row = conn.execute("select pages_ok, listings_seen, total_results, credits_used, errors, finished_at is not null from scrape_runs where id=%s", (run_id,)).fetchone()
    assert row == (2, 27, 27, 50, [{"warning": "x"}], True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --env-file .env pytest tests/test_repository.py -v`
Expected: FAIL with import error.

- [ ] **Step 3: Implement `repository.py`**

Follow store_watcher's `repository.py` style (`Jsonb(errors)`, `on conflict ... do update`, `greatest(listings.last_seen_date, excluded.last_seen_date)`). `save_listing` upserts `listings` (refreshing `url, address, city, last_price_huf, last_area_m2`) and then `listing_snapshots` (updating `price_huf, area_m2` on conflict). No `SuspiciousEmptyPage` here; that guard lives in the parser.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --env-file .env pytest tests/test_repository.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/garage_watcher/repository.py tests/test_repository.py
git commit -m "feat: listing upserts and scrape-run bookkeeping"
```

---

### Task 5: ScrapingBee fetcher

**Files:**
- Create: `src/garage_watcher/fetch.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Produces:
  ```python
  SCRAPINGBEE_URL = "https://app.scrapingbee.com/api/v1/"
  class FetchError(Exception)
  @dataclass(frozen=True)
  class FetchResult: html: str; cost: int          # cost from the Spb-cost response header, 0 if absent
  class ScrapingBeeFetcher:
      def __init__(self, api_key: str, session: requests.Session | None = None, *, timeout_s: float = 120.0)
      def get(self, url: str, *, stealth: bool = False) -> FetchResult
  ```
  No retry inside the fetcher; the retry policy (premium → stealth) lives in Task 6.

- [ ] **Step 1: Write the failing tests**

```python
import pytest, requests
from garage_watcher.fetch import SCRAPINGBEE_URL, FetchError, ScrapingBeeFetcher

class FakeResponse:
    def __init__(self, status_code=200, text="<html>", headers=None):
        self.status_code, self.text, self.headers, self.encoding = status_code, text, headers or {}, None

class FakeSession:
    def __init__(self, queue): self.queue, self.calls = list(queue), []
    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        item = self.queue.pop(0)
        if isinstance(item, Exception): raise item
        return item

def make(queue):
    s = FakeSession(queue); return ScrapingBeeFetcher("KEY", s), s

def test_premium_request_params_and_cost():
    f, s = make([FakeResponse(headers={"Spb-cost": "25"})])
    r = f.get("https://ingatlan.com/lista/x?page=1")
    c = s.calls[0]
    assert c["url"] == SCRAPINGBEE_URL and c["timeout"] == 120.0
    assert c["params"] == {"api_key": "KEY", "url": "https://ingatlan.com/lista/x?page=1", "render_js": "true",
                           "premium_proxy": "true", "country_code": "hu", "wait_for": "a[data-listing-id]"}
    assert (r.html, r.cost) == ("<html>", 25)

def test_stealth_request_params():
    f, s = make([FakeResponse(headers={"Spb-cost": "75"})])
    assert f.get("u", stealth=True).cost == 75
    p = s.calls[0]["params"]
    assert p["stealth_proxy"] == "true" and "premium_proxy" not in p and p["render_js"] == "true"

def test_non_2xx_raises_fetch_error_with_status():
    f, _ = make([FakeResponse(500, text="upstream")])
    with pytest.raises(FetchError, match="HTTP 500"):
        f.get("u")

def test_transport_error_raises_fetch_error():
    f, _ = make([requests.ConnectionError("boom")])
    with pytest.raises(FetchError):
        f.get("u")

def test_missing_cost_header_is_zero_and_utf8_forced():
    resp = FakeResponse()
    f, _ = make([resp])
    assert f.get("u").cost == 0 and resp.encoding == "utf-8"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --env-file .env pytest tests/test_fetch.py -v`
Expected: FAIL with import error.

- [ ] **Step 3: Implement `fetch.py`**

`session.get(SCRAPINGBEE_URL, params=..., timeout=self.timeout_s)`; `requests.RequestException` → `FetchError(f"{url}: {e}")`; non-2xx → `FetchError(f"{url}: HTTP {status} {resp.text[:200]}")`; set `resp.encoding = "utf-8"`; read `Spb-cost` case-insensitively (requests headers are case-insensitive; the fake uses a plain dict with the exact key `Spb-cost`, so read that key). Log `Spb-cost` and `Spb-resolved-url` at INFO.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --env-file .env pytest tests/test_fetch.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/garage_watcher/fetch.py tests/test_fetch.py
git commit -m "feat: ScrapingBee fetcher"
```

---

### Task 6: Scrape orchestration

**Files:**
- Create: `src/garage_watcher/scrape.py`
- Test: `tests/test_scrape.py`

**Interfaces:**
- Consumes: `parse_listing_page`, `ParseError`, `PAGE_SIZE` (Task 2); `start_run`, `finish_run`, `save_listing` (Task 4); `FetchError`, `FetchResult` (Task 5).
- Produces:
  ```python
  DEFAULT_SEARCH_URL = "https://ingatlan.com/lista/kiado+garazs+szombathely"
  MAX_PAGES = 10
  class ScrapeFailed(Exception)
  @dataclass
  class RunResult: run_id: int; run_date: date; pages_ok: int; pages_failed: int; listings_seen: int; total_results: int | None; credits_used: int; errors: list[dict]
  def budapest_today(now: datetime | None = None) -> date
  def page_url(search_url: str, page: int) -> str            # f"{search_url}?page={page}"
  def run_scrape(conn, fetcher, run_date: date, *, search_url: str = DEFAULT_SEARCH_URL,
                 budget_s: float = 240.0, monotonic: Callable[[], float] = time.monotonic) -> RunResult
  ```
  `fetcher` is anything with `get(url, *, stealth=False) -> FetchResult`.

- [ ] **Step 1: Write the failing tests**

`FakeFetcher(responses: dict[str, list[str | Exception]])`: `get(url, *, stealth=False)` records `(url, stealth)` in `self.calls`, pops the next item for `url` (raise if Exception, else `FetchResult(item, 75 if stealth else 25)`). `P1 = page_url(DEFAULT_SEARCH_URL, 1)`, `P2 = ... 2`. Use `fixture_html("page1")`/`"page2"` and the `make_page`/`make_card` helpers from `test_parse` (import them).

```python
def test_two_pages_recorded_in_full(conn):
    f = FakeFetcher({P1: [fixture_html("page1")], P2: [fixture_html("page2")]})
    r = run_scrape(conn, f, date(2026, 10, 24))
    assert (r.pages_ok, r.pages_failed, r.listings_seen, r.total_results, r.credits_used) == (2, 0, 27, 27, 50)
    assert r.errors == []
    assert conn.execute("select count(*) from listings").fetchone()[0] == 27
    assert conn.execute("select count(*) from listing_snapshots where date='2026-10-24'").fetchone()[0] == 27
    assert conn.execute("select finished_at is not null, listings_seen from scrape_runs").fetchone() == (True, 27)
    assert f.calls == [(P1, False), (P2, False)]

def test_page_two_failure_writes_nothing(conn):
    f = FakeFetcher({P1: [fixture_html("page1")], P2: [FetchError("HTTP 500"), FetchError("HTTP 502")]})
    with pytest.raises(ScrapeFailed):
        run_scrape(conn, f, date(2026, 10, 24))
    assert conn.execute("select count(*) from listing_snapshots").fetchone()[0] == 0
    assert conn.execute("select count(*) from listings").fetchone()[0] == 0
    ok, failed, errors, finished = conn.execute("select pages_ok, pages_failed, errors, finished_at is not null from scrape_runs").fetchone()
    assert (ok, failed, finished) == (1, 1, True) and errors[0]["page"] == 2 and "HTTP 502" in errors[0]["error"]
    assert f.calls == [(P1, False), (P2, False), (P2, True)]

def test_parse_error_triggers_stealth_retry_then_succeeds(conn):
    challenge = "<html><title>Csak egy gyors ellenőrzés</title></html>"
    f = FakeFetcher({P1: [challenge, fixture_html("page1")], P2: [fixture_html("page2")]})
    r = run_scrape(conn, f, date(2026, 10, 24))
    assert f.calls[:2] == [(P1, False), (P1, True)] and r.credits_used == 100 and r.listings_seen == 27

def test_count_mismatch_is_warning_not_failure(conn):
    html = make_page([make_card(i) for i in range(1, 26)], total_results=27, total_pages=1)  # 25 cards, site says 27
    f = FakeFetcher({P1: [html]})
    r = run_scrape(conn, f, date(2026, 10, 24))
    assert r.pages_failed == 0 and r.listings_seen == 25
    assert any("27" in e.get("warning", "") for e in r.errors)
    assert conn.execute("select count(*) from listing_snapshots").fetchone()[0] == 25

def test_duplicate_id_across_pages_is_deduped(conn):
    p1 = make_page([make_card(i) for i in range(1, 21)], total_results=21, page=1, total_pages=2)
    p2 = make_page([make_card(20), make_card(21)], total_results=21, page=2, total_pages=2)
    r = run_scrape(conn, FakeFetcher({P1: [p1], P2: [p2]}), date(2026, 10, 24))
    assert r.listings_seen == 21 and conn.execute("select count(*) from listing_snapshots").fetchone()[0] == 21

def test_same_day_twice_is_idempotent(conn):
    pages = {P1: [fixture_html("page1")] * 2, P2: [fixture_html("page2")] * 2}
    f = FakeFetcher(pages)
    run_scrape(conn, f, date(2026, 10, 24)); run_scrape(conn, f, date(2026, 10, 24))
    assert conn.execute("select count(*) from listing_snapshots").fetchone()[0] == 27
    assert conn.execute("select count(*) from scrape_runs").fetchone()[0] == 2
    assert conn.execute("select count(distinct first_seen_date) from listings").fetchone()[0] == 1

def test_budget_exceeded_fails_run(conn):
    clock = iter([0.0, 500.0])  # started, then the check before page 2
    f = FakeFetcher({P1: [fixture_html("page1")], P2: [fixture_html("page2")]})
    with pytest.raises(ScrapeFailed, match="budget"):
        run_scrape(conn, f, date(2026, 10, 24), monotonic=lambda: next(clock))
    assert conn.execute("select count(*) from listing_snapshots").fetchone()[0] == 0

def test_too_many_pages_fails_run(conn):
    html = make_page([make_card(1)], total_results=300, page=1, total_pages=15)
    with pytest.raises(ScrapeFailed, match="pages"):
        run_scrape(conn, FakeFetcher({P1: [html]}), date(2026, 10, 24))

def test_budapest_today_rolls_over_at_local_midnight():
    from datetime import UTC, datetime
    assert budapest_today(datetime(2026, 10, 24, 22, 30, tzinfo=UTC)) == date(2026, 10, 25)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --env-file .env pytest tests/test_scrape.py -v`
Expected: FAIL with import error.

- [ ] **Step 3: Implement `scrape.py`**

Copy `budapest_today` and the `RunResult`/`ScrapeFailed` shape from store_watcher's `scrape.py`. Algorithm for `run_scrape` (this is the one body the tests do not fully determine):
1. `started = monotonic()`; `run_id = start_run(conn, run_date)`; `credits = 0`; `pages: list[ParsedPage] = []`; `errors: list[dict] = []`.
2. `_fetch_page(n)`: `url = page_url(search_url, n)`; try `fetcher.get(url)` + `parse_listing_page`; on `(FetchError, ParseError)` log a warning and try once more with `stealth=True`; add each successful `FetchResult.cost` to `credits`; a second failure propagates.
3. Page 1 via `_fetch_page(1)`. If `total_pages > MAX_PAGES` → fail with `f"too many pages: {total_pages}"`. For `n` in `2..total_pages`: if `monotonic() - started > budget_s` → fail with `"time budget exceeded"`; else `_fetch_page(n)`.
   Failure = `finish_run(conn, run_id, pages_ok=len(pages), pages_failed=1, listings_seen=0, total_results=<page1's if known>, credits_used=credits, errors=[{"page": n, "error": f"{type(e).__name__}: {e}"}])` then `raise ScrapeFailed(message) from e`. Nothing else is written.
4. Success: collect page warnings as `{"page": n, "warning": w}`; dedupe listings by `listing_id` keeping the first; if a page other than the last has fewer than `PAGE_SIZE` cards → warning `{"page": n, "warning": f"only {k} cards"}`; if `len(deduped) != total_results` → warning `{"warning": f"collected {len} listings but site reports {total_results}"}`.
5. `with conn.transaction(): for l in deduped: save_listing(conn, l, run_date)`; then `finish_run(... pages_ok=len(pages), pages_failed=0, listings_seen=len(deduped), total_results, credits_used=credits, errors)`; return `RunResult`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --env-file .env pytest tests/test_scrape.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/garage_watcher/scrape.py tests/test_scrape.py
git commit -m "feat: all-or-nothing daily scrape run with stealth retry"
```

---

### Task 7: HTTP handling and Vercel adapter

**Files:**
- Create: `src/garage_watcher/web.py`, `api/scrape.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `RunResult`, `ScrapeFailed`, `run_scrape`, `budapest_today`, `DEFAULT_SEARCH_URL` (Task 6); `ScrapingBeeFetcher` (Task 5); `db.connect` (Task 3).
- Produces:
  ```python
  def handle_scrape_request(auth_header: str | None, *, secret: str | None, database_url: str | None,
                            scrapingbee_key: str | None, search_url: str = DEFAULT_SEARCH_URL,
                            run: Callable[[str, str, str], RunResult] | None = None) -> tuple[int, dict]
  ```
  `run(database_url, scrapingbee_key, search_url)`; default opens a connection and calls `run_scrape(conn, ScrapingBeeFetcher(key), budapest_today(), search_url=search_url)`.

- [ ] **Step 1: Write the failing tests**

Port store_watcher's `tests/test_web.py`: `result()` builds `RunResult(run_id=1, run_date=date(2026,10,24), pages_ok=2, pages_failed=0, listings_seen=27, total_results=27, credits_used=50, errors=[])`; every call passes `scrapingbee_key="SB"`. Keep `test_rejects_when_secret_unset`, `test_rejects_wrong_token`, `test_rejects_missing_header`, `test_missing_database_url` (body `{"error": "DATABASE_URL not set"}`), `test_scrape_failed_returns_502`. Replace the 207 test and extend the success test:

```python
def test_missing_scrapingbee_key():
    status, body = handle_scrape_request(AUTH, secret="s3cret", database_url=URL, scrapingbee_key=None, run=lambda *a: result())
    assert (status, body) == (500, {"error": "SCRAPINGBEE_API_KEY not set"})

def test_success_returns_200_and_passes_config():
    seen = []
    def run(db, key, url): seen.append((db, key, url)); return result()
    status, body = handle_scrape_request(AUTH, secret="s3cret", database_url=URL, scrapingbee_key="SB", search_url="https://x/lista", run=run)
    assert status == 200 and seen == [(URL, "SB", "https://x/lista")]
    assert (body["listings_seen"], body["credits_used"], body["run_date"]) == (27, 50, "2026-10-24")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --env-file .env pytest tests/test_web.py -v`
Expected: FAIL with import error.

- [ ] **Step 3: Implement `web.py` and `api/scrape.py`**

`web.py` follows store_watcher's `web.py` with the extra config check (secret check first, then `DATABASE_URL`, then `SCRAPINGBEE_API_KEY`) and a flat 200 on success. `api/scrape.py` is store_watcher's adapter with `garage_watcher` imports and these extra keyword args: `scrapingbee_key=os.environ.get("SCRAPINGBEE_API_KEY")`, `search_url=os.environ.get("SEARCH_URL") or DEFAULT_SEARCH_URL`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --env-file .env pytest -v`
Expected: whole suite PASS.

- [ ] **Step 5: Commit**

```bash
git add src/garage_watcher/web.py api/scrape.py tests/test_web.py
git commit -m "feat: cron endpoint with bearer auth and Vercel adapter"
```

---

### Task 8: CLI, README, requirements, live acceptance

**Files:**
- Create: `src/garage_watcher/cli.py`, `README.md`, `requirements.txt`

**Interfaces:**
- Consumes: everything above.
- Produces: `garage-watcher migrate` and `garage-watcher scrape [--date YYYY-MM-DD] [--search-url URL]`; exit 2 on missing `DATABASE_URL` (or missing `SCRAPINGBEE_API_KEY` for `scrape`), 1 on `ScrapeFailed`, 0 otherwise.

- [ ] **Step 1: Implement `cli.py`**

Port store_watcher's `cli.py`: `scrape` adds `--search-url` (default `os.environ.get("SEARCH_URL") or DEFAULT_SEARCH_URL`), builds `ScrapingBeeFetcher(os.environ["SCRAPINGBEE_API_KEY"])`, prints `f"{r.run_date}: {r.pages_ok} pages, {r.listings_seen} listings, {r.credits_used} credits"` and one `warning:` line per entry in `r.errors`.

- [ ] **Step 2: Verify CLI config errors**

Run: `env -u DATABASE_URL uv run garage-watcher migrate; echo "exit $?"` and `env -u SCRAPINGBEE_API_KEY DATABASE_URL=postgresql://x uv run garage-watcher scrape; echo "exit $?"`
Expected: both print a one-line error to stderr and `exit 2`.

- [ ] **Step 3: Live acceptance run (costs ~50 ScrapingBee credits)**

Put the real key in `.env`. Run: `uv run --env-file .env garage-watcher migrate && uv run --env-file .env garage-watcher scrape`
Expected: two INFO lines with `Spb-cost`, final line `2026-MM-DD: 2 pages, 27 listings, 50 credits` (listing count may differ if the market changed; it must equal the site's total or come with a `warning:` line).

Run again, then: `uv run --env-file .env python -c "import psycopg,os;c=psycopg.connect(os.environ['DATABASE_URL']);print(c.execute('select count(*) from listing_snapshots').fetchone(), c.execute('select count(*) from scrape_runs where finished_at is not null').fetchone(), c.execute('select * from daily_availability').fetchall())"`
Expected: snapshot count equals listings seen (not doubled), 2 finished runs, one `daily_availability` row with that unit count and plausible averages (price tens of thousands HUF, area 10–25 m²).

- [ ] **Step 4: Generate requirements and README**

Run: `uv export --no-dev --no-hashes --no-emit-project -o requirements.txt`
Write `README.md` by adapting store_watcher's README: local setup (port 5434), env vars incl. `SCRAPINGBEE_API_KEY`/`SEARCH_URL`, deploy steps (Vercel project, Marketplace Postgres, set `CRON_SECRET` + `SCRAPINGBEE_API_KEY`, run `migrate` with the prod URL, `vercel deploy`, curl 401/200 check), response codes `200/502/401/500`, cost note (~50 credits/day), the "key was in a chat transcript, rotate it" reminder, and the four spec §4 queries under "Example queries" with the `left_censored` caveat.

- [ ] **Step 5: Full suite and commit**

Run: `uv run --env-file .env pytest -q`
Expected: all PASS.

```bash
git add src/garage_watcher/cli.py README.md requirements.txt uv.lock
git commit -m "feat: CLI, README and Vercel requirements"
```

- [ ] **Step 6: Deploy (owner's account)**

Owner creates the Vercel project, attaches Marketplace Postgres, sets `CRON_SECRET`, `SCRAPINGBEE_API_KEY` (then rotates the old key), runs `DATABASE_URL=<prod> uv run garage-watcher migrate`, `vercel deploy`. Verify `curl -i https://<app>/api/scrape` → 401 and with `-H "Authorization: Bearer $CRON_SECRET"` → 200 with `listings_seen` matching the site; next morning one new `scrape_runs` row with `finished_at` set.
