from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools import bounded_tight_deadband_rehearsal_analyze
from host.otis_tools import bounded_tight_deadband_bundle
from host.otis_tools import bounded_tight_deadband_operational_rehearsal
from host.otis_tools import bounded_tight_deadband_preflight


def _fake_g1() -> dict[str, object]:
    policy_sha = sha256(bounded_tight_deadband_bundle.POLICY_PATH.read_bytes()).hexdigest()
    return {
        "qualification_sequence_gate": "Q3",
        "run_id": "g1-pass",
        "run_dir": "/retained/g1-pass",
        "run_manifest_sha256": "1" * 64,
        "analysis_sha256": "2" * 64,
        "analysis_file_sha256": "3" * 64,
        "seal_sha256": "4" * 64,
        "seal_file_sha256": "5" * 64,
        "evidence_content_sha256": "6" * 64,
        "bundle_sha256": "7" * 64,
        "sequence_prerequisites": {"q1": {}, "q2": {}},
        "firmware": {
            "source_sha256": "a" * 64,
            "configuration_sha256": "b" * 64,
            "profile_id": "cx319_tight_lower",
            "fqbn": "rp2040:test",
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
    monkeypatch.setattr(bounded_tight_deadband_bundle, "_git_identity", lambda: ("d" * 40, "clean"))
    monkeypatch.setattr(bounded_tight_deadband_bundle, "validate_no_write_qualification_pass", lambda path: fake_g1)
    monkeypatch.setattr(
        bounded_tight_deadband_bundle,
        "_firmware_build_provenance",
        lambda firmware: {
            "configuration": {"sha256": firmware["configuration_sha256"]},
            "target": {"fqbn": firmware["fqbn"]},
            "invocation": {"arduino_cli_version": "test"},
            "toolchain": {
                "compiler_identity": "test",
                "installed_sha256": "0" * 64,
            },
        },
    )
    proposal_path = tmp_path / "proposal.json"

    proposal = bounded_tight_deadband_bundle.create_proposal(
        no_write_run_dir=tmp_path / "g1", output_path=proposal_path
    )
    # A documentation-only descendant commit does not invalidate an otherwise
    # identical operational bundle; current tool and policy bytes remain bound.
    monkeypatch.setattr(bounded_tight_deadband_bundle, "_git_identity", lambda: ("e" * 40, "clean"))
    assert bounded_tight_deadband_bundle.validate_proposal(proposal_path) == proposal

    monkeypatch.setattr(
        bounded_tight_deadband_preflight,
        "load_programme_status",
        lambda: {
            "programmes": {
                bounded_tight_deadband_bundle.PROGRAMME_ID: {
                    "allowed_operations": ["offline_preparation"]
                }
            }
        },
    )
    result = bounded_tight_deadband_preflight.evaluate(proposal_path)
    assert result["status"] == "passed"
    assert all(result["checks"].values())
    assert set(result["hardware_operations"].values()) == {0}
    assert proposal["authority"]["effective"] is False


def test_g2_current_firmware_delta_reuses_q3_and_accepts_unattended_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qualification = {
        **_fake_g1(),
        "run_id": "current-firmware-pass",
        "run_dir": str(tmp_path / "current-firmware-pass"),
        "current_firmware_qualification": {
            "type": "exact_flash_session_absence_low_cadence"
        },
        "retained_q3_pass": {"run_id": "retained-q3"},
    }
    monkeypatch.setattr(
        bounded_tight_deadband_bundle,
        "_git_identity",
        lambda: ("d" * 40, "clean"),
    )
    monkeypatch.setattr(
        bounded_tight_deadband_bundle,
        "validate_current_firmware_qualification_pass",
        lambda **kwargs: qualification,
    )
    monkeypatch.setattr(
        bounded_tight_deadband_bundle,
        "_firmware_build_provenance",
        lambda firmware: {
            "configuration": {"sha256": firmware["configuration_sha256"]},
            "target": {"fqbn": firmware["fqbn"]},
            "invocation": {"arduino_cli_version": "test"},
            "toolchain": {
                "compiler_identity": "test",
                "installed_sha256": "0" * 64,
            },
        },
    )
    proposal_path = tmp_path / "current-proposal.json"
    proposal = bounded_tight_deadband_bundle.create_proposal(
        no_write_run_dir=tmp_path / "retained-q3",
        current_firmware_qualification_run_dir=(
            tmp_path / "current-firmware-pass"
        ),
        output_path=proposal_path,
    )

    assert proposal["firmware_entry"]["mode"] == (
        "verify_installed_exact_current_qualified_image_no_flash"
    )
    assert bounded_tight_deadband_bundle.validate_proposal(proposal_path) == proposal

    monkeypatch.setattr(
        bounded_tight_deadband_preflight,
        "load_programme_status",
        lambda: {
            "programmes": {
                bounded_tight_deadband_bundle.PROGRAMME_ID: {
                    "allowed_operations": [
                        "offline_preparation",
                        "g2_live_leg",
                    ],
                    "q4_unattended_phase_authority": {"effective": True},
                }
            }
        },
    )
    result = bounded_tight_deadband_preflight.evaluate(proposal_path)
    assert result["status"] == "passed"
    assert all(result["checks"].values())
    assert set(result["hardware_operations"].values()) == {0}


def test_g2_rejects_pre_q3_no_write_evidence_before_reading_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        bounded_tight_deadband_bundle,
        "validate_run_manifest",
        lambda path: {
            "cx319": {
                "leg": "A",
                "qualification_sequence_gate": "Q1",
                "runtime_contract": {
                    "id": "cx319_g1_prewrite_runtime_contract_v1"
                },
            }
        },
    )

    with pytest.raises(ValueError, match="Q3 physical no-write qualification"):
        bounded_tight_deadband_bundle.validate_no_write_qualification_pass(tmp_path)


def test_g2_uses_q3_sequence_status_not_superseded_g1_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "q3-pass"
    run_dir.mkdir()
    firmware = {
        "git_commit": "a" * 40,
        "uf2": {"sha256": "b" * 64},
    }
    manifest = {
        "qualification_evidence": True,
        "firmware": firmware,
        "bundle": {"path": str(run_dir / "bundle.json"), "bundle_sha256": "c" * 64},
        "cx319": {
            "leg": "A",
            "qualification_sequence_gate": "Q3",
            "runtime_contract": {"id": bounded_tight_deadband_bundle.NO_WRITE_RUNTIME_CONTRACT_ID},
        },
    }
    unsigned_analysis: dict[str, object] = {
        "status": "pass",
        "checks": {"canonical": True},
        "qualification_sequence_gate": "Q3",
    }
    analysis = {
        **unsigned_analysis,
        "analysis_sha256": bounded_tight_deadband_bundle._canonical_sha256(
            unsigned_analysis
        ),
    }
    unsigned_seal: dict[str, object] = {
        "status": "pass",
        "leg": "A",
        "profile_id": "cx319_tight_lower",
        "qualification_sequence_gate": "Q3",
        "seal_type": "cx319_q3_physical_no_write_qualification_seal_v1",
        "qualification_evidence": True,
        "bundle_sha256": "c" * 64,
        "analysis": {
            "sha256": "d" * 64,
            "analysis_sha256": analysis["analysis_sha256"],
        },
        "uf2_sha256": "b" * 64,
        "setup_writes": 0,
        "dac_value_writes": 0,
        "automatic_writes": 0,
        "control_arms": 0,
    }
    seal = {
        **unsigned_seal,
        "seal_sha256": bounded_tight_deadband_bundle._canonical_sha256(unsigned_seal),
    }
    frozen_bundle = {
        "host_source_revision": "e" * 40,
        "firmware": firmware,
        "policy": {"sha256": "f" * 64},
    }
    status = {
        "completed_g1_evidence": {"run_id": "superseded-g1"},
        "q3_sequence_result": {
            "run_id": run_dir.name,
            "host_source_revision": "e" * 40,
            "firmware_source_revision": "a" * 40,
            "bundle_sha256": "c" * 64,
            "seal_sha256": seal["seal_sha256"],
            "evidence_content_sha256": "1" * 64,
            "uf2_sha256": "b" * 64,
            "dac_value_writes": 0,
            "setup_stimuli": 0,
            "control_arms": 0,
            "automatic_corrections": 0,
        },
    }
    monkeypatch.setattr(
        bounded_tight_deadband_bundle,
        "validate_run_manifest",
        lambda path: manifest,
    )
    monkeypatch.setattr(
        bounded_tight_deadband_bundle,
        "_read",
        lambda path, label: analysis if "analysis" in label else seal,
    )
    monkeypatch.setattr(
        bounded_tight_deadband_bundle,
        "_sha256_file",
        lambda path: "d" * 64,
    )
    monkeypatch.setattr(
        bounded_tight_deadband_bundle,
        "validate_frozen_bundle",
        lambda path: frozen_bundle,
    )
    monkeypatch.setattr(
        bounded_tight_deadband_bundle,
        "load_programme_status",
        lambda: {"programmes": {bounded_tight_deadband_bundle.PROGRAMME_ID: status}},
    )
    monkeypatch.setattr(
        bounded_tight_deadband_bundle,
        "package_identity",
        lambda path: {"content_sha256": "1" * 64},
    )
    monkeypatch.setattr(
        bounded_tight_deadband_bundle,
        "_validate_q1_q3_sequence",
        lambda **kwargs: {"q1": {}, "q2": {}},
    )

    observed = bounded_tight_deadband_bundle.validate_no_write_qualification_pass(
        run_dir
    )

    assert observed["qualification_sequence_gate"] == "Q3"
    assert observed["run_id"] == run_dir.name
    assert observed["evidence_content_sha256"] == "1" * 64


def test_accelerated_operational_path_runs_supervisor_analyzer_seal_and_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proposal = {
        "bundle_sha256": "e" * 64,
        "source_revision": "f" * 40,
        "firmware": {
            "source_sha256": "a" * 64,
            "configuration_sha256": "b" * 64,
            "build_manifest": {"sha256": "c" * 64},
        },
        "leg_spec": {"profile_id": "cx319_tight_lower"},
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
        bounded_tight_deadband_operational_rehearsal,
        "validate_proposal",
        lambda path: proposal,
    )
    monkeypatch.setattr(
        bounded_tight_deadband_rehearsal_analyze,
        "validate_proposal",
        lambda path: proposal,
    )

    result = bounded_tight_deadband_operational_rehearsal.run(
        proposal_path=proposal_path,
        output_dir=tmp_path / "operational",
    )

    assert result["status"] == "passed"
    assert set(result["hardware_operations"].values()) == {0}
    analysis = json.loads(Path(result["analysis"]).read_text(encoding="utf-8"))
    assert analysis["status"] == "passed"
    assert all(analysis["verdict"]["checks"].values())
    registration = json.loads(
        Path(result["registration"]).read_text(encoding="utf-8")
    )
    assert registration["mode"] == "actual_temporary_external_index_registration"
    assert registration["temporary_index_validation"]["valid"] is True
    assert {
        item["attempt_classification"]
        for item in registration["attempt_classifications_exercised"]
    } == {"completed_campaign", "interrupted_campaign"}
