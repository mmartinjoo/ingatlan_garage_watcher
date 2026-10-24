import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

from garage_watcher.db import connect, migrate

FIXTURES = Path(__file__).parent / "fixtures"

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://garage_watcher:garage_watcher@localhost:5434/garage_watcher_test",
)


def fixture_html(name: str) -> str:
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")


@pytest.fixture
def conn():
    """Fresh, fully migrated schema for every test."""
    db_name = urlparse(TEST_DATABASE_URL).path.lstrip("/")
    if not db_name.endswith("_test"):
        pytest.fail(
            f"Refusing to drop schema: TEST_DATABASE_URL database {db_name!r} "
            "does not end in '_test'.",
            pytrace=False,
        )
    c = connect(TEST_DATABASE_URL)
    c.execute("drop schema public cascade")
    c.execute("create schema public")
    c.commit()
    migrate(c)
    yield c
    c.rollback()
    c.close()
