from __future__ import annotations

from host.otis_tools.cx317_final_readiness import (
    Check,
    _decision,
    _future_experiment,
    _section,
    _verification_checks,
)


def _verification() -> dict:
    return {
        "schema_version": 1,
        "pytest": {
            "result": "pass",
            "passed": 581,
            "skipped": 2,
            "failed": 0,
            "errors": 0,
        },
        "firmware_matrix": {
            "result": "pass",
            "expected_pass_profiles": 12,
            "passed_profiles": 12,
            "expected_fail_profiles": 4,
            "guarded_failures_observed": 4,
        },
        "no_hardware_validation": {
            "result": "pass",
            "evidence": "integrated fixtures passed",
        },
    }


def test_final_readiness_fails_if_any_mandatory_gate_fails() -> None:
    checks = [Check("a", True, "ok"), Check("b", False, "failed")]

    assert _decision(checks, []) == "not_ready"


def test_final_readiness_remains_observe_only_with_unresolved_evidence() -> None:
    checks = [Check("a", True, "ok")]
    blockers = [{"status": "unavailable"}]

    assert _decision(checks, blockers) == "ready_for_more_observe_only_testing"


def test_single_step_review_requires_every_blocker_resolved() -> None:
    checks = [Check("a", True, "ok")]
    blockers = [{"status": "resolved"}, {"status": "resolved"}]

    assert _decision(checks, blockers) == (
        "ready_for_separate_single_step_actuation_review"
    )


def test_future_experiment_is_non_actuating_and_fails_parameter_selection_closed() -> None:
    proposal = _future_experiment("ready_for_more_observe_only_testing")

    assert proposal["authorization_status"] == "not_authorized_by_this_programme"
    assert proposal["feedback_derived_dac_commands"] is False
    assert proposal["automatic_actuation"] is False
    settling = proposal["phase_2_conditional_open_loop_settling"]
    assert settling["exact_step_codes"].startswith("unavailable_")
    assert settling["sample_cadence"].startswith("unavailable_")
    assert settling["dwell_duration"].startswith("unavailable_")


def test_final_verification_requires_exact_complete_results() -> None:
    checks = _verification_checks(_verification())
    assert all(item.passed for item in checks)

    failed = _verification()
    failed["firmware_matrix"]["guarded_failures_observed"] = 3
    checks = _verification_checks(failed)
    assert next(
        item for item in checks if item.identifier == "final_firmware_matrix"
    ).passed is False


def test_report_section_extraction_stops_at_next_heading() -> None:
    source = "# Report\n\n## Wanted\n\nbody\n\n## Next\n\nother\n"

    assert _section(source, "Wanted") == "## Wanted\n\nbody"
