from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools import cx319_g2_bundle
from host.otis_tools import cx319_g2_live
from host.otis_tools import cx319_g2_run
from host.otis_tools.cx319_g2_bundle import BUNDLE_ID, TOOL_ID as PROPOSAL_TOOL
from host.otis_tools.cx319_g2_contract import canonical_sha256
from host.otis_tools.cx319_g2_live import (
    ACTIVATION_ID,
    OPERATIONAL_REHEARSAL_SEAL,
    TOOL_ID,
    create_activation,
    main,
    validate_frozen_activation,
    validate_operational_rehearsal,
)
from host.otis_tools.programme_status import ProgrammeExecutionBlocked


def _write(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _proposal(path: Path) -> dict[str, object]:
    unsigned: dict[str, object] = {
        "schema_version": 1,
        "tool": PROPOSAL_TOOL,
        "bundle_id": BUNDLE_ID,
        "status": "proposed_not_authorized",
        "authority": {"effective": False},
    }
    value = {**unsigned, "bundle_sha256": canonical_sha256(unsigned)}
    _write(path, value)
    return value


def test_frozen_activation_can_be_revalidated_from_retained_proposal(
    tmp_path: Path,
) -> None:
    proposal_path = tmp_path / "proposal.json"
    proposal = _proposal(proposal_path)
    unsigned: dict[str, object] = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "activation_id": ACTIVATION_ID,
        "programme_id": "cx319_stabilized_tight_deadband",
        "operation": "g2_live_leg",
        "gate": "G2",
        "leg": "A",
        "status": "effective_exact_leg_authority",
        "proposal": {
            "path": str(proposal_path),
            "sha256": sha256(proposal_path.read_bytes()).hexdigest(),
            "bundle_sha256": proposal["bundle_sha256"],
        },
        "operational_rehearsal": {"path": "/retained/rehearsal.json"},
        "authority": {
            "effective": True,
            "firmware_flash": False,
            "setup_code": 0xA808,
            "setup_write_limit": 1,
            "automatic_correction_limit": 4,
            "maximum_automatic_step_codes": 21,
            "maximum_cumulative_codes": 84,
            "minimum_code": 0xA800,
            "maximum_code": 0xAB00,
            "phase_or_hybrid_actionable": False,
            "automatic_retry": False,
            "automatic_restore": False,
        },
    }
    activation = {
        **unsigned,
        "activation_sha256": canonical_sha256(unsigned),
    }
    activation_path = tmp_path / "activation.json"
    _write(activation_path, activation)

    observed, observed_proposal = validate_frozen_activation(activation_path)

    assert observed == activation
    assert observed_proposal == proposal


def test_activation_is_blocked_before_any_input_or_hardware_lookup(
    tmp_path: Path,
) -> None:
    with pytest.raises(ProgrammeExecutionBlocked, match="g2_live_leg"):
        create_activation(
            proposal_path=tmp_path / "missing-proposal.json",
            operational_rehearsal_path=tmp_path / "missing-rehearsal.json",
            serial_device="/dev/not-opened",
            operator_instruction_ref="not-authorized",
            output_path=tmp_path / "must-not-exist.json",
        )

    assert not (tmp_path / "must-not-exist.json").exists()


def test_activation_cli_reports_the_block_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "activate",
                "--proposal",
                str(tmp_path / "missing-proposal.json"),
                "--operational-rehearsal",
                str(tmp_path / "missing-rehearsal.json"),
                "--serial-device",
                "/dev/not-opened",
                "--operator-instruction-ref",
                "not-authorized",
                "--output",
                str(tmp_path / "must-not-exist.json"),
            ]
        )

    assert exc.value.code == 2
    error = capsys.readouterr().err
    assert "g2_live_leg" in error
    assert "Traceback" not in error


def test_activation_consumer_accepts_the_exact_accelerated_rehearsal_seal(
    tmp_path: Path,
) -> None:
    proposal = {"bundle_sha256": "a" * 64}
    analysis_path = tmp_path / "analysis.json"
    _write(analysis_path, {"status": "passed"})
    unsigned_seal: dict[str, object] = {
        "seal_type": OPERATIONAL_REHEARSAL_SEAL,
        "status": "passed",
        "proposal_bundle_sha256": proposal["bundle_sha256"],
        "analysis_file_sha256": sha256(analysis_path.read_bytes()).hexdigest(),
    }
    seal = {
        **unsigned_seal,
        "seal_sha256": canonical_sha256(unsigned_seal),
    }
    seal_path = tmp_path / "seal.json"
    _write(seal_path, seal)
    result_path = tmp_path / "result.json"
    _write(
        result_path,
        {
            "schema_version": 1,
            "tool": "cx319_g2_accelerated_operational_rehearsal_v1",
            "status": "passed",
            "proposal_bundle_sha256": proposal["bundle_sha256"],
            "hardware_operations": {
                "serial_opens": 0,
                "firmware_flashes": 0,
                "dac_writes": 0,
                "control_arms": 0,
            },
            "seal": str(seal_path),
            "analysis": str(analysis_path),
            "artifact_content_sha256": "b" * 64,
        },
    )

    observed = validate_operational_rehearsal(result_path, proposal)

    assert observed["seal_sha256"] == seal["seal_sha256"]


