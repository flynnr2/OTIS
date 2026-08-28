"""Frozen-contract supervisor for the GNSS baud-envelope programme.

The supervisor owns schedule and programme-terminal semantics, but never opens
the serial device.  A sole-owner capture process remains the only transport
owner; the live runner supplies bounded commands through that process and feeds
request-bound firmware snapshots back here.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping


PROGRAMME_ID = "OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_V1"
TOOL_ID = "otis_gnss_baud_envelope_supervisor_v1"
DEFAULT_CONTRACT = (
    Path(__file__).resolve().parents[2]
    / "profiles/qualification/otis_gnss_baud_envelope_characterization_v1.json"
)
EVENTS_PATH = Path("reports/gnss_baud_envelope_supervisor_events_v1.jsonl")
STATE_PATH = Path("reports/gnss_baud_envelope_supervisor_state_v1.json")

BAUD_ALLOWLIST = (9600, 19200, 38400, 57600, 115200)
EXPECTED_SEGMENTS = (
    ("S01", 9600, 1200),
    ("S02", 19200, 1200),
    ("S03", 38400, 1200),
    ("S04", 57600, 1200),
    ("S05", 115200, 1200),
    ("S06", 57600, 2700),
    ("S07", 38400, 2700),
    ("S08", 19200, 2700),
    ("S09", 9600, 2700),
    ("S10", 115200, 21900),
    ("S11", 9600, 4500),
)
EXPECTED_CONTINUATION_SEGMENTS = (
    ("S01", "S06", 57600, 1200),
    ("S02", "S07", 38400, 2700),
    ("S03", "S08", 19200, 2700),
    ("S04", "S09", 9600, 2700),
    ("S05", "S10", 115200, 21900),
    ("S06", "S11", 9600, 4500),
)
EXPECTED_RESUME_SEGMENTS = (
    ("S01", "S10", 115200, 20100),
    ("S02", "S11", 9600, 4500),
)
TRUE_PROGRAMME_FAULTS = frozenset(
    {
        "d14_d8_capture_loss",
        "shared_queue_corruption",
        "evidence_discontinuity",
        "identity_contradiction",
        "command_outside_frozen_table",
        "raw_ring_memory_or_ordering_corruption",
        "sole_usb_serial_owner_loss",
        "evidence_carrier_failure",
        "serial_link_unrecoverable",
        "operator_stop",
    }
)
RATE_LOCAL_FAULTS = frozenset(
    {
        "uart_overrun",
        "uart_framing",
        "uart_parity",
        "uart_break",
        "raw_ring_overflow",
        "metadata_checksum_failure",
        "metadata_truncation",
        "metadata_oversize",
        "parser_drop",
        "transport_metadata_hold",
        "transition_target_failed_recovered",
    }
)


def canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("GNSS baud-envelope contract root must be an object")
    if value.get("programme_id") != PROGRAMME_ID:
        raise ValueError("unexpected GNSS baud-envelope programme identity")
    authority = value.get("authority")
    if (
        not isinstance(authority, dict)
        or authority.get("physical_authority") is not False
        or authority.get("effective") is not False
    ):
        raise ValueError("tracked GNSS baud-envelope contract must keep physical authority false")
    allowlist = tuple(_contract_bauds(value))
    if allowlist != BAUD_ALLOWLIST:
        raise ValueError("GNSS baud-envelope allowlist differs from the frozen five rates")
    segments = segment_plan(value)
    continuation = value.get("continuation")
    if continuation is None:
        observed = tuple(
            (segment.segment_id, segment.baud, segment.confirmed_online_duration_s)
            for segment in segments
        )
        if observed != EXPECTED_SEGMENTS:
            raise ValueError("GNSS baud-envelope schedule differs from frozen S01..S11")
        if sum(item[2] for item in observed) != 12 * 60 * 60:
            raise ValueError("GNSS baud-envelope schedule is not exactly 12 online hours")
    else:
        if not isinstance(continuation, Mapping):
            raise ValueError("continuation contract section must be an object")
        observed_continuation = tuple(
            (
                segment.segment_id,
                segment.logical_segment_id,
                segment.baud,
                segment.confirmed_online_duration_s,
            )
            for segment in segments
        )
        resume = value.get("contract_id") == (
            "otis_gnss_baud_envelope_characterization_resume_v1"
        )
        expected_continuation = (
            EXPECTED_RESUME_SEGMENTS if resume else EXPECTED_CONTINUATION_SEGMENTS
        )
        if observed_continuation != expected_continuation:
            raise ValueError(
                "GNSS baud-envelope continuation schedule differs from local S01..S06/logical S06..S11"
            )
        expected_requests = tuple(range(1, 3 if resume else 7))
        if tuple(int(value) for value in continuation.get("local_request_sequences", ())) != expected_requests:
            raise ValueError("continuation request sequences differ")
        rejected = tuple(continuation.get("reject_logical_segment_ids_from_live_command_surface", ()))
        expected_rejected = (
            ("S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09")
            if resume
            else ("S01", "S02", "S03", "S04", "S05")
        )
        if rejected != expected_rejected:
            raise ValueError("continuation rejected logical segment set differs")
        if tuple(int(value) for value in continuation.get("attachment_baud_allowlist", ())) != BAUD_ALLOWLIST:
            raise ValueError("continuation attachment allowlist differs")
    final = value.get("final_state")
    if not isinstance(final, dict) or int(final.get("required_baud", -1)) != 9600:
        raise ValueError("GNSS baud-envelope final state must require confirmed 9600")
    transition = value.get("transition_policy")
    if not isinstance(transition, dict) or int(transition.get("initial_baud_epoch", -1)) != 1:
        raise ValueError("GNSS baud-envelope initial epoch must be 1")
    initial_baud = transition.get("initial_confirmed_baud")
    if continuation is None and int(initial_baud) != 9600:
        raise ValueError("GNSS baud-envelope initial state must be confirmed 9600 epoch 1")
    if continuation is not None and initial_baud != "fresh_attachment_baud_from_allowlist":
        raise ValueError("continuation initial baud must derive from fresh attachment")
    workload = value.get("peak_status_workload")
    if (
        not isinstance(workload, dict)
        or workload.get("command") != "GNSS STATUS"
        or int(workload.get("minimum_period_ms", -1)) != 1000
        or int(workload.get("response_completion_deadline_ms", -1)) != 5000
        or int(workload.get("maximum_request_rate_hz", -1)) != 1
        or int(workload.get("challenges_per_900_second_phase", -1)) != 900
        or workload.get(
            "next_challenge_requires_previous_complete_end_marker_and_host_drain"
        )
        is not True
        or workload.get(
            "may_overlap_transition_discovery_recovery_or_metadata_requalification"
        )
        is not False
    ):
        raise ValueError("GNSS baud-envelope peak workload differs from the frozen contract")
    return value


def _contract_bauds(contract: Mapping[str, Any]) -> list[int]:
    values = contract.get("baud_allowlist")
    if not isinstance(values, list):
        raise ValueError("contract baud_allowlist must be an array")
    result: list[int] = []
    for item in values:
        if isinstance(item, dict):
            item = item.get("baud")
        result.append(int(item))
    return result


@dataclass(frozen=True)
class PhasePlan:
    phase_id: str
    kind: str
    duration_s: int


@dataclass(frozen=True)
class SegmentPlan:
    segment_id: str
    baud: int
    confirmed_online_duration_s: int
    phases: tuple[PhasePlan, ...]
    logical_segment_id: str = ""

    @property
    def source_segment_id(self) -> str:
        return self.segment_id

    @property
    def effective_logical_segment_id(self) -> str:
        return self.logical_segment_id or self.segment_id


def _phase_values(item: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    values = item.get("phases")
    if isinstance(values, list):
        return [value for value in values if isinstance(value, Mapping)]
    values = item.get("phase_plan")
    if isinstance(values, list):
        return [value for value in values if isinstance(value, Mapping)]
    return []


def segment_plan(contract: Mapping[str, Any]) -> tuple[SegmentPlan, ...]:
    schedule = contract.get("schedule")
    if not isinstance(schedule, Mapping) or not isinstance(schedule.get("segments"), list):
        raise ValueError("contract schedule.segments must be an array")
    result: list[SegmentPlan] = []
    for raw in schedule["segments"]:
        if not isinstance(raw, Mapping):
            raise ValueError("schedule segment must be an object")
        segment_id = str(raw.get("segment_id", raw.get("id", "")))
        baud = int(raw.get("baud", raw.get("target_baud", -1)))
        duration = int(
            raw.get(
                "confirmed_online_duration_s",
                raw.get("duration_s", raw.get("confirmed_online_s", -1)),
            )
        )
        raw_phases = _phase_values(raw)
        phases: list[PhasePlan] = []
        for index, phase in enumerate(raw_phases, start=1):
            kind = str(
                phase.get(
                    "kind",
                    phase.get("class", phase.get("phase", phase.get("name", ""))),
                )
            )
            phase_id = str(
                phase.get("phase_id", phase.get("id", f"{segment_id}_P{index:02d}"))
            )
            seconds = int(
                phase.get(
                    "duration_s",
                    phase.get("confirmed_online_duration_s", phase.get("seconds", -1)),
                )
            )
            phases.append(PhasePlan(phase_id, kind, seconds))
        if not phases:
            phases = [PhasePlan(f"{segment_id}_ordinary", "ordinary", duration)]
        if sum(phase.duration_s for phase in phases) != duration:
            raise ValueError(f"{segment_id} phase durations do not equal segment duration")
        if any(phase.duration_s <= 0 for phase in phases):
            raise ValueError(f"{segment_id} has a non-positive phase duration")
        logical_segment_id = str(raw.get("logical_segment_id", segment_id))
        result.append(
            SegmentPlan(
                segment_id,
                baud,
                duration,
                tuple(phases),
                logical_segment_id,
            )
        )
    return tuple(result)


def counter_domain(contract: Mapping[str, Any], name: str) -> dict[str, Any]:
    domains = contract.get("counter_domains")
    if isinstance(domains, Mapping):
        raw = domains.get(name)
        if isinstance(raw, Mapping):
            return dict(raw)
        for candidate in domains.values():
            if isinstance(candidate, Mapping) and candidate.get("name") == name:
                return dict(candidate)
    elif isinstance(domains, list):
        for raw in domains:
            if isinstance(raw, Mapping) and raw.get("name") == name:
                return dict(raw)
    if name == "host_monotonic_ns":
        return {"name": name, "ticks_per_second": 1_000_000_000, "wraps": False}
    raise ValueError(f"unknown counter domain: {name}")


def ticks_per_second(contract: Mapping[str, Any], name: str) -> int:
    domain = counter_domain(contract, name)
    for key in ("ticks_per_second", "nominal_hz", "frequency_hz"):
        if key in domain:
            value = int(domain[key])
            if value > 0:
                return value
    if domain.get("unit") == "microseconds":
        return 1_000_000
    if domain.get("unit") == "nanoseconds":
        return 1_000_000_000
    raise ValueError(f"counter domain lacks an exact tick rate: {name}")


def exact_counter_delta(
    start: int, end: int, *, contract: Mapping[str, Any], domain_name: str
) -> int:
    if start < 0 or end < 0:
        raise ValueError("counter values must be non-negative")
    domain = counter_domain(contract, domain_name)
    modulus_value = domain.get("modulus_ticks", domain.get("modulus"))
    rollover = str(domain.get("rollover", ""))
    wraps = bool(
        domain.get(
            "wraps",
            rollover in {
                "modular_forward",
                "wrapping_unsigned_forward_only_with_half_range_ambiguity_limit",
            },
        )
    )
    if modulus_value is None and wraps and domain.get("width_bits") is not None:
        modulus_value = 1 << int(domain["width_bits"])
    if end >= start:
        return end - start
    if not wraps or modulus_value is None:
        raise ValueError(f"backward movement in non-wrapping domain {domain_name}")
    modulus = int(modulus_value)
    if not 0 <= start < modulus or not 0 <= end < modulus:
        raise ValueError(f"counter outside declared modulus for {domain_name}")
    delta = modulus - start + end
    maximum = domain.get("maximum_unambiguous_forward_ticks")
    if maximum is not None and delta > int(maximum):
        raise ValueError(f"ambiguous wrapped delta in {domain_name}")
    return delta


def exact_counter_deltas(
    start: Mapping[str, Any], end: Mapping[str, Any]
) -> dict[str, int]:
    if set(start) != set(end):
        raise ValueError("counter snapshots have different fields")
    deltas: dict[str, int] = {}
    for name in sorted(start):
        before = int(start[name])
        after = int(end[name])
        if before < 0 or after < before:
            raise ValueError(f"monotonic counter moved backward: {name}")
        deltas[name] = after - before
    return deltas


def _atomic_replace_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
        suffix=".tmp", delete=False
    ) as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class CampaignSupervisor:
    """Deterministic full or bounded-continuation state machine."""

    def __init__(
        self,
        contract: Mapping[str, Any],
        *,
        run_id: str,
        initial_state: Mapping[str, Any],
        event_path: Path | None = None,
        state_path: Path | None = None,
        clock_domain: str = "host_monotonic_ns",
    ) -> None:
        if not run_id:
            raise ValueError("run_id must be non-empty")
        self.contract = deepcopy(dict(contract))
        self.segments = segment_plan(self.contract)
        self.continuation = isinstance(self.contract.get("continuation"), Mapping)
        self.contract_sha256 = canonical_sha256(self.contract)
        self.run_id = run_id
        self.event_path = event_path
        self.state_path = state_path
        self.clock_domain = clock_domain
        ticks_per_second(self.contract, clock_domain)
        transition_policy = self.contract["transition_policy"]
        initial_baud = int(initial_state.get("confirmed_baud", -1))
        expected_initial_baud = transition_policy["initial_confirmed_baud"]
        baud_exact = (
            initial_baud in BAUD_ALLOWLIST
            if self.continuation
            and expected_initial_baud == "fresh_attachment_baud_from_allowlist"
            else initial_baud == int(expected_initial_baud)
        )
        required_initial = (
            initial_state.get("programme_id") == PROGRAMME_ID
            and initial_state.get("profile_id")
            == self.contract["firmware_profile"]["profile_id"]
            and baud_exact
            and int(initial_state.get("baud_epoch", -1))
            == int(transition_policy["initial_baud_epoch"])
            and initial_state.get("identity_confirmed") is True
            and initial_state.get("configuration_confirmed") is True
            and initial_state.get("snapshot_generation") is not None
            and (
                not self.continuation
                or (
                    initial_state.get("fresh_rmc") is True
                    and initial_state.get("fresh_gga") is True
                    and initial_state.get("fresh_two_gsa") is True
                    and initial_state.get("startup_discovery") is not None
                )
            )
        )
        if not required_initial:
            raise ValueError("initial no-command attachment snapshot is not exact")
        self.confirmed_baud = initial_baud
        self.baud_epoch = int(initial_state["baud_epoch"])
        self.initial_state = deepcopy(dict(initial_state))
        self.segment_index = 0
        self.phase_index = 0
        self.request_sequence = 0
        self.event_sequence = 0
        self.last_heartbeat_ticks = 0
        self.active_request: dict[str, Any] | None = None
        self.active_phase: dict[str, Any] | None = None
        self.transition_results: dict[int, dict[str, Any]] = {}
        self.completed_segments: list[dict[str, Any]] = []
        self.local_fault_classes: set[str] = set()
        self.terminal: dict[str, Any] | None = None
        self._write_state()

    @property
    def current_segment(self) -> SegmentPlan | None:
        if self.segment_index >= len(self.segments):
            return None
        return self.segments[self.segment_index]

    @property
    def current_phase(self) -> PhasePlan | None:
        segment = self.current_segment
        if segment is None or self.phase_index >= len(segment.phases):
            return None
        return segment.phases[self.phase_index]

    def _event(self, event: str, *, timestamp_ticks: int, **fields: Any) -> dict[str, Any]:
        if timestamp_ticks < 0:
            raise ValueError("timestamp_ticks must be non-negative")
        self.event_sequence += 1
        segment = self.current_segment
        if segment is not None and (
            "segment_id" in fields
            or event.startswith("transition_")
            or event.startswith("phase_")
            or event in {"segment_completed", "rate_local_fault"}
        ):
            fields.setdefault("source_segment_id", segment.source_segment_id)
            fields.setdefault(
                "logical_segment_id", segment.effective_logical_segment_id
            )
        value = {
            "schema_version": 1,
            "programme_id": PROGRAMME_ID,
            "contract_sha256": self.contract_sha256,
            "run_id": self.run_id,
            "event_sequence": self.event_sequence,
            "last_heartbeat_ticks": self.last_heartbeat_ticks,
            "event": event,
            "timestamp_ticks": timestamp_ticks,
            "timestamp_domain": self.clock_domain,
            **fields,
        }
        if self.event_path is not None:
            self.event_path.parent.mkdir(parents=True, exist_ok=True)
            with self.event_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        self._write_state()
        return value

    def _state(self) -> dict[str, Any]:
        segment = self.current_segment
        phase = self.current_phase
        return {
            "schema_version": 1,
            "tool": TOOL_ID,
            "programme_id": PROGRAMME_ID,
            "contract_sha256": self.contract_sha256,
            "run_id": self.run_id,
            "clock_domain": self.clock_domain,
            "initial_attachment": self.initial_state,
            "event_sequence": self.event_sequence,
            "segment_index": self.segment_index,
            "current_segment_id": None if segment is None else segment.segment_id,
            "current_source_segment_id": None if segment is None else segment.source_segment_id,
            "current_logical_segment_id": (
                None if segment is None else segment.effective_logical_segment_id
            ),
            "current_target_baud": None if segment is None else segment.baud,
            "phase_index": self.phase_index,
            "current_phase_id": None if phase is None else phase.phase_id,
            "confirmed_baud": self.confirmed_baud,
            "baud_epoch": self.baud_epoch,
            "request_sequence": self.request_sequence,
            "active_request": self.active_request,
            "active_phase": self.active_phase,
            "completed_segments": self.completed_segments,
            "first_fault_classes": sorted(self.local_fault_classes),
            "terminal": self.terminal,
        }

    def _write_state(self) -> None:
        if self.state_path is not None:
            _atomic_replace_json(self.state_path, self._state())

    def next_transition_request(self, *, timestamp_ticks: int) -> dict[str, Any]:
        if self.terminal is not None:
            raise ValueError("programme is terminal")
        segment = self.current_segment
        if segment is None:
            raise ValueError("schedule is complete")
        if self.active_phase is not None:
            raise ValueError("cannot transition during an online phase")
        if self.active_request is not None:
            return deepcopy(self.active_request)
        self.request_sequence += 1
        request = {
            "request_sequence": self.request_sequence,
            "segment_id": segment.segment_id,
            "source_segment_id": segment.source_segment_id,
            "logical_segment_id": segment.effective_logical_segment_id,
            "source_baud": self.confirmed_baud,
            "source_baud_epoch": self.baud_epoch,
            "target_baud": segment.baud,
            "expected_prior_request_sequence": self.request_sequence - 1,
            "transition_mode": (
                "same_target_session_bind"
                if self.continuation
                and self.request_sequence == 1
                and self.confirmed_baud == segment.baud
                else "baud_change"
            ),
        }
        request["physical_transmit_required"] = (
            request["transition_mode"] != "same_target_session_bind"
        )
        self.active_request = request
        self._event("transition_requested", timestamp_ticks=timestamp_ticks, **request)
        return deepcopy(request)

    def heartbeat(self, *, timestamp_ticks: int) -> None:
        """Refresh authoritative supervisor liveness without flooding the ledger."""

        if timestamp_ticks < self.last_heartbeat_ticks:
            raise ValueError("supervisor heartbeat moved backward")
        self.last_heartbeat_ticks = timestamp_ticks
        self._write_state()

    def accept_transition(
        self, result: Mapping[str, Any], *, timestamp_ticks: int
    ) -> dict[str, Any]:
        if self.terminal is not None:
            raise ValueError("programme is terminal")
        request_sequence = int(result.get("request_sequence", -1))
        normalized = deepcopy(dict(result))
        previous = self.transition_results.get(request_sequence)
        if previous is not None:
            if previous != normalized:
                self.programme_fault("identity_contradiction", timestamp_ticks=timestamp_ticks)
                raise ValueError("contradictory duplicate transition result")
            return deepcopy(previous)
        if self.active_request is None:
            self.programme_fault("identity_contradiction", timestamp_ticks=timestamp_ticks)
            raise ValueError("transition result has no active request")
        request = self.active_request
        exact = all(
            result.get(name) == request[name]
            for name in (
                "segment_id",
                "source_segment_id",
                "logical_segment_id",
                "source_baud",
                "target_baud",
                "transition_mode",
                "physical_transmit_required",
            )
        ) and int(result.get("source_baud_epoch", -1)) == request["source_baud_epoch"]
        if request_sequence != request["request_sequence"] or not exact:
            self.programme_fault("identity_contradiction", timestamp_ticks=timestamp_ticks)
            raise ValueError("transition result contradicts the active request")
        status = str(result.get("status", ""))
        self.transition_results[request_sequence] = normalized
        self.active_request = None
        if status == "confirmed":
            required = (
                "identity_confirmed",
                "configuration_confirmed",
                "fresh_rmc",
                "fresh_gga",
                "fresh_two_gsa",
                "first_dependent_snapshot_bound",
            )
            if any(result.get(field) is not True for field in required):
                self.programme_fault("identity_contradiction", timestamp_ticks=timestamp_ticks)
                raise ValueError("confirmed transition lacks causal completion evidence")
            confirmed_baud = int(result.get("confirmed_baud", -1))
            new_epoch = int(result.get("baud_epoch", -1))
            minimum_epoch = (
                self.baud_epoch
                if request["transition_mode"] == "same_target_session_bind"
                else self.baud_epoch + 1
            )
            if confirmed_baud != request["target_baud"] or new_epoch < minimum_epoch:
                self.programme_fault("identity_contradiction", timestamp_ticks=timestamp_ticks)
                raise ValueError("confirmed transition has impossible baud or epoch")
            if (
                request["transition_mode"] == "same_target_session_bind"
                and new_epoch != self.baud_epoch
            ):
                self.programme_fault("identity_contradiction", timestamp_ticks=timestamp_ticks)
                raise ValueError("same-target binding must preserve the baud epoch")
            self.confirmed_baud = confirmed_baud
            self.baud_epoch = new_epoch
            self._event("transition_confirmed", timestamp_ticks=timestamp_ticks, **normalized)
        elif status == "target_failed_recovered":
            recovered = int(result.get("recovered_baud", -1))
            new_epoch = int(result.get("baud_epoch", -1))
            if recovered not in BAUD_ALLOWLIST or new_epoch <= self.baud_epoch:
                self.programme_fault("identity_contradiction", timestamp_ticks=timestamp_ticks)
                raise ValueError("transition recovery has impossible baud or epoch")
            self.confirmed_baud = recovered
            self.baud_epoch = new_epoch
            segment = self.current_segment
            assert segment is not None
            self.completed_segments.append(
                {
                    "segment_id": segment.segment_id,
                    "source_segment_id": segment.source_segment_id,
                    "logical_segment_id": segment.effective_logical_segment_id,
                    "baud": segment.baud,
                    "status": "transition_failed_receiver_recovered",
                    "recovered_baud": recovered,
                }
            )
            self.local_fault_classes.add("transition_target_failed_recovered")
            self._event("transition_target_failed_recovered", timestamp_ticks=timestamp_ticks, **normalized)
            self.segment_index += 1
            self.phase_index = 0
            self._write_state()
        elif status == "serial_link_unrecoverable":
            self._event("transition_unrecoverable", timestamp_ticks=timestamp_ticks, **normalized)
            self.programme_fault("serial_link_unrecoverable", timestamp_ticks=timestamp_ticks)
        else:
            self.programme_fault("identity_contradiction", timestamp_ticks=timestamp_ticks)
            raise ValueError(f"unsupported transition status: {status}")
        return normalized

    def start_phase(
        self,
        *,
        timestamp_ticks: int,
        online_counter_ticks: int | None = None,
        online_counter_domain: str | None = None,
        counters: Mapping[str, Any],
        metrics: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.terminal is not None:
            raise ValueError("programme is terminal")
        if self.active_request is not None or self.active_phase is not None:
            raise ValueError("phase cannot start with another transaction active")
        segment = self.current_segment
        phase = self.current_phase
        if segment is None or phase is None:
            raise ValueError("no phase remains")
        if self.confirmed_baud != segment.baud:
            raise ValueError("phase cannot start before target baud confirmation")
        normalized_counters = {key: int(value) for key, value in counters.items()}
        if not normalized_counters or any(value < 0 for value in normalized_counters.values()):
            raise ValueError("phase start requires non-negative counter snapshot")
        online_ticks = timestamp_ticks if online_counter_ticks is None else online_counter_ticks
        online_domain = self.clock_domain if online_counter_domain is None else online_counter_domain
        ticks_per_second(self.contract, online_domain)
        self.active_phase = {
            "segment_id": segment.segment_id,
            "source_segment_id": segment.source_segment_id,
            "logical_segment_id": segment.effective_logical_segment_id,
            "baud": segment.baud,
            "baud_epoch": self.baud_epoch,
            "phase_id": phase.phase_id,
            "phase_kind": phase.kind,
            "required_duration_s": phase.duration_s,
            "start_ticks": timestamp_ticks,
            "online_start_ticks": online_ticks,
            "online_counter_domain": online_domain,
            "start_counters": normalized_counters,
        }
        return self._event(
            "phase_started",
            timestamp_ticks=timestamp_ticks,
            **self.active_phase,
            counters=normalized_counters,
            metrics=dict(metrics or {}),
        )

    def record_local_fault(
        self, fault_class: str, *, timestamp_ticks: int, detail: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        if fault_class not in RATE_LOCAL_FAULTS:
            raise ValueError(f"not a rate-local fault: {fault_class}")
        segment = self.current_segment
        if segment is None:
            raise ValueError("rate-local fault outside a scheduled segment")
        first = fault_class not in self.local_fault_classes
        self.local_fault_classes.add(fault_class)
        return self._event(
            "rate_local_fault",
            timestamp_ticks=timestamp_ticks,
            segment_id=segment.segment_id,
            baud=segment.baud,
            fault_class=fault_class,
            first_occurrence=first,
            detail=dict(detail or {}),
        )

    def complete_phase(
        self,
        *,
        timestamp_ticks: int,
        online_counter_ticks: int | None = None,
        counters: Mapping[str, Any],
        metrics: Mapping[str, Any] | None = None,
        status_challenges: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
    ) -> dict[str, Any]:
        if self.active_phase is None:
            raise ValueError("no online phase is active")
        phase = self.active_phase
        online_end_ticks = (
            timestamp_ticks if online_counter_ticks is None else online_counter_ticks
        )
        online_domain = str(phase["online_counter_domain"])
        elapsed_ticks = exact_counter_delta(
            int(phase["online_start_ticks"]), online_end_ticks,
            contract=self.contract, domain_name=online_domain
        )
        required_ticks = int(phase["required_duration_s"]) * ticks_per_second(
            self.contract, online_domain
        )
        if elapsed_ticks < required_ticks:
            raise ValueError("phase has not accumulated its confirmed-online duration")
        normalized_counters = {key: int(value) for key, value in counters.items()}
        deltas = exact_counter_deltas(phase["start_counters"], normalized_counters)
        event = self._event(
            "phase_completed",
            timestamp_ticks=timestamp_ticks,
            segment_id=phase["segment_id"],
            baud=phase["baud"],
            baud_epoch=phase["baud_epoch"],
            phase_id=phase["phase_id"],
            phase_kind=phase["phase_kind"],
            required_duration_s=phase["required_duration_s"],
            online_start_ticks=phase["online_start_ticks"],
            online_end_ticks=online_end_ticks,
            elapsed_ticks=elapsed_ticks,
            elapsed_domain=online_domain,
            counters=normalized_counters,
            counter_deltas=deltas,
            metrics=dict(metrics or {}),
            status_challenges=[dict(item) for item in status_challenges],
        )
        self.active_phase = None
        segment = self.current_segment
        assert segment is not None
        self.phase_index += 1
        if self.phase_index >= len(segment.phases):
            self.completed_segments.append(
                {
                    "segment_id": segment.segment_id,
                    "source_segment_id": segment.source_segment_id,
                    "logical_segment_id": segment.effective_logical_segment_id,
                    "baud": segment.baud,
                    "status": "complete",
                }
            )
            self._event(
                "segment_completed",
                timestamp_ticks=timestamp_ticks,
                segment_id=segment.segment_id,
                baud=segment.baud,
                confirmed_online_duration_s=segment.confirmed_online_duration_s,
            )
            self.segment_index += 1
            self.phase_index = 0
        self._write_state()
        return event

    def programme_fault(
        self,
        reason: str,
        *,
        timestamp_ticks: int,
        error_detail: str | None = None,
    ) -> dict[str, Any]:
        if reason not in TRUE_PROGRAMME_FAULTS:
            raise ValueError(f"not a frozen programme fault: {reason}")
        if self.terminal is not None:
            return deepcopy(self.terminal)
        terminal_name = (
            "serial_link_unrecoverable"
            if reason == "serial_link_unrecoverable"
            else "programme_invalid_due_to_platform_or_evidence_failure"
        )
        self.terminal = {
            "terminal": terminal_name,
            "reason": reason,
            "completed_segment_count": len(self.completed_segments),
            "last_confirmed_baud": self.confirmed_baud,
            "last_confirmed_baud_epoch": self.baud_epoch,
        }
        if error_detail is not None:
            self.terminal["error_detail"] = error_detail
        self._event("programme_terminal", timestamp_ticks=timestamp_ticks, **self.terminal)
        return deepcopy(self.terminal)

    def finish(
        self,
        *,
        timestamp_ticks: int,
        final_state_evidence: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.terminal is not None:
            return deepcopy(self.terminal)
        if self.current_segment is not None or self.active_phase is not None:
            raise ValueError("cannot finish before the frozen schedule completes")
        final = self.contract["final_state"]
        evidence = dict(final_state_evidence or {})
        required_evidence = (
            evidence.get("confirmed_baud") == int(final["required_baud"])
            and evidence.get("identity_confirmed") is True
            and evidence.get("configuration_confirmed") is True
            and evidence.get("fresh_rmc") is True
            and evidence.get("fresh_gga") is True
            and evidence.get("fresh_two_gsa") is True
            and evidence.get("snapshot_generation") is not None
            and evidence.get("metadata_frontier") is not None
        )
        if self.confirmed_baud != int(final["required_baud"]) or not required_evidence:
            return self.programme_fault("identity_contradiction", timestamp_ticks=timestamp_ticks)
        partial = any(item["status"] != "complete" for item in self.completed_segments)
        if self.continuation:
            terminal_name = (
                "multi_baud_characterization_continuation_partial_receiver_recovered"
                if partial
                else "multi_baud_characterization_continuation_complete"
            )
        else:
            terminal_name = (
                "multi_baud_characterization_partial_receiver_recovered"
                if partial
                else "multi_baud_characterization_complete"
            )
        self.terminal = {
            "terminal": terminal_name,
            "reason": "frozen_schedule_complete",
            "completed_segment_count": sum(
                item["status"] == "complete" for item in self.completed_segments
            ),
            "scheduled_segment_count": len(self.segments),
            "last_confirmed_baud": self.confirmed_baud,
            "last_confirmed_baud_epoch": self.baud_epoch,
            "final_identity_confirmed": evidence["identity_confirmed"],
            "final_configuration_confirmed": evidence["configuration_confirmed"],
            "final_metadata_requalified": True,
            "final_snapshot_generation": int(evidence["snapshot_generation"]),
            "final_metadata_frontier": int(evidence["metadata_frontier"]),
        }
        self._event("programme_terminal", timestamp_ticks=timestamp_ticks, **self.terminal)
        return deepcopy(self.terminal)


def read_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid event JSON at line {line_number}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"event line {line_number} is not an object")
            if int(value.get("event_sequence", -1)) != line_number:
                raise ValueError("event sequence is not contiguous")
            events.append(value)
    return events
