"""Accelerated, non-qualifying rehearsal of the Stage 7 Part B host clocks.

This invokes the production Cx317BoundedActiveSupervisor transition methods with a
deterministic clock.  It has no serial, FIFO or actuation authority and cannot
substitute for the 24-hour hardware evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import argparse
import json

from .cx317_active_campaign import _atomic_json
from .cx317_stage7_part_b_matrix import STAGE7_PROMPT, STAGE7_PROMPT_SHA256
from .cx317_bounded_active_supervisor import (
    PART_B_CLEARANCE_GRACE_S,
    PART_B_DURATION_S,
    PART_B_SERVICE_LOAD_QUERIES,
    PART_B_SERVICE_LOAD_STARTS_S,
    BOUNDED_ACTIVE_QUALIFICATION_TIMEOUT_S,
    Cx317BoundedActiveSupervisor,
    _next_selected_interval_is_cadence_eligible,
    load_cx317_bounded_active_spec,
    part_b_timeline_preflight,
)


TOOL_PATH = Path(__file__).resolve()
SUPERVISOR_PATH = TOOL_PATH.with_name("cx317_bounded_active_supervisor.py")
REPO_ROOT = TOOL_PATH.parents[2]


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _supervisor(root: Path) -> Cx317BoundedActiveSupervisor:
    run = root / "run"
    (run / "csv").mkdir(parents=True, exist_ok=True)
    spec, identities = load_cx317_bounded_active_spec("part_b", 0xA82A)
    return Cx317BoundedActiveSupervisor(
        part="part_b",
        run_dir=run,
        command_fifo=root / "command.fifo",
        abort_fifo=root / "abort.fifo",
        spec=spec,
        identities=identities,
        expected_build_identity="a" * 64 + ":" + "b" * 64,
        allow_manual_start=True,
        allow_arm=True,
        duration_s=None,
    )


def _abort_case(
    root: Path,
    *,
    state: dict[str, object],
    health: dict[tuple[str, str], str],
    now_epoch: float,
    expected_reason: str,
) -> bool:
    supervisor = _supervisor(root)
    supervisor.state.update(state)
    commands: list[str] = []
    supervisor._command = commands.append  # type: ignore[method-assign]
    supervisor._maybe_finish(health, now_epoch)
    terminal = supervisor.state.get("terminal") or {}
    return (
        terminal.get("result") == "aborted"
        and terminal.get("reason") == expected_reason
        and commands == ["ACTIVE ABORT"]
    )


def rehearse() -> dict[str, object]:
    """Traverse every duration/service terminal branch with no live I/O."""
    timeline = part_b_timeline_preflight()
    cases: dict[str, bool] = {
        "cross_layer_timeline_satisfiable": all(
            timeline["checks"].values()
        )
    }
    with TemporaryDirectory(prefix="cx317-stage7b-rehearsal-") as temporary:
        root = Path(temporary)

        qualification = _supervisor(root / "qualification")
        qualification._identity_ready = (  # type: ignore[method-assign]
            lambda health: True
        )
        qualification._maybe_qualify(
            {("cx317_active", "manual_start_confirmed"): "true"},
            {
                "decision_id": "ctl:rehearsal:qualification",
                "preview_available": "true",
                "model_applicability": "applicable",
                "diagnostic_health": "healthy",
                "frequency_error_hz": "0.000000000",
            },
        )
        cases["healthy_preview_starts_qualification_clock"] = (
            isinstance(
                qualification.state["qualification_started_utc"], str
            )
            and qualification.state["qualification_started_utc"].endswith(
                "Z"
            )
        )

        cases["qualification_timeout_aborts"] = _abort_case(
            root / "qualification_timeout",
            state={
                "supervisor_started_utc": "1970-01-01T00:00:00Z",
                "qualification_started_utc": None,
            },
            health={},
            now_epoch=float(BOUNDED_ACTIVE_QUALIFICATION_TIMEOUT_S),
            expected_reason="stage7_qualification_timeout",
        )

        service = _supervisor(root / "service")
        service.state["qualification_started_utc"] = "1970-01-01T00:00:00Z"
        service_commands: list[str] = []
        service._command = service_commands.append  # type: ignore[method-assign]
        monotonic = 1.0
        wall = float(PART_B_SERVICE_LOAD_STARTS_S[0] - 1)
        with patch(
            "host.otis_tools.cx317_bounded_active_supervisor.time.time",
            side_effect=lambda: wall,
        ):
            service._service_load(monotonic)
            no_early_service = not service_commands
            for start in PART_B_SERVICE_LOAD_STARTS_S:
                wall = float(start)
                for _ in range(PART_B_SERVICE_LOAD_QUERIES):
                    service._service_load(monotonic)
                    monotonic += 1.01
                service._service_load(monotonic)
                monotonic += 1.01
        cases["four_service_bursts_exact"] = (
            no_early_service
            and service_commands
            == ["CONFIG?"]
            * (
                len(PART_B_SERVICE_LOAD_STARTS_S)
                * PART_B_SERVICE_LOAD_QUERIES
            )
            and service.state["part_b_service_bursts_complete"]
            == list(range(len(PART_B_SERVICE_LOAD_STARTS_S)))
            and service.state["part_b_service_burst_index"] is None
        )

        interlock = _supervisor(root / "service_arm_interlock")
        interlock.state["qualification_started_utc"] = (
            "1970-01-01T00:00:00Z"
        )
        interlock_commands: list[str] = []
        interlock._command = interlock_commands.append  # type: ignore[method-assign]
        interlock.state["arm_pending"] = True
        wall = float(PART_B_SERVICE_LOAD_STARTS_S[0])
        with patch(
            "host.otis_tools.cx317_bounded_active_supervisor.time.time",
            side_effect=lambda: wall,
        ):
            interlock._service_load(1.0)
            pending_arm_delayed_service = not interlock_commands
            interlock.state["arm_pending"] = False
            interlock._service_load(1.0)
        service_started_only_after_clear = (
            interlock_commands == ["CONFIG?"]
            and interlock.state["part_b_service_burst_index"] == 0
        )
        cases["service_and_one_shot_authorization_do_not_overlap"] = (
            pending_arm_delayed_service and service_started_only_after_clear
        )

        cadence = _supervisor(root / "cadence_regression")
        controls = cadence.run_dir / "csv/control_previews_v1.csv"
        estimates = cadence.run_dir / "csv/estimates_v2.csv"
        modulus = (1 << 32) * 16
        spacing = 9_599_940_352
        eligible_ticks = 763_248_107_312
        unwrapped = [
            eligible_ticks - (75 - index) * spacing
            for index in range(78)
        ]
        lines = [
            "control_seq,preview_available,decision_timestamp_ticks,"
            "decision_reason_code\n"
        ]
        for index, ticks in enumerate(unwrapped):
            preview = "true" if index == 75 else "false"
            reason = (
                "inside_evidence_deadband"
                if index == 75
                else "decision_cadence_hold"
            )
            lines.append(
                f"{index},{preview},{ticks % modulus},{reason}\n"
            )
        controls.write_text("".join(lines), encoding="utf-8")
        estimates.write_text(
            "estimate_id,source_count_seq\n", encoding="utf-8"
        )
        cases["failed_1799_second_cadence_boundary_is_not_armed"] = not (
            _next_selected_interval_is_cadence_eligible(
                controls, estimates
            )
        )

        clear_health = {
            ("cx317_active", "state"): "DISARMED",
            ("cx317_active", "evidence_phase"): "evidence_clear",
        }
        stable = _supervisor(root / "stable")
        stable.state.update(
            {
                "qualification_started_utc": "1970-01-01T00:00:00Z",
                "arm_pending": False,
                "duration_elapsed": False,
                "part_b_service_bursts_complete": [0, 1, 2, 3],
            }
        )
        stable._maybe_finish(clear_health, float(PART_B_DURATION_S))
        cases["zero_correction_24h_passes"] = (
            stable.state["duration_elapsed"] is True
            and stable.state["terminal"]["result"] == "healthy_stop"
        )

        boundary = _supervisor(root / "boundary")
        boundary.state.update(
            {
                "qualification_started_utc": "1970-01-01T00:00:00Z",
                "arm_pending": True,
                "duration_elapsed": False,
                "part_b_service_bursts_complete": [0, 1, 2, 3],
            }
        )
        outstanding = {
            ("cx317_active", "state"): "AWAITING_RESPONSE",
            ("cx317_active", "evidence_phase"): "application_preserved",
        }
        boundary._maybe_finish(outstanding, float(PART_B_DURATION_S))
        waiting_only = (
            boundary.state["duration_elapsed"] is True
            and boundary.state["terminal"] is None
        )
        boundary.state["arm_pending"] = False
        boundary._maybe_finish(
            clear_health,
            float(PART_B_DURATION_S + 1500),
        )
        cases["boundary_transaction_clears_inside_grace"] = (
            waiting_only
            and boundary.state["terminal"]["result"] == "healthy_stop"
        )

        no_rearm = _supervisor(root / "no_rearm")
        no_rearm.state.update(
            {
                "manual_start_sent": True,
                "arm_pending": False,
                "duration_elapsed": True,
            }
        )
        arm_commands: list[str] = []
        no_rearm._identity_ready = lambda health: True  # type: ignore[method-assign]
        no_rearm._command = arm_commands.append  # type: ignore[method-assign]
        no_rearm._maybe_start_or_arm(
            {
                ("cx317_active", "state"): "DISARMED",
                ("cx317_active", "manual_start_confirmed"): "true",
                ("cx317_active", "correction_count"): "0",
                ("cx317_active", "arm_eligible"): "true",
                ("cx317_active", "evidence_phase"): "evidence_clear",
                ("cx317_active", "selected_interval_count"): "599",
                ("cx317_active", "uptime_s"): "88800",
            }
        )
        cases["duration_boundary_inhibits_new_arm"] = not arm_commands

        cases["clearance_timeout_aborts"] = _abort_case(
            root / "clearance_timeout",
            state={
                "qualification_started_utc": "1970-01-01T00:00:00Z",
                "arm_pending": True,
                "duration_elapsed": True,
                "part_b_service_bursts_complete": [0, 1, 2, 3],
            },
            health=outstanding,
            now_epoch=float(
                PART_B_DURATION_S + PART_B_CLEARANCE_GRACE_S
            ),
            expected_reason="part_b_clearance_grace_expired",
        )
        cases["incomplete_service_schedule_aborts"] = _abort_case(
            root / "missing_service",
            state={
                "qualification_started_utc": "1970-01-01T00:00:00Z",
                "arm_pending": False,
                "duration_elapsed": False,
                "part_b_service_bursts_complete": [0, 1, 2],
            },
            health=clear_health,
            now_epoch=float(PART_B_DURATION_S),
            expected_reason="part_b_required_service_bursts_incomplete",
        )

        persisted = _supervisor(root / "persisted")
        persisted.state.update(
            {
                "qualification_started_utc": "1970-01-01T00:00:00Z",
                "duration_elapsed": True,
                "part_b_service_bursts_complete": [0, 1, 2, 3],
                "part_b_arm_resume_after_control_seq": 78,
            }
        )
        persisted._save()
        reloaded = _supervisor(root / "persisted")
        cases["duration_and_service_state_persist_exactly"] = (
            reloaded.state["qualification_started_utc"]
            == "1970-01-01T00:00:00Z"
            and reloaded.state["duration_elapsed"] is True
            and reloaded.state["part_b_service_bursts_complete"]
            == [0, 1, 2, 3]
            and reloaded.state["part_b_arm_resume_after_control_seq"] == 78
        )

    return {
        "schema_version": 1,
        "test": "stage7_part_b_accelerated_control_rehearsal",
        "generated_utc": _utc_now(),
        "qualification_evidence": False,
        "hardware_actuation": False,
        "serial_or_fifo_authority": False,
        "production_logic_exercised": [
            "Cx317BoundedActiveSupervisor._maybe_qualify",
            "Cx317BoundedActiveSupervisor._service_load",
            "Cx317BoundedActiveSupervisor._maybe_finish",
            "Cx317BoundedActiveSupervisor._maybe_start_or_arm",
            "Cx317BoundedActiveSupervisor state persistence",
        ],
        "bindings": {
            "supervisor_path": str(SUPERVISOR_PATH.relative_to(REPO_ROOT)),
            "supervisor_sha256": sha256(
                SUPERVISOR_PATH.read_bytes()
            ).hexdigest(),
            "rehearsal_tool_path": str(TOOL_PATH.relative_to(REPO_ROOT)),
            "rehearsal_tool_sha256": sha256(
                TOOL_PATH.read_bytes()
            ).hexdigest(),
            "stage7_prompt_path": STAGE7_PROMPT.as_posix(),
            "stage7_prompt_sha256": STAGE7_PROMPT_SHA256,
        },
        "timeline_preflight": timeline,
        "cases": cases,
        "status": "pass" if all(cases.values()) else "fail",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = rehearse()
    if args.output.exists():
        raise FileExistsError(f"rehearsal report already exists: {args.output}")
    _atomic_json(args.output, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
