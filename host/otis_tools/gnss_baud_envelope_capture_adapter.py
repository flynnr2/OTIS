"""Sole-owner ``capture_device`` adapter for the GNSS baud programme.

The adapter writes only to the capture owner's bounded command FIFO and reads
only retained ``health.csv``/capture state.  It never opens the serial device.
Coherent firmware snapshots are delimited by explicit begin/end STS records;
partial bursts are never interpreted as current state.
"""

from __future__ import annotations

import csv
from collections import deque
from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping

from .capture_runtime_checks import _serial_owner_pids
from .gnss_baud_envelope_run import PhaseOutcome, PhaseStart
from .gnss_baud_envelope_supervisor import (
    BAUD_ALLOWLIST,
    PROGRAMME_ID,
    PhasePlan,
    SegmentPlan,
    exact_counter_delta,
    exact_counter_deltas,
    ticks_per_second,
)
from .serial_commands import send_timestamped_command_to_fifo


TOOL_ID = "otis_gnss_baud_envelope_capture_adapter_v1"
CHARACTERIZATION_COMPONENT = "gnss_baud_characterization"
COMMAND_TABLE_ID = "otis_gnss_fixed_pmtk_v1"
UART_COMPONENT = "gnss_uart_rx"
RECEIVER_COMPONENT = "gnss_receiver"
STARTUP_DISCOVERY_TELEMETRY_KEYS = (
    "startup_hint_attempted",
    "startup_hint_baud",
    "startup_hint_identity_outcome",
    "startup_fallback_entered",
    "initial_discovery_identity_baud",
    "initial_discovery_outcome",
    "pmtk605_peripheral_complete_count",
    "pmtk605_last_peripheral_complete_ticks",
    "pmtk605_last_peripheral_complete_ticks_available",
    "pmtk605_last_peripheral_complete_ticks_domain",
)
CAPTURE_STATE = Path("reports/capture_device_state.json")
HEALTH_CSV = Path("csv/health.csv")
RAW_SERIAL = Path("raw/serial.log")
EXTENDED_COUNTER_KEY = "extended_counter_ticks"
LIVE_CAPTURE_STATUS_INTERVAL_S = 1.0
FIRMWARE_SNAPSHOT_DEADLINE_S = 15.0
PLATFORM_MIRROR_ADVANCE_DEADLINE_S = 15.0
INITIAL_ATTACHMENT_DEADLINE_S = 120.0
CONTINUATION_NMEA_IDENTITY = "NMEA_CADENCE_OBSERVED"
ONLINE_FAULT_COUNTERS = frozenset(
    {
        "bytes_dropped_before_retention",
        "hardware_overrun_count",
        "hardware_framing_count",
        "hardware_parity_count",
        "hardware_break_count",
        "overflow_count",
        "link_checksum_failure_count",
        "metadata_checksum_failure_count",
        "parser_drop_count",
        "truncated_count",
        "oversize_count",
        "metadata_hold_count",
    }
)

UART_COUNTER_KEYS = {
    "uart_bytes_observed": "bytes_observed",
    "uart_bytes_dropped_before_retention": "bytes_dropped_before_retention",
    "uart_rx_interrupt_count": "rx_irq_count",
    "hardware_overrun_count": "hardware_overrun_count",
    "hardware_framing_count": "hardware_framing_count",
    "hardware_parity_count": "hardware_parity_count",
    "hardware_break_count": "hardware_break_count",
    "ring_overflow_count": "overflow_count",
    "consumer_service_call_count": "service_call_count",
    "consumer_budget_exhausted_count": "budget_exhausted_call_count",
    "ring_nonempty_after_budget_count": "ring_nonempty_after_budget_call_count",
}
RECEIVER_COUNTER_KEYS = {
    "link_checksum_valid_count": "link_checksum_valid_count",
    "link_checksum_failure_count": "link_checksum_failure_count",
    "checksum_valid_count": "metadata_checksum_valid_count",
    "checksum_failure_count": "metadata_checksum_failure_count",
    "parser_drop_count": "parser_drop_count",
    "truncated_count": "truncated_count",
    "oversize_count": "oversize_count",
    "rmc_count": "rmc_count",
    "gga_count": "gga_count",
    "gsa_count": "gsa_count",
    "metadata_hold_count": "metadata_hold_count",
}
NONINTERFERENCE_COUNTER_KEYS = {
    ("capture", "dropped_count"): "capture_dropped_count",
    ("capture", "pps_count_boundary_dropped_count"):
        "pps_count_boundary_dropped_count",
    ("pps_d14", "rejected_short_count"): "d14_rejected_short_count",
    ("pps_d14", "rejected_long_count"): "d14_rejected_long_count",
    ("pps_gate", "boundary_ring_dropped_count"):
        "pps_gate_boundary_ring_dropped_count",
    ("pps_gate", "rejected_window_count"): "pps_gate_rejected_window_count",
    ("pps_gate", "missing_pps_count"): "pps_gate_missing_pps_count",
    ("pps_gate", "pps_interval_anomaly_count"):
        "pps_gate_interval_anomaly_count",
    ("pps_gate", "boundary_sequence_gap_count"):
        "pps_gate_boundary_sequence_gap_count",
    ("pps_gate", "boundary_sequence_duplicate_count"):
        "pps_gate_boundary_sequence_duplicate_count",
    ("pps_gate", "boundary_overflow_count"): "pps_gate_boundary_overflow_count",
    ("pps_gate", "counter_snapshot_invalid_count"):
        "pps_gate_counter_snapshot_invalid_count",
    ("pps_gate", "physical_aperture_incomplete_count"):
        "pps_gate_physical_aperture_incomplete_count",
    ("pps_gate", "association_loss_count"): "pps_gate_association_loss_count",
    ("pps_gate", "snapshot_continuity_loss_count"):
        "pps_gate_snapshot_continuity_loss_count",
    ("pps_gate", "physical_pps_missing_count"):
        "pps_gate_physical_pps_missing_count",
    ("dual_core", "service_publish_failures"):
        "shared_queue_corruption_count",
    ("dual_core", "telemetry_dropped"): "telemetry_dropped_count",
}
METRIC_KEYS = {
    (UART_COMPONENT, "phase_window_maximum_bytes_drained_per_interrupt"):
        "maximum_isr_drain_batch",
    (UART_COMPONENT, "phase_window_maximum_interrupt_gap_ticks"):
        "maximum_isr_entry_gap_ticks",
    (UART_COMPONENT, "phase_window_maximum_interrupt_residence_ticks"):
        "maximum_isr_residence_ticks",
    (UART_COMPONENT, "phase_window_ring_high_water"): "ring_high_water",
    (UART_COMPONENT, "phase_window_maximum_consumer_service_gap_ticks"):
        "maximum_service_gap_ticks",
    (UART_COMPONENT, "phase_window_maximum_consumer_drain_batch"):
        "maximum_consumer_drain_batch",
}
COMPLETED_PEAK_METRIC_KEYS = {
    (UART_COMPONENT, "completed_peak_maximum_bytes_drained_per_interrupt"):
        "maximum_isr_drain_batch",
    (UART_COMPONENT, "completed_peak_maximum_interrupt_gap_ticks"):
        "maximum_isr_entry_gap_ticks",
    (UART_COMPONENT, "completed_peak_maximum_interrupt_residence_ticks"):
        "maximum_isr_residence_ticks",
    (UART_COMPONENT, "completed_peak_ring_high_water"): "ring_high_water",
    (UART_COMPONENT, "completed_peak_maximum_consumer_service_gap_ticks"):
        "maximum_service_gap_ticks",
    (UART_COMPONENT, "completed_peak_maximum_consumer_drain_batch"):
        "maximum_consumer_drain_batch",
}


