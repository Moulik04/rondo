"""Turn one StatsBomb match's raw JSON into rows for each shared table.

Pure functions: no files, no global state. :mod:`rondo.core.statsbomb_ingest` drives them
match by match and writes the rows through the schemas in :mod:`rondo.core.schemas`.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import orjson
from shapely.geometry import Polygon

from rondo.core.positions import position_group

Row = dict[str, Any]
Rows = dict[str, list[Row]]

#: Event keys stored as their own columns; everything else goes into ``details`` JSON.
_EVENT_CORE_KEYS = {
    "id",
    "index",
    "period",
    "timestamp",
    "minute",
    "second",
    "type",
    "possession",
    "possession_team",
    "play_pattern",
    "team",
    "player",
    "position",
    "location",
    "duration",
    "under_pressure",
    "off_camera",
    "out",
    "counterpress",
    "related_events",
}

DEFENSIVE_TYPES = {
    "Duel",
    "Interception",
    "Block",
    "Clearance",
    "Ball Recovery",
    "50/50",
    "Foul Committed",
    "Shield",
}
_SUCCESS = {"Won", "Success", "Success In Play", "Success Out", "Success To Team"}
_FAIL = {"Lost", "Lost In Play", "Lost Out", "Success To Opposition"}
RED_CARDS = {"Red Card", "Second Yellow"}


def timestamp_to_s(ts: str) -> float:
    """Convert StatsBomb's 'HH:MM:SS.fff' period timestamp to seconds."""
    h, m, sec = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(sec)


def clock_to_s(clock: str | None) -> float | None:
    """Convert a lineup clock 'MM:SS' (minutes may exceed 59) to seconds."""
    if clock is None:
        return None
    m, sec = clock.split(":")
    return int(m) * 60 + float(sec)


def _xy(loc: list[float] | None) -> tuple[float | None, float | None]:
    if not loc:
        return None, None
    return float(loc[0]), float(loc[1])


def _name(obj: dict[str, Any] | None) -> str | None:
    return obj.get("name") if obj else None


def _id(obj: dict[str, Any] | None) -> int | None:
    return obj.get("id") if obj else None


def _success(outcome: str | None) -> bool | None:
    if outcome in _SUCCESS:
        return True
    if outcome in _FAIL:
        return False
    return None


def _base(e: dict[str, Any], match_id: int) -> Row:
    x, y = _xy(e.get("location"))
    return {
        "event_id": e["id"],
        "match_id": match_id,
        "team_id": _id(e.get("team")),
        "player_id": _id(e.get("player")),
        "period": e["period"],
        "timestamp_s": timestamp_to_s(e["timestamp"]),
        "x": x,
        "y": y,
    }


def parse_events(events: list[dict[str, Any]], match_id: int) -> Rows:
    """Parse a match's events into rows for events and the typed event tables."""
    out: Rows = defaultdict(list)
    for e in events:
        etype = e["type"]["name"]
        base = _base(e, match_id)
        details = {k: v for k, v in e.items() if k not in _EVENT_CORE_KEYS}
        out["events"].append(
            {
                **base,
                "index": e["index"],
                "minute": e["minute"],
                "second": e["second"],
                "type_id": e["type"]["id"],
                "type_name": etype,
                "possession": e.get("possession"),
                "possession_team_id": _id(e.get("possession_team")),
                "play_pattern": _name(e.get("play_pattern")),
                "position_id": _id(e.get("position")),
                "position_name": _name(e.get("position")),
                "duration": e.get("duration"),
                "under_pressure": bool(e.get("under_pressure", False)),
                "off_camera": bool(e.get("off_camera", False)),
                "out": bool(e.get("out", False)),
                "counterpress": bool(e.get("counterpress", False)),
                "related_events": e.get("related_events", []),
                "details": orjson.dumps(details).decode() if details else None,
            }
        )
        under = bool(e.get("under_pressure", False))
        if etype == "Shot":
            out["shots"].append(_shot_row(e, base, under))
            for slot in e["shot"].get("freeze_frame", []):
                fx, fy = _xy(slot.get("location"))
                out["shot_freeze_frames"].append(
                    {
                        "event_id": e["id"],
                        "match_id": match_id,
                        "player_id": _id(slot.get("player")),
                        "position_name": _name(slot.get("position")),
                        "teammate": bool(slot.get("teammate", False)),
                        "x": fx,
                        "y": fy,
                    }
                )
        elif etype == "Pass":
            out["passes"].append(_pass_row(e, base, under))
        elif etype == "Carry":
            ex, ey = _xy(e["carry"].get("end_location"))
            out["carries"].append(
                {
                    **base,
                    "end_x": ex,
                    "end_y": ey,
                    "duration": e.get("duration"),
                    "under_pressure": under,
                }
            )
        elif etype == "Pressure":
            out["pressures"].append(
                {
                    **base,
                    "duration": e.get("duration"),
                    "counterpress": bool(e.get("counterpress", False)),
                }
            )
        if etype in DEFENSIVE_TYPES:
            out["defensive_actions"].append(_defensive_row(e, etype, base, under))
    return out


