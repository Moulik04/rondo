"""Age status per person and competition-season (``player_age_status``), for the minors rule.

Birth dates come only from Wikidata (with its precision: day, month or year) and Wyscout's
player file. They're used to decide who may be named, and are never published.

Only Wikidata links of high or medium confidence supply a birth date: a low-confidence link
(name search alone) could be the wrong person, and must never clear a minor.

For each person, every source becomes an interval of possible birth dates (one day for a
day-precise date, a month or a year otherwise). The intervals are intersected; if they don't
overlap, the sources disagree and the person is ``unverified``. For each competition-season the
person appears in, with window = that competition-season's first and last match in the data:

- ``verified_adult``: even the latest possible birth date makes them 18 by the window start;
- ``minor_during_season``: even the earliest possible birth date leaves them under 18 at the
  window start (so under 18 at some point in the window);
- ``unverified``: no birth date, disagreeing sources, or a date too imprecise to decide.
"""

from __future__ import annotations

import calendar
import datetime as dt
from collections import defaultdict
from pathlib import Path
from typing import Any

from rondo.core import store
from rondo.core.dfl_fetch import dfl_raw_dir
from rondo.core.dfl_ingest import match_files
from rondo.core.parquet_io import write_single
from rondo.core.schemas import PLAYER_AGE_STATUS

#: Wyscout and Wikidata dates within this many days count as agreeing (time zones, typos).
AGREE_DAYS = 1


def add_years(d: dt.date, years: int) -> dt.date:
    """``d`` plus whole years (29 February becomes 28 February in non-leap years)."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def interval(d: dt.date, precision: int | None) -> tuple[dt.date, dt.date]:
    """Return the birth-date range a Wikidata date stands for."""
    # Wikidata precision: 11 = day, 10 = month, 9 = year.
    if precision is None or precision >= 11:
        return d, d
    if precision == 10:
        return d.replace(day=1), d.replace(day=calendar.monthrange(d.year, d.month)[1])
    return dt.date(d.year, 1, 1), dt.date(d.year, 12, 31)


def combine(
    sources: list[tuple[str, dt.date, dt.date]],
) -> tuple[dt.date | None, dt.date | None, str | None, str | None]:
    """Intersect the sources' intervals; return (low, high, sources, problem).

    Two sources whose intervals miss each other by at most ``AGREE_DAYS`` still agree; the
    result then spans both. Further apart, they disagree.
    """
    if not sources:
        return None, None, None, "no birth date"
    names = "+".join(sorted({s[0] for s in sources}))
    lo = max(s[1] for s in sources)
    hi = min(s[2] for s in sources)
    if lo > hi:
        if (lo - hi).days > AGREE_DAYS:
            return None, None, names, "sources disagree"
        lo, hi = hi, lo
    return lo, hi, names, None


def status(lo: dt.date | None, hi: dt.date | None, window_start: dt.date) -> str:
    """Age status for one window, given the range of possible birth dates."""
    if lo is None or hi is None:
        return "unverified"
    if add_years(hi, 18) <= window_start:
        return "verified_adult"
    if add_years(lo, 18) > window_start:
        return "minor_during_season"
    return "unverified"


def windows(con: Any) -> dict[str, tuple[str, int | None, int | None, dt.date, dt.date]]:
    """Competition-season key -> (provider, competition, season, first match, last match)."""
    out = {}
    for c, s, a, b in con.execute(
        "select competition_id, season_id, min(match_date), max(match_date) from matches "
        "group by 1, 2"
    ).fetchall():
        out[f"statsbomb:{c}/{s}"] = ("statsbomb", c, s, a, b)
    for c, s, a, b in con.execute(
        "select competition_id, season_id, min(date_utc)::date, max(date_utc)::date "
        "from wy_matches group by 1, 2"
    ).fetchall():
        out[f"wyscout:{c}/{s}"] = ("wyscout", c, s, a, b)
    for key, (a, b) in _dfl_windows(con).items():
        out[key] = ("dfl", None, None, a, b)
    return out


def _dfl_competition(match: str) -> str:
    """DFL competition id for a match, from the raw file names (e.g. DFL-COM-000001)."""
    for kind, path in match_files(dfl_raw_dir()).get(match, {}).items():
        if kind == "meta" and "DFL-COM-" in path.name:
            return path.name.split("_DFL-MAT-")[0].rsplit("_", 1)[-1]
    return "DFL-COM-unknown"


def _dfl_windows(con: Any) -> dict[str, tuple[dt.date, dt.date]]:
    spans: dict[str, list[dt.date]] = defaultdict(list)
    for match, date in con.execute(
        "select distinct match_id, match_date from tracking_meta"
    ).fetchall():
        spans[f"dfl:{_dfl_competition(match)}/2022-23"].append(date)
    return {k: (min(v), max(v)) for k, v in spans.items()}


def build(parquet: Path) -> dict[str, int]:
    """Compute ``player_age_status`` for every person and competition-season."""
    con = store.connect()
    store.create_views(con, parquet)
    wins = windows(con)
    # Who appears where.
    appear: dict[str, set[str]] = defaultdict(set)
    for person, c, s in con.execute(
        """select x.person_id, m.competition_id, m.season_id
           from player_xref x join player_match_minutes m
             on x.provider = 'statsbomb' and m.player_id::varchar = x.provider_player_id
           group by all"""
    ).fetchall():
        appear[person].add(f"statsbomb:{c}/{s}")
    for person, c, s in con.execute(
        """select x.person_id, m.competition_id, m.season_id
           from player_xref x join wy_lineups l
             on x.provider = 'wyscout' and l.player_id::varchar = x.provider_player_id
           join wy_matches m using (match_id) group by all"""
    ).fetchall():
        appear[person].add(f"wyscout:{c}/{s}")
    for person, match in con.execute(
        """select x.person_id, l.match_id from player_xref x join dfl_lineups l
             on x.provider = 'dfl' and l.player_id = x.provider_player_id group by all"""
    ).fetchall():
        appear[person].add(f"dfl:{_dfl_competition(match)}/2022-23")
    # Birth-date sources.
    sources: dict[str, list[tuple[str, dt.date, dt.date]]] = defaultdict(list)
    for person, d, prec in con.execute(
        """select distinct x.person_id, w.birth_date, w.birth_date_precision
           from player_xref x join wikidata_people w using (qid)
           where w.birth_date is not null and x.confidence in ('high', 'medium')"""
    ).fetchall():
        sources[person].append(("wikidata", *interval(d, prec)))
    for person, d in con.execute(
        """select distinct x.person_id, p.birth_date from player_xref x join wy_players p
             on x.provider = 'wyscout' and p.player_id::varchar = x.provider_player_id
           where p.birth_date is not null"""
    ).fetchall():
        sources[person].append(("wyscout", d, d))
    con.close()

    rows = []
    for person, keys in appear.items():
        lo, hi, src, problem = combine(sources.get(person, []))
        for key in sorted(keys):
            prov, c, s, start, end = wins[key]
            st = status(lo, hi, start)
            rows.append(
                {
                    "person_id": person,
                    "competition_season": key,
                    "provider": prov,
                    "competition_id": c,
                    "season_id": s,
                    "window_start": start,
                    "window_end": end,
                    "status": st,
                    "birth_date_low": lo,
                    "birth_date_high": hi,
                    "birth_date_source": src,
                    "note": problem,
                }
            )
    n = write_single(parquet / "player_age_status.parquet", rows, PLAYER_AGE_STATUS)
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r["status"]] += 1
    return {"rows": n, "persons": len(appear), **counts}
