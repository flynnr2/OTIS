from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json

import pytest

import host.otis_tools.cx318_stage4_live_analyze as live_analyze
from host.otis_tools.cx318_hybrid_preview import load_profile as load_hybrid_profile
from host.otis_tools.cx318_relative_phase import load_profile as load_phase_profile
from host.otis_tools.cx318_stage4_firmware_parity import _boundaries, _host_outputs
from host.otis_tools.cx318_stage4_live_analyze import (
    FREQUENCY_SELECTED,
    HYBRID_SELECTED,
    PHASE_SELECTED,
    _live_parity,
    _sha256_file,
    _stage4_build_contract,
    _static_code_binding,
    _transport_and_authority_checks,
    analyze_run,
)


STATIC_CODE = 0xA828
DAC_EPOCH = 4


def _fixed(value: float | None) -> str:
    return "" if value is None else f"{value:.15f}"


def _live_rows(intervals: int = 1200):
    counter = 0xF0000000
    snapshots = []
    counts = []
    for sequence in range(1, intervals + 2):
        if sequence > 1:
            counter = (counter - 10_000_000) % (1 << 32)
        snapshots.append(
            {
                "session": "1",
                "snapshot_sequence": str(sequence),
                "cumulative_down_counter": str(counter),
                "reference_sequence": str(sequence),
                "reference_timestamp_ticks": str(sequence * 16_000_000),
                "status": "0",
                "backend": "pio_wait_cumulative_snapshot_dma_v1",
            }
        )
        counts.append(
            {
                "count_seq": str(sequence),
                "counted_edges": "10000000",
                "flags": "16",
            }
        )

    phase_profile, _ = load_phase_profile()
    hybrid_profile, _ = load_hybrid_profile()
    selected = json.loads(HYBRID_SELECTED.read_text(encoding="utf-8"))
    candidate_id = selected["selection"]["selected_candidate_id"]
    candidate = next(
        item for item in hybrid_profile["candidates"] if item["candidate_id"] == candidate_id
    )
    phase_hash = _sha256_file(PHASE_SELECTED)
    hybrid_hash = _sha256_file(HYBRID_SELECTED)
    frequency_hash = _sha256_file(FREQUENCY_SELECTED)
    outputs = _host_outputs(
        _boundaries(
            snapshots,
            counts,
            timer_hz=16_000_000,
            events=[],
            start_code=STATIC_CODE,
        ),
        nominal_edges=10_000_000,
        timer_hz=16_000_000,
        period_ns=100.0,
        phase_profile=phase_profile,
        phase_configuration_sha256=phase_hash,
        hybrid_profile=hybrid_profile,
        selected_candidate=candidate,
        start_code=STATIC_CODE,
        reset_first=True,
    )
    rph_rows = []
    phe_rows = []
    hpr_rows = []
    last_event_ticks = None
    for index, (record, _estimate, decision) in enumerate(outputs, start=1):
        ticks = round(decision.timestamp_s * 16_000_000)
        if decision.frequency_observation_event:
            last_event_ticks = ticks
        frequency_available = decision.modeled_frequency_error_hz is not None
        age = (
            (ticks - last_event_ticks) / 16_000_000
            if frequency_available and last_event_ticks is not None
            else None
        )
        rph_rows.append(
            {
                "record_type": "RPH",
                "schema_version": "1",
                "phase_epoch": str(record.phase_epoch),
                "observation_sequence": str(record.observation_sequence),
                "capture_session": str(record.capture_session),
                "opening_snapshot_sequence": str(record.opening_snapshot_sequence),
                "closing_snapshot_sequence": str(record.closing_snapshot_sequence),
                "opening_reference_sequence": str(record.opening_reference_sequence),
                "closing_reference_sequence": str(record.closing_reference_sequence),
                "dac_epoch": str(DAC_EPOCH),
                "source_backend": "pio_wait_cumulative_snapshot_dma_v1",
                "source_file_sha256": "live_stream_unsealed",
                "method_id": "CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1",
                "configuration_sha256": phase_hash,
                "interval_edges": "" if record.interval_edges is None else str(record.interval_edges),
                "edge_error_cycles": "" if record.edge_error_cycles is None else str(record.edge_error_cycles),
                "relative_phase_cycles": str(record.relative_phase_cycles),
                "relative_phase_time_ns": str(int(record.relative_phase_time_ns)),
                "qualification_state": record.qualification_state,
                "observation_age_s": "0",
                "discontinuity_reason": record.discontinuity_reason or "",
                "calibrated_uncertainty_status": "unavailable",
            }
        )
        qualification = (
            "invalid"
            if record.qualification_state == "invalid"
            else "qualified" if frequency_available else "initializing"
        )
        reason = (
            record.discontinuity_reason or "invalid_phase_input"
            if record.qualification_state == "invalid"
            else (
                "selected_600_interval_frequency_fresh"
                if decision.frequency_observation_event
                else "selected_600_interval_frequency_retained"
            )
            if frequency_available
            else "selected_600_interval_frequency_initializing"
        )
        phe_rows.append(
            {
                "record_type": "PHE",
                "schema_version": "1",
                "phase_epoch": str(record.phase_epoch),
                "observation_sequence": str(record.observation_sequence),
                "source_relative_phase_observation": f"RPH:{record.phase_epoch}:{record.observation_sequence}",
                "raw_relative_phase_cycles": str(record.relative_phase_cycles),
                "raw_relative_phase_time_ns": str(int(record.relative_phase_time_ns)),
                "filtered_relative_phase_cycles": str(record.relative_phase_cycles),
                "estimated_frequency_error_hz": _fixed(decision.observed_frequency_error_hz if frequency_available else None),
                "estimator_id": "CX318_RELATIVE_PHASE_RAW_PLUS_SELECTED600_V1",
                "configuration_sha256": phase_hash,
                "estimate_age_s": _fixed(age),
                "qualification_state": qualification,
                "uncertainty_status": "unavailable",
                "reason_codes": reason,
            }
        )
        hpr_rows.append(
            {
                "record_type": "HPR",
                "schema_version": "1",
                "preview_sequence": str(index),
                "candidate_id": candidate_id,
                "candidate_configuration_sha256": hybrid_hash,
                "phase_estimator_id": "CX318_RELATIVE_PHASE_RAW_PLUS_SELECTED600_V1",
                "phase_estimator_configuration_sha256": phase_hash,
                "frequency_estimator_id": "cx317_selected_600s_nonoverlap_v1",
                "frequency_estimator_configuration_sha256": frequency_hash,
                "configuration_sha256": hybrid_hash,
                "phase_epoch": str(record.phase_epoch),
                "observation_sequence": str(record.observation_sequence),
                "dac_epoch": str(DAC_EPOCH),
                "decision_timestamp_ticks": str(ticks),
                "time_domain": "rp2040_timer0",
                "source_phase_estimate": f"PHE:{record.phase_epoch}:{record.observation_sequence}",
                "source_frequency_estimate": f"PHE:{record.phase_epoch}:{record.observation_sequence}" if frequency_available else "unavailable",
                "raw_relative_phase_cycles": str(record.relative_phase_cycles),
                "modeled_relative_phase_cycles": _fixed(decision.modeled_relative_phase_cycles),
                "observed_frequency_error_hz": _fixed(decision.observed_frequency_error_hz),
                "modeled_frequency_error_hz": _fixed(decision.modeled_frequency_error_hz),
                "frequency_term_hz": _fixed(decision.frequency_term_hz),
                "phase_bias_hz": _fixed(decision.phase_bias_hz),
                "combined_frequency_error_hz": _fixed(decision.combined_desired_frequency_change_hz),
                "actual_applied_code": str(STATIC_CODE),
                "shadow_code_before": str(decision.shadow_code_before),
                "shadow_code_after": str(decision.shadow_code_after),
                "band_state_before": decision.band_state_before,
                "band_state_after": decision.band_state_after,
                "preview_state": decision.preview_state,
                "decision_reason": decision.decision_reason,
                "frequency_observation_event": str(decision.frequency_observation_event).lower(),
                "counterfactual_decision": str(decision.counterfactual_decision).lower(),
                "counterfactual_correction": str(decision.counterfactual_correction).lower(),
                "raw_counterfactual_delta_codes": _fixed(decision.raw_delta_codes),
                "counterfactual_delta_codes": "" if decision.limited_delta_codes is None else str(decision.limited_delta_codes),
                "counterfactual_code": str(decision.shadow_code_after),
                "step_limited": str(decision.step_limited).lower(),
                "range_clamped": str(decision.range_clamped).lower(),
                "correction_count": str(decision.correction_count),
                "cumulative_movement_codes": str(decision.cumulative_movement_codes),
                "alternating_correction_count": str(decision.alternating_correction_count),
                "modeled_not_observed_after_divergence": str(decision.modeled_not_observed_after_divergence).lower(),
                "uncertainty_status": "unavailable",
                "actionable": "false",
                "actuation_authorized": "false",
                "authorization_consumed": "false",
            }
        )
    return snapshots, counts, rph_rows, phe_rows, hpr_rows