def _shot_row(e: dict[str, Any], base: Row, under: bool) -> Row:
    shot = e["shot"]
    end = shot.get("end_location") or []
    outcome = _name(shot.get("outcome"))
    shot_type = _name(shot.get("type"))
    return {
        **base,
        "minute": e["minute"],
        "second": e["second"],
        "end_x": end[0] if len(end) > 0 else None,
        "end_y": end[1] if len(end) > 1 else None,
        "end_z": end[2] if len(end) > 2 else None,
        "statsbomb_xg": shot.get("statsbomb_xg"),
        "shot_type": shot_type,
        "outcome": outcome,
        "is_goal": outcome == "Goal",
        "is_penalty": shot_type == "Penalty",
        "body_part": _name(shot.get("body_part")),
        "technique": _name(shot.get("technique")),
        "first_time": bool(shot.get("first_time", False)),
        "one_on_one": bool(shot.get("one_on_one", False)),
        "open_goal": bool(shot.get("open_goal", False)),
        "aerial_won": bool(shot.get("aerial_won", False)),
        "deflected": bool(shot.get("deflected", False)),
        "follows_dribble": bool(shot.get("follows_dribble", False)),
        "under_pressure": under,
        "key_pass_id": shot.get("key_pass_id"),
        "has_freeze_frame": bool(shot.get("freeze_frame")),
        "play_pattern": _name(e.get("play_pattern")),
    }


def _pass_row(e: dict[str, Any], base: Row, under: bool) -> Row:
    p = e["pass"]
    ex, ey = _xy(p.get("end_location"))
    outcome = _name(p.get("outcome"))
    return {
        **base,
        "end_x": ex,
        "end_y": ey,
        "length": p.get("length"),
        "angle": p.get("angle"),
        "height": _name(p.get("height")),
        "recipient_id": _id(p.get("recipient")),
        "outcome": outcome,
        "is_complete": outcome is None,
        "pass_type": _name(p.get("type")),
        "body_part": _name(p.get("body_part")),
        "technique": _name(p.get("technique")),
        "cross": bool(p.get("cross", False)),
        "switch": bool(p.get("switch", False)),
        "cut_back": bool(p.get("cut_back", False)),
        "through_ball": bool(p.get("through_ball", False))
        or _name(p.get("technique")) == "Through Ball",
        "shot_assist": bool(p.get("shot_assist", False)),
        "goal_assist": bool(p.get("goal_assist", False)),
        "aerial_won": bool(p.get("aerial_won", False)),
        "deflected": bool(p.get("deflected", False)),
        "miscommunication": bool(p.get("miscommunication", False)),
        "under_pressure": under,
        "assisted_shot_id": p.get("assisted_shot_id"),
        "play_pattern": _name(e.get("play_pattern")),
    }


