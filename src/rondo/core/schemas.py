"""pyarrow schemas for every shared table. These are the code side of docs/DATA_CONTRACT.md."""

from __future__ import annotations

import pyarrow as pa

i16, i32, f32, f64 = pa.int16(), pa.int32(), pa.float32(), pa.float64()
s, b = pa.string(), pa.bool_()


def _schema(*cols: tuple[str, pa.DataType]) -> pa.Schema:
    return pa.schema([pa.field(name, typ) for name, typ in cols])


_EV = (("event_id", s), ("match_id", i32))
_ACTOR = (("team_id", i32), ("player_id", i32), ("period", i16), ("timestamp_s", f64))

COMPETITIONS = _schema(
    ("competition_id", i32),
    ("season_id", i32),
    ("competition_name", s),
    ("season_name", s),
    ("country_name", s),
    ("competition_gender", s),
    ("competition_youth", b),
    ("competition_international", b),
    ("scope", s),
    ("scope_group", s),
)

MATCHES = _schema(
    ("match_id", i32),
    ("competition_id", i32),
    ("season_id", i32),
    ("scope", s),
    ("match_date", pa.date32()),
    ("kick_off", s),
    ("home_team_id", i32),
    ("away_team_id", i32),
    ("home_score", i16),
    ("away_score", i16),
    ("match_week", i16),
    ("competition_stage", s),
    ("stadium_id", i32),
    ("stadium_name", s),
    ("referee_id", i32),
    ("referee_name", s),
    ("match_status", s),
    ("match_status_360", s),
    ("data_version", s),
    ("shot_fidelity_version", s),
    ("xy_fidelity_version", s),
    ("has_360", b),
)

MATCH_PERIODS = _schema(("match_id", i32), ("period", i16), ("length_s", f64))

TEAMS = _schema(("team_id", i32), ("team_name", s), ("team_gender", s), ("country_name", s))

PLAYERS = _schema(
    ("player_id", i32),
    ("player_name", s),
    ("player_nickname", s),
    ("country_name", s),
    ("n_matches_listed", i32),
    ("n_name_variants", i16),
)

LINEUPS = _schema(
    ("match_id", i32),
    ("team_id", i32),
    ("player_id", i32),
    ("jersey_number", i16),
    ("started", b),
    ("n_cards", i16),
    ("red_card_minute", f32),
    ("cards", s),
)

LINEUP_POSITIONS = _schema(
    ("match_id", i32),
    ("team_id", i32),
    ("player_id", i32),
    ("spell", i16),
    ("position_id", i16),
    ("position_name", s),
    ("position_group", s),
    ("from_clock_s", f32),
    ("to_clock_s", f32),
    ("from_period", i16),
    ("to_period", i16),
    ("start_reason", s),
    ("end_reason", s),
)

EVENTS = _schema(
    *_EV,
    ("index", i32),
    ("period", i16),
    ("timestamp_s", f64),
    ("minute", i16),
    ("second", i16),
    ("type_id", i16),
    ("type_name", s),
    ("possession", i32),
    ("possession_team_id", i32),
    ("play_pattern", s),
    ("team_id", i32),
    ("player_id", i32),
    ("position_id", i16),
    ("position_name", s),
    ("x", f32),
    ("y", f32),
    ("duration", f32),
    ("under_pressure", b),
    ("off_camera", b),
    ("out", b),
    ("counterpress", b),
    ("related_events", pa.list_(s)),
    ("details", s),
)

SHOTS = _schema(
    *_EV,
    ("team_id", i32),
    ("player_id", i32),
    ("period", i16),
    ("minute", i16),
    ("second", i16),
    ("timestamp_s", f64),
    ("x", f32),
    ("y", f32),
    ("end_x", f32),
    ("end_y", f32),
    ("end_z", f32),
    ("statsbomb_xg", f32),
    ("shot_type", s),
    ("outcome", s),
    ("is_goal", b),
    ("is_penalty", b),
    ("body_part", s),
    ("technique", s),
    ("first_time", b),
    ("one_on_one", b),
    ("open_goal", b),
    ("aerial_won", b),
    ("deflected", b),
    ("follows_dribble", b),
    ("under_pressure", b),
    ("key_pass_id", s),
    ("has_freeze_frame", b),
    ("play_pattern", s),
)

