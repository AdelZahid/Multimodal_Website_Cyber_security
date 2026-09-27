#!/usr/bin/env python
"""
Enhanced Web Scraper - Entry Point

Reads URLs from the configured URL file, downloads each page, extracts
text / source-code blocks, tracks third-party resources, and appends
results to the dataset CSV.

Quick start:
    python main.py
    python main.py --workers 8 --max-retries 2
    python main.py --urls-file urls/urls.txt --source-code
    python main.py --playwright --dry-run
"""

import argparse
import logging
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import config
from modules.utils import create_directories


def setup_logging(log_level="INFO"):
    """Configure logging to console and file."""
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    log_dir = config.LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(config.LOG_FORMAT) if hasattr(config, "LOG_FORMAT") else \
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    try:
        file_handler = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except Exception as exc:
        print(f"Warning: could not set up file logging: {exc}")

    return logging.getLogger("main")


def load_urls_from_file(filepath):
    """Load raw URLs from *filepath*, one per line."""
    urls = []
    path = Path(filepath)
    if not path.is_absolute():
        path = BASE_DIR / path

    if not path.exists():
        raise FileNotFoundError(f"URL file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            url = line.strip()
            if url and not url.startswith("#"):
                urls.append(url)

    return urls


def main():
    parser = argparse.ArgumentParser(
        description="Enhanced Web Scraper for building a website dataset."
    )
    parser.add_argument(
        "--urls-file",
        default=str(config.URL_FILE) if hasattr(config, "URL_FILE") else "urls/malicious_urls.txt",
        help="Path to the URL list file (default: config.URL_FILE)",
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=config.MAX_WORKERS,
        help=f"Number of worker threads (default: {config.MAX_WORKERS})",
    )
    parser.add_argument(
        "--max-retries", "-r",
        type=int,
        default=config.MAX_RETRIES,
        help=f"Max download retries per URL (default: {config.MAX_RETRIES})",
    )
    parser.add_argument(
        "--timeout", "-t",
        type=int,
        default=config.REQUEST_TIMEOUT,
        help=f"Request timeout in seconds (default: {config.REQUEST_TIMEOUT})",
    )
    parser.add_argument(
        "--playwright",
        action="store_true",
        help="Enable Playwright browser fallback for failed requests",
    )
    parser.add_argument(
        "--source-code",
        action="store_true",
        help="Extract source-code blocks from each page",
    )
    parser.add_argument(
        "--no-ssl",
        action="store_true",
        help="Disable SSL certificate verification",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load and filter URLs without downloading",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    parser.add_argument(
        "--clear-checkpoint",
        action="store_true",
        help="Ignore checkpoint and reprocess all URLs",
    )

    args = parser.parse_args()

    # --- setup ---
    logger = setup_logging(args.log_level)
    logger.info("Enhanced Web Scraper starting up")
    logger.info(f"Workers: {args.workers}  Max retries: {args.max_retries}  Timeout: {args.timeout}s")
    logger.info(f"Playwright fallback: {'ON' if args.playwright else 'OFF'}")
    logger.info(f"Source-code extraction: {'ON' if args.source_code else 'OFF'}")

    create_directories()

    # --- load URLs ---
    try:
        raw_urls = load_urls_from_file(args.urls_file)
        logger.info(f"Loaded {len(raw_urls)} raw URLs from {args.urls_file}")
    except FileNotFoundError as exc:
        logger.error(str(exc))
        sys.exit(1)

    # --- import here so logging is configured first ---
    from enhanced_scraper import EnhancedScraper, is_valid_url, remove_duplicates, normalize_url

    # --- filter & normalise ---
    valid_urls = [u for u in raw_urls if is_valid_url(u)]
    normalised = [normalize_url(u) for u in valid_urls]
    unique_urls = remove_duplicates(normalised)

    logger.info(f"Valid URLs: {len(valid_urls)}  Unique: {len(unique_urls)}")

    if args.dry_run:
        logger.info("Dry run complete; exiting without scraping")
        return

    if not unique_urls:
        logger.warning("No valid URLs to process; exiting")
        return

    # --- scraper ---
    scraper = EnhancedScraper(
        max_workers=args.workers,
        max_retries=args.max_retries,
        timeout=args.timeout,
        use_playwright=args.playwright,
        extract_source_code=args.source_code,
        verify_ssl=not args.no_ssl,
    )

    if args.clear_checkpoint:
        scraper.checkpoint.clear()
        logger.info("Checkpoint cleared; all URLs will be reprocessed")

    scraper.run(unique_urls)
    scraper.cleanup()
    scraper.print_summary()


if __name__ == "__main__":
    main()
