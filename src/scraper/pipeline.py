from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from scraper import queue, storage
from scraper.config import Settings
from scraper.models import CrawlTask, Item
from scraper.parsers import get_parser


@dataclass
class IngestResult:
    items: Counter[str] = field(default_factory=Counter)
    enqueued: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {**self.items, "enqueued": self.enqueued, "skipped": self.skipped}


def store_items(
    settings: Settings, source: str, items: Iterable[Item], raw_key: str, run_id: str
) -> Counter[str]:
    return Counter(storage.upsert_item(settings, source, it, raw_key, run_id) for it in items)


def schedule(settings: Settings, tasks: Iterable[CrawlTask]) -> tuple[int, int]:
    fresh: list[CrawlTask] = []
    skipped = 0
    for task in tasks:
        if task.depth > settings.max_depth or not storage.mark_seen(
            settings, task.run_id, task.url
        ):
            skipped += 1
            continue
        fresh.append(task)
    if fresh:
        queue.enqueue_batch(settings, fresh)
    return len(fresh), skipped


def ingest(settings: Settings, task: CrawlTask, html: str, raw_key: str) -> IngestResult:
    parsed = get_parser(task.source).parse(html, task)
    result = IngestResult(
        items=store_items(settings, task.source, parsed.items, raw_key, task.run_id)
    )
    result.enqueued, result.skipped = schedule(settings, parsed.next_tasks)
    return result
