from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools.cx318_stage5_manifest import (
    LIVE_LEG_SEAL_TYPE,
    HOST_TOOL_PATHS,
    REHEARSAL_SEAL_TYPE,
    STAGE4_BINDING_TYPE,
    create_manifest,
    validate_manifest,
)


ROOT = Path(__file__).resolve().parents[1]


def _digest(value: dict[str, object]) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _profile_defines(profile_id: str) -> dict[str, str]:
    matrix = json.loads((ROOT / "firmware/arduino/firmware_matrix.json").read_text())
    return next(item["defines"] for item in matrix["profiles"] if item["id"] == profile_id)


def _build(tmp_path: Path, profile_id: str) -> tuple[Path, Path]:
    uf2 = tmp_path / f"{profile_id}.uf2"
    uf2.write_bytes(b"exact UF2 fixture\n")
    build = tmp_path / f"{profile_id}_build.json"
    build.write_text(json.dumps({
        "schema_version": 1,
        "artifacts": [{"name": uf2.name, "sha256": _sha(uf2), "size_bytes": uf2.stat().st_size}],
        "provenance": {
            "source": {"state": "clean", "sha256": "a" * 64, "git_commit": "b" * 40},
            "configuration": {"profile_id": profile_id, "sha256": "c" * 64, "defines": _profile_defines(profile_id)},
        },
    }), encoding="utf-8")
    return build, uf2


