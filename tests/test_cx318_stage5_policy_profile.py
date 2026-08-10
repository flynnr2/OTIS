from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "profiles/discipline/cx318_stage5_tight_active_v1.json"


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _load() -> dict[str, object]:
    return json.loads(PROFILE.read_text(encoding="utf-8"))


def test_stage5_policy_bindings_are_exact() -> None:
    profile = _load()
    assert profile["policy_id"] == "CX318_STAGE5_TIGHT_ACTIVE_FREQUENCY_ONLY_V1"
    assert profile["status"] == "frozen_before_stage5_hardware_or_write"
    assert profile["oscillator_identity"] == "CX317"
    assert profile["programme_label"] == "CX318"

    for binding in profile["bindings"].values():
        path = ROOT / binding["path"]
        assert path.is_file(), path
        assert _sha256(path) == binding["sha256"]


def test_stage5_integer_hysteresis_is_the_authoritative_active_band() -> None:
    profile = _load()
    source = profile["authoritative_input"]
    band = profile["tight_hysteretic_band"]
    assert source["span_s"] == 600
    assert source["quantity"] == "signed_integer_accumulated_edge_error_counts"
    assert source["integer_counts_are_authoritative"] is True
    assert band == {
        "initial_and_rearm_state": "REQUALIFY_OUTSIDE",
        "outside_state": "OUTSIDE",
        "inside_state": "TIGHT_INSIDE",
        "entry_absolute_counts_lte": 2,
        "entry_consecutive_fresh_estimates": 2,
        "release_absolute_counts_gte": 4,
        "release_consecutive_fresh_estimates": 2,
        "three_count_rule": "retain_previous_band_state",
        "pending_counter_reset_on": [
            "opposite_evidence",
            "invalidity",
            "dac_epoch_transition",
            "capture_session_transition",
        ],
        "transition_observation_rule": (
            "clear_prior_pending_evidence_then_credit_the_current_observation_only_when_it_is_a_fresh_valid_600s_estimate_in_the_new_identity"
        ),
        "entry_pending_controller_rule": (
            "hold_without_request_until_entry_is_confirmed_or_opposite_evidence_returns_the_policy_to_ordinary_OUTSIDE_eligibility"
        ),
        "release_pending_controller_rule": (
            "remain_inside_and_hold_without_request_until_release_is_confirmed"
        ),
        "outside_three_count_controller_rule": (
            "eligible_for_the_frozen_frequency_controller"
        ),
        "confirmed_release_controller_rule": (
            "eligible_for_the_frozen_frequency_controller"
        ),
        "confirmed_entry_controller_rule": (
            "hold_at_the_last_confirmed_applied_code"
        ),
    }


def test_stage5_leg_and_controller_limits_are_frozen() -> None:
    profile = _load()
    controller = profile["frequency_controller"]
    assert controller["maximum_automatic_step_codes"] == 21
    assert (controller["minimum_code"], controller["maximum_code"]) == (
        0xA800,
        0xAB00,
    )
    assert controller["minimum_applied_correction_cadence_s"] == 1800
    assert controller["settling_exclusion_s"] == 900
    assert controller["fresh_support_after_settling_s"] == 600
    assert controller["full_history_reset_s"] == 1500
    assert controller["maximum_outstanding_requests"] == 1
    assert controller["automatic_retry"] is False
    assert controller["automatic_restore"] is False
    assert controller["reboot_recovery"] is False

    leg_a = profile["legs"]["A"]
    leg_b = profile["legs"]["B"]
    assert (leg_a["exact_setup_code"], leg_a["required_automatic_direction"]) == (
        0xA808,
        "positive",
    )
    assert (leg_b["exact_setup_code"], leg_b["required_automatic_direction"]) == (
        0xA848,
        "negative",
    )
    for leg in (leg_a, leg_b):
        assert leg["maximum_automatic_corrections"] == 4
        assert leg["maximum_cumulative_automatic_movement_codes"] == 84

    finite = profile["finite_runtime"]
    assert finite["qualification_deadline_s"] == 90 * 60
    assert finite["maximum_qualified_duration_s"] == 4 * 60 * 60
    assert finite["no_extension_after_finite_endpoint"] is True


def test_rehearsal_reuses_exact_profile_without_consuming_setup_write() -> None:
    rehearsal = _load()["same_profile_rehearsal"]
    assert rehearsal["required_before_each_long_leg"] is True
    assert rehearsal["reuse_exact_leg_profile_uf2_config_and_limits"] is True
    assert rehearsal["accelerated_or_relaxed_profile_forbidden"] is True
    assert rehearsal["minimum_capture_duration_s"] == 2700
    assert rehearsal["minimum_selected_600s_estimates"] >= 1
    assert rehearsal["reconfirmed_pre_setup_code"] == 0xA828
    assert rehearsal["firmware_local_pre_setup_dac_epoch"] == 0
    assert rehearsal["setup_or_automatic_dac_write_during_rehearsal"] is False
    assert rehearsal["same_fail_static_stop_conditions"] is True
    assert rehearsal["manifest_must_bind_exact_rehearsal_seal"] is True


def test_phase_hybrid_and_shadow_paths_have_zero_authority() -> None:
    profile = _load()
    phase = profile["phase_and_hybrid_authority"]
    assert phase["continuous_preview_required"] is True
    assert phase["current_confirmed_applied_code_and_dac_epoch_are_observation_inputs"] is True
    for field in (
        "actionable",
        "actuation_authorized",
        "authorization_consumed",
        "may_influence_frequency_controller_delta",
        "may_influence_frequency_controller_eligibility",
        "may_mutate_frequency_controller_response_or_budget_state",
        "may_issue_command_or_write_dac",
    ):
        assert phase[field] is False

    shadows = profile["zero_authority_shadows"]
    assert shadows["historical_v2"]["integer_equivalent_inside_absolute_counts_lte"] == 3
    assert shadows["symmetric_two_count_floor_guard"]["inside_absolute_counts_lte"] == 2
    assert shadows["symmetric_two_count_floor_guard"]["outside_absolute_counts_gte"] == 3
    assert shadows["may_change_active_band_or_controller_state"] is False
    assert shadows["may_change_active_delta_eligibility_response_or_budget"] is False
    assert shadows["may_issue_command_or_write_dac"] is False
