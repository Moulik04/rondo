"""Data-quality checks on the shared tables (``make check``).

Each check is a named function returning a :class:`CheckResult`. Status is one of:

- ``PASS``: no problems;
- ``EXCEPTIONS``: a check whose rule allows listed exceptions (outliers or known gaps); every exception is counted in the report;
- ``FAIL``: the data contradicts the contract. ``make check`` exits 1.

``python -m rondo.core.checks`` runs everything and writes ``reports/data_quality.md``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from rondo.core import scope as sc
from rondo.core import store
from rondo.core.paths import parquet_dir, reports_dir, statsbomb_raw_dir

#: How far outside the pitch a 360 player location may sit (pitch units), see the report.
FRAME_360_MARGIN = 5.0
#: Allowed gap between a team's summed minutes and 11 x match length (minus red cards).
TEAM_MINUTES_TOLERANCE = 1.0
#: SPADL pass-family types produced from StatsBomb Pass events.
PASS_FAMILY = (
    "pass",
    "cross",
    "throw_in",
    "freekick_crossed",
    "freekick_short",
    "corner_crossed",
    "corner_short",
    "goalkick",
)
SHOT_FAMILY = ("shot", "shot_freekick", "shot_penalty")
LIST_LIMIT = 25


@dataclass
class CheckResult:
    """Outcome of one check."""

    name: str
    description: str
    status: str
    summary: str
    exceptions: list[str] = field(default_factory=list)
    n_exceptions: int = 0


@dataclass
class Ctx:
    """What the checks read: a DuckDB connection with views, and the raw checkout."""

    con: duckdb.DuckDBPyConnection
    checkout: Path
    scope: tuple[sc.CompetitionSeason, ...] = sc.SCOPE
    check_section_2: bool = True

    def q(self, sql: str) -> list[tuple]:
        """Run SQL and return all rows."""
        return self.con.execute(sql).fetchall()

    def one(self, sql: str) -> object:
        """Run SQL and return the first value."""
        return self.con.execute(sql).fetchall()[0][0]


def _result(
    name: str, description: str, problems: list[str], summary: str, allow: bool = False
) -> CheckResult:
    status = "PASS" if not problems else ("EXCEPTIONS" if allow else "FAIL")
    return CheckResult(
        name, description, status, summary, problems[:LIST_LIMIT], n_exceptions=len(problems)
    )


CHECKS: list[Callable[[Ctx], CheckResult]] = []


def check(fn: Callable[[Ctx], CheckResult]) -> Callable[[Ctx], CheckResult]:
    """Register a check."""
    CHECKS.append(fn)
    return fn


@check
def match_counts_per_competition_season(ctx: Ctx) -> CheckResult:
    """Check matches per competition-season against the raw files and the project spec"""
    table = dict(
        ((c, s), n)
        for c, s, n in ctx.q("select competition_id, season_id, count(*) from matches group by all")
    )
    problems, groups = [], {}
    for cs in ctx.scope:
        raw = len(
            json.loads(
                (
                    ctx.checkout
                    / "data"
                    / "matches"
                    / str(cs.competition_id)
                    / f"{cs.season_id}.json"
                ).read_text()
            )
        )
        got = table.get((cs.competition_id, cs.season_id), 0)
        if got != raw:
            problems.append(f"{cs.competition_id}/{cs.season_id}: table {got}, matches file {raw}")
        if ctx.check_section_2 and cs.expected_matches is not None and raw != cs.expected_matches:
            problems.append(
                f"{cs.competition_id}/{cs.season_id}: file {raw}, §2 says {cs.expected_matches}"
            )
        groups[cs.group] = groups.get(cs.group, 0) + got
    if ctx.check_section_2:
        for group, (n, _) in sc.EXPECTED_GROUP_TOTALS.items():
            if groups.get(group) != n:
                problems.append(f"{group}: {groups.get(group)} matches, §2 says {n}")
    total = sum(table.values())
    return _result(
        "match_counts_per_competition_season",
        "Matches per competition-season equal the matches files and the expected counts.",
        problems,
        f"{len(table)} competition-seasons, {total} matches",
    )


@check
def totals_match_section_2(ctx: Ctx) -> CheckResult:
    """Total and core match counts, and matches with 360 data, equal §2."""
    total, n360, core, core360 = ctx.con.execute(
        "select count(*), sum(has_360::int), sum((scope='core')::int), "
        "sum((scope='core' and has_360)::int) from matches"
    ).fetchall()[0]
    problems = []
    if ctx.check_section_2:
        for label, got, want in [
            ("matches", total, sc.EXPECTED_TOTAL_MATCHES),
            ("matches with 360", n360, sc.EXPECTED_TOTAL_360),
            ("core matches", core, sc.EXPECTED_CORE_MATCHES),
            ("core matches with 360", core360, sc.EXPECTED_CORE_360),
        ]:
            if got != want:
                problems.append(f"{label}: {got}, §2 says {want}")
    return _result(
        "totals_match_section_2",
        "Total, core and 360 match counts equal the expected counts.",
        problems,
        f"{total} matches ({n360} with 360); core {core} ({core360} with 360)",
    )


@check
def events_belong_to_known_matches(ctx: Ctx) -> CheckResult:
    """Every event's match is in the matches table, and every match has events."""
    orphans = ctx.q(
        "select match_id, count(*) from events anti join matches using (match_id) group by 1"
    )
    empty = ctx.q(
        "select match_id from matches "
        "anti join (select distinct match_id from events) using (match_id)"
    )
    problems = [f"match {m}: {n} events with no match row" for m, n in orphans]
    problems += [f"match {m}: no events" for (m,) in empty]
    return _result(
        "events_belong_to_known_matches",
        "Every event belongs to a known match, and every match has events.",
        problems,
        f"{ctx.one('select count(*) from events')} events",
    )


@check
def event_ids_unique(ctx: Ctx) -> CheckResult:
    """Event ids are unique across the whole corpus."""
    dups = ctx.q("select event_id, count(*) from events group by 1 having count(*) > 1 limit 100")
    return _result(
        "event_ids_unique",
        "Event ids are unique.",
        [f"{e}: {n} times" for e, n in dups],
        f"{ctx.one('select count(distinct event_id) from events')} distinct ids",
    )


