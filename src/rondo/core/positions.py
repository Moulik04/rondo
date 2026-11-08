"""StatsBomb position ids to Rondo's seven position groups (see docs/DATA_CONTRACT.md)."""

from __future__ import annotations

GROUPS = ("GK", "CB", "FB/WB", "DM/CM", "AM", "W", "ST")

POSITION_GROUP: dict[int, str] = {
    1: "GK",
    2: "FB/WB",
    3: "CB",
    4: "CB",
    5: "CB",
    6: "FB/WB",
    7: "FB/WB",
    8: "FB/WB",
    9: "DM/CM",
    10: "DM/CM",
    11: "DM/CM",
    12: "W",
    13: "DM/CM",
    14: "DM/CM",
    15: "DM/CM",
    16: "W",
    17: "W",
    18: "AM",
    19: "AM",
    20: "AM",
    21: "W",
    22: "ST",
    23: "ST",
    24: "ST",
    25: "ST",
}


def position_group(position_id: int | None) -> str | None:
    """Return the group for a StatsBomb position id, or None if unknown."""
    if position_id is None:
        return None
    return POSITION_GROUP.get(position_id)