def test_live_parity_replays_two_authoritative_frequency_events() -> None:
    snapshots, counts, rph, phe, hpr = _live_rows()

    checks, result = _live_parity(
        snapshots,
        counts,
        rph,
        phe,
        hpr,
        static_code=STATIC_CODE,
        dac_epoch=DAC_EPOCH,
    )

    assert all(check.passed for check in checks)
    assert result["mismatch_count"] == 0
    assert result["authoritative_frequency_event_count"] == 2
    assert result["duration_s"] == 1200.0


def test_live_parity_reports_bounded_field_mismatch() -> None:
    snapshots, counts, rph, phe, hpr = _live_rows(4)
    hpr[2]["phase_bias_hz"] = "0.001"

    checks, result = _live_parity(
        snapshots,
        counts,
        rph,
        phe,
        hpr,
        static_code=STATIC_CODE,
        dac_epoch=DAC_EPOCH,
    )

    assert not next(check for check in checks if check.identifier == "live_host_firmware_phase_hybrid_parity").passed
    assert result["mismatch_count"] == 1
    assert "HPR.phase_bias_hz" in " ".join(result["first_mismatches"][0]["errors"])


def test_static_code_binding_rejects_arbitrary_self_attested_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "prior.json"
    evidence.write_text('{"application":"0xA828"}\n', encoding="utf-8")
    manifest = {
        "stage4_live_preview": {
            "profile_id": "cx318_stage4_nonactuating_preview",
            "static_code": "0xA828",
            "dac_epoch": 4,
            "static_code_evidence": {
                "path": "prior.json",
                "sha256": sha256(evidence.read_bytes()).hexdigest(),
                "confirmed_code": 0xA828,
                "physical_code_status": "confirmed_exact_static_code",
                "continuous_identity_to_flash": True,
                "intervening_dac_writes": 0,
                "intervening_power_losses": 0,
            },
        }
    }

    check, result = _static_code_binding(tmp_path, manifest)
    assert not check.passed
    assert "proof schema_version" in result["reason"]


