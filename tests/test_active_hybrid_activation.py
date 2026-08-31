from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools import active_hybrid_activation as activation
from host.otis_tools.active_hybrid_programme_contract import (
    CX320_PROGRAMME,
    CX321_PROGRAMME,
    CX322_D9_D6_72H_PROGRAMME,
    CX322_D9_D6_INTEGRATION_PROGRAMME,
    CX323_D9_D6_72H_PROGRAMME,
    SUSTAINED_HYBRID_PROGRAMME,
)


def _write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _semantic(value: dict[str, object], field: str) -> dict[str, object]:
    return {**value, field: activation._canonical_sha256(value)}


def test_long_run_programmes_require_their_exact_evidence_products() -> None:
    campaign18 = {
        entry["contract"]: entry
        for entry in activation._required_files(CX322_D9_D6_72H_PROGRAMME)
    }
    assert campaign18["active_transactions_v2"].get("optional") is None
    assert campaign18["active_hybrid_decisions_v2"].get("optional") is None

    cx323 = {
        entry["contract"]: entry
        for entry in activation._required_files(CX323_D9_D6_72H_PROGRAMME)
    }
    assert cx323["active_transactions_v2"].get("optional") is None
    assert cx323["active_hybrid_decisions_v2"].get("optional") is None
    assert cx323["active_hybrid_maintenance_v1"] == {
        "path": "csv/active_hybrid_maintenance_v1.csv",
        "contract": "active_hybrid_maintenance_v1",
    }

    for historical in (
        CX320_PROGRAMME,
        CX321_PROGRAMME,
        CX322_D9_D6_INTEGRATION_PROGRAMME,
        SUSTAINED_HYBRID_PROGRAMME,
    ):
        contracts = {
            entry["contract"] for entry in activation._required_files(historical)
        }
        assert "active_transactions_v2" not in contracts
        assert "active_hybrid_decisions_v2" not in contracts
        assert "active_hybrid_maintenance_v1" not in contracts


def test_campaign18_activation_accepts_only_exact_shared_rehearsal_receipt(
    tmp_path: Path,
) -> None:
    bundle = {
        "programme_id": CX322_D9_D6_72H_PROGRAMME.programme_id,
        "bundle_sha256": "b" * 64,
        "host_tools": {},
    }
    proposal = {"proposal_sha256": "c" * 64}
    coverage = {
        name: True
        for name in (
            *activation.REHEARSAL_COVERAGE,
            *activation.CAMPAIGN18_REHEARSAL_COVERAGE,
            "integrated_setup_provenance_boundary",
            "mandatory_sustained_status_snapshot_identity",
        )
    }
    unsigned = {
        "schema_version": 1,
        "report_type": CX322_D9_D6_72H_PROGRAMME.rehearsal_report_type,
        "status": "passed",
        "bundle_sha256": bundle["bundle_sha256"],
        "proposal_sha256": proposal["proposal_sha256"],
        "physical_actions_performed": 0,
        "qualification_evidence": False,
        "coverage": coverage,
        "tool_bindings": {},
        "setup_provenance_contract": activation.integrated_setup_provenance_contract(
            CX322_D9_D6_72H_PROGRAMME
        ),
        "real_process_topology": {
            "cx322_real_transaction_path": {
                "complete_multi_transaction_sequence": True,
                "request_sequences_consumed": [1, 2],
                "gnss_hold_and_causal_requalification": True,
                "gnss_bootstrap_in_progress_observed_by_supervisor": True,
                "first_post_requalification_consumer_exact": True,
                "first_post_recovery_consumer_decision_sequence": 12,
            }
        },
        "accelerated_qualified_device_clock": {
            "correction_admission_close_elapsed_s": 257_700,
            "qualified_endpoint_elapsed_s": 259_200,
            "admission_open_at_floor_before_exact_boundary": True,
            "admission_closed_at_exact_boundary": True,
            "forward_host_utc_step_did_not_close_early": True,
            "backward_host_utc_step_did_not_delay_endpoint": True,
        },
    }
    receipt = _semantic(unsigned, "rehearsal_sha256")
    receipt_path = tmp_path / (
        f"{CX322_D9_D6_72H_PROGRAMME.rehearsal_report_type}.json"
    )
    _write(receipt_path, receipt)
    _write(
        tmp_path / "process_topology/run/run_manifest.json",
        {
            "programme_id": CX322_D9_D6_72H_PROGRAMME.programme_id,
            "profile_identity": CX322_D9_D6_72H_PROGRAMME.profile_id,
            "contracts": {
                "active_transactions_v2": 2,
                "active_hybrid_decisions_v2": 2,
            },
            "files": [
                {
                    "path": "csv/active_transactions_v2.csv",
                    "contract": "active_transactions_v2",
                },
                {
                    "path": "csv/active_hybrid_decisions_v2.csv",
                    "contract": "active_hybrid_decisions_v2",
                },
            ],
            "domains": [
                {"name": "rp2040_timer0_extended", "nominal_hz": 16_000_000}
            ],
        },
    )

    observed = activation.validate_operational_rehearsal(
        receipt_path,
        bundle=bundle,
        proposal=proposal,
        require_current_tools=False,
        programme=CX322_D9_D6_72H_PROGRAMME,
    )

    assert observed["report_type"] == (
        CX322_D9_D6_72H_PROGRAMME.rehearsal_report_type
    )
    changed = dict(receipt)
    changed["real_process_topology"] = {
        "cx322_real_transaction_path": {
            "complete_multi_transaction_sequence": True,
            "request_sequences_consumed": [1, 2],
            "gnss_hold_and_causal_requalification": False,
            "gnss_bootstrap_in_progress_observed_by_supervisor": True,
            "first_post_requalification_consumer_exact": True,
            "first_post_recovery_consumer_decision_sequence": 12,
        }
    }
    changed_unsigned = {
        key: value for key, value in changed.items() if key != "rehearsal_sha256"
    }
    changed["rehearsal_sha256"] = activation._canonical_sha256(changed_unsigned)
    _write(receipt_path, changed)
    with pytest.raises(ValueError, match="Campaign 18 rehearsal lacks"):
        activation.validate_operational_rehearsal(
            receipt_path,
            bundle=bundle,
            proposal=proposal,
            require_current_tools=False,
            programme=CX322_D9_D6_72H_PROGRAMME,
        )


