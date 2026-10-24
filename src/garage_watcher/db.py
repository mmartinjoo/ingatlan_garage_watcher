from importlib import resources

import psycopg


def connect(url: str) -> psycopg.Connection:
    # prepare_threshold=None disables server-side prepared statements so
    # pooled (pgbouncer-style) connection strings work.
    return psycopg.connect(url, prepare_threshold=None)


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply unapplied migrations in filename order; return the newly applied names."""
    conn.execute(
        "create table if not exists schema_migrations ("
        "name text primary key, applied_at timestamptz not null default now())"
    )
    applied = {r[0] for r in conn.execute("select name from schema_migrations")}
    files = sorted(
        (f for f in resources.files("garage_watcher.migrations").iterdir()
         if f.name.endswith(".sql")),
        key=lambda f: f.name,
    )
    newly_applied = []
    for f in files:
        if f.name in applied:
            continue
        conn.execute(f.read_text(encoding="utf-8"))
        conn.execute("insert into schema_migrations (name) values (%s)", (f.name,))
        newly_applied.append(f.name)
    conn.commit()
    return newly_applied
