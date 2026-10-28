from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from scraper.models import CrawlTask, Item


@dataclass
class ParseResult:
    items: list[Item] = field(default_factory=list)
    next_tasks: list[CrawlTask] = field(default_factory=list)


class Parser(ABC):
    source: ClassVar[str]
    seeds: ClassVar[tuple[str, ...]]
    requires_js: ClassVar[bool] = False
    wait_for: ClassVar[str | None] = None

    @abstractmethod
    def parse(self, html: str, task: CrawlTask) -> ParseResult: ...

    def child(self, task: CrawlTask, url: str, kind: str) -> CrawlTask:
        return CrawlTask.model_validate(
            {
                "url": url,
                "source": task.source,
                "kind": kind,
                "depth": task.depth + 1,
                "run_id": task.run_id,
            }
        )