SHOT_FREEZE_FRAMES = _schema(
    *_EV,
    ("player_id", i32),
    ("position_name", s),
    ("teammate", b),
    ("x", f32),
    ("y", f32),
)

PASSES = _schema(
    *_EV,
    *_ACTOR,
    ("x", f32),
    ("y", f32),
    ("end_x", f32),
    ("end_y", f32),
    ("length", f32),
    ("angle", f32),
    ("height", s),
    ("recipient_id", i32),
    ("outcome", s),
    ("is_complete", b),
    ("pass_type", s),
    ("body_part", s),
    ("technique", s),
    ("cross", b),
    ("switch", b),
    ("cut_back", b),
    ("through_ball", b),
    ("shot_assist", b),
    ("goal_assist", b),
    ("aerial_won", b),
    ("deflected", b),
    ("miscommunication", b),
    ("under_pressure", b),
    ("assisted_shot_id", s),
    ("play_pattern", s),
)

CARRIES = _schema(
    *_EV,
    *_ACTOR,
    ("x", f32),
    ("y", f32),
    ("end_x", f32),
    ("end_y", f32),
    ("duration", f32),
    ("under_pressure", b),
)

PRESSURES = _schema(*_EV, *_ACTOR, ("x", f32), ("y", f32), ("duration", f32), ("counterpress", b))

DEFENSIVE_ACTIONS = _schema(
    *_EV,
    *_ACTOR,
    ("x", f32),
    ("y", f32),
    ("action", s),
    ("subtype", s),
    ("outcome", s),
    ("is_success", b),
    ("card", s),
    ("counterpress", b),
    ("under_pressure", b),
)

FRAMES_360 = _schema(
    *_EV,
    ("slot", i16),
    ("teammate", b),
    ("actor", b),
    ("keeper", b),
    ("x", f32),
    ("y", f32),
)

VISIBLE_AREAS_360 = _schema(
    *_EV,
    ("polygon", pa.list_(f32)),
    ("n_points", i16),
    ("is_valid", b),
    ("area", f32),
    ("n_visible_players", i16),
)

PLAYER_MATCH_MINUTES = _schema(
    ("match_id", i32),
    ("team_id", i32),
    ("player_id", i32),
    ("competition_id", i32),
    ("season_id", i32),
    ("started", b),
    ("minutes", f32),
    ("minute_on", f32),
    ("minute_off", f32),
    ("sent_off", b),
    ("primary_position_group", s),
    ("minutes_by_group", s),
)

SPADL_ACTIONS = _schema(
    ("provider", s),
    ("match_id", i32),
    ("action_id", i32),
    ("original_event_id", s),
    ("period_id", i16),
    ("time_seconds", f64),
    ("team_id", i32),
    ("player_id", i32),
    ("start_x", f32),
    ("start_y", f32),
    ("end_x", f32),
    ("end_y", f32),
    ("type_id", i16),
    ("result_id", i16),
    ("bodypart_id", i16),
    ("type_name", s),
    ("result_name", s),
    ("bodypart_name", s),
)

#: Tables partitioned by competition and season (spadl_actions also by provider).
PARTITIONED: dict[str, pa.Schema] = {
    "events": EVENTS,
    "shots": SHOTS,
    "shot_freeze_frames": SHOT_FREEZE_FRAMES,
    "passes": PASSES,
    "carries": CARRIES,
    "pressures": PRESSURES,
    "defensive_actions": DEFENSIVE_ACTIONS,
    "frames_360": FRAMES_360,
    "visible_areas_360": VISIBLE_AREAS_360,
}

#: Single-file tables.
SINGLE: dict[str, pa.Schema] = {
    "competitions": COMPETITIONS,
    "matches": MATCHES,
    "match_periods": MATCH_PERIODS,
    "teams": TEAMS,
    "players": PLAYERS,
    "lineups": LINEUPS,
    "lineup_positions": LINEUP_POSITIONS,
    "player_match_minutes": PLAYER_MATCH_MINUTES,
}

ALL: dict[str, pa.Schema] = {**SINGLE, **PARTITIONED, "spadl_actions": SPADL_ACTIONS}
