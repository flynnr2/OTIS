"""Two-process OTIS runtime: foreground experiment owner plus capture worker."""
from __future__ import annotations

import csv
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .active_status_contract import (
    ACTIVE_STATUS_WIRE_KEYS,
    SNAPSHOT_BEGIN_KEY,
    complete_active_status_snapshots,
)
from .adaptive_hybrid_supervisor import (
    AdaptiveHybridSupervisor,
    prepare_runtime_context,
)
from .adaptive_hybrid_transactions import SUPERVISOR_STATE, _atomic_json
from .adaptive_hybrid_transport import read_capture_transport_state
from .contracts import HEALTH_FIELDS
from .run_loader import load_manifest
from .run_spec import load_run_spec, verify_current_host_toolset
from .serial_commands import send_timestamped_command_to_fifo

NORMAL_FIFO = Path("control/normal_commands.fifo")
EMERGENCY_FIFO = Path("control/emergency_abort.fifo")
CAPTURE_STATE = Path("reports/capture_device_state.json")
RAW_SERIAL = Path("raw/serial.log")
CAPTURE_LOG = Path("reports/capture_device.stdout.log")
ABORT_DELIVERY_TIMEOUT_S = 15.0
CAPTURE_START_TIMEOUT_S = 15.0
CAPTURE_STOP_TIMEOUT_S = 15.0
HOST_MARKER_PREFIX = "# OTIS_HOST "


@dataclass(frozen=True)
class LiveExperiment:
    """Run-local handles exposed to a deterministic start adapter."""

    run_dir: Path
    device: str
    capture_pid: int
    emergency_fifo: Path

    def submit_explicit_abort(self) -> None:
        send_timestamped_command_to_fifo(self.emergency_fifo, "ACTIVE ABORT")


class _AbortDeliveryObserver:
    """Read only evidence after capture's exact priority-abort frontier."""

    READ_BYTES = 65536

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir.resolve()
        self.frontier: dict[str, Any] | None = None
        self.offset: int | None = None
        self.partial = b""
        self.marker_seen = False
        self.rows: list[dict[str, str]] = []
        self.highest_started_generation = 0

    def observe(self, capture: dict[str, Any]) -> dict[tuple[str, str], str] | None:
        frontier = capture.get("emergency_abort_raw_frontier")
        if frontier is None:
            return None
        if (
            not isinstance(frontier, dict)
            or frontier.get("run_directory") != str(self.run_dir)
            or type(frontier.get("search_offset_bytes")) is not int
            or frontier["search_offset_bytes"] < 0
            or any(
                type(frontier.get(key)) is not int or frontier[key] < 0
                for key in ("device", "inode")
            )
        ):
            raise ValueError("capture abort frontier is malformed or belongs to another run")
        if self.frontier is None:
            self.frontier = dict(frontier)
            self.offset = frontier["search_offset_bytes"]
        elif frontier != self.frontier:
            raise ValueError("capture abort frontier changed")
        assert self.offset is not None
        with (self.run_dir / RAW_SERIAL).open("rb") as handle:
            metadata = os.fstat(handle.fileno())
            if (metadata.st_dev, metadata.st_ino) != (
                frontier["device"], frontier["inode"]
            ):
                raise ValueError("abort frontier differs from capture's raw file")
            if self.offset > metadata.st_size:
                raise ValueError("abort evidence was truncated")
            handle.seek(self.offset)
            payload = handle.read(self.READ_BYTES)
            self.offset += len(payload)
        lines = (self.partial + payload).split(b"\n")
        self.partial = lines.pop()
        if len(self.partial) > self.READ_BYTES:
            raise ValueError("post-abort raw line exceeds the observation bound")
        for line in lines:
            text = line.decode("utf-8", errors="strict")
            if text.startswith(HOST_MARKER_PREFIX):
                marker = json.loads(text[len(HOST_MARKER_PREFIX):])
                if not isinstance(marker, dict):
                    raise ValueError("post-abort host marker is malformed")
                if marker.get("event") == "emergency_abort_sent":
                    if self.marker_seen:
                        raise ValueError("capture recorded repeated abort-send markers")
                    self.marker_seen = True
                    self.rows.clear()
                continue
            if not self.marker_seen or not text.startswith("STS,"):
                continue
            values = next(csv.reader([text]))
            if len(values) != len(HEALTH_FIELDS):
                raise ValueError("post-abort status row width differs")
            row = dict(zip(HEALTH_FIELDS, values, strict=True))
            if row["component"] != "adaptive_hybrid":
                continue
            if row["status_key"] == SNAPSHOT_BEGIN_KEY:
                self.highest_started_generation = max(
                    self.highest_started_generation, int(row["status_value"])
                )
                self.rows.clear()
            self.rows.append(row)
            if len(self.rows) > len(ACTIVE_STATUS_WIRE_KEYS):
                raise ValueError("post-abort snapshot exceeds its declared bound")
        snapshots, newest_started = complete_active_status_snapshots(self.rows)
        if (
            not snapshots
            or int(snapshots[-1]["snapshot_generation_complete"])
            != max(newest_started, self.highest_started_generation)
        ):
            return None
        return {
            ("adaptive_hybrid", key): value
            for key, value in snapshots[-1].items()
        }