class ProgrammeTerminalError(RuntimeError):
    """Immediate evidence-bearing terminal raised by the live adapter."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class RetainedSnapshot:
    generation: int
    begin_status_sequence: int
    end_status_sequence: int
    end_timestamp_ticks: int
    fields: Mapping[tuple[str, str], str]
    field_status_sequences: Mapping[tuple[str, str], int]
    field_timestamp_ticks: Mapping[tuple[str, str], int]

    def value(self, component: str, key: str) -> str:
        try:
            return self.fields[(component, key)]
        except KeyError as exc:
            raise ValueError(f"coherent snapshot lacks {component}.{key}") from exc

    def integer(self, component: str, key: str) -> int:
        value = self.value(component, key)
        if not value.isdigit():
            raise ValueError(f"snapshot {component}.{key} is not unsigned integer")
        return int(value)

    def observed_in_envelope(self, component: str, key: str) -> bool:
        sequence = self.field_status_sequences.get((component, key))
        return (
            sequence is not None
            and self.begin_status_sequence < sequence < self.end_status_sequence
        )


class HealthSnapshotReducer:
    """Incrementally reduce an append-only health CSV in O(new bytes)."""

    def __init__(self, path: Path, *, retention: int = 64) -> None:
        if retention <= 0:
            raise ValueError("snapshot retention must be positive")
        self.path = path
        self.offset = 0
        self.partial = b""
        self.header: list[str] | None = None
        self.active: dict[tuple[str, str], str] | None = None
        self.active_status_sequences: dict[tuple[str, str], int] | None = None
        self.active_timestamp_ticks: dict[tuple[str, str], int] | None = None
        self.active_begin_status_sequence: int | None = None
        self.snapshots: deque[RetainedSnapshot] = deque(maxlen=retention)
        self.bytes_read = 0

    def _row(self, line: bytes) -> dict[str, str]:
        text = line.decode("utf-8")
        if self.header is None:
            self.header = next(csv.reader([text]))
            return {}
        values = next(csv.reader([text]))
        if len(values) != len(self.header):
            raise ValueError("health CSV row has wrong field count")
        return dict(zip(self.header, values, strict=True))

    def poll(self) -> list[RetainedSnapshot]:
        if not self.path.is_file():
            return []
        size = self.path.stat().st_size
        if size < self.offset:
            raise ValueError("health CSV was truncated during capture")
        with self.path.open("rb") as handle:
            handle.seek(self.offset)
            chunk = handle.read()
            self.offset = handle.tell()
        self.bytes_read += len(chunk)
        data = self.partial + chunk
        parts = data.split(b"\n")
        self.partial = parts.pop()
        lines = parts
        completed: list[RetainedSnapshot] = []
        for raw_line in lines:
            row = self._row(raw_line.rstrip(b"\r"))
            if not row:
                continue
            component = row.get("component", "")
            key = row.get("status_key", "")
            value = row.get("status_value", "")
            identity = (component, key)
            try:
                row_status_sequence = int(row["status_seq"])
                row_timestamp_ticks = int(row["timestamp_ticks"])
            except (KeyError, ValueError) as exc:
                raise ValueError("health CSV status identity is malformed") from exc
            if (
                component == CHARACTERIZATION_COMPONENT
                and key == "snapshot"
                and value == "begin"
            ):
                self.active = {identity: value}
                self.active_status_sequences = {identity: row_status_sequence}
                self.active_timestamp_ticks = {identity: row_timestamp_ticks}
                self.active_begin_status_sequence = row_status_sequence
                continue
            if self.active is None:
                continue
            assert self.active_status_sequences is not None
            assert self.active_timestamp_ticks is not None
            if identity in self.active and not (
                identity == (CHARACTERIZATION_COMPONENT, "snapshot")
                and value == "end"
            ):
                raise ValueError(
                    f"duplicate field inside coherent snapshot: {component}.{key}"
                )
            self.active[identity] = value
            self.active_status_sequences[identity] = row_status_sequence
            self.active_timestamp_ticks[identity] = row_timestamp_ticks
            if not (
                component == CHARACTERIZATION_COMPONENT
                and key == "snapshot"
                and value == "end"
            ):
                continue
            try:
                generation = int(
                    self.active[(CHARACTERIZATION_COMPONENT, "snapshot_generation")]
                )
                status_sequence = int(row["status_seq"])
                timestamp_ticks = int(row["timestamp_ticks"])
            except (KeyError, ValueError):
                self.active = None
                continue
            snapshot = RetainedSnapshot(
                    generation=generation,
                    begin_status_sequence=int(self.active_begin_status_sequence),
                end_status_sequence=status_sequence,
                end_timestamp_ticks=timestamp_ticks,
                fields=dict(self.active),
                field_status_sequences=dict(self.active_status_sequences),
                field_timestamp_ticks=dict(self.active_timestamp_ticks),
            )
            if self.snapshots and snapshot.generation <= self.snapshots[-1].generation:
                raise ValueError("coherent snapshot generation is not strictly increasing")
            self.snapshots.append(snapshot)
            completed.append(snapshot)
            self.active = None
            self.active_status_sequences = None
            self.active_timestamp_ticks = None
            self.active_begin_status_sequence = None
        return completed


def retained_snapshots(path: Path) -> list[RetainedSnapshot]:
    """Reconstruct complete snapshots for bounded offline fixtures."""

    reducer = HealthSnapshotReducer(path, retention=1_000_000)
    reducer.poll()
    return list(reducer.snapshots)


def snapshot_counters(snapshot: RetainedSnapshot) -> dict[str, int]:
    result: dict[str, int] = {}
    for source, target in UART_COUNTER_KEYS.items():
        result[target] = snapshot.integer(UART_COMPONENT, source)
    for source, target in RECEIVER_COUNTER_KEYS.items():
        result[target] = snapshot.integer(RECEIVER_COMPONENT, source)
    for identity, target in NONINTERFERENCE_COUNTER_KEYS.items():
        result[target] = snapshot.integer(*identity)
    result["dual_core_partition_fault_count"] = (
        0 if snapshot.value("dual_core", "partition_fault") == "none" else 1
    )
    return result


def snapshot_metrics(snapshot: RetainedSnapshot, *, ring_capacity: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ring_capacity_entries": ring_capacity,
        "identity_exact": snapshot.value(RECEIVER_COMPONENT, "identity_stable") == "true",
        "configuration_exact": snapshot.value(RECEIVER_COMPONENT, "configuration_confirmed") == "true",
        "uart_isr_drain_complete_observed": (
            snapshot.value(UART_COMPONENT, "isr_drain_policy")
            == "drain_fifo_until_empty"
            and snapshot.value(UART_COMPONENT, "isr_timing_policy")
            == "entry_exit_timer_reads_only"
        ),
        "phase_window_sequence": snapshot.integer(
            UART_COMPONENT, "phase_window_sequence"
        ),
    }
    for identity, target in METRIC_KEYS.items():
        result[target] = snapshot.integer(*identity)
    return result


def completed_peak_metrics(
    snapshot: RetainedSnapshot,
    *,
    expected_challenge_sequence: int,
    ring_capacity: int,
) -> dict[str, Any]:
    """Extract only the immutable firmware tail for one completed challenge."""

    if (
        snapshot.value(UART_COMPONENT, "completed_peak_available") != "true"
        or snapshot.integer(
            UART_COMPONENT, "completed_peak_challenge_sequence"
        ) != expected_challenge_sequence
        or snapshot.value(UART_COMPONENT, "completed_peak_observation_phase")
        != "peak_load"
    ):
        raise ValueError(
            "completed peak UART tail is unavailable or belongs to another challenge"
        )
    result: dict[str, Any] = {
        "ring_capacity_entries": ring_capacity,
        "identity_exact": snapshot.value(RECEIVER_COMPONENT, "identity_stable")
        == "true",
        "configuration_exact": snapshot.value(
            RECEIVER_COMPONENT, "configuration_confirmed"
        )
        == "true",
        "uart_isr_drain_complete_observed": (
            snapshot.value(UART_COMPONENT, "isr_drain_policy")
            == "drain_fifo_until_empty"
            and snapshot.value(UART_COMPONENT, "isr_timing_policy")
            == "entry_exit_timer_reads_only"
        ),
        "phase_window_sequence": expected_challenge_sequence,
    }
    for identity, target in COMPLETED_PEAK_METRIC_KEYS.items():
        result[target] = snapshot.integer(*identity)
    return result


def startup_discovery_evidence(
    snapshot: RetainedSnapshot,
    contract: Mapping[str, Any],
    *,
    require_resolved: bool = False,
) -> dict[str, Any]:
    """Validate and retain the causal startup-discovery transaction state."""
    startup = contract.get("startup_discovery")
    if not isinstance(startup, Mapping):
        raise ValueError("startup discovery contract is unavailable")
    if startup.get("required_causal_telemetry") != list(
        STARTUP_DISCOVERY_TELEMETRY_KEYS
    ):
        raise ValueError("startup discovery telemetry contract differs")
    hint_baud = snapshot.integer(RECEIVER_COMPONENT, "startup_hint_baud")
    attempted = snapshot.value(RECEIVER_COMPONENT, "startup_hint_attempted")
    hint_outcome = snapshot.value(
        RECEIVER_COMPONENT, "startup_hint_identity_outcome"
    )
    fallback_entered = snapshot.value(
        RECEIVER_COMPONENT, "startup_fallback_entered"
    )
    identity_baud_value = snapshot.value(
        RECEIVER_COMPONENT, "initial_discovery_identity_baud"
    )
    initial_outcome = snapshot.value(RECEIVER_COMPONENT, "initial_discovery_outcome")
    complete_count = snapshot.integer(
        RECEIVER_COMPONENT, "pmtk605_peripheral_complete_count"
    )
    complete_ticks = snapshot.integer(
        RECEIVER_COMPONENT, "pmtk605_last_peripheral_complete_ticks"
    )
    ticks_available = snapshot.value(
        RECEIVER_COMPONENT, "pmtk605_last_peripheral_complete_ticks_available"
    )
    ticks_domain = snapshot.value(
        RECEIVER_COMPONENT, "pmtk605_last_peripheral_complete_ticks_domain"
    )
    if (
        attempted not in {"true", "false"}
        or fallback_entered not in {"true", "false"}
        or hint_outcome
        not in {
            "not_attempted",
            "pending",
            "confirmed",
            "timed_out",
            "transmit_failed",
        }
        or initial_outcome not in {"pending", "hint_confirmed", "fallback_confirmed"}
        or ticks_available not in {"true", "false"}
        or hint_baud != int(startup["hint_baud"])
        or ticks_domain != startup["pmtk605_peripheral_complete_counter_domain"]
        or (complete_count == 0) != (ticks_available == "false")
        or (complete_count == 0) != (complete_ticks == 0)
    ):
        raise ValueError("startup discovery telemetry is malformed or contradictory")
    identity_baud: int | None
    if identity_baud_value == "unavailable":
        identity_baud = None
    elif identity_baud_value.isdigit():
        identity_baud = int(identity_baud_value)
        if identity_baud not in startup["fallback_scan_bauds"]:
            raise ValueError("initial discovery identity baud is outside the frozen scan")
    else:
        raise ValueError("initial discovery identity baud is malformed")
    unresolved = initial_outcome == "pending"
    if hint_outcome == "not_attempted":
        coherent = (
            attempted == "false"
            and fallback_entered == "false"
            and unresolved
            and identity_baud is None
            and complete_count == 0
        )
    elif hint_outcome == "pending":
        coherent = attempted == "true" and unresolved and identity_baud is None
    elif hint_outcome == "confirmed":
        coherent = (
            attempted == "true"
            and fallback_entered == "false"
            and initial_outcome == "hint_confirmed"
            and identity_baud == hint_baud
            and complete_count >= 1
        )
    else:
        coherent = (
            attempted == "true"
            and fallback_entered == "true"
            and initial_outcome in {"pending", "fallback_confirmed"}
            and (
                identity_baud is None
                if initial_outcome == "pending"
                else identity_baud in startup["fallback_scan_bauds"]
            )
            and complete_count >= 1
        )
    if not coherent or (require_resolved and unresolved):
        raise ValueError("startup discovery telemetry is not causally resolved")
    return {
        "hint_attempted": attempted == "true",
        "hint_baud": hint_baud,
        "hint_identity_outcome": hint_outcome,
        "fallback_entered": fallback_entered == "true",
        "initial_identity_baud": identity_baud,
        "initial_discovery_outcome": initial_outcome,
        "pmtk605_peripheral_complete_count": complete_count,
        "pmtk605_last_peripheral_complete_ticks": complete_ticks,
        "pmtk605_last_peripheral_complete_ticks_available": ticks_available == "true",
        "pmtk605_last_peripheral_complete_ticks_domain": ticks_domain,
    }


class CaptureDeviceTransport:
    """Physical transport adapter layered on the existing capture owner."""

    def __init__(
        self,
        *,
        contract: Mapping[str, Any],
        run_dir: Path,
        normal_fifo: Path,
        device: str,
        capture_pid: int,
        capture_status_interval_s: float,
        expected_runtime_identity: Mapping[tuple[str, str], str],
        poll_interval_s: float = 0.2,
    ) -> None:
        self.contract = contract
        raw_uart = contract.get("raw_uart_acquisition")
        if isinstance(raw_uart, Mapping):
            self._ring_capacity_entries = int(raw_uart["ring_capacity_entries"])
        elif isinstance(contract.get("continuation"), Mapping):
            # The continuation runs the same fixed firmware ring as its bound
            # prefix contract; the compact continuation contract does not
            # duplicate that unchanged section.
            self._ring_capacity_entries = 1024
        else:
            raise ValueError("raw UART acquisition contract is unavailable")
        self.run_dir = run_dir.resolve()
        self.normal_fifo = normal_fifo.resolve()
        self.device = device
        self.capture_pid = capture_pid
        required_runtime_identities = {
            (CHARACTERIZATION_COMPONENT, "programme_id"),
            (CHARACTERIZATION_COMPONENT, "contract_sha256"),
            (CHARACTERIZATION_COMPONENT, "command_table_id"),
            ("build", "profile_id"),
            ("build", "git_commit"),
            ("build", "source_sha256"),
            ("build", "config_sha256"),
            ("firmware", "version"),
        }
        if set(expected_runtime_identity) != required_runtime_identities:
            raise ValueError("expected running-firmware identity field set differs")
        self.expected_runtime_identity = {
            identity: str(value)
            for identity, value in expected_runtime_identity.items()
        }
        if capture_status_interval_s != LIVE_CAPTURE_STATUS_INTERVAL_S:
            raise ValueError(
                "live GNSS baud capture status interval must be frozen at exactly 1 s"
            )
        self.poll_interval_s = poll_interval_s
        self._heartbeat: Callable[[int], None] = lambda _ticks: None
        self._local_fault: Callable[[Mapping[str, Any]], None] = lambda _fault: None
        self._integrity_check: Callable[[], None] = lambda: None
        self._last_generation = 0
        self._online_counter_ticks = 0
        self._challenge_sequence = 0
        self._last_challenge_sent_ns: int | None = None
        self._latest_phase_snapshot: RetainedSnapshot | None = None
        self._latest_phase_start_counters: dict[str, int] | None = None
        self._latest_phase_segment_id: str | None = None
        self._last_transition_frontier = 0
        self._transport_metadata_hold_count = 0
        self._snapshot_reducer = HealthSnapshotReducer(self.run_dir / HEALTH_CSV)
        self._programme_counter_baseline: dict[str, int] | None = None
        self._snapshot_capture_session: int | None = None
        self._snapshot_reference_sequence: int | None = None
        self._last_mirror_generation = 0
        self._last_observed_mirror_generation = 0
        self._last_mirror_advance_ns: int | None = None
        self._last_pmtk605_peripheral_complete_count = 0
        self._last_pmtk605_peripheral_complete_ticks = 0

    @property
    def now_ticks(self) -> int:
        return time.monotonic_ns()

    def bind_heartbeat(self, callback: Callable[[int], None]) -> None:
        self._heartbeat = callback

    def bind_local_fault(
        self, callback: Callable[[Mapping[str, Any]], None]
    ) -> None:
        self._local_fault = callback

    def bind_integrity_check(self, callback: Callable[[], None]) -> None:
        self._integrity_check = callback

    def _assert_capture(self) -> None:
        self._integrity_check()
        if (
            self._last_mirror_advance_ns is not None
            and self.now_ticks - self._last_mirror_advance_ns
            > int(PLATFORM_MIRROR_ADVANCE_DEADLINE_S * 1_000_000_000)
        ):
            raise ProgrammeTerminalError(
                "evidence_discontinuity",
                "D14/D8 platform mirror did not advance within its bounded deadline",
            )
        state = json.loads((self.run_dir / CAPTURE_STATE).read_text(encoding="utf-8"))
        if (
            state.get("pid") != self.capture_pid
            or state.get("capture_active") is not True
            or state.get("serial_open") is not True
        ):
            raise ProgrammeTerminalError(
                "sole_usb_serial_owner_loss", "sole-owner capture is not active"
            )
        owners = _serial_owner_pids(self.device)
        if owners != {self.capture_pid}:
            raise ProgrammeTerminalError(
                "sole_usb_serial_owner_loss",
                f"sole serial owner mismatch: {sorted(owners)}",
            )
        raw = self.run_dir / RAW_SERIAL
        if not raw.is_file() or time.time() - raw.stat().st_mtime > 5.0:
            raise ProgrammeTerminalError(
                "evidence_carrier_failure", "retained serial evidence is stale"
            )

    def _assert_snapshot_programme_health(
        self, snapshot: RetainedSnapshot
    ) -> tuple[bool, bool]:
        required_in_envelope = {
            *( (UART_COMPONENT, key) for key in UART_COUNTER_KEYS ),
            *( (RECEIVER_COMPONENT, key) for key in RECEIVER_COUNTER_KEYS ),
            *NONINTERFERENCE_COUNTER_KEYS,
            *(identity for identity in METRIC_KEYS),
            *(identity for identity in COMPLETED_PEAK_METRIC_KEYS),
            *self.expected_runtime_identity,
            ("dual_core", "partition_fault"),
            (UART_COMPONENT, "isr_drain_policy"),
            (UART_COMPONENT, "isr_timing_policy"),
            (UART_COMPONENT, "phase_window_sequence"),
            (UART_COMPONENT, "completed_peak_available"),
            (UART_COMPONENT, "completed_peak_challenge_sequence"),
            (UART_COMPONENT, "completed_peak_observation_phase"),
            ("pps_gate", "characterization_mirror_available"),
            ("pps_gate", "characterization_mirror_generation"),
            ("pps_gate", "characterization_mirror_capture_session"),
            ("pps_gate", "characterization_mirror_reference_sequence"),
            (CHARACTERIZATION_COMPONENT, EXTENDED_COUNTER_KEY),
            (CHARACTERIZATION_COMPONENT, "snapshot_extended_ticks_available"),
            (CHARACTERIZATION_COMPONENT, "snapshot_counter_domain"),
            (CHARACTERIZATION_COMPONENT, "snapshot_tick_rate_hz"),
            (CHARACTERIZATION_COMPONENT, "snapshot_capture_session"),
            (CHARACTERIZATION_COMPONENT, "snapshot_reference_sequence"),
            (CHARACTERIZATION_COMPONENT, "transition_evidence_frontier"),
        }
        if isinstance(self.contract.get("startup_discovery"), Mapping):
            required_in_envelope.update(
                (RECEIVER_COMPONENT, key)
                for key in STARTUP_DISCOVERY_TELEMETRY_KEYS
            )
        if isinstance(self.contract.get("continuation"), Mapping):
            required_in_envelope.update(
                {
                    (RECEIVER_COMPONENT, "metadata_fresh"),
                    (RECEIVER_COMPONENT, "checksum_requalified"),
                    (RECEIVER_COMPONENT, "gsa_checksum_requalified"),
                }
            )
        missing = sorted(
            f"{component}.{key}"
            for component, key in required_in_envelope
            if not snapshot.observed_in_envelope(component, key)
        )
        if missing:
            raise ProgrammeTerminalError(
                "evidence_discontinuity",
                "decision fields missing from coherent envelope: " + ",".join(missing),
            )
        runtime_mismatches = sorted(
            f"{component}.{key}={snapshot.fields.get((component, key))!r}"
            for (component, key), expected in self.expected_runtime_identity.items()
            if snapshot.fields.get((component, key)) != expected
        )
        if runtime_mismatches:
            raise ProgrammeTerminalError(
                "identity_contradiction",
                "running firmware identity differs: " + ",".join(runtime_mismatches),
            )
        try:
            startup_evidence = (
                startup_discovery_evidence(snapshot, self.contract)
                if isinstance(self.contract.get("startup_discovery"), Mapping)
                else None
            )
            capture_session = snapshot.integer(
                CHARACTERIZATION_COMPONENT, "snapshot_capture_session"
            )
            reference_sequence = snapshot.integer(
                CHARACTERIZATION_COMPONENT, "snapshot_reference_sequence"
            )
            mirror_generation = snapshot.integer(
                "pps_gate", "characterization_mirror_generation"
            )
            mirror_session = snapshot.integer(
                "pps_gate", "characterization_mirror_capture_session"
            )
            mirror_reference = snapshot.integer(
                "pps_gate", "characterization_mirror_reference_sequence"
            )
            mirror_available = snapshot.value(
                "pps_gate", "characterization_mirror_available"
            )
            if (
                self._characterization(snapshot, "snapshot_extended_ticks_available")
                != "true"
                or self._characterization(snapshot, "snapshot_counter_domain")
                != "rp2040_timer0_extended"
                or snapshot.integer(
                    CHARACTERIZATION_COMPONENT, "snapshot_tick_rate_hz"
                )
                != ticks_per_second(self.contract, "rp2040_timer0_extended")
            ):
                raise ValueError("snapshot counter-domain binding is unavailable")
            if mirror_available == "false":
                if mirror_generation != 0 or mirror_session != 0 or mirror_reference != 0:
                    raise ValueError("unavailable platform mirror has nonzero identity")
                # Core1 needs several physical D14 boundaries before it can
                # promote the first complete mirror.  This is observation
                # latency, not contradictory evidence; retry within the
                # caller's bounded snapshot deadline.
                return False, False
            if (
                mirror_available != "true"
                or mirror_generation == 0
                or mirror_session != capture_session
                or mirror_reference == 0
                or mirror_reference > reference_sequence
            ):
                raise ValueError("snapshot platform-mirror binding is contradictory")
        except ValueError as exc:
            raise ProgrammeTerminalError(
                "evidence_discontinuity", str(exc)
            ) from exc
        if startup_evidence is not None:
            pmtk605_count = int(
                startup_evidence["pmtk605_peripheral_complete_count"]
            )
            pmtk605_ticks = int(
                startup_evidence["pmtk605_last_peripheral_complete_ticks"]
            )
            if (
                pmtk605_count < self._last_pmtk605_peripheral_complete_count
                or pmtk605_ticks < self._last_pmtk605_peripheral_complete_ticks
                or (
                    pmtk605_count > self._last_pmtk605_peripheral_complete_count
                    and self._last_pmtk605_peripheral_complete_count > 0
                    and pmtk605_ticks
                    <= self._last_pmtk605_peripheral_complete_ticks
                )
            ):
                raise ProgrammeTerminalError(
                    "evidence_discontinuity",
                    "PMTK605 peripheral-complete evidence moved backward",
                )
            self._last_pmtk605_peripheral_complete_count = pmtk605_count
            self._last_pmtk605_peripheral_complete_ticks = pmtk605_ticks
        if (
            self._snapshot_capture_session is not None
            and capture_session != self._snapshot_capture_session
        ):
            raise ProgrammeTerminalError(
                "evidence_discontinuity", "snapshot capture session changed"
            )
        if (
            self._snapshot_reference_sequence is not None
            and reference_sequence < self._snapshot_reference_sequence
        ):
            raise ProgrammeTerminalError(
                "evidence_discontinuity", "snapshot reference sequence moved backward"
            )
        self._snapshot_capture_session = capture_session
        self._snapshot_reference_sequence = reference_sequence
        if mirror_generation > self._last_observed_mirror_generation:
            self._last_observed_mirror_generation = mirror_generation
            self._last_mirror_advance_ns = self.now_ticks
        if self._programme_counter_baseline is None:
            return True, mirror_generation > self._last_mirror_generation
        counters = snapshot_counters(snapshot)
        deltas = exact_counter_deltas(self._programme_counter_baseline, counters)
        shared = {
            "shared_queue_corruption_count",
            "dual_core_partition_fault_count",
        }
        evidence = {"telemetry_dropped_count"}
        d14_d8 = set(NONINTERFERENCE_COUNTER_KEYS.values()) - shared - evidence
        for names, reason in (
            (shared, "shared_queue_corruption"),
            (evidence, "evidence_discontinuity"),
            (d14_d8, "d14_d8_capture_loss"),
        ):
            advanced = sorted(name for name in names if deltas.get(name, 0) > 0)
            if advanced:
                raise ProgrammeTerminalError(
                    reason,
                    f"programme counter advanced in snapshot {snapshot.generation}: "
                    + ",".join(advanced),
                )
        return True, mirror_generation > self._last_mirror_generation

    def _wait_snapshot(
        self,
        predicate: Callable[[RetainedSnapshot], bool],
        *,
        deadline_s: float,
        description: str,
        require_fresh_mirror: bool = True,
    ) -> RetainedSnapshot:
        deadline = time.monotonic() + deadline_s
        while time.monotonic() < deadline:
            self._assert_capture()
            self._heartbeat(self.now_ticks)
            snapshots = self._snapshot_reducer.poll()
            for snapshot in snapshots:
                if snapshot.generation <= self._last_generation:
                    continue
                mirror_ready, mirror_fresh = (
                    self._assert_snapshot_programme_health(snapshot)
                )
                if not mirror_ready:
                    continue
                if require_fresh_mirror and not mirror_fresh:
                    continue
                if predicate(snapshot):
                    self._last_generation = snapshot.generation
                    self._last_mirror_generation = max(
                        self._last_mirror_generation,
                        snapshot.integer(
                            "pps_gate", "characterization_mirror_generation"
                        ),
                    )
                    return snapshot
            time.sleep(self.poll_interval_s)
        raise TimeoutError(f"timed out waiting for {description}")

    def initial_state_evidence(
        self, *, expected_device: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Bind the no-command attachment snapshot before local S01 is constructed."""

        profile_id = str(self.contract["firmware_profile"]["profile_id"])
        expected_identity = str(expected_device["gnss_identity"])
        expected_configuration = str(expected_device["gnss_configuration"])
        continuation = self.contract.get("continuation")
        is_continuation = isinstance(continuation, Mapping)

        def exact_initial(snapshot: RetainedSnapshot) -> bool:
            try:
                confirmed_baud = snapshot.integer(
                    CHARACTERIZATION_COMPONENT, "confirmed_baud"
                )
                epoch = snapshot.integer(CHARACTERIZATION_COMPONENT, "baud_epoch")
                startup_evidence = (
                    startup_discovery_evidence(
                        snapshot, self.contract, require_resolved=True
                    )
                    if is_continuation
                    else None
                )
                attachment_exact = (
                    confirmed_baud
                    in tuple(int(value) for value in continuation["attachment_baud_allowlist"])
                    and epoch
                    == int(self.contract["transition_policy"]["initial_baud_epoch"])
                    and startup_evidence is not None
                    and startup_evidence["initial_identity_baud"] == confirmed_baud
                    and startup_evidence["hint_attempted"] is True
                    and startup_evidence["pmtk605_peripheral_complete_count"] >= 1
                    and startup_evidence[
                        "pmtk605_last_peripheral_complete_ticks_available"
                    ]
                    is True
                    and snapshot.value(RECEIVER_COMPONENT, "metadata_fresh")
                    == "true"
                    and snapshot.value(RECEIVER_COMPONENT, "checksum_requalified")
                    == "true"
                    and snapshot.value(
                        RECEIVER_COMPONENT, "gsa_checksum_requalified"
                    )
                    == "true"
                    and snapshot.integer(RECEIVER_COMPONENT, "rmc_count") >= 1
                    and snapshot.integer(RECEIVER_COMPONENT, "gga_count") >= 1
                    and snapshot.integer(RECEIVER_COMPONENT, "gsa_count") >= 2
                ) if is_continuation else (
                    confirmed_baud == 9600 and epoch == 1
                )
                observed_identity = snapshot.value(
                    RECEIVER_COMPONENT, "receiver_identity"
                )
                identity_exact = observed_identity == expected_identity or (
                    is_continuation
                    and observed_identity == CONTINUATION_NMEA_IDENTITY
                )
                return (
                    snapshot.value("build", "profile_id") == profile_id
                    and self._characterization(snapshot, "programme_id") == PROGRAMME_ID
                    and attachment_exact
                    and identity_exact
                    and snapshot.value(RECEIVER_COMPONENT, "output_configuration_signature")
                    == expected_configuration
                    and snapshot.value(RECEIVER_COMPONENT, "identity_stable") == "true"
                    and snapshot.value(RECEIVER_COMPONENT, "configuration_confirmed") == "true"
                    and self._characterization(snapshot, "snapshot_extended_ticks_available")
                    == "true"
                    and self._characterization(snapshot, "snapshot_counter_domain")
                    == "rp2040_timer0_extended"
                    and snapshot.value(
                        "pps_gate", "characterization_mirror_available"
                    )
                    == "true"
                    and snapshot.integer(CHARACTERIZATION_COMPONENT, "snapshot_tick_rate_hz")
                    == ticks_per_second(self.contract, "rp2040_timer0_extended")
                )
            except (KeyError, TypeError, ValueError):
                return False

        snapshot = self._wait_snapshot(
            exact_initial,
            deadline_s=(
                int(continuation["attachment_deadline_ms"]) / 1000
                if is_continuation
                else INITIAL_ATTACHMENT_DEADLINE_S
            ),
            description="exact no-command initial attachment",
        )
        self._programme_counter_baseline = snapshot_counters(snapshot)
        self._snapshot_capture_session = snapshot.integer(
            CHARACTERIZATION_COMPONENT, "snapshot_capture_session"
        )
        self._snapshot_reference_sequence = snapshot.integer(
            CHARACTERIZATION_COMPONENT, "snapshot_reference_sequence"
        )
        confirmed_baud = snapshot.integer(
            CHARACTERIZATION_COMPONENT, "confirmed_baud"
        )
        baud_epoch = snapshot.integer(CHARACTERIZATION_COMPONENT, "baud_epoch")
        startup_evidence = (
            startup_discovery_evidence(
                snapshot, self.contract, require_resolved=True
            )
            if is_continuation
            else None
        )
        return {
            "programme_id": PROGRAMME_ID,
            "profile_id": profile_id,
            "confirmed_baud": confirmed_baud,
            "baud_epoch": baud_epoch,
            "identity_confirmed": True,
            "configuration_confirmed": True,
            "receiver_identity": expected_identity,
            "configuration_identity": expected_configuration,
            "snapshot_generation": snapshot.generation,
            "metadata_frontier": snapshot.integer(
                CHARACTERIZATION_COMPONENT, "transition_evidence_frontier"
            ),
            "snapshot_capture_session": snapshot.integer(
                CHARACTERIZATION_COMPONENT, "snapshot_capture_session"
            ),
            "snapshot_reference_sequence": snapshot.integer(
                CHARACTERIZATION_COMPONENT, "snapshot_reference_sequence"
            ),
            "fresh_rmc": is_continuation,
            "fresh_gga": is_continuation,
            "fresh_two_gsa": is_continuation,
            **(
                {"startup_discovery": startup_evidence}
                if startup_evidence is not None
                else {}
            ),
        }

    @staticmethod
    def _characterization(snapshot: RetainedSnapshot, key: str) -> str:
        return snapshot.value(CHARACTERIZATION_COMPONENT, key)

    def transition(
        self, request: Mapping[str, Any], command: str
    ) -> Mapping[str, Any]:
        prior_frontier = 0
        self._snapshot_reducer.poll()
        snapshots = list(self._snapshot_reducer.snapshots)
        if snapshots:
            latest = snapshots[-1]
            self._last_generation = max(self._last_generation, latest.generation)
            try:
                prior_frontier = latest.integer(
                    CHARACTERIZATION_COMPONENT, "transition_evidence_frontier"
                )
            except ValueError:
                prior_frontier = 0
        physical_transmit_required = bool(
            request.get("physical_transmit_required", True)
        )
        same_target_binding = (
            request.get("transition_mode") == "same_target_session_bind"
        )
        continuation = self.contract.get("continuation")
        if isinstance(continuation, Mapping):
            rejected_logical_ids = set(
                continuation["reject_logical_segment_ids_from_live_command_surface"]
            )
            if request.get("logical_segment_id") in rejected_logical_ids:
                raise ValueError("continuation cannot run logical S01..S05")
        if same_target_binding != (not physical_transmit_required):
            raise ValueError("transition mode and physical-transmit requirement differ")
        if same_target_binding and int(request["source_baud"]) != int(
            request["target_baud"]
        ):
            raise ValueError("same-target binding cannot change baud")
        source_segment_id = str(
            request.get("source_segment_id", request["segment_id"])
        )
        sent = self.now_ticks
        send_timestamped_command_to_fifo(
            self.normal_fifo, command, created_monotonic_ns=sent
        )

        def request_bound(snapshot: RetainedSnapshot) -> bool:
            fields = snapshot.fields
            try:
                return (
                    fields[(CHARACTERIZATION_COMPONENT, "programme_id")]
                    == PROGRAMME_ID
                    and int(fields[(CHARACTERIZATION_COMPONENT, "request_sequence")])
                    == int(request["request_sequence"])
                    and fields[(CHARACTERIZATION_COMPONENT, "segment_id")]
                    == source_segment_id
                    and int(fields[(CHARACTERIZATION_COMPONENT, "source_baud")])
                    == int(request["source_baud"])
                    and int(
                        fields[(CHARACTERIZATION_COMPONENT, "source_baud_epoch")]
                    )
                    == int(request["source_baud_epoch"])
                    and int(fields[(CHARACTERIZATION_COMPONENT, "target_baud")])
                    == int(request["target_baud"])
                )
            except (KeyError, ValueError):
                return False

        acceptance_deadline_ms = int(
            self.contract["transition_policy"]["request_acceptance_deadline_ms"]
        )
        observation_allowance_s = 2.0 * LIVE_CAPTURE_STATUS_INTERVAL_S
        accepted_snapshot = self._wait_snapshot(
            lambda snapshot: request_bound(snapshot)
            and self._characterization(snapshot, "request_disposition")
            in {"accepted", "duplicate"}
            and (
                not same_target_binding
                or self._characterization(snapshot, "transition_state")
                in {"await_fresh_metadata", "complete"}
            ),
            deadline_s=acceptance_deadline_ms / 1000 + observation_allowance_s,
            description=f"transition {request['request_sequence']} acceptance",
            require_fresh_mirror=False,
        )
        accepted_observed = self.now_ticks
        acceptance_within = accepted_observed - sent <= int(
            acceptance_deadline_ms / 1000 + observation_allowance_s
        ) * 1_000_000_000
        if not acceptance_within:
            raise ProgrammeTerminalError(
                "evidence_discontinuity", "transition acceptance missed its deadline"
            )

        terminal_states = {"complete", "recovered", "unrecoverable", "platform_fault"}
        recovery_states = {"recovery_scanning", "recovered", "unrecoverable"}
        snapshot = accepted_snapshot
        state = self._characterization(snapshot, "transition_state")
        if same_target_binding and state not in {"await_fresh_metadata", "complete"}:
            raise ProgrammeTerminalError(
                "evidence_discontinuity",
                "same-target binding did not reach fresh-metadata completion after acceptance",
            )
        if (
            physical_transmit_required
            and self._characterization(snapshot, "target_command_transmit_complete")
            != "true"
            and state not in terminal_states
            and state not in recovery_states
        ):
            snapshot = self._wait_snapshot(
                lambda value: request_bound(value)
                and (
                    self._characterization(
                        value, "target_command_transmit_complete"
                    )
                    == "true"
                    or self._characterization(value, "transition_state")
                    in terminal_states | recovery_states
                ),
                deadline_s=2.0,
                description=f"transition {request['request_sequence']} physical TX completion",
                require_fresh_mirror=False,
            )
            state = self._characterization(snapshot, "transition_state")
        tx_complete = (
            self._characterization(snapshot, "target_command_transmit_complete")
            == "true"
        )
        tx_elapsed_ms = snapshot.integer(
            CHARACTERIZATION_COMPONENT, "target_command_transmit_elapsed_ms"
        )
        if (
            (physical_transmit_required and not tx_complete)
            or (same_target_binding and (tx_complete or tx_elapsed_ms != 0))
            or tx_elapsed_ms
            > int(
                self.contract["transition_policy"][
                    "uart_physical_transmit_deadline_ms"
                ]
            )
        ):
            raise ProgrammeTerminalError(
                "evidence_discontinuity",
                "transition lacks bounded physical UART completion",
            )

        if state not in terminal_states | recovery_states and not (
            self._characterization(snapshot, "target_identity_confirmed") == "true"
            and self._characterization(snapshot, "target_output_confirmed") == "true"
        ):
            snapshot = self._wait_snapshot(
                lambda value: request_bound(value)
                and (
                    (
                        self._characterization(value, "target_identity_confirmed")
                        == "true"
                        and self._characterization(value, "target_output_confirmed")
                        == "true"
                    )
                    or self._characterization(value, "transition_state")
                    in terminal_states | recovery_states
                ),
                deadline_s=12.0,
                description=(
                    f"transition {request['request_sequence']} target identity/output"
                ),
                require_fresh_mirror=False,
            )
            state = self._characterization(snapshot, "transition_state")
        target_identity = (
            self._characterization(snapshot, "target_identity_confirmed") == "true"
        )
        target_output = (
            self._characterization(snapshot, "target_output_confirmed") == "true"
        )
        target_identity_elapsed_ms = snapshot.integer(
            CHARACTERIZATION_COMPONENT, "target_identity_elapsed_ms"
        )
        target_output_elapsed_ms = snapshot.integer(
            CHARACTERIZATION_COMPONENT, "target_output_elapsed_ms"
        )

        deadline = int(self.contract["transition_policy"]["serial_link_unrecoverable_deadline_ms"]) / 1000
        if state not in terminal_states:
            remaining = max(0.001, deadline - (self.now_ticks - sent) / 1_000_000_000)
            snapshot = self._wait_snapshot(
                lambda value: request_bound(value)
                and self._characterization(value, "transition_state")
                in terminal_states,
                deadline_s=remaining,
                description=f"transition {request['request_sequence']} causal completion",
                require_fresh_mirror=False,
            )
        state = self._characterization(snapshot, "transition_state")
        frontier = snapshot.integer(
            CHARACTERIZATION_COMPONENT, "transition_evidence_frontier"
        )
        common: dict[str, Any] = {
            **request,
            "completed_within_deadline": self.now_ticks - sent
            <= int(self.contract["transition_policy"]["complete_transition_deadline_ms"])
            * 1_000_000,
            "snapshot_generation": snapshot.generation,
            "metadata_frontier": frontier,
            "transition_milestones": {
                "acceptance": {
                    "snapshot_generation": accepted_snapshot.generation,
                    "observed_host_elapsed_ns": accepted_observed - sent,
                    "within_deadline": acceptance_within,
                },
                "physical_transmit": {
                    "required": physical_transmit_required,
                    "complete": tx_complete,
                    "firmware_elapsed_ms": tx_elapsed_ms,
                    "deadline_ms": int(
                        self.contract["transition_policy"][
                            "uart_physical_transmit_deadline_ms"
                        ]
                    ),
                },
                "target_confirmation": {
                    "identity_confirmed": target_identity,
                    "output_confirmed": target_output,
                    "identity_elapsed_ms": target_identity_elapsed_ms,
                    "output_elapsed_ms": target_output_elapsed_ms,
                    "deadline_ms": int(
                        self.contract["transition_policy"][
                            "target_identity_and_output_confirmation_deadline_ms"
                        ]
                    ),
                },
                "terminal": {
                    "state": state,
                    "transition_complete_elapsed_ms": snapshot.integer(
                        CHARACTERIZATION_COMPONENT,
                        "transition_complete_elapsed_ms",
                    ),
                    "recovery_started_elapsed_ms": snapshot.integer(
                        CHARACTERIZATION_COMPONENT,
                        "recovery_started_elapsed_ms",
                    ),
                    "recovery_terminal_elapsed_ms": snapshot.integer(
                        CHARACTERIZATION_COMPONENT,
                        "recovery_terminal_elapsed_ms",
                    ),
                },
            },
        }
        if state == "complete":
            complete_elapsed_ms = snapshot.integer(
                CHARACTERIZATION_COMPONENT, "transition_complete_elapsed_ms"
            )
            target_deadline_ms = int(
                self.contract["transition_policy"][
                    "target_identity_and_output_confirmation_deadline_ms"
                ]
            )
            if (
                not target_identity
                or not target_output
                or target_identity_elapsed_ms > target_deadline_ms
                or target_output_elapsed_ms > target_deadline_ms
                or complete_elapsed_ms
                > int(
                    self.contract["transition_policy"][
                        "complete_transition_deadline_ms"
                    ]
                )
            ):
                raise ProgrammeTerminalError(
                    "evidence_discontinuity", "confirmed transition missed a milestone"
                )
            confirmed = snapshot.integer(CHARACTERIZATION_COMPONENT, "confirmed_baud")
            epoch = snapshot.integer(CHARACTERIZATION_COMPONENT, "baud_epoch")
            exact = (
                confirmed == int(request["target_baud"])
                and (
                    epoch == int(request["source_baud_epoch"])
                    if same_target_binding
                    else epoch > int(request["source_baud_epoch"])
                )
                and frontier > prior_frontier
                and self._characterization(snapshot, "first_dependent_snapshot") == "true"
                and snapshot.value(RECEIVER_COMPONENT, "configuration_confirmed") == "true"
                and snapshot.value(RECEIVER_COMPONENT, "identity_stable") == "true"
            )
            if not exact:
                raise RuntimeError("transition completed without exact dependent snapshot")
            self._last_transition_frontier = frontier
            return {
                **common,
                "status": "confirmed",
                "confirmed_baud": confirmed,
                "baud_epoch": epoch,
                "identity_confirmed": True,
                "configuration_confirmed": True,
                "fresh_rmc": True,
                "fresh_gga": True,
                "fresh_two_gsa": True,
                "first_dependent_snapshot_bound": True,
            }
        if state == "recovered":
            recovery_started_ms = snapshot.integer(
                CHARACTERIZATION_COMPONENT, "recovery_started_elapsed_ms"
            )
            recovery_terminal_ms = snapshot.integer(
                CHARACTERIZATION_COMPONENT, "recovery_terminal_elapsed_ms"
            )
            if (
                recovery_terminal_ms < recovery_started_ms
                or recovery_terminal_ms - recovery_started_ms
                > int(self.contract["transition_policy"]["recovery_scan_deadline_ms"])
                or recovery_terminal_ms
                > int(
                    self.contract["transition_policy"][
                        "serial_link_unrecoverable_deadline_ms"
                    ]
                )
            ):
                raise ProgrammeTerminalError(
                    "evidence_discontinuity", "transition recovery missed its deadline"
                )
            recovered = snapshot.integer(CHARACTERIZATION_COMPONENT, "recovered_baud")
            recovered_exact = (
                recovered in BAUD_ALLOWLIST
                and frontier > prior_frontier
                and self._characterization(snapshot, "first_dependent_snapshot") == "true"
                and snapshot.value(RECEIVER_COMPONENT, "configuration_confirmed") == "true"
                and snapshot.value(RECEIVER_COMPONENT, "identity_stable") == "true"
            )
            if not recovered_exact:
                raise RuntimeError("firmware recovery lacks exact causal evidence")
            self._last_transition_frontier = frontier
            return {
                **common,
                "status": "target_failed_recovered",
                "recovered_baud": recovered,
                "baud_epoch": snapshot.integer(CHARACTERIZATION_COMPONENT, "baud_epoch"),
            }
        if state == "unrecoverable":
            recovery_terminal_ms = snapshot.integer(
                CHARACTERIZATION_COMPONENT, "recovery_terminal_elapsed_ms"
            )
            if recovery_terminal_ms > int(
                self.contract["transition_policy"][
                    "serial_link_unrecoverable_deadline_ms"
                ]
            ):
                raise ProgrammeTerminalError(
                    "evidence_discontinuity", "unrecoverable verdict missed its deadline"
                )
            return {**common, "status": "serial_link_unrecoverable"}
        raise RuntimeError("firmware reported a transition platform fault")

    @staticmethod
    def _phase_name(phase: PhasePlan) -> str:
        return "peak_load" if phase.kind == "peak_status" else "ordinary_online"

    def _phase_snapshot(
        self,
        *,
        segment: SegmentPlan,
        phase: PhasePlan,
        baud_epoch: int,
        accepted_observation_phases: set[str] | None = None,
    ) -> RetainedSnapshot:
        expected_phases = accepted_observation_phases or {self._phase_name(phase)}

        def matches(snapshot: RetainedSnapshot) -> bool:
            try:
                return (
                    self._characterization(snapshot, "observation_phase") in expected_phases
                    and self._characterization(snapshot, "segment_id") == segment.segment_id
                    and snapshot.integer(CHARACTERIZATION_COMPONENT, "confirmed_baud") == segment.baud
                    and snapshot.integer(CHARACTERIZATION_COMPONENT, "baud_epoch") == baud_epoch
                    and snapshot.value(RECEIVER_COMPONENT, "identity_stable") == "true"
                    and snapshot.value(RECEIVER_COMPONENT, "configuration_confirmed") == "true"
                )
            except ValueError:
                return False

        return self._wait_snapshot(
            matches,
            deadline_s=FIRMWARE_SNAPSHOT_DEADLINE_S,
            description="fresh phase snapshot",
        )

    def begin_online_phase(
        self, *, segment: SegmentPlan, phase: PhasePlan, baud_epoch: int
    ) -> PhaseStart:
        # The host ledger owns the peak phase boundary. Before the first peak
        # challenge firmware remains in ordinary_online; each challenge-local
        # response is separately attributed peak_load below.
        accepted = (
            {"ordinary_online", "peak_load"}
            if phase.kind == "peak_status"
            else {"ordinary_online"}
        )
        snapshot = self._phase_snapshot(
            segment=segment,
            phase=phase,
            baud_epoch=baud_epoch,
            accepted_observation_phases=accepted,
        )
        counters = snapshot_counters(snapshot)
        counters["transport_metadata_hold_count"] = (
            self._transport_metadata_hold_count
        )
        self._latest_phase_start_counters = counters
        self._latest_phase_segment_id = segment.effective_logical_segment_id
        # The cumulative programme counter is reconstructed only from qualified
        # adjacent device snapshots; it never passes through wall seconds.
        return PhaseStart(
            start_ticks=self.now_ticks,
            online_counter_ticks=self._online_counter_ticks,
            online_counter_domain="rp2040_timer0_extended",
            start_counters=counters,
            metrics=snapshot_metrics(
                snapshot,
                ring_capacity=self._ring_capacity_entries,
            ),
        )

    def _challenge(
        self,
        *,
        segment: SegmentPlan,
        baud_epoch: int,
        status_command: Callable[[int], str],
    ) -> tuple[dict[str, Any], RetainedSnapshot, dict[str, Any]]:
        sequence = self._challenge_sequence + 1
        workload = self.contract["peak_status_workload"]
        period_ns = int(workload["minimum_period_ms"]) * 1_000_000
        response_deadline_ms = int(workload["response_completion_deadline_ms"])
        attempt_count = 0
        while True:
            while (
                self._last_challenge_sent_ns is not None
                and self.now_ticks - self._last_challenge_sent_ns < period_ns
            ):
                self._assert_capture()
                self._heartbeat(self.now_ticks)
                time.sleep(self.poll_interval_s)
            attempt_count += 1
            raw_path = self.run_dir / RAW_SERIAL
            response_start_bytes = raw_path.stat().st_size
            response_start_status_sequence = (
                self._snapshot_reducer.snapshots[-1].end_status_sequence
                if self._snapshot_reducer.snapshots
                else 0
            )
            sent = self.now_ticks
            self._last_challenge_sent_ns = sent
            send_timestamped_command_to_fifo(
                self.normal_fifo,
                status_command(sequence),
                created_monotonic_ns=sent,
            )

            def response(snapshot: RetainedSnapshot) -> bool:
                try:
                    if (
                        self._characterization(snapshot, "segment_id")
                        != segment.segment_id
                        or snapshot.integer(CHARACTERIZATION_COMPONENT, "baud_epoch")
                        != baud_epoch
                        or snapshot.integer(
                            CHARACTERIZATION_COMPONENT,
                            "status_request_sequence",
                        )
                        != sequence
                        or self._characterization(
                            snapshot, "status_request_segment_id"
                        )
                        != segment.segment_id
                        or snapshot.integer(
                            CHARACTERIZATION_COMPONENT,
                            "status_request_baud_epoch",
                        )
                        != baud_epoch
                    ):
                        return False
                    completed = (
                        snapshot.integer(
                            CHARACTERIZATION_COMPONENT,
                            "status_challenge_sequence",
                        )
                        == sequence
                        and self._characterization(
                            snapshot, "status_challenge_active"
                        )
                        == "false"
                        and self._characterization(snapshot, "observation_phase")
                        == "peak_load"
                    )
                    disposition = self._characterization(
                        snapshot, "status_request_disposition"
                    )
                    return completed or disposition.startswith("rejected_")
                except ValueError:
                    return False

            try:
                snapshot = self._wait_snapshot(
                    response,
                    deadline_s=response_deadline_ms / 1000,
                    description="completed or rejected status challenge",
                    require_fresh_mirror=False,
                )
            except TimeoutError as exc:
                raise ProgrammeTerminalError(
                    "evidence_discontinuity",
                    f"status challenge {sequence} for {segment.segment_id} "
                    f"baud epoch {baud_epoch} response did not complete within the "
                    f"frozen {response_deadline_ms} ms deadline: {exc}",
                ) from exc
            completed_ticks = self.now_ticks
            completed = (
                snapshot.integer(
                    CHARACTERIZATION_COMPONENT, "status_challenge_sequence"
                )
                == sequence
                and self._characterization(snapshot, "status_challenge_active")
                == "false"
                and self._characterization(snapshot, "observation_phase")
                == "peak_load"
            )
            disposition = self._characterization(
                snapshot, "status_request_disposition"
            )
            if completed:
                self._challenge_sequence = sequence
                response_end_bytes = raw_path.stat().st_size
                response_bytes = max(0, response_end_bytes - response_start_bytes)
                # The challenge response closes the peak window, but that
                # response snapshot contains the pre-close phase-window view.
                # Bind the verdict metrics only from a later ordinary snapshot
                # carrying firmware's immutable completed-peak tail for N.
                peak_tail = self._wait_snapshot(
                    lambda value: (
                        self._characterization(value, "segment_id")
                        == segment.segment_id
                        and value.integer(
                            CHARACTERIZATION_COMPONENT, "baud_epoch"
                        )
                        == baud_epoch
                        and self._characterization(value, "observation_phase")
                        == "ordinary_online"
                        and value.value(UART_COMPONENT, "completed_peak_available")
                        == "true"
                        and value.integer(
                            UART_COMPONENT, "completed_peak_challenge_sequence"
                        )
                        == sequence
                    ),
                    deadline_s=FIRMWARE_SNAPSHOT_DEADLINE_S,
                    description=f"completed peak UART tail for challenge {sequence}",
                    require_fresh_mirror=False,
                )
                peak_metrics = completed_peak_metrics(
                    peak_tail,
                    expected_challenge_sequence=sequence,
                    ring_capacity=self._ring_capacity_entries,
                )
                return (
                    {
                        "challenge_sequence": sequence,
                        "source_segment_id": segment.source_segment_id,
                        "logical_segment_id": segment.effective_logical_segment_id,
                        "attempt_count": attempt_count,
                        "sent_ticks": sent,
                        "completed_ticks": completed_ticks,
                        "host_drained_ticks": completed_ticks,
                        "timestamp_domain": "host_monotonic_ns",
                        "response_bytes": response_bytes,
                        "response_duration_ns": completed_ticks - sent,
                        "response_start_raw_offset": response_start_bytes,
                        "response_end_raw_offset": response_end_bytes,
                        "response_start_status_sequence": response_start_status_sequence,
                        "response_end_status_sequence": snapshot.end_status_sequence,
                        "response_snapshot_generation": snapshot.generation,
                        "completed_peak_snapshot_generation": peak_tail.generation,
                        "completed_peak_end_status_sequence":
                            peak_tail.end_status_sequence,
                        "completed_peak_challenge_sequence": sequence,
                    },
                    peak_tail,
                    peak_metrics,
                )
            if disposition != "rejected_phase":
                raise ProgrammeTerminalError(
                    "identity_contradiction",
                    f"status challenge {sequence} rejected as {disposition}",
                )
            # A qualification race is a bounded metadata hold.  Firmware did
            # not consume the sequence, so wait for fresh ordinary evidence and
            # retry the exact same sequence at the frozen non-overlap cadence.
            self._wait_snapshot(
                lambda value: (
                    self._characterization(value, "segment_id")
                    == segment.segment_id
                    and value.integer(
                        CHARACTERIZATION_COMPONENT, "baud_epoch"
                    )
                    == baud_epoch
                    and value.value(RECEIVER_COMPONENT, "checksum_requalified")
                    == "true"
                    and value.value(
                        RECEIVER_COMPONENT, "gsa_checksum_requalified"
                    )
                    == "true"
                ),
                deadline_s=FIRMWARE_SNAPSHOT_DEADLINE_S,
                description="status challenge metadata requalification",
            )

    @staticmethod
    def _qualified_interval(
        before: RetainedSnapshot,
        after: RetainedSnapshot,
    ) -> tuple[bool, dict[str, int]]:
        before_counters = snapshot_counters(before)
        after_counters = snapshot_counters(after)
        deltas = exact_counter_deltas(before_counters, after_counters)
        endpoints_qualified = all(
            snapshot.value(RECEIVER_COMPONENT, key) == "true"
            for snapshot in (before, after)
            for key in ("checksum_requalified", "gsa_checksum_requalified")
        )
        no_hidden_fault_or_hold = all(
            deltas.get(counter, 0) == 0 for counter in ONLINE_FAULT_COUNTERS
        )
        return endpoints_qualified and no_hidden_fault_or_hold, deltas

    def complete_online_phase(
        self,
        *,
        segment: SegmentPlan,
        phase: PhasePlan,
        baud_epoch: int,
        start: PhaseStart,
        status_command: Callable[[int], str],
    ) -> PhaseOutcome:
        required = phase.duration_s * ticks_per_second(
            self.contract, "rp2040_timer0_extended"
        )
        accumulated = 0
        accepted = (
            {"ordinary_online", "peak_load"}
            if phase.kind == "peak_status"
            else {"ordinary_online"}
        )
        prior = self._phase_snapshot(
            segment=segment,
            phase=phase,
            baud_epoch=baud_epoch,
            accepted_observation_phases=accepted,
        )
        prior_ticks = prior.integer(CHARACTERIZATION_COMPONENT, EXTENDED_COUNTER_KEY)
        challenges: list[Mapping[str, Any]] = []
        local_faults: list[Mapping[str, Any]] = []
        observed_fault_classes: set[str] = set()
        last_snapshot = prior
        phase_metrics: dict[str, Any] | None = (
            None
            if phase.kind == "peak_status"
            else snapshot_metrics(
                prior,
                ring_capacity=self._ring_capacity_entries,
            )
        )
        def phase_complete() -> bool:
            return accumulated >= required and (
                phase.kind != "peak_status"
                or len(challenges) == phase.duration_s
            )

        while not phase_complete():
            attributed_metrics: dict[str, Any] | None = None
            prior_qualified = all(
                prior.value(RECEIVER_COMPONENT, key) == "true"
                for key in ("checksum_requalified", "gsa_checksum_requalified")
            )
            if (
                phase.kind == "peak_status"
                and prior_qualified
                and len(challenges) < phase.duration_s
            ):
                challenge, current, completed_metrics = self._challenge(
                        segment=segment,
                        baud_epoch=baud_epoch,
                        status_command=status_command,
                    )
                challenges.append(challenge)
                attributed_metrics = completed_metrics
            else:
                current = self._phase_snapshot(
                    segment=segment,
                    phase=phase,
                    baud_epoch=baud_epoch,
                    accepted_observation_phases=accepted,
                )
            current_ticks = current.integer(
                CHARACTERIZATION_COMPONENT, EXTENDED_COUNTER_KEY
            )
            qualified, counter_deltas = self._qualified_interval(prior, current)
            current_metrics = (
                attributed_metrics
                if attributed_metrics is not None
                else snapshot_metrics(
                    current,
                    ring_capacity=self._ring_capacity_entries,
                )
            )
            metric_attributed = phase.kind != "peak_status" or (
                attributed_metrics is not None
            )
            if metric_attributed:
                if phase_metrics is None:
                    phase_metrics = current_metrics
                else:
                    for name, value in current_metrics.items():
                        if isinstance(value, bool):
                            phase_metrics[name] = bool(phase_metrics[name]) and value
                        elif name == "ring_capacity_entries":
                            if phase_metrics[name] != value:
                                raise ProgrammeTerminalError(
                                    "evidence_discontinuity",
                                    "UART ring capacity changed during phase",
                                )
                        else:
                            phase_metrics[name] = max(
                                int(phase_metrics[name]), int(value)
                            )
            fault_map = {
                "hardware_overrun_count": "uart_overrun",
                "hardware_framing_count": "uart_framing",
                "hardware_parity_count": "uart_parity",
                "hardware_break_count": "uart_break",
                "bytes_dropped_before_retention": "raw_ring_overflow",
                "overflow_count": "raw_ring_overflow",
                "link_checksum_failure_count": "metadata_checksum_failure",
                "metadata_checksum_failure_count": "metadata_checksum_failure",
                "parser_drop_count": "parser_drop",
                "truncated_count": "metadata_truncation",
                "oversize_count": "metadata_oversize",
            }
            interval_transport_fault = False
            for counter, fault_class in fault_map.items():
                if counter_deltas.get(counter, 0) <= 0:
                    continue
                interval_transport_fault = True
                if fault_class not in observed_fault_classes:
                    observed_fault_classes.add(fault_class)
                    fault = {
                            "fault_class": fault_class,
                            "timestamp_ticks": self.now_ticks,
                            "counter": counter,
                            "counter_delta": counter_deltas[counter],
                        }
                    local_faults.append(fault)
                    self._local_fault(fault)
            if (
                counter_deltas.get("metadata_hold_count", 0) > 0
                and interval_transport_fault
            ):
                self._transport_metadata_hold_count += counter_deltas[
                    "metadata_hold_count"
                ]
                if "transport_metadata_hold" not in observed_fault_classes:
                    observed_fault_classes.add("transport_metadata_hold")
                    fault = {
                            "fault_class": "transport_metadata_hold",
                            "timestamp_ticks": self.now_ticks,
                            "counter_delta": counter_deltas["metadata_hold_count"],
                        }
                    local_faults.append(fault)
                    self._local_fault(fault)
            # The transition frontier binds the accepted baud epoch; it is not
            # an online-duration clock and legitimately remains stable until
            # the next transition.  Online freshness comes from a newer
            # coherent generation/reference sequence and forward movement in
            # the exact extended Timer0 domain.
            prior_frontier = prior.integer(
                CHARACTERIZATION_COMPONENT, "transition_evidence_frontier"
            )
            current_frontier = current.integer(
                CHARACTERIZATION_COMPONENT, "transition_evidence_frontier"
            )
            current_reference = current.integer(
                CHARACTERIZATION_COMPONENT, "snapshot_reference_sequence"
            )
            prior_reference = prior.integer(
                CHARACTERIZATION_COMPONENT, "snapshot_reference_sequence"
            )
            current_mirror_generation = current.integer(
                "pps_gate", "characterization_mirror_generation"
            )
            prior_mirror_generation = prior.integer(
                "pps_gate", "characterization_mirror_generation"
            )
            interval_ticks = exact_counter_delta(
                prior_ticks,
                current_ticks,
                contract=self.contract,
                domain_name="rp2040_timer0_extended",
            )
            coherent_progress = (
                current.generation > prior.generation
                and current_reference >= prior_reference
                and current_mirror_generation > prior_mirror_generation
                and interval_ticks > 0
                and prior_frontier >= self._last_transition_frontier
                and current_frontier >= prior_frontier
            )
            qualified = qualified and coherent_progress
            if qualified:
                accumulated += interval_ticks
            prior_ticks = current_ticks
            prior = current
            last_snapshot = current
            self._heartbeat(self.now_ticks)
        self._online_counter_ticks += accumulated
        if phase_metrics is None:
            raise ProgrammeTerminalError(
                "evidence_discontinuity", "peak phase has no attributed peak metrics"
            )
        self._latest_phase_snapshot = last_snapshot
        end_counters = snapshot_counters(last_snapshot)
        end_counters["transport_metadata_hold_count"] = (
            self._transport_metadata_hold_count
        )
        return PhaseOutcome(
            end_ticks=self.now_ticks,
            online_counter_ticks=self._online_counter_ticks,
            end_counters=end_counters,
            metrics=phase_metrics,
            # First occurrences were synchronously published above so the
            # supervisor/monitor can report them during multi-hour phases.
            local_faults=(),
            status_challenges=tuple(challenges),
            sole_owner_preserved=True,
            d14_d8_noninterference=all(
                exact_counter_deltas(start.start_counters, end_counters).get(target, 0)
                == 0
                for target in NONINTERFERENCE_COUNTER_KEYS.values()
            ) and end_counters["dual_core_partition_fault_count"] == 0,
            evidence_continuous=True,
        )

    def final_state_evidence(self) -> Mapping[str, Any]:
        snapshot = self._latest_phase_snapshot
        baseline = self._latest_phase_start_counters
        if (
            snapshot is None
            or baseline is None
            or self._latest_phase_segment_id != "S11"
        ):
            raise RuntimeError("final S11 snapshot evidence is unavailable")
        counters = snapshot_counters(snapshot)
        frontier = snapshot.integer(
            CHARACTERIZATION_COMPONENT, "transition_evidence_frontier"
        )
        return {
            "confirmed_baud": snapshot.integer(
                CHARACTERIZATION_COMPONENT, "confirmed_baud"
            ),
            "identity_confirmed": (
                snapshot.value(RECEIVER_COMPONENT, "identity_stable") == "true"
            ),
            "configuration_confirmed": (
                snapshot.value(RECEIVER_COMPONENT, "configuration_confirmed")
                == "true"
            ),
            "fresh_rmc": counters["rmc_count"] > baseline["rmc_count"],
            "fresh_gga": counters["gga_count"] > baseline["gga_count"],
            "fresh_two_gsa": counters["gsa_count"] >= baseline["gsa_count"] + 2,
            "snapshot_generation": snapshot.generation,
            "metadata_frontier": frontier,
        }
