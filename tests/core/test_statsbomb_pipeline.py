"""StatsBomb ingest, minutes, SPADL and checks.

Runs on the synthetic fixture by default and on the full local data with ``--real``.
"""

import json
import re
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import statsbomb_fixture as fx

from rondo.core import checks, schemas
from rondo.core.statsbomb_parse import clock_to_s, timestamp_to_s

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = (ROOT / "docs" / "DATA_CONTRACT.md").read_text()


# --- contract -------------------------------------------------------------------------------


@pytest.mark.parametrize("table", sorted(schemas.ALL))
def test_schema_columns_are_documented(table):
    section = re.search(rf"^### {table}\n(.*?)(?=^### |\Z)", CONTRACT, re.S | re.M)
    if table == "lineup_positions":
        section = re.search(
            r"Also \*\*lineup_positions\*\*(.*?)(?=^### |\Z)", CONTRACT, re.S | re.M
        )
    assert section, f"DATA_CONTRACT.md has no section for {table}"
    for col in schemas.ALL[table].names:
        assert re.search(rf"\b{re.escape(col)}\b", section.group(1)), (
            f"{table}.{col} is in schemas.py but not in DATA_CONTRACT.md"
        )


@pytest.mark.parametrize("table", sorted(schemas.ALL))
def test_written_files_match_schema(sb_store, table):
    path = sb_store.parquet / (f"{table}.parquet" if table in schemas.SINGLE else table)
    files = [path] if path.is_file() else sorted(path.rglob("*.parquet"))
    assert files, f"no files for {table}"
    for f in files[:3]:
        assert pq.read_schema(f).names == schemas.ALL[table].names


# --- parsing helpers ------------------------------------------------------------------------


def test_time_parsing():
    assert timestamp_to_s("00:45:12.500") == pytest.approx(2712.5)
    assert clock_to_s("93:30") == 5610
    assert clock_to_s(None) is None


# --- checks (both synthetic and real) -------------------------------------------------------


@pytest.mark.parametrize("check_fn", checks.CHECKS, ids=lambda f: f.__name__)
def test_check_does_not_fail(sb_store, check_fn):
    result = check_fn(sb_store.ctx())
    assert result.status != "FAIL", f"{result.name}: {result.summary}; {result.exceptions[:5]}"


# --- values known by construction (synthetic only) ------------------------------------------


def q(sb_store, sql):
    return sb_store.con.sql(sql).fetchall()


@pytest.mark.synthetic_only
def test_every_check_passes_cleanly_on_fixture(sb_store):
    for r in checks.run_all(sb_store.ctx()):
        assert r.status == "PASS", (r.name, r.exceptions)


@pytest.mark.synthetic_only
def test_row_counts(sb_store):
    assert q(sb_store, "select count(*) from matches") == [(2,)]
    assert q(sb_store, "select count(*) from shots") == [(6,)]
    assert q(sb_store, "select count(*) from shots where not is_penalty") == [(4,)]
    assert q(sb_store, "select count(*) from shot_freeze_frames") == [(10,)]
    assert q(sb_store, "select distinct match_id from frames_360") == [(fx.MATCH_IDS[0],)]
    assert q(sb_store, "select count(distinct match_id) from visible_areas_360") == [(1,)]


@pytest.mark.synthetic_only
def test_minutes_by_construction(sb_store):
    sql = "select player_id, minutes from player_match_minutes where match_id = "
    mins = {p: round(m, 3) for p, m in q(sb_store, f"{sql}{fx.MATCH_IDS[0]}")}
    assert mins[fx.pid(fx.HOME, 1)] == 94.0
    assert mins[fx.pid(fx.HOME, 11)] == 66.0
    assert mins[fx.pid(fx.HOME, 12)] == 28.0
    assert mins[fx.pid(fx.AWAY, 7)] == 77.0  # red card at 76:00 on the clock; first half ran 46 min
    assert fx.pid(fx.HOME, 13) not in mins  # unused substitute
    assert len(mins) == 23


@pytest.mark.synthetic_only
def test_position_groups(sb_store):
    rows = dict(
        q(
            sb_store,
            "select player_id, primary_position_group from player_match_minutes "
            f"where match_id = {fx.MATCH_IDS[0]}",
        )
    )
    assert rows[fx.pid(fx.HOME, 1)] == "GK"
    assert rows[fx.pid(fx.HOME, 3)] == "CB"
    assert rows[fx.pid(fx.HOME, 11)] == "ST"


@pytest.mark.synthetic_only
def test_spadl_drops_injury_clearance_and_keeps_shots(sb_store):
    n_pass = q(sb_store, "select count(*) from events where type_name = 'Pass'")[0][0]
    fam = ", ".join(f"'{t}'" for t in checks.PASS_FAMILY)
    n_spadl = q(sb_store, f"select count(*) from spadl_actions where type_name in ({fam})")[0][0]
    assert n_pass - n_spadl == 2  # one Injury Clearance pass per match
    assert q(sb_store, "select count(*) from spadl_actions where type_name like 'shot%'") == [(6,)]


@pytest.mark.synthetic_only
def test_spadl_attacks_left_to_right(sb_store):
    (x,) = q(sb_store, "select min(start_x) from spadl_actions where type_name like 'shot%'")[0]
    assert x > 80


@pytest.mark.synthetic_only
def test_checks_catch_bad_data(sb_store):
    con = sb_store.con
    con.execute(
        "create or replace temp view events as select * replace (x + 500 as x) "
        f"from read_parquet('{sb_store.parquet}/events/**/*.parquet', hive_partitioning=true)"
    )
    con.execute(
        "create or replace temp view matches as select * replace (home_score + 1 as home_score) "
        f"from read_parquet('{sb_store.parquet}/matches.parquet')"
    )
    try:
        ctx = sb_store.ctx()
        coords = checks.event_coordinates_in_pitch(ctx)
        goals = checks.spadl_goals_equal_score(ctx)
        assert coords.status == "FAIL" and "events.x" in coords.exceptions[0]
        assert goals.status == "FAIL" and "score 2-1, SPADL 1-1" in goals.exceptions[0]
    finally:
        con.execute("drop view if exists temp.events")
        con.execute("drop view if exists temp.matches")


@pytest.mark.synthetic_only
def test_report_renders(sb_store):
    ctx = sb_store.ctx()
    text = checks.render(checks.run_all(ctx), checks.info_tables(ctx))
    assert text.startswith("# Data quality")
    assert "spadl_goals_equal_score" in text


# --- real data only -------------------------------------------------------------------------


@pytest.mark.real
def test_real_source_pinned(sb_store):
    src = json.loads((sb_store.checkout.parent / "SOURCE.json").read_text())
    from rondo.core.scope import STATSBOMB_COMMIT

    assert src["commit"] == STATSBOMB_COMMIT
