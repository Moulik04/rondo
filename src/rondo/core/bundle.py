"""Build a Bridges-2 bundle: ``make gpu-bundle MODEL=<track>/<name> SPLIT=<train|eval>``.

Writes ``dist/gpu/<name>-<split>-<sha7>.tar.zst`` and a ``.sha256`` file next to it.
Contents:

- ``code/``: the committed tree at HEAD (``git archive``), including ``uv.lock``;
- ``data/<table>.parquet``: exactly the tables and columns the model's config names, filtered
  to the split's ids;
- ``split.json`` and ``manifest.json``.

**A training bundle holds only training and validation ids. Test ids travel only in an
evaluation bundle.** The model config (``configs/<track>/<name>.yaml``) names its data::

    data:
      split_file: configs/value/splits/example.yaml  # unit: match_id | player_id
      tables:                                        # train: [...], val: [...], test: [...]
        spadl_actions: [match_id, action_id, type_name, start_x, start_y]

``MODEL=core/hello`` is the hello job: code only, no data.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import yaml
import zstandard

from rondo.core import store
from rondo.core.paths import REPO_ROOT, parquet_dir

UNITS = ("match_id", "player_id")


def _git(*args: str, repo: Path) -> bytes:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True).stdout


def load_split(path: Path) -> dict[str, Any]:
    """Load a split file and check it: a known unit, and disjoint train/val/test ids."""
    split = yaml.safe_load(path.read_text())
    if split.get("unit") not in UNITS:
        raise ValueError(f"{path}: unit must be one of {UNITS}")
    sets = {k: set(split.get(k) or []) for k in ("train", "val", "test")}
    for a, b in (("train", "val"), ("train", "test"), ("val", "test")):
        overlap = sets[a] & sets[b]
        if overlap:
            raise ValueError(f"{path}: {len(overlap)} ids in both {a} and {b}")
    return split


def bundle_ids(split: dict[str, Any], which: str) -> list[int]:
    """Ids a bundle may carry: train + val for a training bundle, test for an evaluation one."""
    if which == "train":
        return sorted({*(split.get("train") or []), *(split.get("val") or [])})
    if which == "eval":
        return sorted(split.get("test") or [])
    raise ValueError("split must be 'train' or 'eval'")


def build_bundle(
    model: str,
    which: str,
    *,
    repo: Path = REPO_ROOT,
    parquet: Path | None = None,
    out_dir: Path | None = None,
    config_path: Path | None = None,
    allow_dirty: bool = False,
) -> Path:
    """Build the bundle and its SHA-256 file; return the bundle path."""
    track, name = model.split("/", 1)
    if not allow_dirty and _git("status", "--porcelain", repo=repo).strip():
        raise SystemExit("working tree has uncommitted changes: commit first (bundles carry HEAD)")
    sha = _git("rev-parse", "HEAD", repo=repo).decode().strip()
    out_dir = out_dir or repo / "dist" / "gpu"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}-{which}-{sha[:7]}.tar.zst"
    manifest: dict[str, Any] = {
        "model": model,
        "split": which,
        "git_sha": sha,
        "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "tables": {},
    }

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        code = stage / "code"
        code.mkdir()
        with tarfile.open(fileobj=io.BytesIO(_git("archive", "HEAD", repo=repo))) as t:
            t.extractall(code, filter="data")
        split_out: dict[str, Any] = {}
        if model != "core/hello":
            cfg_path = config_path or repo / "configs" / track / f"{name}.yaml"
            data_cfg = yaml.safe_load(cfg_path.read_text())["data"]
            split = load_split(repo / data_cfg["split_file"])
            unit, ids = split["unit"], bundle_ids(split, which)
            split_out = {"unit": unit}
            if which == "train":
                split_out |= {"train": split.get("train") or [], "val": split.get("val") or []}
            else:
                split_out |= {"test": split.get("test") or []}
            (stage / "data").mkdir()
            con = store.connect()
            con.execute("create temp table ids (id bigint)")
            con.executemany("insert into ids values (?)", [(i,) for i in ids])
            for table, cols in data_cfg["tables"].items():
                if unit not in cols:
                    raise ValueError(f"{table}: columns must include the split unit {unit!r}")
                src = store.source(parquet or parquet_dir(), table)
                path = stage / "data" / f"{table}.parquet"
                con.execute(
                    f"copy (select {', '.join(cols)} from {src} "
                    f"where {unit} in (select id from ids)) to '{path}' (format parquet)"
                )
                n = con.execute(f"select count(*) from '{path}'").fetchall()[0][0]
                manifest["tables"][table] = {"columns": cols, "rows": n}
            con.close()
        (stage / "split.json").write_text(json.dumps(split_out))
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=1))
        with target.open("wb") as raw:
            cctx = zstandard.ZstdCompressor(level=10, threads=-1)
            with cctx.stream_writer(raw) as zw, tarfile.open(fileobj=zw, mode="w|") as tar:
                for p in sorted(stage.iterdir()):
                    tar.add(p, arcname=p.name)

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (target.parent / f"{target.name}.sha256").write_text(f"{digest}  {target.name}\n")
    return target


def read_bundle(path: Path, dest: Path) -> dict[str, Any]:
    """Extract a bundle into ``dest`` and return its manifest."""
    with (
        path.open("rb") as raw,
        zstandard.ZstdDecompressor().stream_reader(raw) as zr,
        tarfile.open(fileobj=zr, mode="r|") as tar,
    ):
        tar.extractall(dest, filter="data")
    return json.loads((dest / "manifest.json").read_text())


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="<track>/<name>, or core/hello")
    parser.add_argument("--split", required=True, choices=["train", "eval"])
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    path = build_bundle(args.model, args.split, allow_dirty=args.allow_dirty)
    print(f"{path}\n{(path.parent / f'{path.name}.sha256').read_text().strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
