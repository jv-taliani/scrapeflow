from typing import Any

from scraper import storage
from scraper.config import Settings
from scraper.models import CrawlTask
from scraper.parsers import get_parser
from scraper.pipeline import store_items


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    settings = Settings.from_env()
    raw = storage.load_raw(settings, event["key"])
    meta = raw.metadata
    task = CrawlTask.model_validate(
        {
            "url": meta["url"],
            "source": event["source"],
            "kind": meta["kind"],
            "depth": int(meta.get("depth", "0")),
            "run_id": meta.get("run_id") or event["key"].split("/")[2],
        }
    )
    parsed = get_parser(task.source).parse(raw.html, task)
    counts = store_items(settings, task.source, parsed.items, raw.key, task.run_id)
    return {"key": raw.key, "status": "ok", **counts}
