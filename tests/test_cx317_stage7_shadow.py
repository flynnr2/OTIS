from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import json

import pytest

from host.otis_tools.cx317_stage7_shadow import (
    CONTRACT_SHA256,
    CandidateEngine,
    ShadowObservation,
    V1_CONTRACT,
    V1_CONTRACT_SHA256,
    frozen_content_binding_matches,
    load_contract,
    run_shadow,
)


CONTRACT_PATH = Path("profiles/discipline/cx317_stage7_shadow_deadband_v1.json")


def _observation(
    sequence: int,
    timestamp_s: int,
    error_hz: float,
    *,
    code: int = 0xA82A,
) -> ShadowObservation:
    return ShadowObservation(
        observation_sequence=sequence,
        estimate_id=f"est:cx317:selected600:{sequence:06d}",
        timestamp_s=timestamp_s,
        frequency_error_hz=error_hz,
        actual_applied_code=code,
    )


def test_stage7_shadow_contract_is_exact_finite_and_non_actionable() -> None:
    contract = load_contract()
    assert contract.contract_sha256 == CONTRACT_SHA256
    assert contract.authoritative_deadband_hz == 0.006249995628992717
    assert contract.detection_floor_hz == 0.0033333317438761396
    assert contract.maximum_step == 21
    assert contract.cadence_s == 1800
    assert contract.settling_s + contract.fresh_support_s == 1500
    assert contract.budgets == {"part_a": (4, 84), "part_b": (32, 672)}
    assert [item.candidate_id for item in contract.candidates] == [
        "v2_symmetric_baseline",
        "symmetric_three_count_5mhz",
        "symmetric_two_count_floor_guard",
        "hysteretic_two_count_to_v2",
        "hysteretic_three_count_to_v2",
    ]
    assert all(
        item.entry_threshold_hz >= contract.detection_floor_hz
        and item.release_threshold_hz >= item.entry_threshold_hz
        for item in contract.candidates
    )

    source = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert source["authority"] == {
        "actionable": False,
        "actuation_authorized": False,
        "may_consume_authorization": False,
        "may_change_live_controller_state": False,
        "may_change_live_response_state": False,
        "may_change_live_budget": False,
        "may_issue_command": False,
        "may_write_dac": False,
        "counterfactual_only_after_code_divergence": True,
        "candidate_adoption_during_stage7": False,
    }


def test_v3_initial_condition_binding_preserves_v1_numerics_and_history() -> None:
    current = load_contract()
    historical = load_contract(V1_CONTRACT)
    assert current.contract_id == "CX317_STAGE7_SHADOW_DEADBAND_V3"
    assert current.contract_sha256 == CONTRACT_SHA256
    assert current.part_a_start_code == 0xA800
    assert historical.contract_id == "CX317_STAGE7_SHADOW_DEADBAND_V1"
    assert historical.contract_sha256 == V1_CONTRACT_SHA256
    assert current.authoritative_deadband_hz == historical.authoritative_deadband_hz
    assert current.candidates == historical.candidates
    assert current.budgets == historical.budgets


def test_frozen_prompt_binding_resolves_exact_tracked_history() -> None:
    prompt = Path(
        "docs/60_EXPERIMENTS/"
        "CX317_BOUNDED_CLOSED_LOOP_ACQUISITION_CODEX_PROGRAMME/"
        "07_DUAL_CORE_ACTIVE_ENDURANCE_PROMPT.md"
    )
    assert frozen_content_binding_matches(
        prompt,
        "0ab20ab75c58583789fad512f0eb326ef58bfd467e73ebb35fa2281c94efc512",
    )
    assert not frozen_content_binding_matches(prompt, "0" * 64)


def test_stage7_shadow_contract_rejects_any_post_freeze_change(
    tmp_path: Path,
) -> None:
    changed = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    changed["candidates"][0]["entry_threshold_hz"] = 0.001
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="hash differs"):
        load_contract(path)


def test_shadow_candidates_consume_same_observation_without_authority() -> None:
    decisions = run_shadow(
        [_observation(1, 0, 0.005000000819563866)],
        part="part_a",
        start_code=0xA82A,
    )
    assert len(decisions) == 5
    assert {item.estimate_id for item in decisions} == {
        "est:cx317:selected600:000001"
    }
    assert all(
        not item.actionable
        and not item.actuation_authorized
        and not item.authorization_consumed
        for item in decisions
    )
    by_id = {item.candidate_id: item for item in decisions}
    assert not by_id["v2_symmetric_baseline"].counterfactual_write
    assert not by_id["symmetric_three_count_5mhz"].counterfactual_write
    floor = by_id["symmetric_two_count_floor_guard"]
    assert floor.counterfactual_write
    assert floor.limited_delta_codes == -14
    assert floor.shadow_code_after == 0xA82A - 14
    assert floor.state_after == "SETTLING"


