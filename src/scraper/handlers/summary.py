from collections import Counter
from typing import Any

from scraper.logging import get_logger

log = get_logger(__name__)
UPSERT_FIELDS = ("created", "updated", "unchanged")


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    results: list[dict[str, Any]] = event.get("results", [])
    status = Counter(r.get("status", "error") for r in results)
    upserts = Counter({f: sum(int(r.get(f, 0)) for r in results) for f in UPSERT_FIELDS})
    errors = [
        {"key": r.get("key"), "error": r.get("error")} for r in results if r.get("status") != "ok"
    ]
    summary = {
        "source": event.get("source"),
        "prefix": event.get("prefix"),
        "pages": len(results),
        "ok": status["ok"],
        "error": len(errors),
        **upserts,
        "errors": errors[:50],
    }
    log.info("reprocessamento concluído", extra={"source": summary["source"], "data": summary})
    return summary
