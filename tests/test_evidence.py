from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from host.otis_tools.evidence import EVIDENCE_MANIFEST, EvidenceError, create_evidence_snapshot
from host.otis_tools.validate_run import validate_run


EXAMPLE = Path("examples/h0_pps_tcxo_synthetic")


def _completed_run(tmp_path: Path, name: str = "run") -> Path:
    run_dir = tmp_path / name
    shutil.copytree(EXAMPLE, run_dir)
    (run_dir / "COMPLETE").touch()
    return run_dir


def _snapshot(run_dir: Path) -> dict:
    return json.loads((run_dir / EVIDENCE_MANIFEST).read_text(encoding="utf-8"))


def _append_build_provenance(
    run_dir: Path,
    filename: str = "health.csv",
) -> dict[str, str]:
    values = {
        "provenance_format": "otis_generated_build_v1",
        "git_commit": "a" * 40,
        "source_state": "dirty",
        "source_sha256": "d" * 64,
        "config_sha256": "b" * 64,
        "board": "arduino_nano_connect",
        "board_name": "Arduino Nano RP2040 Connect",
        "fqbn": "rp2040:rp2040:arduino_nano_connect",
        "core_provider": "rp2040",
        "core_version": "6.0.0",
        "core_installed_sha256": "e" * 64,
        "profile_id": "phase5_qualification",
        "toolchain": "pqt-gcc@5.0.0-9576866",
        "compiler": "pqt-gcc@5.0.0-9576866/arm-none-eabi-g++@16.1.0",
        "toolchain_installed_sha256": "f" * 64,
        "arduino_cli_version": "1.4.1",
        "invocation_id": "c" * 64,
    }
    statuses = [
        ("build", "provenance_format", values["provenance_format"]),
        ("firmware", "git_commit", values["git_commit"]),
        ("firmware", "source_state", values["source_state"]),
        ("firmware", "source_hash", values["source_sha256"]),
        ("firmware", "config_hash", values["config_sha256"]),
        ("system", "board", values["board"]),
        ("system", "board_name", values["board_name"]),
        ("system", "fqbn", values["fqbn"]),
        ("system", "arduino_core_provider", values["core_provider"]),
        ("system", "arduino_core_version", values["core_version"]),
        (
            "system",
            "arduino_core_installed_hash",
            values["core_installed_sha256"],
        ),
        ("build", "profile_id", values["profile_id"]),
        ("build", "toolchain", values["toolchain"]),
        ("build", "compiler", values["compiler"]),
        (
            "build",
            "toolchain_installed_hash",
            values["toolchain_installed_sha256"],
        ),
        ("build", "arduino_cli_version", values["arduino_cli_version"]),
        ("build", "invocation_id", values["invocation_id"]),
    ]
    path = run_dir / filename
    with path.open("a", encoding="utf-8") as handle:
        for offset, (component, key, value) in enumerate(statuses, start=10):
            handle.write(
                f"STS,1,{offset},{1_632_000_000 + offset},rp2040_timer0,"
                f"{component},{key},{value},INFO,32768\n"
            )
    return values


def test_snapshot_is_deterministic_and_covers_profile_and_declared_evidence(tmp_path: Path) -> None:
    first = _completed_run(tmp_path, "first")
    second = _completed_run(tmp_path, "second")

    create_evidence_snapshot(first)
    create_evidence_snapshot(second)

    assert _snapshot(first) == _snapshot(second)
    artifacts = {entry["path"]: entry for entry in _snapshot(first)["artifacts"]}
    assert artifacts["run_manifest.json"]["role"] == "run_manifest"
    assert artifacts["raw_events.csv"]["contract"] == "raw_events_v1"
    assert artifacts["selected_profile.yaml"]["role"] == "profile_snapshot"
    assert validate_run(first) == 0


def test_snapshot_captures_exact_emitted_firmware_build_provenance(
    tmp_path: Path,
) -> None:
    run_dir = _completed_run(tmp_path)
    expected = _append_build_provenance(run_dir)

    create_evidence_snapshot(run_dir)

    snapshot = _snapshot(run_dir)
    assert snapshot["firmware_build_provenance"] == dict(
        sorted(expected.items())
    )
    assert validate_run(run_dir) == 0


def test_snapshot_rejects_partial_or_malformed_build_provenance(
    tmp_path: Path,
) -> None:
    run_dir = _completed_run(tmp_path)
    with (run_dir / "health.csv").open("a", encoding="utf-8") as handle:
        handle.write(
            "STS,1,10,10,rp2040_timer0,build,provenance_format,"
            "otis_generated_build_v1,INFO,32768\n"
            "STS,1,11,11,rp2040_timer0,firmware,git_commit,"
            f"{'a' * 40},INFO,32768\n"
        )

    with pytest.raises(EvidenceError, match="incomplete"):
        create_evidence_snapshot(run_dir)


def test_complete_banner_cannot_mask_later_partial_boot(tmp_path: Path) -> None:
    run_dir = _completed_run(tmp_path)
    _append_build_provenance(run_dir)
    with (run_dir / "health.csv").open("a", encoding="utf-8") as handle:
        handle.write(
            "STS,1,99,1632000099,rp2040_timer0,build,provenance_format,"
            "otis_generated_build_v1,INFO,32768\n"
        )

    with pytest.raises(EvidenceError, match="banner 2 is incomplete"):
        create_evidence_snapshot(run_dir)


