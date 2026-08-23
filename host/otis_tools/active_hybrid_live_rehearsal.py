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
import csv
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
import threading
import time
from types import SimpleNamespace
from typing import Any, Callable

from .abort_transport import send_abort
from .active_hybrid_bundle import validate_bundle
from .active_hybrid_live_supervisor import (
    ARM_LIFETIME_S,
    CORRECTION_RESPONSE_RESERVE_S,
    PLANT_SIGN_PREARM_MIN_ACCEPTED_INTERVALS,
    QUERY_PERIOD_S,
    RP2040_TIMER0_TICKS_PER_SECOND,
    ActiveHybridLiveSupervisor,
    load_active_hybrid_spec,
)
from .active_hybrid_run import _wait_for_terminal_abort_delivery
from .active_transactions import (
    _await_cx321_plant_sign_response,
    _join_cx321_psq_response_to_act,
)
from .active_hybrid_proposal import validate_proposal
from .active_hybrid_programme_contract import (
    ActiveHybridProgramme,
    CX320_PROGRAMME,
    programme_from_mapping,
)
from .active_hybrid_policy import ActiveHybridController, load_policy
from .active_hybrid_rehearsal import (
    _ahy_row,
    _observation,
    _transaction_rows,
    run as run_accelerated_rehearsal,
)
from .active_status_contract import (
    ACTIVE_STATUS_KEYS,
    ACTIVE_STATUS_SNAPSHOT_CONTRACT,
    CX321_ACTIVE_STATUS_KEYS,
    CX321_ACTIVE_STATUS_SNAPSHOT_CONTRACT,
    SUSTAINED_HYBRID_ACTIVE_STATUS_KEYS,
    SUSTAINED_HYBRID_ACTIVE_STATUS_SNAPSHOT_CONTRACT,
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
from .contracts import (
    ACTIVE_HYBRID_DECISION_V1_FIELDS,
    ACTIVE_TRANSACTION_V1_FIELDS,
    CONTRACT_FIELDS,
    PPS_SNAPSHOT_FIELDS,
)
from .cx321_plant_sign_evidence_guard import (
    PLANT_SIGN_QUALIFICATION_V1_FIELDS,
    PlantSignReplayContext,
    complete_plant_sign_evidence_chain,
    replay_plant_sign_evidence,
    replay_plant_sign_windows_against_snapshots,
)
from .run_paths import cx321_csv_files, default_csv_files
from .serial_commands import send_timestamped_command_to_fifo
from .time_domains import RP2040_TIMER0_MICROS_WRAP_TICKS


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


def _active_status_generation_complete(
    run_dir: Path, expected_generation: int
) -> bool:
    path = run_dir / "reports/cx317_active_status_live_state_v1.json"
    if not path.is_file() or expected_generation <= 0:
        return False
    value = _read_object(path)
    return (
        value.get("state") == "complete"
        and value.get("generation") == expected_generation
        and value.get("newest_started_generation") == expected_generation
        and value.get("newest_complete_generation") == expected_generation
    )


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


def _selected_programme(
    value: dict[str, Any],
) -> ActiveHybridProgramme:
    """Select a frozen programme, retaining CX320 fixture compatibility."""

    try:
        return programme_from_mapping(value)
    except ValueError:
        return CX320_PROGRAMME


def _active_hybrid_wire_fixture(bundle: dict[str, Any]) -> bytes:
    programme = _selected_programme(bundle)
    active_binding = (
        bundle["programme_policy"]
        if programme.identification_required
        else bundle["policy"]
    )
    policy = _read_object(Path(str(active_binding["path"])))
    bindings = policy["bindings"]
    frequency_binding = (
        "natural_frequency_estimator"
        if programme.identification_required
        else "frequency_estimator"
    )
    response_binding = (
        "natural_response_classifier"
        if programme.identification_required
        else "response_policy"
    )
    values = {field: "0" for field in ACTIVE_HYBRID_DECISION_V1_FIELDS}
    values.update(
        {
            "record_type": "AHY",
            "schema_version": "1",
            "hybrid_record_sequence": "1",
            "decision_sequence": "1",
            "decision_timestamp_s": "2401",
            "run_identity": programme.runtime_run_identity,
            "build_identity": str(bundle["firmware"]["build_identity"]),
            "profile_identity": programme.profile_id,
            "capture_session": "1",
            "source_first_sequence": "1799",
            "source_last_sequence": "2399",
            "frequency_estimator_sha256": bindings[frequency_binding][
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
            "active_policy_sha256": (
                active_binding["sha256"]
                if programme.identification_required
                else active_binding["policy_sha256"]
            ),
            "response_policy_sha256": bindings[response_binding]["sha256"],
            "actionable": "false",
        }
    )
    return (
        ",".join(values[field] for field in ACTIVE_HYBRID_DECISION_V1_FIELDS)
        + "\r\n"
    ).encode()


def _post_abort_active_status_wire_fixture(
    *,
    generation: int,
    bundle: dict[str, Any] | None = None,
    applied_code: int | None = None,
    dac_epoch: int | None = None,
    correction_count: int | None = None,
    cumulative_movement_codes: int | None = None,
) -> bytes:
    programme = _selected_programme(bundle or {})
    if programme.identification_required:
        keys = CX321_ACTIVE_STATUS_KEYS
        contract = CX321_ACTIVE_STATUS_SNAPSHOT_CONTRACT
    elif programme.sustained_regulation:
        keys = SUSTAINED_HYBRID_ACTIVE_STATUS_KEYS
        contract = SUSTAINED_HYBRID_ACTIVE_STATUS_SNAPSHOT_CONTRACT
    else:
        keys = ACTIVE_STATUS_KEYS
        contract = ACTIVE_STATUS_SNAPSHOT_CONTRACT
    values = {key: "unavailable" for key in keys}
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
    if programme.identification_required and bundle is not None:
        bindings = bundle["identification"]["bindings"]
        applied_code = (
            programme.setup_code - 21 if applied_code is None else applied_code
        )
        dac_epoch = 2 if dac_epoch is None else dac_epoch
        correction_count = 1 if correction_count is None else correction_count
        cumulative_movement_codes = (
            21
            if cumulative_movement_codes is None
            else cumulative_movement_codes
        )
        values.update(
            {
                "plant_sign_state": "FAIL_STATIC",
                "plant_sign_pre_window_count": "1",
                "plant_sign_accumulator_accepted_intervals": "1400",
                "plant_sign_arm_window_eligible": "false",
                "plant_sign_gate_sha256": bindings["plant_sign_gate"]["sha256"],
                "identification_estimator_sha256": bindings[
                    "identification_estimator"
                ]["sha256"],
                "identification_estimator_config_sha256": bundle[
                    "identification"
                ]["estimator_runtime_config"]["sha256"],
                "natural_frequency_estimator_sha256": bindings[
                    "natural_frequency_estimator"
                ]["sha256"],
            }
        )
    if applied_code is not None:
        values.update(
            {
                "confirmed_applied_code_known": "true",
                "confirmed_applied_code": str(applied_code),
            }
        )
    if correction_count is not None:
        values["correction_count"] = str(correction_count)
    if cumulative_movement_codes is not None:
        values["cumulative_movement_codes"] = str(cumulative_movement_codes)
    if dac_epoch is not None:
        values["dac_epoch"] = str(dac_epoch)
    records = [
        (SNAPSHOT_BEGIN_KEY, str(generation)),
        (SNAPSHOT_CONTRACT_KEY, contract),
        *((key, values[key]) for key in keys),
        (SNAPSHOT_COMPLETE_KEY, str(generation)),
    ]
    return "".join(
        f"STS,1,{sequence},{sequence * 16000},rp2040_timer0,"
        f"cx317_active,{key},{value},INFO,0\r\n"
        for sequence, (key, value) in enumerate(records, start=1)
    ).encode()


def _wire_rows(rows: list[dict[str, str]], fields: tuple[str, ...] | list[str]) -> bytes:
    return "".join(
        ",".join(row[field] for field in fields) + "\r\n" for row in rows
    ).encode()


def _write_all_fd(descriptor: int, payload: bytes) -> None:
    """Write one complete PTY fixture without assuming full ``os.write``."""

    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short zero-byte PTY write")
        view = view[written:]


def _cx321_plant_sign_fixture(
    bundle: dict[str, Any],
) -> tuple[
    PlantSignReplayContext,
    list[dict[str, str]],
    list[dict[str, str]],
]:
    """Return an exact response prefix and its canonical raw SNP support."""

    programme = _selected_programme(bundle)
    bindings = bundle["identification"]["bindings"]
    context = PlantSignReplayContext(
        run_identity=programme.runtime_run_identity,
        build_identity=str(bundle["firmware"]["build_identity"]),
        profile_identity=programme.profile_id,
        policy_sha256=str(bundle["programme_policy"]["sha256"]),
        plant_sign_gate_sha256=str(bindings["plant_sign_gate"]["sha256"]),
        identification_estimator_sha256=str(
            bindings["identification_estimator"]["sha256"]
        ),
        identification_estimator_config_sha256=str(
            bundle["identification"]["estimator_runtime_config"]["sha256"]
        ),
        natural_frequency_estimator_sha256=str(
            bindings["natural_frequency_estimator"]["sha256"]
        ),
        capture_session=1,
    )

    def base(sequence: int, event: str) -> dict[str, str]:
        row = {field: "" for field in PLANT_SIGN_QUALIFICATION_V1_FIELDS}
        row.update(
            {
                "record_type": "PSQ",
                "schema_version": "1",
                "qualification_record_sequence": str(sequence),
                "event": event,
                "event_timestamp_ticks": "0",
                "run_identity": context.run_identity,
                "build_identity": context.build_identity,
                "profile_identity": context.profile_identity,
                "capture_session": str(context.capture_session),
                "policy_sha256": context.policy_sha256,
                "plant_sign_gate_sha256": context.plant_sign_gate_sha256,
                "identification_estimator_sha256": (
                    context.identification_estimator_sha256
                ),
                "identification_estimator_config_sha256": (
                    context.identification_estimator_config_sha256
                ),
                "natural_frequency_estimator_sha256": (
                    context.natural_frequency_estimator_sha256
                ),
                "setup_application_sequence": "1",
                "setup_application_timestamp_ticks": str(context.timer_hz),
                "setup_applied_code": str(context.setup_code),
                "setup_dac_epoch": "1",
                "state_before": "PLANT_SIGN_QUALIFY",
                "state_after": "PLANT_SIGN_QUALIFY",
                "reason": event,
                "actionable": "false",
            }
        )
        return row

    def window(
        row: dict[str, str], *, first: int, opened_s: int, total: int, epoch: int
    ) -> None:
        close_s = opened_s + 1500
        row.update(
            {
                "event_timestamp_ticks": str(close_s * context.timer_hz),
                "total_count": str(total),
                "signed_error_counts": str(
                    total - context.nominal_frequency_hz * 1500
                ),
                "open_ticks": str(opened_s * context.timer_hz),
                "close_ticks": str(close_s * context.timer_hz),
                "source_first_sequence": str(first),
                "source_last_sequence": str(first + 1500),
                "accepted_intervals": "1500",
                "dac_epoch": str(epoch),
                "tight_state": "TIGHT_INSIDE",
            }
        )

    pre1 = base(1, "pre1")
    window(pre1, first=901, opened_s=901, total=15_000_000_002, epoch=1)
    pre1.update(
        {
            "state_before": "FREQUENCY_ACQUIRE",
            "state_after": "FREQUENCY_ACQUIRE",
            "reason": "first_pre_identification_window_accepted",
        }
    )
    pre2 = base(2, "pre2")
    window(pre2, first=2401, opened_s=2401, total=15_000_000_002, epoch=1)
    pre2.update(
        {
            "state_before": "FREQUENCY_ACQUIRE",
            "state_after": "PLANT_SIGN_QUALIFY",
            "reason": "identification_request_ready",
        }
    )
    request = base(3, "request")
    request.update(
        {
            "event_timestamp_ticks": pre2["close_ticks"],
            "pre_error_counts": "2",
            "current_code": str(context.setup_code),
            "request_sequence": "1",
            "requested_delta_codes": "-21",
            "requested_code": str(context.setup_code - 21),
            "reason": "identification_request_created",
        }
    )
    application = base(4, "application")
    application.update(
        {
            "event_timestamp_ticks": str(3902 * context.timer_hz),
            "request_sequence": "1",
            "acceptance_sequence": "1",
            "application_sequence": "1",
            "requested_delta_codes": "-21",
            "requested_code": str(context.setup_code - 21),
            "accepted_code": str(context.setup_code - 21),
            "applied_code": str(context.setup_code - 21),
            "application_timestamp_ticks": str(3902 * context.timer_hz),
            "dac_epoch": "2",
            "reason": "identification_applied_response_pending",
        }
    )
    response = base(5, "response")
    window(
        response,
        first=4802,
        opened_s=4802,
        total=14_999_999_997,
        epoch=2,
    )
    for key in (
        "request_sequence",
        "acceptance_sequence",
        "application_sequence",
        "requested_delta_codes",
        "requested_code",
        "accepted_code",
        "applied_code",
        "application_timestamp_ticks",
    ):
        response[key] = application[key]
    response.update(
        {
            "pre_total_count": "15000000002",
            "post_total_count": "14999999997",
            "response_counts": "-5",
            "response_source_last_sequence": response["source_last_sequence"],
            "sign_pass": "true",
            "magnitude_pass": "true",
            "exact_evidence_pass": "true",
            "tight_reentry_pass": "true",
            "passed": "true",
            "state_after": "PLANT_SIGN_RESPONSE_ACK_PENDING",
            "reason": "identification_response_exact_ack_pending",
            "event_timestamp_ticks": response["close_ticks"],
        }
    )
    prefix = [pre1, pre2, request, application, response]

    snapshots: dict[int, dict[str, str]] = {}
    next_origin = 3_000_000_000
    for record in (pre1, pre2, response):
        first = int(record["source_first_sequence"])
        last = int(record["source_last_sequence"])
        opened = int(record["open_ticks"])
        total = int(record["total_count"])
        if first in snapshots:
            counter = int(snapshots[first]["cumulative_down_counter"])
        else:
            counter = next_origin
            next_origin = (next_origin - 700_000_000) & 0xFFFFFFFF
            snapshots[first] = {
                "record_type": "SNP",
                "schema_version": "1",
                "session": "1",
                "snapshot_sequence": str(first),
                "cumulative_down_counter": str(counter),
                "reference_sequence": str(first),
                "reference_timestamp_ticks": str(
                    opened % RP2040_TIMER0_MICROS_WRAP_TICKS
                ),
                "status": "0",
                "backend": "pio_wait_cumulative_snapshot_dma_v1",
            }
        first_interval = total - 1499 * 10_000_000
        for offset, sequence in enumerate(range(first + 1, last + 1), 1):
            count = first_interval if offset == 1 else 10_000_000
            counter = (counter - count) & 0xFFFFFFFF
            item = {
                "record_type": "SNP",
                "schema_version": "1",
                "session": "1",
                "snapshot_sequence": str(sequence),
                "cumulative_down_counter": str(counter),
                "reference_sequence": str(sequence),
                "reference_timestamp_ticks": str(
                    (opened + offset * context.timer_hz)
                    % RP2040_TIMER0_MICROS_WRAP_TICKS
                ),
                "status": "0",
                "backend": "pio_wait_cumulative_snapshot_dma_v1",
            }
            existing = snapshots.get(sequence)
            if existing is not None and existing != item:
                raise RuntimeError("CX321 SNP fixture shared boundary differs")
            snapshots[sequence] = item
    return context, prefix, [snapshots[key] for key in sorted(snapshots)]


def _cx321_transaction_fixture(
    manifest: dict[str, Any],
) -> list[dict[str, str]]:
    """Return one canonical dual-core identification ACT lifecycle."""

    from .active_hybrid_rehearsal import _transaction_rows

    spec, identities = load_active_hybrid_spec(manifest)
    decision = SimpleNamespace(
        decision_sequence=1,
        source_first_sequence=2401,
        source_last_sequence=3901,
        timestamp_s=3901,
        current_applied_code=spec.start_code,
        requested_delta_codes=-21,
        requested_code=spec.start_code - 21,
        frequency_error_hz=2.0 / 1500.0,
    )
    phases = _transaction_rows(
        decision,
        record_sequence=2,
        request_sequence=1,
        application_sequence=1,
        dac_epoch=2,
        cumulative_movement=21,
        run_identity=spec.run_identity,
        build_identity=str(manifest["firmware"]["build_identity"]),
        policy_sha256=identities["active_policy_sha256"],
        estimator_sha256=identities["estimator_sha256"],
        model_sha256=identities["model_sha256"],
        response_policy_sha256=identities["response_policy_sha256"],
        numerical_policy_sha256=identities["numerical_policy_sha256"],
        profile_identity=spec.profile,
    )
    # ACT carries Core 1's later acknowledgement-consumption second.  The PSQ
    # fixture's exact Core 0 tick is 3902 s, deliberately exercising a legal
    # cross-second join against this 3903 s ACT value.
    manual = dict(phases[0])
    manual.update(
        {
            "transaction_record_sequence": "1",
            "event": "manual_start",
            "authorization_sequence": "0",
            "nonce": "0",
            "request_sequence": "0",
            "decision_sequence": "0",
            "source_first_sequence": "0",
            "source_last_sequence": "0",
            "decision_timestamp_s": "1",
            "current_applied_code": str(spec.start_code),
            "requested_delta_codes": "0",
            "requested_code": str(spec.start_code),
            "correction_ordinal": "0",
            "cumulative_after_codes": "0",
            "pre_error_hz": "0.000000000000",
            "accepted_code": str(spec.start_code),
            "accepted_timestamp_s": "1",
            "applied_code": str(spec.start_code),
            "application_sequence": "0",
            "application_timestamp_s": "1",
            "i2c_ok": "true",
            "clamped": "false",
            "ambiguous": "false",
            "dac_epoch": "1",
            "estimator_history_reset": "false",
            "correction_count": "0",
            "cumulative_movement_codes": "0",
            "post_error_hz": "0.000000000000",
            "observed_response_hz": "0.000000000000",
            "cumulative_response_hz": "0.000000000000",
            "consecutive_indeterminate": "0",
            "active_state": "DISARMED",
            "response_class": "unavailable",
            "reason": "manual_start_established",
            "evidence_state": "evidence_clear",
        }
    )
    return [manual, *phases]


def _cx321_first_natural_transaction_fixture(
    bundle: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    """Build the first natural decision from the exact CX321 handoff state."""

    programme = _selected_programme(bundle)
    policy = load_policy(Path(str(bundle["policy"]["path"])))
    controller = ActiveHybridController(policy, setup_application_s=1)
    identification_application_s = 3902
    qualification_started_s = 6304
    first_natural_decision_s = 8402
    controller.rebase_after_plant_sign(
        applied_code=programme.setup_code - 21,
        dac_epoch=2,
        application_s=identification_application_s,
        qualification_started_s=qualification_started_s,
        attestation_id="psq:1:5:complete-chain",
    )
    # The identification transaction consumed decision/request identity 1.
    # The first natural decision is therefore the next global decision.
    controller.decision_sequence = 1
    decision = controller.decide(
        _observation(
            controller,
            timestamp_s=first_natural_decision_s,
            sequence=first_natural_decision_s,
            frequency_error_hz=0.0,
            counts=0,
            tight_state="TIGHT_INSIDE",
            relative_phase_cycles=-24,
        )
    )
    if not (
        decision.plant_sign_handoff_first_consumer
        and decision.correction_count_before == 1
        and decision.cumulative_movement_before_codes == 21
        and decision.natural_chatter_origin_code == programme.setup_code - 21
        and decision.natural_cumulative_movement_codes == 0
        and decision.natural_direction_count == 0
        and decision.phase_materially_influenced
        and decision.requested_delta_codes != 0
    ):
        raise RuntimeError("CX321 first natural decision did not consume exact handoff")
    ahy = _ahy_row(
        decision,
        record_sequence=1,
        run_identity=programme.runtime_run_identity,
        build_identity=str(bundle["firmware"]["build_identity"]),
        policy_sha256=str(bundle["programme_policy"]["sha256"]),
        response_policy_sha256=policy.response_policy_sha256,
        profile_identity=programme.profile_id,
    )
    ahy.update(
        {
            "authority_state": "ARMED",
            "request_sequence": "2",
            "acceptance_sequence": "2",
            "application_sequence": "2",
        }
    )
    controller.note_application(
        decision,
        applied_code=decision.requested_code,
        dac_epoch=3,
        downstream_consumers_exact=True,
    )
    transactions = _transaction_rows(
        decision,
        record_sequence=6,
        request_sequence=2,
        application_sequence=2,
        dac_epoch=3,
        cumulative_movement=controller.cumulative_movement_codes,
        run_identity=programme.runtime_run_identity,
        build_identity=str(bundle["firmware"]["build_identity"]),
        policy_sha256=str(bundle["programme_policy"]["sha256"]),
        estimator_sha256=policy.frequency_estimator_sha256,
        model_sha256=policy.plant_model_sha256,
        response_policy_sha256=policy.response_policy_sha256,
        numerical_policy_sha256=policy.policy_sha256,
        profile_identity=programme.profile_id,
    )
    response = transactions[-1]
    response_decision = controller.decide(
        _observation(
            controller,
            timestamp_s=int(transactions[2]["application_timestamp_s"]) + 1500,
            sequence=int(transactions[2]["application_timestamp_s"]) + 1500,
            frequency_error_hz=float(response["post_error_hz"]),
            counts=round(float(response["post_error_hz"]) * 600),
            tight_state="TIGHT_INSIDE",
            relative_phase_cycles=-24,
            outstanding_response=True,
        )
    )
    response_ahy = _ahy_row(
        response_decision,
        record_sequence=2,
        run_identity=programme.runtime_run_identity,
        build_identity=str(bundle["firmware"]["build_identity"]),
        policy_sha256=str(bundle["programme_policy"]["sha256"]),
        response_policy_sha256=policy.response_policy_sha256,
        profile_identity=programme.profile_id,
    )
    response_ahy.update(
        {
            "authority_state": "AWAITING_RESPONSE",
            "request_sequence": "2",
            "acceptance_sequence": "2",
            "application_sequence": "2",
        }
    )
    return [ahy, response_ahy], transactions, {
        "request_sequence": 2,
        "decision_timestamp_s": decision.timestamp_s,
        "identification_application_timestamp_s": identification_application_s,
        "requested_delta_codes": decision.requested_delta_codes,
        "requested_code": decision.requested_code,
        "applied_dac_epoch": 3,
        "global_correction_count_before": decision.correction_count_before,
        "global_cumulative_movement_before_codes": (
            decision.cumulative_movement_before_codes
        ),
        "natural_chatter_origin_code": decision.natural_chatter_origin_code,
        "natural_cumulative_movement_codes": (
            decision.natural_cumulative_movement_codes
        ),
        "natural_direction_count": decision.natural_direction_count,
        "plant_sign_handoff_first_consumer": (
            decision.plant_sign_handoff_first_consumer
        ),
        "phase_materially_influenced": decision.phase_materially_influenced,
    }


def _cx322_first_observational_transaction_fixture(
    bundle: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    """Build one exact first-phase observation and its later-authority release.

    The response lands inside the retained response deadband.  CX320 would
    treat that response as an endpoint; CX322 must retain it as a non-terminal
    observation, acknowledge the exact durable evidence, and release later
    authority only after the following fresh TIGHT estimate.
    """

    programme = _selected_programme(bundle)
    if not programme.response_checkpoint_observational:
        raise ValueError("CX322 observational transaction fixture selected elsewhere")
    policy = load_policy(Path(str(bundle["policy"]["path"])))
    controller = ActiveHybridController(policy, setup_application_s=1)
    ahy: list[dict[str, str]] = []
    decision = None
    for timestamp_s, relative_phase_cycles in (
        (600, 0),
        (1200, 0),
        (1800, 0),
        (2400, 36),
    ):
        decision = controller.decide(
            _observation(
                controller,
                timestamp_s=timestamp_s,
                sequence=timestamp_s,
                frequency_error_hz=0.0,
                counts=0,
                tight_state="TIGHT_INSIDE",
                relative_phase_cycles=relative_phase_cycles,
            )
        )
        ahy.append(
            _ahy_row(
                decision,
                record_sequence=len(ahy) + 1,
                run_identity=programme.runtime_run_identity,
                build_identity=str(bundle["firmware"]["build_identity"]),
                policy_sha256=str(bundle["policy"]["policy_sha256"]),
                response_policy_sha256=policy.response_policy_sha256,
                profile_identity=programme.profile_id,
            )
        )
    if decision is None or not (
        decision.phase_materially_influenced
        and decision.requested_delta_codes != 0
    ):
        raise RuntimeError("CX322 fixture did not reach a first material request")

    controller.note_application(
        decision,
        applied_code=decision.requested_code,
        dac_epoch=2,
        downstream_consumers_exact=True,
    )
    transactions = _transaction_rows(
        decision,
        record_sequence=2,
        request_sequence=1,
        application_sequence=1,
        dac_epoch=2,
        cumulative_movement=abs(decision.requested_delta_codes),
        run_identity=programme.runtime_run_identity,
        build_identity=str(bundle["firmware"]["build_identity"]),
        policy_sha256=str(bundle["policy"]["policy_sha256"]),
        estimator_sha256=policy.frequency_estimator_sha256,
        model_sha256=policy.plant_model_sha256,
        response_policy_sha256=policy.response_policy_sha256,
        numerical_policy_sha256=policy.policy_sha256,
        profile_identity=programme.profile_id,
    )
    first = transactions[0]
    manual = dict(first)
    manual.update(
        {
            "transaction_record_sequence": "1",
            "event": "manual_start",
            "authorization_sequence": "0",
            "nonce": "0",
            "request_sequence": "0",
            "decision_sequence": "0",
            "source_first_sequence": "0",
            "source_last_sequence": "0",
            "decision_timestamp_s": "1",
            "current_applied_code": str(programme.setup_code),
            "requested_delta_codes": "0",
            "requested_code": str(programme.setup_code),
            "correction_ordinal": "0",
            "cumulative_after_codes": "0",
            "pre_error_hz": "0.000000000000",
            "accepted_code": str(programme.setup_code),
            "accepted_timestamp_s": "1",
            "applied_code": str(programme.setup_code),
            "application_sequence": "0",
            "application_timestamp_s": "1",
            "i2c_ok": "true",
            "clamped": "false",
            "ambiguous": "false",
            "dac_epoch": "1",
            "estimator_history_reset": "false",
            "correction_count": "0",
            "cumulative_movement_codes": "0",
            "post_error_hz": "0.000000000000",
            "observed_response_hz": "0.000000000000",
            "cumulative_response_hz": "0.000000000000",
            "consecutive_indeterminate": "0",
            "active_state": "DISARMED",
            "response_class": "unavailable",
            "reason": "manual_start_established",
            "evidence_state": "evidence_clear",
        }
    )

    response = transactions[-1]
    if response["response_class"] != "inside_deadband":
        raise RuntimeError("CX322 fixture response did not exercise endpoint retention")
    response_timestamp_s = int(transactions[2]["application_timestamp_s"]) + (
        policy.settling_exclusion_s + policy.fresh_support_s
    )
    response_decision = controller.decide(
        _observation(
            controller,
            timestamp_s=response_timestamp_s,
            sequence=response_timestamp_s,
            frequency_error_hz=float(response["post_error_hz"]),
            counts=round(float(response["post_error_hz"]) * 600),
            tight_state="TIGHT_INSIDE",
            relative_phase_cycles=36,
            outstanding_response=True,
        )
    )
    response_ahy = _ahy_row(
        response_decision,
        record_sequence=len(ahy) + 1,
        run_identity=programme.runtime_run_identity,
        build_identity=str(bundle["firmware"]["build_identity"]),
        policy_sha256=str(bundle["policy"]["policy_sha256"]),
        response_policy_sha256=policy.response_policy_sha256,
        profile_identity=programme.profile_id,
    )
    response_ahy.update(
        {
            "authority_state": "AWAITING_RESPONSE",
            "request_sequence": "1",
            "acceptance_sequence": "1",
            "application_sequence": "1",
        }
    )
    ahy.append(response_ahy)
    controller.note_response(
        classification=response["response_class"],
        predicted_sign_observed=True,
        exact_replay=True,
        support_fresh=True,
        applied_epoch_exact=True,
    )
    release = controller.decide(
        _observation(
            controller,
            timestamp_s=response_timestamp_s + 600,
            sequence=response_timestamp_s + 600,
            frequency_error_hz=float(response["post_error_hz"]),
            counts=round(float(response["post_error_hz"]) * 600),
            tight_state="TIGHT_INSIDE",
            relative_phase_cycles=36,
        )
    )
    if not (
        release.state_after == "HYBRID_TRACKING"
        and release.reason
        == "first_phase_observation_recorded_and_tight_reacquired"
        and release.requested_delta_codes == 0
    ):
        raise RuntimeError("CX322 fixture did not release later authority exactly")
    ahy.append(
        _ahy_row(
            release,
            record_sequence=len(ahy) + 1,
            run_identity=programme.runtime_run_identity,
            build_identity=str(bundle["firmware"]["build_identity"]),
            policy_sha256=str(bundle["policy"]["policy_sha256"]),
            response_policy_sha256=policy.response_policy_sha256,
            profile_identity=programme.profile_id,
        )
    )
    return ahy, [manual, *transactions], {
        "request_sequence": 1,
        "requested_delta_codes": decision.requested_delta_codes,
        "requested_code": decision.requested_code,
        "applied_dac_epoch": 2,
        "response_class": response["response_class"],
        "later_authority_release_reason": release.reason,
    }


def _sustained_multi_transaction_fixture(
    bundle: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    """Exercise natural repetition, challenge, recovery, and first consumers.

    This is deliberately a progressive sequence rather than a set of isolated
    component examples.  Each application is followed by its response record,
    response-bearing controller decision, acknowledgement consumption, and the
    first subsequent decision that depends on that acknowledgement.
    """

    programme = _selected_programme(bundle)
    if not programme.sustained_regulation:
        raise ValueError("sustained transaction fixture selected elsewhere")
    policy = load_policy(Path(str(bundle["policy"]["path"])))
    controller = ActiveHybridController(policy, setup_application_s=1)
    ahy: list[dict[str, str]] = []
    transactions: list[dict[str, str]] = []
    applications: list[dict[str, Any]] = []
    dependent_response: dict[str, str] | None = None

    def append_decision(decision: Any, *, request_sequence: int = 0) -> None:
        nonlocal dependent_response
        row = _ahy_row(
            decision,
            record_sequence=len(ahy) + 1,
            run_identity=programme.runtime_run_identity,
            build_identity=str(bundle["firmware"]["build_identity"]),
            policy_sha256=str(bundle["policy"]["policy_sha256"]),
            response_policy_sha256=policy.response_policy_sha256,
            profile_identity=programme.profile_id,
        )
        if dependent_response is not None:
            row.update(
                {
                    "request_sequence": dependent_response["request_sequence"],
                    "acceptance_sequence": dependent_response[
                        "request_sequence"
                    ],
                    "application_sequence": dependent_response[
                        "application_sequence"
                    ],
                    "response_class": dependent_response["response_class"],
                    "actual_applied_code": dependent_response["applied_code"],
                    "actual_dac_epoch": dependent_response["dac_epoch"],
                    "downstream_epoch_exact": "true",
                }
            )
            dependent_response = None
        elif request_sequence:
            row.update(
                {
                    "authority_state": "ARMED",
                    "request_sequence": str(request_sequence),
                    "acceptance_sequence": str(request_sequence),
                    "application_sequence": str(request_sequence),
                }
            )
        ahy.append(row)

    def observe(timestamp_s: int, phase_cycles: int, *, response: bool = False):
        return controller.decide(
            _observation(
                controller,
                timestamp_s=timestamp_s,
                sequence=timestamp_s,
                frequency_error_hz=0.0,
                counts=0,
                tight_state="TIGHT_INSIDE",
                relative_phase_cycles=phase_cycles,
                outstanding_response=response,
            )
        )

    def append_response_boundary(
        decision: Any, response: dict[str, str]
    ) -> None:
        append_decision(decision)
        ahy[-1].update(
            {
                "authority_state": "AWAITING_RESPONSE",
                "request_sequence": response["request_sequence"],
                "acceptance_sequence": response["request_sequence"],
                "application_sequence": response["application_sequence"],
            }
        )

    def transact(decision: Any, *, request_sequence: int) -> dict[str, str]:
        append_decision(decision, request_sequence=request_sequence)
        controller.note_application(
            decision,
            applied_code=decision.requested_code,
            dac_epoch=controller.dac_epoch + 1,
            downstream_consumers_exact=True,
        )
        rows = _transaction_rows(
            decision,
            record_sequence=2 + len(transactions),
            request_sequence=request_sequence,
            application_sequence=request_sequence,
            dac_epoch=controller.dac_epoch,
            cumulative_movement=controller.cumulative_movement_codes,
            run_identity=programme.runtime_run_identity,
            build_identity=str(bundle["firmware"]["build_identity"]),
            policy_sha256=str(bundle["policy"]["policy_sha256"]),
            estimator_sha256=policy.frequency_estimator_sha256,
            model_sha256=policy.plant_model_sha256,
            response_policy_sha256=policy.response_policy_sha256,
            numerical_policy_sha256=policy.policy_sha256,
            profile_identity=programme.profile_id,
        )
        transactions.extend(rows)
        application = {
            "request_sequence": request_sequence,
            "decision_sequence": decision.decision_sequence,
            "reason": decision.reason,
            "requested_delta_codes": decision.requested_delta_codes,
            "requested_code": decision.requested_code,
            "dac_epoch": controller.dac_epoch,
            "correction_count": controller.correction_count,
            "automatic_application_count": controller.automatic_application_count,
            "cumulative_movement_codes": controller.cumulative_movement_codes,
            "application_timestamp_s": int(rows[2]["application_timestamp_s"]),
        }
        applications.append(application)
        return rows[-1]

    # Establish the exact qualified origin and first phase residence.
    for timestamp_s, phase_cycles in ((600, 0), (1200, 0), (1800, 0)):
        append_decision(observe(timestamp_s, phase_cycles))

    response = transact(observe(2400, 36), request_sequence=1)
    response_timestamp_s = 2402 + policy.settling_exclusion_s + policy.fresh_support_s
    response_decision = observe(response_timestamp_s, 36, response=True)
    append_response_boundary(response_decision, response)
    controller.note_response(
        classification=response["response_class"],
        predicted_sign_observed=True,
        exact_replay=True,
        support_fresh=True,
        applied_epoch_exact=True,
    )
    dependent_response = response
    release = observe(response_timestamp_s + 600, 36)
    append_decision(release)
    if release.reason != "first_phase_observation_recorded_and_tight_reacquired":
        raise RuntimeError("sustained fixture did not consume first response exactly")

    response = transact(observe(4800, 30), request_sequence=2)
    response_decision = observe(6302, 30, response=True)
    append_response_boundary(response_decision, response)
    controller.note_response(
        classification=response["response_class"],
        predicted_sign_observed=True,
        exact_replay=True,
        support_fresh=True,
        applied_epoch_exact=True,
    )
    dependent_response = response

    challenge = observe(43_800, 30)
    if challenge.reason != "deliberate_reversal_challenge_request_ready":
        raise RuntimeError("sustained fixture did not reach the frozen challenge")
    response = transact(challenge, request_sequence=3)
    response_decision = observe(45_302, 30, response=True)
    append_response_boundary(response_decision, response)
    controller.note_response(
        classification=response["response_class"],
        predicted_sign_observed=True,
        exact_replay=True,
        support_fresh=True,
        applied_epoch_exact=True,
    )
    dependent_response = response

    recovery = observe(45_600, -36)
    if recovery.reason != "deliberate_reversal_challenge_recovery_request_ready":
        raise RuntimeError("sustained fixture did not reach challenge recovery")
    response = transact(recovery, request_sequence=4)
    response_decision = observe(47_102, -36, response=True)
    append_response_boundary(response_decision, response)
    controller.note_response(
        classification=response["response_class"],
        predicted_sign_observed=True,
        exact_replay=True,
        support_fresh=True,
        applied_epoch_exact=True,
    )
    dependent_response = response
    first_post_recovery_consumer = observe(47_702, 0)
    append_decision(first_post_recovery_consumer)

    first = transactions[0]
    manual = dict(first)
    manual.update(
        {
            "transaction_record_sequence": "1",
            "event": "manual_start",
            "authorization_sequence": "0",
            "nonce": "0",
            "request_sequence": "0",
            "decision_sequence": "0",
            "source_first_sequence": "0",
            "source_last_sequence": "0",
            "decision_timestamp_s": "1",
            "current_applied_code": str(programme.setup_code),
            "requested_delta_codes": "0",
            "requested_code": str(programme.setup_code),
            "correction_ordinal": "0",
            "cumulative_after_codes": "0",
            "pre_error_hz": "0.000000000000",
            "accepted_code": str(programme.setup_code),
            "accepted_timestamp_s": "1",
            "applied_code": str(programme.setup_code),
            "application_sequence": "0",
            "application_timestamp_s": "1",
            "i2c_ok": "true",
            "clamped": "false",
            "ambiguous": "false",
            "dac_epoch": "1",
            "estimator_history_reset": "false",
            "correction_count": "0",
            "cumulative_movement_codes": "0",
            "post_error_hz": "0.000000000000",
            "observed_response_hz": "0.000000000000",
            "cumulative_response_hz": "0.000000000000",
            "consecutive_indeterminate": "0",
            "active_state": "DISARMED",
            "response_class": "unavailable",
            "reason": "manual_start_established",
            "evidence_state": "evidence_clear",
        }
    )
    snapshot = controller.snapshot()
    if not (
        snapshot["correction_count"] == 4
        and snapshot["automatic_application_count"] == 3
        and snapshot["deliberate_challenge_applied"]
        and snapshot["deliberate_challenge_recovery_applied"]
        and snapshot["natural_reversal_observed"]
        and not snapshot["transaction_outstanding"]
        and first_post_recovery_consumer.requested_delta_codes == 0
    ):
        raise RuntimeError("sustained fixture final identity/accounting mismatch")
    return ahy, [manual, *transactions], {
        "applications": applications,
        "final_snapshot": snapshot,
        "first_response_consumer_reason": release.reason,
        "first_post_recovery_consumer_decision_sequence": (
            first_post_recovery_consumer.decision_sequence
        ),
    }


def _cx322_selected_estimate_fixture(
    ahy: list[dict[str, str]], bundle: dict[str, Any]
) -> list[dict[str, str]]:
    """Provide the exact timer coordinates consumed by the live replay guard."""

    policy = load_policy(Path(str(bundle["policy"]["path"])))
    rows: list[dict[str, str]] = []
    for index, decision in enumerate(ahy, start=1):
        frequency_error_hz = float(decision["frequency_error_hz"])
        frequency_hz = 10_000_000.0 + frequency_error_hz
        values = {field: "" for field in CONTRACT_FIELDS["estimates_v2"]}
        values.update(
            {
                "record_type": "EST",
                "schema_version": "2",
                "estimate_seq": str(index),
                "estimate_id": f"est:cx317:selected600:rehearsal:{index:06d}",
                "estimator_timestamp_ticks": str(
                    (
                        int(decision["decision_timestamp_s"])
                        * RP2040_TIMER0_TICKS_PER_SECOND
                    )
                    % RP2040_TIMER0_MICROS_WRAP_TICKS
                ),
                "time_domain": "rp2040_timer0",
                "source_count_seq": decision["source_last_sequence"],
                "source_count_ref": f"live:CNT:{decision['source_last_sequence']}",
                "source_reference_first_seq": decision["source_first_sequence"],
                "source_reference_last_seq": decision["source_last_sequence"],
                "source_status_refs": "live:STS:pps_gate",
                "source_dac_ref": f"live:DAC:{decision['dac_epoch']}",
                "manifest_ref": "firmware_config:cx322_direct_hybrid",
                "estimator_version": policy.frequency_estimator_id,
                "config_hash": policy.frequency_estimator_sha256,
                "observation_validity": "valid",
                "observation_reason_codes": "contiguous_snapshot_span",
                "reference_validity": "valid",
                "reference_age_s": "0",
                "reference_continuity": "true",
                "count_validity": "valid",
                "count_age_s": "0",
                "count_continuity": "true",
                "diagnostic_health": "healthy",
                "diagnostic_reason_codes": "diagnostic_healthy",
                "frequency_observation_hz": f"{frequency_hz:.12f}",
                "accepted_sample_count": "600",
                "estimator_confidence": "unavailable",
                "frequency_estimate_hz": f"{frequency_hz:.12f}",
                "frequency_error_hz": f"{frequency_error_hz:.12f}",
                "uncertainty_status": "unavailable",
                "uncertainty_reason_codes": "fixture_unavailable",
                "correlation_policy": "not_combined_missing_components",
                "uncertainty_model_ref": "unavailable:combined_uncertainty",
                "drift_enabled": "false",
                "preview_eligibility": "true",
                "eligibility_reason_codes": "preview_input_observe_only",
            }
        )
        rows.append(values)
    return rows


def _cx322_active_status_wire_fixture(
    *,
    generation: int,
    query_nonce: str,
    evidence_phase: str,
    bundle: dict[str, Any],
    applied: bool,
    checkpoint_passed: bool,
    evidence_request_sequence: int = 1,
    applied_code: int | None = None,
    dac_epoch: int | None = None,
    correction_count: int | None = None,
    automatic_application_count: int | None = None,
    cumulative_movement_codes: int | None = None,
    natural_reversal_observed: bool = False,
    deliberate_challenge_applied: bool = False,
    deliberate_challenge_recovery_applied: bool = False,
    deliberate_challenge_direction: int = 0,
    deliberate_challenge_code: int = 0,
    deliberate_challenge_dac_epoch: int = 0,
    deliberate_challenge_application_ticks: int = 0,
) -> bytes:
    """Return one complete CX322 status snapshot for a phase frontier."""

    programme = _selected_programme(bundle)
    policy = _read_object(Path(str(bundle["policy"]["path"])))
    bindings = policy["bindings"]
    requested_code = programme.setup_code - 5 if applied_code is None else applied_code
    keys = (
        SUSTAINED_HYBRID_ACTIVE_STATUS_KEYS
        if programme.sustained_regulation
        else ACTIVE_STATUS_KEYS
    )
    contract = (
        SUSTAINED_HYBRID_ACTIVE_STATUS_SNAPSHOT_CONTRACT
        if programme.sustained_regulation
        else ACTIVE_STATUS_SNAPSHOT_CONTRACT
    )
    physical_count = int(applied) if correction_count is None else correction_count
    automatic_count = (
        physical_count
        if automatic_application_count is None
        else automatic_application_count
    )
    movement = 5 if applied else 0
    if cumulative_movement_codes is not None:
        movement = cumulative_movement_codes
    current_epoch = (2 if applied else 1) if dac_epoch is None else dac_epoch
    values = {key: "unavailable" for key in keys}
    values.update(
        {
            "enabled": "true",
            "run_identity": programme.runtime_run_identity,
            "build_identity": str(bundle["firmware"]["build_identity"]),
            "profile_identity": programme.profile_id,
            "estimator_sha256": bindings["frequency_estimator"]["sha256"],
            "model_sha256": bindings["plant_model"]["sha256"],
            "active_policy_sha256": bundle["policy"]["policy_sha256"],
            "response_policy_sha256": bindings["response_policy"]["sha256"],
            "numerical_policy_sha256": bundle["policy"]["policy_sha256"],
            "state": (
                "DISARMED"
                if checkpoint_passed
                else ("AWAITING_RESPONSE" if applied else "ARMED")
            ),
            "reason": (
                "response_accepted_new_arm_required"
                if checkpoint_passed
                else "armed_one_shot_authorization"
            ),
            "evidence_pending": str(evidence_phase != "evidence_clear").lower(),
            "evidence_phase": evidence_phase,
            "capture_lease_live": "true",
            "manual_start_confirmed": "true",
            "arm_eligible": "false",
            "fail_static": "false",
            "setup_gnss_eligible": "true",
            "setup_reference_eligible": "true",
            "setup_partition_healthy": "true",
            "hybrid_state": (
                "HYBRID_TRACKING" if checkpoint_passed else "FIRST_PHASE_TRANSACTION"
            ),
            "hybrid_reason": (
                "first_phase_observation_recorded_and_tight_reacquired"
                if checkpoint_passed
                else "first_phase_application_checkpoint_required"
            ),
            "first_phase_checkpoint_passed": str(checkpoint_passed).lower(),
            "phase_nonzero_application_count": str(int(applied)),
            "phase_material_application_count": str(int(applied)),
            "frequency_only_application_count": "0",
            "session_id": "1",
            "query_nonce": query_nonce,
            "uptime_s": "4502",
            "evidence_request_sequence": (
                "0"
                if evidence_phase == "evidence_clear"
                else str(evidence_request_sequence)
            ),
            "expected_setup_code": f"0x{programme.setup_code:04X}",
            "confirmed_applied_code_known": "true",
            "confirmed_applied_code": str(
                requested_code if applied else programme.setup_code
            ),
            "correction_count": str(physical_count),
            "cumulative_movement_codes": str(movement),
            "dac_epoch": str(current_epoch),
            "selected_interval_count": "0",
            "automatic_retry": "false",
            "automatic_restore": "false",
        }
    )
    if programme.sustained_regulation:
        values.update(
            {
                "automatic_application_count": str(automatic_count),
                "natural_reversal_observed": str(natural_reversal_observed).lower(),
                "deliberate_challenge_applied": str(deliberate_challenge_applied).lower(),
                "deliberate_challenge_cancelled": "false",
                "deliberate_challenge_unexercised": "false",
                "deliberate_challenge_recovery_applied": str(
                    deliberate_challenge_recovery_applied
                ).lower(),
                "deliberate_challenge_direction": str(
                    deliberate_challenge_direction
                ),
                "deliberate_challenge_code": str(deliberate_challenge_code),
                "deliberate_challenge_dac_epoch": str(
                    deliberate_challenge_dac_epoch
                ),
                "deliberate_challenge_application_ticks": str(
                    deliberate_challenge_application_ticks
                ),
            }
        )
    records = [
        (SNAPSHOT_BEGIN_KEY, str(generation)),
        (SNAPSHOT_CONTRACT_KEY, contract),
        *((key, values[key]) for key in keys),
        (SNAPSHOT_COMPLETE_KEY, str(generation)),
    ]
    return "".join(
        f"STS,1,{generation * 1000 + sequence},"
        f"{(generation * 1000 + sequence) * 16000},rp2040_timer0,"
        f"cx317_active,{key},{value},INFO,0\r\n"
        for sequence, (key, value) in enumerate(records, start=1)
    ).encode()


def _cx321_active_status_wire_fixture(
    *,
    generation: int,
    query_nonce: str,
    evidence_phase: str,
    evidence_request_sequence: int,
    bundle: dict[str, Any],
    applied_code: int | None = None,
    dac_epoch: int = 2,
    correction_count: int = 1,
    cumulative_movement_codes: int = 21,
) -> bytes:
    programme = _selected_programme(bundle)
    policy = _read_object(Path(str(bundle["programme_policy"]["path"])))
    bindings = policy["bindings"]
    if applied_code is None:
        applied_code = programme.setup_code - 21
    identification_pending = evidence_request_sequence == 1
    values = {key: "unavailable" for key in CX321_ACTIVE_STATUS_KEYS}
    values.update(
        {
            "enabled": "true",
            "run_identity": programme.runtime_run_identity,
            "build_identity": str(bundle["firmware"]["build_identity"]),
            "profile_identity": programme.profile_id,
            "estimator_sha256": bindings["natural_frequency_estimator"][
                "sha256"
            ],
            "model_sha256": bindings["plant_model"]["sha256"],
            "active_policy_sha256": bundle["programme_policy"]["sha256"],
            "response_policy_sha256": bindings[
                "natural_response_classifier"
            ]["sha256"],
            "numerical_policy_sha256": bundle["policy"]["policy_sha256"],
            "state": "ARMED",
            "reason": "armed_one_shot_authorization",
            "evidence_pending": str(evidence_phase != "evidence_clear").lower(),
            "evidence_phase": evidence_phase,
            "capture_lease_live": "true",
            "manual_start_confirmed": "true",
            "arm_eligible": "true",
            "fail_static": "false",
            "setup_gnss_eligible": "true",
            "setup_reference_eligible": "true",
            "setup_partition_healthy": "true",
            "hybrid_state": (
                "FREQUENCY_ACQUIRE"
                if identification_pending
                else "FIRST_PHASE_TRANSACTION"
            ),
            "hybrid_reason": (
                "frequency_acquisition"
                if identification_pending
                else "first_phase_application_checkpoint_required"
            ),
            "first_phase_checkpoint_passed": "false",
            "phase_nonzero_application_count": "0",
            "phase_material_application_count": "0",
            "frequency_only_application_count": "0",
            "session_id": "1",
            "query_nonce": query_nonce,
            "uptime_s": "6303",
            "evidence_request_sequence": str(evidence_request_sequence),
            "expected_setup_code": f"0x{programme.setup_code:04X}",
            "confirmed_applied_code_known": "true",
            "confirmed_applied_code": str(applied_code),
            "correction_count": str(correction_count),
            "cumulative_movement_codes": str(cumulative_movement_codes),
            "dac_epoch": str(dac_epoch),
            "selected_interval_count": "0",
            "automatic_retry": "false",
            "automatic_restore": "false",
            "plant_sign_state": (
                "PLANT_SIGN_RESPONSE_ACK_PENDING"
                if identification_pending
                else "PHASE_QUALIFY"
            ),
            "plant_sign_pre_window_count": "2",
            "plant_sign_accumulator_accepted_intervals": "1500",
            "plant_sign_arm_window_eligible": "false",
            "plant_sign_gate_sha256": bindings["plant_sign_gate"]["sha256"],
            "identification_estimator_sha256": bindings[
                "identification_estimator"
            ]["sha256"],
            "identification_estimator_config_sha256": bundle[
                "identification"
            ]["estimator_runtime_config"]["sha256"],
            "natural_frequency_estimator_sha256": bindings[
                "natural_frequency_estimator"
            ]["sha256"],
        }
    )
    records = [
        (SNAPSHOT_BEGIN_KEY, str(generation)),
        (SNAPSHOT_CONTRACT_KEY, CX321_ACTIVE_STATUS_SNAPSHOT_CONTRACT),
        *((key, values[key]) for key in CX321_ACTIVE_STATUS_KEYS),
        (SNAPSHOT_COMPLETE_KEY, str(generation)),
    ]
    return "".join(
        f"STS,1,{generation * 1000 + sequence},"
        f"{(generation * 1000 + sequence) * 16000},rp2040_timer0,"
        f"cx317_active,{key},{value},INFO,0\r\n"
        for sequence, (key, value) in enumerate(records, start=1)
    ).encode()


def _cx321_ack_handoff_fixture(
    prefix: list[dict[str, str]], *, attestation_sha256: str
) -> list[dict[str, str]]:
    application = prefix[3]
    response = prefix[4]
    common_echo = {
        key: application[key]
        for key in (
            "request_sequence",
            "acceptance_sequence",
            "application_sequence",
            "requested_delta_codes",
            "requested_code",
            "accepted_code",
            "applied_code",
            "application_timestamp_ticks",
            "dac_epoch",
        )
    }

    def base(sequence: int, event: str) -> dict[str, str]:
        row = {field: "" for field in PLANT_SIGN_QUALIFICATION_V1_FIELDS}
        row.update(
            {
                key: prefix[0][key]
                for key in (
                    "record_type",
                    "schema_version",
                    "run_identity",
                    "build_identity",
                    "profile_identity",
                    "capture_session",
                    "policy_sha256",
                    "plant_sign_gate_sha256",
                    "identification_estimator_sha256",
                    "identification_estimator_config_sha256",
                    "natural_frequency_estimator_sha256",
                    "setup_application_sequence",
                    "setup_application_timestamp_ticks",
                    "setup_applied_code",
                    "setup_dac_epoch",
                )
            }
        )
        row.update(
            {
                "qualification_record_sequence": str(sequence),
                "event": event,
                "state_before": "PLANT_SIGN_RESPONSE_ACK_PENDING",
                "state_after": "PHASE_QUALIFY",
                "reason": "identification_response_acknowledged",
                "actionable": "false",
                **common_echo,
                "response_counts": response["response_counts"],
                "response_source_last_sequence": response[
                    "response_source_last_sequence"
                ],
                "acknowledged_response_record_sequence": response[
                    "qualification_record_sequence"
                ],
                "host_replay_exact": "true",
                "replay_attestation_sha256": attestation_sha256,
            }
        )
        return row

    ack = base(6, "response_ack")
    ack["event_timestamp_ticks"] = str(int(response["close_ticks"]) + 16_000_000)
    handoff = base(7, "handoff")
    handoff.update(
        {
            "event_timestamp_ticks": str(int(response["close_ticks"]) + 32_000_000),
            "state_before": "PHASE_QUALIFY",
            "reason": "plant_sign_first_natural_consumer_handoff_exact",
            "global_correction_count": "1",
            "global_cumulative_movement_codes": "21",
            "global_last_application_timestamp_ticks": application[
                "application_timestamp_ticks"
            ],
            "natural_chatter_origin_code": application["applied_code"],
            "natural_cumulative_movement_codes": "0",
            "natural_direction_count": "0",
            "attested": "true",
        }
    )
    return [ack, handoff]


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
    programme = _selected_programme(bundle)
    files = [
        dict(entry)
        for entry in (
            cx321_csv_files()
            if programme.identification_required
            else default_csv_files()
        )
    ]
    value: dict[str, Any] = {
        "schema_version": 1,
        "compatibility_floor": programme.compatibility_floor,
        "template": False,
        "run_id": run_dir.name,
        "created_utc": _utc_now(),
        "started_at_utc": _utc_now(),
        "stage": programme.live_stage,
        "mode": f"{programme.key}_accelerated_live_topology_rehearsal_pty",
        "programme_id": programme.programme_id,
        "run_identity": programme.runtime_run_identity,
        "profile_identity": programme.profile_id,
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
        programme.manifest_section: {
            "profile_id": programme.profile_id,
            "run_identity": programme.runtime_run_identity,
            "setup": {"code": programme.setup_code},
            "automatic_control": {
                "maximum_total_applications": (
                    programme.maximum_physical_applications
                ),
                "maximum_step_codes": programme.maximum_step_codes,
                "maximum_cumulative_movement_codes": programme.maximum_cumulative_movement_codes,
                "minimum_applied_cadence_s": programme.minimum_applied_cadence_s,
                "minimum_code": programme.minimum_code,
                "maximum_code": programme.maximum_code,
                **(
                    {
                        "maximum_total_automatic_applications": (
                            programme.maximum_applications
                        ),
                        "maximum_deliberate_challenges": (
                            programme.maximum_deliberate_challenges
                        ),
                    }
                    if programme.sustained_regulation
                    else {}
                ),
            },
            "qualification": {
                "qualified_duration_s": programme.qualified_duration_s,
                "absolute_wall_clock_limit_s": programme.absolute_wall_limit_s,
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
    if programme.identification_required:
        value["domains"].append(
            {
                "name": "rp2040_timer0_extended",
                "nominal_hz": 16_000_000,
            }
        )
        value["programme_policy"] = bundle["programme_policy"]
        value["identification"] = bundle["identification"]
        value[programme.manifest_section]["plant_sign_identification"] = {
            "required": True,
            "contract": "plant_sign_qualification_v1",
            "programme_policy": bundle["programme_policy"],
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
    programme = _selected_programme(value)
    section = value.get(programme.manifest_section, {})
    if not isinstance(host, dict) or not isinstance(section, dict):
        raise ValueError("active-hybrid rehearsal manifest host/programme is malformed")
    bundle_path = Path(str(bundle_binding.get("path", ""))).resolve()
    proposal_path = Path(str(proposal_binding.get("path", ""))).resolve()
    bundle = (
        validate_bundle(bundle_path)
        if programme is CX320_PROGRAMME
        else validate_bundle(bundle_path, programme)
    )
    proposal = (
        validate_proposal(proposal_path)
        if programme is CX320_PROGRAMME
        else validate_proposal(proposal_path, programme)
    )
    device = str(host.get("serial_device", ""))
    if (
        path != path.parent / "run_manifest.json"
        or value.get("manifest_sha256") != _canonical_sha256(unsigned)
        or value.get("mode")
        != f"{programme.key}_accelerated_live_topology_rehearsal_pty"
        or value.get("stage") != programme.live_stage
        or value.get("programme_id") != programme.programme_id
        or value.get("run_identity") != programme.runtime_run_identity
        or value.get("profile_identity") != programme.profile_id
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
        or section.get("profile_id") != programme.profile_id
        or section.get("run_identity") != programme.runtime_run_identity
        or section.get("setup", {}).get("code") != programme.setup_code
    ):
        raise ValueError(
            f"{programme.key.upper()} rehearsal manifest identity or no-I/O boundary differs"
        )
    contracts = value.get("contracts", {})
    if (
        not isinstance(contracts, dict)
        or (
            "plant_sign_qualification_v1" in contracts
        )
        is not programme.identification_required
        or (
            programme.identification_required
            and (
                value.get("programme_policy") != bundle.get("programme_policy")
                or value.get("identification") != bundle.get("identification")
                or section.get("plant_sign_identification", {}).get("contract")
                != "plant_sign_qualification_v1"
            )
        )
    ):
        raise ValueError(
            f"{programme.key.upper()} rehearsal evidence contract selection differs"
        )
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
    if supervisor.programme.identification_required:
        health.update(
            {
                ("cx317_active", "plant_sign_state"): "FREQUENCY_ACQUIRE",
                ("cx317_active", "plant_sign_pre_window_count"): "0",
                (
                    "cx317_active",
                    "plant_sign_accumulator_accepted_intervals",
                ): "0",
                ("cx317_active", "plant_sign_arm_window_eligible"): "false",
                **{
                    ("cx317_active", key): value
                    for key, value in supervisor.plant_sign_identities.items()
                    if key != "policy_sha256"
                },
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
    cx321 = ("cx317_active", "plant_sign_state") in health
    contract = (
        CX321_ACTIVE_STATUS_SNAPSHOT_CONTRACT
        if cx321
        else ACTIVE_STATUS_SNAPSHOT_CONTRACT
    )
    keys = CX321_ACTIVE_STATUS_KEYS if cx321 else ACTIVE_STATUS_KEYS
    latest = reducer.observe(
        row("cx317_active", SNAPSHOT_BEGIN_KEY, str(generation))
    )
    latest = reducer.observe(
        row(
            "cx317_active",
            SNAPSHOT_CONTRACT_KEY,
            contract,
        )
    )
    for key in keys:
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
    # Preserve the non-zero subsecond phase that escaped the attempt-8 host
    # validator.  Scientific boundaries are measured from this exact device
    # timestamp, while integer uptime remains a conservative lower bound.
    origin_subsecond_ticks = 13_602_864
    origin_ticks = (
        origin_uptime_s * RP2040_TIMER0_TICKS_PER_SECOND
        + origin_subsecond_ticks
    )
    estimate_path = supervisor.run_dir / "csv/estimates_v2.csv"
    estimate = {field: "" for field in CONTRACT_FIELDS["estimates_v2"]}
    estimate.update(
        {
            "record_type": "EST",
            "schema_version": "2",
            "estimate_seq": "541",
            "estimate_id": "est:cx317:selected600:device_clock_rehearsal",
            "estimator_timestamp_ticks": str(origin_ticks),
            "time_domain": "rp2040_timer0",
            "source_count_ref": "live:CNT:2400",
            "source_dac_ref": "live:DAC:1",
            "estimator_version": "cx317_selected_600s_nonoverlap_v1",
            "observation_validity": "valid",
            "reference_validity": "valid",
            "reference_continuity": "true",
            "count_validity": "valid",
            "count_continuity": "true",
            "diagnostic_health": "healthy",
            "accepted_sample_count": "600",
            "preview_eligibility": "true",
        }
    )
    with estimate_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=CONTRACT_FIELDS["estimates_v2"]
        )
        writer.writeheader()
        writer.writerow(estimate)

    supervisor.state["setup_confirmed_utc"] = supervisor.envelope.wall_origin_utc
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
            ("cx317_active", "dac_epoch"): "1",
            ("cx317_active", "session_id"): "1",
            ("cx317_active", "hybrid_state"): "HYBRID_TRACKING",
            ("cx317_active", "first_phase_checkpoint_passed"): "true",
            ("cx317_active", "phase_nonzero_application_count"): "2",
            ("cx317_active", "phase_material_application_count"): "2",
            ("cx317_active", "correction_count"): "2",
            ("cx317_active", "cumulative_movement_codes"): "8",
        }
    )

    health[("cx317_active", "uptime_s")] = str(origin_uptime_s)
    supervisor._maybe_qualify(health)
    fractional_origin_deferred = (
        supervisor.state["qualified_origin_estimate_id"] is None
    )
    health[("cx317_active", "uptime_s")] = str(origin_uptime_s + 1)
    supervisor._maybe_qualify(health)
    exact_origin_established = (
        supervisor.state["qualified_origin_estimate_id"]
        == "est:cx317:selected600:device_clock_rehearsal"
        and supervisor.state["qualified_origin_timestamp_ticks"] == origin_ticks
        and supervisor.state["qualified_origin_session_id"] == 1
    )

    qualified_duration_s = supervisor.programme.qualified_duration_s
    admission_elapsed_s = qualified_duration_s - CORRECTION_RESPONSE_RESERVE_S
    health[("cx317_active", "uptime_s")] = str(
        origin_uptime_s + admission_elapsed_s
    )
    admission_open_at_floor = not supervisor._close_response_horizon_if_required(
        health
    )
    health[("cx317_active", "uptime_s")] = str(
        origin_uptime_s + admission_elapsed_s + 1
    )
    admission_closed_conservatively = supervisor._close_response_horizon_if_required(
        health
    )

    wall_origin_epoch = datetime.fromisoformat(
        supervisor.envelope.wall_origin_utc.replace("Z", "+00:00")
    ).timestamp()
    health[("cx317_active", "uptime_s")] = str(
        origin_uptime_s + qualified_duration_s
    )
    supervisor._maybe_finish(health, wall_origin_epoch + 50_000, 0.0)
    endpoint_open_after_forward_utc_step = supervisor.state["terminal"] is None
    health[("cx317_active", "uptime_s")] = str(
        origin_uptime_s + qualified_duration_s + 1
    )
    supervisor._maybe_finish(health, wall_origin_epoch - 1_000, 0.0)
    endpoint_closed_after_backward_utc_step = (
        (supervisor.state.get("terminal") or {}).get("reason")
        == (
            f"{supervisor.programme.key}_"
            f"{supervisor.programme.qualified_duration_s // 3600}h_"
            "qualified_endpoint_complete"
        )
    )

    result = {
        "time_domain": "rp2040_timer0",
        "capture_session": 1,
        "qualified_origin_subsecond_ticks": origin_subsecond_ticks,
        "fractional_origin_deferred_until_lower_bound": (
            fractional_origin_deferred
        ),
        "exact_fractional_origin_established": exact_origin_established,
        "correction_admission_close_elapsed_s": admission_elapsed_s,
        "qualified_endpoint_elapsed_s": qualified_duration_s,
        "admission_open_at_floor_before_exact_boundary": (
            admission_open_at_floor
        ),
        "admission_closed_at_first_conservative_uptime": (
            admission_closed_conservatively
        ),
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
            "fractional_origin_deferred_until_lower_bound",
            "exact_fractional_origin_established",
            "admission_open_at_floor_before_exact_boundary",
            "admission_closed_at_first_conservative_uptime",
            "forward_host_utc_step_did_not_close_early",
            "backward_host_utc_step_did_not_delay_endpoint",
        )
    ):
        raise RuntimeError("CX320 qualified device-clock rehearsal failed")
    return result


def _exercise_cx321_host_ordering(
    *,
    output_dir: Path,
    bundle_path: Path,
    bundle: dict[str, Any],
    proposal_path: Path,
    proposal: dict[str, Any],
) -> dict[str, Any]:
    """Exercise the pre2 arm window and ACT-before-PSQ split boundary."""

    supervisor, health = _prewrite_boundary_supervisor(
        run_dir=output_dir / "prearm",
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
    )
    commands: list[str] = []
    supervisor._command = commands.append  # type: ignore[method-assign]
    supervisor.state["manual_start_sent"] = True
    for key, expected in supervisor.plant_sign_identities.items():
        if key != "policy_sha256":
            health[("cx317_active", key)] = expected
    health.update(
        {
            ("cx317_active", "manual_start_confirmed"): "true",
            ("cx317_active", "state"): "DISARMED",
            ("cx317_active", "arm_eligible"): "true",
            ("cx317_active", "evidence_pending"): "false",
            ("cx317_active", "evidence_phase"): "evidence_clear",
            ("cx317_active", "hybrid_state"): "FREQUENCY_ACQUIRE",
            ("cx317_active", "plant_sign_state"): "FREQUENCY_ACQUIRE",
            ("cx317_active", "plant_sign_pre_window_count"): "1",
            (
                "cx317_active",
                "plant_sign_accumulator_accepted_intervals",
            ): "1399",
            ("cx317_active", "plant_sign_arm_window_eligible"): "false",
        }
    )
    supervisor._maybe_start_or_arm(health)
    no_early_arm = not commands
    health[("cx317_active", "plant_sign_accumulator_accepted_intervals")] = "1400"
    health[("cx317_active", "plant_sign_arm_window_eligible")] = "true"
    supervisor._maybe_start_or_arm(health)
    one_exact_pre2_arm = (
        len(commands) == 1
        and commands[0].startswith("ACTIVE ARM 1 ")
        and supervisor.state["plant_sign_prearm_sent"] is True
    )

    split_path = output_dir / "phase4_split" / "plant_sign_qualification_v1.csv"
    split_path.parent.mkdir(parents=True)
    split_path.write_text("event,request_sequence\n", encoding="utf-8")

    def append_response() -> None:
        time.sleep(0.05)
        with split_path.open("a", encoding="utf-8") as handle:
            handle.write("response,7\n")
            handle.flush()
            os.fsync(handle.fileno())

    writer = threading.Thread(target=append_response)
    writer.start()
    _, response = _await_cx321_plant_sign_response(
        split_path, request_sequence=7, timeout_s=0.5
    )
    writer.join()
    phase4_waited_for_matching_psq = response == {
        "event": "response",
        "request_sequence": "7",
    }
    result = {
        "prearm_minimum_accepted_intervals": (
            PLANT_SIGN_PREARM_MIN_ACCEPTED_INTERVALS
        ),
        "arm_lifetime_s": ARM_LIFETIME_S,
        "status_query_margin_s": QUERY_PERIOD_S,
        "no_early_or_stale_identification_arm": no_early_arm,
        "one_exact_pre2_identification_arm": one_exact_pre2_arm,
        "phase4_waited_for_matching_psq_after_act_split": (
            phase4_waited_for_matching_psq
        ),
        "physical_actions_performed": 0,
    }
    if not all(
        result[key]
        for key in (
            "no_early_or_stale_identification_arm",
            "one_exact_pre2_identification_arm",
            "phase4_waited_for_matching_psq_after_act_split",
        )
    ):
        raise RuntimeError("CX321 host ordering rehearsal failed")
    return result


def _exercise_cx321_real_transaction_path(
    *,
    master: int,
    run_dir: Path,
    manifest: dict[str, Any],
    bundle: dict[str, Any],
) -> dict[str, Any]:
    """Drive the exact CX321 lifecycle through capture and live supervisor."""

    context, prefix, snapshots = _cx321_plant_sign_fixture(bundle)
    transactions = _cx321_transaction_fixture(manifest)
    response_act = transactions[-1]
    psq_replay = replay_plant_sign_evidence(prefix, context)
    snapshot_proof = replay_plant_sign_windows_against_snapshots(
        prefix, snapshots, context
    )
    act_join = _join_cx321_psq_response_to_act(
        psq_response=prefix[-1],
        act_response=response_act,
        timer_hz=context.timer_hz,
    )
    chain = complete_plant_sign_evidence_chain(
        psq_replay=psq_replay,
        snapshot_window_proof=snapshot_proof,
        act_response_join=act_join,
    )
    expected_phase4 = (
        "ACTIVE EVIDENCE 1 4 5 -5 1 2 6302 "
        f"{chain['attestation_sha256']}"
    )

    stop = threading.Event()
    identification_phase4_observed = threading.Event()
    natural_phase4_observed = threading.Event()
    write_lock = threading.Lock()
    observed_commands: list[str] = []
    errors: list[str] = []
    state = {
        "generation": 0,
        "evidence_phase": "request_pending",
        "evidence_request_sequence": 1,
        "applied_code": _selected_programme(bundle).setup_code - 21,
        "dac_epoch": 2,
        "correction_count": 1,
        "cumulative_movement_codes": 21,
    }

    def emulate_firmware() -> None:
        buffered = b""
        try:
            while not stop.is_set():
                readable, _, _ = select.select([master], [], [], 0.05)
                if not readable:
                    continue
                buffered += os.read(master, 4096)
                while b"\n" in buffered:
                    raw, buffered = buffered.split(b"\n", 1)
                    command = raw.rstrip(b"\r").decode("ascii")
                    observed_commands.append(command)
                    if command.startswith("ACTIVE EVIDENCE 1 "):
                        phase = int(command.split()[3])
                        expected = {
                            1: "request_pending",
                            2: "acceptance_pending",
                            3: "application_pending",
                            4: "response_pending",
                        }[phase]
                        if state["evidence_phase"] != expected:
                            raise RuntimeError(
                                f"phase {phase} released from "
                                f"{state['evidence_phase']}"
                            )
                        state["evidence_phase"] = {
                            1: "acceptance_pending",
                            2: "application_pending",
                            3: "response_pending",
                            4: "evidence_clear",
                        }[phase]
                        if phase == 4:
                            if command != expected_phase4:
                                raise RuntimeError(
                                    "extended phase-4 command differs: "
                                    f"{command!r}"
                                )
                            state["evidence_request_sequence"] = 0
                            identification_phase4_observed.set()
                    elif command.startswith("ACTIVE EVIDENCE 2 "):
                        phase = int(command.split()[3])
                        expected = {
                            1: "request_pending",
                            2: "acceptance_pending",
                            3: "application_pending",
                            4: "response_pending",
                        }[phase]
                        if state["evidence_phase"] != expected:
                            raise RuntimeError(
                                f"natural phase {phase} released from "
                                f"{state['evidence_phase']}"
                            )
                        state["evidence_phase"] = {
                            1: "acceptance_pending",
                            2: "application_pending",
                            3: "response_pending",
                            4: "evidence_clear",
                        }[phase]
                        if phase == 3:
                            natural = state["natural_summary"]
                            state["applied_code"] = natural["requested_code"]
                            state["dac_epoch"] = natural["applied_dac_epoch"]
                            state["correction_count"] = 2
                            state["cumulative_movement_codes"] = (
                                21 + abs(natural["requested_delta_codes"])
                            )
                        if phase == 4:
                            if command != "ACTIVE EVIDENCE 2 4":
                                raise RuntimeError(
                                    "natural phase-4 command differs: "
                                    f"{command!r}"
                                )
                            state["evidence_request_sequence"] = 0
                            natural_phase4_observed.set()
                    if command.startswith("ACTIVE SNAPSHOT "):
                        nonce = command.split()[2]
                        state["generation"] += 1
                        payload = _cx321_active_status_wire_fixture(
                            generation=int(state["generation"]),
                            query_nonce=nonce,
                            evidence_phase=str(state["evidence_phase"]),
                            evidence_request_sequence=int(
                                state["evidence_request_sequence"]
                            ),
                            bundle=bundle,
                            applied_code=int(state["applied_code"]),
                            dac_epoch=int(state["dac_epoch"]),
                            correction_count=int(state["correction_count"]),
                            cumulative_movement_codes=int(
                                state["cumulative_movement_codes"]
                            ),
                        )
                        with write_lock:
                            _write_all_fd(master, payload)
        except (OSError, RuntimeError, UnicodeDecodeError, ValueError) as exc:
            errors.append(str(exc))
            identification_phase4_observed.set()
            natural_phase4_observed.set()

    emulator = threading.Thread(target=emulate_firmware, daemon=True)
    emulator.start()
    try:
        evidence_wire = b"".join(
            (
                _wire_rows(snapshots, PPS_SNAPSHOT_FIELDS),
                _wire_rows(prefix, PLANT_SIGN_QUALIFICATION_V1_FIELDS),
            )
        )
        with write_lock:
            _write_all_fd(master, evidence_wire)
        _wait_until(
            lambda: _read_object(
                run_dir / "reports/cx317_active_supervisor_state.json"
            ).get("initial_session_id")
            == 1,
            10.0,
            "CX321 initial complete status identity before ACT",
        )
        with write_lock:
            _write_all_fd(
                master,
                _wire_rows(transactions, ACTIVE_TRANSACTION_V1_FIELDS),
            )
        if not identification_phase4_observed.wait(20.0):
            raise TimeoutError("CX321 extended phase-4 ACK was not observed")
        if errors:
            raise RuntimeError("CX321 firmware emulator failed: " + errors[0])
        ack_handoff = _cx321_ack_handoff_fixture(
            prefix,
            attestation_sha256=str(chain["attestation_sha256"]),
        )
        with write_lock:
            _write_all_fd(
                master,
                _wire_rows(
                    ack_handoff, PLANT_SIGN_QUALIFICATION_V1_FIELDS
                ),
            )
        psq_path = run_dir / "csv/plant_sign_qualification_v1.csv"
        _wait_until(
            lambda: len(psq_path.read_text(encoding="utf-8").splitlines())
            == 8,
            10.0,
            "captured CX321 response_ack and handoff",
        )
        _wait_until(
            lambda: set(
                _read_object(
                    run_dir
                    / "reports/cx317_active_supervisor_state.json"
                ).get("acknowledged_record_sequences", [])
            )
            >= {2, 3, 4, 5},
            10.0,
            "live-supervisor phase-4 firmware-consumption confirmation",
        )
        natural_ahy, natural_transactions, natural_summary = (
            _cx321_first_natural_transaction_fixture(bundle)
        )
        state.update(
            {
                "natural_summary": natural_summary,
                "evidence_phase": "request_pending",
                "evidence_request_sequence": 2,
            }
        )
        with write_lock:
            _write_all_fd(
                master,
                _wire_rows(
                    natural_ahy, ACTIVE_HYBRID_DECISION_V1_FIELDS
                ),
            )
            _write_all_fd(
                master,
                _wire_rows(
                    natural_transactions, ACTIVE_TRANSACTION_V1_FIELDS
                ),
            )
        if not natural_phase4_observed.wait(30.0):
            raise TimeoutError("CX321 natural phase-4 ACK was not observed")
        if errors:
            raise RuntimeError("CX321 firmware emulator failed: " + errors[0])
        _wait_until(
            lambda: set(
                _read_object(
                    run_dir
                    / "reports/cx317_active_supervisor_state.json"
                ).get("acknowledged_record_sequences", [])
            )
            >= {2, 3, 4, 5, 6, 7, 8, 9},
            10.0,
            "first natural response replay and firmware consumption",
        )
    finally:
        stop.set()
        emulator.join(timeout=2.0)
    captured_psq = list(
        csv.DictReader(psq_path.open("r", newline="", encoding="utf-8"))
    )
    replay = replay_plant_sign_evidence(
        captured_psq,
        context,
        require_ack_handoff=True,
        expected_ack_attestation_sha256=str(chain["attestation_sha256"]),
    )
    phases = [
        command
        for command in observed_commands
        if command.startswith("ACTIVE EVIDENCE 1 ")
    ]
    natural_phases = [
        command
        for command in observed_commands
        if command.startswith("ACTIVE EVIDENCE 2 ")
    ]
    return {
        "canonical_psq_field_count": len(
            PLANT_SIGN_QUALIFICATION_V1_FIELDS
        ),
        "canonical_snp_rows_captured": len(snapshots),
        "canonical_act_field_count": len(ACTIVE_TRANSACTION_V1_FIELDS),
        "evidence_phase_commands": phases,
        "extended_phase4_command": expected_phase4,
        "complete_evidence_chain_sha256": chain["attestation_sha256"],
        "raw_snapshot_proof_sha256": snapshot_proof["proof_sha256"],
        "act_response_join": act_join,
        "raw_timer_rollover_between_application_and_response": (
            int(prefix[3]["application_timestamp_ticks"])
            < RP2040_TIMER0_MICROS_WRAP_TICKS
            < int(prefix[4]["open_ticks"])
        ),
        "firmware_consumption_confirmed": len(phases) == 4,
        "response_ack_handoff_exact": (
            replay["ack_exact"] and replay["handoff_exact"]
        ),
        "first_natural_decision": natural_summary,
        "natural_ahy_rows_captured": len(natural_ahy),
        "natural_evidence_phase_commands": natural_phases,
        "natural_response_firmware_consumption_confirmed": (
            len(natural_phases) == 4
        ),
        "last_status_generation": int(state["generation"]),
        "physical_actions_performed": 0,
    }


def _exercise_cx322_real_transaction_path(
    *,
    master: int,
    run_dir: Path,
    bundle: dict[str, Any],
) -> dict[str, Any]:
    """Drive observational responses through the actual host process path."""

    programme = _selected_programme(bundle)
    if programme.sustained_regulation:
        ahy, transactions, summary = _sustained_multi_transaction_fixture(bundle)
        applications = {
            int(item["request_sequence"]): item
            for item in summary["applications"]
        }
    else:
        ahy, transactions, summary = _cx322_first_observational_transaction_fixture(
            bundle
        )
        applications = {
            1: {
                "request_sequence": 1,
                "requested_code": summary["requested_code"],
                "dac_epoch": summary["applied_dac_epoch"],
                "correction_count": 1,
                "automatic_application_count": 1,
                "cumulative_movement_codes": abs(
                    summary["requested_delta_codes"]
                ),
            }
        }
    estimates = _cx322_selected_estimate_fixture(ahy, bundle)
    stop = threading.Event()
    phase4_observed = threading.Event()
    write_lock = threading.Lock()
    observed_commands: list[str] = []
    errors: list[str] = []
    state: dict[str, Any] = {
        "generation": 0,
        "evidence_phase": "evidence_clear",
        "evidence_request_sequence": 0,
        "applied": False,
        "checkpoint_passed": False,
        "applied_code": programme.setup_code,
        "dac_epoch": 1,
        "correction_count": 0,
        "automatic_application_count": 0,
        "cumulative_movement_codes": 0,
        "query_nonce": "0",
    }

    def emit_active_status() -> None:
        state["generation"] += 1
        payload = _cx322_active_status_wire_fixture(
            generation=int(state["generation"]),
            query_nonce=str(state["query_nonce"]),
            evidence_phase=str(state["evidence_phase"]),
            bundle=bundle,
            applied=bool(state["applied"]),
            checkpoint_passed=bool(state["checkpoint_passed"]),
            evidence_request_sequence=int(
                state["evidence_request_sequence"]
            ),
            applied_code=int(state["applied_code"]),
            dac_epoch=int(state["dac_epoch"]),
            correction_count=int(state["correction_count"]),
            automatic_application_count=int(
                state["automatic_application_count"]
            ),
            cumulative_movement_codes=int(
                state["cumulative_movement_codes"]
            ),
            natural_reversal_observed=(
                programme.sustained_regulation
                and int(state["correction_count"]) >= 4
            ),
            deliberate_challenge_applied=(
                programme.sustained_regulation
                and int(state["correction_count"]) >= 3
            ),
            deliberate_challenge_recovery_applied=(
                programme.sustained_regulation
                and int(state["correction_count"]) >= 4
            ),
            deliberate_challenge_direction=(
                -1 if programme.sustained_regulation else 0
            ),
            deliberate_challenge_code=(
                int(applications[3]["requested_code"])
                if programme.sustained_regulation
                else 0
            ),
            deliberate_challenge_dac_epoch=(
                int(applications[3]["dac_epoch"])
                if programme.sustained_regulation
                else 0
            ),
            deliberate_challenge_application_ticks=(
                43_800 * RP2040_TIMER0_TICKS_PER_SECOND
                if programme.sustained_regulation
                else 0
            ),
        )
        with write_lock:
            _write_all_fd(master, payload)

    def emulate_firmware() -> None:
        buffered = b""
        try:
            while not stop.is_set():
                readable, _, _ = select.select([master], [], [], 0.05)
                if not readable:
                    continue
                buffered += os.read(master, 4096)
                while b"\n" in buffered:
                    raw, buffered = buffered.split(b"\n", 1)
                    command = raw.rstrip(b"\r").decode("ascii")
                    observed_commands.append(command)
                    if command.startswith("ACTIVE EVIDENCE "):
                        fields = command.split()
                        request_sequence = int(fields[2])
                        phase = int(fields[3])
                        if request_sequence != state["evidence_request_sequence"]:
                            if (
                                phase != 1
                                or state["evidence_phase"] != "evidence_clear"
                                or request_sequence
                                != state["evidence_request_sequence"] + 1
                            ):
                                raise RuntimeError(
                                    "observational request identity/order mismatch: "
                                    f"request={request_sequence}, phase={phase}, "
                                    f"prior_request={state['evidence_request_sequence']}, "
                                    f"prior_phase={state['evidence_phase']}"
                                )
                            state["evidence_request_sequence"] = request_sequence
                            state["evidence_phase"] = "request_pending"
                        expected = {
                            1: "request_pending",
                            2: "acceptance_pending",
                            3: "application_pending",
                            4: "response_pending",
                        }[phase]
                        if state["evidence_phase"] != expected:
                            raise RuntimeError(
                                f"CX322 phase {phase} released from "
                                f"{state['evidence_phase']}"
                            )
                        state["evidence_phase"] = {
                            1: "acceptance_pending",
                            2: "application_pending",
                            3: "response_pending",
                            4: "evidence_clear",
                        }[phase]
                        if phase >= 2:
                            state["applied"] = True
                            application = applications[request_sequence]
                            for key in (
                                "requested_code",
                                "dac_epoch",
                                "correction_count",
                                "automatic_application_count",
                                "cumulative_movement_codes",
                            ):
                                target = (
                                    "applied_code" if key == "requested_code" else key
                                )
                                state[target] = int(application[key])
                        if phase == 4:
                            if request_sequence == 1:
                                state["checkpoint_passed"] = True
                            if programme.sustained_regulation:
                                # Sustained rehearsal spans more than one
                                # live-health freshness interval.  Mirror the
                                # firmware's periodic status publication after
                                # each complete transaction so downstream
                                # identity checks remain exercised, not waived.
                                emit_active_status()
                            if request_sequence == len(applications):
                                phase4_observed.set()
                    if command.startswith("ACTIVE SNAPSHOT "):
                        state["query_nonce"] = command.split()[2]
                        emit_active_status()
        except (OSError, RuntimeError, UnicodeDecodeError, ValueError) as exc:
            errors.append(str(exc))
            phase4_observed.set()

    emulator = threading.Thread(target=emulate_firmware, daemon=True)
    emulator.start()
    try:
        _wait_until(
            lambda: _read_object(
                run_dir / "reports/cx317_active_supervisor_state.json"
            ).get("initial_session_id")
            == 1,
            15.0,
            "CX322 initial complete status identity before ACT",
        )
        with write_lock:
            _write_all_fd(
                master,
                _wire_rows(estimates, CONTRACT_FIELDS["estimates_v2"]),
            )
        estimate_path = run_dir / "csv/estimates_v2.csv"
        _wait_until(
            lambda: estimate_path.is_file()
            and sum(1 for _ in estimate_path.open(encoding="utf-8"))
            >= len(estimates) + 1,
            10.0,
            "CX322 exact selected-estimate timestamps before AHY replay",
        )
        with write_lock:
            _write_all_fd(master, _wire_rows(ahy, ACTIVE_HYBRID_DECISION_V1_FIELDS))
            _write_all_fd(
                master,
                _wire_rows(transactions, ACTIVE_TRANSACTION_V1_FIELDS),
            )
        if not phase4_observed.wait(30.0):
            raise TimeoutError("observational final phase-4 ACK was not observed")
        if errors:
            raise RuntimeError("CX322 firmware emulator failed: " + errors[0])
        _wait_until(
            lambda: set(
                _read_object(
                    run_dir / "reports/cx317_active_supervisor_state.json"
                ).get("acknowledged_record_sequences", [])
            )
            >= set(range(2, 2 + 4 * len(applications))),
            10.0,
            "observational response replay and firmware consumption",
        )
        _wait_until(
            lambda: bool(
                _read_object(
                    run_dir / "reports/cx317_active_supervisor_state.json"
                ).get("first_phase_observation_checkpoint_exact")
            ),
            10.0,
            "CX322 exact observation checkpoint and later-authority release",
        )
    finally:
        stop.set()
        emulator.join(timeout=2.0)

    events_path = run_dir / "reports/cx317_active_supervisor_events.jsonl"
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    evidence_commands = [
        command
        for command in observed_commands
        if command.startswith("ACTIVE EVIDENCE ")
    ]
    retained_response_events = [
        event
        for event in events
        if event.get("event") == "response_retained_as_nonterminal_observation"
    ]
    result = {
        "active_hybrid_rows_captured": len(ahy),
        "active_transaction_rows_captured": len(transactions),
        "evidence_phase_commands": evidence_commands,
        "response_class": (
            "multiple_observational"
            if programme.sustained_regulation
            else summary["response_class"]
        ),
        "response_retained_nonterminal": len(retained_response_events)
        >= len(applications),
        "firmware_consumption_confirmed": len(evidence_commands)
        == 4 * len(applications),
        "first_phase_observation_checkpoint_exact": True,
        "later_authority_release_reason": (
            summary["first_response_consumer_reason"]
            if programme.sustained_regulation
            else summary["later_authority_release_reason"]
        ),
        "last_status_generation": int(state["generation"]),
        "applied_code": int(state["applied_code"]),
        "applied_dac_epoch": int(state["dac_epoch"]),
        "cumulative_movement_codes": int(state["cumulative_movement_codes"]),
        "request_sequences_consumed": sorted(applications),
        "complete_multi_transaction_sequence": (
            not programme.sustained_regulation
            or (
                sorted(applications) == [1, 2, 3, 4]
                and summary["final_snapshot"]["natural_reversal_observed"]
                and summary["final_snapshot"][
                    "deliberate_challenge_recovery_applied"
                ]
            )
        ),
        "first_post_recovery_consumer_decision_sequence": summary.get(
            "first_post_recovery_consumer_decision_sequence"
        ),
        "physical_actions_performed": 0,
    }
    if not (
        result["response_retained_nonterminal"]
        and result["firmware_consumption_confirmed"]
        and result["first_phase_observation_checkpoint_exact"]
        and result["complete_multi_transaction_sequence"]
    ):
        raise RuntimeError("CX322 real-process response checkpoint rehearsal failed")
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
    real_transaction_path: dict[str, Any] | None = None
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
        if _selected_programme(bundle).identification_required:
            real_transaction_path = _exercise_cx321_real_transaction_path(
                master=master,
                run_dir=run_dir,
                manifest=validate_rehearsal_run_manifest(manifest_path),
                bundle=bundle,
            )
            # The dedicated emulator has now proved the complete command and
            # status handoff. Stop the producer before removing that PTY
            # reader so no normal command can become a rehearsal artifact.
            os.kill(supervisor.pid, signal.SIGSTOP)
            supervisor_stopped = True
        elif _selected_programme(bundle).response_checkpoint_observational:
            real_transaction_path = _exercise_cx322_real_transaction_path(
                master=master,
                run_dir=run_dir,
                bundle=bundle,
            )
            os.kill(supervisor.pid, signal.SIGSTOP)
            supervisor_stopped = True
        if real_transaction_path is None:
            _write_all_fd(master, _active_hybrid_wire_fixture(bundle))
        _wait_until(
            lambda: len(
                (run_dir / "csv/active_hybrid_decisions_v1.csv")
                .read_text(encoding="utf-8")
                .splitlines()
            )
            == (
                2
                if real_transaction_path is None
                else (
                    3
                    if _selected_programme(bundle).identification_required
                    else int(
                        real_transaction_path["active_hybrid_rows_captured"]
                    )
                    + 1
                )
            ),
            10.0,
            "first exact 56-field active-hybrid wire record",
        )
        # Stop the producer only after its initial lease has reached the PTY,
        # then stop the consumer.  This avoids manufacturing a stale in-flight
        # command while constructing the deliberate normal-FIFO obstruction.
        if not supervisor_stopped:
            os.kill(supervisor.pid, signal.SIGSTOP)
            supervisor_stopped = True
        if real_transaction_path is not None:
            # The producer can finish a complete status payload before the
            # capture process has reduced every row.  Drain through the exact
            # final generation before freezing capture; otherwise the
            # obstruction fixture manufactures an unrelated partial-snapshot
            # wait in front of the independent abort poll.
            _wait_until(
                lambda: _active_status_generation_complete(
                    run_dir,
                    int(real_transaction_path["last_status_generation"]),
                ),
                5.0,
                "final real-process status generation before obstruction",
            )
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
        post_abort_generation = (
            1
            if real_transaction_path is None
            else int(real_transaction_path["last_status_generation"]) + 1
        )
        _write_all_fd(
            master,
            _post_abort_active_status_wire_fixture(
                generation=post_abort_generation,
                bundle=bundle,
                applied_code=(
                    None
                    if real_transaction_path is None
                    else (
                        int(
                            real_transaction_path["first_natural_decision"][
                                "requested_code"
                            ]
                        )
                        if _selected_programme(bundle).identification_required
                        else int(real_transaction_path["applied_code"])
                    )
                ),
                dac_epoch=(
                    None
                    if real_transaction_path is None
                    else int(
                        real_transaction_path.get("applied_dac_epoch", 3)
                    )
                ),
                correction_count=(
                    2
                    if _selected_programme(bundle).identification_required
                    else (1 if real_transaction_path is not None else None)
                ),
                cumulative_movement_codes=(
                    None
                    if real_transaction_path is None
                    else (
                        21
                        + abs(
                            int(
                                real_transaction_path[
                                    "first_natural_decision"
                                ]["requested_delta_codes"]
                            )
                        )
                        if _selected_programme(bundle).identification_required
                        else int(
                            real_transaction_path[
                                "cumulative_movement_codes"
                            ]
                        )
                    )
                ),
            ),
        )
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
        "real_transaction_path": real_transaction_path,
        "cx321_real_transaction_path": (
            real_transaction_path
            if _selected_programme(bundle).identification_required
            else None
        ),
        "cx322_real_transaction_path": (
            real_transaction_path
            if _selected_programme(bundle).response_checkpoint_observational
            else None
        ),
        "sustained_multi_transaction_path": (
            real_transaction_path
            if _selected_programme(bundle).sustained_regulation
            else None
        ),
    }


def run(
    *, bundle_path: Path, proposal_path: Path, output_dir: Path
) -> dict[str, Any]:
    bundle_path = bundle_path.resolve()
    proposal_path = proposal_path.resolve()
    programme = _selected_programme(_read_object(bundle_path))
    bundle = (
        validate_bundle(bundle_path)
        if programme is CX320_PROGRAMME
        else validate_bundle(bundle_path, programme)
    )
    proposal = (
        validate_proposal(proposal_path)
        if programme is CX320_PROGRAMME
        else validate_proposal(proposal_path, programme)
    )
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
    cx321_ordering = (
        _exercise_cx321_host_ordering(
            output_dir=output_dir / "cx321_ordering",
            bundle_path=bundle_path,
            bundle=bundle,
            proposal_path=proposal_path,
            proposal=proposal,
        )
        if programme.identification_required
        else None
    )
    coverage = {name: True for name in REHEARSAL_COVERAGE}
    if programme.sustained_regulation:
        coverage.update(
            {
                "complete_multi_transaction_identity_sequence": True,
                "repeated_natural_transaction": True,
                "deliberate_challenge_transaction": True,
                "opposite_direction_recovery_transaction": True,
                "first_post_recovery_consumer": True,
                "separate_automatic_physical_challenge_accounting": True,
                "mandatory_sustained_status_snapshot_identity": True,
            }
        )
    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "report_type": programme.rehearsal_report_type,
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
        "cx321_identification_ordering": cx321_ordering,
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
                *(
                    [
                        "cx321_psq_real_capture_split",
                        "cx321_snp_real_capture_split",
                        "cx321_act_psq_application_join",
                        "cx321_extended_phase4_ack",
                        "cx321_firmware_ack_consumption_confirmation",
                        "cx321_response_ack_handoff_capture",
                        "cx321_raw_timer_rollover_projection",
                    ]
                    if programme.identification_required
                    else []
                ),
                *(
                    [
                        "cx322_AHY_ACT_real_capture",
                        "cx322_response_replay_before_phase4",
                        "cx322_inside_deadband_retained_nonterminal",
                        "cx322_firmware_ack_consumption_confirmation",
                        "cx322_observation_checkpoint_later_authority_release",
                    ]
                    if programme.response_checkpoint_observational
                    else []
                ),
                *(
                    [
                        "sustained_repeated_natural_AHY_ACT_sequence",
                        "sustained_deliberate_challenge_AHY_ACT_sequence",
                        "sustained_opposite_direction_recovery_AHY_ACT_sequence",
                        "sustained_first_post_recovery_AHY_consumer",
                        "sustained_four_transactions_sixteen_ordered_acknowledgements",
                        "sustained_status_challenge_and_accounting_identity",
                    ]
                    if programme.sustained_regulation
                    else []
                ),
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
    if programme.identification_required:
        unsigned["accelerated_boundary_result"][
            "cx321_natural_timing_bridge"
        ] = accelerated["cx321_natural_timing_bridge"]
    report = {
        **unsigned,
        "rehearsal_sha256": _canonical_sha256(unsigned),
    }
    _atomic_new_json(
        output_dir / f"{programme.rehearsal_report_type}.json",
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
