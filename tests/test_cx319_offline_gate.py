from __future__ import annotations

import json
from pathlib import Path

import pytest

from host.otis_tools import cx319_offline_gate
from tools.firmware_matrix import configuration_hash, load_matrix, source_input_hash


def _matrix_summary(tmp_path: Path) -> Path:
    matrix = load_matrix(cx319_offline_gate.MATRIX_PATH)
    profiles = {item["id"]: item for item in matrix["profiles"]}
    source_sha256 = source_input_hash(matrix_path=cx319_offline_gate.MATRIX_PATH)
    manifests: dict[str, str] = {}
    for profile_id in ("cx319_tight_lower", "cx319_tight_upper"):
        manifest = tmp_path / f"{profile_id}.json"
        manifest.write_text(
            json.dumps(
                {
                    "provenance": {
                        "source": {"sha256": source_sha256},
                        "configuration": {
                            "profile_id": profile_id,
                            "sha256": configuration_hash(
                                matrix, profiles[profile_id]
                            ),
                        },
                    },
                    "resource_budget": {"status": "within_budget"},
                }
            ),
            encoding="utf-8",
        )
        manifests[profile_id] = str(manifest)
    path = tmp_path / "matrix_summary.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "all_verified": True,
                "source_state": "dirty",
                "results": [
                    {
                        "profile_id": "cx319_tight_lower",
                        "outcome": "pass",
                        "verified": True,
                        "build_manifest": manifests["cx319_tight_lower"],
                    },
                    {
                        "profile_id": "cx319_tight_upper",
                        "outcome": "pass",
                        "verified": True,
                        "build_manifest": manifests["cx319_tight_upper"],
                    },
                    {
                        "profile_id": "invalid_cx319_lower_parameters",
                        "outcome": "fail",
                        "verified": True,
                        "config_sha256": configuration_hash(
                            matrix, profiles["invalid_cx319_lower_parameters"]
                        ),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _binding(relative_path: str) -> dict[str, str]:
    path = cx319_offline_gate.REPO_ROOT / relative_path
    return {
        "path": relative_path,
        "sha256": cx319_offline_gate._sha256_file(path),
    }


def _replay_reports(tmp_path: Path) -> tuple[Path, Path, Path]:
    corpus = _binding("profiles/replay/cx318_stage2_replay_corpus_v1.json")
    stage2 = tmp_path / "stage2.json"
    stage2.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tool": "cx318_stage2_replay_v1",
                "status": "complete_with_explicit_missing_sources",
                "run_count": 40,
                "status_counts": {
                    "missing_or_inadequate_raw_source": 1,
                    "replayed": 39,
                },
                "corpus": corpus,
                "candidate_profile": _binding(
                    "profiles/estimators/cx318_relative_phase_candidates_v1.json"
                ),
                "authority": {
                    "actionable": False,
                    "actuation_authorized": False,
                    "authorization_consumed": False,
                    "hardware_access": False,
                },
            }
        ),
        encoding="utf-8",
    )
    stage3 = tmp_path / "stage3.json"
    stage3.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tool": "cx318_stage3_hybrid_replay_v1",
                "status": "complete_with_explicit_missing_sources",
                "run_count": 40,
                "status_counts": {
                    "missing_or_inadequate_raw_source": 1,
                    "replayed": 39,
                },
                "corpus": corpus,
                "hybrid_profile": _binding(
                    "profiles/discipline/cx318_hybrid_preview_candidates_v1.json"
                ),
                "authority": {
                    "actionable": False,
                    "actuation_authorized": False,
                    "authorization_consumed": False,
                    "may_write_dac": False,
                },
                "frequency_only_forced_zero_parity": {
                    "exact": True,
                    "mismatch_count": 0,
                    "phase_contribution_forced_hz": 0.0,
                    "observation_count": 151,
                    "sealed_decision_count": 151,
                },
            }
        ),
        encoding="utf-8",
    )
    parity = tmp_path / "parity.json"
    parity.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tool": "cx318_stage4_firmware_parity_v1",
                "status": "passed",
                "corpus": corpus,
                "corpus_membership_matches_accepted_stage2": True,
                "declared_run_count": 40,
                "eligible_run_count": 32,
                "passed_run_count": 32,
                "failed_run_count": 0,
                "expected_missing_or_inadequate_run_count": 1,
                "boundary_count": 353394,
                "compared_record_count": 353394,
                "mismatch_count": 0,
                "profiles": {
                    "phase_selected": _binding(
                        "profiles/estimators/cx318_relative_phase_selected_v1.json"
                    ),
                    "hybrid_selected": _binding(
                        "profiles/discipline/cx318_hybrid_preview_selected_v1.json"
                    ),
                },
                "firmware_sources": {
                    "engine": _binding(
                        "firmware/arduino/otis_nano_rp2040_connect/"
                        "otis_cx318_selected_preview_engine.cpp"
                    ),
                    "harness": _binding(
                        "tests/cpp/cx318_selected_preview_engine_harness.cpp"
                    ),
                    "header": _binding(
                        "firmware/arduino/otis_nano_rp2040_connect/"
                        "otis_cx318_selected_preview_engine.h"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )
    return stage2, stage3, parity


def _evaluate(tmp_path: Path) -> dict[str, object]:
    return cx319_offline_gate.evaluate(
        _matrix_summary(tmp_path),
        *_replay_reports(tmp_path),
    )


def test_g0_gate_crosses_authority_policy_firmware_and_replay(
    tmp_path: Path,
) -> None:
    result = _evaluate(tmp_path)

    assert result["status"] == "passed"
    assert result["mode"] == "offline_no_io"
    assert all(result["checks"].values())
    assert set(result["hardware_operations"].values()) == {0}
    assert result["next_gate"] == (
        "explicit_operator_authorization_for_bench_rehearsal"
    )


def test_g0_gate_rejects_missing_expected_firmware_result(tmp_path: Path) -> None:
    summary = _matrix_summary(tmp_path)
    payload = json.loads(summary.read_text(encoding="utf-8"))
    payload["results"].pop()
    summary.write_text(json.dumps(payload), encoding="utf-8")

    result = cx319_offline_gate.evaluate(summary, *_replay_reports(tmp_path))

    assert result["status"] == "failed"
    assert not result["checks"]["required_profile_set_present_once"]


def test_g0_gate_accepts_other_valid_profiles_from_tier_selection(
    tmp_path: Path,
) -> None:
    summary = _matrix_summary(tmp_path)
    payload = json.loads(summary.read_text(encoding="utf-8"))
    payload["results"].append(
        {
            "profile_id": "synthetic_usb",
            "outcome": "pass",
            "verified": True,
        }
    )
    summary.write_text(json.dumps(payload), encoding="utf-8")

    result = cx319_offline_gate.evaluate(summary, *_replay_reports(tmp_path))

    assert result["status"] == "passed"
    assert result["checks"]["required_profile_set_present_once"]


def test_g0_gate_rejects_hybrid_replay_authority(tmp_path: Path) -> None:
    stage2, stage3, parity = _replay_reports(tmp_path)
    payload = json.loads(stage3.read_text(encoding="utf-8"))
    payload["authority"]["may_write_dac"] = True
    stage3.write_text(json.dumps(payload), encoding="utf-8")

    result = cx319_offline_gate.evaluate(
        _matrix_summary(tmp_path), stage2, stage3, parity
    )

    assert result["status"] == "failed"
    assert not result["checks"]["hybrid_corpus_replay_exact_zero_authority"]


def test_policy_bindings_and_offline_authority_are_exact() -> None:
    policy = cx319_offline_gate.load_policy()

    assert policy["policy_id"] == cx319_offline_gate.POLICY_ID
    assert policy["authority"]["allowed_operation"] == "offline_preparation"
    assert policy["authority"]["hardware_interaction"] is False
    assert policy["phase_and_hybrid_authority"]["actionable"] is False


def test_policy_hash_drift_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    policy = json.loads(cx319_offline_gate.POLICY_PATH.read_text(encoding="utf-8"))
    policy["status"] = "changed"
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    monkeypatch.setattr(cx319_offline_gate, "EXPECTED_POLICY_HASH", "0" * 64)

    with pytest.raises(ValueError, match="identity or status|hash differs"):
        cx319_offline_gate.load_policy(path)
