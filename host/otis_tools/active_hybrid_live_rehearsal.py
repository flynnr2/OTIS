"""Exercise the CX320 host process topology over a PTY without hardware I/O.

This rehearsal runs the real capture process and the real live-supervisor loop
with three distinct FIFOs, but binds them to a pseudo-terminal.  Long-duration
controller, response, degradation, and finalization boundaries are exercised
by the frozen accelerated rehearsal.  The receipt distinguishes those two
forms of coverage and makes no firmware, USB-device, DAC, plant, or physical
qualification claim.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import pty
import select
import signal
import stat
import subprocess
import sys
import time
from typing import Any, Callable

from .abort_transport import send_abort
from .active_hybrid_bundle import validate_bundle
from .active_hybrid_proposal import validate_proposal
from .active_hybrid_rehearsal import run as run_accelerated_rehearsal
from .capture_runtime_checks import _capture_state_ready, _serial_owner_pids
from .capture_segment_rotation import prepare_transition, request_rotation
from .run_paths import default_csv_files
from .serial_commands import send_timestamped_command_to_fifo


ROOT = Path(__file__).resolve().parents[2]
TOOL_ID = "cx320_active_hybrid_live_topology_rehearsal_v1"
REPORT_TYPE = "cx320_active_hybrid_live_topology_rehearsal_v1"
MODE = "cx320_accelerated_live_topology_rehearsal_pty"
LIVE_STAGE = "CX320_BOUNDED_ACTIVE_HYBRID_PHASE_FREQUENCY_LIVE"
PROGRAMME_ID = "CX320_BOUNDED_ACTIVE_HYBRID_PHASE_FREQUENCY_V1"
RUN_IDENTITY = "cx320_active_hybrid:3200001"
PROFILE_ID = "cx320_active_hybrid"
CAPABILITY = "cx320-active-hybrid-live-topology-rehearsal"
REHEARSAL_COVERAGE = (
    "capture_device_real_process",
    "pty_serial_carrier",
    "sole_serial_owner",
    "normal_command_fifo",
    "emergency_abort_fifo",
    "host_abort_fifo",
    "live_supervisor_process",
    "setup_propagation",
    "progressive_checkpoint",
    "conditional_release",
    "response_classification",
    "phase_only_degradation",
    "shared_fail_static_fault",
    "transport_obstruction",
    "terminal_abort_delivery_before_capture_close",
    "logical_evidence_rotation",
    "analysis_seal_registration",
)


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


def _canonical_sha256(value: dict[str, Any]) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        if os.write(descriptor, payload) != len(payload):
            raise OSError(f"short immutable JSON write: {path}")
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
        time.sleep(0.05)
    raise TimeoutError(f"timed out waiting for {description}")


def _read_until(master: int, expected: bytes, timeout_s: float = 10.0) -> bytes:
    deadline = time.monotonic() + timeout_s
    observed = b""
    while time.monotonic() < deadline:
        readable, _, _ = select.select([master], [], [], 0.1)
        if not readable:
            continue
        observed += os.read(master, 4096)
        if expected in observed:
            return observed
    raise TimeoutError(
        f"did not observe emulated firmware command {expected!r}: {observed!r}"
    )


def _binding_matches(binding: object) -> bool:
    if not isinstance(binding, dict):
        return False
    path = Path(str(binding.get("path", ""))).resolve()
    return (
        path.is_file()
        and binding.get("path") == str(path)
        and binding.get("sha256") == _sha256_file(path)
        and binding.get("size_bytes") == path.stat().st_size
    )


def _create_rehearsal_run_manifest(
    *,
    run_dir: Path,
    bundle_path: Path,
    bundle: dict[str, Any],
    proposal_path: Path,
    proposal: dict[str, Any],
    device: str,
) -> Path:
    files = [dict(entry) for entry in default_csv_files()]
    value: dict[str, Any] = {
        "schema_version": 1,
        "compatibility_floor": "CX319_EVIDENCE_EPOCH_1",
        "template": False,
        "run_id": run_dir.name,
        "created_utc": _utc_now(),
        "started_at_utc": _utc_now(),
        "stage": LIVE_STAGE,
        "mode": MODE,
        "programme_id": PROGRAMME_ID,
        "run_identity": RUN_IDENTITY,
        "profile_identity": PROFILE_ID,
        "board": "pty_no_physical_hardware",
        "capture_mode": "real_capture_device_process_over_pty",
        "qualification_evidence": False,
        "physical_actions_performed": 0,
        "actionable": False,
        "actuation_authorized": False,
        "authority_effective": False,
        "bundle": {
            "path": str(bundle_path),
            "sha256": _sha256_file(bundle_path),
            "size_bytes": bundle_path.stat().st_size,
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "proposal": {
            "path": str(proposal_path),
            "sha256": _sha256_file(proposal_path),
            "size_bytes": proposal_path.stat().st_size,
            "proposal_sha256": proposal["proposal_sha256"],
        },
        "firmware": bundle["firmware"],
        "policy": bundle["policy"],
        "host": {
            "serial_device": device,
            "baud": 115200,
            "sole_serial_owner": True,
            "serial_owner_count": 1,
            "tool_bindings": bundle["host_tools"],
            "fifos": {
                "normal_command": "control/normal_commands.fifo",
                "emergency_abort": "control/emergency_abort.fifo",
                "host_abort": "control/host_abort.fifo",
            },
        },
        "cx320": {
            "profile_id": PROFILE_ID,
            "run_identity": RUN_IDENTITY,
            "setup": {"code": 0xA83C},
            "automatic_control": {
                "maximum_total_applications": 4,
                "maximum_step_codes": 21,
                "maximum_cumulative_movement_codes": 84,
                "minimum_applied_cadence_s": 1800,
                "minimum_code": 0xA800,
                "maximum_code": 0xAB00,
            },
            "qualification": {
                "qualified_duration_s": 43_200,
                "absolute_wall_clock_limit_s": 57_600,
                "no_extension": True,
            },
        },
        "domains": [
            {"name": "rp2040_timer0", "nominal_hz": 16_000_000},
            {"name": "h1_cx317_ocxo_10mhz", "nominal_hz": 10_000_000},
        ],
        "channels": [
            {
                "channel_id": 1,
                "role": "authoritative_pps_reference",
                "record_family": "raw_events_v1",
            },
            {
                "channel_id": 2,
                "role": "pps_gated_oscillator_count",
                "record_family": "count_observations_v1",
            },
            {
                "channel_id": 3,
                "role": "independent_external_event_not_authority",
                "record_family": "raw_events_v1",
            },
        ],
        "contracts": {
            entry["contract"]: 2 if entry["contract"] == "estimates_v2" else 1
            for entry in files
        },
        "files": files,
        "expected_artifacts": [
            "raw/serial.log",
            "reports/capture_device_state.json",
            "reports/cx317_active_supervisor_state.json",
            "reports/cx317_active_supervisor_events.jsonl",
        ],
        "evidence_artifacts": [
            "raw/serial.log",
            "reports/capture_device_state.json",
            "reports/cx317_active_supervisor_state.json",
            "reports/cx317_active_supervisor_events.jsonl",
        ],
    }
    value["manifest_sha256"] = _canonical_sha256(value)
    path = run_dir / "run_manifest.json"
    _atomic_new_json(path, value)
    return path


def validate_rehearsal_run_manifest(path: Path) -> dict[str, Any]:
    """Validate the only manifest accepted by supervisor rehearsal mode."""

    path = path.resolve()
    value = _read_object(path)
    unsigned = {
        key: item for key, item in value.items() if key != "manifest_sha256"
    }
    bundle_binding = value.get("bundle", {})
    proposal_binding = value.get("proposal", {})
    host = value.get("host", {})
    cx320 = value.get("cx320", {})
    if not isinstance(host, dict) or not isinstance(cx320, dict):
        raise ValueError("CX320 rehearsal manifest host/programme is malformed")
    bundle_path = Path(str(bundle_binding.get("path", ""))).resolve()
    proposal_path = Path(str(proposal_binding.get("path", ""))).resolve()
    bundle = validate_bundle(bundle_path)
    proposal = validate_proposal(proposal_path)
    device = str(host.get("serial_device", ""))
    if (
        path != path.parent / "run_manifest.json"
        or value.get("manifest_sha256") != _canonical_sha256(unsigned)
        or value.get("mode") != MODE
        or value.get("stage") != LIVE_STAGE
        or value.get("programme_id") != PROGRAMME_ID
        or value.get("run_identity") != RUN_IDENTITY
        or value.get("profile_identity") != PROFILE_ID
        or value.get("qualification_evidence") is not False
        or value.get("physical_actions_performed") != 0
        or value.get("actionable") is not False
        or value.get("actuation_authorized") is not False
        or value.get("authority_effective") is not False
        or not device.startswith("/dev/pts/")
        or host.get("serial_owner_count") != 1
        or host.get("sole_serial_owner") is not True
        or len(set(host.get("fifos", {}).values())) != 3
        or bundle_binding.get("sha256") != _sha256_file(bundle_path)
        or bundle_binding.get("size_bytes") != bundle_path.stat().st_size
        or bundle_binding.get("bundle_sha256") != bundle["bundle_sha256"]
        or proposal_binding.get("sha256") != _sha256_file(proposal_path)
        or proposal_binding.get("size_bytes") != proposal_path.stat().st_size
        or proposal_binding.get("proposal_sha256") != proposal["proposal_sha256"]
        or proposal["exact_bundle"]["bundle_sha256"] != bundle["bundle_sha256"]
        or value.get("firmware") != bundle["firmware"]
        or value.get("policy") != bundle["policy"]
        or host.get("tool_bindings") != bundle["host_tools"]
        or cx320.get("profile_id") != PROFILE_ID
        or cx320.get("run_identity") != RUN_IDENTITY
        or cx320.get("setup", {}).get("code") != 0xA83C
    ):
        raise ValueError("CX320 rehearsal manifest identity or no-I/O boundary differs")
    if not all(_binding_matches(item) for item in bundle["host_tools"].values()):
        raise ValueError("CX320 rehearsal current host-tool binding differs")
    return value


def _run_real_process_topology(
    *,
    output_dir: Path,
    bundle_path: Path,
    bundle: dict[str, Any],
    proposal_path: Path,
    proposal: dict[str, Any],
) -> dict[str, Any]:
    run_dir = output_dir / "process_topology" / "run"
    transition_dir = output_dir / "process_topology" / "transition"
    carrier_dir = output_dir / "process_topology" / "carrier"
    run_dir.mkdir(parents=True)
    (run_dir / "reports").mkdir()
    master, slave = pty.openpty()
    device = os.ttyname(slave)
    os.close(slave)
    manifest_path = _create_rehearsal_run_manifest(
        run_dir=run_dir,
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
        device=device,
    )
    normal = run_dir / "control/normal_commands.fifo"
    emergency = run_dir / "control/emergency_abort.fifo"
    host_abort = run_dir / "control/host_abort.fifo"
    capture = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "host.otis_tools.capture_device",
            "--device",
            device,
            "--run-dir",
            str(run_dir),
            "--duration-s",
            "120",
            "--status-interval",
            "1",
            "--command-fifo",
            str(normal),
            "--emergency-command-fifo",
            str(emergency),
            "--write-timeout-s",
            "1",
            "--normal-command-max-age-s",
            "2",
            "--segment-control-dir",
            str(carrier_dir),
            "--segment-capability",
            CAPABILITY,
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    supervisor: subprocess.Popen[str] | None = None
    capture_output = ""
    supervisor_output = ""
    capture_stopped = False
    normal_fifo_queued = 0
    normal_fifo_saturated = False
    try:
        _wait_until(
            lambda: (
                capture.poll() is None
                and normal.is_fifo()
                and emergency.is_fifo()
                and _capture_state_ready(run_dir, capture.pid)
            ),
            15.0,
            "real capture process and PTY carrier",
        )
        owners_before = _serial_owner_pids(device)
        if owners_before != {capture.pid}:
            raise RuntimeError(
                f"capture is not sole PTY owner: {sorted(owners_before)}"
            )
        supervisor = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "host.otis_tools.active_hybrid_live_supervisor",
                "--manifest",
                str(manifest_path),
                "--run-dir",
                str(run_dir),
                "--command-fifo",
                str(normal),
                "--emergency-command-fifo",
                str(emergency),
                "--abort-fifo",
                str(host_abort),
                "--expected-build-identity",
                str(bundle["firmware"]["build_identity"]),
                "--duration-s",
                "60",
                "--rehearsal-manifest",
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _wait_until(
            lambda: (
                supervisor.poll() is None
                and host_abort.exists()
                and stat.S_ISFIFO(host_abort.stat().st_mode)
            ),
            15.0,
            "real live supervisor and host-abort FIFO",
        )
        initial_commands = _read_until(master, b"DAC?\n")
        os.kill(capture.pid, signal.SIGSTOP)
        capture_stopped = True
        for _ in range(100_000):
            try:
                send_timestamped_command_to_fifo(normal, "CONFIG?")
                normal_fifo_queued += 1
            except BlockingIOError:
                normal_fifo_saturated = True
                break
        if not normal_fifo_saturated:
            raise RuntimeError("CX320 rehearsal normal FIFO did not saturate")
        send_abort(host_abort)
        time.sleep(0.25)
        os.kill(capture.pid, signal.SIGCONT)
        capture_stopped = False
        observed_commands = _read_until(master, b"ACTIVE ABORT\n")
        _wait_until(
            lambda: int(
                _read_object(run_dir / "reports/capture_device_state.json").get(
                    "emergency_aborts_sent", 0
                )
            )
            == 1,
            10.0,
            "priority abort delivery through sole owner",
        )
        supervisor_output, _ = supervisor.communicate(timeout=15)
        if supervisor.returncode != 3:
            raise RuntimeError(
                "live supervisor rehearsal did not reach independent-host-abort "
                f"terminal: exit={supervisor.returncode}; {supervisor_output[-2000:]}"
            )
        prepare_transition(run_dir / "run_manifest.json", transition_dir)
        rotation = request_rotation(
            control_dir=carrier_dir,
            capability=CAPABILITY,
            to_run=transition_dir,
            mode="transition",
            operation_id="cx320-live-topology-rehearsal-rotation",
        )
        if rotation.get("serial_reopened") is not False:
            raise RuntimeError("CX320 rehearsal logical rotation reopened serial")
        owners_after = _serial_owner_pids(device)
        if owners_after != {capture.pid}:
            raise RuntimeError("CX320 rehearsal lost sole ownership after rotation")
    finally:
        if capture_stopped:
            os.kill(capture.pid, signal.SIGCONT)
        if supervisor is not None and supervisor.poll() is None:
            supervisor.terminate()
            try:
                supervisor_output, _ = supervisor.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                supervisor.kill()
                supervisor_output, _ = supervisor.communicate(timeout=5)
        if capture.poll() is None:
            capture.send_signal(signal.SIGINT)
        try:
            capture_output, _ = capture.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            capture.kill()
            capture_output, _ = capture.communicate(timeout=5)
        os.close(master)
    if capture.returncode != 0:
        raise RuntimeError(
            f"capture process rehearsal failed: {capture_output[-4000:]}"
        )
    state = _read_object(run_dir / "reports/capture_device_state.json")
    terminal = _read_object(run_dir / "reports/cx317_active_supervisor_state.json")
    return {
        "capture_pid": capture.pid,
        "supervisor_pid": None if supervisor is None else supervisor.pid,
        "device": device,
        "owners_before": sorted(owners_before),
        "owners_after_rotation": sorted(owners_after),
        "observed_command_bytes_sha256": sha256(observed_commands).hexdigest(),
        "initial_command_bytes_sha256": sha256(initial_commands).hexdigest(),
        "config_query_observed": b"CONFIG?\n" in initial_commands,
        "normal_fifo_queued_before_saturation": normal_fifo_queued,
        "normal_fifo_saturated": normal_fifo_saturated,
        "priority_abort_observed": b"ACTIVE ABORT\n" in observed_commands,
        "capture_emergency_aborts_sent": state.get("emergency_aborts_sent"),
        "supervisor_terminal": terminal.get("terminal"),
        "rotation": rotation,
        "capture_output_sha256": sha256(capture_output.encode()).hexdigest(),
        "supervisor_output_sha256": sha256(supervisor_output.encode()).hexdigest(),
    }


def run(
    *, bundle_path: Path, proposal_path: Path, output_dir: Path
) -> dict[str, Any]:
    bundle_path = bundle_path.resolve()
    proposal_path = proposal_path.resolve()
    bundle = validate_bundle(bundle_path)
    proposal = validate_proposal(proposal_path)
    if proposal["exact_bundle"]["bundle_sha256"] != bundle["bundle_sha256"]:
        raise ValueError("CX320 rehearsal proposal and bundle differ")
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"CX320 live rehearsal output is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    accelerated = run_accelerated_rehearsal(
        bundle_path=bundle_path,
        proposal_path=proposal_path,
        output_dir=output_dir / "accelerated_boundaries",
    )
    topology = _run_real_process_topology(
        output_dir=output_dir,
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
    )
    coverage = {name: True for name in REHEARSAL_COVERAGE}
    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "report_type": REPORT_TYPE,
        "tool": TOOL_ID,
        "tool_sha256": _sha256_file(Path(__file__)),
        "created_utc": _utc_now(),
        "status": "passed",
        "bundle_sha256": bundle["bundle_sha256"],
        "proposal_sha256": proposal["proposal_sha256"],
        "physical_actions_performed": 0,
        "qualification_evidence": False,
        "coverage": coverage,
        "tool_bindings": bundle["host_tools"],
        "real_process_topology": topology,
        "accelerated_boundary_result": {
            "status": accelerated["status"],
            "seal_sha256": accelerated["seal_sha256"],
            "evidence_content_sha256": accelerated["evidence_content_sha256"],
            "registration_valid": accelerated["registration_valid"],
        },
        "coverage_provenance": {
            "real_process": [
                "capture_device_real_process",
                "pty_serial_carrier",
                "sole_serial_owner",
                "normal_command_fifo",
                "emergency_abort_fifo",
                "host_abort_fifo",
                "live_supervisor_process",
                "terminal_abort_delivery_before_capture_close",
                "logical_evidence_rotation",
            ],
            "accelerated_deterministic": [
                "setup_propagation",
                "progressive_checkpoint",
                "conditional_release",
                "response_classification",
                "phase_only_degradation",
                "shared_fail_static_fault",
                "transport_obstruction",
                "analysis_seal_registration",
            ],
        },
        "unexercised_physical_boundaries": [
            "RP2040 USB CDC and cross-core runtime",
            "AD5693R I2C write and CX317 plant response",
            "physical D14 PPS and D8 oscillator capture",
        ],
    }
    report = {
        **unsigned,
        "rehearsal_sha256": _canonical_sha256(unsigned),
    }
    _atomic_new_json(
        output_dir / "cx320_active_hybrid_live_topology_rehearsal_v1.json",
        report,
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run(
            bundle_path=args.bundle,
            proposal_path=args.proposal,
            output_dir=args.output_dir,
        )
    except (
        FileExistsError,
        FileNotFoundError,
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
