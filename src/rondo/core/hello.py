"""The hello job: prove the GPU stack works on Bridges-2 before any real training.

Checks CUDA from PyTorch, that the build supports the V100's architecture (sm_70), times a
matrix multiply and a small graph-network pass, and writes a run record like any other run.

On Bridges-2 (via ``jobs/core/hello.sbatch``)::

    python -m rondo.core.hello --runs "$PROJECT/rondo/runs"

On the Mac, the same code on CPU or MPS with small sizes (``make test`` runs it)::

    python -m rondo.core.hello --smoke --runs data/runs/core
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from rondo.core import runs


def _device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _sync(device: str) -> None:
    import torch

    if device == "cuda":
        torch.cuda.synchronize()
    elif device == "mps":
        torch.mps.synchronize()


def time_matmul(device: str, n: int, reps: int, dtype_name: str) -> dict[str, float]:
    """Time an n x n matrix multiply; return milliseconds per multiply and TFLOP/s."""
    import torch

    dtype = getattr(torch, dtype_name)
    a = torch.randn(n, n, device=device, dtype=dtype)
    b = torch.randn(n, n, device=device, dtype=dtype)
    (a @ b).sum().item()  # warm-up
    _sync(device)
    start = time.perf_counter()
    for _ in range(reps):
        c = a @ b
    _sync(device)
    secs = (time.perf_counter() - start) / reps
    assert bool(torch.isfinite(c).all())
    return {"ms": secs * 1000, "tflops": 2 * n**3 / secs / 1e12}


def time_gcn(device: str, n_nodes: int, n_edges: int, reps: int) -> dict[str, float]:
    """Time a two-layer GCN forward and backward pass on a random graph."""
    import torch
    from torch_geometric.nn import GCNConv

    torch.manual_seed(0)
    x = torch.randn(n_nodes, 32, device=device)
    edge_index = torch.randint(0, n_nodes, (2, n_edges), device=device)

    class Net(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.c1, self.c2 = GCNConv(32, 64), GCNConv(64, 8)

        def forward(self, x: Any, ei: Any) -> Any:
            return self.c2(self.c1(x, ei).relu(), ei)

    net = Net().to(device)
    net(x, edge_index).sum().backward()  # warm-up
    _sync(device)
    start = time.perf_counter()
    for _ in range(reps):
        net.zero_grad()
        out = net(x, edge_index)
        out.sum().backward()
    _sync(device)
    assert bool(torch.isfinite(out).all())
    return {"ms": (time.perf_counter() - start) / reps * 1000}


def run(runs_root: Path, smoke: bool) -> dict[str, Any]:
    """Run every check, write the run folder, and return the metrics."""
    import torch

    device = _device()
    if not smoke and device != "cuda":
        raise SystemExit("no CUDA device: run on a GPU node, or pass --smoke")
    config = {"job": "hello", "smoke": smoke, "device": device}
    run_dir, record = runs.start_run(runs_root, "core", "hello", config)
    print((run_dir / "env.txt").read_text(), end="")
    start = time.perf_counter()
    metrics: dict[str, Any] = {"device": device}
    if device == "cuda":
        major, minor = torch.cuda.get_device_capability(0)
        arch = f"sm_{major}{minor}"
        metrics["compute_capability"] = f"{major}.{minor}"
        metrics["arch_supported_by_build"] = arch in torch.cuda.get_arch_list()
        print(f"{arch} in this PyTorch build's arch list: {metrics['arch_supported_by_build']}")
    n, reps = (256, 3) if smoke else (8192, 20)
    metrics["matmul_fp32"] = time_matmul(device, n, reps, "float32")
    if device == "cuda":
        metrics["matmul_fp16"] = time_matmul(device, n, reps, "float16")
    nodes, edges = (1_000, 5_000) if smoke else (200_000, 2_000_000)
    metrics["gcn_forward_backward"] = time_gcn(device, nodes, edges, 3 if smoke else 20)
    for k, v in metrics.items():
        print(f"{k}: {v}")
    runs.finish_run(run_dir, record, time.perf_counter() - start, "ok", metrics)
    print(f"run folder: {run_dir}")
    return metrics


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True, help="folder to write the run into")
    parser.add_argument("--smoke", action="store_true", help="tiny sizes; CPU or MPS allowed")
    args = parser.parse_args(argv)
    run(args.runs, args.smoke)
    return 0


if __name__ == "__main__":
    sys.exit(main())
