"""Analyze and externally seal one finite CX318 Stage 5 live leg.

This analyzer never sends a command.  It replays the frequency-only
transaction and tight-deadband evidence, proves the phase/hybrid surfaces had
zero authority, and emits an immutable per-leg verdict.
"""

from __future__ import annotations

import argparse
import csv
from decimal import Decimal
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from .contracts import CsvValidationContext, validate_csv
from .cx317_active_campaign import (
    ACTIVE_CSV,
    HEALTH_CSV,
    _read_csv,
    validate_transaction_history,
)
from .active_status_contract import latest_complete_health
from .cx317_bounded_active import ResponseClassifier
from .cx318_stage5_manifest import (
    LIVE_STAGE,
    LIVE_LEG_SEAL_TYPE,
    _canonical_digest,
    validate_manifest,
)
from .cx318_stage5_rehearsal_analyze import (
    CAPTURE_STATE,
    HOST_MARKER_PREFIX,
    SUPERVISOR_EVENTS,
    SUPERVISOR_STATE,
    _authority_false,
    _contract_path,
    _host_markers,
)
from .cx318_stage5_supervisor import (
    CONTROL_CSV,
    DAC_CSV,
    ENVIRONMENT_CSV,
    ESTIMATES_CSV,
    HPR_CSV,
    PHE_CSV,
    RPH_CSV,
    TDB_CSV,
    healthy_required_direction_applications,
    load_stage5_spec,
)
from .cx318_stage5_tight_replay import replay_tight_deadband
from .cx318_stage5_tight_replay import replay_tight_deadband_chain
from .cx318_stage5_runtime_contract import evaluate_health_integrity
from .cx317_i_only_preview_replay import (
    IOnlyPreviewEngine,
    Observation,
    load_post_campaign_policy,
)
from .cx317_stage6_live_analyze import (
    EXPECTED_BACKEND,
    EXPECTED_DIAGNOSTIC_VERSION,
    EXPECTED_SELECTED_VERSION,
    SERIALIZED_12_DECIMAL_HALF_UNIT,
    TICKS_PER_SECOND,
    _check_continuity,
)
from .evidence import EVIDENCE_MANIFEST, validate_evidence_snapshot
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, COMPLETE_MARKER, load_manifest
from .capture_device import SEGMENT_CLOSURE
from .cx318_stage5_rehearsal_analyze import _capture_closure
from .timebase import unwrap_ticks


TOOL_ID = "cx318_stage5_live_analyze_v1"
OUTPUT = Path("reports/cx318_stage5_live_leg_seal_v1.json")
TRANSITION_STAGE = "CX318_STAGE5_TRANSITION_SPOOL"
TRANSITION_PROMOTION_REPORT = Path("reports/cx318_stage5_promotion_v1.json")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite Stage 5 leg seal: {path}")
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
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _bool(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"malformed Boolean {value!r}")


def _serialized_difference(value: str, expected: float) -> float:
    return float(abs(Decimal(value) - Decimal.from_float(expected)))


def _contiguous(rows: list[dict[str, str]], field: str) -> bool:
    if not rows:
        return False
    observed = [int(row[field]) for row in rows]
    return observed == list(range(observed[0], observed[-1] + 1))


