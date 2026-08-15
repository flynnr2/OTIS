from __future__ import annotations

from pathlib import Path
import csv

from host.otis_tools.capture_serial import CsvRecordSplitter
from host.otis_tools.contracts import CONTRACT_FIELDS, CsvValidationContext, validate_csv
from host.otis_tools.run_paths import default_csv_files


SHA256 = "a" * 64


def _write_contract(path: Path, contract: str, values: dict[str, str]) -> None:
    fields = CONTRACT_FIELDS[contract]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({field: values.get(field, "") for field in fields})


def test_phase_preview_contracts_validate_and_remain_non_actionable(
    tmp_path: Path,
) -> None:
    rph_path = tmp_path / "relative_phase_observations_v1.csv"
    _write_contract(
        rph_path,
        "relative_phase_observations_v1",
        {
            "record_type": "RPH",
            "schema_version": "1",
            "phase_epoch": "1",
            "observation_sequence": "1",
            "capture_session": "4",
            "opening_snapshot_sequence": "101",
            "closing_snapshot_sequence": "102",
            "opening_reference_sequence": "201",
            "closing_reference_sequence": "202",
            "dac_epoch": "3",
            "source_backend": "pio_wait_cumulative_snapshot_dma_v1",
            "source_file_sha256": "live_stream_unsealed",
            "method_id": "CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1",
            "configuration_sha256": SHA256,
            "interval_edges": "10000001",
            "edge_error_cycles": "1",
            "relative_phase_cycles": "1",
            "relative_phase_time_ns": "100",
            "qualification_state": "qualified",
            "observation_age_s": "0",
            "calibrated_uncertainty_status": "unavailable",
        },
    )
    phe_path = tmp_path / "phase_estimator_outputs_v1.csv"
    _write_contract(
        phe_path,
        "phase_estimator_outputs_v1",
        {
            "record_type": "PHE",
            "schema_version": "1",
            "phase_epoch": "1",
            "observation_sequence": "1",
            "source_relative_phase_observation": "RPH:1:1",
            "raw_relative_phase_cycles": "1",
            "raw_relative_phase_time_ns": "100",
            "filtered_relative_phase_cycles": "1",
            "estimated_frequency_error_hz": "0.00166666666666667",
            "estimator_id": "CX318_RELATIVE_PHASE_RAW_PLUS_SELECTED600_V1",
            "configuration_sha256": SHA256,
            "estimate_age_s": "0",
            "qualification_state": "qualified",
            "uncertainty_status": "unavailable",
            "reason_codes": "selected_600_interval_frequency_fresh",
        },
    )
    hpr_path = tmp_path / "hybrid_preview_decisions_v1.csv"
    _write_contract(
        hpr_path,
        "hybrid_preview_decisions_v1",
        {
            "record_type": "HPR",
            "schema_version": "1",
            "preview_sequence": "1",
            "candidate_id": "p21600_cap1_v2",
            "candidate_configuration_sha256": SHA256,
            "phase_estimator_id": "CX318_RELATIVE_PHASE_RAW_PLUS_SELECTED600_V1",
            "phase_estimator_configuration_sha256": SHA256,
            "frequency_estimator_id": "cx317_selected_600s_nonoverlap_v1",
            "frequency_estimator_configuration_sha256": SHA256,
            "configuration_sha256": SHA256,
            "phase_epoch": "1",
            "observation_sequence": "1",
            "dac_epoch": "3",
            "decision_timestamp_ticks": "16000000",
            "time_domain": "rp2040_timer0",
            "source_phase_estimate": "PHE:1:1",
            "source_frequency_estimate": "PHE:1:1",
            "raw_relative_phase_cycles": "1",
            "modeled_relative_phase_cycles": "0.5",
            "observed_frequency_error_hz": "0.001",
            "modeled_frequency_error_hz": "0.0011",
            "frequency_term_hz": "-0.001",
            "phase_bias_hz": "-0.0001",
            "combined_frequency_error_hz": "-0.0011",
            "actual_applied_code": "43001",
            "shadow_code_before": "43001",
            "shadow_code_after": "43000",
            "band_state_before": "OUTSIDE",
            "band_state_after": "INSIDE",
            "frequency_observation_event": "true",
            "counterfactual_decision": "true",
            "counterfactual_correction": "true",
            "raw_counterfactual_delta_codes": "-1.25",
            "counterfactual_delta_codes": "-1",
            "counterfactual_code": "43000",
            "step_limited": "false",
            "range_clamped": "false",
            "correction_count": "1",
            "cumulative_movement_codes": "1",
            "alternating_correction_count": "0",
            "modeled_not_observed_after_divergence": "true",
            "preview_state": "HYBRID_TRACKING_PREVIEW",
            "decision_reason": "preview_available_observe_only",
            "uncertainty_status": "unavailable",
            "actionable": "false",
            "actuation_authorized": "false",
            "authorization_consumed": "false",
        },
    )

    context = CsvValidationContext(
        contract="relative_phase_observations_v1",
        known_channels=frozenset(),
        known_domains=frozenset(),
    )
    assert validate_csv(rph_path, context).ok
    rph_rows = list(csv.DictReader(rph_path.open(encoding="utf-8")))
    rph_rows[0]["source_file_sha256"] = "not_a_source_identity"
    _write_contract(rph_path, "relative_phase_observations_v1", rph_rows[0])
    result = validate_csv(rph_path, context)
    assert not result.ok
    assert "source_file_sha256 must be a lowercase SHA-256" in " ".join(result.errors)

    context = CsvValidationContext(
        contract="phase_estimator_outputs_v1",
        known_channels=frozenset(),
        known_domains=frozenset(),
    )
    assert validate_csv(phe_path, context).ok
    phe_rows = list(csv.DictReader(phe_path.open(encoding="utf-8")))
    phe_rows[0]["source_relative_phase_observation"] = "RPH:1:999"
    _write_contract(phe_path, "phase_estimator_outputs_v1", phe_rows[0])
    result = validate_csv(phe_path, context)
    assert not result.ok
    assert "source_relative_phase_observation must equal RPH:1:1" in " ".join(
        result.errors
    )
    context = CsvValidationContext(
        contract="hybrid_preview_decisions_v1",
        known_channels=frozenset(),
        known_domains=frozenset(),
    )
    assert validate_csv(hpr_path, context).ok

    rows = list(csv.DictReader(hpr_path.open(encoding="utf-8")))
    rows[0]["source_frequency_estimate"] = "PHE:1:999"
    _write_contract(hpr_path, "hybrid_preview_decisions_v1", rows[0])
    result = validate_csv(hpr_path, context)
    assert not result.ok
    assert "source_frequency_estimate must equal PHE:1:1" in " ".join(
        result.errors
    )

    rows[0]["source_frequency_estimate"] = "PHE:1:1"
    rows[0]["authorization_consumed"] = "true"
    _write_contract(hpr_path, "hybrid_preview_decisions_v1", rows[0])
    result = validate_csv(hpr_path, context)
    assert not result.ok
    assert "authorization_consumed must remain false" in " ".join(result.errors)

    rows[0]["authorization_consumed"] = "false"
    rows[0]["counterfactual_delta_codes"] = "2"
    _write_contract(hpr_path, "hybrid_preview_decisions_v1", rows[0])
    result = validate_csv(hpr_path, context)
    assert not result.ok
    assert "counterfactual_delta_codes must equal" in " ".join(result.errors)

    rows[0]["counterfactual_correction"] = "false"
    rows[0]["shadow_code_after"] = rows[0]["shadow_code_before"]
    rows[0]["counterfactual_code"] = rows[0]["shadow_code_after"]
    rows[0]["decision_reason"] = "prospective_low_net_excess_path"
    rows[0]["modeled_not_observed_after_divergence"] = "false"
    _write_contract(hpr_path, "hybrid_preview_decisions_v1", rows[0])
    assert validate_csv(hpr_path, context).ok

    rows[0]["counterfactual_decision"] = "false"
    _write_contract(hpr_path, "hybrid_preview_decisions_v1", rows[0])
    result = validate_csv(hpr_path, context)
    assert not result.ok
    assert "raw_counterfactual_delta_codes must be empty" in " ".join(result.errors)