def _range_problems(
    ctx: Ctx, table: str, cols: list[tuple[str, float]], slack: float = 0.0
) -> list[str]:
    """Count values outside [0, hi] (or, with ``slack``, outside [-slack, hi + slack])."""
    problems = []
    for col, hi in cols:
        n = ctx.one(f"select count(*) from {table} where {col} < -{slack} or {col} > {hi + slack}")
        if n:
            lo_hi = ctx.con.execute(f"select min({col}), max({col}) from {table}").fetchall()[0]
            bound = f"[0, {hi}]" if not slack else f"[-{slack:g}, {hi + slack:g}]"
            problems.append(
                f"{table}.{col}: {n} values outside {bound} "
                f"(range {lo_hi[0]:.2f} to {lo_hi[1]:.2f})"
            )
    return problems


#: StatsBomb's own data reaches 120.9 and 80.9 (one decimal past the 120 x 80 edge).
EDGE_SLACK = 1.0
_EVENT_COORDS = [
    ("events", [("x", 120), ("y", 80)]),
    ("passes", [("end_x", 120), ("end_y", 80)]),
    ("carries", [("end_x", 120), ("end_y", 80)]),
    ("shot_freeze_frames", [("x", 120), ("y", 80)]),
]


@check
def event_coordinates_in_pitch(ctx: Ctx) -> CheckResult:
    """Event-frame coordinates lie within 120 x 80 (up to 1 unit over is listed, not failed)."""
    hard = [p for t, cols in _EVENT_COORDS for p in _range_problems(ctx, t, cols, EDGE_SLACK)]
    if hard:
        return _result(
            "event_coordinates_in_pitch",
            "Event, pass/carry end and freeze-frame coordinates lie within 120 x 80.",
            hard,
            f"values more than {EDGE_SLACK:g} unit outside the pitch",
        )
    edge = [p for t, cols in _EVENT_COORDS for p in _range_problems(ctx, t, cols)]
    return _result(
        "event_coordinates_in_pitch",
        "Event, pass/carry end and freeze-frame coordinates lie within 120 x 80. StatsBomb's "
        f"data runs up to 120.9 and 80.9, so values at most {EDGE_SLACK:g} unit past an edge "
        "are listed with counts; anything further is a FAIL.",
        edge,
        f"no value more than {EDGE_SLACK:g} unit outside the pitch",
        allow=True,
    )


@check
def spadl_coordinates_in_pitch(ctx: Ctx) -> CheckResult:
    """SPADL coordinates lie within 105 x 68 metres."""
    problems = _range_problems(
        ctx, "spadl_actions", [("start_x", 105), ("start_y", 68), ("end_x", 105), ("end_y", 68)]
    )
    return _result(
        "spadl_coordinates_in_pitch",
        "SPADL start and end coordinates lie within 105 x 68.",
        problems,
        f"{ctx.one('select count(*) from spadl_actions')} actions",
    )


@check
def team_minutes_match_length(ctx: Ctx) -> CheckResult:
    """Each team's minutes are 11 x match length, less time lost to red cards."""
    rows = ctx.q(
        f"""
        with len as (select match_id, sum(length_s) / 60 as len from match_periods
                     where period <= 4 group by 1),
        t as (select m.match_id, m.team_id, sum(m.minutes) as mins,
                     sum(case when m.sent_off then len.len - m.minute_off else 0 end) as red_loss,
                     sum(m.started::int) as starters
              from player_match_minutes m join len using (match_id) group by 1, 2)
        select t.match_id, t.team_id, t.mins, 11 * len.len - t.red_loss as expected, t.starters
        from t join len using (match_id)
        where abs(t.mins - (11 * len.len - t.red_loss)) > {TEAM_MINUTES_TOLERANCE}
           or t.starters <> 11
        order by abs(t.mins - (11 * len.len - t.red_loss)) desc
        """
    )
    n = ctx.one(
        "select count(*) from (select distinct match_id, team_id from player_match_minutes)"
    )
    problems = [
        f"match {m} team {t}: {mins:.1f} min vs expected {exp:.1f} ({st} starters)"
        for m, t, mins, exp, st in rows
    ]
    return _result(
        "team_minutes_match_length",
        f"Each team's summed minutes are within {TEAM_MINUTES_TOLERANCE:g} min of 11 x match "
        "length (less red-card time), with 11 starters; outliers listed.",
        problems,
        f"{n} team-matches",
        allow=True,
    )


@check
def no_player_for_both_teams(ctx: Ctx) -> CheckResult:
    """No player appears for both teams in one match (lineups, minutes or events)."""
    problems = []
    for table in ("lineups", "player_match_minutes", "events"):
        for m, p in ctx.q(
            f"select match_id, player_id from {table} where player_id is not null "
            "group by 1, 2 having count(distinct team_id) > 1"
        ):
            problems.append(f"{table}: player {p} for both teams in match {m}")
    return _result(
        "no_player_for_both_teams",
        "No player appears for both teams in one match (lineups, minutes, events).",
        problems,
        "lineups, player_match_minutes and events checked",
    )


@check
def shot_xg_in_unit_interval(ctx: Ctx) -> CheckResult:
    """StatsBomb's shot xG lies within [0, 1] and is present for every shot."""
    bad = ctx.one("select count(*) from shots where statsbomb_xg < 0 or statsbomb_xg > 1")
    missing = ctx.one("select count(*) from shots where statsbomb_xg is null")
    problems = []
    if bad:
        problems.append(f"{bad} shots with xG outside [0, 1]")
    if missing:
        problems.append(f"{missing} shots with no xG")
    return _result(
        "shot_xg_in_unit_interval",
        "Shot xG lies within [0, 1] (and is present).",
        problems,
        f"{ctx.one('select count(*) from shots')} shots",
    )