def test_static_code_binding_uses_values_derived_from_validated_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = tmp_path / "prior.json"
    evidence.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        live_analyze,
        "_validate_static_proof",
        lambda _proof: (STATIC_CODE, DAC_EPOCH, "runs/source"),
    )
    manifest = {
        "stage4_live_preview": {
            "profile_id": "cx318_stage4_nonactuating_preview",
            "static_code": STATIC_CODE,
            "dac_epoch": DAC_EPOCH,
            "static_code_evidence": {
                "path": "prior.json",
                "sha256": sha256(evidence.read_bytes()).hexdigest(),
            },
        }
    }

    check, result = _static_code_binding(tmp_path, manifest)
    assert check.passed
    assert result["static_code"] == STATIC_CODE


def _stage4_build_manifest(tmp_path: Path) -> tuple[Path, dict]:
    matrix = json.loads(
        (Path(__file__).resolve().parents[1] / "firmware/arduino/firmware_matrix.json").read_text(
            encoding="utf-8"
        )
    )
    profile = next(
        item
        for item in matrix["profiles"]
        if item["id"] == "cx318_stage4_nonactuating_preview"
    )
    defines = dict(profile["defines"])
    defines["OTIS_CX318_STAGE4_STATIC_CODE"] = f"0x{STATIC_CODE:04X}u"
    defines["OTIS_CX318_STAGE4_DAC_EPOCH"] = f"{DAC_EPOCH}u"
    build = {
        "provenance": {
            "configuration": {
                "profile_id": "cx318_stage4_nonactuating_preview",
                "defines": defines,
            }
        }
    }
    path = tmp_path / "firmware_build_manifest.json"
    path.write_text(json.dumps(build), encoding="utf-8")
    return path, build


