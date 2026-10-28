from functools import cache
from typing import TYPE_CHECKING, Any

import boto3

from scraper.config import Settings

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource
    from mypy_boto3_lambda.client import LambdaClient
    from mypy_boto3_s3.client import S3Client
    from mypy_boto3_sqs.client import SQSClient
    from mypy_boto3_stepfunctions.client import SFNClient


def _kwargs(settings: Settings) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"region_name": settings.region}
    if settings.endpoint_url:
        kwargs["endpoint_url"] = settings.endpoint_url
    return kwargs


@cache
def s3(settings: Settings) -> "S3Client":
    return boto3.client("s3", **_kwargs(settings))


@cache
def sqs(settings: Settings) -> "SQSClient":
    return boto3.client("sqs", **_kwargs(settings))


@cache
def dynamodb(settings: Settings) -> "DynamoDBServiceResource":
    return boto3.resource("dynamodb", **_kwargs(settings))


@cache
def stepfunctions(settings: Settings) -> "SFNClient":
    return boto3.client("stepfunctions", **_kwargs(settings))


@cache
def lambda_(settings: Settings) -> "LambdaClient":
    return boto3.client("lambda", **_kwargs(settings))


def clear_cache() -> None:
    for factory in (s3, sqs, dynamodb, stepfunctions, lambda_):
        factory.cache_clear()