@check
def non_penalty_shots_have_freeze_frames(ctx: Ctx) -> CheckResult:
    """Every non-penalty shot has a freeze frame; exceptions listed."""
    rows = ctx.q(
        "select match_id, event_id, shot_type, period from shots "
        "where not is_penalty and not has_freeze_frame order by match_id"
    )
    n = ctx.one("select count(*) from shots where not is_penalty")
    return _result(
        "non_penalty_shots_have_freeze_frames",
        "Every non-penalty shot has a freeze frame; exceptions listed.",
        [f"match {m}: shot {e} ({t}, period {p})" for m, e, t, p in rows],
        f"{n} non-penalty shots, {n - len(rows)} with freeze frames",
        allow=True,
    )


@check
def frames_360_belong_to_events(ctx: Ctx) -> CheckResult:
    """Every 360 frame belongs to an existing event.

    A match where *none* of the 360 frames match its events file is a provider-side id
    mismatch (listed). A match where only *some* fail to match would point to a parsing bug
    (FAIL).
    """
    rows = ctx.q(
        """select v.match_id, count(*) as total,
                  count(*) filter (where e.event_id is null) as orphans
           from visible_areas_360 v left join events e using (event_id)
           group by 1 having count(*) filter (where e.event_id is null) > 0 order by 1"""
    )
    total = ctx.one("select count(*) from visible_areas_360")
    partial = [f"match {m}: {o} of {t} frames unmatched" for m, t, o in rows if o < t]
    whole = [
        f"match {m}: none of its {t} 360 frames match an event id in its events file"
        for m, t, o in rows
        if o == t
    ]
    lost = sum(t for _, t, o in rows if o == t)
    desc = (
        "Every 360 frame's event exists in events. Whole matches whose 360 ids don't match "
        "their events file are provider-side mismatches and are listed; a partial mismatch fails."
    )
    if partial:
        return _result("frames_360_belong_to_events", desc, partial, "partial mismatches")
    return _result(
        "frames_360_belong_to_events",
        desc,
        whole,
        f"{total} events with 360 frames; {lost} in {len(whole)} matches can't be linked",
        allow=True,
    )


@check
def visible_areas_are_valid_polygons(ctx: Ctx) -> CheckResult:
    """Each 360 visible area is a valid polygon (shapely ``is_valid``); exceptions listed."""
    rows = ctx.q(
        "select match_id, event_id, n_points from visible_areas_360 where not is_valid order by 1"
    )
    total = ctx.one("select count(*) from visible_areas_360")
    return _result(
        "visible_areas_are_valid_polygons",
        "Each 360 visible area is a valid polygon; exceptions listed.",
        [f"match {m}: event {e} ({n} points)" for m, e, n in rows],
        f"{total} visible areas, {total - len(rows)} valid",
        allow=True,
    )


@check
def frames_360_players_on_pitch(ctx: Ctx) -> CheckResult:
    """360 player locations lie on the pitch within a documented margin; exceptions listed."""
    mg = FRAME_360_MARGIN
    rows = ctx.q(
        f"""select match_id, count(*) from frames_360
            where x < -{mg} or x > 120 + {mg} or y < -{mg} or y > 80 + {mg}
            group by 1 order by 2 desc"""
    )
    total = ctx.one("select count(*) from frames_360")
    bad = sum(n for _, n in rows)
    return _result(
        "frames_360_players_on_pitch",
        f"360 player locations lie within the 120 x 80 pitch plus a {mg:g}-unit margin; "
        "exceptions listed.",
        [f"match {m}: {n} locations outside" for m, n in rows],
        f"{total} player locations, {bad} outside the margin",
        allow=True,
    )


@check
def spadl_goals_equal_score(ctx: Ctx) -> CheckResult:
    """SPADL goals per match (own goals included, shootout excluded) equal the final score."""
    rows = ctx.q(
        """
        with g as (
          select m.match_id, m.home_score, m.away_score,
            sum(case when (a.type_name like 'shot%' and a.result_name = 'success'
                           and a.team_id = m.home_team_id)
                       or (a.result_name = 'owngoal' and a.team_id = m.away_team_id)
                     then 1 else 0 end) as home_goals,
            sum(case when (a.type_name like 'shot%' and a.result_name = 'success'
                           and a.team_id = m.away_team_id)
                       or (a.result_name = 'owngoal' and a.team_id = m.home_team_id)
                     then 1 else 0 end) as away_goals
          from matches m left join spadl_actions a
            on a.match_id = m.match_id and a.provider = 'statsbomb' and a.period_id < 5
          group by all)
        select match_id, home_score, away_score, home_goals, away_goals from g
        where home_goals <> home_score or away_goals <> away_score order by 1
        """
    )
    n = ctx.one("select count(*) from matches")
    return _result(
        "spadl_goals_equal_score",
        "Goals per match from SPADL (own goals included, shootout excluded) equal the score.",
        [f"match {m}: score {hs}-{as_}, SPADL {hg}-{ag}" for m, hs, as_, hg, ag in rows],
        f"{n - len(rows)} of {n} matches agree",
    )


