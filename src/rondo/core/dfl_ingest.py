"""Load the DFL open data (Bassek et al., 2025) into the tracking tables.

- ``tracking_frames``: one row per object (each player, and the ball) per frame, loaded with
  kloppy's Sportec loader in the ``sportec`` coordinate system: metres, origin at the centre
  spot, x along the pitch length, y across it (bottom to top). Positions are absolute: teams
  swap ends at half-time (``tracking_meta.home_attacks`` says which way the home team attacks).
- ``tracking_meta``: one row per match and period (pitch size, frame rate, frame range).
- ``dfl_lineups``: the match sheet (from the match information file, via kloppy).
- ``dfl_events``: the official event feed, one row per ``<Event>`` element of the raw XML, with
  its DFL type. Read directly with lxml rather than kloppy: kloppy synthesises some events and
  drops others' types.

Run with ``python -m rondo.core.dfl_ingest``.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import pyarrow as pa
from lxml import etree

from rondo.core import schemas
from rondo.core.dfl_fetch import dfl_raw_dir
from rondo.core.parquet_io import PartitionWriter, partition_path, reset_dir, write_single
from rondo.core.paths import parquet_dir

#: Frames and events per match, from Bassek et al. (2025), Scientific Data 12:195, Table 1.
PUBLISHED: dict[str, tuple[int, int]] = {
    "J03WMX": (145_967, 1_840),
    "J03WN1": (141_561, 1_459),
    "J03WPY": (146_211, 1_579),
    "J03WOH": (137_214, 1_457),
    "J03WQQ": (142_345, 1_679),
    "J03WOY": (142_536, 1_578),
    "J03WR9": (146_810, 1_545),
}
CHUNK_FRAMES = 10_000


def match_files(raw: Path) -> dict[str, dict[str, Path]]:
    """Map each DFL match id (e.g. J03WMX) to its three files."""
    out: dict[str, dict[str, Path]] = {}
    kinds = {"matchinformation": "meta", "events_raw": "events", "positions_raw_observed": "pos"}
    for p in sorted(raw.glob("DFL_*.xml")):
        m = re.search(r"DFL-MAT-(\w+)\.xml$", p.name)
        kind = next((v for k, v in kinds.items() if k in p.name), None)
        if m and kind:
            out.setdefault(m.group(1), {})[kind] = p
    return out


def _flush(cols: dict[str, list], writer: PartitionWriter) -> int:
    n = len(cols["frame"])
    if n:
        writer.write_arrow(pa.table(cols, schema=schemas.TRACKING_FRAMES))
        for v in cols.values():
            v.clear()
    return n


def load_tracking(match: str, files: dict[str, Path], out: Path) -> tuple[list, list, int]:
    """Write one match's frames; return (meta rows, lineup rows, rows written)."""
    from kloppy import sportec

    ds = sportec.load_tracking(
        meta_data=files["meta"], raw_data=files["pos"], coordinates="sportec"
    )
    md = ds.metadata
    home, away = md.teams[0], md.teams[1]
    pitch = md.pitch_dimensions
    writer = PartitionWriter(
        partition_path(out, "tracking_frames", provider="dfl", match_id=match),
        schemas.TRACKING_FRAMES,
    )
    cols: dict[str, list] = {name: [] for name in schemas.TRACKING_FRAMES.names}
    written = 0
    per_period: dict[int, list[Any]] = {}
    for i, f in enumerate(ds.records):
        pid = f.period.id
        ts = f.timestamp.total_seconds()
        span = per_period.setdefault(pid, [f.frame_id, f.frame_id, 0, ts, ts])
        span[1], span[2], span[4] = f.frame_id, span[2] + 1, ts
        alive = f.ball_state is not None and f.ball_state.name == "ALIVE"
        owner = f.ball_owning_team.team_id if f.ball_owning_team else None
        objects: list[tuple[str, str | None, int | None, Any, Any]] = []
        if f.ball_coordinates is not None:
            objects.append(("ball", None, None, f.ball_coordinates, None))
        for player, pdata in f.players_data.items():
            if pdata.coordinates is None:
                continue
            objects.append(
                (
                    player.player_id,
                    player.team.team_id,
                    player.jersey_no,
                    pdata.coordinates,
                    pdata.speed,
                )
            )
        for obj_id, team, jersey, c, speed in objects:
            cols["provider"].append("dfl")
            cols["match_id"].append(match)
            cols["period"].append(pid)
            cols["frame"].append(f.frame_id)
            cols["time_s"].append(ts)
            cols["object_id"].append(obj_id)
            cols["team_id"].append(team)
            cols["jersey_no"].append(jersey)
            cols["x"].append(c.x)
            cols["y"].append(c.y)
            cols["z"].append(getattr(c, "z", None))
            cols["provider_speed"].append(speed)
            cols["ball_alive"].append(alive)
            cols["ball_owning_team_id"].append(owner)
        if (i + 1) % CHUNK_FRAMES == 0:
            written += _flush(cols, writer)
    written += _flush(cols, writer)
    writer.close()

    meta_rows = []
    date = md.date.date() if isinstance(md.date, dt.datetime) else md.date
    for pid, (first, last, n, start_s, end_s) in sorted(per_period.items()):
        attacks = md.orientation.name if md.orientation else None
        meta_rows.append(
            {
                "provider": "dfl",
                "match_id": match,
                "competition": None,
                "match_date": date,
                "home_team_id": home.team_id,
                "home_team_name": home.name,
                "away_team_id": away.team_id,
                "away_team_name": away.name,
                "pitch_length": pitch.pitch_length,
                "pitch_width": pitch.pitch_width,
                "frame_rate": md.frame_rate,
                "period": pid,
                "first_frame": first,
                "last_frame": last,
                "n_frames": n,
                "start_s": start_s,
                "end_s": end_s,
                "home_attacks": _home_attacks(attacks, pid),
            }
        )
    lineup_rows = [
        {
            "match_id": match,
            "team_id": team.team_id,
            "team_name": team.name,
            "player_id": p.player_id,
            "first_name": p.first_name,
            "last_name": p.last_name,
            "jersey_no": p.jersey_no,
            "starting": bool(p.starting),
            "starting_position": p.starting_position.name if p.starting_position else None,
        }
        for team in md.teams
        for p in team.players
    ]
    del ds
    return meta_rows, lineup_rows, written


