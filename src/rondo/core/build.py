"""``make data``: fetch every source (pinned or checksummed), then build every shared table.

Steps: StatsBomb fetch, ingest, minutes, SPADL; Wyscout fetch, ingest and SPADL; DFL fetch and
tracking load; the World Cup 2018 cross-provider match links; player identity (Wikidata, cached
under data/raw/wikidata/) and age status; DuckDB views. Each step prints
its timing; the Makefile times the whole run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from rondo.core import (
    ages,
    dfl_fetch,
    dfl_ingest,
    identity,
    identity_teams,
    minutes,
    spadl,
    statsbomb_fetch,
    statsbomb_ingest,
    store,
    wyscout_fetch,
    wyscout_ingest,
    xref,
)
from rondo.core.figshare import fetched
from rondo.core.paths import duckdb_path, parquet_dir, statsbomb_raw_dir
from rondo.core.scope import STATSBOMB_COMMIT


def _sb_fetched(root: Path) -> bool:
    src = root / "SOURCE.json"
    if not src.exists():
        return False
    meta = json.loads(src.read_text())
    return meta.get("commit") == STATSBOMB_COMMIT and all(
        (root / "open-data" / path).exists() for path in meta["files"]
    )


def _step(name: str, t: float, detail: object = "") -> float:
    now = time.perf_counter()
    print(f"[{name}] {now - t:.0f}s {detail}".rstrip(), flush=True)
    return now


def main(argv: list[str] | None = None) -> int:
    """Run the full build."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only", choices=["statsbomb", "wyscout", "dfl", "xref", "identity"], default=None
    )
    args = parser.parse_args(argv)
    out = parquet_dir()
    t0 = t = time.perf_counter()
    do = (lambda s: True) if args.only is None else (lambda s: s == args.only)

    if do("statsbomb"):
        raw = statsbomb_raw_dir()
        if not _sb_fetched(raw):
            statsbomb_fetch.fetch(raw)
        t = _step("fetch", t)
        t = _step("ingest", t, statsbomb_ingest.build(raw / "open-data", out))
        t = _step("minutes", t, minutes.build(out))
        t = _step("spadl", t, f"{spadl.build(raw / 'open-data', out)} actions")
    if do("wyscout"):
        raw = wyscout_fetch.wyscout_raw_dir()
        if not fetched(raw):
            wyscout_fetch.fetch(raw)
        t = _step("wyscout_fetch", t)
        t = _step("wyscout", t, wyscout_ingest.build(raw, out))
    if do("dfl"):
        raw = dfl_fetch.dfl_raw_dir()
        if not fetched(raw):
            dfl_fetch.fetch(raw)
        t = _step("dfl_fetch", t)
        t = _step("dfl", t, dfl_ingest.build(raw, out))
    if do("xref"):
        t = _step("xref", t, xref.build(out))
    if do("identity"):
        t = _step("identity_teams", t, identity_teams.build(out, log=False))
        t = _step("identity", t, identity.build(out, log=False))
        t = _step("ages", t, ages.build(out))

    views = store.build(out, duckdb_path())
    print(f"[duckdb] {duckdb_path()}: {len(views)} views; total {time.perf_counter() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
