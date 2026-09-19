from __future__ import annotations

"""Scientific and authority predicates retained through the host replacement."""
import json
from hashlib import sha256
from pathlib import Path

import pytest

from host.otis_tools import adaptive_hybrid_analyze as analyze_module
from host.otis_tools.adaptive_hybrid_analyze import (
    _normalize_terminal,
    classify_scientific_outcome,
)
from host.otis_tools.adaptive_hybrid_contract import (
    ADAPTIVE_HYBRID_PROGRAMME,
    UNATTENDED_72_HOUR_HYBRID_CONTROL,
    INHIBITED_ZERO_WRITE,
    envelope_for_purpose,
    programme_from_mapping,
)
from host.otis_tools.capture_device import _require_exact_manifest, _split_targets
from host.otis_tools.contracts import (
    CONTROL_PREVIEW_V1_FIELDS,
    CURRENT_PLANT_MODEL_ID,
    CURRENT_PLANT_MODEL_PATH,
    CURRENT_PLANT_MODEL_REF,
    TIGHT_DEADBAND_DECISION_V1_FIELDS,
    _check_control_preview_v1,
)


def test_empty_maintenance_is_exact_only_for_proven_zero_write_authority() -> None:
    empty_replay = {
        "transaction_row_count": 0,
        "decision_row_count": 0,
        "maintenance_row_count": 0,
        "maintenance_replay": {
            "exact": False,
            "decision_count": 0,
            "comparisons": [],
        },
    }

    retained = analyze_module._inhibited_zero_write_maintenance_replay(
        empty_replay, authority_exact=False
    )
    assert retained["exact"] is False
    exempt = analyze_module._inhibited_zero_write_maintenance_replay(
        empty_replay, authority_exact=True
    )
    assert exempt["exact"] is True
    assert exempt["applicability"] == "not_applicable"
    assert "frozen_authority_forbids" in exempt["reason"]
    assert exempt["replay_mode"] == "not_applicable_no_controller_authority"
    assert exempt["controller_state_authority"] == "none"

    for count_field in (
        "transaction_row_count",
        "decision_row_count",
        "maintenance_row_count",
    ):
        with_record = {**empty_replay, count_field: 1}
        assert analyze_module._inhibited_zero_write_maintenance_replay(
            with_record, authority_exact=True
        )["exact"] is False


def test_programme_mapping_rejects_any_contradictory_current_identity() -> None:
    exact = {
        "programme_id": ADAPTIVE_HYBRID_PROGRAMME.programme_id,
        "image_identity": ADAPTIVE_HYBRID_PROGRAMME.profile_id,
        "run_identity": ADAPTIVE_HYBRID_PROGRAMME.runtime_run_identity,
    }
    assert programme_from_mapping(exact) is ADAPTIVE_HYBRID_PROGRAMME
    for key in exact:
        contradictory = {**exact, key: "retired-or-unknown"}
        with pytest.raises(ValueError, match="non-current"):
            programme_from_mapping(contradictory)


@pytest.mark.parametrize(
    ("terminal", "exact", "decision"),
    [
        (
            {
                "result": "healthy_stop",
                "reason": ADAPTIVE_HYBRID_PROGRAMME.qualified_endpoint_reason,
                "preliminary_decision": "pending_offline_scientific_analysis",
            },
            True,
            ADAPTIVE_HYBRID_PROGRAMME.qualified_endpoint_reason,
        ),
        (
            {
                "result": "aborted",
                "reason": "operator requested stop",
                "primary_decision": "adaptive_hybrid_operator_abort",
            },
            True,
            "adaptive_hybrid_operator_abort",
        ),
        (
            {
                "result": "nonpass",
                "reason": "independently verified firmware response terminal",
                "primary_decision": "adaptive_hybrid_authority_not_sustained",
            },
            True,
            "adaptive_hybrid_authority_not_sustained",
        ),
        (
            {
                "result": "nonpass",
                "reason": "invalid qualified claim",
                "primary_decision": ADAPTIVE_HYBRID_PROGRAMME.qualified_endpoint_reason,
            },
            False,
            None,
        ),
    ],
)
def test_terminal_normalization_preserves_canonical_scientific_decision(
    terminal: dict[str, object], exact: bool, decision: str | None
) -> None:
    observed_exact, observed_decision, _, _ = _normalize_terminal(
        terminal, ADAPTIVE_HYBRID_PROGRAMME
    )
    assert observed_exact is exact
    assert observed_decision == decision


