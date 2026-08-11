"""Fail-static supervisor for Stage 7 dual-core confirmation/endurance.

The capture process remains the sole serial owner.  This supervisor only uses
the command FIFO and the independent ABORT-only FIFO.  Every ACT phase is
fsynced into an immutable capsule before the corresponding release crosses to
the device.  Shadow analysis is deliberately absent from this authority path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import json
import secrets
import time
from typing import Any

from .contracts import CsvValidationContext, validate_csv
from .cx317_abort_path import AbortFifo
from .cx317_active_campaign import (
    ACTIVE_CSV,
    ARM_PROGRESS_THRESHOLD,
    HEALTH_CSV,
    LEASE_PERIOD_S,
    QUERY_PERIOD_S,
    ActiveCampaignSupervisor,
    CampaignSpec,
    _latest_health,
    _read_csv,
    _utc_now,
    validate_transaction_history,
    validate_transaction_row,
)
from .run_loader import CAPTURE_IN_PROGRESS_FLAG
from .serial_commands import send_timestamped_command_to_fifo
from .timebase import unwrap_ticks


REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "profiles/discipline/cx317_bounded_active_v2.json"
REHEARSAL_POLICY_PATH = (
    REPO_ROOT / "profiles/discipline/cx317_stage7_rehearsal_v1.json"
)
CONTROL_CSV = Path("csv/control_previews_v1.csv")
ESTIMATES_CSV = Path("csv/estimates_v2.csv")
DAC_CSV = Path("csv/dac_steps.csv")
PART_B_DURATION_S = 24 * 60 * 60
BOUNDED_ACTIVE_QUALIFICATION_TIMEOUT_S = 90 * 60
PART_A_QUALIFIED_TIMEOUT_S = 4 * 60 * 60
PART_B_CLEARANCE_GRACE_S = 60 * 60
PART_A_SERVICE_LOAD_QUERIES = 60
PART_B_SERVICE_LOAD_STARTS_S = (3600, 25200, 46800, 68400)
PART_B_SERVICE_LOAD_QUERIES = 60
SELECTED_INTERVAL_S = 600
DECISION_CADENCE_S = 1800
REHEARSAL_SELECTED_INTERVAL_S = 120
REHEARSAL_DECISION_CADENCE_S = 240
REHEARSAL_ARM_PROGRESS_THRESHOLD = 105
REHEARSAL_QUALIFICATION_TIMEOUT_S = 7 * 60
REHEARSAL_QUALIFIED_TIMEOUT_S = 20 * 60
REHEARSAL_FC0_STARTUP_INHIBIT_S = 60
REHEARSAL_FC0_CONTROL_READY_CLEAN_WINDOWS = 3
REHEARSAL_STARTUP_WARMUP_S = 60
ACTIVE_ARM_LIFETIME_S = 110
CAPTURE_TRANSPORT_STATE = Path("reports/capture_device_state.json")
CAPTURE_TRANSPORT_STATE_MAX_AGE_S = 15
NORMAL_COMMAND_ACK_TIMEOUT_S = 3.0
NORMAL_COMMAND_ACK_POLL_S = 0.02
RP2040_TIMER0_TICKS_PER_SECOND = 16_000_000
REAL_FC0_STARTUP_INHIBIT_S = 600
REAL_FC0_CONTROL_READY_CLEAN_WINDOWS = 3
REAL_STARTUP_WARMUP_S = 1800


@dataclass(frozen=True)
class BoundedActiveTiming:
    selected_interval_s: int
    decision_cadence_s: int
    arm_progress_threshold: int
    qualification_timeout_s: int
    qualified_timeout_s: int
    service_load_queries: int
    service_query_period_s: float


def bounded_active_timing(part: str) -> BoundedActiveTiming:
    if part == "rehearsal":
        return BoundedActiveTiming(
            selected_interval_s=REHEARSAL_SELECTED_INTERVAL_S,
            decision_cadence_s=REHEARSAL_DECISION_CADENCE_S,
            arm_progress_threshold=REHEARSAL_ARM_PROGRESS_THRESHOLD,
            qualification_timeout_s=REHEARSAL_QUALIFICATION_TIMEOUT_S,
            qualified_timeout_s=REHEARSAL_QUALIFIED_TIMEOUT_S,
            service_load_queries=PART_A_SERVICE_LOAD_QUERIES,
            service_query_period_s=1.0,
        )
    if part in {"part_a", "part_b"}:
        return BoundedActiveTiming(
            selected_interval_s=SELECTED_INTERVAL_S,
            decision_cadence_s=DECISION_CADENCE_S,
            arm_progress_threshold=ARM_PROGRESS_THRESHOLD,
            qualification_timeout_s=BOUNDED_ACTIVE_QUALIFICATION_TIMEOUT_S,
            qualified_timeout_s=(
                PART_A_QUALIFIED_TIMEOUT_S
                if part == "part_a"
                else PART_B_DURATION_S + PART_B_CLEARANCE_GRACE_S
            ),
            service_load_queries=(
                PART_A_SERVICE_LOAD_QUERIES
                if part == "part_a"
                else PART_B_SERVICE_LOAD_QUERIES
            ),
            service_query_period_s=1.0,
        )
    raise ValueError(f"unsupported Stage 7 part {part!r}")


def rehearsal_timeline_preflight(
    policy: dict[str, object] | None = None,
) -> dict[str, object]:
    """Prove the accelerated cross-layer sequence fits every frozen clock."""
    if policy is None:
        policy = json.loads(REHEARSAL_POLICY_PATH.read_text(encoding="utf-8"))
    timing = policy.get("timing_s", {})
    if not isinstance(timing, dict):
        timing = {}
    expected = {
        "pps_backend_startup_inhibit": REHEARSAL_FC0_STARTUP_INHIBIT_S,
        "pps_backend_control_ready_clean_windows": (
            REHEARSAL_FC0_CONTROL_READY_CLEAN_WINDOWS
        ),
        "startup_warmup": REHEARSAL_STARTUP_WARMUP_S,
        "selected_span": REHEARSAL_SELECTED_INTERVAL_S,
        "settling_exclusion": 60,
        "full_history_reset": 180,
        "recovery_fresh_support": 120,
        "decision_cadence": REHEARSAL_DECISION_CADENCE_S,
        "minimum_applied_correction_cadence": 240,
        "qualification_timeout": REHEARSAL_QUALIFICATION_TIMEOUT_S,
        "qualified_timeout": REHEARSAL_QUALIFIED_TIMEOUT_S,
    }
    values = {
        key: int(timing.get(key, -1))
        for key in expected
    }
    lower_layer_ready_s = (
        values["pps_backend_startup_inhibit"]
        + values["pps_backend_control_ready_clean_windows"]
    )
    first_arm_window_s = max(
        lower_layer_ready_s,
        values["startup_warmup"] + REHEARSAL_ARM_PROGRESS_THRESHOLD,
    )
    first_actionable_decision_s = (
        values["startup_warmup"] + values["selected_span"]
    )
    response_ready_after_application_s = max(
        values["full_history_reset"],
        values["settling_exclusion"]
        + values["recovery_fresh_support"],
    )
    conservative_post_application_completion_s = (
        response_ready_after_application_s
        + values["decision_cadence"]
        + values["selected_span"]
        + response_ready_after_application_s
        + PART_A_SERVICE_LOAD_QUERIES
        + values["decision_cadence"]
    )
    checks = {
        "policy_timers_exact": values == expected,
        "lower_layer_ready_before_arm_window": (
            lower_layer_ready_s
            <= values["startup_warmup"] + REHEARSAL_ARM_PROGRESS_THRESHOLD
        ),
        "arm_window_precedes_first_actionable_decision": (
            first_arm_window_s < first_actionable_decision_s
        ),
        "arm_lifetime_covers_first_actionable_decision": (
            first_actionable_decision_s - first_arm_window_s
            < ACTIVE_ARM_LIFETIME_S
        ),
        "first_actionable_decision_precedes_qualification_timeout": (
            first_actionable_decision_s
            < values["qualification_timeout"]
        ),
        "response_service_and_later_decision_fit_qualified_timeout": (
            conservative_post_application_completion_s
            < values["qualified_timeout"]
        ),
        "complete_sequence_fits_manifest_wall_clock": (
            first_actionable_decision_s
            + conservative_post_application_completion_s
            < values["qualification_timeout"]
            + values["qualified_timeout"]
        ),
    }
    return {
        "checks": checks,
        "derived_s": {
            "lower_layer_ready": lower_layer_ready_s,
            "first_arm_window": first_arm_window_s,
            "first_actionable_decision": first_actionable_decision_s,
            "response_ready_after_application": (
                response_ready_after_application_s
            ),
            "conservative_post_application_completion": (
                conservative_post_application_completion_s
            ),
        },
    }


def part_b_timeline_preflight(
    policy: dict[str, object] | None = None,
) -> dict[str, object]:
    """Prove the exact 24-hour control sequence has no terminal dead end.

    This is deliberately independent of the live clock.  It binds the lower
    layer, estimator, controller, service-load and post-duration response
    clocks before a Part B artifact can be accepted.
    """
    if policy is None:
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    parameters = policy.get("parameters", {})
    if not isinstance(parameters, dict):
        parameters = {}
    expected = {
        "startup_warmup_s": 1800,
        "settling_exclusion_s": 900,
        "fresh_support_after_settling_s": 600,
        "full_history_reset_s": 1500,
        "minimum_applied_correction_cadence_s": 1800,
        "arming_maximum_lifetime_s": 120,
    }
    values = {key: int(parameters.get(key, -1)) for key in expected}
    lower_layer_ready_s = (
        REAL_FC0_STARTUP_INHIBIT_S
        + REAL_FC0_CONTROL_READY_CLEAN_WINDOWS
    )
    earliest_qualification_s = max(
        lower_layer_ready_s,
        values["startup_warmup_s"] + SELECTED_INTERVAL_S,
    )
    response_ready_after_application_s = max(
        values["full_history_reset_s"],
        values["settling_exclusion_s"]
        + values["fresh_support_after_settling_s"],
    )
    conservative_boundary_transaction_clear_s = (
        values["arming_maximum_lifetime_s"]
        + response_ready_after_application_s
    )
    final_service_burst_complete_s = (
        max(PART_B_SERVICE_LOAD_STARTS_S)
        + PART_B_SERVICE_LOAD_QUERIES
    )
    maximum_wall_clock_s = (
        BOUNDED_ACTIVE_QUALIFICATION_TIMEOUT_S
        + PART_B_DURATION_S
        + PART_B_CLEARANCE_GRACE_S
    )
    checks = {
        "policy_timers_exact": values == expected,
        "lower_layer_ready_before_first_qualification": (
            lower_layer_ready_s < earliest_qualification_s
        ),
        "first_qualification_precedes_deadline": (
            earliest_qualification_s < BOUNDED_ACTIVE_QUALIFICATION_TIMEOUT_S
        ),
        "service_bursts_strictly_increase": (
            tuple(sorted(set(PART_B_SERVICE_LOAD_STARTS_S)))
            == PART_B_SERVICE_LOAD_STARTS_S
        ),
        "all_service_bursts_finish_before_24h": (
            final_service_burst_complete_s < PART_B_DURATION_S
        ),
        "qualified_duration_contains_whole_selected_intervals": (
            PART_B_DURATION_S % SELECTED_INTERVAL_S == 0
        ),
        "qualified_duration_contains_whole_decision_cadences": (
            PART_B_DURATION_S % DECISION_CADENCE_S == 0
        ),
        "clearance_covers_boundary_transaction_response": (
            conservative_boundary_transaction_clear_s
            < PART_B_CLEARANCE_GRACE_S
        ),
        "absolute_wall_clock_is_exactly_bounded": (
            maximum_wall_clock_s == 26 * 60 * 60 + 30 * 60
        ),
    }
    return {
        "checks": checks,
        "derived_s": {
            "lower_layer_ready": lower_layer_ready_s,
            "earliest_qualification": earliest_qualification_s,
            "service_burst_starts": list(PART_B_SERVICE_LOAD_STARTS_S),
            "final_service_burst_complete": final_service_burst_complete_s,
            "qualified_duration": PART_B_DURATION_S,
            "response_ready_after_application": (
                response_ready_after_application_s
            ),
            "conservative_boundary_transaction_clear": (
                conservative_boundary_transaction_clear_s
            ),
            "clearance_grace": PART_B_CLEARANCE_GRACE_S,
            "maximum_wall_clock": maximum_wall_clock_s,
        },
    }


def load_cx317_bounded_active_spec(part: str, start_code: int) -> tuple[CampaignSpec, dict[str, str]]:
    if part not in {"part_a", "part_b", "rehearsal"}:
        raise ValueError(f"unsupported Stage 7 part {part!r}")
    if not 0xA800 <= start_code <= 0xAB00:
        raise ValueError("Stage 7 start code is outside A800..AB00")
    if part in {"part_a", "rehearsal"} and start_code != 0xA800:
        raise ValueError(
            f"Stage 7 {part} requires the frozen exact A800 start"
        )
    policy_path = REHEARSAL_POLICY_PATH if part == "rehearsal" else POLICY_PATH
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    if part == "rehearsal":
        timeline = rehearsal_timeline_preflight(policy)
        if not all(timeline["checks"].values()):
            raise ValueError(
                "Stage 7 rehearsal cross-layer timeline is unsatisfiable: "
                + json.dumps(timeline, sort_keys=True)
            )
        bindings = policy["bindings"]
        policy_hash = sha256(policy_path.read_bytes()).hexdigest()
        return CampaignSpec(
            campaign="stage7_rehearsal",
            profile="cx317_dual_core_active_rehearsal",
            run_identity="cx317_stage7_rehearsal:3170005",
            start_code=start_code,
            correction_limit=2,
            cumulative_limit=42,
            minimum_code=0xA800,
            maximum_code=0xAB00,
            maximum_step=21,
        ), {
            "estimator_sha256": bindings["selected_estimator_sha256"],
            "model_sha256": bindings["plant_model_sha256"],
            "active_policy_sha256": policy_hash,
            "response_policy_sha256": bindings["response_policy_sha256"],
            "numerical_policy_sha256": policy_hash,
        }
    if part == "part_b":
        timeline = part_b_timeline_preflight(policy)
        if not all(timeline["checks"].values()):
            raise ValueError(
                "Stage 7 Part B cross-layer timeline is unsatisfiable: "
                + json.dumps(timeline, sort_keys=True)
            )
    is_a = part == "part_a"
    spec = CampaignSpec(
        campaign=f"stage7_{part}",
        profile=(
            "cx317_dual_core_active_part_a"
            if is_a
            else "cx317_dual_core_active_endurance_part_b"
        ),
        run_identity=(
            "cx317_stage7_part_a:3170003"
            if is_a
            else "cx317_stage7_part_b:3170004"
        ),
        start_code=start_code,
        correction_limit=4 if is_a else 32,
        cumulative_limit=84 if is_a else 672,
        minimum_code=0xA800,
        maximum_code=0xAB00,
        maximum_step=21,
    )
    bindings = policy["bindings"]
    return spec, {
        "estimator_sha256": bindings["selected_estimator_sha256"],
        "model_sha256": bindings["plant_model_sha256"],
        "active_policy_sha256": sha256(POLICY_PATH.read_bytes()).hexdigest(),
        "response_policy_sha256": bindings["response_policy_sha256"],
        "numerical_policy_sha256": bindings["numerical_preview_policy_sha256"],
    }


def _latest_preview(path: Path) -> dict[str, str] | None:
    rows = _read_csv(path)
    return rows[-1] if rows else None


def _next_selected_interval_is_cadence_eligible(
    controls_path: Path,
    estimates_path: Path,
    *,
    selected_interval_s: int = SELECTED_INTERVAL_S,
    decision_cadence_s: int = DECISION_CADENCE_S,
) -> bool:
    """Conservatively predict whether an arm can be consumed next interval.

    The device only consumes an authorization when the controller evaluates an
    eligible decision.  Selected estimates arrive every 600 seconds, while the
    frozen controller decision cadence is 1800 seconds.  Arming before either
    intervening cadence-hold interval leaves the one-shot authorization unused
    and therefore correctly faults when its short lifetime expires.

    Firmware evaluates integer uptime seconds, not the PPS source sequence.
    The source sequence is a count identity and can lead or lag uptime by
    several seconds during a long run.  CTL timestamps are emitted from the
    same monotonic RP2040 timer domain used to derive uptime.  Project the next
    boundary with the shortest observed selected-interval spacing and require
    its floored second to satisfy the cadence.  This deliberately defers an
    ambiguous nominal 1800-second boundary by one selected interval rather
    than granting an authorization that firmware may classify as a hold.
    """
    del estimates_path  # retained in the API for callers and historical tests
    rows = _read_csv(controls_path)
    if not rows:
        return False
    eligible = [row for row in rows if row.get("preview_available") == "true"]
    if not eligible:
        return True
    try:
        ticks, _ = unwrap_ticks(
            [int(row["decision_timestamp_ticks"]) for row in rows]
        )
        eligible_index = max(
            index
            for index, row in enumerate(rows)
            if row.get("preview_available") == "true"
        )
    except (KeyError, TypeError, ValueError):
        return False
    positive_spacings = [
        later - earlier
        for earlier, later in zip(ticks, ticks[1:])
        if later > earlier
    ]
    conservative_spacing = min(
        positive_spacings,
        default=selected_interval_s * RP2040_TIMER0_TICKS_PER_SECOND,
    )
    projected_next_s = (
        ticks[-1] + conservative_spacing
    ) // RP2040_TIMER0_TICKS_PER_SECOND
    last_eligible_s = (
        ticks[eligible_index] // RP2040_TIMER0_TICKS_PER_SECOND
    )
    return projected_next_s - last_eligible_s >= decision_cadence_s


def _parse_utc_epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


class Cx317BoundedActiveSupervisor(ActiveCampaignSupervisor):
    def __init__(self, *, part: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.part = part
        self.timing = bounded_active_timing(part)
        self._last_arm_monotonic: float | None = None
        self._live_command_ack_required = False
        self._arm_progress_control_ref: str | None = None
        self._arm_progress_reset_seen = False
        self._next_service_command_monotonic = 0.0
        self.state.setdefault("stage7_part", part)
        self.state.setdefault("response_count", 0)
        self.state.setdefault("supervisor_started_utc", _utc_now())
        self.state.setdefault("qualification_started_utc", None)
        self.state.setdefault("part_a_service_load_sent", 0)
        self.state.setdefault("part_a_service_load_complete", False)
        self.state.setdefault("part_a_service_load_completed_control_seq", None)
        self.state.setdefault("part_a_post_service_eligible_control_seq", None)
        self.state.setdefault("part_b_service_bursts_complete", [])
        self.state.setdefault("part_b_service_burst_sent", 0)
        self.state.setdefault("part_b_service_burst_index", None)
        self.state.setdefault("part_b_arm_resume_after_control_seq", None)
        self.state.setdefault("duration_elapsed", False)
        self.state.setdefault("arm_sent_at_utc", None)
        self._save()

    def _command(self, command: str) -> None:
        before = (
            self._check_capture_transport_state()
            if self._live_command_ack_required
            else None
        )
        send_timestamped_command_to_fifo(self.command_fifo, command)
        self._event("command_submitted", command=command)
        if before is None:
            return
        before_sent = int(before["commands_sent"])
        deadline = time.monotonic() + NORMAL_COMMAND_ACK_TIMEOUT_S
        while True:
            current = self._check_capture_transport_state()
            sent = int(current["commands_sent"])
            if sent == before_sent + 1:
                self._event(
                    "command_acknowledged",
                    command=command,
                    commands_sent=sent,
                )
                return
            if sent != before_sent:
                raise ValueError(
                    "capture command acknowledgement sequence changed "
                    f"unexpectedly: before={before_sent} current={sent}"
                )
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "capture did not acknowledge the fresh normal command "
                    f"within {NORMAL_COMMAND_ACK_TIMEOUT_S:.1f} s: {command}"
                )
            time.sleep(NORMAL_COMMAND_ACK_POLL_S)

    def _check_capture_transport_state(self) -> dict[str, Any]:
        path = self.run_dir / CAPTURE_TRANSPORT_STATE
        if not path.is_file():
            raise ValueError("capture transport state is missing")
        state = json.loads(path.read_text(encoding="utf-8"))
        age_s = time.time() - _parse_utc_epoch(str(state["updated_utc"]))
        if age_s < -1 or age_s > CAPTURE_TRANSPORT_STATE_MAX_AGE_S:
            raise ValueError(
                f"capture transport state is stale: age_s={age_s:.3f}"
            )
        exact = {
            "capture_active": True,
            "serial_open": True,
            "command_fifo_configured": True,
            "emergency_command_fifo_configured": True,
            "state_heartbeat_interval_s": 5.0,
            "normal_command_batch_limit": 1,
            "normal_command_max_age_s": 2.0,
            "write_timeout_s": 1.0,
        }
        for key, expected in exact.items():
            if state.get(key) != expected:
                raise ValueError(
                    "capture transport state mismatch: "
                    f"{key}={state.get(key)!r}, expected {expected!r}"
                )
        for key in (
            "malformed_utf8",
            "parser_errors",
            "reconnect_count",
            "commands_rejected",
            "emergency_aborts_sent",
        ):
            if int(state.get(key, -1)) != 0:
                raise ValueError(
                    f"capture transport counter {key} is {state.get(key)!r}"
                )
        return state

    def _arm_progress_epoch_ready(
        self, preview: dict[str, str] | None, progress: int
    ) -> bool:
        """Require a fresh estimator-progress reset after every control row.

        CTL transport and ACTIVE? health transport are independent.  A newly
        received CTL can therefore be paired briefly with the preceding
        selected_interval_count=598 status.  Treating that stale high-water
        value as progress toward the *next* selected estimate arms just after
        the decision instead of just before the following one.  A low progress
        observation after the latest CTL proves that the next estimator epoch
        has actually begun; fail conservatively until that reset is observed.
        """
        control_ref = None
        if preview is not None:
            control_ref = preview.get("decision_id") or preview.get("control_seq")
        if control_ref != self._arm_progress_control_ref:
            self._arm_progress_control_ref = control_ref
            self._arm_progress_reset_seen = False
        if progress < self.timing.arm_progress_threshold:
            self._arm_progress_reset_seen = True
        return self._arm_progress_reset_seen

    def _process_transactions(self) -> None:
        path = self.run_dir / ACTIVE_CSV
        if not path.exists():
            return
        validation = validate_csv(
            path,
            CsvValidationContext(
                "active_transactions_v1", frozenset(), frozenset()
            ),
        )
        if validation.errors:
            raise ValueError(
                "ACT contract validation failed: " + "; ".join(validation.errors)
            )
        rows = _read_csv(path)
        validate_transaction_history(
            rows,
            self.spec,
            self.identities,
            self.expected_build_identity,
            dual_core=True,
        )
        acknowledged = set(self.state["acknowledged_record_sequences"])
        observed_manual = set(self.state["observed_manual_record_sequences"])
        for row in rows:
            record_sequence = int(row["transaction_record_sequence"])
            validate_transaction_row(
                row, self.spec, self.identities, self.expected_build_identity
            )
            event = row["event"]
            if event == "manual_start":
                if record_sequence in observed_manual:
                    continue
                self._event(
                    "manual_start_observed",
                    record_sequence=record_sequence,
                    applied_code=int(row["applied_code"]),
                )
                self.state["observed_manual_record_sequences"].append(
                    record_sequence
                )
                self.state["observed_manual_record_sequences"].sort()
                self._save()
                continue
            if record_sequence in acknowledged:
                continue
            phase = {
                "request_created": 1,
                "core0_accepted": 2,
                "application": 3,
                "application_fault": 3,
                "response": 4,
            }.get(event)
            if phase is None:
                raise ValueError(f"unexpected Stage 7 ACT event {event!r}")
            self._preserve_and_acknowledge(row, phase)
            if event == "request_created":
                self._event(
                    "core1_request_released_after_durable_capsule",
                    request_sequence=int(row["request_sequence"]),
                    requested_code=int(row["requested_code"]),
                    delta_codes=int(row["requested_delta_codes"]),
                )
            elif event == "core0_accepted":
                self._event(
                    "core0_acceptance_released_after_durable_capsule",
                    request_sequence=int(row["request_sequence"]),
                    accepted_code=int(row["accepted_code"]),
                )
            elif event == "application_fault":
                raise ValueError("Core 0 single I2C application attempt failed")
            elif event == "application":
                self.state["arm_pending"] = False
                self.state["arm_sent_at_utc"] = None
                self._last_arm_monotonic = None
                self._save()
                self._event(
                    "cross_core_application_confirmed",
                    request_sequence=int(row["request_sequence"]),
                    applied_code=int(row["applied_code"]),
                    correction_count=int(row["correction_count"]),
                    cumulative_movement_codes=int(
                        row["cumulative_movement_codes"]
                    ),
                )
            elif event == "response":
                classification = row["response_class"]
                active_state = row["active_state"]
                self.state["response_count"] += 1
                self._event(
                    "response_classified",
                    request_sequence=int(row["request_sequence"]),
                    response_class=classification,
                    post_error_hz=float(row["post_error_hz"]),
                    observed_response_hz=float(row["observed_response_hz"]),
                    response_count=self.state["response_count"],
                )
                if active_state == "OUT_OF_MODEL_HOLD":
                    self.state["terminal"] = {
                        "result": "held",
                        "reason": "out_of_model_hold",
                        "utc": _utc_now(),
                    }
                elif classification in {
                    "wrong_sign",
                    "excess_response",
                    "growing_error",
                    "measurement_or_actuator_fault",
                }:
                    self.state["terminal"] = {
                        "result": "fault",
                        "reason": classification,
                        "utc": _utc_now(),
                    }
                self._save()

    def _maybe_qualify(
        self,
        health: dict[tuple[str, str], str],
        preview: dict[str, str] | None,
    ) -> None:
        if self.state["qualification_started_utc"] is not None:
            return
        if not self._identity_ready(health) or preview is None:
            return
        if (
            health.get(("cx317_active", "manual_start_confirmed")) == "true"
            and preview.get("preview_available") == "true"
            and preview.get("model_applicability") == "applicable"
            and preview.get("diagnostic_health") == "healthy"
        ):
            self.state["qualification_started_utc"] = _utc_now()
            self._save()
            self._event(
                "warmup_and_qualification_complete",
                decision_id=preview.get("decision_id"),
                frequency_error_hz=preview.get("frequency_error_hz"),
            )

    def _check_fail_static_health(
        self, health: dict[tuple[str, str], str]
    ) -> None:
        faults = {
            "dual_core_partition": health.get(
                ("dual_core", "partition_fault")
            ),
            "dual_core_fail_static": health.get(
                ("dual_core", "fail_static")
            ),
            "active_fail_static": health.get(
                ("cx317_active", "fail_static")
            ),
            "capture_dropped": health.get(("capture", "dropped_count")),
            "boundary_dropped": health.get(
                ("capture", "pps_count_boundary_dropped_count")
            ),
            "telemetry_dropped": health.get(
                ("dual_core", "telemetry_dropped")
            ),
        }
        if faults["dual_core_partition"] not in {None, "none"}:
            raise ValueError(
                "dual-core partition fault: "
                f"{faults['dual_core_partition']}"
            )
        for key in ("dual_core_fail_static", "active_fail_static"):
            if faults[key] == "true":
                raise ValueError(f"live {key} asserted")
        for key in ("capture_dropped", "boundary_dropped"):
            if faults[key] not in {None, "0"}:
                raise ValueError(f"live {key} is {faults[key]}")
        if not self._telemetry_drop_runtime_healthy(
            faults["telemetry_dropped"]
        ):
            raise ValueError(
                f"live telemetry_dropped is {faults['telemetry_dropped']}"
            )

    def _telemetry_drop_runtime_healthy(self, observed: str | None) -> bool:
        """Campaign hook; Stage 7 retains its absolute zero requirement."""

        return observed in {None, "0"}

        if self.state["manual_start_sent"]:
            manual_rows = [
                row
                for row in _read_csv(self.run_dir / DAC_CSV)
                if row.get("event") in {"manual_apply", "manual_write_failed"}
            ]
            if manual_rows and manual_rows[-1]["event"] != "manual_apply":
                raise ValueError("one-shot manual start DAC write failed")

    def _service_load(self, now: float) -> None:
        if now < self._next_service_command_monotonic:
            return
        if self.part in {"part_a", "rehearsal"}:
            required_responses = 2 if self.part == "rehearsal" else 1
            if self.state["response_count"] < required_responses or self.state[
                "part_a_service_load_complete"
            ]:
                return
            sent = int(self.state["part_a_service_load_sent"])
            if sent < self.timing.service_load_queries:
                self._command("CONFIG?")
                self.state["part_a_service_load_sent"] = sent + 1
                self._next_service_command_monotonic = (
                    now + self.timing.service_query_period_s
                )
                self._save()
                return
            self.state["part_a_service_load_complete"] = True
            preview = _latest_preview(self.run_dir / CONTROL_CSV)
            self.state["part_a_service_load_completed_control_seq"] = (
                int(preview["control_seq"]) if preview is not None else -1
            )
            self._save()
            self._event(
                "part_a_bounded_service_load_complete",
                query_count=self.timing.service_load_queries,
                control_seq=self.state[
                    "part_a_service_load_completed_control_seq"
                ],
            )
            return

        qualified = self.state["qualification_started_utc"]
        if qualified is None:
            return
        elapsed = time.time() - _parse_utc_epoch(qualified)
        complete = set(self.state["part_b_service_bursts_complete"])
        active_index = self.state["part_b_service_burst_index"]
        if active_index is None:
            # Never begin the high-volume service snapshot while a one-shot
            # authorization is live.  The burst may start late; it must not
            # consume most of the authorization lifetime or hide its outcome.
            if self.state["arm_pending"]:
                return
            active_index = next(
                (
                    index
                    for index, start in enumerate(PART_B_SERVICE_LOAD_STARTS_S)
                    if elapsed >= start and index not in complete
                ),
                None,
            )
            if active_index is None:
                return
            self.state["part_b_service_burst_index"] = active_index
            self.state["part_b_service_burst_sent"] = 0
            self._save()
            self._event(
                "part_b_service_load_started",
                burst_index=active_index,
                elapsed_s=int(elapsed),
            )
        sent = int(self.state["part_b_service_burst_sent"])
        if sent < PART_B_SERVICE_LOAD_QUERIES:
            self._command("CONFIG?")
            self.state["part_b_service_burst_sent"] = sent + 1
            self._next_service_command_monotonic = now + 1.0
            self._save()
            return
        complete.add(int(active_index))
        self.state["part_b_service_bursts_complete"] = sorted(complete)
        self.state["part_b_service_burst_index"] = None
        self.state["part_b_service_burst_sent"] = 0
        preview = _latest_preview(self.run_dir / CONTROL_CSV)
        self.state["part_b_arm_resume_after_control_seq"] = (
            int(preview["control_seq"]) if preview is not None else -1
        )
        self._save()
        self._event(
            "part_b_service_load_complete",
            burst_index=active_index,
            query_count=PART_B_SERVICE_LOAD_QUERIES,
            arm_resume_after_control_seq=self.state[
                "part_b_arm_resume_after_control_seq"
            ],
        )

    def _maybe_start_or_arm(
        self, health: dict[tuple[str, str], str]
    ) -> None:
        if not self._identity_ready(health):
            return
        state = health.get(("cx317_active", "state"), "")
        reason = health.get(("cx317_active", "reason"), "")
        if state in {"FAULT", "ABORTED"}:
            raise ValueError(f"device active state {state.lower()}: {reason}")
        if state == "OUT_OF_MODEL_HOLD":
            self.state["terminal"] = {
                "result": "held",
                "reason": reason or "out_of_model_hold",
                "utc": _utc_now(),
            }
            self._save()
            return

        manual_confirmed = (
            health.get(("cx317_active", "manual_start_confirmed")) == "true"
        )
        preview = _latest_preview(self.run_dir / CONTROL_CSV)
        if (
            self.allow_manual_start
            and not manual_confirmed
            and not self.state["manual_start_sent"]
            and state == "DISARMED"
        ):
            if preview is not None:
                raise ValueError(
                    "manual-start window missed: a controller decision "
                    "already exists"
                )
            uptime = int(health.get(("cx317_active", "uptime_s"), "-1"))
            startup_warmup_s = (
                REHEARSAL_STARTUP_WARMUP_S
                if self.part == "rehearsal"
                else REAL_STARTUP_WARMUP_S
            )
            if uptime < 0 or (
                uptime + NORMAL_COMMAND_ACK_TIMEOUT_S >= startup_warmup_s
            ):
                raise ValueError(
                    "manual-start deadline missed: "
                    f"uptime={uptime} warmup={startup_warmup_s}"
                )
            self._command(f"DAC SET 0x{self.spec.start_code:04X}")
            self.state["manual_start_sent"] = True
            self._save()
            self._event("manual_start_requested", code=self.spec.start_code)
            return

        if self.state["arm_pending"] and state == "DISARMED":
            sent_at = self.state.get("arm_sent_at_utc")
            age = (
                time.time() - _parse_utc_epoch(sent_at)
                if isinstance(sent_at, str) and sent_at
                else 0.0
            )
            if age > 120.0:
                self.state["arm_pending"] = False
                self.state["arm_sent_at_utc"] = None
                self._last_arm_monotonic = None
                self._save()
                self._event("unused_zero_delta_arm_consumed_without_write")
        if (
            not self.allow_arm
            or not manual_confirmed
            or self.state["arm_pending"]
            or self.state["duration_elapsed"]
        ):
            return
        # Part A's post-service decision is an observation/terminal gate, not
        # another actuation criterion.  Once the bounded service interval is
        # complete, wait for _maybe_finish() to observe the next eligible
        # preview and stop before granting a new authorization even when that
        # preview proposes a non-zero correction.
        if self.part in {"part_a", "rehearsal"} and self.state[
            "part_a_service_load_complete"
        ]:
            return

        correction_count = int(
            health.get(("cx317_active", "correction_count"), "0")
        )
        if correction_count >= self.spec.correction_limit:
            return
        if preview is not None and preview.get("control_state") == "FAULT":
            raise ValueError(
                "latest controller decision is faulted: "
                f"{preview.get('decision_reason_code', 'unavailable')}"
            )
        if self.part == "part_b":
            if self.state["part_b_service_burst_index"] is not None:
                return
            resume_after = self.state.get(
                "part_b_arm_resume_after_control_seq"
            )
            if resume_after is not None:
                try:
                    latest_control_seq = int(preview["control_seq"])
                except (KeyError, TypeError, ValueError):
                    return
                if latest_control_seq <= int(resume_after):
                    return
                self.state["part_b_arm_resume_after_control_seq"] = None
                self._save()
                self._event(
                    "part_b_post_service_control_observed_arm_resumed",
                    control_seq=latest_control_seq,
                )
        progress = int(
            health.get(("cx317_active", "selected_interval_count"), "0")
        )
        arm_progress_epoch_ready = self._arm_progress_epoch_ready(
            preview, progress
        )
        if preview is not None:
            try:
                limited_delta = int(preview.get("limited_delta_codes") or "0")
            except ValueError:
                limited_delta = 0
            if preview.get("preview_available") == "true" and limited_delta == 0:
                return
        arm_eligible = health.get(("cx317_active", "arm_eligible")) == "true"
        evidence_clear = (
            health.get(("cx317_active", "evidence_phase")) == "evidence_clear"
        )
        if (
            state == "DISARMED"
            and arm_eligible
            and evidence_clear
            and progress >= self.timing.arm_progress_threshold
            and arm_progress_epoch_ready
            and _next_selected_interval_is_cadence_eligible(
                self.run_dir / CONTROL_CSV,
                self.run_dir / ESTIMATES_CSV,
                selected_interval_s=self.timing.selected_interval_s,
                decision_cadence_s=self.timing.decision_cadence_s,
            )
        ):
            uptime = int(health[("cx317_active", "uptime_s")])
            self.state["authorization_sequence"] += 1
            sequence = self.state["authorization_sequence"]
            nonce = secrets.randbits(32) or 1
            expiry = uptime + 110
            self._command(f"ACTIVE ARM {sequence} {nonce} {expiry}")
            self.state["arm_pending"] = True
            self.state["arm_sent_at_utc"] = _utc_now()
            self._last_arm_monotonic = time.monotonic()
            self._save()
            self._event(
                "one_decision_armed",
                authorization_sequence=sequence,
                nonce=nonce,
                expiry_s=expiry,
                selected_interval_count=progress,
            )

    def _maybe_finish(
        self, health: dict[tuple[str, str], str], now_epoch: float
    ) -> None:
        if self.state["terminal"] is not None:
            return
        state = health.get(("cx317_active", "state"), "")
        evidence_clear = (
            health.get(("cx317_active", "evidence_phase")) == "evidence_clear"
        )
        qualified = self.state["qualification_started_utc"]
        if qualified is None:
            started = self.state.get("supervisor_started_utc")
            if (
                isinstance(started, str)
                and now_epoch - _parse_utc_epoch(started)
                >= self.timing.qualification_timeout_s
            ):
                self._abort("stage7_qualification_timeout")
            return
        qualified_elapsed_s = now_epoch - _parse_utc_epoch(qualified)
        if self.part in {"part_a", "rehearsal"}:
            baseline = self.state.get(
                "part_a_service_load_completed_control_seq"
            )
            if (
                self.state["part_a_service_load_complete"]
                and baseline is not None
                and self.state.get("part_a_post_service_eligible_control_seq")
                is None
            ):
                preview = _latest_preview(self.run_dir / CONTROL_CSV)
                if (
                    preview is not None
                    and int(preview["control_seq"]) > int(baseline)
                    and preview.get("preview_available") == "true"
                    and preview.get("model_applicability") == "applicable"
                    and preview.get("diagnostic_health") == "healthy"
                ):
                    self.state[
                        "part_a_post_service_eligible_control_seq"
                    ] = int(preview["control_seq"])
                    self._save()
                    self._event(
                        "part_a_post_service_eligible_decision_observed",
                        control_seq=int(preview["control_seq"]),
                        limited_delta_codes=preview.get(
                            "limited_delta_codes"
                        ),
                    )
            required_responses = 2 if self.part == "rehearsal" else 1
            if (
                self.state["response_count"] >= required_responses
                and self.state["part_a_service_load_complete"]
                and self.state.get("part_a_post_service_eligible_control_seq")
                is not None
                and not self.state["arm_pending"]
                and state == "DISARMED"
                and evidence_clear
            ):
                self.state["terminal"] = {
                    "result": "healthy_stop",
                    "reason": "exact_cross_core_transaction_and_bounded_service_interval",
                    "utc": _utc_now(),
                }
                self._save()
            elif qualified_elapsed_s >= self.timing.qualified_timeout_s:
                self._abort(f"{self.part}_qualified_duration_expired")
            return
        if qualified_elapsed_s >= PART_B_DURATION_S:
            if not self.state["duration_elapsed"]:
                self.state["duration_elapsed"] = True
                self._save()
                self._event("part_b_24h_duration_elapsed_waiting_for_clear_state")
            required_bursts = set(range(len(PART_B_SERVICE_LOAD_STARTS_S)))
            completed_bursts = set(self.state["part_b_service_bursts_complete"])
            if completed_bursts != required_bursts:
                self._abort("part_b_required_service_bursts_incomplete")
                return
            if (
                not self.state["arm_pending"]
                and state == "DISARMED"
                and evidence_clear
            ):
                self.state["terminal"] = {
                    "result": "healthy_stop",
                    "reason": "24h_after_qualification_complete",
                    "utc": _utc_now(),
                }
                self._save()
            elif qualified_elapsed_s >= (
                PART_B_DURATION_S + PART_B_CLEARANCE_GRACE_S
            ):
                self._abort("part_b_clearance_grace_expired")

    def run(self) -> int:
        capture_flag = self.run_dir / CAPTURE_IN_PROGRESS_FLAG
        if not capture_flag.exists():
            raise RuntimeError("capture is not marked in progress")
        started = time.monotonic()
        last_lease = 0.0
        last_query = 0.0
        with AbortFifo(self.abort_fifo) as abort:
            self._live_command_ack_required = True
            self._event(
                "stage7_supervisor_started",
                part=self.part,
                abort_fifo=str(self.abort_fifo),
                authoritative_deadband_hz=0.006249995628992717,
            )
            self._command("CONFIG?")
            self._command("DAC?")
            while True:
                now = time.monotonic()
                if abort.poll():
                    self._abort("independent_host_abort_fifo")
                    return 3
                if not capture_flag.exists():
                    self._abort("capture_owner_lost")
                    return 4
                if self.duration_s is not None and now - started > self.duration_s:
                    self._abort("supervisor_duration_expired")
                    return 5
                if now - last_lease >= LEASE_PERIOD_S:
                    self._check_capture_transport_state()
                    self._renew_lease()
                    last_lease = now
                if now - last_query >= QUERY_PERIOD_S:
                    self._command("ACTIVE?")
                    last_query = now
                self._process_transactions()
                health = _latest_health(self.run_dir / HEALTH_CSV)
                self._check_fail_static_health(health)
                preview = _latest_preview(self.run_dir / CONTROL_CSV)
                self._maybe_qualify(health, preview)
                self._service_load(now)
                self._maybe_finish(health, time.time())
                if self.state["terminal"] is None:
                    self._maybe_start_or_arm(health)
                if self.state["terminal"] is not None:
                    self._event("stage7_campaign_terminal", **self.state["terminal"])
                    return 0 if self.state["terminal"]["result"] == "healthy_stop" else 2
                time.sleep(0.2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--part", choices=("part_a", "part_b", "rehearsal"), required=True
    )
    parser.add_argument("--start-code", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--command-fifo", type=Path, required=True)
    parser.add_argument(
        "--emergency-command-fifo", type=Path, required=True
    )
    parser.add_argument("--abort-fifo", type=Path, required=True)
    parser.add_argument("--expected-build-identity", required=True)
    parser.add_argument("--allow-manual-start", action="store_true")
    parser.add_argument("--allow-arm", action="store_true")
    parser.add_argument("--duration-s", type=float)
    parser.add_argument("--console-events", action="store_true")
    args = parser.parse_args(argv)
    fifo_paths = {
        args.command_fifo.absolute(),
        args.emergency_command_fifo.absolute(),
        args.abort_fifo.absolute(),
    }
    if len(fifo_paths) != 3:
        parser.error(
            "command, emergency-command and independent-abort FIFOs "
            "must be distinct"
        )
    spec, identities = load_cx317_bounded_active_spec(args.part, args.start_code)
    supervisor = Cx317BoundedActiveSupervisor(
        part=args.part,
        run_dir=args.run_dir,
        command_fifo=args.command_fifo,
        abort_fifo=args.abort_fifo,
        spec=spec,
        identities=identities,
        expected_build_identity=args.expected_build_identity,
        allow_manual_start=args.allow_manual_start,
        allow_arm=args.allow_arm,
        duration_s=args.duration_s,
        emergency_command_fifo=args.emergency_command_fifo,
        console_events=args.console_events,
    )
    try:
        return supervisor.run()
    except (OSError, RuntimeError, SystemExit, ValueError) as exc:
        supervisor._event("stage7_supervisor_fault", error=str(exc))
        supervisor._abort(f"stage7_supervisor_fault:{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
