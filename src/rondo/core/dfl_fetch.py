"""Fetch the DFL open tracking and event data (Bassek et al., 2025) from figshare.

Seven matches from 2022/23: match information, events and TRACAB positions (about 2.6 GB of
XML). Each file is checked against figshare's MD5; DOIs and SHA-256s go to
``data/raw/dfl/SOURCE.json``. Licence: CC BY 4.0 (see docs/DATA_TERMS.md).

Run with ``python -m rondo.core.dfl_fetch`` (part of ``make data``).
"""

from __future__ import annotations

import sys
from pathlib import Path

from rondo.core.figshare import fetch_articles
from rondo.core.paths import data_dir

ARTICLES = {"dfl_open_data": 28196177}
PAPER_DOI = "10.1038/s41597-025-04505-y"


def dfl_raw_dir() -> Path:
    """Return the folder holding the raw DFL files."""
    return data_dir() / "raw" / "dfl"


def fetch(root: Path) -> Path:
    """Download (or verify) the DFL files and write SOURCE.json."""
    return fetch_articles(root, "dfl", ARTICLES, {"paper_doi": PAPER_DOI})


def main() -> int:
    """CLI entry point."""
    fetch(dfl_raw_dir())
    return 0


if __name__ == "__main__":
    sys.exit(main())
