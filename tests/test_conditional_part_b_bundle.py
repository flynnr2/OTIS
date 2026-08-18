from __future__ import annotations

import json
from pathlib import Path

import pytest

from host.otis_tools import conditional_part_b_bundle
from host.otis_tools.range_spanning_bundle import canonical_sha256, sha256_file


def _write_seal(path: Path, unsigned: dict[str, object]) -> dict[str, object]:
    value = {**unsigned, "seal_sha256": canonical_sha256(unsigned)}
    path.write_text(json.dumps(value), encoding="utf-8")
    return value


def test_lower_reacquisition_accepts_exact_passed_upper_completion(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence_manifest.json"
    evidence.write_text("{}", encoding="utf-8")
    old = tmp_path / "old.json"
    _write_seal(
        old,
        {"status": "bounded_nonpass", "tool_sha256": "1" * 64},
    )
    path = tmp_path / "completion.json"
    checks = {
        "accepted_outcome_path_exact": True,
        "mapping_target_stable_tight_hold_without_correction_demonstrated": True,
    }
    seal = _write_seal(
        path,
        {
            "status": "passed",
            "programme_id": conditional_part_b_bundle.UPPER_COMPLETION_PROGRAMME_ID,
            "gate": "PBUC",
            "leg": "C",
            "sequence_index": 4,
            "acceptance_path": "mapping_target_stable_tight_hold_without_correction",
            "scientific_outcome": "stimulus_nonactionable_stable_tight_hold",
            "terminal": {
                "result": "aborted",
                "reason": "stage5_finite_qualified_endpoint_nonpass",
            },
            "terminal_abort_delivery": {"exact": True},
            "checks": checks,
            "transactions": {"application_count": 0, "response_count": 0},
            "tight_entry_transition_count": 1,
            "analysis_supersession": {
                "raw_acquisition_unchanged": True,
                "physical_rerun": False,
                "superseded_status": "bounded_nonpass",
                "superseded_seal_path": str(old),
                "superseded_seal_file_sha256": sha256_file(old),
            },
            "evidence_snapshot": {
                "path": str(evidence),
                "sha256": sha256_file(evidence),
            },
            "run": {"path": "/retained/completion"},
            "predecessor_leg_seal_sha256": "2" * 64,
        },
    )

    binding = conditional_part_b_bundle._validate_lower_reacquisition_predecessor(
        path
    )

    assert binding["seal_sha256"] == seal["seal_sha256"]
    assert binding["acceptance_path"] == (
        "mapping_target_stable_tight_hold_without_correction"
    )


def test_lower_reacquisition_rejects_unlinked_completion_replay(
    tmp_path: Path,
) -> None:
    path = tmp_path / "completion.json"
    _write_seal(
        path,
        {
            "status": "passed",
            "programme_id": conditional_part_b_bundle.UPPER_COMPLETION_PROGRAMME_ID,
            "gate": "PBUC",
            "leg": "C",
            "sequence_index": 4,
        },
    )

    with pytest.raises(ValueError, match="exact passed upper-completion"):
        conditional_part_b_bundle._validate_lower_reacquisition_predecessor(path)
