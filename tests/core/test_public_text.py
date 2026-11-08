"""The disclaimer and data credits are copied exactly from docs/DATA_TERMS.md (rule 10)."""

import re
from pathlib import Path

import pytest

from rondo import SITE_TITLE

ROOT = Path(__file__).resolve().parents[2]
TERMS = ROOT / "docs" / "DATA_TERMS.md"
README = ROOT / "README.md"
WEB_CREDITS = ROOT / "web" / "src" / "shell" / "credits.ts"
WEB_INDEX = ROOT / "web" / "index.html"


def public_text() -> dict[str, tuple[str, str]]:
    """Parse the canonical table between the PUBLIC TEXT markers: key -> (text, link)."""
    body = TERMS.read_text()
    block = re.search(r"<!-- BEGIN PUBLIC TEXT -->(.*?)<!-- END PUBLIC TEXT -->", body, re.S)
    assert block, "DATA_TERMS.md is missing its PUBLIC TEXT block"
    rows = {}
    for line in block.group(1).strip().splitlines()[2:]:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        key, text, link = cells
        rows[key] = (text, link)
    return rows


ROWS = public_text()


def test_block_has_disclaimer_and_credits():
    assert ROWS["disclaimer"][0] == (
        "Independent project by Moulik Jain. "
        "Not affiliated with any data provider, league, federation or club."
    )
    assert {"statsbomb", "wyscout", "dfl", "wikidata", "ccby"} <= ROWS.keys()


@pytest.mark.parametrize("target", [README, WEB_CREDITS], ids=["README", "web footer"])
@pytest.mark.parametrize("key", sorted(ROWS))
def test_text_and_link_copied_exactly(target, key):
    text, link = ROWS[key]
    content = target.read_text()
    assert text in content, f"{target.name} is missing the {key!r} text from DATA_TERMS.md"
    if link:
        assert link in content, f"{target.name} is missing the {key!r} link from DATA_TERMS.md"


def test_site_title_is_the_same_everywhere():
    assert SITE_TITLE == "Rondo · European football analytics"
    assert README.read_text().splitlines()[0] == f"# {SITE_TITLE}"
    assert f'SITE_TITLE = "{SITE_TITLE}"' in WEB_CREDITS.read_text()
    assert f"<title>{SITE_TITLE}</title>" in WEB_INDEX.read_text()
