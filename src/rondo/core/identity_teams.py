"""Map every provider team (StatsBomb, Wyscout, DFL) to its Wikidata item.

For each team, Wikidata's entity search is asked for the club's name (or "<country> national
football team" for national teams). The first result that is a men's club or a men's national
team, and isn't a women's, youth or reserve side, is taken. Every mapping records the search
text and the candidates seen, so ``reports/team_wikidata.csv`` can be checked by hand.

Writes ``team_wikidata.parquet``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from rondo.core import store
from rondo.core.parquet_io import write_single
from rondo.core.schemas import TEAM_WIKIDATA
from rondo.core.wikidata import Client

CLUB_TYPES = {"Q476028", "Q103229495"}
NATIONAL_TYPES = {"Q6979593", "Q135408445"}
#: StatsBomb competitions between national teams (World Cup, Euros, Copa América, AFCON).
SB_INTERNATIONAL = {43, 55, 223, 1267}
_EXCLUDE = re.compile(
    r"women|female|féminin|youth|under-?\d|\bu-?\d\d\b|reserve|juvenil|academy|\bB team|"
    r"\bII\b|\sB$|\sB\s",
    re.I,
)


def provider_teams(con: Any) -> list[dict[str, Any]]:
    """Every team in the shared tables, with its kind (club or national)."""
    teams = []
    intl = ", ".join(str(c) for c in SB_INTERNATIONAL)
    for tid, name, national in con.execute(
        f"""select t.team_id, t.team_name,
                   bool_or(m.competition_id in ({intl})) as national
            from teams t join matches m on t.team_id in (m.home_team_id, m.away_team_id)
            group by 1, 2 order by 1"""
    ).fetchall():
        teams.append(
            {
                "provider": "statsbomb",
                "team_id": str(tid),
                "team_name": name,
                "kind": "national" if national else "club",
            }
        )
    for tid, name, kind in con.execute(
        "select team_id, name, type from wy_teams order by 1"
    ).fetchall():
        teams.append(
            {
                "provider": "wyscout",
                "team_id": str(tid),
                "team_name": name,
                "kind": "national" if kind == "national" else "club",
            }
        )
    for tid, name in con.execute(
        "select distinct team_id, team_name from dfl_lineups order by 1"
    ).fetchall():
        teams.append({"provider": "dfl", "team_id": tid, "team_name": name, "kind": "club"})
    return teams


#: Provider spellings that Wikidata's search doesn't resolve on its own.
#: The mapping still requires a men's club or national-team item, so an alias can't force a
#: wrong type. Reviewed in reports/team_wikidata.csv.
SEARCH_ALIASES = {
    "Cape Verde Islands": "Cape Verde",
    "Almería": "UD Almería",
    "Bochum": "VfL Bochum",
    "Caen": "Stade Malherbe Caen",
    "Cincinnati": "FC Cincinnati",
    "Freiburg": "SC Freiburg",
    "Ingolstadt": "FC Ingolstadt 04",
    "Köln": "1. FC Köln",
    "Nice": "OGC Nice",
    "Roma": "AS Roma",
    "Stuttgart": "VfB Stuttgart",
    "Tenerife": "CD Tenerife",
}


def search_texts(team: dict[str, Any]) -> list[str]:
    """Return the texts to search Wikidata for, most specific first."""
    name = SEARCH_ALIASES.get(team["team_name"], team["team_name"])
    if team["kind"] == "national":
        return [f"{name} national football team", f"{name} men's national football team"]
    return [name, f"{name} football club", f"{name} FC", f"{name} CF"]


def types_of(client: Client, qids: list[str]) -> dict[str, set[str]]:
    """``P31`` types for each item (one SPARQL query per 50 items)."""
    out: dict[str, set[str]] = {q: set() for q in qids}
    for i in range(0, len(qids), 50):
        values = " ".join(f"wd:{q}" for q in qids[i : i + 50])
        for r in client.sparql(
            f"SELECT ?item ?type WHERE {{ VALUES ?item {{ {values} }} ?item wdt:P31 ?type }}"
        ):
            out[r["item"].rsplit("/", 1)[1]].add(r["type"].rsplit("/", 1)[1])
    return out


def build(parquet: Path, client: Client | None = None, log: bool = True) -> dict[str, int]:
    """Map every provider team; write ``team_wikidata.parquet``."""
    client = client or Client()
    con = store.connect()
    store.create_views(con, parquet)
    teams = provider_teams(con)
    con.close()

    def pick(text: str, kind: str) -> tuple[dict[str, Any] | None, int | None]:
        wanted = NATIONAL_TYPES if kind == "national" else CLUB_TYPES
        for r, c in enumerate(searches[text]):
            label, desc = c.get("label") or "", c.get("description") or ""
            if types.get(c["id"], set()) & wanted and not _EXCLUDE.search(f"{label} {desc}"):
                return c, r
        return None, None

    searches: dict[str, list[dict[str, Any]]] = {}
    types: dict[str, set[str]] = {}
    rows = []
    for i, t in enumerate(teams):
        chosen = rank = used = None
        for text in search_texts(t):
            if text not in searches:
                searches[text] = client.search(text)
                new = [c["id"] for c in searches[text] if c["id"] not in types]
                types.update(types_of(client, new) if new else {})
            chosen, rank = pick(text, t["kind"])
            used = text
            if chosen:
                break
        rows.append(
            {
                **t,
                "qid": chosen["id"] if chosen else None,
                "qid_label": chosen.get("label") if chosen else None,
                "qid_description": chosen.get("description") if chosen else None,
                "search_text": used,
                "rank": rank,
                "candidates": "; ".join(
                    f"{c['id']} {c.get('label', '')}" for c in searches[used][:5]
                ),
            }
        )
        if log and (i + 1) % 50 == 0:
            print(f"teams: {i + 1} of {len(teams)}", flush=True)
    n = write_single(parquet / "team_wikidata.parquet", rows, TEAM_WIKIDATA)
    return {"teams": n, "mapped": sum(r["qid"] is not None for r in rows)}
