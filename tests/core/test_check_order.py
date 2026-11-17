"""The data-quality report lists rows in one fixed order on every run.

DuckDB returns grouped and tied rows in whatever order its threads produce them, so every
list in the report must sort on a key that leaves no ties. Each case builds only the columns
one check reads, inserts rows out of order with ties, and expects the report's order: by
count where a list is ranked, then by id or name.
"""

from pathlib import Path

import duckdb
import pytest

from rondo.core import checks


def ctx_with(tables: dict[str, tuple[str, list[tuple]]]) -> checks.Ctx:
    """A checks context over an in-memory database holding just these tables."""
    con = duckdb.connect()
    for name, (columns, rows) in tables.items():
        con.execute(f"create table {name} ({columns})")
        if rows:
            con.executemany(f"insert into {name} values ({', '.join('?' * len(rows[0]))})", rows)
    return checks.Ctx(con, Path("."))


PLAYERS = "match_id integer, team_id integer, player_id integer"
MINUTES = (
    "match_id integer, team_id integer, started boolean, minutes float, minute_off float, "
    "sent_off boolean"
)
SHOTS = (
    "match_id integer, event_id varchar, shot_type varchar, period smallint, "
    "is_penalty boolean, has_freeze_frame boolean"
)
XREF = "provider varchar, provider_player_id varchar, qid varchar, same_match_partner varchar"
#: StatsBomb id, its Wikidata item, Wyscout partner id, the partner's item.
PAIRS = (
    ("5503", "Q1001", "3359", "Q1002"),
    ("3501", "Q1003", "8287", "Q1004"),
    ("6379", "Q1007", "3322", "Q1007"),
    ("40724", "Q1005", "25413", "Q1006"),
    ("7787", "Q1009", "14943", "Q1010"),
    ("20055", "Q1011", "4213", "Q1012"),
    ("11392", "Q1013", "7896", "Q1014"),
)
WY_IDS = (180864419, 180864420, 180864421, 180864422, 180864423, 180864424)
FRAMES = ((10000, 0.0), (10001, 0.04), (10003, 0.12))

