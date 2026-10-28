import itertools
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT = (5, 20)
RETRY_STATUSES = (429, 500, 502, 503, 504)
USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0.0.0 Safari/537.36",
)


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    html: str
    fetched_at: str


class DomainThrottle:
    def __init__(
        self,
        min_interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, url: str) -> None:
        if self.min_interval <= 0:
            return
        domain = urlsplit(url).netloc
        with self._lock:
            last = self._last.get(domain)
            if last is not None:
                remaining = self.min_interval - (self._clock() - last)
                if remaining > 0:
                    self._sleep(remaining)
            self._last[domain] = self._clock()


class HttpClient:
    def __init__(
        self,
        throttle_seconds: float = 1.0,
        proxy_url: str | None = None,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
        backoff_factor: float = 1.0,
        user_agents: Iterable[str] = USER_AGENTS,
        session: requests.Session | None = None,
    ) -> None:
        self.timeout = timeout
        self.throttle = DomainThrottle(throttle_seconds)
        self._user_agents = itertools.cycle(tuple(user_agents))
        self.session = session or requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=backoff_factor,
            status_forcelist=RETRY_STATUSES,
            allowed_methods=frozenset({"GET", "HEAD"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        if proxy_url:
            self.session.proxies.update({"http": proxy_url, "https": proxy_url})

    def next_user_agent(self) -> str:
        return next(self._user_agents)

    def fetch(self, url: str) -> FetchResult:
        self.throttle.wait(url)
        response = self.session.get(
            url, timeout=self.timeout, headers={"User-Agent": self.next_user_agent()}
        )
        response.raise_for_status()
        if "charset" not in response.headers.get("Content-Type", "").lower():
            response.encoding = "utf-8"
        return FetchResult(
            url=response.url,
            status_code=response.status_code,
            html=response.text,
            fetched_at=datetime.now(UTC).isoformat(),
        )
