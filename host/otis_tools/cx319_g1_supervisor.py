"""Fail-static supervisor for the CX319 G1 exact no-write rehearsal.

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

from .active_status_contract import latest_complete_health
from .cx317_abort_path import AbortFifo
from .cx317_active_campaign import (
    ACTIVE_CSV,
    HEALTH_CSV,
    LEASE_PERIOD_S,
    QUERY_PERIOD_S,
    CampaignSpec,
    _read_csv,
)
from .cx318_stage5_supervisor import DAC_CSV, Stage5Leg, Stage5Supervisor
from .cx319_g1_bundle import (
    G1_BENCH_OPERATION,
    POLICY_PATH,
    PROGRAMME_ID,
    REHEARSAL_STAGE,
    normal_command_allowed,
    validate_run_manifest,
)
from .cx319_runtime_contract import (
    TELEMETRY_BASELINE_STABLE_OBSERVATIONS,
    Stage5Readiness,
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


def load_cx319_spec(
    leg: str,
) -> tuple[CampaignSpec, dict[str, str], Stage5Leg]:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if (
        policy.get("policy_id")
        != "CX319_STABILIZED_TIGHT_DEADBAND_FREQUENCY_ONLY_V1"
        or leg not in {"A", "B"}
    ):
        raise ValueError("unexpected CX319 policy or leg identity")
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
        "numerical_policy_sha256": base_policy["bindings"][
            "numerical_preview_policy_sha256"
        ],
    }
    return spec, identities, Stage5Leg(leg, direction, direction_name)


class Cx319G1Supervisor(Stage5Supervisor):
    """Current-identity wrapper with an exact no-write command boundary."""

    def __init__(self, *, leg: Stage5Leg, **kwargs: object) -> None:
        super().__init__(
            mode=EXPECTED_MODE,
            leg=leg,
            allow_manual_start=False,
            allow_arm=False,
            tight_deadband_policy_sha256=_sha256(POLICY_PATH),
            **kwargs,
        )
        self.state["programme_id"] = PROGRAMME_ID
        self.state["cx319_gate"] = "G1"
        self.state["cx319_mode"] = "no_write_rehearsal"
        self.state["cx319_leg"] = leg.leg
        self.state.setdefault("telemetry_drop_candidate", None)
        self.state.setdefault("telemetry_drop_candidate_observations", 0)
        self.state.setdefault("telemetry_drop_last_status_seq", 0)
        self.state.setdefault("telemetry_drop_baseline", None)
        self.state.setdefault("telemetry_drop_baseline_status_seq", None)
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
        if baseline is not None:
            return readiness
        mismatches = list(readiness.mismatches)
        mismatches.append(
            "host-attach telemetry baseline has "
            f"{self.state['telemetry_drop_candidate_observations']}/"
            f"{TELEMETRY_BASELINE_STABLE_OBSERVATIONS} stable observations"
        )
        return Stage5Readiness(
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
        self._observe_telemetry_drop_baseline()
        super()._check_fail_static_health(health)

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
                    self._command("ACTIVE?")
                    last_query = now
                self._process_transactions()
                health = latest_complete_health(self.run_dir / HEALTH_CSV)
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
    args = parser.parse_args(argv)
    try:
        require_programme_operation_allowed(
            PROGRAMME_ID, G1_BENCH_OPERATION
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
        or args.expected_build_identity != expected_build
    ):
        parser.error("manifest run/leg/build does not match G1 supervisor request")
    spec, identities, leg = load_cx319_spec(args.leg)
    supervisor = Cx319G1Supervisor(
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
    )
    try:
        return supervisor.run()
    except (OSError, RuntimeError, SystemExit, TimeoutError, ValueError) as exc:
        supervisor._event("cx319_g1_supervisor_fault", error=str(exc))
        supervisor._abort(f"cx319_g1_supervisor_fault:{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