CASES = {
    "events_belong_to_known_matches": (
        {
            "matches": (
                "match_id integer",
                [(3869685,), (3795107,), (3857256,), (3830254,), (3788750,)],
            ),
            "events": (
                "match_id integer",
                [
                    (m,)
                    for m in (
                        3895302,
                        3869685,
                        3890561,
                        3895302,
                        3788741,
                        3890561,
                        3773386,
                        3890561,
                    )
                ],
            ),
        },
        [
            "match 3773386: 1 events with no match row",
            "match 3788741: 1 events with no match row",
            "match 3890561: 3 events with no match row",
            "match 3895302: 2 events with no match row",
            "match 3788750: no events",
            "match 3795107: no events",
            "match 3830254: no events",
            "match 3857256: no events",
        ],
    ),
    "event_ids_unique": (
        {
            "events": (
                "event_id varchar",
                [(e,) for e in ("d9f1", "a3c2", "c118", "7b40", "5e0d", "b204", "0e55")]
                + [(e,) for e in ("b204", "7b40", "d9f1", "c118", "a3c2", "5e0d")],
            )
        },
        [
            "5e0d: 2 times",
            "7b40: 2 times",
            "a3c2: 2 times",
            "b204: 2 times",
            "c118: 2 times",
            "d9f1: 2 times",
        ],
    ),
    "team_minutes_match_length": (
        {
            "match_periods": (
                "match_id integer, period smallint, length_s double",
                [(m, p, 2700.0) for m in (3869685, 3795107, 3857256) for p in (1, 2)],
            ),
            # Every team plays 985 of 990 minutes: six team-matches tied 5 minutes short.
            "player_match_minutes": (
                MINUTES,
                [
                    (m, t, True, 85.0 if i == 0 else 90.0, None, False)
                    for m in (3869685, 3795107, 3857256)
                    for t in (217, 206)
                    for i in range(11)
                ],
            ),
        },
        [
            "match 3795107 team 206: 985.0 min vs expected 990.0 (11 starters)",
            "match 3795107 team 217: 985.0 min vs expected 990.0 (11 starters)",
            "match 3857256 team 206: 985.0 min vs expected 990.0 (11 starters)",
            "match 3857256 team 217: 985.0 min vs expected 990.0 (11 starters)",
            "match 3869685 team 206: 985.0 min vs expected 990.0 (11 starters)",
            "match 3869685 team 217: 985.0 min vs expected 990.0 (11 starters)",
        ],
    ),
    "no_player_for_both_teams": (
        {
            "lineups": (
                PLAYERS,
                [
                    (m, t, p)
                    for m, p in (
                        (3869685, 5503),
                        (3795107, 40724),
                        (3869685, 3501),
                        (3857256, 6379),
                        (3830254, 8287),
                        (3795107, 3359),
                    )
                    for t in (217, 206)
                ],
            ),
            "player_match_minutes": (PLAYERS, []),
            "events": (PLAYERS, []),
        },
        [
            "lineups: player 3359 for both teams in match 3795107",
            "lineups: player 40724 for both teams in match 3795107",
            "lineups: player 8287 for both teams in match 3830254",
            "lineups: player 6379 for both teams in match 3857256",
            "lineups: player 3501 for both teams in match 3869685",
            "lineups: player 5503 for both teams in match 3869685",
        ],
    ),
    "non_penalty_shots_have_freeze_frames": (
        {
            "shots": (
                SHOTS,
                [
                    (3795107, "f2", "Free Kick", 1, False, False),
                    (3795107, "c7", "Open Play", 1, False, False),
                    (3788741, "b5", "Open Play", 1, False, False),
                    (3795107, "e8", "Corner", 1, False, False),
                    (3795107, "a1", "Open Play", 2, False, False),
                    (3795107, "d4", "Open Play", 2, False, False),
                    (3795107, "p9", "Penalty", 2, True, False),
                    (3795107, "e3", "Open Play", 2, False, True),
                ],
            )
        },
        [
            "match 3788741: shot b5 (Open Play, period 1)",
            "match 3795107: shot a1 (Open Play, period 2)",
            "match 3795107: shot c7 (Open Play, period 1)",
            "match 3795107: shot d4 (Open Play, period 2)",
            "match 3795107: shot e8 (Corner, period 1)",
            "match 3795107: shot f2 (Free Kick, period 1)",
        ],
    ),
    "visible_areas_are_valid_polygons": (
        {
            "visible_areas_360": (
                "match_id integer, event_id varchar, n_points smallint, is_valid boolean",
                [
                    (3869685, "e9", 4, False),
                    (3869685, "e2", 5, False),
                    (3795107, "e5", 3, False),
                    (3869685, "e7", 4, False),
                    (3869685, "e4", 6, False),
                    (3869685, "e1", 5, True),
                ],
            )
        },
        [
            "match 3795107: event e5 (3 points)",
            "match 3869685: event e2 (5 points)",
            "match 3869685: event e4 (6 points)",
            "match 3869685: event e7 (4 points)",
            "match 3869685: event e9 (4 points)",
        ],
    ),
    "frames_360_players_on_pitch": (
        {
            "frames_360": (
                "match_id integer, x float, y float",
                [
                    (m, 130.0, 40.0)
                    for m in (3869685, 3795107, 3895302, 3857256, 3830254, 3890561, 3788750)
                    for _ in range(2)
                ]
                + [(3895302, 40.0, -6.0), (3788741, 60.0, 40.0)],
            )
        },
        [
            "match 3895302: 3 locations outside",
            "match 3788750: 2 locations outside",
            "match 3795107: 2 locations outside",
            "match 3830254: 2 locations outside",
            "match 3857256: 2 locations outside",
            "match 3869685: 2 locations outside",
            "match 3890561: 2 locations outside",
        ],
    ),
    "wy_coordinates_convert": (
        {
            "wy_events": (
                "event_id bigint, x float, y float, subtype_name varchar, period smallint",
                [(e, 50.0, 50.0, "Simple pass", 1) for e in WY_IDS],
            ),
            # Each action starts at the origin, not at (52.5, 34): all six types are off.
            "spadl_actions": (
                "provider varchar, original_event_id varchar, type_name varchar, "
                "start_x float, start_y float",
                [
                    ("wyscout", str(e), t, 0.0, 0.0)
                    for e, t in zip(
                        WY_IDS,
                        ("shot", "pass", "cross", "dribble", "interception", "clearance"),
                        strict=True,
                    )
                ],
            ),
        },
        [
            "1 clearance actions off the documented formula",
            "1 cross actions off the documented formula",
            "1 dribble actions off the documented formula",
            "1 interception actions off the documented formula",
            "1 pass actions off the documented formula",
            "1 shot actions off the documented formula",
        ],
    ),
    "tracking_frames_at_25hz": (
        {
            # Each period skips frame 10002 once.
            "tracking_frames": (
                "match_id varchar, period smallint, frame integer, time_s double",
                [
                    (m, p, f, t)
                    for m, p in (
                        ("DFL-MAT-J03WPY", 2),
                        ("DFL-MAT-J03WMX", 1),
                        ("DFL-MAT-J03WPY", 1),
                        ("DFL-MAT-J03WN1", 2),
                        ("DFL-MAT-J03WMX", 2),
                        ("DFL-MAT-J03WN1", 1),
                    )
                    for f, t in FRAMES
                ],
            ),
            "tracking_meta": ("frame_rate float", [(25.0,), (30.0,), (24.0,)]),
        },
        [
            "DFL-MAT-J03WMX period 1: 1 irregular steps",
            "DFL-MAT-J03WMX period 2: 1 irregular steps",
            "DFL-MAT-J03WN1 period 1: 1 irregular steps",
            "DFL-MAT-J03WN1 period 2: 1 irregular steps",
            "DFL-MAT-J03WPY period 1: 1 irregular steps",
            "DFL-MAT-J03WPY period 2: 1 irregular steps",
            "frame rate 24.0 in metadata",
            "frame rate 30.0 in metadata",
        ],
    ),
    "same_match_links_agree": (
        {
            "player_xref": (
                XREF,
                [
                    row
                    for a, qa, b, qb in PAIRS
                    for row in (("statsbomb", a, qa, b), ("wyscout", b, qb, a))
                ],
            )
        },
        # Provider ids are text, so they sort as text.
        [
            "StatsBomb 11392 -> Q1013, Wyscout 7896 -> Q1014",
            "StatsBomb 20055 -> Q1011, Wyscout 4213 -> Q1012",
            "StatsBomb 3501 -> Q1003, Wyscout 8287 -> Q1004",
            "StatsBomb 40724 -> Q1005, Wyscout 25413 -> Q1006",
            "StatsBomb 5503 -> Q1001, Wyscout 3359 -> Q1002",
            "StatsBomb 7787 -> Q1009, Wyscout 14943 -> Q1010",
        ],
    ),
}


