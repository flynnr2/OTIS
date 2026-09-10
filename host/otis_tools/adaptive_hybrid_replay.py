"""Offline measurement, response, capsule, and D10-isolation replay helpers."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any


SELECTED_ESTIMATOR_ID = "OTIS_PPS_GATED_FREQUENCY_ESTIMATOR_V1"
SERIALIZED_12_DECIMAL_HALF_UNIT = Decimal("0.0000000000005")


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _contract_paths(manifest: Any, contract: str) -> list[Path]:
    return [
        manifest.root / item["path"]
        for item in manifest.files
        if item.get("contract") == contract
    ]


def _single_contract_path(manifest: Any, contract: str) -> Path:
    paths = _contract_paths(manifest, contract)
    if len(paths) != 1:
        raise ValueError(f"expected one {contract} artifact, got {len(paths)}")
    return paths[0]


def _raw_event_path(manifest: Any, record_type: str) -> Path:
    entries = [
        item
        for item in manifest.files
        if item.get("contract") == "raw_events_v1"
        and item.get("record_type") == record_type
    ]
    if len(entries) != 1:
        raise ValueError(f"expected one {record_type} raw-event artifact")
    return manifest.root / entries[0]["path"]


def _selected_frequency_estimator_sha256(manifest_value: dict[str, Any]) -> str:
    transaction_identities = manifest_value.get("transaction_identities", {})
    frozen = (
        transaction_identities.get("estimator_sha256")
        if isinstance(transaction_identities, dict)
        else None
    )
    if not isinstance(frozen, str) or len(frozen) != 64:
        raise ValueError("frozen frequency-estimator identity is unavailable")
    try:
        int(frozen, 16)
    except ValueError as error:
        raise ValueError("frozen frequency-estimator identity is malformed") from error
    return frozen


def _measurement_replay(
    manifest: Any,
    manifest_value: dict[str, Any],
) -> tuple[bool, dict[str, Any], dict[str, dict[str, str]]]:
    """Recompute D14-gated D8 frequency estimates; retain D10 separately."""
    counts = _read_csv(_single_contract_path(manifest, "count_observations_v1"))
    snapshots = _read_csv(_single_contract_path(manifest, "pps_snapshots_v1"))
    references = _read_csv(_raw_event_path(manifest, "REF"))
    d10_local_error: str | None = None
    try:
        external_events = _read_csv(_raw_event_path(manifest, "EVT"))
    except (OSError, UnicodeError, csv.Error) as error:
        external_events = []
        d10_local_error = f"{type(error).__name__}: {error}"
    estimates = _read_csv(_single_contract_path(manifest, "estimates_v2"))
    d10_channel_exact = d10_local_error is None and all(
        row.get("record_type") == "EVT" and row.get("channel_id") == "0"
        for row in external_events
    )
    d14_channel_exact = bool(references) and all(
        row.get("record_type") == "REF" and row.get("channel_id") == "1"
        for row in references
    )
    if not counts or not snapshots or not references or not estimates:
        return False, {
            "reason": "D14/D8 measurement replay source is empty",
            "D10": {
                "row_count": len(external_events),
                "channel_exact": d10_channel_exact,
                "local_error": d10_local_error,
            },
        }, {}
    expected_hash = _selected_frequency_estimator_sha256(manifest_value)
    count_by_seq = {int(row["count_seq"]): row for row in counts}
    sequence_exact = [int(row["estimate_seq"]) for row in estimates] == list(
        range(int(estimates[0]["estimate_seq"]), int(estimates[-1]["estimate_seq"]) + 1)
    )
    exact = sequence_exact and d14_channel_exact
    identifiers: set[str] = set()
    selected_windows: list[tuple[int, int]] = []
    comparisons: list[dict[str, Any]] = []
    estimates_by_id: dict[str, dict[str, str]] = {}
    for row in estimates:
        identifier = row["estimate_id"]
        unique = identifier not in identifiers
        identifiers.add(identifier)
        estimates_by_id[identifier] = row
        if row.get("estimator_version") != SELECTED_ESTIMATOR_ID:
            continue
        first = int(row["source_reference_first_seq"])
        last = int(row["source_reference_last_seq"])
        selected_windows.append((first, last))
        sources = [count_by_seq.get(sequence) for sequence in range(first + 1, last + 1)]
        source_exact = len(sources) == 600 and all(sources)
        if source_exact:
            total = sum(int(item["counted_edges"]) for item in sources if item)
            # The selected firmware estimator performs both operations in its
            # declared binary64 implementation domain before serializing each
            # result to 12 decimal places.  Replaying the rational quotient
            # instead invents precision that the producer never possessed at
            # a 10 MHz magnitude (and can reject its separately computed error
            # even when the source edge total is exact).
            frequency_binary64 = float(total) / 600.0
            error_binary64 = frequency_binary64 - 10_000_000.0
            frequency = Decimal.from_float(frequency_binary64)
            error = Decimal.from_float(error_binary64)
            frequency_difference = abs(Decimal(row["frequency_estimate_hz"]) - frequency)
            error_difference = abs(Decimal(row["frequency_error_hz"]) - error)
        else:
            total = None
            frequency_difference = Decimal("Infinity")
            error_difference = Decimal("Infinity")
        row_exact = (
            unique
            and source_exact
            and int(row["source_count_seq"]) == last
            and int(row["accepted_sample_count"]) == 600
            and row["config_hash"] == expected_hash
            and row["observation_validity"] == "valid"
            and row["reference_validity"] == "valid"
            and row["count_validity"] == "valid"
            and frequency_difference <= SERIALIZED_12_DECIMAL_HALF_UNIT
            and error_difference <= SERIALIZED_12_DECIMAL_HALF_UNIT
        )
        exact &= row_exact
        comparisons.append(
            {
                "estimate_id": identifier,
                "total_counted_edges": total,
                "absolute_frequency_difference_hz": (
                    None if frequency_difference.is_infinite() else float(frequency_difference)
                ),
                "absolute_error_difference_hz": (
                    None if error_difference.is_infinite() else float(error_difference)
                ),
                "pass": row_exact,
            }
        )
    nonoverlap = bool(selected_windows) and all(
        later_first >= earlier_last
        for (_, earlier_last), (later_first, _) in zip(selected_windows, selected_windows[1:])
    )
    exact &= nonoverlap
    return bool(exact), {
        "estimate_sequence_exact": sequence_exact,
        "calculation_domain": "firmware_ieee754_binary64_then_fixed_12_decimal",
        "selected_count": len(selected_windows),
        "selected_nonoverlap": nonoverlap,
        "D10": {
            "row_count": len(external_events),
            "channel_exact": d10_channel_exact,
            "local_error": d10_local_error,
            "authority": "evidence_only",
            "enters_D14_D8_replay": False,
        },
        "D14": {"row_count": len(references), "channel_exact": d14_channel_exact},
        "comparisons": comparisons,
    }, estimates_by_id


class ResponseClass(str, Enum):
    HEALTHY_DETECTED = "healthy_detected"
    HEALTHY_INDETERMINATE = "healthy_indeterminate_near_resolution"
    INSIDE_DEADBAND = "inside_deadband"
    LIMIT_REACHED = "limit_reached"
    WRONG_SIGN = "wrong_sign"
    EXCESS_RESPONSE = "excess_response"
    GROWING_ERROR = "growing_error"
    MEASUREMENT_OR_ACTUATOR_FAULT = "measurement_or_actuator_fault"


@dataclass(frozen=True)
class ResponseResult:
    classification: ResponseClass
    reason: str
    observed_response_hz: float | None
    cumulative_response_hz: float | None
    consecutive_indeterminate: int


class ResponseClassifier:
    def __init__(
        self, *, observational: bool, policy_document: dict[str, Any]
    ) -> None:
        value = policy_document
        if value.get("policy_id") != "OTIS_RESPONSE_CLASSIFICATION_V1":
            raise ValueError("response classification identity differs")
        p = value["parameters"]
        self.gain_min = float(p["gain_min_hz_per_code"])
        self.gain_max = float(p["gain_max_hz_per_code"])
        self.floor = float(p["empirical_detection_floor_hz"])
        self.deadband = float(p["error_deadband_hz"])
        self.wrong_sign_minimum = float(p["wrong_sign_minimum_hz"])
        self.growth_margin = float(p["growing_error_margin_hz"])
        self.excess_margin = float(p["excess_response_additive_margin_hz"])
        self.maximum_indeterminate = int(p["maximum_consecutive_indeterminate"])
        self.observational = observational
        self.baseline_error_hz: float | None = None
        self.cumulative_delta_codes = 0
        self.consecutive_indeterminate = 0

    def classify(
        self, *, pre_error_hz: float, post_error_hz: float, applied_delta_codes: int,
        current_code: int, minimum_code: int, maximum_code: int,
    ) -> ResponseResult:
        if applied_delta_codes == 0 or not all(map(math.isfinite, (pre_error_hz, post_error_hz))):
            return ResponseResult(ResponseClass.MEASUREMENT_OR_ACTUATOR_FAULT, "invalid_response_evidence", None, None, 0)
        if self.baseline_error_hz is None:
            self.baseline_error_hz = pre_error_hz
        self.cumulative_delta_codes += applied_delta_codes
        observed = post_error_hz - pre_error_hz
        cumulative = post_error_hz - self.baseline_error_hz
        if (
            observed * applied_delta_codes < 0
            and abs(observed) >= self.wrong_sign_minimum
        ) or (
            cumulative * self.cumulative_delta_codes < 0
            and abs(cumulative) >= self.wrong_sign_minimum
        ):
            result = (ResponseClass.WRONG_SIGN, "observed_response_opposes_positive_plant_gain")
        elif abs(post_error_hz) > abs(pre_error_hz) + self.growth_margin:
            result = (ResponseClass.GROWING_ERROR, "absolute_error_grew_beyond_frozen_margin")
        elif abs(observed) > abs(applied_delta_codes) * self.gain_max + self.excess_margin:
            result = (ResponseClass.EXCESS_RESPONSE, "response_exceeds_gain_envelope_plus_empirical_margin")
        elif (
            observed * applied_delta_codes > 0 and abs(observed) >= self.floor
        ) or (
            cumulative * self.cumulative_delta_codes > 0
            and abs(cumulative) >= self.floor
        ):
            result = (ResponseClass.HEALTHY_DETECTED, "response_detected_with_commanded_sign")
        else:
            self.consecutive_indeterminate += 1
            if (
                not self.observational
                and self.consecutive_indeterminate > self.maximum_indeterminate
                and abs(self.cumulative_delta_codes) * self.gain_min >= 2 * self.floor
            ):
                result = (ResponseClass.MEASUREMENT_OR_ACTUATOR_FAULT, "persistent_response_absence_after_cumulative_expected_detection")
            else:
                result = (ResponseClass.HEALTHY_INDETERMINATE, "healthy_evidence_below_empirical_detection_floor")
        if result[0] is not ResponseClass.HEALTHY_INDETERMINATE:
            self.consecutive_indeterminate = 0
        return ResponseResult(result[0], result[1], observed, cumulative, self.consecutive_indeterminate)


def _response_replay(
    rows: list[dict[str, str]], minimum_code: int, maximum_code: int,
    *, response_classification_observational: bool = False,
    response_policy_document: dict[str, Any],
) -> tuple[bool, list[dict[str, Any]]]:
    classifier = ResponseClassifier(
        observational=response_classification_observational,
        policy_document=response_policy_document,
    )
    grouped: dict[int, list[dict[str, str]]] = {}
    for row in rows:
        if row.get("event") != "manual_start":
            grouped.setdefault(int(row["request_sequence"]), []).append(row)
    exact = True
    results: list[dict[str, Any]] = []
    for request_sequence, group in sorted(grouped.items()):
        events = [row["event"] for row in group]
        if events != ["request_created", "request_accepted", "application", "response"]:
            exact = False
            results.append({"request_sequence": request_sequence, "events": events, "exact": False})
            continue
        created, _, applied, response = group
        replayed = classifier.classify(
            pre_error_hz=float(created["pre_error_hz"]),
            post_error_hz=float(response["post_error_hz"]),
            applied_delta_codes=int(created["requested_delta_codes"]),
            current_code=int(applied["applied_code"]),
            minimum_code=minimum_code,
            maximum_code=maximum_code,
        )
        row_exact = (
            response["response_class"] == replayed.classification.value
            and response["reason"] == replayed.reason
            and replayed.observed_response_hz is not None
            and math.isclose(float(response["observed_response_hz"]), replayed.observed_response_hz, rel_tol=0, abs_tol=5e-9)
        )
        exact &= row_exact
        results.append({"request_sequence": request_sequence, "replayed_class": replayed.classification.value, "exact": row_exact})
    return bool(exact), results


def _capsules_exact(
    run_dir: Path, rows: list[dict[str, str]], events: list[dict[str, Any]],
    supervisor_state: dict[str, Any], *,
    permitted_unacknowledged_sequences: frozenset[int] = frozenset(),
) -> tuple[bool, dict[str, str]]:
    expected_rows = [row for row in rows if row.get("event") != "manual_start"]
    hashes: dict[str, str] = {}
    exact = True
    expected_paths: set[Path] = set()
    phase = {"request_created": 1, "request_accepted": 2, "application": 3, "application_fault": 3, "response": 4}
    acknowledgements = {
        (int(item["record_sequence"]), int(item["phase"]))
        for item in events if item.get("event") == "transaction_phase_acknowledged"
    }
    for row in expected_rows:
        record = int(row["transaction_record_sequence"])
        relative = Path("reports") / f"step_{int(row['request_sequence']):03d}" / f"record_{record:06d}_{row['event']}.json"
        expected_paths.add(relative)
        path = run_dir / relative
        if not path.is_file() or json.loads(path.read_text(encoding="utf-8")) != row:
            exact = False
            continue
        hashes[str(relative)] = sha256(path.read_bytes()).hexdigest()
        if ((record, phase[row["event"]]) in acknowledgements) != (record not in permitted_unacknowledged_sequences):
            exact = False
    actual = {
        path.relative_to(run_dir)
        for path in (run_dir / "reports").glob("step_*/record_*_*.json")
        if not path.name.endswith("_response_replay_attestation.json")
    }
    exact &= actual == expected_paths
    expected_sequences = sorted(
        int(row["transaction_record_sequence"])
        for row in expected_rows
        if int(row["transaction_record_sequence"]) not in permitted_unacknowledged_sequences
    )
    exact &= sorted(supervisor_state.get("acknowledged_record_sequences", [])) == expected_sequences
    return bool(exact), hashes
