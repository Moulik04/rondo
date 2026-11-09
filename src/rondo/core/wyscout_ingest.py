r"""Build the Wyscout tables (``wy_*``) and Wyscout SPADL actions.

Each competition's events file is parsed once and processed match by match: raw events go to
``wy_events`` (partitioned by competition and season), and each match is converted to SPADL
with socceraction into ``spadl_actions/provider=wyscout/...``.

Name fix: 899 player and 8 team names in the raw files carry literal ``\\uXXXX`` escapes
(e.g. ``Konat\\u00e9``). They are decoded, and invisible soft hyphens (U+00AD) removed.

Run with ``python -m rondo.core.wyscout_ingest``.
"""

from __future__ import annotations

import datetime as dt
import re
import sys
import time
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any

import orjson
import pandas as pd

from rondo.core import schemas
from rondo.core.parquet_io import PartitionWriter, partition_path, reset_dir, write_single
from rondo.core.paths import parquet_dir
from rondo.core.wyscout_fetch import wyscout_raw_dir

#: Wyscout competition id -> (file suffix, published counts: matches, events, players), from
#: Pappalardo et al. (2019), Scientific Data 6:236, Table 1.
COMPETITIONS: dict[int, tuple[str, int, int, int]] = {
    795: ("Spain", 380, 628_659, 619),
    364: ("England", 380, 643_150, 603),
    524: ("Italy", 380, 647_372, 686),
    426: ("Germany", 306, 519_407, 537),
    412: ("France", 380, 632_807, 629),
    28: ("World_Cup", 64, 101_759, 736),
    102: ("European_Championship", 51, 78_140, 552),
}
PUBLISHED_TOTALS = (1_941, 3_251_294, 4_299)
PERIODS = {"1H": 1, "2H": 2, "E1": 3, "E2": 4, "P": 5}
_ESC = re.compile(r"\\u([0-9a-fA-F]{4})")


def fix_name(s: str | None) -> str | None:
    r"""Decode literal ``\\uXXXX`` escapes and drop soft hyphens."""
    if s is None:
        return None
    return _ESC.sub(lambda m: chr(int(m.group(1), 16)), s).replace("­", "")


def _load(path: Path) -> Any:
    return orjson.loads(path.read_bytes())


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def match_row(m: dict[str, Any]) -> dict[str, Any]:
    """Flatten one Wyscout match into a ``wy_matches`` row."""
    sides = {d["side"]: d for d in m["teamsData"].values()}
    h, a = sides["home"], sides["away"]
    return {
        "match_id": m["wyId"],
        "competition_id": m["competitionId"],
        "season_id": m["seasonId"],
        "round_id": m.get("roundId"),
        "gameweek": m.get("gameweek"),
        "date_utc": dt.datetime.fromisoformat(m["dateutc"]),
        "label": fix_name(m.get("label")),
        "status": m.get("status"),
        "duration": m.get("duration"),
        "venue": fix_name(m.get("venue")),
        "home_team_id": h["teamId"],
        "away_team_id": a["teamId"],
        "home_score": h["score"],
        "away_score": a["score"],
        "home_score_ht": h["scoreHT"],
        "away_score_ht": a["scoreHT"],
        "home_score_et": h["scoreET"],
        "away_score_et": a["scoreET"],
        "home_score_p": h["scoreP"],
        "away_score_p": a["scoreP"],
        # Goals before any shootout: scoreET is cumulative after extra time (0 if none).
        "home_goals": max(h["score"], h["scoreET"]),
        "away_goals": max(a["score"], a["scoreET"]),
    }


