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
