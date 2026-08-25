from __future__ import annotations

from host.otis_tools import sustained_hybrid_successor_study as study


def test_frozen_contract_is_offline_only_and_semantically_exact() -> None:
    contract = study.load_contract()

    assert contract["contract_sha256"] == (
        "d60c26c90d7f06f4c605f2b35159209315f4c1b035dd9831f76c78e1200ea7cf"
    )
    assert contract["authority"]["offline_analysis"] is True
    assert set(contract["authority"].values()) == {False, True}
    assert contract["terminal_outcomes"] == [
        "selected_changed_successor",
        "no_controller_successor_selected",
        "study_invalid_due_to_evidence_or_replay_mismatch",
    ]


def test_persistent_one_count_release_and_reset_boundaries() -> None:
    gate = study.CandidateFrequencyGate("persistent_one_count_release_v1")
    first, first_reason = gate.effective_frequency_error(
        frequency_error_hz=1 / 600,
        counts=1,
        tight_state=study.TIGHT_INSIDE,
        capture_session=1,
        dac_epoch=2,
        source_first=1,
        source_last=600,
    )
    second, second_reason = gate.effective_frequency_error(
        frequency_error_hz=1 / 600,
        counts=1,
        tight_state=study.TIGHT_INSIDE,
        capture_session=1,
        dac_epoch=2,
        source_first=601,
        source_last=1200,
    )

    assert first == 0.0
    assert first_reason == "persistent_one_count_first_hold"
    assert second == 1 / 600
    assert second_reason == "persistent_one_count_released"

    reset, reset_reason = gate.effective_frequency_error(
        frequency_error_hz=0.0,
        counts=0,
        tight_state=study.TIGHT_INSIDE,
        capture_session=1,
        dac_epoch=2,
        source_first=1201,
        source_last=1800,
    )
    after_reset, after_reset_reason = gate.effective_frequency_error(
        frequency_error_hz=1 / 600,
        counts=1,
        tight_state=study.TIGHT_INSIDE,
        capture_session=1,
        dac_epoch=3,
        source_first=1801,
        source_last=2400,
    )

    assert reset == 0.0
    assert reset_reason == "persistence_not_applicable"
    assert after_reset == 0.0
    assert after_reset_reason == "persistent_one_count_first_hold"


def test_attempt4_comparison_replays_v1_and_rejects_all_frozen_candidates() -> None:
    report = study.create_comparison_report()

    assert report["status"] == "passed"
    assert report["terminal"] == "no_controller_successor_selected"
    assert report["selected_candidate_id"] is None
    assert report["exact_v1_baseline"]["exact"] is True
    assert report["exact_v1_baseline"]["decision_count"] == 52
    assert report["source_validation"]["bound_file_count"] == 22
    assert report["exact_v1_baseline"]["application_deltas"] == [
        -6,
        -1,
        -1,
        -6,
        -1,
        -1,
        -1,
        5,
        5,
        -5,
        5,
    ]
    assert report["exact_v1_baseline"]["terminal_reason"] == (
        "prospective_low_efficiency_path"
    )
    assert report["exact_v1_baseline"]["first_seven_phase_material"] is True
    assert report["exact_v1_baseline"]["first_seven_path_codes"] == 17
    assert report["exact_v1_baseline"][
        "last_four_phase_nonmaterial_frequency_driven"
    ] is True
    assert report["exact_v1_baseline"]["last_four_path_codes"] == 20
    assert report["exact_v1_baseline"]["last_four_net_codes"] == 10
    assert report["causal_ablations"]["late_frequency_driven_observed_deltas"] == [
        5,
        5,
        -5,
        5,
    ]
    assert report["causal_ablations"]["late_one_count_hold_deltas"] == [0, 0, 0, 0]
    assert report["causal_ablations"]["late_requests_cadence_limited"] is False
    comparisons = report["candidate_comparisons"]
    assert [item["candidate_id"] for item in comparisons] == [
        "one_count_tight_hold_v1",
        "tight_phase_only_v1",
        "persistent_one_count_release_v1",
    ]
    assert all(item["selectable"] is False for item in comparisons)
    assert all(
        item["first_discriminating_failure"]
        == "minimum:phase_behavior_preserved"
        for item in comparisons
    )
    persistent = comparisons[2]
    persistent_cases = {
        item["case_id"]: item for item in persistent["perturbations"]
    }
    for case_id in (
        "dac_epoch_reset",
        "capture_session_reset",
        "estimator_reset",
        "settling_support_reset",
    ):
        assert persistent_cases[case_id]["pass"] is True
        assert persistent_cases[case_id]["detail"]["post_transition_reason"] == (
            "persistent_one_count_first_hold"
        )
    assert persistent_cases["contradictory_identity"]["detail"][
        "state_after"
    ] == "FAIL_STATIC"
    assert report["decision"]["next_gate"] == (
        "estimator_or_controller_architecture_revision"
    )
    unsigned = {
        key: value for key, value in report.items() if key != "report_sha256"
    }
    assert report["report_sha256"] == study._canonical_sha256(unsigned)
