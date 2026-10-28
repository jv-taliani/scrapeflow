from decimal import Decimal

import boto3
import pytest

from scraper import storage
from scraper.config import Settings
from scraper.handlers import list_raw, reparse, summary
from scraper.http import FetchResult
from scraper.models import CrawlTask
from scraper.parsers import books
from tests.conftest import fixture_html

DETAIL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
INDEX = "https://books.toscrape.com/index.html"


def _save(settings: Settings, url: str, kind: str, html: str, run_id: str = "run-1") -> str:
    task = CrawlTask.model_validate(
        {"url": url, "source": "books", "kind": kind, "depth": 1, "run_id": run_id}
    )
    page = FetchResult(url=url, status_code=200, html=html, fetched_at="t")
    return storage.save_raw(settings, task, page)


def _latest(settings: Settings) -> dict[str, object]:
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(settings.items_table)
    item = table.get_item(Key={"pk": "books#a-light-in-the-attic_1000", "sk": "v#latest"})
    return item["Item"]


def test_list_raw_returns_keys_under_prefix(settings: Settings) -> None:
    key = _save(settings, DETAIL, "detail", fixture_html("books_detail.html"))
    _save(settings, DETAIL, "detail", "x", run_id="run-2")

    out = list_raw.handler({"source": "books", "prefix": "raw/books/run-1/"})

    assert out == {"source": "books", "prefix": "raw/books/run-1/", "keys": [key]}


def test_list_raw_defaults_to_whole_source(settings: Settings) -> None:
    _save(settings, DETAIL, "detail", "x")
    _save(settings, DETAIL, "detail", "x", run_id="run-2")
    assert len(list_raw.handler({"source": "books"})["keys"]) == 2


def test_list_raw_rejects_foreign_prefix(settings: Settings) -> None:
    with pytest.raises(ValueError, match="não pertence"):
        list_raw.handler({"source": "books", "prefix": "raw/quotes_js/"})


def test_reparse_rebuilds_item_from_s3_without_fetching(settings: Settings) -> None:
    key = _save(settings, DETAIL, "detail", fixture_html("books_detail.html"))

    first = reparse.handler({"source": "books", "key": key})
    again = reparse.handler({"source": "books", "key": key})

    assert first == {"key": key, "status": "ok", "created": 1}
    assert again == {"key": key, "status": "ok", "unchanged": 1}
    latest = _latest(settings)
    assert latest["raw_s3_key"] == key
    assert latest["run_id"] == "run-1"


def test_reparse_applies_parser_fix(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    key = _save(settings, DETAIL, "detail", fixture_html("books_detail.html"))
    monkeypatch.setattr(books, "_PRICE", __import__("re").compile(r"\d+"))
    reparse.handler({"source": "books", "key": key})
    assert _latest(settings)["price"] == Decimal("51")

    monkeypatch.undo()
    assert reparse.handler({"source": "books", "key": key})["updated"] == 1
    assert _latest(settings)["price"] == Decimal("51.77")


def test_reparse_listing_has_no_items(settings: Settings) -> None:
    key = _save(settings, INDEX, "listing", fixture_html("books_listing_page1.html"))
    assert reparse.handler({"source": "books", "key": key}) == {"key": key, "status": "ok"}


def test_summary_aggregates_results() -> None:
    out = summary.handler(
        {
            "source": "books",
            "prefix": "raw/books/run-1/",
            "results": [
                {"key": "a", "status": "ok", "created": 1},
                {"key": "b", "status": "ok", "unchanged": 1},
                {"key": "c", "status": "ok"},
                {"key": "d", "status": "error", "error": "ValueError"},
            ],
        }
    )
    assert out == {
        "source": "books",
        "prefix": "raw/books/run-1/",
        "pages": 4,
        "ok": 3,
        "error": 1,
        "created": 1,
        "updated": 0,
        "unchanged": 1,
        "errors": [{"key": "d", "error": "ValueError"}],
    }
