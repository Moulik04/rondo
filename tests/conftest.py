"""Shared test setup.

By default the data tests run on a synthetic StatsBomb tree built in a temp folder. With
``--real`` (``make test-real``) the same tests run on the local full data under
``RONDO_DATA_DIR`` (default ``data/``).
"""

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

import statsbomb_fixture as fx

from rondo.core import checks, minutes, spadl, statsbomb_ingest, store
from rondo.core import scope as sc
from rondo.core.paths import parquet_dir, statsbomb_raw_dir


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


@pytest.fixture(scope="session")
def sb_store(request, tmp_path_factory):
    """Built StatsBomb tables plus a DuckDB connection with views over them."""
    if request.config.getoption("--real"):
        parquet, checkout, scope, real = (
            parquet_dir(),
            statsbomb_raw_dir() / "open-data",
            sc.SCOPE,
            True,
        )
    else:
        root = tmp_path_factory.mktemp("statsbomb")
        checkout = fx.write(root)
        parquet = root / "parquet"
        scope, real = fx.FIXTURE_SCOPE, False
        statsbomb_ingest.build(checkout, parquet, scope=scope, log=False)
        minutes.build(parquet)
        spadl.build(checkout, parquet, scope=scope, log=False)
    con = store.connect()
    store.create_views(con, parquet)
    yield Store(parquet, checkout, con, scope, real)
    con.close()
