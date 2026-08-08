"""Reconstruct the CX317 Stage 7B handoff for the CX318 programme.

This tool is offline and read-only with respect to the supplied source run.  It
does not import a serial, command, abort, authorization, or actuator module.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import argparse
import csv
import json
import math
import os
import statistics
import tempfile
from typing import Any

from jsonschema import Draft202012Validator

from .cx317_stage7_shadow import (
    ShadowObservation,
    load_contract,
    run_shadow,
)


TOOL_VERSION = "cx318_stage1_handoff_v1"
DEFAULT_PROFILE = (
    Path(__file__).resolve().parents[2]
    / "profiles/discipline/cx318_stage1_contracts_v1.json"
)
DEFAULT_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "schemas/cx318_stage1_contracts_v1.schema.json"
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def _serialize(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return ""
    return str(value)


def _longest_true_residence(observations: list[bool], cadence_s: int) -> int:
    longest = current = 0
    for inside in observations:
        current = current + cadence_s if inside else 0
        longest = max(longest, current)
    return longest


def reconstruct_phase(
    snapshots: list[dict[str, str]],
    counts: list[dict[str, str]],
    *,
    nominal_edges: int,
    counter_width_bits: int,
    expected_backend: str,
    period_ns_per_cycle: int,
) -> tuple[dict[str, Any], dict[int, int]]:
    """Return an exact raw-phase summary and cumulative error by REF sequence."""

    if len(snapshots) < 2:
        raise ValueError("at least two snapshots are required")
    modulus = 1 << counter_width_bits
    count_by_sequence = {int(row["count_seq"]): row for row in counts}
    first = snapshots[0]
    session = first["session"]
    previous_snapshot_sequence = int(first["snapshot_sequence"])
    previous_reference_sequence = int(first["reference_sequence"])
    previous_counter = int(first["cumulative_down_counter"])
    if first["backend"] != expected_backend or int(first["status"]) != 0:
        raise ValueError("opening snapshot identity or status differs")

    cumulative = 0
    cumulative_by_reference = {previous_reference_sequence: 0}
    edge_error_distribution: Counter[int] = Counter()
    cumulative_values: list[int] = []
    stream_digest = sha256()

    for row in snapshots[1:]:
        snapshot_sequence = int(row["snapshot_sequence"])
        reference_sequence = int(row["reference_sequence"])
        counter = int(row["cumulative_down_counter"])
        if (
            row["session"] != session
            or row["backend"] != expected_backend
            or int(row["status"]) != 0
            or snapshot_sequence != previous_snapshot_sequence + 1
            or reference_sequence != previous_reference_sequence + 1
        ):
            raise ValueError(
                f"snapshot discontinuity at sequence {snapshot_sequence}"
            )
        interval_edges = (previous_counter - counter) % modulus
        count = count_by_sequence.get(snapshot_sequence)
        if count is None or int(count["counted_edges"]) != interval_edges:
            raise ValueError(
                f"CNT parity failure at snapshot {snapshot_sequence}"
            )
        edge_error = interval_edges - nominal_edges
        cumulative += edge_error
        cumulative_by_reference[reference_sequence] = cumulative
        cumulative_values.append(cumulative)
        edge_error_distribution[edge_error] += 1
        stream_digest.update(
            (
                f"{session},{snapshot_sequence},{reference_sequence},"
                f"{interval_edges},{edge_error},{cumulative}\n"
            ).encode("ascii")
        )
        previous_snapshot_sequence = snapshot_sequence
        previous_reference_sequence = reference_sequence
        previous_counter = counter

    interval_count = len(cumulative_values)
    x_mean = (interval_count + 1) / 2.0
    y_mean = sum(cumulative_values) / interval_count
    sxx = sum((index - x_mean) ** 2 for index in range(1, interval_count + 1))
    sxy = sum(
        (index - x_mean) * (value - y_mean)
        for index, value in enumerate(cumulative_values, 1)
    )
    slope = sxy / sxx
    intercept = y_mean - slope * x_mean
    residuals = [
        value - (intercept + slope * index)
        for index, value in enumerate(cumulative_values, 1)
    ]
    final_window = min(90000, interval_count)
    opening_window_reference = int(
        snapshots[len(snapshots) - final_window - 1]["reference_sequence"]
    )
    final_window_movement = (
        cumulative - cumulative_by_reference[opening_window_reference]
    )
    summary = {
        "phase_epoch_count": 1,
        "phase_zero": "opening_snapshot_boundary_session_local_arbitrary",
        "capture_session": int(session),
        "opening_snapshot_sequence": int(first["snapshot_sequence"]),
        "closing_snapshot_sequence": previous_snapshot_sequence,
        "opening_reference_sequence": int(first["reference_sequence"]),
        "closing_reference_sequence": previous_reference_sequence,
        "snapshot_count": len(snapshots),
        "accepted_interval_count": interval_count,
        "unreconstructible_opening_interval_count": 1,
        "snapshot_sequence_discontinuities": 0,
        "cnt_parity_failures": 0,
        "edge_error_distribution_counts": {
            str(key): edge_error_distribution[key]
            for key in sorted(edge_error_distribution)
        },
        "full_run_movement_cycles": cumulative,
        "full_run_movement_ns": cumulative * period_ns_per_cycle,
        "final_window_interval_count": final_window,
        "final_window_opening_reference_sequence": opening_window_reference,
        "final_window_movement_cycles": final_window_movement,
        "final_window_movement_ns": (
            final_window_movement * period_ns_per_cycle
        ),
        "detrended_residual_diagnostic": {
            "claim_scope": "ols_diagnostic_only_not_raw_phase_or_calibrated_phase",
            "fit_slope_cycles_per_nominal_second": slope,
            "residual_rms_cycles": math.sqrt(
                sum(value * value for value in residuals) / interval_count
            ),
            "residual_min_cycles": min(residuals),
            "residual_max_cycles": max(residuals),
            "residual_range_cycles": max(residuals) - min(residuals),
            "terminal_residual_cycles": residuals[-1],
        },
        "relative_phase_stream_sha256": stream_digest.hexdigest(),
        "calibrated_uncertainty_status": "unavailable",
    }
    return summary, cumulative_by_reference


def _recompute_authoritative(
    rows: list[dict[str, str]],
    cumulative_by_reference: dict[int, int],
    *,
    nominal_frequency_hz: int,
    expected_estimator_sha256: str,
    historical_v2_threshold_hz: float,
) -> tuple[dict[str, Any], list[ShadowObservation]]:
    exact_errors: list[float] = []
    integer_errors: list[int] = []
    v2_inside: list[bool] = []
    shadow_observations: list[ShadowObservation] = []
    for row in rows:
        first = int(row["source_reference_first_seq"])
        last = int(row["source_reference_last_seq"])
        span = last - first
        if (
            span != 600
            or row["selected_estimator_sha256"]
            != expected_estimator_sha256
            or row["eligible"] != "true"
        ):
            raise ValueError(
                f"authoritative identity differs at {row['estimate_id']}"
            )
        try:
            integer_error = (
                cumulative_by_reference[last]
                - cumulative_by_reference[first]
            )
        except KeyError as exc:
            raise ValueError(
                f"missing raw boundary for {row['estimate_id']}"
            ) from exc
        exact_error = integer_error / span
        observed_error = float(row["frequency_error_hz"])
        if not math.isclose(
            exact_error, observed_error, rel_tol=0.0, abs_tol=1e-9
        ):
            raise ValueError(
                f"frequency reconstruction mismatch at {row['estimate_id']}"
            )
        exact_errors.append(exact_error)
        integer_errors.append(integer_error)
        v2_inside.append(abs(observed_error) <= historical_v2_threshold_hz)
        shadow_observations.append(
            ShadowObservation(
                observation_sequence=int(row["observation_sequence"]),
                estimate_id=row["estimate_id"],
                timestamp_s=int(row["timestamp_s"]),
                frequency_error_hz=observed_error,
                actual_applied_code=int(row["actual_applied_code"]),
                actual_dac_epoch=int(row["actual_dac_epoch"]),
                eligible=True,
            )
        )
    summary = {
        "observation_count": len(rows),
        "raw_snapshot_frequency_parity": True,
        "all_eligible": True,
        "integer_edge_error_distribution_counts": {
            str(key): count
            for key, count in sorted(Counter(integer_errors).items())
        },
        "minimum_error_hz": min(exact_errors),
        "maximum_error_hz": max(exact_errors),
        "mean_error_hz": statistics.fmean(exact_errors),
        "median_error_hz": statistics.median(exact_errors),
        "rms_error_hz": math.sqrt(
            statistics.fmean(value * value for value in exact_errors)
        ),
        "historical_v2_inside_fraction": sum(v2_inside) / len(v2_inside),
        "historical_v2_longest_inside_residence_s": _longest_true_residence(
            v2_inside, 600
        ),
        "tight_entry_abs_lte_two_count_observations": sum(
            abs(value) <= 2 for value in integer_errors
        ),
        "three_count_observations": sum(
            abs(value) == 3 for value in integer_errors
        ),
        "loose_release_abs_gte_four_count_observations": sum(
            abs(value) >= 4 for value in integer_errors
        ),
    }
    return summary, shadow_observations


def _replay_shadow(
    observed_rows: list[dict[str, str]],
    observations: list[ShadowObservation],
    *,
    part: str,
    start_code: int,
) -> dict[str, Any]:
    contract = load_contract()
    replayed = run_shadow(
        observations,
        contract=contract,
        part=part,
        start_code=start_code,
    )
    exact = len(observed_rows) == len(replayed)
    grouped: dict[str, list[Any]] = defaultdict(list)
    for observed, decision in zip(observed_rows, replayed):
        expected = asdict(decision)
        exact = exact and observed["part"] == part
        exact = exact and (
            observed["shadow_contract_sha256"]
            == contract.contract_sha256
        )
        for field, value in expected.items():
            actual = observed[field]
            if isinstance(value, float) and actual not in {"", "nan"}:
                exact = exact and math.isclose(
                    float(actual), value, rel_tol=0.0, abs_tol=5e-13
                )
            else:
                exact = exact and actual == _serialize(value)
        grouped[decision.candidate_id].append(decision)
    candidate_summaries: dict[str, Any] = {}
    for candidate_id, decisions in sorted(grouped.items()):
        final = decisions[-1]
        candidate_summaries[candidate_id] = {
            "observation_count": len(decisions),
            "counterfactual_corrections": sum(
                decision.counterfactual_write for decision in decisions
            ),
            "path_codes": final.path_codes,
            "net_movement_codes": final.net_movement_codes,
            "alternating_correction_count": (
                final.alternating_correction_count
            ),
            "terminal_band_state": final.band_state_after,
            "terminal_preview_state": final.state_after,
            "zero_authority": all(
                not decision.actionable
                and not decision.actuation_authorized
                and not decision.authorization_consumed
                for decision in decisions
            ),
        }
    return {
        "contract_id": contract.contract_id,
        "contract_sha256": contract.contract_sha256,
        "decision_count": len(replayed),
        "exact_replay": exact,
        "all_authority_fields_false": all(
            summary["zero_authority"]
            for summary in candidate_summaries.values()
        ),
        "candidate_summaries": candidate_summaries,
    }


def analyze(
    run_dir: Path,
    *,
    profile_path: Path = DEFAULT_PROFILE,
    schema_path: Path = DEFAULT_SCHEMA,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(profile)
    bindings = profile["bindings"]
    oscillator = profile["oscillator_contract"]
    paths = {
        "pps_snapshots": run_dir / "csv/pps_snapshots.csv",
        "count_observations": run_dir / "csv/count_observations.csv",
        "dac_steps": run_dir / "csv/dac_steps.csv",
        "active_transactions": run_dir / "csv/active_transactions_v1.csv",
        "authoritative_observations": (
            run_dir / "reports/stage7_authoritative_observations_v1.csv"
        ),
        "shadow_decisions": (
            run_dir / "reports/stage7_shadow_decisions_v1.csv"
        ),
        "evidence_manifest": run_dir / "evidence_manifest.json",
    }
    source_hashes_before = {
        name: _sha256_file(path) for name, path in paths.items()
    }
    phase, cumulative_by_reference = reconstruct_phase(
        _read_csv(paths["pps_snapshots"]),
        _read_csv(paths["count_observations"]),
        nominal_edges=int(oscillator["nominal_frequency_hz"]),
        counter_width_bits=int(oscillator["counter_width_bits"]),
        expected_backend=bindings["snapshot_backend"],
        period_ns_per_cycle=int(oscillator["period_ns_per_cycle"]),
    )
    authoritative_rows = _read_csv(paths["authoritative_observations"])
    frequency, shadow_observations = _recompute_authoritative(
        authoritative_rows,
        cumulative_by_reference,
        nominal_frequency_hz=int(oscillator["nominal_frequency_hz"]),
        expected_estimator_sha256=bindings["frequency_estimator"]["sha256"],
        historical_v2_threshold_hz=float(
            profile["tight_hysteretic_deadband"][
                "historical_v2_threshold_hz"
            ]
        ),
    )
    shadow = _replay_shadow(
        _read_csv(paths["shadow_decisions"]),
        shadow_observations,
        part="part_b",
        start_code=int(authoritative_rows[0]["actual_applied_code"]),
    )
    dac_rows = _read_csv(paths["dac_steps"])
    transaction_rows = _read_csv(paths["active_transactions"])
    applications = [
        row for row in transaction_rows if row["event"] == "application"
    ]
    source_hashes_after = {
        name: _sha256_file(path) for name, path in paths.items()
    }
    result = {
        "schema_version": 1,
        "tool": TOOL_VERSION,
        "status": "pass",
        "source_run": str(run_dir),
        "contract_profile": {
            "path": str(profile_path),
            "sha256": _sha256_file(profile_path),
            "schema_path": str(schema_path),
            "schema_sha256": _sha256_file(schema_path),
        },
        "source_file_sha256": source_hashes_before,
        "sources_unchanged_during_analysis": (
            source_hashes_before == source_hashes_after
        ),
        "relative_phase": phase,
        "frequency": frequency,
        "shadow": shadow,
        "dac_epoch_continuity": {
            "dac_record_count": len(dac_rows),
            "automatic_application_count": len(applications),
            "applications": [
                {
                    "application_timestamp_s": int(
                        row["application_timestamp_s"]
                    ),
                    "applied_code": int(row["applied_code"]),
                    "dac_epoch": int(row["dac_epoch"]),
                }
                for row in applications
            ],
            "raw_phase_epoch_count": phase["phase_epoch_count"],
            "raw_phase_reset_at_healthy_dac_transition": False,
            "evidence": "one continuous snapshot session and sequence spans the separately recorded DAC application",
        },
        "sign_convention": {
            "positive_edge_error_increases_relative_phase_cycles": True,
            "positive_relative_phase_requires_negative_phase_bias": True,
        },
        "authority": profile["authority_separation"],
        "claims_not_made": profile["claims_not_made"],
    }
    if not (
        result["sources_unchanged_during_analysis"]
        and shadow["exact_replay"]
        and shadow["all_authority_fields_false"]
        and frequency["raw_snapshot_frequency_parity"]
    ):
        raise ValueError("Stage 1 handoff reconstruction did not pass")
    return result


def _markdown(result: dict[str, Any]) -> str:
    phase = result["relative_phase"]
    frequency = result["frequency"]
    shadow = result["shadow"]
    return f"""# CX318 Stage 1 CX317 Handoff Reconstruction