def _cx321_rehearsal_receipt(tmp_path: Path) -> tuple[Path, dict, dict]:
    digest = "a" * 64
    extended = f"ACTIVE EVIDENCE 1 4 5 -5 1 2 6302 {digest}"
    bundle = {
        "programme_id": CX321_PROGRAMME.programme_id,
        "bundle_sha256": "b" * 64,
        "host_tools": {},
    }
    proposal = {"proposal_sha256": "c" * 64}
    unsigned = {
        "schema_version": 1,
        "report_type": CX321_PROGRAMME.rehearsal_report_type,
        "status": "passed",
        "bundle_sha256": bundle["bundle_sha256"],
        "proposal_sha256": proposal["proposal_sha256"],
        "physical_actions_performed": 0,
        "qualification_evidence": False,
        "coverage": {
            name: True for name in activation.REHEARSAL_COVERAGE
        },
        "tool_bindings": {},
        "cx321_identification_ordering": {
            "no_early_or_stale_identification_arm": True,
            "one_exact_pre2_identification_arm": True,
            "phase4_waited_for_matching_psq_after_act_split": True,
        },
        "real_process_topology": {
            "cx321_real_transaction_path": {
                "canonical_psq_field_count": 60,
                "canonical_snp_rows_captured": 4502,
                "canonical_act_field_count": 47,
                "evidence_phase_commands": [
                    "ACTIVE EVIDENCE 1 1",
                    "ACTIVE EVIDENCE 1 2",
                    "ACTIVE EVIDENCE 1 3",
                    extended,
                ],
                "extended_phase4_command": extended,
                "complete_evidence_chain_sha256": digest,
                "raw_snapshot_proof_sha256": "d" * 64,
                "act_response_join": {"exact": True},
                "raw_timer_rollover_between_application_and_response": True,
                "firmware_consumption_confirmed": True,
                "response_ack_handoff_exact": True,
                "first_natural_decision": {
                    "request_sequence": 2,
                    "global_correction_count_before": 1,
                    "global_cumulative_movement_before_codes": 21,
                    "natural_cumulative_movement_codes": 0,
                    "natural_direction_count": 0,
                    "plant_sign_handoff_first_consumer": True,
                    "phase_materially_influenced": True,
                },
                "natural_evidence_phase_commands": [
                    "ACTIVE EVIDENCE 2 1",
                    "ACTIVE EVIDENCE 2 2",
                    "ACTIVE EVIDENCE 2 3",
                    "ACTIVE EVIDENCE 2 4",
                ],
                "natural_response_firmware_consumption_confirmed": True,
                "natural_ahy_rows_captured": 2,
            }
        },
    }
    receipt = _semantic(unsigned, "rehearsal_sha256")
    path = tmp_path / "cx321-rehearsal.json"
    _write(path, receipt)
    return path, bundle, proposal


def test_cx321_activation_accepts_exact_real_process_transaction_receipt(
    tmp_path: Path,
) -> None:
    path, bundle, proposal = _cx321_rehearsal_receipt(tmp_path)

    result = activation.validate_operational_rehearsal(
        path,
        bundle=bundle,
        proposal=proposal,
        require_current_tools=False,
        programme=CX321_PROGRAMME,
    )

    assert result["rehearsal_sha256"]


def test_sustained_activation_accepts_exact_multi_transaction_coverage(
    tmp_path: Path,
) -> None:
    bundle = {
        "programme_id": SUSTAINED_HYBRID_PROGRAMME.programme_id,
        "bundle_sha256": "b" * 64,
        "host_tools": {},
    }
    proposal = {"proposal_sha256": "c" * 64}
    expected_coverage = (
        set(activation.REHEARSAL_COVERAGE)
        | set(activation.SUSTAINED_REHEARSAL_COVERAGE)
    )
    unsigned = {
        "schema_version": 1,
        "report_type": SUSTAINED_HYBRID_PROGRAMME.rehearsal_report_type,
        "status": "passed",
        "bundle_sha256": bundle["bundle_sha256"],
        "proposal_sha256": proposal["proposal_sha256"],
        "physical_actions_performed": 0,
        "qualification_evidence": False,
        "coverage": {name: True for name in expected_coverage},
        "tool_bindings": {},
    }
    path = tmp_path / "sustained-rehearsal.json"
    _write(path, _semantic(unsigned, "rehearsal_sha256"))

    result = activation.validate_operational_rehearsal(
        path,
        bundle=bundle,
        proposal=proposal,
        require_current_tools=False,
        programme=SUSTAINED_HYBRID_PROGRAMME,
    )

    assert result["rehearsal_sha256"]


