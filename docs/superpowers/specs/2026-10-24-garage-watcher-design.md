# Design: ingatlan_garage_watcher

Date: 2026-10-24. Status: approved by owner on 2026-10-24.

> **Change 2026-10-24 (owner):** the job runs **weekly** (cron `0 4 * * 1`, Mondays) instead of daily, and
> `days_listed` is the plain `last_seen_date - first_seen_date` (migration 003), no `+1`. Mentions of
> "daily" below are historical; the code itself has no cadence assumption.

## 1. Intent

A small daily tracker for "garage for rent in Szombathely" on ingatlan.com. It records which ads are on the
listing page each day, with price, address and area, into PostgreSQL. The value comes from running it every
day for months and then asking SQL questions. There is no UI.

Questions it must answer with plain SQL:

1. How many days, on average, until a garage ad disappears (proxy for "rented out").
2. How many units were available in a given month (e.g. September or December 2026).
3. Average monthly rent price.
4. Average area in m².

## 2. Goals, non-goals, anti-goals

Goals
- One run per day, fully automated, on Vercel.
- Every ad on every page of the search result is recorded with: ad ID, price (HUF/month), address, area (m²).
- Data model that makes the four questions one-query answers.
- Reuse the conventions of the sibling project `store_watcher` so both projects feel the same.

Non-goals
- No dashboards, charts, notifications or emails.
- No visiting ad detail pages. Only the list page is read.
- No photos, descriptions, seller info, labels ("Új építésű"), or map data.
- No multi-city support in v1 (the search URL is configurable, but one search per deployment).

Anti-goals (would make this a failure even if it technically works)
- Recording a day where some ads are missing because a page failed, which would make those ads look like
  they disappeared. A partial day must never be written.
- Recording a Cloudflare challenge page or an empty layout as "zero ads".
- Leaking the ScrapingBee key or database URL into the repo.

## 3. Constraints and findings (verified 2026-10-24)

- **Access.** ingatlan.com is behind a Cloudflare *interactive* challenge and its robots.txt disallows
  `/lista`. A plain HTTP request from a server gets 403. The owner chose to go through **ScrapingBee**;
  the risk that the site breaks this, and the ToS grey zone, are accepted by the owner.
- **ScrapingBee works for this URL.** Measured:
  - `premium_proxy=true, render_js=true, country_code=hu, wait_for=a[data-listing-id]` → 200, all cards, ~15 s, 25 credits.
  - `stealth_proxy=true, render_js=true` → 200, all cards, ~48 s, 75 credits.
  - Responses are ~5.5 MB because the headless browser inlines ~2 000 `data:image` URIs. Harmless.
- **Page structure** (identical in a logged-in browser and via ScrapingBee):
  - card: `a.listing-card[data-listing-id]`, `href="/<id>"`
  - price: `span.fw-bold.fs-5` in the card, e.g. `30 000  Ft/hó`
  - address: `span.d-block.fs-7` in the card, e.g. `Szombathely, Jászai Mari utca`
  - area: the `span.fs-6.fw-bold` after the `Alapterület` label, e.g. `15 m<sup>2</sup>`
  - pagination marker: `<span class="text-gray-500">1</span><span class="text-gray-200"> / 2</span>`
  - total results: attribute `data-listings-page--main-total-number-of-results-value="27"`
  - 20 cards per page; next page is `?page=N`. Today: 27 results, 2 pages.
- **Vercel.** Python runtime (3.12 default). Hobby plan: `maxDuration` up to 300 s, one daily cron is fine.
  Cron calls the path with GET and `Authorization: Bearer $CRON_SECRET`, always UTC.
- **Reference project.** `/Users/joomartin/code/dokkinger/store_watcher` defines the house style (section 6).

## 4. Data model

