"""Independent replay analyzer for GNSS baud-envelope campaign ledgers."""

from __future__ import annotations

import argparse
from collections import defaultdict
from decimal import Decimal, localcontext
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .gnss_baud_envelope_supervisor import (
    BAUD_ALLOWLIST,
    PROGRAMME_ID,
    canonical_sha256,
    exact_counter_delta,
    exact_counter_deltas,
    load_contract,
    read_events,
    segment_plan,
    ticks_per_second,
)


TOOL_ID = "otis_gnss_baud_envelope_analyzer_v1"
ANALYSIS_TYPE = "otis_gnss_baud_envelope_analysis_v1"
CONTINUATION_ANALYSIS_TYPE = "otis_gnss_baud_envelope_continuation_analysis_v1"
CONTINUATION_CONTRACT_ID = (
    "otis_gnss_baud_envelope_characterization_continuation_v1"
)
CONTINUATION_COMPLETION_TERMINAL = "continuation_capture_complete"
RESUME_CONTRACT_ID = "otis_gnss_baud_envelope_characterization_resume_v1"
RESUME_ANALYSIS_TYPE = "otis_gnss_baud_envelope_resume_analysis_v1"
RESUME_COMPLETION_TERMINAL = "resume_capture_complete"
SEAL_TYPE = "otis_gnss_baud_envelope_seal_v1"

CONTINUATION_LOGICAL_PHASE_KEYS = (
    ("S06", "peak_status"),
    ("S06", "clean_requalification"),
    ("S07", "ordinary_entry"),
    ("S07", "peak_status"),
    ("S07", "clean_requalification"),
    ("S08", "ordinary_entry"),
    ("S08", "peak_status"),
    ("S08", "clean_requalification"),
    ("S09", "ordinary_entry"),
    ("S09", "peak_status"),
    ("S09", "clean_requalification"),
    ("S10", "ordinary_entry"),
    ("S10", "peak_status"),
    ("S10", "ordinary_soak"),
    ("S11", "closing_clean_soak"),
)
RESUME_LOGICAL_PHASE_KEYS = (
    ("S10", "ordinary_soak"),
    ("S11", "closing_clean_soak"),
)

FAULT_COUNTERS = (
    "hardware_overrun_count",
    "hardware_framing_count",
    "hardware_parity_count",
    "hardware_break_count",
    "bytes_dropped_before_retention",
    "overflow_count",
    "link_checksum_failure_count",
    "metadata_checksum_failure_count",
    "parser_drop_count",
    "truncated_count",
    "oversize_count",
)
METADATA_HOLD_COUNTERS = (
    "transport_metadata_hold_count",
)
SHARED_PLATFORM_FAULT_COUNTERS = (
    "capture_dropped_count",
    "pps_count_boundary_dropped_count",
    "d14_rejected_short_count",
    "d14_rejected_long_count",
    "pps_gate_boundary_ring_dropped_count",
    "pps_gate_rejected_window_count",
    "pps_gate_missing_pps_count",
    "pps_gate_interval_anomaly_count",
    "pps_gate_boundary_sequence_gap_count",
    "pps_gate_boundary_sequence_duplicate_count",
    "pps_gate_boundary_overflow_count",
    "pps_gate_counter_snapshot_invalid_count",
    "pps_gate_physical_aperture_incomplete_count",
    "pps_gate_association_loss_count",
    "pps_gate_snapshot_continuity_loss_count",
    "pps_gate_physical_pps_missing_count",
    "shared_queue_corruption_count",
    "dual_core_partition_fault_count",
    "telemetry_dropped_count",
)
DENOMINATOR_COUNTERS = (
    "bytes_observed",
    "metadata_checksum_valid_count",
    "rmc_count",
    "gga_count",
    "gsa_count",
)


def _sum_fields(rows: Iterable[Mapping[str, int]], names: Iterable[str]) -> int:
    return sum(int(row.get(name, 0)) for row in rows for name in names)


def _max_metric(rows: Iterable[Mapping[str, Any]], name: str) -> int | None:
    values = [int(row[name]) for row in rows if row.get(name) is not None]
    return max(values) if values else None


def _zero_bound(events: int, denominator: int, *, scale: int = 1) -> dict[str, Any]:
    if denominator <= 0:
        return {
            "event_count": events,
            "denominator": denominator,
            "one_sided_95_percent_poisson_upper_rate": None,
            "interpretation": "no denominator retained",
        }
    with localcontext() as context:
        context.prec = 16
        rate = Decimal(3 * scale) / Decimal(denominator)
    return {
        "event_count": events,
        "denominator": denominator,
        "one_sided_95_percent_poisson_upper_rate": (
            format(rate, ".12g") if events == 0 else None
        ),
        "exact_zero_event_expression": (
            f"{3 * scale}/{denominator}" if events == 0 else None
        ),
        "interpretation": (
            "finite empirical 3/N bound; not proof of timeless or independent failure probability"
            if events == 0
            else "3/N zero-event bound does not apply because events were observed"
        ),
    }


def _planned_phase_keys(contract: Mapping[str, Any]) -> set[tuple[str, str]]:
    return {
        (segment.segment_id, phase.phase_id)
        for segment in segment_plan(contract)
        for phase in segment.phases
    }


