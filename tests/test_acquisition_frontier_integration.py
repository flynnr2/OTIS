from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import pty
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from host.otis_tools import adaptive_hybrid_replay as replay
from host.otis_tools import adaptive_hybrid_supervisor as supervisor_module
from host.otis_tools import capture_device as capture_module
from tests.capture_fixtures import write_simulated_run
from tests.runtime_fixtures import construct_simulated_supervisor
from host.otis_tools.run_spec import _transaction_identities
from host.otis_tools.acquisition_frontier import (
    FRONTIER_PATH,
    FRONTIER_POLICY,
    FRONTIER_STATE_PATH,
    read_acquisition_readiness,
)
from host.otis_tools.authoritative_inputs import (
    REFERENCE_ACCEPTANCE_POLICY_PATH,
    validate_authoritative_inputs,
    collect_authoritative_inputs,
)
from host.otis_tools.contracts import CONTRACT_FIELDS
from host.otis_tools.firmware_host_contract import RECORD_FIELD_WIRE_TYPES, WIRE_TYPES

_FROZEN_INPUTS = validate_authoritative_inputs(collect_authoritative_inputs())
_ACCEPTANCE_POLICY_SHA = str(
    _FROZEN_INPUTS.binding(REFERENCE_ACCEPTANCE_POLICY_PATH)["sha256"]
)


def _manifest() -> dict[str, object]:
    frozen = _FROZEN_INPUTS
    policy = frozen.document(REFERENCE_ACCEPTANCE_POLICY_PATH)
    binding = frozen.binding(REFERENCE_ACCEPTANCE_POLICY_PATH)
    return {
        "schema_version": 1,
        "run_id": "frontier-pty",
        "acquisition_frontier": FRONTIER_POLICY,
        "authoritative_inputs": frozen.as_dict(),
        "reference_acceptance": {
            "policy_id": policy["policy_id"],
            "policy_sha256": binding["sha256"],
            "path": REFERENCE_ACCEPTANCE_POLICY_PATH,
        },
        "transaction_identities": {"estimator_sha256": _transaction_identities(_FROZEN_INPUTS)["estimator_sha256"]},
        "channels": [
            {
                "channel_id": 0,
                "pin": "D10",
                "role": "external_event",
                "record_type": "EVT",
                "control_authority": False,
                "terminal_authority": False,
                "authority": "evidence_only",
            },
            {
                "channel_id": 1,
                "pin": "D14",
                "role": "authoritative_pps_reference",
                "record_type": "REF",
            },
        ],
        "files": [
            {"contract": "raw_events_v1", "record_type": "EVT", "path": "csv/external_events.csv"},
            {"contract": "raw_events_v1", "record_type": "REF", "path": "csv/reference_events.csv"},
            {"contract": "pps_snapshots_v1", "path": "csv/pps_snapshots.csv"},
            {"contract": "count_observations_v1", "path": "csv/count_observations.csv"},
            {"contract": "accepted_pps_spans_v1", "path": "csv/accepted_pps_spans_v1.csv"},
            {"contract": "estimates_v3", "path": "csv/estimates_v3.csv"},
        ],
    }


def _row(contract: str, values: dict[str, str]) -> bytes:
    fields = CONTRACT_FIELDS[contract]
    return (",".join(values[field] for field in fields) + "\n").encode("ascii")


def _ref(sequence: int, ticks: int) -> bytes:
    return _row("raw_events_v1", {
        "record_type": "REF", "schema_version": "1", "event_seq": str(1000 + sequence),
        "channel_id": "1", "edge": "R", "timestamp_ticks": str(ticks),
        "capture_domain": "rp2040_monotonic_us32", "flags": "16",
    })


def _evt(sequence: int, ticks: int) -> bytes:
    return _row("raw_events_v1", {
        "record_type": "EVT", "schema_version": "1", "event_seq": str(sequence),
        "channel_id": "0", "edge": "R", "timestamp_ticks": str(ticks),
        "capture_domain": "rp2040_monotonic_us32", "flags": "32",
    })


def _snapshot(sequence: int, ticks: int) -> bytes:
    return _row("pps_snapshots_v1", {
        "record_type": "SNP", "schema_version": "1", "session": "1",
        "snapshot_sequence": str(sequence),
        "cumulative_down_counter": str((0xFFFFFFFF - sequence * 10_000_000) % (1 << 32)),
        "reference_sequence": str(sequence), "reference_timestamp_ticks": str(ticks),
        "status": "0", "backend": "pio_wait_cumulative_snapshot_dma_v1",
    })


