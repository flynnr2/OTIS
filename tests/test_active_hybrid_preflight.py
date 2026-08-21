from __future__ import annotations

import json
from pathlib import Path

from host.otis_tools import active_hybrid_preflight as preflight_tool
from host.otis_tools.active_hybrid_programme_contract import CX321_PROGRAMME


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