def test_sustained_activation_rejects_missing_multi_transaction_coverage(
    tmp_path: Path,
) -> None:
    bundle = {
        "programme_id": SUSTAINED_HYBRID_PROGRAMME.programme_id,
        "bundle_sha256": "b" * 64,
        "host_tools": {},
    }
    proposal = {"proposal_sha256": "c" * 64}
    unsigned = {
        "schema_version": 1,
        "report_type": SUSTAINED_HYBRID_PROGRAMME.rehearsal_report_type,
        "status": "passed",
        "bundle_sha256": bundle["bundle_sha256"],
        "proposal_sha256": proposal["proposal_sha256"],
        "physical_actions_performed": 0,
        "qualification_evidence": False,
        "coverage": {name: True for name in activation.REHEARSAL_COVERAGE},
        "tool_bindings": {},
    }
    path = tmp_path / "incomplete-sustained-rehearsal.json"
    _write(path, _semantic(unsigned, "rehearsal_sha256"))

    with pytest.raises(ValueError, match="rehearsal receipt"):
        activation.validate_operational_rehearsal(
            path,
            bundle=bundle,
            proposal=proposal,
            require_current_tools=False,
            programme=SUSTAINED_HYBRID_PROGRAMME,
        )


def test_integrated_activation_requires_unarmed_observation_coverage(
    tmp_path: Path,
) -> None:
    bundle = {
        "programme_id": CX322_D9_D6_INTEGRATION_PROGRAMME.programme_id,
        "bundle_sha256": "b" * 64,
        "host_tools": {},
    }
    proposal = {"proposal_sha256": "c" * 64}
    expected_coverage = (
        set(activation.REHEARSAL_COVERAGE)
        | set(activation.INTEGRATED_REHEARSAL_COVERAGE)
    )
    unsigned = {
        "schema_version": 1,
        "report_type": (
            CX322_D9_D6_INTEGRATION_PROGRAMME.rehearsal_report_type
        ),
        "status": "passed",
        "bundle_sha256": bundle["bundle_sha256"],
        "proposal_sha256": proposal["proposal_sha256"],
        "physical_actions_performed": 0,
        "qualification_evidence": False,
        "coverage": {name: True for name in expected_coverage},
        "tool_bindings": {},
        "setup_provenance_contract": (
            activation.integrated_setup_provenance_contract(
                CX322_D9_D6_INTEGRATION_PROGRAMME
            )
        ),
    }
    path = tmp_path / "integrated-rehearsal.json"
    _write(path, _semantic(unsigned, "rehearsal_sha256"))

    result = activation.validate_operational_rehearsal(
        path,
        bundle=bundle,
        proposal=proposal,
        require_current_tools=False,
        programme=CX322_D9_D6_INTEGRATION_PROGRAMME,
    )

    assert result["rehearsal_sha256"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidence_phase_commands", ["ACTIVE EVIDENCE 1 1"]),
        ("complete_evidence_chain_sha256", "0" * 63),
        ("raw_timer_rollover_between_application_and_response", False),
        ("firmware_consumption_confirmed", False),
        ("response_ack_handoff_exact", False),
        ("act_response_join", {"exact": False}),
        ("natural_response_firmware_consumption_confirmed", False),
        ("natural_evidence_phase_commands", ["ACTIVE EVIDENCE 2 1"]),
        ("first_natural_decision", {"request_sequence": 2}),
    ],
)
def test_cx321_activation_rejects_incomplete_real_process_transaction_receipt(
    tmp_path: Path, field: str, value: object
) -> None:
    path, bundle, proposal = _cx321_rehearsal_receipt(tmp_path)
    receipt = json.loads(path.read_text(encoding="utf-8"))
    transaction = receipt["real_process_topology"][
        "cx321_real_transaction_path"
    ]
    transaction[field] = value
    receipt.pop("rehearsal_sha256")
    _write(path, _semantic(receipt, "rehearsal_sha256"))

    with pytest.raises(ValueError, match="real-process plant-sign"):
        activation.validate_operational_rehearsal(
            path,
            bundle=bundle,
            proposal=proposal,
            require_current_tools=False,
            programme=CX321_PROGRAMME,
        )


