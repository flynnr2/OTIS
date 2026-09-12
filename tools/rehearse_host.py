"""Run one nonphysical OTIS rehearsal through the production live owner."""

from __future__ import annotations

import argparse
import json
import os
import pty
import shutil
import threading
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from host.otis_tools.adaptive_hybrid_analyze import analyze
from host.otis_tools.adaptive_hybrid_contract import ADAPTIVE_HYBRID_PROGRAMME
from host.otis_tools.evidence_package import ANALYSIS_REPORT
from host.otis_tools.live_run import run_experiment
from host.otis_tools.offline import finish_run
from host.otis_tools.run_spec import (
    REHEARSAL_RECEIPT_CONTRACT,
    _validate_rehearsal_receipt,
    create_run_record,
    load_run_spec,
    required_rehearsal_boundaries,
)
from host.otis_tools.serial_commands import timestamped_command_line
from tools.otis_rehearsal_device import DeterministicPtyInstrument


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _capture_command(device: str, run_dir: Path) -> list[str]:
    return [
        os.environ.get("PYTHON", os.sys.executable), "-m", "host.otis_tools.capture_device",
        "--device", device, "--baud", "115200", "--run-dir", str(run_dir),
        "--status-interval", "5", "--command-fifo", str(run_dir / "control/normal_commands.fifo"),
        "--emergency-command-fifo", str(run_dir / "control/emergency_abort.fifo"),
        "--write-timeout-s", "1", "--normal-command-max-age-s", "2",
    ]


def _exercise_normal_transport(path: Path, raw_path: Path) -> tuple[int, dict[str, object]]:
    """Prove stale normal rejection and actual normal-writer backpressure."""
    stale = (timestamped_command_line("ACTIVE?", created_monotonic_ns=time.monotonic_ns() - 5_000_000_000) + "\n").encode("ascii")
    descriptor = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
    try:
        os.write(descriptor, stale)
    finally:
        os.close(descriptor)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if raw_path.is_file() and '"event": "host_command_rejected"' in raw_path.read_text(encoding="utf-8", errors="replace"):
            break
        time.sleep(0.01)
    else:
        raise TimeoutError("capture did not reject the stale normal command")
    descriptor = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
    payload = stale * 1024
    attempted = len(payload)
    written_total = 0
    blocked_at: int | None = None
    while payload:
        try:
            written = os.write(descriptor, payload)
            if written <= 0:
                raise RuntimeError("normal FIFO write made no progress")
            written_total += written
            payload = payload[written:]
        except BlockingIOError:
            blocked_at = time.monotonic_ns()
            break
    if blocked_at is None:
        os.close(descriptor)
        raise RuntimeError("normal FIFO did not exert bounded writer backpressure")
    return descriptor, {
        "schema_version": 1,
        "contract": "otis_rehearsal_normal_transport_obstruction_v1",
        "stale_rejection_raw_marker": True,
        "normal_writer_blocked": True,
        "attempted_bytes": attempted,
        "written_bytes": written_total,
        "blocked_at_monotonic_ns": blocked_at,
    }


def _write_normal_transport_report(run_dir: Path, report: Mapping[str, object]) -> Path:
    """Retain host-observed normal FIFO backpressure without altering raw capture."""
    path = run_dir / "reports/rehearsal_normal_transport_obstruction_v1.json"
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = dict(report)
    document["report_sha256"] = sha256(_canonical(document)).hexdigest()
    with path.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return path


def _normal_transport_obstruction_proved(run_dir: Path, raw: str) -> bool:
    path = run_dir / "reports/rehearsal_normal_transport_obstruction_v1.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    unsigned = {key: value for key, value in report.items() if key != "report_sha256"}
    return (
        report.get("schema_version") == 1
        and report.get("contract") == "otis_rehearsal_normal_transport_obstruction_v1"
        and report.get("report_sha256") == sha256(_canonical(unsigned)).hexdigest()
        and report.get("stale_rejection_raw_marker") is True
        and report.get("normal_writer_blocked") is True
        and report.get("writer_held_through_abort_submission") is True
        and isinstance(report.get("attempted_bytes"), int)
        and isinstance(report.get("written_bytes"), int)
        and 0 < report["written_bytes"] < report["attempted_bytes"]
        and isinstance(report.get("blocked_at_monotonic_ns"), int)
        and isinstance(report.get("abort_submitted_monotonic_ns"), int)
        and isinstance(report.get("writer_closed_monotonic_ns"), int)
        and report["blocked_at_monotonic_ns"] <= report["abort_submitted_monotonic_ns"] <= report["writer_closed_monotonic_ns"]
        and '"event": "host_command_rejected"' in raw
        and "normal command timestamp is stale" in raw
    )


