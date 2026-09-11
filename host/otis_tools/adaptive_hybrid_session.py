"""The concrete capture/supervisor/monitor lifecycle shared by OTIS run and PTY.

Lifecycle readiness is transport/observation readiness. Only the supervisor's
fresh device census can admit control authority. This owner never implicitly
closes a physical capture in response to a host diagnostic.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from typing import Any

from .capture_device import _capture_state_ready, _serial_owner_pids

ROOT = Path(__file__).resolve().parents[2]
SESSION_PATH = Path("reports/adaptive_hybrid_session_v1.json")
SUPERVISOR_READY_PATH = Path("reports/adaptive_hybrid_supervisor_ready_v1.json")
MONITOR_STATE_PATH = Path("reports/adaptive_hybrid_monitor_state_v1.json")
MONITOR_SAMPLES_PATH = Path("reports/adaptive_hybrid_monitor_samples_v1.jsonl")
MONITOR_STOP_PATH = Path("control/monitor.stop")


def _write_state(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(value, output, sort_keys=True, allow_nan=False)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def _binding(run_dir: Path, manifest_path: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    if manifest_path.resolve() != run_dir / "run_manifest.json":
        raise ValueError("session manifest is outside its run")
    return {
        "run_directory": str(run_dir),
        "manifest_bytes_sha256": sha256(manifest_path.read_bytes()).hexdigest(),
    }


def publish_supervisor_ready(
    run_dir: Path, manifest_path: Path, *, census_process_nonce: int
) -> None:
    _write_state(run_dir / SUPERVISOR_READY_PATH, {
        "schema_version": 1, "role": "supervisor", "phase": "census_pending",
        **_binding(run_dir, manifest_path), "pid": os.getpid(),
        "observed_monotonic_ns": time.monotonic_ns(),
        "census_process_nonce": census_process_nonce,
        "control_authority": False,
    })


def publish_monitor_state(
    run_dir: Path, manifest_binding: dict[str, Any], *, sample_count: int,
    status: str, diagnostic: str | None = None,
) -> None:
    _write_state(run_dir / MONITOR_STATE_PATH, {
        "schema_version": 1, "role": "monitor", "phase": "observing",
        **manifest_binding, "pid": os.getpid(),
        "observed_monotonic_ns": time.monotonic_ns(),
        "sample_count": sample_count, "status": status,
        "diagnostic": diagnostic, "control_authority": False,
    })


class AdaptiveHybridSession:
    def __init__(self, *, run_dir: Path, device: str, physical: bool) -> None:
        self.run_dir = run_dir.resolve()
        self.device = device
        self.physical = physical
        self.binding = _binding(self.run_dir, self.run_dir / "run_manifest.json")
        self.processes: dict[str, subprocess.Popen[str]] = {}
        self.launched_ns: dict[str, int] = {}
        self.logs: list[Any] = []
        self.publication_error: OSError | None = None
        self.state: dict[str, Any] = {
            "schema_version": 1, **self.binding, "physical": physical,
            "device": device, "processes": {}, "phase": "prepared",
            "control_authority": False,
        }
        self._save()

    def _save(self) -> None:
        self.state["processes"] = {
            name: {"pid": process.pid, "exit": process.poll(),
                   "launched_monotonic_ns": self.launched_ns[name]}
            for name, process in self.processes.items()
        }
        _write_state(self.run_dir / SESSION_PATH, self.state)

    def _launch(self, role: str, command: list[str], log_path: Path) -> subprocess.Popen[str]:
        if role in self.processes:
            raise ValueError(f"session already launched {role}")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        output = log_path.open("x", encoding="utf-8")
        self.logs.append(output)
        self.launched_ns[role] = time.monotonic_ns()
        process = subprocess.Popen(command, cwd=ROOT, stdout=output, stderr=output,
                                   text=True, start_new_session=True)
        self.processes[role] = process
        try:
            self._save()
        except OSError as exc:
            # Return the actual owner before surfacing an artifact failure. The
            # caller must be able to retain a process that already started.
            self.publication_error = exc
        return process

    def launch_capture(self, command: list[str], log_path: Path) -> subprocess.Popen[str]:
        return self._launch("capture", command, log_path)

    def launch_support(
        self, *, supervisor_command: list[str], monitor_command: list[str],
        supervisor_log: Path, monitor_log: Path,
    ) -> tuple[subprocess.Popen[str], subprocess.Popen[str]]:
        supervisor = self._launch("supervisor", supervisor_command, supervisor_log)
        monitor = self._launch("monitor", monitor_command, monitor_log)
        return supervisor, monitor

    def _require_alive(self, roles: tuple[str, ...]) -> None:
        if self.publication_error is not None:
            raise OSError(f"session process receipt publication failed: {self.publication_error}")
        for role in roles:
            process = self.processes[role]
            if process.poll() is not None:
                raise RuntimeError(f"session {role} exited before readiness: {process.returncode}")

    def wait_capture_ready(self, timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        capture = self.processes["capture"]
        while time.monotonic() < deadline:
            self._require_alive(("capture",))
            if (_capture_state_ready(self.run_dir, capture.pid)
                and (self.run_dir / "control/normal_commands.fifo").is_fifo()
                and (self.run_dir / "control/emergency_abort.fifo").is_fifo()):
                if _serial_owner_pids(self.device) != {capture.pid}:
                    raise RuntimeError("capture is not the sole serial owner")
                self.state["phase"] = "capture_ready"
                self._save()
                return
            time.sleep(0.02)
        raise TimeoutError("session capture readiness deadline expired")

    def _receipt(self, role: str, path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads((self.run_dir / path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if not isinstance(value, dict):
            raise ValueError(f"session {role} receipt is malformed")
        observed = value.get("observed_monotonic_ns")
        if (value.get("schema_version") != 1 or value.get("role") != role
            or value.get("pid") != self.processes[role].pid
            or any(value.get(key) != item for key, item in self.binding.items())
            or type(observed) is not int or observed < self.launched_ns[role]
            or observed > time.monotonic_ns() or value.get("control_authority") is not False):
            raise ValueError(f"session {role} receipt differs from the launched process")
        return value

    def wait_support_ready(self, timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self._require_alive(("capture", "supervisor", "monitor"))
            supervisor = self._receipt("supervisor", SUPERVISOR_READY_PATH)
            monitor = self._receipt("monitor", MONITOR_STATE_PATH)
            if supervisor is not None and monitor is not None:
                if (supervisor.get("phase") != "census_pending"
                    or type(supervisor.get("census_process_nonce")) is not int
                    or supervisor["census_process_nonce"] <= 0
                    or monitor.get("phase") != "observing"
                    or type(monitor.get("sample_count")) is not int
                    or monitor["sample_count"] < 1):
                    raise ValueError("session readiness receipt has no initialized observer")
                if not (self.run_dir / "control/host_abort.fifo").is_fifo():
                    raise ValueError("supervisor receipt lacks its independent abort ingress")
                self.state["phase"] = "observing"
                self.state["readiness"] = {"supervisor": supervisor, "monitor": monitor}
                self._save()
                return
            time.sleep(0.02)
        raise TimeoutError("session support readiness deadline expired (initialized supervisor and first monitor sample)")

    def check_monitor(self) -> None:
        """Surface fresh observer findings without assigning it terminal authority."""
        monitor = self._receipt("monitor", MONITOR_STATE_PATH)
        if monitor is None:
            raise RuntimeError("session monitor receipt disappeared after readiness")
        if (time.monotonic_ns() - monitor["observed_monotonic_ns"] > 15_000_000_000
            or type(monitor.get("sample_count")) is not int or monitor["sample_count"] < 1):
            raise RuntimeError("session monitor stopped publishing fresh observations")
        monitor_status = monitor.get("status")
        if monitor_status == "review_required":
            detail = monitor.get("diagnostic")
            suffix = "" if not detail else f": {detail}"
            raise RuntimeError(f"session monitor requires review{suffix}")
        if monitor_status not in {
            "running", "awaiting_expected_evidence", "terminal"
        }:
            raise ValueError(
                f"session monitor status is not recognized: {monitor_status!r}"
            )

    def wait_for_terminal(self, timeout_s: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self.check_monitor()
            path = self.run_dir / "reports/adaptive_hybrid_supervisor_state.json"
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                state = {}
            if not isinstance(state, dict):
                raise ValueError("session supervisor state is malformed")
            terminal = state.get("terminal")
            if isinstance(terminal, dict):
                return terminal
            self._require_alive(("capture", "supervisor", "monitor"))
            time.sleep(0.2)
        raise TimeoutError("finite session supervisor terminal deadline expired")

    @staticmethod
    def _reap(process: subprocess.Popen[str], timeout_s: float) -> int:
        if process.poll() is None:
            process.terminate()
        try:
            return process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.wait(timeout=5.0)

    def close_capture_after_authorized_terminal(self, *, timeout_s: float) -> int:
        # The physical caller owns terminal/explicit-operator authorization.
        # No exception cleanup path calls this operation automatically.
        result = self._reap(self.processes["capture"], timeout_s)
        self.state["phase"] = "capture_closed"
        self._save()
        return result

    def close_after_capture_closed(self) -> dict[str, Any]:
        capture = self.processes.get("capture")
        if capture is not None and capture.poll() is None:
            raise RuntimeError("session closure refuses to tear down a live capture owner")
        monitor = self.processes.get("monitor")
        if monitor is not None and monitor.poll() is None:
            (self.run_dir / MONITOR_STOP_PATH).touch()
            try:
                monitor.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self._reap(monitor, 3.0)
        supervisor = self.processes.get("supervisor")
        if supervisor is not None:
            self._reap(supervisor, 5.0)
        self.state["phase"] = "closed"
        self._save()
        for output in self.logs:
            output.close()
        return self.state["processes"]

    def close_simulated(self) -> dict[str, Any]:
        canonical = os.path.realpath(self.device)
        if (self.physical or canonical != self.device
            or re.fullmatch(r"/dev/(?:pts/[0-9]+|ttys[0-9]+)", canonical) is None):
            raise RuntimeError("simulated cleanup refuses a physical or non-PTY session")
        capture = self.processes.get("capture")
        if capture is not None and capture.poll() is None:
            try:
                os.kill(capture.pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
            self._reap(capture, 3.0)
        return self.close_after_capture_closed()
