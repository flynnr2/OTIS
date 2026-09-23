"""Independent current CSV validation for raw timing and derived records."""
from __future__ import annotations

import csv
from typing import Any

from .contracts import CsvValidationContext, validate_csv


def validate_manifest_csvs(manifest, *, expected_policy_sha256: str | None = None) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for item in manifest.files:
        contract = item.get("contract")
        path = manifest.root / str(item.get("path", ""))
        if not isinstance(contract, str) or path.suffix.lower() != ".csv":
            continue
        if not path.is_file() and item.get("optional") is True:
            continue
        record_type = item.get("record_type")
        label = f"{contract}:{record_type}" if isinstance(record_type, str) else contract
        fail_local = contract == "raw_events_v1" and record_type == "EVT"
        try:
            validation = validate_csv(path, CsvValidationContext(
                contract, manifest.known_channels, manifest.known_domains,
                expected_policy_sha256=expected_policy_sha256,
            ))
            row_count = validation.row_count
            errors = list(validation.errors)
            warnings = list(validation.warnings)
            exact = validation.ok
        except (OSError, UnicodeError, csv.Error) as error:
            if not fail_local:
                raise
            row_count = 0
            errors = [f"fail-local D10 validation error: {type(error).__name__}: {error}"]
            warnings = []
            exact = False
        results[label] = {
            "contract": contract, "record_type": record_type,
            "path": str(path.relative_to(manifest.root)), "row_count": row_count,
            "errors": errors, "warnings": warnings, "exact": exact,
            "authority": "fail_local" if fail_local else "authoritative",
        }
    return results


def authoritative_csvs_exact(results: dict[str, Any]) -> bool:
    authoritative = [item for item in results.values() if item.get("authority") == "authoritative"]
    return bool(authoritative) and all(item.get("exact") is True for item in authoritative)


def d10_isolated(section: dict[str, Any], measurement: dict[str, Any]) -> bool:
    d10 = section.get("external_event_input", {})
    return (
        d10.get("pin") == "D10"
        and d10.get("authority") == "evidence_only"
        and d10.get("control_eligible") is False
        and d10.get("terminal_eligible") is False
        and measurement.get("D10", {}).get("enters_D14_D8_replay") is not True
    )