def test_stage4_build_contract_requires_complete_rebound_matrix_profile(
    tmp_path: Path,
) -> None:
    path, _build = _stage4_build_manifest(tmp_path)
    manifest = {"firmware": {"config_id": "cx318_stage4_nonactuating_preview"}}

    check = _stage4_build_contract(
        manifest, path, static_code=STATIC_CODE, dac_epoch=DAC_EPOCH
    )

    assert check.passed


def test_stage4_build_contract_rejects_omitted_or_extra_defines(tmp_path: Path) -> None:
    path, build = _stage4_build_manifest(tmp_path)
    manifest = {"firmware": {"config_id": "cx318_stage4_nonactuating_preview"}}
    del build["provenance"]["configuration"]["defines"]["OTIS_ENABLE_ENV_SENSORS"]
    build["provenance"]["configuration"]["defines"]["OTIS_UNDECLARED_OVERRIDE"] = "1"
    path.write_text(json.dumps(build), encoding="utf-8")

    check = _stage4_build_contract(
        manifest, path, static_code=STATIC_CODE, dac_epoch=DAC_EPOCH
    )

    assert not check.passed
    assert "OTIS_ENABLE_ENV_SENSORS" in check.evidence
    assert "OTIS_UNDECLARED_OVERRIDE" in check.evidence


