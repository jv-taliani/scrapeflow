from decimal import Decimal

import pytest

from scraper.models import Book, CrawlTask
from scraper.parsers import get_parser, sources
from tests.conftest import fixture_html

DETAIL_URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"


def _task(url: str, kind: str, depth: int = 0) -> CrawlTask:
    return CrawlTask.model_validate(
        {"url": url, "source": "books", "kind": kind, "depth": depth, "run_id": "run-1"}
    )


def test_registry_knows_books() -> None:
    assert "books" in sources()
    with pytest.raises(KeyError):
        get_parser("nope")


def test_listing_yields_details_and_next_page() -> None:
    task = _task("https://books.toscrape.com/index.html", "listing")
    result = get_parser("books").parse(fixture_html("books_listing_page1.html"), task)

    details = [t for t in result.next_tasks if t.kind == "detail"]
    listings = [t for t in result.next_tasks if t.kind == "listing"]
    assert result.items == []
    assert len(details) == 20
    assert details[0].url == DETAIL_URL
    assert [t.url for t in listings] == ["https://books.toscrape.com/catalogue/page-2.html"]
    assert all(t.depth == 1 and t.run_id == "run-1" for t in result.next_tasks)


def test_last_listing_page_has_no_next() -> None:
    task = _task("https://books.toscrape.com/catalogue/page-50.html", "listing", depth=49)
    result = get_parser("books").parse(fixture_html("books_listing_last.html"), task)

    assert all(t.kind == "detail" for t in result.next_tasks)
    assert result.next_tasks[0].url.startswith("https://books.toscrape.com/catalogue/")
    assert "/catalogue/catalogue/" not in result.next_tasks[0].url


def test_detail_page_parses_book() -> None:
    result = get_parser("books").parse(
        fixture_html("books_detail.html"), _task(DETAIL_URL, "detail")
    )

    assert result.next_tasks == []
    [book] = result.items
    assert isinstance(book, Book)
    assert book.item_id == "a-light-in-the-attic_1000"
    assert book.title == "A Light in the Attic"
    assert book.price == Decimal("51.77")
    assert book.availability == 22
    assert book.rating == 3
    assert book.upc == "a897fe39b1053632"
    assert book.category == "Poetry"
    assert book.description and book.description.startswith("It's hard to imagine")
    assert book.image_url == (
        "https://books.toscrape.com/media/cache/fe/72/fe72f0532301ec28892ae79a629a293c.jpg"
    )
    assert book.tracked_price() == Decimal("51.77")


def test_detail_without_product_raises() -> None:
    with pytest.raises(ValueError, match="product_page"):
        get_parser("books").parse("<html><body>404</body></html>", _task(DETAIL_URL, "detail"))
