"""CPU smoke test of the GPU stack: the same code later runs on CUDA and MPS."""

import sys

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("torch_geometric")

from rondo.core.machine import tiny_gcn_forward  # noqa: E402


def test_pyg_forward_pass_on_cpu():
    assert tiny_gcn_forward("cpu").startswith("ok, output (4, 3), finite=True")


@pytest.mark.skipif(sys.platform != "darwin", reason="Apple MPS exists only on macOS")
def test_torch_sees_mps_on_mac():
    assert torch.backends.mps.is_available()
