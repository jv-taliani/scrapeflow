from typing import Any

from scraper import storage
from scraper.config import Settings
from scraper.parsers import get_parser


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    source = event["source"]
    get_parser(source)
    prefix = event.get("prefix") or f"raw/{source}/"
    if not prefix.startswith(f"raw/{source}/"):
        raise ValueError(f"prefixo {prefix!r} não pertence à fonte {source!r}")
    keys = storage.list_raw(Settings.from_env(), prefix)
    return {"source": source, "prefix": prefix, "keys": keys}
