from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools import no_write_qualification_bundle as bundle_tool
from host.otis_tools import no_write_qualification_preflight
from tools.firmware_matrix import configuration_hash, load_matrix, source_input_hash


def _fake_build(tmp_path: Path, leg: str = "A") -> tuple[Path, Path]:
    matrix = load_matrix(bundle_tool.MATRIX_PATH)
    profile_id = bundle_tool.leg_spec(leg)["profile_id"]
    profile = next(item for item in matrix["profiles"] if item["id"] == profile_id)
    uf2 = tmp_path / "otis_nano_rp2040_connect.ino.uf2"
    uf2.write_bytes(b"exact cx319 g1 test firmware")
    manifest = tmp_path / "firmware_build_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provenance": {
                    "source": {
                        "git_commit": "1" * 40,
                        "state": "clean",
                        "sha256": source_input_hash(
                            matrix_path=bundle_tool.MATRIX_PATH
                        ),
                    },
                    "configuration": {
                        "profile_id": profile_id,
                        "defines": profile["defines"],
                        "fqbn": matrix["target"]["fqbn"],
                        "sha256": configuration_hash(matrix, profile),
                    },
                    "invocation": {"id": "cx319-test-invocation"},
                },
                "artifacts": [
                    {
                        "name": uf2.name,
                        "sha256": sha256(uf2.read_bytes()).hexdigest(),
                        "size_bytes": uf2.stat().st_size,
                    }
                ],
                "resource_budget": {
                    "contract": "otis_firmware_resource_budget_v1",
                    "status": "within_budget",
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest, uf2


def _create_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leg: str = "A"
) -> tuple[Path, dict[str, object]]:
    manifest, uf2 = _fake_build(tmp_path, leg)
    monkeypatch.setattr(bundle_tool, "_git_identity", lambda: ("1" * 40, "clean"))
    path = tmp_path / "no_write_qualification_bundle.json"
    value = bundle_tool.create_bundle(
        leg=leg,
        build_manifest_path=manifest,
        uf2_path=uf2,
        serial_device="/dev/cu.test-otis",
        output_path=path,
    )
    return path, value


def _q3_prerequisite_runs(
    tmp_path: Path, firmware: dict[str, object]
) -> tuple[Path, Path]:
    q1 = tmp_path / "passing-q1"
    q2 = tmp_path / "passing-q2"
    (q1 / "reports").mkdir(parents=True)
    (q2 / "reports").mkdir(parents=True)
    (q1 / "COMPLETE").write_text("complete\n", encoding="utf-8")
    (q2 / "COMPLETE").write_text("complete\n", encoding="utf-8")
    q1_bundle = {
        "bundle_sha256": "a" * 64,
        "firmware": firmware,
    }
    (q1 / bundle_tool.RUN_BUNDLE_PATH).write_text(
        json.dumps(q1_bundle), encoding="utf-8"
    )
    (q1 / "reports/cx319_g1_rehearsal_seal_v1.json").write_text(
        json.dumps(
            {
                "status": "pass",
                "seal_type": "cx319_g1_no_write_rehearsal_seal_v1",
                "seal_sha256": "b" * 64,
                "bundle_sha256": q1_bundle["bundle_sha256"],
                "uf2_sha256": firmware["uf2"]["sha256"],
                "setup_writes": 0,
                "dac_value_writes": 0,
                "automatic_writes": 0,
                "control_arms": 0,
                "actuation_authorized": False,
            }
        ),
        encoding="utf-8",
    )
    q2_bundle = {"bundle_sha256": "c" * 64}
    (q2 / "cx319_q2_exact_bundle_v1.json").write_text(
        json.dumps(q2_bundle), encoding="utf-8"
    )
    (q2 / "reports/cx319_q2_transaction_seal_v1.json").write_text(
        json.dumps(
            {
                "status": "pass",
                "seal_type": "cx319_q2_inhibited_transaction_seal_v1",
                "seal_sha256": "d" * 64,
                "bundle_sha256": q2_bundle["bundle_sha256"],
                "physical_setup_writes": 1,
                "physical_automatic_writes": 0,
                "physical_oscillator_movement_possible": False,
                "live_authority_granted": False,
            }
        ),
        encoding="utf-8",
    )
    return q1, q2


