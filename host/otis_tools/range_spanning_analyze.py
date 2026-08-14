"""Analyze and seal a finite CX319 Part A range-map segment."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .contracts import CsvValidationContext, validate_csv
from .range_spanning_bundle import canonical_sha256, sha256_file, validate_bundle
from .run_loader import load_manifest
from .validate_run import _validate_manifest, _validate_raw_serial_framing


TOOL_ID = "cx319_range_spanning_analyze_v1"
ANALYSIS_TYPE = "cx319_range_spanning_part_a_segment_analysis_v1"
SEAL_TYPE = "cx319_range_spanning_part_a_segment_seal_v1"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_events(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid supervisor event line {line_number}: {exc}"
                ) from exc
            if not isinstance(value, dict):
                raise ValueError(f"supervisor event line {line_number} is not an object")
            values.append(value)
    return values


def analyze(
    *, bundle_path: Path, run_dir: Path, output_path: Path, seal_path: Path
) -> dict[str, Any]:
    bundle_path = bundle_path.resolve()
    run_dir = run_dir.resolve()
    bundle = validate_bundle(bundle_path)
    failures: list[str] = []
    manifest = load_manifest(run_dir)
    validation_errors = _validate_manifest(run_dir, manifest)
    validation_errors.extend(_validate_raw_serial_framing(run_dir))
    for entry in manifest.files:
        path = run_dir / str(entry.get("path", ""))
        if entry.get("optional") and not path.exists():
            continue
        result = validate_csv(
            path,
            CsvValidationContext(
                contract=str(entry.get("contract", "")),
                known_channels=manifest.known_channels,
                known_domains=manifest.known_domains,
                template=manifest.is_template,
                tight_deadband_policy_sha256=(
                    manifest.data.get("policy", {}).get("sha256")
                    if isinstance(manifest.data.get("policy"), dict)
                    else None
                ),
            ),
        )
        validation_errors.extend(
            f"{entry.get('path')}: {error}" for error in result.errors
        )
    if validation_errors:
        failures.append("canonical_contract_validation_failed")
        failures.extend(validation_errors)

    events_path = run_dir / "reports/range_spanning_supervisor_events.jsonl"
    events = _read_events(events_path)
    completed = [item for item in events if item.get("event") == "point_completed"]
    terminals = [item for item in events if item.get("event") == "terminal"]
    expected_prefix = bundle["part_a_segment"]["survey_prefix"]
    observed_codes = [int(item.get("code", -1)) for item in completed]
    if observed_codes != expected_prefix[: len(observed_codes)]:
        failures.append("completed_point_order_differs_from_frozen_prefix")
    if not terminals:
        failures.append("supervisor_terminal_absent")
        terminal: dict[str, Any] = {}
    else:
        terminal = terminals[-1]
        if terminal.get("result") not in {"healthy_stop", "aborted"}:
            failures.append("supervisor_terminal_result_invalid")

    dac_rows = _read_csv(run_dir / "csv/dac_steps.csv")
    estimates = _read_csv(run_dir / "csv/estimates_v2.csv")
    tdb_rows = _read_csv(run_dir / "csv/tight_deadband_decisions_v1.csv")
    hybrid_rows = _read_csv(run_dir / "csv/hybrid_preview_decisions_v1.csv")
    active_rows = _read_csv(run_dir / "csv/active_transactions_v1.csv")
    raw_rows = _read_csv(run_dir / "csv/raw_events.csv")
    count_rows = _read_csv(run_dir / "csv/count_observations.csv")
    if active_rows:
        failures.append("active_transaction_records_present_in_zero_authority_part_a")
    if not any(
        row.get("channel_id") == "1" and row.get("record_type") == "REF"
        for row in raw_rows
    ):
        failures.append("authoritative_d14_reference_records_absent")
    if not any(row.get("channel_id") == "2" for row in count_rows):
        failures.append("authoritative_d8_count_records_absent")

    estimate_by_id = {row.get("estimate_id", ""): row for row in estimates}
    tdb_by_sequence = {
        int(row["decision_sequence"]): row
        for row in tdb_rows
        if row.get("decision_sequence", "").isdigit()
    }
    dac_by_sequence = {
        int(row["seq"]): row
        for row in dac_rows
        if row.get("seq", "").isdigit()
    }
    point_results: list[dict[str, Any]] = []
    previous_epoch = -1
    for point in completed:
        point_index = int(point.get("point_index", -1))
        code = int(point.get("code", -1))
        dac_sequence = int(point.get("dac_sequence", -1))
        tdb_sequences = [int(item) for item in point.get("tdb_sequences", [])]
        epoch = int(point.get("dac_epoch", -1))
        if point_index != len(point_results):
            failures.append(f"point_{point_index}_index_not_contiguous")
        if epoch <= previous_epoch:
            failures.append(f"point_{point_index}_dac_epoch_not_strictly_increasing")
        previous_epoch = epoch
        dac = dac_by_sequence.get(dac_sequence)
        if dac is None or (
            dac.get("event") != "manual_apply"
            or int(dac.get("dac_code_requested", -1)) != code
            or int(dac.get("dac_code_applied", -1)) != code
            or dac.get("dac_code_clamped") != "0"
        ):
            failures.append(f"point_{point_index}_exact_dac_application_missing")
        if len(tdb_sequences) != 2:
            failures.append(f"point_{point_index}_requires_two_tdb_observations")
        rows = [tdb_by_sequence.get(sequence) for sequence in tdb_sequences]
        if any(row is None for row in rows):
            failures.append(f"point_{point_index}_declared_tdb_record_missing")
            rows = []
        for row in rows:
            assert row is not None
            if int(row.get("dac_epoch", -1)) != epoch:
                failures.append(f"point_{point_index}_cross_epoch_tdb_record")
            if any(
                row.get(field) != "false"
                for field in (
                    "actionable",
                    "actuation_authorized",
                    "authorization_consumed",
                )
            ):
                failures.append(f"point_{point_index}_tdb_authority_contamination")
            estimate = estimate_by_id.get(row.get("estimate_id", ""))
            if estimate is None or (
                estimate.get("estimator_version")
                != "cx317_selected_600s_nonoverlap_v1"
                or estimate.get("observation_validity") != "valid"
                or estimate.get("manifest_ref")
                != "firmware_config:cx319_range_map_part_a"
            ):
                failures.append(f"point_{point_index}_selected_estimate_binding_invalid")
        matching_hybrid = [
            row
            for row in hybrid_rows
            if int(row.get("dac_epoch", -1)) == epoch
            and int(row.get("actual_applied_code", -1)) == code
        ]
        if not matching_hybrid:
            failures.append(f"point_{point_index}_hybrid_epoch_propagation_absent")
        elif any(
            row.get(field) != "false"
            for row in matching_hybrid
            for field in ("actionable", "actuation_authorized", "authorization_consumed")
        ):
            failures.append(f"point_{point_index}_hybrid_authority_contamination")
        counts = [int(row["integer_edge_error_counts"]) for row in rows]
        point_results.append(
            {
                "point_index": point_index,
                "code": code,
                "code_hex": f"0x{code:04X}",
                "dac_sequence": dac_sequence,
                "dac_epoch": epoch,
                "tdb_sequences": tdb_sequences,
                "integer_edge_error_counts": counts,
                "terminal_band_state": rows[-1]["state_after"] if rows else "unknown",
                "terminal_reason": rows[-1]["reason_codes"] if rows else "unknown",
                "hybrid_records_same_code_epoch": len(matching_hybrid),
            }
        )

    if terminal.get("result") == "healthy_stop" and terminal.get("reason") == "survey_prefix_complete":
        if len(point_results) != len(expected_prefix):
            failures.append("prefix_complete_terminal_without_all_frozen_points")
    elif terminal.get("result") == "healthy_stop" and terminal.get("reason") == "finite_wall_deadline_before_next_point":
        if not point_results:
            failures.append("finite_deadline_terminal_without_decision_bearing_point")

    status = "passed" if not failures else "failed"
    unsigned = {
        "schema_version": 1,
        "analysis_type": ANALYSIS_TYPE,
        "tool": TOOL_ID,
        "created_utc": _utc_now(),
        "status": status,
        "bundle_sha256": bundle["bundle_sha256"],
        "bundle_file_sha256": sha256_file(bundle_path),
        "run_id": run_dir.name,
        "terminal": terminal,
        "completed_point_count": len(point_results),
        "frozen_point_count": len(expected_prefix),
        "point_results": point_results,
        "failures": failures,
        "claims_boundary": (
            "Finite Part A survey-prefix evidence only. It neither completes the "
            "full boundary map nor authorizes Part B, phase, or hybrid actuation."
        ),
    }
    analysis = {**unsigned, "analysis_sha256": canonical_sha256(unsigned)}
    from .range_spanning_bundle import _atomic_new_json

    _atomic_new_json(output_path.resolve(), analysis)
    seal_unsigned = {
        "schema_version": 1,
        "seal_type": SEAL_TYPE,
        "tool": TOOL_ID,
        "status": status,
        "bundle_sha256": bundle["bundle_sha256"],
        "analysis_sha256": analysis["analysis_sha256"],
        "analysis_file_sha256": sha256_file(output_path.resolve()),
        "run_id": run_dir.name,
        "claims_boundary": analysis["claims_boundary"],
    }
    seal = {**seal_unsigned, "seal_sha256": canonical_sha256(seal_unsigned)}
    _atomic_new_json(seal_path.resolve(), seal)
    return analysis


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seal", type=Path, required=True)
    args = parser.parse_args(argv)
    result = analyze(
        bundle_path=args.bundle,
        run_dir=args.run_dir,
        output_path=args.output,
        seal_path=args.seal,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