def lineup_rows(m: dict[str, Any]) -> list[dict[str, Any]]:
    """Lineup, bench and substitution rows for one match."""
    rows = []
    for d in m["teamsData"].values():
        f = d.get("formation") or {}
        # 6 team-matches (5 England, 1 France) store substitutions as the string "null".
        subs = f.get("substitutions")
        subs = subs if isinstance(subs, list) else []
        subs_in = {s["playerIn"]: s["minute"] for s in subs}
        subs_out = {s["playerOut"]: s["minute"] for s in subs}
        for status in ("lineup", "bench"):
            for p in f.get(status) or []:
                pid = p["playerId"]
                rows.append(
                    {
                        "match_id": m["wyId"],
                        "team_id": d["teamId"],
                        "player_id": pid,
                        "status": status,
                        "goals": _int(p.get("goals")),
                        "own_goals": _int(p.get("ownGoals")),
                        "assists": _int(p.get("assists")),
                        "yellow_cards": _int(p.get("yellowCards")),
                        "red_cards": _int(p.get("redCards")),
                        "sub_in_minute": subs_in.get(pid),
                        "sub_out_minute": subs_out.get(pid),
                    }
                )
    return rows


def event_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten raw events into ``wy_events`` rows (0-100 coordinates, as given)."""
    rows = []
    for e in events:
        pos = e.get("positions") or []
        start = pos[0] if len(pos) > 0 else {}
        end = pos[1] if len(pos) > 1 else {}
        rows.append(
            {
                "event_id": e["id"],
                "match_id": e["matchId"],
                "period": PERIODS.get(e["matchPeriod"]),
                "match_period": e["matchPeriod"],
                "event_sec": e["eventSec"],
                "type_id": _int(e.get("eventId")),
                "type_name": e.get("eventName"),
                "subtype_id": _int(e.get("subEventId")),
                "subtype_name": e.get("subEventName"),
                "team_id": e.get("teamId"),
                "player_id": e.get("playerId") or None,
                "x": start.get("x"),
                "y": start.get("y"),
                "end_x": end.get("x"),
                "end_y": end.get("y"),
                "tags": [t["id"] for t in e.get("tags") or []],
            }
        )
    return rows


def spadl_rows(events: list[dict[str, Any]], match_id: int, home_team_id: int) -> list[dict]:
    """Convert one match's raw events to SPADL rows (left to right per team)."""
    from socceraction import spadl
    from socceraction.data.wyscout.loader import _convert_events

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ev = _convert_events(pd.DataFrame(events))
        actions = spadl.wyscout.convert_to_actions(ev, home_team_id)
        actions = spadl.play_left_to_right(actions, home_team_id)
        actions = spadl.add_names(actions)
    out = pd.DataFrame(
        {
            "provider": "wyscout",
            "match_id": match_id,
            "action_id": actions["action_id"].astype(int),
            "original_event_id": actions["original_event_id"].astype(object),
            "period_id": actions["period_id"].astype(int),
            "time_seconds": actions["time_seconds"].astype(float),
            "team_id": actions["team_id"].astype(int),
            "player_id": actions["player_id"].astype("Int64"),
            "start_x": actions["start_x"],
            "start_y": actions["start_y"],
            "end_x": actions["end_x"],
            "end_y": actions["end_y"],
            "type_id": actions["type_id"].astype(int),
            "result_id": actions["result_id"].astype(int),
            "bodypart_id": actions["bodypart_id"].astype(int),
            "type_name": actions["type_name"],
            "result_name": actions["result_name"],
            "bodypart_name": actions["bodypart_name"],
        }
    )
    rows = out.to_dict("records")
    for r in rows:
        for col in ("player_id", "original_event_id"):
            if pd.isna(r[col]):
                r[col] = None
            elif col == "original_event_id":
                r[col] = str(int(float(r[col])))
        if r["player_id"] == 0:
            r["player_id"] = None
    return rows


