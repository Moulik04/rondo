"""Convert StatsBomb events to SPADL actions with socceraction, one match at a time.

Output: ``spadl_actions/provider=statsbomb/competition_id=…/season_id=…/part-0.parquet`` in
SPADL's 105 x 68 m frame, with every action turned so its team attacks left to right.
"""

from __future__ import annotations

import time
import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from rondo.core import schemas
from rondo.core.parquet_io import PartitionWriter, partition_path, reset_dir
from rondo.core.scope import SCOPE, CompetitionSeason

BATCH_MATCHES = 20


def _version(v: Any) -> int | None:
    """Return a fidelity version as an int (socceraction needs ints; StatsBomb gives strings)."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def convert_match(loader: Any, match: dict[str, Any]) -> pd.DataFrame:
    """Return one match's SPADL actions (names added, left-to-right per team)."""
    from socceraction import spadl

    events = loader.events(match["match_id"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        actions = spadl.statsbomb.convert_to_actions(
            events,
            home_team_id=match["home_team_id"],
            xy_fidelity_version=_version(match["xy_fidelity_version"]),
            shot_fidelity_version=_version(match["shot_fidelity_version"]),
        )
        actions = spadl.play_left_to_right(actions, match["home_team_id"])
        actions = spadl.add_names(actions)
    return actions


def to_rows(actions: pd.DataFrame, match_id: int) -> list[dict[str, Any]]:
    """Map socceraction's columns onto the spadl_actions schema."""
    out = pd.DataFrame(
        {
            "provider": "statsbomb",
            "match_id": match_id,
            "action_id": actions["action_id"].astype(int),
            # Dribbles socceraction inserts between actions have no source event: keep null.
            "original_event_id": actions["original_event_id"].astype(object),
            "period_id": actions["period_id"].astype(int),
            "time_seconds": actions["time_seconds"].astype(float),
            "team_id": actions["team_id"].astype(int),
            "player_id": actions["player_id"].astype("Int64"),
            "start_x": actions["start_x"],
            "start_y": actions["start_y"],
            "end_x": actions["end_x"],
            "end_y": actions["end_y"],
            "type_id": actions["type_id"].astype(int),
            "result_id": actions["result_id"].astype(int),
            "bodypart_id": actions["bodypart_id"].astype(int),
            "type_name": actions["type_name"],
            "result_name": actions["result_name"],
            "bodypart_name": actions["bodypart_name"],
        }
    )
    rows = out.to_dict("records")
    for r in rows:
        for col in ("player_id", "original_event_id"):
            if pd.isna(r[col]):
                r[col] = None
    return rows


def build(
    checkout: Path,
    parquet: Path,
    scope: Sequence[CompetitionSeason] = SCOPE,
    log: bool = True,
) -> int:
    """Convert every in-scope match; return the number of actions written."""
    from socceraction.data.statsbomb import StatsBombLoader

    loader = StatsBombLoader(getter="local", root=str(checkout / "data"))
    root = parquet / "spadl_actions" / "provider=statsbomb"
    if root.exists():
        reset_dir(root)
    matches = pd.read_parquet(parquet / "matches.parquet")
    total, start = 0, time.perf_counter()
    for cs in scope:
        ms = matches[
            (matches.competition_id == cs.competition_id) & (matches.season_id == cs.season_id)
        ].sort_values("match_id")
        writer = PartitionWriter(
            partition_path(
                parquet / "spadl_actions",
                "provider=statsbomb",
                competition_id=cs.competition_id,
                season_id=cs.season_id,
            ),
            schemas.SPADL_ACTIONS,
        )
        batch: list[dict[str, Any]] = []
        for i, m in enumerate(ms.to_dict("records")):
            batch += to_rows(convert_match(loader, m), m["match_id"])
            if (i + 1) % BATCH_MATCHES == 0:
                writer.write(batch)
                total += len(batch)
                batch = []
        writer.write(batch)
        total += len(batch)
        writer.close()
        if log:
            print(
                f"spadl {cs.competition_id}/{cs.season_id}: {len(ms)} matches "
                f"({total} actions, {time.perf_counter() - start:.0f}s)",
                flush=True,
            )
    return total