@check
def spadl_reconciles_passes_shots_carries(ctx: Ctx) -> CheckResult:
    """Each Pass, Shot and Carry event maps to the SPADL actions socceraction documents.

    Mapping (socceraction 1.5.3, ``socceraction/spadl/statsbomb.py``):

    - Pass: one pass-family action, except outcome ``Injury Clearance`` or ``Unknown``
      (dropped as not part of play); a pass of type ``Interception`` also yields an
      ``interception`` action first (``_insert_interception_passes``);
    - Shot: one shot-family action (``shot``, ``shot_freekick``, ``shot_penalty``);
    - Carry: one ``dribble`` action.
    """
    fam = {"Pass": PASS_FAMILY, "Shot": SHOT_FAMILY, "Carry": ("dribble",)}
    fam_case = " ".join(
        f"when ev.type_name = '{t}' then a.type_name in ({', '.join(repr(x) for x in f)})"
        for t, f in fam.items()
    )
    rows = ctx.q(
        f"""
        with ev as (
          select e.match_id, e.event_id, e.type_name,
            case when e.type_name = 'Pass'
                  and coalesce(json_extract_string(e.details, '$.pass.outcome.name'), '')
                      in ('Injury Clearance', 'Unknown') then 0 else 1 end as want_fam,
            case when e.type_name = 'Pass'
                  and json_extract_string(e.details, '$.pass.type.name') = 'Interception'
                 then 1 else 0 end as want_int
          from events e where e.type_name in ('Pass', 'Shot', 'Carry')),
        got as (
          select ev.match_id, ev.event_id, ev.type_name, ev.want_fam, ev.want_int,
            count(a.action_id) filter (where case {fam_case} end) as n_fam,
            count(a.action_id) filter (where a.type_name = 'interception') as n_int,
            count(a.action_id) as n_all
          from ev left join spadl_actions a
            on a.provider = 'statsbomb' and a.match_id = ev.match_id
           and a.original_event_id = ev.event_id
          group by all)
        select type_name, match_id, count(*) as bad from got
        where n_fam <> want_fam or n_int <> want_int or n_all <> want_fam + want_int
        group by 1, 2 order by 1, 2
        """
    )
    stats = ctx.q(
        """select type_name, count(*),
                  count(*) filter (where json_extract_string(details, '$.pass.type.name')
                                   = 'Interception'),
                  count(*) filter (where json_extract_string(details, '$.pass.outcome.name')
                                   in ('Injury Clearance', 'Unknown'))
           from events where type_name in ('Pass', 'Shot', 'Carry') group by 1 order by 1"""
    )
    summary = "; ".join(
        f"{t} {n}" + (f" ({i} split into interception + pass, {d} dropped)" if t == "Pass" else "")
        for t, n, i, d in stats
    )
    return _result(
        "spadl_reconciles_passes_shots_carries",
        "Every Pass, Shot and Carry event maps to the SPADL actions socceraction 1.5.3 documents: "
        "one action per event, except that passes with outcome Injury Clearance or Unknown are "
        "dropped and passes of type Interception also yield an interception action.",
        [f"{t}, match {m}: {b} events don't map as documented" for t, m, b in rows],
        summary,
    )


#: Each provider's SPADL actions trace to its own events table (id expression, table).
_EVENT_SOURCES = {
    "statsbomb": ("event_id", "events"),
    "wyscout": ("cast(event_id as varchar)", "wy_events"),
}


@check
def spadl_actions_trace_to_events(ctx: Ctx) -> CheckResult:
    """Every SPADL action's source event exists; only inserted dribbles have none."""
    providers = [r[0] for r in ctx.q("select distinct provider from spadl_actions order by 1")]
    problems, summary = [], []
    for prov in providers:
        id_expr, table = _EVENT_SOURCES[prov]
        unknown = ctx.one(
            f"""select count(*) from spadl_actions a
                where a.provider = '{prov}' and a.original_event_id is not null
                  and a.original_event_id not in (select {id_expr} from {table})"""
        )
        sourceless = ctx.q(
            f"select type_name, count(*) from spadl_actions where provider = '{prov}' "
            "and original_event_id is null group by 1 order by 1"
        )
        if unknown:
            problems.append(f"{prov}: {unknown} actions point to an event id not in {table}")
        problems += [
            f"{prov}: {n} {t} actions with no source event" for t, n in sourceless if t != "dribble"
        ]
        inserted = sum(n for t, n in sourceless if t == "dribble")
        summary.append(f"{prov}: {inserted} inserted dribbles without a source event")
    return _result(
        "spadl_actions_trace_to_events",
        "Every SPADL action's original_event_id exists in its provider's events table; only the "
        "dribbles socceraction inserts between actions (_add_dribbles) have none.",
        problems,
        "; ".join(summary),
    )


# --- Phase 2: Wyscout, cross-provider links, tracking -----------------------------------------

#: Highest believable player speed in tracking data, m/s (about 43 km/h; the fastest recorded
#: sprinters peak near 12.4 m/s). Speeds are measured over 5 frames (0.2 s).
SPEED_CAP = 12.0
SPEED_WINDOW_FRAMES = 5


def _has(ctx: Ctx, *tables: str) -> bool:
    names = {r[0] for r in ctx.q("select table_name from information_schema.tables")}
    return all(t in names for t in tables)


def _skip(name: str, description: str, needs: str) -> CheckResult:
    return CheckResult(name, description, "SKIP", f"{needs} not built")


@check
def wy_counts_match_published(ctx: Ctx) -> CheckResult:
    """Wyscout matches, events and players per competition equal Pappalardo et al., Table 1."""
    from rondo.core.wyscout_ingest import COMPETITIONS

    name, desc = (
        "wy_counts_match_published",
        "Matches, events and players per competition equal the published table (players = "
        "distinct players in the competition's lineups, bench included).",
    )
    if not _has(ctx, "wy_matches", "wy_events", "wy_lineups"):
        return _skip(name, desc, "wy_* tables")
    if not ctx.check_section_2:
        return CheckResult(name, desc, "SKIP", "published counts apply to the real data only")
    got = {
        c: (m, e, p)
        for c, m, e, p in ctx.q(
            """select m.competition_id, count(distinct m.match_id),
                      (select count(*) from wy_events e join wy_matches mm using (match_id)
                       where mm.competition_id = m.competition_id),
                      (select count(distinct l.player_id) from wy_lineups l
                       join wy_matches mm using (match_id)
                       where mm.competition_id = m.competition_id)
               from wy_matches m group by 1"""
        )
    }
    problems = []
    for cid, (suffix, *want) in COMPETITIONS.items():
        have = got.get(cid, (0, 0, 0))
        for label, h, w in zip(("matches", "events", "players"), have, want, strict=True):
            if h != w:
                problems.append(f"{suffix}: {h} {label}, published {w}")
    tot = [sum(v[i] for v in got.values()) for i in range(2)]
    return _result(name, desc, problems, f"{tot[0]} matches, {tot[1]} events in 7 competitions")


