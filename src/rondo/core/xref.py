"""Cross-provider match links for the 2018 World Cup (StatsBomb 43/3 and Wyscout 28).

Links by evidence first: a StatsBomb match pairs with the Wyscout match played within a day of
it with the same goals for both sides (before any shootout). Team names then confirm the pair
and align the sides: a team whose name matches pairs by name; if only one does, the other
pairs by elimination (a match has two teams). Every link records its evidence and a confidence
tier; anything unmatched or ambiguous is listed, never forced.

Writes ``match_xref.parquet`` and ``team_xref.parquet``.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from rondo.core import store
from rondo.core.parquet_io import write_single
from rondo.core.schemas import MATCH_XREF, TEAM_XREF

SB_WC2018 = (43, 3)
WY_WC2018 = 28


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def _same(a: str, b: str) -> bool:
    return _norm(a) == _norm(b)


def link(sb: list[dict[str, Any]], wy: list[dict[str, Any]]) -> tuple[list[dict], list[str]]:
    """Link matches; return (links, problems). Inputs are rows with names and goals."""
    links, problems = [], []
    used: set[int] = set()
    for s in sorted(sb, key=lambda r: r["match_id"]):
        cands = []
        for w in wy:
            dd = abs((w["date_utc"].date() - s["match_date"]).days)
            if dd > 1:
                continue
            teams_s = {s["home_name"], s["away_name"]}
            teams_w = {w["home_name"], w["away_name"]}
            named = sum(any(_same(a, b) for b in teams_w) for a in teams_s)
            goals_s = sorted([s["home_goals"], s["away_goals"]])
            goals_w = sorted([w["home_goals"], w["away_goals"]])
            if goals_s != goals_w or named == 0:
                continue
            cands.append((dd, -named, w))
        if not cands:
            problems.append(f"StatsBomb match {s['match_id']}: no Wyscout match within a day")
            continue
        cands.sort(key=lambda c: (c[0], c[1]))
        best = [c for c in cands if c[:2] == cands[0][:2]]
        if len(best) > 1:
            problems.append(f"StatsBomb match {s['match_id']}: {len(best)} equally good matches")
            continue
        dd, neg_named, w = cands[0]
        if w["match_id"] in used:
            problems.append(f"Wyscout match {w['match_id']} linked twice")
            continue
        used.add(w["match_id"])
        # Align sides: by name where possible, else by elimination.
        if _same(s["home_name"], w["home_name"]) or _same(s["away_name"], w["away_name"]):
            home_w, away_w, sides_agree = w["home_team_id"], w["away_team_id"], True
        elif _same(s["home_name"], w["away_name"]) or _same(s["away_name"], w["home_name"]):
            home_w, away_w, sides_agree = w["away_team_id"], w["home_team_id"], False
        else:
            problems.append(f"StatsBomb match {s['match_id']}: sides can't be aligned")
            continue
        g_home_w = w["home_goals"] if sides_agree else w["away_goals"]
        g_away_w = w["away_goals"] if sides_agree else w["home_goals"]
        named = -neg_named
        links.append(
            {
                "competition": "FIFA World Cup 2018",
                "sb_match_id": s["match_id"],
                "wy_match_id": w["match_id"],
                "sb_date": s["match_date"],
                "wy_date_utc": w["date_utc"],
                "date_diff_days": dd,
                "sb_home_team_id": s["home_team_id"],
                "sb_away_team_id": s["away_team_id"],
                "wy_team_for_sb_home": home_w,
                "wy_team_for_sb_away": away_w,
                "sides_agree": sides_agree,
                "score_agrees": (g_home_w, g_away_w) == (s["home_goals"], s["away_goals"]),
                "names_matched": named,
                "method": "date + score + team names"
                if named == 2
                else "date + score + one team name (other by elimination)",
                "confidence": "high" if named == 2 and dd == 0 else "medium",
            }
        )
    return links, problems


def build(parquet: Path) -> dict[str, int]:
    """Build ``match_xref`` and ``team_xref`` for the 2018 World Cup."""
    con = store.connect()
    store.create_views(con, parquet)
    sb = [
        dict(
            zip(
                [
                    "match_id",
                    "match_date",
                    "home_team_id",
                    "away_team_id",
                    "home_goals",
                    "away_goals",
                    "home_name",
                    "away_name",
                ],
                r,
                strict=True,
            )
        )
        for r in con.execute(
            f"""select m.match_id, m.match_date, m.home_team_id, m.away_team_id, m.home_score,
                       m.away_score, h.team_name, a.team_name
                from matches m join teams h on h.team_id = m.home_team_id
                join teams a on a.team_id = m.away_team_id
                where m.competition_id = {SB_WC2018[0]} and m.season_id = {SB_WC2018[1]}"""
        ).fetchall()
    ]
    wy = [
        dict(
            zip(
                [
                    "match_id",
                    "date_utc",
                    "home_team_id",
                    "away_team_id",
                    "home_goals",
                    "away_goals",
                    "home_name",
                    "away_name",
                ],
                r,
                strict=True,
            )
        )
        for r in con.execute(
            f"""select m.match_id, m.date_utc, m.home_team_id, m.away_team_id, m.home_goals,
                       m.away_goals, h.name, a.name
                from wy_matches m join wy_teams h on h.team_id = m.home_team_id
                join wy_teams a on a.team_id = m.away_team_id
                where m.competition_id = {WY_WC2018}"""
        ).fetchall()
    ]
    names = {("sb", r["home_team_id"]): r["home_name"] for r in sb}
    names |= {("sb", r["away_team_id"]): r["away_name"] for r in sb}
    names |= {("wy", r["home_team_id"]): r["home_name"] for r in wy}
    names |= {("wy", r["away_team_id"]): r["away_name"] for r in wy}
    con.close()
    links, problems = link(sb, wy)
    for p in problems:
        print(f"xref: {p}")
    pairs: dict[tuple[int, int], dict[str, int]] = defaultdict(lambda: {"n": 0, "name": 0})
    for lk in links:
        for sb_t, wy_t in (
            (lk["sb_home_team_id"], lk["wy_team_for_sb_home"]),
            (lk["sb_away_team_id"], lk["wy_team_for_sb_away"]),
        ):
            pairs[(sb_t, wy_t)]["n"] += 1
            pairs[(sb_t, wy_t)]["name"] += int(_same(names[("sb", sb_t)], names[("wy", wy_t)]))
    teams = [
        {
            "sb_team_id": sb_t,
            "wy_team_id": wy_t,
            "sb_name": names[("sb", sb_t)],
            "wy_name": names[("wy", wy_t)],
            "n_matches": v["n"],
            "by_name": v["name"],
            "by_elimination": v["n"] - v["name"],
        }
        for (sb_t, wy_t), v in sorted(pairs.items())
    ]
    return {
        "match_xref": write_single(parquet / "match_xref.parquet", links, MATCH_XREF),
        "team_xref": write_single(parquet / "team_xref.parquet", teams, TEAM_XREF),
        "problems": len(problems),
    }
