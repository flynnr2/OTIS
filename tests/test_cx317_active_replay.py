from __future__ import annotations

from host.otis_tools.cx317_active_replay import run_all


REQUIRED = {
    "ideal_convergence",
    "smallest_measured_gain",
    "largest_measured_gain",
    "quantized_noisy_response",
    "indeterminate_then_cumulative_detection",
    "wrong_sign_plant",
    "excessive_gain",
    "growing_error",
    "persistent_absent_response",
    "drift_temperature_boundaries",
    "gnss_fix_invalid",
    "gnss_fix_stale",
    "gnss_recovery_new_session",
    "missing_pps",
    "malformed_pps",
    "snapshot_fault",
    "count_fault",
    "requested_accepted_applied_disagreement",
    "i2c_failure",
    "acknowledgement_timeout",
    "duplicate_acknowledgement",
    "stale_acknowledgement",
    "clamp",
    "step_limit",
    "cumulative_limit",
    "correction_count_limit",
    "cadence_limit",
    "capture_owner_loss",
    "reconnect_reboot",
    "abort",
    "telemetry_backpressure_state_isolation",
    "lost_transaction_evidence",
}


def test_both_campaigns_cover_every_mandatory_scenario_and_pass() -> None:
    results = run_all()

    assert {item.campaign for item in results} == {"A", "B"}
    for campaign in ("A", "B"):
        names = {item.scenario for item in results if item.campaign == campaign}
        assert REQUIRED <= names
    assert all(item.passed for item in results)
    assert all(not item.automatic_retry for item in results)
    assert all(not item.automatic_restore for item in results)