def _home_attacks(orientation: str | None, period: int) -> str | None:
    """Which way the home team attacks in a period, from kloppy's orientation."""
    if orientation is None:
        return None
    first = {"HOME_AWAY": "right", "AWAY_HOME": "left"}.get(orientation)
    if first is None:
        return orientation.lower()
    if period % 2 == 1:
        return first
    return "left" if first == "right" else "right"


def _num(v: str | None) -> float | None:
    return float(v) if v not in (None, "") else None


def load_events(match: str, path: Path) -> list[dict[str, Any]]:
    """Every ``<Event>`` element of the raw DFL event file, with its type."""
    rows = []
    for ev in etree.parse(str(path)).getroot().iter("Event"):
        child = ev[0] if len(ev) else None
        grand = child[0] if child is not None and len(child) else None
        attrs = dict(child.attrib) if child is not None else {}
        if grand is not None:
            attrs = {**attrs, **{f"{grand.tag}.{k}": v for k, v in grand.attrib.items()}}

        rows.append(
            {
                "match_id": match,
                "event_id": ev.get("EventId"),
                "event_time": ev.get("EventTime"),
                "event_type": child.tag if child is not None else None,
                "event_subtype": grand.tag if grand is not None else None,
                "team_id": attrs.get("Team"),
                "player_id": attrs.get("Player"),
                "x": _num(ev.get("X-Position")),
                "y": _num(ev.get("Y-Position")),
                "attributes": json.dumps(attrs, ensure_ascii=False),
            }
        )
    return rows


def build(raw: Path, out: Path, log: bool = True) -> dict[str, int]:
    """Build every DFL table; return row counts."""
    if (out / "tracking_frames" / "provider=dfl").exists():
        reset_dir(out / "tracking_frames" / "provider=dfl")
    meta, lineups, events = [], [], []
    frames = 0
    start = time.perf_counter()
    for match, files in sorted(match_files(raw).items()):
        m, lu, n = load_tracking(match, files, out)
        meta += m
        lineups += lu
        frames += n
        events += load_events(match, files["events"])
        if log:
            print(
                f"dfl {match}: {sum(r['n_frames'] for r in m)} frames, {n} object rows "
                f"({time.perf_counter() - start:.0f}s)",
                flush=True,
            )
    return {
        "tracking_frames": frames,
        "tracking_meta": write_single(out / "tracking_meta.parquet", meta, schemas.TRACKING_META),
        "dfl_lineups": write_single(out / "dfl_lineups.parquet", lineups, schemas.DFL_LINEUPS),
        "dfl_events": write_single(out / "dfl_events.parquet", events, schemas.DFL_EVENTS),
    }


def main() -> int:
    """CLI entry point."""
    for k, v in build(dfl_raw_dir(), parquet_dir()).items():
        print(f"{k}: {v} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
