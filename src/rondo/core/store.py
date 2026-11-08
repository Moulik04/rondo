"""DuckDB views over the shared Parquet files (the main session's ``rondo.duckdb``).

Views, not copies: the Parquet files stay the single source of truth, and the database file
stays small. Tracks build their own DuckDB files the same way and never open this one.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from rondo.core import schemas

#: Default memory cap for DuckDB on the 8 GB Mac.
MEMORY_LIMIT = "3GB"


def connect(db: Path | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection with Rondo's memory cap."""
    con = duckdb.connect(str(db) if db else ":memory:", read_only=read_only)
    con.execute(f"SET memory_limit = '{MEMORY_LIMIT}'")
    return con


def source(parquet: Path, table: str) -> str:
    """Return the SQL table expression that reads one shared table's Parquet files."""
    if table in schemas.SINGLE:
        return f"read_parquet('{parquet / f'{table}.parquet'}')"
    return f"read_parquet('{parquet / table}/**/*.parquet', hive_partitioning = true)"


def create_views(con: duckdb.DuckDBPyConnection, parquet: Path) -> list[str]:
    """Create (or replace) one view per table that exists under ``parquet``."""
    made = []
    for table in schemas.ALL:
        path = parquet / (f"{table}.parquet" if table in schemas.SINGLE else table)
        if path.exists():
            con.execute(f"CREATE OR REPLACE VIEW {table} AS SELECT * FROM {source(parquet, table)}")
            made.append(table)
    return made


def build(parquet: Path, db: Path) -> list[str]:
    """(Re)create ``db`` with views over every table in ``parquet``."""
    if db.exists():
        db.unlink()
    con = connect(db)
    try:
        return create_views(con, parquet)
    finally:
        con.close()