@check
def wy_totals_match_expected(ctx: Ctx) -> CheckResult:
    """Totals against the expected counts (1,941 matches, 3,251,294 events, 4,299 players)."""
    from rondo.core.wyscout_ingest import PUBLISHED_TOTALS

    name, desc = (
        "wy_totals_match_expected",
        "Total matches and events equal the expected counts and the paper. The expected figure of 4,299 "
        "players with birth dates is compared with the players file and listed if it differs.",
    )
    if not _has(ctx, "wy_matches", "wy_events", "wy_players", "wy_lineups"):
        return _skip(name, desc, "wy_* tables")
    if not ctx.check_section_2:
        return CheckResult(name, desc, "SKIP", "published counts apply to the real data only")
    m, e, pf, pl, bd = ctx.q(
        """select (select count(*) from wy_matches), (select count(*) from wy_events),
                  (select count(*) from wy_players),
                  (select count(distinct player_id) from wy_lineups),
                  (select count(*) from wy_players where birth_date is not null)"""
    )[0]
    want_m, want_e, want_p = PUBLISHED_TOTALS
    hard = [
        f"{lbl}: {h}, expected {w}"
        for lbl, h, w in (("matches", m, want_m), ("events", e, want_e))
        if h != w
    ]
    if hard:
        return _result(name, desc, hard, "totals differ")
    soft = []
    if pf != want_p:
        soft.append(
            f"players file has {pf} players ({bd} with birth dates), not {want_p}; "
            f"{pl} distinct players appear in lineups; the paper's per-competition player "
            "counts sum to 4,362"
        )
    return _result(name, desc, soft, f"{m} matches, {e} events, {pf} players", allow=True)


@check
def wy_events_belong_to_matches(ctx: Ctx) -> CheckResult:
    """Every Wyscout event belongs to a known match; event ids are unique."""
    name, desc = (
        "wy_events_belong_to_matches",
        "Every Wyscout event belongs to a known match, and event ids are unique.",
    )
    if not _has(ctx, "wy_matches", "wy_events"):
        return _skip(name, desc, "wy_* tables")
    orphans = ctx.one("select count(*) from wy_events anti join wy_matches using (match_id)")
    dups = ctx.one("select count(*) - count(distinct event_id) from wy_events")
    problems = [f"{orphans} events with no match"] if orphans else []
    problems += [f"{dups} duplicate event ids"] if dups else []
    return _result(name, desc, problems, f"{ctx.one('select count(*) from wy_events')} events")


@check
def wy_goals_equal_score(ctx: Ctx) -> CheckResult:
    """Wyscout SPADL goals per match (own goals included, shootout excluded) equal the score.

    Two known gaps are classified and listed rather than failed: a goal scored directly from
    a corner (socceraction converts the corner to a corner action, so SPADL has no scoring
    shot; the raw corner carries goal tag 101), and a goal whose scoring event is missing from
    the raw data (only the keeper's save attempt is tagged). Any other gap fails.
    """
    name, desc = (
        "wy_goals_equal_score",
        "Goals per match from Wyscout SPADL (own goals included, shootout excluded) equal the "
        "score before any shootout. Goals direct from corners (no SPADL shot) and goals with "
        "no scoring event in the raw data are listed; any other gap fails.",
    )
    if not _has(ctx, "wy_matches", "wy_events", "spadl_actions"):
        return _skip(name, desc, "wy_* tables")
    rows = ctx.q(
        """
        with sides as (
          select match_id, home_team_id as team_id, away_team_id as opp, home_goals as goals
          from wy_matches
          union all
          select match_id, away_team_id, home_team_id, away_goals from wy_matches),
        sp as (
          select s.match_id, s.team_id, s.goals,
            count(a.action_id) filter (where (a.type_name like 'shot%'
                  and a.result_name = 'success' and a.team_id = s.team_id)
                  or (a.result_name = 'owngoal' and a.team_id = s.opp)) as spadl_goals
          from sides s left join spadl_actions a
            on a.provider = 'wyscout' and a.match_id = s.match_id and a.period_id < 5
          group by all),
        raw as (
          select s.match_id, s.team_id,
            count(e.event_id) filter (where e.team_id = s.team_id and e.type_name = 'Free Kick'
                  and e.subtype_name in ('Corner', 'Free kick cross', 'Free Kick')
                  and list_contains(e.tags, 101)) as corner_goals,
            count(e.event_id) filter (where e.team_id = s.team_id
                  and (e.type_name = 'Shot' or e.subtype_name in ('Free kick shot', 'Penalty'))
                  and list_contains(e.tags, 101)) as shot_goals
          from sides s left join wy_events e on e.match_id = s.match_id and e.period < 5
          group by all)
        select sp.match_id, sp.team_id, sp.goals, sp.spadl_goals, raw.corner_goals,
               raw.shot_goals
        from sp join raw using (match_id, team_id)
        where sp.goals <> sp.spadl_goals order by 1, 2
        """
    )
    hard, listed = [], []
    for m, team, goals, sp, corner, shots in rows:
        missing = goals - sp
        if 0 < missing <= corner:
            listed.append(f"match {m}, team {team}: {missing} goal(s) direct from a corner")
        elif missing > 0 and shots + corner < goals:
            listed.append(
                f"match {m}, team {team}: {missing} goal(s) with no scoring event in the raw "
                "data (only the keeper's save attempt is tagged)"
            )
        else:
            hard.append(f"match {m}, team {team}: score {goals}, SPADL {sp}")
    n = ctx.one("select count(*) from wy_matches")
    bad_matches = len({r[0] for r in rows})
    summary = f"{n - bad_matches} of {n} matches agree exactly"
    if hard:
        return _result(name, desc, hard + listed, summary)
    return _result(name, desc, listed, summary, allow=True)


