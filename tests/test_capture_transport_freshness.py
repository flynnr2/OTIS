from __future__ import annotations

import json
from pathlib import Path

import pytest

from host.otis_tools import adaptive_hybrid_transport as transport
from host.otis_tools import capture_device as capture


def _capture_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, written_ns: int
) -> Path:
    runner = capture.CaptureDeviceRunner(
        capture.CaptureDeviceConfig(
            device="/dev/unused",
            baud=115200,
            run_dir=tmp_path,
            command_fifo=tmp_path / "control" / "normal_commands.fifo",
            emergency_command_fifo=tmp_path / "control" / "emergency_abort.fifo",
            normal_command_max_age_s=2.0,
        )
    )
    runner.capture_active = True
    runner.serial_open = True
    monkeypatch.setattr(capture.time, "monotonic_ns", lambda: written_ns)
    runner._write_state()
    return tmp_path / capture.CAPTURE_STATE


def _supervisor(tmp_path: Path) -> transport.ControlSupervisorBase:
    supervisor = object.__new__(transport.ControlSupervisorBase)
    supervisor.run_dir = tmp_path
    supervisor.state = {"terminal": None}
    supervisor._abort = lambda _reason: pytest.fail(
        "transport freshness must not submit an abort"
    )
    return supervisor


def test_capture_transport_freshness_uses_producer_monotonic_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written_ns = 1_000_000_000
    state_path = _capture_state(tmp_path, monkeypatch, written_ns=written_ns)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["updated_monotonic_ns"] == written_ns
    assert state["updated_utc"].endswith("Z")

    supervisor = _supervisor(tmp_path)
    monkeypatch.setattr(
        transport.time, "monotonic_ns", lambda: written_ns + 1_000_000_000
    )
    for wall_clock_s in (-10**12, 10**12):
        monkeypatch.setattr(
            transport.time, "time", lambda value=wall_clock_s: value
        )
        assert supervisor._check_capture_transport_state() == state
    assert supervisor.state["terminal"] is None


@pytest.mark.parametrize(
    ("age_ns", "stale"),
    [
        (
            transport.CAPTURE_TRANSPORT_STATE_MAX_AGE_S * 1_000_000_000,
            False,
        ),
        (
            transport.CAPTURE_TRANSPORT_STATE_MAX_AGE_S * 1_000_000_000 + 1,
            True,
        ),
    ],
)
def test_capture_transport_freshness_uses_an_exact_integer_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    age_ns: int,
    stale: bool,
) -> None:
    written_ns = 1_000_000_000
    _capture_state(tmp_path, monkeypatch, written_ns=written_ns)
    monkeypatch.setattr(transport.time, "monotonic_ns", lambda: written_ns + age_ns)
    supervisor = _supervisor(tmp_path)
    if stale:
        with pytest.raises(ValueError, match="is stale"):
            supervisor._check_capture_transport_state()
    else:
        assert supervisor._check_capture_transport_state()["updated_monotonic_ns"] == (
            written_ns
        )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("missing", "updated_monotonic_ns is malformed"),
        ("bool", "updated_monotonic_ns is malformed"),
        ("zero", "updated_monotonic_ns is malformed"),
        ("negative", "updated_monotonic_ns is malformed"),
        ("text", "updated_monotonic_ns is malformed"),
        ("future", "from the future"),
        ("stale", "is stale"),
    ],
)
def test_capture_transport_rejects_malformed_or_nonfresh_monotonic_heartbeat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    expected: str,
) -> None:
    written_ns = 1_000_000_000
    state_path = _capture_state(tmp_path, monkeypatch, written_ns=written_ns)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if mutation == "missing":
        del state["updated_monotonic_ns"]
    elif mutation == "bool":
        state["updated_monotonic_ns"] = True
    elif mutation == "zero":
        state["updated_monotonic_ns"] = 0
    elif mutation == "negative":
        state["updated_monotonic_ns"] = -1
    elif mutation == "text":
        state["updated_monotonic_ns"] = "1000000000"
    elif mutation == "future":
        state["updated_monotonic_ns"] = written_ns + 1
    elif mutation == "stale":
        state["updated_monotonic_ns"] = written_ns
    state_path.write_text(json.dumps(state), encoding="utf-8")

    now_ns = (
        written_ns
        if mutation != "stale"
        else written_ns
        + (transport.CAPTURE_TRANSPORT_STATE_MAX_AGE_S + 1)
        * 1_000_000_000
    )
    monkeypatch.setattr(transport.time, "monotonic_ns", lambda: now_ns)
    supervisor = _supervisor(tmp_path)
    with pytest.raises(ValueError, match=expected):
        supervisor._check_capture_transport_state()
    assert supervisor.state["terminal"] is None