def _defensive_row(e: dict[str, Any], etype: str, base: Row, under: bool) -> Row:
    key = {"Ball Recovery": "ball_recovery", "50/50": "50_50", "Foul Committed": "foul_committed"}
    obj = e.get(key.get(etype, etype.lower()), {}) or {}
    subtype = _name(obj.get("type"))
    outcome = _name(obj.get("outcome"))
    if etype == "Ball Recovery":
        success: bool | None = not obj.get("recovery_failure", False)
    elif etype == "Duel" and subtype == "Aerial Lost":
        success = False
    else:
        success = _success(outcome)
    return {
        **base,
        "action": etype,
        "subtype": subtype,
        "outcome": outcome,
        "is_success": success,
        "card": _name(obj.get("card")),
        "counterpress": bool(e.get("counterpress", False)),
        "under_pressure": under,
    }


def period_lengths(events: list[dict[str, Any]]) -> dict[int, float]:
    """Return {period: length in seconds} from each period's latest 'Half End' event."""
    lengths: dict[int, float] = {}
    for e in events:
        if e["type"]["name"] == "Half End":
            t = timestamp_to_s(e["timestamp"])
            lengths[e["period"]] = max(t, lengths.get(e["period"], 0.0))
    return lengths


def parse_lineups(lineups: list[dict[str, Any]], match_id: int) -> Rows:
    """Parse a match's lineups into lineups and lineup_positions rows."""
    out: Rows = defaultdict(list)
    for team in lineups:
        for p in team["lineup"]:
            cards = p.get("cards", [])
            reds = [c for c in cards if c.get("card_type") in RED_CARDS]
            red_clock = clock_to_s(reds[0]["time"]) if reds else None
            positions = p.get("positions", [])
            out["lineups"].append(
                {
                    "match_id": match_id,
                    "team_id": team["team_id"],
                    "player_id": p["player_id"],
                    "jersey_number": p.get("jersey_number"),
                    "started": any(q.get("start_reason") == "Starting XI" for q in positions),
                    "n_cards": len(cards),
                    "red_card_minute": red_clock / 60 if red_clock is not None else None,
                    "cards": orjson.dumps(cards).decode(),
                }
            )
            for i, q in enumerate(positions):
                out["lineup_positions"].append(
                    {
                        "match_id": match_id,
                        "team_id": team["team_id"],
                        "player_id": p["player_id"],
                        "spell": i,
                        "position_id": q.get("position_id"),
                        "position_name": q.get("position"),
                        "position_group": position_group(q.get("position_id")),
                        "from_clock_s": clock_to_s(q.get("from")),
                        "to_clock_s": clock_to_s(q.get("to")),
                        "from_period": q.get("from_period"),
                        "to_period": q.get("to_period"),
                        "start_reason": q.get("start_reason"),
                        "end_reason": q.get("end_reason"),
                    }
                )
    return out


def parse_360(frames: list[dict[str, Any]], match_id: int) -> Rows:
    """Parse a match's 360 frames into frames_360 and visible_areas_360 rows."""
    out: Rows = defaultdict(list)
    for f in frames:
        area = f.get("visible_area") or []
        pts = list(zip(area[0::2], area[1::2], strict=False))
        poly = Polygon(pts) if len(pts) >= 3 else None
        ff = f.get("freeze_frame") or []
        out["visible_areas_360"].append(
            {
                "event_id": f["event_uuid"],
                "match_id": match_id,
                "polygon": [float(v) for v in area],
                "n_points": len(pts),
                "is_valid": bool(poly is not None and poly.is_valid),
                "area": float(poly.area) if poly is not None else None,
                "n_visible_players": len(ff),
            }
        )
        for slot, p in enumerate(ff):
            x, y = _xy(p.get("location"))
            out["frames_360"].append(
                {
                    "event_id": f["event_uuid"],
                    "match_id": match_id,
                    "slot": slot,
                    "teammate": bool(p.get("teammate", False)),
                    "actor": bool(p.get("actor", False)),
                    "keeper": bool(p.get("keeper", False)),
                    "x": x,
                    "y": y,
                }
            )
    return out
