import json
import os
import time
from collections.abc import Callable, Iterator
from typing import Any

import boto3
import pytest

pytestmark = pytest.mark.integration

ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
BUCKET = os.environ.get("SCRAPER_BUCKET", "scraper-raw-local")
WORKER = "scraper-worker"
MAX_PAGES = 3


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_ENDPOINT_URL": ENDPOINT,
    }.items():
        monkeypatch.setenv(name, value)


def client(name: str) -> Any:
    return boto3.client(name, endpoint_url=ENDPOINT, region_name="us-east-1")


def wait_until(check: Callable[[], Any], timeout: float = 180, every: float = 3) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result := check():
            return result
        time.sleep(every)
    raise AssertionError(f"condição não atingida em {timeout}s")


def _set_worker_env(lam: Any, env: dict[str, str]) -> None:
    lam.update_function_configuration(FunctionName=WORKER, Environment={"Variables": env})
    wait_until(
        lambda: (
            lam.get_function_configuration(FunctionName=WORKER)["LastUpdateStatus"] == "Successful"
        ),
        timeout=60,
        every=1,
    )


@pytest.fixture
def limited_worker() -> Iterator[None]:
    lam = client("lambda")
    original = lam.get_function_configuration(FunctionName=WORKER)["Environment"]["Variables"]
    _set_worker_env(lam, {**original, "MAX_PAGES": str(MAX_PAGES)})
    yield
    _set_worker_env(lam, original)


def _queue_idle(sqs: Any) -> bool:
    url = sqs.get_queue_url(QueueName="scraper-urls")["QueueUrl"]
    attrs = sqs.get_queue_attributes(
        QueueUrl=url,
        AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
    )["Attributes"]
    return (
        int(attrs["ApproximateNumberOfMessages"])
        + int(attrs["ApproximateNumberOfMessagesNotVisible"])
        == 0
    )


def test_crawl_then_reprocess(limited_worker: None) -> None:
    lam, s3, sqs, sfn = client("lambda"), client("s3"), client("sqs"), client("stepfunctions")
    ddb = boto3.resource("dynamodb", endpoint_url=ENDPOINT, region_name="us-east-1")

    resp = lam.invoke(FunctionName="scraper-producer", Payload=json.dumps({"source": "books"}))
    assert "FunctionError" not in resp
    run_id = json.loads(resp["Payload"].read())["run_id"]
    prefix = f"raw/books/{run_id}/"

    def raw_keys() -> list[str]:
        listing = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
        return [o["Key"] for o in listing.get("Contents", [])]

    wait_until(lambda: len(raw_keys()) >= MAX_PAGES)
    wait_until(lambda: _queue_idle(sqs))
    keys = raw_keys()
    assert len(keys) == MAX_PAGES

    table = ddb.Table("scraper-items")
    details = [
        s3.head_object(Bucket=BUCKET, Key=k)["Metadata"]
        for k in keys
        if s3.head_object(Bucket=BUCKET, Key=k)["Metadata"]["kind"] == "detail"
    ]
    assert details
    for meta in details:
        item_id = meta["url"].rstrip("/").split("/")[-2]
        item = table.get_item(Key={"pk": f"books#{item_id}", "sk": "v#latest"}).get("Item")
        assert item is not None, item_id
        assert item["url"] == meta["url"]

    arn = next(
        m["stateMachineArn"]
        for m in sfn.list_state_machines()["stateMachines"]
        if m["name"] == "scraper-reprocess"
    )
    execution = sfn.start_execution(
        stateMachineArn=arn, input=json.dumps({"source": "books", "prefix": prefix})
    )
    desc = wait_until(
        lambda: (
            (d := sfn.describe_execution(executionArn=execution["executionArn"]))["status"]
            != "RUNNING"
            and d
        )
    )
    assert desc["status"] == "SUCCEEDED"
    summary = json.loads(desc["output"])
    assert summary["pages"] == MAX_PAGES
    assert summary["error"] == 0
    assert summary["created"] + summary["updated"] == 0