def _stage4_seal(tmp_path: Path) -> Path:
    value: dict[str, object] = {
        "schema_version": 1,
        "binding_type": STAGE4_BINDING_TYPE,
        "run": {"manifest_sha256": "a" * 64},
        "live_analysis": {"status": "passed"},
        "evidence_snapshot": {"sha256": "b" * 64, "snapshot_digest": "c" * 64},
    }
    value["binding_sha256"] = _digest(value)
    path = tmp_path / "external-stage4-pass.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _rehearsal_seal(tmp_path: Path, *, leg: str, build: Path, uf2: Path, profile: str) -> Path:
    rehearsal_run = tmp_path / f"rehearsal-source-{leg}"
    rehearsal_run.mkdir(exist_ok=True)
    run_manifest = rehearsal_run / "run_manifest.json"
    evidence = rehearsal_run / "reports/evidence_snapshot.json"
    evidence.parent.mkdir(exist_ok=True)
    run_manifest.write_text("exact rehearsal manifest fixture\n", encoding="utf-8")
    evidence.write_text("exact rehearsal evidence fixture\n", encoding="utf-8")
    (rehearsal_run / "COMPLETE").write_text("fixture complete\n", encoding="utf-8")
    (rehearsal_run / "reports/capture_device_state.json").write_text(
        json.dumps({"capture_active": False, "logical_segment_closed": True}),
        encoding="utf-8",
    )
    value: dict[str, object] = {
        "schema_version": 1,
        "seal_type": REHEARSAL_SEAL_TYPE,
        "tool": "cx318_stage5_rehearsal_analyze_v1",
        "status": "passed",
        "leg": leg,
        "profile_id": profile,
        "build_manifest_sha256": _sha(build),
        "uf2_sha256": _sha(uf2),
        "rehearsal": {
            "capture_duration_s": 2700,
            "selected_600s_estimates": 1,
            "setup_writes": 0,
            "dac_writes": 0,
            "automatic_writes": 0,
            "accelerated_or_relaxed_limits": False,
        },
        "run": {"path": str(rehearsal_run), "manifest_sha256": _sha(run_manifest)},
        "evidence_snapshot": {
            "path": str(evidence),
            "sha256": _sha(evidence),
            "snapshot_digest": "f" * 64,
        },
        "checks": {"fixture_exact": True},
        "source_artifacts_sha256": {
            "run_manifest.json": _sha(run_manifest),
            "reports/evidence_snapshot.json": _sha(evidence),
            "COMPLETE": _sha(rehearsal_run / "COMPLETE"),
            "reports/capture_device_state.json": _sha(
                rehearsal_run / "reports/capture_device_state.json"
            ),
        },
    }
    value["seal_sha256"] = _digest(value)
    path = tmp_path / f"external-rehearsal-{leg}.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _live_a_seal(tmp_path: Path, stage4: Path) -> Path:
    build, uf2 = _build(tmp_path, "cx318_stage5_tight_lower")
    rehearsal = _rehearsal_seal(
        tmp_path,
        leg="A",
        build=build,
        uf2=uf2,
        profile="cx318_stage5_tight_lower",
    )
    run = tmp_path / "live-a-source"
    manifest_path = create_manifest(
        mode="live",
        leg="A",
        run_dir=run,
        build_manifest_path=build,
        uf2_path=uf2,
        stage4_seal_path=stage4,
        rehearsal_seal_path=rehearsal,
        serial_device="/dev/cu.fixture",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    (run / "reports").mkdir(exist_ok=True)
    (run / "COMPLETE").write_text("fixture complete\n", encoding="utf-8")
    (run / "reports/capture_device_state.json").write_text(
        json.dumps({"capture_active": False, "logical_segment_closed": True}),
        encoding="utf-8",
    )
    transition = tmp_path / "live-a-transition"
    transition.mkdir()
    transition_manifest = transition / "run_manifest.json"
    transition_manifest.write_text("fixture transition\n", encoding="utf-8")
    value: dict[str, object] = {
        "seal_type": LIVE_LEG_SEAL_TYPE,
        "tool": "cx318_stage5_live_analyze_v1",
        "tool_sha256": _sha(HOST_TOOL_PATHS["live_analyzer"]),
        "status": "passed",
        "failure_class": "none",
        "leg": "A",
        "profile_id": "cx318_stage5_tight_lower",
        "policy_sha256": manifest["policy"]["sha256"],
        "build_manifest_sha256": manifest["firmware"]["sha256"],
        "uf2_sha256": manifest["firmware"]["uf2"]["sha256"],
        "stage4_binding_sha256": manifest["stage4_seal"]["binding_sha256"],
        "rehearsal_seal_sha256": manifest["stage5"]["rehearsal_seal"][
            "seal_sha256"
        ],
        "required_direction": "positive",
        "checks": {"fixture_exact": True},
        "run": {"path": str(run), "manifest_sha256": _sha(manifest_path)},
        "source_artifacts_sha256": {
            "run_manifest.json": _sha(manifest_path),
            "COMPLETE": _sha(run / "COMPLETE"),
            "reports/capture_device_state.json": _sha(
                run / "reports/capture_device_state.json"
            ),
        },
        "transition_source": {
            "root": str(transition),
            "owner_pid": 123,
            "transport_generation": 2,
            "manifest_sha256": _sha(transition_manifest),
            "checks": {"fixture_exact": True},
            "source_artifacts_sha256": {
                "run_manifest.json": _sha(transition_manifest)
            },
        },
    }
    value["seal_sha256"] = _digest(value)
    path = tmp_path / "external-live-A.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_rehearsal_manifest_is_exact_same_profile_no_write_and_validates(tmp_path: Path) -> None:
    build, uf2 = _build(tmp_path, "cx318_stage5_tight_lower")
    path = create_manifest(
        mode="rehearsal", leg="A", run_dir=tmp_path / "rehearsal", build_manifest_path=build,
        uf2_path=uf2, stage4_seal_path=_stage4_seal(tmp_path), serial_device="/dev/cu.fixture",
    )
    manifest = validate_manifest(path)
    assert manifest["stage5"]["firmware_profile"] == "cx318_stage5_tight_lower"
    assert manifest["stage5"]["setup"] == {
        "code": 0xA808, "code_hex": "0xA808", "maximum_writes": 0, "authorized": False,
    }
    automatic = manifest["stage5"]["automatic_frequency_control"]
    assert automatic["required_direction"] == "positive"
    assert (automatic["maximum_corrections"], automatic["maximum_cumulative_movement_codes"]) == (0, 0)
    assert (automatic["maximum_step_codes"], automatic["minimum_applied_correction_cadence_s"]) == (21, 1800)
    assert (automatic["settling_exclusion_s"], automatic["fresh_support_after_settling_s"]) == (900, 600)
    assert manifest["stage5"]["qualification"] == {
        "deadline_s": 5400, "maximum_qualified_duration_s": 14400, "no_extension_after_finite_endpoint": True,
    }
    assert manifest["stage5"]["rehearsal"]["minimum_capture_duration_s"] == 2700
    assert manifest["policy"]["bindings"]["master_prompt"]
    assert manifest["policy"]["bindings"]["stage5_prompt"]
    assert "tight_deadband_decisions_v1" in manifest["contracts"]


def test_live_manifest_requires_and_binds_matching_passed_rehearsal_seal(tmp_path: Path) -> None:
    build, uf2 = _build(tmp_path, "cx318_stage5_tight_upper")
    seal = _rehearsal_seal(tmp_path, leg="B", build=build, uf2=uf2, profile="cx318_stage5_tight_upper")
    stage4 = _stage4_seal(tmp_path)
    leg_a_seal = _live_a_seal(tmp_path, stage4)
    path = create_manifest(
        mode="live", leg="B", run_dir=tmp_path / "live", build_manifest_path=build, uf2_path=uf2,
        stage4_seal_path=stage4, rehearsal_seal_path=seal, leg_a_seal_path=leg_a_seal,
        serial_device="/dev/cu.fixture",
    )
    manifest = validate_manifest(path)
    stage5 = manifest["stage5"]
    assert stage5["setup"]["code"] == 0xA848
    assert stage5["automatic_frequency_control"]["required_direction"] == "negative"
    assert (stage5["automatic_frequency_control"]["maximum_corrections"], stage5["automatic_frequency_control"]["maximum_cumulative_movement_codes"]) == (4, 84)
    assert stage5["rehearsal_seal"]["sha256"] == _sha(seal)
    assert stage5["leg_a_seal"]["seal_sha256"] == json.loads(
        leg_a_seal.read_text(encoding="utf-8")
    )["seal_sha256"]
    leg_a_value = json.loads(leg_a_seal.read_text(encoding="utf-8"))
    transition_manifest = (
        Path(leg_a_value["transition_source"]["root"]) / "run_manifest.json"
    )
    original_transition = transition_manifest.read_text(encoding="utf-8")
    transition_manifest.write_text("tampered transition\n", encoding="utf-8")
    with pytest.raises(ValueError, match="transition source artifact changed"):
        validate_manifest(path)
    transition_manifest.write_text(original_transition, encoding="utf-8")
    stage4.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Stage 4 seal"):
        validate_manifest(path)


def test_live_leg_b_is_forbidden_without_a_passed_leg_a_seal(tmp_path: Path) -> None:
    build, uf2 = _build(tmp_path, "cx318_stage5_tight_upper")
    rehearsal = _rehearsal_seal(
        tmp_path,
        leg="B",
        build=build,
        uf2=uf2,
        profile="cx318_stage5_tight_upper",
    )
    with pytest.raises(ValueError, match="leg B requires --leg-a-seal"):
        create_manifest(
            mode="live",
            leg="B",
            run_dir=tmp_path / "forbidden-b",
            build_manifest_path=build,
            uf2_path=uf2,
            stage4_seal_path=_stage4_seal(tmp_path),
            rehearsal_seal_path=rehearsal,
            serial_device="/dev/cu.fixture",
        )


def test_live_rejects_rehearsal_source_changed_after_external_seal(tmp_path: Path) -> None:
    build, uf2 = _build(tmp_path, "cx318_stage5_tight_lower")
    seal = _rehearsal_seal(
        tmp_path,
        leg="A",
        build=build,
        uf2=uf2,
        profile="cx318_stage5_tight_lower",
    )
    seal_value = json.loads(seal.read_text(encoding="utf-8"))
    source_run = Path(seal_value["run"]["path"])
    (source_run / "run_manifest.json").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="changed after sealing"):
        create_manifest(
            mode="live",
            leg="A",
            run_dir=tmp_path / "reject-tampered-rehearsal",
            build_manifest_path=build,
            uf2_path=uf2,
            stage4_seal_path=_stage4_seal(tmp_path),
            rehearsal_seal_path=seal,
            serial_device="/dev/cu.fixture",
        )


