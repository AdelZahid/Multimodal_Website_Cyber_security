#!/usr/bin/env python
"""
Simple runner for the Enhanced Web Scraper.

Runs a quick scrape with default settings and minimal configuration.
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import config
from modules.utils import create_directories, load_urls, is_valid_url, normalize_url, remove_duplicates
from enhanced_scraper import EnhancedScraper


def main():
    create_directories()

    raw_urls = load_urls()
    valid_urls = [u for u in raw_urls if is_valid_url(u)]
    unique_urls = remove_duplicates([normalize_url(u) for u in valid_urls])

    print(f"URLs ready: {len(unique_urls)}")
    print(f"Workers: {config.MAX_WORKERS}  Timeout: {config.REQUEST_TIMEOUT}s")

    scraper = EnhancedScraper()
    scraper.run(unique_urls)
    scraper.cleanup()
    scraper.print_summary()


if __name__ == "__main__":
    main()
