import pytest

from rondo.core import machine


def test_replace_block_swaps_only_the_generated_part():
    text = f"intro\n{machine.BEGIN}\nold\n{machine.END}\noutro\n"
    out = machine.replace_block(text, f"{machine.BEGIN}\nnew\n{machine.END}")
    assert out == f"intro\n{machine.BEGIN}\nnew\n{machine.END}\noutro\n"


def test_replace_block_requires_markers():
    with pytest.raises(ValueError):
        machine.replace_block("no markers here", "x")


def test_render_flags_low_disk():
    info = machine.MachineInfo(
        measured_at="t",
        os="os",
        chip="chip",
        memory_bytes=8 * 2**30,
        disk_total_bytes=200 * 10**9,
        disk_free_bytes=10 * 10**9,
        python="CPython 3.12",
    )
    assert "**below** the 60 GB" in machine.render(info)
    info.disk_free_bytes = 70 * 10**9
    assert "meets the 60 GB" in machine.render(info)
