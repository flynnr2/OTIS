from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from host.otis_tools import active_hybrid_preflight as preflight_tool
from host.otis_tools.active_hybrid_programme_contract import (
    CX321_PROGRAMME,
    CX322_D9_D6_INTEGRATION_PROGRAMME,
    SUSTAINED_HYBRID_PROGRAMME,
    integrated_setup_provenance_contract,
)
from host.otis_tools.gnss_operational_baud_policy import (
    GNSS_OPERATIONAL_BAUD_POLICY,
)


def test_structural_preflight_accepts_exact_declared_live_authority_state() -> None:
    programme = SUSTAINED_HYBRID_PROGRAMME
    status = {
        "active_programme": programme.status_programme_id,
        "programmes": {
            programme.status_programme_id: {
                "allowed_operations": [
                    "offline_preparation",
                    programme.operation,
                ],
                "physical_authority_effective": True,
            }
        },
    }

    assert preflight_tool._programme_status_allows_preflight(status, programme)


def test_integrated_preflight_binds_historical_cx322_seal_without_current_replay(
    tmp_path: Path, monkeypatch,
) -> None:
    seal_path = tmp_path / "cx322_seal.json"
    seal = {
        "programme_id": "CX322_BOUNDED_HYBRID_FACT_GATHERING_V1",
        "status": "passed",
        "primary_decision": "bounded_direct_hybrid_evidence_acquired",
        "seal_sha256": "a" * 64,
    }
    seal_path.write_text(json.dumps(seal), encoding="utf-8")
    status = {
        "programmes": {
            CX322_D9_D6_INTEGRATION_PROGRAMME.status_programme_id: {
                "predecessor_programme": "cx322_bounded_hybrid_fact_gathering",
                "predecessor_evidence": {
                    "seal_path": str(seal_path),
                    "seal_file_sha256": sha256(seal_path.read_bytes()).hexdigest(),
                    "seal_size_bytes": seal_path.stat().st_size,
                    "seal_sha256": seal["seal_sha256"],
                    "terminal_primary_decision": seal["primary_decision"],
                },
            }
        }
    }
    monkeypatch.setattr(
        preflight_tool,
        "audit_predecessor",
        lambda: (_ for _ in ()).throw(
            AssertionError("current-source historical audit must not run")
        ),
    )

    observed = preflight_tool._predecessor_evidence(
        status, CX322_D9_D6_INTEGRATION_PROGRAMME
    )

    assert observed["status"] == "passed"
    assert observed["seal_sha256"] == seal["seal_sha256"]
    assert observed["binding_mode"] == (
        "historical_content_addressed_cx322_terminal_seal"
    )


def test_cx321_structural_preflight_exercises_extended_phase4_envelope(
    tmp_path: Path, monkeypatch,
) -> None:
    bundle_path = tmp_path / "bundle.json"
    proposal_path = tmp_path / "proposal.json"
    bundle_path.write_text(
        json.dumps({"programme_id": CX321_PROGRAMME.programme_id}),
        encoding="utf-8",
    )
    proposal_path.write_text("{}", encoding="utf-8")
    bundle = {
        "programme_id": CX321_PROGRAMME.programme_id,
        "bundle_sha256": "b" * 64,
        "firmware": {
            "configuration_sha256": "c" * 64,
            "build_identity": "d" * 64 + ":" + "e" * 64,
            "uf2": {"sha256": "f" * 64},
        },
        "policy": {"policy_sha256": "1" * 64},
        "gnss_uart_policy": GNSS_OPERATIONAL_BAUD_POLICY,
        "offline_replay": {"selection_checks": {"selected": True}},
        "topology": {"normal_and_priority_abort_fifos_distinct": True},
    }
    proposal = {
        "proposal_sha256": "2" * 64,
        "exact_bundle": {"bundle_sha256": bundle["bundle_sha256"]},
        "authority": {"effective": False},
    }
    monkeypatch.setattr(
        preflight_tool, "validate_bundle", lambda _path, _programme: bundle
    )
    monkeypatch.setattr(
        preflight_tool, "validate_proposal", lambda _path, _programme: proposal
    )
    monkeypatch.setattr(
        preflight_tool,
        "audit_predecessor",
        lambda: {
            "status": "passed",
            "programme_seal": {"seal_sha256": "3" * 64},
        },
    )
    monkeypatch.setattr(
        preflight_tool,
        "load_programme_status",
        lambda: {
            "active_programme": CX321_PROGRAMME.status_programme_id,
            "programmes": {
                CX321_PROGRAMME.status_programme_id: {
                    "allowed_operations": ["offline_preparation"],
                    "physical_authority_effective": False,
                }
            },
        },
    )

    result = preflight_tool.preflight(
        bundle_path=bundle_path, proposal_path=proposal_path
    )

    assert result["report_type"] == "cx321_active_hybrid_structural_preflight_v1"
    assert result["checks"]["cx321_extended_phase4_envelope_parses"] is True
    assert result["normalized_command_rehearsal"][7].startswith(
        "ACTIVE EVIDENCE 1 4 5 -3 1 2 9000 "
    )
    assert result["claim_boundary"]["serial_device_access"] is False


def test_integrated_preflight_requires_bound_unknown_to_known_setup_semantics(
    tmp_path: Path, monkeypatch,
) -> None:
    programme = CX322_D9_D6_INTEGRATION_PROGRAMME
    bundle_path = tmp_path / "bundle.json"
    proposal_path = tmp_path / "proposal.json"
    bundle_path.write_text(
        json.dumps({"programme_id": programme.programme_id}), encoding="utf-8"
    )
    proposal_path.write_text("{}", encoding="utf-8")
    provenance = integrated_setup_provenance_contract(programme)
    bundle = {
        "programme_id": programme.programme_id,
        "bundle_sha256": "b" * 64,
        "engineering_contract": {"contract_semantic_sha256": "a" * 64},
        "setup": {"provenance": provenance},
        "firmware": {
            "configuration_sha256": "c" * 64,
            "build_identity": "d" * 64 + ":" + "e" * 64,
            "uf2": {"sha256": "f" * 64},
        },
        "policy": {"policy_sha256": "1" * 64},
        "gnss_uart_policy": GNSS_OPERATIONAL_BAUD_POLICY,
        "offline_replay": {"selection_checks": {"selected": True}},
        "topology": {"normal_and_priority_abort_fifos_distinct": True},
    }
    proposal = {
        "proposal_sha256": "2" * 64,
        "exact_bundle": {"bundle_sha256": bundle["bundle_sha256"]},
        "authority": {"effective": False},
    }
    monkeypatch.setattr(
        preflight_tool, "validate_bundle", lambda _path, _programme: bundle
    )
    monkeypatch.setattr(
        preflight_tool, "validate_proposal", lambda _path, _programme: proposal
    )
    monkeypatch.setattr(
        preflight_tool,
        "_predecessor_evidence",
        lambda _status, _programme: {"status": "passed", "seal_sha256": "3" * 64},
    )
    monkeypatch.setattr(
        preflight_tool,
        "load_programme_status",
        lambda: {
            "active_programme": programme.status_programme_id,
            "programmes": {
                programme.status_programme_id: {
                    "allowed_operations": ["offline_preparation"],
                    "physical_authority_effective": False,
                }
            },
        },
    )

    result = preflight_tool.preflight(
        bundle_path=bundle_path, proposal_path=proposal_path
    )

    assert result["checks"]["integrated_engineering_contract_bound"] is True
    assert result["checks"]["unknown_boot_DAC_state_not_inferred"] is True
    assert result["checks"]["setup_is_frozen_stimulus_not_restoration"] is True
