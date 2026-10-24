from datetime import date

from psycopg.types.json import Jsonb

from garage_watcher.parse import ParsedListing


def start_run(conn, run_date: date) -> int:
    run_id = conn.execute(
        "insert into scrape_runs (started_at, date) values (now(), %s) returning id",
        (run_date,),
    ).fetchone()[0]
    conn.commit()
    return run_id


def finish_run(
    conn,
    run_id: int,
    *,
    pages_ok: int,
    pages_failed: int,
    listings_seen: int,
    total_results: int | None,
    credits_used: int,
    errors: list[dict],
) -> None:
    conn.execute(
        "update scrape_runs set finished_at = now(), pages_ok = %s, pages_failed = %s, "
        "listings_seen = %s, total_results = %s, credits_used = %s, errors = %s where id = %s",
        (pages_ok, pages_failed, listings_seen, total_results, credits_used, Jsonb(errors), run_id),
    )
    conn.commit()


def save_listing(conn, listing: ParsedListing, run_date: date) -> None:
    """Upsert one listing and its snapshot for the day. The caller owns the transaction."""
    conn.execute(
        """
        insert into listings (id, url, address, city, first_seen_date, last_seen_date,
                              last_price_huf, last_area_m2)
        values (%s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (id) do update set
            url = excluded.url,
            address = excluded.address,
            city = excluded.city,
            last_seen_date = greatest(listings.last_seen_date, excluded.last_seen_date),
            last_price_huf = excluded.last_price_huf,
            last_area_m2 = excluded.last_area_m2
        """,
        (
            listing.listing_id, listing.url, listing.address, listing.city,
            run_date, run_date, listing.price_huf, listing.area_m2,
        ),
    )
    conn.execute(
        """
        insert into listing_snapshots (listing_id, date, price_huf, area_m2)
        values (%s, %s, %s, %s)
        on conflict (listing_id, date) do update set
            price_huf = excluded.price_huf,
            area_m2 = excluded.area_m2
        """,
        (listing.listing_id, run_date, listing.price_huf, listing.area_m2),
    )