```sql
create table listings (
  id              bigint primary key,            -- ingatlan.com ad id
  url             text not null,                 -- https://ingatlan.com/<id>
  address         text not null,
  city            text,                          -- text before the first comma
  first_seen_date date not null,
  last_seen_date  date not null,
  last_price_huf  integer,
  last_area_m2    numeric(8,2)
);

create table listing_snapshots (                 -- one row per ad per successful run
  listing_id bigint not null references listings(id),
  date       date not null,
  price_huf  integer,
  area_m2    numeric(8,2),
  primary key (listing_id, date)
);
create index on listing_snapshots (date);

create table scrape_runs (                       -- audit row per run, finished_at null = killed mid-run
  id             serial primary key,
  started_at     timestamptz not null default now(),
  finished_at    timestamptz,
  date           date not null,                  -- Budapest local date
  pages_ok       integer not null default 0,
  pages_failed   integer not null default 0,
  listings_seen  integer not null default 0,
  total_results  integer,
  credits_used   integer,
  errors         jsonb not null default '[]'
);
```

Views (the product):

```sql
-- one row per ad with how long it was visible.
-- left_censored = already present on the very first run, true start unknown; exclude from averages.
create view listing_durations as
select l.id, l.address, l.city, l.last_price_huf, l.last_area_m2,
       l.first_seen_date, l.last_seen_date,
       (l.last_seen_date - l.first_seen_date) + 1 as days_listed,
       l.last_seen_date < (select max(date) from scrape_runs
                           where finished_at is not null and pages_failed = 0) as is_gone,
       l.first_seen_date = (select min(date) from scrape_runs
                            where finished_at is not null and pages_failed = 0) as left_censored
from listings l;

-- daily market summary straight from snapshots
create view daily_availability as
select date,
       count(*)                 as units,
       round(avg(price_huf))    as avg_price_huf,
       round(avg(area_m2), 1)   as avg_area_m2
from listing_snapshots
group by date;
```

The four questions:

```sql
-- 1. average days until an ad is pulled (excluding ads whose start we never saw)
select round(avg(days_listed), 1) from listing_durations where is_gone and not left_censored;
-- 2. units available per month (average of daily counts; also max/min are one keyword away)
select date_trunc('month', date) as month, round(avg(units)) as avg_units
from daily_availability group by 1 order by 1;
-- 3. average price per month
select date_trunc('month', date) as month, round(avg(avg_price_huf)) from daily_availability group by 1 order by 1;
-- 4. average area per month
select date_trunc('month', date) as month, round(avg(avg_area_m2), 1) from daily_availability group by 1 order by 1;
```

Semantics
- "Disappeared" = not present in the latest successful run. Days listed = last seen minus first seen, inclusive.
- An ad that vanishes and comes back under the same ID simply extends `last_seen_date`; the gap is visible
  in `listing_snapshots`. Reposts under a new ID are new listings (accepted limitation).
- Snapshots are only written for fully successful runs, so a failed day is a hole, never a false disappearance.

## 5. Behaviour of one run

1. Vercel cron fires `GET /api/scrape` daily at 04:00 UTC (05:00/06:00 Budapest). The run date is the
   Budapest local date.
2. Reject unless `Authorization: Bearer <CRON_SECRET>` matches (constant-time). 401 otherwise.
3. Insert a `scrape_runs` row immediately (so a killed run leaves `finished_at` null).
4. Fetch page 1 through ScrapingBee: premium proxy, JS rendering, `country_code=hu`,
   `wait_for=a[data-listing-id]`. On any failure (non-2xx, transport error, parse error) retry the same
   page once with the stealth proxy. Still failing → the run fails.
5. Parse: cards, price, address, area, current page, total pages, total results. Zero cards while
   `total_results > 0` is a hard parse error (challenge page or layout change), not "zero ads".
6. Determine total pages from the pagination marker, falling back to `ceil(total_results / 20)`.
   Fetch pages 2..N the same way. Hard cap 10 pages; time budget 240 s (below `maxDuration` 300).
