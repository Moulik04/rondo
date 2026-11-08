"""GPU run records, the GPU ledger and test-evaluation logs.

Every run writes ``runs/<run_id>/`` with ``config.yaml``, ``git_sha``, ``env.txt``,
``train_log.csv``, ``metrics.json`` (validation only), ``model.pt`` and ``run.json`` (what
the ledger reads). MJ copies run folders back to ``data/runs/<track>/``; ``make report``
builds ``reports/gpu_ledger.md`` from them against the budgets in ``jobs/core/budget.yaml``.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import platform
import subprocess
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

#: Service units charged per GPU-hour, by GPU type.
SU_PER_GPU_HOUR = {"V100": 1.0, "H100": 2.0, "cpu": 0.0, "mps": 0.0}


def config_hash(config: dict[str, Any]) -> str:
    """Short, stable hash of a config (key order doesn't matter)."""
    blob = json.dumps(config, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def git_sha(repo: Path | None = None) -> str:
    """Return the current commit, or 'unknown' outside a git checkout (e.g. in a bundle)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return out.stdout.strip()


def gpu_type() -> str:
    """'V100', 'H100', another CUDA device name, 'mps' or 'cpu'."""
    import torch

    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        for known in ("V100", "H100"):
            if known in name:
                return known
        return name
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def collect_env() -> str:
    """Describe the environment: GPU, driver, Python, PyTorch, CUDA and PyG versions."""
    import torch

    lines = [
        f"python: {platform.python_version()}",
        f"platform: {platform.platform()}",
        f"torch: {torch.__version__}",
        f"cuda (torch build): {torch.version.cuda}",
        f"cuda available: {torch.cuda.is_available()}",
    ]
    try:
        import torch_geometric

        lines.append(f"torch_geometric: {torch_geometric.__version__}")
    except ImportError:
        lines.append("torch_geometric: not installed")
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        lines += [
            f"gpu: {props.name}",
            f"gpu memory: {props.total_memory / 2**30:.1f} GiB",
            f"compute capability: {props.major}.{props.minor}",
            f"arch list: {' '.join(torch.cuda.get_arch_list())}",
            f"cudnn: {torch.backends.cudnn.version()}",
        ]
        try:
            smi = subprocess.run(
                ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                check=True,
            )
            lines.append(f"driver: {smi.stdout.strip()}")
        except (OSError, subprocess.CalledProcessError):
            lines.append("driver: unknown (nvidia-smi unavailable)")
    else:
        lines.append(f"gpu: {gpu_type()}")
    return "\n".join(lines) + "\n"


@dataclass
class RunRecord:
    """What the ledger needs about one run (``run.json``)."""

    run_id: str
    track: str
    model: str
    config_hash: str
    git_sha: str
    gpu_type: str
    started_at: str
    wall_time_s: float = 0.0
    sus: float = 0.0
    outcome: str = "running"


def start_run(
    runs_root: Path, track: str, model: str, config: dict[str, Any], repo: Path | None = None
) -> tuple[Path, RunRecord]:
    """Create ``runs_root/<run_id>/`` with config, git sha and environment."""
    now = dt.datetime.now(dt.UTC)
    run_id = f"{model}-{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True)
    sha = git_sha(repo)
    (run_dir / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=True))
    (run_dir / "git_sha").write_text(sha + "\n")
    (run_dir / "env.txt").write_text(collect_env())
    record = RunRecord(
        run_id=run_id,
        track=track,
        model=model,
        config_hash=config_hash(config),
        git_sha=sha,
        gpu_type=gpu_type(),
        started_at=now.isoformat(timespec="seconds"),
    )
    (run_dir / "run.json").write_text(json.dumps(asdict(record), indent=1))
    return run_dir, record


def log_train_step(run_dir: Path, row: dict[str, Any]) -> None:
    """Append one row to ``train_log.csv`` (header written on first call)."""
    path = run_dir / "train_log.csv"
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)


def finish_run(
    run_dir: Path, record: RunRecord, wall_time_s: float, outcome: str, metrics: dict[str, Any]
) -> RunRecord:
    """Write validation metrics and the final ``run.json`` (with SUs charged)."""
    if any(k.startswith("test") for k in metrics):
        raise ValueError("metrics.json holds validation metrics only; test results go elsewhere")
    record.wall_time_s = round(wall_time_s, 1)
    record.sus = round(wall_time_s / 3600 * SU_PER_GPU_HOUR.get(record.gpu_type, 1.0), 3)
    record.outcome = outcome
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=1))
    (run_dir / "run.json").write_text(json.dumps(asdict(record), indent=1))
    return record


def append_test_log(evals_dir: Path, track: str, run_id: str, sha: str, split: str) -> Path:
    """Append a test evaluation to ``evals/<track>_TEST_LOG.md``."""
    path = evals_dir / f"{track}_TEST_LOG.md"
    if not path.exists():
        path.write_text(
            f"# {track} test log\n\nOne line per test evaluation.\n\n"
            "| Time (UTC) | Run | Git SHA | Split |\n|---|---|---|---|\n"
        )
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    with path.open("a") as f:
        f.write(f"| {now} | {run_id} | {sha} | {split} |\n")
    return path


def load_runs(runs_root: Path) -> list[RunRecord]:
    """Read every ``run.json`` under ``runs_root`` (any depth)."""
    out = []
    for p in sorted(runs_root.rglob("run.json")):
        out.append(RunRecord(**json.loads(p.read_text())))
    return out


def render_ledger(runs: list[RunRecord], budget: dict[str, Any]) -> str:
    """Render ``reports/gpu_ledger.md``: every run, and SUs used against each track's budget."""
    total = float(budget["total_su"])
    reserve = float(budget["rerun_reserve_fraction"])
    lines = [
        "# GPU ledger",
        "",
        "Generated by `make report` from the run folders under `data/runs/`. Don't edit by hand.",
        "",
        f"Allocation granted to Rondo: {total:g} SU (as of {budget['as_of']}).",
        "",
        "| Track | Share | Budget (SU) | Of which rerun reserve | Used (SU) | Left (SU) |",
        "|---|---|---|---|---|---|",
    ]
    for track, share in budget["split"].items():
        b = total * float(share)
        used = sum(r.sus for r in runs if r.track == track)
        lines.append(
            f"| {track} | {float(share):.0%} | {b:.1f} | {b * reserve:.1f} | {used:.2f} | "
            f"{b - used:.1f} |"
        )
    other = sum(r.sus for r in runs if r.track not in budget["split"])
    lines += [
        "",
        f"Runs outside the track budgets (e.g. the core hello job): {other:.2f} SU.",
        "",
        "| Run | Track | Model | Config hash | Git SHA | GPU | Wall time (s) | SU | Outcome |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in runs:
        lines.append(
            f"| {r.run_id} | {r.track} | {r.model} | {r.config_hash} | {r.git_sha[:7]} | "
            f"{r.gpu_type} | {r.wall_time_s:g} | {r.sus:g} | {r.outcome} |"
        )
    if not runs:
        lines.append("| (no runs yet) | | | | | | | | |")
    return "\n".join(lines) + "\n"
