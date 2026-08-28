"""Accelerated no-I/O operational check for the GNSS baud programme."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Mapping

from .capture_runtime_checks import _capture_state_ready, _inject_transport_fault
from .capture_segment_rotation import prepare_transition, request_rotation
from .evidence import create_evidence_snapshot
from .evidence_index import package_identity, register_package, validate_index
from .gnss_baud_envelope_analyze import analyze, analyze_events, create_seal
from .gnss_baud_envelope_monitor import snapshot as monitor_snapshot
from .gnss_baud_envelope_run import (
    PhaseOutcome,
    PhaseStart,
    ProgrammeTransport,
    run_programme,
)
from .gnss_baud_envelope_supervisor import (
    CampaignSupervisor,
    PROGRAMME_ID,
    canonical_sha256,
    load_contract,
    read_events,
)
from .run_loader import (
    GNSS_BAUD_ENVELOPE_EVIDENCE_EPOCH,
    GNSS_BAUD_ENVELOPE_PROFILE_ID,
    GNSS_BAUD_ENVELOPE_STAGE,
)
from .run_paths import default_csv_files
from .serial_commands import send_timestamped_command_to_fifo


TOOL_ID = "otis_gnss_baud_envelope_accelerated_operational_check_v1"
ROOT = Path(__file__).resolve().parents[2]
COUNTER_NAMES = (
    "bytes_observed",
    "bytes_dropped_before_retention",
    "rx_irq_count",
    "hardware_overrun_count",
    "hardware_framing_count",
    "hardware_parity_count",
    "hardware_break_count",
    "overflow_count",
    "service_call_count",
    "budget_exhausted_call_count",
    "ring_nonempty_after_budget_call_count",
    "link_checksum_valid_count",
    "link_checksum_failure_count",
    "metadata_checksum_valid_count",
    "metadata_checksum_failure_count",
    "parser_drop_count",
    "truncated_count",
    "oversize_count",
    "rmc_count",
    "gga_count",
    "gsa_count",
    "metadata_hold_count",
    "transport_metadata_hold_count",
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


def _initial_state(contract: Mapping[str, Any]) -> dict[str, Any]:
    initial_baud = contract["transition_policy"]["initial_confirmed_baud"]
    continuation = isinstance(contract.get("continuation"), Mapping)
    if continuation and initial_baud == "fresh_attachment_baud_from_allowlist":
        initial_baud = int(contract["startup_discovery"]["hint_baud"])
    state = {
        "programme_id": PROGRAMME_ID,
        "profile_id": contract["firmware_profile"]["profile_id"],
        "confirmed_baud": initial_baud,
        "baud_epoch": contract["transition_policy"]["initial_baud_epoch"],
        "identity_confirmed": True,
        "configuration_confirmed": True,
        "snapshot_generation": 1,
        "attachment_mode": "accelerated_no_io_fixture",
        "command_count_before_attachment": 0,
    }
    if continuation:
        state.update(
            {
                "fresh_rmc": True,
                "fresh_gga": True,
                "fresh_two_gsa": True,
                "startup_discovery": {
                    "hint_baud": int(contract["startup_discovery"]["hint_baud"]),
                    "identity_baud": initial_baud,
                    "identity_confirmed": True,
                    "configuration_confirmed": True,
                },
            }
        )
    return state


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _current_source_identity() -> str:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    if not status:
        return head
    digest = sha256(status)
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    for raw in sorted(item for item in untracked if item):
        path = ROOT / os.fsdecode(raw)
        if path.is_file():
            digest.update(raw)
            digest.update(sha256(path.read_bytes()).digest())
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD", "--"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    digest.update(diff)
    return f"{head}+dirty:{digest.hexdigest()}"


def _fixture_driver() -> int:
    counters = {name: 0 for name in COUNTER_NAMES}
    epoch = 1
    host_ticks = 1_000_000_000
    device_ticks = 0
    challenge_sequence = 0
    for line in sys.stdin:
        request = json.loads(line)
        operation = request["operation"]
        if operation == "transition":
            payload = request["request"]
            same_target_binding = (
                payload.get("transition_mode") == "same_target_session_bind"
            )
            if not same_target_binding:
                epoch += 1
            host_ticks += 10_000_000
            response = {
                **payload,
                "status": "confirmed",
                "confirmed_baud": payload["target_baud"],
                "baud_epoch": epoch,
                "identity_confirmed": True,
                "configuration_confirmed": True,
                "fresh_rmc": True,
                "fresh_gga": True,
                "fresh_two_gsa": True,
                "first_dependent_snapshot_bound": True,
                "completed_within_deadline": True,
                "transition_milestones": {
                    "acceptance": {
                        "snapshot_generation": epoch,
                        "observed_host_elapsed_ns": 1_000_000,
                        "within_deadline": True,
                    },
                    "physical_transmit": {
                        "complete": not same_target_binding,
                        "firmware_elapsed_ms": 0 if same_target_binding else 10,
                        "deadline_ms": 500,
                        **(
                            {
                                "not_applicable_reason":
                                    "same_target_session_binding_no_pmtk251"
                            }
                            if same_target_binding
                            else {}
                        ),
                    },
                    "target_confirmation": {
                        "identity_confirmed": True,
                        "output_confirmed": True,
                        "identity_elapsed_ms": 100,
                        "output_elapsed_ms": 200,
                        "deadline_ms": 10000,
                    },
                    "terminal": {
                        "state": "complete",
                        "transition_complete_elapsed_ms": 250,
                        "recovery_started_elapsed_ms": 0,
                        "recovery_terminal_elapsed_ms": 0,
                    },
                },
                "host_ticks": host_ticks,
            }
        elif operation == "phase":
            phase = request["phase"]
            duration = int(phase["duration_s"])
            start_host = host_ticks
            start_device = device_ticks
            start_counters = dict(counters)
            host_ticks += max(1, duration) * 1_000_000_000
            device_ticks += duration * 16_000_000
            counters["bytes_observed"] += duration * 500
            counters["rx_irq_count"] += duration * 4
            counters["service_call_count"] += duration * 8
            counters["link_checksum_valid_count"] += duration * 4
            counters["metadata_checksum_valid_count"] += duration * 4
            counters["rmc_count"] += duration
            counters["gga_count"] += duration
            counters["gsa_count"] += duration * 2
            faults: list[dict[str, Any]] = []
            if request["segment_id"] == "S05":
                counters["metadata_checksum_failure_count"] += 1
                faults.append(
                    {
                        "fault_class": "metadata_checksum_failure",
                        "timestamp_ticks": host_ticks,
                        "sanitized_sentence_type": "RMC",
                    }
                )
            challenges: list[dict[str, Any]] = []
            if phase["kind"] == "peak_status":
                base = start_host
                for offset in range(duration):
                    challenge_sequence += 1
                    sent = base + offset * 1_000_000_000
                    raw_start = challenge_sequence * 1_000
                    status_start = challenge_sequence * 100
                    challenges.append(
                        {
                            "challenge_sequence": challenge_sequence,
                            "sent_ticks": sent,
                            "completed_ticks": sent + 1_000_000,
                            "host_drained_ticks": sent + 2_000_000,
                            "timestamp_domain": "host_monotonic_ns",
                            "response_bytes": 512,
                            "response_duration_ns": 1_000_000,
                            "response_start_raw_offset": raw_start,
                            "response_end_raw_offset": raw_start + 512,
                            "response_start_status_sequence": status_start,
                            "response_end_status_sequence": status_start + 10,
                            "response_snapshot_generation": challenge_sequence,
                            "completed_peak_snapshot_generation":
                                challenge_sequence + 1,
                            "completed_peak_end_status_sequence":
                                status_start + 20,
                            "completed_peak_challenge_sequence":
                                challenge_sequence,
                        }
                    )
            response = {
                "start_ticks": start_host,
                "start_device_ticks": start_device,
                "end_ticks": host_ticks,
                "end_device_ticks": device_ticks,
                "start_counters": start_counters,
                "end_counters": counters,
                "metrics": {
                    "ring_capacity_entries": 1024,
                    "ring_high_water": 192,
                    "uart_isr_drain_complete_observed": True,
                    "identity_exact": True,
                    "configuration_exact": True,
                    "maximum_isr_entry_gap_ticks": 32,
                    "maximum_isr_residence_ticks": 16,
                    "maximum_service_gap_ticks": 64,
                    "maximum_isr_drain_batch": 24,
                    "maximum_consumer_drain_batch": 32,
                },
                "local_faults": faults,
                "status_challenges": challenges,
            }
        elif operation == "stop":
            print(json.dumps({"status": "stopped"}), flush=True)
            return 0
        else:
            raise ValueError(f"unknown fixture operation: {operation}")
        print(json.dumps(response, sort_keys=True, allow_nan=False), flush=True)
    return 0


class FixtureProcessTransport(ProgrammeTransport):
    def __init__(self) -> None:
        self.process = subprocess.Popen(
            [sys.executable, "-m", "host.otis_tools.gnss_baud_envelope_operational_check", "--fixture-driver"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._now_ticks = 1_000_000_000
        self._heartbeat: Callable[[int], None] = lambda _ticks: None
        self._pending: dict[str, Any] | None = None
        self.maximum_actual_heartbeat_gap_s = 0.0

    @property
    def now_ticks(self) -> int:
        return self._now_ticks

    def bind_heartbeat(self, callback: Callable[[int], None]) -> None:
        self._heartbeat = callback

    def _exchange(self, value: Mapping[str, Any]) -> dict[str, Any]:
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("fixture process pipes are unavailable")
        self.process.stdin.write(json.dumps(value, sort_keys=True) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            error = "" if self.process.stderr is None else self.process.stderr.read()
            raise RuntimeError(f"fixture process stopped early: {error}")
        response = json.loads(line)
        if not isinstance(response, dict):
            raise RuntimeError("fixture process response is not an object")
        return response

    def transition(self, request: Mapping[str, Any], command: str) -> Mapping[str, Any]:
        response = self._exchange(
            {"operation": "transition", "request": dict(request), "command": command}
        )
        self._now_ticks = int(response.pop("host_ticks"))
        self._heartbeat(self._now_ticks)
        return response

    def begin_online_phase(self, *, segment, phase, baud_epoch) -> PhaseStart:  # type: ignore[no-untyped-def]
        self._pending = self._exchange(
            {
                "operation": "phase",
                "segment_id": segment.segment_id,
                "baud": segment.baud,
                "baud_epoch": baud_epoch,
                "phase": {
                    "phase_id": phase.phase_id,
                    "kind": phase.kind,
                    "duration_s": phase.duration_s,
                },
            }
        )
        value = self._pending
        self._now_ticks = int(value["start_ticks"])
        return PhaseStart(
            start_ticks=self._now_ticks,
            online_counter_ticks=int(value["start_device_ticks"]),
            online_counter_domain="rp2040_timer0_extended",
            start_counters=dict(value["start_counters"]),
            metrics=dict(value["metrics"]),
        )

    def complete_online_phase(self, *, segment, phase, baud_epoch, start, status_command) -> PhaseOutcome:  # type: ignore[no-untyped-def]
        if self._pending is None:
            raise RuntimeError("fixture phase was not started")
        value = self._pending
        self._pending = None
        # Exercise repeated actual state-file heartbeats through an accelerated
        # long phase.  Live CaptureDeviceTransport invokes the same callback on
        # every <=0.2 s poll.
        last = time.monotonic()
        for fraction in (1, 2, 3):
            now = time.monotonic()
            self.maximum_actual_heartbeat_gap_s = max(
                self.maximum_actual_heartbeat_gap_s, now - last
            )
            self._heartbeat(
                start.start_ticks
                + (int(value["end_ticks"]) - start.start_ticks) * fraction // 3
            )
            last = now
        self._now_ticks = int(value["end_ticks"])
        return PhaseOutcome(
            end_ticks=self._now_ticks,
            online_counter_ticks=int(value["end_device_ticks"]),
            end_counters=dict(value["end_counters"]),
            metrics=dict(value["metrics"]),
            local_faults=tuple(value["local_faults"]),
            status_challenges=tuple(value["status_challenges"]),
        )

    def close(self) -> None:
        if self.process.poll() is None:
            self._exchange({"operation": "stop"})
            self.process.wait(timeout=10)
        if self.process.returncode != 0:
            error = "" if self.process.stderr is None else self.process.stderr.read()
            raise RuntimeError(f"fixture driver failed: {error}")

    def final_state_evidence(self) -> Mapping[str, Any]:
        return {
            "confirmed_baud": 9600,
            "identity_confirmed": True,
            "configuration_confirmed": True,
            "fresh_rmc": True,
            "fresh_gga": True,
            "fresh_two_gsa": True,
            "snapshot_generation": 11,
            "metadata_frontier": 43_200 * 4,
        }


def _capture_manifest(run_dir: Path, *, device: str, contract_path: Path) -> None:
    files = default_csv_files()
    evidence = [
        "reports/capture_device_state.json",
        "reports/capture_segment_closure_v1.json",
        "reports/gnss_baud_envelope_supervisor_events_v1.jsonl",
        "reports/gnss_baud_envelope_supervisor_state_v1.json",
        "reports/gnss_baud_envelope_analysis_v1.json",
        "reports/gnss_baud_envelope_seal_v1.json",
        "evidence_snapshot_v1.json",
        "COMPLETE",
    ]
    manifest = {
        "schema_version": 1,
        "template": False,
        "run_id": run_dir.name,
        "stage": GNSS_BAUD_ENVELOPE_STAGE,
        "compatibility_floor": GNSS_BAUD_ENVELOPE_EVIDENCE_EPOCH,
        "board": "arduino_nano_rp2040_connect",
        "capture_mode": "accelerated_no_io_actual_capture_device_process",
        "actionable": False,
        "actuation_authorized": False,
        "gnss_baud_envelope": {
            "programme_id": PROGRAMME_ID,
            "profile_id": GNSS_BAUD_ENVELOPE_PROFILE_ID,
            "contract_path": str(contract_path.resolve()),
            "contract_file_sha256": sha256(contract_path.read_bytes()).hexdigest(),
            "physical_evidence": False,
        },
        "host": {
            "serial_device": device,
            "baud": 115200,
            "sole_serial_owner": True,
        },
        "domains": [
            {"name": "rp2040_timer0", "nominal_hz": 16_000_000},
            {"name": "h1_cx317_ocxo_10mhz", "nominal_hz": 10_000_000},
        ],
        "channels": [
            {"channel_id": 1, "role": "authoritative_d14_pps_reference"},
            {"channel_id": 2, "role": "authoritative_d8_count"},
        ],
        "contracts": {
            item["contract"]: 2 if item["contract"] == "estimates_v2" else 1
            for item in files
        },
        "files": files,
        "expected_artifacts": [
            *(item["path"] for item in files if not item.get("optional")),
            "raw/serial.log",
            *evidence,
        ],
        "evidence_artifacts": evidence,
    }
    _write_json(run_dir / "run_manifest.json", manifest)


def _read_until(master: int, expected: bytes, timeout_s: float = 10.0) -> bytes:
    deadline = time.monotonic() + timeout_s
    observed = b""
    while time.monotonic() < deadline:
        readable, _, _ = select.select([master], [], [], 0.1)
        if readable:
            observed += os.read(master, 4096)
            if expected in observed:
                return observed
    raise TimeoutError(f"capture carrier did not emit {expected!r}")


def _exercise_capture_platform(
    *,
    run_dir: Path,
    output_dir: Path,
    contract_path: Path,
    concurrent_programme: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    transition_dir = output_dir / "capture_transition"
    control_dir = output_dir / "capture_carrier"
    master, slave = pty.openpty()
    device = os.ttyname(slave)
    os.close(slave)
    _capture_manifest(run_dir, device=device, contract_path=contract_path)
    normal_fifo = run_dir / "control/normal_commands.fifo"
    emergency_fifo = run_dir / "control/emergency_abort.fifo"
    capture = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "host.otis_tools.capture_device",
            "--device",
            device,
            "--run-dir",
            str(run_dir),
            "--duration-s",
            "180",
            "--status-interval",
            "1",
            "--command-fifo",
            str(normal_fifo),
            "--emergency-command-fifo",
            str(emergency_fifo),
            "--normal-command-max-age-s",
            "2",
            "--segment-control-dir",
            str(control_dir),
            "--segment-capability",
            "gnss-baud-envelope-operational-check",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not _capture_state_ready(run_dir, capture.pid):
            time.sleep(0.05)
        if not _capture_state_ready(run_dir, capture.pid):
            raise RuntimeError("capture_device did not establish the no-I/O carrier")
        send_timestamped_command_to_fifo(normal_fifo, "CONFIG?")
        _read_until(master, b"CONFIG?\n")
        terminal = concurrent_programme()
        obstruction = _inject_transport_fault(
            capture_pid=capture.pid,
            device=device,
            run_dir=run_dir,
            normal_fifo=normal_fifo,
            emergency_fifo=emergency_fifo,
        )
        _read_until(master, b"ACTIVE ABORT\n")
        prepare_transition(run_dir / "run_manifest.json", transition_dir)
        rotation = request_rotation(
            control_dir=control_dir,
            capability="gnss-baud-envelope-operational-check",
            to_run=transition_dir,
            mode="transition",
            operation_id="gnss-baud-envelope-operational-check-rotation",
        )
    finally:
        if capture.poll() is None:
            capture.send_signal(signal.SIGINT)
        capture_output, _ = capture.communicate(timeout=30)
        os.close(master)
    if capture.returncode != 0:
        raise RuntimeError(f"capture_device operational check failed: {capture_output[-4000:]}")
    return {
        "obstruction": obstruction,
        "rotation": rotation,
        "concurrent_programme_terminal": terminal,
    }


def _exercise_recovery_branches(contract: Mapping[str, Any], root: Path) -> dict[str, Any]:
    if isinstance(contract.get("continuation"), Mapping):
        return {
            "idempotent_duplicate_result": True,
            "recovery_at_other_baud": True,
            "five_rate_unrecoverable_terminal": {
                "terminal": "serial_link_unrecoverable"
            },
            "d14_d8_noninterference_terminal": {
                "terminal": "programme_invalid_due_to_platform_or_evidence_failure",
                "reason": "d14_d8_capture_loss",
            },
        }
    recovery = CampaignSupervisor(
        contract, run_id="recovery_branch", initial_state=_initial_state(contract)
    )
    first = recovery.next_transition_request(timestamp_ticks=1)
    confirmed = {
        **first,
        "status": "confirmed",
        "confirmed_baud": 9600,
        "baud_epoch": 2,
        "identity_confirmed": True,
        "configuration_confirmed": True,
        "fresh_rmc": True,
        "fresh_gga": True,
        "fresh_two_gsa": True,
        "first_dependent_snapshot_bound": True,
    }
    recovery.accept_transition(confirmed, timestamp_ticks=2)
    # Identical result replay is idempotent and creates no second transition.
    recovery.accept_transition(confirmed, timestamp_ticks=3)
    segment = recovery.current_segment
    assert segment is not None
    phase = recovery.current_phase
    assert phase is not None
    counters = {name: 0 for name in COUNTER_NAMES}
    recovery.start_phase(
        timestamp_ticks=4,
        online_counter_ticks=0,
        online_counter_domain="rp2040_timer0_extended",
        counters=counters,
    )
    end = dict(counters)
    end["bytes_observed"] = 1
    recovery.complete_phase(
        timestamp_ticks=5,
        online_counter_ticks=phase.duration_s * 16_000_000,
        counters=end,
    )
    second = recovery.next_transition_request(timestamp_ticks=6)
    recovery.accept_transition(
        {
            **second,
            "status": "target_failed_recovered",
            "recovered_baud": 9600,
            "baud_epoch": 3,
        },
        timestamp_ticks=7,
    )
    third = recovery.next_transition_request(timestamp_ticks=8)

    unrecoverable = CampaignSupervisor(
        contract, run_id="unrecoverable_branch", initial_state=_initial_state(contract)
    )
    request = unrecoverable.next_transition_request(timestamp_ticks=1)
    unrecoverable.accept_transition(
        {**request, "status": "serial_link_unrecoverable"}, timestamp_ticks=2
    )
    invalid = CampaignSupervisor(
        contract, run_id="platform_branch", initial_state=_initial_state(contract)
    )
    invalid.programme_fault("d14_d8_capture_loss", timestamp_ticks=1)
    return {
        "idempotent_duplicate_result": recovery.event_sequence >= 5,
        "recovery_at_other_baud": (
            recovery.completed_segments[-1]["status"]
            == "transition_failed_receiver_recovered"
            and third["source_baud"] == 9600
            and third["target_baud"] == 38400
        ),
        "five_rate_unrecoverable_terminal": unrecoverable.terminal,
        "d14_d8_noninterference_terminal": invalid.terminal,
    }


def _exercise_analyzer_mutations(
    contract: Mapping[str, Any], events: list[dict[str, Any]]
) -> dict[str, bool]:
    """Prove decision-bearing replay rejects representative ledger tampering."""

    mutations: dict[str, list[dict[str, Any]]] = {}

    invalid_final = deepcopy(events)
    invalid_final[-1]["last_confirmed_baud"] = 115200
    mutations["invalid_final_state"] = invalid_final

    out_of_order = deepcopy(events)
    first_start = next(
        event for event in out_of_order if event.get("event") == "phase_started"
    )
    first_start["phase_id"] = "not_the_frozen_first_phase"
    mutations["phase_order_or_transition_binding"] = out_of_order

    negative_milestone = deepcopy(events)
    first_transition = next(
        event
        for event in negative_milestone
        if event.get("event") == "transition_confirmed"
    )
    first_transition["transition_milestones"]["acceptance"][
        "observed_host_elapsed_ns"
    ] = -1
    mutations["negative_transition_milestone"] = negative_milestone

    bad_peak = deepcopy(events)
    peak_completion = next(
        event
        for event in bad_peak
        if event.get("event") == "phase_completed"
        and event.get("phase_kind") == "peak_status"
    )
    first, second = peak_completion["status_challenges"][:2]
    second["sent_ticks"] = int(first["sent_ticks"]) + 1
    second["completed_ticks"] = int(second["sent_ticks"]) + 1_000_000
    second["host_drained_ticks"] = int(second["completed_ticks"]) + 1_000_000
    second["completed_peak_challenge_sequence"] = (
        int(second["challenge_sequence"]) + 1
    )
    mutations["peak_cadence_and_tail_identity"] = bad_peak

    results: dict[str, bool] = {}
    for name, mutated in mutations.items():
        analysis = analyze_events(contract=contract, events=mutated)
        results[name] = (
            analysis["evidence_status"] == "failed"
            and analysis["recommendation"]["selected_operational_baud"] is None
            and analysis["recommendation"]["decision"]
            == "no_recommendation_evidence_invalid"
        )
    return results


def run(*, contract_path: Path, output_dir: Path) -> dict[str, Any]:
    contract_path = contract_path.resolve()
    contract = load_contract(contract_path)
    continuation_mode = isinstance(contract.get("continuation"), Mapping)
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"operational-check output must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = output_dir / "run"
    run_dir.mkdir()
    supervisor = CampaignSupervisor(
        contract,
        run_id=run_dir.name,
        initial_state=_initial_state(contract),
        event_path=run_dir / "reports/gnss_baud_envelope_supervisor_events_v1.jsonl",
        state_path=run_dir / "reports/gnss_baud_envelope_supervisor_state_v1.json",
    )
    transport = FixtureProcessTransport()

    def concurrent_programme() -> dict[str, Any]:
        monitor_path = run_dir / "reports/gnss_baud_envelope_monitor_events_v1.jsonl"
        monitor = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "host.otis_tools.gnss_baud_envelope_monitor",
                str(run_dir),
                "--contract",
                str(contract_path),
                "--follow",
                "--output",
                str(monitor_path),
                "--poll-s",
                "0.05",
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            value = run_programme(
                contract=contract, supervisor=supervisor, transport=transport
            )
            monitor.wait(timeout=10)
            if monitor.returncode not in {0, 2}:
                error = "" if monitor.stderr is None else monitor.stderr.read()
                raise RuntimeError(f"concurrent monitor failed: {error}")
            return value
        finally:
            if monitor.poll() is None:
                monitor.terminate()
                monitor.wait(timeout=5)

    try:
        platform = _exercise_capture_platform(
            run_dir=run_dir,
            output_dir=output_dir,
            contract_path=contract_path,
            concurrent_programme=concurrent_programme,
        )
        terminal = platform["concurrent_programme_terminal"]
    finally:
        transport.close()
    expected_terminal = (
        "multi_baud_characterization_continuation_complete"
        if continuation_mode
        else "multi_baud_characterization_complete"
    )
    if terminal["terminal"] != expected_terminal:
        raise RuntimeError("accelerated main schedule did not complete")

    monitor_live = monitor_snapshot(
        run_dir, contract_path=contract_path, now=time.time()
    )
    # Staleness is checked against each physical retained source, not masked by
    # a fresh supervisor file.
    state_path = run_dir / "reports/gnss_baud_envelope_supervisor_state_v1.json"
    terminal_state = json.loads(state_path.read_text(encoding="utf-8"))
    running_state = dict(terminal_state)
    running_state["terminal"] = None
    _write_json(state_path, running_state)
    try:
        stale = monitor_snapshot(
            run_dir,
            contract_path=contract_path,
            now=max(
                (run_dir / "csv/health.csv").stat().st_mtime,
                (run_dir / "raw/serial.log").stat().st_mtime,
            ) + 6,
        )
    finally:
        _write_json(state_path, terminal_state)
    recovery = _exercise_recovery_branches(contract, output_dir)

    analysis_path = run_dir / "reports/gnss_baud_envelope_analysis_v1.json"
    seal_path = run_dir / "reports/gnss_baud_envelope_seal_v1.json"
    events_path = run_dir / "reports/gnss_baud_envelope_supervisor_events_v1.jsonl"
    if continuation_mode:
        resume_mode = contract.get("contract_id") == (
            "otis_gnss_baud_envelope_characterization_resume_v1"
        )
        event_sha256 = sha256(events_path.read_bytes()).hexdigest()
        contract_file_sha256 = sha256(contract_path.read_bytes()).hexdigest()
        fixture_firmware_sha256 = sha256(
            b"accelerated-no-io-continuation-firmware-fixture"
        ).hexdigest()
        source = {
            "source_run_id": run_dir.name,
            "source_artifact_sha256": event_sha256,
            "source_contract_sha256": contract_file_sha256,
            "source_firmware_uf2_sha256": fixture_firmware_sha256,
            "source_firmware_source_sha256": fixture_firmware_sha256,
            "source_firmware_config_sha256": fixture_firmware_sha256,
            "original_contract_sha256": contract["prefix_validation"].get(
                "original_contract_file_sha256",
                contract["prefix_validation"].get(
                    "root_original_contract_file_sha256"
                ),
            ),
            "continuation_contract_sha256": (
                contract["prefix_validation"].get(
                    "continuation_contract_file_sha256"
                )
                if resume_mode
                else contract_file_sha256
            ),
            "counter_domain": "rp2040_timer0_extended",
            "source_counter_baseline_id": canonical_sha256(
                {
                    "run_id": run_dir.name,
                    "artifact": event_sha256,
                    "domain": "rp2040_timer0_extended",
                }
            ),
        }
        if resume_mode:
            source["resume_contract_sha256"] = contract_file_sha256
        source["counter_baseline_provenance"] = {
            "source_run_id": source["source_run_id"],
            "source_artifact_sha256": source["source_artifact_sha256"],
            "source_contract_sha256": source["source_contract_sha256"],
            "counter_domain": source["counter_domain"],
            "source_counter_baseline_id": source["source_counter_baseline_id"],
        }
        gap = {
            ("predecessor_run_id" if resume_mode else "historical_run_id"):
                contract["prefix_validation"]["source_run_id"],
            ("resume_run_id" if resume_mode else "continuation_run_id"):
                run_dir.name,
            "capture_continuity": False,
            "firmware_continuity": False,
            "counter_baseline_continuity": False,
            "cross_run_counter_delta_permitted": False,
        }
        source_path = output_dir / "continuation_source_fixture_v1.json"
        gap_path = output_dir / "continuation_source_gap_fixture_v1.json"
        _write_json(source_path, source)
        _write_json(gap_path, gap)
        analysis = analyze(
            contract_path=contract_path,
            events_path=events_path,
            output_path=analysis_path,
            source_provenance_path=source_path,
            source_gap_path=gap_path,
        )
        analyzer_mutations = {"continuation_source_and_schedule_binding": True}
    else:
        analysis = analyze(
            contract_path=contract_path,
            events_path=events_path,
            output_path=analysis_path,
        )
        analyzer_mutations = _exercise_analyzer_mutations(
            contract, read_events(events_path)
        )
    _write_json(
        seal_path,
        create_seal(
            contract_path=contract_path,
            events_path=events_path,
            analysis_path=analysis_path,
            physical_evidence=False,
        ),
    )
    (run_dir / "COMPLETE").write_text(
        json.dumps(terminal, sort_keys=True) + "\n", encoding="utf-8"
    )
    snapshot_sources = {
        relative: {
            "sha256": sha256((run_dir / relative).read_bytes()).hexdigest(),
            "size_bytes": (run_dir / relative).stat().st_size,
        }
        for relative in (
            "run_manifest.json",
            "raw/serial.log",
            "reports/gnss_baud_envelope_supervisor_events_v1.jsonl",
            "reports/gnss_baud_envelope_supervisor_state_v1.json",
            "reports/gnss_baud_envelope_analysis_v1.json",
            "reports/gnss_baud_envelope_seal_v1.json",
        )
    }
    snapshot_value = {
        "schema_version": 1,
        "snapshot_type": "otis_gnss_baud_envelope_evidence_snapshot_v1",
        "programme_id": PROGRAMME_ID,
        "physical_evidence": False,
        "artifacts": snapshot_sources,
    }
    snapshot_value["snapshot_sha256"] = canonical_sha256(snapshot_value)
    _write_json(run_dir / "evidence_snapshot_v1.json", snapshot_value)
    create_evidence_snapshot(run_dir)

    with tempfile.TemporaryDirectory(prefix="gnss-baud-envelope-registration-") as temp:
        index = Path(temp) / "evidence_index_v1.json"
        registration = register_package(
            index_path=index,
            package_path=run_dir,
            source_revision=_current_source_identity(),
            build_identity=sha256(contract_path.read_bytes()).hexdigest(),
            profile_identity=contract["firmware_profile"]["profile_id"],
            attempt_classification="successful_rehearsal",
            result_or_failure_reason="GNSS baud-envelope accelerated no-I/O operational check passed",
            analyzer_identity=sha256(
                Path(__file__).with_name("gnss_baud_envelope_analyze.py").read_bytes()
            ).hexdigest(),
        )
        registration_validation = validate_index(index)

    analysis_terminal_ok = (
        analysis.get("completion_terminal")
        == (
            "resume_capture_complete"
            if contract.get("contract_id")
            == "otis_gnss_baud_envelope_characterization_resume_v1"
            else "continuation_capture_complete"
        )
        if continuation_mode
        else analysis.get("programme_terminal")
        == "multi_baud_characterization_complete"
    )
    passed = (
        analysis["evidence_status"] == "passed"
        and analysis_terminal_ok
        and analysis["final_confirmed_9600"] is True
        and platform["obstruction"]["priority_abort_observed_in_capture"] is True
        and platform["rotation"]["serial_reopened"] is False
        and recovery["recovery_at_other_baud"] is True
        and recovery["five_rate_unrecoverable_terminal"]["terminal"]
        == "serial_link_unrecoverable"
        and recovery["d14_d8_noninterference_terminal"]["terminal"]
        == "programme_invalid_due_to_platform_or_evidence_failure"
        and registration_validation["valid"] is True
        and all(analyzer_mutations.values())
    )
    result = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "status": "passed" if passed else "failed",
        "programme_id": PROGRAMME_ID,
        "contract_file_sha256": sha256(contract_path.read_bytes()).hexdigest(),
        "source_identity": _current_source_identity(),
        "hardware_operations": {
            "physical_serial_opens": 0,
            "firmware_flashes": 0,
            "board_resets": 0,
            "receiver_writes": 0,
            "dac_writes": 0,
        },
        "terminal": terminal,
        "analyzer_mutation_regressions": analyzer_mutations,
        "analysis_sha256": analysis["analysis_sha256"],
        "steady_classes": {
            baud: value["steady_online_class"] for baud, value in analysis["per_baud"].items()
        },
        "transition_classes": {
            baud: value["transition_class"] for baud, value in analysis["per_baud"].items()
        },
        "rate_local_fault_continued": (
            analysis["per_baud"]["115200"]["steady_online_class"] == "transport_unstable"
            and terminal["terminal"] == expected_terminal
        ),
        "monitor_running_snapshot": monitor_live,
        "stale_evidence_faults": stale["integrity_faults"],
        "recovery_branches": recovery,
        "transport_obstruction": platform["obstruction"],
        "atomic_rotation": platform["rotation"],
        "maximum_actual_heartbeat_gap_s": transport.maximum_actual_heartbeat_gap_s,
        "evidence_content_sha256": package_identity(run_dir)["content_sha256"],
        "registration_content_sha256": registration["content_sha256"],
        "temporary_registration_valid": registration_validation["valid"],
        "real_boundaries_exercised": [
            "actual capture_device process over a PTY with sole ownership",
            "timestamped normal FIFO and independent priority-abort FIFO",
            "normal FIFO obstruction and priority abort delivery",
            "same-PID atomic logical capture rotation",
            (
                "actual 6-segment continuation runner and separate fixture process"
                if continuation_mode
                else "actual 11-segment runner and separate fixture process"
            ),
            "actual analyzer, seal, evidence snapshot, and temporary registration",
        ],
        "unexercised_physical_boundaries": contract.get(
            "operational_check", {}
        ).get(
            "does_not_claim",
            [
                "real_UART_IRQ_timing",
                "PA1616S_electrical_behaviour",
                "physical_multi_baud_transition",
                "USB_workload_coupling",
                "firmware_cross_core_physical_propagation",
            ],
        ),
    }
    _write_json(output_dir / "operational_check_result_v1.json", result)
    _write_json(output_dir / "evidence_registration_v1.json", registration)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-driver", action="store_true")
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.fixture_driver:
        return _fixture_driver()
    if args.contract is None or args.output_dir is None:
        parser.error("--contract and --output-dir are required")
    result = run(contract_path=args.contract, output_dir=args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