@check
def wy_coordinates_convert(ctx: Ctx) -> CheckResult:
    """Wyscout 0-100 positions convert to SPADL metres as documented.

    Every SPADL action from a Wyscout event starts at (x * 1.05, (100 - y) * 0.68), except
    goal kicks (placed at (5, 34)) and keeper saves (moved to the keeper's goal), which
    socceraction repositions on purpose. Corners sit at a corner flag and in-play penalties on
    the spot. Penalties logged at the wrong end (raw x below 50) are listed.
    """
    name = "wy_coordinates_convert"
    desc = (
        "Wyscout 0-100 positions convert to SPADL as (x * 1.05, (100 - y) * 0.68), except goal "
        "kicks and keeper saves, which socceraction repositions. Corners sit at a corner flag "
        "and in-play penalties at the spot (94, 34); penalties logged at the wrong end are "
        "listed."
    )
    if not _has(ctx, "wy_events", "spadl_actions"):
        return _skip(name, desc, "wy_* tables")
    off = ctx.q(
        """select a.type_name, count(*) from spadl_actions a
           join wy_events e on a.provider = 'wyscout'
            and a.original_event_id = cast(e.event_id as varchar)
           where a.type_name not in ('goalkick', 'keeper_save')
             and (abs(a.start_x - e.x * 1.05) > 0.01
                  or abs(a.start_y - (100 - e.y) * 0.68) > 0.01)
           group by 1"""
    )
    corners = ctx.q(
        """select count(*), count(*) filter (where not (x >= 95 and (y <= 5 or y >= 95)))
           from wy_events where subtype_name = 'Corner'"""
    )[0]
    spot = ctx.q(
        """select count(*), count(*) filter (where abs(a.start_x - 94.0) > 2
                                              or abs(a.start_y - 34.0) > 2)
           from spadl_actions a join wy_events e on a.provider = 'wyscout'
            and a.original_event_id = cast(e.event_id as varchar)
           where e.subtype_name = 'Penalty' and e.period < 5 and e.x >= 50"""
    )[0]
    pens = ctx.q(
        """select period, count(*) filter (where x < 50), count(*) from wy_events
           where subtype_name = 'Penalty' group by 1 order by 1"""
    )
    problems = [f"{n} {t} actions off the documented formula" for t, n in off]
    if corners[1]:
        problems.append(f"{corners[1]} of {corners[0]} corners not at a corner flag (raw)")
    if spot[1]:
        problems.append(f"{spot[1]} of {spot[0]} in-play penalties not within 2 m of the spot")
    problems += [
        f"period {p}: {bad} of {n} penalties logged at the wrong end (raw x < 50)"
        for p, bad, n in pens
        if bad
    ]
    n_ok = ctx.one(
        """select count(*) from spadl_actions a join wy_events e on a.provider = 'wyscout'
           and a.original_event_id = cast(e.event_id as varchar)
           where a.type_name not in ('goalkick', 'keeper_save')"""
    )
    return _result(
        name,
        desc,
        problems,
        f"{n_ok} actions checked against their raw event; {corners[0]} corners and "
        f"{spot[0]} in-play penalties checked against fixed positions",
        allow=True,
    )


@check
def match_xref_complete(ctx: Ctx) -> CheckResult:
    """All 64 World Cup 2018 matches link one to one, with scores and sides agreeing."""
    name, desc = (
        "match_xref_complete",
        "All 64 matches of the 2018 World Cup link one to one between StatsBomb and Wyscout, "
        "and every link's score agrees.",
    )
    if not _has(ctx, "match_xref"):
        return _skip(name, desc, "match_xref")
    if not ctx.check_section_2:
        return CheckResult(name, desc, "SKIP", "published counts apply to the real data only")
    n, sb, wy, score = ctx.q(
        "select count(*), count(distinct sb_match_id), count(distinct wy_match_id), "
        "sum(score_agrees::int) from match_xref"
    )[0]
    problems = []
    if not (n == sb == wy == 64):
        problems.append(f"{n} links ({sb} StatsBomb, {wy} Wyscout matches), expected 64")
    if score != n:
        problems.append(f"{n - score} links where the score disagrees")
    tiers = ", ".join(
        f"{c} {k}"
        for k, c in ctx.q("select confidence, count(*) from match_xref group by 1 order by 1")
    )
    return _result(name, desc, problems, f"{n} links ({tiers})")


@check
def tracking_frames_match_published(ctx: Ctx) -> CheckResult:
    """Frames per DFL match equal Bassek et al. (2025), Table 1."""
    from rondo.core.dfl_ingest import PUBLISHED

    name, desc = (
        "tracking_frames_match_published",
        "Frames per DFL match equal the published table.",
    )
    if not _has(ctx, "tracking_frames", "tracking_meta"):
        return _skip(name, desc, "tracking tables")
    if not ctx.check_section_2:
        return CheckResult(name, desc, "SKIP", "published counts apply to the real data only")
    got = dict(
        ctx.q(
            "select match_id, count(distinct (period, frame)) from tracking_frames "
            "where provider = 'dfl' group by 1"
        )
    )
    meta = dict(ctx.q("select match_id, sum(n_frames) from tracking_meta group by 1"))
    problems = []
    for m, (frames, _) in PUBLISHED.items():
        if got.get(m) != frames or meta.get(m) != frames:
            problems.append(f"{m}: {got.get(m)} frames ({meta.get(m)} in meta), published {frames}")
    return _result(name, desc, problems, f"{sum(got.values())} frames in {len(got)} matches")


@check
def tracking_frames_at_25hz(ctx: Ctx) -> CheckResult:
    """Within each period, consecutive frames are one frame and 0.04 s apart."""
    name, desc = (
        "tracking_frames_at_25hz",
        "Within each period, consecutive frames are exactly one frame number and 0.04 s apart.",
    )
    if not _has(ctx, "tracking_frames"):
        return _skip(name, desc, "tracking tables")
    rows = ctx.q(
        """with t as (select distinct match_id, period, frame, time_s from tracking_frames),
           d as (select match_id, period, frame - lag(frame) over w as df,
                        time_s - lag(time_s) over w as dt
                 from t window w as (partition by match_id, period order by frame))
           select match_id, period, count(*) from d
           where df is not null and (df <> 1 or abs(dt - 0.04) > 1e-6) group by 1, 2"""
    )
    rate = ctx.q("select distinct frame_rate from tracking_meta")
    problems = [f"{m} period {p}: {n} irregular steps" for m, p, n in rows]
    problems += [f"frame rate {r} in metadata" for (r,) in rate if r != 25]
    return _result(name, desc, problems, "frame spacing checked in every period")