def test_each_health_file_ignores_legacy_rows_before_its_own_sentinel(
    tmp_path: Path,
) -> None:
    run_dir = _completed_run(tmp_path)
    expected = _append_build_provenance(run_dir)
    second_name = "health_second.csv"
    header = (run_dir / "health.csv").read_text(encoding="utf-8").splitlines()[0]
    (run_dir / second_name).write_text(
        header
        + "\n"
        + "STS,1,1,10,rp2040_timer0,firmware,git_commit,"
        + f"{'9' * 40},INFO,32768\n",
        encoding="utf-8",
    )
    _append_build_provenance(run_dir, second_name)
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append(
        {"path": second_name, "contract": "health_v1"}
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    create_evidence_snapshot(run_dir)

    assert _snapshot(run_dir)["firmware_build_provenance"] == dict(
        sorted(expected.items())
    )
    assert validate_run(run_dir) == 0


def test_legacy_identity_rows_remain_legacy_even_for_phase5_run(
    tmp_path: Path,
) -> None:
    run_dir = _completed_run(tmp_path)
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["stage"] = "PHASE5_PPS_BACKEND_QUALIFICATION"
    manifest["firmware"]["name"] = "otis_nano_rp2040_connect"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with (run_dir / "health.csv").open("a", encoding="utf-8") as handle:
        handle.write(
            "STS,1,10,1632000010,rp2040_timer0,firmware,git_commit,"
            f"{'a' * 40},INFO,32768\n"
            "STS,1,11,1632000011,rp2040_timer0,system,board,"
            "arduino_nano_rp2040_connect,INFO,32768\n"
        )

    create_evidence_snapshot(run_dir)

    assert "firmware_build_provenance" not in _snapshot(run_dir)
    assert validate_run(run_dir) == 0


def test_required_generated_banner_must_be_present(tmp_path: Path) -> None:
    run_dir = _completed_run(tmp_path)
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["firmware"]["build_provenance_required"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(EvidenceError, match="sentinel banner is missing"):
        create_evidence_snapshot(run_dir)


def test_snapshot_covers_raw_bytes_and_detects_later_mutation(tmp_path: Path, capsys) -> None:
    run_dir = _completed_run(tmp_path)
    (run_dir / "raw").mkdir()
    raw_log = run_dir / "raw" / "serial.log"
    raw_log.write_bytes(b"preserved raw bytes\n")
    create_evidence_snapshot(run_dir)

    raw_log.write_bytes(b"changed raw bytes\n")

    assert validate_run(run_dir) == 1
    assert "raw/serial.log: SHA-256 differs from evidence snapshot" in capsys.readouterr().err


def test_snapshot_detects_manifest_mutation_and_new_unsealed_raw_evidence(tmp_path: Path, capsys) -> None:
    run_dir = _completed_run(tmp_path)
    create_evidence_snapshot(run_dir)
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["operator_notes"] = "changed after sealing"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "raw").mkdir()
    (run_dir / "raw" / "late.log").write_text("late evidence\n", encoding="utf-8")

    assert validate_run(run_dir) == 1
    errors = capsys.readouterr().err
    assert "run_manifest.json: SHA-256 differs from evidence snapshot" in errors
    assert "raw/late.log: evidence-bearing artifact is not covered" in errors


def test_snapshot_refuses_in_progress_incomplete_and_overwrite(tmp_path: Path) -> None:
    run_dir = _completed_run(tmp_path)
    (run_dir / "capture_in_progress.flag").touch()
    with pytest.raises(EvidenceError, match="in progress"):
        create_evidence_snapshot(run_dir)

    (run_dir / "capture_in_progress.flag").unlink()
    (run_dir / "COMPLETE").unlink()
    with pytest.raises(EvidenceError, match="COMPLETE"):
        create_evidence_snapshot(run_dir)

    create_evidence_snapshot(run_dir, allow_incomplete=True)
    assert _snapshot(run_dir)["run_state"] == "partial"
    with pytest.raises(FileExistsError, match="already exists"):
        create_evidence_snapshot(run_dir, allow_incomplete=True)


def test_validator_warns_when_legacy_run_has_no_snapshot(tmp_path: Path, capsys) -> None:
    run_dir = _completed_run(tmp_path)

    assert validate_run(run_dir) == 0
    assert "immutable evidence snapshot is missing" in capsys.readouterr().err


def test_snapshot_rejects_manifest_path_escape(tmp_path: Path) -> None:
    run_dir = _completed_run(tmp_path)
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "../outside.csv"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(EvidenceError, match="normalized run-relative"):
        create_evidence_snapshot(run_dir)


def test_snapshot_rejects_declared_artifact_through_symlink(tmp_path: Path) -> None:
    run_dir = _completed_run(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evidence.csv").write_text("not run-local\n", encoding="utf-8")
    (run_dir / "linked").symlink_to(outside, target_is_directory=True)
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "linked/evidence.csv"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(EvidenceError, match="symbolic link"):
        create_evidence_snapshot(run_dir)