def _healthy_transport_inputs(tmp_path: Path):
    raw = tmp_path / "serial.log"
    raw.write_text(
        '# OTIS_HOST {"event":"capture_started"}\n'
        '# OTIS_HOST {"event":"host_command_sent","command":"CONFIG?"}\n'
        '# OTIS_HOST {"event":"capture_stopped"}\n',
        encoding="utf-8",
    )
    capture = {
        "capture_active": False,
        "serial_open": False,
        "parser_errors": 0,
        "malformed_utf8": 0,
        "reconnect_count": 0,
        "commands_rejected": 0,
        "emergency_aborts_sent": 0,
        "emergency_abort_latched": False,
        "commands_sent": 1,
    }
    values = {
        ("build", "enable_cx318_stage4_preview"): "1",
        ("build", "enable_dac_ad5693r"): "0",
        ("build", "enable_cx317_i_only_preview"): "0",
        ("build", "enable_cx317_bounded_active"): "0",
        ("cx318_preview", "actionable"): "false",
        ("cx318_preview", "actuation_authorized"): "false",
        ("cx318_preview", "authorization_consumed"): "false",
        ("cx318_preview", "initialized"): "true",
        ("dual_core", "partition_fault"): "none",
        ("dual_core", "fail_static"): "false",
        ("dual_core", "service_fault_capsule"): "clear",
        ("dual_core", "telemetry_dropped"): "0",
        ("dual_core", "service_publish_failures"): "0",
        ("dual_core", "service_take_accounting"): "successful_only",
        ("dual_core", "service_drain_budget_per_loop"): "16",
        ("dual_core", "core1_trace_sampling"): "bounded_coarse",
        ("dual_core", "core1_trace_period_ms"): "250",
        ("dual_core", "service_to_timing_depth"): "0",
        ("dual_core", "service_to_timing_high_water"): "2",
        ("dual_core", "cx318_preview_depth"): "0",
        ("dual_core", "cx318_preview_high_water"): "2",
    }
    for component, key in (
        ("capture", "dropped_count"),
        ("capture", "pps_count_boundary_dropped_count"),
        ("capture", "error_flags"),
        ("pps_gate", "boundary_ring_dropped_count"),
        ("pps_gate", "rejected_window_count"),
        ("pps_gate", "missing_pps_count"),
        ("pps_gate", "pps_interval_anomaly_count"),
        ("pps_gate", "count_saturated_count"),
        ("pps_gate", "boundary_sequence_gap_count"),
        ("pps_gate", "boundary_sequence_duplicate_count"),
        ("pps_gate", "boundary_overflow_count"),
        ("pps_gate", "counter_snapshot_invalid_count"),
        ("pps_gate", "association_loss_count"),
        ("pps_gate", "snapshot_overwrite_count"),
        ("pps_gate", "snapshot_continuity_loss_count"),
        ("pps_gate", "snapshot_pio_rxstall_count"),
        ("pps_gate", "snapshot_dma_error_count"),
        ("pps_gate", "snapshot_dma_stopped_count"),
        ("pps_gate", "physical_pps_missing_count"),
        ("pps_d14", "rejected_short_count"),
        ("pps_d14", "rejected_long_count"),
        ("pps_d10", "short_interval_count"),
        ("pps_d10", "buffer_overflow_count"),
    ):
        values[(component, key)] = "0"
    health = [
        {"component": component, "status_key": key, "status_value": value}
        for (component, key), value in values.items()
    ]
    return raw, capture, health


def test_transport_authority_check_allows_only_benign_queries(tmp_path: Path) -> None:
    raw, capture, health = _healthy_transport_inputs(tmp_path)
    checks, _ = _transport_and_authority_checks(raw, capture, health, [], [])
    assert all(check.passed for check in checks)

    raw.write_text(
        raw.read_text(encoding="utf-8")
        + '# OTIS_HOST {"event":"host_command_sent","command":"DAC SET 0xA828"}\n',
        encoding="utf-8",
    )
    checks, result = _transport_and_authority_checks(raw, capture, health, [], [])
    assert not next(check for check in checks if check.identifier == "zero_dac_active_or_unapproved_commands").passed
    assert result["unexpected_commands"] == ["DAC SET 0xA828"]


def test_transport_check_rejects_any_historical_static_binding_drift(
    tmp_path: Path,
) -> None:
    raw, capture, health = _healthy_transport_inputs(tmp_path)
    health.extend(
        [
            {
                "component": "cx318_preview",
                "status_key": "confirmed_static_code",
                "status_value": "0xA829",
            },
            {
                "component": "cx318_preview",
                "status_key": "confirmed_static_code",
                "status_value": "0xA828",
            },
            {
                "component": "cx318_preview",
                "status_key": "static_code",
                "status_value": "0xA828",
            },
            {
                "component": "cx318_preview",
                "status_key": "dac_epoch",
                "status_value": str(DAC_EPOCH),
            },
        ]
    )

    checks, result = _transport_and_authority_checks(
        raw,
        capture,
        health,
        [],
        [],
        static_code=STATIC_CODE,
        dac_epoch=DAC_EPOCH,
    )

    assert not next(
        check
        for check in checks
        if check.identifier == "live_health_fail_static_and_authority_guards"
    ).passed
    assert result["health_history_violation_count"] == 1


def test_analyzer_refuses_capture_in_progress_before_loading_manifest(tmp_path: Path) -> None:
    (tmp_path / "capture_in_progress.flag").touch()
    with pytest.raises(ValueError, match="capture is in progress"):
        analyze_run(tmp_path)
