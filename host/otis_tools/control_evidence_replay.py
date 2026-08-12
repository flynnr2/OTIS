"""Replay current measurement, controller, transaction, and response evidence.

This analyzer never sends a command.  It replays the frequency-only
transaction and tight-deadband evidence, proves the phase/hybrid surfaces had
zero authority, and emits an immutable per-leg verdict.
"""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any

from .active_transactions import _read_csv
from .active_control_policy import ResponseClassifier
from .campaign_finalization import _contract_path
from .frequency_control_replay import (
    IOnlyPreviewEngine,
    Observation,
    load_current_replay_policy,
)
from .measurement_replay import (
    EXPECTED_DIAGNOSTIC_VERSION,
    EXPECTED_SELECTED_VERSION,
    SERIALIZED_12_DECIMAL_HALF_UNIT,
    TICKS_PER_SECOND,
    check_continuity,
)
from .timebase import unwrap_ticks


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _bool(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"malformed Boolean {value!r}")


def _serialized_difference(value: str, expected: float) -> float:
    return float(abs(Decimal(value) - Decimal.from_float(expected)))


def _measurement_replay(
    manifest: Any,
    manifest_value: dict[str, Any],
) -> tuple[bool, dict[str, Any], dict[str, dict[str, str]]]:
    """Recompute current count/snapshot and estimator evidence exactly."""

    counts = _read_csv(_contract_path(manifest, "count_observations_v1"))
    snapshots = _read_csv(_contract_path(manifest, "pps_snapshots_v1"))
    references = _read_csv(_contract_path(manifest, "raw_events_v1"))
    estimates = _read_csv(_contract_path(manifest, "estimates_v2"))
    if not counts or not snapshots or not references or not estimates:
        return False, {"reason": "measurement replay source is empty"}, {}
    continuity, count_by_seq = check_continuity(counts, snapshots, references)
    continuity_exact = all(item.passed for item in continuity)
    expected_estimator_hash = manifest_value["policy"]["bindings"][
        "selected_frequency_estimator"
    ]["sha256"]
    sequences = [int(row["estimate_seq"]) for row in estimates]
    sequence_exact = sequences == list(range(sequences[0], sequences[-1] + 1))
    identifiers: set[str] = set()
    comparisons: list[dict[str, Any]] = []
    selected_last: list[int] = []
    maximum_frequency_difference = 0.0
    maximum_error_difference = 0.0
    exact = continuity_exact and sequence_exact
    estimates_by_id: dict[str, dict[str, str]] = {}
    for row in estimates:
        identifier = row["estimate_id"]
        unique = identifier not in identifiers
        identifiers.add(identifier)
        estimates_by_id[identifier] = row
        selected = row["estimator_version"] == EXPECTED_SELECTED_VERSION
        diagnostic = row["estimator_version"] == EXPECTED_DIAGNOSTIC_VERSION
        span = 600 if selected else 60 if diagnostic else 0
        if selected:
            selected_last.append(int(row["source_reference_last_seq"]))
        first = int(row["source_reference_first_seq"])
        last = int(row["source_reference_last_seq"])
        sources = [count_by_seq.get(sequence) for sequence in range(first + 1, last + 1)]
        source_exact = span > 0 and len(sources) == span and all(sources)
        if source_exact:
            total = sum(int(item["counted_edges"]) for item in sources if item)
            host_frequency = float(total) / float(span)
            host_error = host_frequency - 10_000_000.0
            frequency_difference = max(
                _serialized_difference(row["frequency_estimate_hz"], host_frequency),
                _serialized_difference(row["frequency_observation_hz"], host_frequency),
            )
            error_difference = _serialized_difference(
                row["frequency_error_hz"], host_error
            )
        else:
            total = None
            host_frequency = None
            frequency_difference = math.inf
            error_difference = math.inf
        maximum_frequency_difference = max(
            maximum_frequency_difference, frequency_difference
        )
        maximum_error_difference = max(maximum_error_difference, error_difference)
        fields_exact = (
            unique
            and source_exact
            and int(row["source_count_seq"]) == last
            and row["source_count_ref"] == f"live:CNT:{last}"
            and int(row["accepted_sample_count"]) == span
            and row["config_hash"] == expected_estimator_hash
            and row["observation_validity"] == "valid"
            and row["reference_validity"] == "valid"
            and row["reference_continuity"] == "true"
            and row["count_validity"] == "valid"
            and row["count_continuity"] == "true"
            and row["diagnostic_health"] == "healthy"
            and row["uncertainty_status"] == "unavailable"
            and row["combined_standard_uncertainty_hz"] == ""
            and row["expanded_uncertainty_hz"] == ""
            and row["drift_enabled"] == "false"
            and frequency_difference <= SERIALIZED_12_DECIMAL_HALF_UNIT
            and error_difference <= SERIALIZED_12_DECIMAL_HALF_UNIT
        )
        exact &= fields_exact
        comparisons.append(
            {
                "estimate_id": identifier,
                "span_s": span,
                "total_counted_edges": total,
                "host_frequency_hz": host_frequency,
                "absolute_frequency_difference_hz": (
                    frequency_difference if math.isfinite(frequency_difference) else None
                ),
                "absolute_error_difference_hz": (
                    error_difference if math.isfinite(error_difference) else None
                ),
                "pass": fields_exact,
            }
        )
    selected_nonoverlap = bool(selected_last) and all(
        later - earlier == 600
        for earlier, later in zip(selected_last, selected_last[1:])
    )
    exact &= selected_nonoverlap
    return exact, {
        "continuity": [
            {"id": item.identifier, "pass": item.passed, "evidence": item.evidence}
            for item in continuity
        ],
        "estimate_sequence_exact": sequence_exact,
        "selected_count": len(selected_last),
        "selected_nonoverlap": selected_nonoverlap,
        "maximum_frequency_difference_hz": (
            maximum_frequency_difference
            if math.isfinite(maximum_frequency_difference)
            else None
        ),
        "maximum_error_difference_hz": (
            maximum_error_difference if math.isfinite(maximum_error_difference) else None
        ),
        "comparisons": comparisons,
    }, estimates_by_id


