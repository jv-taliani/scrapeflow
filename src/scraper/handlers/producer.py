from typing import Any

from scraper.config import Settings
from scraper.logging import get_logger
from scraper.models import CrawlTask, new_run_id
from scraper.parsers import get_parser
from scraper.pipeline import schedule

log = get_logger(__name__)


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    settings = Settings.from_env()
    source = event["source"]
    parser = get_parser(source)
    run_id = event.get("run_id") or new_run_id()
    seeds = event.get("seeds") or list(parser.seeds)
    tasks = [
        CrawlTask.model_validate(
            {"url": url, "source": source, "kind": "listing", "run_id": run_id}
        )
        for url in seeds
    ]
    enqueued, skipped = schedule(settings, tasks)
    log.info(
        "seeds enfileiradas",
        extra={
            "run_id": run_id,
            "source": source,
            "data": {"enqueued": enqueued, "skipped": skipped},
        },
    )
    return {"run_id": run_id, "source": source, "enqueued": enqueued, "skipped": skipped}
