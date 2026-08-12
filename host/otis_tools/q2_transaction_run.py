"""Run the exact electrically inhibited CX319 Q2 transaction rehearsal."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable

from .active_status_contract import latest_complete_health
from .board_identity import read_board_identity
from .evidence import create_evidence_snapshot
from .evidence_index import DEFAULT_INDEX, register_package, validate_index_location
from .platform_rehearsal import _capture_state_ready, _serial_owner_pids
from .q2_transaction_analyze import (
    ANALYSIS_PATH,
    BUNDLE_PATH,
    FLASH_RECORD_PATH,
    OPERATOR_CONFIRMATION_PATH,
    REPORT_PATH,
    SEAL_PATH,
    SETUP_AUTHORITY_PATH,
    _q2_case_evidence,
    analyze,
    report_markdown,
    seal,
)
from .q2_transaction_bundle import validate_bundle
from .run_paths import default_csv_files
from .serial_commands import send_timestamped_command_to_fifo


TOOL_ID = "cx319_q2_transaction_runner_v1"
CAPTURE_LOG = Path("reports/q2_capture_launcher.log")
RUN_TIMEOUT_S = 20 * 60
FAILURE_PATH = Path("reports/q2_orchestration_failure_v1.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable Q2 artifact: {path}")
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
        suffix=".tmp", delete=False
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


def _wait_until(predicate: Callable[[], bool], timeout_s: float, description: str) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise TimeoutError(f"timed out waiting for {description}")


def _create_manifest(run_dir: Path, bundle: dict[str, Any]) -> None:
    files = default_csv_files()
    payload = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "created_utc": _utc_now(),
        "started_at_utc": _utc_now(),
        "template": False,
        "stage": "CX319_Q2_INHIBITED_TRANSACTION_REHEARSAL",
        "host": {
            "tool": TOOL_ID,
            "version": 1,
            "git_commit": bundle["source_revision"],
            "serial_device": bundle["device"]["path"],
            "baud": bundle["device"]["baud"],
        },
        "firmware": {
            "name": "otis_nano_rp2040_connect",
            "version": "SW1",
            "git_commit": bundle["firmware"]["git_commit"],
            "build_provenance_required": True,
        },
        "domains": [{"name": "rp2040_timer0", "nominal_hz": 16000000}],
        "channels": [
            {"channel_id": 0, "role": "generic_pulse", "record_family": "raw_events_v1"},
            {"channel_id": 1, "role": "pps_reference", "record_family": "raw_events_v1"},
            {"channel_id": 2, "role": "xcxo_observation", "record_family": "count_observations_v1"},
        ],
        "files": files,
        "expected_artifacts": [entry["path"] for entry in files if not entry.get("optional")],
        "evidence_artifacts": [
            BUNDLE_PATH.as_posix(),
            OPERATOR_CONFIRMATION_PATH.as_posix(),
            SETUP_AUTHORITY_PATH.as_posix(),
            FLASH_RECORD_PATH.as_posix(),
            ANALYSIS_PATH.as_posix(),
            REPORT_PATH.as_posix(),
        ],
        "q2": {
            "bundle_sha256": bundle["bundle_sha256"],
            "case_count": 38,
            "physical_setup_writes": 1,
            "physical_automatic_writes": 0,
            "oscillator_control_input_isolated": True,
        },
        "known_limitations": [
            "Q2 is a diagnostic transaction rehearsal, not a live oscillator-control qualification."
        ],
    }
    _atomic_new_json(run_dir / "run_manifest.json", payload)


def _flash_exact(bundle: dict[str, Any], output_path: Path, arduino_cli: str) -> dict[str, Any]:
    device = str(bundle["device"]["path"])
    owners = _serial_owner_pids(device)
    if owners:
        raise ValueError(f"serial device already has owners: {sorted(owners)}")
    before = read_board_identity(device, arduino_cli=arduino_cli)
    firmware = bundle["firmware"]
    command = [
        arduino_cli, "upload", "--port", device, "--fqbn", firmware["fqbn"],
        "--input-file", firmware["uf2"]["path"],
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    after: dict[str, str] | None = None
    if completed.returncode == 0:
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            try:
                after = read_board_identity(device, arduino_cli=arduino_cli)
                break
            except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
                time.sleep(0.5)
    passed = completed.returncode == 0 and before == after
    record = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "operation": "exact_q2_diagnostic_flash",
        "status": "pass" if passed else "fail",
        "completed_utc": _utc_now(),
        "command": command,
        "exit_code": completed.returncode,
        "stdout_sha256": sha256(completed.stdout.encode()).hexdigest(),
        "stderr_sha256": sha256(completed.stderr.encode()).hexdigest(),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
        "board_before": before,
        "board_after": after,
        "bundle_sha256": bundle["bundle_sha256"],
        "build_manifest_sha256": firmware["build_manifest"]["sha256"],
        "uf2_sha256": firmware["uf2"]["sha256"],
        "profile_id": firmware["profile_id"],
        "dac_boot_operation": "i2c_address_probe_only",
        "dac_value_write_attempts": 0,
    }
    _atomic_new_json(output_path, record)
    if not passed:
        raise RuntimeError("exact Q2 diagnostic flash failed")
    return record


def _read_health(run_dir: Path) -> list[dict[str, str]]:
    path = run_dir / "csv/health.csv"
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _case_complete(run_dir: Path, case_id: int, nonce: int) -> bool:
    try:
        cases = _q2_case_evidence(_read_health(run_dir))
    except (ValueError, csv.Error):
        return False
    observed = cases.get(case_id, {})
    return (
        observed.get("query_nonce") == str(nonce)
        and observed.get("case_pass") == "true"
        and observed.get("case_complete") == str(case_id)
    )


def _setup_phases_for(run_dir: Path, request: dict[str, Any]) -> list[str]:
    phases: list[str] = []
    current: dict[str, str] | None = None
    for row in _read_health(run_dir):
        if row.get("component") != "cx317_setup":
            continue
        key = row.get("status_key", "")
        value = row.get("status_value", "")
        if key == "phase":
            if current is not None and all(
                current.get(name) == str(request[name])
                for name in ("authorization_sequence", "status_generation", "query_nonce")
            ):
                phases.append(current["phase"])
            current = {"phase": value}
        elif current is not None:
            current[key] = value
    if current is not None and all(
        current.get(name) == str(request[name])
        for name in ("authorization_sequence", "status_generation", "query_nonce")
    ):
        phases.append(current["phase"])
    return phases


def _production_setup_complete(run_dir: Path, request: dict[str, Any]) -> bool:
    phases = _setup_phases_for(run_dir, request)
    expected = [
        "firmware_received", "core1_authorized", "core0_accepted",
        "core1_execution_released", "applied",
    ]
    cursor = 0
    for phase in phases:
        if cursor < len(expected) and phase == expected[cursor]:
            cursor += 1
    return cursor == len(expected)


def _setup_ready(health: dict[tuple[str, str], str], bundle: dict[str, Any]) -> bool:
    active = "cx317_active"
    return (
        health.get((active, "build_identity"))
        == bundle["firmware"]["source_sha256"] + ":" + bundle["firmware"]["configuration_sha256"]
        and health.get((active, "profile_identity")) == bundle["firmware"]["profile_id"]
        and health.get((active, "state")) == "DISARMED"
        and health.get((active, "capture_lease_live")) == "true"
        and health.get((active, "setup_gnss_eligible")) == "true"
        and health.get((active, "setup_reference_eligible")) == "true"
        and health.get((active, "setup_partition_healthy")) == "true"
        and health.get((active, "manual_start_confirmed")) == "false"
        and health.get((active, "fail_static")) == "false"
        and int(health.get((active, "session_id"), "0")) > 0
    )


def _obtain_current_setup_snapshot(
    run_dir: Path, normal_fifo: Path, bundle: dict[str, Any]
) -> dict[tuple[str, str], str]:
    deadline = time.monotonic() + 180.0
    lease_sequence = 1
    while time.monotonic() < deadline:
        send_timestamped_command_to_fifo(normal_fifo, f"ACTIVE LEASE {lease_sequence}")
        nonce = secrets.randbits(32) or 1
        send_timestamped_command_to_fifo(normal_fifo, f"ACTIVE SNAPSHOT {nonce}")
        try:
            _wait_until(
                lambda: latest_complete_health(
                    run_dir / "csv/health.csv", required_query_nonce=nonce
                ).get(("cx317_active", "query_nonce")) == str(nonce),
                8.0,
                "nonce-bound Q2 setup snapshot",
            )
        except TimeoutError:
            lease_sequence += 1
            continue
        health = latest_complete_health(
            run_dir / "csv/health.csv", required_query_nonce=nonce
        )
        if _setup_ready(health, bundle):
            return health
        lease_sequence += 1
        time.sleep(1.0)
    raise TimeoutError("Q2 setup predicates did not become current within 180 seconds")


def run_q2(
    *, bundle_path: Path, run_dir: Path, evidence_index_path: Path,
    arduino_cli: str, operator_confirmed_inhibited: bool
) -> dict[str, Any]:
    if not operator_confirmed_inhibited:
        raise ValueError("explicit operator confirmation of the Q2 inhibited topology is required")
    bundle = validate_bundle(bundle_path.resolve())
    evidence_index_path = validate_index_location(evidence_index_path)
    run_dir = run_dir.resolve()
    if run_dir.exists():
        raise FileExistsError(f"Q2 run directory already exists: {run_dir}")
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "control").mkdir()
    shutil.copyfile(bundle_path.resolve(), run_dir / BUNDLE_PATH)
    confirmation = {
        "schema_version": 1,
        "confirmed": True,
        "confirmed_utc": _utc_now(),
        "topology": "dac_analogue_output_disconnected_from_oscillator_efc_vctrl",
        "oscillator_powered": True,
        "dac_i2c_reachable": True,
        "maximum_inhibited_window_s": 1800,
        "claims_boundary": "The DAC remains digitally reachable but cannot move the physical oscillator control input.",
    }
    _atomic_new_json(run_dir / OPERATOR_CONFIRMATION_PATH, confirmation)
    _create_manifest(run_dir, bundle)
    _flash_exact(bundle, run_dir / FLASH_RECORD_PATH, arduino_cli)

    normal_fifo = run_dir / "control/normal_commands.fifo"
    capture_log = (run_dir / CAPTURE_LOG).open("x", encoding="utf-8")
    capture = subprocess.Popen(
        [
            sys.executable, "-m", "host.otis_tools.capture_device",
            "--device", bundle["device"]["path"], "--run-dir", str(run_dir),
            "--duration-s", str(RUN_TIMEOUT_S), "--status-interval", "5",
            "--command-fifo", str(normal_fifo), "--write-timeout-s", "1",
            "--normal-command-max-age-s",
            str(bundle["commands"]["normal_command_max_age_s"]),
        ],
        cwd=Path(__file__).resolve().parents[2], stdout=capture_log,
        stderr=capture_log, text=True,
    )
    try:
        _wait_until(
            lambda: (
                capture.poll() is None and normal_fifo.exists()
                and stat.S_ISFIFO(normal_fifo.stat().st_mode)
                and _capture_state_ready(run_dir, capture.pid)
            ),
            20.0,
            "Q2 continuous serial carrier",
        )
        send_timestamped_command_to_fifo(normal_fifo, "CONFIG?")
        send_timestamped_command_to_fifo(normal_fifo, "DAC?")
        nonce_base = secrets.randbits(31) or 1
        for case_id in range(1, 39):
            nonce = (nonce_base + case_id) & 0xFFFFFFFF or case_id
            send_timestamped_command_to_fifo(
                normal_fifo, f"Q2 CASE {nonce} {case_id}"
            )
            _wait_until(
                lambda case_id=case_id, nonce=nonce: _case_complete(
                    run_dir, case_id, nonce
                ),
                12.0,
                f"Q2 diagnostic case {case_id}",
            )

        health = _obtain_current_setup_snapshot(run_dir, normal_fifo, bundle)
        active = "cx317_active"
        request: dict[str, Any] = {
            "authorization_sequence": 1,
            "status_generation": int(health[(active, "snapshot_generation_complete")]),
            "query_nonce": int(health[(active, "query_nonce")]),
            "expires_s": int(health[(active, "uptime_s")]) + 30,
            "session_id": int(health[(active, "session_id")]),
            "requested_code": int(bundle["firmware"]["start_code"]),
            "one_shot_ordinal": 1,
            "configuration_identity": bundle["firmware"]["configuration_sha256"],
        }
        _atomic_new_json(
            run_dir / SETUP_AUTHORITY_PATH,
            {
                "schema_version": 1,
                "created_utc": _utc_now(),
                "request": request,
                "snapshot": {
                    key: value for (component, key), value in health.items()
                    if component == active
                },
            },
        )
        setup_command = (
            "ACTIVE SETUP 1 "
            f"{request['status_generation']} {request['query_nonce']} "
            f"{request['expires_s']} {request['session_id']} "
            f"0x{request['requested_code']:04X} 1 "
            f"{request['configuration_identity']}"
        )
        send_timestamped_command_to_fifo(normal_fifo, setup_command)
        _wait_until(
            lambda: _production_setup_complete(run_dir, request),
            20.0,
            "production Q2 received/authorized/accepted/applied acknowledgement chain",
        )
    finally:
        if capture.poll() is None:
            capture.send_signal(signal.SIGINT)
            try:
                capture.wait(timeout=20.0)
            except subprocess.TimeoutExpired:
                capture.terminate()
                capture.wait(timeout=10.0)
        capture_log.close()
    if capture.returncode != 0:
        raise RuntimeError(f"Q2 capture carrier exited {capture.returncode}")

    analysis = analyze(run_dir)
    _atomic_new_json(run_dir / ANALYSIS_PATH, analysis)
    (run_dir / REPORT_PATH).write_text(report_markdown(analysis), encoding="utf-8")
    if analysis["status"] != "pass":
        raise RuntimeError(f"Q2 analyzer failed: {run_dir / ANALYSIS_PATH}")
    (run_dir / "COMPLETE").touch(exist_ok=False)
    create_evidence_snapshot(run_dir)
    seal_value = seal(run_dir, analysis)
    _atomic_new_json(run_dir / SEAL_PATH, seal_value)
    registered = register_package(
        index_path=evidence_index_path,
        package_path=run_dir,
        source_revision=bundle["source_revision"],
        build_identity=bundle["firmware"]["build_manifest"]["sha256"],
        profile_identity=bundle["firmware"]["profile_id"],
        attempt_classification="successful_rehearsal",
        result_or_failure_reason="CX319 Q2 electrically inhibited transaction rehearsal passed",
        analyzer_identity=_sha256_file(Path(__file__).with_name("q2_transaction_analyze.py")),
    )
    return {
        "status": "pass",
        "run_dir": str(run_dir),
        "seal_sha256": seal_value["seal_sha256"],
        "registered_content_sha256": registered["content_sha256"],
    }


def _retain_failed_attempt(
    *, run_dir: Path, bundle_path: Path, evidence_index_path: Path,
    error: Exception
) -> str | None:
    if not run_dir.is_dir():
        return None
    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        failure_path = run_dir / FAILURE_PATH
        if not failure_path.exists():
            _atomic_new_json(
                failure_path,
                {
                    "schema_version": 1,
                    "tool": TOOL_ID,
                    "status": "fail",
                    "failure_class": "platform_defect_caught_in_rehearsal",
                    "recorded_utc": _utc_now(),
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "claims_boundary": "Failed Q2 evidence only; no live authority granted.",
                },
            )
        registered = register_package(
            index_path=validate_index_location(evidence_index_path),
            package_path=run_dir,
            source_revision=str(bundle.get("source_revision", "unknown")),
            build_identity=str(
                bundle.get("firmware", {}).get("build_manifest", {}).get(
                    "sha256", "unknown"
                )
            ),
            profile_identity=str(
                bundle.get("firmware", {}).get("profile_id", "unknown")
            ),
            attempt_classification="failed_rehearsal",
            result_or_failure_reason=f"CX319 Q2 stopped: {error}",
            analyzer_identity=_sha256_file(
                Path(__file__).with_name("q2_transaction_analyze.py")
            ),
        )
        return str(registered["content_sha256"])
    except Exception:  # noqa: BLE001 - never replace the primary Q2 failure.
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--evidence-index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--arduino-cli", default="arduino-cli")
    parser.add_argument("--operator-confirmed-inhibited", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_q2(
            bundle_path=args.bundle, run_dir=args.run_dir,
            evidence_index_path=args.evidence_index,
            arduino_cli=args.arduino_cli,
            operator_confirmed_inhibited=args.operator_confirmed_inhibited,
        )
    except (
        FileExistsError, KeyboardInterrupt, OSError, RuntimeError, TimeoutError,
        ValueError,
    ) as exc:
        retained = _retain_failed_attempt(
            run_dir=args.run_dir.resolve(), bundle_path=args.bundle.resolve(),
            evidence_index_path=args.evidence_index, error=exc
        )
        suffix = f"; retained_content_sha256={retained}" if retained else ""
        parser.error(str(exc) + suffix)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
