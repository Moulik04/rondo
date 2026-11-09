"""Player identity across providers: one Rondo ``person_id`` per person (``player_xref``).

Evidence before spelling:

1. Every provider team is mapped to its Wikidata item (:mod:`rondo.core.identity_teams`).
2. Wikidata squads: everyone with a ``P54`` (member of sports team) statement for those teams,
   with the membership's start and end, birth date (with precision) and names in eight
   languages.
3. Each provider player is matched to the Wikidata people who were members of the teams the
   player appeared for, around the dates they appeared. A link needs a strong name match and a
   unique best candidate. A Wyscout birth date that equals Wikidata's raises confidence; one
   that contradicts it rules the candidate out.
4. Same-match evidence: in the 2018 World Cup, StatsBomb and Wyscout players are paired within
   each linked match and team by name and minutes. Links made through Wikidata must agree with
   these pairs; the agreement rate is a built-in accuracy check.
5. Links form a graph; each connected group with at most one Wikidata item is one person.
   Groups that would join two different Wikidata items are not merged, and are reported.

Unmatched and ambiguous players are listed, never forced.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rondo.core import store
from rondo.core.parquet_io import write_single
from rondo.core.schemas import PLAYER_XREF, WIKIDATA_PEOPLE
from rondo.core.wikidata import Client

LANGS = ("en", "es", "fr", "it", "de", "pt", "nl", "ca")
#: Membership years outside this window can't matter for Rondo's coverage (2003-2024).
MEMBERSHIP_FROM, MEMBERSHIP_TO = 2000, 2025
#: Name score needed to link, and the margin the best candidate needs over the next one.
LINK_SCORE, MARGIN = 0.8, 0.1
SLACK_DAYS = 365  # membership dates on Wikidata are often only accurate to the year


# --- names ------------------------------------------------------------------------------------


def fold(s: str) -> str:
    """Lower-case, strip accents and punctuation, collapse spaces."""
    s = unicodedata.normalize("NFKD", s.replace("ß", "ss").replace("ø", "o").replace("đ", "d"))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s.replace("-", " ").replace("'", ""))
    return re.sub(r"\s+", " ", s).strip()


def name_score(provider_names: list[str], wd_names: set[str]) -> float:
    """How well a provider player's names match a Wikidata person's names (0 to 1).

    1.0 an exact (folded) match; 0.9 when every token of one name is in the other (e.g. a full
    name containing the common name); 0.85 for an initial plus surname ("L. Messi"); 0.5 for
    a shared surname only.
    """
    best = 0.0
    folded_wd = {fold(n) for n in wd_names if n}
    for pn in provider_names:
        if not pn:
            continue
        p = fold(pn)
        ptoks = p.split()
        if not ptoks:
            continue
        for w in folded_wd:
            if p == w:
                return 1.0
            wtoks = w.split()
            if not wtoks:
                continue
            ps, ws = set(ptoks), set(wtoks)
            if len(ps) >= 2 and len(ws) >= 2 and (ps <= ws or ws <= ps):
                best = max(best, 0.9)
            elif (
                len(ptoks) >= 2
                and len(ptoks[0]) == 1
                and ptoks[-1] == wtoks[-1]
                and wtoks[0].startswith(ptoks[0])
            ):
                best = max(best, 0.85)
            elif len(ptoks) == 1 and len(wtoks) == 1 and ptoks[0] == wtoks[0]:
                best = max(best, 1.0)
            elif ptoks[-1] == wtoks[-1] and len(ptoks[-1]) > 2:
                best = max(best, 0.5)
    return best


# --- Wikidata squads --------------------------------------------------------------------------


@dataclass
class Person:
    """What Wikidata says about one person."""

    qid: str
    names: set[str] = field(default_factory=set)
    dob: dt.date | None = None
    dob_precision: int | None = None
    memberships: list[tuple[str, dt.date | None, dt.date | None]] = field(default_factory=list)


def _date(v: str | None) -> dt.date | None:
    if not v:
        return None
    m = re.match(r"^\+?(-?\d{4})-(\d{2})-(\d{2})", v)
    if not m:
        return None
    y, mo, d = (int(g) for g in m.groups())
    try:
        return dt.date(y, max(mo, 1), max(d, 1))
    except ValueError:
        return None


def fetch_people(client: Client, team_qids: list[str], log: bool = True) -> dict[str, Person]:
    """Everyone who was a member of these teams around Rondo's years, with dates and names."""
    people: dict[str, Person] = {}
    for i in range(0, len(team_qids), 8):
        values = " ".join(f"wd:{q}" for q in team_qids[i : i + 8])
        rows = client.sparql(
            f"""SELECT ?team ?player ?start ?end WHERE {{
                  VALUES ?team {{ {values} }}
                  ?player p:P54 ?st . ?st ps:P54 ?team .
                  OPTIONAL {{ ?st pq:P580 ?start }} OPTIONAL {{ ?st pq:P582 ?end }}
                  FILTER(!BOUND(?end) || YEAR(?end) >= {MEMBERSHIP_FROM})
                  FILTER(!BOUND(?start) || YEAR(?start) <= {MEMBERSHIP_TO})
                }}"""
        )
        for r in rows:
            q = r["player"].rsplit("/", 1)[1]
            team = r["team"].rsplit("/", 1)[1]
            p = people.setdefault(q, Person(q))
            p.memberships.append((team, _date(r.get("start")), _date(r.get("end"))))
        if log:
            print(
                f"wikidata squads: {min(i + 8, len(team_qids))} of {len(team_qids)} teams, "
                f"{len(people)} people",
                flush=True,
            )
    qids = sorted(people)
    langs = ", ".join(f'"{lang}"' for lang in LANGS)
    for i in range(0, len(qids), 250):
        values = " ".join(f"wd:{q}" for q in qids[i : i + 250])
        for r in client.sparql(
            f"""SELECT ?player ?dob ?prec WHERE {{
                  VALUES ?player {{ {values} }}
                  ?player p:P569/psv:P569 ?node .
                  ?node wikibase:timeValue ?dob ; wikibase:timePrecision ?prec .
                }}"""
        ):
            p = people[r["player"].rsplit("/", 1)[1]]
            prec = int(r["prec"])
            # Keep the most precise date if there are several.
            if p.dob_precision is None or prec > p.dob_precision:
                p.dob, p.dob_precision = _date(r["dob"]), prec
        for r in client.sparql(
            f"""SELECT ?player ?name WHERE {{
                  VALUES ?player {{ {values} }}
                  {{ ?player rdfs:label ?name }} UNION {{ ?player skos:altLabel ?name }}
                  FILTER(LANG(?name) IN ({langs}))
                }}"""
        ):
            people[r["player"].rsplit("/", 1)[1]].names.add(r["name"])
        if log and (i // 250) % 20 == 0:
            print(f"wikidata people: {min(i + 250, len(qids))} of {len(qids)}", flush=True)
    return people


# --- provider players -------------------------------------------------------------------------


@dataclass
class ProviderPlayer:
    """One provider's player, with names and the teams and dates they appeared for."""

    provider: str
    player_id: str
    names: list[str]
    display_name: str
    birth_date: dt.date | None = None
    appearances: list[tuple[str, dt.date, dt.date]] = field(default_factory=list)


def provider_players(con: Any) -> list[ProviderPlayer]:
    """StatsBomb players who played, Wyscout lineup players, and DFL match-sheet players."""
    team_q = {
        (p, t): q
        for p, t, q in con.execute(
            "select provider, team_id, qid from team_wikidata where qid is not null"
        ).fetchall()
    }
    out: dict[tuple[str, str], ProviderPlayer] = {}
    for pid, name, nick in con.execute(
        """select p.player_id, p.player_name, p.player_nickname from players p
           where p.player_id in (select player_id from player_match_minutes)"""
    ).fetchall():
        out[("statsbomb", str(pid))] = ProviderPlayer(
            "statsbomb", str(pid), [nick, name], nick or name
        )
    for pid, team, first, last in con.execute(
        """select m.player_id, m.team_id, min(x.match_date), max(x.match_date)
           from player_match_minutes m join matches x using (match_id) group by 1, 2"""
    ).fetchall():
        q = team_q.get(("statsbomb", str(team)))
        if q and ("statsbomb", str(pid)) in out:
            out[("statsbomb", str(pid))].appearances.append((q, first, last))
    wy_names = {
        pid: (short, first, mid, last, bd)
        for pid, short, first, mid, last, bd in con.execute(
            "select player_id, short_name, first_name, middle_name, last_name, birth_date "
            "from wy_players"
        ).fetchall()
    }
    for pid, team, first, last in con.execute(
        """select l.player_id, l.team_id, min(m.date_utc)::date, max(m.date_utc)::date
           from wy_lineups l join wy_matches m using (match_id) group by 1, 2"""
    ).fetchall():
        key = ("wyscout", str(pid))
        if key not in out:
            short, fn, mid, ln, bd = wy_names.get(pid, (None, None, None, None, None))
            full = " ".join(x for x in (fn, mid, ln) if x)
            out[key] = ProviderPlayer(
                "wyscout",
                str(pid),
                [short, full, f"{fn} {ln}" if fn and ln else None],
                short or full or str(pid),
                bd,
            )
        q = team_q.get(("wyscout", str(team)))
        if q:
            out[key].appearances.append((q, first, last))
    for pid, team, fn, ln, date in con.execute(
        """select l.player_id, l.team_id, any_value(l.first_name), any_value(l.last_name),
                  min(m.match_date)
           from dfl_lineups l join tracking_meta m using (match_id) group by 1, 2"""
    ).fetchall():
        key = ("dfl", pid)
        name = " ".join(x for x in (fn, ln) if x)
        if key not in out:
            out[key] = ProviderPlayer("dfl", pid, [name], name)
        q = team_q.get(("dfl", team))
        if q:
            out[key].appearances.append((q, date, date))
    return list(out.values())


def _overlaps(start: dt.date | None, end: dt.date | None, first: dt.date, last: dt.date) -> bool:
    slack = dt.timedelta(days=SLACK_DAYS)
    return (start is None or start <= last + slack) and (end is None or end >= first - slack)


def match_player(pp: ProviderPlayer, by_team: dict[str, list[Person]]) -> dict[str, Any]:
    """Pick the Wikidata person for one provider player, or explain why not."""
    scores: dict[str, dict[str, Any]] = {}
    for team, first, last in pp.appearances:
        for person in by_team.get(team, []):
            s = scores.get(person.qid)
            if s is None:
                ns = name_score(pp.names, person.names)
                if ns < 0.5:
                    continue
                s = scores[person.qid] = {"person": person, "name": ns, "teams": 0, "dated": 0}
            mships = [m for m in person.memberships if m[0] == team]
            if any(_overlaps(m[1], m[2], first, last) for m in mships):
                s["teams"] += 1
                s["dated"] += any(m[1] is not None and m[2] is not None for m in mships)
    candidates = []
    for s in scores.values():
        p = s["person"]
        if s["teams"] == 0:
            continue
        dob_check = None
        if pp.birth_date and p.dob and p.dob_precision and p.dob_precision >= 11:
            dob_check = abs((pp.birth_date - p.dob).days) <= 1
            if not dob_check:
                continue  # a contradicting birth date rules the candidate out
        bonus = 0.15 if dob_check else 0.0
        candidates.append((s["name"] + bonus, s["teams"], s, dob_check))
    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
    result: dict[str, Any] = {"qid": None, "status": "unmatched", "n_candidates": len(candidates)}
    if not candidates:
        return result
    top = candidates[0]
    runner = candidates[1] if len(candidates) > 1 else None
    if top[0] < LINK_SCORE:
        result["status"] = "weak name match"
        return result
    if runner and runner[0] > top[0] - MARGIN and runner[1] >= top[1]:
        result["status"] = "ambiguous"
        return result
    s, dob_check = top[2], top[3]
    high = (s["name"] >= 0.9 and (dob_check or s["teams"] >= 2 or s["dated"] >= 1)) or (
        dob_check is True and s["name"] >= 0.8
    )
    return {
        "qid": s["person"].qid,
        "status": "linked",
        "confidence": "high" if high else "medium",
        "name_score": s["name"],
        "team_support": s["teams"],
        "dob_agrees": dob_check,
        "n_candidates": len(candidates),
    }


# --- second pass: name search for players the squads didn't cover ----------------------------

FOOTBALLER = "Q937857"


def _search_name(pp: ProviderPlayer) -> str | None:
    """Return the name to search for: the first name that isn't just an initial."""
    for n in pp.names:
        if n and not re.match(r"^\w\.\s", n):
            return n
    return pp.names[0] if pp.names else None


def fallback(
    client: Client,
    players: list[ProviderPlayer],
    team_country: dict[str, str],
    log: bool = True,
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Person]]:
    """Search Wikidata by name for unmatched players; link only with independent evidence.

    - high: name match (>= 0.9), a footballer, and the Wyscout birth date agrees;
    - medium: name match (>= 0.9), a footballer, and their citizenship or sporting nationality
      is the country of the national team they played for;
    - low: exact name, the only footballer the search finds, and a plausible age (15-45).
      Low links join identities but are never used to verify an age.
    """
    found: dict[tuple[str, str], list[str]] = {}
    for i, pp in enumerate(players):
        text = _search_name(pp)
        if text:
            found[(pp.provider, pp.player_id)] = [c["id"] for c in client.search(text, limit=10)]
        if log and (i + 1) % 200 == 0:
            print(f"name search: {i + 1} of {len(players)}", flush=True)
    qids = sorted({q for v in found.values() for q in v})
    info: dict[str, dict[str, Any]] = {
        q: {"names": set(), "footballer": False, "dob": None, "prec": None, "countries": set()}
        for q in qids
    }
    langs = ", ".join(f'"{lang}"' for lang in LANGS)
    for i in range(0, len(qids), 250):
        values = " ".join(f"wd:{q}" for q in qids[i : i + 250])
        for r in client.sparql(
            f"SELECT ?p WHERE {{ VALUES ?p {{ {values} }} ?p wdt:P106 wd:{FOOTBALLER} }}"
        ):
            info[r["p"].rsplit("/", 1)[1]]["footballer"] = True
        for r in client.sparql(
            f"""SELECT ?p ?c WHERE {{ VALUES ?p {{ {values} }}
                  {{ ?p wdt:P27 ?c }} UNION {{ ?p wdt:P1532 ?c }} }}"""
        ):
            info[r["p"].rsplit("/", 1)[1]]["countries"].add(r["c"].rsplit("/", 1)[1])
        for r in client.sparql(
            f"""SELECT ?p ?dob ?prec WHERE {{ VALUES ?p {{ {values} }}
                  ?p p:P569/psv:P569 ?node .
                  ?node wikibase:timeValue ?dob ; wikibase:timePrecision ?prec . }}"""
        ):
            d = info[r["p"].rsplit("/", 1)[1]]
            if d["prec"] is None or int(r["prec"]) > d["prec"]:
                d["dob"], d["prec"] = _date(r["dob"]), int(r["prec"])
        for r in client.sparql(
            f"""SELECT ?p ?name WHERE {{ VALUES ?p {{ {values} }}
                  {{ ?p rdfs:label ?name }} UNION {{ ?p skos:altLabel ?name }}
                  FILTER(LANG(?name) IN ({langs})) }}"""
        ):
            info[r["p"].rsplit("/", 1)[1]]["names"].add(r["name"])
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for pp in players:
        key = (pp.provider, pp.player_id)
        countries = {team_country[t] for t, _, _ in pp.appearances if t in team_country}
        first = min((a[1] for a in pp.appearances), default=None)
        tiers: dict[str, list[tuple[str, float]]] = {"high": [], "medium": [], "low": []}
        footballers = []
        for q in found.get(key, []):
            d = info[q]
            if not d["footballer"]:
                continue
            ns = name_score(pp.names, d["names"])
            if ns < 0.9:
                continue
            footballers.append(q)
            exact_dob = d["dob"] is not None and (d["prec"] or 0) >= 11
            if pp.birth_date and exact_dob:
                if abs((pp.birth_date - d["dob"]).days) <= 1:
                    tiers["high"].append((q, ns))
                continue  # a contradicting birth date rules the candidate out
            if countries and d["countries"] & countries:
                tiers["medium"].append((q, ns))
            elif ns == 1.0 and d["dob"] and first:
                age = (first - d["dob"]).days / 365.25
                if 15 <= age <= 45:
                    tiers["low"].append((q, ns))
        for conf in ("high", "medium", "low"):
            cands = tiers[conf]
            if conf == "low" and len(footballers) != 1:
                break
            if len(cands) == 1:
                out[key] = {
                    "qid": cands[0][0],
                    "confidence": conf,
                    "name_score": cands[0][1],
                    "dob_agrees": True if conf == "high" else None,
                }
                break
            if len(cands) > 1:
                break  # ambiguous at the strongest tier with evidence: don't guess
    linked = {
        link["qid"]: Person(
            link["qid"],
            info[link["qid"]]["names"],
            info[link["qid"]]["dob"],
            info[link["qid"]]["prec"],
            [],
        )
        for link in out.values()
    }
    return out, linked


