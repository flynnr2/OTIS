from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from types import MethodType, SimpleNamespace

import pytest

from host.otis_tools import adaptive_hybrid_monitor as monitor
from host.otis_tools import live_run
from host.otis_tools.active_status_contract import (
    ACTIVE_STATUS_SNAPSHOT_CONTRACT,
    SNAPSHOT_BEGIN_KEY,
    SNAPSHOT_COMPLETE_KEY,
    SNAPSHOT_CONTRACT_KEY,
)
from host.otis_tools.adaptive_hybrid_transport import (
    ControlSupervisorBase,
    ExplicitSupervisorAbort,
)
from host.otis_tools.contracts import HEALTH_FIELDS
from host.otis_tools.firmware_host_contract import (
    ACTIVE_STATUS_COMPONENT,
    ACTIVE_STATUS_KEYS,
    ACTIVE_STATUS_VALUE_WIRE_TYPES,
    WIRE_TYPES,
)


def _capture_state(path: Path, *, abort: bool) -> dict[str, object]:
    value = {
        "schema_version": 1,
        "updated_monotonic_ns": __import__("time").monotonic_ns(),
        "pid": os.getpid(),
        "capture_active": True,
        "serial_open": True,
        "command_fifo_configured": True,
        "emergency_command_fifo_configured": True,
        "state_heartbeat_interval_s": 5.0,
        "normal_command_batch_limit": 1,
        "normal_command_max_age_s": 2.0,
        "write_timeout_s": 1.0,
        "malformed_utf8": 0,
        "parser_errors": 0,
        "reconnect_count": 0,
        "commands_rejected": 0,
        "emergency_abort_latched": abort,
        "emergency_aborts_sent": int(abort),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return value


def test_priority_abort_is_observed_by_owner_without_a_relay_or_resend(tmp_path: Path) -> None:
    state_path = tmp_path / "reports/capture_device_state.json"
    state = _capture_state(state_path, abort=True)
    # Abort observation must survive the diagnostic that placed the owner on hold.
    state["parser_errors"] = 1
    state_path.write_text(json.dumps(state), encoding="utf-8")
    owner = object.__new__(ControlSupervisorBase)
    owner.run_dir = tmp_path
    owner.expected_capture_pid = os.getpid()
    owner._live_command_ack_required = True
    observed: list[dict[str, object]] = []
    owner._observe_explicit_capture_abort = MethodType(
        lambda self, state: observed.append(state), owner
    )

    with pytest.raises(ExplicitSupervisorAbort):
        owner._poll_wait_abort()

    assert len(observed) == 1
    assert observed[0]["emergency_aborts_sent"] == 1


def _active_value(key: str) -> str:
    wire_type = WIRE_TYPES[ACTIVE_STATUS_VALUE_WIRE_TYPES[key]]
    if wire_type["kind"] == "integer":
        return "0"
    if wire_type["kind"] == "enum":
        return str(wire_type["values"][0])
    if wire_type["kind"] == "escaped_atom":
        return "value"
    if wire_type["kind"] == "lower_hex":
        return "a" * int(wire_type["length"])
    if wire_type["kind"] == "hex_integer":
        return "0x0000"
    if wire_type["kind"] == "literal_or":
        return str(wire_type["literal"])
    raise AssertionError(wire_type)


def _status_line(key: str, value: str, sequence: int) -> str:
    row = {
        "record_type": "STS",
        "schema_version": "1",
        "status_seq": str(sequence),
        "timestamp_ticks": str(sequence),
        "status_domain": "rp2040_monotonic_us32",
        "component": ACTIVE_STATUS_COMPONENT,
        "status_key": key,
        "status_value": value,
        "severity": "INFO",
        "flags": "0",
    }
    from io import StringIO
    stream = StringIO()
    csv.DictWriter(stream, fieldnames=HEALTH_FIELDS, lineterminator="\n").writerow(row)
    return stream.getvalue()


def _aborted_snapshot() -> bytes:
    values = {key: _active_value(key) for key in ACTIVE_STATUS_KEYS}
    values.update({
        "state": "ABORTED",
        "fail_static": "true",
        "evidence_pending": "false",
        "evidence_phase": "evidence_clear",
        "evidence_request_sequence": "0",
        "confirmed_applied_code_known": "false",
    })
    rows = [
        (SNAPSHOT_BEGIN_KEY, "7"),
        (SNAPSHOT_CONTRACT_KEY, ACTIVE_STATUS_SNAPSHOT_CONTRACT),
        *values.items(),
        (SNAPSHOT_COMPLETE_KEY, "7"),
    ]
    return "".join(
        _status_line(key, value, sequence)
        for sequence, (key, value) in enumerate(rows, 1)
    ).encode("utf-8")


def test_abort_delivery_requires_post_frontier_marker_and_accepts_fragmented_active_without_pps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = tmp_path / "raw/serial.log"
    raw.parent.mkdir(parents=True)
    # A complete pre-frontier snapshot is not causal abort evidence.
    raw.write_bytes(_aborted_snapshot())
    frontier_offset = raw.stat().st_size
    marker = b'# OTIS_HOST {"event":"emergency_abort_sent"}\n'
    snapshot = _aborted_snapshot()
    raw.write_bytes(raw.read_bytes() + marker + snapshot[: len(snapshot) // 2])
    metadata = raw.stat()
    state = _capture_state(tmp_path / "reports/capture_device_state.json", abort=True)
    state["emergency_abort_raw_frontier"] = {
        "run_directory": str(tmp_path.resolve()),
        "search_offset_bytes": frontier_offset,
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
    }
    calls = 0

    def read_state(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            with raw.open("ab") as output:
                output.write(snapshot[len(snapshot) // 2 :])
        return state

    monkeypatch.setattr(live_run, "read_capture_transport_state", read_state)
    live_run.wait_for_abort_delivery(
        tmp_path,
        {"result": "aborted"},
        deadline_ns=__import__("time").monotonic_ns() + 2_000_000_000,
    )
    assert calls >= 2


def test_monitor_is_a_projection_and_never_publishes_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "reports").mkdir()
    capture = _capture_state(tmp_path / "reports/capture_device_state.json", abort=False)
    supervisor = {
        "host_verification_hold": {"source": "fixture"},
        "qualified_d14_accepted_apertures": 12,
    }
    (tmp_path / "reports/adaptive_hybrid_supervisor_state.json").write_text(
        json.dumps(supervisor), encoding="utf-8"
    )
    monkeypatch.setattr(
        monitor, "load_manifest",
        lambda _run_dir: SimpleNamespace(data={"host": {"serial_device": "/dev/none"}}),
    )
    monkeypatch.setattr(monitor, "_serial_owner_pids", lambda _device: {capture["pid"]})
    before = set(tmp_path.rglob("*"))
    value = monitor.snapshot(tmp_path)
    after = set(tmp_path.rglob("*"))
    assert value["phase"] == "review_hold"
    assert value["monitor_command_authority"] is False
    assert value["supervisor_control_authority"] is None
    assert value["progress"]["qualified_d14_accepted_apertures"] == 12
    assert after == before


def test_simulated_runtime_requires_explicit_pty_capture_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "run_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        live_run, "load_manifest",
        lambda _run_dir: SimpleNamespace(
            path=manifest, data={"execution_kind": "simulated"}
        ),
    )
    with pytest.raises(ValueError, match="caller-supplied PTY"):
        live_run.run_experiment(
            manifest_path=manifest,
            device="/dev/ttys9",
            physical=False,
        )


def test_live_entry_rejects_changed_host_tool_bytes_before_starting_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = tmp_path / "run_manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    manifest = {
        "execution_kind": "physical",
        "run_spec": {"path": "run_spec.json"},
        "host": {
            "serial_device": "/dev/fake",
            "baud": 115200,
            "capture": {
                "status_interval_s": 5,
                "write_timeout_s": 1,
                "normal_command_max_age_s": 2,
                "normal_command_batch_limit": 1,
            },
        },
    }
    frozen_spec = object()
    monkeypatch.setattr(
        live_run,
        "load_manifest",
        lambda _run_dir: SimpleNamespace(path=manifest_path, data=manifest),
    )
    monkeypatch.setattr(live_run, "prepare_runtime_context", lambda _manifest: object())
    monkeypatch.setattr(live_run, "load_run_spec", lambda _path: frozen_spec)

    def reject_toolset(spec: object) -> None:
        assert spec is frozen_spec
        raise ValueError("current host tool bytes differ")

    monkeypatch.setattr(live_run, "verify_current_host_toolset", reject_toolset)
    monkeypatch.setattr(
        live_run.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("capture started before tool verification"),
    )

    with pytest.raises(ValueError, match="host tool bytes differ"):
        live_run.run_experiment(
            manifest_path=manifest_path,
            device="/dev/fake",
            physical=True,
        )
