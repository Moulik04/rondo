"""Measure the local machine and print its generated Markdown block.

Run with ``python -m rondo.core.machine`` (``make machines``).
Everything in the generated block is measured here; nothing is typed by hand.
"""

from __future__ import annotations

import argparse
import datetime as dt
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

BEGIN = "<!-- BEGIN GENERATED: python -m rondo.core.machine -->"
END = "<!-- END GENERATED -->"

#: Phase 0 asks for at least this much free disk before data work.
MIN_FREE_DISK_GB = 60.0


@dataclass
class TorchCheck:
    """Results of the PyTorch / PyTorch Geometric checks."""

    torch_version: str = "not installed"
    pyg_version: str = "not installed"
    mps_built: bool = False
    mps_available: bool = False
    cuda_available: bool = False
    cpu_forward: str = "not run"
    mps_forward: str = "not run"


@dataclass
class MachineInfo:
    """What was measured, and when."""

    measured_at: str
    os: str
    chip: str
    memory_bytes: int | None
    disk_total_bytes: int
    disk_free_bytes: int
    python: str
    torch: TorchCheck = field(default_factory=TorchCheck)


def _sysctl(key: str) -> str | None:
    """Return a sysctl value on macOS, or None where sysctl is unavailable."""
    try:
        out = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def describe_os() -> str:
    """Return a human-readable OS name and version."""
    mac_version = platform.mac_ver()[0]
    if mac_version:
        build = _sysctl("kern.osversion")
        return f"macOS {mac_version}" + (f" (build {build})" if build else "")
    return f"{platform.system()} {platform.release()}"


def describe_chip() -> str:
    """Return the CPU / SoC name."""
    return _sysctl("machdep.cpu.brand_string") or platform.processor() or platform.machine()


def memory_bytes() -> int | None:
    """Return physical memory in bytes, or None if it cannot be read."""
    value = _sysctl("hw.memsize")
    if value and value.isdigit():
        return int(value)
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def check_torch() -> TorchCheck:
    """Check that PyTorch sees MPS and that PyG runs a tiny forward pass."""
    result = TorchCheck()
    try:
        import torch
    except ImportError:
        return result
    result.torch_version = torch.__version__
    result.mps_built = bool(torch.backends.mps.is_built())
    result.mps_available = bool(torch.backends.mps.is_available())
    result.cuda_available = bool(torch.cuda.is_available())
    try:
        import torch_geometric
    except ImportError:
        return result
    result.pyg_version = torch_geometric.__version__
    result.cpu_forward = tiny_gcn_forward("cpu")
    if result.mps_available:
        result.mps_forward = tiny_gcn_forward("mps")
    return result


def tiny_gcn_forward(device: str) -> str:
    """Run one GCN layer on a 4-node graph and describe the outcome."""
    import torch
    from torch_geometric.data import Data
    from torch_geometric.nn import GCNConv

    torch.manual_seed(0)
    edge_index = torch.tensor([[0, 1, 1, 2, 2, 3], [1, 0, 2, 1, 3, 2]], dtype=torch.long)
    graph = Data(x=torch.randn(4, 2), edge_index=edge_index).to(device)
    layer = GCNConv(2, 3).to(device)
    try:
        start = time.perf_counter()
        out = layer(graph.x, graph.edge_index)
        if device == "mps":
            torch.mps.synchronize()
        elapsed_ms = (time.perf_counter() - start) * 1000
    except Exception as exc:  # report, don't crash: this is a diagnostic
        return f"failed: {type(exc).__name__}: {exc}"
    finite = bool(torch.isfinite(out).all())
    return f"ok, output {tuple(out.shape)}, finite={finite}, {elapsed_ms:.1f} ms"


def measure(root: Path) -> MachineInfo:
    """Measure the machine that hosts ``root``."""
    disk = shutil.disk_usage(root)
    return MachineInfo(
        measured_at=dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC"),
        os=describe_os(),
        chip=describe_chip(),
        memory_bytes=memory_bytes(),
        disk_total_bytes=disk.total,
        disk_free_bytes=disk.free,
        python=f"{platform.python_implementation()} {platform.python_version()}",
        torch=check_torch(),
    )


def _gb(n: int | None) -> str:
    """Format bytes as decimal GB with binary GiB in brackets."""
    if n is None:
        return "unmeasured"
    return f"{n / 1e9:.1f} GB ({n / 2**30:.1f} GiB)"


def render(info: MachineInfo) -> str:
    """Render the generated Markdown block (markers included)."""
    free_gb = info.disk_free_bytes / 1e9
    below = free_gb < MIN_FREE_DISK_GB
    disk_note = (
        f"**below** the {MIN_FREE_DISK_GB:.0f} GB Phase 0 threshold"
        if below
        else f"meets the {MIN_FREE_DISK_GB:.0f} GB Phase 0 threshold"
    )
    t = info.torch
    rows = [
        ("Measured", info.measured_at),
        ("OS", info.os),
        ("Chip", info.chip),
        ("Memory", _gb(info.memory_bytes)),
        ("Disk (volume holding the repo)", f"{_gb(info.disk_total_bytes)} total"),
        ("Disk free", f"{_gb(info.disk_free_bytes)}: {disk_note}"),
        ("Python", info.python),
        ("PyTorch", t.torch_version),
        ("MPS built / available", f"{t.mps_built} / {t.mps_available}"),
        ("CUDA available", str(t.cuda_available)),
        ("PyTorch Geometric", t.pyg_version),
        ("PyG GCN forward pass, CPU", t.cpu_forward),
        ("PyG GCN forward pass, MPS", t.mps_forward),
    ]
    lines = [BEGIN, "", "| Item | Value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    lines += ["", END]
    return "\n".join(lines)


def replace_block(text: str, block: str) -> str:
    """Replace the generated block in ``text``; raise if the markers are missing."""
    start, end = text.find(BEGIN), text.find(END)
    if start == -1 or end == -1 or end < start:
        raise ValueError("generated-block markers not found")
    return text[:start] + block + text[end + len(END) :]


def main(argv: list[str] | None = None) -> int:
    """Print the measured block, or write it into a Markdown file with ``--write``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", type=Path, help="Markdown file whose block to replace")
    args = parser.parse_args(argv)
    root = (args.write.parent if args.write else Path.cwd()).resolve()
    block = render(measure(root))
    if args.write:
        args.write.write_text(replace_block(args.write.read_text(), block))
    print(block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
