from __future__ import annotations

import json
from pathlib import Path

import pytest

from host.otis_tools import active_hybrid_bundle as bundle_tool
from host.otis_tools import active_hybrid_proposal as proposal_tool
from host.otis_tools.active_hybrid_programme_contract import (
    CX321_PROGRAMME,
    CX322_D9_D6_72H_PROGRAMME,
    CX323_D9_D6_72H_PROGRAMME,
)


def _write_semantic(path: Path, value: dict, field: str) -> dict:
    result = {**value, field: proposal_tool._canonical_sha256(value)}
    path.write_text(json.dumps(result), encoding="utf-8")
    return result


def test_successor_proposal_preserves_root_authority_and_frozen_envelope(
    tmp_path: Path, monkeypatch
) -> None:
    root_bundle = "1" * 64
    parent_path = tmp_path / "parent.json"
    parent = _write_semantic(
        parent_path,
        {
            "proposal_id": proposal_tool.PROPOSAL_ID,
            "exact_bundle": {"bundle_sha256": root_bundle},
        },
        "proposal_sha256",
    )
    monkeypatch.setattr(
        proposal_tool, "ROOT_PROPOSAL_SHA256", parent["proposal_sha256"]
    )
    monkeypatch.setattr(proposal_tool, "ROOT_BUNDLE_SHA256", root_bundle)
    authority_path = tmp_path / "authority.json"
    authority_path.write_text(
        json.dumps(
            {
                "authority_type": "cx320_explicit_operator_authority_v1",
                "named_bundle_sha256": root_bundle,
                "named_proposal_sha256": parent["proposal_sha256"],
                "stage_5_effective": True,
                "expanded_recovery_authority": {"effective": True},
                "frozen_scientific_boundary": {
                    "controller_thresholds_may_change_without_new_decision": False
                },
            }
        ),
        encoding="utf-8",
    )
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text("{}", encoding="utf-8")
    bundle = {
        "run_identity": "cx320_active_hybrid:3200001",
        "bundle_sha256": "2" * 64,
        "policy": {"policy_sha256": "3" * 64},
        "firmware": {
            "build_identity": "4" * 64 + ":" + "5" * 64,
            "uf2": {"sha256": "6" * 64},
        },
    }
    monkeypatch.setattr(proposal_tool, "validate_bundle", lambda path: bundle)
    output = tmp_path / "successor.json"

    created = proposal_tool.create_successor_proposal(
        bundle_path=bundle_path,
        parent_proposal_path=parent_path,
        operator_authority_path=authority_path,
        output_path=output,
        successor_reason="attempt 2 after pre-setup firmware integrity repair",
    )
    validated = proposal_tool.validate_proposal(output)

    assert created == validated
    assert created["authority"]["effective"] is False
    assert created["lineage"][
        "scientific_thresholds_criteria_and_duration_unchanged"
    ] is True
    assert created["lineage"]["successor_reason"] == (
        "attempt 2 after pre-setup firmware integrity repair"
    )
    assert created["progressive_envelope"] == proposal_tool._progressive_envelope()