def test_terminal_normalization_accepts_exact_zero_write_success() -> None:
    bench_attempt = envelope_for_purpose(INHIBITED_ZERO_WRITE).as_dict()
    terminal = {
        "result": "healthy_stop",
        "reason": "inhibited_zero_write_complete",
        "preliminary_decision": "pending_offline_scientific_analysis",
        "last_confirmed_code": None,
    }

    exact, decision, result, reason = _normalize_terminal(
        terminal,
        ADAPTIVE_HYBRID_PROGRAMME,
        bench_attempt=bench_attempt,
    )

    assert exact is True
    assert decision == "inhibited_zero_write_complete"
    assert result == "healthy_stop"
    assert reason == "inhibited_zero_write_complete"


def test_terminal_normalization_rejects_fabricated_zero_write_success() -> None:
    bench_attempt = envelope_for_purpose(INHIBITED_ZERO_WRITE).as_dict()
    terminal = {
        "result": "healthy_stop",
        "reason": "inhibited_zero_write_complete",
        "preliminary_decision": "pending_offline_scientific_analysis",
        "last_confirmed_code": None,
    }
    fabricated_envelope = json.loads(json.dumps(bench_attempt))
    fabricated_envelope["authority"]["total_dac_value_write_limit"] = 1
    contradictory_code = {**terminal, "last_confirmed_code": 0xA84D}
    contradictory_primary = {
        **terminal,
        "primary_decision": "inhibited_zero_write_complete",
    }

    rejected = (
        _normalize_terminal(terminal, ADAPTIVE_HYBRID_PROGRAMME),
        _normalize_terminal(
            terminal,
            ADAPTIVE_HYBRID_PROGRAMME,
            bench_attempt=envelope_for_purpose(
                UNATTENDED_72_HOUR_HYBRID_CONTROL
            ).as_dict(),
        ),
        _normalize_terminal(
            terminal,
            ADAPTIVE_HYBRID_PROGRAMME,
            bench_attempt=fabricated_envelope,
        ),
        _normalize_terminal(
            contradictory_code,
            ADAPTIVE_HYBRID_PROGRAMME,
            bench_attempt=bench_attempt,
        ),
        _normalize_terminal(
            contradictory_primary,
            ADAPTIVE_HYBRID_PROGRAMME,
            bench_attempt=bench_attempt,
        ),
    )
    assert all(exact is False and decision is None for exact, decision, _, _ in rejected)


def test_terminal_normalization_uses_exact_72_hour_success() -> None:
    long_run_terminal = {
        "result": "healthy_stop",
        "reason": "adaptive_hybrid_endurance_complete",
        "preliminary_decision": "pending_offline_scientific_analysis",
        "last_confirmed_code": 0xA84D,
    }
    bench_attempt = envelope_for_purpose(
        UNATTENDED_72_HOUR_HYBRID_CONTROL
    ).as_dict()

    exact, decision, _, _ = _normalize_terminal(
        long_run_terminal,
        ADAPTIVE_HYBRID_PROGRAMME,
        bench_attempt=bench_attempt,
    )
    assert exact is True
    assert decision == "adaptive_hybrid_endurance_complete"

    exact, decision, _, _ = _normalize_terminal(
        {
            **long_run_terminal,
            "reason": "retired_short_gate_complete",
        },
        ADAPTIVE_HYBRID_PROGRAMME,
        bench_attempt=bench_attempt,
    )
    assert exact is False
    assert decision is None


def test_control_preview_binds_exact_current_plant_profile() -> None:
    row = {field: "" for field in CONTROL_PREVIEW_V1_FIELDS}
    row.update(
        {
            "plant_model_ref": CURRENT_PLANT_MODEL_REF,
            "plant_model_id": CURRENT_PLANT_MODEL_ID,
            "plant_model_version": "1",
            "plant_model_hash": sha256(CURRENT_PLANT_MODEL_PATH.read_bytes()).hexdigest(),
        }
    )
    errors: list[str] = []
    _check_control_preview_v1(row, 1, errors)
    assert not [error for error in errors if "plant_model_" in error]

    row["plant_model_version"] = "2"
    row["plant_model_hash"] = "0" * 64
    errors = []
    _check_control_preview_v1(row, 1, errors)
    assert "row 1: plant_model_version must be 1" in errors
    assert "row 1: plant_model_hash must match the current plant profile bytes" in errors


