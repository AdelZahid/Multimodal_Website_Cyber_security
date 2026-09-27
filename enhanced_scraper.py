"""
Enhanced Web Scraper

Provides the EnhancedScraper class for multi-threaded web scraping with
text extraction, source code detection, third-party resource tracking,
and checkpoint-based resume capability.

Usage:
    from enhanced_scraper import EnhancedScraper
    scraper = EnhancedScraper()
    scraper.run(urls)
"""

import csv
import json
import re
import time
import socket
import random
import logging
import threading
import requests
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup, Comment

BASE_DIR = Path(__file__).resolve().parent
import sys

sys.path.insert(0, str(BASE_DIR))

import config
from modules.text_extractor import TextExtractor
from modules.checkpoint import CheckpointManager
from modules.utils import (
    create_directories,
    remove_duplicates,
    normalize_url,
    is_valid_url,
    pad_id,
    html_path,
    text_path,
    thirdparty_path,
    relative_html_path,
    relative_text_path,
    relative_thirdparty_path,
    save_html,
    save_text,
    save_json,
)

logger = logging.getLogger("enhanced_scraper")

_UA_POOL = [
    config.USER_AGENT,
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.6 Mobile/15E148 Safari/604.1"
    ),
]

# "risk", "category" and "illicit_activity_type" are retained for
# backwards compatibility with previously collected datasets and are
# always written as empty values.
DATASET_FIELDS = [
    "id",
    "url",
    "final_url",
    "http_status",
    "html_file",
    "text_file",
    "thirdparty_file",
    "risk",
    "category",
    "illicit_activity_type",
    "text_length",
    "collected_at",
]

FAILED_FIELDS = ["url", "error"]


def get_registered_domain(url_or_netloc):
    """Extract base/registered domain from URL or hostname."""
    if not url_or_netloc:
        return ""
    if "://" not in url_or_netloc:
        url_or_netloc = "http://" + url_or_netloc
    netloc = urlparse(url_or_netloc).netloc.split(":")[0].lower()
    parts = netloc.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return netloc


