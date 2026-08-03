"""Evidence-only Stage 4 candidate evaluation for PPS cumulative spans.

The tool evaluates resolution, delay, boxcar bandwidth, drift, temperature,
invalidation and conditional historical plant-gain compatibility.  It never
selects an estimator or controller parameter automatically.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import argparse
import json
import math
import tempfile
from typing import Any


TOOL_VERSION = "pps_estimator_selection_evaluation_v1"
METHOD_ID = "PPS_CUMULATIVE_SNAPSHOT_SPAN_V1"
REQUIRED_CANDIDATE_SPANS_S = (60, 120, 300, 600)
MINIMUM_STABLE_INTERVALS = 21_600


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _boxcar_3db_ratio() -> float:
    """Solve sin(pi*x)/(pi*x) == 1/sqrt(2) on 0 < x < 1."""

    lower = 0.0
    upper = 1.0
    target = 1.0 / math.sqrt(2.0)
    for _ in range(80):
        middle = (lower + upper) / 2.0
        response = math.sin(math.pi * middle) / (math.pi * middle)
        if response > target:
            lower = middle
        else:
            upper = middle
    return (lower + upper) / 2.0


def _indexed(
    values: Any, *, key_fields: tuple[str, ...], label: str
) -> dict[tuple[Any, ...], dict[str, Any]]:
    if not isinstance(values, list):
        raise ValueError(f"baseline {label} must be a list")
    output: dict[tuple[Any, ...], dict[str, Any]] = {}
    for value in values:
        if not isinstance(value, dict):
            raise ValueError(f"baseline {label} entries must be objects")
        try:
            key = tuple(value[field] for field in key_fields)
        except KeyError as exc:
            raise ValueError(f"baseline {label} entry missing {exc.args[0]}") from exc
        if key in output:
            raise ValueError(f"baseline {label} contains duplicate key {key}")
        output[key] = value
    return output


def _prior_gain(prior: dict[str, Any]) -> dict[str, float]:
    try:
        response = prior["plant_response"]
        slope = response["local_slope"]
        uncertainty = slope["uncertainty"]
        voltage_per_code = prior["control_path"]["estimated_v_per_code"]
        nominal = slope["hz_per_code"]
        minimum = uncertainty["hz_per_v_min"] * voltage_per_code
        maximum = uncertainty["hz_per_v_max"] * voltage_per_code
        temperature = response["applicability"]["temperature_range_c"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"prior plant model missing gain/applicability field: {exc}") from exc
    values = {
        "minimum_hz_per_code": float(minimum),
        "nominal_hz_per_code": float(nominal),
        "maximum_hz_per_code": float(maximum),
        "temperature_min_c": float(temperature["min_c"]),
        "temperature_max_c": float(temperature["max_c"]),
        "settling_t95_min_s": float(response["settling_evidence"]["t95_s_min"]),
        "settling_t95_max_s": float(response["settling_evidence"]["t95_s_max"]),
    }
    if not (
        0 < values["minimum_hz_per_code"]
        <= values["nominal_hz_per_code"]
        <= values["maximum_hz_per_code"]
    ):
        raise ValueError("prior plant gain range/sign is invalid")
    return values


def evaluate_selection_data(
    baseline: dict[str, Any], prior_model: dict[str, Any]
) -> dict[str, Any]:
    if baseline.get("method_id") != METHOD_ID:
        raise ValueError("baseline estimator method does not match Stage 4 method")
    if baseline.get("source_immutability_verified") is not True:
        raise ValueError("baseline source immutability was not verified")
    analysis = baseline.get("analysis_interval")
    if not isinstance(analysis, dict) or analysis.get("status") != (
        "manifest_declared_stable_interval"
    ):
        raise ValueError("baseline is not restricted to a declared stable interval")
    interval_count = analysis.get("interval_count")
    if (
        isinstance(interval_count, bool)
        or not isinstance(interval_count, int)
        or interval_count < MINIMUM_STABLE_INTERVALS
    ):
        raise ValueError("baseline does not contain the required 21,600 stable intervals")
    if baseline.get("invalid_interval_count") != 0:
        raise ValueError("declared stable interval contains invalid evidence")

    statistics_by_key = _indexed(
        baseline.get("span_statistics"),
        key_fields=("mode", "span_seconds"),
        label="span_statistics",
    )
    withheld_by_span = _indexed(
        baseline.get("withheld_span_windows"),
        key_fields=("span_seconds",),
        label="withheld_span_windows",
    )
    drift_root = baseline.get("linear_drift")
    temperature_root = baseline.get("temperature_association")
    if not isinstance(drift_root, dict) or not isinstance(temperature_root, dict):
        raise ValueError("baseline per-span drift/temperature evidence is missing")
    drift_by_key = _indexed(
        drift_root.get("by_estimator_span"),
        key_fields=("mode", "span_seconds"),
        label="linear_drift.by_estimator_span",
    )
    temperature_by_key = _indexed(
        temperature_root.get("by_estimator_span"),
        key_fields=("mode", "span_seconds"),
        label="temperature_association.by_estimator_span",
    )
    available_spans = sorted(
        int(span_s)
        for mode, span_s in statistics_by_key
        if mode == "non_overlapping"
    )
    missing_required = sorted(
        set(REQUIRED_CANDIDATE_SPANS_S) - set(available_spans)
    )
    if missing_required:
        raise ValueError(
            f"required non-overlapping span evidence missing: {missing_required}"
        )
    gain = _prior_gain(prior_model)
    raw_temperature = temperature_root.get("raw_one_second_intervals")
    current_temperature_min = (
        raw_temperature.get("temperature_min_c")
        if isinstance(raw_temperature, dict)
        else None
    )
    current_temperature_max = (
        raw_temperature.get("temperature_max_c")
        if isinstance(raw_temperature, dict)
        else None
    )
    prior_temperature_context_covered = (
        isinstance(current_temperature_min, (int, float))
        and not isinstance(current_temperature_min, bool)
        and isinstance(current_temperature_max, (int, float))
        and not isinstance(current_temperature_max, bool)
        and gain["temperature_min_c"] <= float(current_temperature_min)
        and float(current_temperature_max) <= gain["temperature_max_c"]
    )

    boxcar_ratio = _boxcar_3db_ratio()
    candidates: list[dict[str, Any]] = []
    for span_s in available_spans:
        key = ("non_overlapping", span_s)
        try:
            stats = statistics_by_key[key]
            withheld = withheld_by_span[(span_s,)]
            drift = drift_by_key[key]
            temperature = temperature_by_key[key]
        except KeyError as exc:
            raise ValueError(f"required non-overlapping span evidence missing: {span_s} s") from exc
        increment = float(stats["count_increment_hz"])
        observed_range = float(stats["range_hz"])
        if increment <= 0 or observed_range < 0:
            raise ValueError(f"invalid resolution evidence for {span_s} s")
        expected_independent = interval_count // span_s
        if stats.get("eligible_estimate_count") != expected_independent:
            raise ValueError(
                f"{span_s} s independent estimate count does not cover the declared interval"
            )
        if withheld.get("withheld_window_count") != 0:
            raise ValueError(f"{span_s} s span has withheld stable-interval windows")
        detection_floor = observed_range + increment
        # This is a historical detectability comparison, never current plant
        # authority.  Run 020 reports negligible residual association with its
        # near-air proxy (r=-0.032782, simple R^2=0.00107466) but strong
        # temperature/time confounding (r=0.960077), so leaving its recorded
        # temperature context is a warning against model extrapolation rather
        # than a reason to erase the measured historical gain comparison.
        conditional_step = math.ceil(
            detection_floor / gain["minimum_hz_per_code"]
        )
        candidates.append(
            {
                "span_seconds": span_s,
                "required_stage4_candidate": span_s
                in REQUIRED_CANDIDATE_SPANS_S,
                "shorter_diagnostic_candidate": span_s
                < min(REQUIRED_CANDIDATE_SPANS_S),
                "independent_decision_cadence_s": span_s,
                "independent_decision_cadence_status": "candidate non-overlapping estimator epoch only; not a selected or proposed controller cadence",
                "clean_time_to_first_estimate_s": withheld[
                    "clean_time_to_first_estimate_s"
                ],
                "fresh_support_recovery_time_s": withheld[
                    "fresh_support_recovery_time_s"
                ],
                "startup_and_recovery_provenance": {
                    "disposition": "architecture screen",
                    "source_hierarchy": 4,
                    "source": "PPS_CUMULATIVE_SNAPSHOT_SPAN_V1 fail-closed fresh-support semantics",
                    "calculation": "a T-second estimate requires T new contiguous accepted one-second intervals after startup or invalidation",
                    "applicability": "estimator support only; plant settling and controller inhibition add separately",
                },
                "boxcar_group_delay_s": span_s / 2.0,
                "boxcar_minus_3db_bandwidth_hz": boxcar_ratio / span_s,
                "boxcar_first_null_hz": 1.0 / span_s,
                "delay_and_bandwidth_provenance": {
                    "disposition": "characterization reference",
                    "source_hierarchy": 4,
                    "source": "documented rectangular-window calculation from the selected candidate span; not a measured plant bandwidth or control-performance requirement",
                    "calculation": "group_delay=T/2; -3 dB bandwidth=x/T where sin(pi*x)/(pi*x)=1/sqrt(2); first_null=1/T",
                },
                "count_increment_hz": increment,
                "count_increment_provenance": {
                    "disposition": "architecture screen",
                    "source_hierarchy": 4,
                    "source": "PPS_CUMULATIVE_SNAPSHOT_SPAN_V1 method contract derived from accepted adjacent integer counts and nominal accepted PPS intervals",
                    "calculation": "one counted edge divided by T nominal accepted one-second intervals gives 1/T Hz",
                    "uncertainty_status": "unavailable; resolution is not calibrated uncertainty",
                },
                "observed_nonoverlapping_range_hz": observed_range,
                "observed_robust_scale_hz": stats[
                    "robust_scale_1p4826_mad_hz"
                ],
                "observed_population_stddev_hz": stats[
                    "population_stddev_hz"
                ],
                "empirical_detection_floor_hz": detection_floor,
                "empirical_detection_floor_rule": "full observed non-overlapping baseline range plus one representable count increment; explicitly conservative finite-run engineering assumption, not statistical or calibrated uncertainty",
                "empirical_detection_floor_provenance": {
                    "disposition": "model-applicability bound",
                    "source_hierarchy": [2, 4, 5],
                    "source": "direct Stage 3 assembled-rig fixed-code observations plus documented arithmetic; adding one increment is an explicitly labelled conservative engineering assumption because calibrated combined uncertainty is unavailable",
                    "calculation": "observed full non-overlapping range + 1/T Hz",
                    "control_authority": False,
                },
                "conditional_smallest_step_codes_at_prior_minimum_gain": conditional_step,
                "conditional_predicted_response_hz_at_prior_minimum_gain": (
                    conditional_step * gain["minimum_hz_per_code"]
                    if conditional_step is not None
                    else None
                ),
                "code_domain_resolution_status": (
                    "conditional_historical_comparison_only"
                    if prior_temperature_context_covered
                    else "conditional_historical_comparison_only_outside_recorded_temperature_context"
                ),
                "code_domain_control_authority": False,
                "conditional_code_domain_provenance": {
                    "disposition": "characterization reference",
                    "source_hierarchy": 3,
                    "source": "sealed Run 020 CX317 evidence, same physical topology but different counter backend and estimator method",
                    "calculation": "ceil(empirical_detection_floor_hz / historical_minimum_gain_hz_per_code)",
                    "applicability": "historical comparison only; not a current PPS-gated plant specification or controller-step authority",
                },
                "historical_coarse_t95_plus_fresh_support_s": gain[
                    "settling_t95_max_s"
                ]
                + span_s,
                "settling_comparison_status": "characterization_only; coarse prior t95 is not a tuned time constant or controller cadence",
                "settling_comparison_provenance": {
                    "disposition": "characterization reference",
                    "source_hierarchy": [3, 4],
                    "source": "sealed Run 020 CX317 coarse settling observation on OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE plus candidate estimator fresh-support duration",
                    "calculation": "historical maximum observed t95 + T seconds fresh estimator support",
                    "applicability": "backend/method-mismatched planning comparison only; no plant-model, settling-exclusion, or cadence authority",
                },
                "independent_estimate_count": stats["eligible_estimate_count"],
                "overlapping_estimate_count": statistics_by_key[
                    ("overlapping", span_s)
                ]["eligible_estimate_count"],
                "overlapping_lag1_correlation": statistics_by_key[
                    ("overlapping", span_s)
                ]["lag1_correlation"],
                "drift": drift,
                "temperature_association": temperature,
                "calibrated_resolution_status": "unavailable",
            }
        )
    return {
        "schema_version": 1,
        "tool_version": TOOL_VERSION,
        "method_id": METHOD_ID,
        "baseline_config_hash": baseline.get("config_hash"),
        "required_stable_intervals": MINIMUM_STABLE_INTERVALS,
        "stable_duration_provenance": {
            "disposition": "architecture screen",
            "source_hierarchy": 5,
            "source": "immutable Stage 3 programme prompt minimum six-hour stable capture requirement",
            "calculation": "6 h * 3600 s/h = 21,600 nominal accepted one-second intervals",
            "applicability": "explicitly conservative programme evidence-volume assumption where no physically sufficient observation duration was previously established; it is not a derived controller-performance, thermal-equilibrium, or calibrated-stability threshold",
        },
        "observed_stable_intervals": interval_count,
        "required_candidate_spans_s": list(REQUIRED_CANDIDATE_SPANS_S),
        "evaluated_spans_s": available_spans,
        "candidate_span_provenance": {
            "disposition": "characterization reference",
            "source_hierarchy": 5,
            "source": "immutable Stage 2/4 programme prompts",
            "applicability": "programme-defined exploration grid only; no candidate span is an acceptance requirement or selected estimator/controller policy until measured Stage 3 noise, drift, delay, recovery and conditional plant comparison are evaluated",
        },
        "boxcar_minus_3db_ratio": boxcar_ratio,
        "boxcar_bandwidth_derivation": "positive root x of sin(pi*x)/(pi*x)=1/sqrt(2); bandwidth=x/span",
        "historical_prior": {
            **gain,
            "disposition": "characterization reference",
            "source_hierarchy": 3,
            "stage3_temperature_within_recorded_run020_context": prior_temperature_context_covered,
            "stage3_temperature_min_c": current_temperature_min,
            "stage3_temperature_max_c": current_temperature_max,
            "temperature_evidence": {
                "run020_residual_correlation": -0.032782,
                "run020_simple_r_squared": 0.00107466,
                "run020_temperature_elapsed_correlation": 0.960077,
                "source": "sealed Run 020 h1_characterization_summary.md, Near-VCOCXO Temperature",
                "interpretation": "near-air temperature showed negligible residual association but was strongly confounded with elapsed time; Run 020 did not establish a thermal model",
            },
            "status": "characterization_reference_only; backend/method differ, the recorded temperature range is context rather than a demonstrated sensitivity bound, and this prior has no current plant-model or control authority",
        },
        "candidates": candidates,
        "selection_status": "not_selected_by_evaluation_tool",
        "selection_authority": "formal Stage 4 report using sealed Stage 3 evidence",
        "actuation_authority": False,
    }


def evaluate_selection(
    baseline_path: Path, prior_model_path: Path, output_path: Path
) -> Path:
    source_hashes = {
        "stage3_baseline_analysis": _sha256_file(baseline_path),
        "historical_prior_model": _sha256_file(prior_model_path),
    }
    result = evaluate_selection_data(
        _load_object(baseline_path), _load_object(prior_model_path)
    )
    result["source_evidence"] = {
        "stage3_baseline_analysis": {
            "path": str(baseline_path),
            "sha256": source_hashes["stage3_baseline_analysis"],
        },
        "historical_prior_model": {
            "path": str(prior_model_path),
            "sha256": source_hashes["historical_prior_model"],
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(output_path)
    if source_hashes != {
        "stage3_baseline_analysis": _sha256_file(baseline_path),
        "historical_prior_model": _sha256_file(prior_model_path),
    }:
        output_path.unlink(missing_ok=True)
        raise RuntimeError("selection-evaluation source changed while writing")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate Stage 4 estimator spans without selecting or actuating."
    )
    parser.add_argument("baseline_analysis", type=Path)
    parser.add_argument("historical_prior_model", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        destination = evaluate_selection(
            args.baseline_analysis, args.historical_prior_model, args.output
        )
    except (FileNotFoundError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
