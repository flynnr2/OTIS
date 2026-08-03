from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from host.otis_tools.cx317_i_only_preview_replay import (
    DEFAULT_POLICY,
    IOnlyPreviewEngine,
    Observation,
    load_policy,
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
