"""Execute, close, analyze, seal and register one authorized CX319 G2 leg.

This is the sole G2 physical entry point.  It deliberately does not flash
firmware: the activation binds the exact G1-qualified firmware, and the
pre-write runtime identity must match before the one setup stimulus is sent.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time
from typing import Any

from .board_identity import read_board_identity
from .cx319_g1_rehearsal import _wait_until
from .cx319_g2_contract import (
    MAXIMUM_QUALIFIED_DURATION_S,
    QUALIFICATION_DEADLINE_S,
)
from .cx319_g2_live import (
    RUN_ACTIVATION_PATH,
    RUN_PROPOSAL_PATH,
    create_run_manifest,
    validate_activation,
    validate_run_manifest,
)
from .cx319_g2_live_analyze import analyze
from .evidence import create_evidence_snapshot, validate_evidence_snapshot
from .evidence_index import DEFAULT_INDEX, register_package
from .platform_rehearsal import _capture_state_ready, _serial_owner_pids
from .programme_status import (
    CX319_G2_LIVE_LEG,
    require_programme_operation_allowed,
)
from .cx319_g1_bundle import PROGRAMME_ID
from .run_loader import load_manifest
from .serial_commands import send_timestamped_command_to_fifo


TOOL_ID = "cx319_g2_run_v1"
CAPTURE_LOG = Path("reports/cx319_g2_capture_launcher.log")
SUPERVISOR_LOG = Path("reports/cx319_g2_supervisor.log")
ORCHESTRATION_FAILURE = Path("reports/cx319_g2_orchestration_failure_v1.json")
MAXIMUM_WALL_S = QUALIFICATION_DEADLINE_S + MAXIMUM_QUALIFIED_DURATION_S


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    from .cx319_g2_live import _atomic_new_json as write

    write(path, value)


def _copy_immutable(source: Path, destination: Path) -> None:
    payload = source.resolve().read_bytes()
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        written = os.write(descriptor, payload)
        if written != len(payload):
            raise OSError(
                f"short immutable copy: expected {len(payload)}, wrote {written}"
            )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _terminal(run_dir: Path) -> dict[str, Any] | None:
    state = _read_json(run_dir / "reports/cx317_active_supervisor_state.json")
    terminal = state.get("terminal") if state else None
    return terminal if isinstance(terminal, dict) else None


def _terminal_expected(terminal: dict[str, Any] | None) -> bool:
    if terminal is None:
        return False
    return (
        terminal.get("result") == "healthy_stop"
        and terminal.get("reason")
        == "required_direction_and_two_estimate_tight_entry"
    ) or (
        terminal.get("result") == "aborted"
        and terminal.get("reason")
        in {
            "stage5_qualification_deadline_expired",
            "stage5_finite_qualified_endpoint_nonpass",
        }
    )


def _write_complete(run_dir: Path, terminal: dict[str, Any]) -> None:
    payload = (
        json.dumps(
            {
                "completed_utc": _utc_now(),
                "completion": "cx319_g2_finite_physical_leg",
                "terminal": terminal,
            },
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    descriptor = os.open(
        run_dir / "COMPLETE", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
    )
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _graceful_capture_stop(capture: subprocess.Popen[str]) -> int:
    if capture.poll() is None:
        capture.send_signal(signal.SIGINT)
    try:
        return capture.wait(timeout=30.0)
    except subprocess.TimeoutExpired:
        capture.send_signal(signal.SIGINT)
        try:
            return capture.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            capture.terminate()
            return capture.wait(timeout=5.0)


def _retain_failure(
    *,
    run_dir: Path,
    activation: dict[str, Any],
    evidence_index_path: Path,
    error: Exception,
) -> dict[str, Any]:
    failure = {
        "schema_version": 1,
        "report_type": "cx319_g2_orchestration_failure_v1",
        "tool": TOOL_ID,
        "programme_id": PROGRAMME_ID,
        "gate": "G2",
        "leg": "A",
        "attempt_classification": "failed_live_leg",
        "failure_class": "platform_or_live_stop_rule_failure",
        "recorded_utc": _utc_now(),
        "error_type": type(error).__name__,
        "error": str(error),
        "terminal": _terminal(run_dir),
        "activation_sha256": activation["activation_sha256"],
        "claims_boundary": (
            "Retained failed G2 evidence only; this grants no retry, G3, "
            "phase, hybrid, or later-programme authority."
        ),
    }
    _atomic_new_json(run_dir / ORCHESTRATION_FAILURE, failure)
    return register_package(
        index_path=evidence_index_path,
        package_path=run_dir,
        source_revision="g2-activation:" + activation["activation_sha256"],
        build_identity=activation["proposal"]["bundle_sha256"],
        profile_identity="cx319_tight_lower",
        attempt_classification="failed_live_leg",
        result_or_failure_reason=f"CX319 G2 orchestration failed: {error}",
        analyzer_identity=_sha256_file(Path(__file__)),
    )


def run_live_leg(
    *,
    activation_path: Path,
    run_dir: Path,
    evidence_index_path: Path,
    arduino_cli: str,
) -> dict[str, Any]:
    require_programme_operation_allowed(PROGRAMME_ID, CX319_G2_LIVE_LEG)
    activation_path = activation_path.resolve()
    activation, proposal = validate_activation(activation_path)
    run_dir = run_dir.resolve()
    if run_dir.exists():
        raise FileExistsError(f"CX319 G2 run already exists: {run_dir}")
    device = str(activation["device"]["path"])
    owners = _serial_owner_pids(device)
    if owners:
        raise ValueError(f"serial device already has owners: {sorted(owners)}")
    board = read_board_identity(device, arduino_cli=arduino_cli)
    if (
        board.get("serial_number")
        != activation["device"]["expected_board_serial"]
    ):
        raise ValueError("connected board serial differs from G2 activation")

    run_dir.mkdir(parents=True)
    (run_dir / "reports").mkdir()
    run_activation = run_dir / RUN_ACTIVATION_PATH
    run_proposal = run_dir / RUN_PROPOSAL_PATH
    _copy_immutable(activation_path, run_activation)
    _copy_immutable(Path(activation["proposal"]["path"]), run_proposal)
    manifest_path = run_dir / "run_manifest.json"
    create_run_manifest(
        activation_path=run_activation,
        proposal_path=run_proposal,
        run_dir=run_dir,
        output_path=manifest_path,
    )
    validate_run_manifest(manifest_path)

    normal_fifo = run_dir / "control/normal_commands.fifo"
    emergency_fifo = run_dir / "control/emergency_abort.fifo"
    host_abort_fifo = run_dir / "control/host_abort.fifo"
    capture_log = (run_dir / CAPTURE_LOG).open("x", encoding="utf-8")
    supervisor_log = (run_dir / SUPERVISOR_LOG).open("x", encoding="utf-8")
    capture_args = [
        sys.executable,
        "-m",
        "host.otis_tools.capture_device",
        "--device",
        device,
        "--run-dir",
        str(run_dir),
        "--duration-s",
        str(MAXIMUM_WALL_S + 180.0),
        "--status-interval",
        "5",
        "--command-fifo",
        str(normal_fifo),
        "--emergency-command-fifo",
        str(emergency_fifo),
        "--write-timeout-s",
        "1",
        "--normal-command-max-age-s",
        "2",
    ]
    capture = subprocess.Popen(
        capture_args,
        cwd=Path(__file__).resolve().parents[2],
        stdout=capture_log,
        stderr=capture_log,
        text=True,
    )
    supervisor: subprocess.Popen[str] | None = None
    orchestration_error: Exception | None = None
    try:
        _wait_until(
            lambda: (
                capture.poll() is None
                and normal_fifo.exists()
                and emergency_fifo.exists()
                and stat.S_ISFIFO(normal_fifo.stat().st_mode)
                and stat.S_ISFIFO(emergency_fifo.stat().st_mode)
                and _capture_state_ready(run_dir, capture.pid)
            ),
            20.0,
            "G2 sole capture ownership and bounded command paths",
        )
        expected_build = (
            proposal["firmware"]["source_sha256"]
            + ":"
            + proposal["firmware"]["configuration_sha256"]
        )
        supervisor_args = [
            sys.executable,
            "-m",
            "host.otis_tools.cx319_g2_supervisor",
            "--manifest",
            str(manifest_path),
            "--run-dir",
            str(run_dir),
            "--command-fifo",
            str(normal_fifo),
            "--emergency-command-fifo",
            str(emergency_fifo),
            "--abort-fifo",
            str(host_abort_fifo),
            "--expected-build-identity",
            expected_build,
            "--duration-s",
            str(MAXIMUM_WALL_S + 120.0),
        ]
        supervisor = subprocess.Popen(
            supervisor_args,
            cwd=Path(__file__).resolve().parents[2],
            stdout=supervisor_log,
            stderr=supervisor_log,
            text=True,
        )
        _wait_until(
            lambda: supervisor.poll() is None and host_abort_fifo.exists(),
            15.0,
            "G2 supervisor and independent host abort",
        )
        _wait_until(
            lambda: _terminal(run_dir) is not None or supervisor.poll() is not None,
            MAXIMUM_WALL_S + 120.0,
            "finite G2 supervisor terminal",
        )
        terminal = _terminal(run_dir)
        if not _terminal_expected(terminal):
            raise RuntimeError(
                "G2 supervisor reached a non-canonical terminal: "
                + json.dumps(terminal, sort_keys=True)
            )
        expected_exit = 0 if terminal["result"] == "healthy_stop" else 2
        try:
            supervisor_exit = supervisor.wait(timeout=15.0)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("G2 supervisor did not exit at its finite terminal") from exc
        if supervisor_exit != expected_exit:
            raise RuntimeError(
                f"G2 supervisor exited {supervisor_exit}, expected {expected_exit}"
            )
        capture_exit = _graceful_capture_stop(capture)
        if capture_exit != 0:
            raise RuntimeError(f"G2 capture exited with status {capture_exit}")
    except Exception as exc:
        orchestration_error = exc
        if emergency_fifo.exists() and capture.poll() is None:
            try:
                send_timestamped_command_to_fifo(emergency_fifo, "ACTIVE ABORT")
                time.sleep(0.5)
            except (OSError, TimeoutError, ValueError):
                pass
        _graceful_capture_stop(capture)
    finally:
        capture_log.close()
        supervisor_log.close()
        if supervisor is not None and supervisor.poll() is None:
            supervisor.terminate()
            try:
                supervisor.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                supervisor.kill()
                supervisor.wait(timeout=5.0)
        if capture.poll() is None:
            capture.terminate()
            capture.wait(timeout=5.0)

    if orchestration_error is not None:
        indexed = _retain_failure(
            run_dir=run_dir,
            activation=activation,
            evidence_index_path=evidence_index_path,
            error=orchestration_error,
        )
        raise RuntimeError(
            "CX319 G2 orchestration failed; retained evidence "
            f"{indexed['content_sha256']}: {orchestration_error}"
        ) from orchestration_error

    terminal = _terminal(run_dir)
    assert terminal is not None
    _write_complete(run_dir, terminal)
    snapshot_path = create_evidence_snapshot(run_dir)
    loaded = load_manifest(run_dir)
    failures, warnings = validate_evidence_snapshot(run_dir, loaded)
    if failures or warnings:
        raise RuntimeError(
            "CX319 G2 evidence snapshot validation failed: "
            + json.dumps({"failures": failures, "warnings": warnings})
        )
    seal_path, seal = analyze(run_dir)
    classification = (
        "successful_live_leg"
        if seal["status"] == "passed"
        else "bounded_nonpass_live_leg"
        if seal["status"] == "bounded_nonpass"
        else "failed_live_leg"
    )
    indexed = register_package(
        index_path=evidence_index_path,
        package_path=run_dir,
        source_revision=proposal["source_revision"],
        build_identity=proposal["firmware"]["build_manifest"]["sha256"],
        profile_identity=proposal["leg_spec"]["profile_id"],
        attempt_classification=classification,
        result_or_failure_reason=f"CX319 G2 {seal['status']}",
        analyzer_identity=seal["tool_sha256"],
    )
    if seal["status"] == "failed":
        raise RuntimeError(
            "CX319 G2 integrity analysis failed; retained evidence "
            f"{indexed['content_sha256']}"
        )
    return {
        "status": seal["status"],
        "run_dir": str(run_dir),
        "activation_sha256": activation["activation_sha256"],
        "proposal_bundle_sha256": proposal["bundle_sha256"],
        "firmware_flashes": 0,
        "analysis_and_seal": str(seal_path),
        "seal_sha256": seal["seal_sha256"],
        "evidence_snapshot": str(snapshot_path),
        "evidence_content_sha256": indexed["content_sha256"],
        "evidence_index": str(evidence_index_path.expanduser().resolve()),
        "board": board,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activation", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--evidence-index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--arduino-cli", default="arduino-cli")
    args = parser.parse_args(argv)
    try:
        result = run_live_leg(
            activation_path=args.activation,
            run_dir=args.run_dir,
            evidence_index_path=args.evidence_index,
            arduino_cli=args.arduino_cli,
        )
    except (
        FileExistsError,
        FileNotFoundError,
        KeyError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
