from __future__ import annotations

import csv
from pathlib import Path

from host.otis_tools.capture_serial import CsvRecordSplitter
from host.otis_tools.adaptive_hybrid_monitor import _exact_record_progress
from host.otis_tools.contracts import (
    ACTIVE_HYBRID_DECISION_V2_FIELDS,
    CsvValidationContext,
    validate_csv,
)
from host.otis_tools.firmware_host_contract import RECORD_FIELDS


ROOT = Path(__file__).resolve().parents[1]
SHA256 = "a" * 64


def _row() -> dict[str, str]:
    values = {field: "0" for field in ACTIVE_HYBRID_DECISION_V2_FIELDS}
    values.update(
        {
            "record_type": "AHY",
            "schema_version": "2",
            "hybrid_record_sequence": "1",
            "decision_sequence": "1",
            "decision_timestamp_ticks": "3600000000",
            "time_domain": "rp2040_monotonic_us64",
            "decision_timestamp_s": "3600",
            "run_identity": "adaptive_hybrid_regulation:1",
            "build_identity": f"{SHA256}:{SHA256}",
            "image_identity": "adaptive_hybrid_regulation",
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
            "reason": "phase_material_ordinary_request_ready",
            "active_policy_sha256": SHA256,
            "response_policy_sha256": SHA256,
            "actionable": "false",
        }
    )
    return values


def _write(path: Path, row: dict[str, str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ACTIVE_HYBRID_DECISION_V2_FIELDS)
        writer.writeheader()
        writer.writerow(row)


def test_active_hybrid_contract_validates_materiality_and_epoch_propagation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "active_hybrid_decisions_v2.csv"
    row = _row()
    _write(path, row)
    context = CsvValidationContext(
        "active_hybrid_decisions_v2", frozenset(), frozenset()
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


def test_current_policy_uses_exact_integer_materiality_and_defers_holds_to_ahm(
    tmp_path: Path,
) -> None:
    path = tmp_path / "active_hybrid_decisions_v2.csv"
    context = CsvValidationContext(
        "active_hybrid_decisions_v2", frozenset(), frozenset()
    )
    row = _row()
    row.update(
        {
            "image_identity": "adaptive_hybrid_regulation",
            "reason": "phase_material_ordinary_request_ready",
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
        / "firmware/arduino/otis_nano_rp2040_connect/otis_adaptive_hybrid_regulation_live.cpp"
    ).read_text(encoding="utf-8")
    assert "OTIS_CONTRACT_ACTIVE_HYBRID_DECISIONS_V2_HEADER" in source
    assert RECORD_FIELDS["active_hybrid_decisions_v2"] == tuple(
        ACTIVE_HYBRID_DECISION_V2_FIELDS
    )

    target = tmp_path / "active_hybrid_decisions_v2.csv"
    with CsvRecordSplitter({"active_hybrid_decisions_v2": target}) as splitter:
        line = ",".join(_row()[field] for field in ACTIVE_HYBRID_DECISION_V2_FIELDS)
        assert splitter.process_line(line) == "active_hybrid_decisions_v2"
    assert target.read_text(encoding="utf-8").splitlines()[0] == ",".join(
        ACTIVE_HYBRID_DECISION_V2_FIELDS
    )


def test_active_hybrid_contract_rejects_missing_coarse_unknown_and_backward_timing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "active_hybrid_decisions_v2.csv"

    def errors_for(rows: list[dict[str, str]]) -> str:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=ACTIVE_HYBRID_DECISION_V2_FIELDS
            )
            writer.writeheader()
            writer.writerows(rows)
        return " ".join(
            validate_csv(
                path,
                CsvValidationContext(
                    "active_hybrid_decisions_v2", frozenset(), frozenset()
                ),
            ).errors
        )

    missing = _row()
    missing["decision_timestamp_ticks"] = ""
    assert "decision_timestamp_ticks" in errors_for([missing])

    coarse = _row()
    coarse["schema_version"] = "1"
    assert "unsupported schema_version 1" in errors_for([coarse])

    unknown = _row()
    unknown["time_domain"] = "controller_seconds"
    assert "unsupported timestamp domain" in errors_for([unknown])

    first = _row()
    second = _row()
    second["hybrid_record_sequence"] = "2"
    second["decision_sequence"] = "2"
    second["decision_timestamp_ticks"] = str(
        int(first["decision_timestamp_ticks"]) - 1
    )
    assert "violates rp2040_monotonic_us64 progression" in errors_for(
        [first, second]
    )


def test_monitor_reads_exact_ahy_timing_directly() -> None:
    first = _row()
    second = _row()
    second["hybrid_record_sequence"] = "2"
    second["decision_sequence"] = "2"
    second["decision_timestamp_ticks"] = str(
        int(first["decision_timestamp_ticks"]) + 1
    )
    progress = _exact_record_progress(
        rows=[first, second],
        sequence_field="hybrid_record_sequence",
        timestamp_field="decision_timestamp_ticks",
        record_type="AHY",
        age_s=0.0,
    )
    assert progress["mismatches"] == []
    assert progress["latest"] == {
        "hybrid_record_sequence": "2",
        "decision_timestamp_ticks": second["decision_timestamp_ticks"],
        "time_domain": "rp2040_monotonic_us64",
    }

    second["decision_timestamp_ticks"] = str(
        int(first["decision_timestamp_ticks"]) - 1
    )
    progress = _exact_record_progress(
        rows=[first, second],
        sequence_field="hybrid_record_sequence",
        timestamp_field="decision_timestamp_ticks",
        record_type="AHY",
        age_s=0.0,
    )
    assert progress["mismatches"] == ["AHY row 2 identity differs"]
