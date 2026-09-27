"""
Global configuration for Website Dataset Generator
"""

from pathlib import Path

# =====================================================
# PROJECT PATHS
# =====================================================

BASE_DIR = Path(__file__).resolve().parent

URL_FILE = BASE_DIR / "urls" / "malicious_urls.txt"

DATASET_DIR = BASE_DIR / "WebsiteDataset"

HTML_DIR = DATASET_DIR / "html"

TEXT_DIR = DATASET_DIR / "text"

THIRDPARTY_DIR = DATASET_DIR / "thirdparty"

LOG_DIR = BASE_DIR / "logs"

CHECKPOINT_FILE = BASE_DIR / "checkpoint.json"

DATASET_FILE = DATASET_DIR / "dataset.csv"

FAILED_FILE = BASE_DIR / "failed_urls.csv"

LOG_FILE = LOG_DIR / "scraper.log"

# =====================================================
# HTTP SETTINGS
# =====================================================

REQUEST_TIMEOUT = 5

MAX_RETRIES = 1

RETRY_DELAY = 2

VERIFY_SSL = False

ALLOW_REDIRECTS = True

# =====================================================
# PLAYWRIGHT SETTINGS
# =====================================================

USE_PLAYWRIGHT = False

HEADLESS = True

PLAYWRIGHT_TIMEOUT = 30000

WAIT_AFTER_LOAD = 3000

# =====================================================
# MULTITHREADING
# =====================================================

ENABLE_MULTITHREADING = True

MAX_WORKERS = 16

# =====================================================
# DATASET OPTIONS
# =====================================================

SAVE_HTML = True

SAVE_TEXT = True

SAVE_THIRDPARTY = True

SAVE_FAILED_URLS = True

SAVE_CHECKPOINT = True

# =====================================================
# ID FORMAT
# =====================================================

ID_PADDING = 6

# =====================================================
# HTML PARSER
# =====================================================

HTML_PARSER = "lxml"

# =====================================================
# USER AGENT
# =====================================================

USER_AGENT = (
    "Mozilla/5.0 "
    "(Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/138.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT
}

# =====================================================
# CREATE DIRECTORIES
# =====================================================

DIRECTORIES = [
    DATASET_DIR,
    HTML_DIR,
    TEXT_DIR,
    THIRDPARTY_DIR,
    LOG_DIR
]
