"""Validate, analyze, and seal one targeted equilibrium characterization run."""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from datetime import datetime, timezone
from fractions import Fraction
import json
from pathlib import Path
from typing import Any, Sequence

from .contracts import CsvValidationContext, validate_csv
from .range_spanning_bundle import _atomic_new_json, canonical_sha256, sha256_file
from .run_loader import load_manifest
from .sustained_hybrid_equilibrium_estimator_recovery_study import (
    SupportObservation,
    _constant_model,
    _history_model,
    _interval_json,
    _model_interval,
    _prediction_interval,
    _slow_drift_model,
)
from .sustained_hybrid_equilibrium_estimator_study import count_quantization_interval
from .targeted_equilibrium_bundle import (
    gnss_health_reasons,
    split_runtime_gnss_reasons,
    validate_bundle,
)
from .validate_run import _validate_manifest, _validate_raw_serial_framing


TOOL_ID = "otis_targeted_equilibrium_analyze_v1"
ANALYSIS_TYPE = "otis_targeted_equilibrium_characterization_analysis_v1"
SEAL_TYPE = "otis_targeted_equilibrium_characterization_seal_v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _read_events(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"event line {line_number} is not an object")
            result.append(value)
    return result


def _fraction(value: str | int | Fraction) -> Fraction:
    return value if isinstance(value, Fraction) else Fraction(str(value))


def _support_from_rows(
    *,
    run_id: str,
    dwell: dict[str, Any],
    tdb: dict[str, str],
    estimate: dict[str, str],
    count_by_sequence: dict[int, dict[str, str]],
    reference_by_sequence: dict[int, dict[str, str]],
) -> SupportObservation:
    first = int(estimate["source_reference_first_seq"])
    last = int(estimate["source_reference_last_seq"])
    if last - first != 600 or int(estimate["accepted_sample_count"]) != 600:
        raise ValueError("selected support is not exactly 600 D14 intervals")
    references = [
        reference_by_sequence.get(sequence) for sequence in range(first, last + 1)
    ]
    if len(references) != 601 or any(row is None for row in references):
        raise ValueError("selected support lacks exact D14 boundary rows")
    if any(
        row is not None
        and (
            row.get("channel_id") != "1"
            or row.get("capture_domain") != "rp2040_timer0"
        )
        for row in references
    ):
        raise ValueError("selected support D14 domain identity differs")
    rows = [count_by_sequence.get(sequence) for sequence in range(first + 1, last + 1)]
    if len(rows) != 600 or any(row is None for row in rows):
        raise ValueError("selected support lacks exact D8 count rows")
    exact_rows = [row for row in rows if row is not None]
    if any(
        row.get("channel_id") != "2"
        or row.get("gate_domain") != "rp2040_timer0"
        or row.get("source_domain") != "h1_cx317_ocxo_10mhz"
        for row in exact_rows
    ):
        raise ValueError("selected support D8 domain identity differs")
    total = sum(int(row["counted_edges"]) for row in exact_rows)
    error = total - 6_000_000_000
    if error != int(tdb["integer_edge_error_counts"]):
        raise ValueError("selected support raw D8 arithmetic differs from TDB consumer")
    return SupportObservation(
        evidence_source=run_id,
        segment=str(dwell["label"]),
        code=int(dwell["code"]),
        dac_epoch=f"{run_id}:DAC:{tdb['dac_epoch']}",
        capture_session=str(tdb["capture_session"]),
        first_snapshot_sequence=first,
        last_snapshot_sequence=last,
        first_reference_sequence=first,
        last_reference_sequence=last,
        first_count_sequence=first + 1,
        last_count_sequence=last,
        total_counted_edges=total,
        count_error=error,
        midpoint_reference_sequence=Fraction(first + last, 2),
        history_class=str(dwell["history_class"]),
    )


def _evaluate_numerical(
    model_id: str,
    supports: Sequence[SupportObservation],
    *,
    gain: Fraction,
    slope_limit: Fraction,
    dead_zone: Fraction,
) -> dict[str, Any]:
    if model_id == "constant_equilibrium_per_stage5_thermal_segment_v1":
        return _constant_model(supports, gain)
    if model_id == "bounded_slow_drift_equilibrium_v1":
        return _slow_drift_model(supports, gain, slope_limit)
    if model_id == "direction_history_conditioned_equilibrium_v1":
        return _history_model(supports, gain, dead_zone)
    raise ValueError(f"unsupported frozen model: {model_id}")