@check
def tracking_players_and_ball_in_play(ctx: Ctx) -> CheckResult:
    """While the ball is in play, 22 players and the ball are present; exceptions listed."""
    name, desc = (
        "tracking_players_and_ball_in_play",
        "While the ball is in play, every frame has 22 players and the ball; exceptions "
        "(e.g. after a red card) are listed per match.",
    )
    if not _has(ctx, "tracking_frames"):
        return _skip(name, desc, "tracking tables")
    rows = ctx.q(
        """with f as (select match_id, period, frame,
                        count(*) filter (where object_id <> 'ball') as players,
                        count(*) filter (where object_id = 'ball') as ball
                 from tracking_frames where ball_alive group by 1, 2, 3)
           select match_id, count(*),
                  count(*) filter (where players <> 22), count(*) filter (where ball = 0),
                  min(players), max(players)
           from f group by 1 order by 1"""
    )
    reds = (
        dict(
            ctx.q(
                "select match_id, count(*) from dfl_events where event_type = 'Caution' "
                "and json_extract_string(attributes, '$.CardColor') = 'red' group by 1"
            )
        )
        if _has(ctx, "dfl_events")
        else {}
    )
    problems = [
        f"{m}: {np} of {n} in-play frames without 22 players (range {lo}-{hi}), "
        f"{nb} without the ball; red cards in the official events: {reds.get(m, 0)}"
        for m, n, np, nb, lo, hi in rows
        if np or nb
    ]
    alive = sum(r[1] for r in rows)
    return _result(name, desc, problems, f"{alive} in-play frames", allow=True)


@check
def tracking_speed_cap(ctx: Ctx) -> CheckResult:
    """No player exceeds the documented speed cap; violations listed, never deleted."""
    name = "tracking_speed_cap"
    desc = (
        f"No player moves faster than {SPEED_CAP:g} m/s, measured over {SPEED_WINDOW_FRAMES} "
        "frames (0.2 s). Violations are listed per match; no data is deleted."
    )
    if not _has(ctx, "tracking_frames"):
        return _skip(name, desc, "tracking tables")
    w = SPEED_WINDOW_FRAMES
    rows = ctx.q(
        f"""with p as (select match_id, period, object_id, frame, x, y,
                         lag(x, {w}) over win as x0, lag(y, {w}) over win as y0,
                         lag(frame, {w}) over win as f0
                  from tracking_frames where object_id <> 'ball'
                  window win as (partition by match_id, period, object_id order by frame)),
           s as (select match_id, object_id,
                        sqrt((x - x0) * (x - x0) + (y - y0) * (y - y0)) / ((frame - f0) / 25.0)
                          as speed
                 from p where f0 is not null and frame - f0 = {w})
           select match_id, count(*) filter (where speed > {SPEED_CAP}),
                  count(distinct object_id) filter (where speed > {SPEED_CAP}),
                  max(speed), count(*)
           from s group by 1 order by 1"""
    )
    problems = [
        f"{m}: {n} measurements above {SPEED_CAP:g} m/s from {p} players (max {mx:.1f} m/s)"
        for m, n, p, mx, _ in rows
        if n
    ]
    total = sum(r[4] for r in rows)
    over = sum(r[1] for r in rows)
    return _result(
        name, desc, problems, f"{total} speed measurements, {over} above the cap", allow=True
    )


# --- Phase 3: identity and the minors rule ----------------------------------------------------


@check
def same_match_links_agree(ctx: Ctx) -> CheckResult:
    """Wikidata links agree with the 2018 World Cup same-match pairs; disagreements listed."""
    name, desc = (
        "same_match_links_agree",
        "Where a 2018 World Cup StatsBomb player and their same-match Wyscout partner are both "
        "linked to Wikidata, the two links name the same person. Disagreements are listed "
        "(they are never merged).",
    )
    if not _has(ctx, "player_xref"):
        return _skip(name, desc, "player_xref")
    rows = ctx.q(
        """select a.provider_player_id, b.provider_player_id, a.qid, b.qid
           from player_xref a join player_xref b
             on a.provider = 'statsbomb' and b.provider = 'wyscout'
            and a.same_match_partner = b.provider_player_id
            and b.same_match_partner = a.provider_player_id
           where a.qid is not null and b.qid is not null"""
    )
    bad = [f"StatsBomb {a} -> {qa}, Wyscout {b} -> {qb}" for a, b, qa, qb in rows if qa != qb]
    n = len(rows)
    rate = (n - len(bad)) / n if n else 0.0
    return _result(name, desc, bad, f"{n - len(bad)} of {n} pairs agree ({rate:.1%})", allow=True)


@check
def one_person_per_provider_id(ctx: Ctx) -> CheckResult:
    """Persons appearing under two ids within one provider are listed."""
    name, desc = (
        "one_person_per_provider_id",
        "Each person has one id per provider; persons under two or more ids within one "
        "provider are listed.",
    )
    if not _has(ctx, "player_xref"):
        return _skip(name, desc, "player_xref")
    rows = ctx.q(
        """select provider, person_id, list(provider_player_id order by provider_player_id)
           from player_xref where qid is not null
           group by 1, 2 having count(*) > 1 order by 1, 2"""
    )
    return _result(
        name,
        desc,
        [f"{p}: {person} has ids {', '.join(ids)}" for p, person, ids in rows],
        f"{len(rows)} persons with more than one id in a provider",
        allow=True,
    )


@check
def every_person_has_age_status(ctx: Ctx) -> CheckResult:
    """Every person with an appearance has an age status for each competition-season."""
    name, desc = (
        "every_person_has_age_status",
        "Every linked or unlinked provider player has an age status for each "
        "competition-season they appear in.",
    )
    if not _has(ctx, "player_xref", "player_age_status"):
        return _skip(name, desc, "player_age_status")
    missing = ctx.one(
        "select count(distinct person_id) from player_xref "
        "where person_id not in (select person_id from player_age_status)"
    )
    total = ctx.one("select count(distinct person_id) from player_age_status")
    return _result(
        name,
        desc,
        [f"{missing} persons without any age status"] if missing else [],
        f"{total} persons with age statuses",
    )