def test_exact_bundle_manifest_and_offline_preflight_cross_all_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, value = _create_bundle(tmp_path, monkeypatch)

    assert bundle_tool.validate_bundle(path) == value
    assert value["operator_authority"]["authority_id"] == (
        "CX319_Q1_Q3_SEQUENCE_AUTHORITY_V1"
    )
    assert value["authority"]["dac_value_write"] is False
    assert value["authority"]["control_arm"] is False

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run_manifest = bundle_tool.create_run_manifest(
        bundle_path=path,
        run_dir=run_dir,
        output_path=run_dir / "run_manifest.json",
    )
    assert bundle_tool.validate_run_manifest(run_dir / "run_manifest.json") == (
        run_manifest
    )
    assert run_manifest["actuation_authorized"] is False
    assert run_manifest["compatibility_floor"] == "CX319_EVIDENCE_EPOCH_1"
    assert run_manifest["operator_authority"] == value["operator_authority"]

    preflight = no_write_qualification_preflight.evaluate(path)
    assert preflight["status"] == "passed"
    assert all(preflight["checks"].values())
    assert set(preflight["hardware_operations"].values()) == {0}


def test_q3_bundle_binds_passing_q1_q2_and_requires_fresh_exact_flash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, uf2 = _fake_build(tmp_path)
    build = json.loads(manifest.read_text(encoding="utf-8"))
    build["provenance"]["source"]["sha256"] = "e" * 64
    build["provenance"]["configuration"]["sha256"] = "f" * 64
    manifest.write_text(json.dumps(build), encoding="utf-8")
    monkeypatch.setattr(bundle_tool, "_git_identity", lambda: ("2" * 40, "clean"))
    monkeypatch.setattr(bundle_tool, "_git_is_ancestor", lambda *_args: True)
    firmware = bundle_tool.validate_build(
        leg="A",
        build_manifest_path=manifest,
        uf2_path=uf2,
        allow_clean_ancestor_source=True,
        allow_qualified_ancestor_image=True,
    )
    q1, q2 = _q3_prerequisite_runs(tmp_path, firmware)
    path = tmp_path / "q3-bundle.json"

    value = bundle_tool.create_bundle(
        leg="A",
        build_manifest_path=manifest,
        uf2_path=uf2,
        serial_device="/dev/cu.test-otis",
        output_path=path,
        sequence_gate="Q3",
        q1_run_dir=q1,
        q2_run_dir=q2,
    )

    assert bundle_tool.validate_bundle(path) == value
    assert value["qualification_sequence_gate"] == "Q3"
    assert value["firmware_entry"] == {
        "mode": "single_exact_flash",
        "firmware_flashes_allowed": 1,
    }
    assert value["q3_prerequisites"]["q1"]["uf2_sha256"] == (
        value["firmware"]["uf2"]["sha256"]
    )
    run_dir = tmp_path / "q3-run"
    run_dir.mkdir()
    run_manifest = bundle_tool.create_run_manifest(
        bundle_path=path,
        run_dir=run_dir,
        output_path=run_dir / "run_manifest.json",
    )
    assert run_manifest["qualification_evidence"] is True
    assert run_manifest["cx319"]["qualification_sequence_gate"] == "Q3"


def test_bundle_rejects_write_authority_even_with_recomputed_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _ = _create_bundle(tmp_path, monkeypatch)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["authority"]["dac_value_write"] = True
    unsigned = {
        key: item for key, item in value.items() if key != "bundle_sha256"
    }
    value["bundle_sha256"] = bundle_tool._canonical_sha256(unsigned)
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="write/live authority"):
        bundle_tool.validate_bundle(path)


def test_q1_run_manifest_binds_the_exact_sub_horizon_detach_schedule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, value = _create_bundle(tmp_path, monkeypatch)
    run_dir = tmp_path / "q1-run"
    run_dir.mkdir()

    manifest = bundle_tool.create_run_manifest(
        bundle_path=path,
        run_dir=run_dir,
        output_path=run_dir / "run_manifest.json",
        q1_real_io=True,
    )

    assert manifest["q1_real_io"] == value["q1_real_io"]
    assert all(
        item["detached_s"] < 2.0
        for item in manifest["q1_real_io"]["intentional_detach_schedule"]
    )
    assert "reports/cx319_q1_real_io_prelude_v1.json" in manifest[
        "expected_artifacts"
    ]
    assert "reports/cx319_q1_evidence_session_baseline_v1.json" in manifest[
        "expected_artifacts"
    ]


