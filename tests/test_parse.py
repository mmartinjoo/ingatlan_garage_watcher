from decimal import Decimal

import pytest

from conftest import fixture_html
from garage_watcher.parse import ParseError, parse_listing_page


def make_card(listing_id, price="30 000  Ft/hó", address="Szombathely, X utca", area="15 m<sup>2</sup>"):
    price_html = f'<span class="fw-bold fs-5 text-gray-900 me-2">{price}</span>' if price is not None else ""
    address_html = f'<span class="d-block fs-7 text-gray-900">{address}</span>' if address is not None else ""
    area_html = (
        f'<span class="fs-7 text-gray-400">Alapterület</span>'
        f'<span class="fs-6 text-gray-900 fw-bold">{area}</span>'
        if area is not None else ""
    )
    return (
        f'<a class="listing-card row" data-listing-id="{listing_id}" href="/{listing_id}">'
        f"<div>{price_html}{address_html}</div><div class=\"d-flex flex-column\">{area_html}</div></a>"
    )


def make_page(cards, total_results=27, page=1, total_pages=2, with_pagination=True, with_total_attr=True):
    total_attr = (
        f' data-listings-page--main-total-number-of-results-value="{total_results}"' if with_total_attr else ""
    )
    pagination = (
        f'<span class="text-gray-500">{page}</span><span class="text-gray-200"> / {total_pages}</span>'
        if with_pagination else ""
    )
    return f"<html><body><div{total_attr}>{''.join(cards)}{pagination}</div></body></html>"


def test_page1_counts_and_pagination():
    page = parse_listing_page(fixture_html("page1"))
    assert len(page.listings) == 20
    assert (page.page, page.total_pages, page.total_results) == (1, 2, 27)
    assert page.warnings == []


def test_page1_first_listing_fields():
    first = parse_listing_page(fixture_html("page1")).listings[0]
    assert first.listing_id == 35639715
    assert first.url == "https://ingatlan.com/35639715"
    assert first.price_huf == 30000
    assert first.address == "Szombathely, Jászai Mari utca"
    assert first.city == "Szombathely"
    assert first.area_m2 == Decimal("15")


def test_page2_is_last_page_and_disjoint():
    p1 = parse_listing_page(fixture_html("page1"))
    p2 = parse_listing_page(fixture_html("page2"))
    assert len(p2.listings) == 7
    assert (p2.page, p2.total_pages, p2.total_results) == (2, 2, 27)
    assert {l.listing_id for l in p1.listings}.isdisjoint({l.listing_id for l in p2.listings})
    assert all(l.price_huf and l.price_huf > 0 for l in p2.listings)
    assert all(l.area_m2 and l.area_m2 > 0 for l in p1.listings + p2.listings)


def test_unparseable_price_and_missing_area_are_none_with_warnings():
    page = parse_listing_page(make_page([make_card(1, price="100 €/hó", area=None)]))
    assert (page.listings[0].price_huf, page.listings[0].area_m2) == (None, None)
    assert any("price" in w for w in page.warnings) and any("area" in w for w in page.warnings)


def test_comma_decimal_area_and_address_without_comma():
    l = parse_listing_page(make_page([make_card(1, address="Szombathely", area="15,5 m<sup>2</sup>")])).listings[0]
    assert (l.address, l.city, l.area_m2) == ("Szombathely", "Szombathely", Decimal("15.5"))


def test_zero_cards_with_results_is_error():
    with pytest.raises(ParseError):
        parse_listing_page(make_page([], total_results=27))


def test_missing_total_attribute_is_error():
    with pytest.raises(ParseError):
        parse_listing_page(make_page([make_card(1)], with_total_attr=False))


def test_total_pages_falls_back_to_ceil_of_results():
    page = parse_listing_page(make_page([make_card(1)], total_results=27, with_pagination=False))
    assert (page.page, page.total_pages) == (1, 2)