def _mapped_state(value: str) -> str:
    return {
        "WARMUP_INHIBIT": "WARMUP_INHIBIT",
        "QUALIFYING": "QUALIFYING",
        "SETTLING_INHIBIT": "SETTLE_PREVIEW",
        "TRACKING": "LOCKED_PREVIEW",
        "OUT_OF_MODEL_HOLD": "OUT_OF_MODEL_HOLD",
        "FAULT": "FAULT",
        "ABORTED": "FAULT",
    }[value]


def _controller_replay(
    controls: list[dict[str, str]],
    estimates_by_id: dict[str, dict[str, str]],
    tdb_rows: list[dict[str, str]],
    dac_rows: list[dict[str, str]],
    applications: list[dict[str, str]],
    *,
    stage5_policy_sha256: str,
    policy_id: str = "CX319_STABILIZED_TIGHT_DEADBAND_FREQUENCY_ONLY_V1",
) -> tuple[bool, dict[str, Any]]:
    """Replay current frequency decisions and bind each requested delta."""

    if not controls or not dac_rows:
        return False, {"reason": "controller or DAC history is empty"}
    policy = load_current_replay_policy()
    engine = IOnlyPreviewEngine(policy)
    decision_ticks, wrap_count = unwrap_ticks(
        [int(row["decision_timestamp_ticks"]) for row in controls]
    )
    ordered_dac = sorted(dac_rows, key=lambda row: int(row["elapsed_ms"]))
    next_dac = 0
    tdb_by_estimate = {row["estimate_id"]: row for row in tdb_rows}
    if len(tdb_by_estimate) != len(tdb_rows):
        return False, {"reason": "duplicate TDB estimate identity"}
    comparisons: list[dict[str, Any]] = []
    exact = [int(row["control_seq"]) for row in controls] == list(
        range(len(controls))
    )
    raw_delta_tolerance = (
        abs(policy.integrator_gain) + 1.0
    ) * SERIALIZED_12_DECIMAL_HALF_UNIT
    maximum_error_difference = 0.0
    maximum_delta_difference = 0.0
    for row, timestamp_ticks in zip(controls, decision_ticks):
        timestamp_s = timestamp_ticks // TICKS_PER_SECOND
        while (
            next_dac < len(ordered_dac)
            and int(ordered_dac[next_dac]["elapsed_ms"]) // 1000 <= timestamp_s
        ):
            engine.note_dac_epoch(
                int(ordered_dac[next_dac]["elapsed_ms"]) // 1000,
                preserve_applied_cadence=True,
            )
            next_dac += 1
        source = estimates_by_id.get(row["est_input_ref"])
        tdb = tdb_by_estimate.get(row["est_input_ref"])
        frequency_error = (
            float(source["frequency_error_hz"]) if source is not None else None
        )
        previous = engine.state
        host = engine.process(
            Observation(
                timestamp_s=timestamp_s,
                frequency_error_hz=frequency_error,
                current_code=int(row["current_dac_code"]),
                estimator_valid=source is not None,
                reference_valid=source is not None,
                count_valid=source is not None,
                model_applicable=row["model_applicability"] == "applicable",
                frequency_controller_eligible=(
                    _bool(tdb["frequency_controller_eligible"])
                    if tdb is not None
                    else None
                ),
                frequency_gate_reason=(tdb["reason_codes"] if tdb else None),
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
        maximum_error_difference = max(maximum_error_difference, error_difference)
        maximum_delta_difference = max(maximum_delta_difference, delta_difference)
        row_exact = (
            source is not None
            and row["time_domain"] == "rp2040_timer0"
            and row["plant_model_hash"] == policy.plant_model_hash
            and row["policy_version"] == policy_id
            and row["config_hash"] == stage5_policy_sha256
            and row["control_state"] == _mapped_state(str(host["state"]))
            and row["previous_control_state"] == _mapped_state(previous)
            and _bool(row["state_transition"]) == (previous != host["state"])
            and row["transition_reason_code"] == host["reason"]
            and row["decision_reason_code"] == host["reason"]
            and _bool(row["preview_eligibility"]) == bool(host["preview_available"])
            and _bool(row["preview_available"]) == bool(host["preview_available"])
            and _bool(row["preview_only"])
            and not _bool(row["actuation_authorized"])
            and not _bool(row["actionable"])
            and error_difference <= SERIALIZED_12_DECIMAL_HALF_UNIT
            and delta_difference <= raw_delta_tolerance
        )
        if host["preview_available"]:
            row_exact &= (
                int(row["limited_delta_codes"]) == int(host["limited_delta_codes"])
                and int(row["proposed_dac_code"]) == int(host["proposed_code"])
                and _bool(row["step_limited"]) == bool(host["step_limited"])
                and _bool(row["range_clamped"]) == bool(host["range_clamped"])
            )
        else:
            row_exact &= all(
                row[field] == ""
                for field in (
                    "raw_delta_codes",
                    "limited_delta_codes",
                    "proposed_dac_code",
                )
            )
        exact &= row_exact
        comparisons.append(
            {
                "decision_id": row["decision_id"],
                "host_state": host["state"],
                "live_state": row["control_state"],
                "host_reason": host["reason"],
                "live_reason": row["decision_reason_code"],
                "absolute_error_difference_hz": (
                    error_difference if math.isfinite(error_difference) else None
                ),
                "absolute_raw_delta_difference_codes": (
                    delta_difference if math.isfinite(delta_difference) else None
                ),
                "pass": row_exact,
            }
        )
    controls_by_sequence = {int(row["control_seq"]): row for row in controls}
    application_bindings: list[dict[str, Any]] = []
    for application in applications:
        control = controls_by_sequence.get(int(application["decision_sequence"]))
        bound = (
            control is not None
            and int(application["requested_delta_codes"])
            == int(control["limited_delta_codes"])
            and int(application["requested_code"])
            == int(control["proposed_dac_code"])
            and tdb_by_estimate.get(control["est_input_ref"], {}).get(
                "frequency_controller_eligible"
            )
            == "true"
        )
        exact &= bound
        application_bindings.append(
            {
                "decision_sequence": int(application["decision_sequence"]),
                "pass": bound,
            }
        )
    return exact, {
        "row_count": len(controls),
        "decision_timestamp_wrap_count": wrap_count,
        "maximum_error_difference_hz": (
            maximum_error_difference if math.isfinite(maximum_error_difference) else None
        ),
        "maximum_raw_delta_difference_codes": (
            maximum_delta_difference if math.isfinite(maximum_delta_difference) else None
        ),
        "raw_delta_tolerance_codes": raw_delta_tolerance,
        "comparisons": comparisons,
        "application_bindings": application_bindings,
    }


def _response_replay(
    rows: list[dict[str, str]], minimum_code: int, maximum_code: int
) -> tuple[bool, list[dict[str, Any]]]:
    classifier = ResponseClassifier(legacy_response_deadband_enabled=False)
    grouped: dict[int, list[dict[str, str]]] = {}
    for row in rows:
        if row.get("event") != "manual_start":
            grouped.setdefault(int(row["request_sequence"]), []).append(row)
    results: list[dict[str, Any]] = []
    # A finite bounded-nonpass may legitimately contain the exact setup and no
    # automatic request.  Empty automatic history is structurally exact; the
    # pass-specific gate below still requires a healthy completed transaction.
    exact = True
    for request_sequence, group in sorted(grouped.items()):
        events = [row["event"] for row in group]
        if events != ["request_created", "core0_accepted", "application", "response"]:
            exact = False
            results.append(
                {"request_sequence": request_sequence, "events": events, "exact": False}
            )
            continue
        created, _, applied, response = group
        replayed = classifier.classify(
            pre_error_hz=float(created["pre_error_hz"]),
            post_error_hz=float(response["post_error_hz"]),
            applied_delta_codes=int(created["requested_delta_codes"]),
            current_code=int(applied["applied_code"]),
            minimum_code=minimum_code,
            maximum_code=maximum_code,
            evidence_healthy=True,
        )
        row_exact = (
            response["response_class"] == replayed.classification.value
            and response["reason"] == replayed.reason
            and replayed.observed_response_hz is not None
            and replayed.cumulative_response_hz is not None
            and math.isclose(
                float(response["observed_response_hz"]),
                replayed.observed_response_hz,
                rel_tol=0.0,
                abs_tol=5e-9,
            )
            and math.isclose(
                float(response["cumulative_response_hz"]),
                replayed.cumulative_response_hz,
                rel_tol=0.0,
                abs_tol=5e-9,
            )
            and int(response["consecutive_indeterminate"])
            == replayed.consecutive_indeterminate
        )
        exact &= row_exact
        results.append(
            {
                "request_sequence": request_sequence,
                "observed_class": response["response_class"],
                "replayed_class": replayed.classification.value,
                "observed_reason": response["reason"],
                "replayed_reason": replayed.reason,
                "exact": row_exact,
            }
        )
    return exact, results


def _capsules_exact(
    run_dir: Path,
    rows: list[dict[str, str]],
    events: list[dict[str, Any]],
    supervisor_state: dict[str, Any],
) -> tuple[bool, dict[str, str]]:
    expected_rows = [row for row in rows if row.get("event") != "manual_start"]
    hashes: dict[str, str] = {}
    exact = True
    expected_paths: set[Path] = set()
    phase_by_event = {
        "request_created": 1,
        "core0_accepted": 2,
        "application": 3,
        "application_fault": 3,
        "response": 4,
    }
    acknowledgements = {
        (int(event["record_sequence"]), int(event["phase"]))
        for event in events
        if event.get("event") == "transaction_phase_acknowledged"
    }
    for row in expected_rows:
        record_sequence = int(row["transaction_record_sequence"])
        request_sequence = int(row["request_sequence"])
        relative = Path("reports") / f"step_{request_sequence:03d}" / (
            f"record_{record_sequence:06d}_{row['event']}.json"
        )
        expected_paths.add(relative)
        path = run_dir / relative
        if not path.is_file() or json.loads(path.read_text(encoding="utf-8")) != row:
            exact = False
            continue
        hashes[str(relative)] = _sha256_file(path)
        if (record_sequence, phase_by_event[row["event"]]) not in acknowledgements:
            exact = False
    actual_paths = {
        path.relative_to(run_dir)
        for path in (run_dir / "reports").glob("step_*/record_*_*.json")
    }
    expected_sequences = sorted(
        int(row["transaction_record_sequence"]) for row in expected_rows
    )
    exact &= actual_paths == expected_paths
    exact &= sorted(supervisor_state.get("acknowledged_record_sequences", [])) == expected_sequences
    return exact, hashes


def _commands_exact(
    markers: list[dict[str, Any]],
    events: list[dict[str, Any]],
    capture_state: dict[str, Any],
    *,
    setup_code: int,
    allowed_emergency_aborts: int,
) -> bool:
    submitted = [
        str(item["command"])
        for item in events
        if item.get("event") == "command_submitted"
    ]
    sent = [
        str(item["command"])
        for item in markers
        if item.get("event") == "host_command_sent"
    ]
    acknowledged = [
        str(item["command"])
        for item in events
        if item.get("event") == "host_written"
    ]
    emergency_events = [
        item
        for item in events
        if item.get("event") == "emergency_device_abort_submitted"
    ]
    setup_pattern = re.compile(
        rf"ACTIVE SETUP [1-9][0-9]* [1-9][0-9]* [1-9][0-9]* "
        rf"[1-9][0-9]* [1-9][0-9]* 0x{setup_code:04X} 1 [0-9a-f]{{64}}",
        re.IGNORECASE,
    )
    allowed_fixed = {"CONFIG?", "DAC?", "ACTIVE?"}
    normal_grammar_exact = all(
        command in allowed_fixed
        or re.fullmatch(r"ACTIVE SNAPSHOT [1-9][0-9]*", command) is not None
        or setup_pattern.fullmatch(command) is not None
        or re.fullmatch(r"ACTIVE LEASE [1-9][0-9]*", command) is not None
        or re.fullmatch(
            r"ACTIVE ARM [1-9][0-9]* [1-9][0-9]* [1-9][0-9]*", command
        )
        is not None
        or re.fullmatch(r"ACTIVE EVIDENCE [1-9][0-9]* [1-4]", command)
        is not None
        for command in submitted
    )
    leases = [
        int(command.split()[2])
        for command in submitted
        if command.startswith("ACTIVE LEASE ")
    ]
    arms = [
        int(command.split()[2])
        for command in submitted
        if command.startswith("ACTIVE ARM ")
    ]
    expected_sent = [
        *submitted,
        *(["ACTIVE ABORT"] * allowed_emergency_aborts),
    ]
    setup_commands = [command for command in submitted if setup_pattern.fullmatch(command)]
    return (
        submitted == acknowledged
        and sent == expected_sent
        and normal_grammar_exact
        and submitted.count("CONFIG?") == 1
        and submitted.count("DAC?") == 1
        and len(setup_commands) == 1
        and leases == list(range(1, len(leases) + 1))
        and arms == list(range(1, len(arms) + 1))
        and len(arms) <= 4
        and len(emergency_events) == allowed_emergency_aborts
        and not any(
            item.get("event") == "device_abort_submission_failed"
            for item in events
        )
        and int(capture_state.get("commands_sent", -1)) == len(sent)
    )
