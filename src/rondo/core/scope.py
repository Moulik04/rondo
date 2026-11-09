"""Which StatsBomb competition-seasons Rondo covers.

Men's matches from 2003/04 on. ``core`` feeds both products; ``extra`` is used only for
training variants and tournament profiles. Everything else (including the older one-off
historical matches) is out of scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Scope = Literal["core", "extra"]

#: The StatsBomb open-data commit Rondo is pinned to.
STATSBOMB_COMMIT = "4b73468fc5b0f1950f9f66fada70ad3a4f9327cb"
STATSBOMB_REPO = "https://github.com/statsbomb/open-data.git"


@dataclass(frozen=True)
class CompetitionSeason:
    """One StatsBomb competition-season in scope, with its expected counts."""

    competition_id: int
    season_id: int
    scope: Scope
    group: str
    expected_matches: int | None
    expected_matches_360: int | None


def _cs(
    competition_id: int, season_id: int, scope: Scope, group: str, n: int | None, n360: int | None
) -> CompetitionSeason:
    return CompetitionSeason(competition_id, season_id, scope, group, n, n360)


# Barcelona's La Liga seasons from 2004/05 to 2020/21. The source gives only the group total
# (486 matches, 35 with 360 frames, all in 2020/21), so the check runs at group level.
_BARCELONA_SEASONS = [37, 38, 39, 40, 41, 21, 22, 23, 24, 25, 26, 2, 1, 4, 42, 90]
_UCL_FINAL_SEASONS = [44, 37, 39, 41, 21, 22, 23, 24, 25, 26, 27, 2, 1, 4]

SCOPE: tuple[CompetitionSeason, ...] = (
    _cs(11, 27, "core", "full season", 380, 0),
    _cs(2, 27, "core", "full season", 380, 0),
    _cs(12, 27, "core", "full season", 380, 0),
    _cs(7, 27, "core", "full season", 377, 0),
    _cs(9, 27, "core", "one team: Leverkusen", 34, 0),
    _cs(9, 281, "core", "one team: Leverkusen", 34, 34),
    *(_cs(11, s, "core", "one team: Barcelona", None, None) for s in _BARCELONA_SEASONS),
    _cs(7, 108, "core", "one team: Paris Saint-Germain", 26, 26),
    _cs(7, 235, "core", "one team: Paris Saint-Germain", 32, 32),
    _cs(2, 44, "core", "one team: Arsenal", 38, 0),
    *(_cs(16, s, "core", "Champions League final", 1, 0) for s in _UCL_FINAL_SEASONS),
    _cs(43, 3, "core", "tournament", 64, 0),
    _cs(43, 106, "core", "tournament", 64, 64),
    _cs(55, 43, "core", "tournament", 51, 51),
    _cs(55, 282, "core", "tournament", 51, 51),
    _cs(223, 282, "extra", "tournament", 32, 0),
    _cs(1267, 107, "extra", "tournament", 52, 1),
    _cs(1238, 108, "extra", "full season", 115, 0),
    _cs(44, 107, "extra", "one team: Inter Miami", 6, 6),
)

#: Expected group totals where there is no per-season count.
EXPECTED_GROUP_TOTALS: dict[str, tuple[int, int]] = {"one team: Barcelona": (486, 35)}

#: Expected totals.
EXPECTED_TOTAL_MATCHES = 2616
EXPECTED_TOTAL_360 = 300
EXPECTED_CORE_MATCHES = 2411
EXPECTED_CORE_360 = 293


def scope_of(competition_id: int, season_id: int) -> Scope | None:
    """Return 'core' or 'extra' for a competition-season in scope, else None."""
    for cs in SCOPE:
        if (cs.competition_id, cs.season_id) == (competition_id, season_id):
            return cs.scope
    return None
