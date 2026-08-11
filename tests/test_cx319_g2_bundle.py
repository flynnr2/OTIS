from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools import cx319_g2_analyze
from host.otis_tools import cx319_g2_bundle
from host.otis_tools import cx319_g2_operational_rehearsal
from host.otis_tools import cx319_g2_preflight


def _fake_g1() -> dict[str, object]:
    policy_sha = sha256(cx319_g2_bundle.POLICY_PATH.read_bytes()).hexdigest()
    return {
        "run_id": "g1-pass",
        "run_dir": "/retained/g1-pass",
        "run_manifest_sha256": "1" * 64,
        "analysis_sha256": "2" * 64,
        "analysis_file_sha256": "3" * 64,
        "seal_sha256": "4" * 64,
        "seal_file_sha256": "5" * 64,
        "evidence_content_sha256": "6" * 64,
        "bundle_sha256": "7" * 64,
        "firmware": {
            "source_sha256": "a" * 64,
            "configuration_sha256": "b" * 64,
            "profile_id": "cx319_tight_lower",
            "uf2": {"sha256": "c" * 64},
        },
        "policy": {
            "policy_id": "CX319_STABILIZED_TIGHT_DEADBAND_FREQUENCY_ONLY_V1",
            "sha256": policy_sha,
        },
    }


def test_g2_proposal_and_preflight_remain_non_authorizing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_g1 = _fake_g1()
    monkeypatch.setattr(cx319_g2_bundle, "_git_identity", lambda: ("d" * 40, "clean"))
    monkeypatch.setattr(cx319_g2_bundle, "validate_g1_pass", lambda path: fake_g1)
    proposal_path = tmp_path / "proposal.json"

    proposal = cx319_g2_bundle.create_proposal(
        g1_run_dir=tmp_path / "g1", output_path=proposal_path
    )
    # A documentation-only descendant commit does not invalidate an otherwise
    # identical operational bundle; current tool and policy bytes remain bound.
    monkeypatch.setattr(cx319_g2_bundle, "_git_identity", lambda: ("e" * 40, "clean"))
    assert cx319_g2_bundle.validate_proposal(proposal_path) == proposal

    result = cx319_g2_preflight.evaluate(proposal_path)
    assert result["status"] == "passed"
    assert all(result["checks"].values())
    assert set(result["hardware_operations"].values()) == {0}
    assert proposal["authority"]["effective"] is False


def test_accelerated_operational_path_runs_supervisor_analyzer_seal_and_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proposal = {
        "bundle_sha256": "e" * 64,
        "firmware": {
            "source_sha256": "a" * 64,
            "configuration_sha256": "b" * 64,
        },
        "intended_live_envelope": {
            "setup_writes": 1,
            "automatic_corrections": 4,
            "maximum_step_codes": 21,
            "maximum_cumulative_codes": 84,
            "minimum_code": 0xA800,
            "maximum_code": 0xAB00,
            "minimum_applied_cadence_s": 1800,
            "settling_exclusion_s": 900,
            "fresh_support_s": 600,
            "qualification_deadline_s": 5400,
            "maximum_qualified_duration_s": 14400,
            "one_request_outstanding": True,
            "automatic_retry": False,
            "automatic_restore": False,
        },
    }
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    monkeypatch.setattr(
        cx319_g2_operational_rehearsal,
        "validate_proposal",
        lambda path: proposal,
    )
    monkeypatch.setattr(
        cx319_g2_analyze,
        "validate_proposal",
        lambda path: proposal,
    )

    result = cx319_g2_operational_rehearsal.run(
        proposal_path=proposal_path,
        output_dir=tmp_path / "operational",
    )

    assert result["status"] == "passed"
    assert set(result["hardware_operations"].values()) == {0}
    analysis = json.loads(Path(result["analysis"]).read_text(encoding="utf-8"))
    assert analysis["status"] == "passed"
    assert all(analysis["verdict"]["checks"].values())
