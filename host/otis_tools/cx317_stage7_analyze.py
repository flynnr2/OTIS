"""Frozen offline exit-gate analyzer for Stage 7 Parts A and B."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path
import argparse
import json
import math
import statistics
import tempfile
from typing import Any

from .contracts import CsvValidationContext, validate_csv
from .cx317_active_campaign import (
    _read_csv,
    validate_transaction_history,
    validate_transaction_row,
)
from .cx317_bounded_active import ResponseClassifier
from .cx317_i_only_preview_replay import IOnlyPreviewEngine, Observation, load_post_campaign_policy
from .cx317_stage7_part_b_matrix import STAGE7_PROMPT, STAGE7_PROMPT_SHA256
from .cx317_stage7_part_b_rehearsal import SUPERVISOR_PATH, TOOL_PATH
from .cx317_stage6_dual_core_analyze import _estimator_parity, _rows_for
from .cx317_stage6_live_analyze import (
    SERIALIZED_12_DECIMAL_HALF_UNIT,
    TICKS_PER_SECOND,
    _check_continuity,
    _host_markers,
    _one_marker,
    _serialized_difference,
)
from .cx317_stage7_shadow import (
    ShadowContract,
    ShadowObservation,
    load_contract,
    run_shadow,
)
from .cx317_stage7_shadow_monitor import (
    AUTHORITATIVE,
    SHADOW,
    SHADOW_FIELDS,
    _actual_state,
    _selected_rows,
    refresh,
)
from .cx317_stage7_supervisor import (
    PART_A_QUALIFIED_TIMEOUT_S,
    PART_A_SERVICE_LOAD_QUERIES,
    PART_B_CLEARANCE_GRACE_S,
    PART_B_DURATION_S,
    PART_B_SERVICE_LOAD_STARTS_S,
    STAGE7_QUALIFICATION_TIMEOUT_S,
    load_stage7_spec,
)
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, load_manifest
from .timebase import unwrap_ticks


REPO_ROOT = Path(__file__).resolve().parents[2]
PART_A_STABILITY_MIN_OBSERVATIONS = 36
PART_A_STABILITY_MIN_DURATION_S = 6 * 60 * 60
HISTORICAL_REPLAYS = (
    (
        "campaign_a_v3",
        REPO_ROOT
        / "runs/cx317_bounded_closed_loop_acquisition/"
        "campaign_20260803T080615Z/stage4/"
        "campaign_a_v3_20260803T183120Z",
        0xA950,
        16,
        336,
        "reports/campaign_a_v3_analysis_v1.json",
    ),
    (
        "campaign_b",
        REPO_ROOT
        / "runs/cx317_bounded_closed_loop_acquisition/"
        "campaign_20260803T080615Z/stage5/"
        "campaign_b_20260804T022822Z",
        0xA800,
        8,
        168,
        "reports/campaign_b_analysis_v1.json",
    ),
)


@dataclass(frozen=True)
class Check:
    identifier: str
    passed: bool
    evidence: str


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _bool(value: str) -> bool:
    if value not in {"true", "false"}:
        raise ValueError(f"invalid serialized bool {value!r}")
    return value == "true"


def _latest_health_rows(
    rows: list[dict[str, str]],
) -> dict[tuple[str, str], str]:
    latest: dict[tuple[str, str], str] = {}
    for row in rows:
        if row.get("record_type") == "STS":
            latest[(row.get("component", ""), row.get("status_key", ""))] = (
                row.get("status_value", "")
            )
    return latest


def _mapped_state(value: str) -> str:
    return {
        "WARMUP_INHIBIT": "WARMUP_INHIBIT",
        "QUALIFYING": "QUALIFYING",
        "SETTLING_INHIBIT": "SETTLE_PREVIEW",
        "TRACKING": "LOCKED_PREVIEW",
        "FAULT": "FAULT",
        "ABORTED": "FAULT",
        "OUT_OF_MODEL_HOLD": "OUT_OF_MODEL_HOLD",
    }[value]


def _controller_parity(
    rows: list[dict[str, str]], estimates: list[dict[str, str]]
) -> tuple[Check, dict[str, Any]]:
    policy = load_post_campaign_policy()
    engine = IOnlyPreviewEngine(policy)
    by_id = {row["estimate_id"]: row for row in estimates}
    timestamps, wraps = unwrap_ticks(
        [int(row["decision_timestamp_ticks"]) for row in rows]
    )
    valid = [int(row["control_seq"]) for row in rows] == list(range(len(rows)))
    comparisons: list[dict[str, Any]] = []
    max_error = 0.0
    max_delta = 0.0
    for row, timestamp_ticks in zip(rows, timestamps, strict=True):
        estimate = by_id.get(row["est_input_ref"])
        error = float(estimate["frequency_error_hz"]) if estimate else None
        reason = row["decision_reason_code"]
        previous = engine.state
        host = engine.process(
            Observation(
                timestamp_s=timestamp_ticks // TICKS_PER_SECOND,
                frequency_error_hz=error,
                current_code=int(row["current_dac_code"]),
                reference_valid=reason != "reference_invalid",
                estimator_valid=reason not in {
                    "reference_invalid",
                    "estimator_invalid_or_snapshot_gap",
                },
                count_valid=reason not in {"reference_invalid", "count_invalid"},
                model_applicable=row["model_applicability"] == "applicable",
                recovery_requested=reason == "explicit_recovery_fresh_support",
                dac_epoch=reason == "dac_epoch_full_history_reset",
            )
        )
        host_error = host["frequency_error_hz"]
        error_difference = (
            0.0
            if row["frequency_error_hz"] == "" and host_error is None
            else math.inf
            if row["frequency_error_hz"] == "" or host_error is None
            else _serialized_difference(row["frequency_error_hz"], float(host_error))
        )
        host_delta = host["raw_delta_codes"]
        delta_difference = (
            0.0
            if row["raw_delta_codes"] == "" and host_delta is None
            else math.inf
            if row["raw_delta_codes"] == "" or host_delta is None
            else _serialized_difference(row["raw_delta_codes"], float(host_delta))
        )
        exact = (
            row["policy_version"] == policy.policy_id
            and row["config_hash"] == policy.config_hash
            and row["plant_model_hash"] == policy.plant_model_hash
            and row["control_state"] == _mapped_state(str(host["state"]))
            and row["previous_control_state"] == _mapped_state(previous)
            and row["decision_reason_code"] == host["reason"]
            and _bool(row["preview_available"]) == bool(host["preview_available"])
            and _bool(row["preview_only"])
            and not _bool(row["actuation_authorized"])
            and not _bool(row["actionable"])
            and error_difference <= SERIALIZED_12_DECIMAL_HALF_UNIT
            and delta_difference
            <= (abs(policy.integrator_gain) + 1.0)
            * SERIALIZED_12_DECIMAL_HALF_UNIT
        )
        if host["preview_available"]:
            exact = exact and (
                int(row["limited_delta_codes"]) == host["limited_delta_codes"]
                and int(row["proposed_dac_code"]) == host["proposed_code"]
                and _bool(row["step_limited"]) == host["step_limited"]
                and _bool(row["range_clamped"]) == host["range_clamped"]
            )
        else:
            exact = exact and all(
                row[field] == ""
                for field in (
                    "raw_delta_codes",
                    "limited_delta_codes",
                    "proposed_dac_code",
                )
            )
        valid = valid and exact
        max_error = max(max_error, error_difference)
        max_delta = max(max_delta, delta_difference)
        comparisons.append(
            {
                "control_seq": row["control_seq"],
                "firmware_reason": reason,
                "host_reason": host["reason"],
                "pass": exact,
            }
        )
    return (
        Check(
            "controller_host_firmware_exact_replay",
            valid,
            f"{len(rows)} controls; max differences {max_error:.17g} Hz/{max_delta:.17g} codes",
        ),
        {"timer_wrap_count": wraps, "comparisons": comparisons},
    )


def _transactions(
    rows: list[dict[str, str]], spec: Any, identities: dict[str, str], build_identity: str
) -> tuple[Check, dict[str, Any]]:
    validate_transaction_history(
        rows,
        spec,
        identities,
        build_identity,
        dual_core=True,
    )
    valid = [int(row["transaction_record_sequence"]) for row in rows] == list(
        range(1, len(rows) + 1)
    )
    manual = [row for row in rows if row["event"] == "manual_start"]
    valid = valid and len(manual) == 1
    if manual:
        validate_transaction_row(manual[0], spec, identities, build_identity)
    automatic = [row for row in rows if row["event"] != "manual_start"]
    by_request: dict[int, list[dict[str, str]]] = {}
    for row in automatic:
        validate_transaction_row(row, spec, identities, build_identity)
        by_request.setdefault(int(row["request_sequence"]), []).append(row)
    expected_events = ["request_created", "core0_accepted", "application", "response"]
    applications = [row for row in automatic if row["event"] == "application"]
    complete_request_groups = 0
    latencies: list[dict[str, int]] = []
    response_replays: list[dict[str, Any]] = []
    response_classifier = ResponseClassifier()
    for request_sequence, group in sorted(by_request.items()):
        events = [row["event"] for row in group]
        valid = valid and events == expected_events
        if events != expected_events:
            continue
        complete_request_groups += 1
        created, accepted, applied, response = group
        requested = int(created["requested_code"])
        replayed_response = response_classifier.classify(
            pre_error_hz=float(created["pre_error_hz"]),
            post_error_hz=float(response["post_error_hz"]),
            applied_delta_codes=int(created["requested_delta_codes"]),
            current_code=int(applied["applied_code"]),
            minimum_code=spec.minimum_code,
            maximum_code=spec.maximum_code,
            evidence_healthy=True,
        )
        response_exact = (
            response["response_class"] == replayed_response.classification.value
            and response["reason"] == replayed_response.reason
            and replayed_response.observed_response_hz is not None
            and replayed_response.cumulative_response_hz is not None
            and math.isclose(
                float(response["observed_response_hz"]),
                replayed_response.observed_response_hz,
                rel_tol=0.0,
                abs_tol=5e-9,
            )
            and math.isclose(
                float(response["cumulative_response_hz"]),
                replayed_response.cumulative_response_hz,
                rel_tol=0.0,
                abs_tol=5e-9,
            )
            and int(response["consecutive_indeterminate"])
            == replayed_response.consecutive_indeterminate
        )
        exact = (
            int(created["accepted_code"]) == 0
            and int(accepted["accepted_code"]) == requested
            and int(applied["applied_code"]) == requested
            and int(response["applied_code"]) == requested
            and applied["i2c_ok"] == "true"
            and applied["clamped"] == "false"
            and applied["ambiguous"] == "false"
            and applied["estimator_history_reset"] == "true"
            and all(row["actionable"] == "false" for row in group)
            and response_exact
        )
        valid = valid and exact
        latencies.append(
            {
                "request_sequence": request_sequence,
                "acceptance_latency_s": int(accepted["accepted_timestamp_s"])
                - int(created["decision_timestamp_s"]),
                "application_latency_s": int(applied["application_timestamp_s"])
                - int(accepted["accepted_timestamp_s"]),
            }
        )
        response_replays.append(
            {
                "request_sequence": request_sequence,
                "observed_class": response["response_class"],
                "replayed_class": replayed_response.classification.value,
                "observed_reason": response["reason"],
                "replayed_reason": replayed_response.reason,
                "pass": response_exact,
            }
        )
    ordinals = [int(row["correction_count"]) for row in applications]
    valid = valid and ordinals == list(range(1, len(applications) + 1))
    movements = [abs(int(row["requested_delta_codes"])) for row in applications]
    times = [int(row["application_timestamp_s"]) for row in applications]
    valid = valid and all(
        later - earlier >= 1800 for earlier, later in zip(times, times[1:])
    )
    valid = (
        valid
        and len(applications) <= spec.correction_limit
        and sum(movements) <= spec.cumulative_limit
        and all(0 < movement <= spec.maximum_step for movement in movements)
    )
    return (
        Check(
            "exact_four_phase_cross_core_transactions",
            valid,
            f"{len(applications)} applications, path {sum(movements)} codes, {complete_request_groups}/{len(by_request)} complete four-phase request groups",
        ),
        {
            "application_count": len(applications),
            "complete_request_group_count": complete_request_groups,
            "request_group_count": len(by_request),
            "path_codes": sum(movements),
            "net_movement_codes": (
                int(applications[-1]["applied_code"]) - spec.start_code
                if applications
                else 0
            ),
            "corrections": [
                {
                    "request_sequence": int(row["request_sequence"]),
                    "application_timestamp_s": int(
                        row["application_timestamp_s"]
                    ),
                    "delta_codes": int(row["requested_delta_codes"]),
                    "direction": (
                        "positive"
                        if int(row["requested_delta_codes"]) > 0
                        else "negative"
                    ),
                    "applied_code": int(row["applied_code"]),
                }
                for row in applications
            ],
            "latencies": latencies,
            "response_replays": response_replays,
            "all_response_classifications_replay_exactly": (
                complete_request_groups == len(by_request)
                and all(item["pass"] for item in response_replays)
            ),
            "final_code": int(applications[-1]["applied_code"])
            if applications
            else spec.start_code,
        },
    )


def _series_metrics(rows: list[dict[str, str]]) -> dict[str, Any]:
    values = [float(row["frequency_error_hz"]) for row in rows]
    times = [float(row["timestamp_s"]) for row in rows]
    if not values:
        return {"count": 0}
    mean = statistics.fmean(values)
    centered = [value - mean for value in values]
    gamma0 = sum(value * value for value in centered) / len(centered)
    autocorrelations: list[float] = []
    for lag in range(1, min(6, len(values) - 1) + 1):
        covariance = sum(
            centered[index] * centered[index - lag]
            for index in range(lag, len(values))
        ) / len(values)
        autocorrelations.append(covariance / gamma0 if gamma0 > 0.0 else 0.0)
    positive_sum = 0.0
    for correlation in autocorrelations:
        if correlation <= 0.0:
            break
        positive_sum += correlation
    effective_n = len(values) / (1.0 + 2.0 * positive_sum)
    lag_max = min(3, len(values) - 1)
    long_run_variance = gamma0
    for lag in range(1, lag_max + 1):
        gamma = sum(
            centered[index] * centered[index - lag]
            for index in range(lag, len(values))
        ) / len(values)
        long_run_variance += 2.0 * (1.0 - lag / (lag_max + 1.0)) * gamma
    hac_se = math.sqrt(max(0.0, long_run_variance) / len(values))
    time_mean = statistics.fmean(times)
    denominator = sum((value - time_mean) ** 2 for value in times)
    slope = (
        sum((time - time_mean) * (value - mean) for time, value in zip(times, values, strict=True))
        / denominator
        if denominator > 0.0
        else 0.0
    )
    inside = [abs(value) <= 0.006249995628992717 for value in values]
    crossings = sum(left != right for left, right in zip(inside, inside[1:]))
    longest = 0
    current = 0
    for item in inside:
        current = current + 1 if item else 0
        longest = max(longest, current)
    residences: list[dict[str, Any]] = []
    residence_start = 0
    for index in range(1, len(values) + 1):
        boundary = index == len(values)
        if not boundary:
            boundary = (
                inside[index] != inside[index - 1]
                or times[index] - times[index - 1] > 601.0
            )
        if boundary:
            first = times[residence_start]
            last = times[index - 1]
            residences.append(
                {
                    "state": "inside" if inside[index - 1] else "outside",
                    "estimate_count": index - residence_start,
                    "first_timestamp_s": first,
                    "last_timestamp_s": last,
                    "continuous_residence_s": last - first + 600.0,
                }
            )
            residence_start = index
    return {
        "count": len(values),
        "mean_hz": mean,
        "median_hz": statistics.median(values),
        "minimum_hz": min(values),
        "maximum_hz": max(values),
        "authoritative_inside_fraction": sum(inside) / len(inside),
        "authoritative_boundary_crossings": crossings,
        "longest_inside_residence_estimates": longest,
        "longest_inside_continuous_residence_s": max(
            (
                item["continuous_residence_s"]
                for item in residences
                if item["state"] == "inside"
            ),
            default=0.0,
        ),
        "residences": residences,
        "newey_west_lag": lag_max,
        "newey_west_mean_standard_error_hz": hac_se,
        "autocorrelation_lags_1_to_6": autocorrelations,
        "effective_sample_size_initial_positive_acf": effective_n,
        "linear_drift_hz_per_s": slope,
        "successive_estimates_assumed_independent": False,
    }


def _pearson(rows: list[dict[str, str]], field: str) -> dict[str, Any]:
    pairs: list[tuple[float, float]] = []
    for row in rows:
        try:
            context = float(row[field])
            error = float(row["frequency_error_hz"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(context) and math.isfinite(error):
            pairs.append((context, error))
    if len(pairs) < 3:
        return {"count": len(pairs), "pearson_r": None}
    x_mean = statistics.fmean(item[0] for item in pairs)
    y_mean = statistics.fmean(item[1] for item in pairs)
    numerator = sum(
        (x - x_mean) * (y - y_mean) for x, y in pairs
    )
    x_power = sum((x - x_mean) ** 2 for x, _ in pairs)
    y_power = sum((y - y_mean) ** 2 for _, y in pairs)
    correlation = (
        numerator / math.sqrt(x_power * y_power)
        if x_power > 0.0 and y_power > 0.0
        else None
    )
    return {"count": len(pairs), "pearson_r": correlation}


def _context_analysis(rows: list[dict[str, str]]) -> dict[str, Any]:
    by_code: dict[str, list[dict[str, str]]] = {}
    by_service: dict[str, list[dict[str, str]]] = {}
    by_direction: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        by_code.setdefault(row["actual_applied_code"], []).append(row)
        by_service.setdefault(row["service_load_state"], []).append(row)
        by_direction.setdefault(
            (
                row["actual_applied_code"],
                row["preceding_actual_correction_direction"],
            ),
            [],
        ).append(float(row["frequency_error_hz"]))

    code_segments: list[tuple[str, int, int]] = []
    if rows:
        segment_code = rows[0]["actual_applied_code"]
        segment_start = 0
        for index, row in enumerate(rows[1:], 1):
            if row["actual_applied_code"] != segment_code:
                code_segments.append((segment_code, segment_start, index - 1))
                segment_code = row["actual_applied_code"]
                segment_start = index
        code_segments.append((segment_code, segment_start, len(rows) - 1))
    segment_counts: dict[str, int] = {}
    for code, _, _ in code_segments:
        segment_counts[code] = segment_counts.get(code, 0) + 1

    paired: dict[str, Any] = {}
    for code in sorted(by_code, key=int):
        positive = by_direction.get((code, "positive"), [])
        negative = by_direction.get((code, "negative"), [])
        paired[code] = {
            "positive_preceding_count": len(positive),
            "negative_preceding_count": len(negative),
            "positive_preceding_mean_hz": (
                statistics.fmean(positive) if positive else None
            ),
            "negative_preceding_mean_hz": (
                statistics.fmean(negative) if negative else None
            ),
            "direction_paired_difference_hz": (
                statistics.fmean(positive) - statistics.fmean(negative)
                if positive and negative
                else None
            ),
            "adequate_for_hysteresis_claim": (
                len(positive) >= 2 and len(negative) >= 2
            ),
        }

    qualification = [row["gnss_qualification"] == "qualified" for row in rows]
    outage_runs: list[int] = []
    outage = 0
    for qualified in qualification:
        if qualified:
            if outage:
                outage_runs.append(outage)
                outage = 0
        else:
            outage += 1
    if outage:
        outage_runs.append(outage)

    return {
        "fixed_code_residuals": {
            code: {
                **_series_metrics(group),
                "distinct_residence_segments": segment_counts.get(code, 0),
                "naturally_revisited": segment_counts.get(code, 0) > 1,
            }
            for code, group in sorted(by_code.items(), key=lambda item: int(item[0]))
        },
        "service_load_residuals": {
            state: _series_metrics(group)
            for state, group in sorted(by_service.items())
        },
        "gnss_qualification": {
            "observation_count": len(rows),
            "qualified_count": sum(qualification),
            "qualified_fraction": (
                sum(qualification) / len(rows) if rows else None
            ),
            "unqualified_run_lengths_estimates": outage_runs,
            "longest_unqualified_run_estimates": max(outage_runs, default=0),
        },
        "naturally_observed_direction_paired_hysteresis": paired,
        "hysteresis_claim": (
            "direction_paired_support_available"
            if any(
                value["adequate_for_hysteresis_claim"]
                for value in paired.values()
            )
            else "unresolved_inadequate_natural_direction_paired_support"
        ),
        "environment_associations_noncausal": {
            "temperature_c": _pearson(rows, "temperature_c"),
            "relative_humidity_pct": _pearson(
                rows, "relative_humidity_pct"
            ),
            "pressure_pa": _pearson(rows, "pressure_pa"),
            "causal_claim": False,
        },
    }


def _shadow_context_sensitivity(
    authoritative: list[dict[str, str]], shadow: list[dict[str, str]]
) -> dict[str, Any]:
    context = {
        row["observation_sequence"]: row for row in authoritative
    }
    candidates: dict[str, list[dict[str, str]]] = {}
    for row in shadow:
        candidates.setdefault(row["candidate_id"], []).append(row)
    result: dict[str, Any] = {}
    for candidate, rows in sorted(candidates.items()):
        by_gnss: dict[str, dict[str, int]] = {}
        by_service: dict[str, dict[str, int]] = {}
        by_elapsed: dict[str, dict[str, int]] = {}
        contextual_errors: list[dict[str, str]] = []
        for row in rows:
            observation = context[row["observation_sequence"]]
            contextual_errors.append(
                {
                    "frequency_error_hz": row[
                        "counterfactual_error_hz"
                    ],
                    "temperature_c": observation["temperature_c"],
                    "relative_humidity_pct": observation[
                        "relative_humidity_pct"
                    ],
                    "pressure_pa": observation["pressure_pa"],
                }
            )
            elapsed = int(observation["elapsed_since_actual_dac_s"])
            elapsed_band = (
                "lt_1800_s"
                if elapsed < 1800
                else "1800_to_7199_s"
                if elapsed < 7200
                else "ge_7200_s"
            )
            write = row["counterfactual_write"] == "true"
            for collection, key in (
                (by_gnss, observation["gnss_qualification"]),
                (by_service, observation["service_load_state"]),
                (by_elapsed, elapsed_band),
            ):
                bucket = collection.setdefault(
                    key, {"observations": 0, "counterfactual_writes": 0}
                )
                bucket["observations"] += 1
                bucket["counterfactual_writes"] += int(write)
        result[candidate] = {
            "by_gnss_qualification": by_gnss,
            "by_service_load_state": by_service,
            "by_elapsed_since_actual_dac": by_elapsed,
            "environment_associations": {
                "temperature_c": _pearson(
                    contextual_errors, "temperature_c"
                ),
                "relative_humidity_pct": _pearson(
                    contextual_errors, "relative_humidity_pct"
                ),
                "pressure_pa": _pearson(
                    contextual_errors, "pressure_pa"
                ),
            },
            "causal_claim": False,
        }
    return result


def _row_bool(row: dict[str, Any], field: str) -> bool:
    value = row[field]
    if isinstance(value, bool):
        return value
    if value in {"true", "false"}:
        return value == "true"
    raise ValueError(f"invalid shadow bool {field}={value!r}")


def _candidate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    finite_rows = [
        row
        for row in rows
        if math.isfinite(float(row["counterfactual_error_hz"]))
    ]
    temporal = _series_metrics(
        [
            {
                "frequency_error_hz": str(row["counterfactual_error_hz"]),
                "timestamp_s": str(row["timestamp_s"]),
            }
            for row in finite_rows
        ]
    )
    states = [row["band_state_after"] for row in rows]
    timestamps = [int(row["timestamp_s"]) for row in rows]
    inside_residences: list[float] = []
    start: int | None = None
    for index in range(len(rows) + 1):
        is_inside = index < len(rows) and states[index] == "INSIDE"
        continuous = (
            index == 0
            or index == len(rows)
            or timestamps[index] - timestamps[index - 1] <= 601
        )
        if is_inside and start is None:
            start = index
        if start is not None and (
            not is_inside or (index > start and not continuous)
        ):
            end = index - 1
            inside_residences.append(
                float(timestamps[end] - timestamps[start] + 600)
            )
            start = index if is_inside else None
    errors = [abs(float(row["counterfactual_error_hz"])) for row in finite_rows]
    terminal = rows[-1] if rows else None
    first_inside = next(
        (index for index, state in enumerate(states) if state == "INSIDE"),
        None,
    )
    transitions = [row.get("transition") for row in rows]
    return {
        "observations": len(rows),
        "entry_events": sum(item == "outside_to_inside" for item in transitions),
        "release_events": sum(item == "inside_to_outside" for item in transitions),
        "boundary_churn_count": sum(bool(item) for item in transitions),
        "time_to_first_inside_residence_s": (
            timestamps[first_inside] - timestamps[0]
            if first_inside is not None and timestamps
            else None
        ),
        "continuous_inside_residence_s": inside_residences,
        "longest_continuous_inside_residence_s": max(
            inside_residences, default=0.0
        ),
        "inside_occupancy_fraction": (
            sum(state == "INSIDE" for state in states) / len(states)
            if states
            else None
        ),
        "counterfactual_corrections": (
            int(terminal["correction_count"]) if terminal else 0
        ),
        "sum_absolute_path_codes": (
            int(terminal["path_codes"]) if terminal else 0
        ),
        "net_movement_codes": (
            int(terminal["net_movement_codes"]) if terminal else 0
        ),
        "alternating_correction_count": (
            int(terminal["alternating_correction_count"])
            if terminal
            else 0
        ),
        "clamp_approach_count": sum(
            _row_bool(row, "range_clamped") for row in rows
        ),
        "dither_hold_count": sum(
            row["state_after"] == "DITHER_HOLD"
            and (
                index == 0
                or rows[index - 1]["state_after"] != "DITHER_HOLD"
            )
            for index, row in enumerate(rows)
        ),
        "budget_hold_count": sum(
            row["state_after"] == "BUDGET_HOLD"
            and (
                index == 0
                or rows[index - 1]["state_after"] != "BUDGET_HOLD"
            )
            for index, row in enumerate(rows)
        ),
        "median_absolute_counterfactual_error_hz": (
            statistics.median(errors) if errors else None
        ),
        "rms_counterfactual_error_hz": (
            math.sqrt(statistics.fmean(value * value for value in errors))
            if errors
            else None
        ),
        "linear_drift_hz_per_s": temporal.get("linear_drift_hz_per_s"),
        "autocorrelation_lags_1_to_6": temporal.get(
            "autocorrelation_lags_1_to_6", []
        ),
        "newey_west_lag": temporal.get("newey_west_lag"),
        "newey_west_mean_standard_error_hz": temporal.get(
            "newey_west_mean_standard_error_hz"
        ),
        "effective_sample_size": temporal.get(
            "effective_sample_size_initial_positive_acf"
        ),
        "terminal_state": terminal["state_after"] if terminal else "unavailable",
        "successive_estimates_assumed_independent": False,
    }


def _candidate_metric_map(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        candidates.setdefault(str(row["candidate_id"]), []).append(row)
    return {
        candidate: _candidate_metrics(group)
        for candidate, group in sorted(candidates.items())
    }


def _candidate_comparisons(
    rows: list[dict[str, Any]], *, post_part_b: bool
) -> dict[str, Any]:
    by_candidate: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_candidate.setdefault(str(row["candidate_id"]), []).append(row)
    baseline = by_candidate.get("v2_symmetric_baseline", [])
    baseline_metrics = _candidate_metrics(baseline)
    result: dict[str, Any] = {}
    for candidate, candidate_rows in sorted(by_candidate.items()):
        if len(candidate_rows) != len(baseline):
            raise ValueError("shadow candidates do not share exact observations")
        improvements = [
            abs(float(base["counterfactual_error_hz"]))
            - abs(float(item["counterfactual_error_hz"]))
            for base, item in zip(baseline, candidate_rows, strict=True)
        ]
        improvement_metrics = _series_metrics(
            [
                {
                    "frequency_error_hz": str(value),
                    "timestamp_s": str(row["timestamp_s"]),
                }
                for value, row in zip(
                    improvements, candidate_rows, strict=True
                )
            ]
        )
        mean = improvement_metrics.get("mean_hz", 0.0)
        standard_error = improvement_metrics.get(
            "newey_west_mean_standard_error_hz", 0.0
        )
        lower = mean - 1.96 * standard_error
        upper = mean + 1.96 * standard_error
        metrics = _candidate_metrics(candidate_rows)
        extra_corrections = (
            metrics["counterfactual_corrections"]
            - baseline_metrics["counterfactual_corrections"]
        )
        extra_path = (
            metrics["sum_absolute_path_codes"]
            - baseline_metrics["sum_absolute_path_codes"]
        )
        extra_churn = (
            metrics["boundary_churn_count"]
            - baseline_metrics["boundary_churn_count"]
        )
        extra_alternations = (
            metrics["alternating_correction_count"]
            - baseline_metrics["alternating_correction_count"]
        )
        result[candidate] = {
            "mean_absolute_error_improvement_hz": mean,
            "median_absolute_error_improvement_hz": statistics.median(
                improvements
            )
            if improvements
            else None,
            "paired_newey_west_95pct_interval_hz": [lower, upper],
            "paired_hac_interval_excludes_zero_in_favour_of_candidate": (
                lower > 0.0
            ),
            "extra_corrections_vs_v2": extra_corrections,
            "extra_path_codes_vs_v2": extra_path,
            "extra_boundary_churn_vs_v2": extra_churn,
            "extra_alternations_vs_v2": extra_alternations,
            "post_part_b_recommendation_eligible_on_stage7_data_only": (
                post_part_b
                and candidate != "v2_symmetric_baseline"
                and metrics["dither_hold_count"] == 0
                and metrics["budget_hold_count"] == 0
                and metrics["clamp_approach_count"] == 0
                and extra_corrections <= 4
                and extra_path <= 84
                and extra_churn <= 4
                and extra_alternations <= 1
                and bool(improvements)
                and statistics.median(improvements)
                >= 0.0016666666666666668
                and lower > 0.0
            ),
            "automatic_adoption": False,
        }
    return result


def _shadow_observations(
    rows: list[dict[str, str]],
) -> list[ShadowObservation]:
    return [
        ShadowObservation(
            observation_sequence=int(row["observation_sequence"]),
            estimate_id=row["estimate_id"],
            timestamp_s=int(row["timestamp_s"]),
            frequency_error_hz=float(row["frequency_error_hz"]),
            actual_applied_code=int(row["actual_applied_code"]),
            actual_dac_epoch=int(row["actual_dac_epoch"]),
            eligible=row["eligible"] == "true",
        )
        for row in rows
    ]


def _gain_sensitivity(
    authoritative: list[dict[str, str]],
    *,
    part: str,
    start_code: int,
    contract: ShadowContract,
) -> dict[str, Any]:
    observations = _shadow_observations(authoritative)
    result: dict[str, Any] = {}
    for gain in (contract.gain_min, contract.gain_nominal, contract.gain_max):
        sensitivity_contract = replace(contract, gain_nominal=gain)
        decisions = run_shadow(
            observations,
            contract=sensitivity_contract,
            part=part,
            start_code=start_code,
        )
        result[f"{gain:.18g}"] = _candidate_metric_map(
            [asdict(item) for item in decisions]
        )
    return result


def _historical_shadow_replays() -> tuple[Check, dict[str, Any]]:
    contract = load_contract()
    all_exact = True
    output: dict[str, Any] = {}
    for (
        label,
        run_dir,
        start_code,
        correction_limit,
        path_limit,
        analysis_relative,
    ) in HISTORICAL_REPLAYS:
        selected = _selected_rows(run_dir / "csv/estimates_v2.csv")
        active = _read_csv(run_dir / "csv/active_transactions_v1.csv")
        observations = [
            ShadowObservation(
                observation_sequence=index,
                estimate_id=row["estimate_id"],
                timestamp_s=int(row["source_reference_last_seq"]),
                frequency_error_hz=float(row["frequency_error_hz"]),
                actual_applied_code=_actual_state(
                    active,
                    int(row["source_reference_last_seq"]),
                    start_code,
                )[0],
                actual_dac_epoch=_actual_state(
                    active,
                    int(row["source_reference_last_seq"]),
                    start_code,
                )[1],
                eligible=True,
            )
            for index, row in enumerate(selected, 1)
        ]
        decisions = run_shadow(
            observations,
            contract=contract,
            part="part_b",
            start_code=start_code,
        )
        serialized = [asdict(item) for item in decisions]
        baseline = [
            item
            for item in decisions
            if item.candidate_id == "v2_symmetric_baseline"
            and item.counterfactual_write
        ]
        applications = [row for row in active if row["event"] == "application"]
        baseline_exact = len(baseline) == len(applications) and all(
            decision.timestamp_s == int(application["source_last_sequence"])
            and decision.limited_delta_codes
            == int(application["requested_delta_codes"])
            and decision.proposed_code == int(application["requested_code"])
            and decision.shadow_code_after == int(application["applied_code"])
            for decision, application in zip(
                baseline, applications, strict=True
            )
        )
        analysis_path = run_dir / analysis_relative
        prior_analysis = json.loads(
            analysis_path.read_text(encoding="utf-8")
        )
        prior_gate = prior_analysis.get("stage_exit_passed") is True
        baseline_metrics = _candidate_metrics(
            [
                row
                for row in serialized
                if row["candidate_id"] == "v2_symmetric_baseline"
            ]
        )
        baseline_within_original_budget = (
            baseline_metrics["counterfactual_corrections"]
            <= correction_limit
            and baseline_metrics["sum_absolute_path_codes"] <= path_limit
            and baseline_metrics["dither_hold_count"] == 0
            and baseline_metrics["budget_hold_count"] == 0
            and baseline_metrics["clamp_approach_count"] == 0
        )
        exact = prior_gate and baseline_exact and baseline_within_original_budget
        all_exact = all_exact and exact
        output[label] = {
            "run_dir": str(run_dir.relative_to(REPO_ROOT)),
            "authoritative_analysis_path": str(
                analysis_path.relative_to(REPO_ROOT)
            ),
            "authoritative_analysis_sha256": _sha256_file(analysis_path),
            "authoritative_stage_exit_passed": prior_gate,
            "selected_observations": len(observations),
            "v2_baseline_exact_application_replay": baseline_exact,
            "v2_baseline_within_original_campaign_budget": (
                baseline_within_original_budget
            ),
            "original_campaign_correction_limit": correction_limit,
            "original_campaign_path_limit_codes": path_limit,
            "candidate_metrics": _candidate_metric_map(serialized),
            "gain_sensitivity": {
                f"{gain:.18g}": _candidate_metric_map(
                    [
                        asdict(item)
                        for item in run_shadow(
                            observations,
                            contract=replace(contract, gain_nominal=gain),
                            part="part_b",
                            start_code=start_code,
                        )
                    ]
                )
                for gain in (
                    contract.gain_min,
                    contract.gain_nominal,
                    contract.gain_max,
                )
            },
            "every_counterfactual_decision_has_reason": all(
                bool(item.decision_reason) for item in decisions
            ),
            "shadow_authority": False,
        }
    return (
        Check(
            "sealed_campaign_a_b_v2_and_shadow_replay",
            all_exact,
            "both sealed authoritative exits pass and V2 baseline applications replay exactly within original budgets",
        ),
        output,
    )


def _shadow_replay(
    authoritative: list[dict[str, str]],
    shadow: list[dict[str, str]],
    part: str,
    start_code: int,
    contract: ShadowContract,
) -> tuple[Check, dict[str, Any]]:
    observations = [
        ShadowObservation(
            observation_sequence=int(row["observation_sequence"]),
            estimate_id=row["estimate_id"],
            timestamp_s=int(row["timestamp_s"]),
            frequency_error_hz=float(row["frequency_error_hz"]),
            actual_applied_code=int(row["actual_applied_code"]),
            actual_dac_epoch=int(row["actual_dac_epoch"]),
            eligible=row["eligible"] == "true",
        )
        for row in authoritative
    ]
    expected = run_shadow(
        observations, contract=contract, part=part, start_code=start_code
    )
    valid = len(shadow) == len(expected)
    for observed, replayed in zip(shadow, expected):
        expected_row = {
            **asdict(replayed),
            "part": part,
            "shadow_contract_sha256": contract.contract_sha256,
        }
        for field in SHADOW_FIELDS:
            value = expected_row[field]
            serialized = (
                "true" if value is True else "false" if value is False else "" if value is None else str(value)
            )
            actual = observed[field]
            if isinstance(value, float) and actual not in {"", "nan"}:
                valid = valid and math.isclose(
                    float(actual), value, rel_tol=0.0, abs_tol=5e-13
                )
            else:
                valid = valid and actual == serialized
        valid = valid and observed["actionable"] == "false"
        valid = valid and observed["actuation_authorized"] == "false"
        valid = valid and observed["authorization_consumed"] == "false"
    summaries = _candidate_metric_map(shadow)
    return (
        Check(
            "frozen_shadow_exact_replay_and_zero_authority",
            valid,
            f"{len(authoritative)} authoritative observations, {len(shadow)} candidate decisions",
        ),
        summaries,
    )


def analyze(run_dir: Path, *, build_manifest: Path, uf2: Path) -> tuple[Path, dict[str, Any]]:
    run_dir = run_dir.resolve()
    if (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise RuntimeError("capture still in progress")
    manifest = load_manifest(run_dir)
    if manifest.stage not in {
        "CX317_DUAL_CORE_ACTIVE_PART_A",
        "CX317_DUAL_CORE_ACTIVE_PART_B",
    } or manifest.is_template:
        raise ValueError("run is not an instantiated Stage 7 part")
    part = str(manifest.data["active_campaign"]["part"])
    start_code = int(manifest.data["active_campaign"]["start_code"])
    shadow_contract_path = REPO_ROOT / str(
        manifest.data["shadow_contract"]["path"]
    )
    shadow_contract = load_contract(shadow_contract_path)
    spec, identities = load_stage7_spec(part, start_code)
    checks: list[Check] = []

    build = json.loads(build_manifest.read_text(encoding="utf-8"))
    firmware = manifest.data["firmware"]
    artifact_ok = (
        firmware["source_state"] == "clean"
        and firmware["profile_id"] == spec.profile
        and firmware["build_manifest_sha256"] == _sha256_file(build_manifest)
        and firmware["uf2_sha256"] == _sha256_file(uf2)
        and build["provenance"]["configuration"]["sha256"]
        == firmware["configuration_sha256"]
        and build["provenance"]["source"]["sha256"]
        == firmware["source_sha256"]
        and manifest.data["shadow_contract"]["sha256"]
        == shadow_contract.contract_sha256
    )
    checks.append(
        Check(
            "exact_clean_artifact_and_frozen_contract",
            artifact_ok,
            f"profile {firmware['profile_id']}; UF2 {firmware['uf2_sha256']}",
        )
    )
    campaign = manifest.data["active_campaign"]
    expected_duration = (
        PART_A_QUALIFIED_TIMEOUT_S if part == "part_a" else PART_B_DURATION_S
    )
    expected_grace = 0 if part == "part_a" else PART_B_CLEARANCE_GRACE_S
    finite_runtime_ok = (
        int(campaign.get("qualification_timeout_s", -1))
        == STAGE7_QUALIFICATION_TIMEOUT_S
        and int(campaign.get("duration_after_qualification_s", -1))
        == expected_duration
        and int(campaign.get("post_duration_clearance_grace_s", -1))
        == expected_grace
        and int(campaign.get("maximum_wall_clock_s", -1))
        == STAGE7_QUALIFICATION_TIMEOUT_S + expected_duration + expected_grace
        and campaign.get("timeout_disposition")
        == "fail_static_abort_diagnostic_no_stage_exit"
        and (
            part != "part_b"
            or (
                bool(campaign.get("cross_layer_timeline_preflight", {}).get("checks"))
                and all(
                    value is True
                    for value in campaign[
                        "cross_layer_timeline_preflight"
                    ]["checks"].values()
                )
            )
        )
    )
    checks.append(
        Check(
            "finite_runtime_contract_bound",
            finite_runtime_ok,
            "qualification/duration/clearance maxima "
            f"{STAGE7_QUALIFICATION_TIMEOUT_S}/{expected_duration}/{expected_grace} s",
        )
    )

    if part == "part_b":
        prerequisite = manifest.data.get("prerequisite_gates", {})
        matrix_binding = manifest.data.get("part_b_matrix_binding", {})
        a1 = prerequisite.get("part_a1_fixed_code_stability", {})
        a2 = prerequisite.get("part_a2_cross_core_transaction", {})
        rehearsal = prerequisite.get(
            "part_b_accelerated_control_rehearsal", {}
        )
        a1_document = a1.get("document", {})
        a2_document = a2.get("document", {})
        rehearsal_document = rehearsal.get("document", {})
        rehearsal_bindings = rehearsal_document.get("bindings", {})
        a2_transactions = a2_document.get("transactions", {})

        def gate_file_exact(entry: dict[str, Any]) -> bool:
            try:
                path = Path(entry["path"])
                return (
                    path.is_file()
                    and _sha256_file(path) == entry["sha256"]
                )
            except (KeyError, OSError, TypeError):
                return False

        prerequisite_ok = (
            set(prerequisite)
            == {
                "part_a1_fixed_code_stability",
                "part_a2_cross_core_transaction",
                "part_b_accelerated_control_rehearsal",
            }
            and gate_file_exact(a1)
            and gate_file_exact(a2)
            and gate_file_exact(rehearsal)
            and a1_document.get("status") == "pass"
            and a1_document.get("test")
            == "part_a_fixed_code_stability"
            and a1_document.get("applicable") is True
            and bool(a1_document.get("criteria"))
            and all(
                value is True
                for value in a1_document.get("criteria", {}).values()
            )
            and a2_document.get("status") == "pass"
            and a2_document.get("part") == "part_a"
            and 1 <= int(a2_transactions.get("application_count", 0)) <= 4
            and a2_transactions.get(
                "all_response_classifications_replay_exactly"
            )
            is True
            and int(a2_transactions.get("final_code", -1)) == start_code
            and rehearsal_document.get("status") == "pass"
            and rehearsal_document.get("test")
            == "stage7_part_b_accelerated_control_rehearsal"
            and rehearsal_document.get("qualification_evidence") is False
            and rehearsal_document.get("hardware_actuation") is False
            and rehearsal_document.get("serial_or_fifo_authority") is False
            and bool(rehearsal_document.get("cases"))
            and all(
                value is True
                for value in rehearsal_document.get("cases", {}).values()
            )
            and bool(
                rehearsal_document.get("timeline_preflight", {}).get(
                    "checks"
                )
            )
            and all(
                value is True
                for value in rehearsal_document.get(
                    "timeline_preflight", {}
                ).get("checks", {}).values()
            )
            and rehearsal_bindings.get("supervisor_sha256")
            == _sha256_file(SUPERVISOR_PATH)
            and rehearsal_bindings.get("rehearsal_tool_sha256")
            == _sha256_file(TOOL_PATH)
            and rehearsal_bindings.get("stage7_prompt_sha256")
            == STAGE7_PROMPT_SHA256
            and _sha256_file(REPO_ROOT / STAGE7_PROMPT)
            == STAGE7_PROMPT_SHA256
        )
        checks.append(
            Check(
                "sealed_composite_part_a_handoff",
                prerequisite_ok,
                "embedded A1 stability and A2 transaction gates with exact "
                f"Part B start {start_code}, plus accelerated Part B rehearsal",
            )
        )
        try:
            from tools.firmware_matrix import source_input_hash

            derived_matrix_path = Path(matrix_binding["path"])
            matrix_derivation = matrix_binding["derivation"]
            matrix_ok = (
                derived_matrix_path.is_file()
                and _sha256_file(derived_matrix_path)
                == matrix_binding["sha256"]
                and matrix_derivation.get("stage7_prompt_sha256")
                == STAGE7_PROMPT_SHA256
                and int(
                    matrix_derivation.get("exact_part_b_start_code", -1)
                )
                == start_code
                and source_input_hash(matrix_path=derived_matrix_path)
                == firmware["source_sha256"]
            )
        except (KeyError, OSError, TypeError, ValueError):
            matrix_ok = False
        checks.append(
            Check(
                "derived_part_b_artifact_start_binding",
                matrix_ok,
                f"derived build matrix and artifact bind start {start_code}",
            )
        )

    for entry in manifest.files:
        path = run_dir / str(entry["path"])
        if not path.exists():
            continue
        result = validate_csv(
            path,
            CsvValidationContext(
                str(entry["contract"]),
                manifest.known_channels,
                manifest.known_domains,
                allow_rp2040_timer0_wrap=(
                    "rp2040_timer0" in manifest.known_domains
                ),
            ),
        )
        if result.errors:
            raise ValueError(f"{entry['contract']} invalid: {'; '.join(result.errors)}")

    counts = _rows_for(manifest, run_dir, "count_observations_v1")
    snapshots = _rows_for(manifest, run_dir, "pps_snapshots_v1")
    references = _rows_for(manifest, run_dir, "raw_events_v1")
    estimates = _rows_for(manifest, run_dir, "estimates_v2")
    controls = _rows_for(manifest, run_dir, "control_previews_v1")
    active = _rows_for(manifest, run_dir, "active_transactions_v1")
    health_rows = _rows_for(manifest, run_dir, "health_v1")
    dac = _rows_for(manifest, run_dir, "dac_steps_v1")

    continuity, count_by_seq = _check_continuity(counts, snapshots, references)
    checks.extend(Check(item.identifier, item.passed, item.evidence) for item in continuity)
    estimator_check, _ = _estimator_parity(estimates, count_by_seq, identities["estimator_sha256"])
    checks.append(estimator_check)
    controller_check, controller_replay = _controller_parity(controls, estimates)
    checks.append(controller_check)
    transaction_check, transactions = _transactions(
        active, spec, identities, firmware["build_identity"]
    )
    checks.append(transaction_check)

    applications = [row for row in active if row["event"] == "application"]
    exact_dac = (
        len(dac) == len(applications) + 1
        and dac[0]["event"] == "manual_apply"
        and int(dac[0]["dac_code_requested"]) == start_code
        and int(dac[0]["dac_code_applied"]) == start_code
        and all(
            row["event"] == "active_apply"
            and int(row["dac_code_requested"]) == int(application["requested_code"])
            and int(row["dac_code_applied"]) == int(application["applied_code"])
            and int(row["flags"]) == 0
            for row, application in zip(dac[1:], applications, strict=True)
        )
    )
    checks.append(
        Check(
            "single_manual_start_and_one_physical_write_per_application",
            exact_dac,
            f"{len(dac)} DAC rows for {len(applications)} automatic applications",
        )
    )

    latest = _latest_health_rows(health_rows)
    critical_high_water = int(
        latest.get(("dual_core", "critical_high_water"), "-1")
    )
    queue_ok = (
        latest.get(("dual_core", "partition_fault")) == "none"
        and latest.get(("dual_core", "fail_static")) == "false"
        and latest.get(("cx317_active", "fail_static")) == "false"
        and int(latest.get(("dual_core", "telemetry_dropped"), "-1")) == 0
        and int(latest.get(("dual_core", "observation_high_water"), "0")) > 0
        # Part B explicitly permits a stable 24-hour zero-correction pass.
        # Such a run legitimately has no actuator-critical traffic; Part A2
        # supplies the required live cross-core transaction proof.
        and (
            critical_high_water > 0
            if applications
            else part == "part_b" and critical_high_water == 0
        )
        and int(latest.get(("dual_core", "evidence_high_water"), "0")) > 0
    )
    checks.append(
        Check(
            "dual_core_queues_and_fail_static_health",
            queue_ok,
            f"partition {latest.get(('dual_core', 'partition_fault'))}; telemetry dropped {latest.get(('dual_core', 'telemetry_dropped'))}",
        )
    )

    refresh(
        run_dir,
        part=part,
        start_code=start_code,
        contract=shadow_contract,
    )
    authoritative = _read_csv(run_dir / AUTHORITATIVE)
    shadow = _read_csv(run_dir / SHADOW)
    selected = _selected_rows(run_dir / "csv/estimates_v2.csv")
    observation_ok = (
        len(authoritative) == len(selected)
        and [row["estimate_id"] for row in authoritative]
        == [row["estimate_id"] for row in selected]
        and all(
            row["shadow_contract_sha256"]
            == shadow_contract.contract_sha256
            for row in authoritative
        )
        and all(
            row["preserved_while_capture_active"] == "true"
            for row in authoritative
        )
        and all(row["eligible"] == "true" for row in authoritative)
    )
    checks.append(
        Check(
            "every_qualified_600s_estimate_preserved_with_context",
            observation_ok,
            f"{len(authoritative)}/{len(selected)} qualified observations preserved",
        )
    )
    shadow_check, shadow_summaries = _shadow_replay(
        authoritative, shadow, part, start_code, shadow_contract
    )
    checks.append(shadow_check)
    historical_check, historical_replays = _historical_shadow_replays()
    checks.append(historical_check)

    supervisor = json.loads(
        (run_dir / "reports/cx317_active_supervisor_state.json").read_text(
            encoding="utf-8"
        )
    )
    terminal = supervisor.get("terminal") or {}
    qualified = supervisor.get("qualification_started_utc")
    completed = terminal.get("utc")
    qualified_duration = (
        __import__("datetime").datetime.fromisoformat(
            completed.replace("Z", "+00:00")
        ).timestamp()
        - __import__("datetime").datetime.fromisoformat(
            qualified.replace("Z", "+00:00")
        ).timestamp()
        if qualified and completed
        else 0.0
    )
    if part == "part_a":
        schedule_ok = (
            terminal.get("result") == "healthy_stop"
            and qualified_duration <= PART_A_QUALIFIED_TIMEOUT_S + 1.0
            and int(supervisor.get("response_count", 0)) >= 1
            and int(supervisor.get("response_count", 0)) <= 4
            and supervisor.get("part_a_service_load_complete") is True
            and int(supervisor.get("part_a_service_load_sent", 0))
            == PART_A_SERVICE_LOAD_QUERIES
            and supervisor.get("part_a_post_service_eligible_control_seq")
            is not None
        )
        schedule_evidence = (
            f"qualified duration {qualified_duration:.0f} s; responses "
            f"{supervisor.get('response_count')}; service queries "
            f"{supervisor.get('part_a_service_load_sent')}; post-service "
            "eligible control "
            f"{supervisor.get('part_a_post_service_eligible_control_seq')}"
        )
    else:
        schedule_ok = (
            terminal.get("result") == "healthy_stop"
            and qualified_duration >= PART_B_DURATION_S
            and qualified_duration <= (
                PART_B_DURATION_S + PART_B_CLEARANCE_GRACE_S + 1.0
            )
            and set(supervisor.get("part_b_service_bursts_complete", []))
            == set(range(len(PART_B_SERVICE_LOAD_STARTS_S)))
        )
        schedule_evidence = (
            f"qualified duration {qualified_duration:.0f} s; completed service bursts "
            f"{supervisor.get('part_b_service_bursts_complete')}"
        )
    checks.append(Check("part_specific_duration_and_service_schedule", schedule_ok, schedule_evidence))

    markers = _host_markers(run_dir / "raw/serial.log")
    stopped = _one_marker(markers, "capture_stopped")
    transport_ok = all(
        int(stopped.get(key, -1)) == 0
        for key in (
            "malformed_utf8",
            "parser_errors",
            "reconnect_count",
            "commands_rejected",
        )
    ) and not [row for row in markers if row.get("event") == "partial_line_dropped"]
    checks.append(
        Check(
            "capture_transport_complete_and_clean",
            transport_ok,
            "zero parser/malformed/reconnect/rejected-command/partial-line faults",
        )
    )

    stability_gate: dict[str, Any] = {
        "schema_version": 1,
        "test": "part_a_fixed_code_stability",
        "applicable": part == "part_a" and start_code == 0xA82A,
        "status": "not_applicable",
        "claim_scope": "fixed_code_stability_only_not_active_transaction_confirmation",
    }
    if stability_gate["applicable"]:
        observation_duration_s = (
            int(authoritative[-1]["timestamp_s"])
            - int(authoritative[0]["timestamp_s"])
            + 600
            if authoritative
            else 0
        )
        abort_ticks = min(
            (
                int(row["timestamp_ticks"])
                for row in health_rows
                if row.get("component") == "cx317_active"
                and row.get("status_key") == "state"
                and row.get("status_value") == "ABORTED"
            ),
            default=None,
        )
        pre_stop_health_rows = [
            row
            for row in health_rows
            if abort_ticks is None or int(row["timestamp_ticks"]) < abort_ticks
        ]
        pre_stop = _latest_health_rows(pre_stop_health_rows)
        pre_stop_health_ok = (
            pre_stop.get(("dual_core", "partition_fault")) == "none"
            and pre_stop.get(("dual_core", "fail_static")) == "false"
            and pre_stop.get(("cx317_active", "fail_static")) == "false"
            and int(pre_stop.get(("dual_core", "telemetry_dropped"), "-1")) == 0
            and int(pre_stop.get(("gnss_receiver", "parser_drop_count"), "-1")) == 0
            and int(pre_stop.get(("gnss_receiver", "checksum_failure_count"), "-1")) == 0
            and int(pre_stop.get(("gnss_receiver", "truncated_count"), "-1")) == 0
        )
        stability_criteria = {
            "minimum_observations": len(authoritative)
            >= PART_A_STABILITY_MIN_OBSERVATIONS,
            "minimum_qualified_duration": observation_duration_s
            >= PART_A_STABILITY_MIN_DURATION_S,
            "all_observations_inside_authoritative_deadband": bool(authoritative)
            and all(
                row["authoritative_deadband_state"] == "inside"
                for row in authoritative
            ),
            "all_observations_gnss_qualified": bool(authoritative)
            and all(row["gnss_qualification"] == "qualified" for row in authoritative),
            "zero_automatic_applications_and_movement": (
                len(applications) == 0
                and int(transactions["path_codes"]) == 0
                and int(transactions["net_movement_codes"]) == 0
            ),
            "continuous_raw_count_snapshot_evidence": all(
                item.passed for item in continuity
            ),
            "exact_estimator_controller_shadow_replay": (
                estimator_check.passed
                and controller_check.passed
                and observation_ok
                and shadow_check.passed
            ),
            "pre_stop_health_clean": pre_stop_health_ok,
            "deliberate_fail_static_endpoint": (
                terminal.get("result") == "aborted"
                and terminal.get("reason") == "independent_host_abort_fifo"
            ),
            "host_transport_counters_zero": all(
                int(stopped.get(key, -1)) == 0
                for key in (
                    "malformed_utf8",
                    "parser_errors",
                    "reconnect_count",
                    "commands_rejected",
                )
            ),
        }
        stability_passed = all(stability_criteria.values())
        stability_gate.update(
            {
                "status": "pass" if stability_passed else "fail",
                "criteria": stability_criteria,
                "observed": {
                    "qualified_observations": len(authoritative),
                    "qualified_duration_s": observation_duration_s,
                    "minimum_error_hz": min(
                        float(row["frequency_error_hz"]) for row in authoritative
                    ),
                    "maximum_error_hz": max(
                        float(row["frequency_error_hz"]) for row in authoritative
                    ),
                    "automatic_applications": len(applications),
                    "path_codes": int(transactions["path_codes"]),
                    "terminal": terminal,
                },
            }
        )
        _atomic_json(
            run_dir / "reports/part_a_fixed_code_stability_gate.json",
            stability_gate,
        )

    passed = all(check.passed for check in checks)
    result = {
        "schema_version": 1,
        "tool": "cx317_stage7_analyze_v1",
        "status": "pass" if passed else "fail",
        "part": part,
        "run_id": manifest.run_id,
        "checks": [asdict(check) for check in checks],
        "transactions": transactions,
        "subtests": {"part_a_fixed_code_stability": stability_gate},
        "controller_replay": controller_replay,
        "authoritative_time_series": _series_metrics(authoritative),
        "authoritative_context_analysis": _context_analysis(authoritative),
        "shadow_candidate_summaries": shadow_summaries,
        "shadow_candidate_comparisons": _candidate_comparisons(
            shadow, post_part_b=part == "part_b"
        ),
        "shadow_gain_sensitivity": _gain_sensitivity(
            authoritative,
            part=part,
            start_code=start_code,
            contract=shadow_contract,
        ),
        "shadow_context_sensitivity": _shadow_context_sensitivity(
            authoritative, shadow
        ),
        "sealed_campaign_a_b_shadow_replays": historical_replays,
        "claims": {
            "bounded_frequency_control_endurance": passed and part == "part_b",
            "calibrated_accuracy": False,
            "utc_traceability": False,
            "phase_lock": False,
            "holdover": False,
            "shadow_candidate_adopted": False,
        },
    }
    output = run_dir / "reports/stage7_exit_gate.json"
    _atomic_json(output, result)
    return output, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--build-manifest", type=Path, required=True)
    parser.add_argument("--uf2", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output, result = analyze(
            args.run_dir,
            build_manifest=args.build_manifest,
            uf2=args.uf2,
        )
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(output)
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