def _count(sequence: int, opening: int, closing: int) -> bytes:
    return _row("count_observations_v1", {
        "record_type": "CNT", "schema_version": "1", "count_seq": str(sequence),
        "channel_id": "2", "gate_open_ticks": str(opening), "gate_close_ticks": str(closing),
        "gate_domain": "rp2040_monotonic_us32", "counted_edges": "10000000",
        "source_edge": "R", "source_domain": "h1_oscillator_10mhz", "flags": "16",
    })


def _canonical(contract: str, *, record_type: str, schema_version: int) -> dict[str, str]:
    result: dict[str, str] = {}
    for field in CONTRACT_FIELDS[contract]:
        kind = WIRE_TYPES[RECORD_FIELD_WIRE_TYPES[contract][field]]
        if kind["kind"] == "record_type":
            result[field] = record_type
        elif kind["kind"] == "schema_version":
            result[field] = str(schema_version)
        elif kind["kind"] == "optional":
            result[field] = ""
        elif kind["kind"] in {"integer", "finite_decimal"}:
            result[field] = "0"
        elif kind["kind"] == "enum":
            result[field] = str(kind["values"][0])
        elif kind["kind"] == "escaped_atom":
            result[field] = "value"
        elif kind["kind"] == "lower_hex":
            result[field] = "0" * int(kind["length"])
        elif kind["kind"] == "lower_hex_or_literal":
            result[field] = str(kind["literal"])
        else:
            raise AssertionError(f"missing canonical value for {contract}.{field}")
    return result


def _estimate(first: int, last: int, ticks: int, identifier: str, *, sequence: int = 1) -> bytes:
    row = _canonical("estimates_v3", record_type="EST", schema_version=3)
    row.update({
        "record_type": "EST", "schema_version": "3", "estimate_seq": str(sequence),
        "estimate_id": identifier, "estimator_timestamp_ticks": str(ticks),
        "time_domain": "rp2040_monotonic_us32", "capture_session": "1",
        "source_acceptance_epoch": "1",
        "source_opening_accepted_boundary_ordinal": "0",
        "source_closing_accepted_boundary_ordinal": "600",
        "source_opening_snapshot_sequence": str(first),
        "source_closing_snapshot_sequence": str(last),
        "source_opening_reference_sequence": str(first),
        "source_closing_reference_sequence": str(last),
        "source_accepted_spans_ref": "live:APS:1:1:0:600",
        "estimator_version": replay.SELECTED_ESTIMATOR_ID,
        "config_hash": _transaction_identities(_FROZEN_INPUTS)["estimator_sha256"], "observation_validity": "valid",
        "reference_continuity": "true", "reference_validity": "valid",
        "count_validity": "valid", "count_continuity": "true",
        "diagnostic_health": "healthy",
        "frequency_estimate_hz": "10000000", "frequency_error_hz": "0",
        "accepted_sample_count": "600", "drift_enabled": "false",
        "preview_eligibility": "true",
    })
    return _row("estimates_v3", row)


def _accepted_span(opening: int, closing: int, opening_ticks: int, closing_ticks: int) -> bytes:
    row = _canonical(
        "accepted_pps_spans_v1", record_type="APS", schema_version=1
    )
    row.update({
        "record_type": "APS", "schema_version": "1", "capture_session": "1",
        "acceptance_epoch": "1", "accepted_boundary_ordinal": str(closing - 10),
        "opening_snapshot_sequence": str(opening),
        "closing_snapshot_sequence": str(closing),
        "opening_reference_sequence": str(opening),
        "closing_reference_sequence": str(closing),
        "opening_reference_timestamp_ticks": str(opening_ticks),
        "closing_reference_timestamp_ticks": str(closing_ticks),
        "time_domain": "rp2040_monotonic_us32",
        "source_count_first_sequence": str(closing),
        "source_count_last_sequence": str(closing),
        "source_count_record_count": "1", "counted_edges": "10000000",
        "excluded_candidate_count": "0", "nominal_interval_count": "1",
        "acceptance_policy_sha256": _ACCEPTANCE_POLICY_SHA,
    })
    return _row("accepted_pps_spans_v1", row)


def _write_all(descriptor: int, data: bytes) -> None:
    while data:
        written = os.write(descriptor, data)
        data = data[written:]


