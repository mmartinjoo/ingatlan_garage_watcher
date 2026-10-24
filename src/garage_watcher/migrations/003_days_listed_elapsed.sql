-- days_listed = elapsed days between the first and last run that saw the ad (plain date difference).
-- Resolution equals the run cadence (weekly since 2026-10-24); an ad seen in a single run shows 0.
-- left_censored = already present on the very first run, true start unknown; exclude from averages.
create or replace view listing_durations as
select l.id, l.address, l.city, l.last_price_huf, l.last_area_m2,
       l.first_seen_date, l.last_seen_date,
       l.last_seen_date - l.first_seen_date as days_listed,
       l.last_seen_date < (select max(date) from scrape_runs
                           where finished_at is not null and pages_failed = 0) as is_gone,
       l.first_seen_date = (select min(date) from scrape_runs
                            where finished_at is not null and pages_failed = 0) as left_censored
from listings l;