def test_live_rejects_wrong_profile_or_non_exact_rehearsal_and_stale_stage4_seal(tmp_path: Path) -> None:
    build, uf2 = _build(tmp_path, "cx318_stage5_tight_lower")
    seal = _rehearsal_seal(tmp_path, leg="A", build=build, uf2=uf2, profile="cx318_stage5_tight_lower")
    value = json.loads(seal.read_text())
    value["rehearsal"]["capture_duration_s"] = 2699
    value["seal_sha256"] = _digest({key: item for key, item in value.items() if key != "seal_sha256"})
    seal.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="2700"):
        create_manifest(
            mode="live", leg="A", run_dir=tmp_path / "reject-short", build_manifest_path=build, uf2_path=uf2,
            stage4_seal_path=_stage4_seal(tmp_path), rehearsal_seal_path=seal, serial_device="/dev/cu.fixture",
        )

    stage4 = _stage4_seal(tmp_path)
    stage4_value = json.loads(stage4.read_text())
    stage4_value["live_analysis"]["status"] = "failed"
    stage4_value["binding_sha256"] = _digest({key: item for key, item in stage4_value.items() if key != "binding_sha256"})
    stage4.write_text(json.dumps(stage4_value), encoding="utf-8")
    with pytest.raises(ValueError, match="Stage 4 seal"):
        create_manifest(
            mode="rehearsal", leg="A", run_dir=tmp_path / "reject-stage4", build_manifest_path=build, uf2_path=uf2,
            stage4_seal_path=stage4, serial_device="/dev/cu.fixture",
        )


def test_manifest_never_overwrites_evidence_or_accepts_relaxed_build(tmp_path: Path) -> None:
    build, uf2 = _build(tmp_path, "cx318_stage5_tight_lower")
    run_dir = tmp_path / "occupied"
    run_dir.mkdir()
    (run_dir / "evidence.txt").write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError, match="new or empty"):
        create_manifest(
            mode="rehearsal", leg="A", run_dir=run_dir, build_manifest_path=build, uf2_path=uf2,
            stage4_seal_path=_stage4_seal(tmp_path), serial_device="/dev/cu.fixture",
        )
    assert (run_dir / "evidence.txt").read_text(encoding="utf-8") == "preserve"

    value = json.loads(build.read_text())
    value["provenance"]["configuration"]["defines"]["OTIS_CX317_DECISION_CADENCE_S"] = "1u"
    build.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="accelerated or relaxed"):
        create_manifest(
            mode="rehearsal", leg="A", run_dir=tmp_path / "relaxed", build_manifest_path=build, uf2_path=uf2,
            stage4_seal_path=_stage4_seal(tmp_path), serial_device="/dev/cu.fixture",
        )
