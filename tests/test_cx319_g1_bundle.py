from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools import cx319_g1_bundle as bundle_tool
from host.otis_tools import cx319_g1_preflight
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
    path = tmp_path / "cx319_g1_bundle.json"
    value = bundle_tool.create_bundle(
        leg=leg,
        build_manifest_path=manifest,
        uf2_path=uf2,
        serial_device="/dev/cu.test-otis",
        output_path=path,
    )
    return path, value


def test_exact_bundle_manifest_and_offline_preflight_cross_all_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, value = _create_bundle(tmp_path, monkeypatch)

    assert bundle_tool.validate_bundle(path) == value
    assert value["operator_authority"]["authority_id"] == (
        "CX319_G1_NO_WRITE_BENCH_AUTHORITY_V1"
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
    assert run_manifest["h_phase"] == "H1"
    assert run_manifest["operator_authority"] == value["operator_authority"]

    preflight = cx319_g1_preflight.evaluate(path)
    assert preflight["status"] == "passed"
    assert all(preflight["checks"].values())
    assert set(preflight["hardware_operations"].values()) == {0}


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


def test_historical_v1_frozen_bundle_remains_structurally_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _ = _create_bundle(tmp_path, monkeypatch)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["runtime_contract"]["id"] = (
        "cx319_g1_prewrite_runtime_contract_v1"
    )
    value["host_tools"].pop("host_attach_contract")
    unsigned = {key: item for key, item in value.items() if key != "bundle_sha256"}
    value["bundle_sha256"] = bundle_tool._canonical_sha256(unsigned)
    path.write_text(json.dumps(value), encoding="utf-8")

    assert bundle_tool.validate_frozen_bundle(path) == value
    with pytest.raises(ValueError, match="host tool binding"):
        bundle_tool.validate_bundle(path)


@pytest.mark.parametrize(
    ("command", "allowed"),
    [
        ("CONFIG?", True),
        ("DAC?", True),
        ("FC0?", True),
        ("ACTIVE?", True),
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