7. **What counts as a complete day** (owner decision): a run is complete when every page returned 2xx and
   parsed with at least one card. A count mismatch (deduped ads ≠ `total_results`, or a non-last page with
   fewer than 20 cards) does **not** fail the run; the day is written and the mismatch is recorded as a
   warning string in the run row's `errors` list so odd days can be found in SQL. Hitting the 10-page cap
   or the 240 s budget fails the run.
   **All-or-nothing.** If every page succeeded: in one transaction, upsert `listings`
   (keep earliest `first_seen_date`, advance `last_seen_date`, refresh last price/area/address), upsert one
   `listing_snapshots` row per ad, finish the run row. Duplicate IDs across pages (ordering can shift
   between fetches) are deduped. If any page failed: finish the run row with the error, write no
   listing or snapshot rows, respond 502.
8. Response JSON mirrors the run row (`run_date, pages_ok, pages_failed, listings_seen, total_results,
   credits_used, errors`). 200 on success, 502 on failure, 500 on missing config, 401 on bad auth.

Parsing rules
- Price: keep digits only → integer HUF. Missing or non-numeric → `null` with a warning; the ad is still recorded.
- Area: the number before `m` → `numeric`. Missing → `null` with a warning.
- Address: whitespace-normalised text; `city` = text before the first comma.
- Encoding forced to UTF-8 (Hungarian accents).

## 6. Stack and conventions (decided; mirror `store_watcher`)

- Python 3.12, uv project (`pyproject.toml`, `uv.lock`, `uv_build` backend), `requirements.txt` generated
  with `uv export --no-dev --no-hashes --no-emit-project -o requirements.txt` for Vercel.
- Dependencies: `beautifulsoup4` (html.parser backend), `psycopg[binary]` (psycopg 3, no ORM), `requests`,
  `tzdata`. Dev: `pytest`. No ScrapingBee SDK; plain `requests` to `https://app.scrapingbee.com/api/v1/`.
- Layout:
  ```
  api/scrape.py                         # thin Vercel adapter, BaseHTTPRequestHandler subclass `handler`
  src/garage_watcher/
    fetch.py        # ScrapingBee client only (FetchError)
    parse.py        # pure functions, HTML in → frozen dataclasses out (ParseError)
    repository.py   # SQL upserts, run bookkeeping
    scrape.py       # the job (ScrapeFailed), budapest_today, time budget
    web.py          # auth + outcome → HTTP status
    db.py           # connect(prepare_threshold=None), migrate()
    cli.py          # `garage-watcher migrate | scrape [--date] [--search-url]`
    migrations/001_schema.sql, 002_views.sql
  tests/            # pytest, fakes as arguments (no mock lib), fixtures/page1.html page2.html
  docker-compose.yml, docker/initdb/01-test-db.sql   # postgres:16 on host port 5434 (5433 is store_watcher's), db + db_test
  vercel.json, .vercelignore, .env.example, README.md
  ```
- `vercel.json`: cron `0 4 * * *` → `/api/scrape`, `regions: ["fra1"]`, `functions.api/scrape.py.maxDuration: 300`.
  `pyproject.toml` has `[tool.vercel] entrypoint = "api.scrape:handler"`.
- Postgres from the Vercel Marketplace. Env: `DATABASE_URL` (fallback `POSTGRES_URL`), `TEST_DATABASE_URL`,
  `CRON_SECRET`, `SCRAPINGBEE_API_KEY`, optional `SEARCH_URL`
  (default `https://ingatlan.com/lista/kiado+garazs+szombathely`). `.env` is gitignored, loaded with
  `uv run --env-file .env`. Secrets live only in Vercel env vars and `.env`.
- Migrations: numbered SQL files tracked in `schema_migrations`, run by hand with the CLI (locally and
  against production). The cron function never migrates.
