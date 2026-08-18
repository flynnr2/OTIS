from __future__ import annotations

import json
from pathlib import Path

import pytest

from host.otis_tools import cx319_part_b_programme_seal as sealer
from host.otis_tools.range_spanning_bundle import canonical_sha256, sha256_file


def _inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    readiness_path = tmp_path / "readiness.json"
    readiness_path.write_text("{}", encoding="utf-8")
    lower_path = tmp_path / "lower.json"
    lower = {
        "status": "passed",
        "scientific_outcome": "required_direction_qualification_passed",
        "terminal": {"result": "healthy_stop"},
        "transactions": {
            "application_count": 2,
            "response_count": 2,
            "healthy_required_direction_count": 2,
        },
        "tight_entry_transition_count": 1,
    }
    lower_path.write_text(json.dumps(lower), encoding="utf-8")
    upper_path = tmp_path / "upper.json"
    upper_path.write_text("{}", encoding="utf-8")
    completion_path = tmp_path / "completion.json"
    completion_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        sealer,
        "validate_readiness_record",
        lambda path: {
            "readiness_sha256": "1" * 64,
            "mapping_evaluation": {
                "failures": [],
                "transitions": {
                    "lower_outbound": {
                        "basis": "observed_mixed_code_distribution",
                        "transition_width_codes": 4,
                    },
                    "lower_return": {
                        "basis": "observed_mixed_code_distribution",
                        "transition_width_codes": 4,
                    },
                },
                "directional_displacement": {"lower": {"passed": True}},
                "part_b_reachability": {"lower": {"passed": True}},
            },
        },
    )
    monkeypatch.setattr(
        sealer,
        "_validate_upper_completion_predecessor",
        lambda path: {
            "seal_sha256": "2" * 64,
            "lower_pass": {
                "path": str(lower_path),
                "file_sha256": sha256_file(lower_path),
                "seal_sha256": "3" * 64,
                "evidence_snapshot": {},
            },
        },
    )
    monkeypatch.setattr(
        sealer,
        "_validate_lower_reacquisition_predecessor",
        lambda path: {
            "seal_sha256": "4" * 64,
            "predecessor_leg_seal_sha256": "2" * 64,
        },
    )
    monkeypatch.setattr(sealer, "_git_identity", lambda: ("5" * 40, "clean"))
    return readiness_path, upper_path, completion_path


def test_seals_observed_results_and_explicit_inferred_reacquisition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness, upper, completion = _inputs(tmp_path, monkeypatch)
    output = tmp_path / "programme_seal.json"

    value = sealer.create_programme_seal(
        mapping_readiness_path=readiness,
        upper_path=upper,
        upper_completion_path=completion,
        output_path=output,
        created_utc="2026-08-18T00:00:00Z",
    )

    assert value["status"] == "passed"
    assert value["lower_reacquisition"]["disposition"] == "inferred_pass"
    assert value["lower_reacquisition"]["physical_acquisition_performed"] is False
    assert value["authority"]["additional_physical_leg_required_for_this_decision"] is False
    assert "must not be cited as three independently observed" in value["claims_boundary"]
    unsigned = {key: item for key, item in value.items() if key != "seal_sha256"}
    assert value["seal_sha256"] == canonical_sha256(unsigned)


def test_rejects_completion_not_bound_to_original_upper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness, upper, completion = _inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(
        sealer,
        "_validate_lower_reacquisition_predecessor",
        lambda path: {"predecessor_leg_seal_sha256": "9" * 64},
    )

    with pytest.raises(ValueError, match="exact right-censored upper"):
        sealer.create_programme_seal(
            mapping_readiness_path=readiness,
            upper_path=upper,
            upper_completion_path=completion,
            output_path=tmp_path / "programme_seal.json",
        )
