from __future__ import annotations

from pathlib import Path

from host.otis_tools import active_hybrid_live_rehearsal
from host.otis_tools.active_control_policy import ResponseClass, ResponseClassifier
from host.otis_tools.active_hybrid_live_analyze import (
    _classify_decision,
    _response_horizon_facts,
)
from host.otis_tools.active_hybrid_policy import load_policy
from host.otis_tools.active_hybrid_programme_contract import (
    CX322_PROGRAMME,
    progressive_checkpoint_contract,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "profiles/discipline/cx322_bounded_hybrid_fact_gathering_v1.json"
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_cx322_freezes_observational_response_semantics() -> None:
    policy = load_policy(POLICY)
    assert policy.response_checkpoint_observational is True
    assert policy.maximum_applications == 4
    assert policy.maximum_cumulative_movement_codes == 84
    assert policy.maximum_step_codes == 21
    progressive = progressive_checkpoint_contract(CX322_PROGRAMME)
    assert progressive["phase_material_application_count_is_acquisition_pass_gate"] is False
    assert (
        progressive[
            "later_authority_requires_exact_response_observation_and_tight_reacquisition"
        ]
        is True
    )
    assert "minimum_phase_material_applications_for_pass" not in progressive


def test_cx322_compiles_the_exact_timer_projection_path() -> None:
    preview = (FIRMWARE / "otis_cx317_preview_live.cpp").read_text(
        encoding="utf-8"
    )

    assert (
        "#if OTIS_ENABLE_CX32X_EXACT_ACTIVE_TIMING\n"
        "OtisTimer0Extension timer_extension = {};"
    ) in preview
    for function in (
        "bool otis_cx317_preview_live_extend_timer0_ticks",
        "bool otis_cx317_preview_live_project_setup_timer0_ticks",
    ):
        body = preview[preview.index(function) :]
        assert body.index("#if OTIS_ENABLE_CX32X_EXACT_ACTIVE_TIMING") < body.index(
            "#else"
        )
    boundary = preview[
        preview.index("void otis_cx317_preview_live_on_boundary") :
    ]
    assert boundary.index("otis_timer0_extension_advance_boundary") < boundary.index(
        "#if OTIS_ENABLE_CX321_ACTIVE_HYBRID"
    )


def test_cx322_real_process_fixture_connects_response_to_later_authority() -> None:
    policy = load_policy(POLICY)
    bundle = {
        "programme_id": CX322_PROGRAMME.programme_id,
        "run_identity": CX322_PROGRAMME.runtime_run_identity,
        "profile_identity": CX322_PROGRAMME.profile_id,
        "firmware": {"build_identity": "a" * 64 + ":" + "b" * 64},
        "policy": {
            "path": str(POLICY.resolve()),
            "policy_sha256": policy.policy_sha256,
        },
    }

    ahy, transactions, summary = (
        active_hybrid_live_rehearsal._cx322_first_observational_transaction_fixture(
            bundle
        )
    )

    assert [row["event"] for row in transactions] == [
        "manual_start",
        "request_created",
        "core0_accepted",
        "application",
        "response",
    ]
    assert transactions[-1]["response_class"] == "inside_deadband"
    assert ahy[-2]["authority_state"] == "AWAITING_RESPONSE"
    assert ahy[-1]["state_after"] == "HYBRID_TRACKING"
    assert summary["later_authority_release_reason"] == (
        "first_phase_observation_recorded_and_tight_reacquired"
    )


def test_cx322_does_not_promote_repeated_low_response_to_measurement_fault() -> None:
    classifier = ResponseClassifier(
        legacy_response_deadband_enabled=False,
        response_classification_observational=True,
    )
    for _ in range(3):
        result = classifier.classify(
            pre_error_hz=0.0,
            post_error_hz=0.0,
            applied_delta_codes=21,
            current_code=0xA900,
            minimum_code=0xA800,
            maximum_code=0xAB00,
        )
        assert result.classification is ResponseClass.HEALTHY_INDETERMINATE


def test_cx322_complete_integrity_passes_without_materiality_or_sign_gate() -> None:
    assert _classify_decision(
        integrity_exact=True,
        operator_abort=False,
        platform_terminal=False,
        phase_degraded=True,
        endpoint_complete=True,
        material_applications=0,
        first_checkpoint_passed=False,
        responses_healthy=False,
        tight_reacquired_and_retained=False,
        policy_limits_exact=True,
        phase_pass=False,
        frequency_pass=False,
        minimum_material_applications=2,
        fact_gathering=True,
    ) == ("passed", "bounded_direct_hybrid_evidence_acquired")


def test_response_horizons_preserve_epoch_censoring() -> None:
    active = [
        {
            "event": "application",
            "request_sequence": "1",
            "decision_sequence": "10",
            "application_timestamp_s": "1000",
            "dac_epoch": "2",
            "applied_code": "43070",
            "requested_delta_codes": "2",
            "pre_error_hz": "0.001",
        },
        {
            "event": "response",
            "request_sequence": "1",
            "application_timestamp_s": "1000",
            "observed_response_hz": "-0.002",
            "post_error_hz": "-0.001",
        },
        {
            "event": "application",
            "request_sequence": "2",
            "decision_sequence": "20",
            "application_timestamp_s": "3000",
            "dac_epoch": "3",
            "applied_code": "43073",
            "requested_delta_codes": "3",
            "pre_error_hz": "-0.001",
        },
    ]
    decisions = [
        {
            "decision_timestamp_s": "1600",
            "dac_epoch": "2",
            "current_applied_code": "43070",
            "frequency_error_hz": "0.002",
        },
        {
            "decision_timestamp_s": "3600",
            "dac_epoch": "3",
            "current_applied_code": "43073",
            "frequency_error_hz": "0.0005",
        },
    ]
    facts = _response_horizon_facts(
        active,
        decisions,
        horizons_s=[600, 1500, 3600, 7200],
        settling_exclusion_s=900,
    )
    first = facts["per_application"][0]["horizons"]
    assert first[0]["available"] is True
    assert first[0]["settling_exclusion_complete"] is False
    assert first[1]["source"] == "ACT_exact_response_checkpoint"
    assert first[2]["available"] is False
    assert first[2]["censor_reason"] == "right_censored_by_subsequent_application"
    assert facts["pooled_by_horizon"]["1500"]["nonpositive_direction_count"] == 1
