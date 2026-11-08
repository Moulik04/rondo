"""Small helpers for writing Parquet tables through fixed schemas."""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

COMPRESSION = "zstd"


def to_table(rows: Iterable[dict[str, Any]], schema: pa.Schema) -> pa.Table:
    """Build a table from row dicts; missing keys become null, extra keys are an error."""
    rows = list(rows)
    names = set(schema.names)
    for r in rows[:1]:
        extra = set(r) - names
        if extra:
            raise ValueError(f"columns not in schema: {sorted(extra)}")
    return pa.Table.from_pylist(rows, schema=schema)


def write_single(path: Path, rows: Iterable[dict[str, Any]], schema: pa.Schema) -> int:
    """Write a whole table to one Parquet file; return the row count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    table = to_table(rows, schema)
    pq.write_table(table, path, compression=COMPRESSION)
    return table.num_rows


def partition_path(root: Path, table: str, **parts: Any) -> Path:
    """Return ``root/table/k=v/.../part-0.parquet`` (Hive-style)."""
    p = root / table
    for k, v in parts.items():
        p = p / f"{k}={v}"
    return p / "part-0.parquet"


class PartitionWriter:
    """Append row batches to one partition file; each batch becomes a row group."""

    def __init__(self, path: Path, schema: pa.Schema) -> None:
        """Prepare a writer for ``path`` (opened on the first batch)."""
        self.path = path
        self.schema = schema
        self.rows_written = 0
        self._writer: pq.ParquetWriter | None = None

    def write(self, rows: list[dict[str, Any]]) -> None:
        """Write one batch of rows (skipped if empty)."""
        if not rows:
            return
        if self._writer is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._writer = pq.ParquetWriter(self.path, self.schema, compression=COMPRESSION)
        self._writer.write_table(to_table(rows, self.schema))
        self.rows_written += len(rows)

    def close(self) -> None:
        """Close the file if one was opened."""
        if self._writer is not None:
            self._writer.close()
            self._writer = None


def reset_dir(path: Path) -> None:
    """Delete and recreate a generated directory."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
