"""Execute, finalize, seal, and register one exact CX320 physical campaign.

The runner owns process lifecycle, not the serial device.  ``capture_device``
remains the sole serial owner and exposes separate normal and priority-abort
FIFOs.  The runner performs one manifest-bound upload and has no controller
retry or restoration path.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import signal
import stat
import subprocess
import sys
import time
from typing import Any, Callable, IO

from .active_hybrid_activation import (
    EXPECTED_BOARD_SERIAL,
    OPERATION,
    RUN_ACTIVATION_PATH,
    RUN_BUNDLE_PATH,
    RUN_MANIFEST_PATH,
    RUN_PROPOSAL_PATH,
    create_run_manifest,
    validate_activation,
    validate_frozen_run_manifest,
)
from .active_status_live_state import LIVE_STATE_PATH, read_live_health_state
from .active_hybrid_programme_contract import (
    ActiveHybridProgramme,
    CX320_PROGRAMME,
    programme_from_mapping,
)
from .board_identity import read_board_identity
from .capture_device import _detect_single_device
from .capture_runtime_checks import _capture_state_ready, _serial_owner_pids
from .evidence import (
    EVIDENCE_MANIFEST,
    create_evidence_snapshot,
    validate_evidence_snapshot,
)
from .evidence_finalization import (
    advance_phase,
    begin_finalization,
    journal_path_for,
    record_failure,
    recover_registration,
    set_registration_intent,
)
from .evidence_index import DEFAULT_INDEX, package_identity, register_package
from .programme_status import require_programme_operation_allowed
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, load_manifest
from .serial_commands import send_timestamped_command_to_fifo


TOOL_ID = "cx320_active_hybrid_physical_runner_v1"
STATUS_PROGRAMME_ID = "cx320_bounded_active_hybrid"
CAPTURE_LOG = Path("reports/cx320_active_hybrid_capture.log")
SUPERVISOR_LOG = Path("reports/cx320_active_hybrid_supervisor.log")
SUPERVISOR_STATE = Path("reports/cx317_active_supervisor_state.json")
ORCHESTRATION_FAILURE = Path("reports/cx320_active_hybrid_orchestration_failure_v1.json")
ABORT_DELIVERY_FAILURE = Path(
    "reports/cx320_active_hybrid_abort_delivery_failure_v1.json"
)
FLASH_RECORD = Path("reports/cx320_active_hybrid_firmware_entry_v1.json")
FINALIZATION_FAILURE = Path("reports/cx320_active_hybrid_finalization_failure_v1.json")
LIVE_SEAL = Path("reports/cx320_active_hybrid_physical_seal_v1.json")
COMPLETE = Path("COMPLETE")
NORMAL_FIFO = Path("control/normal_commands.fifo")
EMERGENCY_FIFO = Path("control/emergency_abort.fifo")
HOST_ABORT_FIFO = Path("control/host_abort.fifo")
ABSOLUTE_WALL_LIMIT_S = 57_600
CAPTURE_DURATION_S = ABSOLUTE_WALL_LIMIT_S + 180
SUPERVISOR_DURATION_S = ABSOLUTE_WALL_LIMIT_S + 120
PROCESS_START_TIMEOUT_S = 30.0
ABORT_DELIVERY_TIMEOUT_S = 15.0
CAPTURE_STOP_TIMEOUT_S = 30.0
COMPLETED_INDEX_CLASSIFICATION = "completed_campaign"
INTERRUPTED_INDEX_CLASSIFICATION = "interrupted_campaign"
PRIMARY_DECISIONS = {
    "bounded_active_hybrid_control_passed",
    "phase_influence_not_exercised",
    "first_phase_transaction_passed_sustained_result_incomplete",
    "phase_channel_degraded_frequency_control_retained",
    "hybrid_response_wrong_or_frequency_not_reacquired",
    "hybrid_policy_chatter_or_budget_nonpass",
    "frequency_performance_materially_degraded",
    "right_censored_incomplete",
    "measurement_authority_or_platform_fault",
    "operator_abort",
}
HEALTHY_PRELIMINARY_DECISIONS = {
    "pending_offline_scientific_analysis",
    "phase_influence_not_exercised",
    "first_phase_transaction_passed_sustained_result_incomplete",
    "hybrid_response_wrong_or_frequency_not_reacquired",
}


def _programme_path(
    path: Path, programme: ActiveHybridProgramme
) -> Path:
    if programme is CX320_PROGRAMME:
        return path
    return Path(str(path).replace("cx320", programme.key))


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        if os.write(descriptor, payload) != len(payload):
            raise OSError(f"short immutable JSON write: {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _copy_immutable(source: Path, destination: Path) -> None:
    payload = source.resolve().read_bytes()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444
    )
    try:
        if os.write(descriptor, payload) != len(payload):
            raise OSError(f"short immutable copy: {destination}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _wait_until(
    predicate: Callable[[], bool], timeout_s: float, description: str
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise TimeoutError(f"timed out waiting for {description}")


def _locate_board_by_serial(
    expected_serial: str, *, arduino_cli: str
) -> tuple[str, dict[str, str]]:
    listing = json.loads(
        subprocess.run(
            [arduino_cli, "board", "list", "--format", "json"],
            text=True,
            capture_output=True,
            check=True,
            timeout=15,
        ).stdout
    )
    addresses = [
        str(item.get("port", {}).get("address", ""))
        for item in listing.get("detected_ports", [])
        if item.get("port", {}).get("properties", {}).get("serialNumber")
        == expected_serial
    ]
    if len(addresses) != 1:
        raise ValueError(
            f"expected exactly one board serial {expected_serial}, got {addresses}"
        )
    address = addresses[0]
    return address, read_board_identity(address, arduino_cli=arduino_cli)


def _fresh_auto_detect_device() -> str:
    """Resolve the current sole USB CDC path without retaining an old path."""

    try:
        return _detect_single_device()
    except SystemExit as exc:
        raise ValueError(str(exc)) from exc


def _upload_exact_firmware(
    *,
    run_dir: Path,
    activation: dict[str, Any],
    device: str,
    board_before: dict[str, str],
    arduino_cli: str,
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    authority = activation["authority"]
    firmware = activation["firmware"]
    if authority.get("firmware_flash_limit") != 1:
        raise ValueError("CX320 activation does not grant exactly one firmware upload")
    command = [
        arduino_cli,
        "upload",
        "--port",
        device,
        "--fqbn",
        str(firmware["fqbn"]),
        "--input-file",
        str(firmware["uf2"]["path"]),
    ]
    started_utc = _utc_now()
    completed = subprocess.run(
        command, text=True, capture_output=True, check=False, timeout=120
    )
    device_after: str | None = None
    board_after: dict[str, str] | None = None
    reappearance_error = ""
    if completed.returncode == 0:
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            try:
                if programme.fresh_serial_auto_detect:
                    device_after = _fresh_auto_detect_device()
                    board_after = read_board_identity(
                        device_after, arduino_cli=arduino_cli
                    )
                else:
                    device_after, board_after = _locate_board_by_serial(
                        EXPECTED_BOARD_SERIAL, arduino_cli=arduino_cli
                    )
                break
            except (
                OSError,
                ValueError,
                subprocess.SubprocessError,
                json.JSONDecodeError,
            ) as exc:
                reappearance_error = str(exc)
                time.sleep(0.5)
    expected_serial = (
        None if programme.fresh_serial_auto_detect else EXPECTED_BOARD_SERIAL
    )
    passed = (
        completed.returncode == 0
        and device_after is not None
        and board_after is not None
        and board_before.get("serial_number")
        == board_after.get("serial_number")
        and (
            programme.fresh_serial_auto_detect
            or board_after.get("serial_number") == EXPECTED_BOARD_SERIAL
        )
    )
    record = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "operation": f"exact_{programme.key}_firmware_upload",
        "status": "passed" if passed else "failed",
        "started_utc": started_utc,
        "completed_utc": _utc_now(),
        "firmware_flash_count": 1,
        "command": command,
        "exit_code": completed.returncode,
        "stdout_sha256": sha256(completed.stdout.encode()).hexdigest(),
        "stderr_sha256": sha256(completed.stderr.encode()).hexdigest(),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
        "expected_board_serial": expected_serial,
        "device_selection": (
            "fresh_capture_device_--auto-detect"
            if programme.fresh_serial_auto_detect
            else "expected_board_serial"
        ),
        "board_identity_confirmed_before": True,
        "board_identity_confirmed_after": passed,
        "usb_reenumerated": board_after is not None,
        "device_before": device,
        "device_after": device_after,
        "serial_path_changed": device_after not in {None, device},
        "board_before": board_before,
        "board_after": board_after,
        "board_reappearance_error": reappearance_error,
        "bundle_sha256": activation["bundle"]["bundle_sha256"],
        "build_identity": firmware["build_identity"],
        "uf2_sha256": firmware["uf2"]["sha256"],
        "profile_id": firmware["profile_id"],
        "dac_boot_operation": "i2c_address_probe_only",
        "dac_value_write_attempts": 0,
    }
    record["record_sha256"] = sha256(
        json.dumps(
            record, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    _atomic_new_json(run_dir / _programme_path(FLASH_RECORD, programme), record)
    if not passed:
        raise RuntimeError(
            "exact CX320 upload or board re-enumeration failed; automatic retry is forbidden"
        )
    assert device_after is not None and board_after is not None
    return device_after, board_after, record


def _capture_command(
    *,
    device: str,
    run_dir: Path,
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "host.otis_tools.capture_device",
    ]
    command.extend(
        [
            "--auto-detect",
            "--expected-auto-detect-device",
            device,
        ]
        if programme.fresh_serial_auto_detect
        else ["--device", device]
    )
    command.extend([
        "--run-dir",
        str(run_dir),
        "--duration-s",
        str(programme.capture_duration_s),
        "--status-interval",
        "5",
        "--command-fifo",
        str(run_dir / NORMAL_FIFO),
        "--emergency-command-fifo",
        str(run_dir / EMERGENCY_FIFO),
        "--write-timeout-s",
        "1",
        "--normal-command-max-age-s",
        "2",
    ])
    return command


def _supervisor_command(
    *,
    run_dir: Path,
    build_identity: str,
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "host.otis_tools.active_hybrid_live_supervisor",
        "--manifest",
        str(run_dir / RUN_MANIFEST_PATH),
        "--run-dir",
        str(run_dir),
        "--command-fifo",
        str(run_dir / NORMAL_FIFO),
        "--emergency-command-fifo",
        str(run_dir / EMERGENCY_FIFO),
        "--abort-fifo",
        str(run_dir / HOST_ABORT_FIFO),
        "--expected-build-identity",
        build_identity,
        "--duration-s",
        str(programme.supervisor_duration_s),
    ]


def _launch_process(command: list[str], log: IO[str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        command,
        cwd=Path(__file__).resolve().parents[2],
        stdout=log,
        stderr=log,
        text=True,
    )


def _terminal(run_dir: Path) -> dict[str, Any] | None:
    state = _read_json(run_dir / SUPERVISOR_STATE)
    terminal = state.get("terminal") if state else None
    return terminal if isinstance(terminal, dict) else None


def _terminal_expected(
    terminal: dict[str, Any] | None,
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
) -> bool:
    if terminal is None:
        return False
    result = terminal.get("result")
    decision_is_valid = (
        terminal.get("preliminary_decision")
        in programme.healthy_preliminary_decisions
        if result == "healthy_stop"
        else terminal.get("primary_decision") in programme.terminal_decisions
    )
    static_code = terminal.get("last_confirmed_code")
    static_code_is_valid = type(static_code) is int or (
        result == "aborted" and static_code is None
    )
    return bool(
        result in {"healthy_stop", "nonpass", "aborted"}
        and decision_is_valid
        and static_code_is_valid
    )


def _record_abort_delivery_failure(
    run_dir: Path,
    *,
    terminal: dict[str, Any] | None,
    error: Exception,
) -> Path:
    path = run_dir / ABORT_DELIVERY_FAILURE
    if path.exists():
        return path
    _atomic_new_json(
        path,
        {
            "schema_version": 1,
            "report_type": "cx320_active_hybrid_abort_delivery_failure_v1",
            "tool": TOOL_ID,
            "recorded_utc": _utc_now(),
            "bounded_delivery_wait_s": ABORT_DELIVERY_TIMEOUT_S,
            "terminal": terminal,
            "capture_state": _read_json(
                run_dir / "reports/capture_device_state.json"
            ),
            "error_type": type(error).__name__,
            "error": str(error),
            "delivery_status": "bounded_failure",
            "claims_boundary": (
                "Priority abort delivery plus a complete resulting firmware "
                "ABORTED/fail-static snapshot was not confirmed before the "
                "bounded deadline. This record does not claim that firmware "
                "consumed and applied the abort."
            ),
        },
    )
    return path


def _wait_for_terminal_abort_delivery(
    run_dir: Path, terminal: dict[str, Any]
) -> None:
    if terminal.get("result") != "aborted":
        return

    def delivered() -> bool:
        state = _read_json(run_dir / "reports/capture_device_state.json")
        if not (
            state
            and state.get("capture_active") is True
            and state.get("emergency_abort_latched") is True
            and int(state.get("emergency_aborts_sent", 0)) == 1
        ):
            return False
        live = read_live_health_state(run_dir / LIVE_STATE_PATH)
        if live.state != "complete":
            return False
        health = live.health
        if not (
            health.get(("cx317_active", "state")) == "ABORTED"
            and health.get(("cx317_active", "fail_static")) == "true"
            and health.get(("cx317_active", "evidence_pending")) == "false"
            and health.get(("cx317_active", "evidence_phase")) == "evidence_clear"
            and health.get(("cx317_active", "evidence_request_sequence")) == "0"
        ):
            return False
        static_code = terminal.get("last_confirmed_code")
        if type(static_code) is int:
            return bool(
                health.get(("cx317_active", "confirmed_applied_code_known"))
                == "true"
                and int(
                    health.get(("cx317_active", "confirmed_applied_code"), "-1")
                )
                == static_code
            )
        return static_code is None

    try:
        _wait_until(
            delivered,
            ABORT_DELIVERY_TIMEOUT_S,
            "priority abort delivery before sole-owner capture close",
        )
    except (OSError, TimeoutError, TypeError, ValueError) as exc:
        _record_abort_delivery_failure(
            run_dir,
            terminal=terminal,
            error=exc,
        )
        raise


def _graceful_capture_stop(capture: subprocess.Popen[str]) -> int:
    if capture.poll() is None:
        capture.send_signal(signal.SIGINT)
    try:
        return capture.wait(timeout=CAPTURE_STOP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        capture.send_signal(signal.SIGINT)
        try:
            return capture.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            capture.terminate()
            return capture.wait(timeout=5.0)


def _bounded_priority_abort(
    run_dir: Path,
    emergency_fifo: Path,
    capture: subprocess.Popen[str],
) -> None:
    if capture.poll() is not None:
        return
    try:
        state_path = run_dir / "reports/capture_device_state.json"
        state = _read_json(state_path) or {}
        if not emergency_fifo.exists():
            raise FileNotFoundError(f"priority abort FIFO unavailable: {emergency_fifo}")
        if not state.get("emergency_abort_latched"):
            send_timestamped_command_to_fifo(emergency_fifo, "ACTIVE ABORT")
        _wait_until(
            lambda: bool(
                (_read_json(state_path) or {}).get("emergency_abort_latched")
                and int(
                    (_read_json(state_path) or {}).get("emergency_aborts_sent", 0)
                )
                == 1
            ),
            ABORT_DELIVERY_TIMEOUT_S,
            "best-effort priority abort delivery",
        )
    except (OSError, SystemExit, TimeoutError, TypeError, ValueError) as exc:
        error = exc if isinstance(exc, Exception) else RuntimeError(str(exc))
        _record_abort_delivery_failure(
            run_dir,
            terminal=_terminal(run_dir),
            error=error,
        )


def _write_failure(
    *,
    run_dir: Path,
    activation: dict[str, Any],
    error: Exception,
    phase: str,
) -> Path:
    path = run_dir / ORCHESTRATION_FAILURE
    if path.exists():
        return path
    _atomic_new_json(
        path,
        {
            "schema_version": 1,
            "report_type": "cx320_active_hybrid_orchestration_failure_v1",
            "tool": TOOL_ID,
            "recorded_utc": _utc_now(),
            "phase": phase,
            "failure_class": "platform_or_live_stop_rule_failure",
            "error_type": type(error).__name__,
            "error": str(error),
            "terminal": _terminal(run_dir),
            "activation_sha256": activation["activation_sha256"],
            "bundle_sha256": activation["bundle"]["bundle_sha256"],
            "automatic_retry": False,
            "automatic_restore": False,
            "claims_boundary": (
                "Retained physical or prewrite terminal evidence only; this "
                "artifact grants no retry, tuning, extension, or restoration."
            ),
        },
    )
    return path


def _registration(
    *,
    activation: dict[str, Any],
    status: str,
    reason: str,
    analyzer_identity: str,
) -> dict[str, str]:
    classification = (
        COMPLETED_INDEX_CLASSIFICATION
        if status in {"passed", "bounded_nonpass"}
        else INTERRUPTED_INDEX_CLASSIFICATION
    )
    return {
        "source_revision": str(activation["firmware"]["source_revision"]),
        "build_identity": str(activation["firmware"]["build_identity"]),
        "profile_identity": str(activation["profile_identity"]),
        "attempt_classification": classification,
        "result_or_failure_reason": reason,
        "analyzer_identity": analyzer_identity,
    }


def _register_unfinalized(
    *,
    run_dir: Path,
    activation: dict[str, Any],
    evidence_index_path: Path,
    error: Exception,
) -> dict[str, Any]:
    return register_package(
        index_path=evidence_index_path,
        package_path=run_dir,
        **_registration(
            activation=activation,
            status="failed",
            reason=f"CX320 retained unfinalized terminal: {error}",
            analyzer_identity=_sha256_file(Path(__file__)),
        ),
    )


def _write_complete(
    run_dir: Path,
    *,
    terminal: dict[str, Any] | None,
    orchestration_error: Exception | None,
) -> Path:
    path = run_dir / COMPLETE
    if path.exists():
        return path
    _atomic_new_json(
        path,
        {
            "completed_utc": _utc_now(),
            "completion": "cx320_finite_physical_campaign",
            "terminal": terminal,
            "orchestration_error": (
                None if orchestration_error is None else str(orchestration_error)
            ),
        },
    )
    return path


def _create_partial_evidence_snapshot(run_dir: Path) -> Path:
    """Freeze every available declared artifact after a partial terminal.

    The generic snapshot creator correctly rejects missing required artifacts.
    A stopped physical attempt still needs an immutable, explicitly partial
    inventory so offline analysis can report those absences without losing the
    evidence that did arrive.
    """

    manifest = load_manifest(run_dir)
    sources: dict[str, dict[str, str]] = {
        manifest.path.relative_to(run_dir).as_posix(): {"role": "run_manifest"}
    }
    raw_dir = run_dir / "raw"
    if raw_dir.is_dir():
        for path in sorted(raw_dir.rglob("*")):
            if path.is_file():
                sources[path.relative_to(run_dir).as_posix()] = {
                    "role": "raw_evidence"
                }
    for entry in manifest.files:
        relative = entry.get("path")
        if not isinstance(relative, str):
            continue
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != relative:
            raise ValueError(f"unsafe partial evidence path: {relative!r}")
        metadata = {"role": "declared_artifact"}
        contract = entry.get("contract")
        if isinstance(contract, str) and contract:
            metadata["contract"] = contract
        if (run_dir / relative).is_file():
            sources[relative] = metadata
    evidence_artifacts = manifest.data.get("evidence_artifacts", [])
    if not isinstance(evidence_artifacts, list):
        raise ValueError("CX320 evidence_artifacts must be a list")
    for relative in evidence_artifacts:
        if not isinstance(relative, str):
            raise ValueError("CX320 evidence artifact path must be a string")
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != relative:
            raise ValueError(f"unsafe partial evidence path: {relative!r}")
        if (run_dir / relative).is_file():
            sources[relative] = {"role": "declared_artifact"}

    artifacts: list[dict[str, Any]] = []
    for relative, metadata in sorted(sources.items()):
        path = run_dir / relative
        try:
            path.resolve(strict=True).relative_to(run_dir)
        except ValueError as exc:
            raise ValueError(
                f"partial evidence artifact escapes through a symlink: {relative}"
            ) from exc
        current = run_dir
        if any(
            (current := current / part).is_symlink()
            for part in PurePosixPath(relative).parts
        ):
            raise ValueError(f"partial evidence artifact is a symlink: {relative}")
        artifacts.append(
            {
                "path": relative,
                **metadata,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    snapshot: dict[str, Any] = {
        "schema_version": 1,
        "run_id": manifest.run_id,
        "run_state": "partial",
        "digest_algorithm": "sha256",
        "artifacts": artifacts,
    }
    snapshot["snapshot_digest"] = sha256(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    destination = run_dir / EVIDENCE_MANIFEST
    _atomic_new_json(destination, snapshot)
    return destination


def _snapshotted_artifact_identities(
    run_dir: Path, snapshot_path: Path
) -> dict[str, str | None]:
    snapshot = _read_json(snapshot_path)
    if snapshot is None or not isinstance(snapshot.get("artifacts"), list):
        raise ValueError("CX320 evidence snapshot is malformed")
    identities: dict[str, str | None] = {}
    for entry in snapshot["artifacts"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("CX320 evidence snapshot artifact is malformed")
        relative = str(entry["path"])
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != relative:
            raise ValueError(f"unsafe snapshotted artifact path: {relative!r}")
        path = run_dir / relative
        identities[relative] = _sha256_file(path) if path.is_file() else None
    return identities


def _analyze(run_dir: Path) -> tuple[Path, dict[str, Any]]:
    from .active_hybrid_live_analyze import analyze

    return analyze(run_dir)


def _finalize_and_register(
    *,
    run_dir: Path,
    activation: dict[str, Any],
    evidence_index_path: Path,
    finalization_journal: Path,
    orchestration_error: Exception | None,
) -> dict[str, Any]:
    terminal = _terminal(run_dir)
    _write_complete(
        run_dir,
        terminal=terminal,
        orchestration_error=orchestration_error,
    )
    advance_phase(
        finalization_journal,
        "completion",
        {"terminal": terminal, "orchestration_error": str(orchestration_error or "")},
    )
    snapshot_creation_error: str | None = None
    try:
        snapshot = create_evidence_snapshot(
            run_dir, allow_incomplete=orchestration_error is not None
        )
    except Exception as exc:
        if orchestration_error is None:
            raise
        snapshot_creation_error = str(exc)
        snapshot = _create_partial_evidence_snapshot(run_dir)
    loaded = load_manifest(run_dir)
    failures, warnings = validate_evidence_snapshot(run_dir, loaded)
    if orchestration_error is None and (failures or warnings):
        raise RuntimeError(
            "CX320 evidence snapshot validation failed: "
            + json.dumps({"failures": failures, "warnings": warnings})
        )
    advance_phase(
        finalization_journal,
        "snapshot",
        {
            "path": str(snapshot),
            "failures": failures,
            "warnings": warnings,
            "generic_snapshot_error": snapshot_creation_error,
        },
    )
    frozen_acquisition_identities = _snapshotted_artifact_identities(
        run_dir, snapshot
    )
    seal_path, seal = _analyze(run_dir)
    if frozen_acquisition_identities != _snapshotted_artifact_identities(
        run_dir, snapshot
    ):
        raise RuntimeError("CX320 analyzer changed snapshotted acquisition evidence")
    advance_phase(
        finalization_journal,
        "analysis",
        {
            "status": seal["status"],
            "primary_decision": seal["primary_decision"],
            "tool_sha256": seal["tool_sha256"],
        },
    )
    advance_phase(
        finalization_journal,
        "seal",
        {"path": str(seal_path), "seal_sha256": seal["seal_sha256"]},
    )
    registration = _registration(
        activation=activation,
        status=str(seal["status"]),
        reason=(
            f"CX320 {seal['status']}: {seal['primary_decision']}"
            + (
                f"; orchestration={orchestration_error}"
                if orchestration_error is not None
                else ""
            )
        ),
        analyzer_identity=str(seal["tool_sha256"]),
    )
    set_registration_intent(
        finalization_journal,
        registration=registration,
        expected_content_sha256=package_identity(run_dir)["content_sha256"],
    )
    indexed = recover_registration(finalization_journal)
    return {
        "status": seal["status"],
        "primary_decision": seal["primary_decision"],
        "run_dir": str(run_dir),
        "seal": str(seal_path),
        "seal_sha256": seal["seal_sha256"],
        "evidence_snapshot": str(snapshot),
        "evidence_content_sha256": indexed["content_sha256"],
        "evidence_index": str(evidence_index_path.expanduser().resolve()),
        "orchestration_error": (
            None if orchestration_error is None else str(orchestration_error)
        ),
    }


def run_active_hybrid_qualification(
    *,
    activation_path: Path,
    run_dir: Path,
    evidence_index_path: Path = DEFAULT_INDEX,
    arduino_cli: str = "arduino-cli",
) -> dict[str, Any]:
    activation_path = activation_path.resolve()
    activation_value = _read_json(activation_path)
    if activation_value is None:
        raise ValueError("active-hybrid activation is unreadable")
    programme = programme_from_mapping(activation_value)
    activation, bundle, _proposal = (
        validate_activation(activation_path)
        if programme is CX320_PROGRAMME
        else validate_activation(activation_path, programme=programme)
    )
    require_programme_operation_allowed(
        programme.status_programme_id, programme.operation
    )
    run_dir = run_dir.resolve()
    if run_dir.exists():
        raise FileExistsError(f"CX320 live run already exists: {run_dir}")
    device = (
        _fresh_auto_detect_device()
        if programme.fresh_serial_auto_detect
        else str(activation["device"]["path"])
    )
    owners = _serial_owner_pids(device)
    if owners:
        raise ValueError(f"serial device already has owners: {sorted(owners)}")
    board = read_board_identity(device, arduino_cli=arduino_cli)
    if (
        not programme.fresh_serial_auto_detect
        and board.get("serial_number") != EXPECTED_BOARD_SERIAL
    ):
        raise ValueError("connected board serial differs from CX320 activation")

    run_dir.mkdir(parents=True)
    (run_dir / "reports").mkdir()
    (run_dir / "control").mkdir()
    run_activation = run_dir / programme.run_activation_path
    run_bundle = run_dir / programme.run_bundle_path
    run_proposal = run_dir / programme.run_proposal_path
    _copy_immutable(activation_path, run_activation)
    _copy_immutable(Path(activation["bundle"]["path"]), run_bundle)
    _copy_immutable(Path(activation["proposal"]["path"]), run_proposal)
    try:
        upload_args = {
            "run_dir": run_dir,
            "activation": activation,
            "device": device,
            "board_before": board,
            "arduino_cli": arduino_cli,
        }
        if programme is CX320_PROGRAMME:
            device, board, _flash = _upload_exact_firmware(**upload_args)
        else:
            device, board, _flash = _upload_exact_firmware(
                **upload_args, programme=programme
            )
    except (Exception, KeyboardInterrupt) as caught:
        exc = (
            caught
            if isinstance(caught, Exception)
            else RuntimeError("operator interrupted CX320 firmware entry")
        )
        _write_failure(
            run_dir=run_dir,
            activation=activation,
            error=exc,
            phase="firmware_entry",
        )
        indexed = _register_unfinalized(
            run_dir=run_dir,
            activation=activation,
            evidence_index_path=evidence_index_path,
            error=exc,
        )
        raise RuntimeError(
            "CX320 firmware entry failed; retained evidence "
            f"{indexed['content_sha256']}: {exc}"
        ) from exc

    manifest_path = run_dir / RUN_MANIFEST_PATH
    try:
        if programme.fresh_serial_auto_detect:
            freshly_detected = _fresh_auto_detect_device()
            if freshly_detected != device:
                raise RuntimeError(
                    "fresh serial path changed before capture ownership"
                )
        create_run_manifest(
            activation_path=run_activation,
            bundle_path=run_bundle,
            proposal_path=run_proposal,
            run_dir=run_dir,
            output_path=manifest_path,
            serial_device=device,
        )
        finalization_journal = begin_finalization(
            run_dir=run_dir,
            index_path=evidence_index_path,
            required_seal=programme.physical_seal_path,
            registration=_registration(
                activation=activation,
                status="failed",
                reason="pending CX320 physical finalization",
                analyzer_identity=_sha256_file(Path(__file__)),
            ),
        )
    except (Exception, KeyboardInterrupt) as caught:
        exc = (
            caught
            if isinstance(caught, Exception)
            else RuntimeError("operator interrupted CX320 post-flash preparation")
        )
        _write_failure(
            run_dir=run_dir,
            activation=activation,
            error=exc,
            phase="post_flash_prewrite",
        )
        indexed = _register_unfinalized(
            run_dir=run_dir,
            activation=activation,
            evidence_index_path=evidence_index_path,
            error=exc,
        )
        raise RuntimeError(
            "CX320 post-flash preparation failed; retained evidence "
            f"{indexed['content_sha256']}: {exc}"
        ) from exc

    capture_log: IO[str] | None = None
    supervisor_log: IO[str] | None = None
    capture: subprocess.Popen[str] | None = None
    supervisor: subprocess.Popen[str] | None = None
    orchestration_error: Exception | None = None
    capture_closed = False
    try:
        capture_log = (
            run_dir / _programme_path(CAPTURE_LOG, programme)
        ).open("x", encoding="utf-8")
        supervisor_log = (
            run_dir / _programme_path(SUPERVISOR_LOG, programme)
        ).open("x", encoding="utf-8")
        capture = _launch_process(
            _capture_command(
                device=device, run_dir=run_dir, programme=programme
            ),
            capture_log,
        )
        normal_fifo = run_dir / NORMAL_FIFO
        emergency_fifo = run_dir / EMERGENCY_FIFO
        host_abort_fifo = run_dir / HOST_ABORT_FIFO
        _wait_until(
            lambda: (
                capture.poll() is None
                and normal_fifo.exists()
                and emergency_fifo.exists()
                and stat.S_ISFIFO(normal_fifo.stat().st_mode)
                and stat.S_ISFIFO(emergency_fifo.stat().st_mode)
                and _capture_state_ready(run_dir, capture.pid)
            ),
            PROCESS_START_TIMEOUT_S,
            "sole-owner capture and bounded command paths",
        )
        if _serial_owner_pids(device) != {capture.pid}:
            raise RuntimeError("capture_device is not the sole serial owner")
        supervisor = _launch_process(
            _supervisor_command(
                run_dir=run_dir,
                build_identity=str(bundle["firmware"]["build_identity"]),
                programme=programme,
            ),
            supervisor_log,
        )
        _wait_until(
            lambda: (
                supervisor is not None
                and supervisor.poll() is None
                and host_abort_fifo.exists()
                and stat.S_ISFIFO(host_abort_fifo.stat().st_mode)
            ),
            PROCESS_START_TIMEOUT_S,
            "live supervisor and independent host abort path",
        )
        _wait_until(
            lambda: _terminal(run_dir) is not None
            or (supervisor is not None and supervisor.poll() is not None),
            programme.supervisor_duration_s,
            "finite CX320 supervisor terminal",
        )
        terminal = _terminal(run_dir)
        if not _terminal_expected(terminal, programme):
            raise RuntimeError(
                "CX320 supervisor reached a non-canonical terminal: "
                + json.dumps(terminal, sort_keys=True)
            )
        assert supervisor is not None and terminal is not None
        supervisor_exit = supervisor.wait(timeout=15.0)
        valid_exits = {0} if terminal["result"] == "healthy_stop" else {2, 3, 4, 5}
        if supervisor_exit not in valid_exits:
            raise RuntimeError(
                f"CX320 supervisor exited {supervisor_exit}, expected {sorted(valid_exits)}"
            )
        _wait_for_terminal_abort_delivery(run_dir, terminal)
        capture_exit = _graceful_capture_stop(capture)
        capture_closed = True
        advance_phase(
            finalization_journal, "capture_closed", {"capture_exit": capture_exit}
        )
        if capture_exit != 0:
            raise RuntimeError(f"CX320 capture exited with status {capture_exit}")
    except (Exception, KeyboardInterrupt) as caught:
        exc = (
            caught
            if isinstance(caught, Exception)
            else RuntimeError("operator interrupted CX320 live orchestration")
        )
        orchestration_error = exc
        _write_failure(
            run_dir=run_dir,
            activation=activation,
            error=exc,
            phase="live_orchestration",
        )
        if (
            capture is not None
            and (_terminal(run_dir) or {}).get("result") != "aborted"
        ):
            _bounded_priority_abort(
                run_dir,
                run_dir / EMERGENCY_FIFO,
                capture,
            )
        if capture is None:
            capture_closed = True
            advance_phase(
                finalization_journal,
                "capture_closed",
                {"capture_not_started": True, "after_error": str(exc)},
            )
        elif not capture_closed:
            try:
                capture_exit = _graceful_capture_stop(capture)
                capture_closed = True
                advance_phase(
                    finalization_journal,
                    "capture_closed",
                    {"capture_exit": capture_exit, "after_error": str(exc)},
                )
            except Exception as close_error:
                record_failure(
                    finalization_journal,
                    phase="capture_closed",
                    error=close_error,
                )
    finally:
        if capture_log is not None:
            capture_log.close()
        if supervisor_log is not None:
            supervisor_log.close()
        if supervisor is not None and supervisor.poll() is None:
            supervisor.terminate()
            try:
                supervisor.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                supervisor.kill()
                supervisor.wait(timeout=5.0)
        if capture is not None and capture.poll() is None:
            capture.terminate()
            try:
                capture.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                capture.kill()
                capture.wait(timeout=5.0)

    # The finally block is the last bounded process-reaping path.  If it had to
    # reap capture after an earlier close failure, retain and finalize that
    # partial terminal instead of stranding it as an unfinalized package.
    if capture is not None and not capture_closed and capture.poll() is not None:
        capture_closed = True
        advance_phase(
            finalization_journal,
            "capture_closed",
            {
                "capture_exit": capture.poll(),
                "forced_after_error": str(orchestration_error or ""),
            },
        )

    if not capture_closed:
        indexed = _register_unfinalized(
            run_dir=run_dir,
            activation=activation,
            evidence_index_path=evidence_index_path,
            error=orchestration_error or RuntimeError("capture closure failed"),
        )
        raise RuntimeError(
            "CX320 capture closure failed; retained evidence "
            f"{indexed['content_sha256']}"
        )
    try:
        result = _finalize_and_register(
            run_dir=run_dir,
            activation=activation,
            evidence_index_path=evidence_index_path,
            finalization_journal=finalization_journal,
            orchestration_error=orchestration_error,
        )
    except Exception as exc:
        record_failure(finalization_journal, phase="seal", error=exc)
        if not (run_dir / EVIDENCE_MANIFEST).is_file():
            _atomic_new_json(
                run_dir / _programme_path(FINALIZATION_FAILURE, programme),
                {
                    "schema_version": 1,
                    "report_type": "cx320_active_hybrid_finalization_failure_v1",
                    "recorded_utc": _utc_now(),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "physical_rerun_required": False,
                },
            )
        indexed = _register_unfinalized(
            run_dir=run_dir,
            activation=activation,
            evidence_index_path=evidence_index_path,
            error=exc,
        )
        raise RuntimeError(
            "CX320 finalization failed over retained evidence "
            f"{indexed['content_sha256']}: {exc}"
        ) from exc
    result.update(
        {
            "activation_sha256": activation["activation_sha256"],
            "bundle_sha256": activation["bundle"]["bundle_sha256"],
            "build_identity": activation["firmware"]["build_identity"],
            "firmware_flashes": 1,
            "flash_record": str(
                run_dir / _programme_path(FLASH_RECORD, programme)
            ),
            "board": board,
        }
    )
    if orchestration_error is not None:
        raise RuntimeError(
            "CX320 physical orchestration reached a retained terminal: "
            f"{orchestration_error}; evidence {result['evidence_content_sha256']}"
        ) from orchestration_error
    if result["status"] == "failed":
        raise RuntimeError(
            "CX320 integrity analysis failed; retained evidence "
            f"{result['evidence_content_sha256']}"
        )
    return result


def _journal_phase_complete(journal: dict[str, Any], phase: str) -> bool:
    return journal.get("phases", {}).get(phase) is not None


def recover_active_hybrid_finalization(
    *, run_dir: Path, evidence_index_path: Path | None = None
) -> dict[str, Any]:
    """Resume deterministic finalization without board, serial, or actuator I/O."""

    run_dir = run_dir.resolve()
    if (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise ValueError("cannot recover finalization while capture is active")
    if not (run_dir / COMPLETE).is_file():
        raise ValueError("CX320 retained run is not marked complete")
    manifest_path = run_dir / RUN_MANIFEST_PATH
    manifest = validate_frozen_run_manifest(manifest_path)
    activation_path = Path(manifest["activation"]["path"])
    activation = _read_json(activation_path)
    if activation is None:
        raise ValueError("CX320 retained activation is unavailable")
    try:
        programme = programme_from_mapping(manifest)
    except ValueError:
        programme = programme_from_mapping(activation)
    raw_path = run_dir / "raw/serial.log"

    def retained_identity(path: Path) -> str | None:
        return _sha256_file(path) if path.is_file() else None

    identities = {
        "manifest": retained_identity(manifest_path),
        "raw": retained_identity(raw_path),
    }
    journal_path = journal_path_for(run_dir)
    journal = _read_json(journal_path)
    if journal is None:
        raise ValueError("CX320 finalization journal is unavailable")
    index_path = (
        evidence_index_path.expanduser().resolve()
        if evidence_index_path is not None
        else Path(journal["index_path"])
    )
    snapshot = run_dir / EVIDENCE_MANIFEST
    if not snapshot.is_file():
        try:
            snapshot = create_evidence_snapshot(run_dir, allow_incomplete=True)
        except Exception:
            snapshot = _create_partial_evidence_snapshot(run_dir)
    if not _journal_phase_complete(journal, "snapshot"):
        advance_phase(journal_path, "snapshot", {"path": str(snapshot)})
    frozen_acquisition_identities = _snapshotted_artifact_identities(
        run_dir, snapshot
    )
    seal_path = run_dir / programme.physical_seal_path
    if seal_path.is_file():
        seal = _read_json(seal_path)
        if seal is None:
            raise ValueError("CX320 retained physical seal is malformed")
    else:
        seal_path, seal = _analyze(run_dir)
    journal = _read_json(journal_path) or journal
    if not _journal_phase_complete(journal, "analysis"):
        advance_phase(
            journal_path,
            "analysis",
            {
                "status": seal["status"],
                "primary_decision": seal["primary_decision"],
                "tool_sha256": seal["tool_sha256"],
            },
        )
    journal = _read_json(journal_path) or journal
    if not _journal_phase_complete(journal, "seal"):
        advance_phase(
            journal_path,
            "seal",
            {"path": str(seal_path), "seal_sha256": seal["seal_sha256"]},
        )
    if identities != {
        "manifest": retained_identity(manifest_path),
        "raw": retained_identity(raw_path),
    } or frozen_acquisition_identities != _snapshotted_artifact_identities(
        run_dir, snapshot
    ):
        raise RuntimeError("offline recovery changed frozen acquisition evidence")
    registration = _registration(
        activation=activation,
        status=str(seal["status"]),
        reason=f"CX320 offline finalization recovery: {seal['primary_decision']}",
        analyzer_identity=str(seal["tool_sha256"]),
    )
    set_registration_intent(
        journal_path,
        registration=registration,
        expected_content_sha256=package_identity(run_dir)["content_sha256"],
    )
    indexed = recover_registration(journal_path)
    return {
        "status": seal["status"],
        "primary_decision": seal["primary_decision"],
        "run_dir": str(run_dir),
        "seal": str(seal_path),
        "seal_sha256": seal["seal_sha256"],
        "evidence_snapshot": str(snapshot),
        "evidence_content_sha256": indexed["content_sha256"],
        "evidence_index": str(index_path),
        "physical_rerun": False,
        "device_or_actuator_io": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    execute = commands.add_parser("run")
    execute.add_argument("--activation", type=Path, required=True)
    execute.add_argument("--run-dir", type=Path, required=True)
    execute.add_argument("--evidence-index", type=Path, default=DEFAULT_INDEX)
    execute.add_argument("--arduino-cli", default="arduino-cli")
    recover = commands.add_parser("recover-finalization")
    recover.add_argument("--run-dir", type=Path, required=True)
    recover.add_argument("--evidence-index", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            result = run_active_hybrid_qualification(
                activation_path=args.activation,
                run_dir=args.run_dir,
                evidence_index_path=args.evidence_index,
                arduino_cli=args.arduino_cli,
            )
        else:
            result = recover_active_hybrid_finalization(
                run_dir=args.run_dir,
                evidence_index_path=args.evidence_index,
            )
    except (
        FileExistsError,
        FileNotFoundError,
        KeyError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        TimeoutError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
