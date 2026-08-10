"""Fail-static supervisor for CX318 Stage 5 rehearsal and live legs.

The capture process remains the sole serial owner.  Rehearsal mode sends only
leases and read-only queries and can never issue a setup command or arm.  Live
mode permits the one exact leg setup stimulus and short-lived frequency-only
authorizations after the frozen identity and telemetry gates pass.  Relative
phase, hybrid preview, historical V2, and symmetric shadow records are checked
as evidence only and never enter the command path.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import secrets
import time

from .cx317_abort_path import AbortFifo
from .cx317_active_campaign import (
    ACTIVE_CSV,
    HEALTH_CSV,
    LEASE_PERIOD_S,
    QUERY_PERIOD_S,
    CampaignSpec,
    _latest_health,
    _read_csv,
    _utc_now,
)
from .cx317_stage7_supervisor import (
    ESTIMATES_CSV,
    Stage7Supervisor,
    Stage7Timing,
    _latest_preview,
    _next_selected_interval_is_cadence_eligible,
    _parse_utc_epoch,
)
from .cx318_stage5_manifest import (
    LIVE_STAGE,
    POLICY_PATH,
    REHEARSAL_STAGE,
    validate_manifest,
)
from .cx318_stage5_tight_replay import replay_tight_deadband
from .run_loader import CAPTURE_IN_PROGRESS_FLAG
from .run_paths import TIGHT_DEADBAND_DECISIONS_CSV


CONTROL_CSV = Path("csv/control_previews_v1.csv")
DAC_CSV = Path("csv/dac_steps.csv")
ENVIRONMENT_CSV = Path("csv/environment.csv")
RPH_CSV = Path("csv/relative_phase_observations_v1.csv")
PHE_CSV = Path("csv/phase_estimator_outputs_v1.csv")
HPR_CSV = Path("csv/hybrid_preview_decisions_v1.csv")
TDB_CSV = Path("csv") / TIGHT_DEADBAND_DECISIONS_CSV

REHEARSAL_DURATION_S = 2700
QUALIFICATION_DEADLINE_S = 5400
MAXIMUM_QUALIFIED_DURATION_S = 14400
SELECTED_INTERVAL_S = 600
DECISION_CADENCE_S = 1800
ARM_PROGRESS_THRESHOLD = 520
ARM_LIFETIME_S = 110


@dataclass(frozen=True)
class Stage5Leg:
    leg: str
    required_direction: int
    required_direction_name: str


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load_stage5_spec(
    leg: str,
) -> tuple[CampaignSpec, dict[str, str], Stage5Leg]:
    """Load the exact frozen leg identity used by firmware and ACT replay."""

    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if (
        policy.get("policy_id")
        != "CX318_STAGE5_TIGHT_ACTIVE_FREQUENCY_ONLY_V1"
        or policy.get("status") != "frozen_before_stage5_hardware_or_write"
    ):
        raise ValueError("unexpected Stage 5 policy identity")
    if leg not in {"A", "B"}:
        raise ValueError("Stage 5 leg must be A or B")
    selected = policy["legs"][leg]
    expected = {
        "A": ("cx318_stage5_tight_lower", 3185001, 0xA808, "positive", 1),
        "B": ("cx318_stage5_tight_upper", 3185002, 0xA848, "negative", -1),
    }[leg]
    exact = (
        selected["firmware_profile"],
        selected["run_binding_tag"],
        selected["exact_setup_code"],
        selected["required_automatic_direction"],
        selected["maximum_automatic_corrections"],
        selected["maximum_cumulative_automatic_movement_codes"],
    )
    if exact != (*expected[:4], 4, 84):
        raise ValueError(f"Stage 5 leg {leg} policy is not exact")
    controller = policy["frequency_controller"]
    if (
        controller["minimum_code"],
        controller["maximum_code"],
        controller["maximum_automatic_step_codes"],
        controller["minimum_applied_correction_cadence_s"],
        controller["settling_exclusion_s"],
        controller["fresh_support_after_settling_s"],
        controller["full_history_reset_s"],
    ) != (0xA800, 0xAB00, 21, 1800, 900, 600, 1500):
        raise ValueError("Stage 5 controller limits or clocks are not exact")
    profile, tag, setup_code, direction_name, direction = expected
    spec = CampaignSpec(
        campaign=f"cx318_stage5_leg_{leg.lower()}",
        profile=profile,
        run_identity=f"{profile}:{tag}",
        start_code=setup_code,
        correction_limit=4,
        cumulative_limit=84,
        minimum_code=0xA800,
        maximum_code=0xAB00,
        maximum_step=21,
    )
    bindings = policy["bindings"]
    identities = {
        "estimator_sha256": bindings["selected_frequency_estimator"]["sha256"],
        "model_sha256": bindings["plant_model"]["sha256"],
        "active_policy_sha256": _sha256(POLICY_PATH),
        "response_policy_sha256": bindings["response_policy"]["sha256"],
        "numerical_policy_sha256": bindings[
            "inherited_frequency_controller_numerics"
        ]["sha256"],
    }
    return spec, identities, Stage5Leg(leg, direction, direction_name)


def _rows_present(path: Path) -> bool:
    return bool(_read_csv(path))


def _selected_estimates(path: Path) -> list[dict[str, str]]:
    return [
        row
        for row in _read_csv(path)
        if row.get("estimator_version")
        == "cx317_selected_600s_nonoverlap_v1"
    ]


class Stage5Supervisor(Stage7Supervisor):
    """Exact Stage 5 authority supervisor built on the proven dual-core path."""

    def __init__(self, *, mode: str, leg: Stage5Leg, **kwargs: object) -> None:
        if mode not in {"rehearsal", "live"}:
            raise ValueError("Stage 5 mode must be rehearsal or live")
        allow_manual_start = bool(kwargs.get("allow_manual_start"))
        allow_arm = bool(kwargs.get("allow_arm"))
        if mode == "rehearsal" and (allow_manual_start or allow_arm):
            raise ValueError("Stage 5 rehearsal cannot have setup or arm authority")
        if mode == "live" and not (allow_manual_start and allow_arm):
            raise ValueError("Stage 5 live requires explicit setup and arm authority")
        # Part B selects the long-lived, dual-core transaction implementation;
        # every Stage 7 timing/service decision is overridden below.
        super().__init__(part="part_b", **kwargs)
        self.mode = mode
        self.leg = leg
        self.part = f"stage5_{mode}_{leg.leg.lower()}"
        self.timing = Stage7Timing(
            selected_interval_s=SELECTED_INTERVAL_S,
            decision_cadence_s=DECISION_CADENCE_S,
            arm_progress_threshold=ARM_PROGRESS_THRESHOLD,
            qualification_timeout_s=QUALIFICATION_DEADLINE_S,
            qualified_timeout_s=MAXIMUM_QUALIFIED_DURATION_S,
            service_load_queries=0,
            service_query_period_s=1.0,
        )
        self.state["stage5_mode"] = mode
        self.state["stage5_leg"] = leg.leg
        self.state.setdefault("setup_confirmed_utc", None)
        self.state.setdefault("expected_direction_seen", False)
        self.state.setdefault("tight_entry_seen", False)
        self.state.setdefault("latest_replayed_tdb_rows", 0)
        self.state.setdefault("rehearsal_started_monotonic", None)
        self._save()

    def _latest_tdb(self) -> dict[str, str] | None:
        path = self.run_dir / TDB_CSV
        rows = _read_csv(path)
        if not rows:
            return None
        if len(rows) != int(self.state["latest_replayed_tdb_rows"]):
            result = replay_tight_deadband(path)
            if not result.exact:
                raise ValueError(
                    "live TDB replay mismatch: " + "; ".join(result.errors[:4])
                )
            self.state["latest_replayed_tdb_rows"] = len(rows)
            self._save()
        return rows[-1]

    def _check_zero_authority_preview(self) -> None:
        for relative in (CONTROL_CSV, RPH_CSV, PHE_CSV, HPR_CSV, TDB_CSV):
            rows = _read_csv(self.run_dir / relative)
            if not rows:
                continue
            row = rows[-1]
            for field in (
                "actionable",
                "actuation_authorized",
                "authorization_consumed",
            ):
                if field in row and row[field] != "false":
                    raise ValueError(
                        f"preview authority contamination: {relative}:{field}="
                        f"{row[field]!r}"
                    )

    def _check_fail_static_health(
        self, health: dict[tuple[str, str], str]
    ) -> None:
        super()._check_fail_static_health(health)
        exact_false = (
            ("cx317_preview", "actuation_authorized"),
            ("cx317_preview", "actionable"),
            ("cx318_preview", "actuation_authorized"),
            ("cx318_preview", "actionable"),
            ("cx318_preview", "authorization_consumed"),
        )
        for key in exact_false:
            observed = health.get(key)
            if observed not in {None, "false"}:
                raise ValueError(f"live zero-authority status violated: {key}={observed}")
        if health.get(("cx317_preview", "telemetry_dropped_frames")) not in {
            None,
            "0",
        }:
            raise ValueError("Stage 5 frequency/TDB preview telemetry dropped")
        self._check_zero_authority_preview()

    def _process_transactions(self) -> None:
        super()._process_transactions()
        rows = _read_csv(self.run_dir / ACTIVE_CSV)
        manual = [row for row in rows if row.get("event") == "manual_start"]
        if len(manual) > 1:
            raise ValueError("Stage 5 contains more than one setup transaction")
        if manual:
            if int(manual[0]["applied_code"]) != self.spec.start_code:
                raise ValueError("Stage 5 setup applied the wrong exact code")
            if self.state["setup_confirmed_utc"] is None:
                self.state["setup_confirmed_utc"] = _utc_now()
                self._save()
                self._event(
                    "stage5_setup_confirmed",
                    leg=self.leg.leg,
                    applied_code=self.spec.start_code,
                    dac_epoch=int(manual[0]["dac_epoch"]),
                )
        applications = [row for row in rows if row.get("event") == "application"]
        # The prompt declares this as a required demonstrated outcome, not a
        # one-sided actuator clamp: a bounded convergence path may legitimately
        # make a later opposite adjustment.  Require at least one completed
        # application in the setup-implied direction at the leg pass gate.
        if any(
            (int(row["requested_delta_codes"]) > 0)
            - (int(row["requested_delta_codes"]) < 0)
            == self.leg.required_direction
            for row in applications
        ):
            if not self.state["expected_direction_seen"]:
                self.state["expected_direction_seen"] = True
                self._save()
                self._event(
                    "stage5_required_automatic_direction_observed",
                    leg=self.leg.leg,
                    direction=self.leg.required_direction_name,
                )

    def _maybe_qualify(self, health: dict[tuple[str, str], str]) -> None:
        if self.mode != "live" or self.state["qualification_started_utc"] is not None:
            return
        if self.state["setup_confirmed_utc"] is None or not self._identity_ready(health):
            return
        tdb = self._latest_tdb()
        if tdb is None or int(tdb["dac_epoch"]) < 1:
            return
        self.state["qualification_started_utc"] = _utc_now()
        self._save()
        self._event(
            "stage5_post_setup_qualification_complete",
            leg=self.leg.leg,
            decision_sequence=int(tdb["decision_sequence"]),
            dac_epoch=int(tdb["dac_epoch"]),
        )

    def _maybe_start_or_arm(
        self, health: dict[tuple[str, str], str]
    ) -> None:
        if self.mode != "live" or not self._identity_ready(health):
            return
        state = health.get(("cx317_active", "state"), "")
        reason = health.get(("cx317_active", "reason"), "")
        if state in {"FAULT", "ABORTED"}:
            raise ValueError(f"device active state {state.lower()}: {reason}")
        if state == "OUT_OF_MODEL_HOLD":
            raise ValueError(f"device entered out-of-model hold: {reason}")

        manual_confirmed = (
            health.get(("cx317_active", "manual_start_confirmed")) == "true"
        )
        if (
            not manual_confirmed
            and not self.state["manual_start_sent"]
            and state == "DISARMED"
        ):
            # The setup consumes the leg's sole predetermined stimulus.  Wait
            # for the same-profile A828/epoch-0 preview identity and an empty
            # live-run transaction history before sending it.
            pre_setup_exact = (
                health.get(("cx318_preview", "static_code")) == "0xA828"
                and health.get(("cx318_preview", "applied_code")) == "0xA828"
                and health.get(("cx318_preview", "dac_epoch")) == "0"
                and health.get(("cx317_active", "dac_epoch")) == "0"
                and health.get(("cx317_active", "correction_count")) == "0"
                and not _rows_present(self.run_dir / ACTIVE_CSV)
                and not _rows_present(self.run_dir / DAC_CSV)
            )
            if not pre_setup_exact:
                return
            self._command(f"DAC SET 0x{self.spec.start_code:04X}")
            self.state["manual_start_sent"] = True
            self._save()
            self._event(
                "stage5_exact_setup_requested",
                leg=self.leg.leg,
                code=self.spec.start_code,
            )
            return
        if self.state["arm_pending"] and state == "DISARMED":
            sent_at = self.state.get("arm_sent_at_utc")
            age = (
                time.time() - _parse_utc_epoch(sent_at)
                if isinstance(sent_at, str) and sent_at
                else 0.0
            )
            # ACTIVE? is queried every 10 s.  A 15 s floor prevents the stale
            # pre-arm DISARMED status from being mistaken for consumption,
            # while still clearing a genuine zero-delta decision well before
            # the 110 s authorization lifetime matters.
            if age > 15.0:
                self.state["arm_pending"] = False
                self.state["arm_sent_at_utc"] = None
                self._save()
                self._event("stage5_unused_zero_delta_arm_consumed_without_write")
        if not manual_confirmed or self.state["arm_pending"]:
            return
        tdb = self._latest_tdb()
        if tdb is not None and tdb.get("state_after") == "TIGHT_INSIDE":
            return
        correction_count = int(
            health.get(("cx317_active", "correction_count"), "0")
        )
        if correction_count >= self.spec.correction_limit:
            return
        preview = _latest_preview(self.run_dir / CONTROL_CSV)
        if preview is None or preview.get("control_state") == "FAULT":
            return
        try:
            limited_delta = int(preview.get("limited_delta_codes") or "0")
        except ValueError:
            return
        if preview.get("preview_available") != "true" or limited_delta == 0:
            return
        if tdb is None or tdb.get("frequency_controller_eligible") != "true":
            return
        if preview.get("est_input_ref") != tdb.get("estimate_id"):
            return
        progress = int(
            health.get(("cx317_active", "selected_interval_count"), "0")
        )
        if not self._arm_progress_epoch_ready(preview, progress):
            return
        arm_eligible = health.get(("cx317_active", "arm_eligible")) == "true"
        evidence_clear = (
            health.get(("cx317_active", "evidence_phase")) == "evidence_clear"
        )
        if not (
            state == "DISARMED"
            and arm_eligible
            and evidence_clear
            and progress >= ARM_PROGRESS_THRESHOLD
            and _next_selected_interval_is_cadence_eligible(
                self.run_dir / CONTROL_CSV,
                self.run_dir / ESTIMATES_CSV,
                selected_interval_s=SELECTED_INTERVAL_S,
                decision_cadence_s=DECISION_CADENCE_S,
            )
        ):
            return
        uptime = int(health[("cx317_active", "uptime_s")])
        self.state["authorization_sequence"] += 1
        sequence = self.state["authorization_sequence"]
        nonce = secrets.randbits(32) or 1
        expiry = uptime + ARM_LIFETIME_S
        self._command(f"ACTIVE ARM {sequence} {nonce} {expiry}")
        self.state["arm_pending"] = True
        self.state["arm_sent_at_utc"] = _utc_now()
        self._save()
        self._event(
            "stage5_one_decision_armed",
            leg=self.leg.leg,
            authorization_sequence=sequence,
            expiry_s=expiry,
            selected_interval_count=progress,
        )

    def _rehearsal_evidence_ready(
        self, health: dict[tuple[str, str], str]
    ) -> bool:
        if not self._identity_ready(health):
            return False
        if health.get(("cx317_active", "manual_start_confirmed")) != "false":
            raise ValueError("Stage 5 rehearsal observed a manual setup")
        if health.get(("cx317_active", "arm_eligible")) == "true":
            raise ValueError("Stage 5 rehearsal unexpectedly became arm eligible")
        if _rows_present(self.run_dir / ACTIVE_CSV) or _rows_present(
            self.run_dir / DAC_CSV
        ):
            raise ValueError("Stage 5 rehearsal contains a DAC or ACT row")
        if not _selected_estimates(self.run_dir / ESTIMATES_CSV):
            return False
        if self._latest_tdb() is None:
            return False
        if not all(
            _rows_present(self.run_dir / relative)
            for relative in (RPH_CSV, PHE_CSV, HPR_CSV)
        ):
            return False
        sources = {
            row.get("source", "").lower()
            for row in _read_csv(self.run_dir / ENVIRONMENT_CSV)
        }
        if not {"sht4x", "bmp280"} <= sources:
            return False
        return (
            health.get(("cx318_preview", "static_code")) == "0xA828"
            and health.get(("cx318_preview", "applied_code")) == "0xA828"
            and health.get(("cx318_preview", "dac_epoch")) == "0"
        )

    def _maybe_finish(
        self,
        health: dict[tuple[str, str], str],
        now_epoch: float,
        elapsed_monotonic_s: float,
    ) -> None:
        if self.state["terminal"] is not None:
            return
        state = health.get(("cx317_active", "state"), "")
        evidence_clear = (
            health.get(("cx317_active", "evidence_phase")) == "evidence_clear"
        )
        if self.mode == "rehearsal":
            if elapsed_monotonic_s < REHEARSAL_DURATION_S:
                return
            if self._rehearsal_evidence_ready(health):
                self.state["terminal"] = {
                    "result": "healthy_stop",
                    "reason": "2700s_exact_profile_no_write_rehearsal_complete",
                    "utc": _utc_now(),
                }
                self._save()
                return
            self._abort("stage5_rehearsal_endpoint_without_required_evidence")
            return

        setup = self.state["setup_confirmed_utc"]
        qualified = self.state["qualification_started_utc"]
        if setup is not None and qualified is None:
            if now_epoch - _parse_utc_epoch(setup) >= QUALIFICATION_DEADLINE_S:
                self._abort("stage5_qualification_deadline_expired")
            return
        if qualified is None:
            return
        tdb = self._latest_tdb()
        tight = tdb is not None and tdb.get("state_after") == "TIGHT_INSIDE"
        if tight and not self.state["tight_entry_seen"]:
            self.state["tight_entry_seen"] = True
            self._save()
            self._event(
                "stage5_two_estimate_tight_entry_observed",
                leg=self.leg.leg,
                decision_sequence=int(tdb["decision_sequence"]),
            )
        if (
            self.state["tight_entry_seen"]
            and self.state["expected_direction_seen"]
            and int(self.state["response_count"]) >= 1
            and not self.state["arm_pending"]
            and state == "DISARMED"
            and evidence_clear
        ):
            self.state["terminal"] = {
                "result": "healthy_stop",
                "reason": "required_direction_and_two_estimate_tight_entry",
                "utc": _utc_now(),
            }
            self._save()
            return
        if now_epoch - _parse_utc_epoch(qualified) >= MAXIMUM_QUALIFIED_DURATION_S:
            self._abort("stage5_finite_qualified_endpoint_nonpass")

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
                "stage5_supervisor_started",
                mode=self.mode,
                leg=self.leg.leg,
                abort_fifo=str(self.abort_fifo),
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
                self._maybe_qualify(health)
                self._maybe_finish(health, time.time(), now - started)
                if self.state["terminal"] is None:
                    self._maybe_start_or_arm(health)
                if self.state["terminal"] is not None:
                    self._event("stage5_campaign_terminal", **self.state["terminal"])
                    return (
                        0
                        if self.state["terminal"]["result"] == "healthy_stop"
                        else 2
                    )
                time.sleep(0.2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("rehearsal", "live"), required=True)
    parser.add_argument("--leg", choices=("A", "B"), required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--command-fifo", type=Path, required=True)
    parser.add_argument("--emergency-command-fifo", type=Path, required=True)
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
        parser.error("normal, emergency, and host-abort FIFOs must be distinct")
    manifest = validate_manifest(args.manifest)
    expected_stage = REHEARSAL_STAGE if args.mode == "rehearsal" else LIVE_STAGE
    manifest_build_identity = (
        manifest.get("firmware", {}).get("source_sha256", "")
        + ":"
        + manifest.get("firmware", {}).get("configuration_sha256", "")
    )
    if (
        args.manifest.resolve() != (args.run_dir / "run_manifest.json").resolve()
        or manifest.get("stage") != expected_stage
        or manifest.get("stage5", {}).get("leg") != args.leg
        or args.expected_build_identity != manifest_build_identity
    ):
        parser.error(
            "manifest run/mode/leg/build does not match the supervisor request"
        )
    spec, identities, leg = load_stage5_spec(args.leg)
    supervisor = Stage5Supervisor(
        mode=args.mode,
        leg=leg,
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
    except (OSError, RuntimeError, SystemExit, TimeoutError, ValueError) as exc:
        supervisor._event("stage5_supervisor_fault", error=str(exc))
        supervisor._abort(f"stage5_supervisor_fault:{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
