"""Wyscout ingest, cross-provider links, tracking checks and DFL event parsing."""

import datetime as dt

import pytest
import wyscout_fixture as wfx

from rondo.core import checks, dfl_ingest, xref
from rondo.core.wyscout_ingest import fix_name


def q(sb_store, sql):
    return sb_store.con.execute(sql).fetchall()


# --- Wyscout --------------------------------------------------------------------------------


def test_fix_name_decodes_escapes_and_soft_hyphens():
    assert fix_name("I. Konat\\u00e9") == "I. Konaté"
    assert fix_name("J. Gu\\u00f0munds\\u00adson") == "J. Guðmundsson"
    assert fix_name(None) is None


@pytest.mark.synthetic_only
def test_wyscout_tables(sb_store):
    assert q(sb_store, "select count(*) from wy_events") == [(11,)]
    assert q(sb_store, "select count(*) from wy_lineups") == [(22,)]  # "null" substitutions
    assert q(sb_store, f"select name from wy_teams where team_id = {wfx.AWAY}") == [
        ("Atlético Fixture",)
    ]
    assert q(sb_store, "select home_goals, away_goals from wy_matches") == [(1, 0)]


@pytest.mark.synthetic_only
def test_wyscout_kickoff_converts_to_centre_spot(sb_store):
    rows = q(
        sb_store,
        """select a.start_x, a.start_y from spadl_actions a join wy_events e
           on a.provider = 'wyscout' and a.original_event_id = cast(e.event_id as varchar)
           where e.x = 50 and e.y = 50 and e.type_name = 'Pass'""",
    )
    assert rows and all(abs(x - 52.5) < 1e-6 and abs(y - 34) < 1e-6 for x, y in rows)


# --- cross-provider links -------------------------------------------------------------------


def _m(mid, date, h, a, hg, ag, hn, an):
    d = dt.datetime.combine(date, dt.time(15)) if isinstance(date, dt.date) else date
    return {
        "match_id": mid,
        "match_date": date,
        "date_utc": d,
        "home_team_id": h,
        "away_team_id": a,
        "home_goals": hg,
        "away_goals": ag,
        "home_name": hn,
        "away_name": an,
    }


def test_link_by_date_score_and_elimination():
    day = dt.date(2018, 6, 23)
    sb = [_m(1, day, 10, 11, 1, 2, "South Korea", "Mexico")]
    wy = [
        _m(9, day, 20, 21, 1, 2, "Korea Republic", "Mexico"),
        _m(8, day, 22, 23, 1, 2, "Belgium", "Tunisia"),  # same day and score, wrong teams
    ]
    links, problems = xref.link(sb, wy)
    assert problems == []
    (lk,) = links
    assert lk["wy_match_id"] == 9 and lk["confidence"] == "medium"
    assert (lk["wy_team_for_sb_home"], lk["wy_team_for_sb_away"]) == (20, 21)


def test_link_lists_unmatched_instead_of_forcing():
    day = dt.date(2018, 6, 23)
    sb = [_m(1, day, 10, 11, 1, 0, "Spain", "Iran")]
    wy = [_m(9, day, 20, 21, 2, 0, "Spain", "Iran")]  # score disagrees
    links, problems = xref.link(sb, wy)
    assert links == [] and "no Wyscout match" in problems[0]


# --- tracking -------------------------------------------------------------------------------


@pytest.mark.synthetic_only
def test_tracking_checks_catch_jumps_and_missing_players(sb_store):
    con = sb_store.con
    src = f"read_parquet('{sb_store.parquet}/tracking_frames/**/*.parquet', hive_partitioning=true)"
    con.execute(
        "create or replace temp view tracking_frames as select * replace ("
        "case when object_id = 'P03' and frame = 10050 then x + 30 else x end as x) "
        f"from {src} where not (object_id = 'P05' and frame between 10010 and 10019)"
    )
    try:
        ctx = sb_store.ctx()
        speed = checks.tracking_speed_cap(ctx)
        players = checks.tracking_players_and_ball_in_play(ctx)
        assert speed.status == "EXCEPTIONS" and "above 12 m/s" in speed.exceptions[0]
        assert players.status == "EXCEPTIONS" and "10 of 200" in players.exceptions[0]
    finally:
        con.execute("drop view if exists temp.tracking_frames")


def test_home_attacks_flips_each_period():
    assert dfl_ingest._home_attacks("HOME_AWAY", 1) == "right"
    assert dfl_ingest._home_attacks("HOME_AWAY", 2) == "left"
    assert dfl_ingest._home_attacks("AWAY_HOME", 1) == "left"


def test_dfl_events_parse(tmp_path):
    xml = tmp_path / "events.xml"
    xml.write_text(
        '<PutDataRequest><Event EventId="1" EventTime="2023-05-27T15:30:36.890+02:00" '
        'X-Position="55.2" Y-Position="34.0"><Play Team="T1" Player="P1">'
        '<Pass Distance="short"/></Play></Event>'
        '<Event EventId="2" EventTime="2023-05-27T15:31:00.000+02:00">'
        '<Caution Team="T2" Player="P2" CardColor="red"/></Event></PutDataRequest>'
    )
    rows = dfl_ingest.load_events("M1", xml)
    assert [(r["event_type"], r["event_subtype"], r["player_id"]) for r in rows] == [
        ("Play", "Pass", "P1"),
        ("Caution", None, "P2"),
    ]
    assert rows[0]["x"] == pytest.approx(55.2) and rows[1]["x"] is None
    assert '"CardColor": "red"' in rows[1]["attributes"]