def national_team_countries(client: Client, con: Any) -> dict[str, str]:
    """Map each national-team item to its country.

    ``P1532`` (country for sport) wins over ``P17`` (country); ties go to the smallest item
    id, so reruns agree.
    """
    qids = sorted(
        q
        for (q,) in con.execute(
            "select distinct qid from team_wikidata where kind = 'national' and qid is not null"
        ).fetchall()
    )
    found: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"P1532": set(), "P17": set()})
    for i in range(0, len(qids), 100):
        values = " ".join(f"wd:{q}" for q in qids[i : i + 100])
        for r in client.sparql(
            f"""SELECT ?t ?prop ?c WHERE {{ VALUES ?t {{ {values} }}
                  {{ ?t wdt:P1532 ?c BIND("P1532" AS ?prop) }}
                  UNION {{ ?t wdt:P17 ?c BIND("P17" AS ?prop) }} }}"""
        ):
            found[r["t"].rsplit("/", 1)[1]][r["prop"]].add(r["c"].rsplit("/", 1)[1])
    out = {}
    for team, props in found.items():
        pick = props["P1532"] or props["P17"]
        if pick:
            out[team] = min(pick, key=lambda q: int(q[1:]))
    return out


# --- same-match evidence (2018 World Cup) -----------------------------------------------------


