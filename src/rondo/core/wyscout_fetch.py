"""Fetch Wyscout open data (Pappalardo et al., 2019) from figshare.

Downloads each file once, checks it against figshare's own MD5, records the article DOIs and
a SHA-256 per file in ``data/raw/wyscout/SOURCE.json``, and unzips the matches and events
archives in place. Licence: CC BY 4.0 (see docs/DATA_TERMS.md).

Run with ``python -m rondo.core.wyscout_fetch`` (part of ``make data``).
"""

from __future__ import annotations

import sys
from pathlib import Path

from rondo.core.figshare import fetch_articles
from rondo.core.paths import data_dir

#: figshare articles in collection 10.6084/m9.figshare.c.4415000.v5 that Rondo uses.
ARTICLES = {
    "competitions": 7765316,
    "matches": 7770422,
    "teams": 7765310,
    "players": 7765196,
    "events": 7770599,
    "event_names": 11743836,
    "tag_names": 11743818,
}
COLLECTION_DOI = "10.6084/m9.figshare.c.4415000.v5"


def wyscout_raw_dir() -> Path:
    """Return the folder holding the raw Wyscout files."""
    return data_dir() / "raw" / "wyscout"


def fetch(root: Path) -> Path:
    """Download (or verify) the Wyscout files and write SOURCE.json."""
    return fetch_articles(root, "wyscout", ARTICLES, {"collection_doi": COLLECTION_DOI})


def main() -> int:
    """CLI entry point."""
    fetch(wyscout_raw_dir())
    return 0


if __name__ == "__main__":
    sys.exit(main())
