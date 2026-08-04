"""Fail-static supervisor for Stage 7 dual-core confirmation/endurance.

The capture process remains the sole serial owner.  This supervisor only uses
the command FIFO and the independent ABORT-only FIFO.  Every ACT phase is
fsynced into an immutable capsule before the corresponding release crosses to
the device.  Shadow analysis is deliberately absent from this authority path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import json
import secrets
import time

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
    validate_transaction_row,
)
from .run_loader import CAPTURE_IN_PROGRESS_FLAG


REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "profiles/discipline/cx317_bounded_active_v2.json"
CONTROL_CSV = Path("csv/control_previews_v1.csv")
DAC_CSV = Path("csv/dac_steps.csv")
PART_B_DURATION_S = 24 * 60 * 60
PART_A_SERVICE_LOAD_QUERIES = 60
PART_B_SERVICE_LOAD_STARTS_S = (3600, 25200, 46800, 68400)
PART_B_SERVICE_LOAD_QUERIES = 60
CAPTURE_TICKS_PER_SECOND = 16_000_000
SELECTED_INTERVAL_S = 600
DECISION_CADENCE_S = 1800


def load_stage7_spec(part: str, start_code: int) -> tuple[CampaignSpec, dict[str, str]]:
    if part not in {"part_a", "part_b"}:
        raise ValueError(f"unsupported Stage 7 part {part!r}")
    if not 0xA800 <= start_code <= 0xAB00:
        raise ValueError("Stage 7 start code is outside A800..AB00")
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
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


def _next_selected_interval_is_cadence_eligible(path: Path) -> bool:
    """Conservatively predict whether an arm can be consumed next interval.

    The device only consumes an authorization when the controller evaluates an
    eligible decision.  Selected estimates arrive every 600 seconds, while the
    frozen controller decision cadence is 1800 seconds.  Arming before either
    intervening cadence-hold interval leaves the one-shot authorization unused
    and therefore correctly faults when its short lifetime expires.
    """
    rows = _read_csv(path)
    if not rows:
        return False
    eligible = [row for row in rows if row.get("preview_available") == "true"]
    if not eligible:
        return True
    try:
        latest_ticks = int(rows[-1]["decision_timestamp_ticks"])
        last_eligible_ticks = int(eligible[-1]["decision_timestamp_ticks"])
    except (KeyError, TypeError, ValueError):
        return False
    next_selected_ticks = latest_ticks + (
        SELECTED_INTERVAL_S * CAPTURE_TICKS_PER_SECOND
    )
    return next_selected_ticks - last_eligible_ticks >= (
        DECISION_CADENCE_S * CAPTURE_TICKS_PER_SECOND
    )


def _parse_utc_epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


class Stage7Supervisor(ActiveCampaignSupervisor):
    def __init__(self, *, part: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.part = part
        self._last_arm_monotonic: float | None = None
        self._next_service_command_monotonic = 0.0
        self.state.setdefault("stage7_part", part)
        self.state.setdefault("response_count", 0)
        self.state.setdefault("qualification_started_utc", None)
        self.state.setdefault("part_a_service_load_sent", 0)
        self.state.setdefault("part_a_service_load_complete", False)
        self.state.setdefault("part_a_service_load_completed_control_seq", None)
        self.state.setdefault("part_a_post_service_eligible_control_seq", None)
        self.state.setdefault("part_b_service_bursts_complete", [])
        self.state.setdefault("part_b_service_burst_sent", 0)
        self.state.setdefault("part_b_service_burst_index", None)
        self.state.setdefault("duration_elapsed", False)
        self.state.setdefault("arm_sent_at_utc", None)
        self._save()

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
        acknowledged = set(self.state["acknowledged_record_sequences"])
        observed_manual = set(self.state["observed_manual_record_sequences"])
        for row in _read_csv(path):
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
        for key in (
            "capture_dropped",
            "boundary_dropped",
            "telemetry_dropped",
        ):
            if faults[key] not in {None, "0"}:
                raise ValueError(f"live {key} is {faults[key]}")

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
        if self.part == "part_a":
            if self.state["response_count"] < 1 or self.state[
                "part_a_service_load_complete"
            ]:
                return
            sent = int(self.state["part_a_service_load_sent"])
            if sent < PART_A_SERVICE_LOAD_QUERIES:
                self._command("CONFIG?")
                self.state["part_a_service_load_sent"] = sent + 1
                self._next_service_command_monotonic = now + 1.0
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
                query_count=PART_A_SERVICE_LOAD_QUERIES,
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
        self._save()
        self._event(
            "part_b_service_load_complete",
            burst_index=active_index,
            query_count=PART_B_SERVICE_LOAD_QUERIES,
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
        if (
            self.allow_manual_start
            and not manual_confirmed
            and not self.state["manual_start_sent"]
            and state == "DISARMED"
        ):
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

        correction_count = int(
            health.get(("cx317_active", "correction_count"), "0")
        )
        if correction_count >= self.spec.correction_limit:
            return
        preview = _latest_preview(self.run_dir / CONTROL_CSV)
        if preview is not None:
            try:
                limited_delta = int(preview.get("limited_delta_codes") or "0")
            except ValueError:
                limited_delta = 0
            if preview.get("preview_available") == "true" and limited_delta == 0:
                return
        progress = int(
            health.get(("cx317_active", "selected_interval_count"), "0")
        )
        arm_eligible = health.get(("cx317_active", "arm_eligible")) == "true"
        evidence_clear = (
            health.get(("cx317_active", "evidence_phase")) == "evidence_clear"
        )
        if (
            state == "DISARMED"
            and arm_eligible
            and evidence_clear
            and progress >= ARM_PROGRESS_THRESHOLD
            and _next_selected_interval_is_cadence_eligible(
                self.run_dir / CONTROL_CSV
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
        if self.part == "part_a":
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
            if (
                self.state["response_count"] >= 1
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
            return
        qualified = self.state["qualification_started_utc"]
        if qualified is None:
            return
        if now_epoch - _parse_utc_epoch(qualified) >= PART_B_DURATION_S:
            if not self.state["duration_elapsed"]:
                self.state["duration_elapsed"] = True
                self._save()
                self._event("part_b_24h_duration_elapsed_waiting_for_clear_state")
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

    def run(self) -> int:
        capture_flag = self.run_dir / CAPTURE_IN_PROGRESS_FLAG
        if not capture_flag.exists():
            raise RuntimeError("capture is not marked in progress")
        started = time.monotonic()
        last_lease = 0.0
        last_query = 0.0
        with AbortFifo(self.abort_fifo) as abort:
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
    parser.add_argument("--part", choices=("part_a", "part_b"), required=True)
    parser.add_argument("--start-code", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--command-fifo", type=Path, required=True)
    parser.add_argument("--abort-fifo", type=Path, required=True)
    parser.add_argument("--expected-build-identity", required=True)
    parser.add_argument("--allow-manual-start", action="store_true")
    parser.add_argument("--allow-arm", action="store_true")
    parser.add_argument("--duration-s", type=float)
    args = parser.parse_args(argv)
    spec, identities = load_stage7_spec(args.part, args.start_code)
    supervisor = Stage7Supervisor(
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
    )
    try:
        return supervisor.run()
    except (OSError, RuntimeError, SystemExit, ValueError) as exc:
        supervisor._event("stage7_supervisor_fault", error=str(exc))
        supervisor._abort(f"stage7_supervisor_fault:{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
