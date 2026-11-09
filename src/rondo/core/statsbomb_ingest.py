"""Build the shared StatsBomb Parquet tables, one match at a time.

Reads the pinned checkout (see :mod:`rondo.core.statsbomb_fetch`) and writes every table in
docs/DATA_CONTRACT.md except ``player_match_minutes`` and ``spadl_actions``, which have their
own modules. Run with ``python -m rondo.core.statsbomb_ingest``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import orjson

from rondo.core import schemas
from rondo.core.parquet_io import PartitionWriter, partition_path, reset_dir, write_single
from rondo.core.paths import parquet_dir, statsbomb_raw_dir
from rondo.core.scope import SCOPE, CompetitionSeason
from rondo.core.statsbomb_parse import parse_360, parse_events, parse_lineups, period_lengths

#: The tables this module writes (others, e.g. ``wy_*``, belong to other providers).
STATSBOMB_TABLES = {
    "competitions",
    "matches",
    "match_periods",
    "teams",
    "players",
    "lineups",
    "lineup_positions",
    "events",
    "shots",
    "shot_freeze_frames",
    "passes",
    "carries",
    "pressures",
    "defensive_actions",
    "frames_360",
    "visible_areas_360",
}

#: Matches per row group in partitioned files.
BATCH_MATCHES = 20


def _load(path: Path) -> Any:
    return orjson.loads(path.read_bytes())


def match_row(m: dict[str, Any], cs: CompetitionSeason) -> dict[str, Any]:
    """Flatten one entry of a StatsBomb matches file into a ``matches`` row."""
    meta = m.get("metadata") or {}
    stadium, referee = m.get("stadium") or {}, m.get("referee") or {}
    stage = m.get("competition_stage") or {}
    return {
        "match_id": m["match_id"],
        "competition_id": cs.competition_id,
        "season_id": cs.season_id,
        "scope": cs.scope,
        "match_date": dt.date.fromisoformat(m["match_date"]),
        "kick_off": m.get("kick_off"),
        "home_team_id": m["home_team"]["home_team_id"],
        "away_team_id": m["away_team"]["away_team_id"],
        "home_score": m.get("home_score"),
        "away_score": m.get("away_score"),
        "match_week": m.get("match_week"),
        "competition_stage": stage.get("name"),
        "stadium_id": stadium.get("id"),
        "stadium_name": stadium.get("name"),
        "referee_id": referee.get("id"),
        "referee_name": referee.get("name"),
        "match_status": m.get("match_status"),
        "match_status_360": m.get("match_status_360"),
        "data_version": meta.get("data_version"),
        "shot_fidelity_version": meta.get("shot_fidelity_version"),
        "xy_fidelity_version": meta.get("xy_fidelity_version"),
        "has_360": m.get("match_status_360") == "available",
    }


def _team_rows(m: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for side in ("home", "away"):
        t = m[f"{side}_team"]
        rows.append(
            {
                "team_id": t[f"{side}_team_id"],
                "team_name": t[f"{side}_team_name"],
                "team_gender": t.get(f"{side}_team_gender"),
                "country_name": (t.get("country") or {}).get("name"),
            }
        )
    return rows


class _Players:
    """Accumulate one players row per player_id across lineups."""

    def __init__(self) -> None:
        self.latest: dict[int, tuple[dt.date, dict[str, Any]]] = {}
        self.names: dict[int, set[tuple[str, str | None]]] = defaultdict(set)
        self.n: dict[int, int] = defaultdict(int)

    def add(self, lineups: list[dict[str, Any]], match_date: dt.date) -> None:
        for team in lineups:
            for p in team["lineup"]:
                pid = p["player_id"]
                self.n[pid] += 1
                self.names[pid].add((p["player_name"], p.get("player_nickname")))
                if pid not in self.latest or match_date >= self.latest[pid][0]:
                    self.latest[pid] = (match_date, p)

    def rows(self) -> list[dict[str, Any]]:
        out = []
        for pid, (_, p) in sorted(self.latest.items()):
            out.append(
                {
                    "player_id": pid,
                    "player_name": p["player_name"],
                    "player_nickname": p.get("player_nickname"),
                    "country_name": (p.get("country") or {}).get("name"),
                    "n_matches_listed": self.n[pid],
                    "n_name_variants": len(self.names[pid]),
                }
            )
        return out


def build(
    checkout: Path,
    out: Path,
    scope: Sequence[CompetitionSeason] = SCOPE,
    log: bool = True,
) -> dict[str, int]:
    """Build every StatsBomb table under ``out``; return row counts per table."""
    data = checkout / "data"
    own = [n for n in [*schemas.PARTITIONED, *schemas.SINGLE] if n in STATSBOMB_TABLES]
    for name in own:
        target = out / name if name in schemas.PARTITIONED else out / f"{name}.parquet"
        if target.is_dir():
            reset_dir(target)
        elif target.exists():
            target.unlink()

    comps = {(c["competition_id"], c["season_id"]): c for c in _load(data / "competitions.json")}
    small: dict[str, list[dict[str, Any]]] = defaultdict(list)
    teams: dict[int, dict[str, Any]] = {}
    players = _Players()
    counts: dict[str, int] = defaultdict(int)
    start = time.perf_counter()
    n_done = 0

    for cs in scope:
        c = comps[(cs.competition_id, cs.season_id)]
        small["competitions"].append(
            {
                "competition_id": cs.competition_id,
                "season_id": cs.season_id,
                "competition_name": c["competition_name"],
                "season_name": c["season_name"],
                "country_name": c.get("country_name"),
                "competition_gender": c.get("competition_gender"),
                "competition_youth": bool(c.get("competition_youth")),
                "competition_international": bool(c.get("competition_international")),
                "scope": cs.scope,
                "scope_group": cs.group,
            }
        )
        writers = {
            name: PartitionWriter(
                partition_path(out, name, competition_id=cs.competition_id, season_id=cs.season_id),
                schema,
            )
            for name, schema in schemas.PARTITIONED.items()
        }
        batch: dict[str, list[dict[str, Any]]] = defaultdict(list)
        matches = _load(data / "matches" / str(cs.competition_id) / f"{cs.season_id}.json")
        for i, m in enumerate(sorted(matches, key=lambda m: m["match_id"])):
            mid = m["match_id"]
            row = match_row(m, cs)
            small["matches"].append(row)
            for t in _team_rows(m):
                teams[t["team_id"]] = t
            events = _load(data / "events" / f"{mid}.json")
            for period, length in sorted(period_lengths(events).items()):
                small["match_periods"].append(
                    {"match_id": mid, "period": period, "length_s": length}
                )
            for name, rows in parse_events(events, mid).items():
                batch[name].extend(rows)
            del events
            lineups = _load(data / "lineups" / f"{mid}.json")
            players.add(lineups, row["match_date"])
            for name, rows in parse_lineups(lineups, mid).items():
                small[name].extend(rows)
            if row["has_360"]:
                for name, rows in parse_360(
                    _load(data / "three-sixty" / f"{mid}.json"), mid
                ).items():
                    batch[name].extend(rows)
            n_done += 1
            if (i + 1) % BATCH_MATCHES == 0:
                _flush(batch, writers, counts)
        _flush(batch, writers, counts)
        for w in writers.values():
            w.close()
        if log:
            print(
                f"{cs.competition_id}/{cs.season_id}: {len(matches)} matches "
                f"({n_done} total, {time.perf_counter() - start:.0f}s)",
                flush=True,
            )

    small["teams"] = sorted(teams.values(), key=lambda t: t["team_id"])
    small["players"] = players.rows()
    for name in ["competitions", "matches", "match_periods", "teams", "players", "lineups"]:
        counts[name] = write_single(out / f"{name}.parquet", small[name], schemas.SINGLE[name])
    counts["lineup_positions"] = write_single(
        out / "lineup_positions.parquet", small["lineup_positions"], schemas.LINEUP_POSITIONS
    )
    return dict(counts)


def _flush(
    batch: dict[str, list[dict[str, Any]]],
    writers: dict[str, PartitionWriter],
    counts: dict[str, int],
) -> None:
    for name, rows in batch.items():
        writers[name].write(rows)
        counts[name] += len(rows)
    batch.clear()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, default=statsbomb_raw_dir() / "open-data")
    parser.add_argument("--out", type=Path, default=parquet_dir())
    args = parser.parse_args(argv)
    counts = build(args.checkout, args.out)
    for name, n in sorted(counts.items()):
        print(f"{name}: {n} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
