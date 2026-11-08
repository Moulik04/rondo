"""``make data``: fetch StatsBomb, build every shared table, then the DuckDB views.

Each step prints its own timing; the whole run is timed by the Makefile.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from rondo.core import minutes, spadl, statsbomb_fetch, statsbomb_ingest, store
from rondo.core.paths import duckdb_path, parquet_dir, statsbomb_raw_dir
from rondo.core.scope import STATSBOMB_COMMIT


def _fetched(root: Path) -> bool:
    src = root / "SOURCE.json"
    if not src.exists():
        return False
    meta = json.loads(src.read_text())
    return meta.get("commit") == STATSBOMB_COMMIT and all(
        (root / "open-data" / path).exists() for path in meta["files"]
    )


def main(argv: list[str] | None = None) -> int:
    """Run the full StatsBomb build."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-spadl", action="store_true", help="skip the slowest step")
    args = parser.parse_args(argv)
    raw, out = statsbomb_raw_dir(), parquet_dir()
    t0 = time.perf_counter()
    if _fetched(raw):
        print("statsbomb: checkout matches SOURCE.json, not fetching")
    else:
        statsbomb_fetch.fetch(raw)
    print(f"[fetch] {time.perf_counter() - t0:.0f}s", flush=True)

    t = time.perf_counter()
    counts = statsbomb_ingest.build(raw / "open-data", out)
    print(f"[ingest] {time.perf_counter() - t:.0f}s {counts}", flush=True)

    t = time.perf_counter()
    print(f"[minutes] {minutes.build(out)} {time.perf_counter() - t:.0f}s", flush=True)

    if not args.skip_spadl:
        t = time.perf_counter()
        n = spadl.build(raw / "open-data", out)
        print(f"[spadl] {n} actions {time.perf_counter() - t:.0f}s", flush=True)

    views = store.build(out, duckdb_path())
    print(f"[duckdb] {duckdb_path()}: {len(views)} views; total {time.perf_counter() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
