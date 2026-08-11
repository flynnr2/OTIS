from __future__ import annotations

from host.otis_tools.cx319_g2_runtime_contract import (
    canonical_prewrite_fixture,
    evaluate_health_integrity,
    evaluate_prewrite_readiness,
    evaluate_telemetry_drop_history,
)


IDENTITY = {
    "run_identity": "cx319_tight_lower:3195001",
    "build_identity": "a" * 64 + ":" + "b" * 64,
    "profile_identity": "cx319_tight_lower",
    "estimator_sha256": "c" * 64,
    "model_sha256": "d" * 64,
    "active_policy_sha256": "e" * 64,
    "response_policy_sha256": "f" * 64,
    "numerical_policy_sha256": "1" * 64,
}


def _rows(values: list[int]) -> list[dict[str, str]]:
    return [
        {
            "record_type": "STS",
            "status_seq": str(index),
            "component": "dual_core",
            "status_key": "telemetry_dropped",
            "status_value": str(value),
        }
        for index, value in enumerate(values, start=1)
    ]


def test_nonzero_attach_baseline_preserves_every_other_absolute_gate() -> None:
    health = canonical_prewrite_fixture(
        expected_identity=IDENTITY,
        planned_live_stimulus_code=0xA808,
    )
    health[("dual_core", "telemetry_dropped")] = "3"

    integrity = evaluate_health_integrity(
        health, telemetry_drop_baseline=3
    )
    readiness = evaluate_prewrite_readiness(
        health,
        expected_identity=IDENTITY,
        planned_live_stimulus_code=0xA808,
        active_row_count=0,
        dac_row_count=0,
        telemetry_drop_baseline=3,
    )

    assert integrity.clean is True
    assert readiness.ready is True

    health[("capture", "dropped_count")] = "1"
    integrity = evaluate_health_integrity(
        health, telemetry_drop_baseline=3
    )
    assert integrity.clean is False


def test_post_attach_increment_fails_health_integrity() -> None:
    health = canonical_prewrite_fixture(
        expected_identity=IDENTITY,
        planned_live_stimulus_code=0xA808,
    )
    health[("dual_core", "telemetry_dropped")] = "4"

    integrity = evaluate_health_integrity(
        health, telemetry_drop_baseline=3
    )

    assert integrity.clean is False
    assert any("frozen host-attach baseline 3" in item for item in integrity.mismatches)


def test_prewrite_rejects_receiver_identity_epoch_two_before_setup() -> None:
    health = canonical_prewrite_fixture(
        expected_identity=IDENTITY,
        planned_live_stimulus_code=0xA808,
    )
    health.update(
        {
            ("gnss_receiver", "identity_epoch"): "2",
            ("gnss_receiver", "identity_stable"): "false",
            ("gnss_receiver", "metadata_control_eligible"): "false",
            ("gnss_receiver", "raw_pps_control_eligible"): "false",
            ("gnss_receiver", "control_eligible"): "false",
        }
    )

    readiness = evaluate_prewrite_readiness(
        health,
        expected_identity=IDENTITY,
        planned_live_stimulus_code=0xA808,
        active_row_count=0,
        dac_row_count=0,
    )

    assert readiness.ready is False
    assert any(
        "gnss_receiver.identity_epoch='2'" in item
        for item in readiness.mismatches
    )
    assert any(
        "gnss_receiver.control_eligible='false'" in item
        for item in readiness.mismatches
    )


def test_history_allows_convergence_then_requires_a_frozen_value() -> None:
    result = evaluate_telemetry_drop_history(
        _rows([0, 3, 3, 3]),
        frozen_baseline=3,
        frozen_status_seq=3,
    )

    assert result["exact"] is True
    assert result["stable_before_freeze"] is True
    assert result["no_increment_after_freeze"] is True


def test_history_rejects_an_increment_after_freeze() -> None:
    result = evaluate_telemetry_drop_history(
        _rows([3, 3, 4]),
        frozen_baseline=3,
        frozen_status_seq=2,
    )

    assert result["exact"] is False
    assert result["no_increment_after_freeze"] is False


def test_history_rejects_nonincreasing_status_sequences() -> None:
    rows = _rows([3, 3, 3])
    rows[-1]["status_seq"] = "2"

    result = evaluate_telemetry_drop_history(
        rows,
        frozen_baseline=3,
        frozen_status_seq=2,
    )

    assert result["exact"] is False
    assert result["status_sequences_strictly_increasing"] is False
