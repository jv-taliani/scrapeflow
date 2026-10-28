from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from scraper.models import CrawlTask, new_run_id


def test_crawl_task_accepts_spec_message() -> None:
    task = CrawlTask.model_validate_json(
        '{"url": "https://books.toscrape.com/catalogue/page-2.html", "source": "books",'
        ' "kind": "listing", "depth": 1, "run_id": "2026-10-27T20-00-00Z", "attempt": 0}'
    )
    assert task.kind == "listing"
    assert len(task.url_hash) == 64


@pytest.mark.parametrize(
    "payload",
    [
        {"url": "not-a-url", "source": "books", "kind": "listing", "run_id": "r"},
        {"url": "https://x.com", "source": "books", "kind": "other", "run_id": "r"},
        {"url": "https://x.com", "source": "books", "kind": "detail", "run_id": "r", "depth": -1},
    ],
)
def test_crawl_task_rejects_invalid(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CrawlTask.model_validate(payload)


def test_run_id_format() -> None:
    assert new_run_id(datetime(2026, 10, 27, 20, 0, 0, tzinfo=UTC)) == "2026-10-27T20-00-00Z"