def test_tight_deadband_field_names_are_current_and_ordered() -> None:
    first = TIGHT_DEADBAND_DECISION_V1_FIELDS.index("three_count_band_inside")
    second = TIGHT_DEADBAND_DECISION_V1_FIELDS.index("two_count_band_inside")
    assert second == first + 1
    retired_fragments = ("historical_", "symmetric_")
    assert not any(
        field.startswith(retired_fragments)
        for field in TIGHT_DEADBAND_DECISION_V1_FIELDS
    )


def test_capture_refuses_to_invent_a_manifest_or_default_inventory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="existing exact run manifest"):
        _require_exact_manifest(tmp_path)
    with pytest.raises(ValueError, match="existing exact run manifest"):
        _split_targets(tmp_path)


@pytest.mark.parametrize("observed,outcome", [(259200000000000, "endurance_complete"), (259199999999999, "undetermined"), (None, "undetermined")])
def test_endurance_requires_full_exact_host_window(observed, outcome):
    terminal = {"result": "healthy_stop", "reason": "adaptive_hybrid_endurance_complete",
                "preliminary_decision": "pending_offline_scientific_analysis", "last_confirmed_code": 0xA84D,
                "observation_window": {"clock_domain": "host_monotonic_ns", "started_monotonic_ns": 0,
                "deadline_monotonic_ns": 259200000000000, "observed_terminal_monotonic_ns": observed}}
    assert classify_scientific_outcome(terminal, ADAPTIVE_HYBRID_PROGRAMME,
        bench_attempt=envelope_for_purpose(UNATTENDED_72_HOUR_HYBRID_CONTROL).as_dict(),
        qualified_d14_accepted_apertures=259200) == outcome


@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        ("host_verification_hold", {"source": "fixture"}),
        ("gnss_metadata_hold", {"reason": "fixture"}),
        ("terminal", {"result": "healthy_stop"}),
        ("controller_authority_inhibited_reason", "fixture"),
        ("arm_pending", True),
        ("inflight_evidence_acknowledgement", {"request_sequence": 1}),
        ("bench_attempt_arm_admission_closed", True),
    ],
)
def test_published_control_authority_closes_for_every_retained_gate(
    tmp_path: Path, mutation: str, value: object
) -> None:
    from copy import deepcopy

    from tests.runtime_fixtures import construct_simulated_supervisor

    supervisor = construct_simulated_supervisor(tmp_path)
    supervisor.state["startup_census"] = {
        "contract": "adaptive_hybrid_startup_census_v1",
        "authority_admitted": True,
        "process_nonce": supervisor.state["startup_census_process_nonce"],
        "session_id": supervisor.state["initial_session_id"],
    }
    supervisor.state["startup_census_authority_admitted"] = True
    supervisor._save()
    assert supervisor.state["control_authority"] is True

    baseline = deepcopy(supervisor.state)
    supervisor.state = baseline
    supervisor.state[mutation] = value
    supervisor._save()
    assert supervisor.state["control_authority"] is False


def test_published_control_authority_closes_while_setup_is_unconfirmed(
    tmp_path: Path,
) -> None:
    from tests.runtime_fixtures import construct_simulated_supervisor

    supervisor = construct_simulated_supervisor(tmp_path)
    supervisor.state["startup_census"] = {
        "contract": "adaptive_hybrid_startup_census_v1",
        "authority_admitted": True,
        "process_nonce": supervisor.state["startup_census_process_nonce"],
        "session_id": supervisor.state["initial_session_id"],
    }
    supervisor.state["startup_census_authority_admitted"] = True
    supervisor.state["manual_start_sent"] = True
    supervisor.state["setup_confirmed_utc"] = None
    supervisor._save()
    assert supervisor.state["control_authority"] is False



def test_explicit_abort_is_interrupted_without_a_qualification_coordinate() -> None:
    terminal = {
        "result": "aborted",
        "reason": "independent_emergency_abort_fifo",
        "primary_decision": "adaptive_hybrid_operator_abort",
    }

    assert (
        classify_scientific_outcome(
            terminal,
            ADAPTIVE_HYBRID_PROGRAMME,
            bench_attempt=envelope_for_purpose(INHIBITED_ZERO_WRITE).as_dict(),
            qualified_d14_accepted_apertures=None,
        )
        == "interrupted_incomplete"
    )
