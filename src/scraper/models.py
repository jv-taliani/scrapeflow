import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def new_run_id(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H-%M-%SZ")


class CrawlTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    source: str
    kind: Literal["listing", "detail"]
    depth: int = Field(default=0, ge=0)
    run_id: str
    attempt: int = Field(default=0, ge=0)

    @field_validator("url")
    @classmethod
    def _valid_url(cls, value: str) -> str:
        return str(HttpUrl(value))

    @property
    def url_hash(self) -> str:
        return url_hash(self.url)


class Item(BaseModel):
    item_id: str
    url: str

    def tracked_price(self) -> Decimal | None:
        return None


class Book(Item):
    title: str
    price: Decimal
    currency: str = "GBP"
    availability: int
    rating: int = Field(ge=0, le=5)
    upc: str
    category: str | None = None
    description: str | None = None
    image_url: str | None = None

    def tracked_price(self) -> Decimal | None:
        return self.price


class Quote(Item):
    text: str
    author: str
    tags: list[str] = Field(default_factory=list)