Status: `{result['status']}`. This is offline, session-local relative-phase and
frequency/shadow reconstruction; it is not a calibrated or absolute-phase
claim.

## Raw relative phase

- snapshots: {phase['snapshot_count']}; reconstructed adjacent intervals: {phase['accepted_interval_count']}
- phase epoch: one continuous capture session, zero arbitrary at snapshot {phase['opening_snapshot_sequence']}
- full-run movement: {phase['full_run_movement_cycles']} cycles / {phase['full_run_movement_ns']} ns
- final {phase['final_window_interval_count']} s movement: {phase['final_window_movement_cycles']} cycles / {phase['final_window_movement_ns']} ns
- edge-error distribution: `{json.dumps(phase['edge_error_distribution_counts'], sort_keys=True)}`
- deterministic stream SHA-256: `{phase['relative_phase_stream_sha256']}`
- calibrated uncertainty: `{phase['calibrated_uncertainty_status']}`

The OLS residual is labelled diagnostic-only. Its RMS is
{phase['detrended_residual_diagnostic']['residual_rms_cycles']:.9f} cycles and
range is {phase['detrended_residual_diagnostic']['residual_range_cycles']:.9f}
cycles; the fit does not replace raw accumulated phase.

## Frequency and deadband handoff

- authoritative observations reconstructed: {frequency['observation_count']}
- raw snapshot parity: `{frequency['raw_snapshot_frequency_parity']}`
- exact-count error range: {frequency['minimum_error_hz']:.12f} to {frequency['maximum_error_hz']:.12f} Hz
- historical V2 inside fraction: {frequency['historical_v2_inside_fraction']:.12f}
- historical V2 longest inside residence: {frequency['historical_v2_longest_inside_residence_s']} s
- tight-entry observations (absolute error <=2 counts): {frequency['tight_entry_abs_lte_two_count_observations']}
- three-count retain-region observations: {frequency['three_count_observations']}
- loose-release observations (absolute error >=4 counts): {frequency['loose_release_abs_gte_four_count_observations']}

## Shadow replay and authority

- frozen contract: `{shadow['contract_id']}` / `{shadow['contract_sha256']}`
- decisions: {shadow['decision_count']}; exact replay: `{shadow['exact_replay']}`
- every actionable/authorization/consumption field false: `{shadow['all_authority_fields_false']}`
- healthy DAC transition preserved inside the same raw phase epoch: `{not result['dac_epoch_continuity']['raw_phase_reset_at_healthy_dac_transition']}`

Positive excess edge count increases relative phase. A later preview must use a
negative phase-derived frequency bias to bleed positive relative phase toward
the arbitrary epoch zero.

## Claims boundary

No UTC, absolute time error, calibrated delay/uncertainty, generated-output PPS
phase, phase lock, holdover, or continuity across a lost session/reference is
claimed.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    args = parser.parse_args(argv)
    source = args.run_dir.resolve()
    for output in (args.output_json.resolve(), args.output_report.resolve()):
        if output == source or source in output.parents:
            parser.error("outputs must not be written inside the sealed source run")
    try:
        result = analyze(
            args.run_dir, profile_path=args.profile, schema_path=args.schema
        )
        _atomic_write(
            args.output_json,
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        )
        _atomic_write(args.output_report, _markdown(result))
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(args.output_report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
