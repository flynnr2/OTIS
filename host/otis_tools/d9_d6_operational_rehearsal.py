"""Run the D9/D6 readiness operational path over deterministic pseudo-I/O.

This is deliberately a no-hardware programme tool.  Its serial endpoint is a
PTY, physical authority is always false, and it accepts no DAC, GNSS, arm, or
output-selection command.  The capture carrier is nevertheless the production
``capture_device`` process, so CSV splitting, command ingress, abort delivery,
same-owner rotation, evidence snapshotting and temporary registration exercise
the real host path.

The PTY firmware transcript is a contract fixture, not a claim about board
propagation or waveform quality.  In particular it cannot establish voltage,
edge shape, physical D8-to-D9 forwarding, or D6 loopback behaviour.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import pty
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable

from .capture_runtime_checks import _markers, _serial_owner_pids
from .capture_serial import CsvRecordSplitter
from .capture_segment_rotation import prepare_transition, request_rotation
from .contracts import CONTRACT_FIELDS
from .d9_d6_candidate_bundle import validate_rehearsal_input
from .evidence import create_evidence_snapshot
from .evidence_index import register_package, validate_index
from .run_paths import default_csv_files
from .serial_commands import send_command_to_fifo, send_timestamped_command_to_fifo


ROOT = Path(__file__).resolve().parents[2]
TOOL_ID = "d9_d6_readiness_operational_rehearsal_v1"
CAPABILITY = "d9-d6-readiness-operational-rehearsal"
RESULT_PATH = Path("operational_rehearsal_result_v1.json")
ANALYZER_MODULE = "host.otis_tools.d9_d6_readiness_analyze"
CONTRACT_SHA256 = "a6a08d14a03a87b5e0308880c64799baf2e7afecc23cad22d1532f297960de4d"
PROFILE_BY_STRATUM = {
    "baseline": "d9_disabled_no_control_baseline",
    "output": "d9_forwarded_output_no_control",
    "monitor": "d9_d6_forwarded_output_no_control",
}

REHEARSAL_COVERAGE = (
    "production_capture_device_process",
    "pty_serial_carrier",
    "sole_serial_owner",
    "normal_and_priority_command_fifos",
    "repeated_configuration_status_queries",
    "d9_configuration_readback_and_pre_valid_failure_transcript",
    "d8_and_d14_state_transitions",
    "d6_local_absent_stall_overflow_contradiction_transcript",
    "frequency_only_no_hybrid_transcript",
    "transport_obstruction_and_priority_abort",
    "same_owner_logical_rotation",
    "analyzer_seal_snapshot_and_temporary_registration",
    "raw_chronology_replay",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to replace rehearsal artifact: {path}")
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _wait_until(predicate: Callable[[], bool], timeout_s: float, name: str) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.025)
    raise TimeoutError(f"timed out waiting for {name}")


def _read_until(master: int, expected: bytes, timeout_s: float = 5.0) -> bytes:
    deadline = time.monotonic() + timeout_s
    observed = b""
    while time.monotonic() < deadline:
        readable, _, _ = select.select([master], [], [], 0.05)
        if readable:
            observed += os.read(master, 4096)
            if expected in observed:
                return observed
    raise TimeoutError(f"PTY did not receive {expected!r}; observed={observed!r}")


def _write_all(master: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(master, remaining)
        if written <= 0:
            raise OSError("short PTY write")
        remaining = remaining[written:]


def _status(sequence: int, component: str, key: str, value: str, *, flags: int = 0) -> str:
    return (
        f"STS,1,{sequence},{sequence * 16_000_000},rp2040_timer0,"
        f"{component},{key},{value},INFO,{flags}"
    )


def _monitor_snapshot(
    sequence: int, down_counter: int, reference_sequence: int, *, status: int = 0
) -> str:
    return (
        f"MNS,1,1,1,{sequence},{down_counter},{reference_sequence},"
        f"{reference_sequence * 16_000_000},{status},"
        "pio_wait_cumulative_snapshot_cpu_v1,3"
    )


def _authoritative_snapshot(sequence: int, down_counter: int) -> str:
    return (
        f"SNP,1,1,{sequence},{down_counter},{sequence},"
        f"{sequence * 16_000_000},0,pio_wait_cumulative_snapshot_dma_v1"
    )


def _count(sequence: int) -> str:
    return (
        f"CNT,1,{sequence},2,{(sequence - 1) * 16_000_000},"
        f"{sequence * 16_000_000},rp2040_timer0,10000000,R,"
        "h1_cx317_ocxo_10mhz,0"
    )


def deterministic_wire_transcript(
    *, stratum: str = "monitor", include_failure: bool = True
) -> bytes:
    """Return the fixture chronology consumed by the real capture carrier.

    Every monitor fault is followed by another clean D14/D8 observation.  That
    makes the intended containment property inspectable in the raw chronology
    rather than merely asserted by a host-side boolean.
    """

    if stratum not in PROFILE_BY_STRATUM:
        raise ValueError(f"unknown D9/D6 rehearsal stratum: {stratum}")
    lines: list[str] = [_status(1, "boot_capabilities", "selected_profile", PROFILE_BY_STRATUM[stratum])]
    sequence = 1
    if stratum == "baseline":
        lines.append(_status(2, "forwarded_clock_output", "state", "disabled"))
        lines.extend(
            _authoritative_snapshot(index, 0xFFFFFFFF - index * 10_000_000)
            for index in range(3)
        )
        return ("\r\n".join(lines) + "\r\n").encode("ascii")
    for key, value in (
        ("contract_id", "OTIS_D9_D6_READINESS_CONTRACT_V1"),
        ("contract_sha256", CONTRACT_SHA256),
        ("state", "configured_10mhz_forwarded_unqualified"),
        ("source", "D8_GPIO20_GPIN0"),
        ("destination", "D9_GPIO21_GPOUT0"),
        ("integer_divider", "1"),
        ("fractional_divider", "0"),
        ("applied_integer_divider", "1"),
        ("applied_fractional_divider", "0"),
        ("applied_auxsrc", "1"),
        ("source_gpio_function", "8"),
        ("destination_gpio_function", "8"),
        ("inversion", "0"),
        ("drive_strength_ma", "2"),
        ("slew_rate", "slow"),
        ("readback_valid", "true"),
        ("nominal_frequency_hz", "10000000"),
        ("first_valid_ticks", "16000000"),
    ):
        lines.append(_status(sequence, "forwarded_clock_output", key, value))
        sequence += 1
    lines.extend((_status(sequence, "controller", "mode", "frequency_only"), _status(sequence + 1, "controller", "hybrid_authority", "false")))
    sequence += 2
    # First snapshot follows the two repeated status/query responses.
    for index in range(3):
        counter = 0xFFFFFFFF - index * 10_000_000
        lines.extend((_authoritative_snapshot(index, counter), _count(index + 1)))
        if stratum == "monitor":
            lines.append(_monitor_snapshot(index, counter, index))
    if include_failure:
        # Pre-valid configuration fault is distinct from the later valid state.
        lines.append(_status(sequence, "forwarded_clock_output", "state", "invalid_or_transitioning")); sequence += 1
        lines.append(_status(sequence, "forwarded_clock_output", "state", "configured_10mhz_forwarded_unqualified")); sequence += 1
        # D8/D14 transitions; monitor faults remain explicitly local.
        lines.append(_status(sequence, "d8_capture", "state", "source_missing")); sequence += 1
        lines.append(_status(sequence, "d8_capture", "state", "healthy_requalified")); sequence += 1
        lines.append(_status(sequence, "d14_reference", "state", "metadata_degraded")); sequence += 1
        lines.append(_status(sequence, "d14_reference", "state", "healthy_requalified")); sequence += 1
        for state, status in (
            ("monitor_absent", 2),
            ("monitor_stalled", 4),
            ("monitor_overflow", 8),
            ("monitor_contradictory", 16),
        ):
            if stratum == "monitor":
                lines.append(_status(sequence, "forwarded_clock_monitor", "state", state, flags=status)); sequence += 1
    lines.append(_status(sequence, "controller", "decision", "frequency_only_hold_no_hybrid"))
    return ("\r\n".join(lines) + "\r\n").encode("ascii")


def _create_manifest(
    run_dir: Path, device: str, bundle_path: Path, candidate: dict[str, Any],
    firmware: dict[str, Any], *, stratum: str = "monitor"
) -> Path:
    files = [
        entry
        for entry in default_csv_files()
        if entry["contract"]
        in {
            "count_observations_v1",
            "pps_snapshots_v1",
            "forwarded_monitor_snapshots_v1",
            "health_v1",
        }
    ]
    for entry in files:
        entry["optional"] = False
    value: dict[str, Any] = {
        "schema_version": 1,
        "template": False,
        "run_id": run_dir.name,
        "created_utc": _utc_now(),
        "started_at_utc": _utc_now(),
        "stage": "D9_D6_READINESS_OPERATIONAL_REHEARSAL",
        "mode": "d9_d6_no_hardware_pty_rehearsal",
        "qualification_evidence": False,
        "physical_actions_performed": 0,
        "actionable": False,
        "actuation_authorized": False,
        "authority_effective": False,
        "board": "pty_no_physical_hardware",
        "firmware": firmware,
        "d9_d6_readiness": {
            "profile": PROFILE_BY_STRATUM[stratum],
            "physical_authority": False,
            "contract": {
                "contract_id": "OTIS_D9_D6_READINESS_CONTRACT_V1",
                "contract_semantic_sha256": CONTRACT_SHA256,
            },
        },
        "bundle": {
            "path": str(bundle_path.resolve()),
            "file_sha256": _sha256_file(bundle_path),
            "rehearsal_input_id": candidate["input_id"],
        },
        "host": {
            "serial_device": device,
            "baud": 115200,
            "sole_serial_owner": True,
            "capture_tool": "host.otis_tools.capture_device",
        },
        "domains": [
            {"name": "rp2040_timer0", "nominal_hz": 16_000_000},
            {"name": "h1_cx317_ocxo_10mhz", "nominal_hz": 10_000_000},
            {"name": "d9_forwarded_10mhz", "nominal_hz": 10_000_000},
        ],
        "channels": [
            {"channel_id": 1, "role": "authoritative_d14_reference"},
            {"channel_id": 2, "role": "authoritative_d8_count"},
            {"channel_id": 3, "role": "diagnostic_d6_forwarded_d9_monitor", "zero_authority": True},
        ],
        "contracts": {entry["contract"]: 1 for entry in files},
        "files": files,
        "evidence_artifacts": [
            "reports/d9_d6_operational_trace_v1.json",
            "reports/d9_d6_readiness_analysis_v1.json",
        ],
    }
    path = run_dir / "run_manifest.json"
    _write_new_json(path, value)
    return path


def _create_fixture_stratum(
    run_dir: Path, *, stratum: str, bundle_path: Path, candidate: dict[str, Any],
    firmware: dict[str, Any]
) -> None:
    """Create a separate deterministic profile stratum without serial I/O."""

    run_dir.mkdir(parents=True, exist_ok=False)
    _create_manifest(run_dir, "/dev/pts/fixture", bundle_path, candidate, firmware, stratum=stratum)
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    targets = {
        entry["contract"]: run_dir / entry["path"]
        for entry in manifest["files"]
    }
    with CsvRecordSplitter(targets) as splitter:
        for line in deterministic_wire_transcript(stratum=stratum).decode("ascii").splitlines():
            splitter.process_line(line)
    raw = run_dir / "raw/serial.log"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(deterministic_wire_transcript(stratum=stratum))
    _write_new_json(
        run_dir / "reports/capture_device_state.json",
        {"capture_active": False, "serial_open": False, "parser_errors": 0, "fixture": True},
    )


def _load_analyzer() -> Any:
    module = importlib.import_module(ANALYZER_MODULE)
    missing = [name for name in ("analyze", "seal", "report_markdown") if not callable(getattr(module, name, None))]
    if missing:
        raise RuntimeError(f"{ANALYZER_MODULE} lacks required API: {', '.join(missing)}")
    return module


def _monitor_firmware_binding(candidate: dict[str, Any]) -> dict[str, Any]:
    """Derive the one rehearsal firmware identity from the frozen profile."""

    profile = next(
        (
            item
            for item in candidate["firmware_profiles"]
            if item["profile_id"] == PROFILE_BY_STRATUM["monitor"]
        ),
        None,
    )
    if not isinstance(profile, dict):
        raise ValueError("candidate has no exact D9+D6 monitor firmware profile")
    source_revision = candidate["source_state"]["git_revision"]
    build_manifest = profile["build_manifest"]
    return {
        "source_revision": source_revision,
        "profile_id": profile["profile_id"],
        "build_identity": build_manifest["sha256"],
        "configuration": profile["configuration"],
        "build_manifest": build_manifest,
        "elf": profile["elf"],
        "uf2": profile["uf2"],
        "binary_contract": profile["binary_contract"],
    }


def _require_pyserial() -> None:
    try:
        import serial  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "pyserial is required for the real capture_device PTY rehearsal; install the declared project dependency before retrying"
        ) from exc


def _capture_ready(run_dir: Path, pid: int, normal: Path, emergency: Path) -> bool:
    try:
        state = json.loads((run_dir / "reports/capture_device_state.json").read_text())
        return (
            state.get("pid") == pid
            and state.get("capture_active") is True
            and state.get("serial_open") is True
            and normal.exists()
            and emergency.exists()
            and stat.S_ISFIFO(normal.stat().st_mode)
            and stat.S_ISFIFO(emergency.stat().st_mode)
        )
    except (OSError, json.JSONDecodeError):
        return False


def _replay_chronology(run_dir: Path) -> dict[str, Any]:
    health = list(csv.DictReader((run_dir / "csv/health.csv").open(newline="", encoding="utf-8")))
    output = [row for row in health if row["component"] == "forwarded_clock_output"]
    monitor = [row for row in health if row["component"] == "forwarded_clock_monitor"]
    authoritative = (run_dir / "csv/count_observations.csv").read_text(encoding="utf-8").count("\n") - 1
    return {
        "output_readback_before_first_snapshot": any(row["status_key"] == "readback_valid" and row["status_value"] == "true" for row in output),
        "pre_valid_fault_retained": any(row["status_value"] == "invalid_or_transitioning" for row in output),
        "d6_local_faults_retained": sorted(
            {row["status_value"] for row in monitor}
        ),
        "authoritative_d8_count_rows": authoritative,
        "no_hybrid_authority": any(row["status_key"] == "hybrid_authority" and row["status_value"] == "false" for row in health),
    }


def run(*, bundle_path: Path, output_dir: Path) -> dict[str, Any]:
    """Run the no-hardware operational topology and return a sealed receipt."""

    _require_pyserial()
    analyzer = _load_analyzer()
    bundle_path = bundle_path.resolve()
    raw_candidate = json.loads(bundle_path.read_text(encoding="utf-8"))
    candidate = validate_rehearsal_input(raw_candidate)
    firmware = _monitor_firmware_binding(candidate)
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError("D9/D6 rehearsal output directory must be empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    strata_root = output_dir / "strata"
    strata_root.mkdir()
    _create_fixture_stratum(
        strata_root / "baseline", stratum="baseline", bundle_path=bundle_path, candidate=candidate, firmware=firmware
    )
    _create_fixture_stratum(
        strata_root / "output", stratum="output", bundle_path=bundle_path, candidate=candidate, firmware=firmware
    )
    run_dir = strata_root / "monitor"
    run_dir.mkdir()
    transition_dir = output_dir / "transition"
    carrier_dir = output_dir / "carrier"
    master, slave = pty.openpty()
    device = os.ttyname(slave)
    os.close(slave)
    normal = run_dir / "control/normal_commands.fifo"
    emergency = run_dir / "control/emergency_abort.fifo"
    manifest_path = _create_manifest(run_dir, device, bundle_path, candidate, firmware, stratum="monitor")
    capture = subprocess.Popen(
        [
            sys.executable, "-m", "host.otis_tools.capture_device",
            "--device", device, "--baud", "115200", "--run-dir", str(run_dir),
            "--duration-s", "30", "--status-interval", "0.1",
            "--command-fifo", str(normal), "--emergency-command-fifo", str(emergency),
            "--normal-command-max-age-s", "2", "--segment-control-dir", str(carrier_dir),
            "--segment-capability", CAPABILITY,
        ], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    capture_stopped = False
    transcript = b""
    try:
        _wait_until(lambda: _capture_ready(run_dir, capture.pid, normal, emergency), 10, "capture carrier")
        owners = _serial_owner_pids(device)
        if owners != {capture.pid}:
            raise RuntimeError(f"capture carrier is not sole PTY owner: {sorted(owners)}")
        # This is the real normal command ingress: repeated status queries must
        # arrive before the first dependent fixture snapshot is emitted.
        send_timestamped_command_to_fifo(normal, "CONFIG?")
        send_timestamped_command_to_fifo(normal, "CONFIG?")
        commands = _read_until(master, b"CONFIG?\n")
        _write_all(master, deterministic_wire_transcript(stratum="monitor"))
        _wait_until(lambda: (run_dir / "csv/forwarded_monitor_snapshots.csv").exists() and (run_dir / "csv/forwarded_monitor_snapshots.csv").read_text(encoding="utf-8").count("\n") >= 2, 5, "first D6 snapshot")
        # Obstruct normal ingress, then demonstrate that priority abort is
        # accepted and recorded by the sole carrier before it is stopped.
        os.kill(capture.pid, signal.SIGSTOP); capture_stopped = True
        saturated = False
        for _ in range(100_000):
            try:
                send_timestamped_command_to_fifo(normal, "CONFIG?")
            except BlockingIOError:
                saturated = True
                break
        if not saturated:
            raise RuntimeError("normal command FIFO did not saturate")
        send_command_to_fifo(emergency, "ACTIVE ABORT")
        os.kill(capture.pid, signal.SIGCONT); capture_stopped = False
        transcript += _read_until(master, b"ACTIVE ABORT\n")
        _wait_until(lambda: any(row.get("event") == "emergency_abort_sent" for row in _markers(run_dir / "raw/serial.log")), 5, "priority abort evidence")
        prepare_transition(manifest_path, transition_dir)
        rotation = request_rotation(control_dir=carrier_dir, capability=CAPABILITY, to_run=transition_dir, mode="transition", operation_id="d9-d6-readiness-rehearsal-rotation")
        if rotation.get("serial_reopened") is not False or _serial_owner_pids(device) != {capture.pid}:
            raise RuntimeError("same-owner rotation did not retain the sole carrier")
    finally:
        if capture_stopped:
            os.kill(capture.pid, signal.SIGCONT)
        if capture.poll() is None:
            capture.send_signal(signal.SIGINT)
        try:
            capture_output, _ = capture.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            capture.kill(); capture_output, _ = capture.communicate(timeout=5)
        os.close(master)
    if capture.returncode != 0:
        raise RuntimeError(f"capture carrier failed: {capture_output[-2000:]}")
    chronology = _replay_chronology(run_dir)
    trace = {
        "schema_version": 1, "tool": TOOL_ID, "created_utc": _utc_now(),
        "qualification_evidence": False, "physical_actions_performed": 0,
        "rehearsal_coverage": list(REHEARSAL_COVERAGE), "command_bytes_sha256": sha256(commands + transcript).hexdigest(),
        "chronology": chronology,
        "real_boundaries": ["capture_device_process", "PTY_carrier", "FIFO_command_ingress", "priority_abort_delivery", "same_PID_rotation", "evidence_snapshot", "temporary_registration"],
        "fixture_boundaries": ["firmware_status_records", "D8_D14_transitions", "D6_fault_records", "frequency_only_controller_decision"],
        "not_proven": ["physical_D8_to_D9_forwarding", "D9_voltage_waveform_load_or_jitter", "physical_D6_loopback", "board_cross_core_timing", "DAC_or_VCOCXO_response"],
    }
    _write_new_json(output_dir / "reports/d9_d6_operational_trace_v1.json", trace)
    # The root is the candidate package; its three child runs remain distinct
    # profile strata and are never collapsed into a before/after comparison.
    _write_new_json(
        output_dir / "run_manifest.json",
        {
            "schema_version": 1, "compatibility_floor": "CX319_EVIDENCE_EPOCH_1",
            "template": False, "run_id": output_dir.name,
            "created_utc": _utc_now(), "stage": "D9_D6_READINESS_OPERATIONAL_REHEARSAL",
            "cx319": {"profile_id": "d9_d6_forwarded_output_no_control"},
            "qualification_evidence": False, "physical_actions_performed": 0,
            "actionable": False, "actuation_authorized": False,
            "files": [{"path": "csv/health.csv", "contract": "health_v1"}],
            "evidence_artifacts": [
                "reports/d9_d6_operational_trace_v1.json",
                "reports/d9_d6_readiness_analysis_v1.json",
                "reports/D9_D6_READINESS.md",
                "reports/d9_d6_readiness_seal_v1.json",
            ],
            "rehearsal_input": {
                "path": str(bundle_path), "input_id": candidate["input_id"]
            },
        },
    )
    root_health = output_dir / "csv/health.csv"
    root_health.parent.mkdir(parents=True, exist_ok=True)
    with root_health.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CONTRACT_FIELDS["health_v1"])
        writer.writeheader()
        writer.writerow(
            {
                "record_type": "STS", "schema_version": "1", "status_seq": "1",
                "timestamp_ticks": "0", "status_domain": "rp2040_timer0",
                "component": "d9_d6_operational_rehearsal", "status_key": "state",
                "status_value": "complete_no_hardware", "severity": "INFO", "flags": "0",
            }
        )
    analysis = analyzer.analyze(output_dir)
    if analysis.get("terminals", {}).get("programme") != (
        "d9_d6_candidate_bundle_ready_for_physical_authority"
    ):
        raise RuntimeError("D9/D6 rehearsal analyzer did not reach readiness terminal")
    if not all(
        (
            chronology["output_readback_before_first_snapshot"],
            chronology["pre_valid_fault_retained"],
            chronology["no_hybrid_authority"],
            chronology["authoritative_d8_count_rows"] > 0,
        )
    ):
        raise RuntimeError("D9/D6 chronology did not cover its required host invariants")
    seal = analyzer.seal(output_dir, analysis)
    (output_dir / "COMPLETE").touch(exist_ok=False)
    create_evidence_snapshot(output_dir)
    with tempfile.TemporaryDirectory(prefix="otis-d9-d6-registration-") as temporary:
        index_path = Path(temporary) / "evidence_index_v1.json"
        registration = register_package(index_path=index_path, package_path=output_dir, source_revision=str(firmware["source_revision"]), build_identity=str(firmware["build_identity"]), profile_identity=str(firmware["profile_id"]), attempt_classification="successful_rehearsal", result_or_failure_reason="D9/D6 no-hardware operational path passed", analyzer_identity=_sha256_file(Path(analyzer.__file__)))
        index_validation = validate_index(index_path)
    seal_path = output_dir / getattr(analyzer, "SEAL_PATH", Path("reports/d9_d6_readiness_seal_v1.json"))
    result = {"status": "passed", "tool": TOOL_ID, "input_id": candidate["input_id"], "seal_sha256": _sha256_file(seal_path), "registered_content_sha256": registration["content_sha256"], "registration_valid": index_validation["valid"], "qualification_evidence": False, "physical_actions_performed": 0, "output_dir": str(output_dir), "chronology": chronology}
    _write_new_json(output_dir / RESULT_PATH, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(run(bundle_path=args.bundle, output_dir=args.output_dir), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
