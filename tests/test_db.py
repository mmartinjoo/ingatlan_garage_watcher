from garage_watcher.db import migrate


def test_migrate_applies_all_then_nothing(conn):
    assert migrate(conn) == []  # conftest already migrated
    names = [r[0] for r in conn.execute("select name from schema_migrations order by name")]
    assert names == ["001_schema.sql", "002_views.sql", "003_days_listed_elapsed.sql"]


def test_duration_views_on_two_runs(conn):
    conn.execute("insert into scrape_runs (date, finished_at) values ('2026-10-01', now()), ('2026-10-03', now())")
    conn.execute(
        """insert into listings (id, url, address, first_seen_date, last_seen_date, last_price_huf, last_area_m2) values
        (1, 'u', 'a', '2026-10-01', '2026-10-03', 30000, 15),
        (2, 'u', 'b', '2026-10-02', '2026-10-02', 40000, 20)"""
    )
    rows = {r[0]: r for r in conn.execute("select id, days_listed, is_gone, left_censored from listing_durations")}
    assert rows[1][1:] == (2, False, True)  # still listed, start unknown
    assert rows[2][1:] == (0, True, False)  # gone, start known; seen in one run only


def test_daily_availability_aggregates(conn):
    conn.execute(
        "insert into listings (id, url, address, first_seen_date, last_seen_date) values "
        "(1,'u','a','2026-10-01','2026-10-01'), (2,'u','b','2026-10-01','2026-10-01')"
    )
    conn.execute(
        "insert into listing_snapshots (listing_id, date, price_huf, area_m2) values "
        "(1,'2026-10-01',30000,15), (2,'2026-10-01',50000,20)"
    )
    units, price, area = conn.execute("select units, avg_price_huf, avg_area_m2 from daily_availability").fetchone()
    assert (units, price, float(area)) == (2, 40000, 17.5)