@check
def low_links_never_verify_age(ctx: Ctx) -> CheckResult:
    """Low-confidence links neither merge persons nor supply a Wikidata birth date."""
    name, desc = (
        "low_links_never_verify_age",
        "A provider player linked to Wikidata only by name search (low confidence) is a person "
        "of their own, and their age status never rests on a Wikidata birth date.",
    )
    if not _has(ctx, "player_xref", "player_age_status"):
        return _skip(name, desc, "player_age_status")
    merged = ctx.one(
        """select count(*) from player_xref x
           where x.confidence = 'low'
             and (select count(*) from player_xref y where y.person_id = x.person_id) > 1"""
    )
    via_wd = ctx.one(
        """select count(distinct a.person_id) from player_age_status a
           join player_xref x using (person_id)
           where x.confidence = 'low' and a.birth_date_source like '%wikidata%'"""
    )
    n = ctx.one("select count(*) from player_xref where confidence = 'low'")
    problems = [f"{merged} low links share a person with another record"] if merged else []
    problems += [f"{via_wd} persons with a low link have a Wikidata birth date"] if via_wd else []
    return _result(name, desc, problems, f"{n} low-confidence links checked")


@check
def no_uncleared_names_published(ctx: Ctx) -> CheckResult:
    """No name of a player not cleared by display_ok appears under web/public/ or reports/."""
    from rondo.core import public
    from rondo.core.paths import REPO_ROOT

    name, desc = (
        "no_uncleared_names_published",
        "No name of a player that core.public.display_ok doesn't clear appears in any text "
        "file under web/public/ or reports/. Matches are reported as "
        "file and count only.",
    )
    if not _has(ctx, "player_xref", "player_age_status"):
        return _skip(name, desc, "player_age_status")
    pq = _parquet_of(ctx)
    blocked = public.blocked_names(pq)
    hits = public.scan([REPO_ROOT / "web" / "public", REPO_ROOT / "reports"], blocked)
    per_file: dict[str, int] = {}
    for f, _ in hits:
        per_file[f] = per_file.get(f, 0) + 1
    return _result(
        name,
        desc,
        [f"{f}: {n} uncleared name(s)" for f, n in sorted(per_file.items())],
        f"{len(blocked)} names blocked; web/public/ and reports/ scanned",
    )


def _parquet_of(ctx: Ctx) -> Path:
    """Return the Parquet folder the context's views read (from the player_xref view)."""
    sql = ctx.one("select sql from duckdb_views() where view_name = 'player_xref'")
    m = re.search(r"read_parquet\('([^']+)/player_xref\.parquet'\)", str(sql))
    return Path(m.group(1)) if m else parquet_dir()


def run_all(ctx: Ctx) -> list[CheckResult]:
    """Run every registered check."""
    return [fn(ctx) for fn in CHECKS]


def info_tables(ctx: Ctx) -> dict[str, list[tuple]]:
    """Facts reported alongside the checks (not pass/fail)."""
    return {
        "events with no SPADL action, by type": ctx.q(
            """select e.type_name, count(*) from events e
               anti join (select original_event_id as event_id from spadl_actions
                          where provider = 'statsbomb') a using (event_id)
               group by 1 order by 2 desc"""
        ),
        "SPADL actions with no source event, by type (inserted by socceraction)": ctx.q(
            """select type_name, count(*) from spadl_actions
               where provider = 'statsbomb' and original_event_id is null group by 1"""
        ),
        "lineup spells ending before they start on the match clock (spells, matches)": ctx.q(
            """select count(*), count(distinct match_id) from lineup_positions
               where to_period is not null
                 and (to_period < from_period
                      or (to_period = from_period and to_clock_s < from_clock_s))"""
        ),
        "defensive actions with no success flag, by action": ctx.q(
            """select action, count(*) from defensive_actions where is_success is null
               group by 1 order by 2 desc"""
        ),
    }


def render(results: list[CheckResult], info: dict[str, list[tuple]]) -> str:
    """Render reports/data_quality.md."""
    lines = [
        "# Data quality",
        "",
        "Generated by `make check` (`python -m rondo.core.checks`). Don't edit by hand.",
        "",
        "| Check | Status | Summary | Exceptions |",
        "|---|---|---|---|",
    ]
    for r in results:
        lines.append(f"| `{r.name}` | {r.status} | {r.summary} | {r.n_exceptions} |")
    for r in results:
        lines += ["", f"## {r.name}", "", r.description, "", f"**{r.status}**: {r.summary}."]
        if r.exceptions:
            shown = (
                f" (first {len(r.exceptions)} of {r.n_exceptions})"
                if r.n_exceptions > len(r.exceptions)
                else ""
            )
            lines += ["", f"Exceptions{shown}:", ""] + [f"- {e}" for e in r.exceptions]
    lines += ["", "## Reported facts (not pass/fail)"]
    for title, rows in info.items():
        lines += ["", f"### {title}", ""]
        lines += [f"- {' | '.join(str(v) for v in row)}" for row in rows] or ["- none"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Run all checks, write the report, exit 1 if any check FAILs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", type=Path, default=parquet_dir())
    parser.add_argument("--checkout", type=Path, default=statsbomb_raw_dir() / "open-data")
    parser.add_argument("--report", type=Path, default=reports_dir() / "data_quality.md")
    args = parser.parse_args(argv)
    con = store.connect()
    store.create_views(con, args.parquet)
    ctx = Ctx(con, args.checkout)
    results = run_all(ctx)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render(results, info_tables(ctx)))
    width = max(len(r.name) for r in results)
    for r in results:
        print(f"{r.status:<10} {r.name:<{width}}  {r.summary} [{r.n_exceptions} exceptions]")
        if r.status == "FAIL":
            for e in r.exceptions[:5]:
                print(f"           - {e}")
    failed = [r.name for r in results if r.status == "FAIL"]
    print(
        f"\n{len(results) - len(failed)} of {len(results)} checks without FAIL; "
        f"report: {args.report}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