class EnhancedScraper:
    """
    Multi-threaded web scraper that downloads pages, extracts text and
    source code, tracks third-party resources, and writes results to a
    structured dataset CSV.

    Parameters
    ----------
    max_workers : int
        Number of worker threads for parallel scraping.
    max_retries : int
        Maximum download attempts per URL.
    verify_ssl : bool or None
        Whether to verify SSL certificates.  Defaults to config.VERIFY_SSL.
    timeout : int or None
        Per-request timeout in seconds.
    rate_limit_delay : float or None
        Delay between retry attempts (exponential backoff multiplier).
    use_playwright : bool or None
        Whether to enable Playwright browser fallback.
    playwright_timeout : int or None
        Playwright navigation timeout in milliseconds.
    extract_source_code : bool
        Whether to extract source-code blocks from each page.
    """

    def __init__(
        self,
        max_workers=None,
        max_retries=None,
        verify_ssl=None,
        timeout=None,
        rate_limit_delay=None,
        use_playwright=None,
        playwright_timeout=None,
        extract_source_code=False,
    ):
        self.max_workers = max_workers or config.MAX_WORKERS
        self.max_retries = max_retries or config.MAX_RETRIES
        self.verify_ssl = config.VERIFY_SSL if verify_ssl is None else verify_ssl
        self.timeout = config.REQUEST_TIMEOUT if timeout is None else timeout
        self.rate_limit_delay = (
            getattr(config, "RATE_LIMIT_DELAY", 2)
            if rate_limit_delay is None
            else rate_limit_delay
        )
        self.use_playwright = config.USE_PLAYWRIGHT if use_playwright is None else use_playwright
        self.playwright_timeout = (
            config.PLAYWRIGHT_TIMEOUT
            if playwright_timeout is None
            else playwright_timeout
        )
        self.do_extract_source_code = extract_source_code

        self.text_extractor = TextExtractor()
        self.checkpoint = CheckpointManager()

        self._local = threading.local()
        self._id_lock = threading.Lock()
        self._checkpoint_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._data_lock = threading.Lock()

        self.dataset_rows = []
        self.failed_urls = []
        self.stats = {"total": 0, "success": 0, "failed": 0, "skipped": 0}

        self.next_id = self._determine_starting_id()

    # ================================================================
    # ID / progress management
    # ================================================================

    def _determine_starting_id(self):
        """Find the next available ID from the existing dataset CSV."""
        dataset_path = config.DATASET_FILE
        max_id = 0

        if dataset_path.exists():
            try:
                with open(dataset_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        try:
                            row_id = int(row.get("id", "0"))
                            if row_id > max_id:
                                max_id = row_id
                        except (ValueError, TypeError):
                            pass
            except Exception:
                pass

        return max_id + 1

    def _get_next_id(self):
        """Atomically retrieve and increment the next dataset ID."""
        with self._id_lock:
            current = self.next_id
            self.next_id += 1
            return current

    def _load_processed_urls(self):
        """Load URLs already present in the dataset CSV."""
        processed = set()
        dataset_path = config.DATASET_FILE
        if dataset_path.exists():
            try:
                with open(dataset_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        url = row.get("url", "")
                        if url:
                            processed.add(url)
            except Exception:
                pass
        return processed

    # ================================================================
    # Download
    # ================================================================

    def _get_session(self):
        """Get or create a thread-local requests Session with pooling."""
        if not hasattr(self._local, "session"):
            session = requests.Session()
            session.headers.update({"User-Agent": config.USER_AGENT})
            adapter = HTTPAdapter(
                pool_connections=self.max_workers,
                pool_maxsize=self.max_workers,
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

    def _download(self, url):
        """Download *url* with retries and UA rotation."""
        session = self._get_session()
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                headers = {"User-Agent": random.choice(_UA_POOL)}
                start = time.time()
                response = session.get(
                    url,
                    headers=headers,
                    timeout=(self.timeout, self.timeout),
                    verify=self.verify_ssl,
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
                    for ua in _UA_POOL:
                        try:
                            response = session.get(
                                url,
                                headers={"User-Agent": ua},
                                timeout=(self.timeout, self.timeout),
                                verify=self.verify_ssl,
                                allow_redirects=config.ALLOW_REDIRECTS,
                            )
                            if response.status_code < 400:
                                return {
                                    "success": True,
                                    "url": url,
                                    "final_url": response.url,
                                    "status_code": response.status_code,
                                    "html": response.text,
                                    "headers": dict(response.headers),
                                    "elapsed": round(time.time() - start, 2),
                                    "redirect_count": len(response.history),
                                    "response_time_ms": round(
                                        (time.time() - start) * 1000, 2
                                    ),
                                    "error": None,
                                }
                        except requests.exceptions.RequestException:
                            continue

                last_error = f"HTTP {response.status_code}"

            except socket.timeout:
                last_error = "Connection timeout"
            except socket.gaierror:
                last_error = "DNS resolution failed"
            except requests.exceptions.ConnectionError as exc:
                last_error = f"Connection error: {exc}"
            except requests.exceptions.RequestException as exc:
                last_error = f"Request exception: {exc}"

            if attempt < self.max_retries:
                backoff = min(self.rate_limit_delay * (2 ** (attempt - 1)), 30)
                logger.warning(
                    f"Retry {attempt}/{self.max_retries} for {url[:80]} "
                    f"in {backoff}s"
                )
                time.sleep(backoff)

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

    def _download_with_playwright(self, url):
        """Attempt download via Playwright browser automation."""
        if not self.use_playwright:
            return None

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("Playwright not installed; skipping browser fallback")
            return None

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=config.HEADLESS,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                context = browser.new_context(
                    user_agent=config.USER_AGENT,
                    viewport={"width": 1920, "height": 1080},
                    ignore_https_errors=True,
                    java_script_enabled=True,
                )
                page = context.new_page()
                start = time.time()
                response = page.goto(
                    url,
                    timeout=self.playwright_timeout,
                    wait_until="domcontentloaded",
                )
                page.wait_for_timeout(config.WAIT_AFTER_LOAD)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass

                html = page.content()
                elapsed = round(time.time() - start, 2)
                status = response.status if response else 200
                final_url = page.url
                headers = dict(response.headers) if response else {}

                browser.close()
                logger.info(f"Playwright fallback succeeded for {url[:80]}")
                return {
                    "success": True,
                    "url": url,
                    "final_url": final_url,
                    "status_code": status,
                    "html": html,
                    "headers": headers,
                    "elapsed": elapsed,
                    "redirect_count": 0,
                    "response_time_ms": round(elapsed * 1000, 2),
                    "error": None,
                }
        except Exception as exc:
            logger.warning(f"Playwright fallback failed for {url[:80]}: {exc}")
            return None

    # ================================================================
    # Third-party resource extraction
    # ================================================================

    def extract_third_party_data(self, html, url):
        """Extract third-party resource information from *html*."""
        soup = BeautifulSoup(html, config.HTML_PARSER)

        target_domain = urlparse(url).netloc.split(":")[0].lower()
        target_registered_domain = get_registered_domain(url)

        all_scripts = [
            t.get("src") for t in soup.find_all("script") if t.get("src")
        ]
        all_stylesheets = [
            t.get("href")
            for t in soup.find_all(
                "link", rel=lambda r: r and "stylesheet" in r.lower()
            )
            if t.get("href")
        ]
        all_fonts = [
            t.get("href")
            for t in soup.find_all(
                "link", rel=lambda r: r and "font" in r.lower()
            )
            if t.get("href")
        ]
        all_iframes = [
            t.get("src") for t in soup.find_all("iframe") if t.get("src")
        ]
        all_images = [
            t.get("src") for t in soup.find_all("img") if t.get("src")
        ]
        all_links = [
            t.get("href") for t in soup.find_all("a") if t.get("href")
        ]
        all_media = []
        for tag in soup.find_all(["video", "audio", "source"]):
            src = tag.get("src")
            if src:
                all_media.append(src)

        def is_external(resource_url):
            if (
                not resource_url
                or resource_url.startswith("data:")
                or resource_url.startswith("#")
            ):
                return False
            parsed = urlparse(resource_url)
            if not parsed.netloc:
                return False
            return get_registered_domain(resource_url) != target_registered_domain

        external_scripts = list(
            set(s for s in all_scripts if is_external(s))
        )
        external_stylesheets = list(
            set(s for s in all_stylesheets if is_external(s))
        )
        external_iframes = list(
            set(f for f in all_iframes if is_external(f))
        )
        external_images = list(
            set(i for i in all_images if is_external(i))
        )
        external_links = list(
            set(l for l in all_links if is_external(l))
        )
        external_media = list(
            set(m for m in all_media if is_external(m))
        )

        third_party_domains = set()
        for res_list in [
            external_scripts,
            external_stylesheets,
            external_iframes,
            external_images,
            external_links,
            external_media,
        ]:
            for res_url in res_list:
                netloc = urlparse(res_url).netloc.split(":")[0].lower()
                if netloc:
                    third_party_domains.add(netloc)

        analytics_pattern = re.compile(
            r"(analytics|gtag|google-analytics|matomo|mixpanel|segment|pixel|doubleclick)",
            re.I,
        )
        analytics_endpoints = [
            r
            for r in (external_scripts + external_links)
            if analytics_pattern.search(r)
        ]

        form_inputs = []
        for inp in soup.find_all("input"):
            form_inputs.append(
                {
                    "type": inp.get("type", ""),
                    "name": inp.get("name", ""),
                    "id": inp.get("id", ""),
                    "class": inp.get("class", []),
                }
            )

        total_external = (
            len(external_scripts)
            + len(external_stylesheets)
            + len(external_iframes)
            + len(external_images)
            + len(external_links)
            + len(external_media)
        )
        total_internal = (
            (len(all_scripts) - len(external_scripts))
            + (len(all_images) - len(external_images))
            + (len(all_links) - len(external_links))
        )

        return {
            "url": url,
            "base_domain": target_domain,
            "extraction_timestamp": datetime.utcnow().isoformat(),
            "external_scripts": external_scripts,
            "external_iframes": external_iframes,
            "external_images": external_images,
            "external_stylesheets": external_stylesheets,
            "external_fonts": list(set(all_fonts)),
            "external_fonts_css": [],
            "form_actions": [
                t.get("action") for t in soup.find_all("form") if t.get("action")
            ],
            "form_inputs": form_inputs,
            "analytics_endpoints": analytics_endpoints,
            "tracking_pixels": [
                img
                for img in external_images
                if "pixel" in img or "tracking" in img
            ],
            "external_links": external_links,
            "cdn_domains": [
                d
                for d in sorted(third_party_domains)
                if "cdn" in d or "cloudflare" in d or "fastly" in d
            ],
            "social_media_widgets": [
                d
                for d in sorted(third_party_domains)
                if any(
                    s in d
                    for s in [
                        "facebook",
                        "twitter",
                        "linkedin",
                        "instagram",
                    ]
                )
            ],
            "advertising_elements": [
                d
                for d in sorted(third_party_domains)
                if any(
                    a in d
                    for a in [
                        "doubleclick",
                        "adservice",
                        "adnxs",
                        "googlesyndication",
                    ]
                )
            ],
            "javascript_frameworks": [],
            "resource_distribution": {
                "scripts": len(all_scripts),
                "stylesheets": len(all_stylesheets),
                "images": len(all_images),
                "iframes": len(all_iframes),
                "fonts": len(all_fonts),
                "links": len(all_links),
                "media": len(all_media),
                "analytics": len(analytics_endpoints),
                "total_external": total_external,
                "total_internal": total_internal,
            },
            "security_risks": [],
            "third_party_domains": sorted(third_party_domains),
            "total_external_resources": total_external,
            "extraction_metadata": {
                "parser_used": "lxml",
                "version": "3.1",
                "extraction_method": (
                    "BeautifulSoup enhanced with requests download"
                ),
            },
        }

    # ================================================================
    # Source-code extraction (basic)
    # ================================================================

    LANGUAGE_PATTERNS = {
        "Python": [
            r"\bdef\s+\w+\s*\(",
            r"\bclass\s+\w+\s*:",
            r"\bimport\s+\w+",
            r"\bfrom\s+\w+\s+import",
        ],
        "JavaScript": [
            r"\bfunction\s+\w+\s*\(",
            r"\bconst\s+\w+\s*=",
            r"\blet\s+\w+\s*=",
            r"\bvar\s+\w+\s*=",
            r"\w+\s*=><\s*",
        ],
        "Java": [
            r"\bpublic\s+\w+\s+\w+\s*\(",
            r"\bimport\s+java\.",
            r"\bpackage\s+\w+",
        ],
        "C++": [
            r"#include\s*<",
            r"\busing\s+namespace\s+\w+",
            r"\bclass\s+\w+\s*\{",
        ],
        "CSS": [
            r"\w+\s*\{",
            r"background-color\s*:",
            r"font-size\s*:",
            r"margin\s*:",
        ],
        "HTML": [
            r"<\w+>",
            r"href\s*=",
            r"src\s*=",
            r"class\s*=",
        ],
        "SQL": [
            r"\bSELECT\s+.*\s+FROM",
            r"\bINSERT\s+INTO",
            r"\bUPDATE\s+\w+\s+SET",
            r"\bDELETE\s+FROM",
        ],
        "PHP": [
            r"\$\w+\s*=",
            r"<\?php",
            r"\?>",
        ],
    }

    def extract_source_code_html(self, html, soup):
        """Extract source-code blocks from *soup*."""
        code_blocks = []

        for tag in soup.find_all(["pre", "code", "script", "style", "textarea"]):
            if tag.name in ("script", "style", "textarea"):
                content = tag.string or ""
            else:
                content = tag.get_text(separator="\n", strip=False)

            if not content or len(content.strip()) < 5:
                continue

            content_clean = content.strip()
            language = self._detect_language(content_clean, tag)
            confidence = self._estimate_confidence(content_clean, language)

            if confidence >= getattr(config, "MIN_CODE_CONFIDENCE", 0.5):
                code_blocks.append(
                    {
                        "content": content_clean,
                        "language": language,
                        "confidence": round(confidence, 4),
                        "element_type": tag.name,
                        "line_count": len(content_clean.split("\n")),
                        "char_count": len(content_clean),
                    }
                )

        code_blocks.sort(key=lambda x: x["confidence"], reverse=True)
        return code_blocks

    def _detect_language(self, content, element):
        """Detect the programming language of *content*."""
        if element and element.get("class"):
            class_str = " ".join(element.get("class", [])).lower()
            for lang in self.LANGUAGE_PATTERNS:
                if lang.lower() in class_str:
                    return lang

        if element and element.get("id"):
            id_str = element.get("id", "").lower()
            for lang in self.LANGUAGE_PATTERNS:
                if lang.lower() in id_str:
                    return lang

        if element and element.get("data-language"):
            data_lang = element.get("data-language", "").lower()
            for lang in self.LANGUAGE_PATTERNS:
                if lang.lower() in data_lang:
                    return lang

        for language, patterns in self.LANGUAGE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    return language

        return "Unknown"

    def _estimate_confidence(self, content, language):
        """Estimate confidence score (0.0-1.0) for a code block."""
        if language == "Unknown":
            return 0.0

        score = 0.0
        for pattern in self.LANGUAGE_PATTERNS.get(language, []):
            if re.search(pattern, content, re.IGNORECASE):
                score += 0.2

        score += min(len(content) / 1000, 0.3)
        line_count = len([line for line in content.split("\n") if line.strip()])
        score += min(line_count / 20, 0.2)

        return min(score, 1.0)

    # ================================================================
    # Per-URL processing
    # ================================================================

    def process_url(self, url):
        """Process a single URL end-to-end and return a result dict."""
        with self._stats_lock:
            self.stats["total"] += 1

        url = normalize_url(url)

        with self._checkpoint_lock:
            if self.checkpoint.contains(url):
                with self._stats_lock:
                    self.stats["skipped"] += 1
                logger.info(f"Skipping (checkpoint): {url[:80]}")
                return {"status": "skipped", "url": url}

        logger.info(f"Processing: {url[:80]}")
        result = self._download(url)

        if not result["success"] and self.use_playwright:
            pw_result = self._download_with_playwright(url)
            if pw_result and pw_result["success"]:
                result = pw_result

        if not result["success"] or not result["html"]:
            if self.use_playwright:
                pw_result = self._download_with_playwright(url)
                if pw_result and pw_result["success"]:
                    result = pw_result
                else:
                    with self._stats_lock:
                        self.stats["failed"] += 1
                    with self._data_lock:
                        self.failed_urls.append(
                            {"url": url, "error": result.get("error", "No content")}
                        )
                    logger.error(f"Failed: {url[:80]} -> {result.get('error')}")
                    return {"status": "failed", "url": url}
            else:
                with self._stats_lock:
                    self.stats["failed"] += 1
                with self._data_lock:
                    self.failed_urls.append(
                        {"url": url, "error": result.get("error", "No content")}
                    )
                logger.error(f"Failed: {url[:80]} -> {result.get('error')}")
                return {"status": "failed", "url": url}

        # If the HTML is suspiciously small (likely a JS-redirect stub),
        # retry via Playwright which executes JavaScript.
        if self.use_playwright and len(result["html"]) < 500:
            logger.info(f"ID check: small HTML ({len(result['html'])} chars), "
                        f"trying Playwright for {url[:70]}")
            pw_result = self._download_with_playwright(url)
            if pw_result and pw_result["success"] and len(pw_result["html"]) > len(result["html"]):
                result = pw_result
                logger.info(f"Playwright provided better content for {url[:70]}")

        idx = self._get_next_id()
        html_content = result["html"]

        try:
            soup = BeautifulSoup(html_content, config.HTML_PARSER)
        except Exception:
            soup = BeautifulSoup(html_content, "html.parser")

        # Text extraction
        try:
            text = self.text_extractor.extract_text(html_content, soup)
        except Exception:
            text = soup.get_text(separator=" ", strip=True)

        # Third-party extraction
        try:
            thirdparty_data = self.extract_third_party_data(html_content, url)
        except Exception as exc:
            logger.warning(f"Third-party extraction error for {url[:80]}: {exc}")
            thirdparty_data = {}

        # Optional source-code extraction
        if self.do_extract_source_code:
            try:
                code_blocks = self.extract_source_code_html(html_content, soup)
                thirdparty_data.setdefault("source_code", code_blocks)
            except Exception as exc:
                logger.warning(f"Source-code extraction error for {url[:80]}: {exc}")

        # Persist artefacts
        row = {
            "id": pad_id(idx),
            "url": url,
            "final_url": result.get("final_url") or url,
            "http_status": result.get("status_code", 0),
            "html_file": relative_html_path(idx),
            "text_file": relative_text_path(idx),
            "thirdparty_file": relative_thirdparty_path(idx),
            "risk": "",
            "category": "",
            "illicit_activity_type": "",
            "text_length": len(text),
            "collected_at": datetime.now().strftime("%Y-%m-%d"),
        }

        try:
            if config.SAVE_HTML and html_content:
                save_html(html_path(idx), html_content)
        except Exception as exc:
            logger.warning(f"Could not save HTML for {url[:80]}: {exc}")

        try:
            if config.SAVE_TEXT:
                save_text(text_path(idx), text or "")
        except Exception as exc:
            logger.warning(f"Could not save text for {url[:80]}: {exc}")

        try:
            if config.SAVE_THIRDPARTY and thirdparty_data:
                save_json(thirdparty_path(idx), thirdparty_data)
        except Exception as exc:
            logger.warning(f"Could not save third-party data for {url[:80]}: {exc}")

        # Update checkpoint
        with self._checkpoint_lock:
            self.checkpoint.add(url)

        # Record result
        with self._stats_lock:
            self.stats["success"] += 1
        with self._data_lock:
            self.dataset_rows.append(row)

        logger.info(
            f"Done: {url[:80]} | status={result.get('status_code', 0)} "
            f"text_len={len(text)} idx={idx}"
        )
        return {"status": "success", "url": url, "row": row}

    # ================================================================
    # Batch execution
    # ================================================================

    def run(self, urls, checkpoint_interval=None):
        """Process *urls* in parallel and persist results."""
        create_directories()

        if checkpoint_interval is None:
            checkpoint_interval = getattr(config, "CHECKPOINT_INTERVAL", 50)

        # Normalise, filter, and de-duplicate
        valid_urls = [u for u in urls if is_valid_url(u)]
        normalised = [normalize_url(u) for u in valid_urls]
        unique_urls = remove_duplicates(normalised)

        # Skip URLs already in the dataset
        processed = self._load_processed_urls()
        to_process = [u for u in unique_urls if u not in processed]

        logger.info(
            f"Loaded {len(unique_urls)} unique URLs; "
            f"{len(processed)} already in dataset; "
            f"{len(to_process)} to process"
        )

        if not to_process:
            logger.info("No URLs to process; exiting")
            return

        checkpoint_count = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_map = {
                executor.submit(self.process_url, url): url for url in to_process
            }
            for future in as_completed(future_map):
                url = future_map[future]
                try:
                    future.result()
                except Exception as exc:
                    logger.error(f"Unhandled error for {url[:80]}: {exc}")
                    with self._stats_lock:
                        self.stats["failed"] += 1
                    with self._data_lock:
                        self.failed_urls.append({"url": url, "error": str(exc)})

                checkpoint_count += 1
                if (
                    config.SAVE_CHECKPOINT
                    and checkpoint_count % checkpoint_interval == 0
                ):
                    with self._checkpoint_lock:
                        self.checkpoint.save()
                    self.save_results(partial=True)
                    logger.info(
                        f"Checkpoint {checkpoint_count}/{len(to_process)} "
                        f"saved ({self.stats['success']} ok, "
                        f"{self.stats['failed']} failed)"
                    )

        # Final saves
        self.save_results()
        with self._checkpoint_lock:
            self.checkpoint.save()

    # ================================================================
    # Persistence
    # ================================================================

    def save_results(self, partial=False):
        """Write dataset CSV and failed-URL CSV.

        Buffers are atomically swapped out under ``_data_lock`` so that
        worker threads appending new rows never have their data clobbered
        by a concurrent checkpoint save.
        """
        # Atomically take ownership of the in-memory buffers.
        with self._data_lock:
            rows_to_write = list(self.dataset_rows)
            failed_to_write = list(self.failed_urls)
            self.dataset_rows = []
            self.failed_urls = []

        rows_written = False
        failed_written = False

        # --- dataset.csv ---
        if rows_to_write:
            dataset_path = config.DATASET_FILE
            try:
                file_exists = dataset_path.exists()
                mode = "a" if file_exists else "w"
                with open(dataset_path, mode, newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(
                        f, fieldnames=DATASET_FIELDS, extrasaction="ignore"
                    )
                    if not file_exists:
                        writer.writeheader()
                    writer.writerows(rows_to_write)
                rows_written = True
            except Exception as exc:
                logger.error(f"Failed to write dataset CSV: {exc}")
                # Rollback: put the rows back so they aren't lost.
                with self._data_lock:
                    self.dataset_rows.extend(rows_to_write)

        # --- failed_urls.csv ---
        if config.SAVE_FAILED_URLS and failed_to_write:
            failed_path = config.FAILED_FILE
            try:
                file_exists = failed_path.exists()
                mode = "a" if file_exists else "w"
                with open(failed_path, mode, newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(
                        f, fieldnames=FAILED_FIELDS, extrasaction="ignore"
                    )
                    if not file_exists:
                        writer.writeheader()
                    writer.writerows(failed_to_write)
                failed_written = True
            except Exception as exc:
                logger.error(f"Failed to write failed URLs CSV: {exc}")
                with self._data_lock:
                    self.failed_urls.extend(failed_to_write)

        if rows_written or failed_written:
            logger.debug(
                f"Persisted {len(rows_to_write)} dataset rows"
                f"{' (partial)' if partial else ''} "
                f"and {len(failed_to_write)} failed URLs"
            )

    def cleanup(self):
        """Release resources."""
        try:
            self.checkpoint.save()
        except Exception:
            pass

    # ================================================================
    # Reporting
    # ================================================================

    @property
    def summary(self):
        """Return a summary dict of scraping statistics."""
        total = self.stats["total"]
        success = self.stats["success"]
        failed = self.stats["failed"]
        skipped = self.stats["skipped"]

        success_rate = (success / total * 100) if total > 0 else 0
        return {
            "total": total,
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "success_rate": round(success_rate, 1),
            "next_id": self.next_id,
        }

    def print_summary(self):
        """Log a human-readable summary of the scraping session."""
        s = self.summary
        logger.info("=" * 60)
        logger.info("SCRAPING COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Total URLs:  {s['total']}")
        logger.info(f"Success:     {s['success']}")
        logger.info(f"Failed:      {s['failed']}")
        logger.info(f"Skipped:     {s['skipped']}")
        logger.info(f"Success rate: {s['success_rate']}%")
        logger.info(f"Last ID:     {pad_id(s['next_id'] - 1)}")
        logger.info("=" * 60)
