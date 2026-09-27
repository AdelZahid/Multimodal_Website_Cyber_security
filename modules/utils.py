"""
Utility functions for Website Dataset Generator
"""

import csv
import json
from pathlib import Path
from datetime import datetime
from urllib.parse import quote, urlencode, urlparse, urlunparse

import config


def create_directories():

    for directory in config.DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)


def load_urls():

    urls = []

    if not config.URL_FILE.exists():
        return urls

    with open(config.URL_FILE, "r", encoding="utf-8") as f:

        for line in f:

            url = line.strip()

            if url:
                urls.append(url)

    return urls


def remove_duplicates(urls):

    unique = []
    seen = set()

    for url in urls:

        if url not in seen:
            seen.add(url)
            unique.append(url)

    return unique


def decode_hxxp(url):
    """Decode malware obfuscation hxxp:// -> http:// and hxxps:// -> https://"""
    return url.replace("hxxps://", "https://").replace("hxxp://", "http://")


def is_valid_url(url):

    try:

        decoded = decode_hxxp(url)

        parsed = urlparse(decoded)

        return parsed.scheme in ("http", "https") and parsed.netloc != ""

    except Exception:

        return False


def normalize_url(url):

    try:

        decoded = decode_hxxp(url.strip())

        parsed = urlparse(decoded)

        scheme = parsed.scheme.lower() or "https"

        netloc = parsed.netloc.lower()

        path = parsed.path or "/"

        query = parsed.query

        fragment = parsed.fragment

        normalized = urlunparse((
            scheme,
            netloc,
            path,
            "",  # params
            query,
            "",  # fragment
        ))

        return normalized

    except Exception:

        return url.strip()


def reescape_urls_file(path=None):

    if path is None:
        path = config.URL_FILE

    if not Path(path).exists():
        return []

    urls = []

    with open(path, "r", encoding="utf-8") as f:

        for line in f:

            url = line.strip()

            if url:
                urls.append(normalize_url(url))

    with open(path, "w", encoding="utf-8") as f:

        for url in urls:
            f.write(url + "\n")

    return urls


def pad_id(index, width=None):

    if width is None:
        width = config.ID_PADDING

    return str(index).zfill(width)


def html_path(index):
    return config.HTML_DIR / f"{pad_id(index)}.html"


def text_path(index):
    return config.TEXT_DIR / f"{pad_id(index)}.txt"


def thirdparty_path(index):
    return config.THIRDPARTY_DIR / f"{pad_id(index)}.json"


def relative_html_path(index):
    return f"html/{pad_id(index)}.html"


def relative_text_path(index):
    return f"text/{pad_id(index)}.txt"


def relative_thirdparty_path(index):
    return f"thirdparty/{pad_id(index)}.json"


def save_html(path, html):

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def save_text(path, text):

    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def save_json(path, data):

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def write_csv(path, rows, fieldnames=None):

    if not rows:
        return

    if fieldnames is None:
        fieldnames = list(rows[0].keys())

    # Check if file exists to determine if we need to write header
    # For dataset files, we always want to write fresh data, so we use 'w' mode
    if "dataset.csv" in str(path):
        mode = "w"
    else:
        mode = "a"
    
    with open(path, mode, newline="", encoding="utf-8") as f:

        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")

        if mode == "w":
            writer.writeheader()

        writer.writerows(rows)


def iso_date():
    return datetime.now().strftime("%Y-%m-%d")
