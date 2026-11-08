"""Where Rondo's local data lives. Override the root with ``RONDO_DATA_DIR``."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def data_dir() -> Path:
    """Root of local data: ``$RONDO_DATA_DIR`` if set, else ``<repo>/data``."""
    return Path(os.environ.get("RONDO_DATA_DIR", REPO_ROOT / "data")).resolve()


def statsbomb_raw_dir() -> Path:
    """Return the folder holding the pinned, sparse StatsBomb checkout."""
    return data_dir() / "raw" / "statsbomb"


def parquet_dir() -> Path:
    """Return the shared Parquet folder (read-only for tracks)."""
    return data_dir() / "parquet"


def duckdb_path() -> Path:
    """Return the main session's DuckDB file (tracks never open it)."""
    return data_dir() / "rondo.duckdb"


def reports_dir() -> Path:
    """Return the generated-reports folder (committed)."""
    return REPO_ROOT / "reports"
