import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest
import requests
import requests_mock

from scraper.http import USER_AGENTS, DomainThrottle, HttpClient


class _Scripted(BaseHTTPRequestHandler):
    script: ClassVar[list[tuple[int, dict[str, str]]]] = []
    hits: ClassVar[list[float]] = []

    def do_GET(self) -> None:
        type(self).hits.append(time.monotonic())
        status, headers = type(self).script.pop(0) if type(self).script else (200, {})
        body = "ok £".encode() if status == 200 else b"err"
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def server() -> Iterator[str]:
    _Scripted.script = []
    _Scripted.hits = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Scripted)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/page"
    httpd.shutdown()


def test_retries_on_5xx_then_succeeds(server: str) -> None:
    _Scripted.script = [(503, {}), (502, {}), (200, {})]
    result = HttpClient(throttle_seconds=0, backoff_factor=0).fetch(server)

    assert result.status_code == 200
    assert result.html == "ok £"
    assert len(_Scripted.hits) == 3


def test_gives_up_after_three_retries(server: str) -> None:
    _Scripted.script = [(500, {})] * 5
    with pytest.raises(requests.HTTPError):
        HttpClient(throttle_seconds=0, backoff_factor=0).fetch(server)
    assert len(_Scripted.hits) == 4


def test_respects_retry_after_on_429(server: str) -> None:
    _Scripted.script = [(429, {"Retry-After": "1"}), (200, {})]
    HttpClient(throttle_seconds=0, backoff_factor=0).fetch(server)

    assert len(_Scripted.hits) == 2
    assert _Scripted.hits[1] - _Scripted.hits[0] >= 0.9


def test_404_is_not_retried(server: str) -> None:
    _Scripted.script = [(404, {})]
    with pytest.raises(requests.HTTPError):
        HttpClient(throttle_seconds=0, backoff_factor=0).fetch(server)
    assert len(_Scripted.hits) == 1


def test_rotates_user_agent_and_uses_timeout() -> None:
    client = HttpClient(throttle_seconds=0)
    with requests_mock.Mocker(session=client.session) as mock:
        mock.get("https://example.com/", text="hi", headers={"Content-Type": "text/html"})
        for _ in range(len(USER_AGENTS) + 1):
            client.fetch("https://example.com/")

    agents = [r.headers["User-Agent"] for r in mock.request_history]
    assert agents[: len(USER_AGENTS)] == list(USER_AGENTS)
    assert agents[-1] == USER_AGENTS[0]
    assert mock.request_history[0].timeout == (5, 20)


def test_respects_declared_charset() -> None:
    client = HttpClient(throttle_seconds=0)
    with requests_mock.Mocker(session=client.session) as mock:
        mock.get(
            "https://example.com/",
            content="ol\xe1".encode("latin-1"),
            headers={"Content-Type": "text/html; charset=ISO-8859-1"},
        )
        assert client.fetch("https://example.com/").html == "olá"


def test_proxy_is_optional() -> None:
    assert HttpClient().session.proxies == {}
    proxied = HttpClient(proxy_url="http://proxy:8080")
    assert proxied.session.proxies == {"http": "http://proxy:8080", "https": "http://proxy:8080"}


def test_throttle_is_per_domain() -> None:
    now = [100.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    throttle = DomainThrottle(1.0, clock=lambda: now[0], sleep=sleep)
    throttle.wait("https://a.com/1")
    now[0] += 0.25
    throttle.wait("https://a.com/2")
    throttle.wait("https://b.com/1")

    assert slept == [pytest.approx(0.75)]
