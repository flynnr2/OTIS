"""Offline measurement, response, capsule, and D10-isolation replay helpers."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
from typing import Any

from .accepted_span_replay import (
    POLICY_PATH as REFERENCE_ACCEPTANCE_POLICY_PATH,
)
from .accepted_span_replay import (
    accepted_window_ref,
    replay_accepted_spans,
)
from .authoritative_inputs import (
    ValidatedAuthoritativeInputs,
    validate_authoritative_inputs,
)
from .raw_measurement_replay import (
    _RAW_REFERENCE_DOMAIN,
    _U32_MODULUS,
    SELECTED_ESTIMATOR_ID,
    _u32,
)

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
    *, validated_inputs: ValidatedAuthoritativeInputs | None = None,
) -> tuple[bool, dict[str, Any], dict[str, dict[str, str]]]:
    """Reconstruct raw accepted D14/D8 spans and verify every emitted estimate."""

    counts = _read_csv(_single_contract_path(manifest, "count_observations_v1"))
    snapshots = _read_csv(_single_contract_path(manifest, "pps_snapshots_v1"))
    references = _read_csv(_raw_event_path(manifest, "REF"))
    spans = _read_csv(_single_contract_path(manifest, "accepted_pps_spans_v1"))
    estimates = _read_csv(_single_contract_path(manifest, "estimates_v3"))
    d10_local_error: str | None = None
    try:
        external_events = _read_csv(_raw_event_path(manifest, "EVT"))
    except (OSError, UnicodeError, csv.Error) as error:
        external_events = []
        d10_local_error = f"{type(error).__name__}: {error}"
    d10_channel_exact = d10_local_error is None and all(
        row.get("record_type") == "EVT" and row.get("channel_id") == "0"
        for row in external_events
    )
    d14_channel_exact = bool(references) and all(
        row.get("record_type") == "REF" and row.get("channel_id") == "1"
        for row in references
    )
    if not counts or not snapshots or not references or not spans:
        return False, {
            "reason": "accepted D14/D8 raw measurement replay source is empty",
            "D10": {"row_count": len(external_events), "channel_exact": d10_channel_exact,
                    "local_error": d10_local_error},
        }, {}
    frozen_inputs = validated_inputs
    if frozen_inputs is None:
        frozen_inputs = validate_authoritative_inputs(manifest_value.get("authoritative_inputs"))
    elif not frozen_inputs.matches(manifest_value.get("authoritative_inputs")):
        raise ValueError("measurement replay authoritative inputs differ")
    policy = frozen_inputs.document(REFERENCE_ACCEPTANCE_POLICY_PATH)
    policy_binding = frozen_inputs.binding(REFERENCE_ACCEPTANCE_POLICY_PATH)
    policy_sha256 = str(policy_binding["sha256"])
    expected_reference_acceptance = {
        "policy_id": policy.get("policy_id"),
        "policy_sha256": policy_sha256,
        "path": REFERENCE_ACCEPTANCE_POLICY_PATH,
    }
    if manifest_value.get("reference_acceptance") != expected_reference_acceptance:
        raise ValueError("run manifest reference-acceptance binding differs")
    expected_hash = _selected_frequency_estimator_sha256(manifest_value)
    acquisition_report: dict[str, Any] | None = None
    if "acquisition_frontier" in manifest_value:
        from .acquisition_frontier import select_required_replay_rows
        try:
            snapshots, references, counts, _, acquisition_report = select_required_replay_rows(
                manifest.root, manifest_value, snapshots=snapshots,
                references=references, counts=counts, estimates=estimates,
            )
        except (OSError, KeyError, TypeError, ValueError) as error:
            return False, {"reason": "acquisition frontier verification failed",
                           "acquisition_frontier": {"exact": False, "errors": [str(error)]}}, {}
    span_exact, span_report, verified_spans = replay_accepted_spans(
        snapshots, references, counts, spans,
        acceptance_policy=policy, acceptance_policy_sha256=policy_sha256,
    )
    estimate_sequences = [_u32(row, "estimate_seq") for row in estimates]
    sequence_exact = all(
        current == (previous + 1) % _U32_MODULUS
        for previous, current in pairwise(estimate_sequences)
    )
    spans_by_stream: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for span in verified_spans:
        spans_by_stream.setdefault(
            (span["capture_session"], span["acceptance_epoch"]), []
        ).append(span)
    raw_measurement_exact = d14_channel_exact and span_exact
    estimate_replay_exact = sequence_exact
    identifiers: set[str] = set()
    selected_windows: list[tuple[int, int, int, int]] = []
    comparisons: list[dict[str, Any]] = []
    selected_sources: list[dict[str, Any]] = []
    estimates_by_id: dict[str, dict[str, str]] = {}
    for row in estimates:
        identifier = row["estimate_id"]
        unique = identifier not in identifiers
        identifiers.add(identifier)
        estimates_by_id[identifier] = row
        estimate_replay_exact &= unique
        if row.get("estimator_version") != SELECTED_ESTIMATOR_ID:
            estimate_replay_exact = False
            continue
        try:
            session = _u32(row, "capture_session")
            epoch = _u32(row, "source_acceptance_epoch")
            opening = _u32(row, "source_opening_accepted_boundary_ordinal")
            closing = _u32(row, "source_closing_accepted_boundary_ordinal")
            available = spans_by_stream.get((session, epoch), [])
            sources = [span for span in available if
                       0 < (span["accepted_boundary_ordinal"] - opening) % _U32_MODULUS <= 600]
            sources.sort(key=lambda span: (span["accepted_boundary_ordinal"] - opening) % _U32_MODULUS)
            source_exact = (
                opening != closing
                and (closing - opening) % _U32_MODULUS == 600
                and len(sources) == 600
                and [((span["accepted_boundary_ordinal"] - opening) % _U32_MODULUS)
                     for span in sources] == list(range(1, 601))
                and row.get("source_accepted_spans_ref")
                    == accepted_window_ref(session, epoch, opening, closing)
                and _u32(row, "source_opening_snapshot_sequence")
                    == sources[0]["opening_snapshot_sequence"]
                and _u32(row, "source_closing_snapshot_sequence")
                    == sources[-1]["closing_snapshot_sequence"]
                and _u32(row, "source_opening_reference_sequence")
                    == sources[0]["opening_reference_sequence"]
                and _u32(row, "source_closing_reference_sequence")
                    == sources[-1]["closing_reference_sequence"]
                and _u32(row, "estimator_timestamp_ticks")
                    == sources[-1]["closing_reference_timestamp_ticks"]
            )
            total = sum(span["counted_edges"] for span in sources) if source_exact else None
            if total is None:
                frequency_difference = error_difference = Decimal("Infinity")
            else:
                frequency_binary64 = float(total) / 600.0
                error_binary64 = frequency_binary64 - 10_000_000.0
                frequency_difference = abs(
                    Decimal(row["frequency_estimate_hz"])
                    - Decimal.from_float(frequency_binary64)
                )
                error_difference = abs(
                    Decimal(row["frequency_error_hz"])
                    - Decimal.from_float(error_binary64)
                )
            row_exact = (
                unique and source_exact
                and row.get("time_domain") == _RAW_REFERENCE_DOMAIN
                and int(row["accepted_sample_count"]) == 600
                and row["config_hash"] == expected_hash
                and all(row.get(field) == "valid" for field in
                        ("observation_validity", "reference_validity", "count_validity"))
                and frequency_difference <= SERIALIZED_12_DECIMAL_HALF_UNIT
                and error_difference <= SERIALIZED_12_DECIMAL_HALF_UNIT
            )
        except (KeyError, TypeError, ValueError, ArithmeticError):
            session = epoch = opening = closing = 0
            sources = []
            total = None
            frequency_difference = error_difference = Decimal("Infinity")
            source_exact = row_exact = False
        estimate_replay_exact &= row_exact
        selected_windows.append((session, epoch, opening, closing))
        summary = {
            "estimate_id": identifier,
            "estimator_sha256": row.get("config_hash"),
            "source_capture_session": session,
            "source_acceptance_epoch": epoch,
            "source_opening_accepted_boundary_ordinal": opening,
            "source_closing_accepted_boundary_ordinal": closing,
            "estimator_timestamp_ticks": (
                int(row["estimator_timestamp_ticks"])
                if row.get("estimator_timestamp_ticks", "").isdecimal() else None
            ),
            "time_domain": row.get("time_domain"),
            "frequency_error_hz": row.get("frequency_error_hz"),
            "accumulated_edge_error_counts": (
                total - 600 * 10_000_000 if total is not None else None
            ),
            "source_exact": source_exact,
            "pass": row_exact,
        }
        selected_sources.append(summary)
        comparisons.append({
            **summary, "total_counted_edges": total,
            "absolute_frequency_difference_hz": (
                None if frequency_difference.is_infinite() else float(frequency_difference)
            ),
            "absolute_error_difference_hz": (
                None if error_difference.is_infinite() else float(error_difference)
            ),
        })
    nonoverlap = all(
        later[:2] != earlier[:2]
        or (later[2] - earlier[3]) % _U32_MODULUS < (1 << 31)
        for earlier, later in pairwise(selected_windows)
    )
    estimate_replay_exact &= nonoverlap
    exact = raw_measurement_exact and estimate_replay_exact
    return bool(exact), {
        "raw_measurement_exact": raw_measurement_exact,
        "estimate_replay": {
            "applicability": (
                "emitted_estimates"
                if estimates
                else "not_applicable_no_emitted_estimates"
            ),
            "emitted_count": len(estimates),
            "exact": estimate_replay_exact,
        },
        "estimate_sequence_exact": sequence_exact,
        "accepted_span_replay": span_report,
        "acquisition_frontier": acquisition_report,
        "calculation_domain": "firmware_ieee754_binary64_then_fixed_12_decimal",
        "selected_count": len(selected_windows), "selected_nonoverlap": nonoverlap,
        "D10": {"row_count": len(external_events), "channel_exact": d10_channel_exact,
                "local_error": d10_local_error, "authority": "evidence_only",
                "enters_D14_D8_replay": False},
        "D14": {"row_count": len(references), "channel_exact": d14_channel_exact},
        "comparisons": comparisons,
        "selected_estimate_sources": selected_sources,
    }, estimates_by_id

def replay_active_decision_measurement_sources(
    manifest: Any, measurement: dict[str, Any]
) -> dict[str, Any]:
    """Bind every retained AHY decision to one reconstructed selected EST.

    The raw measurement replay establishes an EST's D14/D8 source aperture;
    this physical-only consumer proves the later operational decision consumed
    that same selected estimate.  EST rows remain observational unless an AHY
    record actually names their source span.
    """

    from .firmware_host_contract import bounded_modular_lag_matches

    errors: list[str] = []
    joins: list[dict[str, Any]] = []
    try:
        decisions = _read_csv(
            _single_contract_path(manifest, "active_hybrid_decisions_v3")
        )
        sources = measurement.get("selected_estimate_sources")
        if not isinstance(sources, list):
            raise ValueError("selected measurement source summaries are unavailable")
        source_index: dict[tuple[int, int, int, int], list[dict[str, Any]]] = {}
        for source in sources:
            if not isinstance(source, dict):
                raise ValueError("selected measurement comparison is malformed")
            session = source.get("source_capture_session")
            epoch = source.get("source_acceptance_epoch")
            opening = source.get("source_opening_accepted_boundary_ordinal")
            closing = source.get("source_closing_accepted_boundary_ordinal")
            if not all(type(value) is int for value in (session, epoch, opening, closing)):
                continue
            source_index.setdefault((session, epoch, opening, closing), []).append(source)
        for decision in decisions:
            key: tuple[int, int, int, int] | None = None
            try:
                key = (
                    int(decision["capture_session"]),
                    int(decision["source_acceptance_epoch"]),
                    int(decision["source_opening_accepted_boundary_ordinal"]),
                    int(decision["source_closing_accepted_boundary_ordinal"]),
                )
                candidates = source_index.get(key, [])
                source = candidates[0] if len(candidates) == 1 else None
                exact = (
                    source is not None
                    and source.get("pass") is True
                    and decision.get("frequency_estimator_sha256")
                    == source.get("estimator_sha256")
                    and Decimal(decision["frequency_error_hz"])
                    == Decimal(str(source["frequency_error_hz"]))
                    and int(decision["accumulated_edge_error_counts"])
                    == source.get("accumulated_edge_error_counts")
                    and bounded_modular_lag_matches(
                        "estimate_capture_precedes_operational_decision",
                        source=int(source["estimator_timestamp_ticks"]),
                        source_domain=str(source["time_domain"]),
                        target=int(decision["decision_timestamp_ticks"]),
                        target_domain=decision.get("time_domain", ""),
                    )
                )
            except (KeyError, TypeError, ValueError, ArithmeticError):
                source = None
                exact = False
            joins.append(
                {
                    "decision_sequence": decision.get("decision_sequence"),
                    "source_key": list(key) if key is not None else None,
                    "estimate_id": None if source is None else source.get("estimate_id"),
                    "exact": exact,
                }
            )
            if not exact:
                errors.append(
                    f"AHY {decision.get('decision_sequence', '?')} has no unique exact selected EST source"
                )
    except (OSError, UnicodeError, csv.Error, KeyError, TypeError, ValueError) as error:
        errors.append(str(error))
        decisions = []
        source_index = {}
    used = {
        item["estimate_id"] for item in joins
        if item.get("exact") and isinstance(item.get("estimate_id"), str)
    }
    source_count = sum(len(items) for items in source_index.values())
    return {
        "exact": not errors,
        "decision_count": len(decisions),
        "selected_source_count": source_count,
        "consumed_selected_source_count": len(used),
        "unconsumed_selected_source_count": source_count - len(used),
        "joins": joins,
        "errors": errors[:20],
        "error_count": len(errors),
        "scope": "physical_AHY_to_selected_EST_source_timestamp_session_and_numeric_binding",
    }


def replay_phase_accepted_sources(manifest: Any) -> dict[str, Any]:
    """Bind qualified RPH rows to APS and every PHE row to its exact RPH."""

    errors: list[str] = []
    joins: list[dict[str, Any]] = []
    try:
        spans = _read_csv(_single_contract_path(manifest, "accepted_pps_spans_v1"))
        phase_rows = _read_csv(
            _single_contract_path(manifest, "relative_phase_observations_v2")
        )
        outputs = _read_csv(
            _single_contract_path(manifest, "phase_estimator_outputs_v2")
        )
        span_index: dict[tuple[int, int, int], list[dict[str, str]]] = {}
        for row in spans:
            key = (
                int(row["capture_session"]), int(row["acceptance_epoch"]),
                int(row["accepted_boundary_ordinal"]),
            )
            span_index.setdefault(key, []).append(row)
        phase_index: dict[tuple[int, int], list[dict[str, str]]] = {}
        for row in phase_rows:
            key = (int(row["phase_epoch"]), int(row["observation_sequence"]))
            phase_index.setdefault(key, []).append(row)
            if row.get("qualification_state") != "qualified":
                if row.get("source_accepted_span_ref"):
                    errors.append(f"RPH {key} claims APS while non-qualified")
                continue
            accepted_key = (
                int(row["capture_session"]), int(row["acceptance_epoch"]),
                int(row["accepted_boundary_ordinal"]),
            )
            candidates = span_index.get(accepted_key, [])
            span = candidates[0] if len(candidates) == 1 else None
            exact = (
                span is not None
                and row.get("source_accepted_span_ref")
                    == f"live:APS:{accepted_key[0]}:{accepted_key[1]}:{accepted_key[2]}"
                and all(row.get(target) == span.get(source) for target, source in (
                    ("opening_snapshot_sequence", "opening_snapshot_sequence"),
                    ("closing_snapshot_sequence", "closing_snapshot_sequence"),
                    ("opening_reference_sequence", "opening_reference_sequence"),
                    ("closing_reference_sequence", "closing_reference_sequence"),
                    ("interval_edges", "counted_edges"),
                ))
            )
            joins.append({"kind": "RPH_to_APS", "source_key": list(accepted_key),
                          "phase_key": list(key), "exact": exact})
            if not exact:
                errors.append(f"qualified RPH {key} lacks one exact APS source")
        for row in outputs:
            key = (int(row["phase_epoch"]), int(row["observation_sequence"]))
            candidates = phase_index.get(key, [])
            source = candidates[0] if len(candidates) == 1 else None
            exact = (
                source is not None
                and row.get("source_relative_phase_observation")
                    == f"RPH:{key[0]}:{key[1]}"
                and all(row.get(target) == source.get(source_field)
                        for target, source_field in (
                    ("capture_session", "capture_session"),
                    ("acceptance_epoch", "acceptance_epoch"),
                    ("accepted_boundary_ordinal", "accepted_boundary_ordinal"),
                    ("raw_relative_phase_cycles", "relative_phase_cycles"),
                    ("raw_relative_phase_time_ns", "relative_phase_time_ns"),
                    ("qualification_state", "qualification_state"),
                ))
            )
            joins.append({"kind": "PHE_to_RPH", "phase_key": list(key), "exact": exact})
            if not exact:
                errors.append(f"PHE {key} lacks one exact RPH source")
    except (OSError, UnicodeError, csv.Error, KeyError, TypeError, ValueError) as error:
        errors.append(str(error))
    return {
        "exact": not errors,
        "joins": joins,
        "errors": errors[:20],
        "error_count": len(errors),
    }
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


def replay_transaction_capsules(
    run_dir: Path, rows: list[dict[str, str]], events: list[dict[str, Any]],
    supervisor_state: dict[str, Any], *,
    permitted_unacknowledged_sequences: frozenset[int] = frozenset(),
) -> dict[str, Any]:
    expected_rows = [row for row in rows if row.get("event") != "manual_start"]
    hashes: dict[str, str] = {}
    errors: list[str] = []
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
            errors.append(f"ACT record {record}: missing or contradictory capsule {relative}")
            continue
        hashes[str(relative)] = sha256(path.read_bytes()).hexdigest()
        if ((record, phase[row["event"]]) in acknowledgements) != (record not in permitted_unacknowledged_sequences):
            errors.append(f"ACT record {record}: phase {phase[row['event']]} acknowledgement differs from retained record")
    actual = {
        path.relative_to(run_dir)
        for path in (run_dir / "reports").glob("step_*/record_*_*.json")
        if not path.name.endswith("_response_replay_attestation.json")
    }
    if actual != expected_paths:
        errors.append(f"capsule inventory differs: missing={sorted(map(str, expected_paths - actual))}, extra={sorted(map(str, actual - expected_paths))}")
    expected_sequences = sorted(
        int(row["transaction_record_sequence"])
        for row in expected_rows
        if int(row["transaction_record_sequence"]) not in permitted_unacknowledged_sequences
    )
    observed_sequences = sorted(supervisor_state.get("acknowledged_record_sequences", []))
    if observed_sequences != expected_sequences:
        errors.append(f"owner acknowledged ACT frontier differs: expected={expected_sequences}, observed={observed_sequences}")
    return {"exact": not errors, "capsule_sha256": hashes, "errors": errors}
