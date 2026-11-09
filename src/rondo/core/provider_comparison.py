"""Compare StatsBomb and Wyscout on the 64 matches both logged (2018 World Cup).

Two views, both excluding the penalty shootout:

- **Common vocabulary**: both providers' events converted to SPADL by socceraction, so each
  category means the same thing on both sides.
- **Raw**: each provider's own event types, closest equivalents, which show where the two
  definitions differ.

Writes ``reports/provider_comparison.md`` (via ``make report``).
"""

from __future__ import annotations

import statistics
from pathlib import Path

from rondo.core import store

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


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


SPADL_CATEGORIES = {
    "passes": f"type_name in ({_in(PASS_FAMILY)})",
    "shots": "type_name like 'shot%'",
    "goals": "(type_name like 'shot%' and result_name = 'success') or result_name = 'owngoal'",
    "fouls": "type_name = 'foul'",
    "tackles": "type_name = 'tackle'",
}

#: (category, StatsBomb raw definition, SQL on events; Wyscout raw definition, SQL on wy_events)
RAW = [
    (
        "passes",
        "`Pass` events (all kinds, incl. set pieces)",
        "type_name = 'Pass'",
        "`Pass` events plus `Free Kick` passes (throw-ins, goal kicks, corners, free kicks)",
        "type_name = 'Pass' or (type_name = 'Free Kick' and subtype_name in "
        "('Throw in', 'Goal kick', 'Corner', 'Free Kick', 'Free kick cross'))",
    ),
    (
        "shots",
        "`Shot` events (incl. penalties)",
        "type_name = 'Shot'",
        "`Shot` events plus `Free kick shot` and `Penalty`",
        "type_name = 'Shot' or subtype_name in ('Free kick shot', 'Penalty')",
    ),
    (
        "goals",
        "shots with outcome Goal, plus `Own Goal For` events",
        "(type_name = 'Shot' and json_extract_string(details, '$.shot.outcome.name') = 'Goal') "
        "or type_name = 'Own Goal For'",
        "events tagged 101 (goal) on shots, free-kick shots and penalties, plus tag 102 (own goal)",
        "((type_name = 'Shot' or subtype_name in ('Free kick shot', 'Penalty')) "
        "and list_contains(tags, 101)) or list_contains(tags, 102)",
    ),
    (
        "fouls",
        "`Foul Committed` events",
        "type_name = 'Foul Committed'",
        "`Foul` events (all subtypes, incl. hand fouls, protests, simulation, time lost)",
        "type_name = 'Foul'",
    ),
    (
        "tackles",
        "`Duel` events of type Tackle",
        "type_name = 'Duel' and json_extract_string(details, '$.duel.type.name') = 'Tackle'",
        "`Duel` events of subtype Ground defending duel",
        "type_name = 'Duel' and subtype_name = 'Ground defending duel'",
    ),
]


def _per_match(con: object, sql: str) -> dict[int, int]:
    return {m: n for m, n in con.execute(sql).fetchall()}  # type: ignore[attr-defined]


