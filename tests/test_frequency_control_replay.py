from __future__ import annotations

import copy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools.frequency_control_replay import (
    DEFAULT_POLICY,
    CURRENT_REPLAY_POLICY,
    IOnlyPreviewEngine,
    Observation,
    load_policy,
    load_current_replay_policy,
    run_scenarios,
)


def _ready(engine: IOnlyPreviewEngine, error: float = 0.02) -> dict:
    policy = engine.policy
    engine.process(Observation(0, error, policy.fail_static_code, 29.0))
    engine.process(Observation(policy.warmup_s, error, policy.fail_static_code, 29.0))
    return engine.process(
        Observation(
            policy.warmup_s + policy.estimator_span_s,
            error,
            policy.fail_static_code,
            29.0,
        )
    )


def test_policy_values_are_reproducibly_derived_and_non_authorizing() -> None:
    policy = load_policy()

    assert policy.proposed_max_update_codes == 21
    assert policy.active_update_codes == 0
    assert policy.decision_cadence_s == 600
    assert policy.full_history_reset_s == 1500
    assert policy.future_cadence_s == 1800
    assert policy.minimum_code == 0xA800
    assert policy.maximum_code == 0xAB00
    assert policy.fail_static_code == 0xA950
    assert len(policy.provenance) >= 10


def test_current_replay_policy_is_exactly_bound_and_non_authorizing() -> None:
    policy = load_current_replay_policy()

    assert policy.policy_id == "CX317_POST_CAMPAIGN_FREQUENCY_CONTROL_POLICY_V1"
    assert policy.config_hash == sha256(CURRENT_REPLAY_POLICY.read_bytes()).hexdigest()
    assert policy.gain_min == pytest.approx(0.00015873009523809524)
    assert policy.gain_nominal == pytest.approx(0.00017072602587382669)
    assert policy.gain_max == pytest.approx(0.00017334010044578463)
    assert policy.decision_cadence_s == 1800
    assert policy.proposed_max_update_codes == 21
    assert policy.active_update_codes == 0
    assert policy.fail_static_code == 0xA82A
    assert not policy.temperature_required_for_control


def test_current_replay_policy_matrix_passes_without_authority() -> None:
    policy = load_current_replay_policy()
    scenarios = run_scenarios(policy)

    assert all(item["pass"] for item in scenarios)
    for scenario in scenarios:
        rendered = json.dumps(scenario)
        assert '"actionable": true' not in rendered
        assert '"actuation_authorized": true' not in rendered


def test_positive_error_requests_lower_code_and_is_slew_limited() -> None:
    policy = load_policy()
    decision = _ready(IOnlyPreviewEngine(policy), error=0.02)

    assert decision["preview_available"]
    assert decision["proposed_code"] == policy.fail_static_code - 21
    assert decision["limited_delta_codes"] == -21
    assert decision["step_limited"]
    assert decision["active_update_codes"] == 0
    assert not decision["actuation_authorized"]
    assert not decision["actionable"]


def test_evidence_deadband_resets_integrator_and_holds_code() -> None:
    policy = load_policy()
    engine = IOnlyPreviewEngine(policy)
    _ready(engine, error=0.02)
    decision = engine.process(
        Observation(3000, policy.detection_floor_hz, policy.fail_static_code, 29.0)
    )

    assert decision["preview_available"]
    assert decision["proposed_code"] == policy.fail_static_code
    assert decision["integrator_codes"] == 0.0
    assert decision["reason"] == "inside_evidence_deadband"


def test_dac_epoch_requires_the_complete_settling_and_fresh_history_reset() -> None:
    policy = load_policy()
    engine = IOnlyPreviewEngine(policy)
    _ready(engine)
    changed = engine.process(
        Observation(3000, 0.02, policy.fail_static_code, 29.0, dac_epoch=True)
    )
    early = engine.process(
        Observation(4499, 0.02, policy.fail_static_code, 29.0)
    )
    ready = engine.process(
        Observation(4500, 0.02, policy.fail_static_code, 29.0)
    )

    assert changed["state"] == "SETTLING_INHIBIT"
    assert not early["preview_available"]
    assert ready["preview_available"]


def test_fault_is_fail_static_and_requires_explicit_fresh_recovery() -> None:
    policy = load_policy()
    engine = IOnlyPreviewEngine(policy)
    _ready(engine)
    fault = engine.process(
        Observation(3000, 0.02, policy.fail_static_code, 29.0, reference_valid=False)
    )
    held = engine.process(Observation(3600, 0.02, policy.fail_static_code, 29.0))
    reset = engine.process(
        Observation(3600, 0.02, policy.fail_static_code, 29.0, recovery_requested=True)
    )
    recovered = engine.process(
        Observation(4200, 0.02, policy.fail_static_code, 29.0)
    )

    assert fault["state"] == held["state"] == "FAULT"
    assert reset["state"] == "QUALIFYING"
    assert recovered["preview_available"]
    assert all(not row["actionable"] for row in (fault, held, reset, recovered))


def test_model_inapplicability_holds_without_erasing_measurement_and_requalifies() -> None:
    policy = load_policy()
    engine = IOnlyPreviewEngine(policy)
    _ready(engine)
    held = engine.process(
        Observation(
            3000, 0.02, policy.fail_static_code, None,
            model_applicable=False,
        )
    )
    requalifying = engine.process(
        Observation(3600, 0.02, policy.fail_static_code, None)
    )
    recovered = engine.process(
        Observation(4200, 0.02, policy.fail_static_code,
                    policy.temperature_max_c + 10.0)
    )

    assert held["state"] == "OUT_OF_MODEL_HOLD"
    assert held["frequency_error_hz"] == 0.02
    assert not held["preview_available"]
    assert requalifying["state"] == "QUALIFYING"
    assert recovered["preview_available"]
    assert not recovered["actionable"]


def test_complete_required_replay_matrix_passes() -> None:
    scenarios = run_scenarios(load_policy())

    assert len(scenarios) >= 18
    assert all(item["pass"] for item in scenarios)
    categories = {item["category"] for item in scenarios}
    assert {"plant_gain", "range", "noise", "environment", "startup", "settling", "fault_recovery", "limits", "abort"} <= categories


def test_policy_loader_fails_closed_if_update_is_not_evidence_derived(
    tmp_path: Path,
) -> None:
    changed = copy.deepcopy(json.loads(DEFAULT_POLICY.read_text(encoding="utf-8")))
    changed["parameters"]["proposed_future_maximum_update_codes"] = 22
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(changed), encoding="utf-8")

    with pytest.raises(ValueError, match="update size is not tied"):
        load_policy(path)