@pytest.mark.parametrize("name", CASES)
def test_check_lists_exceptions_in_a_fixed_order(name):
    tables, want = CASES[name]
    assert getattr(checks, name)(ctx_with(tables)).exceptions == want


def test_reported_facts_rank_by_count_then_name():
    ctx = ctx_with(
        {
            "events": (
                "event_id varchar, type_name varchar",
                [
                    (f"{t}-{i}", t)
                    for t, n in (
                        ("Duel", 2),
                        ("Pressure", 3),
                        ("Block", 2),
                        ("Dispossessed", 2),
                        ("Clearance", 2),
                        ("Ball Receipt*", 2),
                    )
                    for i in range(n)
                ]
                + [("p1", "Pass")],
            ),
            "spadl_actions": (
                "original_event_id varchar, provider varchar, type_name varchar",
                [("p1", "statsbomb", "pass")]
                + [
                    (None, "statsbomb", t)
                    for t, n in (("dribble", 2), ("take_on", 2), ("clearance", 1), ("bad_touch", 2))
                    for _ in range(n)
                ]
                + [(None, "wyscout", "dribble")],
            ),
            "lineup_positions": (
                "match_id integer, from_period smallint, to_period smallint, "
                "from_clock_s float, to_clock_s float",
                [],
            ),
            "defensive_actions": (
                "action varchar, is_success boolean",
                [
                    (a, None)
                    for a, n in (
                        ("tackle", 2),
                        ("block", 3),
                        ("interception", 2),
                        ("clearance", 2),
                        ("ball_recovery", 2),
                    )
                    for _ in range(n)
                ]
                + [("tackle", True)],
            ),
        }
    )
    assert list(checks.info_tables(ctx).values()) == [
        [
            ("Pressure", 3),
            ("Ball Receipt*", 2),
            ("Block", 2),
            ("Clearance", 2),
            ("Dispossessed", 2),
            ("Duel", 2),
        ],
        [("bad_touch", 2), ("dribble", 2), ("take_on", 2), ("clearance", 1)],
        [(0, 0)],
        [("block", 3), ("ball_recovery", 2), ("clearance", 2), ("interception", 2), ("tackle", 2)],
    ]
