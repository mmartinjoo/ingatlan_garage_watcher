import argparse
import logging
import os
import sys
from datetime import date

from garage_watcher import db
from garage_watcher.fetch import ScrapingBeeFetcher
from garage_watcher.scrape import DEFAULT_SEARCH_URL, ScrapeFailed, budapest_today, run_scrape


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="garage-watcher")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply SQL migrations")
    scrape = sub.add_parser("scrape", help="record every listing of the search for a day")
    scrape.add_argument("--date", type=date.fromisoformat, help="YYYY-MM-DD (default: today, Budapest)")
    scrape.add_argument(
        "--search-url",
        default=os.environ.get("SEARCH_URL") or DEFAULT_SEARCH_URL,
        help="ingatlan.com list URL (default: $SEARCH_URL or the Szombathely garage search)",
    )
    args = parser.parse_args(argv)

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    if args.command == "migrate":
        with db.connect(url) as conn:
            for name in db.migrate(conn):
                print(f"applied {name}")
        return 0
    if args.command == "scrape":
        api_key = os.environ.get("SCRAPINGBEE_API_KEY")
        if not api_key:
            print("SCRAPINGBEE_API_KEY is not set", file=sys.stderr)
            return 2
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        run_date = args.date or budapest_today()
        with db.connect(url) as conn:
            try:
                r = run_scrape(conn, ScrapingBeeFetcher(api_key), run_date, search_url=args.search_url)
            except ScrapeFailed as e:
                print(f"scrape failed for {run_date}: {e}", file=sys.stderr)
                return 1
        print(f"{r.run_date}: {r.pages_ok} pages, {r.listings_seen} listings, {r.credits_used} credits")
        for entry in r.errors:
            print(f"warning: {entry}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
