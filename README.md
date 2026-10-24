# garage-watcher

Weekly tracker for "garage for rent in Szombathely" on ingatlan.com. Every run records each ad on the
search result (id, price, address, area) into Postgres; two SQL views answer the market questions.
Runs as a weekly Vercel cron (`/api/scrape`, Mondays) or via the CLI. Pages are fetched through ScrapingBee because
ingatlan.com sits behind a Cloudflare challenge.

## Local setup

```sh
docker compose up -d            # Postgres on host port 5434 (also creates garage_watcher_test)
cp .env.example .env            # DATABASE_URL, TEST_DATABASE_URL, CRON_SECRET, SCRAPINGBEE_API_KEY, SEARCH_URL
uv sync
uv run --env-file .env garage-watcher migrate
uv run --env-file .env garage-watcher scrape           # optional: --date YYYY-MM-DD, --search-url URL
uv run --env-file .env pytest                          # TEST_DATABASE_URL is needed for DB tests
```

Tests run on saved fixture pages and cost no ScrapingBee credits. A live `scrape` costs about
50 credits (2 pages x 25), so roughly 200 credits a month at one run per week; a stealth retry adds
75 per page.

## Environment variables

| Name | Purpose |
| --- | --- |
| `DATABASE_URL` | Postgres connection string (falls back to `POSTGRES_URL`, which Vercel Marketplace sets) |
| `TEST_DATABASE_URL` | test database; its name must end in `_test` |
| `CRON_SECRET` | bearer token Vercel Cron sends as `Authorization: Bearer <secret>` |
| `SCRAPINGBEE_API_KEY` | ScrapingBee key; never commit it |
| `SEARCH_URL` | optional, default `https://ingatlan.com/lista/kiado+garazs+szombathely` |

## Deploy (Vercel)

1. Create the project and attach a Postgres database (Vercel Marketplace).
2. Set `CRON_SECRET` (long random string) and `SCRAPINGBEE_API_KEY`. Rotate the ScrapingBee key once it is
   in Vercel: the original was pasted into a chat transcript during design.
3. Run migrations locally against the production URL:
   `DATABASE_URL=<prod url> uv run garage-watcher migrate`
4. `vercel deploy`. The cron (`vercel.json`) fires every Monday at 04:00 UTC in `fra1`, `maxDuration` 300 s.
5. Verify: `curl -i https://<app>/api/scrape` returns 401; with the header (below) it returns 200 and a new
   row appears in `scrape_runs` with `listings_seen` matching the site's result count.

`requirements.txt` is for Vercel's installer. Re-generate it after changing dependencies:

```sh
uv export --no-dev --no-hashes --no-emit-project -o requirements.txt
```

## Manual trigger

```sh
curl -H "Authorization: Bearer $CRON_SECRET" https://<app>/api/scrape
```

## How a run works

Page 1 is fetched with ScrapingBee's premium proxy and JS rendering; on any failure (non-2xx, transport
error, or a page without listing cards such as a Cloudflare challenge) the same page is retried once with
the stealth proxy. Pages 2..N follow, up to 10 pages and a 240 s budget.

Writes are all-or-nothing: `listings` and `listing_snapshots` rows are written only when every page
succeeded, so a bad day is a hole in the data, never a false "ad disappeared". A count mismatch between
collected ads and the site's total is recorded as a warning in `scrape_runs.errors`, not a failure.
A `scrape_runs` row with `finished_at IS NULL` means the run was killed mid-way. A failed weekly run leaves
a two-week gap; the manual trigger below fills it on any other day and simply produces a row for that date.

Responses: `200` day recorded, `502` run failed (nothing written, see `error`), `401` bad or missing token,
`500` missing configuration or internal error.

## Example queries

`listing_durations` has one row per ad. `days_listed` is the plain difference between the last and first
run date that saw the ad, so with weekly runs it moves in 7-day steps and an ad seen in a single run shows 0
(it was really listed anywhere from 1 to 13 days). Ads that appear and vanish between two Monday runs are
never recorded. `left_censored` ads were already listed on the very first run, so their true start is
unknown and they must be excluded from duration averages. `daily_availability` has one row per recorded
run date (one per week).

```sql
-- 1. average elapsed days between first and last sighting of ads that are now gone
--    (excluding ads whose start we never saw)
select round(avg(days_listed), 1) from listing_durations where is_gone and not left_censored;

-- 2. units available per month (average of the weekly counts)
select date_trunc('month', date) as month, round(avg(units)) as avg_units
from daily_availability group by 1 order by 1;

-- 3. average price per month
select date_trunc('month', date) as month, round(avg(avg_price_huf)) as avg_price_huf
from daily_availability group by 1 order by 1;

-- 4. average area per month
select date_trunc('month', date) as month, round(avg(avg_area_m2), 1) as avg_area_m2
from daily_availability group by 1 order by 1;
```

## Known risks

ingatlan.com may change its layout (parse errors in `errors`) or block ScrapingBee. Its robots.txt
disallows `/lista`; the owner accepted the terms-of-service grey zone. Fixture pages in `tests/fixtures`
are real ScrapingBee responses from 2026-10-24 with scripts, images and the cookie dialog stripped.
