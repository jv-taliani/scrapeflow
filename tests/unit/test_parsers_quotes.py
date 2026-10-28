from scraper.models import CrawlTask, Quote
from scraper.parsers import get_parser
from tests.conftest import fixture_html

URL = "https://quotes.toscrape.com/js/"


def _task(url: str = URL, depth: int = 0) -> CrawlTask:
    return CrawlTask.model_validate(
        {"url": url, "source": "quotes_js", "kind": "listing", "depth": depth, "run_id": "r"}
    )


def test_quotes_js_is_routed_to_selenium() -> None:
    parser = get_parser("quotes_js")
    assert parser.requires_js is True
    assert parser.wait_for == "div.quote"


def test_rendered_page_yields_quotes_and_next_page() -> None:
    result = get_parser("quotes_js").parse(fixture_html("quotes_js_rendered.html"), _task())

    assert len(result.items) == 10
    first = result.items[0]
    assert isinstance(first, Quote)
    assert first.author == "Albert Einstein"
    assert first.text.startswith("“The world as we have created it")
    assert first.tags == ["change", "deep-thoughts", "thinking", "world"]
    assert [(t.url, t.depth) for t in result.next_tasks] == [
        ("https://quotes.toscrape.com/js/page/2/", 1)
    ]


def test_raw_html_falls_back_to_embedded_json() -> None:
    parser = get_parser("quotes_js")
    rendered = parser.parse(fixture_html("quotes_js_rendered.html"), _task())
    raw = parser.parse(fixture_html("quotes_js_raw.html"), _task())

    assert [q.model_dump() for q in raw.items] == [q.model_dump() for q in rendered.items]
    assert raw.next_tasks == rendered.next_tasks


def test_last_page_has_no_next() -> None:
    url = "https://quotes.toscrape.com/js/page/10/"
    result = get_parser("quotes_js").parse(fixture_html("quotes_js_raw_last.html"), _task(url, 9))

    assert result.items
    assert result.next_tasks == []


def test_page_without_quotes_yields_nothing() -> None:
    result = get_parser("quotes_js").parse("<html><body></body></html>", _task())
    assert result.items == []
    assert result.next_tasks == []
