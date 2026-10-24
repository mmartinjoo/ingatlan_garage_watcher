"""Pure HTML parsing for ingatlan.com listing pages (no network, no DB)."""

import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup, Tag

BASE_URL = "https://ingatlan.com"
PAGE_SIZE = 20

TOTAL_ATTR = "data-listings-page--main-total-number-of-results-value"
AREA_LABEL = "Alapterület"


class ParseError(Exception):
    pass


@dataclass(frozen=True)
class ParsedListing:
    listing_id: int
    url: str
    address: str
    city: str
    price_huf: int | None
    area_m2: Decimal | None


@dataclass(frozen=True)
class ParsedPage:
    listings: list[ParsedListing]
    page: int
    total_pages: int
    total_results: int
    warnings: list[str]


def _norm(text: str) -> str:
    return " ".join(text.split())


def _text(node: Tag | None) -> str:
    return _norm(node.get_text(" ")) if node else ""


def _int(value: str | None) -> int | None:
    try:
        return int(value.strip()) if value and value.strip() else None
    except ValueError:
        return None


def _price_huf(text: str) -> int | None:
    if "Ft" not in text:
        return None
    digits = re.sub(r"\D", "", text.split("Ft")[0])
    return int(digits) if digits else None


def _area_m2(text: str) -> Decimal | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*m", text)
    if not m:
        return None
    try:
        return Decimal(m.group(1).replace(",", "."))
    except InvalidOperation:
        return None


def _area_text(card: Tag) -> str:
    for span in card.find_all("span"):
        if _text(span) == AREA_LABEL:
            return _text(span.find_next_sibling("span"))
    return ""


def _parse_card(card: Tag, warnings: list[str]) -> ParsedListing:
    listing_id = int(card["data-listing-id"])
    price_text = _text(card.select_one("span.fw-bold.fs-5"))
    price = _price_huf(price_text)
    if price is None:
        warnings.append(f"listing {listing_id}: unparseable price {price_text!r}")
    address = _text(card.select_one("span.d-block.fs-7"))
    city = address.split(",", 1)[0].strip() or address
    area = _area_m2(_area_text(card))
    if area is None:
        warnings.append(f"listing {listing_id}: missing area")
    return ParsedListing(
        listing_id=listing_id,
        url=f"{BASE_URL}/{listing_id}",
        address=address,
        city=city,
        price_huf=price,
        area_m2=area,
    )


def _pagination(soup: BeautifulSoup, total_results: int) -> tuple[int, int]:
    for marker in soup.select("span.text-gray-500 + span.text-gray-200"):
        m = re.fullmatch(r"/\s*(\d+)", _text(marker))
        current = _int(_text(marker.find_previous_sibling("span")))
        if m and current is not None:
            return current, int(m.group(1))
    return 1, max(1, math.ceil(total_results / PAGE_SIZE))


def parse_listing_page(html: str) -> ParsedPage:
    soup = BeautifulSoup(html, "html.parser")
    total_node = soup.select_one(f"[{TOTAL_ATTR}]")
    if total_node is None:
        raise ParseError("no total-results attribute; not a listing page")
    total_results = _int(total_node.get(TOTAL_ATTR))
    if total_results is None:
        raise ParseError(f"unparseable total-results attribute {total_node.get(TOTAL_ATTR)!r}")

    cards = soup.select("a.listing-card[data-listing-id]")
    if not cards and total_results > 0:
        raise ParseError(f"no listing cards but site reports {total_results} results")

    warnings: list[str] = []
    listings = [_parse_card(card, warnings) for card in cards]
    page, total_pages = _pagination(soup, total_results)
    return ParsedPage(
        listings=listings,
        page=page,
        total_pages=total_pages,
        total_results=total_results,
        warnings=warnings,
    )
