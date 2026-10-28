import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    return int(raw) if raw.strip() else default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    return float(raw) if raw.strip() else default


@dataclass(frozen=True)
class Settings:
    bucket: str
    items_table: str
    seen_table: str
    queue_url: str
    js_queue_url: str
    endpoint_url: str | None
    region: str
    max_depth: int
    max_pages: int
    throttle_seconds: float
    proxy_url: str | None
    seen_ttl_seconds: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            bucket=os.environ.get("SCRAPER_BUCKET", "scraper-raw-local"),
            items_table=os.environ.get("SCRAPER_ITEMS_TABLE", "scraper-items"),
            seen_table=os.environ.get("SCRAPER_SEEN_TABLE", "scraper-seen"),
            queue_url=os.environ.get("SCRAPER_QUEUE_URL", ""),
            js_queue_url=os.environ.get("SCRAPER_JS_QUEUE_URL", ""),
            endpoint_url=os.environ.get("AWS_ENDPOINT_URL") or None,
            region=os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
            max_depth=_int("MAX_DEPTH", 3),
            max_pages=_int("MAX_PAGES", 50),
            throttle_seconds=_float("SCRAPER_THROTTLE_SECONDS", 1.0),
            proxy_url=os.environ.get("SCRAPER_PROXY_URL") or None,
            seen_ttl_seconds=_int("SCRAPER_SEEN_TTL_SECONDS", 86400),
        )
