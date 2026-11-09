"""Identity reports (``make report``): coverage, the hand-check audit sample, the team map.

- ``reports/identity_coverage.md``: per competition-season, the share of players linked to
  Wikidata and the share ``verified_adult``; minors as counts only, never names.
- ``reports/xref_audit.csv``: 100 links, a random sample stratified by provider and
  competition, with the evidence for each, for MJ to hand-check 20. A name is withheld unless
  :func:`rondo.core.public.display_ok` clears the person for that row's competition-season;
  birth dates never appear. MJ's marks live in ``docs/audit/xref_hand_check.csv`` (ids only),
  and the coverage report computes precision from them.
  The unmasked copy goes to ``data/audit/xref_audit_full.csv`` (gitignored, never published).
- ``reports/team_wikidata.csv``: every provider team and its Wikidata item.
"""

from __future__ import annotations

import csv
import math
import random
from collections import defaultdict
from pathlib import Path

from rondo.core import public, store
from rondo.core.paths import REPO_ROOT, data_dir

SEED = 20261109
SAMPLE = 100
WITHHELD = "[withheld: not cleared by display_ok]"
HAND_CHECK = REPO_ROOT / "docs" / "audit" / "xref_hand_check.csv"


def lower_bound(k: int, n: int, alpha: float = 0.05) -> float:
    """One-sided exact (Clopper-Pearson) lower confidence bound for k successes in n."""
    if k == 0:
        return 0.0

    def tail(p: float) -> float:  # P(X >= k | p)
        return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))

    lo, hi = 0.0, k / n
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if tail(mid) < alpha else (lo, mid)
    return lo


def hand_check(parquet: Path, path: Path = HAND_CHECK) -> list[str]:
    """Markdown lines for MJ's hand check: marks that still match a current link count."""
    if not path.exists():
        return ["No hand-check marks recorded: precision unmeasured."]
    marks = list(csv.DictReader(path.open()))
    con = store.connect()
    store.create_views(con, parquet)
    links = {
        (p, pid): q
        for p, pid, q in con.execute(
            "select provider, provider_player_id, qid from player_xref where qid is not null"
        ).fetchall()
    }
    con.close()
    current = [m for m in marks if links.get((m["provider"], m["provider_player_id"])) == m["qid"]]
    n, k = len(current), sum(m["correct"].strip().lower() == "yes" for m in current)
    stale = len(marks) - n
    if not n:
        return ["No hand-check mark matches a current link: precision unmeasured."]
    return [
        f"Links marked by hand: {n} ({stale} older marks no longer match a link). Correct: {k}. "
        f"Precision on the marked links: {k / n:.1%}; exact one-sided 95% lower bound: "
        f"{lower_bound(k, n):.1%}. The target is at least 98%; a sample of {n} can't show that "
        "on its own, only that the links checked were right.",
    ]


def coverage(parquet: Path) -> str:
    """Render ``reports/identity_coverage.md``."""
    con = store.connect()
    store.create_views(con, parquet)
    rows = con.execute(
        """with s as (
             select a.competition_season, a.person_id, a.status,
                    bool_or(x.qid is not null) as linked
             from player_age_status a join player_xref x using (person_id) group by 1, 2, 3)
           select competition_season, count(*) as players,
                  count(*) filter (where linked) as linked,
                  count(*) filter (where status = 'verified_adult') as adults,
                  count(*) filter (where status = 'minor_during_season') as minors,
                  count(*) filter (where status = 'unverified') as unverified
           from s group by 1 order by 1"""
    ).fetchall()
    names = {
        f"statsbomb:{c}/{s}": f"{n} {sn}"
        for c, s, n, sn in con.execute(
            "select competition_id, season_id, competition_name, season_name from competitions"
        ).fetchall()
    } | {
        f"wyscout:{c}/{s}": n
        for c, s, n in con.execute(
            "select distinct m.competition_id, m.season_id, c.name from wy_matches m "
            "join wy_competitions c using (competition_id)"
        ).fetchall()
    }
    totals = con.execute(
        """select provider, count(*), count(*) filter (where qid is not null),
                  count(*) filter (where status = 'ambiguous'),
                  count(*) filter (where status = 'weak name match'),
                  count(*) filter (where status = 'unmatched')
           from player_xref group by 1 order by 1"""
    ).fetchall()
    dups = con.execute(
        """select provider, count(*) from (
             select provider, person_id from player_xref where qid is not null
             group by 1, 2 having count(*) > 1) group by 1 order by 1"""
    ).fetchall()
    persons = con.execute(
        """select person_id, list(distinct status) from player_age_status group by 1"""
    ).fetchall()
    con.close()
    mixed = sum(1 for _, sts in persons if "minor_during_season" in sts and "verified_adult" in sts)
    ever_minor = sum(1 for _, sts in persons if "minor_during_season" in sts)
    lines = [
        "# Player identity and age coverage",
        "",
        "Generated by `make report`. Don't edit by hand. Counts only: no names, no birth dates.",
        "",
        "## Links per provider",
        "",
        "| Provider | Players | Linked to Wikidata | Ambiguous | Weak name match | Unmatched |",
        "|---|---|---|---|---|---|",
    ]
    for prov, n, linked, amb, weak, unm in totals:
        lines.append(
            f"| {prov} | {n:,} | {linked:,} ({linked / n:.1%}) | {amb:,} | {weak:,} | {unm:,} |"
        )
    lines += [
        "",
        "Provider ids that share a person (one person under two ids within one provider): "
        + (", ".join(f"{p}: {n}" for p, n in dups) if dups else "none")
        + ".",
        "",
        "## Per competition-season",
        "",
        "| Competition-season | Players | Linked | Verified adult | Minor during season | "
        "Unverified |",
        "|---|---|---|---|---|---|",
    ]
    for cs, n, linked, adults, minors, unver in rows:
        label = names.get(cs, cs)
        lines.append(
            f"| {label} (`{cs}`) | {n:,} | {linked / n:.1%} | {adults / n:.1%} | {minors:,} | "
            f"{unver:,} |"
        )
    lines += [
        "",
        "## The minors rule, read per season",
        "",
        f"People who were minors in at least one covered competition-season: {ever_minor:,}. Of "
        f"those, {mixed:,} are verified adults in at least one other covered competition-season: "
        "they may be named in output about those seasons only, never about the seasons when "
        "they were minors.",
        "",
        "## Hand check of the links",
        "",
        *hand_check(parquet),
    ]
    return "\n".join(lines) + "\n"