def wait_for_abort_delivery(
    run_dir: Path,
    terminal: dict[str, Any],
    *,
    expected_capture_pid: int | None = None,
    deadline_ns: int | None = None,
) -> None:
    """Require the send marker and a causally later firmware fail-static snapshot."""
    if terminal.get("result") != "aborted":
        return
    if deadline_ns is None:
        deadline_ns = time.monotonic_ns() + int(
            ABORT_DELIVERY_TIMEOUT_S * 1_000_000_000
        )
    observer = _AbortDeliveryObserver(run_dir)
    while time.monotonic_ns() < deadline_ns:
        state = read_capture_transport_state(
            run_dir,
            expected_pid=expected_capture_pid,
            allow_priority_abort=True,
            require_clean=False,
        )
        if (
            state.get("emergency_abort_latched") is True
            and int(state.get("emergency_aborts_sent", 0)) == 1
        ):
            health = observer.observe(state)
            if health is not None and (
                health.get(("adaptive_hybrid", "state")) == "ABORTED"
                and health.get(("adaptive_hybrid", "fail_static")) == "true"
                and health.get(("adaptive_hybrid", "evidence_pending")) == "false"
                and health.get(("adaptive_hybrid", "evidence_phase")) == "evidence_clear"
                and health.get(("adaptive_hybrid", "evidence_request_sequence")) == "0"
            ):
                static_code = terminal.get("last_confirmed_code")
                if static_code is None or (
                    health.get(("adaptive_hybrid", "confirmed_applied_code_known"))
                    == "true"
                    and int(
                        health.get(("adaptive_hybrid", "confirmed_applied_code"), "-1"),
                        0,
                    )
                    == static_code
                ):
                    return
        remaining_ns = deadline_ns - time.monotonic_ns()
        if remaining_ns > 0:
            time.sleep(min(0.1, remaining_ns / 1_000_000_000))
    raise TimeoutError("priority abort delivery was not confirmed before its deadline")


def _default_capture_command(device: str, run_dir: Path, manifest: dict[str, Any]) -> list[str]:
    host = manifest.get("host")
    if not isinstance(host, dict) or host.get("serial_device") != device:
        raise ValueError("runtime manifest serial device differs from requested attachment")
    baud = host.get("baud")
    capture = host.get("capture")
    if type(baud) is not int or baud <= 0:
        raise ValueError("runtime manifest capture baud is malformed")
    if not isinstance(capture, dict) or set(capture) != {
        "status_interval_s",
        "write_timeout_s",
        "normal_command_max_age_s",
        "normal_command_batch_limit",
    }:
        raise ValueError("runtime manifest capture configuration is malformed")
    if capture["normal_command_batch_limit"] != 1:
        raise ValueError("runtime manifest command batch limit differs")
    for key in ("status_interval_s", "write_timeout_s", "normal_command_max_age_s"):
        if type(capture[key]) not in {int, float} or capture[key] <= 0:
            raise ValueError(f"runtime manifest capture {key} is malformed")
    return [
        sys.executable,
        "-m", "host.otis_tools.capture_device",
        "--device", device,
        "--baud", str(baud),
        "--run-dir", str(run_dir),
        "--status-interval", str(capture["status_interval_s"]),
        "--command-fifo", str(run_dir / NORMAL_FIFO),
        "--emergency-command-fifo", str(run_dir / EMERGENCY_FIFO),
        "--write-timeout-s", str(capture["write_timeout_s"]),
        "--normal-command-max-age-s", str(capture["normal_command_max_age_s"]),
    ]