- Tests: fixture-driven parse tests on real saved pages; DB tests against Docker Postgres with a `conn`
  fixture that refuses to run unless the DB name ends in `_test`; fakes for the fetcher and session.
- Test fixtures: the two real ScrapingBee responses captured on 2026-10-24 (page 1: 20 cards, page 2: 7
  cards), currently at
  `/private/tmp/claude-501/-Users-joomartin-code-dokkinger-ingatlan-garage-watcher/a3dd56db-73bd-4b78-8697-8f394dcb30e7/scratchpad/sb_stealth.html`
  and `.../sb_prem.html`. Strip inlined base64 image payloads
  (`data:image/[a-z]+;base64,[A-Za-z0-9+/=]+` → `data:,`) before committing so each shrinks from 5.5 MB to
  a few hundred KB; verify card counts are still 20 and 7.
- Logging via `logging.getLogger(__name__)`; `Spb-cost` and `Spb-resolved-url` headers logged at INFO;
  unhandled errors `traceback.print_exc` to stderr in the Vercel adapter.

## 6a. What the builder has

- The ScrapingBee key is available in the implementation session (it will be put into `.env`, never the repo).
  Tests run on fixtures and cost nothing; live runs are limited to the acceptance checks (about 50 credits each).
- The fixture pages exist only in a session scratchpad: copying and stripping them into `tests/fixtures/`
  is the **first** implementation step. If they are gone, re-capture page 1 and 2 once via ScrapingBee.
- Vercel project, Marketplace Postgres and env vars are created by the owner in their account; the builder
  prepares everything so deploy is `vercel deploy` plus one migration command.

## 7. Operations

- Local Postgres listens on host port 5434 so it can run alongside `store_watcher` (5433).
- Local: `docker compose up -d`, `cp .env.example .env`, `uv sync`, `uv run --env-file .env garage-watcher migrate`,
  `uv run --env-file .env garage-watcher scrape`, `uv run --env-file .env pytest`.
- Deploy: create Vercel project, attach Marketplace Postgres, set `CRON_SECRET` and `SCRAPINGBEE_API_KEY`,
  run migrations from a laptop with the production `DATABASE_URL`, `vercel deploy`, confirm `curl` without
  the bearer → 401 and with it → 200 plus a new `scrape_runs` row.
- Cost: 2 pages × 25 credits ≈ 50 ScrapingBee credits/day (~1 500/month); a stealth retry adds 75 per page.
- Rotate the ScrapingBee key once it is in Vercel: it was pasted into a chat transcript during design.

## 8. Acceptance

- A local run against the live site records 27 listings (as of 2026-10-24), one finished run row, and a
  second run the same day changes nothing except `finished_at` on a new run row (idempotent upserts).
- Forcing page 2 to fail (fake fetcher in tests) yields a 502, a run row with the error, and zero new
  snapshot rows.
- `daily_availability` returns one row per run date; `listing_durations` flags first-day ads as `left_censored`.
- Test suite green; `uv export` output deploys on Vercel; the daily cron produces one run row per day.

## 9. Left to the builder

- Exact CSS selection of the area span (sibling walk vs. structural selector) as long as fixture tests pass.
- Whether `city` is a stored column (as above) or derived in the view.
- Retry/backoff details inside the budget; whether to send `block_resources` to shrink the response.
- README wording.

## 10. Calls made during design (owner can overrule)

- Premium proxy first, stealth only as retry (owner said "best proxy option"; premium already succeeds and is
  3× cheaper, stealth remains the fallback).
- All-or-nothing writes per run (derived from the anti-goal, not stated by owner).
- Count mismatches are warnings, not failures (owner's answer on 2026-10-24).
- Local Postgres on host port 5434 so both watcher projects can run at once.
- Keep `store_watcher` structure 1:1 including uv, psycopg 3, hand-run migrations.
- Cron at 04:00 UTC; `fra1` region.
- `SEARCH_URL` env var instead of hard-coding, but one search per deployment.
