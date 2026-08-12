"""Fail-static bounded tight-deadband live supervisor.

This module defines the intended live state machine for offline rehearsal.  Its
CLI remains fail-closed unless the exact ``g2_live_leg`` programme operation is
later granted; the current programme status grants only offline preparation.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import secrets

from .active_transactions import (
    ACTIVE_CSV,
    HEALTH_CSV,
    CampaignSpec,
    _read_csv,
    _utc_now,
)
from .frequency_control_supervisor import DAC_CSV, TightDeadbandLeg, FrequencyControlSupervisor
from .no_write_qualification_bundle import POLICY_PATH, PROGRAMME_ID
from .no_write_qualification_supervisor import load_no_write_qualification_spec
from .bounded_tight_deadband_prewrite_contract import (
    RAW_PPS_QUALIFICATION_DEADLINE_S,
    TELEMETRY_BASELINE_STABLE_OBSERVATIONS,
    PrewriteReadiness,
    evaluate_health_integrity,
    evaluate_prewrite_readiness,
    telemetry_drop_observations,
)
from .bounded_tight_deadband_outcome_contract import normal_command_allowed
from .setup_authority_contract import (
    SETUP_AUTHORITY_CONTRACT,
    SETUP_AUTHORITY_LIFETIME_S,
    SETUP_AUTHORITY_PATH,
    canonical_health,
    write_setup_authority_input,
)
from .programme_status import (
    BOUNDED_TIGHT_DEADBAND_LIVE_LEG,
    ProgrammeExecutionBlocked,
    require_programme_operation_allowed,
)


TOOL_ID = "cx319_g2_supervisor_v1"
BOUNDED_TIGHT_DEADBAND_OPERATION = BOUNDED_TIGHT_DEADBAND_LIVE_LEG


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


class BoundedFrequencyControlSupervisor(FrequencyControlSupervisor):
    """Current-identity Leg A live controller with frozen G2 limits."""

    def __init__(self, **kwargs: object) -> None:
        spec = kwargs.get("spec")
        leg = kwargs.get("leg")
        if not isinstance(spec, CampaignSpec) or not isinstance(leg, TightDeadbandLeg):
            raise TypeError("CX319 G2 requires explicit current spec and leg")
        if leg.leg != "A" or leg.required_direction != 1:
            raise ValueError("CX319 G2 is exactly Leg A positive direction")
        super().__init__(
            mode="live",
            allow_manual_start=True,
            allow_arm=True,
            prewrite_contract_startup_grace_s=(
                RAW_PPS_QUALIFICATION_DEADLINE_S
            ),
            tight_deadband_policy_sha256=_sha256(POLICY_PATH),
            **kwargs,
        )
        self.state["programme_id"] = PROGRAMME_ID
        self.state["cx319_gate"] = "G2"
        self.state["cx319_mode"] = "live_frequency_only"
        self.state["cx319_leg"] = "A"
        self.state.setdefault("telemetry_drop_candidate", None)
        self.state.setdefault("telemetry_drop_candidate_observations", 0)
        self.state.setdefault("telemetry_drop_last_status_seq", 0)
        self.state.setdefault("telemetry_drop_baseline", None)
        self.state.setdefault("telemetry_drop_baseline_status_seq", None)
        self.state.setdefault("host_attach_uptime_s", None)
        self.state.setdefault("host_attach_uptime_status_seq", None)
        self.state.setdefault("host_attach_snapshot_generation", None)
        self.state.setdefault(
            "host_attach_query_nonce", secrets.randbits(32) or 1
        )
        self.state.setdefault("setup_authorization_sequence", 0)
        self.state.setdefault("setup_authority_path", None)
        self._save()

    def _event(self, event: str, **fields: object) -> None:
        current_event = (
            "cx319_g2_" + event[len("stage5_") :]
            if event.startswith("stage5_")
            else event
        )
        super()._event(current_event, programme_id=PROGRAMME_ID, **fields)

    def _command(self, command: str) -> None:
        if not normal_command_allowed(command):
            raise ValueError(
                f"CX319 G2 command is outside the exact normal allowlist: {command}"
            )
        super()._command(command)

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

    def _status_query_command(self) -> str:
        return f"ACTIVE SNAPSHOT {self.state['host_attach_query_nonce']}"

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
            generation = int(
                health[("cx317_active", "snapshot_generation_complete")]
            )
        except (KeyError, ValueError):
            return
        self.state["host_attach_uptime_s"] = uptime_s
        self.state["host_attach_uptime_status_seq"] = generation
        self.state["host_attach_snapshot_generation"] = generation
        self._save()
        self._event(
            "cx319_g2_nonce_bound_host_attach_snapshot_frozen",
            query_nonce=self.state["host_attach_query_nonce"],
            snapshot_generation=generation,
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
                    "cx319_g2_telemetry_attach_candidate_observed",
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
                    "cx319_g2_telemetry_attach_baseline_frozen",
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

    def _setup_command(
        self, health: dict[tuple[str, str], str]
    ) -> tuple[str, dict[str, object]]:
        configuration_identity = self.expected_build_identity.split(":", 1)[1]
        if len(configuration_identity) != 64:
            raise ValueError("setup configuration identity is not SHA-256")
        self.state["setup_authorization_sequence"] = (
            int(self.state["setup_authorization_sequence"]) + 1
        )
        active = "cx317_active"
        request: dict[str, object] = {
            "authorization_sequence": self.state[
                "setup_authorization_sequence"
            ],
            "status_generation": int(
                health[(active, "snapshot_generation_complete")]
            ),
            "query_nonce": int(health[(active, "query_nonce")]),
            "expires_s": int(health[(active, "uptime_s")])
            + SETUP_AUTHORITY_LIFETIME_S,
            "session_id": int(health[(active, "session_id")]),
            "requested_code": self.spec.start_code,
            "one_shot_ordinal": 1,
            "configuration_identity": configuration_identity,
        }
        command = (
            "ACTIVE SETUP "
            f"{request['authorization_sequence']} "
            f"{request['status_generation']} {request['query_nonce']} "
            f"{request['expires_s']} {request['session_id']} "
            f"0x{self.spec.start_code:04X} 1 {configuration_identity}"
        )
        return command, request

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
        baseline = self.state.get("telemetry_drop_baseline")
        write_setup_authority_input(
            path,
            {
                "contract": SETUP_AUTHORITY_CONTRACT,
                "created_utc": _utc_now(),
                "request": request,
                "health": canonical_health(health),
                "active_row_count": len(_read_csv(self.run_dir / ACTIVE_CSV)),
                "dac_row_count": len(_read_csv(self.run_dir / DAC_CSV)),
                "telemetry_drop_baseline": int(baseline or 0),
            },
        )
        self.state["setup_authority_path"] = str(SETUP_AUTHORITY_PATH)
        self._save()
        return path


def create_supervisor(
    *,
    run_dir: Path,
    command_fifo: Path,
    emergency_command_fifo: Path,
    abort_fifo: Path,
    expected_build_identity: str,
    duration_s: float | None = None,
    console_events: bool = False,
) -> BoundedFrequencyControlSupervisor:
    spec, identities, leg = load_no_write_qualification_spec("A")
    return BoundedFrequencyControlSupervisor(
        leg=leg,
        run_dir=run_dir,
        command_fifo=command_fifo,
        abort_fifo=abort_fifo,
        spec=spec,
        identities=identities,
        expected_build_identity=expected_build_identity,
        duration_s=duration_s,
        emergency_command_fifo=emergency_command_fifo,
        console_events=console_events,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-spec", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--command-fifo", type=Path)
    parser.add_argument("--emergency-command-fifo", type=Path)
    parser.add_argument("--abort-fifo", type=Path)
    parser.add_argument("--expected-build-identity")
    parser.add_argument("--duration-s", type=float)
    parser.add_argument("--console-events", action="store_true")
    args = parser.parse_args(argv)
    try:
        require_programme_operation_allowed(PROGRAMME_ID, BOUNDED_TIGHT_DEADBAND_OPERATION)
    except ProgrammeExecutionBlocked as exc:
        parser.error(str(exc))
    if args.run_spec is not None:
        value = json.loads(args.run_spec.read_text(encoding="utf-8"))
        if value.get("authority", {}).get("effective") is not True:
            parser.error("CX319 G2 run spec is not an effective operator authority")
        parser.error("use the exact activated run manifest through bounded_tight_deadband_run")
    required = {
        "manifest": args.manifest,
        "run_dir": args.run_dir,
        "command_fifo": args.command_fifo,
        "emergency_command_fifo": args.emergency_command_fifo,
        "abort_fifo": args.abort_fifo,
        "expected_build_identity": args.expected_build_identity,
    }
    missing = sorted(name for name, value in required.items() if value is None)
    if missing:
        parser.error("missing exact G2 supervisor arguments: " + ", ".join(missing))
    from .bounded_tight_deadband_activation import LIVE_STAGE, validate_run_manifest

    manifest = validate_run_manifest(args.manifest)
    fifo_paths = {
        args.command_fifo.absolute(),
        args.emergency_command_fifo.absolute(),
        args.abort_fifo.absolute(),
    }
    build_identity = (
        manifest["firmware"]["source_sha256"]
        + ":"
        + manifest["firmware"]["configuration_sha256"]
    )
    if (
        len(fifo_paths) != 3
        or args.manifest.resolve() != (args.run_dir / "run_manifest.json").resolve()
        or manifest.get("stage") != LIVE_STAGE
        or manifest.get("cx319", {}).get("leg") != "A"
        or args.expected_build_identity != build_identity
    ):
        parser.error("manifest, FIFOs, leg, or build identity differs")
    supervisor = create_supervisor(
        run_dir=args.run_dir,
        command_fifo=args.command_fifo,
        emergency_command_fifo=args.emergency_command_fifo,
        abort_fifo=args.abort_fifo,
        expected_build_identity=args.expected_build_identity,
        duration_s=args.duration_s,
        console_events=args.console_events,
    )
    try:
        return supervisor.run()
    except (OSError, RuntimeError, SystemExit, TimeoutError, ValueError) as exc:
        supervisor._event("cx319_g2_supervisor_fault", error=str(exc))
        supervisor._abort(f"cx319_g2_supervisor_fault:{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
