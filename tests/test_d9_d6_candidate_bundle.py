from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from host.otis_tools.d9_d6_candidate_bundle import (
    BUNDLE_TYPE,
    TERMINAL_READY,
    canonical_sha256,
    file_binding,
    freeze_candidate,
    freeze_rehearsal_input,
    validate_candidate,
    validate_rehearsal_input,
)


def _binding(tmp_path: Path, name: str) -> dict[str, object]:
    path = tmp_path / name
    path.write_text(f"exact {name}\n", encoding="utf-8")
    return file_binding(path)


def _profile(tmp_path: Path, profile_id: str, d9: str, d6: str) -> dict[str, object]:
    defines = {
        "OTIS_ENABLE_D9_D6_READINESS_PROFILE": "1",
        "OTIS_ENABLE_DUAL_CORE_PARTITION": "1",
        "OTIS_ENABLE_GNSS_RECEIVER": "0",
        "OTIS_GNSS_UART_TX_ENABLED": "0",
        "OTIS_GNSS_UART_BAUD": "115200u",
        "OTIS_ENABLE_DAC_AD5693R": "0",
        "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": "0",
        "OTIS_ENABLE_CX320_ACTIVE_HYBRID": "0",
        "OTIS_ENABLE_CX321_ACTIVE_HYBRID": "0",
        "OTIS_ENABLE_CX322_DIRECT_HYBRID": "0",
        "OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION": "0",
        "OTIS_ENABLE_FORWARDED_D9_OUTPUT": d9,
        "OTIS_ENABLE_FORWARDED_D6_MONITOR": d6,
    }
    return {
        "profile_id": profile_id,
        "configuration": {"profile_id": profile_id, "defines": defines},
        "toolchain": {
            "arduino_cli": "1.2.3",
            "core": "rp2040@4.0.1",
            "compiler": "arm-none-eabi-g++",
            "installed_sha256": "1" * 64,
        },
        "build_manifest": _binding(tmp_path, f"{profile_id}.manifest.json"),
        "elf": _binding(tmp_path, f"{profile_id}.elf"),
        "uf2": _binding(tmp_path, f"{profile_id}.uf2"),
        "binary_contract": {
            "status": "disabled_profile"
            if profile_id == "d9_disabled_no_control_baseline"
            else "verified",
            "sha256": "2" * 64,
        },
    }


def _draft(tmp_path: Path) -> dict[str, object]:
    draft: dict[str, object] = {
        "schema_version": 1,
        "bundle_type": BUNDLE_TYPE,
        "tool": BUNDLE_TYPE,
        "effective": False,
        "physical_authority": False,
        "terminal": TERMINAL_READY,
        "source_state": {
            "git_revision": "a" * 40,
            "tree_state": "clean",
            "dirty_paths": [],
            "dirty_paths_sha256": canonical_sha256([]),
        },
        "dependencies": {
            "gnss_baud_envelope": {
                "terminal": "multi_baud_characterization_continuation_complete",
                "selected_operational_baud": 115200,
                "package_sha256": "3" * 64,
                "seal_sha256": "4" * 64,
            },
            "v2_adaptive_study": {
                "contract_sha256": "b7525de381bbd6506978819a46ccdc280993c47aba2d1ab673a9e595b48e325f",
                "derived_manifest_sha256": "705361d252782c911cea63bfca691691c6ab045956942f057f87db31827b4816",
                "report_sha256": "c411e44042162192228b04c4ebd567b90d73ddd77344f9d1d6f494ada863e9e5",
                "tool_bundle_sha256": "fbbcb152880b0079e97eb9b9d216e292aa805ceb829e78996c4e06dee282b1ca",
                "terminal": "provisional_cx322_unchanged_pending_d9_gate",
            },
        },
        "contract": {
            "d9_d6_readiness": {
                "contract_id": "OTIS_D9_D6_READINESS_CONTRACT_V1",
                "contract_semantic_sha256": "a6a08d14a03a87b5e0308880c64799baf2e7afecc23cad22d1532f297960de4d",
                "profile": "d9_d6_forwarded_output_no_control",
                "physical_authority": False,
            },
            "readiness_contract": _binding(tmp_path, "d9_d6_readiness_contract_v1.json"),
        },
        "firmware_profiles": [
            _profile(tmp_path, "d9_disabled_no_control_baseline", "0", "0"),
            _profile(tmp_path, "d9_forwarded_output_no_control", "1", "0"),
            _profile(tmp_path, "d9_d6_forwarded_output_no_control", "1", "1"),
        ],
        "host_tools": [_binding(tmp_path, "capture_device.py"), _binding(tmp_path, "d9_d6_analyze.py")],
        "bench_topology": {
            "d14": "sole_authoritative_pps_input",
            "d8": "sole_authoritative_oscillator_count_input",
            "d9": "forwarded_output_only",
            "d6": "zero_authority_diagnostic_only",
            "wiring": "D9_to_D6_series_1000_ohms",
            "load": "high_impedance_only_no_50_ohm",
        },
        "serial": {"firmware_host_baud": 115200, "device_selection": "capture_device_auto_detect_exactly_one_cu_usbmodem"},
        "scope": {
            "waveform_gate_ceiling": "output_function_correct_but_waveform_evidence_incomplete",
            "waveform_instrument_available": False,
            "frequency_only_soak_permitted": False,
            "d6_qualification_only": True,
        },
        "commands": {
            "receiver_commands_permitted": False,
            "dac_writes_permitted": False,
            "fll_arm_permitted": False,
            "hybrid_arm_permitted": False,
            "phase_authority": False,
        },
        "stop_conditions": ["identity_mismatch", "authoritative_capture_degradation"],
        "evidence_destinations": {"future_run_root": "runs/d9_d6_physical_qualification"},
        "verification": {
            "preflight": {"status": "passed", "report": _binding(tmp_path, "preflight.json")},
            "release": {"status": "passed", "report": _binding(tmp_path, "release.json")},
        },
        "rehearsal": {},
        "finalization": {
            "capture": "current_platform_capture",
            "analyzer": "current_platform_analyzer",
            "sealer": "current_platform_sealer",
            "registration": "current_evidence_index",
            "live_run_directory_created": False,
        },
        "authority": {"activation_required": True, "physical_authority": False, "independent_abort_required": True, "automatic_retry_runs": 0},
    }
    rehearsal_draft = {
        key: deepcopy(value)
        for key, value in draft.items()
        if key not in {"terminal", "rehearsal"}
    }
    rehearsal_input = freeze_rehearsal_input(rehearsal_draft)
    rehearsal_path = tmp_path / "rehearsal_input.json"
    rehearsal_path.write_text(
        json.dumps(rehearsal_input, sort_keys=True), encoding="utf-8"
    )
    draft["rehearsal"] = {
        "status": "passed",
        "hardware_operations": False,
        "input_bundle": file_binding(rehearsal_path),
        "input_id": rehearsal_input["input_id"],
        "report": _binding(tmp_path, "rehearsal.json"),
    }
    return draft


