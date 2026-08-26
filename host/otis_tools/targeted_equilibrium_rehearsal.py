"""Rehearse the complete targeted equilibrium operational path without hardware I/O."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import pty
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
from .range_spanning_bundle import _atomic_new_json, canonical_sha256, sha256_file
from .range_spanning_rehearsal import _line, _read_until
from .range_spanning_run import (
    _append_event,
    _point_tdb_rows,
    _prewrite_ready,
    _replace_json,
    _write_complete,
)
from .run_paths import default_csv_files
from .serial_commands import send_timestamped_command_to_fifo
from .targeted_equilibrium_analyze import analyze
from .targeted_equilibrium_bundle import validate_bundle
from .targeted_equilibrium_run import (
    EVENTS,
    STATE,
    _guarded,
    _targeted_prewrite_ready,
)
from .time_domains import RP2040_TIMER0_MICROS_WRAP_TICKS


TOOL_ID = "otis_targeted_equilibrium_operational_rehearsal_v1"
RESULT_TYPE = "otis_targeted_equilibrium_operational_rehearsal_result_v1"
SEAL_TYPE = "otis_targeted_equilibrium_operational_rehearsal_seal_v1"
ROOT = Path(__file__).resolve().parents[2]


def _health_row(sequence: int, component: str, key: str, value: str) -> bytes:
    return _line(
        {
            "record_type": "STS",
            "schema_version": "1",
            "status_seq": str(sequence),
            "timestamp_ticks": str(sequence * 1000),
            "status_domain": "rp2040_timer0",
            "component": component,
            "status_key": key,
            "status_value": value,
            "severity": "INFO",
            "flags": "0",
        },
        "health_v1",
    )


def _prewrite_records(bundle: dict[str, Any]) -> list[bytes]:
    modulus = RP2040_TIMER0_MICROS_WRAP_TICKS
    records: list[bytes] = []
    for sequence in range(1, 7):
        records.append(
            _line(
                {
                    "record_type": "REF",
                    "schema_version": "1",
                    "event_seq": str(sequence),
                    "channel_id": "1",
                    "edge": "R",
                    "timestamp_ticks": str((sequence * 16_000_000) % modulus),
                    "capture_domain": "rp2040_timer0",
                    "flags": "16",
                },
                "raw_events_v1",
            )
        )
    for sequence in range(2, 7):
        records.append(
            _line(
                {
                    "record_type": "CNT",
                    "schema_version": "1",
                    "count_seq": str(sequence),
                    "channel_id": "2",
                    "gate_open_ticks": str(((sequence - 1) * 16_000_000) % modulus),
                    "gate_close_ticks": str((sequence * 16_000_000) % modulus),
                    "gate_domain": "rp2040_timer0",
                    "counted_edges": "10000000",
                    "source_edge": "R",
                    "source_domain": "h1_cx317_ocxo_10mhz",
                    "flags": "16",
                },
                "count_observations_v1",
            )
        )
    target_baud = str(bundle["gnss_live_boundary"]["target_baud"])
    identities = [
        ("build", "profile_id", "cx319_range_map_part_a"),
        ("firmware", "git_commit", bundle["firmware"]["git_commit"]),
        ("firmware", "source_hash", bundle["firmware"]["source_sha256"]),
        ("firmware", "config_hash", bundle["firmware"]["configuration_sha256"]),
        ("build", "invocation_id", bundle["firmware"]["build_invocation_id"]),
        ("gnss_receiver", "identity_stable", "true"),
        ("gnss_receiver", "metadata_control_eligible", "true"),
        ("gnss_receiver", "raw_pps_control_eligible", "true"),
        ("gnss_receiver", "link_state", "online"),
        ("gnss_receiver", "link_phase", "online"),
        ("gnss_receiver", "link_online", "true"),
        ("gnss_receiver", "configuration_confirmed", "true"),
        ("gnss_receiver", "confirmed_baud", target_baud),
        ("gnss_receiver", "last_identity_response_baud", target_baud),
        (
            "gnss_receiver",
            "output_confirmation_method",
            "pmtk314_ack_observed_exact",
        ),
        ("gnss_receiver", "last_command_ack_packet_type", "314"),
        ("gnss_receiver", "last_command_ack_flag", "3"),
        ("gnss_receiver", "output_configuration_ack_count", "1"),
        ("gnss_receiver", "output_observation_success_count", "1"),
        ("gnss_receiver", "output_observed_sentence_mask", "7"),
        ("gnss_receiver", "output_unexpected_sentence_mask", "0"),
        ("gnss_receiver", "rx_only", "true"),
        ("gnss_receiver", "configuration_failure_count", "0"),
        ("gnss_receiver", "transmit_failure_count", "0"),
        ("gnss_receiver", "link_loss_count", "0"),
        ("pps_d14", "rejected_short_count", "0"),
        ("pps_d14", "rejected_long_count", "0"),
        ("pps_gate", "pps_interval_anomaly_count", "0"),
        ("dual_core", "partition_fault", "none"),
        ("dual_core", "fail_static", "false"),
        ("dual_core", "service_publish_failures", "0"),
        ("dual_core", "telemetry_dropped", "0"),
        ("capture", "dropped_count", "0"),
        ("capture", "pps_count_boundary_dropped_count", "0"),
    ]
    records.extend(
        _health_row(index, component, key, value)
        for index, (component, key, value) in enumerate(identities, start=1)
    )
    hybrid = {field: "" for field in CONTRACT_FIELDS["hybrid_preview_decisions_v1"]}
    hybrid.update(
        record_type="HPR",
        schema_version="1",
        preview_sequence="0",
        candidate_id="p21600_cap1_v2",
        candidate_configuration_sha256="3f0fe4ae2806ab0c9669d8b29b0ce62af897df5e14a56ea273057904de619e76",
        phase_estimator_id="CX318_RELATIVE_PHASE_RAW_PLUS_SELECTED600_V1",
        phase_estimator_configuration_sha256="449c828d2affeff858eb91535e81da0bc9c44840369d741dc1f917a8d662acb4",
        frequency_estimator_id="cx317_selected_600s_nonoverlap_v1",
        frequency_estimator_configuration_sha256="5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c",
        configuration_sha256="3f0fe4ae2806ab0c9669d8b29b0ce62af897df5e14a56ea273057904de619e76",
        phase_epoch="1",
        observation_sequence="1",
        dac_epoch="0",
        decision_timestamp_ticks="96000000",
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
    records.append(_line(hybrid, "hybrid_preview_decisions_v1"))
    return records


def _dwell_records(
    *, dwell: dict[str, Any], reference_start: int, decision_start: int
) -> tuple[list[bytes], int, list[int]]:
    modulus = RP2040_TIMER0_MICROS_WRAP_TICKS
    index = int(dwell["index"])
    epoch = index + 1
    code = int(dwell["code"])
    records: list[bytes] = []
    dac = {
        "record_type": "DAC",
        "schema_version": "1",
        "seq": str(epoch),
        "elapsed_ms": str(1_800_000 + index * 2_700_000),
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
    records.append(_line(dac, "dac_steps_v1"))
    hybrid = {field: "" for field in CONTRACT_FIELDS["hybrid_preview_decisions_v1"]}
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
        phase_epoch=str(epoch),
        observation_sequence="1",
        dac_epoch=str(epoch),
        # The accelerated rehearsal emits one application-propagation record
        # per dwell. Keep that synthetic HPR stream unambiguously ordered in
        # its declared wrapping domain; the full 2,700-second chronology is
        # separately exercised by the raw D14/D8 records below.
        decision_timestamp_ticks=str(96_000_000 + epoch * 16_000_000),
        time_domain="rp2040_timer0",
        source_phase_estimate=f"PHE:{epoch}:1",
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
    records.append(_line(hybrid, "hybrid_preview_decisions_v1"))

    # Exercise the exact 900-second excluded interval plus three contiguous,
    # non-overlapping 600-second supports in accelerated serial time.
    count_error = -3 if code == 43046 else (3 if code == 43094 else 0)
    final_reference = reference_start + 2700
    for sequence in range(reference_start + 1, final_reference + 1):
        records.append(
            _line(
                {
                    "record_type": "REF",
                    "schema_version": "1",
                    "event_seq": str(sequence),
                    "channel_id": "1",
                    "edge": "R",
                    "timestamp_ticks": str((sequence * 16_000_000) % modulus),
                    "capture_domain": "rp2040_timer0",
                    "flags": "16",
                },
                "raw_events_v1",
            )
        )
        within_scientific = sequence > reference_start + 900
        support_offset = sequence - (reference_start + 900)
        edge_adjustment = (
            count_error
            if within_scientific and support_offset in {600, 1200, 1800}
            else 0
        )
        records.append(
            _line(
                {
                    "record_type": "CNT",
                    "schema_version": "1",
                    "count_seq": str(sequence),
                    "channel_id": "2",
                    "gate_open_ticks": str(((sequence - 1) * 16_000_000) % modulus),
                    "gate_close_ticks": str((sequence * 16_000_000) % modulus),
                    "gate_domain": "rp2040_timer0",
                    "counted_edges": str(10_000_000 + edge_adjustment),
                    "source_edge": "R",
                    "source_domain": "h1_cx317_ocxo_10mhz",
                    "flags": "16",
                },
                "count_observations_v1",
            )
        )

    tdb_sequences: list[int] = []
    for support_index in range(3):
        first = reference_start + 900 + support_index * 600
        last = first + 600
        decision = decision_start + support_index
        estimate_id = f"est:cx317:selected600:{decision:06d}"
        estimate = {field: "" for field in CONTRACT_FIELDS["estimates_v2"]}
        estimate.update(
            record_type="EST",
            schema_version="2",
            estimate_seq=str(decision),
            estimate_id=estimate_id,
            estimator_timestamp_ticks=str((last * 16_000_000) % modulus),
            time_domain="rp2040_timer0",
            source_count_seq=str(last),
            source_count_ref=f"rehearsal:CNT:{last}",
            source_reference_first_seq=str(first),
            source_reference_last_seq=str(last),
            source_status_refs="rehearsal:STS:1",
            source_dac_ref=f"rehearsal:DAC:{epoch}",
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
            frequency_observation_hz=f"{10_000_000 + count_error / 600:.12f}",
            accepted_sample_count="600",
            estimator_confidence="unavailable",
            frequency_estimate_hz=f"{10_000_000 + count_error / 600:.12f}",
            frequency_error_hz=f"{count_error / 600:.12f}",
            uncertainty_status="unavailable",
            uncertainty_reason_codes="uncertainty_components_unavailable",
            correlation_policy="not_combined_missing_components",
            uncertainty_model_ref="unavailable:combined_uncertainty",
            drift_enabled="false",
            preview_eligibility="true",
            eligibility_reason_codes="eligible",
        )
        records.append(_line(estimate, "estimates_v2"))
        tdb = {
            field: "" for field in CONTRACT_FIELDS["tight_deadband_decisions_v1"]
        }
        tdb.update(
            record_type="TDB",
            schema_version="1",
            decision_sequence=str(decision),
            estimate_id=estimate_id,
            decision_timestamp_ticks=str((last * 16_000_000) % modulus),
            time_domain="rp2040_timer0",
            capture_session="1",
            dac_epoch=str(epoch),
            integer_edge_error_counts=str(count_error),
            absolute_edge_error_counts=str(abs(count_error)),
            state_before="REQUALIFY_OUTSIDE" if support_index == 0 else "OUTSIDE",
            state_after="OUTSIDE",
            entry_counter="0",
            release_counter="0",
            transition="true" if support_index == 0 else "false",
            frequency_controller_eligible="true",
            requalified="true" if support_index == 0 else "false",
            requalification_reason=(
                "dac_epoch_changed_requalify" if support_index == 0 else ""
            ),
            historical_v2_inside="true" if abs(count_error) <= 3 else "false",
            symmetric_two_count_inside="true" if abs(count_error) <= 2 else "false",
            policy_id="CX318_STAGE5_TIGHT_HYSTERETIC_COUNTS_V1",
            policy_sha256="352daed21b3063c7d58dd8b266f3639f3cbed2500ff59fd2c530243727a5bb3a",
            actionable="false",
            actuation_authorized="false",
            authorization_consumed="false",
            reason_codes="outside_loose_evidence",
        )
        records.append(_line(tdb, "tight_deadband_decisions_v1"))
        tdb_sequences.append(decision)
    return records, final_reference, tdb_sequences


def _manifest(run_dir: Path, bundle_path: Path, bundle: dict[str, Any], device: str) -> None:
    files = default_csv_files()
    evidence = [
        str(EVENTS),
        str(STATE),
        "reports/capture_device_state.json",
        "reports/targeted_equilibrium_analysis_v1.json",
        "reports/targeted_equilibrium_seal_v1.json",
        "COMPLETE",
    ]
    value = {
        "schema_version": 1,
        "template": False,
        "run_id": run_dir.name,
        "stage": "CX319_TARGETED_EQUILIBRIUM_CHARACTERIZATION_REHEARSAL",
        "compatibility_floor": "CX319_EVIDENCE_EPOCH_1",
        "board": "rehearsal_pty",
        "capture_mode": "accelerated_real_capture_device_pty",
        "cx319": {"profile_id": "cx319_range_map_part_a"},
        "actionable": False,
        "actuation_authorized": False,
        "closed_loop_control": False,
        "host": {"serial_device": device, "baud": 115200},
        "bundle": {
            "path": str(bundle_path),
            "sha256": sha256_file(bundle_path),
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "entry": bundle["entry"],
        "policy": {
            "sha256": sha256_file(
                ROOT / "profiles/discipline/cx319_stabilized_tight_deadband_v1.json"
            )
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
            item["contract"]: 2 if item["contract"] == "estimates_v2" else 1
            for item in files
        },
        "files": files,
        "expected_artifacts": [
            *(item["path"] for item in files if not item.get("optional")),
            "raw/serial.log",
            *evidence,
        ],
        "evidence_artifacts": evidence,
    }
    _atomic_new_json(run_dir / "run_manifest.json", value)


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
            "180",
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
            "targeted-equilibrium-rehearsal",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    completed: list[dict[str, Any]] = []
    transient_hold_exercised = False
    recurrent_dwell_holds_exercised = 0
    terminal_transient_snapshot_exercised = False
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
        for record in _prewrite_records(bundle):
            os.write(master, record)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not _targeted_prewrite_ready(run_dir, bundle)[0]:
            time.sleep(0.05)
        ready, reasons = _targeted_prewrite_ready(run_dir, bundle)
        if not ready:
            raise RuntimeError("rehearsal prewrite gate failed: " + "; ".join(reasons))
        _append_event(run_dir / EVENTS, {"event": "prewrite_gate_passed"})

        # Reproduce the attempt-3 escaped boundary through the actual capture
        # parser and targeted runtime guard: one transient metadata
        # disqualification must hold progress, then the next qualified status
        # must resume it.  Identity/configuration contradictions remain covered
        # by the focused runner regression.
        if bundle["gnss_live_boundary"].get("runtime_qualification_policy"):
            transient_sequence = 50_000
            os.write(
                master,
                _health_row(
                    transient_sequence,
                    "gnss_receiver",
                    "metadata_control_eligible",
                    "false",
                ),
            )
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and _targeted_prewrite_ready(
                run_dir, bundle
            )[0]:
                time.sleep(0.05)
            if _guarded(run_dir, bundle, lambda: "advanced") is not False:
                raise RuntimeError(
                    "transient GNSS health did not hold the runtime path"
                )
            os.write(
                master,
                _health_row(
                    transient_sequence + 1,
                    "gnss_receiver",
                    "metadata_control_eligible",
                    "true",
                ),
            )
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not _targeted_prewrite_ready(
                run_dir, bundle
            )[0]:
                time.sleep(0.05)
            if _guarded(run_dir, bundle, lambda: "advanced") != "advanced":
                raise RuntimeError(
                    "GNSS requalification did not resume the runtime path"
                )
            transient_hold_exercised = True
        _append_event(
            run_dir / EVENTS,
            {
                "event": "initial_warmup_complete",
                "minimum_elapsed_s": 1800,
                "observed_elapsed_s": 1800,
                "scheduling_domain": "accelerated_rehearsal_clock",
            },
        )
        reference = 6
        decision = 0
        for dwell in bundle["dwell_plan"]:
            index = int(dwell["index"])
            code = int(dwell["code"])
            command = f"DAC SET 0x{code:04X}"
            _append_event(
                run_dir / EVENTS,
                {
                    "event": "dwell_command_sent",
                    "dwell_index": index,
                    "label": dwell["label"],
                    "code": code,
                    "partition": dwell["partition"],
                    "command": command,
                },
            )
            send_timestamped_command_to_fifo(normal_fifo, command)
            _read_until(master, (command + "\n").encode("ascii"))
            runtime_policy = bool(
                bundle["gnss_live_boundary"].get("runtime_qualification_policy")
            )
            if runtime_policy:
                transient_sequence = 60_000 + index * 2
                os.write(
                    master,
                    _health_row(
                        transient_sequence,
                        "gnss_receiver",
                        "metadata_control_eligible",
                        "false",
                    ),
                )
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline and _targeted_prewrite_ready(
                    run_dir, bundle
                )[0]:
                    time.sleep(0.05)
                if _guarded(run_dir, bundle, lambda: "advanced") is not False:
                    raise RuntimeError(
                        f"rehearsal dwell {index} transient GNSS status did not hold"
                    )
            records, reference, tdb_sequences = _dwell_records(
                dwell=dwell, reference_start=reference, decision_start=decision
            )
            decision += 3
            for offset in range(0, len(records), 256):
                os.write(master, b"".join(records[offset : offset + 256]))
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                parsed = _point_tdb_rows(run_dir, after_sequence=-1, epoch=index + 1)
                if len(parsed) >= 3:
                    break
                time.sleep(0.05)
            if len(_point_tdb_rows(run_dir, after_sequence=-1, epoch=index + 1)) < 3:
                raise RuntimeError(f"rehearsal dwell {index} did not reach TDB consumer")
            if runtime_policy:
                if (
                    _guarded(
                        run_dir,
                        bundle,
                        lambda: _point_tdb_rows(
                            run_dir, after_sequence=-1, epoch=index + 1
                        ),
                    )
                    is not False
                ):
                    raise RuntimeError(
                        f"rehearsal dwell {index} advanced before GNSS requalification"
                    )
                os.write(
                    master,
                    _health_row(
                        transient_sequence + 1,
                        "gnss_receiver",
                        "metadata_control_eligible",
                        "true",
                    ),
                )
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline and not _targeted_prewrite_ready(
                    run_dir, bundle
                )[0]:
                    time.sleep(0.05)
                selected_after_requalification = _guarded(
                    run_dir,
                    bundle,
                    lambda: _point_tdb_rows(
                        run_dir, after_sequence=-1, epoch=index + 1
                    ),
                )
                if not isinstance(selected_after_requalification, list) or len(
                    selected_after_requalification
                ) < 3:
                    raise RuntimeError(
                        f"rehearsal dwell {index} did not resume with retained support"
                    )
                recurrent_dwell_holds_exercised += 1
            row = {
                "dwell_index": index,
                "label": dwell["label"],
                "code": code,
                "code_hex": f"0x{code:04X}",
                "partition": dwell["partition"],
                "history_class": dwell["history_class"],
                "dac_sequence": index + 1,
                "dac_epoch": index + 1,
                "tdb_sequences": tdb_sequences,
                "minimum_elapsed_s": 2700,
                "observed_elapsed_s": 2700,
            }
            completed.append(row)
            _append_event(run_dir / EVENTS, {"event": "dwell_completed", **row})
        if bundle["gnss_live_boundary"].get("runtime_qualification_policy"):
            os.write(
                master,
                _health_row(
                    70_000,
                    "gnss_receiver",
                    "metadata_control_eligible",
                    "false",
                ),
            )
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and _targeted_prewrite_ready(
                run_dir, bundle
            )[0]:
                time.sleep(0.05)
            if _targeted_prewrite_ready(run_dir, bundle)[0]:
                raise RuntimeError(
                    "terminal transient GNSS status did not reach the analyzer fixture"
                )
            terminal_transient_snapshot_exercised = True
        _replace_json(
            run_dir / STATE,
            {
                "schema_version": 1,
                "tool": TOOL_ID,
                "completed_dwells": completed,
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
            capability="targeted-equilibrium-rehearsal",
            to_run=transition_dir,
            mode="transition",
            operation_id="targeted-equilibrium-rehearsal-rotation",
        )
        if rotation.get("serial_reopened") is not False:
            raise RuntimeError("logical rotation reopened the serial device")
    finally:
        if capture.poll() is None:
            capture.send_signal(signal.SIGINT)
        capture_output, _ = capture.communicate(timeout=30)
        os.close(master)
    if capture.returncode != 0:
        raise RuntimeError(f"capture_device rehearsal failed: {capture_output[-4000:]}")
    terminal = {
        "event": "terminal",
        "result": "healthy_stop",
        "reason": "targeted_characterization_complete",
        "completed_dwell_count": len(completed),
        "last_confirmed_code": completed[-1]["code"],
        "automatic_restore_performed": False,
    }
    _append_event(run_dir / EVENTS, terminal)
    state = json.loads((run_dir / STATE).read_text(encoding="utf-8"))
    state["terminal"] = terminal
    _replace_json(run_dir / STATE, state)
    _write_complete(run_dir, terminal)
    analysis = analyze(
        bundle_path=bundle_path,
        run_dir=run_dir,
        output_path=run_dir / "reports/targeted_equilibrium_analysis_v1.json",
        seal_path=run_dir / "reports/targeted_equilibrium_seal_v1.json",
    )
    if analysis["evidence_status"] != "passed":
        raise RuntimeError(f"actual targeted analyzer rejected rehearsal: {analysis['failures']}")
    if terminal_transient_snapshot_exercised and not (
        analysis["gnss_output_configuration_qualification"]["status"] == "passed"
        and analysis["gnss_output_configuration_qualification"][
            "bounded_terminal_snapshot_holds"
        ]
    ):
        raise RuntimeError(
            "actual targeted analyzer did not preserve a completed acquisition "
            "across a bounded terminal GNSS snapshot hold"
        )
    create_evidence_snapshot(run_dir)
    with tempfile.TemporaryDirectory(prefix="targeted-equilibrium-registration-") as temp:
        index = Path(temp) / "evidence_index_v1.json"
        registration = register_package(
            index_path=index,
            package_path=run_dir,
            source_revision=bundle["firmware"]["git_commit"],
            build_identity=bundle["firmware"]["build_manifest"]["sha256"],
            profile_identity="cx319_range_map_part_a",
            attempt_classification="successful_rehearsal",
            result_or_failure_reason="targeted equilibrium operational rehearsal passed",
            analyzer_identity=sha256_file(
                Path(__file__).with_name("targeted_equilibrium_analyze.py")
            ),
        )
        validation = validate_index(index)
    identity = package_identity(run_dir)
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
            "all_twelve_repeated_dac_transactions": len(completed) == 12,
            "exact_1800_warmup_and_2700_dwell_scheduler_contract": True,
            "settling_exclusion_and_three_contiguous_selected600_supports": True,
            "exact_dac_ack_and_cross_epoch_consumer_parser": True,
            "bounded_transient_gnss_health_hold_and_requalification": (
                transient_hold_exercised
            ),
            "recurrent_dwell_gnss_holds_preserve_d14_d8_support": (
                recurrent_dwell_holds_exercised == len(bundle["dwell_plan"])
            ),
            "completed_acquisition_survives_terminal_transient_gnss_snapshot": (
                terminal_transient_snapshot_exercised
            ),
            "domain_rollover_parser_and_validator": True,
            "zero_frequency_phase_and_hybrid_authority": True,
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
        "analysis_sha256": analysis["analysis_sha256"],
        "recurrent_dwell_hold_count": recurrent_dwell_holds_exercised,
        "run_content_sha256": identity["content_sha256"],
        "registration_content_sha256": registration["content_sha256"],
        "transport_report": transport,
        "rotation_response": rotation,
    }
    result = {**unsigned, "result_sha256": canonical_sha256(unsigned)}
    result_path = output_dir / "targeted_equilibrium_operational_rehearsal_result_v1.json"
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
        output_dir / "targeted_equilibrium_operational_rehearsal_seal_v1.json",
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
