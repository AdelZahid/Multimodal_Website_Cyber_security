"""
Checkpoint Manager

Keeps track of processed URLs so the scraper
can resume after interruption.
"""

import json
from pathlib import Path

import config


class CheckpointManager:

    def __init__(self):

        self.file = config.CHECKPOINT_FILE

        self.processed = set()

        self.load()

    # ======================================

    def load(self):

        if not self.file.exists():

            self.processed = set()

            return

        try:

            with open(self.file, "r", encoding="utf-8") as f:

                data = json.load(f)

            self.processed = set(data)

        except Exception:

            self.processed = set()

    # ======================================

    def add(self, url):

        self.processed.add(url)

    def save(self):

        self.file.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        with open(
            self.file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                sorted(list(self.processed)),
                f,
                indent=4
            )

    # ======================================

    def remove(self, url):

        if url in self.processed:

            self.processed.remove(url)

            self.save()

    # ======================================

    def contains(self, url):

        return url in self.processed

    # ======================================

    def clear(self):

        self.processed = set()

        self.save()

    # ======================================

    def count(self):

        return len(self.processed)

    # ======================================

    def get_processed(self):

        return sorted(self.processed)

    # ======================================

    def remaining(self, urls):

        return [

            url

            for url in urls

            if url not in self.processed

        ]