import argparse
import os
import signal
from collections.abc import Callable
from datetime import UTC, datetime
from types import FrameType
from typing import TYPE_CHECKING, Any, Protocol

import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from scraper import aws, storage
from scraper.config import Settings
from scraper.http import DomainThrottle, FetchResult, HttpClient
from scraper.logging import get_logger
from scraper.models import CrawlTask
from scraper.parsers import get_parser
from scraper.pipeline import ingest

if TYPE_CHECKING:
    from mypy_boto3_sqs.type_defs import MessageTypeDef

log = get_logger("selenium_worker")
REBOOTSTRAP_STATUSES = (401, 403)


class Fetcher(Protocol):
    def fetch(self, task: CrawlTask, wait_for: str | None) -> FetchResult: ...

    def close(self) -> None: ...


def make_driver() -> WebDriver:
    options = webdriver.ChromeOptions()
    for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"):
        options.add_argument(arg)
    if binary := os.environ.get("CHROME_BIN"):
        options.binary_location = binary
    service = Service(executable_path=os.environ.get("CHROMEDRIVER") or None)
    driver = webdriver.Chrome(options=options, service=service)
    driver.set_page_load_timeout(30)
    return driver


class SeleniumFetcher:
    def __init__(
        self,
        throttle_seconds: float = 1.0,
        timeout: float = 15,
        driver_factory: Callable[[], WebDriver] = make_driver,
    ) -> None:
        self.timeout = timeout
        self.throttle = DomainThrottle(throttle_seconds)
        self._factory = driver_factory
        self._driver: WebDriver | None = None

    @property
    def driver(self) -> WebDriver:
        if self._driver is None:
            self._driver = self._factory()
        return self._driver

    def fetch(self, task: CrawlTask, wait_for: str | None) -> FetchResult:
        self.throttle.wait(task.url)
        self.driver.get(task.url)
        if wait_for:
            WebDriverWait(self.driver, self.timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, wait_for))
            )
        return FetchResult(
            url=self.driver.current_url,
            status_code=200,
            html=self.driver.page_source,
            fetched_at=datetime.now(UTC).isoformat(),
        )

    def close(self) -> None:
        if self._driver is not None:
            self._driver.quit()
            self._driver = None


def session_from_driver(driver: WebDriver) -> tuple[requests.Session, str]:
    session = requests.Session()
    for cookie in driver.get_cookies():
        session.cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain"),
            path=cookie.get("path", "/"),
        )
    user_agent = str(driver.execute_script("return navigator.userAgent"))
    return session, user_agent


class HybridFetcher:
    def __init__(self, selenium: SeleniumFetcher, settings: Settings) -> None:
        self.selenium = selenium
        self.settings = settings
        self._http: HttpClient | None = None

    def fetch(self, task: CrawlTask, wait_for: str | None) -> FetchResult:
        if self._http is None:
            return self._bootstrap(task, wait_for)
        try:
            return self._http.fetch(task.url)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status not in REBOOTSTRAP_STATUSES:
                raise
            log.info("sessão expirou, refazendo bootstrap", extra={"url": task.url})
            self._http = None
            return self._bootstrap(task, wait_for)

    def _bootstrap(self, task: CrawlTask, wait_for: str | None) -> FetchResult:
        page = self.selenium.fetch(task, wait_for)
        session, user_agent = session_from_driver(self.selenium.driver)
        self._http = HttpClient(
            throttle_seconds=self.settings.throttle_seconds,
            proxy_url=self.settings.proxy_url,
            user_agents=[user_agent],
            session=session,
        )
        self.selenium.close()
        log.info(
            "sessão capturada do navegador",
            extra={"url": task.url, "data": {"cookies": len(session.cookies)}},
        )
        return page

    def close(self) -> None:
        self.selenium.close()
        if self._http is not None:
            self._http.session.close()
            self._http = None


class Worker:
    def __init__(self, settings: Settings, fetcher: Fetcher, wait_seconds: int = 20) -> None:
        self.settings = settings
        self.fetcher = fetcher
        self.wait_seconds = wait_seconds
        self.stopping = False

    def stop(self, signum: int = signal.SIGTERM, frame: FrameType | None = None) -> None:
        log.info("sinal recebido, encerrando", extra={"data": {"signal": signum}})
        self.stopping = True

    def handle(self, message: "MessageTypeDef") -> bool:
        ctx: dict[str, Any] = {"message_id": message.get("MessageId")}
        try:
            task = CrawlTask.model_validate_json(message["Body"])
            receives = int(message.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
            task = task.model_copy(update={"attempt": receives - 1})
            ctx.update(run_id=task.run_id, url=task.url, source=task.source, kind=task.kind)
            if not storage.claim_page(self.settings, task.run_id):
                log.info("orçamento de páginas esgotado", extra=ctx)
                return True
            page = self.fetcher.fetch(task, get_parser(task.source).wait_for)
            key = storage.save_raw(self.settings, task, page)
            outcome = ingest(self.settings, task, page.html, key)
            log.info("página processada", extra={**ctx, "data": outcome.as_dict()})
            return True
        except Exception:
            log.exception("falha ao processar mensagem", extra=ctx)
            return False

    def poll_once(self) -> int:
        client = aws.sqs(self.settings)
        queue_url = self.settings.js_queue_url
        messages = client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=self.wait_seconds,
            AttributeNames=["ApproximateReceiveCount"],
        ).get("Messages", [])
        done = 0
        for message in messages:
            if self.stopping:
                client.change_message_visibility(
                    QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"], VisibilityTimeout=0
                )
                continue
            if self.handle(message):
                client.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
                done += 1
        return done

    def run(self, once: bool = False) -> None:
        try:
            while not self.stopping:
                self.poll_once()
                if once:
                    break
        finally:
            self.fetcher.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="selenium-worker")
    parser.add_argument(
        "--bootstrap-session",
        action="store_true",
        help="usa o Chrome só na primeira página e segue com requests usando os cookies dele",
    )
    parser.add_argument("--once", action="store_true", help="processa um único long poll e sai")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    selenium = SeleniumFetcher(throttle_seconds=settings.throttle_seconds)
    fetcher: Fetcher = HybridFetcher(selenium, settings) if args.bootstrap_session else selenium
    worker = Worker(settings, fetcher)
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    log.info("worker iniciado", extra={"data": {"hybrid": args.bootstrap_session}})
    worker.run(once=args.once)


if __name__ == "__main__":
    main()
