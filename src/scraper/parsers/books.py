import re
from decimal import Decimal
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from scraper.models import Book, CrawlTask
from scraper.parsers import register
from scraper.parsers.base import Parser, ParseResult

RATINGS = {"Zero": 0, "One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}
_PRICE = re.compile(r"[\d.]+")
_AVAILABLE = re.compile(r"\((\d+) available\)")


def _text(node: Node | None) -> str:
    return node.text(strip=True) if node is not None else ""


def _item_id(url: str) -> str:
    parts = [p for p in urlsplit(url).path.split("/") if p]
    if parts and parts[-1] == "index.html":
        parts.pop()
    return parts[-1]


@register
class BooksParser(Parser):
    source = "books"
    seeds = ("https://books.toscrape.com/index.html",)

    def parse(self, html: str, task: CrawlTask) -> ParseResult:
        tree = HTMLParser(html)
        if task.kind == "listing":
            return self._listing(tree, task)
        return ParseResult(items=[self._detail(tree, task)])

    def _listing(self, tree: HTMLParser, task: CrawlTask) -> ParseResult:
        result = ParseResult()
        for link in tree.css("article.product_pod h3 a"):
            href = link.attributes.get("href")
            if href:
                result.next_tasks.append(self.child(task, urljoin(task.url, href), "detail"))
        next_link = tree.css_first("li.next a")
        if next_link is not None and next_link.attributes.get("href"):
            href = next_link.attributes["href"] or ""
            result.next_tasks.append(self.child(task, urljoin(task.url, href), "listing"))
        return result

    def _detail(self, tree: HTMLParser, task: CrawlTask) -> Book:
        main = tree.css_first("article.product_page")
        if main is None:
            raise ValueError(f"página de detalhe sem article.product_page: {task.url}")
        info = {
            _text(row.css_first("th")): _text(row.css_first("td")) for row in main.css("table tr")
        }
        price = _PRICE.search(_text(main.css_first("p.price_color")))
        stock = _AVAILABLE.search(info.get("Availability", ""))
        rating_node = main.css_first("p.star-rating")
        rating_classes = (rating_node.attributes.get("class") or "").split() if rating_node else []
        crumbs = tree.css("ul.breadcrumb li a")
        description = main.css_first("#product_description + p")
        image = main.css_first("#product_gallery img")
        image_src = image.attributes.get("src") if image is not None else None
        return Book(
            item_id=_item_id(task.url),
            url=task.url,
            title=_text(main.css_first("h1")),
            price=Decimal(price.group()) if price else Decimal(0),
            availability=int(stock.group(1)) if stock else 0,
            rating=next((RATINGS[c] for c in rating_classes if c in RATINGS), 0),
            upc=info.get("UPC", ""),
            category=_text(crumbs[-1]) if len(crumbs) >= 3 else None,
            description=_text(description) or None,
            image_url=urljoin(task.url, image_src) if image_src else None,
        )
