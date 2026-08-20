"""Exercise the CX320 host process topology over a PTY without hardware I/O.

This rehearsal runs the real capture process and the real live-supervisor loop
with three distinct FIFOs, but binds them to a pseudo-terminal.  Long-duration
controller, response, degradation, and finalization boundaries are exercised
by the frozen accelerated rehearsal.  The receipt distinguishes those two
forms of coverage and makes no firmware, USB-device, DAC, plant, or physical
qualification claim.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import stat
import subprocess
import sys
import time
from typing import Any, Callable

from .abort_transport import send_abort
from .active_hybrid_bundle import validate_bundle
from .active_hybrid_live_supervisor import (
    CORRECTION_RESPONSE_RESERVE_S,
    QUALIFIED_DURATION_S,
    RP2040_TIMER0_TICKS_PER_SECOND,
    ActiveHybridLiveSupervisor,
    load_active_hybrid_spec,
)
from .active_hybrid_run import _wait_for_terminal_abort_delivery
from .active_hybrid_proposal import validate_proposal
from .active_hybrid_rehearsal import run as run_accelerated_rehearsal
from .active_status_contract import (
    ACTIVE_STATUS_KEYS,
    ACTIVE_STATUS_SNAPSHOT_CONTRACT,
    SNAPSHOT_BEGIN_KEY,
    SNAPSHOT_COMPLETE_KEY,
    SNAPSHOT_CONTRACT_KEY,
)
from .active_status_live_state import ActiveStatusLiveReducer
from .bounded_tight_deadband_prewrite_contract import (
    RAW_PPS_QUALIFICATION_DEADLINE_S,
    canonical_prewrite_fixture,
)
from .capture_runtime_checks import _capture_state_ready, _serial_owner_pids
from .capture_segment_rotation import prepare_transition, request_rotation
from .contracts import ACTIVE_HYBRID_DECISION_V1_FIELDS
from .run_paths import default_csv_files
from .serial_commands import send_timestamped_command_to_fifo


ROOT = Path(__file__).resolve().parents[2]
TOOL_ID = "cx320_active_hybrid_live_topology_rehearsal_v1"
REPORT_TYPE = "cx320_active_hybrid_live_topology_rehearsal_v1"
MODE = "cx320_accelerated_live_topology_rehearsal_pty"
LIVE_STAGE = "CX320_BOUNDED_ACTIVE_HYBRID_PHASE_FREQUENCY_LIVE"
PROGRAMME_ID = "CX320_BOUNDED_ACTIVE_HYBRID_PHASE_FREQUENCY_V1"
RUN_IDENTITY = "cx320_active_hybrid:3200001"
PROFILE_ID = "cx320_active_hybrid"
CAPABILITY = "cx320-active-hybrid-live-topology-rehearsal"
REHEARSAL_COVERAGE = (
    "capture_device_real_process",
    "pty_serial_carrier",
    "sole_serial_owner",
    "normal_command_fifo",
    "emergency_abort_fifo",
    "host_abort_fifo",
    "live_supervisor_process",
    "first_active_hybrid_wire_record",
    "active_hybrid_status_handoff",
    "setup_authority_qualification_deadline",
    "qualified_device_time_boundaries",
    "setup_propagation",
    "progressive_checkpoint",
    "conditional_release",
    "response_classification",
    "phase_only_degradation",
    "shared_fail_static_fault",
    "transport_obstruction",
    "terminal_abort_delivery_before_capture_close",
    "post_abort_complete_active_snapshot",
    "logical_evidence_rotation",
    "analysis_seal_registration",
)


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        if os.write(descriptor, payload) != len(payload):
            raise OSError(f"short immutable JSON write: {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _wait_until(
    predicate: Callable[[], bool], timeout_s: float, description: str
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise TimeoutError(f"timed out waiting for {description}")


def _read_until(master: int, expected: bytes, timeout_s: float = 10.0) -> bytes:
    deadline = time.monotonic() + timeout_s
    observed = b""
    while time.monotonic() < deadline:
        readable, _, _ = select.select([master], [], [], 0.1)
        if not readable:
            continue
        observed += os.read(master, 4096)
        if expected in observed:
            return observed
    raise TimeoutError(
        f"did not observe emulated firmware command {expected!r}: {observed!r}"
    )


def _active_hybrid_wire_fixture(bundle: dict[str, Any]) -> bytes:
    policy = _read_object(Path(str(bundle["policy"]["path"])))
    bindings = policy["bindings"]
    values = {field: "0" for field in ACTIVE_HYBRID_DECISION_V1_FIELDS}
    values.update(
        {
            "record_type": "AHY",
            "schema_version": "1",
            "hybrid_record_sequence": "1",
            "decision_sequence": "1",
            "decision_timestamp_s": "2401",
            "run_identity": RUN_IDENTITY,
            "build_identity": str(bundle["firmware"]["build_identity"]),
            "profile_identity": PROFILE_ID,
            "capture_session": "1",
            "source_first_sequence": "1799",
            "source_last_sequence": "2399",
            "frequency_estimator_sha256": bindings["frequency_estimator"][
                "sha256"
            ],
            "frequency_error_hz": "0.001666666940",
            "accumulated_edge_error_counts": "1",
            "tight_state": "OUTSIDE",
            "phase_estimator_sha256": bindings["phase_estimator"]["sha256"],
            "phase_epoch": "1",
            "phase_observation_sequence": "2394",
            "relative_phase_cycles": "4",
            "phase_continuous": "true",
            "phase_current": "true",
            "phase_step_detected": "false",
            "phase_recorder_published": "true",
            "current_applied_code": str(0xA83C),
            "dac_epoch": "1",
            "phase_applied_code": str(0xA83C),
            "phase_dac_epoch": "1",
            "state_before": "FREQUENCY_ACQUIRE",
            "state_after": "FREQUENCY_ACQUIRE",
            "frequency_term_hz": "-0.001666666940",
            "phase_term_hz": "0.000000000000",
            "combined_demand_hz": "-0.001666666940",
            "raw_combined_delta_codes": "0.000000000000",
            "requested_delta_codes": "0",
            "requested_code": str(0xA83C),
            "counterfactual_frequency_only_delta_codes": "0",
            "phase_materially_influenced": "false",
            "step_limited": "false",
            "range_clamped": "false",
            "cadence_limited": "true",
            "count_limited": "false",
            "cumulative_budget_limited": "false",
            "correction_count_before": "0",
            "cumulative_movement_before_codes": "0",
            "authority_state": "ARMED",
            "request_sequence": "0",
            "acceptance_sequence": "0",
            "application_sequence": "0",
            "response_class": "unavailable",
            "actual_applied_code": str(0xA83C),
            "actual_dac_epoch": "1",
            "downstream_epoch_exact": "true",
            "reason": "minimum_applied_cadence_hold",
            "active_policy_sha256": bundle["policy"]["policy_sha256"],
            "response_policy_sha256": bindings["response_policy"]["sha256"],
            "actionable": "false",
        }
    )
    return (
        ",".join(values[field] for field in ACTIVE_HYBRID_DECISION_V1_FIELDS)
        + "\r\n"
    ).encode()


def _post_abort_active_status_wire_fixture(*, generation: int) -> bytes:
    values = {key: "unavailable" for key in ACTIVE_STATUS_KEYS}
    values.update(
        {
            "enabled": "true",
            "state": "ABORTED",
            "reason": "device_abort_command_via_core0",
            "evidence_pending": "false",
            "evidence_phase": "evidence_clear",
            "fail_static": "true",
            "hybrid_state": "FAIL_STATIC",
            "hybrid_reason": "device_abort_command_via_core0",
            "evidence_request_sequence": "0",
            "confirmed_applied_code_known": "false",
            "confirmed_applied_code": "unavailable",
            "automatic_retry": "false",
            "automatic_restore": "false",
        }
    )
    records = [
        (SNAPSHOT_BEGIN_KEY, str(generation)),
        (SNAPSHOT_CONTRACT_KEY, ACTIVE_STATUS_SNAPSHOT_CONTRACT),
        *((key, values[key]) for key in ACTIVE_STATUS_KEYS),
        (SNAPSHOT_COMPLETE_KEY, str(generation)),
    ]
    return "".join(
        f"STS,1,{sequence},{sequence * 16000},rp2040_timer0,"
        f"cx317_active,{key},{value},INFO,0\r\n"
        for sequence, (key, value) in enumerate(records, start=1)
    ).encode()


def _binding_matches(binding: object) -> bool:
    if not isinstance(binding, dict):
        return False
    path = Path(str(binding.get("path", ""))).resolve()
    return (
        path.is_file()
        and binding.get("path") == str(path)
        and binding.get("sha256") == _sha256_file(path)
        and binding.get("size_bytes") == path.stat().st_size
    )


def _is_pseudo_terminal(device: str) -> bool:
    """Recognize the PTY slave namespaces used by Linux and macOS."""

    return device.startswith("/dev/pts/") or re.fullmatch(
        r"/dev/ttys[0-9]+", device
    ) is not None


def _create_rehearsal_run_manifest(
    *,
    run_dir: Path,
    bundle_path: Path,
    bundle: dict[str, Any],
    proposal_path: Path,
    proposal: dict[str, Any],
    device: str,
) -> Path:
    files = [dict(entry) for entry in default_csv_files()]
    value: dict[str, Any] = {
        "schema_version": 1,
        "compatibility_floor": "CX319_EVIDENCE_EPOCH_1",
        "template": False,
        "run_id": run_dir.name,
        "created_utc": _utc_now(),
        "started_at_utc": _utc_now(),
        "stage": LIVE_STAGE,
        "mode": MODE,
        "programme_id": PROGRAMME_ID,
        "run_identity": RUN_IDENTITY,
        "profile_identity": PROFILE_ID,
        "board": "pty_no_physical_hardware",
        "capture_mode": "real_capture_device_process_over_pty",
        "qualification_evidence": False,
        "physical_actions_performed": 0,
        "actionable": False,
        "actuation_authorized": False,
        "authority_effective": False,
        "bundle": {
            "path": str(bundle_path),
            "sha256": _sha256_file(bundle_path),
            "size_bytes": bundle_path.stat().st_size,
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "proposal": {
            "path": str(proposal_path),
            "sha256": _sha256_file(proposal_path),
            "size_bytes": proposal_path.stat().st_size,
            "proposal_sha256": proposal["proposal_sha256"],
        },
        "firmware": bundle["firmware"],
        "policy": bundle["policy"],
        "host": {
            "serial_device": device,
            "baud": 115200,
            "sole_serial_owner": True,
            "serial_owner_count": 1,
            "tool_bindings": bundle["host_tools"],
            "fifos": {
                "normal_command": "control/normal_commands.fifo",
                "emergency_abort": "control/emergency_abort.fifo",
                "host_abort": "control/host_abort.fifo",
            },
        },
        "cx320": {
            "profile_id": PROFILE_ID,
            "run_identity": RUN_IDENTITY,
            "setup": {"code": 0xA83C},
            "automatic_control": {
                "maximum_total_applications": 4,
                "maximum_step_codes": 21,
                "maximum_cumulative_movement_codes": 84,
                "minimum_applied_cadence_s": 1800,
                "minimum_code": 0xA800,
                "maximum_code": 0xAB00,
            },
            "qualification": {
                "qualified_duration_s": 43_200,
                "absolute_wall_clock_limit_s": 57_600,
                "no_extension": True,
            },
        },
        "domains": [
            {"name": "rp2040_timer0", "nominal_hz": 16_000_000},
            {"name": "h1_cx317_ocxo_10mhz", "nominal_hz": 10_000_000},
        ],
        "channels": [
            {
                "channel_id": 1,
                "role": "authoritative_pps_reference",
                "record_family": "raw_events_v1",
            },
            {
                "channel_id": 2,
                "role": "pps_gated_oscillator_count",
                "record_family": "count_observations_v1",
            },
            {
                "channel_id": 3,
                "role": "independent_external_event_not_authority",
                "record_family": "raw_events_v1",
            },
        ],
        "contracts": {
            entry["contract"]: 2 if entry["contract"] == "estimates_v2" else 1
            for entry in files
        },
        "files": files,
        "expected_artifacts": [
            "raw/serial.log",
            "reports/capture_device_state.json",
            "reports/cx317_active_supervisor_state.json",
            "reports/cx317_active_supervisor_events.jsonl",
        ],
        "evidence_artifacts": [
            "raw/serial.log",
            "reports/capture_device_state.json",
            "reports/cx317_active_supervisor_state.json",
            "reports/cx317_active_supervisor_events.jsonl",
        ],
    }
    value["manifest_sha256"] = _canonical_sha256(value)
    path = run_dir / "run_manifest.json"
    _atomic_new_json(path, value)
    return path


def validate_rehearsal_run_manifest(path: Path) -> dict[str, Any]:
    """Validate the only manifest accepted by supervisor rehearsal mode."""

    path = path.resolve()
    value = _read_object(path)
    unsigned = {
        key: item for key, item in value.items() if key != "manifest_sha256"
    }
    bundle_binding = value.get("bundle", {})
    proposal_binding = value.get("proposal", {})
    host = value.get("host", {})
    cx320 = value.get("cx320", {})
    if not isinstance(host, dict) or not isinstance(cx320, dict):
        raise ValueError("CX320 rehearsal manifest host/programme is malformed")
    bundle_path = Path(str(bundle_binding.get("path", ""))).resolve()
    proposal_path = Path(str(proposal_binding.get("path", ""))).resolve()
    bundle = validate_bundle(bundle_path)
    proposal = validate_proposal(proposal_path)
    device = str(host.get("serial_device", ""))
    if (
        path != path.parent / "run_manifest.json"
        or value.get("manifest_sha256") != _canonical_sha256(unsigned)
        or value.get("mode") != MODE
        or value.get("stage") != LIVE_STAGE
        or value.get("programme_id") != PROGRAMME_ID
        or value.get("run_identity") != RUN_IDENTITY
        or value.get("profile_identity") != PROFILE_ID
        or value.get("qualification_evidence") is not False
        or value.get("physical_actions_performed") != 0
        or value.get("actionable") is not False
        or value.get("actuation_authorized") is not False
        or value.get("authority_effective") is not False
        or not _is_pseudo_terminal(device)
        or host.get("serial_owner_count") != 1
        or host.get("sole_serial_owner") is not True
        or len(set(host.get("fifos", {}).values())) != 3
        or bundle_binding.get("sha256") != _sha256_file(bundle_path)
        or bundle_binding.get("size_bytes") != bundle_path.stat().st_size
        or bundle_binding.get("bundle_sha256") != bundle["bundle_sha256"]
        or proposal_binding.get("sha256") != _sha256_file(proposal_path)
        or proposal_binding.get("size_bytes") != proposal_path.stat().st_size
        or proposal_binding.get("proposal_sha256") != proposal["proposal_sha256"]
        or proposal["exact_bundle"]["bundle_sha256"] != bundle["bundle_sha256"]
        or value.get("firmware") != bundle["firmware"]
        or value.get("policy") != bundle["policy"]
        or host.get("tool_bindings") != bundle["host_tools"]
        or cx320.get("profile_id") != PROFILE_ID
        or cx320.get("run_identity") != RUN_IDENTITY
        or cx320.get("setup", {}).get("code") != 0xA83C
    ):
        raise ValueError("CX320 rehearsal manifest identity or no-I/O boundary differs")
    if not all(_binding_matches(item) for item in bundle["host_tools"].values()):
        raise ValueError("CX320 rehearsal current host-tool binding differs")
    return value


def _prewrite_boundary_supervisor(
    *,
    run_dir: Path,
    bundle_path: Path,
    bundle: dict[str, Any],
    proposal_path: Path,
    proposal: dict[str, Any],
) -> tuple[ActiveHybridLiveSupervisor, dict[tuple[str, str], str]]:
    run_dir.mkdir(parents=True)
    (run_dir / "csv").mkdir()
    manifest_path = _create_rehearsal_run_manifest(
        run_dir=run_dir,
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
        device="/dev/ttys999",
    )
    manifest = validate_rehearsal_run_manifest(manifest_path)
    spec, identities = load_active_hybrid_spec(manifest)
    supervisor = ActiveHybridLiveSupervisor(
        manifest=manifest,
        manifest_path=manifest_path,
        run_dir=run_dir,
        command_fifo=run_dir / "control/normal_commands.fifo",
        emergency_command_fifo=run_dir / "control/emergency_abort.fifo",
        abort_fifo=run_dir / "control/host_abort.fifo",
        spec=spec,
        identities=identities,
        expected_build_identity=str(bundle["firmware"]["build_identity"]),
        duration_s=None,
    )
    expected_identity = {
        "run_identity": spec.run_identity,
        "build_identity": supervisor.expected_build_identity,
        "profile_identity": spec.profile,
        **identities,
    }
    health = canonical_prewrite_fixture(
        expected_identity=expected_identity,
        planned_live_stimulus_code=spec.start_code,
    )
    health[("cx317_active", "query_nonce")] = str(
        supervisor.state["host_attach_query_nonce"]
    )
    health.update(
        {
            ("cx317_active", "hybrid_state"): "SETUP_PENDING",
            ("cx317_active", "hybrid_reason"): "setup_consumers_pending",
            ("cx317_active", "first_phase_checkpoint_passed"): "false",
            ("cx317_active", "phase_nonzero_application_count"): "0",
            ("cx317_active", "phase_material_application_count"): "0",
            ("cx317_active", "frequency_only_application_count"): "0",
        }
    )
    return supervisor, health


def _reduce_complete_active_health(
    health: dict[tuple[str, str], str], *, generation: int
) -> dict[tuple[str, str], str]:
    """Pass a complete fixture through the actual atomic live reducer."""

    reducer = ActiveStatusLiveReducer()
    sequence = 0

    def row(component: str, key: str, value: str) -> dict[str, str]:
        nonlocal sequence
        sequence += 1
        return {
            "record_type": "STS",
            "schema_version": "1",
            "status_seq": str(sequence),
            "timestamp_ticks": str(sequence * 16_000),
            "status_domain": "rp2040_timer0",
            "component": component,
            "status_key": key,
            "status_value": value,
            "severity": "INFO",
            "flags": "0",
        }

    for (component, key), value in sorted(health.items()):
        if component != "cx317_active":
            reducer.observe(row(component, key, value))
    latest = reducer.observe(
        row("cx317_active", SNAPSHOT_BEGIN_KEY, str(generation))
    )
    latest = reducer.observe(
        row(
            "cx317_active",
            SNAPSHOT_CONTRACT_KEY,
            ACTIVE_STATUS_SNAPSHOT_CONTRACT,
        )
    )
    for key in ACTIVE_STATUS_KEYS:
        latest = reducer.observe(
            row("cx317_active", key, health[("cx317_active", key)])
        )
    latest = reducer.observe(
        row("cx317_active", SNAPSHOT_COMPLETE_KEY, str(generation))
    )
    if latest is None or latest.get("state") != "complete":
        raise RuntimeError("CX320 atomic active-status rehearsal did not complete")
    return {
        (str(item["component"]), str(item["status_key"])): str(
            item["status_value"]
        )
        for item in latest["records"]  # type: ignore[index]
    }


def _exercise_prewrite_qualification_boundary(
    *,
    output_dir: Path,
    bundle_path: Path,
    bundle: dict[str, Any],
    proposal_path: Path,
    proposal: dict[str, Any],
) -> dict[str, Any]:
    """Accelerate the exact firmware-grounded setup-authority deadline."""

    waiting, waiting_health = _prewrite_boundary_supervisor(
        run_dir=output_dir / "qualification",
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
    )
    waiting_health[("cx317_active", "setup_reference_eligible")] = "false"
    waiting_health[("gnss_receiver", "raw_pps_control_eligible")] = "false"
    waiting_health[("gnss_receiver", "control_eligible")] = "false"
    waiting_health[("cx317_active", "uptime_s")] = "30"
    early = waiting._check_prewrite_contract(waiting_health, 30.0)

    qualified_health = dict(waiting_health)
    qualified_health[("cx317_active", "setup_reference_eligible")] = "true"
    qualified_health[("gnss_receiver", "raw_pps_control_eligible")] = "true"
    qualified_health[("gnss_receiver", "control_eligible")] = "true"
    qualified_health[("cx317_active", "uptime_s")] = "612"
    ready = waiting._check_prewrite_contract(qualified_health, 612.0)
    reduced_health = _reduce_complete_active_health(
        qualified_health, generation=612
    )
    waiting.state["manual_start_sent"] = True
    waiting._check_fail_static_health(reduced_health)

    deadline, deadline_health = _prewrite_boundary_supervisor(
        run_dir=output_dir / "deadline",
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
    )
    deadline_health[("cx317_active", "setup_reference_eligible")] = "false"
    deadline_health[("gnss_receiver", "raw_pps_control_eligible")] = "false"
    deadline_health[("gnss_receiver", "control_eligible")] = "false"
    deadline_health[("cx317_active", "uptime_s")] = str(
        RAW_PPS_QUALIFICATION_DEADLINE_S
    )
    deadline_rejected = False
    try:
        deadline._check_prewrite_contract(
            deadline_health, float(RAW_PPS_QUALIFICATION_DEADLINE_S)
        )
    except ValueError as exc:
        deadline_rejected = "setup_reference_eligible" in str(exc)

    result = {
        "startup_inhibit_s": 600,
        "observed_historical_qualification_s": 612,
        "qualification_deadline_s": RAW_PPS_QUALIFICATION_DEADLINE_S,
        "waits_while_unqualified_at_30s": early is not None and not early.ready,
        "ready_at_observed_612s": ready is not None and ready.ready,
        "atomic_handoff_hybrid_state": reduced_health.get(
            ("cx317_active", "hybrid_state")
        ),
        "first_post_setup_consumer_passed": True,
        "missing_authority_at_660s_is_terminal": deadline_rejected,
        "setup_commands_issued": 0,
        "physical_actions_performed": 0,
    }
    if not all(
        result[key]
        for key in (
            "waits_while_unqualified_at_30s",
            "ready_at_observed_612s",
            "first_post_setup_consumer_passed",
            "missing_authority_at_660s_is_terminal",
        )
    ):
        raise RuntimeError("CX320 accelerated prewrite boundary rehearsal failed")
    return result


def _exercise_qualified_device_time_boundaries(
    *,
    output_dir: Path,
    bundle_path: Path,
    bundle: dict[str, Any],
    proposal_path: Path,
    proposal: dict[str, Any],
) -> dict[str, Any]:
    """Prove scientific duration is owned by the qualifying device clock."""

    supervisor, health = _prewrite_boundary_supervisor(
        run_dir=output_dir / "qualified_device_clock",
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
    )
    origin_uptime_s = 4_000
    supervisor.state["qualification_started_utc"] = supervisor.envelope.wall_origin_utc
    supervisor.state["qualified_origin_estimate_id"] = (
        "est:cx317:selected600:device_clock_rehearsal"
    )
    supervisor.state["qualified_origin_timestamp_ticks"] = (
        origin_uptime_s * RP2040_TIMER0_TICKS_PER_SECOND
    )
    supervisor.state["qualified_origin_session_id"] = 1
    supervisor.state["manual_start_sent"] = True
    supervisor._save()
    health.update(
        {
            ("cx317_active", "state"): "DISARMED",
            ("cx317_active", "evidence_pending"): "false",
            ("cx317_active", "evidence_phase"): "evidence_clear",
            ("cx317_active", "evidence_request_sequence"): "0",
            ("cx317_active", "manual_start_confirmed"): "true",
            ("cx317_active", "confirmed_applied_code_known"): "true",
            ("cx317_active", "confirmed_applied_code"): "43068",
            ("cx317_active", "session_id"): "1",
            ("cx317_active", "hybrid_state"): "HYBRID_TRACKING",
            ("cx317_active", "first_phase_checkpoint_passed"): "true",
            ("cx317_active", "phase_nonzero_application_count"): "2",
            ("cx317_active", "phase_material_application_count"): "2",
            ("cx317_active", "correction_count"): "2",
            ("cx317_active", "cumulative_movement_codes"): "8",
        }
    )

    admission_elapsed_s = QUALIFIED_DURATION_S - CORRECTION_RESPONSE_RESERVE_S
    health[("cx317_active", "uptime_s")] = str(
        origin_uptime_s + admission_elapsed_s - 1
    )
    admission_open_before = not supervisor._close_response_horizon_if_required(
        health
    )
    health[("cx317_active", "uptime_s")] = str(
        origin_uptime_s + admission_elapsed_s
    )
    admission_closed_exact = supervisor._close_response_horizon_if_required(
        health
    )

    wall_origin_epoch = datetime.fromisoformat(
        supervisor.envelope.wall_origin_utc.replace("Z", "+00:00")
    ).timestamp()
    health[("cx317_active", "uptime_s")] = str(
        origin_uptime_s + QUALIFIED_DURATION_S - 1
    )
    supervisor._maybe_finish(health, wall_origin_epoch + 50_000, 0.0)
    endpoint_open_after_forward_utc_step = supervisor.state["terminal"] is None
    health[("cx317_active", "uptime_s")] = str(
        origin_uptime_s + QUALIFIED_DURATION_S
    )
    supervisor._maybe_finish(health, wall_origin_epoch - 1_000, 0.0)
    endpoint_closed_after_backward_utc_step = (
        (supervisor.state.get("terminal") or {}).get("reason")
        == "cx320_12h_qualified_endpoint_complete"
    )

    result = {
        "time_domain": "rp2040_timer0",
        "capture_session": 1,
        "correction_admission_close_elapsed_s": admission_elapsed_s,
        "qualified_endpoint_elapsed_s": QUALIFIED_DURATION_S,
        "admission_open_one_second_before": admission_open_before,
        "admission_closed_at_exact_boundary": admission_closed_exact,
        "forward_host_utc_step_did_not_close_early": (
            endpoint_open_after_forward_utc_step
        ),
        "backward_host_utc_step_did_not_delay_endpoint": (
            endpoint_closed_after_backward_utc_step
        ),
        "physical_actions_performed": 0,
    }
    if not all(
        result[key]
        for key in (
            "admission_open_one_second_before",
            "admission_closed_at_exact_boundary",
            "forward_host_utc_step_did_not_close_early",
            "backward_host_utc_step_did_not_delay_endpoint",
        )
    ):
        raise RuntimeError("CX320 qualified device-clock rehearsal failed")
    return result


def _run_real_process_topology(
    *,
    output_dir: Path,
    bundle_path: Path,
    bundle: dict[str, Any],
    proposal_path: Path,
    proposal: dict[str, Any],
) -> dict[str, Any]:
    run_dir = output_dir / "process_topology" / "run"
    transition_dir = output_dir / "process_topology" / "transition"
    carrier_dir = output_dir / "process_topology" / "carrier"
    run_dir.mkdir(parents=True)
    (run_dir / "reports").mkdir()
    master, slave = pty.openpty()
    device = os.ttyname(slave)
    os.close(slave)
    manifest_path = _create_rehearsal_run_manifest(
        run_dir=run_dir,
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
        device=device,
    )
    normal = run_dir / "control/normal_commands.fifo"
    emergency = run_dir / "control/emergency_abort.fifo"
    host_abort = run_dir / "control/host_abort.fifo"
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
            "120",
            "--status-interval",
            "1",
            "--command-fifo",
            str(normal),
            "--emergency-command-fifo",
            str(emergency),
            "--write-timeout-s",
            "1",
            "--normal-command-max-age-s",
            "2",
            "--segment-control-dir",
            str(carrier_dir),
            "--segment-capability",
            CAPABILITY,
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    supervisor: subprocess.Popen[str] | None = None
    capture_output = ""
    supervisor_output = ""
    capture_stopped = False
    supervisor_stopped = False
    normal_fifo_queued = 0
    normal_fifo_saturated = False
    try:
        _wait_until(
            lambda: (
                capture.poll() is None
                and normal.is_fifo()
                and emergency.is_fifo()
                and _capture_state_ready(run_dir, capture.pid)
            ),
            15.0,
            "real capture process and PTY carrier",
        )
        owners_before = _serial_owner_pids(device)
        if owners_before != {capture.pid}:
            raise RuntimeError(
                f"capture is not sole PTY owner: {sorted(owners_before)}"
            )
        supervisor = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "host.otis_tools.active_hybrid_live_supervisor",
                "--manifest",
                str(manifest_path),
                "--run-dir",
                str(run_dir),
                "--command-fifo",
                str(normal),
                "--emergency-command-fifo",
                str(emergency),
                "--abort-fifo",
                str(host_abort),
                "--expected-build-identity",
                str(bundle["firmware"]["build_identity"]),
                "--duration-s",
                "60",
                "--rehearsal-manifest",
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _wait_until(
            lambda: (
                supervisor.poll() is None
                and host_abort.exists()
                and stat.S_ISFIFO(host_abort.stat().st_mode)
            ),
            15.0,
            "real live supervisor and host-abort FIFO",
        )
        initial_commands = _read_until(master, b"ACTIVE LEASE 1\n")
        _wait_until(
            lambda: int(
                _read_object(run_dir / "reports/capture_device_state.json").get(
                    "commands_sent", 0
                )
            )
            >= 4,
            10.0,
            "initial live-supervisor command acknowledgements",
        )
        os.write(master, _active_hybrid_wire_fixture(bundle))
        _wait_until(
            lambda: len(
                (run_dir / "csv/active_hybrid_decisions_v1.csv")
                .read_text(encoding="utf-8")
                .splitlines()
            )
            == 2,
            10.0,
            "first exact 56-field active-hybrid wire record",
        )
        # Stop the producer only after its initial lease has reached the PTY,
        # then stop the consumer.  This avoids manufacturing a stale in-flight
        # command while constructing the deliberate normal-FIFO obstruction.
        os.kill(supervisor.pid, signal.SIGSTOP)
        supervisor_stopped = True
        os.kill(capture.pid, signal.SIGSTOP)
        capture_stopped = True
        for _ in range(100_000):
            try:
                send_timestamped_command_to_fifo(normal, "CONFIG?")
                normal_fifo_queued += 1
            except BlockingIOError:
                normal_fifo_saturated = True
                break
        if not normal_fifo_saturated:
            raise RuntimeError("CX320 rehearsal normal FIFO did not saturate")
        send_abort(host_abort)
        os.kill(supervisor.pid, signal.SIGCONT)
        supervisor_stopped = False
        supervisor.wait(timeout=5)
        os.kill(capture.pid, signal.SIGCONT)
        capture_stopped = False
        observed_commands = _read_until(master, b"ACTIVE ABORT\n")
        _wait_until(
            lambda: int(
                _read_object(run_dir / "reports/capture_device_state.json").get(
                    "emergency_aborts_sent", 0
                )
            )
            == 1,
            10.0,
            "priority abort delivery through sole owner",
        )
        os.write(master, _post_abort_active_status_wire_fixture(generation=1))
        supervisor_output, _ = supervisor.communicate(timeout=15)
        if supervisor.returncode != 3:
            raise RuntimeError(
                "live supervisor rehearsal did not reach independent-host-abort "
                f"terminal: exit={supervisor.returncode}; {supervisor_output[-2000:]}"
            )
        terminal_state = _read_object(
            run_dir / "reports/cx317_active_supervisor_state.json"
        )
        _wait_for_terminal_abort_delivery(run_dir, terminal_state["terminal"])
        prepare_transition(run_dir / "run_manifest.json", transition_dir)
        rotation = request_rotation(
            control_dir=carrier_dir,
            capability=CAPABILITY,
            to_run=transition_dir,
            mode="transition",
            operation_id="cx320-live-topology-rehearsal-rotation",
        )
        if rotation.get("serial_reopened") is not False:
            raise RuntimeError("CX320 rehearsal logical rotation reopened serial")
        owners_after = _serial_owner_pids(device)
        if owners_after != {capture.pid}:
            raise RuntimeError("CX320 rehearsal lost sole ownership after rotation")
    finally:
        if supervisor_stopped and supervisor is not None:
            os.kill(supervisor.pid, signal.SIGCONT)
        if capture_stopped:
            os.kill(capture.pid, signal.SIGCONT)
        if supervisor is not None and supervisor.poll() is None:
            supervisor.terminate()
            try:
                supervisor_output, _ = supervisor.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                supervisor.kill()
                supervisor_output, _ = supervisor.communicate(timeout=5)
        if capture.poll() is None:
            capture.send_signal(signal.SIGINT)
        try:
            capture_output, _ = capture.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            capture.kill()
            capture_output, _ = capture.communicate(timeout=5)
        os.close(master)
    if capture.returncode != 0:
        raise RuntimeError(
            f"capture process rehearsal failed: {capture_output[-4000:]}"
        )
    state = _read_object(run_dir / "reports/capture_device_state.json")
    terminal = _read_object(run_dir / "reports/cx317_active_supervisor_state.json")
    return {
        "capture_pid": capture.pid,
        "supervisor_pid": None if supervisor is None else supervisor.pid,
        "device": device,
        "owners_before": sorted(owners_before),
        "owners_after_rotation": sorted(owners_after),
        "observed_command_bytes_sha256": sha256(observed_commands).hexdigest(),
        "initial_command_bytes_sha256": sha256(initial_commands).hexdigest(),
        "config_query_observed": b"CONFIG?\n" in initial_commands,
        "normal_fifo_queued_before_saturation": normal_fifo_queued,
        "normal_fifo_saturated": normal_fifo_saturated,
        "priority_abort_observed": b"ACTIVE ABORT\n" in observed_commands,
        "capture_emergency_aborts_sent": state.get("emergency_aborts_sent"),
        "capture_parser_errors": state.get("parser_errors"),
        "first_active_hybrid_wire_field_count": len(
            ACTIVE_HYBRID_DECISION_V1_FIELDS
        ),
        "post_abort_complete_active_snapshot": True,
        "supervisor_terminal": terminal.get("terminal"),
        "rotation": rotation,
        "capture_output_sha256": sha256(capture_output.encode()).hexdigest(),
        "supervisor_output_sha256": sha256(supervisor_output.encode()).hexdigest(),
    }


def run(
    *, bundle_path: Path, proposal_path: Path, output_dir: Path
) -> dict[str, Any]:
    bundle_path = bundle_path.resolve()
    proposal_path = proposal_path.resolve()
    bundle = validate_bundle(bundle_path)
    proposal = validate_proposal(proposal_path)
    if proposal["exact_bundle"]["bundle_sha256"] != bundle["bundle_sha256"]:
        raise ValueError("CX320 rehearsal proposal and bundle differ")
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"CX320 live rehearsal output is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    accelerated = run_accelerated_rehearsal(
        bundle_path=bundle_path,
        proposal_path=proposal_path,
        output_dir=output_dir / "accelerated_boundaries",
    )
    topology = _run_real_process_topology(
        output_dir=output_dir,
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
    )
    prewrite_boundary = _exercise_prewrite_qualification_boundary(
        output_dir=output_dir / "prewrite_boundary",
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
    )
    qualified_device_clock = _exercise_qualified_device_time_boundaries(
        output_dir=output_dir / "qualified_device_clock",
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
    )
    coverage = {name: True for name in REHEARSAL_COVERAGE}
    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "report_type": REPORT_TYPE,
        "tool": TOOL_ID,
        "tool_sha256": _sha256_file(Path(__file__)),
        "created_utc": _utc_now(),
        "status": "passed",
        "bundle_sha256": bundle["bundle_sha256"],
        "proposal_sha256": proposal["proposal_sha256"],
        "physical_actions_performed": 0,
        "qualification_evidence": False,
        "coverage": coverage,
        "tool_bindings": bundle["host_tools"],
        "real_process_topology": topology,
        "accelerated_prewrite_boundary": prewrite_boundary,
        "accelerated_qualified_device_clock": qualified_device_clock,
        "accelerated_boundary_result": {
            "status": accelerated["status"],
            "seal_sha256": accelerated["seal_sha256"],
            "evidence_content_sha256": accelerated["evidence_content_sha256"],
            "registration_valid": accelerated["registration_valid"],
        },
        "coverage_provenance": {
            "real_process": [
                "capture_device_real_process",
                "pty_serial_carrier",
                "sole_serial_owner",
                "normal_command_fifo",
                "emergency_abort_fifo",
                "host_abort_fifo",
                "live_supervisor_process",
                "first_active_hybrid_wire_record",
                "terminal_abort_delivery_before_capture_close",
                "post_abort_complete_active_snapshot",
                "logical_evidence_rotation",
            ],
            "accelerated_deterministic": [
                "active_hybrid_status_handoff",
                "setup_authority_qualification_deadline",
                "qualified_device_time_boundaries",
                "setup_propagation",
                "progressive_checkpoint",
                "conditional_release",
                "response_classification",
                "phase_only_degradation",
                "shared_fail_static_fault",
                "transport_obstruction",
                "analysis_seal_registration",
            ],
        },
        "unexercised_physical_boundaries": [
            "RP2040 USB CDC and cross-core runtime",
            "AD5693R I2C write and CX317 plant response",
            "physical D14 PPS and D8 oscillator capture",
        ],
    }
    report = {
        **unsigned,
        "rehearsal_sha256": _canonical_sha256(unsigned),
    }
    _atomic_new_json(
        output_dir / "cx320_active_hybrid_live_topology_rehearsal_v1.json",
        report,
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run(
            bundle_path=args.bundle,
            proposal_path=args.proposal,
            output_dir=args.output_dir,
        )
    except (
        FileExistsError,
        FileNotFoundError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        TimeoutError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
