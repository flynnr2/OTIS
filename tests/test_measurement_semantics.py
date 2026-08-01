from __future__ import annotations

from pathlib import Path
import csv
import shutil
import subprocess
import sys

import pytest

from tools import audit_measurement_semantics

from host.otis_tools.contracts import (
    ESTIMATE_V1_FIELDS,
    ESTIMATE_V2_FIELDS,
    CsvValidationContext,
    validate_csv,
)
from host.otis_tools.uncertainty import (
    evaluate_uncertainty,
)


def _base_row() -> dict[str, str]:
    row = {field: "" for field in ESTIMATE_V2_FIELDS}
    row.update(
        {
            "record_type": "EST",
            "schema_version": "2",
            "estimate_seq": "1",
            "estimate_id": "est:fixture:1",
            "estimator_timestamp_ticks": "100",
            "time_domain": "fixture",
            "source_count_ref": "cnt.csv:CNT:1",
            "source_status_refs": "unavailable:STS",
            "source_dac_ref": "unavailable:DAC",
            "manifest_ref": "manifest.json#sha256:fixture",
            "estimator_version": "fixture",
            "config_hash": "fixture",
            "observation_validity": "valid",
            "observation_reason_codes": "observation_valid",
            "reference_validity": "valid",
            "reference_continuity": "true",
            "count_validity": "valid",
            "count_continuity": "true",
            "diagnostic_health": "healthy",
            "diagnostic_reason_codes": "diagnostic_healthy",
            "accepted_sample_count": "3",
            "estimator_confidence": "high",
            "dispersion_hz": "0",
            "uncertainty_status": "unavailable",
            "uncertainty_reason_codes": "counter_aperture_unavailable",
            "correlation_policy": "not_combined_missing_components",
            "uncertainty_model_ref": "unavailable:uncertainty_model",
            "drift_enabled": "false",
            "preview_eligibility": "false",
            "eligibility_reason_codes": "uncertainty_incomplete",
        }
    )
    return row


