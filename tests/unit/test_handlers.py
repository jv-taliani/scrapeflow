import json
from collections.abc import Iterator

import boto3
import pytest
import requests_mock

from scraper.config import Settings
from scraper.handlers import producer, worker
from scraper.http import HttpClient
from tests.conftest import fixture_html

INDEX = "https://books.toscrape.com/index.html"
DETAIL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"


@pytest.fixture
def env(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("SCRAPER_QUEUE_URL", settings.queue_url)
    monkeypatch.setenv("SCRAPER_JS_QUEUE_URL", settings.js_queue_url)
    monkeypatch.setenv("SCRAPER_THROTTLE_SECONDS", "0")
    return Settings.from_env()


@pytest.fixture
def site() -> Iterator[requests_mock.Mocker]:
    client = HttpClient(throttle_seconds=0, backoff_factor=0)
    worker._client = client
    with requests_mock.Mocker(session=client.session) as mock:
        html = {"Content-Type": "text/html"}
        mock.get(INDEX, text=fixture_html("books_listing_page1.html"), headers=html)
        mock.get(DETAIL, text=fixture_html("books_detail.html"), headers=html)
        mock.get("https://books.toscrape.com/broken", status_code=404)
        yield mock
    worker._client = None


def _receive(url: str) -> list[dict[str, object]]:
    sqs = boto3.client("sqs", region_name="us-east-1")
    out: list[dict[str, object]] = []
    while msgs := sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10).get("Messages", []):
        for m in msgs:
            out.append(json.loads(m["Body"]))
            sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])
    return out


def _record(body: dict[str, object] | str, message_id: str = "m1") -> dict[str, object]:
    return {
        "messageId": message_id,
        "body": body if isinstance(body, str) else json.dumps(body),
        "attributes": {"ApproximateReceiveCount": "1"},
    }


def _task(url: str, kind: str, depth: int = 0) -> dict[str, object]:
    return {"url": url, "source": "books", "kind": kind, "depth": depth, "run_id": "run-1"}


def test_producer_enqueues_seeds_once_per_run(env: Settings) -> None:
    first = producer.handler({"source": "books", "run_id": "run-1"})
    again = producer.handler({"source": "books", "run_id": "run-1"})

    assert first == {"run_id": "run-1", "source": "books", "enqueued": 1, "skipped": 0}
    assert again["enqueued"] == 0
    [msg] = _receive(env.queue_url)
    assert msg == {**_task(INDEX, "listing"), "attempt": 0}


def test_producer_generates_run_id(env: Settings) -> None:
    assert producer.handler({"source": "books"})["run_id"].endswith("Z")


def test_worker_listing_saves_raw_and_enqueues_children(
    env: Settings, site: requests_mock.Mocker
) -> None:
    resp = worker.handler({"Records": [_record(_task(INDEX, "listing"))]})

    assert resp == {"batchItemFailures": []}
    keys = boto3.client("s3", region_name="us-east-1").list_objects_v2(Bucket=env.bucket)
    assert next(o["Key"] for o in keys["Contents"]).startswith("raw/books/run-1/")
    children = _receive(env.queue_url)
    assert len(children) == 21
    assert {c["depth"] for c in children} == {1}


def test_worker_detail_upserts_without_duplicates(
    env: Settings, site: requests_mock.Mocker
) -> None:
    event = {"Records": [_record(_task(DETAIL, "detail", depth=1))]}
    worker.handler(event)
    worker.handler(event)

    table = boto3.resource("dynamodb", region_name="us-east-1").Table(env.items_table)
    items = table.scan()["Items"]
    latest = [i for i in items if i["sk"] == "v#latest"]
    assert len(latest) == 1
    assert latest[0]["pk"] == "books#a-light-in-the-attic_1000"
    assert latest[0]["title"] == "A Light in the Attic"
    assert latest[0]["raw_s3_key"].startswith("raw/books/run-1/")
    assert sum(1 for i in items if i["sk"].startswith("price#")) == 1


def test_worker_reports_only_failed_messages(env: Settings, site: requests_mock.Mocker) -> None:
    event = {
        "Records": [
            _record(_task("https://books.toscrape.com/broken", "detail"), "bad-url"),
            _record("{not json", "bad-body"),
            _record(_task(DETAIL, "detail"), "good"),
        ]
    }
    resp = worker.handler(event)

    assert resp["batchItemFailures"] == [
        {"itemIdentifier": "bad-url"},
        {"itemIdentifier": "bad-body"},
    ]


def test_worker_respects_max_depth(
    env: Settings, site: requests_mock.Mocker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_DEPTH", "0")
    worker.handler({"Records": [_record(_task(INDEX, "listing"))]})
    assert _receive(env.queue_url) == []


def test_worker_stops_when_page_budget_is_exhausted(
    env: Settings, site: requests_mock.Mocker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_PAGES", "1")
    worker.handler({"Records": [_record(_task(INDEX, "listing"))]})
    _receive(env.queue_url)
    worker.handler({"Records": [_record(_task(DETAIL, "detail", depth=1))]})

    assert site.call_count == 1
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(env.items_table)
    assert not [i for i in table.scan()["Items"] if i["sk"] == "v#latest"]
