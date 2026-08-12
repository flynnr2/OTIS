"""Shared fail-static frequency-control supervisor mechanics.

The capture process remains the sole serial owner.  Rehearsal mode sends only
leases and read-only queries and can never issue a setup command or arm.  Live
mode permits the one exact leg setup stimulus and short-lived frequency-only
authorizations after the frozen identity and telemetry gates pass.  Relative
phase, hybrid preview, historical V2, and symmetric shadow records are checked
as evidence only and never enter the command path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import secrets
import time

from .abort_transport import AbortFifo
from .active_transactions import (
    ACTIVE_CSV,
    HEALTH_CSV,
    LEASE_PERIOD_S,
    QUERY_PERIOD_S,
    CampaignSpec,
    _read_csv,
    _utc_now,
)
from .active_status_live_state import LIVE_STATE_PATH, read_live_health_state
from .contracts import TIGHT_DEADBAND_POLICY_SHA256
from .active_control_supervisor import (
    ESTIMATES_CSV,
    ControlSupervisorBase,
    ControlTiming,
    _latest_preview,
    _next_selected_interval_is_cadence_eligible,
    _parse_utc_epoch,
)
from .prewrite_readiness_contract import (
    PrewriteReadiness,
    environment_streams_ready,
    evaluate_health_integrity,
    evaluate_prewrite_readiness,
)
from .tight_deadband_policy import replay_tight_deadband
from .run_loader import CAPTURE_IN_PROGRESS_FLAG
from .run_paths import TIGHT_DEADBAND_DECISIONS_CSV
from .setup_authority_contract import (
    SETUP_AUTHORITY_CONTRACT,
    SETUP_AUTHORITY_LIFETIME_S,
    SETUP_AUTHORITY_PATH,
    canonical_health,
    write_setup_authority_input,
)


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
PREWRITE_CONTRACT_STARTUP_GRACE_S = 30
SETUP_RESULT_GRACE_S = QUERY_PERIOD_S
# One active burst may straddle the platform's declared maximum supported USB
# TX obstruction.  The deadline is the same 2,000 ms transport horizon used by
# Q1 detach authority; a completed snapshot still grants no authority until its
# atomic handoff replaces the in-progress state.
ACTIVE_SNAPSHOT_COMPLETION_TIMEOUT_S = 2.0
ACTIVE_SNAPSHOT_COMPLETION_POLL_S = 0.02
ACTIVE_STATUS_COMPLETE_MAX_AGE_S = QUERY_PERIOD_S + 2.0


@dataclass(frozen=True)
class TightDeadbandLeg:
    leg: str
    required_direction: int
    required_direction_name: str


def _rows_present(path: Path) -> bool:
    return bool(_read_csv(path))


def _selected_estimates(path: Path) -> list[dict[str, str]]:
    return [
        row
        for row in _read_csv(path)
        if row.get("estimator_version")
        == "cx317_selected_600s_nonoverlap_v1"
    ]


def healthy_required_direction_applications(
    rows: list[dict[str, str]], required_direction: int
) -> list[dict[str, str]]:
    """Return applications whose own completed response remained healthy."""

    applications = {
        int(row["request_sequence"]): row
        for row in rows
        if row.get("event") == "application"
    }
    healthy_response_classes = {
        "healthy_detected",
        "healthy_indeterminate_near_resolution",
    }
    result: list[dict[str, str]] = []
    for response in rows:
        if (
            response.get("event") != "response"
            or response.get("response_class") not in healthy_response_classes
        ):
            continue
        application = applications.get(int(response["request_sequence"]))
        if application is None:
            continue
        delta = int(application["requested_delta_codes"])
        direction = (delta > 0) - (delta < 0)
        if direction == required_direction:
            result.append(application)
    return result


class FrequencyControlSupervisor(ControlSupervisorBase):
    """Current frequency-control authority supervisor."""

    def __init__(self, *, mode: str, leg: TightDeadbandLeg, **kwargs: object) -> None:
        if mode not in {"rehearsal", "live"}:
            raise ValueError("Stage 5 mode must be rehearsal or live")
        allow_manual_start = bool(kwargs.get("allow_manual_start"))
        allow_arm = bool(kwargs.get("allow_arm"))
        if mode == "rehearsal" and (allow_manual_start or allow_arm):
            raise ValueError("Stage 5 rehearsal cannot have setup or arm authority")
        if mode == "live" and not (allow_manual_start and allow_arm):
            raise ValueError("Stage 5 live requires explicit setup and arm authority")
        tight_deadband_policy_sha256 = str(
            kwargs.pop(
                "tight_deadband_policy_sha256",
                TIGHT_DEADBAND_POLICY_SHA256,
            )
        )
        prewrite_contract_startup_grace_s = float(
            kwargs.pop(
                "prewrite_contract_startup_grace_s",
                PREWRITE_CONTRACT_STARTUP_GRACE_S,
            )
        )
        if prewrite_contract_startup_grace_s <= 0:
            raise ValueError("pre-write startup grace must be positive")
        super().__init__(**kwargs)
        self.mode = mode
        self.leg = leg
        self.tight_deadband_policy_sha256 = tight_deadband_policy_sha256
        self.prewrite_contract_startup_grace_s = (
            prewrite_contract_startup_grace_s
        )
        self.part = f"stage5_{mode}_{leg.leg.lower()}"
        self.timing = ControlTiming(
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
        self.state.setdefault("prewrite_contract_ready_utc", None)
        self.state.setdefault("latest_prewrite_readiness", None)
        self.state.setdefault("terminal_event_emitted", False)
        self.state.setdefault("host_attach_query_nonce", secrets.randbits(32) or 1)
        self.state.setdefault("setup_authorization_sequence", 0)
        self.state.setdefault("setup_authority_path", None)
        self.state.setdefault("setup_requested_utc", None)
        self._save()

    def _prewrite_readiness(
        self, health: dict[tuple[str, str], str]
    ) -> PrewriteReadiness:
        identity = {
            "run_identity": self.spec.run_identity,
            "build_identity": self.expected_build_identity,
            "profile_identity": self.spec.profile,
            **self.identities,
        }
        readiness = evaluate_prewrite_readiness(
            health,
            expected_identity=identity,
            planned_live_stimulus_code=self.spec.start_code,
            active_row_count=len(_read_csv(self.run_dir / ACTIVE_CSV)),
            dac_row_count=len(_read_csv(self.run_dir / DAC_CSV)),
        )
        mismatches = list(readiness.mismatches)
        if health.get(("cx317_active", "query_nonce")) != str(
            self.state["host_attach_query_nonce"]
        ):
            mismatches.append("solicited post-attachment snapshot is absent")
        if not mismatches and not readiness.missing:
            return readiness
        return PrewriteReadiness(
            contract_id=readiness.contract_id,
            ready=False,
            missing=readiness.missing,
            mismatches=tuple(dict.fromkeys(mismatches)),
            inherited_preview_baseline_code=readiness.inherited_preview_baseline_code,
            inherited_preview_baseline_provenance=(
                readiness.inherited_preview_baseline_provenance
            ),
            planned_live_stimulus_code=readiness.planned_live_stimulus_code,
            physical_dac_confirmation=readiness.physical_dac_confirmation,
        )

    def _check_prewrite_contract(
        self,
        health: dict[tuple[str, str], str],
        elapsed_monotonic_s: float,
    ) -> PrewriteReadiness | None:
        # After the one live stimulus, the pre-write contract has served its
        # purpose and the existing live transaction/terminal gates take over.
        if self.mode == "live" and self.state["manual_start_sent"]:
            return None
        readiness = self._prewrite_readiness(health)
        value = readiness.as_dict()
        if self.state.get("latest_prewrite_readiness") != value:
            self.state["latest_prewrite_readiness"] = value
            self._save()
        if readiness.ready:
            if self.state["prewrite_contract_ready_utc"] is None:
                self.state["prewrite_contract_ready_utc"] = _utc_now()
                self._save()
                self._event(
                    "stage5_prewrite_runtime_contract_ready",
                    contract_id=readiness.contract_id,
                    inherited_preview_baseline=(
                        readiness.inherited_preview_baseline_code
                    ),
                    inherited_preview_provenance=(
                        readiness.inherited_preview_baseline_provenance
                    ),
                    planned_live_stimulus=readiness.planned_live_stimulus_code,
                )
            return readiness
        if (
            self.state["prewrite_contract_ready_utc"] is not None
            or elapsed_monotonic_s
            >= self.prewrite_contract_startup_grace_s
        ):
            raise ValueError(
                "Stage 5 pre-write runtime contract failed: "
                + readiness.diagnostic()
            )
        return readiness

    def _latest_tdb(self) -> dict[str, str] | None:
        path = self.run_dir / TDB_CSV
        rows = _read_csv(path)
        if not rows:
            return None
        if len(rows) != int(self.state["latest_replayed_tdb_rows"]):
            result = replay_tight_deadband(
                path,
                policy_sha256=self.tight_deadband_policy_sha256,
            )
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
        integrity = self._runtime_health_integrity(health)
        if integrity.mismatches or (
            self.state["prewrite_contract_ready_utc"] is not None
            and integrity.missing
        ):
            raise ValueError(
                "Stage 5 continuous runtime health contract failed: "
                + integrity.diagnostic()
            )
        self._check_zero_authority_preview()

    def _runtime_health_integrity(
        self, health: dict[tuple[str, str], str]
    ):  # type: ignore[no-untyped-def]
        """Campaign hook retaining the original absolute Stage 5 contract."""

        return evaluate_health_integrity(health)

    def _status_query_command(self) -> str:
        return f"ACTIVE SNAPSHOT {self.state['host_attach_query_nonce']}"

    def _current_health(self) -> dict[tuple[str, str], str]:
        while True:
            selection = read_live_health_state(
                self.run_dir / LIVE_STATE_PATH,
                required_query_nonce=int(
                    self.state["host_attach_query_nonce"]
                ),
            )
            if selection.state in {"absent", "unmatched"}:
                return {}
            if selection.state == "invalid":
                raise ValueError(
                    "active live-health handoff is invalid: "
                    + selection.diagnostic
                )
            if selection.observed_monotonic_ns is None:
                raise ValueError("active live-health handoff has no host clock")
            age_s = (
                time.monotonic_ns() - selection.observed_monotonic_ns
            ) / 1_000_000_000
            if age_s < -0.001:
                raise ValueError("active live-health handoff is from the future")
            if selection.state == "complete":
                if age_s > ACTIVE_STATUS_COMPLETE_MAX_AGE_S:
                    raise ValueError(
                        "active live-health handoff is stale: "
                        f"age_s={age_s:.6f} limit_s="
                        f"{ACTIVE_STATUS_COMPLETE_MAX_AGE_S:.6f}"
                    )
                return selection.health
            remaining_s = ACTIVE_SNAPSHOT_COMPLETION_TIMEOUT_S - age_s
            if remaining_s <= 0:
                raise ValueError(
                    "active live-health snapshot did not complete within "
                    f"{ACTIVE_SNAPSHOT_COMPLETION_TIMEOUT_S:.3f} s: "
                    f"generation={selection.generation}"
                )
            time.sleep(min(ACTIVE_SNAPSHOT_COMPLETION_POLL_S, remaining_s))

    def _setup_command(
        self, health: dict[tuple[str, str], str]
    ) -> tuple[str, dict[str, object]]:
        configuration_identity = self.expected_build_identity.split(":", 1)[1]
        if len(configuration_identity) != 64:
            raise ValueError("setup configuration identity is not SHA-256")
        self.state["setup_authorization_sequence"] = (
            int(self.state["setup_authorization_sequence"]) + 1
        )
        request: dict[str, object] = {
            "authorization_sequence": self.state["setup_authorization_sequence"],
            "status_generation": int(
                health[("cx317_active", "snapshot_generation_complete")]
            ),
            "query_nonce": int(health[("cx317_active", "query_nonce")]),
            "expires_s": int(health[("cx317_active", "uptime_s")])
            + SETUP_AUTHORITY_LIFETIME_S,
            "session_id": int(health[("cx317_active", "session_id")]),
            "requested_code": self.spec.start_code,
            "one_shot_ordinal": 1,
            "configuration_identity": configuration_identity,
        }
        return (
            "ACTIVE SETUP "
            f"{request['authorization_sequence']} "
            f"{request['status_generation']} {request['query_nonce']} "
            f"{request['expires_s']} {request['session_id']} "
            f"0x{self.spec.start_code:04X} 1 {configuration_identity}",
            request,
        )

    def _retain_setup_authority(
        self,
        health: dict[tuple[str, str], str],
        request: dict[str, object],
    ) -> Path:
        path = self.run_dir / SETUP_AUTHORITY_PATH
        if path.exists():
            raise ValueError(
                "an earlier setup authority record exists; refusing an "
                "ambiguous retry"
            )
        write_setup_authority_input(
            path,
            {
                "contract": SETUP_AUTHORITY_CONTRACT,
                "created_utc": _utc_now(),
                "request": request,
                "health": canonical_health(health),
                "active_row_count": len(_read_csv(self.run_dir / ACTIVE_CSV)),
                "dac_row_count": len(_read_csv(self.run_dir / DAC_CSV)),
                "telemetry_drop_baseline": 0,
            },
        )
        self.state["setup_authority_path"] = str(SETUP_AUTHORITY_PATH)
        self._save()
        return path

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
        # The prompt declares this as a required demonstrated outcome, not a
        # one-sided actuator clamp: a bounded convergence path may legitimately
        # make a later opposite adjustment.  Bind the direction claim to the
        # response from that same completed transaction; an application alone,
        # or an unrelated healthy response, cannot satisfy the pass gate.
        if healthy_required_direction_applications(
            rows, self.leg.required_direction
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
            # The setup consumes the leg's sole planned stimulus.  The shared
            # contract distinguishes it from the inherited A828 preview
            # baseline and requires physical DAC confirmation to remain
            # explicitly unknown before this command.
            if not self._prewrite_readiness(health).ready:
                return
            setup_command = getattr(self, "_setup_command", None)
            retain_authority = getattr(self, "_retain_setup_authority", None)
            if setup_command is None or retain_authority is None:
                raise ValueError(
                    "live setup requires a retained firmware-authority "
                    "transaction implementation"
                )
            command, request = setup_command(health)
            retain_authority(health, request)
            self._command(command)
            self.state["manual_start_sent"] = True
            self.state["setup_requested_utc"] = _utc_now()
            self._save()
            self._event(
                "stage5_exact_setup_requested",
                leg=self.leg.leg,
                code=self.spec.start_code,
                authorization_sequence=request["authorization_sequence"],
                status_generation=request["status_generation"],
                query_nonce=request["query_nonce"],
                expires_s=request["expires_s"],
                session_id=request["session_id"],
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
        preview_available = preview.get("preview_available") == "true"
        if preview_available and limited_delta == 0:
            return
        if (
            not preview_available
            and preview.get("decision_reason_code") != "decision_cadence_hold"
        ):
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

    def _check_setup_transaction_timeout(
        self,
        health: dict[tuple[str, str], str],
        now_epoch: float,
    ) -> None:
        if self.mode != "live" or not self.state["manual_start_sent"]:
            return
        if health.get(("cx317_active", "manual_start_confirmed")) == "true":
            return
        requested = self.state.get("setup_requested_utc")
        if not isinstance(requested, str) or not requested:
            self._abort("setup_transaction_missing_host_timestamp")
            return
        if now_epoch - _parse_utc_epoch(requested) >= (
            SETUP_AUTHORITY_LIFETIME_S + SETUP_RESULT_GRACE_S
        ):
            self._abort("setup_transaction_expired_without_observed_result")

    def _rehearsal_evidence_ready(
        self, health: dict[tuple[str, str], str]
    ) -> bool:
        if not self._prewrite_readiness(health).ready:
            return False
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
        if not environment_streams_ready(sources):
            return False
        return True

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
            and tight
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
                    if (
                        self.mode == "rehearsal"
                        and self.state["terminal"] is not None
                        and self.state["terminal"].get("result")
                        == "healthy_stop"
                    ):
                        self._event(
                            "stage5_rehearsal_promotion_handoff_observed"
                        )
                        return 0
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
                    self._command(self._status_query_command())
                    last_query = now
                self._process_transactions()
                health = self._current_health()
                self._check_fail_static_health(health)
                self._check_setup_transaction_timeout(health, time.time())
                self._check_prewrite_contract(health, now - started)
                self._maybe_qualify(health)
                self._maybe_finish(health, time.time(), now - started)
                if self.state["terminal"] is None:
                    self._maybe_start_or_arm(health)
                if self.state["terminal"] is not None:
                    if not self.state["terminal_event_emitted"]:
                        self._event(
                            "stage5_campaign_terminal", **self.state["terminal"]
                        )
                        self.state["terminal_event_emitted"] = True
                        self._save()
                    if (
                        self.mode == "rehearsal"
                        and self.state["terminal"]["result"] == "healthy_stop"
                    ):
                        # Remain read-only and keep the 30-second capture lease
                        # alive until same-owner promotion removes this run's
                        # capture flag. This eliminates monitor-timing races.
                        time.sleep(0.2)
                        continue
                    return (
                        0
                        if self.state["terminal"]["result"] == "healthy_stop"
                        else 2
                    )
                time.sleep(0.2)
