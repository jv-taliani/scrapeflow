from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from scraper import aws
from scraper.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"
REGION = "us-east-1"


def fixture_html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)


@pytest.fixture
def settings() -> Iterator[Settings]:
    with mock_aws():
        aws.clear_cache()
        base = replace(Settings.from_env(), endpoint_url=None, region=REGION, throttle_seconds=0)
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=base.bucket)
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=base.items_table,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb.create_table(
            TableName=base.seen_table,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        sqs = boto3.client("sqs", region_name=REGION)
        queue_url = sqs.create_queue(QueueName="scraper-urls")["QueueUrl"]
        js_queue_url = sqs.create_queue(QueueName="scraper-urls-js")["QueueUrl"]
        yield replace(base, queue_url=queue_url, js_queue_url=js_queue_url)
        aws.clear_cache()
