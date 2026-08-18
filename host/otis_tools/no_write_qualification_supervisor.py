"""Fail-static supervisor for an exact no-write qualification rehearsal.

The implementation reuses the selected tight-deadband supervisor mechanics,
but replaces programme identity, policy bindings and command authority. G1 can
submit only read-only queries and active capture leases. Any transaction row or
attempt to submit setup, arm, evidence-release, sweep or pseudo-reference work
is terminal failure.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import time

from .abort_transport import AbortFifo
from .active_transactions import (
    ACTIVE_CSV,
    HEALTH_CSV,
    LEASE_PERIOD_S,
    QUERY_PERIOD_S,
    CampaignSpec,
    _read_csv,
)
from .active_control_supervisor import (
    CAPTURE_TRANSPORT_STATE,
    CAPTURE_TRANSPORT_STATE_MAX_AGE_S,
    _parse_utc_epoch,
)
from .frequency_control_supervisor import DAC_CSV, TightDeadbandLeg, FrequencyControlSupervisor
from .no_write_qualification_bundle import (
    NO_WRITE_BENCH_OPERATION,
    POLICY_PATH,
    PROGRAMME_ID,
    REHEARSAL_STAGE,
    normal_command_allowed,
    validate_run_manifest,
)
from .no_write_prewrite_readiness_contract import (
    RAW_PPS_QUALIFICATION_DEADLINE_S,
    TELEMETRY_BASELINE_STABLE_OBSERVATIONS,
    PrewriteReadiness,
    evaluate_health_integrity,
    evaluate_prewrite_readiness,
    telemetry_drop_observations,
)
from .programme_status import (
    ProgrammeExecutionBlocked,
    require_programme_operation_allowed,
)
from .run_loader import CAPTURE_IN_PROGRESS_FLAG


TOOL_ID = "cx319_g1_supervisor_v1"
EXPECTED_MODE = "rehearsal"


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load_no_write_qualification_spec(
    leg: str,
) -> tuple[CampaignSpec, dict[str, str], TightDeadbandLeg]:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if policy.get("policy_id") != "CX319_STABILIZED_TIGHT_DEADBAND_FREQUENCY_ONLY_V1":
        raise ValueError("unexpected CX319 policy or leg identity")
    if leg == "C":
        expected = (
            "cx319_range_part_b_upper_completion",
            3196003,
            0xA83C,
            "negative",
            -1,
        )
        correction_limit = 2
        cumulative_limit = 42
    elif leg in {"L", "U"}:
        campaign_path = (
            Path(__file__).resolve().parents[2]
            / "profiles/qualification/cx319_conditional_range_campaign_v3.json"
        )
        campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
        part_b = campaign["part_b"]
        leg_index = 0 if leg == "L" else 1
        selected = part_b["legs"][leg_index]
        expected = {
            "L": ("cx319_range_part_b_lower", 3196001, 0xA800, "positive", 1),
            "U": ("cx319_range_part_b_upper", 3196002, 0xA890, "negative", -1),
        }[leg]
        observed = (
            selected.get("profile_id"),
            expected[1],
            selected.get("setup_code"),
            selected.get("required_direction"),
            part_b.get("maximum_corrections_per_leg"),
            part_b.get("maximum_cumulative_movement_codes_per_leg"),
        )
        if observed != (*expected[:4], 9, 189):
            raise ValueError(f"CX319 conditional Part B leg {leg} is not exact")
        correction_limit = 9
        cumulative_limit = 189
    elif leg in {"A", "B"}:
        selected = policy["legs"][leg]
        expected = {
            "A": ("cx319_tight_lower", 3195001, 0xA808, "positive", 1),
            "B": ("cx319_tight_upper", 3195002, 0xA848, "negative", -1),
        }[leg]
        observed = (
            selected.get("firmware_profile"),
            selected.get("run_binding_tag"),
            selected.get("exact_setup_code"),
            selected.get("required_automatic_direction"),
            selected.get("maximum_automatic_corrections"),
            selected.get("maximum_cumulative_automatic_movement_codes"),
        )
        if observed != (*expected[:4], 4, 84):
            raise ValueError(f"CX319 leg {leg} policy is not exact")
        correction_limit = 4
        cumulative_limit = 84
    else:
        raise ValueError("unexpected CX319 policy or leg identity")
    base_binding = policy["bindings"]["inherited_active_policy_root"]
    base_policy = json.loads(
        (Path(__file__).resolve().parents[2] / base_binding["path"]).read_text(
            encoding="utf-8"
        )
    )
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
        raise ValueError("CX319 controller limits or clocks are not exact")
    profile, tag, setup_code, direction_name, direction = expected
    spec = CampaignSpec(
        campaign=f"cx319_leg_{leg.lower()}",
        profile=profile,
        run_identity=f"{profile}:{tag}",
        start_code=setup_code,
        correction_limit=correction_limit,
        cumulative_limit=cumulative_limit,
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
        "numerical_policy_sha256": base_policy["bindings"][
            "numerical_preview_policy_sha256"
        ],
    }
    return spec, identities, TightDeadbandLeg(leg, direction, direction_name)


class NoWriteQualificationSupervisor(FrequencyControlSupervisor):
    """Current-identity wrapper with an exact no-write command boundary."""

    def __init__(
        self,
        *,
        leg: TightDeadbandLeg,
        allowed_initial_reconnect_count: int = 0,
        initial_lease_sequence: int = 0,
        q1_real_io: bool = False,
        qualification_sequence_gate: str = "Q1",
        **kwargs: object,
    ) -> None:
        if allowed_initial_reconnect_count < 0:
            raise ValueError("allowed initial reconnect count cannot be negative")
        if initial_lease_sequence < 0 or initial_lease_sequence > 0xFFFFFFFF:
            raise ValueError("initial lease sequence must be a uint32")
        if qualification_sequence_gate not in {"Q1", "Q3"}:
            raise ValueError("qualification sequence gate must be Q1 or Q3")
        super().__init__(
            mode=EXPECTED_MODE,
            leg=leg,
            allow_manual_start=False,
            allow_arm=False,
            prewrite_contract_startup_grace_s=(
                RAW_PPS_QUALIFICATION_DEADLINE_S
            ),
            tight_deadband_policy_sha256=_sha256(POLICY_PATH),
            **kwargs,
        )
        self.state["programme_id"] = PROGRAMME_ID
        self.state["cx319_gate"] = "G1"
        self.state["cx319_mode"] = "no_write_rehearsal"
        self.state["cx319_leg"] = leg.leg
        self.state["allowed_initial_reconnect_count"] = (
            allowed_initial_reconnect_count
        )
        self.state["lease_sequence"] = initial_lease_sequence
        self.state["q1_real_io"] = q1_real_io
        self.state["qualification_sequence_gate"] = qualification_sequence_gate
        self.state.setdefault("q1_boundary_burst_sent", False)
        self.state.setdefault("telemetry_drop_candidate", None)
        self.state.setdefault("telemetry_drop_candidate_observations", 0)
        self.state.setdefault("telemetry_drop_last_status_seq", 0)
        self.state.setdefault("telemetry_drop_baseline", None)
        self.state.setdefault("telemetry_drop_baseline_status_seq", None)
        self.state.setdefault("host_attach_uptime_s", None)
        self.state.setdefault("host_attach_uptime_status_seq", None)
        self._save()

    def _event(self, event: str, **fields: object) -> None:
        current_event = (
            "cx319_" + event[len("stage5_") :]
            if event.startswith("stage5_")
            else event
        )
        super()._event(current_event, programme_id=PROGRAMME_ID, **fields)

    def _command(self, command: str) -> None:
        if not normal_command_allowed(command):
            raise ValueError(f"CX319 G1 command is outside no-write allowlist: {command}")
        super()._command(command)

    def _process_transactions(self) -> None:
        if _read_csv(self.run_dir / ACTIVE_CSV):
            raise ValueError("CX319 G1 observed an active transaction row")

    def _prewrite_readiness(self, health):  # type: ignore[no-untyped-def]
        identity = {
            "run_identity": self.spec.run_identity,
            "build_identity": self.expected_build_identity,
            "profile_identity": self.spec.profile,
            **self.identities,
        }
        baseline = self.state.get("telemetry_drop_baseline")
        candidate = self.state.get("telemetry_drop_candidate")
        effective_baseline = baseline if baseline is not None else candidate
        readiness = evaluate_prewrite_readiness(
            health,
            expected_identity=identity,
            planned_live_stimulus_code=self.spec.start_code,
            active_row_count=len(_read_csv(self.run_dir / ACTIVE_CSV)),
            dac_row_count=len(_read_csv(self.run_dir / DAC_CSV)),
            telemetry_drop_baseline=int(effective_baseline or 0),
        )
        mismatches = list(readiness.mismatches)
        if baseline is None:
            mismatches.append(
                "host-attach telemetry baseline has "
                f"{self.state['telemetry_drop_candidate_observations']}/"
                f"{TELEMETRY_BASELINE_STABLE_OBSERVATIONS} stable observations"
            )
        if health.get(("cx317_active", "query_nonce")) != str(
            self.state["host_attach_query_nonce"]
        ):
            mismatches.append("solicited post-attachment snapshot is absent")
        host_attach_uptime_s = self.state.get("host_attach_uptime_s")
        if host_attach_uptime_s is None:
            mismatches.append("nonce-bound device-snapshot uptime is not recorded")
        if not mismatches and not readiness.missing:
            return readiness
        return PrewriteReadiness(
            contract_id=readiness.contract_id,
            ready=False,
            missing=readiness.missing,
            mismatches=tuple(dict.fromkeys(mismatches)),
            inherited_preview_baseline_code=(
                readiness.inherited_preview_baseline_code
            ),
            inherited_preview_baseline_provenance=(
                readiness.inherited_preview_baseline_provenance
            ),
            planned_live_stimulus_code=readiness.planned_live_stimulus_code,
            physical_dac_confirmation=readiness.physical_dac_confirmation,
        )

    def _observe_host_attach_uptime(
        self, health: dict[tuple[str, str], str]
    ) -> None:
        if self.state.get("host_attach_uptime_s") is not None:
            return
        if health.get(("cx317_active", "query_nonce")) != str(
            self.state["host_attach_query_nonce"]
        ):
            return
        try:
            uptime_s = int(health[("cx317_active", "uptime_s")])
            status_seq = int(
                health[("cx317_active", "snapshot_generation_complete")]
            )
        except (KeyError, ValueError):
            return
        self.state["host_attach_uptime_s"] = uptime_s
        self.state["host_attach_uptime_status_seq"] = status_seq
        self.state["host_attach_snapshot_generation"] = status_seq
        self._save()
        self._event(
            "cx319_g1_nonce_bound_device_snapshot_frozen",
            query_nonce=self.state["host_attach_query_nonce"],
            snapshot_generation=status_seq,
            status_seq=status_seq,
            uptime_s=uptime_s,
        )

    def _observe_telemetry_drop_baseline(self) -> None:
        if self.state.get("telemetry_drop_baseline") is not None:
            return
        observations = telemetry_drop_observations(
            _read_csv(self.run_dir / HEALTH_CSV)
        )
        last_status_seq = int(self.state["telemetry_drop_last_status_seq"])
        changed = False
        for status_seq, value in observations:
            if status_seq <= last_status_seq:
                continue
            if self.state.get("telemetry_drop_candidate") == value:
                self.state["telemetry_drop_candidate_observations"] = (
                    int(self.state["telemetry_drop_candidate_observations"])
                    + 1
                )
            else:
                self.state["telemetry_drop_candidate"] = value
                self.state["telemetry_drop_candidate_observations"] = 1
                self._event(
                    "cx319_g1_telemetry_attach_candidate_observed",
                    status_seq=status_seq,
                    telemetry_dropped=value,
                )
            if (
                self.state.get("telemetry_drop_baseline") is None
                and int(self.state["telemetry_drop_candidate_observations"])
                >= TELEMETRY_BASELINE_STABLE_OBSERVATIONS
            ):
                self.state["telemetry_drop_baseline"] = value
                self.state["telemetry_drop_baseline_status_seq"] = status_seq
                self._event(
                    "cx319_g1_telemetry_attach_baseline_frozen",
                    status_seq=status_seq,
                    telemetry_dropped=value,
                    stable_observations=(
                        self.state["telemetry_drop_candidate_observations"]
                    ),
                )
            last_status_seq = status_seq
            self.state["telemetry_drop_last_status_seq"] = status_seq
            changed = True
        if changed:
            self._save()

    def _runtime_health_integrity(self, health):  # type: ignore[no-untyped-def]
        baseline = self.state.get("telemetry_drop_baseline")
        candidate = self.state.get("telemetry_drop_candidate")
        effective_baseline = baseline if baseline is not None else candidate
        return evaluate_health_integrity(
            health, telemetry_drop_baseline=int(effective_baseline or 0)
        )

    def _telemetry_drop_runtime_healthy(self, observed: str | None) -> bool:
        baseline = self.state.get("telemetry_drop_baseline")
        candidate = self.state.get("telemetry_drop_candidate")
        effective_baseline = baseline if baseline is not None else candidate
        if observed is None or effective_baseline is None:
            return observed is None
        try:
            return int(observed) == int(effective_baseline)
        except ValueError:
            return False

    def _check_fail_static_health(self, health):  # type: ignore[no-untyped-def]
        self._observe_host_attach_uptime(health)
        self._observe_telemetry_drop_baseline()
        super()._check_fail_static_health(health)

    def _check_capture_transport_state(self) -> dict[str, object]:
        allowed = int(self.state["allowed_initial_reconnect_count"])
        if allowed == 0:
            return super()._check_capture_transport_state()
        path = self.run_dir / CAPTURE_TRANSPORT_STATE
        if not path.is_file():
            raise ValueError("capture transport state is missing")
        state = json.loads(path.read_text(encoding="utf-8"))
        age_s = time.time() - _parse_utc_epoch(str(state["updated_utc"]))
        if age_s < -1 or age_s > CAPTURE_TRANSPORT_STATE_MAX_AGE_S:
            raise ValueError(f"capture transport state is stale: age_s={age_s:.3f}")
        exact = {
            "capture_active": True,
            "serial_open": True,
            "command_fifo_configured": True,
            "emergency_command_fifo_configured": True,
            "state_heartbeat_interval_s": 5.0,
            "normal_command_batch_limit": 1,
            "normal_command_max_age_s": 2.0,
            "write_timeout_s": 1.0,
            "serial_exclusive_requested": True,
            "reconnect_count": allowed,
            "intentional_detach_count": allowed,
        }
        for key, expected in exact.items():
            if state.get(key) != expected:
                raise ValueError(
                    "capture transport state mismatch: "
                    f"{key}={state.get(key)!r}, expected {expected!r}"
                )
        gaps = state.get("intentional_detach_gaps_ms")
        if (
            not isinstance(gaps, list)
            or len(gaps) != allowed
            or any(not isinstance(gap, (int, float)) or gap >= 2000 for gap in gaps)
        ):
            raise ValueError("Q1 intentional detach gaps are incomplete or out of bounds")
        for key in (
            "malformed_utf8",
            "parser_errors",
            "commands_rejected",
            "emergency_aborts_sent",
        ):
            if int(state.get(key, -1)) != 0:
                raise ValueError(
                    f"capture transport counter {key} is {state.get(key)!r}"
                )
        return state

    def run(self) -> int:
        """Run to a clean G1 terminal before the transport-abort exercise.

        Capture remains the sole serial owner after this supervisor exits. The
        runner then obstructs that owner and exercises the independent abort
        path without racing ongoing query or lease submissions.
        """

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
                    self._command(self._status_query_command())
                    last_query = now
                if (
                    self.state["q1_real_io"]
                    and not self.state["q1_boundary_burst_sent"]
                    and now - started >= RAW_PPS_QUALIFICATION_DEADLINE_S - 10
                ):
                    self._command("CONFIG?")
                    self._command("FC0?")
                    self._command(self._status_query_command())
                    self.state["q1_boundary_burst_sent"] = True
                    self._save()
                    self._event(
                        "cx319_q1_qualification_boundary_burst_sent",
                        boundary_s=RAW_PPS_QUALIFICATION_DEADLINE_S,
                    )
                self._process_transactions()
                health = self._current_health()
                self._check_fail_static_health(health)
                self._check_prewrite_contract(health, now - started)
                self._maybe_qualify(health)
                self._maybe_finish(health, time.time(), now - started)
                self._maybe_start_or_arm(health)
                terminal = self.state.get("terminal")
                if isinstance(terminal, dict):
                    if not self.state["terminal_event_emitted"]:
                        self._event("stage5_campaign_terminal", **terminal)
                        self.state["terminal_event_emitted"] = True
                        self._save()
                    return 0 if terminal.get("result") == "healthy_stop" else 2
                time.sleep(0.2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--leg", choices=("A", "B"), required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--command-fifo", type=Path, required=True)
    parser.add_argument("--emergency-command-fifo", type=Path, required=True)
    parser.add_argument("--abort-fifo", type=Path, required=True)
    parser.add_argument("--expected-build-identity", required=True)
    parser.add_argument("--duration-s", type=float)
    parser.add_argument("--console-events", action="store_true")
    parser.add_argument("--allowed-initial-reconnect-count", type=int, default=0)
    parser.add_argument("--initial-lease-sequence", type=int, default=0)
    parser.add_argument("--q1-real-io", action="store_true")
    parser.add_argument(
        "--qualification-sequence-gate", choices=("Q1", "Q3"), default="Q1"
    )
    args = parser.parse_args(argv)
    try:
        require_programme_operation_allowed(
            PROGRAMME_ID, NO_WRITE_BENCH_OPERATION
        )
    except ProgrammeExecutionBlocked as exc:
        parser.error(str(exc))
    fifo_paths = {
        args.command_fifo.absolute(),
        args.emergency_command_fifo.absolute(),
        args.abort_fifo.absolute(),
    }
    if len(fifo_paths) != 3:
        parser.error("normal, emergency and host-abort FIFOs must be distinct")
    manifest = validate_run_manifest(args.manifest)
    expected_build = (
        manifest["firmware"]["source_sha256"]
        + ":"
        + manifest["firmware"]["configuration_sha256"]
    )
    if (
        args.manifest.resolve() != (args.run_dir / "run_manifest.json").resolve()
        or manifest.get("stage") != REHEARSAL_STAGE
        or manifest.get("cx319", {}).get("leg") != args.leg
        or manifest.get("cx319", {}).get(
            "qualification_sequence_gate", "Q1"
        )
        != args.qualification_sequence_gate
        or args.expected_build_identity != expected_build
    ):
        parser.error("manifest run/leg/build does not match G1 supervisor request")
    spec, identities, leg = load_no_write_qualification_spec(args.leg)
    supervisor = NoWriteQualificationSupervisor(
        leg=leg,
        run_dir=args.run_dir,
        command_fifo=args.command_fifo,
        abort_fifo=args.abort_fifo,
        spec=spec,
        identities=identities,
        expected_build_identity=args.expected_build_identity,
        duration_s=args.duration_s,
        emergency_command_fifo=args.emergency_command_fifo,
        console_events=args.console_events,
        allowed_initial_reconnect_count=args.allowed_initial_reconnect_count,
        initial_lease_sequence=args.initial_lease_sequence,
        q1_real_io=args.q1_real_io,
        qualification_sequence_gate=args.qualification_sequence_gate,
    )
    try:
        return supervisor.run()
    except (OSError, RuntimeError, SystemExit, TimeoutError, ValueError) as exc:
        supervisor._event("cx319_g1_supervisor_fault", error=str(exc))
        supervisor._abort(f"cx319_g1_supervisor_fault:{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
