from typing import Any

from scraper import storage
from scraper.config import Settings
from scraper.http import HttpClient
from scraper.logging import get_logger
from scraper.models import CrawlTask
from scraper.pipeline import ingest

log = get_logger(__name__)
_client: HttpClient | None = None


def http_client(settings: Settings) -> HttpClient:
    global _client
    if _client is None:
        _client = HttpClient(
            throttle_seconds=settings.throttle_seconds, proxy_url=settings.proxy_url
        )
    return _client


def process(settings: Settings, task: CrawlTask) -> dict[str, Any]:
    if not storage.claim_page(settings, task.run_id):
        return {"status": "budget_exhausted"}
    page = http_client(settings).fetch(task.url)
    key = storage.save_raw(settings, task, page)
    return {"status": "ok", "raw_s3_key": key, **ingest(settings, task, page.html, key).as_dict()}


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    settings = Settings.from_env()
    failures: list[dict[str, str]] = []
    for record in event.get("Records", []):
        message_id = record["messageId"]
        ctx: dict[str, Any] = {"message_id": message_id}
        try:
            task = CrawlTask.model_validate_json(record["body"])
            receives = int(record.get("attributes", {}).get("ApproximateReceiveCount", "1"))
            task = task.model_copy(update={"attempt": receives - 1})
            ctx.update(run_id=task.run_id, url=task.url, source=task.source, kind=task.kind)
            outcome = process(settings, task)
            log.info(
                "página processada", extra={**ctx, "data": {**outcome, "attempt": task.attempt}}
            )
        except Exception:
            log.exception("falha ao processar mensagem", extra=ctx)
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}