def _measurement_replay(
    manifest: Any,
    manifest_value: dict[str, Any],
) -> tuple[bool, dict[str, Any], dict[str, dict[str, str]]]:
    """Recompute Stage 5 count/snapshot and estimator evidence exactly."""

    counts = _read_csv(_contract_path(manifest, "count_observations_v1"))
    snapshots = _read_csv(_contract_path(manifest, "pps_snapshots_v1"))
    references = _read_csv(_contract_path(manifest, "raw_events_v1"))
    estimates = _read_csv(_contract_path(manifest, "estimates_v2"))
    if not counts or not snapshots or not references or not estimates:
        return False, {"reason": "measurement replay source is empty"}, {}
    continuity, count_by_seq = _check_continuity(counts, snapshots, references)
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
    policy_id: str = "CX318_STAGE5_TIGHT_ACTIVE_FREQUENCY_ONLY_V1",
) -> tuple[bool, dict[str, Any]]:
    """Replay Stage 5 frequency decisions and bind each requested delta."""

    if not controls or not dac_rows:
        return False, {"reason": "controller or DAC history is empty"}
    policy = load_post_campaign_policy()
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
        if item.get("event") == "command_acknowledged"
    ]
    emergency_events = [
        item
        for item in events
        if item.get("event") == "emergency_device_abort_submitted"
    ]
    setup = f"DAC SET 0x{setup_code:04X}"
    allowed_fixed = {"CONFIG?", "DAC?", "ACTIVE?", setup}
    normal_grammar_exact = all(
        command in allowed_fixed
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
    return (
        submitted == acknowledged
        and sent == expected_sent
        and normal_grammar_exact
        and submitted.count("CONFIG?") == 1
        and submitted.count("DAC?") == 1
        and submitted.count(setup) == 1
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


def _transition_chain(
    run_dir: Path,
    manifest_value: dict[str, Any],
    capture_state: dict[str, Any],
    markers: list[dict[str, Any]],
) -> tuple[bool, dict[str, Any], list[Path]]:
    """Bind the no-authority R→T→L bridge used by the same serial owner."""

    starts = [item for item in markers if item.get("event") == "capture_started"]
    if len(starts) != 1 or not isinstance(starts[0].get("previous_run"), str):
        return False, {"reason": "live start does not name one transition source"}, []
    transition_root = Path(starts[0]["previous_run"]).resolve()
    try:
        transition_manifest = json.loads(
            (transition_root / "run_manifest.json").read_text(encoding="utf-8")
        )
        transition_state = json.loads(
            (transition_root / CAPTURE_STATE).read_text(encoding="utf-8")
        )
        transition_closure = json.loads(
            (transition_root / SEGMENT_CLOSURE).read_text(encoding="utf-8")
        )
        transition_markers = _host_markers(transition_root / "raw/serial.log")
        transition_loaded = load_manifest(transition_root)
        promotion = json.loads(
            (transition_root / TRANSITION_PROMOTION_REPORT).read_text(
                encoding="utf-8"
            )
        )
        rehearsal_seal_path = Path(
            manifest_value["stage5"]["rehearsal_seal"]["path"]
        ).resolve()
        rehearsal_seal = json.loads(rehearsal_seal_path.read_text(encoding="utf-8"))
        rehearsal_root = Path(rehearsal_seal["run"]["path"]).resolve()
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return False, {"reason": f"cannot read transition chain: {exc}"}, []
    transition_starts = [
        item for item in transition_markers if item.get("event") == "capture_started"
    ]
    transition_stops = [
        item for item in transition_markers if item.get("event") == "capture_stopped"
    ]
    counters = transition_closure.get("counters", {})
    live_generation = int(capture_state.get("transport_generation", -1))
    transition_generation = int(transition_closure.get("transport_generation", -1))
    owner_pid = int(capture_state.get("pid", -1))
    transition_manifest_source = transition_manifest.get("host", {}).get(
        "source_manifest", {}
    )
    exact = (
        transition_root.is_dir()
        and not (transition_root / CAPTURE_IN_PROGRESS_FLAG).exists()
        and transition_manifest.get("stage") == TRANSITION_STAGE
        and transition_manifest.get("actionable") is False
        and transition_manifest.get("actuation_authorized") is False
        and transition_manifest.get("host", {}).get("command_ingress") == "forbidden"
        and transition_manifest.get("host", {}).get("serial_device")
        == manifest_value["host"]["serial_device"]
        and int(transition_manifest.get("host", {}).get("baud", -1))
        == int(manifest_value["host"]["baud"])
        and transition_manifest_source.get("path")
        == str(rehearsal_root / "run_manifest.json")
        and transition_manifest_source.get("sha256")
        == _sha256_file(rehearsal_root / "run_manifest.json")
        and len(transition_starts) == 1
        and len(transition_stops) == 1
        and Path(str(transition_starts[0].get("previous_run", ""))).resolve()
        == rehearsal_root
        and int(transition_starts[0].get("owner_pid", -1)) == owner_pid
        and int(starts[0].get("owner_pid", -1)) == owner_pid
        and int(transition_closure.get("owner_pid", -1)) == owner_pid
        and transition_generation + 1 == live_generation
        and int(starts[0].get("transport_generation", -1)) == live_generation
        and transition_closure.get("closure_mode")
        == "same_owner_logical_rotation"
        and transition_closure.get("logical_segment_closed") is True
        and transition_closure.get("physical_serial_open") is True
        and transition_closure.get("serial_reopened") is False
        and Path(str(transition_closure.get("next_run", ""))).resolve() == run_dir
        and transition_state.get("capture_active") is False
        and transition_state.get("logical_segment_closed") is True
        and transition_state.get("physical_serial_open") is True
        and int(transition_state.get("pid", -1)) == owner_pid
        and int(transition_state.get("transport_generation", -1))
        == transition_generation
        and all(
            int(counters.get(name, -1)) == 0
            for name in (
                "malformed_utf8",
                "parser_errors",
                "reconnect_count",
                "commands_sent",
                "commands_rejected",
                "emergency_aborts_sent",
            )
        )
        and promotion.get("serial_reopened") is False
        and int(promotion.get("reconnect_count", -1)) == 0
        and int(promotion.get("owner_pid", -1)) == owner_pid
        and Path(str(promotion.get("rehearsal_run", ""))).resolve()
        == rehearsal_root
        and Path(str(promotion.get("transition_run", ""))).resolve()
        == transition_root
        and Path(str(promotion.get("live_run", ""))).resolve() == run_dir
    )
    relative_paths = {
        "run_manifest.json",
        "raw/serial.log",
        str(CAPTURE_STATE),
        str(SEGMENT_CLOSURE),
        str(TRANSITION_PROMOTION_REPORT),
        *(str(item["path"]) for item in transition_loaded.files),
    }
    hashes: dict[str, str] = {}
    for relative in sorted(relative_paths):
        candidate = (transition_root / relative).resolve()
        try:
            candidate.relative_to(transition_root)
        except ValueError:
            exact = False
            continue
        if not candidate.is_file():
            exact = False
            continue
        hashes[relative] = _sha256_file(candidate)
    tdb_paths = [
        _contract_path(load_manifest(rehearsal_root), "tight_deadband_decisions_v1"),
        _contract_path(transition_loaded, "tight_deadband_decisions_v1"),
        _contract_path(load_manifest(run_dir), "tight_deadband_decisions_v1"),
    ]
    return exact, {
        "root": str(transition_root),
        "owner_pid": owner_pid,
        "transport_generation": transition_generation,
        "manifest_sha256": hashes.get("run_manifest.json"),
        "source_artifacts_sha256": hashes,
        "checks": {
            "same_owner_no_reopen": exact,
            "zero_authority_and_command_free": exact,
            "rehearsal_transition_live_chain_exact": exact,
        },
    }, tdb_paths


def analyze(run_dir: Path) -> tuple[Path, dict[str, Any]]:
    run_dir = run_dir.resolve()
    if (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise ValueError("Stage 5 live capture is still active")
    if not (run_dir / COMPLETE_MARKER).is_file():
        raise ValueError("Stage 5 live run is not marked complete")
    manifest_value = validate_manifest(run_dir / "run_manifest.json")
    if manifest_value.get("stage") != LIVE_STAGE:
        raise ValueError("run is not a Stage 5 live manifest")
    manifest = load_manifest(run_dir)
    leg_name = manifest_value["stage5"]["leg"]
    spec, identities, leg = load_stage5_spec(leg_name)
    build_identity = (
        manifest_value["firmware"]["source_sha256"]
        + ":"
        + manifest_value["firmware"]["configuration_sha256"]
    )

    validations: dict[str, dict[str, Any]] = {}
    for contract in manifest_value["contracts"]:
        result = validate_csv(
            _contract_path(manifest, contract),
            CsvValidationContext(
                contract=contract,
                known_channels=manifest.known_channels,
                known_domains=manifest.known_domains,
                allow_rp2040_timer0_wrap=True,
            ),
        )
        validations[contract] = {
            "ok": result.ok,
            "rows": result.row_count,
            "errors": result.errors,
        }

    active_rows = _read_csv(run_dir / ACTIVE_CSV)
    dac_rows = _read_csv(run_dir / DAC_CSV)
    applications = [row for row in active_rows if row.get("event") == "application"]
    responses = [row for row in active_rows if row.get("event") == "response"]
    manual = [row for row in active_rows if row.get("event") == "manual_start"]
    transaction_history_exact = True
    transaction_error = ""
    try:
        validate_transaction_history(
            active_rows,
            spec,
            identities,
            build_identity,
            dual_core=True,
        )
    except (KeyError, TypeError, ValueError) as exc:
        transaction_history_exact = False
        transaction_error = str(exc)
    response_exact, response_replay = _response_replay(
        active_rows, spec.minimum_code, spec.maximum_code
    )

    measurement_exact, measurement_replay, estimates_by_id = _measurement_replay(
        manifest, manifest_value
    )

    supervisor_state = json.loads((run_dir / SUPERVISOR_STATE).read_text(encoding="utf-8"))
    supervisor_events = [
        json.loads(line)
        for line in (run_dir / SUPERVISOR_EVENTS).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    capture_state = json.loads((run_dir / CAPTURE_STATE).read_text(encoding="utf-8"))
    markers = _host_markers(run_dir / "raw/serial.log")
    transition_exact, transition_source, tdb_chain_paths = _transition_chain(
        run_dir, manifest_value, capture_state, markers
    )
    capsule_exact, capsule_hashes = _capsules_exact(
        run_dir, active_rows, supervisor_events, supervisor_state
    )
    tdb_rows = _read_csv(run_dir / TDB_CSV)
    tdb_replay = (
        replay_tight_deadband_chain(tdb_chain_paths)
        if tdb_chain_paths
        else replay_tight_deadband(run_dir / TDB_CSV)
    )
    tight_entries = [
        row
        for row in tdb_rows
        if row.get("transition") == "true"
        and row.get("state_after") == "TIGHT_INSIDE"
    ]
    healthy_expected_direction = healthy_required_direction_applications(
        active_rows, leg.required_direction
    )
    movements = [abs(int(row["requested_delta_codes"])) for row in applications]
    application_times = [int(row["application_timestamp_s"]) for row in applications]
    cadence_exact = all(
        later - earlier >= 1800
        for earlier, later in zip(application_times, application_times[1:])
    )
    epochs_exact = (
        len(manual) == 1
        and len(responses) == len(applications)
        and int(manual[0].get("dac_epoch", "-1")) == 1
        and [int(row["dac_epoch"]) for row in applications]
        == list(range(2, len(applications) + 2))
        and all(
            int(response["dac_epoch"]) == int(application["dac_epoch"])
            for application, response in zip(applications, responses)
        )
    )
    dac_exact = (
        len(dac_rows) == len(applications) + 1
        and bool(dac_rows)
        and dac_rows[0].get("event") == "manual_apply"
        and int(dac_rows[0]["dac_code_requested"]) == spec.start_code
        and int(dac_rows[0]["dac_code_applied"]) == spec.start_code
        and int(dac_rows[0]["dac_code_clamped"]) == 0
        and int(dac_rows[0]["flags"]) == 0
        and all(
            row.get("event") == "active_apply"
            and int(row["dac_code_requested"]) == int(application["requested_code"])
            and int(row["dac_code_applied"]) == int(application["applied_code"])
            and int(row["dac_code_clamped"]) == 0
            and int(row["flags"]) == 0
            for row, application in zip(
                dac_rows[1:], applications, strict=True
            )
        )
    )
    control_rows = _read_csv(run_dir / CONTROL_CSV)
    controller_controls = control_rows
    controller_estimates = estimates_by_id
    controller_tdb = tdb_rows
    controller_dac = dac_rows
    if tdb_chain_paths:
        chain_roots = [path.parent.parent for path in tdb_chain_paths]
        controller_controls = [
            row
            for root in chain_roots
            for row in _read_csv(
                _contract_path(load_manifest(root), "control_previews_v1")
            )
        ]
        chained_estimate_rows = [
            row
            for root in chain_roots
            for row in _read_csv(_contract_path(load_manifest(root), "estimates_v2"))
        ]
        controller_estimates = {
            row["estimate_id"]: row for row in chained_estimate_rows
        }
        controller_tdb = [
            row for path in tdb_chain_paths for row in _read_csv(path)
        ]
        controller_dac = [
            row
            for root in chain_roots
            for row in _read_csv(_contract_path(load_manifest(root), "dac_steps_v1"))
        ]
    controller_exact, controller_replay = _controller_replay(
        controller_controls,
        controller_estimates,
        controller_tdb,
        controller_dac,
        applications,
        stage5_policy_sha256=manifest_value["policy"]["sha256"],
    )
    final_epoch = len(applications) + 1
    rph_rows = _read_csv(run_dir / RPH_CSV)
    phe_rows = _read_csv(run_dir / PHE_CSV)
    hpr_rows = _read_csv(run_dir / HPR_CSV)
    preview_continuity = (
        _contiguous(control_rows, "control_seq")
        and _contiguous(rph_rows, "observation_sequence")
        and _contiguous(phe_rows, "observation_sequence")
        and _contiguous(hpr_rows, "preview_sequence")
        and _contiguous(tdb_rows, "decision_sequence")
        and int(rph_rows[-1]["dac_epoch"]) == final_epoch
        and int(hpr_rows[-1]["dac_epoch"]) == final_epoch
        and int(tdb_rows[-1]["dac_epoch"]) == final_epoch
    )
    current_tight = (
        bool(tdb_rows)
        and tdb_rows[-1].get("state_after") == "TIGHT_INSIDE"
        and int(tdb_rows[-1]["dac_epoch"]) == final_epoch
        and tdb_rows[-1].get("frequency_controller_eligible") == "false"
    )
    preview_paths = (CONTROL_CSV, RPH_CSV, PHE_CSV, HPR_CSV, TDB_CSV)
    previews_present = all(_read_csv(run_dir / relative) for relative in preview_paths)
    zero_authority = all(_authority_false(run_dir / relative) for relative in preview_paths)
    health = latest_complete_health(run_dir / HEALTH_CSV)
    health_integrity = evaluate_health_integrity(health)
    sources = {
        row.get("source", "").lower()
        for row in _read_csv(run_dir / ENVIRONMENT_CSV)
    }
    evidence_failures, evidence_warnings = validate_evidence_snapshot(run_dir, manifest)
    evidence_path = run_dir / EVIDENCE_MANIFEST
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    terminal = supervisor_state.get("terminal", {})
    terminal_pass = (
        terminal.get("result") == "healthy_stop"
        and terminal.get("reason") == "required_direction_and_two_estimate_tight_entry"
    )
    terminal_bounded_nonpass = (
        terminal.get("result") == "aborted"
        and terminal.get("reason") == "stage5_finite_qualified_endpoint_nonpass"
    )
    allowed_emergency_aborts = 1 if terminal_bounded_nonpass else 0
    capture_starts = [item for item in markers if item.get("event") == "capture_started"]
    capture_stops = [item for item in markers if item.get("event") == "capture_stopped"]
    capture_closure = _capture_closure(
        run_dir,
        capture_state,
        markers,
        allowed_emergency_aborts=allowed_emergency_aborts,
    )

    common_checks = {
        "manifest_exact_live_leg_profile_build_policy_and_rehearsal": True,
        "same_owner_rehearsal_transition_live_chain_exact": transition_exact,
        "all_declared_contracts_validate": all(item["ok"] for item in validations.values()),
        "zero_association_loss_decisions": validations.get(
            "association_loss_decisions_v1", {}
        ).get("rows")
        == 0,
        "capture_closed_cleanly": capture_closure["ok"],
        "command_stream_matches_supervisor_exactly": _commands_exact(
            markers,
            supervisor_events,
            capture_state,
            setup_code=spec.start_code,
            allowed_emergency_aborts=allowed_emergency_aborts,
        ),
        "transaction_history_exact": transaction_history_exact,
        "durable_transaction_capsules_and_phase_acknowledgements_exact": capsule_exact,
        "stage5_response_classifier_replay_exact": response_exact,
        "raw_measurement_and_estimator_replay_exact": measurement_exact,
        "frequency_controller_replay_and_application_binding_exact": controller_exact,
        "single_exact_setup_and_dac_epochs": epochs_exact and dac_exact,
        "automatic_limits_range_and_cadence_exact": (
            len(applications) <= 4
            and all(0 < movement <= 21 for movement in movements)
            and sum(movements) <= 84
            and cadence_exact
            and all(
                spec.minimum_code <= int(row["applied_code"]) <= spec.maximum_code
                for row in applications
            )
        ),
        "tight_deadband_replay_exact": tdb_replay.exact and bool(tdb_rows),
        "phase_hybrid_tdb_continuous_and_zero_authority": (
            previews_present and preview_continuity and zero_authority
        ),
        "both_environment_streams_present": {"sht4x", "bmp280"} <= sources,
        "live_health_has_no_drop_or_fault": health_integrity.clean,
        "sealed_evidence_snapshot_valid": (
            evidence.get("run_state") == "complete"
            and not evidence_failures
            and not evidence_warnings
        ),
    }
    pass_checks = {
        "terminal_reason_is_exact_pass": terminal_pass,
        "required_healthy_automatic_direction_demonstrated": bool(
            healthy_expected_direction
        ),
        "two_estimate_tight_entry_transition_demonstrated": (
            bool(tight_entries) and current_tight
        ),
        "terminal_disarmed_and_evidence_clear": (
            health.get(("cx317_active", "state")) == "DISARMED"
            and health.get(("cx317_active", "evidence_phase")) == "evidence_clear"
            and health.get(("cx317_active", "fail_static")) == "false"
            and supervisor_state.get("arm_pending") is False
            and len(responses) >= 1
        ),
    }
    common_pass = all(common_checks.values())
    if common_pass and all(pass_checks.values()):
        status = "passed"
        failure_class = "none"
    elif common_pass and terminal_bounded_nonpass:
        status = "bounded_nonpass"
        failure_class = "finite_endpoint_without_required_tight_entry"
    else:
        status = "failed"
        failure_class = "integrity_or_live_stop_rule_failure"
    checks = {**common_checks, **pass_checks}

    source_paths = {
        "run_manifest.json",
        "raw/serial.log",
        str(CAPTURE_STATE),
        str(SEGMENT_CLOSURE),
        str(SUPERVISOR_STATE),
        str(SUPERVISOR_EVENTS),
        str(EVIDENCE_MANIFEST),
        str(COMPLETE_MARKER),
        *(str(item["path"]) for item in manifest.files),
        *capsule_hashes,
    }
    source_hashes = {
        relative: _sha256_file(run_dir / relative)
        for relative in sorted(source_paths)
    }
    unsigned: dict[str, Any] = {
        "seal_type": LIVE_LEG_SEAL_TYPE,
        "tool": TOOL_ID,
        "tool_sha256": _sha256_file(Path(__file__)),
        "status": status,
        "failure_class": failure_class,
        "leg": leg_name,
        "profile_id": spec.profile,
        "required_direction": leg.required_direction_name,
        "policy_sha256": manifest_value["policy"]["sha256"],
        "build_manifest_sha256": manifest_value["firmware"]["sha256"],
        "uf2_sha256": manifest_value["firmware"]["uf2"]["sha256"],
        "stage4_binding_sha256": manifest_value["stage4_seal"]["binding_sha256"],
        "rehearsal_seal_sha256": manifest_value["stage5"]["rehearsal_seal"]["seal_sha256"],
        "run": {
            "path": str(run_dir),
            "manifest_sha256": _sha256_file(run_dir / "run_manifest.json"),
        },
        "capture_closure": capture_closure,
        "evidence_snapshot": {
            "path": str(evidence_path),
            "sha256": _sha256_file(evidence_path),
            "snapshot_digest": evidence.get("snapshot_digest"),
        },
        "terminal": terminal,
        "runtime_health_integrity": {
            "clean": health_integrity.clean,
            "missing": health_integrity.missing,
            "mismatches": health_integrity.mismatches,
        },
        "checks": checks,
        "contract_validation": validations,
        "transactions": {
            "history_error": transaction_error,
            "application_count": len(applications),
            "response_count": len(responses),
            "path_codes": sum(movements),
            "required_direction_count": len(healthy_expected_direction),
            "dac_epochs": [int(row["dac_epoch"]) for row in applications],
            "capsules_sha256": capsule_hashes,
            "response_replay": response_replay,
        },
        "measurement_replay": measurement_replay,
        "controller_replay": controller_replay,
        "tight_deadband_replay": tdb_replay.as_dict(),
        "tight_entry_transition_count": len(tight_entries),
        "transition_source": transition_source,
        "source_artifacts_sha256": source_hashes,
    }
    result = {**unsigned, "seal_sha256": _canonical_digest(unsigned)}
    output = run_dir / OUTPUT
    _atomic_new_json(output, result)
    return output, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        output, result = analyze(args.run_dir)
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({"status": result["status"], "output": str(output)}, sort_keys=True))
    return 0 if result["status"] in {"passed", "bounded_nonpass"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
