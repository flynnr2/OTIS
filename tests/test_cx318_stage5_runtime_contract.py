from __future__ import annotations

from host.otis_tools.cx318_stage5_runtime_contract import (
    ACTIVE_STATUS_KEYS,
    HEALTH_INTEGRITY_EXACT,
    INHERITED_PREVIEW_BASELINE_PROVENANCE,
    evaluate_health_integrity,
    evaluate_prewrite_readiness,
)


IDENTITY = {
    "run_identity": "run",
    "build_identity": "build",
    "profile_identity": "profile",
    "estimator_sha256": "estimator",
    "model_sha256": "model",
    "active_policy_sha256": "active-policy",
    "response_policy_sha256": "response-policy",
    "numerical_policy_sha256": "numerical-policy",
}


def complete_prewrite_health() -> dict[tuple[str, str], str]:
    values = {key: "present" for key in ACTIVE_STATUS_KEYS}
    values.update(
        {
            **IDENTITY,
            "enabled": "true",
            "state": "DISARMED",
            "reason": "initialized_disarmed",
            "evidence_pending": "false",
            "evidence_phase": "evidence_clear",
            "capture_lease_live": "true",
            "manual_start_confirmed": "false",
            "arm_eligible": "false",
            "fail_static": "false",
            "session_id": "1",
            "uptime_s": "30",
            "evidence_request_sequence": "0",
            "expected_setup_code": "0xA808",
            "confirmed_applied_code_known": "false",
            "confirmed_applied_code": "unavailable",
            "correction_count": "0",
            "cumulative_movement_codes": "0",
            "dac_epoch": "0",
            "selected_interval_count": "0",
            "automatic_retry": "false",
            "automatic_restore": "false",
        }
    )
    health = {("cx317_active", key): value for key, value in values.items()}
    health.update(
        {
            ("cx318_preview", "static_code"): "0xA828",
            ("cx318_preview", "applied_code"): "0xA828",
            ("cx318_preview", "dac_epoch"): "0",
            ("cx317_preview", "actionable"): "false",
            ("cx317_preview", "actuation_authorized"): "false",
            ("cx318_preview", "actionable"): "false",
            ("cx318_preview", "actuation_authorized"): "false",
            ("cx318_preview", "authorization_consumed"): "false",
            ("dac", "applied_code_known"): "false",
            ("dac", "last_write_ok"): "false",
            ("dac", "last_applied_code"): "unavailable",
            ("capture", "dropped_count"): "0",
            ("capture", "pps_count_boundary_dropped_count"): "0",
            ("dual_core", "telemetry_dropped"): "0",
            ("dual_core", "service_publish_failures"): "0",
            ("dual_core", "partition_fault"): "none",
            ("dual_core", "fail_static"): "false",
            ("cx317_preview", "telemetry_dropped_frames"): "0",
        }
    )
    return health


def test_exact_prewrite_contract_distinguishes_baseline_target_and_confirmation() -> None:
    assert ("cx317_preview", "telemetry_dropped_frames") in HEALTH_INTEGRITY_EXACT
    assert ("cx318_preview", "telemetry_dropped_frames") not in HEALTH_INTEGRITY_EXACT
    result = evaluate_prewrite_readiness(
        complete_prewrite_health(),
        expected_identity=IDENTITY,
        planned_live_stimulus_code=0xA808,
        active_row_count=0,
        dac_row_count=0,
    )

    assert result.ready is True
    assert result.inherited_preview_baseline_code == "0xA828"
    assert (
        result.inherited_preview_baseline_provenance
        == INHERITED_PREVIEW_BASELINE_PROVENANCE
    )
    assert result.planned_live_stimulus_code == "0xA808"
    assert result.physical_dac_confirmation == "unknown_before_live_stimulus"


def test_missing_active_dac_epoch_fails_the_same_contract_used_before_setup() -> None:
    health = complete_prewrite_health()
    del health[("cx317_active", "dac_epoch")]

    result = evaluate_prewrite_readiness(
        health,
        expected_identity=IDENTITY,
        planned_live_stimulus_code=0xA808,
        active_row_count=0,
        dac_row_count=0,
    )

    assert result.ready is False
    assert "missing cx317_active.dac_epoch" in result.missing


def test_a808_target_is_not_accepted_as_a_prewrite_physical_confirmation() -> None:
    health = complete_prewrite_health()
    health[("cx317_active", "confirmed_applied_code_known")] = "true"
    health[("cx317_active", "confirmed_applied_code")] = str(0xA808)

    result = evaluate_prewrite_readiness(
        health,
        expected_identity=IDENTITY,
        planned_live_stimulus_code=0xA808,
        active_row_count=0,
        dac_row_count=0,
    )

    assert result.ready is False
    assert any("confirmed_applied_code_known" in item for item in result.mismatches)


def test_missing_health_is_not_clean() -> None:
    health = complete_prewrite_health()
    del health[("dual_core", "service_publish_failures")]

    integrity = evaluate_health_integrity(health)

    assert integrity.clean is False
    assert "missing dual_core.service_publish_failures" in integrity.missing


def test_missing_active_status_is_not_clean_during_live_operation() -> None:
    health = complete_prewrite_health()
    del health[("cx317_active", "dac_epoch")]

    integrity = evaluate_health_integrity(health)

    assert integrity.clean is False
    assert "missing cx317_active.dac_epoch" in integrity.missing
