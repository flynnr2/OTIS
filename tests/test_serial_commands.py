from __future__ import annotations

import pytest

from host.otis_tools.serial_commands import CommandFifo, parse_serial_command, send_command_to_fifo


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("help", "HELP"),
        ("dac?", "DAC?"),
        ("dac limits?", "DAC LIMITS?"),
        ("dac mid", "DAC MID"),
        ("dac set 32768", "DAC SET 32768"),
        ("dac set 0x8000", "DAC SET 0x8000"),
        ("fc0?", "FC0?"),
        ("sweep?", "SWEEP?"),
        ("sweep load tiny_plus_minus_1", "SWEEP LOAD TINY_PLUS_MINUS_1"),
        ("sweep start", "SWEEP START"),
        ("sweep stop", "SWEEP STOP"),
        ("sweep step", "SWEEP STEP"),
        ("sweep clear", "SWEEP CLEAR"),
    ],
)
def test_parse_serial_command_normalizes_known_atomic_commands(raw: str, normalized: str) -> None:
    assert parse_serial_command(raw).normalized == normalized


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "DAC SET 70000",
        "DAC SET nope",
        "SWEEP LOAD arbitrary",
        "SWEEP ADD 0x8000 5000",
        "RESET",
    ],
)
def test_parse_serial_command_rejects_unknown_or_open_ended_commands(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_serial_command(raw)


def test_send_command_to_fifo_writes_normalized_command(tmp_path) -> None:
    fifo = tmp_path / "control" / "commands.fifo"

    with CommandFifo(fifo) as reader:
        assert send_command_to_fifo(fifo, "dac set 0x8000") == 0
        assert reader.poll() == ["DAC SET 0x8000"]
