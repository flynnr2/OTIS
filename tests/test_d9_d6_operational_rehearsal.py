from __future__ import annotations

import csv
import json
from pathlib import Path

from host.otis_tools import d9_d6_operational_rehearsal as rehearsal
from host.otis_tools.capture_serial import CsvRecordSplitter
from host.otis_tools.contracts import CONTRACT_FIELDS


def _validated_candidate() -> dict:
    profile = {
        "profile_id": "d9_d6_forwarded_output_no_control",
        "configuration": {"profile_id": "d9_d6_forwarded_output_no_control", "defines": {}},
        "build_manifest": {"path": "/fixture/build.json", "size_bytes": 1, "sha256": "d" * 64},
        "elf": {"path": "/fixture/build.elf", "size_bytes": 1, "sha256": "e" * 64},
        "uf2": {"path": "/fixture/build.uf2", "size_bytes": 1, "sha256": "f" * 64},
        "binary_contract": {"status": "verified", "sha256": "a" * 64},
    }
    return {"input_id": "a" * 64, "source_state": {"git_revision": "b" * 40}, "firmware_profiles": [profile]}


def test_deterministic_transcript_carries_d9_identity_and_local_d6_faults() -> None:
    transcript = rehearsal.deterministic_wire_transcript().decode("ascii")

    assert "forwarded_clock_output,integer_divider,1" in transcript
    assert "forwarded_clock_output,fractional_divider,0" in transcript
    assert "build,profile_id,d9_d6_forwarded_output_no_control" in transcript
    assert "boot_capabilities,selected_profile,H1_OCXO_OBSERVE_OPEN_LOOP" in transcript
    assert "controller,hybrid_authority,false" in transcript
    assert "forwarded_clock_monitor,state,monitor_absent" in transcript
    assert "forwarded_clock_monitor,state,monitor_overflow" in transcript
    assert transcript.count("CNT,1,") >= 3
    assert transcript.count("MNS,1,") >= 3


def test_capture_splitter_retains_monitor_separately_from_authoritative_snapshot(
    tmp_path: Path,
) -> None:
    paths = {
        "count_observations_v1": tmp_path / "count.csv",
        "pps_snapshots_v1": tmp_path / "snapshot.csv",
        "forwarded_monitor_snapshots_v1": tmp_path / "monitor.csv",
        "health_v1": tmp_path / "health.csv",
    }
    with CsvRecordSplitter(paths) as splitter:
        for line in rehearsal.deterministic_wire_transcript().decode("ascii").splitlines():
            splitter.process_line(line)

    assert "MNS," not in paths["pps_snapshots_v1"].read_text(encoding="utf-8")
    assert "MNS," in paths["forwarded_monitor_snapshots_v1"].read_text(encoding="utf-8")
    health = list(csv.DictReader(paths["health_v1"].open(newline="", encoding="utf-8")))
    assert any(row["status_value"] == "frequency_only_hold_no_hybrid" for row in health)


def test_manifest_is_explicitly_non_authorizing_and_names_d6_zero_authority(
    tmp_path: Path,
) -> None:
    candidate = _validated_candidate()
    firmware = rehearsal._monitor_firmware_binding(candidate)
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(__import__("json").dumps(candidate), encoding="utf-8")
    run = tmp_path / "run"; run.mkdir()

    manifest = __import__("json").loads(rehearsal._create_manifest(run, "/dev/pts/77", bundle_path, candidate, firmware).read_text())

    assert manifest["qualification_evidence"] is False
    assert manifest["physical_actions_performed"] == 0
    assert manifest["actuation_authorized"] is False
    assert manifest["host"]["serial_device"] == "/dev/pts/77"
    assert next(channel for channel in manifest["channels"] if channel["channel_id"] == 3)["zero_authority"] is True


def test_real_topology_refuses_to_claim_a_rehearsal_without_pyserial(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(rehearsal, "_require_pyserial", lambda: (_ for _ in ()).throw(RuntimeError("pyserial absent")))
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text("{}", encoding="utf-8")

    try:
        rehearsal.run(bundle_path=bundle_path, output_dir=tmp_path / "out")
    except RuntimeError as exc:
        assert "pyserial absent" in str(exc)
    else:
        raise AssertionError("missing transport dependency must fail closed")


def test_real_pty_capture_abort_rotation_analysis_and_registration_path(
    tmp_path: Path, monkeypatch,
) -> None:
    candidate = _validated_candidate()
    monkeypatch.setattr(rehearsal, "validate_rehearsal_input", lambda _raw: candidate)
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(candidate), encoding="utf-8")

    result = rehearsal.run(bundle_path=bundle_path, output_dir=tmp_path / "rehearsal")

    assert result["status"] == "passed"
    assert result["input_id"] == candidate["input_id"]
    assert result["registration_valid"] is True
    assert result["seal_sha256"]
    assert result["chronology"]["no_hybrid_authority"] is True
    assert result["chronology"]["d6_local_faults_retained"] == [
        "monitor_absent",
        "monitor_contradictory",
        "monitor_overflow",
        "monitor_stalled",
    ]
