import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from botocore.exceptions import ClientError

from scraper import aws
from scraper.config import Settings
from scraper.http import FetchResult
from scraper.models import CrawlTask, Item, url_hash

UpsertStatus = Literal["created", "updated", "unchanged"]


@dataclass(frozen=True)
class RawPage:
    key: str
    html: str
    metadata: dict[str, str]


def raw_key(source: str, run_id: str, url: str) -> str:
    return f"raw/{source}/{run_id}/{url_hash(url)}.html"


def content_hash(item: Item) -> str:
    payload = json.dumps(item.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _is_conditional_failure(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


def save_raw(settings: Settings, task: CrawlTask, page: FetchResult) -> str:
    key = raw_key(task.source, task.run_id, task.url)
    aws.s3(settings).put_object(
        Bucket=settings.bucket,
        Key=key,
        Body=page.html.encode("utf-8"),
        ContentType="text/html; charset=utf-8",
        Metadata={
            "url": task.url,
            "status_code": str(page.status_code),
            "fetched_at": page.fetched_at,
            "kind": task.kind,
            "source": task.source,
            "run_id": task.run_id,
            "depth": str(task.depth),
        },
    )
    return key


def load_raw(settings: Settings, key: str) -> RawPage:
    obj = aws.s3(settings).get_object(Bucket=settings.bucket, Key=key)
    metadata = {k.replace("-", "_"): v for k, v in obj["Metadata"].items()}
    return RawPage(key=key, html=obj["Body"].read().decode("utf-8"), metadata=metadata)


def list_raw(settings: Settings, prefix: str) -> list[str]:
    paginator = aws.s3(settings).get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=settings.bucket, Prefix=prefix):
        keys.extend(obj["Key"] for obj in page.get("Contents", []))
    return keys


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None and v != []}


def upsert_item(
    settings: Settings, source: str, item: Item, raw_s3_key: str, run_id: str
) -> UpsertStatus:
    table = aws.dynamodb(settings).Table(settings.items_table)
    digest = content_hash(item)
    now = datetime.now(UTC).isoformat()
    pk = f"{source}#{item.item_id}"
    record = _clean(item.model_dump(mode="python"))
    record.update(
        pk=pk,
        sk="v#latest",
        source=source,
        raw_s3_key=raw_s3_key,
        content_hash=digest,
        updated_at=now,
        run_id=run_id,
    )
    try:
        response = table.put_item(
            Item=record,
            ConditionExpression="attribute_not_exists(pk) OR content_hash <> :h",
            ExpressionAttributeValues={":h": digest},
            ReturnValues="ALL_OLD",
        )
    except ClientError as exc:
        if _is_conditional_failure(exc):
            return "unchanged"
        raise
    old = response.get("Attributes")
    price = item.tracked_price()
    if price is not None:
        old_price = old.get("price") if old else None
        if old_price is None or Decimal(str(old_price)) != price:
            table.put_item(Item={"pk": pk, "sk": f"price#{now}", "price": price, "run_id": run_id})
    return "updated" if old else "created"


def mark_seen(settings: Settings, run_id: str, url: str) -> bool:
    table = aws.dynamodb(settings).Table(settings.seen_table)
    try:
        table.put_item(
            Item={
                "pk": f"url#{run_id}#{url_hash(url)}",
                "url": url,
                "ttl": int(time.time()) + settings.seen_ttl_seconds,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except ClientError as exc:
        if _is_conditional_failure(exc):
            return False
        raise
    return True


def claim_page(settings: Settings, run_id: str) -> bool:
    table = aws.dynamodb(settings).Table(settings.seen_table)
    try:
        table.update_item(
            Key={"pk": f"run#{run_id}"},
            UpdateExpression="ADD pages :one SET #ttl = if_not_exists(#ttl, :ttl)",
            ConditionExpression="attribute_not_exists(pages) OR pages < :max",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={
                ":one": 1,
                ":max": settings.max_pages,
                ":ttl": int(time.time()) + settings.seen_ttl_seconds,
            },
        )
    except ClientError as exc:
        if _is_conditional_failure(exc):
            return False
        raise
    return True