def _held_out_coverage(
    *,
    model_id: str,
    numerical: dict[str, Any],
    held_out: Sequence[SupportObservation],
    gain: Fraction,
    slope_limit: Fraction,
    dead_zone: Fraction,
) -> dict[str, Any]:
    equilibrium = _model_interval(numerical, model_id)
    if equilibrium is None:
        return {
            "passed": False,
            "coverage_count": 0,
            "observation_count": len(held_out),
            "coverage_fraction": f"0/{len(held_out)}",
            "first_uncovered_support": None,
        }
    reference = (
        _fraction(numerical["reference_D14_sequence"])
        if model_id == "bounded_slow_drift_equilibrium_v1"
        else None
    )
    uncovered: list[dict[str, Any]] = []
    for support in held_out:
        effective_equilibrium = equilibrium
        prediction_dead_zone = Fraction(0)
        if reference is not None:
            elapsed_h = (support.midpoint_reference_sequence - reference) / 3600
            displacement = abs(elapsed_h) * slope_limit
            effective_equilibrium = type(equilibrium)(
                equilibrium.lower - displacement, equilibrium.upper + displacement
            )
        elif model_id == "direction_history_conditioned_equilibrium_v1":
            prediction_dead_zone = dead_zone
        prediction = _prediction_interval(
            code=support.code,
            equilibrium=effective_equilibrium,
            gain=gain,
            history_dead_zone=prediction_dead_zone,
        )
        observed = count_quantization_interval(support.count_error)
        if observed.intersect(prediction) is None:
            uncovered.append(
                {
                    "segment": support.segment,
                    "dac_epoch": support.dac_epoch,
                    "count_error": support.count_error,
                    "observed_hz": _interval_json(observed),
                    "predicted_hz": _interval_json(prediction),
                }
            )
    covered = len(held_out) - len(uncovered)
    return {
        "passed": not uncovered and bool(held_out),
        "coverage_count": covered,
        "observation_count": len(held_out),
        "coverage_fraction": f"{covered}/{len(held_out)}",
        "first_uncovered_support": uncovered[0] if uncovered else None,
    }