def test_phase_preview_records_split_and_default_manifest_declares_paths(tmp_path: Path) -> None:
    targets = {
        "relative_phase_observations_v1": tmp_path / "rph.csv",
        "phase_estimator_outputs_v1": tmp_path / "phe.csv",
        "hybrid_preview_decisions_v1": tmp_path / "hpr.csv",
    }
    with CsvRecordSplitter(targets) as splitter:
        for contract, record_type in (
            ("relative_phase_observations_v1", "RPH"),
            ("phase_estimator_outputs_v1", "PHE"),
            ("hybrid_preview_decisions_v1", "HPR"),
        ):
            row = [record_type, "1"] + [""] * (len(CONTRACT_FIELDS[contract]) - 2)
            assert splitter.process_line(",".join(row)) == contract

    files = {entry["contract"]: entry for entry in default_csv_files()}
    assert files["relative_phase_observations_v1"] == {
        "path": "csv/relative_phase_observations_v1.csv",
        "contract": "relative_phase_observations_v1",
        "optional": True,
    }
    assert files["phase_estimator_outputs_v1"] == {
        "path": "csv/phase_estimator_outputs_v1.csv",
        "contract": "phase_estimator_outputs_v1",
        "optional": True,
    }
    assert files["hybrid_preview_decisions_v1"] == {
        "path": "csv/hybrid_preview_decisions_v1.csv",
        "contract": "hybrid_preview_decisions_v1",
        "optional": True,
    }
