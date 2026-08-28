"""Execute the frozen GNSS baud schedule through the sole-owner transport.

This module is deliberately transport-inverted: it does not open a serial
device or create a second bridge.  The physical adapter must use the existing
``capture_device`` command FIFO and return request-bound snapshots retained by
that same capture session.  The accelerated operational check supplies a
deterministic no-I/O adapter to this exact runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .gnss_baud_envelope_supervisor import (
    CampaignSupervisor,
    PhasePlan,
    PROGRAMME_ID,
    SegmentPlan,
    load_contract,
)
from .serial_commands import parse_serial_command


TOOL_ID = "otis_gnss_baud_envelope_run_v1"


def transition_command(request: Mapping[str, Any]) -> str:
    source_segment_id = str(request.get("source_segment_id", request["segment_id"]))
    command = (
        f"GNSS BAUD {PROGRAMME_ID} {int(request['request_sequence'])} "
        f"{source_segment_id} {int(request['source_baud'])} "
        f"{int(request['source_baud_epoch'])} {int(request['target_baud'])}"
    )
    return parse_serial_command(command).normalized


def status_challenge_command(
    *, challenge_sequence: int, segment_id: str, baud_epoch: int
) -> str:
    command = (
        f"GNSS STATUS {PROGRAMME_ID} {challenge_sequence} {segment_id} {baud_epoch}"
    )
    return parse_serial_command(command).normalized


@dataclass(frozen=True)
class PhaseStart:
    start_ticks: int
    online_counter_ticks: int
    online_counter_domain: str
    start_counters: Mapping[str, int]
    metrics: Mapping[str, Any]


@dataclass(frozen=True)
class PhaseOutcome:
    end_ticks: int
    online_counter_ticks: int
    end_counters: Mapping[str, int]
    metrics: Mapping[str, Any]
    local_faults: tuple[Mapping[str, Any], ...] = ()
    status_challenges: tuple[Mapping[str, Any], ...] = ()
    sole_owner_preserved: bool = True
    d14_d8_noninterference: bool = True
    evidence_continuous: bool = True


class ProgrammeTransport(Protocol):
    """One capture-owner adapter; implementations must never open in parallel."""

    @property
    def now_ticks(self) -> int: ...

    def transition(
        self, request: Mapping[str, Any], command: str
    ) -> Mapping[str, Any]: ...

    def begin_online_phase(
        self,
        *,
        segment: SegmentPlan,
        phase: PhasePlan,
        baud_epoch: int,
    ) -> PhaseStart: ...

    def complete_online_phase(
        self,
        *,
        segment: SegmentPlan,
        phase: PhasePlan,
        baud_epoch: int,
        start: PhaseStart,
        status_command: Callable[[int], str],
    ) -> PhaseOutcome: ...

    def bind_heartbeat(self, callback: Callable[[int], None]) -> None: ...

    def bind_local_fault(
        self, callback: Callable[[Mapping[str, Any]], None]
    ) -> None: ...

    def final_state_evidence(self) -> Mapping[str, Any]: ...


def _validate_peak_challenges(
    contract: Mapping[str, Any], phase: PhasePlan, outcome: PhaseOutcome
) -> None:
    if phase.kind != "peak_status":
        if outcome.status_challenges:
            raise ValueError("status challenges appeared outside peak_status")
        return
    workload = contract["peak_status_workload"]
    expected = phase.duration_s * int(workload["maximum_request_rate_hz"])
    if len(outcome.status_challenges) != expected:
        raise ValueError(
            f"peak phase retained {len(outcome.status_challenges)} challenges; expected {expected}"
        )
    previous_complete: int | None = None
    period_ticks = int(workload["minimum_period_ms"]) * 1_000_000
    response_deadline_ticks = (
        int(workload["response_completion_deadline_ms"]) * 1_000_000
    )
    first_sequence: int | None = None
    for index, challenge in enumerate(outcome.status_challenges, start=1):
        if challenge.get("timestamp_domain") != "host_monotonic_ns":
            raise ValueError("peak challenge timestamps must use host_monotonic_ns")
        sequence = int(challenge.get("challenge_sequence", -1))
        if first_sequence is None:
            first_sequence = sequence
        if sequence != first_sequence + index - 1:
            raise ValueError("peak challenge sequence is not contiguous")
        sent = int(challenge.get("sent_ticks", -1))
        completed = int(challenge.get("completed_ticks", -1))
        drained = int(challenge.get("host_drained_ticks", -1))
        if sent < 0 or not sent <= completed <= drained:
            raise ValueError("peak challenge completion/drain ordering is invalid")
        response_bytes = int(challenge.get("response_bytes", -1))
        response_duration_ns = int(challenge.get("response_duration_ns", -1))
        start_offset = int(challenge.get("response_start_raw_offset", -1))
        end_offset = int(challenge.get("response_end_raw_offset", -1))
        start_status = int(challenge.get("response_start_status_sequence", -1))
        end_status = int(challenge.get("response_end_status_sequence", -1))
        response_generation = int(challenge.get("response_snapshot_generation", -1))
        peak_generation = int(
            challenge.get("completed_peak_snapshot_generation", -1)
        )
        peak_end_status = int(
            challenge.get("completed_peak_end_status_sequence", -1)
        )
        peak_sequence = int(
            challenge.get("completed_peak_challenge_sequence", -1)
        )
        if (
            response_bytes <= 0
            or response_duration_ns != completed - sent
            or start_offset < 0
            or end_offset - start_offset != response_bytes
            or start_status < 0
            or end_status <= start_status
            or response_generation <= 0
            or peak_generation <= response_generation
            or peak_end_status <= end_status
            or peak_sequence != sequence
        ):
            raise ValueError("peak challenge lacks exact retained end-marker evidence")
        if response_duration_ns > response_deadline_ticks:
            raise ValueError(
                "peak challenge exceeded the frozen response-completion deadline"
            )
        if previous_complete is not None and sent < previous_complete:
            raise ValueError("peak challenge overlapped its predecessor")
        if index > 1:
            prior_sent = int(outcome.status_challenges[index - 2]["sent_ticks"])
            if sent - prior_sent < period_ticks:
                raise ValueError("peak challenge exceeded the frozen 1 Hz cadence")
        previous_complete = drained


def run_programme(
    *,
    contract: Mapping[str, Any],
    supervisor: CampaignSupervisor,
    transport: ProgrammeTransport,
) -> dict[str, Any]:
    """Run S01..S11, stopping only for a frozen programme terminal."""

    transport.bind_heartbeat(
        lambda timestamp_ticks: supervisor.heartbeat(timestamp_ticks=timestamp_ticks)
    )
    bind_local_fault = getattr(transport, "bind_local_fault", None)
    if bind_local_fault is not None:
        bind_local_fault(
            lambda fault: supervisor.record_local_fault(
                str(fault["fault_class"]),
                timestamp_ticks=int(fault.get("timestamp_ticks", transport.now_ticks)),
                detail={
                    key: value
                    for key, value in fault.items()
                    if key not in {"fault_class", "timestamp_ticks"}
                },
            )
        )
    while supervisor.current_segment is not None and supervisor.terminal is None:
        segment = supervisor.current_segment
        assert segment is not None
        request = supervisor.next_transition_request(timestamp_ticks=transport.now_ticks)
        result = dict(transport.transition(request, transition_command(request)))
        result.setdefault("request_sequence", request["request_sequence"])
        result.setdefault("segment_id", request["segment_id"])
        result.setdefault("source_segment_id", request["source_segment_id"])
        result.setdefault("logical_segment_id", request["logical_segment_id"])
        result.setdefault("source_baud", request["source_baud"])
        result.setdefault("source_baud_epoch", request["source_baud_epoch"])
        result.setdefault("target_baud", request["target_baud"])
        result.setdefault("transition_mode", request["transition_mode"])
        result.setdefault(
            "physical_transmit_required", request["physical_transmit_required"]
        )
        supervisor.accept_transition(result, timestamp_ticks=transport.now_ticks)
        if supervisor.terminal is not None:
            break
        # A recovered target failure advances the state machine past the local
        # segment.  Continue from the exact recovered source state.
        if supervisor.current_segment is not segment:
            continue
        for phase in segment.phases:
            challenge = lambda sequence, sid=segment.source_segment_id: status_challenge_command(
                challenge_sequence=sequence,
                segment_id=sid,
                baud_epoch=supervisor.baud_epoch,
            )
            start = transport.begin_online_phase(
                segment=segment,
                phase=phase,
                baud_epoch=supervisor.baud_epoch,
            )
            supervisor.start_phase(
                timestamp_ticks=start.start_ticks,
                online_counter_ticks=start.online_counter_ticks,
                online_counter_domain=start.online_counter_domain,
                counters=start.start_counters,
                metrics=start.metrics,
            )
            outcome = transport.complete_online_phase(
                segment=segment,
                phase=phase,
                baud_epoch=supervisor.baud_epoch,
                start=start,
                status_command=challenge,
            )
            if not outcome.sole_owner_preserved:
                supervisor.programme_fault(
                    "sole_usb_serial_owner_loss", timestamp_ticks=outcome.end_ticks
                )
                break
            if not outcome.d14_d8_noninterference:
                supervisor.programme_fault(
                    "d14_d8_capture_loss", timestamp_ticks=outcome.end_ticks
                )
                break
            if not outcome.evidence_continuous:
                supervisor.programme_fault(
                    "evidence_discontinuity", timestamp_ticks=outcome.end_ticks
                )
                break
            _validate_peak_challenges(contract, phase, outcome)
            for fault in outcome.local_faults:
                supervisor.record_local_fault(
                    str(fault["fault_class"]),
                    timestamp_ticks=int(fault.get("timestamp_ticks", outcome.end_ticks)),
                    detail={
                        key: value
                        for key, value in fault.items()
                        if key not in {"fault_class", "timestamp_ticks"}
                    },
                )
            supervisor.complete_phase(
                timestamp_ticks=outcome.end_ticks,
                online_counter_ticks=outcome.online_counter_ticks,
                counters=outcome.end_counters,
                metrics=outcome.metrics,
                status_challenges=outcome.status_challenges,
            )
        if supervisor.terminal is not None:
            break
    if supervisor.terminal is not None:
        return supervisor.finish(timestamp_ticks=transport.now_ticks)
    required_final_baud = int(contract["final_state"]["required_baud"])
    if supervisor.confirmed_baud != required_final_baud:
        return supervisor.finish(
            timestamp_ticks=transport.now_ticks, final_state_evidence=None
        )
    return supervisor.finish(
        timestamp_ticks=transport.now_ticks,
        final_state_evidence=transport.final_state_evidence(),
    )


def new_supervisor(
    *,
    contract_path: Path,
    run_dir: Path,
    run_id: str,
    initial_state: Mapping[str, Any],
) -> tuple[dict[str, Any], CampaignSupervisor]:
    contract = load_contract(contract_path)
    supervisor = CampaignSupervisor(
        contract,
        run_id=run_id,
        initial_state=initial_state,
        event_path=run_dir / "reports/gnss_baud_envelope_supervisor_events_v1.jsonl",
        state_path=run_dir / "reports/gnss_baud_envelope_supervisor_state_v1.json",
    )
    return contract, supervisor