def _sensitivity(
    *,
    model_id: str,
    supports: Sequence[SupportObservation],
    gain: Fraction,
    slope_limit: Fraction,
    dead_zone: Fraction,
    usefulness_span: Fraction,
) -> dict[str, Any]:
    def passes(candidate: Sequence[SupportObservation]) -> tuple[bool, dict[str, Any]]:
        numerical = _evaluate_numerical(
            model_id,
            candidate,
            gain=gain,
            slope_limit=slope_limit,
            dead_zone=dead_zone,
        )
        interval = _model_interval(numerical, model_id)
        return (
            interval is not None and interval.width <= usefulness_span,
            {"interval": _interval_json(interval), "numerical": numerical},
        )

    leave_one = []
    for segment in dict.fromkeys(row.segment for row in supports):
        passed, detail = passes([row for row in supports if row.segment != segment])
        leave_one.append({"omitted_segment": segment, "passed": passed, **detail})

    perturbations = []
    return_segments = sorted(
        {row.segment for row in supports if row.history_class == "return"}
    )
    for change in (-1, 1):
        for segment in return_segments:
            modified = [
                replace(row, count_error=row.count_error + change)
                if row.segment == segment
                else row
                for row in supports
            ]
            passed, detail = passes(modified)
            perturbations.append(
                {
                    "segment": segment,
                    "perturbation_counts": change,
                    "passed": passed,
                    **detail,
                }
            )

    above = [
        replace(row, midpoint_reference_sequence=row.midpoint_reference_sequence + 1)
        for row in supports
    ]
    above_passed, above_detail = passes(above)
    return {
        "leave_one_complete_dwell_out": {
            "passed": all(row["passed"] for row in leave_one),
            "cases": leave_one,
        },
        "same_code_one_count_perturbations": {
            "passed": bool(perturbations) and all(row["passed"] for row in perturbations),
            "cases": perturbations,
        },
        "settling_boundary": {
            "below": "rejected_crosses_frozen_900_second_exclusion",
            "at": "captured_supports_evaluated",
            "one_second_above": {"passed": above_passed, **above_detail},
        },
    }


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
        validated = validate_csv(
            path,
            CsvValidationContext(
                contract=str(entry.get("contract", "")),
                known_channels=manifest.known_channels,
                known_domains=manifest.known_domains,
                template=manifest.is_template,
                tight_deadband_policy_sha256=manifest.data.get("policy", {}).get(
                    "sha256"
                ),
            ),
        )
        validation_errors.extend(
            f"{entry.get('path')}: {error}" for error in validated.errors
        )
    if validation_errors:
        failures.extend(["canonical_contract_validation_failed", *validation_errors])

    events = _read_events(
        run_dir / "reports/targeted_equilibrium_supervisor_events.jsonl"
    )
    completed = [row for row in events if row.get("event") == "dwell_completed"]
    terminals = [row for row in events if row.get("event") == "terminal"]
    terminal = terminals[-1] if terminals else {}
    if not terminals:
        failures.append("supervisor_terminal_absent")
    if (
        terminal.get("result") == "healthy_stop"
        and terminal.get("reason") == "targeted_characterization_complete"
        and len(completed) != 12
    ):
        failures.append("healthy_terminal_without_all_twelve_dwells")
    expected_plan = bundle["dwell_plan"]
    warmups = [row for row in events if row.get("event") == "initial_warmup_complete"]
    first_command_position = next(
        (
            index
            for index, row in enumerate(events)
            if row.get("event") == "dwell_command_sent"
        ),
        len(events),
    )
    warmup_position = next(
        (
            index
            for index, row in enumerate(events)
            if row.get("event") == "initial_warmup_complete"
        ),
        len(events),
    )
    if (
        len(warmups) != 1
        or float(
            warmups[0].get(
                "observed_elapsed_s", warmups[0].get("minimum_elapsed_s", 0)
            )
        )
        < 1800
        or warmup_position >= first_command_position
    ):
        failures.append("initial_1800_second_warmup_not_proved_before_first_write")
    if [int(row.get("code", -1)) for row in completed] != [
        int(row["code"]) for row in expected_plan[: len(completed)]
    ]:
        failures.append("completed_dwell_order_differs_from_frozen_plan")

    dac_rows = _read_csv(run_dir / "csv/dac_steps.csv")
    estimates = _read_csv(run_dir / "csv/estimates_v2.csv")
    tdb_rows = _read_csv(run_dir / "csv/tight_deadband_decisions_v1.csv")
    hybrid_rows = _read_csv(run_dir / "csv/hybrid_preview_decisions_v1.csv")
    count_rows = _read_csv(run_dir / "csv/count_observations.csv")
    raw_rows = _read_csv(run_dir / "csv/raw_events.csv")
    active_rows = _read_csv(run_dir / "csv/active_transactions_v1.csv")
    health_rows = _read_csv(run_dir / "csv/health.csv")
    if active_rows:
        failures.append("active_transaction_records_present")
    if manifest.stage == "CX319_TARGETED_EQUILIBRIUM_CHARACTERIZATION_LIVE":
        entry_record = _read_json(
            run_dir / "reports/range_spanning_firmware_entry_v2.json"
        )
        if not (
            entry_record.get("status") == "passed"
            and entry_record.get("operation") == "exact_range_map_firmware_flash"
            and entry_record.get("profile_id") == "cx319_range_map_part_a"
            and entry_record.get("uf2_sha256")
            == bundle["firmware"]["uf2"]["sha256"]
            and int(entry_record.get("firmware_flash_count", -1)) == 1
            and int(entry_record.get("dac_value_write_attempts", -1)) == 0
        ):
            failures.append("exact_firmware_flash_entry_record_invalid")
    if not any(row.get("channel_id") == "1" for row in raw_rows):
        failures.append("authoritative_d14_reference_absent")
    if not any(row.get("channel_id") == "2" for row in count_rows):
        failures.append("authoritative_d8_count_absent")
    latest_health: dict[tuple[str, str], str] = {}
    for row in health_rows:
        latest_health[(row.get("component", ""), row.get("status_key", ""))] = row.get(
            "status_value", ""
        )
    gnss_required = bundle["gnss_live_boundary"]["required_prewrite_health"]
    gnss_mismatches = gnss_health_reasons(
        bundle["gnss_live_boundary"], latest_health
    )
    gnss_held_mismatches, gnss_invariant_mismatches = split_runtime_gnss_reasons(
        bundle["gnss_live_boundary"], gnss_mismatches
    )
    failure_counters = {
        "configuration_failure_count",
        "transmit_failure_count",
        "link_loss_count",
    }
    historical_gnss_failures = [
        f"{row.get('status_key')}={row.get('status_value')}"
        for row in health_rows
        if row.get("component") == "gnss_receiver"
        and row.get("status_key") in failure_counters
        and row.get("status_value") not in {"", "0"}
    ]
    if gnss_invariant_mismatches or historical_gnss_failures:
        failures.append("gnss_output_confirmation_or_stability_qualification_failed")
        failures.extend(gnss_invariant_mismatches)
        failures.extend(historical_gnss_failures)
    dac_by_sequence = {
        int(row["seq"]): row for row in dac_rows if row.get("seq", "").isdigit()
    }
    tdb_by_sequence = {
        int(row["decision_sequence"]): row
        for row in tdb_rows
        if row.get("decision_sequence", "").isdigit()
    }
    estimate_by_id = {row.get("estimate_id", ""): row for row in estimates}
    count_by_sequence = {
        int(row["count_seq"]): row
        for row in count_rows
        if row.get("count_seq", "").isdigit()
    }
    reference_by_sequence = {
        int(row["event_seq"]): row
        for row in raw_rows
        if row.get("event_seq", "").isdigit() and row.get("channel_id") == "1"
    }
    supports: list[SupportObservation] = []
    dwell_results: list[dict[str, Any]] = []
    prior_epoch = -1
    for index, completed_row in enumerate(completed):
        plan = expected_plan[index]
        code = int(plan["code"])
        epoch = int(completed_row.get("dac_epoch", -1))
        dac_sequence = int(completed_row.get("dac_sequence", -1))
        tdb_sequences = [int(item) for item in completed_row.get("tdb_sequences", [])]
        if epoch <= prior_epoch:
            failures.append(f"dwell_{index}_dac_epoch_not_strictly_increasing")
        prior_epoch = epoch
        dac = dac_by_sequence.get(dac_sequence)
        if dac is None or not (
            dac.get("event") == "manual_apply"
            and int(dac.get("dac_code_requested", -1)) == code
            and int(dac.get("dac_code_applied", -1)) == code
            and dac.get("dac_code_clamped") == "0"
        ):
            failures.append(f"dwell_{index}_exact_dac_application_missing")
        if len(tdb_sequences) != 3:
            failures.append(f"dwell_{index}_support_count_not_three")
        if float(
            completed_row.get(
                "observed_elapsed_s", completed_row.get("minimum_elapsed_s", 0)
            )
        ) < 2700:
            failures.append(f"dwell_{index}_minimum_2700_second_elapsed_not_proved")
        local: list[SupportObservation] = []
        for sequence in tdb_sequences:
            tdb = tdb_by_sequence.get(sequence)
            if tdb is None or int(tdb.get("dac_epoch", -1)) != epoch:
                failures.append(f"dwell_{index}_declared_tdb_identity_invalid")
                continue
            if any(
                tdb.get(field) != "false"
                for field in ("actionable", "actuation_authorized", "authorization_consumed")
            ):
                failures.append(f"dwell_{index}_tdb_authority_contamination")
            estimate = estimate_by_id.get(tdb.get("estimate_id", ""))
            if estimate is None or not (
                estimate.get("estimator_version")
                == "cx317_selected_600s_nonoverlap_v1"
                and estimate.get("observation_validity") == "valid"
                and estimate.get("manifest_ref")
                == "firmware_config:cx319_range_map_part_a"
            ):
                failures.append(f"dwell_{index}_selected_estimate_binding_invalid")
                continue
            try:
                local.append(
                    _support_from_rows(
                        run_id=run_dir.name,
                        dwell=plan,
                        tdb=tdb,
                        estimate=estimate,
                        count_by_sequence=count_by_sequence,
                        reference_by_sequence=reference_by_sequence,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                failures.append(f"dwell_{index}_support_reconstruction_failed:{exc}")
        if len(local) == 3 and any(
            right.first_reference_sequence != left.last_reference_sequence
            for left, right in zip(local, local[1:])
        ):
            failures.append(f"dwell_{index}_supports_not_contiguous_nonoverlap")
        matching_hybrid = [
            row
            for row in hybrid_rows
            if int(row.get("dac_epoch", -1)) == epoch
            and int(row.get("actual_applied_code", -1)) == code
        ]
        if not matching_hybrid:
            failures.append(f"dwell_{index}_cross_core_epoch_propagation_absent")
        elif any(
            row.get(field) != "false"
            for row in matching_hybrid
            for field in ("actionable", "actuation_authorized", "authorization_consumed")
        ):
            failures.append(f"dwell_{index}_hybrid_authority_contamination")
        supports.extend(local)
        dwell_results.append(
            {
                **plan,
                "dac_sequence": dac_sequence,
                "dac_epoch": epoch,
                "tdb_sequences": tdb_sequences,
                "integer_edge_error_counts": [row.count_error for row in local],
                "first_dependent_consumer_verified": bool(local),
            }
        )

    identification = [
        row for row in supports if row.segment in {item["label"] for item in expected_plan[:7]}
    ]
    held_out = [
        row for row in supports if row.segment in {item["label"] for item in expected_plan[7:]}
    ]
    if len(identification) != 21 or len(held_out) != 15:
        failures.append("frozen_21_15_support_partition_incomplete")

    model_results: list[dict[str, Any]] = []
    eligible_models: list[str] = []
    if not failures:
        contract = bundle["analysis_contract"]
        gain_cases = {
            name: _fraction(value)
            for name, value in contract["gain_cases_hz_per_code"].items()
        }
        slope_limit = _fraction(contract["maximum_absolute_drift_codes_per_hour"])
        dead_zone = Fraction(contract["maximum_outward_reversal_dead_zone_codes"])
        usefulness = Fraction(contract["maximum_equilibrium_interval_span_codes"])
        lower = [row.count_error for row in identification if row.code == 43046]
        upper = [row.count_error for row in identification if row.code == 43094]
        bracket = bool(lower and upper and min(lower) < 0 < max(upper))
        structural = {
            "constant_equilibrium_per_stage5_thermal_segment_v1": bracket,
            "bounded_slow_drift_equilibrium_v1": bracket
            and len({row.segment for row in identification if row.code == 43070}) >= 3,
            "direction_history_conditioned_equilibrium_v1": bracket
            and {row.history_class for row in identification}
            == {"outbound_or_anchor", "return"},
        }
        for model_id in contract["model_ids"]:
            cases: dict[str, Any] = {}
            for gain_name, gain in gain_cases.items():
                numerical = _evaluate_numerical(
                    model_id,
                    identification,
                    gain=gain,
                    slope_limit=slope_limit,
                    dead_zone=dead_zone,
                )
                interval = _model_interval(numerical, model_id)
                held = _held_out_coverage(
                    model_id=model_id,
                    numerical=numerical,
                    held_out=held_out,
                    gain=gain,
                    slope_limit=slope_limit,
                    dead_zone=dead_zone,
                )
                sensitivity = _sensitivity(
                    model_id=model_id,
                    supports=identification,
                    gain=gain,
                    slope_limit=slope_limit,
                    dead_zone=dead_zone,
                    usefulness_span=usefulness,
                )
                passed = bool(
                    interval is not None
                    and interval.width <= usefulness
                    and held["passed"]
                    and sensitivity["leave_one_complete_dwell_out"]["passed"]
                    and sensitivity["same_code_one_count_perturbations"]["passed"]
                    and sensitivity["settling_boundary"]["one_second_above"]["passed"]
                )
                cases[gain_name] = {
                    "passed": passed,
                    "complete_interval": _interval_json(interval),
                    "useful_span_passed": interval is not None
                    and interval.width <= usefulness,
                    "held_out_prediction": held,
                    "sensitivity": sensitivity,
                    "numerical": numerical,
                }
            model_passed = structural[model_id] and all(
                row["passed"] for row in cases.values()
            )
            if model_passed:
                eligible_models.append(model_id)
            model_results.append(
                {
                    "model_id": model_id,
                    "structurally_identifiable": structural[model_id],
                    "passed": model_passed,
                    "gain_cases": cases,
                }
            )

    evidence_status = "passed" if not failures else "failed"
    scientific_terminal = (
        "invalid_due_to_evidence_or_identity_mismatch"
        if failures
        else (
            "equilibrium_state_observable"
            if eligible_models
            else "equilibrium_state_not_observable"
        )
    )
    temperatures = []
    for row in _read_csv(run_dir / "csv/environment.csv"):
        for key in ("temperature_c", "ambient_temperature_c"):
            try:
                temperatures.append(float(row[key]))
            except (KeyError, TypeError, ValueError):
                pass
    unsigned = {
        "schema_version": 1,
        "analysis_type": ANALYSIS_TYPE,
        "tool": TOOL_ID,
        "created_utc": _utc_now(),
        "evidence_status": evidence_status,
        "scientific_terminal": scientific_terminal,
        "bundle_sha256": bundle["bundle_sha256"],
        "bundle_file_sha256": sha256_file(bundle_path),
        "run_id": run_dir.name,
        "terminal": terminal,
        "completed_dwell_count": len(completed),
        "identification_support_count": len(identification),
        "held_out_support_count": len(held_out),
        "dwell_results": dwell_results,
        "identification_supports": [row.as_report_row() for row in identification],
        "held_out_supports": [row.as_report_row() for row in held_out],
        "nearby_air_temperature_c": {
            "role": "SHT41_nearby_air_covariate_not_CX317_internal_temperature",
            "available_count": len(temperatures),
            "minimum": min(temperatures) if temperatures else None,
            "maximum": max(temperatures) if temperatures else None,
        },
        "gnss_baud_transition_qualification": {
            "status": (
                "passed_current_run_exact_target_baud_health"
                if not gnss_invariant_mismatches and not historical_gnss_failures
                else "failed"
            ),
            "prospective_state": bundle["gnss_live_boundary"].get(
                "baud_transition_qualification_state"
            ),
            "target_baud": bundle["gnss_live_boundary"]["target_baud"],
            "latest_health": {
                key: latest_health.get(("gnss_receiver", key))
                for key in gnss_required
            },
            "historical_failure_counters": historical_gnss_failures,
            "future_reuse_policy": bundle["gnss_live_boundary"][
                "future_reuse_policy"
            ],
            "claim_boundary": (
                "Reusable only while firmware source/configuration, receiver identity, "
                "wiring, and all decision-relevant GNSS transition inputs remain unchanged."
            ),
        },
        "gnss_output_configuration_qualification": {
            "status": "passed"
            if not gnss_invariant_mismatches and not historical_gnss_failures
            else "failed",
            "confirmation_method": latest_health.get(
                ("gnss_receiver", "output_confirmation_method")
            ),
            "latest_health": {
                key: value
                for (component, key), value in latest_health.items()
                if component == "gnss_receiver"
                and (
                    key.startswith("output_")
                    or key.startswith("last_command_ack_")
                    or key in {"link_phase", "last_identity_response_baud"}
                )
            },
            "bounded_terminal_snapshot_holds": gnss_held_mismatches,
            "invariant_mismatches": gnss_invariant_mismatches,
            "historical_failure_counters": historical_gnss_failures,
        },
        "model_results": model_results,
        "eligible_models": eligible_models,
        "failures": failures,
        "claims_boundary": (
            "Predetermined open-loop equilibrium observability only; this result grants no "
            "frequency-control, phase, hybrid, retry, or restoration authority."
        ),
    }
    analysis = {**unsigned, "analysis_sha256": canonical_sha256(unsigned)}
    _atomic_new_json(output_path.resolve(), analysis)
    seal_unsigned = {
        "schema_version": 1,
        "seal_type": SEAL_TYPE,
        "tool": TOOL_ID,
        "evidence_status": evidence_status,
        "scientific_terminal": scientific_terminal,
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
    return 0 if result["evidence_status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