def _owner_events(run_dir: Path) -> list[dict[str, object]]:
    path = run_dir / "reports/adaptive_hybrid_supervisor_events.jsonl"
    if not path.is_file():
        return []
    events: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _owner_startup_census_admitted(run_dir: Path) -> bool:
    return any(
        event.get("event") == "adaptive_hybrid_regulation_startup_census_established"
        and event.get("authority_admitted") is True
        for event in _owner_events(run_dir)
    )


def _owner_startup_precedes_authority(run_dir: Path, *, control_rehearsal: bool) -> bool:
    """Use retained owner event ordering, never simulator-local command state."""
    events = _owner_events(run_dir)
    census_index = next((index for index, event in enumerate(events)
                         if event.get("event") == "adaptive_hybrid_regulation_startup_census_established"
                         and event.get("authority_admitted") is True), None)
    authority_indices = [
        index for index, event in enumerate(events)
        if event.get("event") == "command_submitted"
        and isinstance(event.get("command"), str)
        and event["command"].startswith(("ACTIVE SETUP ", "ACTIVE ARM "))
    ]
    if census_index is None:
        return False
    if not control_rehearsal:
        return not authority_indices
    return bool(authority_indices) and census_index < authority_indices[0]


def _owner_acknowledged_records(run_dir: Path) -> set[int]:
    values: set[int] = set()
    for event in _owner_events(run_dir):
        if event.get("event") != "transaction_phase_acknowledged":
            continue
        sequence = event.get("record_sequence")
        if type(sequence) is int:
            values.add(sequence)
    return values


def _owner_second_response_confirmed(run_dir: Path) -> bool:
    """Require the owner ACK and its first response consumer after record nine."""
    acknowledged = False
    classified = False
    for event in _owner_events(run_dir):
        if (event.get("event") == "transaction_phase_acknowledged"
                and event.get("request_sequence") == 2
                and event.get("record_sequence") == 9):
            acknowledged = True
        elif (acknowledged and event.get("event") == "response_classified"
              and event.get("request_sequence") == 2):
            classified = True
    return acknowledged and classified


def _owner_control_progress(run_dir: Path) -> tuple[object, ...]:
    """Progress only on retained control submissions, ACKs, and consumers."""
    values: list[object] = []
    for event in _owner_events(run_dir):
        name = event.get("event")
        command = event.get("command")
        if (name in {"command_submitted", "host_written"}
                and isinstance(command, str)
                and command.startswith(("ACTIVE SETUP ", "ACTIVE ARM "))):
            values.append((name, command))
        elif name == "transaction_phase_acknowledged":
            values.append((name, event.get("record_sequence")))
        elif name == "response_classified":
            values.append((name, event.get("request_sequence")))
    return tuple(values)


def _analysis_checks(run_dir: Path) -> dict[str, object]:
    try:
        report = json.loads((run_dir / ANALYSIS_REPORT).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    checks = report.get("checks")
    return checks if isinstance(checks, dict) else {}


def _owner_setup_arm_acknowledged(run_dir: Path) -> bool:
    events = _owner_events(run_dir)
    commands = [event.get("command") for event in events
                if event.get("event") == "host_written" and isinstance(event.get("command"), str)]
    return (
        any(command.startswith("ACTIVE SETUP ") for command in commands)
        and any(command.startswith("ACTIVE ARM ") for command in commands)
        and {2, 3, 4, 5}.issubset(_owner_acknowledged_records(run_dir))
    )


def _owner_metadata_hold_requalified(run_dir: Path) -> bool:
    entered: int | None = None
    for index, event in enumerate(_owner_events(run_dir)):
        if (event.get("event") == "adaptive_hybrid_regulation_gnss_metadata_hold_entered"
                and event.get("d14_d8_measurement_continues") is True):
            entered = index
        elif entered is not None and event.get("event") == "adaptive_hybrid_regulation_gnss_metadata_hold_requalified":
            return True
    return False


def _receipt(spec: Any, package: dict[str, Any], output: Path, boundary_results: dict[str, bool], boundaries_path: Path) -> Path:
    if not boundary_results or not all(boundary_results.values()):
        raise ValueError("a rehearsal receipt requires every retained boundary")
    document = spec.document()
    artifact = document["firmware"]["artifact"]
    unsigned = {
        "schema_version": 1, "contract": REHEARSAL_RECEIPT_CONTRACT,
        "status": "passed", "run_spec_sha256": spec.sha256,
        "firmware_artifact_sha256": artifact["firmware_artifact_sha256"],
        "firmware_binary_sha256": artifact["uf2"]["sha256"],
        "host_toolset_sha256": document["host"]["toolset"]["toolset_sha256"],
        "campaign_envelope_sha256": document["campaign"]["bench_attempt"]["envelope_sha256"],
        "package": {
            "path": package["package_directory"],
            "package_content_sha256": package["package_content_sha256"],
        },
        "boundaries": {
            "path": "reports/rehearsal_boundaries_v1.json",
            "sha256": sha256(boundaries_path.read_bytes()).hexdigest(),
        },
    }
    receipt = {**unsigned, "receipt_sha256": sha256(_canonical(unsigned)).hexdigest()}
    # Receipt construction and validation share the default portable package
    # location.  Do this before publishing the external receipt so a producer
    # cannot emit a location that its consumer cannot resolve.
    _validate_rehearsal_receipt(spec, receipt)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2)
        stream.write("\n")
    return output


