"""Fetch StatsBomb open data: a partial, sparse clone pinned to one commit.

Only the files for the competition-seasons in :mod:`rondo.core.scope` are checked out:
competitions, matches, events and lineups for every match in scope, and 360 frames where
the match has them. ``SOURCE.json`` records the commit and a SHA-256 per file.

Run with ``python -m rondo.core.statsbomb_fetch`` (part of ``make data``).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from rondo.core.paths import statsbomb_raw_dir
from rondo.core.scope import SCOPE, STATSBOMB_COMMIT, STATSBOMB_REPO


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    """Run git in ``repo`` and return stdout; raise on failure."""
    out = subprocess.run(
        ["git", "-C", str(repo), *args], input=stdin, capture_output=True, text=True, check=False
    )
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def scope_match_ids(checkout: Path) -> tuple[list[int], list[int]]:
    """Return (all match ids, match ids with 360 data) for the scope, from matches files."""
    ids: list[int] = []
    ids_360: list[int] = []
    for cs in SCOPE:
        path = checkout / "data" / "matches" / str(cs.competition_id) / f"{cs.season_id}.json"
        for match in json.loads(path.read_text()):
            ids.append(match["match_id"])
            if match.get("match_status_360") == "available":
                ids_360.append(match["match_id"])
    return ids, ids_360


def sparse_patterns(ids: list[int], ids_360: list[int]) -> list[str]:
    """Sparse-checkout patterns for exactly the in-scope files."""
    patterns = ["/data/competitions.json", "/data/matches/"]
    for i in ids:
        patterns += [f"/data/events/{i}.json", f"/data/lineups/{i}.json"]
    patterns += [f"/data/three-sixty/{i}.json" for i in ids_360]
    return patterns


def sha256(path: Path) -> str:
    """SHA-256 of a file, streamed."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(root: Path) -> Path:
    """Clone (if needed), check out the in-scope files at the pinned commit, write SOURCE.json."""
    checkout = root / "open-data"
    root.mkdir(parents=True, exist_ok=True)
    if not (checkout / ".git").exists():
        subprocess.run(
            [
                *("git", "clone", "--filter=blob:none", "--sparse", "--no-checkout", "-q"),
                STATSBOMB_REPO,
                str(checkout),
            ],
            check=True,
        )
    base = ["/data/competitions.json", "/data/matches/"]
    _git(checkout, "sparse-checkout", "set", "--no-cone", *base)
    _git(checkout, "checkout", "-q", "--detach", STATSBOMB_COMMIT)
    ids, ids_360 = scope_match_ids(checkout)
    patterns = sparse_patterns(ids, ids_360)
    print(f"checking out {len(patterns)} paths ({len(ids)} matches, {len(ids_360)} with 360)")
    _git(checkout, "sparse-checkout", "set", "--no-cone", "--stdin", stdin="\n".join(patterns))
    head = _git(checkout, "rev-parse", "HEAD").strip()
    if head != STATSBOMB_COMMIT:
        raise RuntimeError(f"checkout is at {head}, expected {STATSBOMB_COMMIT}")

    files = {}
    for p in sorted((checkout / "data").rglob("*.json")):
        rel = p.relative_to(checkout).as_posix()
        files[rel] = {"bytes": p.stat().st_size, "sha256": sha256(p)}
    source = {
        "provider": "statsbomb",
        "repo": STATSBOMB_REPO,
        "commit": head,
        "fetched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "n_files": len(files),
        "files": files,
    }
    out = root / "SOURCE.json"
    out.write_text(json.dumps(source, indent=1))
    print(f"wrote {out} ({len(files)} files)")
    return out


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=statsbomb_raw_dir())
    args = parser.parse_args(argv)
    fetch(args.root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
