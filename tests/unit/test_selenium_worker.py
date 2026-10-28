import json
from typing import Any

import boto3
import pytest
import requests_mock
from selenium_worker.main import HybridFetcher, SeleniumFetcher, Worker

from scraper.config import Settings
from scraper.http import FetchResult
from scraper.models import CrawlTask
from tests.conftest import fixture_html

URL = "https://quotes.toscrape.com/js/"
PAGE2 = "https://quotes.toscrape.com/js/page/2/"


class FakeDriver:
    def __init__(self, html: str) -> None:
        self.page_source = html
        self.current_url = ""
        self.visited: list[str] = []
        self.quit_called = False

    def get(self, url: str) -> None:
        self.visited.append(url)
        self.current_url = url

    def find_element(self, by: str, value: str) -> object:
        return object()

    def get_cookies(self) -> list[dict[str, Any]]:
        return [{"name": "sid", "value": "abc", "domain": "quotes.toscrape.com", "path": "/"}]

    def execute_script(self, script: str) -> str:
        return "FakeChrome/1.0"

    def quit(self) -> None:
        self.quit_called = True


def _task(url: str = URL) -> CrawlTask:
    return CrawlTask.model_validate(
        {"url": url, "source": "quotes_js", "kind": "listing", "run_id": "run-js"}
    )


def _message(body: str, receipt: str = "r1") -> Any:
    return {
        "MessageId": receipt,
        "ReceiptHandle": receipt,
        "Body": body,
        "Attributes": {"ApproximateReceiveCount": "1"},
    }


class StubFetcher:
    def __init__(self, html: str) -> None:
        self.html = html
        self.closed = False
        self.calls: list[tuple[str, str | None]] = []

    def fetch(self, task: CrawlTask, wait_for: str | None) -> FetchResult:
        self.calls.append((task.url, wait_for))
        return FetchResult(url=task.url, status_code=200, html=self.html, fetched_at="t")

    def close(self) -> None:
        self.closed = True


def test_selenium_fetcher_waits_and_returns_page_source() -> None:
    driver = FakeDriver("<div class='quote'></div>")
    fetcher = SeleniumFetcher(throttle_seconds=0, driver_factory=lambda: driver)  # type: ignore[arg-type,return-value]

    page = fetcher.fetch(_task(), "div.quote")
    fetcher.close()

    assert driver.visited == [URL]
    assert page.html == "<div class='quote'></div>"
    assert page.url == URL
    assert driver.quit_called


def test_hybrid_bootstraps_once_then_uses_requests(settings: Settings) -> None:
    driver = FakeDriver(fixture_html("quotes_js_rendered.html"))
    selenium = SeleniumFetcher(throttle_seconds=0, driver_factory=lambda: driver)  # type: ignore[arg-type,return-value]
    hybrid = HybridFetcher(selenium, settings)

    first = hybrid.fetch(_task(), "div.quote")
    assert driver.quit_called
    assert hybrid._http is not None
    with requests_mock.Mocker(session=hybrid._http.session) as mock:
        mock.get(
            PAGE2, text=fixture_html("quotes_js_raw.html"), headers={"Content-Type": "text/html"}
        )
        second = hybrid.fetch(_task(PAGE2), "div.quote")

    assert driver.visited == [URL]
    assert 'class="quote"' in first.html
    assert "var data" in second.html
    sent = mock.request_history[0]
    assert sent.headers["User-Agent"] == "FakeChrome/1.0"
    assert "sid=abc" in sent.headers["Cookie"]


def test_hybrid_rebootstraps_on_403(settings: Settings) -> None:
    drivers = [FakeDriver("<p>1</p>"), FakeDriver("<p>2</p>")]
    selenium = SeleniumFetcher(throttle_seconds=0, driver_factory=drivers.pop)  # type: ignore[arg-type]
    hybrid = HybridFetcher(selenium, settings)
    hybrid.fetch(_task(), None)
    assert hybrid._http is not None
    with requests_mock.Mocker(session=hybrid._http.session) as mock:
        mock.get(PAGE2, status_code=403)
        page = hybrid.fetch(_task(PAGE2), None)

    assert page.html == "<p>1</p>"
    assert drivers == []
    hybrid.close()
    assert hybrid._http is None


def _drain(url: str) -> list[dict[str, Any]]:
    sqs = boto3.client("sqs", region_name="us-east-1")
    out = []
    while msgs := sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10).get("Messages", []):
        for m in msgs:
            out.append(json.loads(m["Body"]))
            sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])
    return out


def test_worker_processes_js_queue_and_enqueues_next_page(settings: Settings) -> None:
    sqs = boto3.client("sqs", region_name="us-east-1")
    sqs.send_message(QueueUrl=settings.js_queue_url, MessageBody=_task().model_dump_json())
    fetcher = StubFetcher(fixture_html("quotes_js_rendered.html"))
    worker = Worker(settings, fetcher, wait_seconds=0)

    worker.run(once=True)

    assert fetcher.calls == [(URL, "div.quote")]
    assert fetcher.closed
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(settings.items_table)
    latest = [i for i in table.scan()["Items"] if i["sk"] == "v#latest"]
    assert len(latest) == 10
    assert all(str(i["pk"]).startswith("quotes_js#") for i in latest)
    assert [t["url"] for t in _drain(settings.js_queue_url)] == [PAGE2]


def test_worker_keeps_message_on_failure(settings: Settings) -> None:
    worker = Worker(settings, StubFetcher(""), wait_seconds=0)
    assert worker.handle(_message("{broken")) is False


def test_worker_returns_unprocessed_messages_when_stopping(settings: Settings) -> None:
    sqs = boto3.client("sqs", region_name="us-east-1")
    sqs.send_message(QueueUrl=settings.js_queue_url, MessageBody=_task().model_dump_json())
    fetcher = StubFetcher("")
    worker = Worker(settings, fetcher, wait_seconds=0)
    worker.stop()

    assert worker.poll_once() == 0
    assert fetcher.calls == []
    assert len(_drain(settings.js_queue_url)) == 1


@pytest.mark.parametrize("budget_left", [False])
def test_worker_skips_when_budget_exhausted(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, budget_left: bool
) -> None:
    monkeypatch.setattr("selenium_worker.main.storage.claim_page", lambda s, r: budget_left)
    fetcher = StubFetcher("")
    assert Worker(settings, fetcher, wait_seconds=0).handle(_message(_task().model_dump_json()))
    assert fetcher.calls == []
