from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools import active_hybrid_activation as activation


def _write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _semantic(value: dict[str, object], field: str) -> dict[str, object]:
    return {**value, field: activation._canonical_sha256(value)}


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
    monkeypatch.setattr(activation, "validate_bundle", lambda _path: bundle)
    monkeypatch.setattr(activation, "validate_proposal", lambda _path: proposal)
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
