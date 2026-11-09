"""Player identity, ages and the minors rule (unit level; no network)."""

import datetime as dt

import pytest

from rondo.core import ages, public, schemas
from rondo.core.identity import Person, ProviderPlayer, match_player, name_score
from rondo.core.parquet_io import write_single

D = dt.date


# --- names and candidates ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("provider", "wikidata", "expected"),
    [
        (["Lionel Andrés Messi Cuccittini"], {"Lionel Messi"}, 0.9),
        (["L. Messi"], {"Lionel Messi"}, 0.85),
        (["K. Mbappé"], {"Kylian Mbappé"}, 0.85),
        (["Neymar"], {"Neymar"}, 1.0),
        (["Thomas Müller"], {"Thomas Muller"}, 1.0),
        (["Sergio Ramos García"], {"Sergio Busquets"}, 0.0),
    ],
)
def test_name_score(provider, wikidata, expected):
    assert name_score(provider, wikidata) == expected


START, END = D(2010, 7, 1), D(2016, 6, 30)


def _person(qid, names, team="Q1", dob=None, start=START, end=END):
    return Person(qid, set(names), dob, 11 if dob else None, [(team, start, end)])


def _player(names, bd=None):
    return ProviderPlayer(
        "wyscout", "1", names, names[0], bd, [("Q1", D(2015, 8, 1), D(2016, 5, 1))]
    )


def test_links_unique_strong_candidate():
    r = match_player(_player(["Jordi Alba"]), {"Q1": [_person("Q10", ["Jordi Alba"])]})
    assert r["qid"] == "Q10" and r["status"] == "linked"


def test_two_equal_candidates_are_ambiguous():
    team = [_person("Q10", ["Jordi Alba"]), _person("Q11", ["Jordi Alba"])]
    r = match_player(_player(["Jordi Alba"]), {"Q1": team})
    assert r["qid"] is None and r["status"] == "ambiguous"


def test_contradicting_birth_date_rules_candidate_out():
    team = [_person("Q10", ["Jordi Alba"], dob=D(1989, 3, 21))]
    r = match_player(_player(["Jordi Alba"], bd=D(1990, 1, 1)), {"Q1": team})
    assert r["qid"] is None


def test_membership_must_overlap_the_season():
    team = [_person("Q10", ["Jordi Alba"], start=D(1990, 1, 1), end=D(1995, 1, 1))]
    assert match_player(_player(["Jordi Alba"]), {"Q1": team})["qid"] is None


# --- ages -------------------------------------------------------------------------------------


def test_status_boundaries():
    start = D(2015, 8, 21)
    assert ages.status(D(1997, 8, 21), D(1997, 8, 21), start) == "verified_adult"  # 18 that day
    assert ages.status(D(1997, 8, 22), D(1997, 8, 22), start) == "minor_during_season"
    assert ages.status(None, None, start) == "unverified"


def test_year_precision_decides_only_when_it_can():
    lo, hi = ages.interval(D(1990, 1, 1), 9)
    assert (lo, hi) == (D(1990, 1, 1), D(1990, 12, 31))
    assert ages.status(lo, hi, D(2015, 8, 1)) == "verified_adult"
    lo, hi = ages.interval(D(1997, 1, 1), 9)
    assert ages.status(lo, hi, D(2015, 8, 1)) == "unverified"  # 18th birthday may fall either side


def test_sources_combine_and_disagree():
    assert (
        ages.combine(
            [("wikidata", D(1990, 5, 1), D(1990, 5, 1)), ("wyscout", D(1990, 5, 2), D(1990, 5, 2))]
        )[3]
        is None
    )  # within a day
    assert (
        ages.combine(
            [("wikidata", D(1990, 5, 1), D(1990, 5, 1)), ("wyscout", D(1991, 5, 1), D(1991, 5, 1))]
        )[3]
        == "sources disagree"
    )
    lo, hi, src, problem = ages.combine(
        [("wikidata", D(1990, 1, 1), D(1990, 12, 31)), ("wyscout", D(1990, 6, 3), D(1990, 6, 3))]
    )
    assert (lo, hi, src, problem) == (D(1990, 6, 3), D(1990, 6, 3), "wikidata+wyscout", None)


# --- display_ok and the scanner ---------------------------------------------------------------


@pytest.fixture
def status_table(tmp_path):
    rows = [
        {"person_id": "adult", "competition_season": "statsbomb:1/1", "status": "verified_adult"},
        {"person_id": "adult", "competition_season": "statsbomb:1/2", "status": "verified_adult"},
        {
            "person_id": "grew_up",
            "competition_season": "statsbomb:1/1",
            "status": "minor_during_season",
        },
        {"person_id": "grew_up", "competition_season": "statsbomb:1/2", "status": "verified_adult"},
        {"person_id": "unknown", "competition_season": "statsbomb:1/2", "status": "unverified"},
    ]
    write_single(tmp_path / "player_age_status.parquet", rows, schemas.PLAYER_AGE_STATUS)
    public._statuses.cache_clear()
    return tmp_path


def test_display_ok(status_table):
    ok = lambda p, cs=None, **kw: public.display_ok(p, cs, parquet=status_table, **kw)  # noqa: E731
    assert ok("adult") and ok("adult", ["statsbomb:1/2"])
    assert not ok("unknown") and not ok("nobody")
    assert not ok("grew_up")  # strict: a minor in any covered season is never named
    assert not ok("grew_up", ["statsbomb:1/2"])
    assert ok("grew_up", ["statsbomb:1/2"], strict=False)  # per-season reading
    assert not ok("grew_up", ["statsbomb:1/1"], strict=False)


def test_scan_finds_whole_names_only(tmp_path):
    (tmp_path / "a.md").write_text("Top scorer: Young Player, then others.")
    (tmp_path / "b.csv").write_text("id,name\n1,Youngplayerson\n")
    (tmp_path / "c.png").write_bytes(b"Young Player")
    hits = public.scan([tmp_path], {"Young Player"})
    assert hits == [(str(tmp_path / "a.md"), "Young Player")]
