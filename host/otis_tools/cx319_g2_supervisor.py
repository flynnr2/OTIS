"""Fail-static CX319 G2 Leg A live supervisor.

This module defines the intended live state machine for offline rehearsal.  Its
CLI remains fail-closed unless the exact ``g2_live_leg`` programme operation is
later granted; the current programme status grants only offline preparation.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from .cx317_active_campaign import ACTIVE_CSV, CampaignSpec, _read_csv
from .cx318_stage5_supervisor import DAC_CSV, Stage5Leg, Stage5Supervisor
from .cx319_g1_bundle import POLICY_PATH, PROGRAMME_ID
from .cx319_g1_supervisor import load_cx319_spec
from .cx319_g2_runtime_contract import evaluate_prewrite_readiness
from .cx319_g2_contract import normal_command_allowed
from .programme_status import (
    CX319_G2_LIVE_LEG,
    ProgrammeExecutionBlocked,
    require_programme_operation_allowed,
)


TOOL_ID = "cx319_g2_supervisor_v1"
G2_LIVE_OPERATION = CX319_G2_LIVE_LEG


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


class Cx319G2Supervisor(Stage5Supervisor):
    """Current-identity Leg A live controller with frozen G2 limits."""

    def __init__(self, **kwargs: object) -> None:
        spec = kwargs.get("spec")
        leg = kwargs.get("leg")
        if not isinstance(spec, CampaignSpec) or not isinstance(leg, Stage5Leg):
            raise TypeError("CX319 G2 requires explicit current spec and leg")
        if leg.leg != "A" or leg.required_direction != 1:
            raise ValueError("CX319 G2 is exactly Leg A positive direction")
        super().__init__(
            mode="live",
            allow_manual_start=True,
            allow_arm=True,
            tight_deadband_policy_sha256=_sha256(POLICY_PATH),
            **kwargs,
        )
        self.state["programme_id"] = PROGRAMME_ID
        self.state["cx319_gate"] = "G2"
        self.state["cx319_mode"] = "live_frequency_only"
        self.state["cx319_leg"] = "A"
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
        return evaluate_prewrite_readiness(
            health,
            expected_identity=identity,
            planned_live_stimulus_code=self.spec.start_code,
            active_row_count=len(_read_csv(self.run_dir / ACTIVE_CSV)),
            dac_row_count=len(_read_csv(self.run_dir / DAC_CSV)),
        )


def create_supervisor(
    *,
    run_dir: Path,
    command_fifo: Path,
    emergency_command_fifo: Path,
    abort_fifo: Path,
    expected_build_identity: str,
    duration_s: float | None = None,
    console_events: bool = False,
) -> Cx319G2Supervisor:
    spec, identities, leg = load_cx319_spec("A")
    return Cx319G2Supervisor(
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
        require_programme_operation_allowed(PROGRAMME_ID, G2_LIVE_OPERATION)
    except ProgrammeExecutionBlocked as exc:
        parser.error(str(exc))
    if args.run_spec is not None:
        value = json.loads(args.run_spec.read_text(encoding="utf-8"))
        if value.get("authority", {}).get("effective") is not True:
            parser.error("CX319 G2 run spec is not an effective operator authority")
        parser.error("use the exact activated run manifest through cx319_g2_run")
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
    from .cx319_g2_live import LIVE_STAGE, validate_run_manifest

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
