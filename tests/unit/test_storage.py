from dataclasses import replace
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

from scraper import storage
from scraper.config import Settings
from scraper.http import FetchResult
from scraper.models import Book, CrawlTask

URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"


def _task(run_id: str = "run-1") -> CrawlTask:
    return CrawlTask.model_validate(
        {"url": URL, "source": "books", "kind": "detail", "depth": 1, "run_id": run_id}
    )


def _book(price: str = "51.77", **overrides: object) -> Book:
    data: dict[str, object] = {
        "item_id": "a-light-in-the-attic_1000",
        "url": URL,
        "title": "A Light in the Attic",
        "price": Decimal(price),
        "availability": 22,
        "rating": 3,
        "upc": "a897fe39b1053632",
        "category": "Poetry",
    }
    data.update(overrides)
    return Book.model_validate(data)


def _rows(settings: Settings) -> list[dict[str, object]]:
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(settings.items_table)
    resp = table.query(KeyConditionExpression=Key("pk").eq("books#a-light-in-the-attic_1000"))
    return resp["Items"]


def test_save_and_load_raw_roundtrip(settings: Settings) -> None:
    page = FetchResult(url=URL, status_code=200, html="<p>£51.77</p>", fetched_at="2026-10-27")
    key = storage.save_raw(settings, _task(), page)

    assert key == f"raw/books/run-1/{_task().url_hash}.html"
    raw = storage.load_raw(settings, key)
    assert raw.html == "<p>£51.77</p>"
    assert raw.metadata["url"] == URL
    assert raw.metadata["status_code"] == "200"
    assert raw.metadata["kind"] == "detail"
    assert raw.metadata["fetched_at"] == "2026-10-27"
    assert storage.list_raw(settings, "raw/books/run-1/") == [key]
    assert storage.list_raw(settings, "raw/books/other/") == []


def test_upsert_is_idempotent(settings: Settings) -> None:
    assert storage.upsert_item(settings, "books", _book(), "k1", "run-1") == "created"
    assert storage.upsert_item(settings, "books", _book(), "k2", "run-2") == "unchanged"

    rows = _rows(settings)
    latest = next(r for r in rows if r["sk"] == "v#latest")
    assert latest["raw_s3_key"] == "k1"
    assert latest["price"] == Decimal("51.77")
    assert [r["sk"] for r in rows].count("v#latest") == 1
    assert sum(1 for r in rows if str(r["sk"]).startswith("price#")) == 1


def test_upsert_records_price_history_only_on_change(settings: Settings) -> None:
    storage.upsert_item(settings, "books", _book(), "k1", "run-1")
    assert storage.upsert_item(settings, "books", _book(availability=5), "k2", "run-2") == "updated"
    assert storage.upsert_item(settings, "books", _book("40.00"), "k3", "run-3") == "updated"

    rows = _rows(settings)
    history = sorted(r["price"] for r in rows if str(r["sk"]).startswith("price#"))
    assert history == [Decimal("40.00"), Decimal("51.77")]
    latest = next(r for r in rows if r["sk"] == "v#latest")
    assert latest["price"] == Decimal("40.00")
    assert latest["run_id"] == "run-3"


def test_mark_seen_dedups_within_run(settings: Settings) -> None:
    assert storage.mark_seen(settings, "run-1", URL) is True
    assert storage.mark_seen(settings, "run-1", URL) is False
    assert storage.mark_seen(settings, "run-2", URL) is True


def test_claim_page_respects_budget(settings: Settings) -> None:
    limited = replace(settings, max_pages=2)
    assert [storage.claim_page(limited, "run-1") for _ in range(3)] == [True, True, False]
    assert storage.claim_page(limited, "run-2") is True
