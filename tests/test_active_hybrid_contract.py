from __future__ import annotations

import csv
import re
from pathlib import Path

from host.otis_tools.capture_serial import CsvRecordSplitter
from host.otis_tools.contracts import (
    ACTIVE_HYBRID_DECISION_V1_FIELDS,
    CsvValidationContext,
    validate_csv,
)


ROOT = Path(__file__).resolve().parents[1]
SHA256 = "a" * 64


def _row() -> dict[str, str]:
    values = {field: "0" for field in ACTIVE_HYBRID_DECISION_V1_FIELDS}
    values.update(
        {
            "record_type": "AHY",
            "schema_version": "1",
            "hybrid_record_sequence": "1",
            "decision_sequence": "1",
            "decision_timestamp_s": "3600",
            "run_identity": "cx320_active_hybrid:3200001",
            "build_identity": f"{SHA256}:{SHA256}",
            "profile_identity": "cx320_active_hybrid",
            "capture_session": "1",
            "source_first_sequence": "3001",
            "source_last_sequence": "3600",
            "frequency_estimator_sha256": SHA256,
            "frequency_error_hz": "0.000000000000",
            "accumulated_edge_error_counts": "0",
            "tight_state": "TIGHT_INSIDE",
            "phase_estimator_sha256": SHA256,
            "phase_epoch": "1",
            "phase_observation_sequence": "3600",
            "relative_phase_cycles": "-24",
            "phase_continuous": "true",
            "phase_current": "true",
            "phase_step_detected": "false",
            "phase_recorder_published": "true",
            "current_applied_code": "43068",
            "dac_epoch": "1",
            "phase_applied_code": "43068",
            "phase_dac_epoch": "1",
            "state_before": "PHASE_QUALIFY",
            "state_after": "PHASE_QUALIFY",
            "frequency_term_hz": "0.000000000000",
            "phase_term_hz": "0.001111111111",
            "combined_demand_hz": "0.001111111111",
            "raw_combined_delta_codes": "3.205003078496",
            "requested_delta_codes": "3",
            "requested_code": "43071",
            "counterfactual_frequency_only_delta_codes": "0",
            "phase_materially_influenced": "true",
            "step_limited": "false",
            "range_clamped": "false",
            "cadence_limited": "false",
            "count_limited": "false",
            "cumulative_budget_limited": "false",
            "correction_count_before": "0",
            "cumulative_movement_before_codes": "0",
            "authority_state": "DISARMED",
            "request_sequence": "0",
            "acceptance_sequence": "0",
            "application_sequence": "0",
            "response_class": "unavailable",
            "actual_applied_code": "43068",
            "actual_dac_epoch": "1",
            "downstream_epoch_exact": "true",
            "reason": "phase_material_request_ready",
            "active_policy_sha256": SHA256,
            "response_policy_sha256": SHA256,
            "actionable": "false",
        }
    )
    return values


def _write(path: Path, row: dict[str, str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ACTIVE_HYBRID_DECISION_V1_FIELDS)
        writer.writeheader()
        writer.writerow(row)


def test_active_hybrid_contract_validates_materiality_and_epoch_propagation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "active_hybrid_decisions_v1.csv"
    row = _row()
    _write(path, row)
    context = CsvValidationContext(
        "active_hybrid_decisions_v1", frozenset(), frozenset()
    )
    assert validate_csv(path, context).ok

    row["phase_materially_influenced"] = "false"
    _write(path, row)
    result = validate_csv(path, context)
    assert not result.ok
    assert "phase materiality counterfactual differs" in " ".join(result.errors)

    row["phase_materially_influenced"] = "true"
    row["downstream_epoch_exact"] = "false"
    _write(path, row)
    result = validate_csv(path, context)
    assert not result.ok
    assert "lacks exact downstream DAC epoch" in " ".join(result.errors)


def test_deliberate_challenge_is_physical_but_not_phase_materiality(
    tmp_path: Path,
) -> None:
    path = tmp_path / "active_hybrid_decisions_v1.csv"
    row = _row()
    row.update(
        {
            "requested_delta_codes": "-21",
            "requested_code": "43047",
            "phase_materially_influenced": "false",
            "reason": "deliberate_reversal_challenge_request_ready",
        }
    )
    _write(path, row)
    context = CsvValidationContext(
        "active_hybrid_decisions_v1", frozenset(), frozenset()
    )

    assert validate_csv(path, context).ok

    row["phase_materially_influenced"] = "true"
    _write(path, row)
    result = validate_csv(path, context)
    assert not result.ok
    assert "phase materiality counterfactual differs" in " ".join(result.errors)


def test_cx323_uses_integer_legacy_materiality_and_defers_lossy_holds_to_ahm(
    tmp_path: Path,
) -> None:
    path = tmp_path / "active_hybrid_decisions_v1.csv"
    context = CsvValidationContext(
        "active_hybrid_decisions_v1", frozenset(), frozenset()
    )
    row = _row()
    row.update(
        {
            "profile_identity": "cx323_d9_d6_72h_adaptive_hybrid",
            "reason": "phase_material_legacy_request_ready",
            "frequency_term_hz": "0.000000000000",
            "phase_term_hz": "0.000000000000",
            "combined_demand_hz": "0.000000000000",
            "raw_combined_delta_codes": "0.000000000000",
            "requested_delta_codes": "6",
            "requested_code": str(int(row["current_applied_code"]) + 6),
            "counterfactual_frequency_only_delta_codes": "5",
            "phase_materially_influenced": "true",
        }
    )
    _write(path, row)
    assert validate_csv(path, context).ok

    row["phase_materially_influenced"] = "false"
    _write(path, row)
    result = validate_csv(path, context)
    assert not result.ok
    assert "phase materiality counterfactual differs" in " ".join(result.errors)

    row.update(
        {
            "reason": "maintenance_request_ready",
            "raw_combined_delta_codes": "-4.807504602373",
            "requested_delta_codes": "-4",
            "requested_code": str(int(row["current_applied_code"]) - 4),
            "counterfactual_frequency_only_delta_codes": "-5",
            "phase_materially_influenced": "false",
        }
    )
    _write(path, row)
    assert validate_csv(path, context).ok

    row["phase_materially_influenced"] = "true"
    _write(path, row)
    result = validate_csv(path, context)
    assert not result.ok
    assert "phase materiality counterfactual differs" in " ".join(result.errors)


def test_firmware_header_and_capture_splitter_use_the_exact_contract(
    tmp_path: Path,
) -> None:
    source = (
        ROOT
        / "firmware/arduino/otis_nano_rp2040_connect/otis_cx317_active_live.cpp"
    ).read_text(encoding="utf-8")
    match = re.search(r'"record_type,schema_version,hybrid_record_sequence[^\"]+', source)
    assert match is not None
    assert match.group(0)[1:].removesuffix(r"\r\n").split(",") == (
        ACTIVE_HYBRID_DECISION_V1_FIELDS
    )

    target = tmp_path / "active_hybrid_decisions_v1.csv"
    with CsvRecordSplitter({"active_hybrid_decisions_v1": target}) as splitter:
        line = ",".join(_row()[field] for field in ACTIVE_HYBRID_DECISION_V1_FIELDS)
        assert splitter.process_line(line) == "active_hybrid_decisions_v1"
    assert target.read_text(encoding="utf-8").splitlines()[0] == ",".join(
        ACTIVE_HYBRID_DECISION_V1_FIELDS
    )
