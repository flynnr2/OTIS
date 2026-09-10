from __future__ import annotations

import pytest

from host.otis_tools.serial_commands import (
    CommandFifo,
    parse_serial_command,
    parse_timestamped_command_line,
    send_command_to_fifo,
    send_timestamped_command_to_fifo,
    timestamped_command_line,
)


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("help", "HELP"),
        ("config?", "CONFIG?"),
        ("dualcore?", "DUALCORE?"),
        ("dac?", "DAC?"),
        ("dac limits?", "DAC LIMITS?"),
        ("count?", "COUNT?"),
        ("active?", "ACTIVE?"),
        ("active snapshot 99", "ACTIVE SNAPSHOT 99"),
        ("active lease 17", "ACTIVE LEASE 17"),
        (
            "active setup 1 7 99 650 4 0xa808 1 " + "B" * 64,
            "ACTIVE SETUP 1 7 99 650 4 0xA808 1 " + "b" * 64,
        ),
        ("active arm 8 1234 2500", "ACTIVE ARM 8 1234 2500"),
        ("active evidence 2 1", "ACTIVE EVIDENCE 2 1"),
        ("active evidence 2 2", "ACTIVE EVIDENCE 2 2"),
        ("active evidence 2 3", "ACTIVE EVIDENCE 2 3"),
        ("active evidence 2 4", "ACTIVE EVIDENCE 2 4"),
        ("active abort", "ACTIVE ABORT"),
    ],
)
def test_parse_serial_command_normalizes_known_atomic_commands(raw: str, normalized: str) -> None:
    assert parse_serial_command(raw).normalized == normalized


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "DUALCORE INVALIDATE_GNSS",
        "DUALCORE RECOVER",
        "DAC MID",
        "DAC ZERO",
        "DAC SET 70000",
        "DAC SET nope",
        "DAC SET 0x8000",
        "FC0?",
        "Q2 CASE 1362166001 38",
        "SWEEP?",
        "SWEEP LOAD arbitrary",
        "SWEEP ADD 0x8000 5000",
        "RESET",
        "PPSGEN ARM arbitrary",
        "PPSGEN?",
        "ACTIVE LEASE 0",
        "ACTIVE SNAPSHOT 0",
        "ACTIVE SNAPSHOT 4294967296",
        "Q2 CASE 0 1",
        "Q2 CASE 1 0",
        "Q2 CASE 1 39",
        "ACTIVE SETUP 1 7 99 650 4 0xA808 1 bad",
        "ACTIVE SETUP 1 7 99 650 4 0xA808 0 " + "b" * 64,
        "ACTIVE ARM 1 2",
        "ACTIVE ARM 1 0 3",
        "ACTIVE EVIDENCE 1",
        "ACTIVE EVIDENCE 1 5",
        "ACTIVE EVIDENCE 1 3 5 -3 1 2 9000 " + "a" * 64,
        "ACTIVE EVIDENCE 1 4 5 -3 1 2 9000 " + "a" * 64,
        "ACTIVE EVIDENCE 1 4 5 -3 1 2 9000 bad",
        "ACTIVE SET 0xA950",
    ],
)
def test_parse_serial_command_rejects_unknown_or_open_ended_commands(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_serial_command(raw)


def test_send_command_to_fifo_writes_normalized_command(tmp_path) -> None:
    fifo = tmp_path / "control" / "commands.fifo"

    with CommandFifo(fifo) as reader:
        assert send_command_to_fifo(fifo, "count?") == 0
        assert reader.poll() == ["COUNT?"]


def test_command_fifo_bounded_poll_preserves_remaining_order(tmp_path) -> None:
    fifo = tmp_path / "control" / "commands.fifo"

    with CommandFifo(fifo) as reader:
        assert send_command_to_fifo(fifo, "CONFIG?") == 0
        assert send_command_to_fifo(fifo, "ACTIVE LEASE 1") == 0
        assert send_command_to_fifo(fifo, "ACTIVE?") == 0

        assert reader.poll(max_lines=1) == ["CONFIG?"]
        assert reader.poll(max_lines=1) == ["ACTIVE LEASE 1"]
        assert reader.poll(max_lines=1) == ["ACTIVE?"]
        assert reader.poll(max_lines=1) == []


def test_timestamped_command_envelope_preserves_exact_validated_command() -> None:
    line = timestamped_command_line(
        "active arm 8 1234 2500", created_monotonic_ns=123456789
    )
    command, created = parse_timestamped_command_line(line)

    assert line == "OTISQ1 123456789 ACTIVE ARM 8 1234 2500"
    assert command.normalized == "ACTIVE ARM 8 1234 2500"
    assert created == 123456789


def test_timestamped_command_fifo_write_is_atomic_and_parseable(tmp_path) -> None:
    fifo = tmp_path / "control" / "commands.fifo"

    with CommandFifo(fifo) as reader:
        assert (
            send_timestamped_command_to_fifo(
                fifo,
                "CONFIG?",
                created_monotonic_ns=987654321,
            )
            == 0
        )
        lines = reader.poll()

    assert lines == ["OTISQ1 987654321 CONFIG?"]
    command, created = parse_timestamped_command_line(lines[0])
    assert command.normalized == "CONFIG?"
    assert created == 987654321