def render(parquet: Path) -> str:
    """Build the comparison report from the shared tables."""
    con = store.connect()
    store.create_views(con, parquet)
    matches = con.execute(
        """select x.sb_match_id, x.wy_match_id, x.sb_date, h.team_name, a.team_name
           from match_xref x join teams h on h.team_id = x.sb_home_team_id
           join teams a on a.team_id = x.sb_away_team_id order by x.sb_date, x.sb_match_id"""
    ).fetchall()
    spadl: dict[str, tuple[dict[int, int], dict[int, int]]] = {}
    for cat, cond in SPADL_CATEGORIES.items():
        sb = _per_match(
            con,
            f"""select a.match_id, count(*) filter (where {cond}) from spadl_actions a
                join match_xref x on x.sb_match_id = a.match_id
                where a.provider = 'statsbomb' and a.period_id < 5 group by 1""",
        )
        wy = _per_match(
            con,
            f"""select a.match_id, count(*) filter (where {cond}) from spadl_actions a
                join match_xref x on x.wy_match_id = a.match_id
                where a.provider = 'wyscout' and a.period_id < 5 group by 1""",
        )
        spadl[cat] = (sb, wy)
    raw: dict[str, tuple[dict[int, int], dict[int, int]]] = {}
    for cat, _, sb_sql, _, wy_sql in RAW:
        sb = _per_match(
            con,
            f"""select e.match_id, count(*) filter (where {sb_sql}) from events e
                join match_xref x on x.sb_match_id = e.match_id where e.period < 5 group by 1""",
        )
        wy = _per_match(
            con,
            f"""select e.match_id, count(*) filter (where {wy_sql}) from wy_events e
                join match_xref x on x.wy_match_id = e.match_id where e.period < 5 group by 1""",
        )
        raw[cat] = (sb, wy)
    con.close()

    def summary_row(label: str, definition: str, sb: dict, wy: dict, pairs: list) -> str:
        s = sum(sb.get(m, 0) for m, _ in pairs)
        w = sum(wy.get(m, 0) for _, m in pairs)
        diffs = [abs(sb.get(a, 0) - wy.get(b, 0)) for a, b in pairs]
        equal = sum(d == 0 for d in diffs)
        ratio = f"{w / s:.3f}" if s else "n/a"
        return (
            f"| {label} | {definition} | {s:,} | {w:,} | {ratio} | "
            f"{statistics.median(diffs):g} | {equal} of {len(pairs)} |"
        )

    pairs = [(m[0], m[1]) for m in matches]
    lines = [
        "# Provider comparison: 2018 World Cup in StatsBomb and Wyscout",
        "",
        "Generated by `make report` (`rondo.core.provider_comparison`). Don't edit by hand. "
        f"Covers the {len(matches)} matches linked in `match_xref`, excluding penalty shootouts.",
        "",
        "## Totals, common vocabulary (both providers converted to SPADL)",
        "",
        "| Category | SPADL definition | StatsBomb | Wyscout | Wyscout / StatsBomb | "
        "Median per-match gap | Matches equal |",
        "|---|---|---|---|---|---|---|",
    ]
    defs = {
        "passes": "pass, cross, throw-in, free kick, corner and goal kick actions",
        "shots": "shot, free-kick shot and penalty",
        "goals": "successful shots plus own goals",
        "fouls": "foul",
        "tackles": "tackle",
    }
    for cat in SPADL_CATEGORIES:
        lines.append(summary_row(cat, defs[cat], *spadl[cat], pairs))
    lines += [
        "",
        "## Totals, each provider's own event types",
        "",
        "| Category | StatsBomb counts | Wyscout counts | StatsBomb | Wyscout | "
        "Wyscout / StatsBomb | Median per-match gap | Matches equal |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for cat, sb_def, _, wy_def, _ in RAW:
        row = summary_row(cat, f"{sb_def} | {wy_def}", *raw[cat], pairs)
        lines.append(row)
    lines += [
        "",
        "## Where the definitions differ",
        "",
        "- **Passes.** StatsBomb logs every pass, set pieces included, as a `Pass` event. "
        "Wyscout records set pieces (throw-ins, goal kicks, corners, free kicks) as `Free Kick` "
        "events. SPADL maps both onto the same pass types. socceraction also drops StatsBomb "
        "passes with outcome Injury Clearance or Unknown.",
        "- **Shots.** Wyscout splits direct free-kick shots and penalties into `Free Kick` "
        "subtypes; StatsBomb keeps them as `Shot` events with a type.",
        "- **Goals.** Both providers credit own goals separately (StatsBomb as paired `Own Goal "
        "For` and `Own Goal Against` events, Wyscout as tag 102). Goals agree with the score in "
        "both providers (checks `spadl_goals_equal_score` and `wy_goals_equal_score`).",
        "- **Fouls.** Wyscout's `Foul` covers more than fouls committed in play: hand fouls, "
        "protests, simulation, time-wasting and late cards are all `Foul` subtypes.",
        "- **Tackles.** StatsBomb records a tackle as a `Duel` of type Tackle (attempted "
        "tackles, won or lost). Wyscout has no tackle type; the closest raw equivalent is the "
        "ground defending duel, which also covers duels without a tackle. socceraction derives "
        "SPADL tackles from each provider differently.",
        "",
        "## Per match, common vocabulary (StatsBomb / Wyscout)",
        "",
        "| Date | Match (StatsBomb names) | Passes | Shots | Goals | Fouls | Tackles |",
        "|---|---|---|---|---|---|---|",
    ]
    for sb_id, wy_id, date, home, away in matches:
        cells = [f"{spadl[c][0].get(sb_id, 0)} / {spadl[c][1].get(wy_id, 0)}" for c in spadl]
        lines.append(f"| {date} | {home} v {away} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