def test_activation_cli_forwards_cx321_programme(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle_path = tmp_path / "cx321-bundle.json"
    bundle_path.write_text(
        json.dumps(
            {
                "programme_id": (
                    "CX321_BOUNDED_ACTIVE_HYBRID_SUCCESSOR_V2"
                )
            }
        ),
        encoding="utf-8",
    )
    observed: dict[str, object] = {}

    def fake_create_activation(**kwargs):
        observed.update(kwargs)
        return {"status": "test"}

    monkeypatch.setattr(activation, "create_activation", fake_create_activation)

    assert (
        activation.main(
            [
                "activate",
                "--bundle",
                str(bundle_path),
                "--proposal",
                str(tmp_path / "proposal.json"),
                "--operational-rehearsal",
                str(tmp_path / "rehearsal.json"),
                "--serial-device",
                "/dev/test-cx321",
                "--operator-instruction-ref",
                "test-authority",
                "--output",
                str(tmp_path / "activation.json"),
            ]
        )
        == 0
    )
    assert getattr(observed["programme"], "key") == "cx321"
    assert json.loads(capsys.readouterr().out)["status"] == "test"


def _inputs(tmp_path: Path) -> tuple[Path, dict, Path, dict, Path, dict]:
    self_binding = activation._binding(Path(activation.__file__))
    bundle_unsigned: dict[str, object] = {
        "schema_version": 1,
        "bundle_id": "cx320_active_hybrid_12h_qualified_16h_wall_bundle_v1",
        "programme_id": activation.PROGRAMME_ID,
        "status": "frozen_non_effective_physical_proposal_input",
        "run_identity": activation.RUNTIME_RUN_IDENTITY,
        "authority": {
            name: False for name in activation.REQUIRED_FALSE_AUTHORITY
        },
        "policy": {
            "policy_id": "CX320_BOUNDED_ACTIVE_HYBRID_TIGHT_V1",
            "policy_sha256": "p" * 64,
        },
        "firmware": {
            "profile_id": activation.PROFILE_IDENTITY,
            "source_revision": "a" * 40,
            "source_sha256": "b" * 64,
            "configuration_sha256": "c" * 64,
            "build_identity": "b" * 64 + ":" + "c" * 64,
            "fqbn": "rp2040:test",
            "build_manifest": {"path": "/retained/build.json", "sha256": "d" * 64},
            "uf2": {"path": "/retained/image.uf2", "sha256": "e" * 64},
        },
        "host_tools": {"activation_and_manifest": self_binding},
        "finite_limits": {
            "qualified_origin": "first_complete_fresh_authoritative_600s_estimate",
            "wall_clock_origin": "sole_capture_owner_records_run_identity",
        },
    }
    bundle = _semantic(bundle_unsigned, "bundle_sha256")
    bundle_path = tmp_path / "bundle.json"
    _write(bundle_path, bundle)

    proposal_unsigned: dict[str, object] = {
        "schema_version": 1,
        "proposal_id": "cx320_active_hybrid_physical_authority_proposal_v1",
        "status": "non_effective_awaiting_separate_operator_decision",
        "programme_id": activation.PROGRAMME_ID,
        "run_identity": activation.RUNTIME_RUN_IDENTITY,
        "exact_bundle": {
            "path": str(bundle_path.resolve()),
            "file_sha256": sha256(bundle_path.read_bytes()).hexdigest(),
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "policy_sha256": bundle["policy"]["policy_sha256"],
        "build_identity": bundle["firmware"]["build_identity"],
        "authority": {
            name: False for name in activation.REQUIRED_FALSE_AUTHORITY
        },
    }
    proposal = _semantic(proposal_unsigned, "proposal_sha256")
    proposal_path = tmp_path / "proposal.json"
    _write(proposal_path, proposal)

    coverage = {name: True for name in activation.REHEARSAL_COVERAGE}
    rehearsal_unsigned: dict[str, object] = {
        "schema_version": 1,
        "report_type": activation.REHEARSAL_REPORT_TYPE,
        "status": "passed",
        "bundle_sha256": bundle["bundle_sha256"],
        "proposal_sha256": proposal["proposal_sha256"],
        "physical_actions_performed": 0,
        "qualification_evidence": False,
        "coverage": coverage,
        "tool_bindings": bundle["host_tools"],
    }
    rehearsal = _semantic(rehearsal_unsigned, "rehearsal_sha256")
    rehearsal_path = tmp_path / "rehearsal.json"
    _write(rehearsal_path, rehearsal)
    return bundle_path, bundle, proposal_path, proposal, rehearsal_path, rehearsal


def _current_validators(
    monkeypatch: pytest.MonkeyPatch, bundle: dict, proposal: dict
) -> None:
    monkeypatch.setattr(
        activation, "validate_bundle", lambda _path, *_args: bundle
    )
    monkeypatch.setattr(
        activation, "validate_proposal", lambda _path, *_args: proposal
    )
    monkeypatch.setattr(activation, "_git_clean", lambda: True)


def test_activation_is_separate_effective_artifact_and_proposal_stays_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal, rehearsal_path, _ = _inputs(
        tmp_path
    )
    _current_validators(monkeypatch, bundle, proposal)
    proposal_before = proposal_path.read_bytes()
    output = tmp_path / "activation.json"

    observed = activation.create_activation(
        bundle_path=bundle_path,
        proposal_path=proposal_path,
        operational_rehearsal_path=rehearsal_path,
        serial_device="/dev/cu.usbmodem-test",
        operator_instruction_ref="operator-authorized bundle and proposal in task",
        output_path=output,
    )

    assert proposal_path.read_bytes() == proposal_before
    assert proposal["authority"]["effective"] is False
    assert observed["authority"] == activation._authority()
    assert observed["authority"]["effective"] is True
    assert observed["device"] == {
        "path": "/dev/cu.usbmodem-test",
        "baud": 115200,
        "expected_board_serial": "503533748A919118",
    }
    assert len(set(observed["topology"]["fifos"].values())) == 3
    validated, _, _ = activation.validate_activation(output)
    assert validated == observed


def test_later_activation_binds_failed_predecessor_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal, rehearsal_path, _ = _inputs(
        tmp_path
    )
    _current_validators(monkeypatch, bundle, proposal)
    predecessor_run = tmp_path / "attempt-1"
    reports = predecessor_run / "reports"
    reports.mkdir(parents=True)
    (predecessor_run / "COMPLETE").write_text("complete\n", encoding="utf-8")
    predecessor_unsigned: dict[str, object] = {
        "status": "failed",
        "run_id": "attempt-1",
        "bundle_sha256": "1" * 64,
        "build_identity": "2" * 64 + ":" + "3" * 64,
        "primary_decision": "measurement_authority_or_platform_fault",
        "acquisition_gate": {"passed": False},
        "offline_finalization_gate": {
            "replayable_without_physical_repeat": False
        },
    }
    predecessor_path = reports / "cx320_active_hybrid_physical_seal_v1.json"
    _write(predecessor_path, _semantic(predecessor_unsigned, "seal_sha256"))
    output = tmp_path / "activation-2.json"

    observed = activation.create_activation(
        bundle_path=bundle_path,
        proposal_path=proposal_path,
        operational_rehearsal_path=rehearsal_path,
        serial_device="/dev/cu.usbmodem-test",
        operator_instruction_ref="expanded bounded recovery authority",
        output_path=output,
        attempt_ordinal=2,
        attempt_reason="repair pre-setup integrity gating",
        predecessor_terminal_path=predecessor_path,
    )

    assert observed["attempt"]["ordinal"] == 2
    assert observed["attempt"]["automatic_retry"] is False
    assert observed["attempt"]["predecessor_physical_terminal"][
        "seal_sha256"
    ] == _semantic(predecessor_unsigned, "seal_sha256")["seal_sha256"]
    validated, _, _ = activation.validate_activation(output)
    assert validated == observed


def test_later_activation_accepts_exact_bounded_operator_abort_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal, rehearsal_path, _ = _inputs(
        tmp_path
    )
    _current_validators(monkeypatch, bundle, proposal)
    predecessor_run = tmp_path / "attempt-4"
    reports = predecessor_run / "reports"
    reports.mkdir(parents=True)
    (predecessor_run / "COMPLETE").write_text("complete\n", encoding="utf-8")
    predecessor_unsigned: dict[str, object] = {
        "status": "bounded_nonpass",
        "run_id": "attempt-4",
        "bundle_sha256": "1" * 64,
        "build_identity": "2" * 64 + ":" + "3" * 64,
        "primary_decision": "operator_abort",
        # A clean acquisition and replayable offline finalization do not fill
        # the missing physical qualification interval after a bounded abort.
        "acquisition_gate": {"passed": True},
        "offline_finalization_gate": {
            "replayable_without_physical_repeat": True
        },
        "scientific_acceptance_checks": {
            "qualified_12h_endpoint_complete": False,
        },
        "terminal": {
            "abort_submission_count": 1,
            "abort_delivery_count": 1,
            "endpoint_complete": False,
            "supervisor_terminal": {
                "result": "aborted",
                "reason": "independent_host_abort_fifo",
            },
        },
    }
    predecessor_path = reports / "cx320_active_hybrid_physical_seal_v1.json"
    _write(predecessor_path, _semantic(predecessor_unsigned, "seal_sha256"))

    observed = activation.create_activation(
        bundle_path=bundle_path,
        proposal_path=proposal_path,
        operational_rehearsal_path=rehearsal_path,
        serial_device="/dev/cu.usbmodem-test",
        operator_instruction_ref="expanded bounded recovery authority",
        output_path=tmp_path / "activation-5.json",
        attempt_ordinal=5,
        attempt_reason="repair exact firmware setup-consumer handoff",
        predecessor_terminal_path=predecessor_path,
    )

    assert observed["attempt"]["ordinal"] == 5
    assert observed["attempt"]["automatic_retry"] is False
    assert observed["attempt"]["predecessor_physical_terminal"][
        "primary_decision"
    ] == "operator_abort"


def test_campaign18_later_activation_accepts_programme_operator_abort_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del monkeypatch
    predecessor_run = tmp_path / "campaign18-attempt-1"
    reports = predecessor_run / "reports"
    reports.mkdir(parents=True)
    (predecessor_run / "COMPLETE").write_text("complete\n", encoding="utf-8")
    predecessor_unsigned: dict[str, object] = {
        "status": "bounded_nonpass",
        "run_id": "campaign18-attempt-1",
        "bundle_sha256": "1" * 64,
        "build_identity": "2" * 64 + ":" + "3" * 64,
        "primary_decision": "cx322_d9_d6_72h_operator_abort",
        "acquisition_gate": {"passed": True},
        "offline_finalization_gate": {
            "replayable_without_physical_repeat": True
        },
        "scientific_acceptance_checks": {},
        "descriptive_prior_comparisons": {
            "qualified_endpoint_complete": False,
        },
        "terminal": {
            "abort_submission_count": 1,
            "abort_delivery_count": 1,
            "endpoint_complete": False,
            "supervisor_terminal": {
                "result": "aborted",
                "reason": "independent_host_abort_fifo",
            },
        },
    }
    predecessor_path = reports / "cx322_d9_d6_72h_physical_seal_v1.json"
    _write(predecessor_path, _semantic(predecessor_unsigned, "seal_sha256"))

    observed = activation._attempt_descriptor(
        ordinal=2,
        reason="repair host-only finalization after pre-actuation abort",
        predecessor_terminal_path=predecessor_path,
        programme=CX322_D9_D6_72H_PROGRAMME,
    )

    assert observed["ordinal"] == 2
    assert observed["predecessor_physical_terminal"][
        "primary_decision"
    ] == "cx322_d9_d6_72h_operator_abort"


@pytest.mark.parametrize(
    ("primary_decision", "supervisor_primary_decision", "supervisor_reason"),
    (
        (
            "cx322_d9_d6_72h_D14_D8_authority_or_capture_fault",
            "cx322_d9_d6_72h_D14_D8_authority_or_capture_fault",
            "cx322_d9_d6_72h_D14_D8_authority_or_capture_fault:session",
        ),
        (
            "cx322_d9_d6_72h_identity_or_evidence_fault",
            "measurement_authority_or_platform_fault",
            "cx322_d9_d6_72h_live_supervisor_fault:"
            "live active_fail_static asserted",
        ),
        (
            "cx322_d9_d6_72h_identity_or_evidence_fault",
            "measurement_authority_or_platform_fault",
            "cx322_d9_d6_72h_live_supervisor_fault:"
            "active live-health handoff is invalid: new snapshot generation "
            "began before the prior generation 2006 completed",
        ),
    ),
)
def test_campaign18_later_activation_accepts_exact_capture_terminal(
    tmp_path: Path,
    primary_decision: str,
    supervisor_primary_decision: str,
    supervisor_reason: str,
) -> None:
    predecessor_run = tmp_path / "campaign18-attempt-2"
    reports = predecessor_run / "reports"
    reports.mkdir(parents=True)
    (predecessor_run / "COMPLETE").write_text("complete\n", encoding="utf-8")
    predecessor_unsigned: dict[str, object] = {
        "status": "failed",
        "run_id": "campaign18-attempt-2",
        "bundle_sha256": "1" * 64,
        "build_identity": "2" * 64 + ":" + "3" * 64,
        "primary_decision": primary_decision,
        "acquisition_gate": {"passed": True},
        "descriptive_prior_comparisons": {
            "qualified_endpoint_complete": False,
        },
        "terminal": {
            "abort_submission_count": 1,
            "abort_delivery_count": 1,
            "endpoint_complete": False,
            "static_terminal_exact": True,
            "supervisor_terminal": {
                "result": "aborted",
                "primary_decision": supervisor_primary_decision,
                "reason": supervisor_reason,
            },
        },
    }
    predecessor_path = reports / "cx322_d9_d6_72h_physical_seal_v1.json"
    _write(predecessor_path, _semantic(predecessor_unsigned, "seal_sha256"))

    observed = activation._attempt_descriptor(
        ordinal=3,
        reason="fresh Campaign18 interval after capture discontinuity",
        predecessor_terminal_path=predecessor_path,
        programme=CX322_D9_D6_72H_PROGRAMME,
    )

    assert observed["ordinal"] == 3
    assert observed["predecessor_physical_terminal"]["primary_decision"] == (
        primary_decision
    )


def test_campaign18_legacy_capture_terminal_requires_exact_misclassification(
    tmp_path: Path,
) -> None:
    predecessor_run = tmp_path / "campaign18-attempt-2"
    reports = predecessor_run / "reports"
    reports.mkdir(parents=True)
    (predecessor_run / "COMPLETE").write_text("complete\n", encoding="utf-8")
    predecessor_unsigned: dict[str, object] = {
        "status": "failed",
        "run_id": "campaign18-attempt-2",
        "bundle_sha256": "1" * 64,
        "build_identity": "2" * 64 + ":" + "3" * 64,
        "primary_decision": "cx322_d9_d6_72h_identity_or_evidence_fault",
        "acquisition_gate": {"passed": True},
        "descriptive_prior_comparisons": {
            "qualified_endpoint_complete": False,
        },
        "terminal": {
            "abort_submission_count": 1,
            "abort_delivery_count": 1,
            "endpoint_complete": False,
            "static_terminal_exact": True,
            "supervisor_terminal": {
                "result": "aborted",
                "primary_decision": "measurement_authority_or_platform_fault",
                "reason": "a different identity failure",
            },
        },
    }
    predecessor_path = reports / "cx322_d9_d6_72h_physical_seal_v1.json"
    _write(predecessor_path, _semantic(predecessor_unsigned, "seal_sha256"))

    with pytest.raises(ValueError, match="incomplete physical gate"):
        activation._attempt_descriptor(
            ordinal=3,
            reason="fresh Campaign18 interval after capture discontinuity",
            predecessor_terminal_path=predecessor_path,
            programme=CX322_D9_D6_72H_PROGRAMME,
        )


def test_later_activation_accepts_exact_pre_setup_provenance_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal, rehearsal_path, _ = _inputs(
        tmp_path
    )
    _current_validators(monkeypatch, bundle, proposal)
    predecessor_run = tmp_path / "attempt-pre-setup"
    reports = predecessor_run / "reports"
    reports.mkdir(parents=True)
    (predecessor_run / "COMPLETE").write_text("complete\n", encoding="utf-8")
    predecessor_unsigned: dict[str, object] = {
        "status": "bounded_nonpass",
        "run_id": "attempt-pre-setup",
        "bundle_sha256": "1" * 64,
        "build_identity": "2" * 64 + ":" + "3" * 64,
        "primary_decision": "pre_setup_provenance_unresolved",
        "acquisition_gate": {"passed": True},
        "offline_finalization_gate": {
            "replayable_without_physical_repeat": True
        },
        "pre_setup_provenance_terminal": {"exact": True},
        "terminal": {
            "abort_submission_count": 1,
            "abort_delivery_count": 1,
            "endpoint_complete": False,
            "supervisor_terminal": {
                "result": "aborted",
                "reason": (
                    "cx322_d9_d6_live_supervisor_fault:"
                    "live active_fail_static asserted"
                ),
            },
        },
    }
    predecessor_path = reports / "cx320_active_hybrid_physical_seal_v1.json"
    _write(predecessor_path, _semantic(predecessor_unsigned, "seal_sha256"))

    observed = activation.create_activation(
        bundle_path=bundle_path,
        proposal_path=proposal_path,
        operational_rehearsal_path=rehearsal_path,
        serial_device="/dev/cu.usbmodem-test",
        operator_instruction_ref="expanded bounded recovery authority",
        output_path=tmp_path / "activation-pre-setup-successor.json",
        attempt_ordinal=2,
        attempt_reason="establish first known DAC state prospectively",
        predecessor_terminal_path=predecessor_path,
    )

    assert observed["attempt"]["ordinal"] == 2
    assert observed["attempt"]["automatic_retry"] is False
    assert observed["attempt"]["predecessor_physical_terminal"][
        "primary_decision"
    ] == "pre_setup_provenance_unresolved"


def test_later_activation_accepts_failed_post_acquisition_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal, rehearsal_path, _ = _inputs(
        tmp_path
    )
    _current_validators(monkeypatch, bundle, proposal)
    predecessor_run = tmp_path / "attempt-4"
    reports = predecessor_run / "reports"
    reports.mkdir(parents=True)
    (predecessor_run / "COMPLETE").write_text("complete\n", encoding="utf-8")
    predecessor_unsigned: dict[str, object] = {
        "status": "failed",
        "run_id": "attempt-4",
        "bundle_sha256": "1" * 64,
        "build_identity": "2" * 64 + ":" + "3" * 64,
        "primary_decision": "measurement_authority_or_platform_fault",
        "acquisition_gate": {"passed": True},
        "offline_finalization_gate": {
            "replayable_without_physical_repeat": True
        },
        "terminal": {
            "abort_submission_count": 1,
            "abort_delivery_count": 1,
            "endpoint_complete": False,
            "static_terminal_exact": True,
            "supervisor_terminal": {
                "result": "aborted",
                "reason": "cx322_live_supervisor_fault",
            },
        },
    }
    predecessor_path = reports / "cx320_active_hybrid_physical_seal_v1.json"
    _write(predecessor_path, _semantic(predecessor_unsigned, "seal_sha256"))

    observed = activation.create_activation(
        bundle_path=bundle_path,
        proposal_path=proposal_path,
        operational_rehearsal_path=rehearsal_path,
        serial_device="/dev/cu.usbmodem-test",
        operator_instruction_ref="expanded bounded recovery authority",
        output_path=tmp_path / "activation-5.json",
        attempt_ordinal=5,
        attempt_reason="repair exact phase-residence timing",
        predecessor_terminal_path=predecessor_path,
    )

    assert observed["attempt"]["ordinal"] == 5
    assert observed["attempt"]["predecessor_physical_terminal"][
        "primary_decision"
    ] == "measurement_authority_or_platform_fault"


def test_later_activation_rejects_unconfirmed_operator_abort_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal, rehearsal_path, _ = _inputs(
        tmp_path
    )
    _current_validators(monkeypatch, bundle, proposal)
    predecessor_run = tmp_path / "attempt-aborted"
    reports = predecessor_run / "reports"
    reports.mkdir(parents=True)
    (predecessor_run / "COMPLETE").write_text("complete\n", encoding="utf-8")
    predecessor_unsigned: dict[str, object] = {
        "status": "bounded_nonpass",
        "run_id": "attempt-aborted",
        "bundle_sha256": "1" * 64,
        "build_identity": "2" * 64 + ":" + "3" * 64,
        "primary_decision": "operator_abort",
        "acquisition_gate": {"passed": False},
        "offline_finalization_gate": {
            "replayable_without_physical_repeat": False
        },
        "terminal": {
            "abort_submission_count": 1,
            "abort_delivery_count": 0,
            "supervisor_terminal": {
                "result": "aborted",
                "reason": "independent_host_abort_fifo",
            },
        },
    }
    predecessor_path = reports / "cx320_active_hybrid_physical_seal_v1.json"
    _write(predecessor_path, _semantic(predecessor_unsigned, "seal_sha256"))

    with pytest.raises(ValueError, match="incomplete physical gate"):
        activation.create_activation(
            bundle_path=bundle_path,
            proposal_path=proposal_path,
            operational_rehearsal_path=rehearsal_path,
            serial_device="/dev/cu.usbmodem-test",
            operator_instruction_ref="expanded bounded recovery authority",
            output_path=tmp_path / "activation.json",
            attempt_ordinal=5,
            attempt_reason="must not accept unconfirmed abort delivery",
            predecessor_terminal_path=predecessor_path,
        )


def test_later_activation_requires_predecessor_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal, rehearsal_path, _ = _inputs(
        tmp_path
    )
    _current_validators(monkeypatch, bundle, proposal)

    with pytest.raises(ValueError, match="requires a predecessor terminal"):
        activation.create_activation(
            bundle_path=bundle_path,
            proposal_path=proposal_path,
            operational_rehearsal_path=rehearsal_path,
            serial_device="/dev/cu.usbmodem-test",
            operator_instruction_ref="expanded bounded recovery authority",
            output_path=tmp_path / "activation-2.json",
            attempt_ordinal=2,
            attempt_reason="repair pre-setup integrity gating",
        )


def test_activation_rejects_old_programme_only_run_identity_before_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal, rehearsal_path, _ = _inputs(
        tmp_path
    )
    old_bundle = {**bundle, "run_identity": "cx320_active_hybrid_12h_v1:3200001"}
    old_proposal = {**proposal, "run_identity": "cx320_active_hybrid_12h_v1:3200001"}
    monkeypatch.setattr(activation, "validate_bundle", lambda _path: old_bundle)
    monkeypatch.setattr(activation, "validate_proposal", lambda _path: old_proposal)
    monkeypatch.setattr(activation, "_git_clean", lambda: True)
    output = tmp_path / "must-not-exist.json"

    with pytest.raises(ValueError, match="differs|identity|authority"):
        activation.create_activation(
            bundle_path=bundle_path,
            proposal_path=proposal_path,
            operational_rehearsal_path=rehearsal_path,
            serial_device="/dev/not-opened",
            operator_instruction_ref="explicit-authority",
            output_path=output,
        )

    assert not output.exists()


def test_activation_requires_complete_real_process_rehearsal_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal, rehearsal_path, rehearsal = _inputs(
        tmp_path
    )
    _current_validators(monkeypatch, bundle, proposal)
    unsigned = {
        key: value for key, value in rehearsal.items() if key != "rehearsal_sha256"
    }
    unsigned["coverage"] = {
        **unsigned["coverage"],
        "terminal_abort_delivery_before_capture_close": False,
    }
    _write(rehearsal_path, _semantic(unsigned, "rehearsal_sha256"))

    with pytest.raises(ValueError, match="rehearsal receipt"):
        activation.create_activation(
            bundle_path=bundle_path,
            proposal_path=proposal_path,
            operational_rehearsal_path=rehearsal_path,
            serial_device="/dev/not-opened",
            operator_instruction_ref="explicit-authority",
            output_path=tmp_path / "activation.json",
        )


def test_dirty_current_inputs_fail_before_effective_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal, rehearsal_path, _ = _inputs(
        tmp_path
    )
    monkeypatch.setattr(activation, "validate_bundle", lambda _path: bundle)
    monkeypatch.setattr(activation, "validate_proposal", lambda _path: proposal)
    monkeypatch.setattr(activation, "_git_clean", lambda: False)
    output = tmp_path / "activation.json"

    with pytest.raises(ValueError, match="clean repository"):
        activation.create_activation(
            bundle_path=bundle_path,
            proposal_path=proposal_path,
            operational_rehearsal_path=rehearsal_path,
            serial_device="/dev/not-opened",
            operator_instruction_ref="explicit-authority",
            output_path=output,
        )

    assert not output.exists()


def test_live_manifest_binds_exact_limits_topology_and_runtime_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal, rehearsal_path, _ = _inputs(
        tmp_path
    )
    _current_validators(monkeypatch, bundle, proposal)
    activation_path = tmp_path / "source-activation.json"
    activation.create_activation(
        bundle_path=bundle_path,
        proposal_path=proposal_path,
        operational_rehearsal_path=rehearsal_path,
        serial_device="/dev/cu.usbmodem-test",
        operator_instruction_ref="operator-authorized bundle and proposal in task",
        output_path=activation_path,
    )

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run_activation = run_dir / activation.RUN_ACTIVATION_PATH
    run_bundle = run_dir / activation.RUN_BUNDLE_PATH
    run_proposal = run_dir / activation.RUN_PROPOSAL_PATH
    run_activation.write_bytes(activation_path.read_bytes())
    run_bundle.write_bytes(bundle_path.read_bytes())
    run_proposal.write_bytes(proposal_path.read_bytes())

    manifest = activation.create_run_manifest(
        activation_path=run_activation,
        bundle_path=run_bundle,
        proposal_path=run_proposal,
        run_dir=run_dir,
        output_path=run_dir / "run_manifest.json",
    )

    assert manifest["run_identity"] == "cx320_active_hybrid:3200001"
    assert manifest["cx320"]["setup"]["code"] == 0xA83C
    assert manifest["cx320"]["automatic_control"] == {
        "authorized": True,
        "maximum_total_applications": 4,
        "maximum_step_codes": 21,
        "maximum_cumulative_movement_codes": 84,
        "minimum_applied_cadence_s": 1800,
        "minimum_code": 0xA800,
        "maximum_code": 0xAB00,
        "maximum_outstanding_requests": 1,
        "automatic_retry": False,
        "automatic_restore": False,
    }
    assert manifest["cx320"]["qualification"]["qualified_duration_s"] == 43_200
    assert manifest["cx320"]["qualification"]["absolute_wall_clock_limit_s"] == 57_600
    assert manifest["host"]["expected_board_serial"] == "503533748A919118"
    assert len(set(manifest["host"]["fifos"].values())) == 3
    assert "active_hybrid_decisions_v1" in manifest["contracts"]
    assert activation.validate_run_manifest(run_dir / "run_manifest.json") == manifest


def test_cli_validation_reports_mismatch_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(SystemExit) as exc:
        activation.main(["validate", str(missing)])

    assert exc.value.code == 2
    error = capsys.readouterr().err
    assert "cannot read CX320 live activation" in error
    assert "Traceback" not in error