def test_shadow_post_divergence_error_is_explicitly_model_based() -> None:
    contract = load_contract()
    candidate = next(
        item
        for item in contract.candidates
        if item.candidate_id == "symmetric_two_count_floor_guard"
    )
    engine = CandidateEngine(contract, candidate, part="part_a", start_code=0xA82A)
    first = engine.process(_observation(1, 0, 0.005000000819563866))
    assert first.counterfactual_write
    second = engine.process(_observation(2, 1800, 0.005000000819563866))
    expected = 0.005000000819563866 + contract.gain_nominal * (-14)
    assert second.counterfactual_error_hz == pytest.approx(expected, abs=1e-15)
    assert second.actual_applied_code == 0xA82A
    assert second.shadow_code_before == 0xA82A - 14


def test_hysteretic_release_requires_two_fresh_estimates_and_cadence() -> None:
    contract = load_contract()
    candidate = next(
        item
        for item in contract.candidates
        if item.candidate_id == "hysteretic_two_count_to_v2"
    )
    engine = CandidateEngine(contract, candidate, part="part_a", start_code=0xA82A)
    first = engine.process(_observation(1, 0, 0.007))
    second = engine.process(_observation(2, 600, 0.007))
    third = engine.process(_observation(3, 1800, 0.007))
    assert first.state_after == "INSIDE"
    assert first.release_consecutive_count == 1
    assert second.state_after == "OUTSIDE"
    assert second.decision_reason == "counterfactual_decision_cadence_hold"
    assert third.counterfactual_write
    assert third.limited_delta_codes == -20


def test_prospective_four_step_alternation_stops_without_write() -> None:
    contract = load_contract()
    candidate = contract.candidates[0]
    engine = CandidateEngine(contract, candidate, part="part_b", start_code=0xA82A)
    engine.band_state = "OUTSIDE"
    engine.directions = [1, -1, 1]
    engine.path_codes = 63
    decision = engine.process(_observation(1, 0, 0.02))
    assert decision.state_after == "DITHER_HOLD"
    assert decision.decision_reason == "prospective_repeated_alternation"
    assert not decision.counterfactual_write
    assert decision.shadow_code_after == 0xA82A


def test_prospective_low_net_excess_path_stops_without_write() -> None:
    contract = load_contract()
    candidate = contract.candidates[0]
    engine = CandidateEngine(contract, candidate, part="part_b", start_code=0xA82A)
    engine.band_state = "OUTSIDE"
    engine.shadow_code = 0xA82A + 21
    engine.path_codes = 147
    engine.directions = [1, 1, -1, 1, -1, 1, -1]
    decision = engine.process(
        _observation(1, 0, 0.02, code=engine.shadow_code)
    )
    assert decision.limited_delta_codes == -21
    assert decision.state_after == "DITHER_HOLD"
    assert decision.decision_reason == "prospective_low_net_excess_path"
    assert not decision.counterfactual_write
    assert decision.path_codes == 147


def test_part_a_budget_hold_is_prospective_and_nonwriting() -> None:
    contract = load_contract()
    candidate = contract.candidates[0]
    engine = CandidateEngine(contract, candidate, part="part_a", start_code=0xA82A)
    engine.band_state = "OUTSIDE"
    engine.correction_count = 4
    engine.path_codes = 84
    decision = engine.process(_observation(1, 0, -0.02))
    assert decision.state_after == "BUDGET_HOLD"
    assert decision.decision_reason == "counterfactual_budget_hold"
    assert not decision.counterfactual_write
    assert decision.correction_count == 4
    assert decision.path_codes == 84


def test_shadow_rejects_nonmonotonic_source_sequence() -> None:
    observations = [
        _observation(2, 600, 0.0),
        _observation(1, 1200, 0.0),
    ]
    with pytest.raises(ValueError, match="not monotonic"):
        run_shadow(observations, part="part_a", start_code=0xA82A)


def test_shadow_decision_serialization_contains_no_authority() -> None:
    decision = run_shadow(
        [_observation(1, 0, -0.01)], part="part_a", start_code=0xA82A
    )[0]
    serialized = asdict(decision)
    assert serialized["record_type"] == "SHD"
    assert serialized["actionable"] is False
    assert serialized["actuation_authorized"] is False
    assert serialized["authorization_consumed"] is False
