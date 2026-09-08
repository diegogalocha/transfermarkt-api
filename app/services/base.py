import base64
import random
import time
from dataclasses import dataclass, field
from typing import Optional
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup
from fastapi import HTTPException
from lxml import etree
from requests import Response, TooManyRedirects
from requests.exceptions import Timeout

from app.settings import settings
from app.utils.utils import trim
from app.utils.xpath import Pagination

MAX_RETRIES = 3
RETRY_BACKOFF = [1, 2, 4]  # seconds between attempts (transient errors)
RETRY_ON_STATUS = {403, 429, 500, 502, 503, 504}

# Statuses that indicate Transfermarkt is serving an anti-bot challenge
# (WAF/Cloudflare "confirm you are human"). These do NOT clear within the
# lifetime of a request, so we fail fast instead of retrying: retrying the
# same flagged IP only makes the caller hang. Request spacing is handled by
# the upstream scheduler (jitter/long delays), not here.
BLOCK_ON_STATUS = {405}

# When Zyte is enabled in "fallback" mode, these upstream statuses trigger a
# retry through Zyte (anti-bot / rate-limit responses from Transfermarkt).
ZYTE_FALLBACK_STATUS = {403, 405, 429}
ZYTE_ENDPOINT = "https://api.zyte.com/v1/extract"
ZYTE_TIMEOUT = 60  # Zyte (esp. browser rendering) can be slower than a direct GET

# Pool of realistic, up-to-date desktop User-Agents. One is picked at random per
# request so we don't fingerprint every request with the same stale UA.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:130.0) "
    "Gecko/20100101 Firefox/130.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) "
    "Gecko/20100101 Firefox/130.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]


def _random_user_agent() -> str:
    """Return a random realistic desktop User-Agent string."""
    return random.choice(USER_AGENTS)


