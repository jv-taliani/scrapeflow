import hashlib
import json
import re
from typing import Any
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from scraper.models import CrawlTask, Quote
from scraper.parsers import register
from scraper.parsers.base import Parser, ParseResult

_EMBEDDED = re.compile(r"var\s+data\s*=\s*(\[.*?\]);\s*\n", re.DOTALL)


def _quote_id(author: str, text: str) -> str:
    return hashlib.sha256(f"{author}\n{text}".encode()).hexdigest()[:16]


@register
class QuotesJsParser(Parser):
    source = "quotes_js"
    seeds = ("https://quotes.toscrape.com/js/",)
    requires_js = True
    wait_for = "div.quote"

    def parse(self, html: str, task: CrawlTask) -> ParseResult:
        tree = HTMLParser(html)
        rows = self._rendered(tree) or self._embedded(html)
        result = ParseResult(
            items=[
                Quote(item_id=_quote_id(a, t), url=task.url, text=t, author=a, tags=tags)
                for t, a, tags in rows
            ]
        )
        next_link = tree.css_first("li.next a")
        href = next_link.attributes.get("href") if next_link is not None else None
        if href:
            result.next_tasks.append(self.child(task, urljoin(task.url, href), "listing"))
        return result

    def _rendered(self, tree: HTMLParser) -> list[tuple[str, str, list[str]]]:
        rows = []
        for node in tree.css("div.quote"):
            text = node.css_first("span.text")
            author = node.css_first("small.author")
            if text is None or author is None:
                continue
            tags = [t.text(strip=True) for t in node.css("a.tag")]
            rows.append((text.text(strip=True), author.text(strip=True), tags))
        return rows

    def _embedded(self, html: str) -> list[tuple[str, str, list[str]]]:
        match = _EMBEDDED.search(html)
        if match is None:
            return []
        data: list[dict[str, Any]] = json.loads(match.group(1))
        return [(d["text"], d["author"]["name"], list(d.get("tags", []))) for d in data]
