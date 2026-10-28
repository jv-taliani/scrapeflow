from collections.abc import Sequence

from scraper import aws
from scraper.config import Settings
from scraper.models import CrawlTask
from scraper.parsers import get_parser

SQS_BATCH_LIMIT = 10


class EnqueueError(RuntimeError):
    pass


def queue_for(settings: Settings, source: str) -> str:
    return settings.js_queue_url if get_parser(source).requires_js else settings.queue_url


def enqueue(settings: Settings, task: CrawlTask, queue_url: str | None = None) -> None:
    aws.sqs(settings).send_message(
        QueueUrl=queue_url or queue_for(settings, task.source),
        MessageBody=task.model_dump_json(),
    )


def enqueue_batch(
    settings: Settings, tasks: Sequence[CrawlTask], queue_url: str | None = None
) -> int:
    client = aws.sqs(settings)
    failed: list[str] = []
    for start in range(0, len(tasks), SQS_BATCH_LIMIT):
        chunk = tasks[start : start + SQS_BATCH_LIMIT]
        by_queue: dict[str, list[tuple[str, CrawlTask]]] = {}
        for offset, task in enumerate(chunk):
            url = queue_url or queue_for(settings, task.source)
            by_queue.setdefault(url, []).append((str(start + offset), task))
        for url, entries in by_queue.items():
            response = client.send_message_batch(
                QueueUrl=url,
                Entries=[{"Id": i, "MessageBody": t.model_dump_json()} for i, t in entries],
            )
            failed.extend(entry["Id"] for entry in response.get("Failed", []))
    if failed:
        raise EnqueueError(f"{len(failed)} mensagens não enfileiradas: ids {failed}")
    return len(tasks)