def _write_boundaries_report(run_dir: Path, spec: Any, required: list[str], results: Mapping[str, bool]) -> Path:
    """Seal independently-derived rehearsal claims as an ordinary package payload."""
    if list(results) != required:
        raise ValueError("boundary report ordering differs from the run specification")
    path = run_dir / "reports/rehearsal_boundaries_v1.json"
    if path.exists():
        raise FileExistsError(path)
    document = {
        "schema_version": 1,
        "contract": "otis_rehearsal_boundaries_v1",
        "run_spec_sha256": spec.sha256,
        "required_boundaries": required,
        "boundary_results": dict(results),
    }
    document["report_sha256"] = sha256(_canonical(document)).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return path


def _analysis_passed(run_dir: Path) -> bool:
    try:
        report = json.loads((run_dir / ANALYSIS_REPORT).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    return report.get("status") == "passed" and report.get("outcome") != "undetermined"


def rehearse(*, spec_path: Path, run_dir: Path, receipt_path: Path | None = None, registry_path: Path | None = None) -> dict[str, Any]:
    """Run one retained run specification through production capture and supervision."""
    run_dir = run_dir.resolve()
    receipt_path = (receipt_path or run_dir.parent / f"{run_dir.name}-rehearsal.json").resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    retained_spec = run_dir / "run_spec.json"
    shutil.copyfile(spec_path.resolve(), retained_spec)
    if retained_spec.read_bytes() != spec_path.resolve().read_bytes():
        raise RuntimeError("retained run specification copy differs")
    spec = load_run_spec(retained_spec)
    master, slave = pty.openpty()
    slave_open = True
    device = os.ttyname(slave)
    record = create_run_record(spec, execution_kind="simulated", run_id=run_dir.name, started_at_utc=_utc_now(), serial_device=device, output_path=run_dir / "run_manifest.json")
    runtime = spec.runtime_manifest(record)
    required_boundaries = required_rehearsal_boundaries(spec)
    control_rehearsal = "two_progressive_transactions_complete" in required_boundaries
    emulator = DeterministicPtyInstrument(master, runtime, ADAPTIVE_HYBRID_PROGRAMME)
    scheduler_error: list[BaseException] = []

    # The capture worker must become the PTY slave's sole owner before its
    # readiness proof; the parent retains only the master producer endpoint.
    os.close(slave)
    slave_open = False

    def on_ready(experiment):
        thread = emulator.start()
        def schedule() -> None:
            try:
                progress = _owner_control_progress(experiment.run_dir)
                last_progress = time.monotonic()
                while control_rehearsal and not _owner_second_response_confirmed(experiment.run_dir):
                    current = _owner_control_progress(experiment.run_dir)
                    if current != progress:
                        progress, last_progress = current, time.monotonic()
                    if time.monotonic() - last_progress >= 20:
                        raise TimeoutError("deterministic transaction phase stopped progressing")
                    time.sleep(0.02)
                if not control_rehearsal:
                    while not _owner_startup_census_admitted(experiment.run_dir):
                        if time.monotonic() - last_progress >= 20:
                            raise TimeoutError("owner did not admit the startup census")
                        time.sleep(0.02)
                    if any(command.startswith(("ACTIVE SETUP ", "ACTIVE ARM ")) for command in emulator.commands):
                        raise RuntimeError("zero-write rehearsal observed control authority")
                pressure_fd, pressure_report = _exercise_normal_transport(
                    experiment.run_dir / "control/normal_commands.fifo", experiment.run_dir / "raw/serial.log"
                )
                try:
                    # Abort while the blocked normal writer remains open.
                    abort_submitted = time.monotonic_ns()
                    experiment.submit_explicit_abort()
                finally:
                    os.close(pressure_fd)
                report = dict(pressure_report)
                report.update({
                    "abort_submitted_monotonic_ns": abort_submitted,
                    "writer_closed_monotonic_ns": time.monotonic_ns(),
                    "writer_held_through_abort_submission": True,
                })
                _write_normal_transport_report(experiment.run_dir, report)
            except Exception as error:  # noqa: BLE001 - scheduler failure must trigger priority termination.
                scheduler_error.append(error)
                experiment.submit_explicit_abort()
        scheduler = threading.Thread(target=schedule, name="otis-rehearsal-scheduler", daemon=True)
        scheduler.start()
        def cleanup() -> None:
            emulator.stop()
            scheduler.join(timeout=2)
            thread.join(timeout=2)
        return cleanup

    try:
        live = run_experiment(manifest_path=run_dir / "run_manifest.json", device=device, physical=False, capture_command=_capture_command(device, run_dir), on_ready=on_ready)
    finally:
        if slave_open:
            os.close(slave)
        os.close(master)
    if scheduler_error:
        raise RuntimeError("rehearsal scheduler failed") from scheduler_error[0]
    if emulator.error is not None:
        raise RuntimeError("deterministic producer failed during rehearsal") from emulator.error
    if live.get("status") != "terminal" or live.get("terminal", {}).get("result") != "aborted":
        raise RuntimeError("rehearsal did not retain its priority-abort terminal")
    raw = (run_dir / "raw/serial.log").read_text(encoding="utf-8", errors="replace")
    analysis_error: Exception | None = None
    try:
        analyze(run_dir)
    except Exception as error:  # noqa: BLE001 - scheduler failure must trigger priority termination.  # noqa: BLE001 - retain a closed capture after analyzer failure.
        analysis_error = error
    analysis_checks = _analysis_checks(run_dir)
    boundary_results = {
        "capture_and_supervisor_processes_ready": live.get("process_topology_count") == 2,
        "startup_census_preceded_control_authority": _owner_startup_precedes_authority(
            run_dir, control_rehearsal=control_rehearsal
        ),
    }
    if control_rehearsal:
        boundary_results.update({
            "setup_arm_and_acknowledgements_exact": _owner_setup_arm_acknowledged(run_dir),
            "two_progressive_transactions_complete": (
                {2, 3, 4, 5, 6, 7, 8, 9}.issubset(_owner_acknowledged_records(run_dir))
                and _owner_second_response_confirmed(run_dir)
                and analysis_checks.get("transaction_capsules_exact") is True
                and analysis_checks.get("transactions_exact") is True
            ),
            "metadata_hold_nonterminal_and_requalified": _owner_metadata_hold_requalified(run_dir),
        })
    boundary_results.update({
        "normal_transport_obstruction_detected": _normal_transport_obstruction_proved(run_dir, raw),
        "priority_abort_delivered_before_capture_close": (
            live.get("terminal", {}).get("result") == "aborted"
            and '"event": "emergency_abort_sent"' in raw
        ),
        "capture_closed_and_offline_outcome_recorded": analysis_error is None and _analysis_passed(run_dir),
    })
    boundaries_path = _write_boundaries_report(run_dir, spec, required_boundaries, boundary_results)
    package = finish_run(run_dir, registry_path=registry_path)
    boundary_results["capture_closed_and_offline_outcome_recorded"] = (
        boundary_results["capture_closed_and_offline_outcome_recorded"]
        and package["capture"]["integrity"] == "complete"
        and package["analysis"]["status"] == "passed"
    )
    if list(boundary_results) != required_boundaries or not all(boundary_results.values()):
        raise RuntimeError("rehearsal retained evidence does not prove every required boundary")
    receipt = _receipt(spec, package, receipt_path, boundary_results, boundaries_path)
    return {"live": live, "package": package, "receipt": str(receipt)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec-path", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--registry", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(rehearse(spec_path=args.spec_path, run_dir=args.run_dir, receipt_path=args.receipt, registry_path=args.registry), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
