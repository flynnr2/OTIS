"""Execute the exact physical no-write qualification rehearsal.

This is the only CX319 G1 hardware entry point. It requires the narrow
machine-readable operator authority, validates the frozen bundle, either
performs one exact flash or verifies a bundle-bound prior exact installation,
maintains one serial owner, runs the no-write supervisor, injects
bounded normal-path obstruction, proves priority abort, rotates evidence with
the same owner, analyzes, seals and registers the retained package.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
from typing import Any, Callable

from .board_identity import read_board_identity
from .capture_segment_rotation import prepare_transition, request_rotation
from .no_write_qualification_analyze import (
    ANALYSIS_PATH,
    FLASH_RECORD_PATH,
    REPORT_PATH,
    SEAL_PATH,
    TRANSPORT_REPORT_PATH,
    _atomic_new_json,
    analyze,
    report_markdown,
    seal,
)
from .no_write_qualification_bundle import (
    NO_WRITE_BENCH_OPERATION,
    PROGRAMME_ID,
    Q1_INTENTIONAL_DETACH_SCHEDULE,
    REHEARSAL_DURATION_S,
    RUN_BUNDLE_PATH,
    TRANSITION_RUN_DIR,
    create_run_manifest,
    validate_bundle,
    validate_confirmed_installed_firmware,
)
from .active_status_contract import latest_complete_health
from .evidence import create_evidence_snapshot, validate_evidence_snapshot
from .evidence_index import (
    DEFAULT_INDEX,
    package_identity,
    register_package,
    validate_index_location,
)
from .evidence_finalization import (
    advance_phase,
    begin_finalization,
    record_failure,
    recover_registration,
    set_registration_intent,
)
from .platform_rehearsal import (
    _capture_state_ready,
    _health_has,
    _inject_transport_fault,
    _serial_owner_pids,
)
from .programme_status import require_programme_operation_allowed
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, load_manifest
from .serial_commands import send_timestamped_command_to_fifo
from .validate_run import validate_run


TOOL_ID = "cx319_g1_rehearsal_v1"
TRANSITION_DIR = TRANSITION_RUN_DIR
SEGMENT_CONTROL_DIR = Path("control/segment_carrier")
ROTATION_OPERATION_ID = "cx319-g1-no-write-owner-handoff"
CAPTURE_LAUNCHER_LOG = Path("reports/cx319_g1_capture_launcher.log")
SUPERVISOR_LOG = Path("reports/cx319_g1_supervisor.log")
ORCHESTRATION_FAILURE_PATH = Path(
    "reports/cx319_g1_orchestration_failure_v1.json"
)
Q1_PRELUDE_PATH = Path("reports/cx319_q1_real_io_prelude_v1.json")
Q1_LEASE_SEQUENCE = 1
Q1_LEASE_LIVE_NONCE = 1362165761
Q1_LEASE_EXPIRED_NONCE = 1362165762
Q1_PHYSICAL_RESTART_TIMEOUT_S = 180.0


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _wait_until(
    predicate: Callable[[], bool], timeout_s: float, description: str
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise RuntimeError(f"timed out waiting for {description}")


def _supervisor_terminal(run_dir: Path) -> bool:
    path = run_dir / "reports/cx317_active_supervisor_state.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    terminal = state.get("terminal")
    return (
        isinstance(terminal, dict)
        and terminal.get("result") == "healthy_stop"
        and state.get("cx319_gate") == "G1"
        and state.get("manual_start_sent") is False
        and state.get("authorization_sequence") == 0
    )


def flash_exact_bundle(
    *, bundle: dict[str, Any], output_path: Path, arduino_cli: str
) -> dict[str, Any]:
    device = str(bundle["device"]["path"])
    owners = _serial_owner_pids(device)
    if owners:
        raise ValueError(f"serial device already has owners: {sorted(owners)}")
    before = read_board_identity(device, arduino_cli=arduino_cli)
    firmware = bundle["firmware"]
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
    started = _utc_now()
    completed = subprocess.run(
        command, text=True, capture_output=True, check=False
    )
    upload_completed_monotonic_ns = time.monotonic_ns()
    after: dict[str, str] | None = None
    reappearance_error: str | None = None
    if completed.returncode == 0:
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            try:
                after = read_board_identity(device, arduino_cli=arduino_cli)
                break
            except (ValueError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
                reappearance_error = str(exc)
                time.sleep(0.5)
    passed = completed.returncode == 0 and before == after
    completed_monotonic_ns = time.monotonic_ns()
    record = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "operation": "exact_cx319_g1_firmware_flash",
        "status": "pass" if passed else "fail",
        "started_utc": started,
        "completed_utc": _utc_now(),
        "completed_monotonic_ns": completed_monotonic_ns,
        "upload_completed_monotonic_ns": upload_completed_monotonic_ns,
        "attempt_count": 1,
        "device": device,
        "command": command,
        "exit_code": completed.returncode,
        "stdout_sha256": sha256(completed.stdout.encode()).hexdigest(),
        "stderr_sha256": sha256(completed.stderr.encode()).hexdigest(),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
        "board_before": before,
        "board_after": after,
        "board_reappearance_error": reappearance_error,
        "bundle_sha256": bundle["bundle_sha256"],
        "profile_id": firmware["profile_id"],
        "build_manifest_sha256": firmware["build_manifest"]["sha256"],
        "uf2_sha256": firmware["uf2"]["sha256"],
        "dac_boot_operation": "i2c_address_probe_only",
        "dac_value_write_attempts": 0,
        "setup_stimulus_attempts": 0,
        "control_arm_attempts": 0,
    }
    _atomic_new_json(output_path, record)
    if not passed:
        raise RuntimeError(f"exact CX319 G1 flash failed: {output_path}")
    return record


def _capture_state(run_dir: Path) -> dict[str, Any]:
    value = _read_json_if_present(run_dir / "reports/capture_device_state.json")
    return value or {}


def _active_snapshot(
    run_dir: Path, *, required_query_nonce: int
) -> dict[tuple[str, str], str]:
    return latest_complete_health(
        run_dir / "csv/health.csv",
        required_query_nonce=required_query_nonce,
    )


def _exercise_q1_real_io_prelude(
    *,
    run_dir: Path,
    device: str,
    capture_pid: int,
    normal_fifo: Path,
    flash: dict[str, Any],
    carrier_initial_ready_monotonic_ns: int,
) -> dict[str, Any]:
    expected_detaches = len(Q1_INTENTIONAL_DETACH_SCHEDULE)
    _wait_until(
        lambda: (
            _capture_state(run_dir).get("serial_open") is True
            and _capture_state(run_dir).get("intentional_detach_count")
            == expected_detaches
            and len(
                _capture_state(run_dir).get("intentional_detach_gaps_ms", [])
            )
            == expected_detaches
        ),
        20.0,
        "Q1 bounded detach and reattach schedule",
    )
    entry_ready_monotonic_ns = flash.get("upload_completed_monotonic_ns")
    if entry_ready_monotonic_ns is None:
        entry_ready_monotonic_ns = flash.get("restart_reappeared_monotonic_ns")
    if not isinstance(entry_ready_monotonic_ns, int):
        raise RuntimeError("Q1 firmware entry lacks a monotonic ready anchor")
    hostless_ms = (
        carrier_initial_ready_monotonic_ns - entry_ready_monotonic_ns
    ) / 1_000_000.0
    if not 0.0 < hostless_ms < 2000.0:
        raise RuntimeError(
            "Q1 firmware-entry-to-carrier interval is outside the declared "
            "<2000 ms "
            f"boot/transport window: {hostless_ms:.3f} ms"
        )
    _wait_until(
        lambda: b"BOOT_WARN,v=1,key=serial_absent,wait_ms=250" in (
            run_dir / "raw/serial.log"
        ).read_bytes(),
        10.0,
        "Q1 host-absent 250 ms boot record",
    )

    serial_module = __import__("serial")
    competing_open_rejected = False
    competing_error = ""
    competing = None
    try:
        competing = serial_module.Serial(
            device,
            baudrate=115200,
            timeout=0.1,
            write_timeout=0.1,
            exclusive=True,
        )
    except (OSError, serial_module.SerialException) as exc:
        competing_open_rejected = True
        competing_error = str(exc)
    finally:
        if competing is not None:
            competing.close()
    if not competing_open_rejected:
        raise RuntimeError("Q1 competing serial open was not rejected by the OS")
    if _serial_owner_pids(device) != {capture_pid}:
        raise RuntimeError("Q1 carrier lost sole serial ownership after open probe")

    send_timestamped_command_to_fifo(
        normal_fifo, f"ACTIVE LEASE {Q1_LEASE_SEQUENCE}"
    )
    send_timestamped_command_to_fifo(
        normal_fifo, f"ACTIVE SNAPSHOT {Q1_LEASE_LIVE_NONCE}"
    )
    _wait_until(
        lambda: _active_snapshot(
            run_dir, required_query_nonce=Q1_LEASE_LIVE_NONCE
        ).get(("cx317_active", "capture_lease_live"))
        == "true",
        15.0,
        "Q1 live lease snapshot",
    )
    lease_live = _active_snapshot(
        run_dir, required_query_nonce=Q1_LEASE_LIVE_NONCE
    )
    time.sleep(31.0)
    send_timestamped_command_to_fifo(
        normal_fifo, f"ACTIVE SNAPSHOT {Q1_LEASE_EXPIRED_NONCE}"
    )
    _wait_until(
        lambda: _active_snapshot(
            run_dir, required_query_nonce=Q1_LEASE_EXPIRED_NONCE
        ).get(("cx317_active", "capture_lease_live"))
        == "false",
        15.0,
        "Q1 expired lease snapshot",
    )
    lease_expired = _active_snapshot(
        run_dir, required_query_nonce=Q1_LEASE_EXPIRED_NONCE
    )
    state = _capture_state(run_dir)
    gaps = state.get("intentional_detach_gaps_ms", [])
    result = {
        "schema_version": 1,
        "report_type": "cx319_q1_real_io_prelude_v1",
        "status": "pass",
        "recorded_utc": _utc_now(),
        "device": device,
        "capture_pid": capture_pid,
        "firmware_entry_operation": flash.get("operation"),
        "firmware_entry_to_carrier_ready_ms": round(hostless_ms, 3),
        "declared_boot_wait_ms": 250,
        "transport_horizon_ms": 2000,
        "intentional_detach_count": state.get("intentional_detach_count"),
        "intentional_detach_gaps_ms": gaps,
        "all_detach_gaps_below_transport_horizon": all(
            isinstance(value, (int, float)) and value < 2000 for value in gaps
        ),
        "serial_exclusive_requested": state.get("serial_exclusive_requested"),
        "competing_open_rejected": competing_open_rejected,
        "competing_open_error": competing_error,
        "sole_owner_after_probe": _serial_owner_pids(device) == {capture_pid},
        "lease_live_snapshot": {
            "query_nonce": lease_live.get(("cx317_active", "query_nonce")),
            "capture_lease_live": lease_live.get(
                ("cx317_active", "capture_lease_live")
            ),
            "generation": lease_live.get(
                ("cx317_active", "snapshot_generation_complete")
            ),
        },
        "lease_expired_snapshot": {
            "query_nonce": lease_expired.get(("cx317_active", "query_nonce")),
            "capture_lease_live": lease_expired.get(
                ("cx317_active", "capture_lease_live")
            ),
            "generation": lease_expired.get(
                ("cx317_active", "snapshot_generation_complete")
            ),
            "setup_partition_healthy": lease_expired.get(
                ("cx317_active", "setup_partition_healthy")
            ),
        },
        "dac_value_writes": 0,
        "setup_stimuli": 0,
        "control_arms": 0,
    }
    if flash.get("operation") == "exact_cx319_g1_firmware_flash":
        result["upload_to_carrier_ready_ms"] = round(hostless_ms, 3)
    else:
        result["restart_reappearance_to_carrier_ready_ms"] = round(
            hostless_ms, 3
        )
    _atomic_new_json(run_dir / Q1_PRELUDE_PATH, result)
    return result


def confirm_installed_bundle(
    *, bundle: dict[str, Any], output_path: Path, arduino_cli: str
) -> dict[str, Any]:
    """Verify the exact prior flash and current board without uploading."""

    entry = bundle.get("firmware_entry", {})
    source_binding = entry.get("source_flash_record", {})
    if entry.get("mode") != "reuse_confirmed_installed_firmware" or not isinstance(
        source_binding, dict
    ):
        raise ValueError("bundle does not bind confirmed installed firmware")
    expected_entry = validate_confirmed_installed_firmware(
        firmware=bundle["firmware"],
        flash_record_path=Path(str(source_binding.get("path", ""))),
    )
    if entry != expected_entry:
        raise ValueError("confirmed installed firmware binding differs")
    device = str(bundle["device"]["path"])
    owners = _serial_owner_pids(device)
    if owners:
        raise ValueError(f"serial device already has owners: {sorted(owners)}")
    current = read_board_identity(device, arduino_cli=arduino_cli)
    installed = entry["installed_board"]
    passed = current == installed
    record = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "operation": "confirmed_installed_cx319_g1_firmware_reuse",
        "status": "pass" if passed else "fail",
        "started_utc": _utc_now(),
        "completed_utc": _utc_now(),
        "attempt_count": 0,
        "firmware_flashes": 0,
        "device": device,
        "board_before": current,
        "board_after": current,
        "installed_board": installed,
        "bundle_sha256": bundle["bundle_sha256"],
        "profile_id": bundle["firmware"]["profile_id"],
        "build_manifest_sha256": bundle["firmware"]["build_manifest"][
            "sha256"
        ],
        "uf2_sha256": bundle["firmware"]["uf2"]["sha256"],
        "source_flash_record": entry["source_flash_record"],
        "source_bundle": entry["source_bundle"],
        "source_bundle_sha256": entry["source_bundle_sha256"],
        "source_build_manifest_sha256": entry[
            "source_build_manifest_sha256"
        ],
        "installed_uf2_sha256": entry["installed_uf2_sha256"],
        "dac_boot_operation": "none_no_reset_no_upload",
        "dac_value_write_attempts": 0,
        "setup_stimulus_attempts": 0,
        "control_arm_attempts": 0,
    }
    _atomic_new_json(output_path, record)
    if not passed:
        raise RuntimeError(
            "current board identity differs from confirmed installed firmware"
        )
    return record


def restart_confirmed_installed_bundle(
    *,
    bundle: dict[str, Any],
    output_path: Path,
    arduino_cli: str,
    timeout_s: float = Q1_PHYSICAL_RESTART_TIMEOUT_S,
    device_exists: Callable[[Path], bool] | None = None,
) -> dict[str, Any]:
    """Observe one physical restart of exact confirmed firmware, without upload."""

    entry = bundle.get("firmware_entry", {})
    source_binding = entry.get("source_flash_record", {})
    if entry.get("mode") != "reuse_confirmed_installed_firmware" or not isinstance(
        source_binding, dict
    ):
        raise ValueError("bundle does not bind confirmed installed firmware")
    expected_entry = validate_confirmed_installed_firmware(
        firmware=bundle["firmware"],
        flash_record_path=Path(str(source_binding.get("path", ""))),
    )
    if entry != expected_entry:
        raise ValueError("confirmed installed firmware binding differs")
    device = str(bundle["device"]["path"])
    owners = _serial_owner_pids(device)
    if owners:
        raise ValueError(f"serial device already has owners: {sorted(owners)}")
    before = read_board_identity(device, arduino_cli=arduino_cli)
    if before != entry["installed_board"]:
        raise RuntimeError(
            "current board identity differs from confirmed installed firmware"
        )

    started = _utc_now()
    print(
        "Q1_RESTART_REQUIRED: press the board reset button once; "
        "the runner is waiting for USB disappearance and reappearance",
        flush=True,
    )
    deadline = time.monotonic() + timeout_s
    device_path = Path(device)
    present = device_exists or (lambda path: path.exists())
    while present(device_path) and time.monotonic() < deadline:
        time.sleep(0.01)
    if present(device_path):
        raise RuntimeError(
            f"timed out after {timeout_s:.0f}s waiting for Q1 board restart"
        )
    restart_disappeared_monotonic_ns = time.monotonic_ns()
    while not present(device_path) and time.monotonic() < deadline:
        time.sleep(0.01)
    if not present(device_path):
        raise RuntimeError(
            f"Q1 board did not reappear within {timeout_s:.0f}s restart window"
        )
    restart_reappeared_monotonic_ns = time.monotonic_ns()

    after: dict[str, str] | None = None
    identity_error: str | None = None
    identity_deadline = time.monotonic() + 30.0
    while time.monotonic() < identity_deadline:
        try:
            after = read_board_identity(device, arduino_cli=arduino_cli)
            break
        except (ValueError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            identity_error = str(exc)
            time.sleep(0.1)
    passed = before == after == entry["installed_board"]
    record = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "operation": "confirmed_installed_cx319_g1_firmware_reuse",
        "status": "pass" if passed else "fail",
        "started_utc": started,
        "completed_utc": _utc_now(),
        "attempt_count": 0,
        "firmware_flashes": 0,
        "ordinary_restart_count": 1,
        "device": device,
        "board_before": before,
        "board_after": after,
        "installed_board": entry["installed_board"],
        "restart_disappeared_monotonic_ns": (
            restart_disappeared_monotonic_ns
        ),
        "restart_reappeared_monotonic_ns": restart_reappeared_monotonic_ns,
        "board_identity_error": identity_error,
        "bundle_sha256": bundle["bundle_sha256"],
        "profile_id": bundle["firmware"]["profile_id"],
        "build_manifest_sha256": bundle["firmware"]["build_manifest"][
            "sha256"
        ],
        "uf2_sha256": bundle["firmware"]["uf2"]["sha256"],
        "source_flash_record": entry["source_flash_record"],
        "source_bundle": entry["source_bundle"],
        "source_bundle_sha256": entry["source_bundle_sha256"],
        "source_build_manifest_sha256": entry[
            "source_build_manifest_sha256"
        ],
        "installed_uf2_sha256": entry["installed_uf2_sha256"],
        "dac_boot_operation": "none_no_upload_ordinary_board_restart",
        "dac_value_write_attempts": 0,
        "setup_stimulus_attempts": 0,
        "control_arm_attempts": 0,
    }
    _atomic_new_json(output_path, record)
    if not passed:
        raise RuntimeError(
            "board identity differed after the confirmed-firmware restart"
        )
    return record


def _write_complete(run_dir: Path) -> None:
    path = run_dir / "COMPLETE"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.write(
            descriptor,
            b"CX319 G1 exact no-write rehearsal completed and analyzed\n",
        )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _copy_exact_bundle(source: Path, destination: Path) -> None:
    payload = source.read_bytes()
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        written = os.write(descriptor, payload)
        if written != len(payload):
            raise OSError(
                f"short exact-bundle copy: expected {len(payload)}, wrote {written}"
            )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_json_if_present(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _retain_orchestration_failure(
    *,
    run_dir: Path,
    bundle: dict[str, Any],
    evidence_index_path: Path,
    error: Exception,
) -> dict[str, Any]:
    """Record and index any failure before the normal analyzer boundary."""

    supervisor_state = _read_json_if_present(
        run_dir / "reports/cx317_active_supervisor_state.json"
    )
    capture_state = _read_json_if_present(
        run_dir / "reports/capture_device_state.json"
    )
    failure = {
        "schema_version": 1,
        "report_type": "cx319_g1_orchestration_failure_v1",
        "tool": TOOL_ID,
        "programme_id": PROGRAMME_ID,
        "gate": "G1",
        "leg": bundle["leg"]["leg"],
        "attempt_classification": "failed_rehearsal",
        "failure_class": "platform_defect_caught_in_rehearsal",
        "recorded_utc": _utc_now(),
        "error_type": type(error).__name__,
        "error": str(error),
        "supervisor_terminal": (
            supervisor_state.get("terminal") if supervisor_state else None
        ),
        "capture_state": capture_state,
        "bundle_sha256": bundle["bundle_sha256"],
        "source_revision": bundle["firmware"]["git_commit"],
        "build_manifest_sha256": bundle["firmware"]["build_manifest"][
            "sha256"
        ],
        "profile_id": bundle["firmware"]["profile_id"],
        "claims_boundary": (
            "Retained failed-rehearsal evidence only; this record grants no "
            "G2, live-write, control-arm, or actuation authority."
        ),
    }
    _atomic_new_json(run_dir / ORCHESTRATION_FAILURE_PATH, failure)
    return register_package(
        index_path=evidence_index_path,
        package_path=run_dir,
        source_revision=bundle["firmware"]["git_commit"],
        build_identity=bundle["firmware"]["build_manifest"]["sha256"],
        profile_identity=bundle["firmware"]["profile_id"],
        attempt_classification="failed_rehearsal",
        result_or_failure_reason=f"CX319 G1 orchestration failed: {error}",
        analyzer_identity=_sha256_file(Path(__file__)),
    )


def run_no_write_qualification(
    *,
    bundle_path: Path,
    run_dir: Path,
    evidence_index_path: Path,
    arduino_cli: str,
    q1_real_io: bool = False,
) -> dict[str, Any]:
    require_programme_operation_allowed(PROGRAMME_ID, NO_WRITE_BENCH_OPERATION)
    bundle_path = bundle_path.resolve()
    bundle = validate_bundle(bundle_path)
    run_dir = run_dir.resolve()
    evidence_index_path = validate_index_location(evidence_index_path)
    if run_dir.exists():
        raise FileExistsError(f"CX319 G1 run already exists: {run_dir}")
    run_dir.mkdir(parents=True)
    (run_dir / "reports").mkdir()
    finalization_journal = begin_finalization(
        run_dir=run_dir,
        index_path=evidence_index_path,
        required_seal=SEAL_PATH,
        registration={
            "source_revision": bundle["firmware"]["git_commit"],
            "build_identity": bundle["firmware"]["build_manifest"]["sha256"],
            "profile_identity": bundle["firmware"]["profile_id"],
            "attempt_classification": "failed_rehearsal",
            "result_or_failure_reason": "pending CX319 G1 finalization",
            "analyzer_identity": _sha256_file(Path(__file__)),
        },
    )
    run_bundle_path = run_dir / RUN_BUNDLE_PATH
    _copy_exact_bundle(bundle_path, run_bundle_path)
    manifest_path = run_dir / "run_manifest.json"
    create_run_manifest(
        bundle_path=run_bundle_path,
        run_dir=run_dir,
        output_path=manifest_path,
        q1_real_io=q1_real_io,
    )
    entry_mode = bundle.get("firmware_entry", {}).get(
        "mode", "single_exact_flash"
    )
    try:
        if entry_mode == "single_exact_flash":
            flash = flash_exact_bundle(
                bundle=bundle,
                output_path=run_dir / FLASH_RECORD_PATH,
                arduino_cli=arduino_cli,
            )
        elif entry_mode == "reuse_confirmed_installed_firmware":
            entry = (
                restart_confirmed_installed_bundle
                if q1_real_io
                else confirm_installed_bundle
            )
            flash = entry(
                bundle=bundle,
                output_path=run_dir / FLASH_RECORD_PATH,
                arduino_cli=arduino_cli,
            )
        else:
            raise ValueError("unsupported G1 firmware entry mode")
    except Exception as exc:
        record_failure(
            finalization_journal,
            phase="capture_closed",
            error=exc,
        )
        indexed = _retain_orchestration_failure(
            run_dir=run_dir,
            bundle=bundle,
            evidence_index_path=evidence_index_path,
            error=exc,
        )
        raise RuntimeError(
            "CX319 G1 firmware entry failed; retained evidence "
            f"{indexed['content_sha256']}: {exc}"
        ) from exc
    transition_dir = run_dir / TRANSITION_DIR
    prepare_transition(manifest_path, transition_dir)

    device = str(bundle["device"]["path"])
    normal_fifo = run_dir / "control/normal_commands.fifo"
    emergency_fifo = run_dir / "control/emergency_abort.fifo"
    host_abort_fifo = run_dir / "control/host_abort.fifo"
    segment_control_dir = run_dir / SEGMENT_CONTROL_DIR
    segment_capability = f"cx319-g1-{bundle['bundle_sha256']}"
    capture_duration_s = REHEARSAL_DURATION_S + 180.0
    capture_log = (run_dir / CAPTURE_LAUNCHER_LOG).open("x", encoding="utf-8")
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
        str(capture_duration_s),
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
        "--segment-control-dir",
        str(segment_control_dir),
        "--segment-capability",
        segment_capability,
    ]
    if q1_real_io:
        for after_s, detached_s in Q1_INTENTIONAL_DETACH_SCHEDULE:
            capture_args.extend(
                [
                    "--intentional-detach",
                    f"{after_s}:{detached_s * 1000.0}",
                ]
            )
    capture = subprocess.Popen(
        capture_args,
        cwd=Path(__file__).resolve().parents[2],
        stdout=capture_log,
        stderr=capture_log,
        text=True,
    )
    supervisor: subprocess.Popen[str] | None = None
    transport: dict[str, Any] | None = None
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
            "capture ownership and bounded command paths",
        )
        carrier_initial_ready_monotonic_ns = time.monotonic_ns()
        if q1_real_io:
            _exercise_q1_real_io_prelude(
                run_dir=run_dir,
                device=device,
                capture_pid=capture.pid,
                normal_fifo=normal_fifo,
                flash=flash,
                carrier_initial_ready_monotonic_ns=(
                    carrier_initial_ready_monotonic_ns
                ),
            )
        expected_build = (
            bundle["firmware"]["source_sha256"]
            + ":"
            + bundle["firmware"]["configuration_sha256"]
        )
        supervisor_args = [
            sys.executable,
            "-m",
            "host.otis_tools.no_write_qualification_supervisor",
            "--leg",
            str(bundle["leg"]["leg"]),
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
            str(REHEARSAL_DURATION_S + 90.0),
        ]
        if q1_real_io:
            supervisor_args.extend(
                [
                    "--allowed-initial-reconnect-count",
                    str(len(Q1_INTENTIONAL_DETACH_SCHEDULE)),
                    "--initial-lease-sequence",
                    str(Q1_LEASE_SEQUENCE),
                    "--q1-real-io",
                ]
            )
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
            "CX319 G1 supervisor and independent host abort",
        )
        send_timestamped_command_to_fifo(normal_fifo, "FC0?")
        _wait_until(
            lambda: _health_has(
                run_dir / "csv/health.csv",
                "pps_gate",
                "snapshot_ring_capacity",
                "128",
            ),
            30.0,
            "explicit PPS queue capacity status",
        )
        _wait_until(
            lambda: (
                _supervisor_terminal(run_dir)
                or supervisor.poll() is not None
            ),
            REHEARSAL_DURATION_S + 90.0,
            "2700 second no-write supervisor terminal",
        )
        if not _supervisor_terminal(run_dir):
            state = _read_json_if_present(
                run_dir / "reports/cx317_active_supervisor_state.json"
            )
            raise RuntimeError(
                "G1 no-write supervisor reached a non-healthy terminal: "
                + json.dumps(
                    state.get("terminal") if state else None,
                    sort_keys=True,
                )
            )
        try:
            supervisor_exit = supervisor.wait(timeout=15.0)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "G1 no-write supervisor did not exit at its finite endpoint"
            ) from exc
        if supervisor_exit != 0:
            raise RuntimeError(
                f"G1 no-write supervisor exited with status {supervisor_exit}"
            )
        transport = _inject_transport_fault(
            capture_pid=capture.pid,
            device=device,
            run_dir=run_dir,
            normal_fifo=normal_fifo,
            emergency_fifo=emergency_fifo,
        )
        owner_handoff = request_rotation(
            control_dir=segment_control_dir,
            capability=segment_capability,
            to_run=transition_dir,
            mode="transition",
            wait_timeout_s=10.0,
            operation_id=ROTATION_OPERATION_ID,
        )
        if (
            owner_handoff.get("status") != "completed"
            or owner_handoff.get("pid") != capture.pid
            or owner_handoff.get("serial_reopened") is not False
            or owner_handoff.get("reconnect_count") != 0
        ):
            raise RuntimeError("G1 same-owner transition changed serial ownership")
        transport["owner_handoff"] = owner_handoff
        _atomic_new_json(run_dir / TRANSPORT_REPORT_PATH, transport)
        try:
            capture_exit = capture.wait(timeout=220.0)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("G1 capture did not close within bounded duration") from exc
        if capture_exit != 0:
            raise RuntimeError(f"G1 capture exited with status {capture_exit}")
        advance_phase(
            finalization_journal,
            "capture_closed",
            {"capture_exit": capture_exit},
        )
    except Exception as exc:
        orchestration_error = exc
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
            try:
                capture.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                capture.kill()
                capture.wait(timeout=5.0)

    if orchestration_error is not None:
        record_failure(
            finalization_journal,
            phase="capture_closed",
            error=orchestration_error,
        )
        indexed = _retain_orchestration_failure(
            run_dir=run_dir,
            bundle=bundle,
            evidence_index_path=evidence_index_path,
            error=orchestration_error,
        )
        raise RuntimeError(
            "CX319 G1 orchestration failed; retained evidence "
            f"{indexed['content_sha256']}: {orchestration_error}"
        ) from orchestration_error

    _write_complete(run_dir)
    advance_phase(finalization_journal, "completion", {})
    snapshot_path = create_evidence_snapshot(run_dir)
    advance_phase(
        finalization_journal, "snapshot", {"path": str(snapshot_path)}
    )
    try:
        analysis = analyze(run_dir)
        _atomic_new_json(run_dir / ANALYSIS_PATH, analysis)
        (run_dir / REPORT_PATH).write_text(
            report_markdown(analysis), encoding="utf-8"
        )
        advance_phase(
            finalization_journal,
            "analysis",
            {"path": str(run_dir / ANALYSIS_PATH), "status": analysis["status"]},
        )
    except Exception as exc:
        record_failure(finalization_journal, phase="analysis", error=exc)
        raise
    if analysis["status"] != "pass":
        failed = sorted(
            name for name, passed in analysis["checks"].items() if not passed
        )
        indexed = register_package(
            index_path=evidence_index_path,
            package_path=run_dir,
            source_revision=bundle["firmware"]["git_commit"],
            build_identity=bundle["firmware"]["build_manifest"]["sha256"],
            profile_identity=bundle["firmware"]["profile_id"],
            attempt_classification="failed_rehearsal",
            result_or_failure_reason="CX319 G1 failed: " + ", ".join(failed),
            analyzer_identity=analysis["bindings"]["analyzer_sha256"],
        )
        raise RuntimeError(
            "CX319 G1 analysis failed; retained evidence "
            f"{indexed['content_sha256']}: {', '.join(failed)}"
        )
    loaded = load_manifest(run_dir)
    failures, warnings = validate_evidence_snapshot(run_dir, loaded)
    if failures or warnings:
        raise RuntimeError(
            "CX319 G1 evidence snapshot validation failed: "
            + json.dumps({"failures": failures, "warnings": warnings})
        )
    if validate_run(run_dir) != 0:
        raise RuntimeError("CX319 G1 generic run validation failed")
    seal_value = seal(run_dir, analysis)
    advance_phase(
        finalization_journal,
        "seal",
        {"path": str(run_dir / SEAL_PATH), "seal_sha256": seal_value["seal_sha256"]},
    )
    registration = {
        "source_revision": bundle["firmware"]["git_commit"],
        "build_identity": bundle["firmware"]["build_manifest"]["sha256"],
        "profile_identity": bundle["firmware"]["profile_id"],
        "attempt_classification": "successful_rehearsal",
        "result_or_failure_reason": "all CX319 G1 exact no-write gates passed",
        "analyzer_identity": analysis["bindings"]["analyzer_sha256"],
    }
    set_registration_intent(
        finalization_journal,
        registration=registration,
        expected_content_sha256=package_identity(run_dir)["content_sha256"],
    )
    try:
        indexed = recover_registration(finalization_journal)
    except Exception as exc:
        record_failure(finalization_journal, phase="registration", error=exc)
        raise RuntimeError(
            "CX319 G1 sealed package is valid but registration failed; "
            f"recover with evidence_finalization {finalization_journal}: {exc}"
        ) from exc
    return {
        "status": "pass",
        "run_dir": str(run_dir),
        "bundle_sha256": bundle["bundle_sha256"],
        "flash_record": str(run_dir / FLASH_RECORD_PATH),
        "analysis": str(run_dir / ANALYSIS_PATH),
        "evidence_snapshot": str(snapshot_path),
        "seal": str(run_dir / SEAL_PATH),
        "seal_sha256": seal_value["seal_sha256"],
        "evidence_content_sha256": indexed["content_sha256"],
        "evidence_index": str(evidence_index_path.expanduser().resolve()),
        "board": flash["board_after"],
        "dac_value_writes": 0,
        "control_arms": 0,
        "q1_real_io": q1_real_io,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--evidence-index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--arduino-cli", default="arduino-cli")
    parser.add_argument("--q1-real-io", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_no_write_qualification(
            bundle_path=args.bundle,
            run_dir=args.run_dir,
            evidence_index_path=args.evidence_index,
            arduino_cli=args.arduino_cli,
            q1_real_io=args.q1_real_io,
        )
    except (
        FileExistsError,
        FileNotFoundError,
        KeyError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