def same_match_pairs(con: Any) -> list[dict[str, Any]]:
    """Pair StatsBomb and Wyscout players within each linked match and team."""
    sb = defaultdict(list)
    for mid, team, pid, name, nick, mins in con.execute(
        """select m.match_id, m.team_id, m.player_id, p.player_name, p.player_nickname, m.minutes
           from player_match_minutes m join players p using (player_id)
           where m.match_id in (select sb_match_id from match_xref)"""
    ).fetchall():
        sb[(mid, team)].append((str(pid), [nick, name], mins))
    wy = defaultdict(list)
    for mid, team, pid, short, fn, ln, status, sub_in, sub_out in con.execute(
        """select l.match_id, l.team_id, l.player_id, p.short_name, p.first_name, p.last_name,
                  l.status, l.sub_in_minute, l.sub_out_minute
           from wy_lineups l left join wy_players p using (player_id)
           where l.match_id in (select wy_match_id from match_xref)"""
    ).fetchall():
        if status == "bench" and sub_in is None:
            continue
        start = 0 if status == "lineup" else sub_in
        end = sub_out if sub_out is not None else 90
        wy[(mid, team)].append((str(pid), [short, f"{fn} {ln}"], max(end - start, 0)))
    pairs = []
    for sb_mid, wy_mid, sbh, sba, wyh, wya in con.execute(
        """select sb_match_id, wy_match_id, sb_home_team_id, sb_away_team_id,
                  wy_team_for_sb_home, wy_team_for_sb_away from match_xref"""
    ).fetchall():
        for sb_team, wy_team in ((sbh, wyh), (sba, wya)):
            opts = []
            for sid, snames, smin in sb[(sb_mid, sb_team)]:
                for wid, wnames, wmin in wy[(wy_mid, wy_team)]:
                    ns = max(
                        name_score(snames, set(w for w in wnames if w)),
                        name_score([w for w in wnames if w], set(s for s in snames if s)),
                    )
                    gap = abs(smin - wmin)
                    if ns >= 0.5:
                        opts.append((ns, -gap, sid, wid, gap))
            opts.sort(reverse=True)
            used_s, used_w = set(), set()
            for ns, _, sid, wid, gap in opts:
                if sid in used_s or wid in used_w:
                    continue
                if ns >= 0.85 or (ns >= 0.5 and gap <= 10):
                    used_s.add(sid)
                    used_w.add(wid)
                    pairs.append(
                        {
                            "sb": sid,
                            "wy": wid,
                            "name": ns,
                            "minutes_gap": gap,
                            "sb_match_id": sb_mid,
                        }
                    )
    return pairs