def _wait(predicate, *, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("timed out waiting for capture result")


def _capture(tmp_path: Path, chunks: list[bytes]) -> tuple[Path, dict[str, object], bytes]:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    master, slave = pty.openpty()
    device = os.path.realpath(os.ttyname(slave))
    manifest = write_simulated_run(run_dir, device)
    process = subprocess.Popen(
        [
            sys.executable, "-m", "host.otis_tools.capture_device", "--device", device,
            "--run-dir", str(run_dir), "--duration-s", "30", "--status-interval", "30",
        ],
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    os.close(slave)
    try:
        _wait(lambda: (run_dir / "reports/capture_device_state.json").is_file())
        _wait(lambda: json.loads((run_dir / "reports/capture_device_state.json").read_text())["serial_open"] is True)
        for chunk in chunks:
            _write_all(master, chunk)
        _wait(lambda: (run_dir / FRONTIER_STATE_PATH).is_file())
        # Capture is allowed to report the hold before closing; the raw and CSV
        # bytes must already be durable at this boundary.
        _wait(lambda: (run_dir / "raw/serial.log").stat().st_size >= sum(map(len, chunks)))
    finally:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        os.close(master)
    assert process.returncode == 0, process.stderr.read().decode("utf-8", "replace")
    return run_dir, manifest, b"".join(chunks)


def _retained_device_lines(run_dir: Path) -> list[bytes]:
    """Remove only complete host annotations; preserve every device line byte."""
    return [
        line for line in (run_dir / "raw/serial.log").read_bytes().splitlines()
        if not line.startswith(b"# OTIS_HOST ")
    ]


def _expected_device_lines(device_bytes: bytes) -> list[bytes]:
    return device_bytes.splitlines()


@pytest.mark.parametrize(
    ("attachment", "chunks", "opening_sequence"),
    [
        ("before_REF", lambda: [_count(10, 0, 1_000_000), _ref(10, 1_000_000), _snapshot(10, 1_000_000), _ref(11, 2_000_000), _snapshot(11, 2_000_000), _count(11, 1_000_000, 2_000_000)], 10),
        ("between_REF_SNP", lambda: [_snapshot(10, 1_000_000), _count(11, 1_000_000, 2_000_000), _ref(11, 2_000_000), _snapshot(11, 2_000_000), _ref(12, 3_000_000), _snapshot(12, 3_000_000), _count(12, 2_000_000, 3_000_000)], 11),
        ("between_SNP_CNT", lambda: [_count(11, 1_000_000, 2_000_000), _ref(11, 2_000_000), _snapshot(11, 2_000_000), _ref(12, 3_000_000), _snapshot(12, 3_000_000), _count(12, 2_000_000, 3_000_000)], 11),
    ],
)
def test_real_capture_anchors_first_possible_complete_pair_after_attachment(
    tmp_path: Path, attachment: str, chunks, opening_sequence: int,
) -> None:
    run_dir, manifest, device_bytes = _capture(tmp_path, chunks())
    artifact = json.loads((run_dir / FRONTIER_PATH).read_text())
    readiness = read_acquisition_readiness(run_dir, manifest)
    assert readiness["ready"] is True
    assert artifact["opening_snapshot"]["record"]["snapshot_sequence"] == str(opening_sequence)
    assert artifact["closing_snapshot"]["record"]["snapshot_sequence"] == str(opening_sequence + 1)
    assert _retained_device_lines(run_dir) == _expected_device_lines(device_bytes), attachment
    assert artifact["first_count"]["capture_line_ordinal"] > artifact["closing_snapshot"]["capture_line_ordinal"]


def test_real_capture_keeps_d10_and_orphan_prefix_but_requires_complete_600_source(
    tmp_path: Path,
) -> None:
    first, intervals = 10, 600
    chunks = _complete_source_chunks(first, intervals)
    # Cross-queue EST latency is legal. The retained EST must wait until its
    # exact post-anchor source has arrived, rather than being treated as stale.
    pending = _estimate(first, first + intervals, (intervals + 1) * 1_000_000, "pending-est")
    chunks.insert(8, pending)
    run_dir, manifest, device_bytes = _capture(tmp_path, chunks)
    readiness = read_acquisition_readiness(run_dir, manifest)
    assert readiness["anchor_ready"] is True, readiness
    assert read_acquisition_readiness(run_dir, manifest, source_estimate_id="missing-est")["ready"] is False
    assert read_acquisition_readiness(run_dir, manifest, source_estimate_id="pending-est")["ready"] is True
    assert (run_dir / "csv/external_events.csv").read_text(encoding="utf-8").count("EVT,") == 1
    assert _retained_device_lines(run_dir) == _expected_device_lines(device_bytes)


def _complete_source_chunks(first: int, intervals: int) -> list[bytes]:
    chunks = [_evt(7, 17), _ref(first, 1_000_000), _snapshot(first, 1_000_000)]
    # Match the producer's SNP,CNT,APS order. This leading CNT closes at the
    # retained opening SNP but belongs to an unretained aperture and must not
    # enter the later accepted-span estimator source.
    chunks.append(_count(first, 0, 1_000_000))
    for sequence in range(first + 1, first + intervals + 1):
        ticks = (sequence - first + 1) * 1_000_000
        chunks.extend((
            _ref(sequence, ticks), _snapshot(sequence, ticks),
            _count(sequence, ticks - 1_000_000, ticks),
            _accepted_span(sequence - 1, sequence, ticks - 1_000_000, ticks),
        ))
    return chunks


def test_prefrontier_estimate_source_enters_hold_and_cannot_arm(tmp_path: Path) -> None:
    first, intervals = 10, 600
    chunks = _complete_source_chunks(first, intervals)
    # The source says it opened at 9, before the immutable frontier anchor at
    # 10. It is not rescued by the later healthy 10..610 retained span.
    chunks.append(_estimate(9, first + intervals, (intervals + 1) * 1_000_000, "prefrontier-est"))
    run_dir, manifest, _ = _capture(tmp_path, chunks)
    readiness = read_acquisition_readiness(run_dir, manifest, source_estimate_id="prefrontier-est")
    assert readiness["ready"] is False
    assert readiness["errors"]


def test_malformed_initial_fragment_is_retained_but_holds_authority(
    tmp_path: Path,
) -> None:
    chunks = [
        # One bounded ASCII first line is an existing declared boot-fragment
        # exception. A malformed device fragment is not, and must remain a
        # retained diagnostic hold rather than a frontier waiver.
        b"\xfftruncated-attachment-fragment\n",
        _ref(10, 1_000_000), _snapshot(10, 1_000_000),
        _ref(11, 2_000_000), _snapshot(11, 2_000_000), _count(11, 1_000_000, 2_000_000),
    ]
    run_dir, manifest, device_bytes = _capture(tmp_path, chunks)
    readiness = read_acquisition_readiness(run_dir, manifest)
    assert readiness["ready"] is False
    assert readiness["errors"]
    assert _retained_device_lines(run_dir) == _expected_device_lines(device_bytes)

    supervisor = object.__new__(supervisor_module.AdaptiveHybridSupervisor)
    supervisor.run_dir = run_dir
    supervisor.acquisition_manifest = manifest
    supervisor.runtime_context = SimpleNamespace(authoritative_inputs=_FROZEN_INPUTS)
    holds: list[tuple[str, str]] = []
    supervisor._enter_host_verification_hold = lambda error, *, source: holds.append((str(error), source))
    assert supervisor._acquisition_authority_ready(expected_capture_session=1) is False
    assert holds and holds[0][1] == "acquisition_frontier"


def test_missing_postfrontier_snapshot_enters_diagnostic_hold(tmp_path: Path) -> None:
    chunks = [
        _count(10, 0, 1_000_000),
        _ref(10, 1_000_000), _snapshot(10, 1_000_000),
        _ref(11, 2_000_000), _snapshot(11, 2_000_000), _count(11, 1_000_000, 2_000_000),
        # The second D14 REF arrives, but its PIO snapshot is absent. The
        # following CNT must not be reattached to the earlier healthy pair.
        _ref(12, 3_000_000), _count(12, 2_000_000, 3_000_000),
    ]
    run_dir, manifest, _ = _capture(tmp_path, chunks)
    readiness = read_acquisition_readiness(run_dir, manifest)
    assert readiness["ready"] is False
    assert any("CNT" in error for error in readiness["errors"])


def test_actual_setup_and_arm_paths_wait_for_missing_live_frontier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise `_maybe_start_or_arm`, without replacing acquisition readiness."""
    manifest = _manifest()
    commands: list[str] = []
    # This is a healthy, current capture status.  The negative decisions below
    # must therefore reach retained-frontier readiness, rather than stopping at
    # a missing or malformed capture-observer status.
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports/capture_device_state.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "capture_active": True,
                "serial_open": True,
                "physical_serial_open": True,
                "logical_segment_closed": False,
                "acquisition_frontier_observer_error": None,
            }
        ),
        encoding="utf-8",
    )
    real_readiness = supervisor_module.read_acquisition_readiness
    readiness_calls: list[tuple[int | None, str | None]] = []

    def observe_readiness(
        run_dir,
        manifest_value,
        *,
        source_estimate_id=None,
        expected_capture_session=None,
        validated_inputs=None,
    ):
        readiness_calls.append((expected_capture_session, source_estimate_id))
        return real_readiness(
            run_dir,
            manifest_value,
            source_estimate_id=source_estimate_id,
            expected_capture_session=expected_capture_session,
            validated_inputs=validated_inputs,
        )

    monkeypatch.setattr(supervisor_module, "read_acquisition_readiness", observe_readiness)

    setup = construct_simulated_supervisor(tmp_path)
    setup.acquisition_manifest = manifest
    setup.state.update(host_verification_hold=None, manual_start_sent=False)
    setup._startup_census_admitted = lambda: True
    setup._identity_ready = lambda _health: True
    setup._prewrite_readiness = lambda _health: SimpleNamespace(ready=True)
    setup._command = commands.append
    setup._setup_command = lambda _health: (_ for _ in ()).throw(
        AssertionError("SETUP must wait for a live frontier")
    )
    setup_gate = setup._acquisition_authority_ready
    setup_gate_calls: list[tuple[int, str | None]] = []

    def observe_setup_gate(*, expected_capture_session: int, source_estimate_id: str | None = None) -> bool:
        setup_gate_calls.append((expected_capture_session, source_estimate_id))
        return setup_gate(
            expected_capture_session=expected_capture_session,
            source_estimate_id=source_estimate_id,
        )

    setup._acquisition_authority_ready = observe_setup_gate
    capture_health = {
        **{("pps_gate", key): value for key, value in
           supervisor_module._AUTHORITATIVE_CAPTURE_EXPECTED_HEALTH.items()},
        ("adaptive_hybrid", "reference_acceptance_state"): "tracking",
        ("adaptive_hybrid", "accepted_anchor_current"): "true",
        ("adaptive_hybrid", "reference_acceptance_policy_sha256"): "1" * 64,
        ("pps_gate", "reference_acceptance_policy_sha256"): "1" * 64,
    }
    setup._maybe_start_or_arm({
        **capture_health,
        ("pps_gate", "snapshot_session"): "1",
        ("adaptive_hybrid", "state"): "DISARMED",
        ("adaptive_hybrid", "reason"): "",
        ("adaptive_hybrid", "manual_start_confirmed"): "false",
        ("adaptive_hybrid", "session_id"): "1",
    })
    assert commands == []
    assert setup_gate_calls == [(1, None)]

    arm = setup
    arm.acquisition_manifest = manifest
    arm.state.update({
        "host_verification_hold": None,
        "manual_start_sent": True,
        "arm_pending": False,
        "setup_confirmed_utc": "2026-09-11T00:00:00Z",
        "setup_confirmation": {"session_id": 1, "applied_code": setup.programme.setup_code, "dac_epoch": 1},
        "initial_session_id": 1,
    })
    arm._startup_census_admitted = lambda: True
    arm._identity_ready = lambda _health: True
    arm._close_response_horizon_if_required = lambda _health: False
    arm._arm_progress_epoch_ready = lambda _preview, _progress: True
    arm._command = commands.append
    arm_gate = arm._acquisition_authority_ready
    arm_gate_calls: list[tuple[int, str | None]] = []

    def observe_arm_gate(*, expected_capture_session: int, source_estimate_id: str | None = None) -> bool:
        arm_gate_calls.append((expected_capture_session, source_estimate_id))
        return arm_gate(
            expected_capture_session=expected_capture_session,
            source_estimate_id=source_estimate_id,
        )

    arm._acquisition_authority_ready = observe_arm_gate
    monkeypatch.setattr(supervisor_module, "_read_csv", lambda _path: [{
        "est_input_ref": "unproved-estimate", "decision_id": "decision-1",
        "preview_available": "true", "preview_eligibility": "true",
    }])
    arm._maybe_start_or_arm({
        **capture_health,
        ("pps_gate", "snapshot_session"): "1",
        ("adaptive_hybrid", "state"): "DISARMED",
        ("adaptive_hybrid", "reason"): "",
        ("adaptive_hybrid", "manual_start_confirmed"): "true",
        ("adaptive_hybrid", "hybrid_state"): "HYBRID_TRACKING",
        ("adaptive_hybrid", "first_phase_checkpoint_passed"): "true",
        ("adaptive_hybrid", "correction_count"): "0",
        ("adaptive_hybrid", "selected_interval_count"): "600",
        ("adaptive_hybrid", "arm_eligible"): "true",
        ("adaptive_hybrid", "evidence_phase"): "evidence_clear",
        ("adaptive_hybrid", "evidence_pending"): "false",
        ("adaptive_hybrid", "session_id"): "1",
    })
    assert commands == []
    assert arm_gate_calls == [(1, "unproved-estimate")]
    assert readiness_calls == [(1, None), (1, "unproved-estimate")]


def test_observer_failure_after_ready_preserves_capture_and_blocks_authority(
    tmp_path: Path,
) -> None:
    """A failed prospective observer cannot stop capture or reuse stale readiness."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    manifest = write_simulated_run(run_dir)
    runner = capture_module.CaptureDeviceRunner(
        capture_module.CaptureDeviceConfig(
            device="/dev/null", baud=115200, run_dir=run_dir
        )
    )
    runner.capture_active = True
    runner.serial_open = True
    sink = capture_module.CaptureSink(
        runner,
        run_dir=run_dir,
        command_fifo_path=None,
        emergency_fifo_path=None,
    )
    try:
        established = b"".join(
            [
                _count(10, 0, 1_000_000),
                _ref(10, 1_000_000),
                _snapshot(10, 1_000_000),
                _ref(11, 2_000_000),
                _snapshot(11, 2_000_000),
                _count(11, 1_000_000, 2_000_000),
            ]
        )
        runner._process_bytes(
            established,
            sink.splitter,
            sink.raw_writer,
            sink.active_status_live_publisher,
            sink.acquisition_frontier_tracker,
        )
        assert read_acquisition_readiness(
            run_dir, manifest, expected_capture_session=1
        )["ready"] is True
        immutable_frontier = (run_dir / FRONTIER_PATH).read_bytes()

        def fail_observe(*_args, **_kwargs) -> None:
            raise OSError("injected observer failure")

        assert sink.acquisition_frontier_tracker is not None
        sink.acquisition_frontier_tracker.observe = fail_observe
        continued = _ref(12, 3_000_000) + _snapshot(12, 3_000_000)
        runner._process_bytes(
            continued,
            sink.splitter,
            sink.raw_writer,
            sink.active_status_live_publisher,
            sink.acquisition_frontier_tracker,
        )

        # The accepted device records continue into both durable views.  The
        # observer error is sticky, while its already-established immutable
        # proof remains byte-identical rather than being rewritten or advanced.
        assert _retained_device_lines(run_dir) == _expected_device_lines(
            established + continued
        )
        assert "1012" in (run_dir / "csv/reference_events.csv").read_text()
        assert "12" in (run_dir / "csv/pps_snapshots.csv").read_text()
        assert (run_dir / FRONTIER_PATH).read_bytes() == immutable_frontier
        state = json.loads(
            (run_dir / "reports/capture_device_state.json").read_text()
        )
        assert state["serial_open"] is True
        assert state["capture_active"] is True
        assert state["acquisition_frontier_observer_error"] == (
            "OSError: injected observer failure"
        )
        # The retained proof itself still reads ready.  New authority must use
        # the capture observer state as a separate, fail-closed live boundary.
        assert read_acquisition_readiness(
            run_dir, manifest, expected_capture_session=1
        )["ready"] is True
        supervisor = object.__new__(supervisor_module.AdaptiveHybridSupervisor)
        supervisor.run_dir = run_dir
        supervisor.acquisition_manifest = manifest
        supervisor.runtime_context = SimpleNamespace(
            authoritative_inputs=_FROZEN_INPUTS
        )
        holds: list[str] = []
        supervisor._enter_host_verification_hold = lambda error, *, source: holds.append(
            f"{source}: {error}"
        )
        assert supervisor._acquisition_authority_ready(
            expected_capture_session=1
        ) is False
        assert holds == [
            "acquisition_frontier: OSError: injected observer failure"
        ]

        # A malformed state root or a missing mandatory health field must also
        # prevent authority even though the earlier immutable proof remains.
        for malformed_state in ([], {}):
            (run_dir / "reports/capture_device_state.json").write_text(
                json.dumps(malformed_state), encoding="utf-8"
            )
            holds.clear()
            assert supervisor._acquisition_authority_ready(
                expected_capture_session=1
            ) is False
            assert holds and holds[0].startswith("acquisition_frontier:")
    finally:
        sink.abandon_incomplete()
