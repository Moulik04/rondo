"""What may be published: the minors rule.

Every export calls :func:`display_ok` before naming a player, passing the competition-seasons
the output is about. A check scans ``web/public/`` and ``reports/`` for the names of everyone
who can't be named in any season.

Rondo reads the minors rule per season: a player may be named in output about a
competition-season only if they were a verified adult throughout it. Someone who debuted as a
minor and kept playing can be named for their adult seasons, never for their minor ones. So an
output that names a player must cover only seasons :func:`display_ok` clears: a career page
leaves out the seasons when the player was a minor, or doesn't name them.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from rondo.core import store
from rondo.core.paths import parquet_dir

ADULT = "verified_adult"

#: Text files that may carry names.
SCANNED_SUFFIXES = {".md", ".csv", ".json", ".html", ".txt", ".tsv", ".yaml", ".yml"}
#: A single-word name shorter than this isn't scanned for (too many false hits, e.g. "Rui").
MIN_SINGLE_WORD = 5


@lru_cache(maxsize=4)
def _statuses(parquet: Path) -> dict[str, dict[str, str]]:
    con = store.connect()
    rows = con.execute(
        f"select person_id, competition_season, status "
        f"from read_parquet('{parquet / 'player_age_status.parquet'}')"
    ).fetchall()
    con.close()
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for person, cs, st in rows:
        out[person][cs] = st
    return dict(out)


def display_ok(
    person_id: str,
    competition_seasons: Iterable[str] | None = None,
    *,
    parquet: Path | None = None,
) -> bool:
    """Return True if this person may be named in output about these competition-seasons.

    ``competition_seasons`` are keys like ``"statsbomb:11/27"``. The person must be
    ``verified_adult`` in every one of them. None means every competition-season the person
    appears in, the safe choice for output that isn't about particular seasons.
    """
    st = _statuses((parquet or parquet_dir()).resolve()).get(person_id)
    if not st:
        return False
    wanted = list(competition_seasons) if competition_seasons is not None else list(st)
    return bool(wanted) and all(st.get(cs) == ADULT for cs in wanted)


def nameable_seasons(person_id: str, *, parquet: Path | None = None) -> list[str]:
    """Return the competition-seasons in which this person may be named, sorted."""
    st = _statuses((parquet or parquet_dir()).resolve()).get(person_id, {})
    return sorted(cs for cs, v in st.items() if v == ADULT)


def blocked_names(parquet: Path | None = None) -> set[str]:
    """Every provider name of every person who can't be named in any season (for scanning).

    A text scan can't tell which season a page is about, so it can't police people cleared for
    some seasons only; for them, the export's call to :func:`display_ok` is the guard.
    """
    pq = (parquet or parquet_dir()).resolve()
    con = store.connect()
    store.create_views(con, pq)
    names: dict[str, set[str]] = defaultdict(set)
    for person, name in con.execute(
        """select x.person_id, n from player_xref x,
             unnest([x.name]) as t(n) where n is not null
           union
           select x.person_id, p.player_name from player_xref x join players p
             on x.provider = 'statsbomb' and p.player_id::varchar = x.provider_player_id
           union
           select x.person_id, p.player_nickname from player_xref x join players p
             on x.provider = 'statsbomb' and p.player_id::varchar = x.provider_player_id
           union
           select x.person_id, trim(p.first_name || ' ' || p.last_name) from player_xref x
             join wy_players p
             on x.provider = 'wyscout' and p.player_id::varchar = x.provider_player_id
           union
           select x.person_id, trim(l.first_name || ' ' || l.last_name) from player_xref x
             join dfl_lineups l on x.provider = 'dfl' and l.player_id = x.provider_player_id"""
    ).fetchall():
        if name:
            names[person].add(name.strip())
    con.close()
    cleared = {p for p in names if nameable_seasons(p, parquet=pq)}
    cleared_names = {n.lower() for p in cleared for n in names[p]}
    blocked = set()
    for person, ns in names.items():
        if person in cleared:
            continue
        for n in ns:
            low = n.lower()
            if " " not in low and len(low) < MIN_SINGLE_WORD:
                continue
            if low in cleared_names:
                continue  # the same string names a cleared player too
            blocked.add(n)
    return blocked


def scan(paths: Iterable[Path], names: set[str]) -> list[tuple[str, str]]:
    """Return (file, name) for every blocked name found in a published text file."""
    if not names:
        return []
    pattern = re.compile(
        r"(?<!\w)("
        + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
        + r")(?!\w)",
        re.IGNORECASE,
    )
    hits = []
    for root in paths:
        files = [root] if root.is_file() else sorted(root.rglob("*")) if root.exists() else []
        for f in files:
            if f.is_file() and f.suffix.lower() in SCANNED_SUFFIXES:
                for m in pattern.finditer(f.read_text(errors="ignore")):
                    hits.append((str(f), m.group(1)))
    return hits