@dataclass
class TransfermarktBase:
    """
    Base class for making HTTP requests to Transfermarkt and extracting data from the web pages.

    Args:
        URL (str): The URL for the web page to be fetched.
    Attributes:
        page (ElementTree): The parsed web page content.
        response (dict): A dictionary to store the response data.
    """

    URL: str
    page: ElementTree = field(default_factory=lambda: None, init=False)
    response: dict = field(default_factory=lambda: {}, init=False)

    def make_request(self, url: Optional[str] = None) -> Response:
        """
        Make an HTTP GET request to the specified URL, with automatic retries on transient errors.

        Args:
            url (str, optional): The URL to make the request to. If not provided, the class's URL
                attribute will be used.

        Returns:
            Response: An HTTP Response object containing the server's response to the request.

        Raises:
            HTTPException: If there are too many redirects, or if the server returns a client or
                server error status code after all retries are exhausted.
        """
        url = self.URL if not url else url
        last_exception: Optional[HTTPException] = None

        for attempt in range(MAX_RETRIES):
            try:
                response: Response = requests.get(
                    url=url,
                    headers={
                        "User-Agent": _random_user_agent(),
                        "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
                    },
                    timeout=10,  # 10 seconds timeout for Transfermarkt requests
                )
            except Timeout:
                last_exception = HTTPException(status_code=504, detail=f"Request timeout for url: {url}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(self._backoff_seconds(RETRY_BACKOFF, attempt))
                    continue
                raise last_exception
            except TooManyRedirects:
                raise HTTPException(status_code=404, detail=f"Not found for url: {url}")
            except ConnectionError:
                last_exception = HTTPException(status_code=500, detail=f"Connection error for url: {url}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(self._backoff_seconds(RETRY_BACKOFF, attempt))
                    continue
                raise last_exception
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error for url: {url}. {e}")

            # Transfermarkt is serving an anti-bot challenge (WAF/Cloudflare).
            # Fail fast: this will not clear within the request, so retrying only
            # makes the caller hang until its own timeout.
            if response.status_code in BLOCK_ON_STATUS:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=(
                        f"Blocked by Transfermarkt anti-bot challenge ({response.status_code}). "
                        f"{response.reason} for url: {url}"
                    ),
                )

            if response.status_code in RETRY_ON_STATUS:
                last_exception = HTTPException(
                    status_code=response.status_code,
                    detail=f"Retryable error ({response.status_code}). {response.reason} for url: {url}",
                )
                if attempt < MAX_RETRIES - 1:
                    time.sleep(self._backoff_seconds(RETRY_BACKOFF, attempt))
                    continue
                raise last_exception

            if 400 <= response.status_code < 500:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Client Error. {response.reason} for url: {url}",
                )

            return response

        raise last_exception

    @staticmethod
    def _backoff_seconds(schedule: list, attempt: int) -> float:
        """Return the backoff for the given attempt plus random jitter.

        Jitter (0-1s) desynchronises concurrent workers so they don't all retry
        at the exact same instant and re-trigger the block.
        """
        base = schedule[attempt] if attempt < len(schedule) else schedule[-1]
        return base + random.uniform(0, 1)

    def _zyte_post(self, url: str, payload: dict) -> dict:
        """POST to the Zyte API and return the parsed JSON, raising on failure."""
        if settings.ZYTE_GEOLOCATION:
            payload["geolocation"] = settings.ZYTE_GEOLOCATION
        try:
            response = requests.post(
                ZYTE_ENDPOINT,
                auth=(settings.ZYTE_API_KEY, ""),
                json=payload,
                timeout=ZYTE_TIMEOUT,
            )
        except Timeout:
            raise HTTPException(status_code=504, detail=f"Zyte timeout for url: {url}")
        except Exception as error:
            raise HTTPException(status_code=502, detail=f"Zyte request error for url: {url}. {error}")

        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Zyte error ({response.status_code}) for url: {url}. {response.text[:200]}",
            )
        return response.json()

    def _fetch_via_zyte_browser(self, url: str) -> bytes:
        """Fetch a browser-rendered page through Zyte (robust against Cloudflare)."""
        data = self._zyte_post(
            url,
            {"url": url, "browserHtml": True, "requestHeaders": {"referer": "https://www.transfermarkt.com/"}},
        )
        html = data.get("browserHtml")
        if not html:
            raise HTTPException(status_code=502, detail=f"Zyte returned no browserHtml for url: {url}")
        print(f"[fetch] via Zyte (browser) -> {url}")
        return html.encode("utf-8")

    def _fetch_via_zyte(self, url: str) -> bytes:
        """
        Fetch a page through the Zyte API (handles proxies, bans and anti-bot
        challenges). Returns the raw HTML bytes.

        Strategy:
        - If ZYTE_RENDER is on, always use browser rendering.
        - Otherwise try the cheaper httpResponseBody first. Transfermarkt serves
          an anti-bot soft-block as a non-200 status (e.g. 202) on some proxies;
          in that case we escalate to browser rendering, which reliably passes.

        Accept-Language is forced to English on the HTTP path so the returned
        markup matches the (English) XPath selectors used across the app.

        Raises:
            HTTPException: If the Zyte request fails or returns no usable body.
        """
        if settings.ZYTE_RENDER:
            return self._fetch_via_zyte_browser(url)

        data = self._zyte_post(
            url,
            {
                "url": url,
                "httpResponseBody": True,
                "customHttpRequestHeaders": [{"name": "Accept-Language", "value": "en-US,en;q=0.9"}],
            },
        )
        body_b64 = data.get("httpResponseBody")
        tm_status = data.get("statusCode")
        if body_b64 and tm_status == 200:
            print(f"[fetch] via Zyte (http) -> {url}")
            return base64.b64decode(body_b64)

        # Anti-bot soft-block over plain HTTP -> escalate to a real browser.
        print(f"[Zyte] httpResponseBody returned Transfermarkt status {tm_status}; escalating to browser for {url}")
        return self._fetch_via_zyte_browser(url)

    def _get_page_bytes(self, url: Optional[str] = None) -> bytes:
        """
        Return the HTML bytes for the given URL applying the configured fetch
        strategy (ZYTE_MODE):

        - "off": direct request only.
        - "always": every request goes through Zyte.
        - "fallback": direct request first; on an anti-bot block (see
          ZYTE_FALLBACK_STATUS) retry through Zyte.

        If Zyte is requested but no API key is configured, behaves like "off".
        """
        url = self.URL if not url else url
        mode = (settings.ZYTE_MODE or "off").lower()
        zyte_ready = bool(settings.ZYTE_API_KEY)

        if mode == "always" and zyte_ready:
            return self._fetch_via_zyte(url)

        try:
            response: Response = self.make_request(url)
            print(f"[fetch] organic (direct) -> {url}")
            return response.content
        except HTTPException as error:
            if mode == "fallback" and zyte_ready and error.status_code in ZYTE_FALLBACK_STATUS:
                print(f"[Zyte] Direct request blocked ({error.status_code}); falling back to Zyte for {url}")
                return self._fetch_via_zyte(url)
            raise

    def request_url_bsoup(self) -> BeautifulSoup:
        """
        Fetch the web page content and parse it using BeautifulSoup.

        Returns:
            BeautifulSoup: A BeautifulSoup object representing the parsed web page content.

        Raises:
            HTTPException: If there are too many redirects, or if the server returns a client or
                server error status code.
        """
        content: bytes = self._get_page_bytes()
        return BeautifulSoup(markup=content, features="html.parser")

    @staticmethod
    def convert_bsoup_to_page(bsoup: BeautifulSoup) -> ElementTree:
        """
        Convert a BeautifulSoup object to an ElementTree.

        Args:
            bsoup (BeautifulSoup): The BeautifulSoup object representing the parsed web page content.

        Returns:
            ElementTree: An ElementTree representing the parsed web page content for further processing.
        """
        return etree.HTML(str(bsoup))

    def request_url_page(self) -> ElementTree:
        """
        Fetch the web page content, parse it using BeautifulSoup, and convert it to an ElementTree.

        Returns:
            ElementTree: An ElementTree representing the parsed web page content for further
                processing.

        Raises:
            HTTPException: If there are too many redirects, or if the server returns a client or
                server error status code.
        """
        bsoup: BeautifulSoup = self.request_url_bsoup()
        return self.convert_bsoup_to_page(bsoup=bsoup)

    def raise_exception_if_not_found(self, xpath: str):
        """
        Raise an exception if the specified XPath does not yield any results on the web page.

        Args:
            xpath (str): The XPath expression to query elements on the page.

        Raises:
            HTTPException: If the specified XPath query does not yield any results, indicating an invalid request.
        """
        if not self.get_text_by_xpath(xpath):
            raise HTTPException(status_code=404, detail=f"Invalid request (url: {self.URL})")

    def get_list_by_xpath(self, xpath: str, remove_empty: Optional[bool] = True) -> Optional[list]:
        """
        Extract a list of elements from the web page using the specified XPath expression.

        Args:
            xpath (str): The XPath expression to query elements on the page.
            remove_empty (bool, optional): If True, remove empty or whitespace-only elements from
                the list. Default is True.

        Returns:
            Optional[list]: A list of elements extracted from the web page based on the XPath query.
                If remove_empty is True, empty or whitespace-only elements are filtered out.
        """
        elements: list = self.page.xpath(xpath)
        if remove_empty:
            elements_valid: list = [trim(e) for e in elements if trim(e)]
        else:
            elements_valid: list = [trim(e) for e in elements]
        return elements_valid or []

    def get_text_by_xpath(
        self,
        xpath: str,
        pos: int = 0,
        iloc: Optional[int] = None,
        iloc_from: Optional[int] = None,
        iloc_to: Optional[int] = None,
        join_str: Optional[str] = None,
    ) -> Optional[str]:
        """
        Extract text content from the web page using the specified XPath expression.

        Args:
            xpath (str): The XPath expression to query elements on the page.
            pos (int, optional): Index of the element to extract if multiple elements match the
                XPath. Default is 0.
            iloc (int, optional): Extract a single element by index, used as an alternative to 'pos'.
            iloc_from (int, optional): Extract a range of elements starting from the specified
                index (inclusive).
            iloc_to (int, optional): Extract a range of elements up to the specified
                index (exclusive).
            join_str (str, optional): If provided, join multiple text elements into a single string
                using this separator.

        Returns:
            Optional[str]: The extracted text content from the web page based on the XPath query and
                optional parameters. If no matching element is found, None is returned.
        """
        element = self.page.xpath(xpath)

        if not element:
            return None

        if isinstance(element, list):
            element = [trim(e) for e in element if trim(e)]

        if isinstance(iloc, int):
            element = element[iloc]

        if isinstance(iloc_from, int) and isinstance(iloc_to, int):
            element = element[iloc_from:iloc_to]

        if isinstance(iloc_to, int):
            element = element[:iloc_to]

        if isinstance(iloc_from, int):
            element = element[iloc_from:]

        if isinstance(join_str, str):
            return join_str.join([trim(e) for e in element])

        try:
            return trim(element[pos])
        except IndexError:
            return None

    def get_last_page_number(self, xpath_base: str = "") -> int:
        """
        Retrieve the last page number for a paginated result based on the provided base XPath.

        Args:
            xpath_base (str): The base XPath for extracting page number information.

        Returns:
            int: The last page number for search results. Returns 1 if no page numbers are found.
        """

        for xpath in [Pagination.PAGE_NUMBER_LAST, Pagination.PAGE_NUMBER_ACTIVE]:
            url_page = self.get_text_by_xpath(xpath_base + xpath)
            if url_page:
                return int(url_page.split("=")[-1].split("/")[-1])
        return 1
