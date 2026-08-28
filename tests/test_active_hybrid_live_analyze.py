from __future__ import annotations

import json
from pathlib import Path

import pytest

from host.otis_tools import active_hybrid_live_analyze as live_analyze
from host.otis_tools.active_hybrid_live_analyze import (
    PRE_SETUP_PROVENANCE_UNRESOLVED,
    _classify_decision,
    _cx320_commands_exact,
    _frequency_metrics,
    _historical_manifest_for_superseding_replay,
    _legacy_checkpoint_terminal_misclassified,
    _legacy_plant_terminal_decision,
    _metric_contract,
    _phase_metrics,
    _pre_setup_commands_exact,
    _pre_setup_provenance_terminal_facts,
    _pre_setup_wall_origin_exact,
    _replay_ahy,
    _response_attestations,
    _response_dependent_consumer_propagation,
    _sustained_regulation_outcome,
    _tight_deadband_policy_sha256,
    _wall_origin_and_setup_order_exact,
)
from host.otis_tools.active_hybrid_programme_contract import (
    CX322_D9_D6_INTEGRATION_PROGRAMME,
)
from host.otis_tools.active_hybrid_policy import load_policy
from host.otis_tools.active_hybrid_rehearsal import (
    _modeled_transaction,
    _write_csv,
)
from host.otis_tools.contracts import (
    ACTIVE_HYBRID_DECISION_V1_FIELDS,
    CONTRACT_FIELDS,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = (
    ROOT / "profiles/discipline/cx320_bounded_active_hybrid_tight_v1.json"
)


def _thresholds() -> dict[str, object]:
    document = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    policy = load_policy(POLICY_PATH)
    return _metric_contract(
        document, comparison_observations=policy.phase_qualification_residence_s
    )


def test_frozen_phase_and_frequency_metrics_pass_matched_1800() -> None:
    rows = []
    for sequence in range(1, 3_601):
        phase = (
            sequence * 10
            if sequence <= 1_800
            else 18_000 + (sequence - 1_800) * 5
        )
        rows.append(
            {
                "phase_epoch": "4",
                "capture_session": "1",
                "observation_sequence": str(sequence),
                "closing_reference_sequence": str(sequence),
                "relative_phase_cycles": str(phase),
                "qualification_state": "qualified",
            }
        )
    first_material = {
        "phase_epoch": "4",
        "capture_session": "1",
        "phase_observation_sequence": "1800",
        "source_last_sequence": "1800",
    }
    thresholds = _thresholds()
    phase = _phase_metrics(rows, first_material, thresholds)
    assert phase["exact"] is True
    assert phase["pass"] is True
    assert phase["absolute_ols_slope_baseline_cycles_per_s"] == 10.0
    assert phase["absolute_ols_slope_matched_active_cycles_per_s"] == 5.0
    assert phase["absolute_ols_slope_active_segment_cycles_per_s"] == 5.0
    assert phase["matched_1800_improvement_cycles"] == 9_000.0
    assert phase["matched_1800_improvement_fraction"] == 0.5

    estimates = [
        {
            "estimate_id": f"estimate-{index}",
            "estimator_version": "cx317_selected_600s_nonoverlap_v1",
            "observation_validity": "valid",
            "reference_validity": "valid",
            "reference_continuity": "true",
            "count_validity": "valid",
            "count_continuity": "true",
            "diagnostic_health": "healthy",
            "source_reference_last_seq": str(reference),
            "frequency_error_hz": str(error),
        }
        for index, (reference, error) in enumerate(
            [
                (600, 0.001),
                (1_200, -0.001),
                (1_800, 0.001),
                (2_400, 0.0011),
                (3_000, -0.0011),
                (3_600, 0.0011),
            ],
            start=1,
        )
    ]
    tdb = [
        {"estimate_id": row["estimate_id"], "state_after": "TIGHT_INSIDE"}
        for row in estimates
    ]
    frequency = _frequency_metrics(estimates, tdb, phase, thresholds)
    assert frequency["exact"] is True
    assert frequency["pass"] is True
    assert frequency["frequency_rms_degradation_hz"] < 1.0 / 600.0
    assert frequency["tight_inside_occupancy_degradation_fraction"] == 0.0


def test_sustained_outcome_uses_exact_raw_phase_window_and_counter_time() -> None:
    decision_rows = [
        {
            "decision_sequence": "1",
            "reason": "phase_material_request_ready",
            "phase_epoch": "1",
            "phase_observation_sequence": "10000",
        },
        {
            "decision_sequence": "2",
            "reason": "deliberate_reversal_challenge_request_ready",
            "phase_epoch": "1",
            "phase_observation_sequence": "50000",
        },
        {
            "decision_sequence": "3",
            "reason": "deliberate_reversal_challenge_recovery_request_ready",
            "phase_epoch": "1",
            "phase_observation_sequence": "60000",
        },
    ]
    active_rows = [
        {
            "event": "application",
            "request_sequence": str(sequence),
            "decision_sequence": str(sequence),
            "application_timestamp_s": str(timestamp),
            "applied_code": str(code),
            "dac_epoch": str(sequence + 1),
            "requested_delta_codes": str(delta),
        }
        for sequence, timestamp, code, delta in (
            (1, 10_000, 43_063, -5),
            (2, 50_000, 43_042, -21),
            (3, 60_000, 43_047, 5),
        )
    ]
    phase_rows = [
        {
            "phase_epoch": "1",
            "observation_sequence": str(sequence),
            "relative_phase_cycles": "7",
            "qualification_state": "qualified",
        }
        for sequence in range(64_801, 86_401)
    ]
    status, decision, facts = _sustained_regulation_outcome(
        integrity_exact=True,
        operator_abort=False,
        platform_terminal=False,
        endpoint_complete=True,
        terminal={},
        supervisor_state={"qualified_origin_timestamp_ticks": 0},
        active_rows=active_rows,
        decision_rows=decision_rows,
        phase_rows=phase_rows,
        applications={
            "automatic_application_count": 2,
            "physical_control_application_count": 3,
            "deliberate_challenge_application_count": 1,
            "cumulative_movement_codes": 31,
        },
        no_fault_or_chatter=True,
        frequency_pass=True,
        qualified_duration_s=86_400,
    )
    assert status == "passed"
    assert decision == "sustained_hybrid_regulation_demonstrated_challenge_reversal"
    assert facts["post_reversal_ticks"] == 26_400 * 16_000_000
    assert facts["final_phase_window_row_count"] == 21_600
    assert facts["final_phase_window_contiguous"] is True
    assert facts["final_phase_OLS_slope_exact_numerator"] == 0
    assert facts["final_phase_slope_pass"] is True


def test_response_identity_reaches_first_dependent_decision_exactly() -> None:
    response = {
        "event": "response",
        "request_sequence": "2",
        "transaction_record_sequence": "9",
        "decision_sequence": "9",
        "application_sequence": "2",
        "applied_code": "43062",
        "dac_epoch": "3",
        "response_class": "healthy_indeterminate_near_resolution",
    }
    boundary = {
        "decision_sequence": "10",
        "authority_state": "AWAITING_RESPONSE",
        "request_sequence": "2",
    }
    consumer = {
        "decision_sequence": "11",
        "authority_state": "DISARMED",
        "request_sequence": "2",
        "application_sequence": "2",
        "response_class": "healthy_indeterminate_near_resolution",
        "actual_applied_code": "43062",
        "actual_dac_epoch": "3",
        "downstream_epoch_exact": "true",
        "reason": "first_phase_observation_recorded_and_tight_reacquired",
    }

    result = _response_dependent_consumer_propagation(
        [response], [boundary, consumer]
    )
    assert result["exact"] is True
    assert result["comparisons"][0]["consumer_decision_sequence"] == 11

    consumer["response_class"] = "unavailable"
    assert _response_dependent_consumer_propagation(
        [response], [boundary, consumer]
    )["exact"] is False


def test_sustained_platform_integrity_fault_precedes_operator_abort_label() -> None:
    status, decision, _ = _sustained_regulation_outcome(
        integrity_exact=False,
        operator_abort=True,
        platform_terminal=False,
        endpoint_complete=False,
        terminal={"primary_decision": "operator_abort"},
        supervisor_state={},
        active_rows=[],
        decision_rows=[],
        phase_rows=[],
        applications={
            "automatic_application_count": 0,
            "physical_control_application_count": 0,
            "deliberate_challenge_application_count": 0,
            "cumulative_movement_codes": 0,
        },
        no_fault_or_chatter=True,
        frequency_pass=False,
        qualified_duration_s=86_400,
    )
    assert status == "failed"
    assert decision == "measurement_authority_or_platform_fault"


def test_command_and_wall_origin_setup_order_are_exact() -> None:
    setup = "ACTIVE SETUP 1 2 3 4 5 0xA83C 1 " + "a" * 64
    submitted = ["CONFIG?", "DUALCORE?", "DAC?", setup]
    events = [
        {"event": "command_submitted", "command": command}
        for command in submitted
    ] + [
        {"event": "host_written", "command": command} for command in submitted
    ]
    markers = [
        {"event": "capture_started"},
        *[
            {"event": "host_command_sent", "command": command}
            for command in submitted
        ],
    ]
    assert _cx320_commands_exact(
        markers,
        events,
        {"emergency_aborts_sent": 0},
        setup_code=0xA83C,
        allowed_emergency_aborts=0,
    )

    manifest = {"started_at_utc": "2026-08-20T12:00:00Z", "manifest_sha256": "b" * 64}
    supervisor_state = {"wall_origin_utc": manifest["started_at_utc"]}
    supervisor_events = [
        {
            "event": "cx320_live_supervisor_started",
            "wall_origin_utc": manifest["started_at_utc"],
            "manifest_sha256": manifest["manifest_sha256"],
        },
        {"event": "cx320_exact_setup_requested"},
    ]
    assert _wall_origin_and_setup_order_exact(
        manifest, supervisor_state, supervisor_events, markers
    )
    assert not _wall_origin_and_setup_order_exact(
        manifest, supervisor_state, list(reversed(supervisor_events)), markers
    )


def test_pre_setup_provenance_terminal_requires_exact_no_authority_path() -> None:
    programme = CX322_D9_D6_INTEGRATION_PROGRAMME
    manifest = {
        "started_at_utc": "2026-08-28T13:25:50Z",
        "manifest_sha256": "a" * 64,
    }
    commands = [
        "CONFIG?",
        "DUALCORE?",
        "DAC?",
        "ACTIVE LEASE 1",
        "ACTIVE SNAPSHOT 9",
        "CONFIG?",
        "ACTIVE LEASE 2",
    ]
    events = [
        {
            "event": f"{programme.key}_live_supervisor_started",
            "wall_origin_utc": manifest["started_at_utc"],
            "manifest_sha256": manifest["manifest_sha256"],
        },
        *[
            {"event": "command_submitted", "command": command}
            for command in commands
        ],
        *[
            {"event": "host_written", "command": command}
            for command in commands
        ],
        {"event": "emergency_device_abort_submitted"},
    ]
    markers = [
        {"event": "capture_started"},
        *[
            {"event": "host_command_sent", "command": command}
            for command in commands
        ],
        {"event": "host_command_sent", "command": "ACTIVE ABORT"},
        {"event": "capture_stopped"},
    ]
    capture_state = {"emergency_aborts_sent": 1}
    supervisor_state = {
        "wall_origin_utc": manifest["started_at_utc"],
        "manual_start_sent": False,
        "setup_requested_utc": None,
        "setup_confirmed_utc": None,
        "setup_authority_path": None,
        "prewrite_contract_ready_utc": None,
        "arm_pending": False,
        "terminal_static_code": None,
        "latest_prewrite_readiness": {
            "physical_dac_confirmation": "unknown_before_live_stimulus"
        },
    }
    health = {
        ("dac", "applied_code_known"): "false",
        ("dac", "last_applied_code"): "unavailable",
        ("cx317_active", "confirmed_applied_code_known"): "false",
        ("cx317_active", "confirmed_applied_code"): "unavailable",
        ("cx317_active", "dac_epoch"): "0",
        ("cx317_active", "state"): "ABORTED",
        ("cx317_active", "hybrid_state"): "SETUP_PENDING",
        ("cx317_active", "fail_static"): "true",
        ("cx317_active", "manual_start_confirmed"): "false",
        ("cx317_active", "evidence_pending"): "false",
        ("cx317_active", "evidence_phase"): "evidence_clear",
        ("cx317_active", "evidence_request_sequence"): "0",
        ("cx317_active", "correction_count"): "0",
        ("cx317_active", "automatic_application_count"): "0",
        ("cx317_active", "cumulative_movement_codes"): "0",
    }
    terminal = {
        "result": "aborted",
        "primary_decision": "measurement_authority_or_platform_fault",
        "reason": (
            f"{programme.key}_live_supervisor_fault:"
            "live active_fail_static asserted"
        ),
    }
    assert _pre_setup_commands_exact(markers, events, capture_state)
    assert _pre_setup_wall_origin_exact(
        manifest, supervisor_state, events, markers, programme
    )

    arguments = {
        "programme": programme,
        "terminal": terminal,
        "supervisor_state": supervisor_state,
        "health": health,
        "active_rows": [],
        "decision_rows": [],
        "dac_rows": [],
        "estimate_rows": [],
        "command_stream_exact": True,
        "wall_origin_exact": True,
        "abort_ordering_exact": True,
        "capture_closure_exact": True,
        "d9_readback_exact": True,
        "aligned_interval_count": 448,
    }
    facts = _pre_setup_provenance_terminal_facts(**arguments)
    assert facts["exact"] is True
    assert facts["aligned_d14_d8_d6_interval_count"] == 448
    assert facts["setup_or_application_authority_reached"] is False
    assert facts["measurement_authority_fault_claimed"] is False

    assert not _pre_setup_provenance_terminal_facts(
        **{**arguments, "active_rows": [{"event": "manual_start"}]}
    )["exact"]
    assert not _pre_setup_provenance_terminal_facts(
        **{**arguments, "d9_readback_exact": False}
    )["exact"]
    assert not _pre_setup_provenance_terminal_facts(
        **{**arguments, "aligned_interval_count": 0}
    )["exact"]

    setup_command = "ACTIVE SETUP 1 2 3 4 5 0xA83C 1 " + "b" * 64
    assert not _pre_setup_commands_exact(
        [
            *markers[:-2],
            {"event": "host_command_sent", "command": setup_command},
            *markers[-2:],
        ],
        [
            *events,
            {"event": "command_submitted", "command": setup_command},
            {"event": "host_written", "command": setup_command},
        ],
        capture_state,
    )


def test_pre_setup_provenance_decision_never_waives_other_integrity_faults() -> None:
    arguments = {
        "operator_abort": False,
        "platform_terminal": True,
        "phase_degraded": False,
        "endpoint_complete": False,
        "material_applications": 0,
        "first_checkpoint_passed": False,
        "responses_healthy": False,
        "tight_reacquired_and_retained": False,
        "policy_limits_exact": False,
        "phase_pass": False,
        "frequency_pass": False,
        "minimum_material_applications": 2,
        "fact_gathering": True,
        "pre_setup_provenance_unresolved": True,
    }
    assert _classify_decision(integrity_exact=True, **arguments) == (
        "bounded_nonpass",
        PRE_SETUP_PROVENANCE_UNRESOLVED,
    )
    assert _classify_decision(integrity_exact=False, **arguments) == (
        "failed",
        "measurement_authority_or_platform_fault",
    )


def test_superseding_replay_rebinds_once_validated_historical_manifest(
    tmp_path: Path,
) -> None:
    identities = {
        "bundle": "bundle_sha256",
        "proposal": "proposal_sha256",
        "activation": "activation_sha256",
    }
    bindings: dict[str, dict[str, object]] = {}
    for name, semantic_key in identities.items():
        unsigned = {"schema_version": 1, "artifact": name}
        artifact = {
            **unsigned,
            semantic_key: live_analyze._canonical_sha256(unsigned),
        }
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(artifact), encoding="utf-8")
        bindings[name] = {
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": live_analyze._sha256_file(path),
            semantic_key: artifact[semantic_key],
        }
    manifest_unsigned = {
        "schema_version": 1,
        "run_id": "attempt-1",
        "run_identity": "cx322_d9_d6_integration_engineering:1",
        "firmware": {"build_identity": "b" * 64 + ":" + "c" * 64},
        **bindings,
    }
    manifest = {
        **manifest_unsigned,
        "manifest_sha256": live_analyze._canonical_sha256(manifest_unsigned),
    }
    manifest_path = tmp_path / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    prior_unsigned = {
        "schema_version": 1,
        "run_id": manifest["run_id"],
        "run_identity": manifest["run_identity"],
        "build_identity": manifest["firmware"]["build_identity"],
        "bundle_sha256": bindings["bundle"]["bundle_sha256"],
        "proposal_sha256": bindings["proposal"]["proposal_sha256"],
        "activation_sha256": bindings["activation"]["activation_sha256"],
        "acquisition_gate": {
            "checks": {"frozen_live_manifest_exact": True}
        },
    }
    prior = {
        **prior_unsigned,
        "seal_sha256": live_analyze._canonical_sha256(prior_unsigned),
    }
    prior_path = tmp_path / "prior_seal.json"
    prior_path.write_text(json.dumps(prior), encoding="utf-8")

    observed, provenance = _historical_manifest_for_superseding_replay(
        manifest_path, prior_path
    )

    assert observed == manifest
    assert provenance["current_contract_validation"] is False
    assert provenance["predecessor_frozen_manifest_attestation_exact"] is True
    (tmp_path / "activation.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="activation byte binding differs"):
        _historical_manifest_for_superseding_replay(manifest_path, prior_path)


def test_ahy_replay_detects_materiality_counterfactual_tamper() -> None:
    policy = load_policy(POLICY_PATH)
    build_identity = "b" * 64 + ":" + "c" * 64
    _, rows, transactions = _modeled_transaction(
        {
            "run_identity": "cx320_active_hybrid:3200001",
            "bundle_sha256": "d" * 64,
            "policy": {"policy_sha256": policy.policy_sha256},
            "firmware": {"build_identity": build_identity},
            "setup": {
                "consumer_epoch_propagation_required": [
                    "frequency_estimator",
                    "phase_estimator",
                    "controller",
                    "preview_replay",
                    "recorder",
                    "response_classifier",
                ]
            },
        }
    )
    replay = _replay_ahy(
        rows,
        transactions,
        policy_path=POLICY_PATH,
        expected_run_identity="cx320_active_hybrid:3200001",
        expected_build_identity=build_identity,
        expected_profile_identity="cx320_active_hybrid",
    )
    assert replay["exact"] is True
    assert replay["phase_material_decision_count"] == 2

    tampered = [dict(row) for row in rows]
    material = next(
        row for row in tampered if row["phase_materially_influenced"] == "true"
    )
    material["counterfactual_frequency_only_delta_codes"] = str(
        int(material["counterfactual_frequency_only_delta_codes"]) + 1
    )
    assert _replay_ahy(
        tampered,
        transactions,
        policy_path=POLICY_PATH,
        expected_run_identity="cx320_active_hybrid:3200001",
        expected_build_identity=build_identity,
        expected_profile_identity="cx320_active_hybrid",
    )["exact"] is False


def test_terminal_response_sign_rejection_is_exact_without_phase4_ack(
    tmp_path: Path,
) -> None:
    policy = load_policy(POLICY_PATH)
    build_identity = "b" * 64 + ":" + "c" * 64
    bundle = {
        "run_identity": "cx320_active_hybrid:3200001",
        "bundle_sha256": "d" * 64,
        "policy": {"policy_sha256": policy.policy_sha256},
        "firmware": {"build_identity": build_identity},
        "setup": {
            "consumer_epoch_propagation_required": [
                "frequency_estimator",
                "phase_estimator",
                "controller",
                "preview_replay",
                "recorder",
                "response_classifier",
            ]
        },
    }
    _, ahy_rows, transaction_rows = _modeled_transaction(bundle)
    material = next(
        row for row in ahy_rows if row["phase_materially_influenced"] == "true"
    )
    response_index = next(
        index
        for index, row in enumerate(transaction_rows)
        if row["event"] == "response"
        and row["decision_sequence"] == material["decision_sequence"]
    )
    response = transaction_rows[response_index]
    response.update(
        {
            "post_error_hz": "0.000000000",
            "observed_response_hz": "0.000000000",
            "cumulative_response_hz": "0.000000000",
            "consecutive_indeterminate": "1",
            "response_class": "healthy_indeterminate_near_resolution",
            "reason": "healthy_evidence_below_empirical_detection_floor",
        }
    )
    horizon_index = next(
        index
        for index, row in enumerate(ahy_rows)
        if int(row["decision_sequence"]) > int(material["decision_sequence"])
        and row["authority_state"] == "AWAITING_RESPONSE"
    )
    ahy_rows[horizon_index]["frequency_error_hz"] = "0.000000000000"
    ahy_rows[horizon_index]["frequency_term_hz"] = "-0.000000000000"
    ahy_rows = ahy_rows[: horizon_index + 1]
    transaction_rows = transaction_rows[: response_index + 1]
    run_dir = tmp_path / "run"
    (run_dir / "csv").mkdir(parents=True)
    _write_csv(
        run_dir / "csv/active_hybrid_decisions_v1.csv",
        ACTIVE_HYBRID_DECISION_V1_FIELDS,
        ahy_rows,
    )
    _write_csv(
        run_dir / "csv/active_transactions_v1.csv",
        CONTRACT_FIELDS["active_transactions_v1"],
        transaction_rows,
    )
    events = [
        {
            "event": "cx320_live_supervisor_fault",
            "error": "CX320 independent host replay differs from the firmware decision",
        }
    ]

    exact, hashes, comparisons, rejected = _response_attestations(
        run_dir, [response], events
    )

    assert exact is True
    assert hashes == {}
    assert rejected == frozenset({int(response["transaction_record_sequence"])})
    assert comparisons == [
        {
            "request_sequence": int(response["request_sequence"]),
            "record_sequence": int(response["transaction_record_sequence"]),
            "exact": True,
            "replayed_attestation_sha256": None,
            "checkpoint_passed": False,
            "expected_rejection": True,
        }
    ]


def test_terminal_classification_uses_one_declared_primary_decision() -> None:
    status, decision = _classify_decision(
        integrity_exact=True,
        operator_abort=False,
        platform_terminal=False,
        phase_degraded=False,
        endpoint_complete=True,
        material_applications=2,
        first_checkpoint_passed=True,
        responses_healthy=True,
        tight_reacquired_and_retained=True,
        policy_limits_exact=True,
        phase_pass=True,
        frequency_pass=True,
        minimum_material_applications=2,
    )
    assert (status, decision) == ("passed", "bounded_active_hybrid_control_passed")

    status, decision = _classify_decision(
        integrity_exact=True,
        operator_abort=False,
        platform_terminal=False,
        phase_degraded=False,
        endpoint_complete=True,
        material_applications=1,
        first_checkpoint_passed=True,
        responses_healthy=True,
        tight_reacquired_and_retained=True,
        policy_limits_exact=True,
        phase_pass=True,
        frequency_pass=True,
        minimum_material_applications=2,
    )
    assert status == "bounded_nonpass"
    assert decision == "first_phase_transaction_passed_sustained_result_incomplete"


def test_legacy_checkpoint_override_does_not_hide_other_platform_faults() -> None:
    terminal = {
        "result": "aborted",
        "primary_decision": "measurement_authority_or_platform_fault",
        "reason": (
            "cx320_live_supervisor_fault:CX320 independent host replay "
            "differs from the firmware decision"
        ),
    }
    assert _legacy_checkpoint_terminal_misclassified(
        terminal, checkpoint_rejection_evidence_exact=True
    )
    assert not _legacy_checkpoint_terminal_misclassified(
        {**terminal, "reason": "cx320_live_supervisor_fault:capture owner lost"},
        checkpoint_rejection_evidence_exact=True,
    )
    assert not _legacy_checkpoint_terminal_misclassified(
        terminal, checkpoint_rejection_evidence_exact=False
    )


def test_legacy_plant_terminal_override_is_exact_and_narrow() -> None:
    terminal = {
        "result": "aborted",
        "primary_decision": "measurement_authority_or_platform_fault",
        "reason": "cx321_live_supervisor_fault:live active_fail_static asserted",
    }
    rows = [
        {
            "event": "pre2",
            "state_after": "PLANT_SIGN_NOT_EXERCISED",
            "reason": "second_pre_window_not_equal_and_tight",
        }
    ]
    assert _legacy_plant_terminal_decision(terminal, rows) == (
        "plant_sign_qualification_not_exercised"
    )
    assert _legacy_plant_terminal_decision(
        {**terminal, "reason": "cx321_live_supervisor_fault:capture owner lost"},
        rows,
    ) is None


def test_ahy_replay_accepts_exact_pre_handoff_scientific_terminal() -> None:
    replay = _replay_ahy(
        [],
        [{"event": "manual_start"}],
        policy_path=POLICY_PATH,
        expected_run_identity="cx321_active_hybrid:3210001",
        expected_build_identity="b" * 64 + ":" + "c" * 64,
        expected_profile_identity="cx321_active_hybrid",
        plant_sign_records=[
            {
                "event": "pre2",
                "state_after": "PLANT_SIGN_NOT_EXERCISED",
                "reason": "second_pre_window_not_equal_and_tight",
            }
        ],
    )
    assert replay["exact"] is True
    assert replay["natural_controller_not_reached"] is True


def test_partial_prewrite_terminal_is_sealed_as_platform_fault(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "partial"
    run_dir.mkdir()
    (run_dir / "run_manifest.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "COMPLETE").write_text("{}\n", encoding="utf-8")
    policy_sha256 = load_policy(POLICY_PATH).policy_sha256
    manifest = {
        "schema_version": 1,
        "stage": "CX320_BOUNDED_ACTIVE_HYBRID_PHASE_FREQUENCY_LIVE",
        "programme_id": "CX320_BOUNDED_ACTIVE_HYBRID_PHASE_FREQUENCY_V1",
        "run_id": "partial",
        "run_identity": "cx320_active_hybrid:3200001",
        "profile_identity": "cx320_active_hybrid",
        "started_at_utc": "2026-08-20T12:00:00Z",
        "manifest_sha256": "a" * 64,
        "channels": [],
        "domains": [],
        "contracts": {},
        "files": [],
        "evidence_artifacts": [],
        "policy": {
            "path": str(POLICY_PATH),
            "sha256": policy_sha256,
            "policy_sha256": policy_sha256,
        },
        "firmware": {
            "build_identity": "b" * 64 + ":" + "c" * 64,
            "uf2": {"sha256": "d" * 64},
        },
        "bundle": {"bundle_sha256": "e" * 64},
        "proposal": {"proposal_sha256": "f" * 64},
        "activation": {"activation_sha256": "1" * 64},
        "cx320": {
            "setup": {"code": 0xA83C},
            "automatic_control": {
                "maximum_total_applications": 4,
                "maximum_cumulative_movement_codes": 84,
                "maximum_step_codes": 21,
                "minimum_applied_cadence_s": 1_800,
                "minimum_code": 0xA800,
                "maximum_code": 0xAB00,
            },
        },
    }
    monkeypatch.setattr(
        live_analyze, "validate_frozen_run_manifest", lambda _path: manifest
    )
    monkeypatch.setattr(
        live_analyze,
        "_replay_ahy",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("partial active-hybrid evidence is unavailable")
        ),
    )
    output, seal = live_analyze.analyze(run_dir)
    assert output.is_file()
    assert seal["status"] == "failed"
    assert seal["primary_decision"] == "measurement_authority_or_platform_fault"
    assert seal["missing_source_artifacts"]
    assert any(
        "active-hybrid replay: partial active-hybrid evidence is unavailable"
        in failure
        for failure in seal["retained_input_failures"]
    )
    assert seal["offline_finalization_gate"]["passed"] is False


def test_cx320_analyzer_binds_tdb_to_frozen_frequency_predecessor() -> None:
    policy_document = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    tight_sha256 = policy_document["bindings"]["frequency_policy_predecessor"][
        "sha256"
    ]
    assert _tight_deadband_policy_sha256(policy_document) == tight_sha256