def _wait_capture_ready(run_dir: Path, capture: subprocess.Popen[str], device: str) -> None:
    from .capture_device import _serial_owner_pids

    deadline_ns = time.monotonic_ns() + int(CAPTURE_START_TIMEOUT_S * 1_000_000_000)
    last_error: Exception | None = None
    while time.monotonic_ns() < deadline_ns:
        if capture.poll() is not None:
            raise RuntimeError(f"capture worker exited before readiness: {capture.returncode}")
        try:
            read_capture_transport_state(run_dir, expected_pid=capture.pid)
            if _serial_owner_pids(device) != {capture.pid}:
                raise RuntimeError("capture worker is not the sole serial owner")
            if not (run_dir / NORMAL_FIFO).is_fifo() or not (run_dir / EMERGENCY_FIFO).is_fifo():
                raise RuntimeError("capture command ingress is incomplete")
            return
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            last_error = exc
        time.sleep(0.02)
    raise TimeoutError(f"capture readiness deadline expired: {last_error}")


def _close_capture(capture: subprocess.Popen[str]) -> int:
    """Request capture's graceful final-record drain, then bound escalation."""
    if capture.poll() is None:
        capture.send_signal(signal.SIGINT)
    try:
        return capture.wait(timeout=CAPTURE_STOP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        capture.kill()
        return capture.wait(timeout=5.0)



def _retain_foreground_review_hold(
    *,
    run_dir: Path,
    device: str,
    capture: subprocess.Popen[str],
    supervisor: AdaptiveHybridSupervisor | None,
    error: Exception,
) -> dict[str, Any]:
    """Keep the foreground owner alive until explicit abort or capture death."""
    state_path = run_dir / SUPERVISOR_STATE
    if supervisor is not None:
        try:
            supervisor._enter_host_verification_hold(error, source="foreground_owner")
        except (OSError, RuntimeError, TypeError, ValueError) as hold_error:
            error = RuntimeError(f"{error}; hold publication failed: {hold_error}")
            supervisor = None
    if supervisor is None:
        try:
            retained = json.loads(state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            retained = {"schema_version": 1, "terminal": None}
        if not isinstance(retained, dict):
            retained = {"schema_version": 1, "terminal": None}
        retained.update({
            "runtime_owner": {
                "pid": os.getpid(),
                "started_monotonic_ns": time.monotonic_ns(),
                "execution": "foreground_review_hold",
                "priority_abort_ingress": str(run_dir / EMERGENCY_FIFO),
            },
            "serial_device": device,
            "control_authority": False,
            "host_verification_hold": {
                "source": "foreground_owner_construction",
                "error_type": type(error).__name__,
                "error": str(error),
                "new_authority": False,
                "capture_and_serial_owner_retained": True,
            },
        })
        _atomic_json(state_path, retained)

    while capture.poll() is None:
        try:
            state = read_capture_transport_state(
                run_dir,
                expected_pid=capture.pid,
                allow_priority_abort=True,
                require_clean=False,
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            time.sleep(0.1)
            continue
        if not (
            state.get("emergency_abort_latched") is True
            or int(state.get("emergency_aborts_sent", 0)) != 0
        ):
            try:
                time.sleep(0.1)
            except KeyboardInterrupt:
                send_timestamped_command_to_fifo(
                    run_dir / EMERGENCY_FIFO, "ACTIVE ABORT"
                )
            continue

        if supervisor is not None:
            supervisor._observe_explicit_capture_abort(state)
            terminal = supervisor.state["terminal"]
            supervisor._emit_terminal_once()
        else:
            terminal = {
                "result": "aborted",
                "reason": "independent_emergency_abort_fifo",
                "primary_decision": "operator_abort",
            }
            try:
                retained = json.loads(state_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, json.JSONDecodeError):
                retained = {"schema_version": 1}
            if not isinstance(retained, dict):
                retained = {"schema_version": 1}
            retained["terminal"] = terminal
            try:
                _atomic_json(state_path, retained)
            except OSError:
                pass
        delivery_error: str | None = None
        try:
            wait_for_abort_delivery(
                run_dir, terminal, expected_capture_pid=capture.pid
            )
        except (OSError, TimeoutError, TypeError, ValueError) as exc:
            delivery_error = str(exc)
        capture_exit = _close_capture(capture)
        status = (
            "abort_delivery_failed"
            if delivery_error is not None
            else "terminal" if capture_exit == 0
            else "capture_closure_failed"
        )
        return {
            "status": status,
            "terminal": terminal,
            "run_directory": str(run_dir),
            "capture_pid": capture.pid,
            "capture_exit": capture_exit,
            "supervisor_exit": 3,
            "abort_delivery_error": delivery_error,
            "process_topology_count": 2,
        }

    return {
        "status": "pending_review_capture_ended",
        "run_directory": str(run_dir),
        "capture_pid": capture.pid,
        "capture_exit": capture.poll(),
        "error_type": type(error).__name__,
        "error": str(error),
        "process_topology_count": 2,
    }

def run_experiment(
    *,
    manifest_path: Path,
    device: str,
    physical: bool,
    capture_command: list[str] | None = None,
    on_ready: Callable[[LiveExperiment], Callable[[], None] | None] | None = None,
) -> dict[str, Any]:
    """Run one already-authorized attachment without flashing or resetting it."""
    manifest_path = manifest_path.resolve()
    run_dir = manifest_path.parent
    loaded = load_manifest(run_dir)
    if loaded.path.resolve() != manifest_path:
        raise ValueError("runtime record is not the run's canonical manifest")
    manifest = loaded.data
    execution_kind = manifest.get("execution_kind")
    expected_kind = "physical" if physical else "simulated"
    if execution_kind != expected_kind:
        raise ValueError(
            f"runtime execution kind differs: {execution_kind!r} != {expected_kind!r}"
        )
    if not physical:
        if capture_command is None:
            raise ValueError("simulated runtime requires a caller-supplied PTY capture command")
        canonical_device = os.path.realpath(device)
        if (
            canonical_device != device
            or re.fullmatch(r"/dev/(?:pts/[0-9]+|ttys[0-9]+)", device) is None
        ):
            raise ValueError("simulated runtime requires its exact PTY slave path")
    elif capture_command is not None:
        raise ValueError("physical runtime uses the manifest-bound capture worker")
    runtime_context = prepare_runtime_context(manifest)
    expected_capture_command = _default_capture_command(device, run_dir, manifest)
    if capture_command is not None and capture_command != expected_capture_command:
        raise ValueError("simulated capture command differs from the manifest-bound worker")
    run_spec = manifest.get("run_spec")
    if not isinstance(run_spec, dict) or not isinstance(run_spec.get("path"), str):
        raise ValueError("runtime manifest has no retained run specification")
    verify_current_host_toolset(load_run_spec(run_dir / run_spec["path"]))
    command = expected_capture_command
    log_path = run_dir / CAPTURE_LOG
    log_path.parent.mkdir(parents=True, exist_ok=True)
    output = log_path.open("x", encoding="utf-8")
    capture = subprocess.Popen(
        command,
        stdout=output,
        stderr=output,
        text=True,
        start_new_session=True,
    )
    cleanup: Callable[[], None] | None = None
    supervisor: AdaptiveHybridSupervisor | None = None
    try:
        _wait_capture_ready(run_dir, capture, device)
        supervisor = AdaptiveHybridSupervisor(
            runtime_context=runtime_context,
            manifest_path=manifest_path,
            run_dir=run_dir,
            command_fifo=run_dir / NORMAL_FIFO,
            emergency_command_fifo=run_dir / EMERGENCY_FIFO,
            expected_capture_pid=capture.pid,
            console_events=False,
        )
        experiment = LiveExperiment(
            run_dir=run_dir,
            device=device,
            capture_pid=capture.pid,
            emergency_fifo=run_dir / EMERGENCY_FIFO,
        )
        if on_ready is not None:
            cleanup = on_ready(experiment)
        supervisor_exit = supervisor.run()
        terminal = supervisor.state.get("terminal")
        if not isinstance(terminal, dict):
            raise RuntimeError("foreground supervisor returned without a terminal")
        wait_for_abort_delivery(
            run_dir, terminal, expected_capture_pid=capture.pid
        )
        capture_exit = _close_capture(capture)
        if capture_exit != 0:
            raise RuntimeError(f"capture worker exited with status {capture_exit}")
        return {
            "status": "terminal",
            "terminal": terminal,
            "run_directory": str(run_dir),
            "capture_pid": capture.pid,
            "capture_exit": capture_exit,
            "supervisor_exit": supervisor_exit,
            "process_topology_count": 2,
        }
    except KeyboardInterrupt:
        send_timestamped_command_to_fifo(run_dir / EMERGENCY_FIFO, "ACTIVE ABORT")
        return _retain_foreground_review_hold(
            run_dir=run_dir,
            device=device,
            capture=capture,
            supervisor=supervisor,
            error=RuntimeError("foreground owner received explicit interrupt"),
        )
    except Exception as exc:
        if not physical:
            _close_capture(capture)
            raise
        return _retain_foreground_review_hold(
            run_dir=run_dir,
            device=device,
            capture=capture,
            supervisor=supervisor,
            error=exc,
        )
    finally:
        if cleanup is not None:
            cleanup()
        output.close()
