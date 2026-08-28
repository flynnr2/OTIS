"""Execute and finalize the activated physical GNSS baud-envelope campaign.

This is the only physical host entry point for the programme.  It validates
the immutable candidate/activation pair, starts the existing capture process
as sole serial owner at the frozen one-second status cadence, performs the
no-command attachment gate, then delegates all programme commands to the
capture FIFO adapter.  Every exceptional terminal uses the independent
priority-abort path before capture rotation and shutdown.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time
from typing import Any, Mapping

from .capture_runtime_checks import _capture_state_ready, _serial_owner_pids
from .board_identity import read_board_identity
from .capture_segment_rotation import prepare_transition, request_rotation
from .evidence import create_evidence_snapshot
from .evidence_index import (
    DEFAULT_INDEX,
    load_index,
    package_identity,
    register_package,
)
from .gnss_baud_envelope_analyze import analyze, create_seal
from .gnss_baud_envelope_capture_adapter import (
    CAPTURE_STATE,
    CHARACTERIZATION_COMPONENT,
    COMMAND_TABLE_ID,
    CaptureDeviceTransport,
    LIVE_CAPTURE_STATUS_INTERVAL_S,
    ProgrammeTerminalError,
)
from .gnss_baud_envelope_run import new_supervisor, run_programme
from .gnss_baud_envelope_monitor import snapshot as monitor_snapshot
from .gnss_baud_envelope_supervisor import PROGRAMME_ID
from .run_loader import GNSS_BAUD_ENVELOPE_PROFILE_ID
from .run_paths import ensure_run_layout
from .serial_commands import send_timestamped_command_to_fifo


TOOL_ID = "otis_gnss_baud_envelope_live_v1"
ROOT = Path(__file__).resolve().parents[2]
NORMAL_FIFO = Path("control/gnss_baud_normal_commands.fifo")
EMERGENCY_FIFO = Path("control/gnss_baud_priority_abort.fifo")
SEGMENT_CONTROL = Path("control/capture_segment_rotation")
EVENTS = Path("reports/gnss_baud_envelope_supervisor_events_v1.jsonl")
STATE = Path("reports/gnss_baud_envelope_supervisor_state_v1.json")
ANALYSIS = Path("reports/gnss_baud_envelope_analysis_v1.json")
SEAL = Path("reports/gnss_baud_envelope_seal_v1.json")
MONITOR = Path("reports/gnss_baud_envelope_monitor_events_v1.jsonl")
LIVE_RESULT = Path("reports/gnss_baud_envelope_live_result_v1.json")
ATTACHMENT_TERMINAL = Path("reports/gnss_baud_envelope_attachment_terminal_v1.json")
FLASH_RECORD = Path("reports/gnss_baud_envelope_firmware_flash_v1.json")
SUCCESS_TERMINALS = frozenset(
    {
        "multi_baud_characterization_complete",
        "multi_baud_characterization_partial_receiver_recovered",
        "multi_baud_characterization_continuation_complete",
        "multi_baud_characterization_continuation_partial_receiver_recovered",
    }
)


def _exception_reason_and_detail(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, ProgrammeTerminalError):
        return exc.reason, exc.detail
    return "evidence_carrier_failure", str(exc)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _path_binding(value: object, *, field: str) -> Path:
    if isinstance(value, Mapping):
        value = value.get("path")
    if not isinstance(value, str) or not value:
        raise ValueError(f"candidate {field} path is unavailable")
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _expected_runtime_identity(
    candidate: Mapping[str, Any],
) -> dict[tuple[str, str], str]:
    firmware = candidate["firmware"]
    configuration = firmware["compile_time_configuration"]
    config_sha256 = configuration.get("sha256")
    if not isinstance(config_sha256, str) or len(config_sha256) != 64:
        raise ValueError("candidate firmware configuration identity is unavailable")
    return {
        (CHARACTERIZATION_COMPONENT, "programme_id"): PROGRAMME_ID,
        (CHARACTERIZATION_COMPONENT, "contract_sha256"): str(
            candidate["contract"]["sha256"]
        ),
        (CHARACTERIZATION_COMPONENT, "command_table_id"): COMMAND_TABLE_ID,
        ("build", "profile_id"): str(firmware["profile_id"]),
        ("build", "git_commit"): str(firmware["source_revision"]),
        ("build", "source_sha256"): str(firmware["source_tree_identity"]),
        ("build", "config_sha256"): config_sha256,
        ("firmware", "version"): str(firmware["firmware_version"]),
    }


def _capture_duration_seconds(
    *, candidate: Mapping[str, Any], contract: Mapping[str, Any]
) -> int:
    segment_online = sum(
        int(segment["confirmed_online_s"])
        for segment in contract["schedule"]["segments"]
    )
    candidate_schedule = candidate["schedule"]
    if segment_online != int(contract["schedule"]["total_confirmed_online_seconds"]):
        raise ValueError("contract schedule online-duration total differs")
    if segment_online != int(candidate_schedule["total_confirmed_online_seconds"]):
        raise ValueError("candidate and contract online-duration totals differ")
    transition_seconds = (
        len(contract["schedule"]["segments"])
        * int(
            contract["transition_policy"][
                "serial_link_unrecoverable_deadline_ms"
            ]
        )
        // 1000
    )
    if transition_seconds != int(
        candidate_schedule["maximum_transition_and_recovery_seconds"]
    ):
        raise ValueError("candidate transition/recovery horizon differs")
    return segment_online + transition_seconds


def _claim_run_directory(run_dir: Path) -> None:
    """Atomically consume one activated run directory before hardware I/O.

    An existing leaf means this activation has already been attempted, even if
    the prior attempt stopped before it could materialize a complete package.
    Recovery of such a directory is an offline finalization operation; it must
    never replay the live activation or flash.
    """

    run_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_dir.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError as exc:
        raise FileExistsError(
            f"activated run directory is already claimed: {run_dir}"
        ) from exc


def _validate_exact_registration(
    *,
    index_path: Path,
    package_path: Path,
    registration: Mapping[str, Any],
) -> None:
    """Validate only the package registered by this campaign finalization."""

    observed = package_identity(package_path)
    content_sha256 = str(registration.get("content_sha256", ""))
    if (
        observed["content_sha256"] != content_sha256
        or observed["file_count"] != registration.get("file_count")
        or observed["total_bytes"] != registration.get("total_bytes")
        or observed["files"] != registration.get("file_manifest")
        or str(package_path.resolve())
        not in registration.get("storage_locations", [])
    ):
        raise RuntimeError("registered campaign package identity differs")
    indexed = load_index(index_path).get("packages", {}).get(content_sha256)
    if indexed != dict(registration):
        raise RuntimeError("registered campaign record differs in evidence index")


def _copy_exact(source: Path, destination: Path, *, expected_sha256: str) -> None:
    if sha256(source.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError(f"activated source identity changed: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _materialize_activated_inputs(
    *,
    candidate_path: Path,
    activation_path: Path,
    candidate: Mapping[str, Any],
    activation: Mapping[str, Any],
    run_dir: Path,
) -> Path:
    """Freeze every activated input in the run before the first hardware I/O."""

    _copy_exact(
        candidate_path.resolve(),
        run_dir / "reports/activated_candidate_bundle_v1.json",
        expected_sha256=str(activation["bundle_sha256"]),
    )
    activation_sha = sha256(activation_path.resolve().read_bytes()).hexdigest()
    _copy_exact(
        activation_path.resolve(),
        run_dir / "reports/activated_live_activation_v1.json",
        expected_sha256=activation_sha,
    )
    for binding, destination, field in (
        (
            candidate["contract"],
            "reports/activated_contract_v1.json",
            "contract",
        ),
        (
            candidate["firmware"]["build_manifest"],
            "reports/activated_firmware_build_manifest_v1.json",
            "firmware build manifest",
        ),
        (
            candidate["preflight"],
            "reports/activated_profile_preflight_v1.json",
            "profile preflight",
        ),
        (
            candidate["operational_check"],
            "reports/activated_operational_check_v1.json",
            "operational check",
        ),
    ):
        source = _path_binding(binding, field=field)
        _copy_exact(
            source,
            run_dir / destination,
            expected_sha256=str(binding["sha256"]),
        )
    template = candidate["run_manifest_template"]
    if not isinstance(template, Mapping):
        raise ValueError("candidate run_manifest_template is not an object")
    manifest_template = run_dir / "reports/activated_run_manifest_template_v1.json"
    _atomic_json(manifest_template, dict(template))
    return manifest_template


def _write_jsonl_record(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _ensure_terminal_artifacts(
    *,
    candidate: Mapping[str, Any],
    activation: Mapping[str, Any],
    run_dir: Path,
    terminal: Mapping[str, Any],
    capture_started: bool,
    attachment_passed: bool,
    abort_attempted: bool,
) -> None:
    """Make every declared terminal artifact explicit, including no-I/O failures."""

    paths = ensure_run_layout(run_dir)
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        manifest = json.loads(
            json.dumps(candidate["run_manifest_template"], allow_nan=False)
        )
        now = _utc_now()
        manifest.update(
            {
                "template": False,
                "run_id": str(activation["run_id"]),
                "created_utc": now,
                "started_at_utc": now,
                "actionable": False,
                "capture_mode": "pre_capture_terminal",
            }
        )
        manifest["firmware"]["build_provenance_required"] = False
        manifest["gnss_baud_envelope"]["physical_evidence"] = False
        manifest["host"]["serial_device"] = str(activation["device"])
        manifest["host"]["baud"] = 115200
        _atomic_json(manifest_path, manifest)
    elif not attachment_passed:
        # A capture may terminate before the full emitted provenance banner.
        # The immutable activated build record remains mandatory; the generic
        # evidence reader is told truthfully not to infer a complete banner.
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["actionable"] = False
        manifest["firmware"]["build_provenance_required"] = False
        _atomic_json(manifest_path, manifest)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        path = run_dir / str(entry["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.touch()
    if not paths.raw_serial_log.exists():
        paths.raw_serial_log.touch()

    capture_log = run_dir / "reports/gnss_baud_envelope_capture_process.log"
    if not capture_log.exists():
        capture_log.touch()
    if not (run_dir / FLASH_RECORD).exists():
        unsigned = {
            "schema_version": 1,
            "tool": TOOL_ID,
            "operation": "exact_gnss_baud_envelope_firmware_flash",
            "status": "failed_before_flash_attempt",
            "completed_utc": _utc_now(),
            "firmware_flash_count": 0,
            "automatic_retry_count": 0,
            "dac_write_attempt_count": 0,
            "control_arm_attempt_count": 0,
            "uf2_sha256": candidate["firmware"]["binary_sha256"],
            "expected_usb_serial": candidate["expected_device"]["usb_serial"],
            "reason": terminal.get("reason", terminal.get("terminal")),
        }
        _atomic_json(
            run_dir / FLASH_RECORD,
            {
                **unsigned,
                "record_sha256": sha256(
                    json.dumps(
                        unsigned, sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest(),
            },
        )
    if not (run_dir / CAPTURE_STATE).exists():
        _atomic_json(
            run_dir / CAPTURE_STATE,
            {
                "schema_version": 1,
                "capture_active": False,
                "serial_open": False,
                "status": "stopped" if capture_started else "not_started",
            },
        )
    closure = run_dir / "reports/capture_segment_closure_v1.json"
    if not closure.exists():
        _atomic_json(
            closure,
            {
                "schema_version": 1,
                "status": "closed" if capture_started else "not_started",
                "reason": terminal.get("reason", terminal.get("terminal")),
            },
        )
    if not (run_dir / EVENTS).exists():
        _write_jsonl_record(
            run_dir / EVENTS,
            {
                "event": "programme_not_started",
                "programme_id": PROGRAMME_ID,
                "contract_sha256": candidate["contract"]["sha256"],
                "terminal": terminal.get("terminal"),
                "reason": terminal.get("reason"),
            },
        )
    if not (run_dir / STATE).exists():
        _atomic_json(
            run_dir / STATE,
            {
                "programme_id": PROGRAMME_ID,
                "contract_sha256": candidate["contract"]["sha256"],
                "terminal": dict(terminal),
            },
        )
    if not (run_dir / MONITOR).exists():
        _write_jsonl_record(
            run_dir / MONITOR,
            {
                "status": "not_started" if not capture_started else "stopped",
                "terminal": terminal.get("terminal"),
            },
        )
    if not (run_dir / ATTACHMENT_TERMINAL).exists():
        _atomic_json(
            run_dir / ATTACHMENT_TERMINAL,
            {
                "schema_version": 1,
                "status": "passed" if attachment_passed else "not_completed",
                "commands_issued_before_attachment": 0,
                "terminal": None if attachment_passed else terminal.get("terminal"),
                "reason": None if attachment_passed else terminal.get("reason"),
            },
        )
    abort_path = run_dir / "reports/gnss_baud_envelope_abort_delivery_v1.json"
    if not abort_path.exists():
        _atomic_json(
            abort_path,
            {
                "schema_version": 1,
                "status": "delivery_failed" if abort_attempted else "not_required",
                "delivery_confirmed": False,
                "reason": (
                    terminal.get("priority_abort_error")
                    if abort_attempted
                    else "programme terminal did not require priority abort"
                ),
            },
        )


def _wait(predicate, *, timeout_s: float, description: str) -> Any:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise TimeoutError(f"timed out waiting for {description}")


def _validate_usb_serial_identity(device: str, expected_serial: str) -> None:
    """Resolve the activated port to its physical USB serial before opening it."""

    from serial.tools import list_ports

    matches = [port for port in list_ports.comports() if port.device == device]
    if len(matches) != 1:
        raise ValueError(
            f"activated serial device must resolve exactly once; observed {len(matches)}"
        )
    observed = matches[0].serial_number
    if observed != expected_serial:
        raise ValueError(
            f"activated USB serial identity differs: expected {expected_serial}, "
            f"observed {observed!r}"
        )


def _locate_arduino_board(
    *, arduino_cli: str, expected_serial: str
) -> tuple[str, dict[str, str]]:
    completed = subprocess.run(
        [arduino_cli, "board", "list", "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    listing = json.loads(completed.stdout)
    addresses = [
        str(item.get("port", {}).get("address", ""))
        for item in listing.get("detected_ports", [])
        if item.get("port", {}).get("properties", {}).get("serialNumber")
        == expected_serial
    ]
    if len(addresses) != 1:
        raise ValueError(
            f"expected one re-enumerated board serial {expected_serial}; got {addresses}"
        )
    device = addresses[0]
    return device, read_board_identity(device, arduino_cli=arduino_cli)


def _flash_exact_once(
    *,
    candidate: Mapping[str, Any],
    activation: Mapping[str, Any],
    run_dir: Path,
) -> tuple[str, dict[str, Any]]:
    """Perform the activation's sole exact flash and bind re-enumeration."""

    device_before = str(activation["device"])
    expected_serial = str(candidate["expected_device"]["usb_serial"])
    if _serial_owner_pids(device_before):
        raise ValueError("serial device has an owner before exact firmware flash")
    _validate_usb_serial_identity(device_before, expected_serial)
    arduino_cli = shutil.which("arduino-cli")
    if arduino_cli is None:
        raise FileNotFoundError("arduino-cli is unavailable for the activated exact flash")
    firmware = candidate["firmware"]
    uf2_path = Path(str(firmware["binary_path"])).resolve()
    observed_uf2_sha = sha256(uf2_path.read_bytes()).hexdigest()
    if observed_uf2_sha != firmware["binary_sha256"]:
        raise ValueError("candidate UF2 identity changed before flash")
    configuration = firmware["compile_time_configuration"]
    fqbn = str(configuration.get("fqbn", ""))
    if not fqbn:
        raise ValueError("candidate build configuration lacks exact FQBN")
    board_before = read_board_identity(device_before, arduino_cli=arduino_cli)
    version = subprocess.run(
        [arduino_cli, "version", "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout.strip()
    command = [
        arduino_cli,
        "upload",
        "--port",
        device_before,
        "--fqbn",
        fqbn,
        "--input-file",
        str(uf2_path),
    ]
    started = _utc_now()
    stdout = ""
    stderr = ""
    exit_code: int | None = None
    timed_out = False
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        stdout = completed.stdout
        stderr = completed.stderr
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = "" if exc.stdout is None else str(exc.stdout)
        stderr = "" if exc.stderr is None else str(exc.stderr)
    device_after: str | None = None
    board_after: dict[str, str] | None = None
    reenumeration_error: str | None = None
    if exit_code == 0:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                device_after, board_after = _locate_arduino_board(
                    arduino_cli=arduino_cli, expected_serial=expected_serial
                )
                _validate_usb_serial_identity(device_after, expected_serial)
                break
            except (
                OSError,
                ValueError,
                subprocess.SubprocessError,
                json.JSONDecodeError,
            ) as exc:
                reenumeration_error = str(exc)
                time.sleep(0.5)
    passed = (
        not timed_out
        and exit_code == 0
        and device_after is not None
        and board_after is not None
        and board_before.get("serial_number")
        == board_after.get("serial_number")
        == expected_serial
    )
    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "operation": "exact_gnss_baud_envelope_firmware_flash",
        "status": "passed" if passed else "failed",
        "started_utc": started,
        "completed_utc": _utc_now(),
        "command": command,
        "timeout_s": 120,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "stdout_sha256": sha256(stdout.encode()).hexdigest(),
        "stderr_sha256": sha256(stderr.encode()).hexdigest(),
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
        "arduino_cli_version": version,
        "device_before": device_before,
        "device_after": device_after,
        "expected_usb_serial": expected_serial,
        "board_before": board_before,
        "board_after": board_after,
        "reenumeration_error": reenumeration_error,
        "fqbn": fqbn,
        "profile_id": firmware["profile_id"],
        "uf2_path": str(uf2_path),
        "uf2_sha256": observed_uf2_sha,
        "firmware_flash_count": 1,
        "automatic_retry_count": 0,
        "dac_write_attempt_count": 0,
        "control_arm_attempt_count": 0,
    }
    record = {**unsigned, "record_sha256": sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()}
    _atomic_json(run_dir / FLASH_RECORD, record)
    if not passed or device_after is None:
        raise RuntimeError("exact firmware flash or USB re-enumeration failed")
    return device_after, record


def _abort_delivery(
    *, emergency_fifo: Path, run_dir: Path, capture: subprocess.Popen[str], timeout_s: float
) -> dict[str, Any]:
    submitted = time.monotonic_ns()
    send_timestamped_command_to_fifo(
        emergency_fifo, "ACTIVE ABORT", created_monotonic_ns=submitted
    )

    def delivered() -> dict[str, Any] | None:
        if capture.poll() is not None:
            raise RuntimeError("capture exited before priority-abort delivery")
        path = run_dir / CAPTURE_STATE
        if not path.is_file():
            return None
        state = json.loads(path.read_text(encoding="utf-8"))
        if (
            state.get("emergency_abort_latched") is True
            and int(state.get("emergency_aborts_sent", 0)) == 1
        ):
            return state
        return None

    state = _wait(delivered, timeout_s=timeout_s, description="priority-abort delivery")
    result = {
        "schema_version": 1,
        "command": "ACTIVE ABORT",
        "submitted_monotonic_ns": submitted,
        "capture_pid": capture.pid,
        "delivery_confirmed": True,
        "emergency_aborts_sent": int(state["emergency_aborts_sent"]),
    }
    _atomic_json(run_dir / "reports/gnss_baud_envelope_abort_delivery_v1.json", result)
    return result


def _launch_capture(
    *,
    candidate: Mapping[str, Any],
    run_dir: Path,
    manifest_template: Path,
    device: str,
    normal_fifo: Path,
    emergency_fifo: Path,
    control_dir: Path,
    capability: str,
    capture_duration_s: int,
) -> tuple[subprocess.Popen[str], Any]:
    """Perform every post-flash/pre-capture step inside one caught boundary."""

    _validate_usb_serial_identity(
        device, str(candidate["expected_device"]["usb_serial"])
    )
    if _serial_owner_pids(device):
        raise ValueError("serial device already has an owner before campaign entry")
    capture_log_path = run_dir / "reports/gnss_baud_envelope_capture_process.log"
    capture_log_path.parent.mkdir(parents=True, exist_ok=True)
    capture_log = capture_log_path.open("x", encoding="utf-8")
    try:
        capture = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "host.otis_tools.capture_device",
                "--device",
                device,
                "--baud",
                "115200",
                "--run-dir",
                str(run_dir),
                "--duration-s",
                str(capture_duration_s),
                "--status-interval",
                str(LIVE_CAPTURE_STATUS_INTERVAL_S),
                "--command-fifo",
                str(normal_fifo),
                "--emergency-command-fifo",
                str(emergency_fifo),
                "--write-timeout-s",
                "1",
                "--normal-command-max-age-s",
                "2",
                "--manifest-template",
                str(manifest_template),
                "--segment-control-dir",
                str(control_dir),
                "--segment-capability",
                capability,
            ],
            cwd=ROOT,
            stdout=capture_log,
            stderr=capture_log,
            text=True,
        )
    except BaseException:
        capture_log.close()
        raise
    return capture, capture_log