def test_authorized_activation_creates_an_exact_live_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy_sha = sha256(cx319_g2_bundle.POLICY_PATH.read_bytes()).hexdigest()
    firmware = {
        "source_sha256": "a" * 64,
        "configuration_sha256": "b" * 64,
        "profile_id": "cx319_tight_lower",
        "build_manifest": {"sha256": "c" * 64},
        "uf2": {"sha256": "d" * 64},
    }
    policy = {
        "policy_id": "CX319_STABILIZED_TIGHT_DEADBAND_FREQUENCY_ONLY_V1",
        "sha256": policy_sha,
    }
    fake_g1 = {
        "run_id": "g1-pass",
        "run_dir": "/retained/g1-pass",
        "run_manifest_sha256": "1" * 64,
        "analysis_sha256": "2" * 64,
        "analysis_file_sha256": "3" * 64,
        "seal_sha256": "4" * 64,
        "seal_file_sha256": "5" * 64,
        "evidence_content_sha256": "6" * 64,
        "bundle_sha256": "7" * 64,
        "firmware": firmware,
        "policy": policy,
    }
    monkeypatch.setattr(
        cx319_g2_bundle, "_git_identity", lambda: ("8" * 40, "clean")
    )
    monkeypatch.setattr(
        cx319_g2_bundle, "validate_g1_pass", lambda path: fake_g1
    )
    proposal_path = tmp_path / "proposal.json"
    proposal = cx319_g2_bundle.create_proposal(
        g1_run_dir=tmp_path / "g1", output_path=proposal_path
    )
    rehearsal = {
        "path": str(tmp_path / "operational.json"),
        "sha256": "9" * 64,
        "artifact_content_sha256": "a" * 64,
        "seal_path": str(tmp_path / "seal.json"),
        "seal_sha256": "b" * 64,
        "seal_file_sha256": "c" * 64,
    }
    monkeypatch.setattr(
        cx319_g2_live, "require_programme_operation_allowed", lambda *args: {}
    )
    monkeypatch.setattr(cx319_g2_live, "_git_clean", lambda: True)
    monkeypatch.setattr(
        cx319_g2_live,
        "validate_operational_rehearsal",
        lambda path, observed: rehearsal,
    )
    activation_path = tmp_path / "activation.json"
    activation = cx319_g2_live.create_activation(
        proposal_path=proposal_path,
        operational_rehearsal_path=tmp_path / "operational.json",
        serial_device="/dev/cu.test",
        operator_instruction_ref="test-authority",
        output_path=activation_path,
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run_proposal = run_dir / cx319_g2_live.RUN_PROPOSAL_PATH
    run_activation = run_dir / cx319_g2_live.RUN_ACTIVATION_PATH
    run_proposal.write_bytes(proposal_path.read_bytes())
    run_activation.write_bytes(activation_path.read_bytes())

    manifest = cx319_g2_live.create_run_manifest(
        activation_path=run_activation,
        proposal_path=run_proposal,
        run_dir=run_dir,
        output_path=run_dir / "run_manifest.json",
    )

    assert manifest["stage"] == cx319_g2_live.LIVE_STAGE
    assert manifest["firmware"] == proposal["firmware"]
    assert manifest["g1_pass"]["evidence_content_sha256"] == "6" * 64
    assert manifest["cx319"]["planned_live_stimulus"]["code"] == 0xA808
    assert manifest["cx319"]["automatic_frequency_control"] == {
        "authorized": True,
        "required_direction": "positive",
        "maximum_corrections": 4,
        "maximum_step_codes": 21,
        "maximum_cumulative_movement_codes": 84,
        "minimum_applied_correction_cadence_s": 1800,
        "minimum_code": 0xA800,
        "maximum_code": 0xAB00,
        "settling_exclusion_s": 900,
        "fresh_support_after_settling_s": 600,
        "one_request_outstanding": True,
        "automatic_retry": False,
        "automatic_restore": False,
    }
    assert cx319_g2_live.validate_frozen_run_manifest(
        run_dir / "run_manifest.json"
    ) == manifest


def test_physical_runner_explicitly_forbids_a_firmware_flash() -> None:
    source = Path("host/otis_tools/cx319_g2_run.py").read_text(encoding="utf-8")

    assert "arduino_cli, \"upload\"" not in source
    assert '"firmware_flashes": 0' in source


def test_post_snapshot_finalization_failure_registers_without_mutating_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    snapshot = run_dir / cx319_g2_run.EVIDENCE_MANIFEST
    snapshot.write_text("sealed-before-analyzer\n", encoding="utf-8")
    registered: dict[str, object] = {}

    def register(**kwargs: object) -> dict[str, str]:
        registered.update(kwargs)
        return {"content_sha256": "f" * 64}

    monkeypatch.setattr(cx319_g2_run, "register_package", register)
    result = cx319_g2_run._retain_finalization_failure(
        run_dir=run_dir,
        activation={"activation_sha256": "a" * 64},
        proposal={
            "source_revision": "b" * 40,
            "firmware": {"build_manifest": {"sha256": "c" * 64}},
            "leg_spec": {"profile_id": "cx319_tight_lower"},
        },
        evidence_index_path=tmp_path / "index.jsonl",
        error=RuntimeError("analyzer mismatch"),
    )

    assert result["content_sha256"] == "f" * 64
    assert snapshot.read_text(encoding="utf-8") == "sealed-before-analyzer\n"
    assert not (run_dir / cx319_g2_run.ORCHESTRATION_FAILURE).exists()
    assert registered["attempt_classification"] == "failed_live_leg"
    assert "finalization failed" in str(registered["result_or_failure_reason"])
