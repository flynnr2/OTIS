"""Promote a closed Stage 5 rehearsal to its sealed live segment.

The capture process remains the sole serial owner throughout. This tool sends
no serial, DAC, active-control, firmware, or GPS command. It first rotates the
rehearsal into an exact no-authority transition spool, seals the now-immutable
rehearsal, creates the live manifest from that passed seal, and only then
rotates the same PID/open serial handle into the live segment.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .capture_device import CAPTURE_STATE, SEGMENT_CARRIER_STATE
from .cx318_capture_segment import prepare_transition, request_rotation
from .cx317_active_campaign import ACTIVE_CSV, HEALTH_CSV, _read_csv
from .active_status_contract import latest_complete_health
from .cx318_stage5_manifest import (
    REHEARSAL_STAGE,
    create_manifest,
    validate_manifest,
)
from .cx318_stage5_rehearsal_analyze import (
    OUTPUT as REHEARSAL_SEAL,
    SUPERVISOR_STATE,
    analyze,
)
from .cx318_stage5_runtime_contract import evaluate_prewrite_readiness
from .cx318_stage5_supervisor import DAC_CSV, load_stage5_spec
from .evidence import create_evidence_snapshot
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, COMPLETE_MARKER
from .programme_status import require_programme_execution_allowed


TOOL_ID = "cx318_stage5_promote_v1"
REPORT = Path("reports/cx318_stage5_promotion_v1.json")
STATE = Path("reports/cx318_stage5_promotion_state_v2.json")
EVENTS = Path("reports/cx318_stage5_promotion_events_v2.jsonl")


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _read_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite promotion evidence: {path}")
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_replace_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _advance(state_path: Path, state: dict[str, Any], phase: str, **fields: Any) -> None:
    state.update(fields)
    state["phase"] = phase
    state["updated_utc"] = _utc_now()
    _atomic_replace_json(state_path, state)
    events_path = state_path.parent / EVENTS.name
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {"utc": state["updated_utc"], "phase": phase, **fields},
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        )
        handle.flush()
        os.fsync(handle.fileno())


def _write_complete(run_dir: Path, rotation: dict[str, Any]) -> Path:
    path = run_dir / COMPLETE_MARKER
    payload = (
        json.dumps(
            {
                "completed_utc": _utc_now(),
                "completion": "same_owner_logical_segment_rotation",
                "rotation": rotation,
            },
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path


def _require_healthy_rehearsal(run_dir: Path, manifest: dict[str, Any]) -> str:
    if manifest.get("stage") != REHEARSAL_STAGE:
        raise ValueError("promotion source is not a Stage 5 rehearsal")
    leg = manifest.get("stage5", {}).get("leg")
    if leg not in {"A", "B"}:
        raise ValueError("promotion source has no exact Stage 5 leg")
    if not (run_dir / CAPTURE_IN_PROGRESS_FLAG).is_file():
        raise ValueError("rehearsal capture is not still owned for logical rotation")
    supervisor = _read_object(run_dir / SUPERVISOR_STATE, "Stage 5 supervisor state")
    terminal = supervisor.get("terminal")
    if (
        supervisor.get("stage5_mode") != "rehearsal"
        or supervisor.get("stage5_leg") != leg
        or not isinstance(terminal, dict)
        or terminal.get("result") != "healthy_stop"
        or terminal.get("reason")
        != "2700s_exact_profile_no_write_rehearsal_complete"
    ):
        raise ValueError("rehearsal supervisor has no exact healthy terminal")
    return leg


def _require_prewrite_runtime_contract(
    run_dir: Path, manifest: dict[str, Any], leg: str
) -> dict[str, object]:
    spec, identities, _ = load_stage5_spec(leg)
    expected_build = (
        manifest["firmware"]["source_sha256"]
        + ":"
        + manifest["firmware"]["configuration_sha256"]
    )
    readiness = evaluate_prewrite_readiness(
        latest_complete_health(run_dir / HEALTH_CSV),
        expected_identity={
            "run_identity": spec.run_identity,
            "build_identity": expected_build,
            "profile_identity": spec.profile,
            **identities,
        },
        planned_live_stimulus_code=spec.start_code,
        active_row_count=len(_read_csv(run_dir / ACTIVE_CSV)),
        dac_row_count=len(_read_csv(run_dir / DAC_CSV)),
    )
    if not readiness.ready:
        raise ValueError(
            "rehearsal terminal does not satisfy the shared Stage 5 pre-write "
            f"runtime contract: {readiness.diagnostic()}"
        )
    return readiness.as_dict()


def promote(
    *,
    rehearsal_run: Path,
    transition_run: Path,
    live_run: Path,
    control_dir: Path,
    capability: str,
    leg_a_seal: Path | None = None,
) -> dict[str, Any]:
    rehearsal_run = rehearsal_run.resolve()
    transition_run = transition_run.resolve()
    live_run = live_run.resolve()
    control_dir = control_dir.resolve()
    rehearsal_manifest_path = rehearsal_run / "run_manifest.json"
    rehearsal_manifest = validate_manifest(rehearsal_manifest_path)
    leg = _require_healthy_rehearsal(rehearsal_run, rehearsal_manifest)
    readiness = _require_prewrite_runtime_contract(
        rehearsal_run, rehearsal_manifest, leg
    )

    state_path = transition_run / STATE
    if state_path.is_file():
        existing = _read_object(state_path, "Stage 5 promotion state")
        if existing.get("phase") == "T_TO_L_COMPLETE" and (
            transition_run / REPORT
        ).is_file():
            return _read_object(
                transition_run / REPORT, "completed Stage 5 promotion report"
            )
        if existing.get("phase") == "REHEARSAL_RETRY_REQUIRED":
            raise ValueError(
                "promotion is terminal REHEARSAL_RETRY_REQUIRED; a fresh "
                "rehearsal is required and no rotation was reissued"
            )
        raise ValueError(
            "promotion has an incomplete durable state at phase "
            f"{existing.get('phase')}; refusing to reissue a rotation"
        )

    carrier = _read_object(
        control_dir / SEGMENT_CARRIER_STATE, "capture carrier state"
    )
    capture_state = _read_object(
        rehearsal_run / CAPTURE_STATE, "capture device state"
    )
    if (
        carrier.get("status") != "running"
        or carrier.get("serial_open") is not True
        or Path(str(carrier.get("current_run", ""))).resolve() != rehearsal_run
        or capture_state.get("capture_active") is not True
        or capture_state.get("serial_open") is not True
        or carrier.get("pid") != capture_state.get("pid")
        or carrier.get("transport_generation")
        != capture_state.get("transport_generation")
        or int(carrier.get("reconnect_count", -1)) != 0
    ):
        raise ValueError("capture carrier does not exactly own the rehearsal")

    transition_manifest = prepare_transition(
        rehearsal_manifest_path, transition_run
    )
    promotion_state: dict[str, Any] = {
        "schema_version": 2,
        "tool": TOOL_ID,
        "phase": "PREPARED",
        "created_utc": _utc_now(),
        "updated_utc": _utc_now(),
        "leg": leg,
        "rehearsal_run": str(rehearsal_run),
        "transition_run": str(transition_run),
        "live_run": str(live_run),
        "owner_pid": carrier["pid"],
        "prewrite_runtime_contract": readiness,
    }
    _advance(state_path, promotion_state, "PREPARED")
    rehearsal_rotation = request_rotation(
        control_dir=control_dir,
        capability=capability,
        to_run=transition_run,
        mode="transition",
        operation_id=f"stage5:{rehearsal_run}:R_TO_T",
    )
    if (
        rehearsal_rotation.get("from_run") != str(rehearsal_run)
        or rehearsal_rotation.get("to_run") != str(transition_run)
        or rehearsal_rotation.get("pid") != carrier.get("pid")
        or rehearsal_rotation.get("serial_reopened") is not False
        or int(rehearsal_rotation.get("reconnect_count", -1)) != 0
    ):
        raise ValueError("rehearsal-to-transition rotation acknowledgement differs")
    _advance(
        state_path,
        promotion_state,
        "R_TO_T_COMPLETE",
        rehearsal_rotation=rehearsal_rotation,
    )

    _write_complete(rehearsal_run, rehearsal_rotation)
    evidence_path = create_evidence_snapshot(rehearsal_run)
    rehearsal_seal_path, rehearsal_seal = analyze(rehearsal_run)
    if rehearsal_seal.get("status") != "passed":
        _advance(
            state_path,
            promotion_state,
            "REHEARSAL_RETRY_REQUIRED",
            rehearsal_seal=str(rehearsal_seal_path),
            rehearsal_seal_status=rehearsal_seal.get("status"),
            retained_segment="no_authority_transition",
        )
        raise ValueError("rehearsal did not produce a passed immutable seal")
    _advance(
        state_path,
        promotion_state,
        "REHEARSAL_SEALED_PASSED",
        evidence_snapshot=str(evidence_path),
        rehearsal_seal=str(rehearsal_seal_path),
    )

    firmware = rehearsal_manifest["firmware"]
    stage4 = rehearsal_manifest["stage4_seal"]
    host = rehearsal_manifest["host"]
    live_manifest = create_manifest(
        mode="live",
        leg=leg,
        run_dir=live_run,
        build_manifest_path=Path(firmware["path"]),
        uf2_path=Path(firmware["uf2"]["path"]),
        stage4_seal_path=Path(stage4["path"]),
        rehearsal_seal_path=rehearsal_seal_path,
        leg_a_seal_path=leg_a_seal,
        serial_device=str(host["serial_device"]),
        baud=int(host["baud"]),
    )
    _advance(
        state_path,
        promotion_state,
        "LIVE_MANIFEST_PREPARED",
        live_manifest=str(live_manifest),
    )
    normal_fifo = live_run / "control/commands.fifo"
    emergency_fifo = live_run / "control/emergency.fifo"
    live_rotation = request_rotation(
        control_dir=control_dir,
        capability=capability,
        to_run=live_run,
        mode="live",
        command_fifo=normal_fifo,
        emergency_command_fifo=emergency_fifo,
        operation_id=f"stage5:{rehearsal_run}:T_TO_L",
    )
    if (
        live_rotation.get("from_run") != str(transition_run)
        or live_rotation.get("to_run") != str(live_run)
        or live_rotation.get("pid") != carrier.get("pid")
        or live_rotation.get("serial_reopened") is not False
        or int(live_rotation.get("reconnect_count", -1)) != 0
    ):
        raise ValueError("transition-to-live rotation acknowledgement differs")
    post_carrier = _read_object(
        control_dir / SEGMENT_CARRIER_STATE, "post-promotion carrier state"
    )
    live_capture = _read_object(live_run / CAPTURE_STATE, "live capture state")
    if (
        post_carrier.get("status") != "running"
        or post_carrier.get("serial_open") is not True
        or Path(str(post_carrier.get("current_run", ""))).resolve() != live_run
        or post_carrier.get("pid") != carrier.get("pid")
        or post_carrier.get("transport_generation")
        != live_rotation.get("transport_generation")
        or int(post_carrier.get("reconnect_count", -1)) != 0
        or live_capture.get("capture_active") is not True
        or live_capture.get("serial_open") is not True
        or live_capture.get("pid") != carrier.get("pid")
        or live_capture.get("transport_generation")
        != live_rotation.get("transport_generation")
    ):
        raise ValueError("live carrier/capture state does not match rotation")

    result = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "created_utc": _utc_now(),
        "leg": leg,
        "owner_pid": carrier["pid"],
        "rehearsal_run": str(rehearsal_run),
        "transition_run": str(transition_run),
        "live_run": str(live_run),
        "transition_manifest": str(transition_manifest),
        "evidence_snapshot": str(evidence_path),
        "rehearsal_seal": str(rehearsal_seal_path),
        "live_manifest": str(live_manifest),
        "normal_command_fifo": str(normal_fifo),
        "emergency_command_fifo": str(emergency_fifo),
        "host_abort_fifo": str(live_run / "control/host_abort.fifo"),
        "rehearsal_rotation": rehearsal_rotation,
        "live_rotation": live_rotation,
        "serial_reopened": False,
        "reconnect_count": 0,
        "promotion_state": str(state_path),
        "status": "completed",
    }
    _atomic_new_json(transition_run / REPORT, result)
    _advance(
        state_path,
        promotion_state,
        "T_TO_L_COMPLETE",
        promotion_report=str(transition_run / REPORT),
        live_rotation=live_rotation,
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rehearsal-run", type=Path, required=True)
    parser.add_argument("--transition-run", type=Path, required=True)
    parser.add_argument("--live-run", type=Path, required=True)
    parser.add_argument("--control-dir", type=Path, required=True)
    parser.add_argument("--capability", required=True)
    parser.add_argument("--leg-a-seal", type=Path)
    args = parser.parse_args(argv)
    try:
        require_programme_execution_allowed("cx318_stage5")
        result = promote(
            rehearsal_run=args.rehearsal_run,
            transition_run=args.transition_run,
            live_run=args.live_run,
            control_dir=args.control_dir,
            capability=args.capability,
            leg_a_seal=args.leg_a_seal,
        )
    except (
        FileExistsError,
        FileNotFoundError,
        KeyError,
        OSError,
        TimeoutError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        RuntimeError,
    ) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