def test_cx321_creator_freezes_prospective_lineage_without_inheriting_authority(
    tmp_path: Path, monkeypatch
) -> None:
    root_bundle = "1" * 64
    parent_path = tmp_path / "parent.json"
    parent = _write_semantic(
        parent_path,
        {
            "proposal_id": proposal_tool.PROPOSAL_ID,
            "exact_bundle": {"bundle_sha256": root_bundle},
        },
        "proposal_sha256",
    )
    monkeypatch.setattr(
        proposal_tool, "ROOT_PROPOSAL_SHA256", parent["proposal_sha256"]
    )
    monkeypatch.setattr(proposal_tool, "ROOT_BUNDLE_SHA256", root_bundle)
    authority_path = tmp_path / "authority.json"
    authority_path.write_text(
        json.dumps(
            {
                "authority_type": "cx320_explicit_operator_authority_v1",
                "named_bundle_sha256": root_bundle,
                "named_proposal_sha256": parent["proposal_sha256"],
                "stage_5_effective": True,
                "expanded_recovery_authority": {"effective": True},
                "frozen_scientific_boundary": {
                    "controller_thresholds_may_change_without_new_decision": (
                        False
                    )
                },
            }
        ),
        encoding="utf-8",
    )
    bundle_path = tmp_path / "cx321_bundle.json"
    bundle_path.write_text("{}", encoding="utf-8")
    bundle = {
        "programme_id": CX321_PROGRAMME.programme_id,
        "run_identity": CX321_PROGRAMME.runtime_run_identity,
        "bundle_sha256": "2" * 64,
        "policy": {"policy_sha256": "3" * 64},
        "programme_policy": {"sha256": "7" * 64},
        "firmware": {
            "build_identity": "4" * 64 + ":" + "5" * 64,
            "uf2": {"sha256": "6" * 64},
        },
    }
    monkeypatch.setattr(
        proposal_tool, "validate_bundle", lambda path, *args: bundle
    )
    output = tmp_path / "cx321_proposal.json"

    created = proposal_tool.create_successor_proposal(
        bundle_path=bundle_path,
        parent_proposal_path=parent_path,
        operator_authority_path=authority_path,
        output_path=output,
        successor_reason="prospective CX321 qualification under a new decision",
        programme=CX321_PROGRAMME,
    )
    validated = proposal_tool.validate_proposal(output, CX321_PROGRAMME)

    assert created == validated
    assert created["proposal_id"] == (
        "cx321_active_hybrid_physical_authority_proposal_v1"
    )
    assert created["programme_policy_sha256"] == "7" * 64
    assert created["profile_identity"] == CX321_PROGRAMME.profile_id
    assert created["lineage"]["inherits_physical_authority"] is False
    assert created["lineage"][
        "successor_qualification_criterion_prospectively_frozen"
    ] is True
    assert created["authority"]["effective"] is False
    assert created["progressive_envelope"] == (
        proposal_tool._progressive_envelope(CX321_PROGRAMME)
    )


def test_72h_creator_declares_changed_authority_envelope_and_duration(
    tmp_path: Path, monkeypatch
) -> None:
    root_bundle = "1" * 64
    parent_path = tmp_path / "parent.json"
    parent = _write_semantic(
        parent_path,
        {
            "proposal_id": proposal_tool.PROPOSAL_ID,
            "exact_bundle": {"bundle_sha256": root_bundle},
        },
        "proposal_sha256",
    )
    monkeypatch.setattr(
        proposal_tool, "ROOT_PROPOSAL_SHA256", parent["proposal_sha256"]
    )
    monkeypatch.setattr(proposal_tool, "ROOT_BUNDLE_SHA256", root_bundle)
    authority_path = tmp_path / "authority.json"
    authority_path.write_text(
        json.dumps(
            {
                "authority_type": "cx320_explicit_operator_authority_v1",
                "named_bundle_sha256": root_bundle,
                "named_proposal_sha256": parent["proposal_sha256"],
                "stage_5_effective": True,
                "expanded_recovery_authority": {"effective": True},
                "frozen_scientific_boundary": {
                    "controller_thresholds_may_change_without_new_decision": False
                },
            }
        ),
        encoding="utf-8",
    )
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text("{}", encoding="utf-8")
    bundle = {
        "programme_id": CX322_D9_D6_72H_PROGRAMME.programme_id,
        "run_identity": CX322_D9_D6_72H_PROGRAMME.runtime_run_identity,
        "bundle_sha256": "2" * 64,
        "policy": {"policy_sha256": "3" * 64},
        "programme_policy": {"sha256": "7" * 64},
        "firmware": {
            "build_identity": "4" * 64 + ":" + "5" * 64,
            "uf2": {"sha256": "6" * 64},
        },
    }
    monkeypatch.setattr(
        proposal_tool, "validate_bundle", lambda path, *args: bundle
    )
    output = tmp_path / "proposal.json"

    created = proposal_tool.create_successor_proposal(
        bundle_path=bundle_path,
        parent_proposal_path=parent_path,
        operator_authority_path=authority_path,
        output_path=output,
        successor_reason="prospectively frozen revised 72-hour programme",
        programme=CX322_D9_D6_72H_PROGRAMME,
    )
    validated = proposal_tool.validate_proposal(
        output, CX322_D9_D6_72H_PROGRAMME
    )

    assert created == validated
    lineage = created["lineage"]
    assert lineage["controller_request_law_unchanged"] is True
    assert lineage[
        "authority_ceilings_and_qualified_duration_changed_by_current_prospectively_frozen_programme"
    ] is True
    assert "scientific_limits_and_duration_unchanged" not in lineage
    assert created["progressive_envelope"] == (
        proposal_tool._progressive_envelope(CX322_D9_D6_72H_PROGRAMME)
    )


