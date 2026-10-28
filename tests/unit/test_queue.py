import json

import boto3
import pytest

from scraper import queue
from scraper.config import Settings
from scraper.models import CrawlTask


def _tasks(n: int) -> list[CrawlTask]:
    return [
        CrawlTask.model_validate(
            {
                "url": f"https://books.toscrape.com/p{i}",
                "source": "books",
                "kind": "detail",
                "run_id": "r",
            }
        )
        for i in range(n)
    ]


def _drain(url: str) -> list[dict[str, object]]:
    sqs = boto3.client("sqs", region_name="us-east-1")
    bodies: list[dict[str, object]] = []
    while True:
        resp = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10)
        msgs = resp.get("Messages", [])
        if not msgs:
            return bodies
        for m in msgs:
            bodies.append(json.loads(m["Body"]))
            sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])


def test_enqueue_batch_splits_in_chunks_of_ten(settings: Settings) -> None:
    assert queue.enqueue_batch(settings, _tasks(23)) == 23
    urls = {b["url"] for b in _drain(settings.queue_url)}
    assert len(urls) == 23


def test_enqueue_single(settings: Settings) -> None:
    queue.enqueue(settings, _tasks(1)[0])
    [body] = _drain(settings.queue_url)
    assert body["source"] == "books"
    assert body["attempt"] == 0


def test_enqueue_batch_raises_on_partial_failure(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        queue.aws.sqs(settings),
        "send_message_batch",
        lambda **kw: {"Successful": [], "Failed": [{"Id": "0", "SenderFault": False, "Code": "x"}]},
    )
    with pytest.raises(queue.EnqueueError):
        queue.enqueue_batch(settings, _tasks(1))
