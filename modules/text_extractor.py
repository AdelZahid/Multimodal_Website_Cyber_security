"""
Text Extraction Module

Extracts clean visible text from HTML.
"""

import re
from bs4 import BeautifulSoup, Comment

import config


class TextExtractor:

    def extract_text(self, html, soup=None):

        if soup is None:

            soup = BeautifulSoup(html, config.HTML_PARSER)

        for tag in ("script", "style", "noscript", "svg", "canvas", "iframe", "header", "footer"):
            for element in soup.find_all(tag):
                element.decompose()

        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        for element in soup.select('[hidden],[style*="display:none"],[style*="visibility:hidden"]'):
            element.decompose()

        text = soup.get_text(separator=" ", strip=True)

        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\n+", "\n", text)

        return text.strip()