def test_cx323_proposal_binds_replacement_controller_without_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_bundle = "1" * 64
    parent_path = tmp_path / "parent.json"
    parent = _write_semantic(
        parent_path,
        {
            "proposal_id": proposal_tool.PROPOSAL_ID,
            "exact_bundle": {"bundle_sha256": root_bundle},
        },
        "proposal_sha256",
    )
    monkeypatch.setattr(
        proposal_tool, "ROOT_PROPOSAL_SHA256", parent["proposal_sha256"]
    )
    monkeypatch.setattr(proposal_tool, "ROOT_BUNDLE_SHA256", root_bundle)
    authority_path = tmp_path / "authority.json"
    authority_path.write_text(
        json.dumps(
            {
                "authority_type": "cx320_explicit_operator_authority_v1",
                "named_bundle_sha256": root_bundle,
                "named_proposal_sha256": parent["proposal_sha256"],
                "stage_5_effective": True,
                "expanded_recovery_authority": {"effective": True},
                "frozen_scientific_boundary": {
                    "controller_thresholds_may_change_without_new_decision": (
                        False
                    )
                },
            }
        ),
        encoding="utf-8",
    )
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text("{}", encoding="utf-8")
    persistent_maintenance = bundle_tool._cx323_successor_binding(
        CX323_D9_D6_72H_PROGRAMME
    )
    exact_bundle = {
        "programme_id": CX323_D9_D6_72H_PROGRAMME.programme_id,
        "run_identity": CX323_D9_D6_72H_PROGRAMME.runtime_run_identity,
        "bundle_sha256": "2" * 64,
        "policy": {"policy_sha256": bundle_tool.CX323_POLICY_SHA256},
        "persistent_maintenance": persistent_maintenance,
        "firmware": {
            "build_identity": "4" * 64 + ":" + "5" * 64,
            "uf2": {"sha256": "6" * 64},
        },
    }
    monkeypatch.setattr(
        proposal_tool, "validate_bundle", lambda path, *args: exact_bundle
    )
    output = tmp_path / "proposal.json"

    created = proposal_tool.create_successor_proposal(
        bundle_path=bundle_path,
        parent_proposal_path=parent_path,
        operator_authority_path=authority_path,
        output_path=output,
        successor_reason="prospectively selected quantization-resistant controller",
        programme=CX323_D9_D6_72H_PROGRAMME,
    )
    assert proposal_tool.validate_proposal(
        output, CX323_D9_D6_72H_PROGRAMME
    ) == created

    lineage = created["lineage"]
    assert created["persistent_maintenance"] == persistent_maintenance
    assert lineage["controller_request_law_prospectively_replaced"] is True
    assert lineage["persistent_maintenance_policy_and_contract_bound"] is True
    assert lineage["inherits_physical_authority"] is False
    assert "controller_request_law_unchanged" not in lineage
    assert all(
        created["authority"][name] is False
        for name in bundle_tool.REQUIRED_FALSE_AUTHORITY
    )

    tampered = json.loads(output.read_text(encoding="utf-8"))
    tampered.pop("proposal_sha256")
    tampered["lineage"].pop(
        "controller_request_law_prospectively_replaced"
    )
    tampered["lineage"]["controller_request_law_unchanged"] = True
    tampered["proposal_sha256"] = proposal_tool._canonical_sha256(tampered)
    output.chmod(0o644)
    output.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="successor proposal lineage differs"):
        proposal_tool.validate_proposal(output, CX323_D9_D6_72H_PROGRAMME)
