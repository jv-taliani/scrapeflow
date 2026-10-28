import argparse
import json
import os
import sys
import time
from typing import Any

from scraper import aws
from scraper.config import Settings

PRODUCER = os.environ.get("SCRAPER_PRODUCER_FUNCTION", "scraper-producer")
STATE_MACHINE = os.environ.get("SCRAPER_STATE_MACHINE", "scraper-reprocess")


def _bucket(settings: Settings) -> str:
    if os.environ.get("SCRAPER_BUCKET"):
        return settings.bucket
    names = [b["Name"] for b in aws.s3(settings).list_buckets().get("Buckets", [])]
    return next((n for n in names if n.startswith("scraper-raw-")), settings.bucket)


def _resolve(settings: Settings) -> Settings:
    sqs = aws.sqs(settings)
    return Settings(
        **{
            **settings.__dict__,
            "bucket": _bucket(settings),
            "queue_url": settings.queue_url
            or sqs.get_queue_url(QueueName="scraper-urls")["QueueUrl"],
            "js_queue_url": settings.js_queue_url
            or sqs.get_queue_url(QueueName="scraper-urls-js")["QueueUrl"],
        }
    )


def crawl(settings: Settings, source: str) -> dict[str, Any]:
    resp = aws.lambda_(settings).invoke(
        FunctionName=PRODUCER, Payload=json.dumps({"source": source}).encode()
    )
    payload: dict[str, Any] = json.loads(resp["Payload"].read())
    if resp.get("FunctionError"):
        raise SystemExit(f"producer falhou: {payload}")
    return payload


def reprocess(settings: Settings, source: str, run_id: str) -> dict[str, Any]:
    if not run_id:
        raise SystemExit("informe RUN_ID=... (saída do make crawl)")
    sfn = aws.stepfunctions(settings)
    machines = sfn.list_state_machines()["stateMachines"]
    arn = next(m["stateMachineArn"] for m in machines if m["name"] == STATE_MACHINE)
    execution = sfn.start_execution(
        stateMachineArn=arn,
        input=json.dumps({"source": source, "prefix": f"raw/{source}/{run_id}/"}),
    )
    while (desc := sfn.describe_execution(executionArn=execution["executionArn"]))[
        "status"
    ] == "RUNNING":
        time.sleep(2)
    return {"status": desc["status"], "output": json.loads(desc.get("output") or "null")}


def _count_queue(settings: Settings, url: str) -> int:
    attrs = aws.sqs(settings).get_queue_attributes(
        QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages"]
    )["Attributes"]
    return int(attrs["ApproximateNumberOfMessages"])


def inspect(settings: Settings) -> dict[str, Any]:
    settings = _resolve(settings)
    table = aws.dynamodb(settings).Table(settings.items_table)
    counts: dict[str, int] = {}
    kwargs: dict[str, Any] = {"ProjectionExpression": "pk, sk"}
    while True:
        page = table.scan(**kwargs)
        for row in page["Items"]:
            if row["sk"] == "v#latest":
                source = str(row["pk"]).split("#", 1)[0]
                counts[source] = counts.get(source, 0) + 1
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    paginator = aws.s3(settings).get_paginator("list_objects_v2")
    objects = sum(
        p.get("KeyCount", 0) for p in paginator.paginate(Bucket=settings.bucket, Prefix="raw/")
    )
    sqs = aws.sqs(settings)
    queues = {}
    for name in ("scraper-urls", "scraper-urls-dlq", "scraper-urls-js", "scraper-urls-js-dlq"):
        queues[name] = _count_queue(settings, sqs.get_queue_url(QueueName=name)["QueueUrl"])
    return {"items": counts, "raw_objects": objects, "queues": queues}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="scraper")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("crawl").add_argument("--source", required=True)
    rep = sub.add_parser("reprocess")
    rep.add_argument("--source", required=True)
    rep.add_argument("--run-id", default="")
    sub.add_parser("inspect")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if args.cmd == "crawl":
        result = crawl(settings, args.source)
    elif args.cmd == "reprocess":
        result = reprocess(settings, args.source, args.run_id)
    else:
        result = inspect(settings)
    json.dump(result, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