def audit(parquet: Path) -> tuple[list[dict], list[dict]]:
    """Draw the stratified sample; return (published rows, unmasked rows)."""
    con = store.connect()
    store.create_views(con, parquet)
    links = con.execute(
        """with comp as (
             select x.provider, x.provider_player_id, a.competition_season,
                    row_number() over (partition by x.provider, x.provider_player_id
                                       order by a.competition_season) as rn
             from player_xref x join player_age_status a using (person_id)
             where split_part(a.competition_season, ':', 1) = x.provider)
           select x.provider, c.competition_season, x.provider_player_id, x.name, x.person_id,
                  x.qid, w.label, x.method, x.confidence, x.name_score, x.team_support,
                  x.dob_agrees, x.same_match_partner
           from player_xref x join comp c using (provider, provider_player_id)
           left join wikidata_people w using (qid)
           where x.qid is not null and c.rn = 1
           order by 1, 2, 3"""
    ).fetchall()
    con.close()
    strata: dict[tuple[str, str], list[tuple]] = defaultdict(list)
    for r in links:
        strata[(r[0], r[1])].append(r)
    total = len(links)
    rng = random.Random(SEED)
    # Proportional allocation (largest remainder), at least one per stratum while possible.
    quota = {k: SAMPLE * len(v) / total for k, v in strata.items()}
    alloc = {k: max(1, int(q)) for k, q in quota.items()}
    for k in sorted(quota, key=lambda k: quota[k] - int(quota[k]), reverse=True):
        if sum(alloc.values()) >= SAMPLE:
            break
        alloc[k] += 1
    while sum(alloc.values()) > SAMPLE:
        k = max(alloc, key=lambda k: alloc[k])
        alloc[k] -= 1
    published, full = [], []
    i = 0
    for key in sorted(strata):
        for r in rng.sample(strata[key], min(alloc[key], len(strata[key]))):
            i += 1
            prov, cs, pid, name, person, qid, label, method, conf, ns, ts, dob, partner = r
            ok = public.display_ok(person, [cs], parquet=parquet)
            row = {
                "audit_id": i,
                "provider": prov,
                "competition_season": cs,
                "provider_player_id": pid,
                "provider_name": name,
                "wikidata": f"https://www.wikidata.org/wiki/{qid}",
                "wikidata_label": label,
                "method": method,
                "confidence": conf,
                "name_score": round(ns, 2) if ns is not None else None,
                "teams_supporting": ts,
                "birth_date_agrees": dob,
                "same_match_partner": partner,
                "cleared_for_display": ok,
                "correct (MJ: yes/no)": "",
            }
            full.append(dict(row))
            if not ok:
                row["provider_name"] = WITHHELD
                row["wikidata_label"] = WITHHELD
            published.append(row)
    return published, full


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def write_all(parquet: Path, reports: Path) -> list[Path]:
    """Write every identity report; return the paths written."""
    public._statuses.cache_clear()
    (reports / "identity_coverage.md").write_text(coverage(parquet))
    published, full = audit(parquet)
    _write_csv(reports / "xref_audit.csv", published)
    _write_csv(data_dir() / "audit" / "xref_audit_full.csv", full)
    con = store.connect()
    store.create_views(con, parquet)
    teams = con.execute(
        "select provider, team_id, team_name, kind, qid, qid_label, qid_description, "
        "search_text, rank from team_wikidata order by provider, team_name"
    ).fetchall()
    con.close()
    cols = [
        "provider",
        "team_id",
        "team_name",
        "kind",
        "qid",
        "qid_label",
        "qid_description",
        "search_text",
        "rank",
    ]
    _write_csv(reports / "team_wikidata.csv", [dict(zip(cols, r, strict=True)) for r in teams])
    return [
        reports / "identity_coverage.md",
        reports / "xref_audit.csv",
        reports / "team_wikidata.csv",
    ]
