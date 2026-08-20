from __future__ import annotations

import json
from pathlib import Path

from host.otis_tools import active_hybrid_proposal as proposal_tool


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