# --- the person graph -------------------------------------------------------------------------


class _UF:
    def __init__(self) -> None:
        self.parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(self, x: tuple[str, str]) -> tuple[str, str]:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: tuple[str, str], b: tuple[str, str]) -> None:
        self.parent[self.find(a)] = self.find(b)


def build(parquet: Path, client: Client | None = None, log: bool = True) -> dict[str, Any]:
    """Link every provider player; write ``player_xref`` and ``wikidata_people``."""
    client = client or Client()
    con = store.connect()
    store.create_views(con, parquet)
    team_qids = sorted(
        {
            q
            for (q,) in con.execute(
                "select distinct qid from team_wikidata where qid is not null"
            ).fetchall()
        }
    )
    people = fetch_people(client, team_qids, log=log)
    by_team: dict[str, list[Person]] = defaultdict(list)
    for p in people.values():
        for team in {m[0] for m in p.memberships}:
            by_team[team].append(p)
    players = provider_players(con)
    results = {(pp.provider, pp.player_id): match_player(pp, by_team) for pp in players}
    unmatched = [pp for pp in players if results[(pp.provider, pp.player_id)]["qid"] is None]
    second, found_people = fallback(
        client, unmatched, national_team_countries(client, con), log=log
    )
    for q, person in found_people.items():
        people.setdefault(q, person)
    for key, link in second.items():
        results[key] = {
            **results[key],
            **link,
            "status": "linked",
            "pass": "name search",
            "team_support": 0,
        }
    pairs = same_match_pairs(con)
    con.close()

    # Agreement between Wikidata links and same-match pairs.
    both = agree = 0
    for pr in pairs:
        a = results.get(("statsbomb", pr["sb"]), {}).get("qid")
        b = results.get(("wyscout", pr["wy"]), {}).get("qid")
        if a and b:
            both += 1
            agree += a == b
        pr["sb_qid"], pr["wy_qid"] = a, b

    uf = _UF()
    for (prov, pid), r in results.items():
        uf.find((prov, pid))
        # Low-confidence links (name search alone) are recorded but never merged: merging would
        # let the player inherit another record's birth date, and a wrong link could then
        # clear a minor.
        if r["qid"] and r.get("confidence") != "low":
            uf.union((prov, pid), ("wd", r["qid"]))
    conflicts = 0
    for pr in pairs:
        a, b = pr["sb_qid"], pr["wy_qid"]
        if a and b and a != b:
            conflicts += 1  # don't merge two Wikidata items
            continue
        uf.union(("statsbomb", pr["sb"]), ("wyscout", pr["wy"]))
    groups: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for node in list(uf.parent):
        groups[uf.find(node)].append(node)
    person_of: dict[tuple[str, str], tuple[str, str | None]] = {}
    for nodes in groups.values():
        qids = sorted(n[1] for n in nodes if n[0] == "wd")
        members = sorted(n for n in nodes if n[0] != "wd")
        if not members:
            continue
        pid = f"wd:{qids[0]}" if len(qids) == 1 else f"{members[0][0]}:{members[0][1]}"
        for m in members:
            person_of[m] = (pid, qids[0] if len(qids) == 1 else None)

    pair_of = {("statsbomb", p["sb"]): p for p in pairs} | {("wyscout", p["wy"]): p for p in pairs}
    rows = []
    for pp in players:
        key = (pp.provider, pp.player_id)
        r = results[key]
        person_id, qid = person_of[key]
        via_pair = r["qid"] is None and qid is not None
        if r["qid"] and r.get("confidence") == "low":
            qid = r["qid"]  # the candidate, for reference; the person stays unmerged
        if r["qid"] and r.get("pass") == "name search":
            method = {
                "high": "wikidata name search + birth date",
                "medium": "wikidata name search + national-team country",
                "low": "wikidata name search: unique footballer, exact name, plausible age",
            }[r["confidence"]]
        elif r["qid"]:
            method = "wikidata: team + dates + name" + (
                " + birth date" if r.get("dob_agrees") else ""
            )
        else:
            method = "same match (2018 World Cup) with a linked player" if via_pair else None
        pr = pair_of.get(key)
        rows.append(
            {
                "person_id": person_id,
                "provider": pp.provider,
                "provider_player_id": pp.player_id,
                "name": pp.display_name,
                "qid": qid,
                "status": "linked" if qid else r["status"],
                "method": method,
                "confidence": r.get("confidence") if r["qid"] else ("medium" if via_pair else None),
                "name_score": r.get("name_score"),
                "team_support": r.get("team_support"),
                "dob_agrees": r.get("dob_agrees"),
                "n_candidates": r.get("n_candidates"),
                "same_match_partner": (pr["wy"] if pp.provider == "statsbomb" else pr["sb"])
                if pr
                else None,
            }
        )
    wd_rows = [
        {
            "qid": p.qid,
            "label": sorted(p.names, key=len)[0] if p.names else None,
            "birth_date": p.dob,
            "birth_date_precision": p.dob_precision,
            "names": json.dumps(sorted(p.names), ensure_ascii=False),
        }
        for p in people.values()
        if any(r["qid"] == p.qid for r in rows)
    ]
    write_single(parquet / "player_xref.parquet", rows, PLAYER_XREF)
    write_single(parquet / "wikidata_people.parquet", wd_rows, WIKIDATA_PEOPLE)
    return {
        "provider_players": len(rows),
        "linked": sum(r["qid"] is not None for r in rows),
        "wikidata_people_fetched": len(people),
        "same_match_pairs": len(pairs),
        "pairs_both_linked": both,
        "pairs_agree": agree,
        "pairs_conflict": conflicts,
        "wikidata_requests": client.fetched,
    }