def test_closed_run_manifest_uses_its_frozen_bundle_not_current_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _ = _create_bundle(tmp_path, monkeypatch)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    manifest = bundle_tool.create_run_manifest(
        bundle_path=path,
        run_dir=run_dir,
        output_path=run_dir / "run_manifest.json",
    )
    monkeypatch.setattr(
        bundle_tool, "_git_identity", lambda: ("9" * 40, "dirty")
    )

    assert bundle_tool.validate_run_manifest(
        run_dir / "run_manifest.json"
    ) == manifest
    with pytest.raises(ValueError, match="clean repository"):
        bundle_tool.validate_bundle(path)


@pytest.mark.parametrize(
    ("command", "allowed"),
    [
        ("CONFIG?", True),
        ("DAC?", True),
        ("FC0?", True),
        ("ACTIVE?", True),
        ("ACTIVE SNAPSHOT 1", True),
        ("ACTIVE SNAPSHOT 4294967295", True),
        ("ACTIVE SNAPSHOT 0", False),
        ("ACTIVE SNAPSHOT 4294967296", False),
        ("ACTIVE LEASE 1", True),
        ("ACTIVE LEASE 4294967295", True),
        ("ACTIVE LEASE 0", False),
        ("ACTIVE LEASE 4294967296", False),
        ("ACTIVE ABORT", False),
        ("DAC SET 0xA808", False),
        ("ACTIVE ARM 1 2 3", False),
        ("PPSGEN START", False),
    ],
)
def test_normal_command_boundary_is_exact(command: str, allowed: bool) -> None:
    assert bundle_tool.normal_command_allowed(command) is allowed


def test_build_must_bind_current_clean_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, uf2 = _fake_build(tmp_path)
    monkeypatch.setattr(bundle_tool, "_git_identity", lambda: ("1" * 40, "dirty"))

    with pytest.raises(ValueError, match="clean repository"):
        bundle_tool.validate_build(
            leg="A", build_manifest_path=manifest, uf2_path=uf2
        )


def test_no_flash_reuse_accepts_an_ancestor_with_identical_firmware_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, uf2 = _fake_build(tmp_path)
    monkeypatch.setattr(bundle_tool, "_git_identity", lambda: ("2" * 40, "clean"))
    monkeypatch.setattr(bundle_tool, "_git_is_ancestor", lambda *_args: True)

    firmware = bundle_tool.validate_build(
        leg="A",
        build_manifest_path=manifest,
        uf2_path=uf2,
        allow_clean_ancestor_source=True,
    )

    assert firmware["git_commit"] == "1" * 40


def test_no_flash_reuse_rejects_a_nonancestor_firmware_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, uf2 = _fake_build(tmp_path)
    monkeypatch.setattr(bundle_tool, "_git_identity", lambda: ("2" * 40, "clean"))
    monkeypatch.setattr(bundle_tool, "_git_is_ancestor", lambda *_args: False)

    with pytest.raises(ValueError, match="current clean source"):
        bundle_tool.validate_build(
            leg="A",
            build_manifest_path=manifest,
            uf2_path=uf2,
            allow_clean_ancestor_source=True,
        )


def test_no_flash_entry_binds_one_prior_exact_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_path, source_bundle = _create_bundle(tmp_path, monkeypatch)
    source_run = tmp_path / "source-run"
    reports = source_run / "reports"
    reports.mkdir(parents=True)
    retained_bundle = source_run / bundle_tool.RUN_BUNDLE_PATH
    retained_bundle.write_bytes(source_path.read_bytes())
    firmware = source_bundle["firmware"]
    board = {
        "address": "/dev/cu.test-otis",
        "serial_number": "503533748A919118",
    }
    flash_record = reports / "cx319_g1_flash_v1.json"
    flash_record.write_text(
        json.dumps(
            {
                "status": "pass",
                "operation": "exact_cx319_g1_firmware_flash",
                "attempt_count": 1,
                "board_before": board,
                "board_after": board,
                "profile_id": firmware["profile_id"],
                "build_manifest_sha256": firmware["build_manifest"]["sha256"],
                "uf2_sha256": firmware["uf2"]["sha256"],
                "bundle_sha256": source_bundle["bundle_sha256"],
                "dac_value_write_attempts": 0,
                "setup_stimulus_attempts": 0,
                "control_arm_attempts": 0,
            }
        ),
        encoding="utf-8",
    )

    entry = bundle_tool.validate_confirmed_installed_firmware(
        firmware=firmware,
        flash_record_path=flash_record,
    )

    assert entry["mode"] == "reuse_confirmed_installed_firmware"
    assert entry["firmware_flashes_allowed"] == 0
    assert entry["installed_uf2_sha256"] == firmware["uf2"]["sha256"]
