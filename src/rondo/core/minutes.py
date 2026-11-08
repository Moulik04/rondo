"""Minutes and positions per player per match (``player_match_minutes``).

Minutes come from the event stream, not from lineup position spells, which are internally
inconsistent in some matches (spells that run backwards in time or overlap; counted in
``reports/data_quality.md``):

- **on**: kick-off for players in the ``Starting XI`` event, else the ``Substitution`` event
  that brought them on;
- **off**: the ``Substitution`` event that took them off, a red or second-yellow card
  (``Foul Committed`` or ``Bad Behaviour``), else the end of the last period played.

Event times become elapsed time since kick-off using each period's measured length (its last
``Half End`` event), so stoppage time counts and breaks don't. The shootout (period 5) never
counts. Position groups split a player's minutes by the share of their events at each position.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from rondo.core import schemas
from rondo.core.parquet_io import write_single
from rondo.core.positions import position_group

RED_CARDS = ("Red Card", "Second Yellow")
#: Fallback period lengths when a period has no 'Half End' event (counted and reported).
NOMINAL_LENGTH = {1: 45 * 60.0, 2: 45 * 60.0, 3: 15 * 60.0, 4: 15 * 60.0}


@dataclass
class Clock:
    """Elapsed time since kick-off for one match, from its period lengths (periods 1-4)."""

    lengths: dict[int, float]
    start: dict[int, float] = field(init=False)
    end: float = field(init=False)

    def __post_init__(self) -> None:
        """Accumulate period start offsets."""
        self.start, total = {}, 0.0
        for p in sorted(self.lengths):
            self.start[p] = total
            total += self.lengths[p]
        self.end = total

    def elapsed(self, period: int, t: float) -> float:
        """Elapsed seconds for time ``t`` into ``period``; the match end for the shootout."""
        if period not in self.lengths:
            return self.end
        return self.start[period] + min(max(t, 0.0), self.lengths[period])


@dataclass
class _Player:
    team_id: int
    on: float | None = None
    off: float | None = None
    started: bool = False
    sent_off: bool = False


def _card(details: dict[str, Any]) -> str | None:
    for key in ("foul_committed", "bad_behaviour"):
        card = (details.get(key) or {}).get("card")
        if card:
            return card.get("name")
    return None


def match_minutes(
    key_events: list[tuple[Any, ...]], lengths: dict[int, float]
) -> tuple[dict[int, _Player], Clock]:
    """Compute on/off times for one match from its key events, in event order.

    ``key_events`` rows are (team_id, player_id, period, timestamp_s, type_name, details JSON).
    """
    clock = Clock(lengths)
    players: dict[int, _Player] = {}
    for team_id, player_id, period, ts, type_name, details_json in key_events:
        details = json.loads(details_json) if details_json else {}
        t = clock.elapsed(int(period), float(ts))
        if type_name == "Starting XI":
            for slot in (details.get("tactics") or {}).get("lineup", []):
                pid = slot["player"]["id"]
                players[pid] = _Player(team_id=int(team_id), on=0.0, started=True)
        elif type_name == "Substitution":
            if player_id is not None and player_id in players:
                players[player_id].off = t
            rep = ((details.get("substitution") or {}).get("replacement") or {}).get("id")
            if rep is not None:
                players[rep] = _Player(team_id=int(team_id), on=t)
        elif player_id is not None and _card(details) in RED_CARDS:
            p = players.get(player_id)
            # Only a red card shown while on the pitch ends a player's time. A card shown to
            # a substitute who hasn't come on, or one already taken off, leaves the team at 11.
            if p is not None and p.on is not None and p.off is None:
                p.sent_off = True
                p.off = t
    return players, clock


def build(parquet: Path) -> dict[str, int]:
    """Compute and write ``player_match_minutes.parquet``; return summary counts."""
    con = duckdb.connect()
    ev = f"read_parquet('{parquet}/events/**/*.parquet', hive_partitioning = true)"
    meta = {
        r[0]: (r[1], r[2])
        for r in con.sql(
            f"select match_id, competition_id, season_id from '{parquet}/matches.parquet'"
        ).fetchall()
    }
    lengths: dict[int, dict[int, float]] = defaultdict(dict)
    for mid, period, length in con.sql(
        f"select match_id, period, length_s from '{parquet}/match_periods.parquet' "
        "where period <= 4"
    ).fetchall():
        lengths[mid][int(period)] = float(length)
    key = defaultdict(list)
    for row in con.sql(
        f"""select match_id, team_id, player_id, period, timestamp_s, type_name, details
            from {ev}
            where type_name in ('Starting XI', 'Substitution', 'Foul Committed', 'Bad Behaviour')
              and period <= 4
            order by match_id, index"""
    ).fetchall():
        key[row[0]].append(row[1:])
    pos_counts: dict[tuple[int, int], Counter[str]] = defaultdict(Counter)
    for mid, pid, position_id, n in con.sql(
        f"""select match_id, player_id, position_id, count(*) from {ev}
            where player_id is not null and period <= 4 group by all"""
    ).fetchall():
        g = position_group(position_id)
        if g:
            pos_counts[(mid, pid)][g] += n

    rows: list[dict[str, Any]] = []
    fallbacks = 0
    for mid in sorted(meta):
        ls = dict(lengths.get(mid, {}))
        for p in (1, 2):
            if p not in ls:
                ls[p] = NOMINAL_LENGTH[p]
                fallbacks += 1
        players, clock = match_minutes(key.get(mid, []), ls)
        for pid, p in sorted(players.items()):
            if p.on is None:
                continue  # carded from the bench: never on the pitch
            off = clock.end if p.off is None else p.off
            minutes = max(off - p.on, 0.0) / 60
            if minutes <= 0:
                continue
            counts = pos_counts.get((mid, pid), Counter())
            total = sum(counts.values())
            by_group = (
                {g: round(minutes * n / total, 2) for g, n in sorted(counts.items())}
                if total
                else {}
            )
            comp, season = meta[mid]
            rows.append(
                {
                    "match_id": mid,
                    "team_id": p.team_id,
                    "player_id": pid,
                    "competition_id": comp,
                    "season_id": season,
                    "started": p.started,
                    "minutes": minutes,
                    "minute_on": p.on / 60,
                    "minute_off": off / 60,
                    "sent_off": p.sent_off,
                    "primary_position_group": counts.most_common(1)[0][0] if counts else None,
                    "minutes_by_group": json.dumps(by_group),
                }
            )
    n = write_single(parquet / "player_match_minutes.parquet", rows, schemas.PLAYER_MATCH_MINUTES)
    return {"rows": n, "period_length_fallbacks": fallbacks}