def _write(path: Path, row: dict[str, str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ESTIMATE_V2_FIELDS)
        writer.writeheader()
        writer.writerow(row)


def test_zero_dispersion_does_not_imply_zero_uncertainty(tmp_path: Path) -> None:
    path = tmp_path / "estimates_v2.csv"
    _write(path, _base_row())
    result = validate_csv(
        path,
        CsvValidationContext(
            contract="estimates_v2",
            known_channels=frozenset(),
            known_domains=frozenset({"fixture"}),
        ),
    )
    assert result.errors == ()


def test_nonzero_dispersion_is_not_promoted_to_uncertainty(
    tmp_path: Path,
) -> None:
    row = _base_row()
    row["dispersion_hz"] = "0.75"
    row["uncertainty_status"] = "incomplete"
    path = tmp_path / "estimates_v2.csv"
    _write(path, row)
    result = validate_csv(
        path,
        CsvValidationContext(
            contract="estimates_v2",
            known_channels=frozenset(),
            known_domains=frozenset({"fixture"}),
        ),
    )
    assert result.errors == ()
    assert row["combined_standard_uncertainty_hz"] == ""


def test_missing_aperture_and_reference_components_are_explicit() -> None:
    result = evaluate_uncertainty({}, estimate_available=True)
    assert result.status == "incomplete"
    assert "counter_aperture_unavailable" in result.reason_codes
    assert "reference_uncertainty_unavailable" in result.reason_codes
    assert result.combined_standard_uncertainty_hz is None


def test_incomplete_uncertainty_cannot_claim_combined_value(tmp_path: Path) -> None:
    row = _base_row()
    row["combined_standard_uncertainty_hz"] = "0"
    path = tmp_path / "estimates_v2.csv"
    _write(path, row)
    result = validate_csv(
        path,
        CsvValidationContext(
            contract="estimates_v2",
            known_channels=frozenset(),
            known_domains=frozenset({"fixture"}),
        ),
    )
    assert any(
        "incomplete or unavailable uncertainty must not claim a combined value"
        in error
        for error in result.errors
    )


def test_quantization_only_complete_case_is_explicit(tmp_path: Path) -> None:
    row = _base_row()
    row.update(
        {
            "uncertainty_status": "available",
            "uncertainty_reason_codes": "uncertainty_complete",
            "count_quantization_standard_uncertainty_hz": "0.288675",
            "combined_standard_uncertainty_hz": "0.288675",
            "correlation_policy": "single_component_no_correlation",
            "uncertainty_model_ref": "fixture:quantization_only_v1",
        }
    )
    path = tmp_path / "estimates_v2.csv"
    _write(path, row)
    result = validate_csv(
        path,
        CsvValidationContext(
            contract="estimates_v2",
            known_channels=frozenset(),
            known_domains=frozenset({"fixture"}),
        ),
    )
    assert result.errors == ()


def test_quantization_only_budget_is_calculated_by_versioned_policy() -> None:
    result = evaluate_uncertainty(
        {"count_quantization_standard_uncertainty_hz": 0.5},
        estimate_available=True,
        required_components=("count_quantization_standard_uncertainty_hz",),
    )
    assert result.status == "available"
    assert result.combined_standard_uncertainty_hz == 0.5
    assert result.correlation_policy == "single_component_no_correlation"
    assert result.model_ref.startswith(
        "phase4_uncertainty_budget_v1#sha256:"
    )


def test_independent_components_use_root_sum_square() -> None:
    result = evaluate_uncertainty(
        {
            "count_quantization_standard_uncertainty_hz": 3.0,
            "reference_standard_uncertainty_hz": 4.0,
        },
        estimate_available=True,
        required_components=(
            "count_quantization_standard_uncertainty_hz",
            "reference_standard_uncertainty_hz",
        ),
        coverage_factor=2.0,
    )
    assert result.status == "available"
    assert result.combined_standard_uncertainty_hz == 5.0
    assert result.expanded_uncertainty_hz == 10.0
    assert result.correlation_policy == "independent_root_sum_square"


def test_contract_rejects_unimplemented_correlation_policy(
    tmp_path: Path,
) -> None:
    row = _base_row()
    row.update(
        {
            "uncertainty_status": "available",
            "uncertainty_reason_codes": "uncertainty_complete",
            "count_quantization_standard_uncertainty_hz": "3",
            "reference_standard_uncertainty_hz": "4",
            "combined_standard_uncertainty_hz": "7",
            "correlation_policy": "fully_correlated",
            "uncertainty_model_ref": "fixture:correlated_v1",
        }
    )
    path = tmp_path / "estimates_v2.csv"
    _write(path, row)
    result = validate_csv(
        path,
        CsvValidationContext(
            contract="estimates_v2",
            known_channels=frozenset(),
            known_domains=frozenset({"fixture"}),
        ),
    )
    assert any("correlation_policy must be one of" in error for error in result.errors)


def test_historical_estimate_v1_remains_readable_without_reinterpretation(
    tmp_path: Path,
) -> None:
    source = _base_row()
    row = {field: source.get(field, "") for field in ESTIMATE_V1_FIELDS}
    row["schema_version"] = "1"
    row["frequency_uncertainty_hz"] = row["dispersion_hz"]
    path = tmp_path / "estimates_v1.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ESTIMATE_V1_FIELDS)
        writer.writeheader()
        writer.writerow(row)
    result = validate_csv(
        path,
        CsvValidationContext(
            contract="estimates_v1",
            known_channels=frozenset(),
            known_domains=frozenset({"fixture"}),
        ),
    )
    assert result.errors == ()


def test_repository_wide_measurement_semantics_inventory_is_current() -> None:
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            sys.executable,
            str(root / "tools" / "audit_measurement_semantics.py"),
            "--check",
        ],
        check=True,
        cwd=root,
    )


def test_measurement_inventory_respects_git_ignores(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is unavailable")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text(
        "runs/\n*.egg-info/\n", encoding="utf-8"
    )
    (tmp_path / "tracked.md").write_text(
        "measurement uncertainty\n", encoding="utf-8"
    )
    (tmp_path / "host").mkdir()
    (tmp_path / "host" / "new.md").write_text(
        "measurement confidence\n", encoding="utf-8"
    )
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "capture.md").write_text(
        "ignored uncertainty\n", encoding="utf-8"
    )
    (tmp_path / "otis.egg-info").mkdir()
    (tmp_path / "otis.egg-info" / "SOURCES.txt").write_text(
        "ignored confidence\n", encoding="utf-8"
    )
    subprocess.run(
        ["git", "add", ".gitignore", "tracked.md"], cwd=tmp_path, check=True
    )

    inventory = audit_measurement_semantics.inventory_bytes(tmp_path).decode()

    assert "tracked.md" in inventory
    assert "host/new.md" in inventory
    assert "runs/capture.md" not in inventory
    assert "otis.egg-info/SOURCES.txt" not in inventory