def _stop_after_same_owner_rotation(
    *,
    capture: subprocess.Popen[str],
    run_dir: Path,
    control_dir: Path,
    capability: str,
) -> dict[str, Any]:
    drain_dir = run_dir.parent / f"{run_dir.name}__post_campaign_drain"
    prepare_transition(run_dir / "run_manifest.json", drain_dir)
    response = request_rotation(
        control_dir=control_dir,
        capability=capability,
        to_run=drain_dir,
        mode="transition",
        wait_timeout_s=15.0,
        operation_id=f"{run_dir.name}-post-campaign-drain",
    )
    if int(response.get("pid", response.get("capture_pid", capture.pid))) != capture.pid:
        raise RuntimeError("same-owner rotation response changed capture PID")
    capture.send_signal(signal.SIGINT)
    try:
        capture.wait(timeout=30)
    except subprocess.TimeoutExpired:
        capture.terminate()
        capture.wait(timeout=10)
    if capture.returncode != 0:
        raise RuntimeError(f"capture exited with status {capture.returncode}")
    return response


def _finalize(
    *,
    candidate: Mapping[str, Any],
    activation: Mapping[str, Any],
    contract_path: Path,
    run_dir: Path,
    terminal: Mapping[str, Any],
    stable_live_result: dict[str, Any],
    analyze_programme: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {"terminal": dict(terminal)}
    flash = json.loads((run_dir / FLASH_RECORD).read_text(encoding="utf-8"))
    physical_evidence = flash.get("status") == "passed"
    if analyze_programme:
        analysis = analyze(
            contract_path=contract_path,
            events_path=run_dir / EVENTS,
            output_path=run_dir / ANALYSIS,
            flash_record_path=run_dir / FLASH_RECORD,
        )
        seal = create_seal(
            contract_path=contract_path,
            events_path=run_dir / EVENTS,
            analysis_path=run_dir / ANALYSIS,
            physical_evidence=physical_evidence,
        )
    else:
        unsigned_analysis = {
            "schema_version": 1,
            "analyzer": "otis_gnss_baud_envelope_interrupted_entry_v1",
            "programme_id": PROGRAMME_ID,
            "contract_sha256": sha256(contract_path.read_bytes()).hexdigest(),
            "evidence_status": "failed",
            "programme_terminal": terminal.get("terminal"),
            "failure_reason": terminal.get("reason", terminal.get("terminal")),
            "final_confirmed_9600": False,
            "physical_evidence": physical_evidence,
        }
        analysis = {
            **unsigned_analysis,
            "analysis_sha256": sha256(
                json.dumps(
                    unsigned_analysis, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest(),
        }
        _atomic_json(run_dir / ANALYSIS, analysis)
        seal = create_seal(
            contract_path=contract_path,
            events_path=run_dir / EVENTS,
            analysis_path=run_dir / ANALYSIS,
            physical_evidence=physical_evidence,
        )
    _atomic_json(run_dir / SEAL, seal)
    result["analysis"] = analysis
    result["seal_sha256"] = seal["seal_sha256"]
    stable_live_result["analysis_sha256"] = analysis["analysis_sha256"]
    stable_live_result["seal_sha256"] = seal["seal_sha256"]
    _atomic_json(run_dir / LIVE_RESULT, stable_live_result)
    complete = run_dir / "COMPLETE"
    if not complete.exists():
        complete.write_text(
            json.dumps({"completed_utc": _utc_now(), "terminal": terminal}, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    snapshot_path = create_evidence_snapshot(run_dir)
    result["evidence_snapshot_sha256"] = sha256(snapshot_path.read_bytes()).hexdigest()
    index_value = activation.get(
        "registration_index_path", candidate.get("registration_index_path")
    )
    if index_value is None:
        index_path = DEFAULT_INDEX
    elif isinstance(index_value, Mapping):
        index_path = Path(str(index_value.get("path", "")))
    elif isinstance(index_value, str) and index_value:
        index_path = Path(index_value)
    else:
        raise ValueError("activated registration_index_path is unavailable")
    if not index_path.is_absolute():
        index_path = ROOT / index_path
    firmware = candidate["firmware"]
    registration = register_package(
        index_path=index_path,
        package_path=run_dir,
        source_revision=str(firmware["source_revision"]),
        build_identity=str(firmware["binary_sha256"]),
        profile_identity=GNSS_BAUD_ENVELOPE_PROFILE_ID,
        attempt_classification=(
            "completed_campaign"
            if terminal.get("terminal") in SUCCESS_TERMINALS
            else "interrupted_campaign"
        ),
        result_or_failure_reason=str(terminal.get("reason", terminal.get("terminal"))),
        analyzer_identity=sha256(
            Path(__file__).with_name("gnss_baud_envelope_analyze.py").read_bytes()
        ).hexdigest(),
    )
    _validate_exact_registration(
        index_path=index_path,
        package_path=run_dir,
        registration=registration,
    )
    result["registration_content_sha256"] = registration["content_sha256"]
    return result


def execute(*, candidate_path: Path, activation_path: Path) -> dict[str, Any]:
    # Imported lazily so the candidate/activation builder remains independently
    # usable during preflight and repository-level source checks.
    from .gnss_baud_envelope_bundle import load_and_validate

    candidate, activation = load_and_validate(candidate_path, activation_path)
    if candidate.get("programme_id") != PROGRAMME_ID:
        raise ValueError("activated candidate programme identity is wrong")
    run_dir = Path(str(activation["run_dir"])).resolve()
    _claim_run_directory(run_dir)
    contract_path = _path_binding(candidate["contract"], field="contract")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    minimum_capture_duration_s = _capture_duration_seconds(
        candidate=candidate, contract=contract
    )
    wall_deadline = datetime.fromisoformat(
        str(activation["wall_deadline_utc"]).replace("Z", "+00:00")
    )
    if wall_deadline <= datetime.now(timezone.utc) + timedelta(
        seconds=minimum_capture_duration_s
    ):
        raise ValueError(
            "activation wall deadline cannot contain the exact capture horizon"
        )
    manifest_template = _materialize_activated_inputs(
        candidate_path=candidate_path,
        activation_path=activation_path,
        candidate=candidate,
        activation=activation,
        run_dir=run_dir,
    )
    try:
        device, flash_record = _flash_exact_once(
            candidate=candidate, activation=activation, run_dir=run_dir
        )
    except Exception as exc:
        terminal = {
            "terminal": "pre_capture_firmware_flash_failed",
            "reason": str(exc),
            "error_type": type(exc).__name__,
            "firmware_flash_retry_permitted": False,
        }
        _ensure_terminal_artifacts(
            candidate=candidate,
            activation=activation,
            run_dir=run_dir,
            terminal=terminal,
            capture_started=False,
            attachment_passed=False,
            abort_attempted=False,
        )
        stable_result = {
            "schema_version": 1,
            "tool": TOOL_ID,
            "programme_id": PROGRAMME_ID,
            "terminal": terminal,
            "capture_pid": None,
            "firmware_flash_record_sha256": sha256(
                (run_dir / FLASH_RECORD).read_bytes()
            ).hexdigest(),
            "priority_abort": {"status": "not_required"},
            "same_owner_rotation": None,
        }
        finalized = _finalize(
            candidate=candidate,
            activation=activation,
            contract_path=contract_path,
            run_dir=run_dir,
            terminal=terminal,
            stable_live_result=stable_result,
            analyze_programme=False,
        )
        return {**stable_result, "registration": finalized}
    normal_fifo = run_dir / str(candidate["capture"]["normal_fifo"])
    emergency_fifo = run_dir / str(candidate["capture"]["priority_fifo"])
    control_dir = run_dir / SEGMENT_CONTROL
    capability = f"gnss-baud-envelope-{candidate['bundle_id']}"
    capture_duration_s = int(
        (wall_deadline - datetime.now(timezone.utc)).total_seconds()
    )
    try:
        if capture_duration_s < minimum_capture_duration_s:
            raise ValueError(
                "activated wall deadline no longer contains the minimum campaign horizon"
            )
        capture, capture_log = _launch_capture(
            candidate=candidate,
            run_dir=run_dir,
            manifest_template=manifest_template,
            device=device,
            normal_fifo=normal_fifo,
            emergency_fifo=emergency_fifo,
            control_dir=control_dir,
            capability=capability,
            capture_duration_s=capture_duration_s,
        )
    except Exception as exc:
        terminal = {
            "terminal": "post_flash_capture_start_failed",
            "reason": str(exc),
            "error_type": type(exc).__name__,
            "firmware_flash_retry_permitted": False,
        }
        _ensure_terminal_artifacts(
            candidate=candidate,
            activation=activation,
            run_dir=run_dir,
            terminal=terminal,
            capture_started=False,
            attachment_passed=False,
            abort_attempted=False,
        )
        stable_result = {
            "schema_version": 1,
            "tool": TOOL_ID,
            "programme_id": PROGRAMME_ID,
            "terminal": terminal,
            "capture_pid": None,
            "capture_duration_s": capture_duration_s,
            "activated_wall_deadline_utc": activation["wall_deadline_utc"],
            "firmware_flash_record_sha256": sha256(
                (run_dir / FLASH_RECORD).read_bytes()
            ).hexdigest(),
            "priority_abort": {"status": "not_required"},
            "same_owner_rotation": None,
        }
        finalized = _finalize(
            candidate=candidate,
            activation=activation,
            contract_path=contract_path,
            run_dir=run_dir,
            terminal=terminal,
            stable_live_result=stable_result,
            analyze_programme=False,
        )
        return {**stable_result, "registration": finalized}
    capture_started = True
    attachment_passed = False
    abort_attempted = False
    supervisor = None
    monitor: subprocess.Popen[str] | None = None
    terminal: dict[str, Any]
    abort: dict[str, Any] | None = None
    rotation: dict[str, Any] | None = None
    try:
        _wait(
            lambda: _capture_state_ready(run_dir, capture.pid),
            timeout_s=30,
            description="sole-owner capture start",
        )
        if _serial_owner_pids(device) != {capture.pid}:
            raise ProgrammeTerminalError(
                "sole_usb_serial_owner_loss", "capture did not become sole owner"
            )
        transport = CaptureDeviceTransport(
            contract=contract,
            run_dir=run_dir,
            normal_fifo=normal_fifo,
            device=device,
            capture_pid=capture.pid,
            capture_status_interval_s=LIVE_CAPTURE_STATUS_INTERVAL_S,
            expected_runtime_identity=_expected_runtime_identity(candidate),
        )
        try:
            initial = transport.initial_state_evidence(
                expected_device=candidate["expected_device"]
            )
        except Exception as exc:
            attachment = {
                "schema_version": 1,
                "terminal": "precommand_attachment_invalid",
                "reason": str(exc),
                "error_type": type(exc).__name__,
                "error_detail": str(exc),
                "commands_issued": 0,
            }
            _atomic_json(run_dir / ATTACHMENT_TERMINAL, attachment)
            raise
        attachment_passed = True
        _atomic_json(
            run_dir / ATTACHMENT_TERMINAL,
            {
                "schema_version": 1,
                "status": "passed",
                "commands_issued_before_attachment": 0,
                "runtime_identity": {
                    f"{component}.{key}": value
                    for (component, key), value in _expected_runtime_identity(
                        candidate
                    ).items()
                },
                "initial_state": dict(initial),
            },
        )
        _contract, supervisor = new_supervisor(
            contract_path=contract_path,
            run_dir=run_dir,
            run_id=str(activation["run_id"]),
            initial_state=initial,
        )
        monitor = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "host.otis_tools.gnss_baud_envelope_monitor",
                str(run_dir),
                "--contract",
                str(contract_path),
                "--follow",
                "--output",
                str(run_dir / MONITOR),
                "--poll-s",
                "1",
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        last_integrity_poll = 0.0

        def monitor_integrity_check() -> None:
            nonlocal last_integrity_poll
            now = time.monotonic()
            if now - last_integrity_poll < 0.5:
                return
            last_integrity_poll = now
            if monitor is None or monitor.poll() is not None:
                raise ProgrammeTerminalError(
                    "evidence_carrier_failure", "authoritative monitor process exited"
                )
            observed = monitor_snapshot(run_dir, contract_path=contract_path)
            if observed.get("status") == "fault":
                raise ProgrammeTerminalError(
                    "evidence_discontinuity",
                    "authoritative monitor fault: "
                    + ",".join(str(item) for item in observed["integrity_faults"]),
                )

        transport.bind_integrity_check(monitor_integrity_check)
        terminal = run_programme(
            contract=_contract, supervisor=supervisor, transport=transport
        )
        if terminal.get("terminal") not in SUCCESS_TERMINALS:
            try:
                abort_attempted = True
                abort = _abort_delivery(
                    emergency_fifo=emergency_fifo,
                    run_dir=run_dir,
                    capture=capture,
                    timeout_s=float(activation.get("abort_deadline_ms", 5000))
                    / 1000,
                )
            except Exception as abort_exc:
                terminal = {
                    **terminal,
                    "priority_abort_delivery": "failed",
                    "priority_abort_error": str(abort_exc),
                }
    except Exception as exc:
        reason, error_detail = _exception_reason_and_detail(exc)
        if supervisor is not None:
            terminal = supervisor.programme_fault(
                reason,
                timestamp_ticks=time.monotonic_ns(),
                error_detail=error_detail,
            )
        else:
            terminal = {
                "terminal": "precommand_attachment_invalid",
                "reason": str(exc),
                "error_type": type(exc).__name__,
                "error_detail": error_detail,
            }
        try:
            abort_attempted = True
            abort = _abort_delivery(
                emergency_fifo=emergency_fifo,
                run_dir=run_dir,
                capture=capture,
                timeout_s=float(activation.get("abort_deadline_ms", 5000)) / 1000,
            )
        except Exception as abort_exc:
            terminal = {
                **terminal,
                "priority_abort_delivery": "failed",
                "priority_abort_error": str(abort_exc),
            }
    finally:
        teardown_failures: list[str] = []
        if monitor is not None:
            try:
                monitor.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    monitor.terminate()
                    monitor.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    monitor.kill()
                    try:
                        monitor.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        teardown_failures.append(
                            "authoritative monitor could not be reaped"
                        )
                except Exception as monitor_exc:
                    teardown_failures.append(
                        f"authoritative monitor teardown failed: {monitor_exc}"
                    )
        if capture.poll() is None:
            try:
                rotation = _stop_after_same_owner_rotation(
                    capture=capture,
                    run_dir=run_dir,
                    control_dir=control_dir,
                    capability=capability,
                )
            except Exception as stop_exc:
                try:
                    capture.send_signal(signal.SIGINT)
                    capture.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    capture.terminate()
                    try:
                        capture.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        capture.kill()
                        try:
                            capture.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            teardown_failures.append(
                                "capture process could not be reaped"
                            )
                except Exception as capture_exc:
                    teardown_failures.append(
                        f"capture forced-stop failed: {capture_exc}"
                    )
                teardown_failures.append(
                    f"same-owner rotation/capture stop failed: {stop_exc}"
                )
        else:
            teardown_failures.append(
                "capture exited before required same-owner rotation "
                f"with returncode {capture.returncode}"
            )
        try:
            capture_log.close()
        except Exception as log_exc:
            teardown_failures.append(f"capture log close failed: {log_exc}")
        if teardown_failures:
            programme_terminal_before_teardown = dict(terminal)
            terminal = {
                "terminal": "programme_invalid_due_to_platform_or_evidence_failure",
                "reason": "evidence_carrier_failure",
                "programme_terminal_before_teardown":
                    programme_terminal_before_teardown,
                "teardown_failures": teardown_failures,
            }
    _ensure_terminal_artifacts(
        candidate=candidate,
        activation=activation,
        run_dir=run_dir,
        terminal=terminal,
        capture_started=capture_started,
        attachment_passed=attachment_passed,
        abort_attempted=abort_attempted,
    )
    stable_result = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "programme_id": PROGRAMME_ID,
        "terminal": terminal,
        "capture_pid": capture.pid,
        "capture_duration_s": capture_duration_s,
        "activated_wall_deadline_utc": activation["wall_deadline_utc"],
        "firmware_flash_record_sha256": sha256(
            (run_dir / FLASH_RECORD).read_bytes()
        ).hexdigest(),
        "priority_abort": abort,
        "same_owner_rotation": rotation,
    }
    finalized = _finalize(
        candidate=candidate,
        activation=activation,
        contract_path=contract_path,
        run_dir=run_dir,
        terminal=terminal,
        stable_live_result=stable_result,
        analyze_programme=supervisor is not None,
    )
    # Registration is deliberately returned only through stdout/caller state;
    # the content-addressed package is immutable after register_package.
    return {**stable_result, "registration": finalized}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--activation", type=Path, required=True)
    args = parser.parse_args(argv)
    result = execute(candidate_path=args.candidate, activation_path=args.activation)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0 if result["terminal"].get("terminal") in SUCCESS_TERMINALS else 2


if __name__ == "__main__":
    raise SystemExit(main())