def test_schema_is_valid() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "schemas/d9_d6_candidate_bundle_v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)


def test_freeze_is_canonical_exact_and_revalidates_every_bound_artifact(tmp_path: Path) -> None:
    frozen = freeze_candidate(_draft(tmp_path))

    assert frozen["bundle_id"] == canonical_sha256({key: value for key, value in frozen.items() if key != "bundle_id"})
    assert validate_candidate(frozen) == frozen
    assert frozen["contract"]["d9_d6_readiness"] == {
        "contract_id": "OTIS_D9_D6_READINESS_CONTRACT_V1",
        "contract_semantic_sha256": "a6a08d14a03a87b5e0308880c64799baf2e7afecc23cad22d1532f297960de4d",
        "profile": "d9_d6_forwarded_output_no_control",
        "physical_authority": False,
    }


def test_rehearsal_input_freezes_before_a_pass_result_exists(tmp_path: Path) -> None:
    final_draft = _draft(tmp_path)
    rehearsal_path = Path(final_draft["rehearsal"]["input_bundle"]["path"])
    rehearsal_input = json.loads(rehearsal_path.read_text(encoding="utf-8"))

    assert "rehearsal" not in rehearsal_input
    assert "terminal" not in rehearsal_input
    assert validate_rehearsal_input(rehearsal_input) == rehearsal_input
    assert rehearsal_input["input_id"] == final_draft["rehearsal"]["input_id"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value["source_state"].update({"tree_state": "dirty"}), "dirty source"),
        (lambda value: value["firmware_profiles"][2]["configuration"]["defines"].update({"OTIS_ENABLE_FORWARDED_D6_MONITOR": "0"}), "non-effective D9/D6 topology"),
        (lambda value: value["serial"].update({"firmware_host_baud": 9600}), "serial auto-detect/baud"),
        (lambda value: value["scope"].update({"frequency_only_soak_permitted": True}), "no-instrument scope"),
        (lambda value: value["commands"].update({"dac_writes_permitted": True}), "non-actuating command"),
        (lambda value: value["contract"]["d9_d6_readiness"].update({"physical_authority": True}), "schema invalid"),
    ],
)
def test_candidate_rejects_scope_or_identity_drift(tmp_path: Path, mutate, message: str) -> None:
    frozen = freeze_candidate(_draft(tmp_path))
    changed = deepcopy(frozen)
    mutate(changed)
    changed["bundle_id"] = canonical_sha256({key: value for key, value in changed.items() if key != "bundle_id"})

    with pytest.raises(ValueError, match=message):
        validate_candidate(changed)


def test_candidate_rejects_unresolved_placeholder_and_changed_bound_file(tmp_path: Path) -> None:
    frozen = freeze_candidate(_draft(tmp_path))
    unresolved = deepcopy(frozen)
    unresolved["evidence_destinations"] = {"future_run_root": "unbound_pre_candidate_bundle"}
    unresolved["bundle_id"] = canonical_sha256({key: value for key, value in unresolved.items() if key != "bundle_id"})
    with pytest.raises(ValueError, match="unresolved placeholder"):
        validate_candidate(unresolved)

    Path(frozen["host_tools"][0]["path"]).write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="identity differs"):
        validate_candidate(frozen)
