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
from .range_spanning_run import (
    EVENTS,
    STATE,
    _adaptive_point_rows,
    _append_event,
    _point_tdb_rows,
    _prewrite_ready,
    _replace_json,
    _write_complete,
)
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


def _records(
    bundle: dict[str, Any], *, point_index: int = 0
) -> list[bytes]:
    modulus = RP2040_TIMER0_MICROS_WRAP_TICKS
    code = int(bundle["part_a_segment"]["survey_prefix"][point_index])
    prior_epoch = int(
        bundle.get("entry", {}).get("expected_live_state", {}).get("dac_epoch", 0)
    )
    epoch = prior_epoch + point_index + 1
    decision_base = (0, 2, 6)[point_index]
    observation_counts = (
        (-6, -6)
        if point_index == 0
        else ((0, 0, 0, 0) if point_index == 1 else (-2, -3, -2, -3, -2, -3))
    )
    continuation = bundle["entry"]["mode"] == "state_preserving_running_attach"
    raw_ticks = (
        (80_000_000, 96_000_000, 112_000_000)
        if continuation
        else (modulus - 16_000_000, 0, 16_000_000)
    )
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
        for index, ticks in enumerate(raw_ticks, start=10)
    ] if point_index == 0 else []
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
            (
                ((64_000_000, 80_000_000), (80_000_000, 96_000_000))
                if continuation
                else ((modulus - 16_000_000, 0), (0, 16_000_000))
            ),
            start=6,
        )
    ] if point_index == 0 else []
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
            (("partition_fault", "none"), ("fail_static", "false")), start=100
        )
    ] if point_index == 0 else []
    dac = {
        "record_type": "DAC",
        "schema_version": "1",
        "seq": str(point_index + 1),
        "elapsed_ms": "1000",
        "step_index": "-1",
        "dac_code_requested": str(code),
        "dac_code_applied": str(code),
        "dac_code_clamped": "0",
        "dac_voltage_measured_v": "",
        "ocxo_tune_voltage_measured_v": "",
        "dwell_ms": "0",
        "event": "manual_apply",
        "flags": "0",
    }
    estimates: list[dict[str, str]] = []
    for offset, count in enumerate(observation_counts, start=1):
        sequence = decision_base + offset
        row = {field: "" for field in CONTRACT_FIELDS["estimates_v2"]}
        row.update(
            record_type="EST",
            schema_version="2",
            estimate_seq=str(sequence),
            estimate_id=f"est:cx317:selected600:{sequence:06d}",
            estimator_timestamp_ticks=str(
                (32_000_000 + sequence * 9_600_000_000) % modulus
            ),
            time_domain="rp2040_timer0",
            source_count_seq=str(sequence),
            source_count_ref=f"rehearsal:CNT:{sequence}",
            source_reference_first_seq=str(sequence),
            source_reference_last_seq=str(sequence + 600),
            source_status_refs="rehearsal:STS:1",
            source_dac_ref=f"rehearsal:DAC:{point_index + 1}",
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
    for offset, count in enumerate(observation_counts, start=1):
        sequence = decision_base + offset
        row = {field: "" for field in CONTRACT_FIELDS["tight_deadband_decisions_v1"]}
        if point_index == 0:
            state_before = "REQUALIFY_OUTSIDE" if offset == 1 else "OUTSIDE"
            state_after = "OUTSIDE"
            transition = offset == 1
            entry_counter = 0
        elif point_index == 1:
            state_before = "REQUALIFY_OUTSIDE" if offset <= 2 else "TIGHT_INSIDE"
            state_after = "REQUALIFY_OUTSIDE" if offset == 1 else "TIGHT_INSIDE"
            transition = offset == 2
            entry_counter = 1 if offset == 1 else 0
        else:
            state_before = "REQUALIFY_OUTSIDE"
            state_after = "REQUALIFY_OUTSIDE"
            transition = False
            entry_counter = 1 if abs(count) <= 2 else 0
        row.update(
            record_type="TDB",
            schema_version="1",
            decision_sequence=str(sequence),
            estimate_id=f"est:cx317:selected600:{sequence:06d}",
            decision_timestamp_ticks=str(
                (32_000_000 + sequence * 9_600_000_000) % modulus
            ),
            time_domain="rp2040_timer0",
            capture_session="1",
            dac_epoch=str(epoch),
            integer_edge_error_counts=str(count),
            absolute_edge_error_counts=str(abs(count)),
            state_before=state_before,
            state_after=state_after,
            entry_counter=str(entry_counter),
            release_counter="0",
            transition="true" if transition else "false",
            frequency_controller_eligible="true",
            requalified="true" if offset == 1 else "false",
            requalification_reason=(
                "dac_epoch_changed_requalify" if offset == 1 else ""
            ),
            historical_v2_inside="true" if abs(count) <= 3 else "false",
            symmetric_two_count_inside="true" if abs(count) <= 2 else "false",
            policy_id="CX318_STAGE5_TIGHT_HYSTERETIC_COUNTS_V1",
            policy_sha256="352daed21b3063c7d58dd8b266f3639f3cbed2500ff59fd2c530243727a5bb3a",
            actionable="false",
            actuation_authorized="false",
            authorization_consumed="false",
            reason_codes=(
                "tight_entry_confirmed" if abs(count) <= 2 else "outside_loose_evidence"
            ),
        )
        tdb.append(row)
    hybrid = {
        field: "" for field in CONTRACT_FIELDS["hybrid_preview_decisions_v1"]
    }
    hybrid.update(
        record_type="HPR",
        schema_version="1",
        preview_sequence=str(epoch),
        candidate_id="p21600_cap1_v2",
        candidate_configuration_sha256="3f0fe4ae2806ab0c9669d8b29b0ce62af897df5e14a56ea273057904de619e76",
        phase_estimator_id="CX318_RELATIVE_PHASE_RAW_PLUS_SELECTED600_V1",
        phase_estimator_configuration_sha256="449c828d2affeff858eb91535e81da0bc9c44840369d741dc1f917a8d662acb4",
        frequency_estimator_id="cx317_selected_600s_nonoverlap_v1",
        frequency_estimator_configuration_sha256="5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c",
        configuration_sha256="3f0fe4ae2806ab0c9669d8b29b0ce62af897df5e14a56ea273057904de619e76",
        phase_epoch="1",
        observation_sequence="1",
        dac_epoch=str(epoch),
        decision_timestamp_ticks=("96000000" if continuation else "16000000"),
        time_domain="rp2040_timer0",
        source_phase_estimate="PHE:1:1",
        source_frequency_estimate="unavailable",
        raw_relative_phase_cycles="0",
        modeled_relative_phase_cycles="0.000000000000000",
        phase_bias_hz="0.000000000000000",
        actual_applied_code=str(code),
        shadow_code_before=str(code),
        shadow_code_after=str(code),
        counterfactual_code=str(code),
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


def _attachment_records(bundle: dict[str, Any]) -> list[bytes]:
    entry = bundle.get("entry", {})
    if entry.get("mode") != "state_preserving_running_attach":
        return []
    live = entry["expected_live_state"]
    modulus = RP2040_TIMER0_MICROS_WRAP_TICKS
    counts = [
        {
            "record_type": "CNT",
            "schema_version": "1",
            "count_seq": str(index),
            "channel_id": "2",
            "gate_open_ticks": str((index - 1) * 16_000_000),
            "gate_close_ticks": str(index * 16_000_000),
            "gate_domain": "rp2040_timer0",
            "counted_edges": "10000000",
            "source_edge": "R",
            "source_domain": "h1_cx317_ocxo_10mhz",
            "flags": "16",
        }
        for index in range(1, 6)
    ]
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
        for index, ticks in enumerate(
            (
                modulus - 16_000_000,
                0,
                16_000_000,
                32_000_000,
                48_000_000,
                64_000_000,
            ),
            start=1,
        )
    ]
    identities = [
        ("build", "profile_id", "cx319_range_map_part_a"),
        ("firmware", "git_commit", bundle["firmware"]["git_commit"]),
        ("firmware", "source_hash", bundle["firmware"]["source_sha256"]),
        ("firmware", "config_hash", bundle["firmware"]["configuration_sha256"]),
        ("build", "invocation_id", bundle["firmware"]["build_invocation_id"]),
        ("gnss_receiver", "identity_stable", "true"),
        ("gnss_receiver", "metadata_control_eligible", "true"),
        ("gnss_receiver", "raw_pps_control_eligible", "true"),
        ("pps_d14", "rejected_short_count", "0"),
        ("pps_d14", "rejected_long_count", "0"),
        ("pps_gate", "pps_interval_anomaly_count", "0"),
        ("dual_core", "partition_fault", "none"),
        ("dual_core", "fail_static", "false"),
        ("dual_core", "service_publish_failures", "0"),
        ("dual_core", "telemetry_dropped", "0"),
        ("dac", "initialized", "true"),
        ("dac", "applied_code_known", "true"),
        ("dac", "last_write_ok", "true"),
        ("dac", "last_requested_code", live["applied_code_hex"]),
        ("dac", "last_applied_code", live["applied_code_hex"]),
        ("cx318_preview", "applied_code", live["applied_code_hex"]),
        ("cx318_preview", "dac_epoch", str(live["dac_epoch"])),
    ]
    health = [
        {
            "record_type": "STS",
            "schema_version": "1",
            "status_seq": str(index),
            "timestamp_ticks": str(index * 1000),
            "status_domain": "rp2040_timer0",
            "component": component,
            "status_key": key,
            "status_value": value,
            "severity": "INFO",
            "flags": "0",
        }
        for index, (component, key, value) in enumerate(identities, start=1)
    ]
    tdb = {field: "" for field in CONTRACT_FIELDS["tight_deadband_decisions_v1"]}
    tdb.update(
        record_type="TDB",
        schema_version="1",
        decision_sequence="0",
        estimate_id="est:cx317:selected600:000000",
        decision_timestamp_ticks="64000000",
        time_domain="rp2040_timer0",
        capture_session="1",
        dac_epoch=str(live["dac_epoch"]),
        integer_edge_error_counts="2",
        absolute_edge_error_counts="2",
        state_before=live["band_state"],
        state_after=live["band_state"],
        entry_counter="2",
        release_counter="0",
        transition="false",
        frequency_controller_eligible="true",
        requalified="true",
        requalification_reason="dac_epoch_changed_requalify",
        historical_v2_inside="true",
        symmetric_two_count_inside="true",
        policy_id="CX318_STAGE5_TIGHT_HYSTERETIC_COUNTS_V1",
        policy_sha256="352daed21b3063c7d58dd8b266f3639f3cbed2500ff59fd2c530243727a5bb3a",
        actionable="false",
        actuation_authorized="false",
        authorization_consumed="false",
        reason_codes="tight_entry_confirmed",
    )
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
        dac_epoch=str(live["dac_epoch"]),
        decision_timestamp_ticks="64000000",
        time_domain="rp2040_timer0",
        source_phase_estimate="PHE:1:1",
        source_frequency_estimate="unavailable",
        raw_relative_phase_cycles="0",
        modeled_relative_phase_cycles="0.000000000000000",
        phase_bias_hz="0.000000000000000",
        actual_applied_code=str(live["applied_code"]),
        shadow_code_before=str(live["applied_code"]),
        shadow_code_after=str(live["applied_code"]),
        counterfactual_code=str(live["applied_code"]),
        band_state_before=live["hybrid_band_state"],
        band_state_after=live["hybrid_band_state"],
        preview_state="RECOVER_PREVIEW",
        decision_reason="predecessor_state_reobserved",
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
        (hybrid, "hybrid_preview_decisions_v1"),
        (tdb, "tight_deadband_decisions_v1"),
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
        "entry": bundle["entry"],
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
        attachment_records = _attachment_records(bundle)
        for record in attachment_records:
            os.write(master, record)
            time.sleep(0.005)
        if attachment_records:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                ready, _reasons = _prewrite_ready(run_dir, bundle)
                if ready:
                    break
                time.sleep(0.05)
            ready, reasons = _prewrite_ready(run_dir, bundle)
            if not ready:
                raise RuntimeError(
                    "continuation attachment rehearsal gate failed: "
                    + "; ".join(reasons)
                )
            live = bundle["entry"]["expected_live_state"]
            _append_event(run_dir / EVENTS, {"event": "prewrite_gate_passed"})
            _append_event(
                run_dir / EVENTS,
                {
                    "event": "state_preserving_attachment_passed",
                    "predecessor_run_id": bundle["entry"]["predecessor_run_id"],
                    "applied_code": live["applied_code"],
                    "dac_epoch": live["dac_epoch"],
                    "band_state": live["band_state"],
                    "next_code": live["next_code"],
                    "firmware_flash_count": 0,
                    "board_reset_count": 0,
                },
            )
        rehearsal_point_count = (
            3 if bundle["part_a_segment"].get("point_plans") is not None else 1
        )
        completed_points: list[dict[str, Any]] = []
        prior_epoch = int(
            bundle.get("entry", {})
            .get("expected_live_state", {})
            .get("dac_epoch", 0)
        )
        prior_tdb_sequence = -1
        point_plans = bundle["part_a_segment"].get("point_plans")
        for point_index in range(rehearsal_point_count):
            code = int(bundle["part_a_segment"]["survey_prefix"][point_index])
            point_plan = (
                point_plans[point_index]
                if point_plans is not None
                else {
                    "role": "survey_point",
                    "minimum_observations": 2,
                    "maximum_observations": 2,
                }
            )
            command = f"DAC SET 0x{code:04X}"
            _append_event(
                run_dir / EVENTS,
                {
                    "event": "point_command_sent",
                    "point_index": point_index,
                    "global_point_index": int(
                        bundle["part_a_segment"].get("global_point_offset", 0)
                    )
                    + point_index,
                    "code": code,
                    "role": point_plan["role"],
                    "minimum_observations": point_plan["minimum_observations"],
                    "maximum_observations": point_plan["maximum_observations"],
                    "command": command,
                },
            )
            send_timestamped_command_to_fifo(normal_fifo, command)
            _read_until(master, (command + "\n").encode("ascii"))
            for record in _records(bundle, point_index=point_index):
                os.write(master, record)
                time.sleep(0.005)
            epoch = prior_epoch + point_index + 1
            deadline = time.monotonic() + 5
            selected_rows: list[dict[str, str]] | None = None
            observation_decision = "awaiting_minimum"
            while time.monotonic() < deadline:
                selected_rows, observation_decision = _adaptive_point_rows(
                    _point_tdb_rows(
                        run_dir,
                        after_sequence=prior_tdb_sequence,
                        epoch=epoch,
                    ),
                    minimum=int(point_plan["minimum_observations"]),
                    maximum=int(point_plan["maximum_observations"]),
                )
                if selected_rows is not None:
                    break
                time.sleep(0.05)
            if selected_rows is None:
                raise RuntimeError(
                    f"rehearsal point {point_index} did not satisfy adaptive observations"
                )
            tdb_sequences = [int(row["decision_sequence"]) for row in selected_rows]
            prior_tdb_sequence = tdb_sequences[-1]
            point = {
                "point_index": point_index,
                "global_point_index": int(
                    bundle["part_a_segment"].get("global_point_offset", 0)
                )
                + point_index,
                "code": code,
                "role": point_plan["role"],
                "minimum_observations": point_plan["minimum_observations"],
                "maximum_observations": point_plan["maximum_observations"],
                "observation_rule_decision": observation_decision,
                "dac_sequence": point_index + 1,
                "dac_epoch": epoch,
                "tdb_sequences": tdb_sequences,
            }
            completed_points.append(point)
            _append_event(run_dir / EVENTS, {"event": "point_completed", **point})
        _replace_json(
            run_dir / STATE,
            {
                "schema_version": 1,
                "tool": TOOL_ID,
                "completed_points": completed_points,
                "terminal": None,
            },
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
        "completed_point_count": len(completed_points),
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
            "adaptive_fixed_two_observation_path": (
                completed_points[0]["observation_rule_decision"] == "fixed_minimum"
            ),
            "adaptive_fixed_four_observation_path": (
                len(completed_points) < 2
                or completed_points[1]["observation_rule_decision"] == "fixed_minimum"
            ),
            "adaptive_mixed_six_observation_extension": (
                len(completed_points) < 3
                or (
                    completed_points[2]["observation_rule_decision"]
                    == "maximum_mixed_extension"
                    and len(completed_points[2]["tdb_sequences"]) == 6
                )
            ),
            "hybrid_same_code_epoch_zero_authority": True,
            "state_preserving_attachment_gate": (
                bundle["entry"]["mode"] != "state_preserving_running_attach"
                or bool(attachment_records)
            ),
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
