"""
HTTP Downloader Module

Uses thread-local sessions with connection pooling for improved
parallelism and reduced lock contention. Implements exponential
backoff and adaptive timeout strategies.
"""

import socket
import threading
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config


class Downloader:

    def __init__(self):

        self._local = threading.local()

        self.headers = config.HEADERS

        self.fallback_user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1",
        ]

    def _get_session(self):

        if not hasattr(self._local, "session"):

            session = requests.Session()

            session.headers.update(self.headers)

            adapter = HTTPAdapter(
                pool_connections=config.MAX_WORKERS,
                pool_maxsize=config.MAX_WORKERS,
                max_retries=Retry(
                    total=0,
                    raise_on_redirect=False,
                    raise_on_status=False,
                    respect_retry_after_header=True,
                ),
            )

            session.mount("http://", adapter)
            session.mount("https://", adapter)

            self._local.session = session

        return self._local.session

    def _exponential_backoff(self, attempt):

        delay = min(config.RETRY_DELAY * (2 ** (attempt - 1)), 30)

        time.sleep(delay)

    def download(self, url):

        session = self._get_session()

        last_error = None

        for attempt in range(1, config.MAX_RETRIES + 1):

            try:

                start = time.time()

                response = session.get(
                    url,
                    timeout=(config.REQUEST_TIMEOUT, config.REQUEST_TIMEOUT),
                    verify=config.VERIFY_SSL,
                    allow_redirects=config.ALLOW_REDIRECTS,
                )

                elapsed = round(time.time() - start, 2)

                if response.status_code < 400:
                    return {
                        "success": True,
                        "url": url,
                        "final_url": response.url,
                        "status_code": response.status_code,
                        "html": response.text,
                        "headers": dict(response.headers),
                        "elapsed": elapsed,
                        "redirect_count": len(response.history),
                        "response_time_ms": round(elapsed * 1000, 2),
                        "error": None,
                    }

                if response.status_code in (403, 429):
                    # Server is blocking - try different user agents
                    for ua in self.fallback_user_agents:
                        try:
                            session.headers.update({"User-Agent": ua})
                            response = session.get(
                                url,
                                timeout=(config.REQUEST_TIMEOUT, config.REQUEST_TIMEOUT),
                                verify=config.VERIFY_SSL,
                                allow_redirects=config.ALLOW_REDIRECTS,
                            )
                            if response.status_code < 400:
                                session.headers.update(self.headers)
                                return {
                                    "success": True,
                                    "url": url,
                                    "final_url": response.url,
                                    "status_code": response.status_code,
                                    "html": response.text,
                                    "headers": dict(response.headers),
                                    "elapsed": elapsed,
                                    "redirect_count": len(response.history),
                                    "response_time_ms": round(elapsed * 1000, 2),
                                    "error": None,
                                }
                        except requests.exceptions.RequestException:
                            continue
                    session.headers.update(self.headers)

                    # All user agents failed
                    return {
                        "success": False,
                        "url": url,
                        "final_url": response.url,
                        "status_code": response.status_code,
                        "html": "",
                        "headers": dict(response.headers),
                        "elapsed": elapsed,
                        "redirect_count": len(response.history),
                        "response_time_ms": round(elapsed * 1000, 2),
                        "error": f"HTTP {response.status_code} Forbidden/Bot blocked",
                    }

                last_error = f"HTTP {response.status_code}"

            except requests.exceptions.ConnectTimeout:

                last_error = "Connection timeout"

            except requests.exceptions.ReadTimeout:

                last_error = "Read timeout"

            except requests.exceptions.ConnectionError as e:

                last_error = str(e)

            except requests.exceptions.RequestException as e:

                last_error = str(e)

            if attempt < config.MAX_RETRIES:

                self._exponential_backoff(attempt)

        return {
            "success": False,
            "url": url,
            "final_url": None,
            "status_code": 0,
            "html": "",
            "headers": {},
            "elapsed": 0,
            "redirect_count": 0,
            "response_time_ms": 0.0,
            "error": last_error,
        }

    def close(self):

        if hasattr(self._local, "session"):

            self._local.session.close()

            self._local.session = None