def _reconstruct_phases(
    contract: Mapping[str, Any],
    events: list[dict[str, Any]],
    *,
    recovered_segment_ids: set[str],
    continuation_mode: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    starts: dict[tuple[str, str], dict[str, Any]] = {}
    phases: list[dict[str, Any]] = []
    failures: list[str] = []
    active: tuple[str, str] | None = None
    plan = segment_plan(contract)
    planned = _planned_phase_keys(contract)
    planned_details = {
        (segment.segment_id, phase.phase_id): (
            segment.baud,
            phase.kind,
            phase.duration_s,
        )
        for segment in plan
        for phase in segment.phases
    }
    continuation_identity = {
        segment.segment_id: (
            segment.source_segment_id,
            segment.effective_logical_segment_id,
        )
        for segment in plan
    }
    expected_phase_order = [
        (segment.segment_id, phase.phase_id)
        for segment in plan
        if segment.segment_id not in recovered_segment_ids
        for phase in segment.phases
    ]
    expected_phase_index = 0
    confirmed_transition_by_segment: dict[str, dict[str, Any]] = {}
    next_challenge_sequence = 1
    previous_challenge_sent: int | None = None
    previous_challenge_drained: int | None = None
    minimum_period_ns = int(
        contract["peak_status_workload"]["minimum_period_ms"]
    ) * 1_000_000
    response_deadline_ns = int(
        contract["peak_status_workload"]["response_completion_deadline_ms"]
    ) * 1_000_000
    for event in events:
        event_name = event.get("event")
        if event_name == "transition_confirmed":
            confirmed_transition_by_segment[str(event.get("segment_id"))] = event
        if event_name == "phase_started":
            key = (str(event.get("segment_id")), str(event.get("phase_id")))
            if active is not None:
                failures.append(f"phase {key} overlaps active phase {active}")
            if key not in planned:
                failures.append(f"unplanned phase started: {key}")
            if continuation_mode and key[0] in continuation_identity:
                source_segment, logical_segment = continuation_identity[key[0]]
                if (
                    event.get("source_segment_id") != source_segment
                    or event.get("logical_segment_id") != logical_segment
                ):
                    failures.append(
                        f"continuation phase start mapping differs: {key}"
                    )
            if (
                expected_phase_index >= len(expected_phase_order)
                or key != expected_phase_order[expected_phase_index]
            ):
                failures.append(f"phase start is out of frozen schedule order: {key}")
            else:
                expected_baud, expected_kind, expected_duration = planned_details[key]
                if (
                    int(event.get("baud", -1)) != expected_baud
                    or event.get("phase_kind") != expected_kind
                    or int(event.get("required_duration_s", -1)) != expected_duration
                ):
                    failures.append(f"phase start differs from frozen contract: {key}")
            transition = confirmed_transition_by_segment.get(key[0])
            if transition is None:
                failures.append(f"phase start lacks preceding confirmed transition: {key}")
            elif (
                int(event.get("baud", -1))
                != int(transition.get("confirmed_baud", -2))
                or int(event.get("baud_epoch", -1))
                != int(transition.get("baud_epoch", -2))
            ):
                failures.append(f"phase start is not bound to transition epoch: {key}")
            if key in starts:
                failures.append(f"phase started more than once: {key}")
            starts[key] = event
            active = key
        elif event_name == "phase_completed":
            key = (str(event.get("segment_id")), str(event.get("phase_id")))
            start = starts.get(key)
            if start is None or active != key:
                failures.append(f"phase completion lacks its exact active start: {key}")
                continue
            if (
                event.get("baud") != start.get("baud")
                or event.get("baud_epoch") != start.get("baud_epoch")
                or event.get("phase_kind") != start.get("phase_kind")
            ):
                failures.append(f"phase identity changed within {key}")
            if continuation_mode and key[0] in continuation_identity:
                source_segment, logical_segment = continuation_identity[key[0]]
                if (
                    event.get("source_segment_id") != source_segment
                    or event.get("logical_segment_id") != logical_segment
                ):
                    failures.append(
                        f"continuation phase completion mapping differs: {key}"
                    )
            if event.get("elapsed_domain") != start.get("online_counter_domain"):
                failures.append(f"phase counter domain changed within {key}")
            if key in planned_details:
                expected_baud, expected_kind, expected_duration = planned_details[key]
                if (
                    int(event.get("baud", -1)) != expected_baud
                    or event.get("phase_kind") != expected_kind
                    or int(event.get("required_duration_s", -1)) != expected_duration
                ):
                    failures.append(f"phase completion differs from frozen contract: {key}")
            try:
                elapsed = exact_counter_delta(
                    int(start["online_start_ticks"]),
                    int(event["online_end_ticks"]),
                    contract=contract,
                    domain_name=str(event["elapsed_domain"]),
                )
                if elapsed != int(event.get("elapsed_ticks", -1)):
                    failures.append(f"reported elapsed ticks differ for {key}")
                rate = ticks_per_second(contract, str(event["elapsed_domain"]))
                if elapsed < int(event["required_duration_s"]) * rate:
                    failures.append(f"confirmed-online duration is short for {key}")
                deltas = exact_counter_deltas(start["counters"], event["counters"])
                if deltas != event.get("counter_deltas"):
                    failures.append(f"reported counter deltas differ for {key}")
            except (KeyError, TypeError, ValueError) as exc:
                failures.append(f"invalid exact counter evidence for {key}: {exc}")
                deltas = {}
                elapsed = 0
                rate = 1
            challenges = event.get("status_challenges", [])
            if not isinstance(challenges, list):
                failures.append(f"phase challenge ledger is not an array: {key}")
                challenges = []
            expected_challenges = (
                int(event.get("required_duration_s", 0))
                if event.get("phase_kind") == "peak_status"
                else 0
            )
            if len(challenges) != expected_challenges:
                failures.append(
                    f"phase challenge count differs from frozen workload: {key}"
                )
            for challenge in challenges:
                try:
                    sequence = int(challenge["challenge_sequence"])
                    sent = int(challenge["sent_ticks"])
                    completed_tick = int(challenge["completed_ticks"])
                    drained = int(challenge["host_drained_ticks"])
                    if sequence != next_challenge_sequence:
                        failures.append("peak challenge sequence is not programme-global contiguous")
                    next_challenge_sequence = sequence + 1
                    if challenge.get("timestamp_domain") != "host_monotonic_ns":
                        failures.append("peak challenge timestamp domain differs")
                    if not (
                        int(start["timestamp_ticks"])
                        <= sent
                        <= completed_tick
                        <= drained
                        <= int(event["timestamp_ticks"])
                    ):
                        failures.append("peak challenge lies outside host phase bounds")
                    if int(challenge.get("response_bytes", 0)) <= 0:
                        failures.append("peak challenge lacks response byte evidence")
                    response_duration = int(
                        challenge.get("response_duration_ns", -1)
                    )
                    start_status = int(
                        challenge.get("response_start_status_sequence", -1)
                    )
                    end_status = int(
                        challenge.get("response_end_status_sequence", -1)
                    )
                    response_generation = int(
                        challenge.get("response_snapshot_generation", -1)
                    )
                    peak_generation = int(
                        challenge.get("completed_peak_snapshot_generation", -1)
                    )
                    peak_end_status = int(
                        challenge.get("completed_peak_end_status_sequence", -1)
                    )
                    peak_sequence = int(
                        challenge.get("completed_peak_challenge_sequence", -1)
                    )
                    if response_duration != completed_tick - sent:
                        failures.append("peak challenge response duration differs")
                    if response_duration > response_deadline_ns:
                        failures.append(
                            "peak challenge response exceeded frozen completion deadline"
                        )
                    if start_status < 0 or end_status <= start_status:
                        failures.append("peak challenge response end marker is invalid")
                    if (
                        response_generation <= 0
                        or peak_generation <= response_generation
                        or peak_end_status <= end_status
                        or peak_sequence != sequence
                    ):
                        failures.append("peak challenge completed-tail identity differs")
                    if (
                        previous_challenge_sent is not None
                        and sent - previous_challenge_sent < minimum_period_ns
                    ):
                        failures.append("peak challenge start gap is below frozen cadence")
                    if (
                        previous_challenge_drained is not None
                        and previous_challenge_drained > sent
                    ):
                        failures.append("peak challenge overlaps prior host drain")
                    previous_challenge_sent = sent
                    previous_challenge_drained = drained
                except (KeyError, TypeError, ValueError):
                    failures.append("peak challenge ledger row is malformed")
            phases.append(
                {
                    "segment_id": key[0],
                    "phase_id": key[1],
                    "phase_kind": str(event.get("phase_kind")),
                    "baud": int(event.get("baud", -1)),
                    "baud_epoch": int(event.get("baud_epoch", -1)),
                    "elapsed_ticks": elapsed,
                    "ticks_per_second": rate,
                    "counter_deltas": deltas,
                    "metrics": dict(event.get("metrics", {})),
                    "status_challenge_count": len(challenges),
                }
            )
            active = None
            if (
                expected_phase_index < len(expected_phase_order)
                and key == expected_phase_order[expected_phase_index]
            ):
                expected_phase_index += 1
    if active is not None:
        failures.append(f"online phase lacks completion: {active}")
    completed = {(row["segment_id"], row["phase_id"]) for row in phases}
    missing = sorted(
        key for key in planned - completed if key[0] not in recovered_segment_ids
    )
    if missing:
        failures.append(f"planned phases not completed: {missing}")
    if expected_phase_index != len(expected_phase_order):
        failures.append("completed phase sequence differs from frozen schedule")
    return phases, failures


def _reconstruct_transitions(
    events: list[dict[str, Any]], contract: Mapping[str, Any], *,
    continuation_mode: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    pending: dict[int, dict[str, Any]] = {}
    transitions: list[dict[str, Any]] = []
    failures: list[str] = []
    expected_sequence = 1
    schedule = segment_plan(contract)
    configured_initial_baud = contract["transition_policy"]["initial_confirmed_baud"]
    known_baud: int | None = (
        None if continuation_mode else int(configured_initial_baud)
    )
    known_epoch = int(contract["transition_policy"]["initial_baud_epoch"])
    for event in events:
        name = event.get("event")
        if name == "transition_requested":
            sequence = int(event.get("request_sequence", -1))
            if sequence != expected_sequence:
                failures.append("transition request sequence is stale, skipped, or repeated")
            source_baud = int(event.get("source_baud", -1))
            if continuation_mode and known_baud is None:
                if source_baud not in BAUD_ALLOWLIST:
                    failures.append(
                        "continuation attachment source baud is outside the allowlist"
                    )
                known_baud = source_baud
            if source_baud != known_baud:
                failures.append("transition source baud differs from last confirmed state")
            if int(event.get("source_baud_epoch", -1)) != known_epoch:
                failures.append("transition source epoch differs from last confirmed state")
            if int(event.get("target_baud", -1)) not in BAUD_ALLOWLIST:
                failures.append("transition target is outside the frozen allowlist")
            if 1 <= sequence <= len(schedule):
                expected_segment = schedule[sequence - 1]
                if (
                    event.get("segment_id") != expected_segment.segment_id
                    or int(event.get("target_baud", -1)) != expected_segment.baud
                ):
                    failures.append("transition request differs from frozen segment order")
                if continuation_mode and (
                    event.get("source_segment_id")
                    != expected_segment.source_segment_id
                    or event.get("logical_segment_id")
                    != expected_segment.effective_logical_segment_id
                ):
                    failures.append("continuation transition mapping differs")
                expected_mode = (
                    "same_target_session_bind"
                    if sequence == 1 and source_baud == expected_segment.baud
                    else "baud_change"
                )
                if continuation_mode and (
                    event.get("transition_mode") != expected_mode
                or event.get("physical_transmit_required")
                    != (expected_mode == "baud_change")
                ):
                    failures.append("continuation transition mode differs")
            pending[sequence] = event
            expected_sequence = sequence + 1
        elif name in {
            "transition_confirmed",
            "transition_target_failed_recovered",
            "transition_unrecoverable",
        }:
            sequence = int(event.get("request_sequence", -1))
            request = pending.pop(sequence, None)
            if request is None:
                failures.append("transition result lacks its exact request")
                continue
            result_fields = [
                "segment_id",
                "source_baud",
                "source_baud_epoch",
                "target_baud",
            ]
            if continuation_mode:
                result_fields.extend(
                    (
                        "source_segment_id",
                        "logical_segment_id",
                        "transition_mode",
                        "physical_transmit_required",
                    )
                )
            for field in result_fields:
                if event.get(field) != request.get(field):
                    failures.append(f"transition result changes request field {field}")
            status = {
                "transition_confirmed": "confirmed",
                "transition_target_failed_recovered": "target_failed_recovered",
                "transition_unrecoverable": "serial_link_unrecoverable",
            }[str(name)]
            normalized = {**event, "result_status": status}
            transitions.append(normalized)
            milestones = event.get("transition_milestones")
            if not isinstance(milestones, Mapping):
                failures.append("transition result lacks progressive milestone ledger")
                milestones = {}
            try:
                acceptance = milestones["acceptance"]
                transmit = milestones["physical_transmit"]
                target = milestones["target_confirmation"]
                terminal_milestone = milestones["terminal"]
                acceptance_elapsed = int(acceptance["observed_host_elapsed_ns"])
                transmit_elapsed = int(transmit["firmware_elapsed_ms"])
                if (
                    acceptance.get("within_deadline") is not True
                    or acceptance_elapsed < 0
                    or acceptance_elapsed
                    > int(
                        contract["transition_policy"][
                            "request_acceptance_deadline_ms"
                        ]
                    )
                    * 1_000_000
                ):
                    failures.append("transition acceptance deadline proof differs")
                same_target_binding = (
                    continuation_mode
                    and request.get("transition_mode")
                    == "same_target_session_bind"
                )
                if same_target_binding:
                    if (
                        transmit.get("complete") is not False
                        or transmit.get("not_applicable_reason")
                        != "same_target_session_binding_no_pmtk251"
                        or transmit_elapsed != 0
                    ):
                        failures.append(
                            "same-target binding physical TX evidence differs"
                        )
                elif (
                    transmit.get("complete") is not True
                    or transmit_elapsed < 0
                    or transmit_elapsed
                    > int(
                        contract["transition_policy"][
                            "uart_physical_transmit_deadline_ms"
                        ]
                    )
                ):
                    failures.append("transition physical TX deadline proof differs")
            except (KeyError, TypeError, ValueError, AttributeError):
                failures.append("transition progressive milestone ledger is malformed")
                target = {}
                terminal_milestone = {}
            if status == "confirmed":
                known_baud = int(event.get("confirmed_baud", -1))
                new_epoch = int(event.get("baud_epoch", -1))
                same_target_binding = (
                    continuation_mode
                    and request.get("transition_mode")
                    == "same_target_session_bind"
                )
                epoch_valid = (
                    new_epoch == known_epoch
                    if same_target_binding
                    else new_epoch > known_epoch
                )
                if known_baud != int(request["target_baud"]) or not epoch_valid:
                    failures.append("confirmed transition has impossible target or epoch")
                known_epoch = new_epoch
                for field in (
                    "identity_confirmed",
                    "configuration_confirmed",
                    "fresh_rmc",
                    "fresh_gga",
                    "fresh_two_gsa",
                    "first_dependent_snapshot_bound",
                ):
                    if event.get(field) is not True:
                        failures.append(f"transition confirmation lacks {field}")
                if event.get("completed_within_deadline") is not True:
                    failures.append("transition confirmation lacks deadline proof")
                try:
                    target_deadline = int(
                        contract["transition_policy"][
                            "target_identity_and_output_confirmation_deadline_ms"
                        ]
                    )
                    identity_elapsed = int(target["identity_elapsed_ms"])
                    output_elapsed = int(target["output_elapsed_ms"])
                    complete_elapsed = int(
                        terminal_milestone["transition_complete_elapsed_ms"]
                    )
                    if (
                        target.get("identity_confirmed") is not True
                        or target.get("output_confirmed") is not True
                        or identity_elapsed < 0
                        or output_elapsed < 0
                        or complete_elapsed < 0
                        or identity_elapsed > target_deadline
                        or output_elapsed > target_deadline
                        or complete_elapsed < identity_elapsed
                        or complete_elapsed < output_elapsed
                        or terminal_milestone.get("state") != "complete"
                        or complete_elapsed
                        > int(
                            contract["transition_policy"][
                                "complete_transition_deadline_ms"
                            ]
                        )
                    ):
                        failures.append("confirmed transition milestone proof differs")
                except (KeyError, TypeError, ValueError, AttributeError):
                    failures.append("confirmed transition milestone proof is malformed")
            elif status == "target_failed_recovered":
                known_baud = int(event.get("recovered_baud", -1))
                new_epoch = int(event.get("baud_epoch", -1))
                if known_baud not in BAUD_ALLOWLIST or new_epoch <= known_epoch:
                    failures.append("transition recovery has impossible state")
                known_epoch = new_epoch
                try:
                    recovery_start = int(
                        terminal_milestone["recovery_started_elapsed_ms"]
                    )
                    recovery_terminal = int(
                        terminal_milestone["recovery_terminal_elapsed_ms"]
                    )
                    if (
                        terminal_milestone.get("state") != "recovered"
                        or recovery_start < 0
                        or recovery_terminal < recovery_start
                        or recovery_terminal - recovery_start
                        > int(
                            contract["transition_policy"][
                                "recovery_scan_deadline_ms"
                            ]
                        )
                        or recovery_terminal
                        > int(
                            contract["transition_policy"][
                                "serial_link_unrecoverable_deadline_ms"
                            ]
                        )
                    ):
                        failures.append("transition recovery milestone proof differs")
                except (KeyError, TypeError, ValueError, AttributeError):
                    failures.append("transition recovery milestone proof is malformed")
            else:
                try:
                    recovery_start = int(
                        terminal_milestone["recovery_started_elapsed_ms"]
                    )
                    recovery_terminal = int(
                        terminal_milestone["recovery_terminal_elapsed_ms"]
                    )
                    if (
                        terminal_milestone.get("state") != "unrecoverable"
                        or recovery_start < 0
                        or recovery_terminal < recovery_start
                        or recovery_terminal - recovery_start
                        > int(
                            contract["transition_policy"][
                                "recovery_scan_deadline_ms"
                            ]
                        )
                        or recovery_terminal
                        > int(
                            contract["transition_policy"][
                                "serial_link_unrecoverable_deadline_ms"
                            ]
                        )
                    ):
                        failures.append("unrecoverable milestone proof differs")
                except (KeyError, TypeError, ValueError, AttributeError):
                    failures.append("unrecoverable milestone proof is malformed")
    if pending:
        failures.append("transition requests lack terminal results")
    return transitions, failures


def _phase_fault_count(phase: Mapping[str, Any]) -> int:
    return _sum_fields([phase["counter_deltas"]], FAULT_COUNTERS)


def _causal_fault_classes(phases: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for phase in phases:
        delta = phase["counter_deltas"]
        if int(delta.get("hardware_overrun_count", 0)):
            cause = "hardware_fifo_not_drained_within_arrival_envelope"
        elif sum(int(delta.get(name, 0)) for name in (
            "hardware_framing_count", "hardware_parity_count", "hardware_break_count"
        )):
            cause = "baud_framing_electrical_or_receiver_serial_evidence"
        elif int(delta.get("overflow_count", 0)):
            cause = "firmware_consumer_or_service_plane_backlog"
        elif sum(int(delta.get(name, 0)) for name in (
            "metadata_checksum_failure_count", "parser_drop_count",
            "truncated_count", "oversize_count"
        )):
            cause = "receiver_content_collector_semantics_or_parser_evidence"
        elif int(delta.get("metadata_hold_count", 0)):
            cause = "receiver_solution_quality_change_not_serial_transport"
        elif _sum_fields([delta], SHARED_PLATFORM_FAULT_COUNTERS):
            cause = "platform_isolation_defect"
        else:
            continue
        result.append(
            {
                "segment_id": phase["segment_id"],
                "phase_id": phase["phase_id"],
                "baud": phase["baud"],
                "primary_interpretation": cause,
            }
        )
    return result


_CONTINUATION_SOURCE_FIELDS = (
    "source_run_id",
    "source_artifact_sha256",
    "source_contract_sha256",
    "source_firmware_uf2_sha256",
    "source_firmware_source_sha256",
    "source_firmware_config_sha256",
    "original_contract_sha256",
    "continuation_contract_sha256",
    "counter_domain",
    "source_counter_baseline_id",
)


def _require_sha256(value: object, label: str) -> str:
    text = str(value)
    if len(text) != 64 or any(byte not in "0123456789abcdef" for byte in text):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return text


def _validate_continuation_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    continuation = contract.get("continuation")
    contract_id = contract.get("contract_id")
    if contract_id not in {CONTINUATION_CONTRACT_ID, RESUME_CONTRACT_ID} or not isinstance(
        continuation, Mapping
    ):
        raise ValueError("continuation analyzer requires the distinct contract")
    if contract_id == CONTINUATION_CONTRACT_ID:
        expected_mapping = [
            {
                "local_request_sequence": index,
                "local_segment_id": f"S{index:02d}",
                "logical_segment_id": f"S{index + 5:02d}",
            }
            for index in range(1, 7)
        ]
        expected_phases = CONTINUATION_LOGICAL_PHASE_KEYS
        expected_seconds = 35_700
        predecessor_key = "historical_run_id"
        source_contract_field = "continuation_contract_sha256"
    else:
        expected_mapping = [
            {
                "local_request_sequence": 1,
                "local_segment_id": "S01",
                "logical_segment_id": "S10",
            },
            {
                "local_request_sequence": 2,
                "local_segment_id": "S02",
                "logical_segment_id": "S11",
            },
        ]
        expected_phases = RESUME_LOGICAL_PHASE_KEYS
        expected_seconds = 24_600
        predecessor_key = "predecessor_run_id"
        source_contract_field = "resume_contract_sha256"
    mapping = continuation.get("local_to_logical_segment_map")
    if mapping != expected_mapping:
        raise ValueError("continuation local-to-logical mapping differs")
    plan = segment_plan(contract)
    observed_mapping = [
        {
            "local_request_sequence": index,
            "local_segment_id": segment.segment_id,
            "logical_segment_id": segment.effective_logical_segment_id,
        }
        for index, segment in enumerate(plan, start=1)
    ]
    if observed_mapping != expected_mapping:
        raise ValueError("continuation schedule mapping differs")
    logical_phases = tuple(
        (segment.effective_logical_segment_id, phase.phase_id)
        for segment in plan
        for phase in segment.phases
    )
    total_phase_seconds = sum(
        phase.duration_s for segment in plan for phase in segment.phases
    )
    total_segment_seconds = sum(
        segment.confirmed_online_duration_s for segment in plan
    )
    if (
        logical_phases != expected_phases
        or total_phase_seconds != expected_seconds
        or total_segment_seconds != expected_seconds
    ):
        raise ValueError("continuation/resume frozen schedule differs")
    if int(contract.get("final_state", {}).get("required_baud", -1)) != 9600:
        raise ValueError("continuation final state must require fresh 9600")
    prefix = contract.get("prefix_validation")
    if not isinstance(prefix, Mapping):
        raise ValueError("continuation original-contract prefix binding is absent")
    return {
        predecessor_key: str(prefix.get("source_run_id", "")),
        "original_contract_sha256": _require_sha256(
            prefix.get(
                "original_contract_file_sha256",
                prefix.get("root_original_contract_file_sha256"),
            ),
            "continuation original contract",
        ),
        "expected_phases": expected_phases,
        "expected_seconds": expected_seconds,
        "source_contract_field": source_contract_field,
        "contract_id": str(contract_id),
    }


def _validate_continuation_source(
    value: Mapping[str, Any] | None,
    *,
    contract_lineage: Mapping[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("continuation source provenance is required")
    source: dict[str, str] = {}
    source_fields = list(_CONTINUATION_SOURCE_FIELDS)
    source_contract_field = str(contract_lineage["source_contract_field"])
    if source_contract_field not in source_fields:
        source_fields.append(source_contract_field)
    for field in source_fields:
        if field not in value or not str(value[field]):
            raise ValueError(f"continuation source provenance lacks {field}")
        source[field] = str(value[field])
    for field in (
        "source_artifact_sha256",
        "source_contract_sha256",
        "source_firmware_uf2_sha256",
        "source_firmware_source_sha256",
        "source_firmware_config_sha256",
        "original_contract_sha256",
        "continuation_contract_sha256",
        *(tuple(["resume_contract_sha256"]) if source_contract_field == "resume_contract_sha256" else ()),
    ):
        _require_sha256(source[field], f"continuation source {field}")
    if (
        source["source_contract_sha256"] != source[source_contract_field]
        or source["original_contract_sha256"]
        != contract_lineage["original_contract_sha256"]
        or source["counter_domain"] != "rp2040_timer0_extended"
    ):
        raise ValueError("continuation source contract/domain lineage differs")
    if any(event.get("run_id") != source["source_run_id"] for event in events):
        raise ValueError("continuation event source run differs")
    baseline = value.get("counter_baseline_provenance")
    expected_baseline = {
        "source_run_id": source["source_run_id"],
        "source_artifact_sha256": source["source_artifact_sha256"],
        "source_contract_sha256": source["source_contract_sha256"],
        "counter_domain": source["counter_domain"],
        "source_counter_baseline_id": source["source_counter_baseline_id"],
    }
    if not isinstance(baseline, Mapping) or dict(baseline) != expected_baseline:
        raise ValueError("continuation counter baseline/source provenance differs")
    return source


def _validate_continuation_source_gap(
    value: Mapping[str, Any] | None,
    *,
    predecessor_run_id: str,
    source: Mapping[str, str],
    resume_mode: bool = False,
) -> dict[str, Any]:
    expected = {
        ("predecessor_run_id" if resume_mode else "historical_run_id"):
            predecessor_run_id,
        ("resume_run_id" if resume_mode else "continuation_run_id"):
            source["source_run_id"],
        "capture_continuity": False,
        "firmware_continuity": False,
        "counter_baseline_continuity": False,
        "cross_run_counter_delta_permitted": False,
    }
    if not isinstance(value, Mapping) or dict(value) != expected:
        raise ValueError("continuation source gap differs")
    return expected


def _analyze_programme_events(
    *,
    contract: Mapping[str, Any],
    events: list[dict[str, Any]],
    continuation_mode: bool = False,
    include_phase_rows: bool = False,
) -> dict[str, Any]:
    contract_hash = canonical_sha256(contract)
    validation_failures: list[str] = []
    for index, event in enumerate(events, start=1):
        if int(event.get("event_sequence", -1)) != index:
            validation_failures.append("event sequence is not contiguous")
            break
        if event.get("programme_id") != PROGRAMME_ID:
            validation_failures.append("event programme identity differs")
            break
        if event.get("contract_sha256") != contract_hash:
            validation_failures.append("event contract identity differs")
            break
    transitions, transition_failures = _reconstruct_transitions(
        events, contract, continuation_mode=continuation_mode
    )
    recovered_segment_ids = {
        str(item["segment_id"])
        for item in transitions
        if item["result_status"] == "target_failed_recovered"
    }
    phases, phase_failures = _reconstruct_phases(
        contract,
        events,
        recovered_segment_ids=recovered_segment_ids,
        continuation_mode=continuation_mode,
    )
    validation_failures.extend(phase_failures)
    validation_failures.extend(transition_failures)
    terminals = [event for event in events if event.get("event") == "programme_terminal"]
    if len(terminals) != 1:
        validation_failures.append("ledger must contain exactly one programme terminal")
    terminal = terminals[-1] if terminals else None
    allowed_success_terminals = (
        {
            "multi_baud_characterization_continuation_complete",
            "multi_baud_characterization_continuation_partial_receiver_recovered",
        }
        if continuation_mode
        else {
            "multi_baud_characterization_complete",
            "multi_baud_characterization_partial_receiver_recovered",
        }
    )
    if terminal is not None:
        terminal_name = terminal.get("terminal")
        if not events or terminal is not events[-1]:
            validation_failures.append("programme terminal must be the last ledger event")
        if terminal_name not in allowed_success_terminals:
            validation_failures.append(
                "programme terminal is not a decision-bearing schedule completion"
            )
        else:
            expected_completed = len(segment_plan(contract)) - len(
                recovered_segment_ids
            )
            try:
                final_shape_exact = (
                    terminal.get("reason") == "frozen_schedule_complete"
                    and int(terminal.get("scheduled_segment_count", -1))
                    == len(segment_plan(contract))
                    and int(terminal.get("completed_segment_count", -1))
                    == expected_completed
                    and int(terminal.get("last_confirmed_baud", -1))
                    == int(contract["final_state"]["required_baud"])
                    and int(terminal.get("last_confirmed_baud_epoch", 0)) > 0
                    and terminal.get("final_identity_confirmed") is True
                    and terminal.get("final_configuration_confirmed") is True
                    and terminal.get("final_metadata_requalified") is True
                    and int(terminal.get("final_snapshot_generation", 0)) > 0
                    and int(terminal.get("final_metadata_frontier", 0)) > 0
                )
            except (TypeError, ValueError):
                final_shape_exact = False
            if not final_shape_exact:
                validation_failures.append(
                    "programme terminal lacks exact final 9600 causal evidence"
                )
            complete_terminal = (
                "multi_baud_characterization_continuation_complete"
                if continuation_mode
                else "multi_baud_characterization_complete"
            )
            partial_terminal = (
                "multi_baud_characterization_continuation_partial_receiver_recovered"
                if continuation_mode
                else "multi_baud_characterization_partial_receiver_recovered"
            )
            if terminal_name == complete_terminal and recovered_segment_ids:
                validation_failures.append(
                    "complete terminal contradicts recovered segment evidence"
                )
            if terminal_name == partial_terminal and not recovered_segment_ids:
                validation_failures.append(
                    "partial terminal lacks a recovered transition"
                )

    plan = segment_plan(contract)
    planned_by_baud: dict[int, set[str]] = defaultdict(set)
    for segment in plan:
        planned_by_baud[segment.baud].add(segment.segment_id)
    completed_phase_keys = {
        (str(phase["segment_id"]), str(phase["phase_id"])) for phase in phases
    }
    completed_by_baud: dict[int, set[str]] = defaultdict(set)
    for segment in plan:
        required = {(segment.segment_id, phase.phase_id) for phase in segment.phases}
        if required.issubset(completed_phase_keys):
            completed_by_baud[segment.baud].add(segment.segment_id)

    platform_confounded = bool(validation_failures) or any(
        _sum_fields([phase["counter_deltas"]], SHARED_PLATFORM_FAULT_COUNTERS)
        for phase in phases
    )
    per_baud: dict[str, Any] = {}
    transition_classes: dict[int, str] = {}
    for baud in BAUD_ALLOWLIST:
        involved = [
            item for item in transitions
            if int(item.get("source_baud", -1)) == baud
            or int(item.get("target_baud", -1)) == baud
        ]
        if platform_confounded and involved:
            transition_class = "transition_platform_confounded"
        elif not involved:
            transition_class = "transition_not_assessed"
        elif any(item["result_status"] != "confirmed" for item in involved):
            transition_class = "transition_unreliable"
        elif all(
            item.get("first_dependent_snapshot_bound") is True
            and item.get("completed_within_deadline") is True
            for item in involved
        ):
            transition_class = "transition_reliable_observed"
        else:
            transition_class = "transition_platform_confounded"
        transition_classes[baud] = transition_class

    for baud in BAUD_ALLOWLIST:
        baud_phases = [phase for phase in phases if phase["baud"] == baud]
        deltas = [phase["counter_deltas"] for phase in baud_phases]
        metrics = [phase["metrics"] for phase in baud_phases]
        online_ticks_by_rate: dict[int, int] = defaultdict(int)
        for phase in baud_phases:
            online_ticks_by_rate[int(phase["ticks_per_second"])] += int(phase["elapsed_ticks"])
        online_seconds = sum(
            ticks // rate for rate, ticks in online_ticks_by_rate.items()
        )
        fault_events = _sum_fields(deltas, FAULT_COUNTERS)
        transport_holds = _sum_fields(deltas, METADATA_HOLD_COUNTERS)
        shared_faults = _sum_fields(deltas, SHARED_PLATFORM_FAULT_COUNTERS)
        bytes_observed = _sum_fields(deltas, ("bytes_observed",))
        valid_frames = _sum_fields(deltas, ("metadata_checksum_valid_count",))
        ring_capacity = _max_metric(metrics, "ring_capacity_entries")
        ring_high_water = _max_metric(metrics, "ring_high_water")
        isr_drain_proven = all(
            metric.get("uart_isr_drain_complete_observed") is True for metric in metrics
        ) if metrics else False
        identity_exact = all(
            metric.get("identity_exact") is True
            and metric.get("configuration_exact") is True
            for metric in metrics
        ) if metrics else False
        complete_visits = completed_by_baud[baud] == planned_by_baud[baud]
        if not baud_phases:
            steady_class = "not_exercised"
        elif platform_confounded or shared_faults or not identity_exact:
            steady_class = "platform_confounded"
        elif fault_events or transport_holds:
            steady_class = "transport_unstable"
        elif not complete_visits:
            steady_class = "nominally_clean_insufficient_evidence"
        elif (
            ring_capacity is not None
            and ring_high_water is not None
            and ring_high_water * 2 <= ring_capacity
            and isr_drain_proven
        ):
            steady_class = "operationally_feasible_observed"
        else:
            steady_class = "operationally_feasible_low_margin"
        counter_totals = {
            name: _sum_fields(deltas, (name,))
            for name in (*FAULT_COUNTERS, *METADATA_HOLD_COUNTERS, *DENOMINATOR_COUNTERS)
        }
        per_baud[str(baud)] = {
            "baud": baud,
            "planned_visits": sorted(planned_by_baud[baud]),
            "completed_visits": sorted(completed_by_baud[baud]),
            "confirmed_online_seconds": online_seconds,
            "phase_count": len(baud_phases),
            "counter_deltas": counter_totals,
            "transport_fault_counter_increment_count": fault_events,
            "transport_caused_metadata_hold_count": transport_holds,
            "shared_platform_fault_count": shared_faults,
            "maximum_raw_ring_high_water": ring_high_water,
            "raw_ring_capacity": ring_capacity,
            "factor_of_two_observed_headroom": (
                None if ring_capacity is None or ring_high_water is None
                else ring_high_water * 2 <= ring_capacity
            ),
            "maximum_uart_isr_gap_ticks": _max_metric(metrics, "maximum_isr_entry_gap_ticks"),
            "maximum_consumer_gap_ticks": _max_metric(metrics, "maximum_service_gap_ticks"),
            "maximum_uart_isr_drain_batch": _max_metric(metrics, "maximum_isr_drain_batch"),
            "steady_online_class": steady_class,
            "transition_class": transition_classes[baud],
            "zero_event_bounds": {
                counter: {
                    "per_byte": _zero_bound(counter_totals[counter], bytes_observed),
                    "per_valid_frame": _zero_bound(counter_totals[counter], valid_frames),
                    "per_online_hour": _zero_bound(
                        counter_totals[counter], online_seconds, scale=3600
                    ),
                }
                for counter in FAULT_COUNTERS
            },
        }

    eligible = [
        baud for baud in BAUD_ALLOWLIST
        if per_baud[str(baud)]["steady_online_class"] == "operationally_feasible_observed"
        and per_baud[str(baud)]["transition_class"] == "transition_reliable_observed"
    ]
    recommended_baud = max(eligible) if eligible else 9600
    final_baud_ok = bool(
        terminal
        and terminal.get("last_confirmed_baud") == 9600
        and terminal.get("final_identity_confirmed") is True
        and terminal.get("final_configuration_confirmed") is True
        and terminal.get("final_metadata_requalified") is True
    )
    evidence_status = "passed" if not validation_failures else "failed"
    programme_terminal = None if terminal is None else terminal.get("terminal")
    result = {
        "schema_version": 1,
        "analysis_type": ANALYSIS_TYPE,
        "tool": TOOL_ID,
        "programme_id": PROGRAMME_ID,
        "contract_sha256": contract_hash,
        "evidence_status": evidence_status,
        "validation_failures": validation_failures,
        "programme_terminal": programme_terminal,
        "final_confirmed_9600": final_baud_ok,
        "phase_attribution": {
            "planned_phase_count": len(_planned_phase_keys(contract)),
            "completed_phase_count": len(phases),
            "discovery_and_transition_counters_excluded": True,
            "ordinary_and_peak_independently_retained": all(
                phase["phase_kind"] in {"ordinary_online", "peak_status", "clean_requalification"}
                for phase in phases
            ),
        },
        "per_baud": per_baud,
        "causal_fault_classifications": _causal_fault_classes(phases),
        "recommendation": {
            "selected_operational_baud": (
                recommended_baud if evidence_status == "passed" else None
            ),
            "decision": (
                "no_recommendation_evidence_invalid"
                if evidence_status != "passed"
                else (
                    f"promote_candidate_{recommended_baud}"
                    if recommended_baud > 9600
                    else "retain_9600"
                )
            ),
            "rule": "highest baud with observed steady feasibility and reliable transitions; otherwise retain 9600",
            "physical_promotion_authorized": False,
        },
    }
    if include_phase_rows:
        result["_phase_rows"] = phases
    result["analysis_sha256"] = canonical_sha256(result)
    return result


def _continuation_phase_rows(
    *,
    contract: Mapping[str, Any],
    phases: list[dict[str, Any]],
    source: Mapping[str, str],
    expected_phases: tuple[tuple[str, str], ...],
    allow_completed_prefix: bool = False,
) -> list[dict[str, Any]]:
    logical_by_local = {
        segment.segment_id: segment.effective_logical_segment_id
        for segment in segment_plan(contract)
    }
    result: list[dict[str, Any]] = []
    for phase in phases:
        local_segment_id = str(phase["segment_id"])
        logical_segment_id = logical_by_local.get(local_segment_id)
        if logical_segment_id is None:
            raise ValueError("continuation phase lacks a logical segment mapping")
        result.append(
            {
                "local_segment_id": local_segment_id,
                "logical_segment_id": logical_segment_id,
                "phase_id": phase["phase_id"],
                "phase_kind": phase["phase_kind"],
                "baud": phase["baud"],
                "baud_epoch": phase["baud_epoch"],
                "elapsed_ticks": phase["elapsed_ticks"],
                "ticks_per_second": phase["ticks_per_second"],
                "status": "completed",
                "source": dict(source),
                "counter_delta_scope": {
                    "operation": "within_source_closing_minus_opening",
                    "source_run_id": source["source_run_id"],
                    "source_artifact_sha256": source[
                        "source_artifact_sha256"
                    ],
                    "source_contract_sha256": source[
                        "source_contract_sha256"
                    ],
                    "source_counter_baseline_id": source[
                        "source_counter_baseline_id"
                    ],
                    "counter_domain": source["counter_domain"],
                },
                "counter_deltas": phase["counter_deltas"],
                "metrics": phase["metrics"],
                "status_challenge_count": phase["status_challenge_count"],
            }
        )
    logical_keys = tuple(
        (phase["logical_segment_id"], phase["phase_id"]) for phase in result
    )
    valid = (
        logical_keys == expected_phases[: len(logical_keys)]
        if allow_completed_prefix
        else logical_keys == expected_phases
    )
    if not valid:
        raise ValueError("continuation analyzed logical phase sequence differs")
    return result


def _continuation_segments(
    contract: Mapping[str, Any],
    source: Mapping[str, str],
    completed_phases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    completed_keys = {
        (str(phase["local_segment_id"]), str(phase["phase_id"]))
        for phase in completed_phases
    }
    return [
        {
            "local_segment_id": segment.segment_id,
            "logical_segment_id": segment.effective_logical_segment_id,
            "baud": segment.baud,
            "confirmed_online_seconds": segment.confirmed_online_duration_s,
            "phase_ids": [phase.phase_id for phase in segment.phases],
            "status": (
                "completed"
                if all(
                    (segment.segment_id, phase.phase_id) in completed_keys
                    for phase in segment.phases
                )
                else "incomplete"
            ),
            "source": dict(source),
            "counter_deltas_combined_across_sources": False,
        }
        for segment in segment_plan(contract)
    ]


def _analyze_continuation_events(
    *,
    contract: Mapping[str, Any],
    events: list[dict[str, Any]],
    source_provenance: Mapping[str, Any] | None,
    source_gap: Mapping[str, Any] | None,
) -> dict[str, Any]:
    lineage = _validate_continuation_contract(contract)
    resume_mode = lineage["contract_id"] == RESUME_CONTRACT_ID
    source = _validate_continuation_source(
        source_provenance,
        contract_lineage=lineage,
        events=events,
    )
    gap = _validate_continuation_source_gap(
        source_gap,
        predecessor_run_id=lineage[
            "predecessor_run_id" if resume_mode else "historical_run_id"
        ],
        source=source,
        resume_mode=resume_mode,
    )
    core = _analyze_programme_events(
        contract=contract,
        events=events,
        continuation_mode=True,
        include_phase_rows=True,
    )
    phase_rows = _continuation_phase_rows(
        contract=contract,
        phases=list(core.pop("_phase_rows")),
        source=source,
        expected_phases=lineage["expected_phases"],
        allow_completed_prefix=core["evidence_status"] != "passed",
    )
    source_programme_terminal = core.get("programme_terminal")
    result = {
        **core,
        "analysis_type": (
            RESUME_ANALYSIS_TYPE if resume_mode else CONTINUATION_ANALYSIS_TYPE
        ),
        "source": dict(source),
        "source_gap": gap,
        "source_programme_terminal": source_programme_terminal,
        "programme_terminal": None,
        "completion_terminal": (
            (
                RESUME_COMPLETION_TERMINAL
                if resume_mode
                else CONTINUATION_COMPLETION_TERMINAL
            )
            if core["evidence_status"] == "passed"
            else None
        ),
        "cross_run_counter_delta_attempted": False,
        "counter_delta_policy": {
            "rule": "subtract_only_within_one_source_run_artifact_contract_and_counter_baseline",
            "cross_source_subtraction_permitted": False,
            "counter_deltas_aggregated_across_sources": False,
        },
        ("resume_schedule" if resume_mode else "continuation_schedule"): {
            "local_segment_count": len(segment_plan(contract)),
            "logical_segment_range": (
                ["S10", "S11"] if resume_mode else ["S06", "S11"]
            ),
            "completed_phase_count": len(phase_rows),
            "required_confirmed_online_seconds": lineage["expected_seconds"],
            "observed_confirmed_online_seconds": sum(
                int(phase["elapsed_ticks"]) // int(phase["ticks_per_second"])
                for phase in phase_rows
            ),
        },
        "phases": phase_rows,
        "segments": _continuation_segments(contract, source, phase_rows),
    }
    result.pop("analysis_sha256", None)
    result["analysis_sha256"] = canonical_sha256(result)
    return result


def analyze_events(
    *,
    contract: Mapping[str, Any],
    events: list[dict[str, Any]],
    source_provenance: Mapping[str, Any] | None = None,
    source_gap: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if contract.get("contract_id") in {
        CONTINUATION_CONTRACT_ID,
        RESUME_CONTRACT_ID,
    }:
        return _analyze_continuation_events(
            contract=contract,
            events=events,
            source_provenance=source_provenance,
            source_gap=source_gap,
        )
    return _analyze_programme_events(contract=contract, events=events)


def derive_source_bindings(
    *, contract: Mapping[str, Any], contract_path: Path, events_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Derive source-local provenance from one retained live package.

    This is deliberately limited to the activated contract/build manifest and
    supervisor ledger in the same run directory.  It never infers continuity
    across runs or subtracts counters across their capture baselines.
    """

    run_dir = events_path.resolve().parent.parent
    build_path = run_dir / "reports/activated_firmware_build_manifest_v1.json"
    build = json.loads(build_path.read_text(encoding="utf-8"))
    provenance = build.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError("activated build manifest lacks provenance")
    configuration = provenance.get("configuration")
    firmware_source = provenance.get("source")
    artifacts = build.get("artifacts")
    if (
        not isinstance(configuration, Mapping)
        or not isinstance(firmware_source, Mapping)
        or not isinstance(artifacts, list)
    ):
        raise ValueError("activated build manifest source/configuration differs")
    uf2 = [
        item
        for item in artifacts
        if isinstance(item, Mapping) and str(item.get("name", "")).endswith(".uf2")
    ]
    if len(uf2) != 1:
        raise ValueError("activated build manifest must bind exactly one UF2")
    events = read_events(events_path)
    run_ids = {str(event.get("run_id", "")) for event in events}
    if len(run_ids) != 1 or not next(iter(run_ids)):
        raise ValueError("supervisor ledger does not bind one source run")
    run_id = next(iter(run_ids))
    prefix = contract.get("prefix_validation")
    if not isinstance(prefix, Mapping):
        raise ValueError("continuation/resume prefix validation is absent")
    contract_file_sha256 = sha256(contract_path.read_bytes()).hexdigest()
    original_contract_sha256 = str(
        prefix.get(
            "original_contract_file_sha256",
            prefix.get("root_original_contract_file_sha256", ""),
        )
    )
    source: dict[str, Any] = {
        "source_run_id": run_id,
        "source_artifact_sha256": sha256(events_path.read_bytes()).hexdigest(),
        "source_contract_sha256": contract_file_sha256,
        "source_firmware_uf2_sha256": str(uf2[0].get("sha256", "")),
        "source_firmware_source_sha256": str(firmware_source.get("sha256", "")),
        "source_firmware_config_sha256": str(configuration.get("sha256", "")),
        "original_contract_sha256": original_contract_sha256,
        "continuation_contract_sha256": (
            contract_file_sha256
            if contract.get("contract_id") == CONTINUATION_CONTRACT_ID
            else str(prefix.get("continuation_contract_file_sha256", ""))
        ),
        "counter_domain": "rp2040_timer0_extended",
        "source_counter_baseline_id": f"{run_id}:capture-baseline:1",
    }
    if contract.get("contract_id") == RESUME_CONTRACT_ID:
        source["resume_contract_sha256"] = contract_file_sha256
    source["counter_baseline_provenance"] = {
        key: source[key]
        for key in (
            "source_run_id",
            "source_artifact_sha256",
            "source_contract_sha256",
            "counter_domain",
            "source_counter_baseline_id",
        )
    }
    predecessor = str(prefix.get("source_run_id", ""))
    resume_mode = contract.get("contract_id") == RESUME_CONTRACT_ID
    gap = {
        ("predecessor_run_id" if resume_mode else "historical_run_id"): predecessor,
        ("resume_run_id" if resume_mode else "continuation_run_id"): run_id,
        "capture_continuity": False,
        "firmware_continuity": False,
        "counter_baseline_continuity": False,
        "cross_run_counter_delta_permitted": False,
    }
    return source, gap


def analyze(
    *,
    contract_path: Path,
    events_path: Path,
    output_path: Path | None = None,
    flash_record_path: Path | None = None,
    source_provenance_path: Path | None = None,
    source_gap_path: Path | None = None,
    source_provenance: Mapping[str, Any] | None = None,
    source_gap: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    continuation_mode = contract.get("contract_id") in {
        CONTINUATION_CONTRACT_ID,
        RESUME_CONTRACT_ID,
    }
    if source_provenance is not None and source_provenance_path is not None:
        raise ValueError("source provenance mapping and path are mutually exclusive")
    if source_gap is not None and source_gap_path is not None:
        raise ValueError("source gap mapping and path are mutually exclusive")
    if source_provenance_path is not None:
        source_provenance = json.loads(
            source_provenance_path.read_text(encoding="utf-8")
        )
    if source_gap_path is not None:
        source_gap = json.loads(source_gap_path.read_text(encoding="utf-8"))
    if continuation_mode:
        if source_provenance is None and source_gap is None:
            source_provenance, source_gap = derive_source_bindings(
                contract=contract,
                contract_path=contract_path,
                events_path=events_path,
            )
        if not isinstance(source_provenance, Mapping):
            raise ValueError("continuation analysis requires source provenance")
        if (
            source_provenance.get("source_artifact_sha256")
            != sha256(events_path.read_bytes()).hexdigest()
            or source_provenance.get("source_contract_sha256")
            != sha256(contract_path.read_bytes()).hexdigest()
        ):
            raise ValueError("continuation source artifact/contract identity differs")
    result = analyze_events(
        contract=contract,
        events=read_events(events_path),
        source_provenance=source_provenance,
        source_gap=source_gap,
    )
    if flash_record_path is not None:
        flash_record = json.loads(flash_record_path.read_text(encoding="utf-8"))
        if (
            not isinstance(flash_record, Mapping)
            or flash_record.get("status") != "passed"
            or int(flash_record.get("firmware_flash_count", -1)) != 1
        ):
            raise ValueError("physical analysis requires one successful exact flash record")
        if continuation_mode and flash_record.get("uf2_sha256") != result.get(
            "source", {}
        ).get("source_firmware_uf2_sha256"):
            raise ValueError("continuation source UF2 identity differs")
        result.pop("analysis_sha256", None)
        result["flash_record"] = {
            "path": str(flash_record_path.resolve()),
            "sha256": sha256(flash_record_path.read_bytes()).hexdigest(),
            "uf2_sha256": flash_record.get("uf2_sha256"),
            "board_serial": flash_record.get("expected_usb_serial"),
        }
        result["analysis_sha256"] = canonical_sha256(result)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    return result


def create_seal(
    *,
    contract_path: Path,
    events_path: Path,
    analysis_path: Path,
    physical_evidence: bool,
) -> dict[str, Any]:
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    unsigned = {
        "schema_version": 1,
        "seal_type": SEAL_TYPE,
        "programme_id": PROGRAMME_ID,
        "contract_sha256": sha256(contract_path.read_bytes()).hexdigest(),
        "events_sha256": sha256(events_path.read_bytes()).hexdigest(),
        "analysis_file_sha256": sha256(analysis_path.read_bytes()).hexdigest(),
        "analysis_content_sha256": analysis.get("analysis_sha256"),
        "evidence_status": analysis.get("evidence_status"),
        "programme_terminal": analysis.get("programme_terminal"),
        "final_confirmed_9600": analysis.get("final_confirmed_9600"),
        "physical_evidence": physical_evidence,
    }
    return {**unsigned, "seal_sha256": canonical_sha256(unsigned)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seal", type=Path)
    parser.add_argument("--physical-evidence", action="store_true")
    parser.add_argument("--flash-record", type=Path)
    parser.add_argument("--source-provenance", type=Path)
    parser.add_argument("--source-gap", type=Path)
    args = parser.parse_args(argv)
    result = analyze(
        contract_path=args.contract,
        events_path=args.events,
        output_path=args.output,
        flash_record_path=args.flash_record,
        source_provenance_path=args.source_provenance,
        source_gap_path=args.source_gap,
    )
    if args.seal is not None:
        seal = create_seal(
            contract_path=args.contract,
            events_path=args.events,
            analysis_path=args.output,
            physical_evidence=args.physical_evidence,
        )
        args.seal.parent.mkdir(parents=True, exist_ok=True)
        args.seal.write_text(
            json.dumps(seal, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0 if result["evidence_status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