def build(raw: Path, out: Path, competitions: dict | None = None, log: bool = True) -> dict:
    """Build every ``wy_*`` table and Wyscout SPADL; return row counts."""
    competitions = competitions or COMPETITIONS
    for name in ("wy_events",):
        if (out / name).exists():
            reset_dir(out / name)
    spadl_root = out / "spadl_actions" / "provider=wyscout"
    if spadl_root.exists():
        reset_dir(spadl_root)
    counts: dict[str, int] = defaultdict(int)
    small: dict[str, list[dict[str, Any]]] = defaultdict(list)
    start = time.perf_counter()

    comps = {c["wyId"]: c for c in _load(raw / "competitions.json")}
    for cid in competitions:
        c = comps[cid]
        small["wy_competitions"].append(
            {
                "competition_id": cid,
                "name": c["name"],
                "area_name": (c.get("area") or {}).get("name"),
                "format": c.get("format"),
                "type": c.get("type"),
            }
        )
    for cid, (suffix, *_published) in competitions.items():
        matches = _load(raw / f"matches_{suffix}.json")
        homes = {}
        for m in matches:
            row = match_row(m)
            small["wy_matches"].append(row)
            small["wy_lineups"].extend(lineup_rows(m))
            homes[m["wyId"]] = (row["home_team_id"], row["season_id"])
        season = {s for _, s in homes.values()}
        if len(season) != 1:
            raise ValueError(f"competition {cid}: expected one season, found {season}")
        sid = season.pop()
        by_match: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for e in _load(raw / f"events_{suffix}.json"):
            by_match[e["matchId"]].append(e)
        ev_writer = PartitionWriter(
            partition_path(out, "wy_events", competition_id=cid, season_id=sid), schemas.WY_EVENTS
        )
        sp_writer = PartitionWriter(
            partition_path(
                out / "spadl_actions", "provider=wyscout", competition_id=cid, season_id=sid
            ),
            schemas.SPADL_ACTIONS,
        )
        for mid in sorted(by_match):
            evs = by_match.pop(mid)
            rows = event_rows(evs)
            ev_writer.write(rows)
            counts["wy_events"] += len(rows)
            home = homes[mid][0] if mid in homes else None
            if home is None:
                raise ValueError(f"events for match {mid} with no row in matches_{suffix}.json")
            srows = spadl_rows(evs, mid, home)
            sp_writer.write(srows)
            counts["spadl_actions(wyscout)"] += len(srows)
        ev_writer.close()
        sp_writer.close()
        if log:
            print(
                f"wyscout {suffix}: {len(matches)} matches, {counts['wy_events']} events so far "
                f"({time.perf_counter() - start:.0f}s)",
                flush=True,
            )

    for t in _load(raw / "teams.json"):
        small["wy_teams"].append(
            {
                "team_id": t["wyId"],
                "name": fix_name(t.get("name")),
                "official_name": fix_name(t.get("officialName")),
                "city": fix_name(t.get("city")),
                "area_name": (t.get("area") or {}).get("name"),
                "type": t.get("type"),
            }
        )
    for p in _load(raw / "players.json"):
        bd = p.get("birthDate")
        small["wy_players"].append(
            {
                "player_id": p["wyId"],
                "short_name": fix_name(p.get("shortName")),
                "first_name": fix_name(p.get("firstName")),
                "middle_name": fix_name(p.get("middleName")) or None,
                "last_name": fix_name(p.get("lastName")),
                "birth_date": dt.date.fromisoformat(bd) if bd else None,
                "role": (p.get("role") or {}).get("code2"),
                "foot": p.get("foot") or None,
                "height": _int(p.get("height")) or None,
                "weight": _int(p.get("weight")) or None,
                "birth_area": (p.get("birthArea") or {}).get("name"),
                "passport_area": (p.get("passportArea") or {}).get("name"),
                "current_team_id": _int(p.get("currentTeamId")) or None,
                "current_national_team_id": _int(p.get("currentNationalTeamId")) or None,
            }
        )
    for name in ("wy_competitions", "wy_matches", "wy_teams", "wy_players", "wy_lineups"):
        counts[name] = write_single(out / f"{name}.parquet", small[name], schemas.SINGLE[name])
    return dict(counts)


def main() -> int:
    """CLI entry point."""
    counts = build(wyscout_raw_dir(), parquet_dir())
    for k, v in sorted(counts.items()):
        print(f"{k}: {v} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
