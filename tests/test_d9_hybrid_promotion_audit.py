from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from host.otis_tools import d9_hybrid_promotion_audit as audit


ROOT = Path(__file__).resolve().parents[1]
REVISION = "f" * 40


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _build_manifests(tmp_path: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for profile_id in audit.REQUIRED_BUILD_PROFILES:
        result[profile_id] = _write_json(
            tmp_path / f"{profile_id}.json",
            {
                "schema_version": 1,
                "provenance": {
                    "configuration": {
                        "profile_id": profile_id,
                        "sha256": profile_id.encode().hex().ljust(64, "0")[:64],
                    },
                    "source": {
                        "git_commit": REVISION,
                        "state": "clean",
                        "sha256": "a" * 64,
                    },
                },
                "artifacts": [
                    {
                        "name": "otis_nano_rp2040_connect.ino.elf",
                        "sha256": "b" * 64,
                    },
                    {
                        "name": "otis_nano_rp2040_connect.ino.uf2",
                        "sha256": "c" * 64,
                    },
                ],
            },
        )
    return result


def _rehearsal(tmp_path: Path) -> Path:
    return _write_json(
        tmp_path / "operational_rehearsal_result_v1.json",
        {
            "status": "passed",
            "input_id": audit.EXPECTED_REHEARSAL_INPUT,
            "physical_actions_performed": 0,
            "qualification_evidence": False,
            "registration_valid": True,
            "seal_sha256": "d" * 64,
        },
    )


def _audit(tmp_path: Path, **changes: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "build_manifest_paths": _build_manifests(tmp_path),
        "retained_rehearsal_path": _rehearsal(tmp_path),
        "source_identity": (REVISION, True, []),
    }
    arguments.update(changes)
    return audit.audit(**arguments)


def test_exact_audit_closes_only_the_non_effective_blocked_terminal(
    tmp_path: Path,
) -> None:
    report = _audit(tmp_path)

    assert report["terminal"] == (
        "non_effective_semantics_verified_promotion_blocked_by_d9_gate"
    )
    assert report["effective"] is False
    assert report["physical_authority"] is False
    assert report["trial_proposal_created"] is False
    assert report["profile_separation"] == {
        "non_actuating_d9_d6": "d9_d6_forwarded_output_no_control",
        "compile_only_unqualified_frequency_control": "d9_d6_frequency_only_lower",
        "retained_standalone_cx322": "cx322_direct_hybrid",
        "combined_d9_d6_cx322_profile_exists": False,
    }
    assert report["blocking_evidence"] == [
        "no_oscilloscope_or_independently_referenced_frequency_counter_"
        "waveform_and_load_evidence",
        "D9_waveform_and_qualified_load_gate_not_passed",
    ]
    assert set(report["builds"]) == set(audit.REQUIRED_BUILD_PROFILES)


def test_audit_rejects_dirty_or_incomplete_exact_candidate(tmp_path: Path) -> None:
    manifests = _build_manifests(tmp_path)
    rehearsal = _rehearsal(tmp_path)
    with pytest.raises(ValueError, match="source is dirty"):
        audit.audit(
            build_manifest_paths=manifests,
            retained_rehearsal_path=rehearsal,
            source_identity=(REVISION, False, [" M tracked.py"]),
        )
    manifests.pop("cx322_direct_hybrid")
    with pytest.raises(ValueError, match="all three exact separated"):
        audit.audit(
            build_manifest_paths=manifests,
            retained_rehearsal_path=rehearsal,
            source_identity=(REVISION, True, []),
        )


def test_audit_rejects_any_combined_d9_cx322_matrix_profile(
    tmp_path: Path,
) -> None:
    matrix = json.loads(audit.FIRMWARE_MATRIX.read_text(encoding="utf-8"))
    mutated = deepcopy(matrix)
    profile = next(
        value for value in mutated["profiles"] if value["id"] == "cx322_direct_hybrid"
    )
    profile["defines"]["OTIS_ENABLE_FORWARDED_D9_OUTPUT"] = "1"
    matrix_path = _write_json(tmp_path / "matrix.json", mutated)

    with pytest.raises(ValueError, match="profile separation differs"):
        _audit(tmp_path, firmware_matrix_path=matrix_path)


def test_audit_rejects_prompt03_authority_or_terminal_mutation(
    tmp_path: Path,
) -> None:
    contract = json.loads(audit.PROMPT03_CONTRACT.read_text(encoding="utf-8"))
    contract["authority"]["hybrid_arm"] = True
    unsigned = {
        key: value for key, value in contract.items() if key != "contract_semantic_sha256"
    }
    contract["contract_semantic_sha256"] = audit._canonical_sha256(unsigned)
    contract_path = _write_json(tmp_path / "prompt03.json", contract)

    with pytest.raises(ValueError, match="entry, terminal, or authority differs"):
        _audit(tmp_path, prompt03_contract_path=contract_path)


def test_audit_rejects_active_frequency_profile_mislabeled_non_actuating(
    tmp_path: Path,
) -> None:
    report = _audit(tmp_path)
    assert report["builds"]["d9_d6_frequency_only_lower"]["authority_class"] == (
        "compile_only_unqualified_frequency_control"
    )
    assert report["builds"]["d9_d6_forwarded_output_no_control"][
        "authority_class"
    ] == "non_actuating_D9_D6"
