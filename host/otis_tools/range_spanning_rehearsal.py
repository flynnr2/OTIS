"""Run the complete accelerated no-hardware CX319 Part A operational path."""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any

from .capture_runtime_checks import _capture_state_ready, _inject_transport_fault
from .capture_segment_rotation import prepare_transition, request_rotation
from .contracts import CONTRACT_FIELDS
from .evidence import create_evidence_snapshot
from .evidence_index import package_identity, register_package, validate_index
from .range_spanning_analyze import analyze
from .range_spanning_bundle import (
    _atomic_new_json,
    canonical_sha256,
    sha256_file,
    validate_bundle,
)
from .range_spanning_run import EVENTS, STATE, _append_event, _replace_json, _write_complete
from .run_paths import default_csv_files
from .serial_commands import send_timestamped_command_to_fifo
from .time_domains import RP2040_TIMER0_MICROS_WRAP_TICKS


TOOL_ID = "cx319_range_spanning_operational_rehearsal_v1"
RESULT_TYPE = "cx319_range_spanning_operational_rehearsal_result_v1"
SEAL_TYPE = "cx319_range_spanning_operational_rehearsal_seal_v1"
ROOT = Path(__file__).resolve().parents[2]


def _line(row: dict[str, str], contract: str) -> bytes:
    fields = CONTRACT_FIELDS[contract]
    with tempfile.SpooledTemporaryFile(mode="w+", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\r\n")
        writer.writerow({field: row.get(field, "") for field in fields})
        handle.seek(0)
        return handle.read().encode("ascii")


def _records() -> list[bytes]:
    modulus = RP2040_TIMER0_MICROS_WRAP_TICKS
    raw = [
        {
            "record_type": "REF",
            "schema_version": "1",
            "event_seq": str(index),
            "channel_id": "1",
            "edge": "R",
            "timestamp_ticks": str(ticks),
            "capture_domain": "rp2040_timer0",
            "flags": "16",
        }
        for index, ticks in enumerate((modulus - 16_000_000, 0, 16_000_000), start=1)
    ]
    counts = [
        {
            "record_type": "CNT",
            "schema_version": "1",
            "count_seq": str(index),
            "channel_id": "2",
            "gate_open_ticks": str(open_ticks),
            "gate_close_ticks": str(close_ticks),
            "gate_domain": "rp2040_timer0",
            "counted_edges": "10000000",
            "source_edge": "R",
            "source_domain": "h1_cx317_ocxo_10mhz",
            "flags": "16",
        }
        for index, (open_ticks, close_ticks) in enumerate(
            ((modulus - 16_000_000, 0), (0, 16_000_000)), start=1
        )
    ]
    health = [
        {
            "record_type": "STS",
            "schema_version": "1",
            "status_seq": str(index),
            "timestamp_ticks": str(index * 1000),
            "status_domain": "rp2040_timer0",
            "component": "dual_core",
            "status_key": key,
            "status_value": value,
            "severity": "INFO",
            "flags": "0",
        }
        for index, (key, value) in enumerate(
            (("partition_fault", "none"), ("fail_static", "false")), start=1
        )
    ]
    dac = {
        "record_type": "DAC",
        "schema_version": "1",
        "seq": "1",
        "elapsed_ms": "1000",
        "step_index": "-1",
        "dac_code_requested": "43008",
        "dac_code_applied": "43008",
        "dac_code_clamped": "0",
        "dac_voltage_measured_v": "",
        "ocxo_tune_voltage_measured_v": "",
        "dwell_ms": "0",
        "event": "manual_apply",
        "flags": "0",
    }
    estimates: list[dict[str, str]] = []
    for sequence, count in ((1, -6), (2, -6)):
        row = {field: "" for field in CONTRACT_FIELDS["estimates_v2"]}
        row.update(
            record_type="EST",
            schema_version="2",
            estimate_seq=str(sequence),
            estimate_id=f"est:cx317:selected600:{sequence:06d}",
            estimator_timestamp_ticks=str(32_000_000 + sequence * 9_600_000_000),
            time_domain="rp2040_timer0",
            source_count_seq=str(sequence),
            source_count_ref=f"rehearsal:CNT:{sequence}",
            source_reference_first_seq=str(sequence),
            source_reference_last_seq=str(sequence + 600),
            source_status_refs="rehearsal:STS:1",
            source_dac_ref="rehearsal:DAC:1",
            manifest_ref="firmware_config:cx319_range_map_part_a",
            estimator_version="cx317_selected_600s_nonoverlap_v1",
            config_hash="5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c",
            observation_validity="valid",
            observation_reason_codes="contiguous_snapshot_span",
            reference_validity="valid",
            reference_age_s="0",
            reference_continuity="true",
            count_validity="valid",
            count_age_s="0",
            count_continuity="true",
            diagnostic_health="healthy",
            diagnostic_reason_codes="diagnostic_healthy",
            frequency_observation_hz=f"{10000000.0 + count / 600.0:.12f}",
            frequency_estimate_hz=f"{10000000.0 + count / 600.0:.12f}",
            frequency_error_hz=f"{count / 600.0:.12f}",
            accepted_sample_count="600",
            estimator_confidence="unavailable",
            uncertainty_status="unavailable",
            uncertainty_reason_codes="uncertainty_components_unavailable",
            correlation_policy="not_combined_missing_components",
            uncertainty_model_ref="unavailable:combined_uncertainty",
            drift_enabled="false",
            preview_eligibility="true",
            eligibility_reason_codes="eligible",
        )
        estimates.append(row)
    tdb: list[dict[str, str]] = []
    for sequence in (1, 2):
        row = {field: "" for field in CONTRACT_FIELDS["tight_deadband_decisions_v1"]}
        row.update(
            record_type="TDB",
            schema_version="1",
            decision_sequence=str(sequence),
            estimate_id=f"est:cx317:selected600:{sequence:06d}",
            decision_timestamp_ticks=str(32_000_000 + sequence * 9_600_000_000),
            time_domain="rp2040_timer0",
            capture_session="1",
            dac_epoch="1",
            integer_edge_error_counts="-6",
            absolute_edge_error_counts="6",
            state_before="REQUALIFY_OUTSIDE" if sequence == 1 else "OUTSIDE",
            state_after="OUTSIDE",
            entry_counter="0",
            release_counter="0",
            transition="true" if sequence == 1 else "false",
            frequency_controller_eligible="true",
            requalified="true" if sequence == 1 else "false",
            requalification_reason=(
                "dac_epoch_changed_requalify" if sequence == 1 else ""
            ),
            historical_v2_inside="false",
            symmetric_two_count_inside="false",
            policy_id="CX318_STAGE5_TIGHT_HYSTERETIC_COUNTS_V1",
            policy_sha256="352daed21b3063c7d58dd8b266f3639f3cbed2500ff59fd2c530243727a5bb3a",
            actionable="false",
            actuation_authorized="false",
            authorization_consumed="false",
            reason_codes="outside_loose_evidence",
        )
        tdb.append(row)
    hybrid = {
        field: "" for field in CONTRACT_FIELDS["hybrid_preview_decisions_v1"]
    }
    hybrid.update(
        record_type="HPR",
        schema_version="1",
        preview_sequence="1",
        candidate_id="p21600_cap1_v2",
        candidate_configuration_sha256="3f0fe4ae2806ab0c9669d8b29b0ce62af897df5e14a56ea273057904de619e76",
        phase_estimator_id="CX318_RELATIVE_PHASE_RAW_PLUS_SELECTED600_V1",
        phase_estimator_configuration_sha256="449c828d2affeff858eb91535e81da0bc9c44840369d741dc1f917a8d662acb4",
        frequency_estimator_id="cx317_selected_600s_nonoverlap_v1",
        frequency_estimator_configuration_sha256="5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c",
        configuration_sha256="3f0fe4ae2806ab0c9669d8b29b0ce62af897df5e14a56ea273057904de619e76",
        phase_epoch="1",
        observation_sequence="1",
        dac_epoch="1",
        decision_timestamp_ticks="16000000",
        time_domain="rp2040_timer0",
        source_phase_estimate="PHE:1:1",
        source_frequency_estimate="unavailable",
        raw_relative_phase_cycles="0",
        modeled_relative_phase_cycles="0.000000000000000",
        phase_bias_hz="0.000000000000000",
        actual_applied_code="43008",
        shadow_code_before="43008",
        shadow_code_after="43008",
        counterfactual_code="43008",
        band_state_before="OUTSIDE",
        band_state_after="OUTSIDE",
        preview_state="RECOVER_PREVIEW",
        decision_reason="frequency_support_or_decision_cadence_hold",
        frequency_observation_event="false",
        counterfactual_decision="false",
        counterfactual_correction="false",
        step_limited="false",
        range_clamped="false",
        correction_count="0",
        cumulative_movement_codes="0",
        alternating_correction_count="0",
        modeled_not_observed_after_divergence="false",
        uncertainty_status="unavailable",
        actionable="false",
        actuation_authorized="false",
        authorization_consumed="false",
    )
    ordered: list[tuple[dict[str, str], str]] = [
        *((row, "raw_events_v1") for row in raw),
        *((row, "count_observations_v1") for row in counts),
        *((row, "health_v1") for row in health),
        (dac, "dac_steps_v1"),
        (hybrid, "hybrid_preview_decisions_v1"),
        *((row, "estimates_v2") for row in estimates),
        *((row, "tight_deadband_decisions_v1") for row in tdb),
    ]
    return [_line(row, contract) for row, contract in ordered]


def _manifest(run_dir: Path, bundle_path: Path, bundle: dict[str, Any], device: str) -> None:
    files = default_csv_files()
    evidence = [
        str(EVENTS),
        str(STATE),
        "reports/capture_device_state.json",
        "reports/range_spanning_analysis_v1.json",
        "reports/range_spanning_seal_v1.json",
        "COMPLETE",
    ]
    value = {
        "schema_version": 1,
        "template": False,
        "run_id": run_dir.name,
        "stage": "CX319_RANGE_SPANNING_PART_A_REHEARSAL",
        "compatibility_floor": "CX319_EVIDENCE_EPOCH_1",
        "board": "rehearsal_pty",
        "capture_mode": "accelerated_real_capture_device_pty",
        "cx319": {"profile_id": "cx319_range_map_part_a"},
        "actionable": False,
        "actuation_authorized": False,
        "host": {"serial_device": device, "baud": 115200},
        "bundle": {
            "path": str(bundle_path),
            "sha256": sha256_file(bundle_path),
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "policy": {
            "sha256": sha256_file(ROOT / "profiles/discipline/cx319_stabilized_tight_deadband_v1.json")
        },
        "domains": [
            {
                "name": "rp2040_timer0",
                "nominal_hz": 16_000_000,
                "counter_width_bits": 36,
                "modulus_ticks": 68_719_476_736,
                "rollover": "modular_forward",
                "maximum_unambiguous_forward_ticks": 34_359_738_368,
            },
            {"name": "h1_cx317_ocxo_10mhz", "nominal_hz": 10_000_000},
        ],
        "channels": [
            {"channel_id": 1, "role": "authoritative_d14_pps_reference", "record_family": "raw_events_v1"},
            {"channel_id": 2, "role": "authoritative_d8_count", "record_family": "count_observations_v1"},
        ],
        "contracts": {
            entry["contract"]: 2 if entry["contract"] == "estimates_v2" else 1
            for entry in files
        },
        "files": files,
        "expected_artifacts": [
            *(entry["path"] for entry in files if not entry.get("optional")),
            "raw/serial.log",
            *evidence,
        ],
        "evidence_artifacts": evidence,
    }
    _atomic_new_json(run_dir / "run_manifest.json", value)


def _read_until(master: int, expected: bytes, timeout_s: float = 5.0) -> bytes:
    deadline = time.monotonic() + timeout_s
    observed = b""
    while time.monotonic() < deadline:
        readable, _, _ = select.select([master], [], [], 0.1)
        if not readable:
            continue
        observed += os.read(master, 4096)
        if expected in observed:
            return observed
    raise TimeoutError(f"did not observe emulated firmware command {expected!r}: {observed!r}")


def run(*, bundle_path: Path, output_dir: Path) -> dict[str, Any]:
    bundle_path = bundle_path.resolve()
    bundle = validate_bundle(bundle_path)
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"rehearsal output must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = output_dir / "run"
    transition_dir = output_dir / "transition"
    control_dir = output_dir / "carrier"
    run_dir.mkdir()
    (run_dir / "reports").mkdir()
    master, slave = pty.openpty()
    device = os.ttyname(slave)
    os.close(slave)
    _manifest(run_dir, bundle_path, bundle, device)
    normal_fifo = run_dir / "control/normal_commands.fifo"
    emergency_fifo = run_dir / "control/emergency_abort.fifo"
    capture = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "host.otis_tools.capture_device",
            "--device",
            device,
            "--run-dir",
            str(run_dir),
            "--duration-s",
            "120",
            "--status-interval",
            "1",
            "--command-fifo",
            str(normal_fifo),
            "--emergency-command-fifo",
            str(emergency_fifo),
            "--normal-command-max-age-s",
            "2",
            "--segment-control-dir",
            str(control_dir),
            "--segment-capability",
            "cx319-range-spanning-rehearsal",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not _capture_state_ready(run_dir, capture.pid):
            time.sleep(0.05)
        if not _capture_state_ready(run_dir, capture.pid):
            raise RuntimeError("capture_device did not establish rehearsal carrier")
        send_timestamped_command_to_fifo(normal_fifo, "CONFIG?")
        _read_until(master, b"CONFIG?\n")
        send_timestamped_command_to_fifo(normal_fifo, "DAC?")
        _read_until(master, b"DAC?\n")
        send_timestamped_command_to_fifo(normal_fifo, "DAC SET 0xA800")
        _read_until(master, b"DAC SET 0xA800\n")
        for record in _records():
            os.write(master, record)
            time.sleep(0.005)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            tdb_path = run_dir / "csv/tight_deadband_decisions_v1.csv"
            if tdb_path.is_file() and len(tdb_path.read_text().splitlines()) >= 3:
                break
            time.sleep(0.05)
        point = {
            "point_index": 0,
            "code": 43008,
            "dac_sequence": 1,
            "dac_epoch": 1,
            "tdb_sequences": [1, 2],
        }
        _append_event(run_dir / EVENTS, {"event": "point_completed", **point})
        _replace_json(
            run_dir / STATE,
            {"schema_version": 1, "tool": TOOL_ID, "completed_points": [point], "terminal": None},
        )
        transport = _inject_transport_fault(
            capture_pid=capture.pid,
            device=device,
            run_dir=run_dir,
            normal_fifo=normal_fifo,
            emergency_fifo=emergency_fifo,
        )
        _read_until(master, b"ACTIVE ABORT\n")
        prepare_transition(run_dir / "run_manifest.json", transition_dir)
        rotation = request_rotation(
            control_dir=control_dir,
            capability="cx319-range-spanning-rehearsal",
            to_run=transition_dir,
            mode="transition",
            operation_id="range-spanning-rehearsal-rotation",
        )
        if rotation.get("serial_reopened") is not False:
            raise RuntimeError("logical rotation reopened the serial device")
    finally:
        if capture.poll() is None:
            capture.send_signal(signal.SIGINT)
        capture_output, _ = capture.communicate(timeout=15)
        os.close(master)
    if capture.returncode != 0:
        raise RuntimeError(f"capture_device rehearsal failed: {capture_output[-4000:]}")
    terminal = {
        "event": "terminal",
        "result": "healthy_stop",
        "reason": "finite_wall_deadline_before_next_point",
        "completed_point_count": 1,
    }
    _append_event(run_dir / EVENTS, terminal)
    state = json.loads((run_dir / STATE).read_text(encoding="utf-8"))
    state["terminal"] = terminal
    _replace_json(run_dir / STATE, state)
    _write_complete(run_dir, terminal)
    analysis = analyze(
        bundle_path=bundle_path,
        run_dir=run_dir,
        output_path=run_dir / "reports/range_spanning_analysis_v1.json",
        seal_path=run_dir / "reports/range_spanning_seal_v1.json",
    )
    if analysis["status"] != "passed":
        raise RuntimeError(f"actual range analyzer rejected rehearsal: {analysis['failures']}")
    create_evidence_snapshot(run_dir)
    with tempfile.TemporaryDirectory(prefix="range-spanning-registration-") as temp:
        index = Path(temp) / "evidence_index_v1.json"
        registration = register_package(
            index_path=index,
            package_path=run_dir,
            source_revision=bundle["firmware"]["git_commit"],
            build_identity=bundle["firmware"]["build_manifest"]["sha256"],
            profile_identity="cx319_range_map_part_a",
            attempt_classification="successful_rehearsal",
            result_or_failure_reason="CX319 range-spanning operational rehearsal passed",
            analyzer_identity=sha256_file(Path(__file__).with_name("range_spanning_analyze.py")),
        )
        validation = validate_index(index)
    run_identity = package_identity(run_dir)
    unsigned = {
        "schema_version": 1,
        "result_type": RESULT_TYPE,
        "tool": TOOL_ID,
        "status": "passed",
        "bundle_sha256": bundle["bundle_sha256"],
        "hardware_operations": {"serial_opens": 0, "firmware_flashes": 0, "dac_writes": 0},
        "real_boundaries": {
            "capture_device_process_and_pty_serial": True,
            "timestamped_normal_command_fifo": True,
            "exact_dac_command_and_ack_parser": True,
            "domain_rollover_parser_and_validator": True,
            "selected_estimate_to_tdb_analyzer": True,
            "hybrid_same_code_epoch_zero_authority": True,
            "normal_fifo_obstruction": transport["normal_fifo_saturated"],
            "independent_priority_abort": transport["priority_abort_observed_in_capture"],
            "continuous_same_pid_rotation": rotation["serial_reopened"] is False,
            "actual_analyzer_and_seal": True,
            "actual_temporary_registration": validation["valid"] is True,
        },
        "unexercised_physical_boundaries": [
            "RP2040 USB CDC and cross-core runtime",
            "AD5693R I2C write and physical plant",
            "D14 PPS and D8 oscillator capture",
        ],
        "physical_boundary_coverage": (
            "deterministic firmware harness plus mandatory live prewrite and first-application gates"
        ),
        "transport_report": transport,
        "rotation_response": rotation,
        "analysis_sha256": analysis["analysis_sha256"],
        "run_content_sha256": run_identity["content_sha256"],
        "registration_content_sha256": registration["content_sha256"],
    }
    result = {**unsigned, "result_sha256": canonical_sha256(unsigned)}
    result_path = output_dir / "range_spanning_operational_rehearsal_result_v1.json"
    _atomic_new_json(result_path, result)
    seal_unsigned = {
        "schema_version": 1,
        "seal_type": SEAL_TYPE,
        "tool": TOOL_ID,
        "status": "passed",
        "bundle_sha256": bundle["bundle_sha256"],
        "result_sha256": result["result_sha256"],
        "result_file_sha256": sha256_file(result_path),
    }
    _atomic_new_json(
        output_dir / "range_spanning_operational_rehearsal_seal_v1.json",
        {**seal_unsigned, "seal_sha256": canonical_sha256(seal_unsigned)},
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run(bundle_path=args.bundle, output_dir=args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
