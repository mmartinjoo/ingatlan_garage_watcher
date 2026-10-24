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
