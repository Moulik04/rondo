"""Shared test setup.

By default the data tests run on synthetic data built in a temp folder: a StatsBomb tree
(``fixtures/statsbomb_fixture.py``), a Wyscout tree (``fixtures/wyscout_fixture.py``) and
tracking frames written directly below. With ``--real`` (``make test-real``) the same tests run
on the local full data under ``RONDO_DATA_DIR`` (default ``data/``).
"""

import sys
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

import statsbomb_fixture as fx
import wyscout_fixture as wfx

from rondo.core import checks, minutes, schemas, spadl, statsbomb_ingest, store, wyscout_ingest
from rondo.core import scope as sc
from rondo.core.parquet_io import PartitionWriter, partition_path, write_single
from rondo.core.paths import parquet_dir, statsbomb_raw_dir

TRACK_MATCH = "FIX001"


def pytest_addoption(parser):
    parser.addoption("--real", action="store_true", help="run data tests on the full local data")


def pytest_collection_modifyitems(config, items):
    real = config.getoption("--real")
    for item in items:
        if "real" in item.keywords and not real:
            item.add_marker(pytest.mark.skip(reason="needs --real (make test-real)"))
        if "synthetic_only" in item.keywords and real:
            item.add_marker(pytest.mark.skip(reason="synthetic fixture only"))


@dataclass
class Store:
    parquet: Path
    checkout: Path
    con: object
    scope: tuple
    real: bool

    def ctx(self):
        return checks.Ctx(self.con, self.checkout, scope=self.scope, check_section_2=self.real)


def write_synthetic_tracking(parquet: Path, frames_per_period: int = 100) -> None:
    """One match, two periods at 25 Hz: 22 players walking slowly, plus the ball."""
    cols = {name: [] for name in schemas.TRACKING_FRAMES.names}
    meta = []
    for period, first in ((1, 10_000), (2, 100_000)):
        for i in range(frames_per_period):
            frame, t = first + i, i / 25
            objects = [("ball", None, None, 0.0, 0.0, 0.2)]
            for k in range(22):
                team = "HOME" if k < 11 else "AWAY"
                objects.append((f"P{k:02d}", team, k % 11 + 1, -40 + 4 * k + 0.05 * i, 0.0, None))
            for obj, team, jersey, x, y, z in objects:
                for name, v in (
                    ("provider", "dfl"),
                    ("match_id", TRACK_MATCH),
                    ("period", period),
                    ("frame", frame),
                    ("time_s", t),
                    ("object_id", obj),
                    ("team_id", team),
                    ("jersey_no", jersey),
                    ("x", x),
                    ("y", y),
                    ("z", z),
                    ("provider_speed", None),
                    ("ball_alive", True),
                    ("ball_owning_team_id", "HOME"),
                ):
                    cols[name].append(v)
        meta.append(
            {
                "provider": "dfl",
                "match_id": TRACK_MATCH,
                "home_team_id": "HOME",
                "away_team_id": "AWAY",
                "pitch_length": 105.0,
                "pitch_width": 68.0,
                "frame_rate": 25.0,
                "period": period,
                "first_frame": first,
                "last_frame": first + frames_per_period - 1,
                "n_frames": frames_per_period,
                "start_s": 0.0,
                "end_s": (frames_per_period - 1) / 25,
                "home_attacks": "right",
            }
        )
    w = PartitionWriter(
        partition_path(parquet, "tracking_frames", provider="dfl", match_id=TRACK_MATCH),
        schemas.TRACKING_FRAMES,
    )
    w.write_arrow(pa.table(cols, schema=schemas.TRACKING_FRAMES))
    w.close()
    write_single(parquet / "tracking_meta.parquet", meta, schemas.TRACKING_META)


@pytest.fixture(scope="session")
def sb_store(request, tmp_path_factory):
    """Built shared tables plus a DuckDB connection with views over them."""
    if request.config.getoption("--real"):
        parquet, checkout, scope, real = (
            parquet_dir(),
            statsbomb_raw_dir() / "open-data",
            sc.SCOPE,
            True,
        )
    else:
        root = tmp_path_factory.mktemp("data")
        checkout = fx.write(root)
        parquet = root / "parquet"
        scope, real = fx.FIXTURE_SCOPE, False
        statsbomb_ingest.build(checkout, parquet, scope=scope, log=False)
        minutes.build(parquet)
        spadl.build(checkout, parquet, scope=scope, log=False)
        wyscout_ingest.build(
            wfx.write(root / "wyscout"), parquet, competitions=wfx.COMPETITIONS, log=False
        )
        write_synthetic_tracking(parquet)
    con = store.connect()
    store.create_views(con, parquet)
    yield Store(parquet, checkout, con, scope, real)
    con.close()
