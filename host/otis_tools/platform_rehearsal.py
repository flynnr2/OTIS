"""Run and seal the non-actuating OTIS platform stabilization rehearsal.

This is the current platform-level orchestration path. It freezes one exact
fixed-code firmware/host bundle, flashes only that actuator-disabled profile,
maintains one serial owner, exercises bounded diagnostic commands, obstructs
the normal host path, proves the independent priority abort path, closes the
capture, analyzes it, creates the repository evidence snapshot, and registers
the complete package in the external content-addressed evidence index.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable

from tools.firmware_matrix import (
    DEFAULT_MATRIX,
    configuration_hash,
    load_matrix,
    source_input_hash,
)

from .board_identity import EXPECTED_SERIAL, read_board_identity
from .contracts import CONTRACT_FIELDS
from .cx318_capture_segment import prepare_transition, request_rotation
from .evidence import create_evidence_snapshot, validate_evidence_snapshot
from .evidence_index import DEFAULT_INDEX, register_package
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, load_manifest
from .run_paths import default_csv_files
from .serial_commands import (
    send_command_to_fifo,
    send_timestamped_command_to_fifo,
)
from .validate_run import validate_run


PROFILE_ID = "cx317_fixed_code_baseline"
TOOL_ID = "otis_platform_rehearsal_v1"
SEAL_TYPE = "otis_platform_rehearsal_seal_v1"
CAPTURE_TOOL = Path(__file__).with_name("capture_device.py")
SERIAL_COMMANDS_TOOL = Path(__file__).with_name("serial_commands.py")
EVIDENCE_TOOL = Path(__file__).with_name("evidence.py")
ANALYSIS_PATH = Path("reports/platform_rehearsal_analysis_v1.json")
ANALYSIS_REPORT_PATH = Path("reports/PLATFORM_REHEARSAL.md")
FLASH_RECORD_PATH = Path("reports/platform_exact_flash_v1.json")
TRANSPORT_REPORT_PATH = Path("reports/platform_transport_rehearsal_v1.json")
SEAL_PATH = Path("reports/platform_rehearsal_seal_v1.json")
BUNDLE_PATH = Path("platform_rehearsal_bundle_v1.json")
HANDOFF_TRANSITION_DIR = Path("owner_handoff_transition")
SEGMENT_CONTROL_DIR = Path("control/segment_carrier")
ROTATION_OPERATION_ID = "platform-rehearsal-owner-handoff"
HOST_MARKER_PREFIX = "# OTIS_HOST "


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
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    return sha256(
        json.dumps(
            value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()


def _atomic_new_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable artifact: {path}")
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _current_git_identity() -> tuple[str, str]:
    root = DEFAULT_MATRIX.parents[2]
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    return commit, "dirty" if status else "clean"


def _profile(matrix: dict[str, Any]) -> dict[str, Any]:
    matches = [item for item in matrix["profiles"] if item["id"] == PROFILE_ID]
    if len(matches) != 1 or matches[0].get("expect") != "pass":
        raise ValueError("matrix lacks one supported fixed-code bench profile")
    profile = matches[0]
    if "bench" not in profile.get("verification_tiers", []):
        raise ValueError("fixed-code profile is not selected for the Bench tier")
    return profile


def validate_nonactuating_build(
    *, matrix_path: Path, build_manifest_path: Path, uf2_path: Path
) -> dict[str, Any]:
    matrix_path = matrix_path.resolve()
    build_manifest_path = build_manifest_path.resolve()
    uf2_path = uf2_path.resolve()
    matrix = load_matrix(matrix_path)
    profile = _profile(matrix)
    defines = profile["defines"]
    forbidden_enabled = {
        "OTIS_ENABLE_DAC_AD5693R",
        "OTIS_ENABLE_H1_DAC_SWEEP",
        "OTIS_ENABLE_CX317_BOUNDED_ACTIVE",
        "OTIS_ENABLE_CX318_STAGE4_PREVIEW",
        "OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP",
        "OTIS_ENABLE_CX318_STAGE5_TIGHT_DEADBAND",
    }
    enabled = sorted(
        key for key in forbidden_enabled if defines.get(key, "0") != "0"
    )
    if enabled:
        raise ValueError(
            "fixed-code rehearsal build exposes actuation/preview authority: "
            + ", ".join(enabled)
        )
    if defines.get("OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED") != "0":
        raise ValueError("fixed-code rehearsal must not promote PPS qualification")

    build = json.loads(build_manifest_path.read_text(encoding="utf-8"))
    provenance = build.get("provenance", {})
    configuration = provenance.get("configuration", {})
    source = provenance.get("source", {})
    current_commit, current_state = _current_git_identity()
    expected_source_sha256 = source_input_hash(matrix_path=matrix_path)
    expected_configuration_sha256 = configuration_hash(matrix, profile)
    if (
        configuration.get("profile_id") != PROFILE_ID
        or configuration.get("defines") != defines
        or configuration.get("fqbn") != matrix["target"]["fqbn"]
        or configuration.get("sha256") != expected_configuration_sha256
    ):
        raise ValueError("build configuration differs from the current fixed profile")
    if (
        source.get("git_commit") != current_commit
        or source.get("state") != current_state
        or source.get("sha256") != expected_source_sha256
    ):
        raise ValueError("build source identity differs from current firmware inputs")
    artifacts = [
        item
        for item in build.get("artifacts", [])
        if item.get("name") == uf2_path.name
    ]
    if len(artifacts) != 1:
        raise ValueError("build manifest does not bind exactly one supplied UF2")
    artifact = artifacts[0]
    if (
        artifact.get("sha256") != _sha256_file(uf2_path)
        or artifact.get("size_bytes") != uf2_path.stat().st_size
    ):
        raise ValueError("supplied UF2 differs from the build manifest")
    resource_budget = build.get("resource_budget", {})
    if (
        resource_budget.get("contract") != "otis_firmware_resource_budget_v1"
        or resource_budget.get("status") != "within_budget"
    ):
        raise ValueError("firmware build does not pass the static resource budget")
    return {
        "profile_id": PROFILE_ID,
        "matrix_sha256": _sha256_file(matrix_path),
        "build_manifest_sha256": _sha256_file(build_manifest_path),
        "uf2_sha256": _sha256_file(uf2_path),
        "uf2_size_bytes": uf2_path.stat().st_size,
        "git_commit": current_commit,
        "source_state": current_state,
        "source_sha256": expected_source_sha256,
        "configuration_sha256": expected_configuration_sha256,
        "build_invocation_id": provenance["invocation"]["id"],
        "fqbn": configuration["fqbn"],
        "resource_budget": resource_budget,
    }


def _serial_owner_pids(device: str) -> set[int]:
    result = subprocess.run(
        ["lsof", "-t", device],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise ValueError(f"cannot inspect serial owners: {result.stderr.strip()}")
    return {
        int(line)
        for line in result.stdout.splitlines()
        if line.strip().isdigit()
    }


def flash_nonactuating_build(
    *,
    device: str,
    binding: dict[str, Any],
    uf2_path: Path,
    output_path: Path,
    arduino_cli: str,
) -> dict[str, Any]:
    owners = _serial_owner_pids(device)
    if owners:
        raise ValueError(f"serial device already has owners: {sorted(owners)}")
    before = read_board_identity(device, arduino_cli=arduino_cli)
    command = [
        arduino_cli,
        "upload",
        "--port",
        device,
        "--fqbn",
        binding["fqbn"],
        "--input-file",
        str(uf2_path.resolve()),
    ]
    started = _utc_now()
    completed = subprocess.run(
        command, text=True, capture_output=True, check=False
    )
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
    record = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "operation": "exact_nonactuating_flash",
        "status": "pass" if passed else "fail",
        "started_utc": started,
        "completed_utc": _utc_now(),
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
        "artifact_binding": binding,
        "actuation_compiled_out": True,
    }
    _atomic_new_json(output_path, record)
    if not passed:
        raise RuntimeError(f"exact non-actuating flash failed: {output_path}")
    return record


def _bundle(
    *, binding: dict[str, Any], duration_s: float, device: str
) -> dict[str, Any]:
    tool_bindings = {
        "platform_rehearsal": _sha256_file(Path(__file__)),
        "capture_device": _sha256_file(CAPTURE_TOOL),
        "serial_commands": _sha256_file(SERIAL_COMMANDS_TOOL),
        "evidence_snapshot": _sha256_file(EVIDENCE_TOOL),
    }
    payload = {
        "schema_version": 1,
        "bundle_id": "otis_platform_rehearsal_bundle_v1",
        "created_utc": _utc_now(),
        "firmware": binding,
        "host_tools": tool_bindings,
        "device": {"path": device, "expected_serial": EXPECTED_SERIAL},
        "capture": {
            "duration_s": duration_s,
            "baud": 115200,
            "write_timeout_s": 1.0,
            "normal_command_max_age_s": 2.0,
            "single_serial_owner_required": True,
        },
        "commands": {
            "representative": ["CONFIG?", "DAC?", "FC0?"],
            "priority_abort": "ACTIVE ABORT",
            "normal_envelope": "OTISQ1_MONOTONIC_NS",
            "expected_device_results": [
                "command/config_snapshot=end",
                "dac/enabled=false",
                "cx317_active/command=rejected_disabled",
            ],
        },
        "fault_injection": {
            "mechanism": "SIGSTOP validated sole capture owner and saturate normal FIFO",
            "abort_path": "distinct emergency FIFO",
            "resume_required": True,
        },
        "stop_conditions": [
            "planned duration reached",
            "capture process exits unexpectedly",
            "serial ownership changes",
            "normal FIFO does not saturate",
            "priority abort is not sent before stale normal commands",
        ],
        "authority": {
            "actuation_compiled_out": True,
            "campaign_progression": False,
            "qualification_promotion": False,
        },
    }
    payload["bundle_sha256"] = _canonical_sha256(payload)
    return payload


def _manifest(
    *,
    run_dir: Path,
    device: str,
    binding: dict[str, Any],
    bundle: dict[str, Any],
    flash_record: dict[str, Any],
) -> dict[str, Any]:
    files = default_csv_files()
    contracts = {
        str(item["contract"]): int(str(item["contract"]).rsplit("_v", 1)[1])
        for item in files
    }
    contracts["run_manifest_v1"] = 1
    evidence_artifacts = [
        BUNDLE_PATH.as_posix(),
        FLASH_RECORD_PATH.as_posix(),
        TRANSPORT_REPORT_PATH.as_posix(),
        "reports/capture_launcher.log",
        "reports/capture_device.log",
        "reports/capture_device_state.json",
        "reports/capture_segment_closure_v1.json",
        ANALYSIS_PATH.as_posix(),
        ANALYSIS_REPORT_PATH.as_posix(),
        (HANDOFF_TRANSITION_DIR / "run_manifest.json").as_posix(),
        (HANDOFF_TRANSITION_DIR / "raw/serial.log").as_posix(),
        (
            HANDOFF_TRANSITION_DIR
            / "reports/capture_device_state.json"
        ).as_posix(),
        (
            HANDOFF_TRANSITION_DIR
            / "reports/capture_segment_closure_v1.json"
        ).as_posix(),
        *[
            (HANDOFF_TRANSITION_DIR / str(item["path"])).as_posix()
            for item in files
        ],
    ]
    return {
        "schema_version": 1,
        "run_id": run_dir.name,
        "created_utc": _utc_now(),
        "started_at_utc": _utc_now(),
        "template": False,
        "stage": "OTIS_PLATFORM_STABILIZATION_REHEARSAL",
        "h_phase": "H1",
        "capture_mode": "pio_wait_cumulative_snapshot_with_independent_gpio_ref",
        "control_mode": "fixed_code_nonactuating",
        "closed_loop_control": False,
        "actionable": False,
        "actuation_authorized": False,
        "qualification_evidence": False,
        "board": "arduino_nano_rp2040_connect",
        "firmware": {
            "name": "otis_nano_rp2040_connect",
            "version": "PLATFORM_STABILIZATION_FIXED_CODE_V1",
            "config_id": PROFILE_ID,
            "git_commit": binding["git_commit"],
            "source_state": binding["source_state"],
            "source_sha256": binding["source_sha256"],
            "configuration_sha256": binding["configuration_sha256"],
            "build_manifest_sha256": binding["build_manifest_sha256"],
            "build_identity": binding["build_invocation_id"],
            "uf2_sha256": binding["uf2_sha256"],
            "uf2_size_bytes": binding["uf2_size_bytes"],
            "build_provenance_required": True,
        },
        "host": {
            "tool": "host.otis_tools.capture_device",
            "version": "platform_rehearsal_v1",
            "serial_device": device,
            "baud": 115200,
            "capture_command_write_timeout_s": 1.0,
            "normal_command_max_age_s": 2.0,
            "normal_command_envelope": "OTISQ1_MONOTONIC_NS",
        },
        "bundle": {
            "path": BUNDLE_PATH.as_posix(),
            "sha256": _sha256_file(run_dir / BUNDLE_PATH),
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "flash": {
            "path": FLASH_RECORD_PATH.as_posix(),
            "sha256": _sha256_file(run_dir / FLASH_RECORD_PATH),
            "board_identity": flash_record["board_after"],
        },
        "domains": [
            {"name": "rp2040_timer0", "nominal_hz": 16000000},
            {"name": "h1_cx317_ocxo_10mhz", "nominal_hz": 10000000},
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
        ],
        "contracts": contracts,
        "files": files,
        "expected_artifacts": [
            "raw/serial.log",
            "csv/raw_events.csv",
            "csv/count_observations.csv",
            "csv/health.csv",
            *evidence_artifacts,
        ],
        "evidence_artifacts": evidence_artifacts,
        "nominal_frequencies_hz": {"cx317": 10000000, "pps": 1},
        "known_limitations": [
            "This short platform rehearsal is not a calibration or stability campaign.",
            "PPS receiver, cable, physical aperture and combined uncertainty remain unavailable.",
            "Live stack evidence is an observed-minimum approximation, not exhaustive canary coverage.",
        ],
    }


def _wait_until(
    predicate: Callable[[], bool], timeout_s: float, description: str
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise RuntimeError(f"timed out waiting for {description}")


def _markers(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith(HOST_MARKER_PREFIX):
                result.append(json.loads(line[len(HOST_MARKER_PREFIX) :]))
    return result


def _health_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _health_has(path: Path, component: str, key: str, value: str) -> bool:
    return any(
        row.get("component") == component
        and row.get("status_key") == key
        and row.get("status_value") == value
        for row in _health_rows(path)
    )


def _latest_health(rows: list[dict[str, str]]) -> dict[tuple[str, str], str]:
    return {
        (row.get("component", ""), row.get("status_key", "")): row.get(
            "status_value", ""
        )
        for row in rows
    }


def _csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _capture_state_ready(run_dir: Path, pid: int) -> bool:
    path = run_dir / "reports/capture_device_state.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        state.get("pid") == pid
        and state.get("capture_active") is True
        and state.get("serial_open") is True
    )


def _inject_transport_fault(
    *,
    capture_pid: int,
    device: str,
    run_dir: Path,
    normal_fifo: Path,
    emergency_fifo: Path,
) -> dict[str, Any]:
    owner_pids = _serial_owner_pids(device)
    if owner_pids != {capture_pid}:
        raise ValueError(
            f"capture is not sole serial owner: {sorted(owner_pids)}"
        )
    started = _utc_now()
    stopped = False
    queued = 0
    saturated = False
    resumed_owner_pids: set[int] = set()
    try:
        os.kill(capture_pid, signal.SIGSTOP)
        stopped = True
        for _ in range(100_000):
            try:
                send_timestamped_command_to_fifo(normal_fifo, "CONFIG?")
                queued += 1
            except BlockingIOError:
                saturated = True
                break
        if not saturated:
            raise RuntimeError("normal command FIFO did not saturate")
        send_command_to_fifo(emergency_fifo, "ACTIVE ABORT")
        os.kill(capture_pid, signal.SIGCONT)
        stopped = False
        raw_path = run_dir / "raw/serial.log"
        _wait_until(
            lambda: any(
                row.get("event") == "emergency_abort_sent"
                for row in _markers(raw_path)
            ),
            10.0,
            "priority abort transmission",
        )
        _wait_until(
            lambda: _serial_owner_pids(device) == {capture_pid},
            5.0,
            "sole serial ownership after capture resume",
        )
        resumed_owner_pids = _serial_owner_pids(device)
    finally:
        if stopped:
            os.kill(capture_pid, signal.SIGCONT)
    return {
        "schema_version": 1,
        "tool": TOOL_ID,
        "status": "pass",
        "started_utc": started,
        "completed_utc": _utc_now(),
        "capture_pid": capture_pid,
        "serial_device": device,
        "serial_owner_pids": sorted(owner_pids),
        "serial_owner_pids_after_resume": sorted(resumed_owner_pids),
        "sole_serial_owner_verified": True,
        "sole_serial_owner_verified_after_resume": (
            resumed_owner_pids == {capture_pid}
        ),
        "owner_pid_unchanged_across_obstruction": (
            owner_pids == resumed_owner_pids == {capture_pid}
        ),
        "normal_fifo_saturated": saturated,
        "timestamped_config_queries_queued": queued,
        "priority_abort_enqueued_while_capture_stopped": True,
        "priority_abort_observed_in_capture": True,
        "capture_resumed": True,
    }


def analyze_rehearsal(
    run_dir: Path,
    *,
    matrix_path: Path,
    build_manifest_path: Path,
    uf2_path: Path,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    binding = validate_nonactuating_build(
        matrix_path=matrix_path,
        build_manifest_path=build_manifest_path,
        uf2_path=uf2_path,
    )
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    bundle = json.loads((run_dir / BUNDLE_PATH).read_text())
    flash = json.loads((run_dir / FLASH_RECORD_PATH).read_text())
    transport = json.loads((run_dir / TRANSPORT_REPORT_PATH).read_text())
    state = json.loads(
        (run_dir / "reports/capture_device_state.json").read_text()
    )
    closure = json.loads(
        (run_dir / "reports/capture_segment_closure_v1.json").read_text()
    )
    transition_state = json.loads(
        (
            run_dir
            / HANDOFF_TRANSITION_DIR
            / "reports/capture_device_state.json"
        ).read_text()
    )
    transition_closure = json.loads(
        (
            run_dir
            / HANDOFF_TRANSITION_DIR
            / "reports/capture_segment_closure_v1.json"
        ).read_text()
    )
    markers = _markers(run_dir / "raw/serial.log")
    marker_events = [str(row.get("event")) for row in markers]
    commands_sent = [
        str(row.get("command"))
        for row in markers
        if row.get("event") == "host_command_sent"
    ]
    health_rows = _health_rows(run_dir / "csv/health.csv")
    health = _latest_health(health_rows)
    counts = _csv_rows(run_dir / "csv/count_observations.csv")
    snapshots = _csv_rows(run_dir / "csv/pps_snapshots.csv")
    dac_rows = _csv_rows(run_dir / "csv/dac_steps.csv")
    active_rows = _csv_rows(run_dir / "csv/active_transactions_v1.csv")
    fatal_rows = [row for row in health_rows if row.get("severity") == "FATAL"]
    try:
        latch_index = marker_events.index("emergency_abort_latched")
        revoke_index = marker_events.index(
            "normal_command_ingress_revoked", latch_index + 1
        )
        accepted_index = next(
            index
            for index, row in enumerate(markers[latch_index + 1 :], latch_index + 1)
            if row.get("event") == "host_command_accepted"
            and row.get("command") == "ACTIVE ABORT"
        )
        sent_index = next(
            index
            for index, row in enumerate(markers[accepted_index + 1 :], accepted_index + 1)
            if row.get("event") == "host_command_sent"
            and row.get("command") == "ACTIVE ABORT"
        )
        complete_index = marker_events.index("emergency_abort_sent", sent_index + 1)
        ordered = [
            latch_index,
            revoke_index,
            accepted_index,
            sent_index,
            complete_index,
        ]
    except (StopIteration, ValueError):
        ordered = []
    count_values_ok = all(
        int(row.get("counted_edges", "0")) > 0 for row in counts
    )
    snapshot_high_water = int(
        health.get(("pps_gate", "snapshot_backlog_high_water"), "999999")
    )
    snapshot_capacity = int(
        health.get(("pps_gate", "snapshot_ring_capacity"), "0")
    )
    criteria = {
        "exact_nonactuating_build_bound": (
            manifest.get("firmware", {}).get("configuration_sha256")
            == binding["configuration_sha256"]
            and manifest.get("firmware", {}).get("uf2_sha256")
            == binding["uf2_sha256"]
            and manifest.get("actuation_authorized") is False
            and manifest.get("closed_loop_control") is False
        ),
        "frozen_bundle_and_single_flash_bound": (
            bundle.get("bundle_sha256")
            == _canonical_sha256(
                {key: value for key, value in bundle.items() if key != "bundle_sha256"}
            )
            and manifest.get("bundle", {}).get("sha256")
            == _sha256_file(run_dir / BUNDLE_PATH)
            and flash.get("status") == "pass"
            and flash.get("attempt_count") == 1
            and flash.get("board_before") == flash.get("board_after")
            and flash.get("board_after", {}).get("serial_number")
            == EXPECTED_SERIAL
        ),
        "one_continuous_bounded_serial_owner": (
            transport.get("sole_serial_owner_verified") is True
            and transport.get("serial_owner_pids")
            == [transport.get("capture_pid")]
            and transport.get("sole_serial_owner_verified_after_resume") is True
            and transport.get("serial_owner_pids_after_resume")
            == [transport.get("capture_pid")]
            and transport.get("owner_pid_unchanged_across_obstruction") is True
            and state.get("capture_active") is False
            and state.get("serial_open") is True
            and state.get("logical_segment_closed") is True
            and state.get("reconnect_count") == 0
            and not (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists()
            and closure.get("closure_mode") == "same_owner_logical_rotation"
            and closure.get("owner_pid") == transport.get("capture_pid")
            and closure.get("physical_serial_open") is True
            and closure.get("serial_reopened") is False
            and closure.get("serial_owner_check")
            == {
                "performed": True,
                "owner_pids": [transport.get("capture_pid")],
            }
            and transport.get("owner_handoff", {}).get("status")
            == "completed"
            and transport.get("owner_handoff", {}).get("pid")
            == transport.get("capture_pid")
            and transport.get("owner_handoff", {}).get("serial_reopened")
            is False
            and transition_state.get("capture_active") is False
            and transition_state.get("serial_open") is False
            and transition_state.get("reconnect_count") == 0
            and transition_closure.get("closure_mode")
            == "physical_serial_close"
            and transition_closure.get("owner_pid")
            == transport.get("capture_pid")
            and transition_closure.get("serial_reopened") is False
            and not (
                run_dir / HANDOFF_TRANSITION_DIR / CAPTURE_IN_PROGRESS_FLAG
            ).exists()
        ),
        "representative_commands_acknowledged_exactly": (
            commands_sent == ["CONFIG?", "DAC?", "FC0?", "ACTIVE ABORT"]
            and health.get(("command", "config_snapshot")) == "end"
            and health.get(("dac", "enabled")) == "false"
            and health.get(("cx317_active", "command"))
            == "rejected_disabled"
        ),
        "normal_obstruction_priority_abort_passed": (
            transport.get("status") == "pass"
            and transport.get("normal_fifo_saturated") is True
            and int(transport.get("timestamped_config_queries_queued", 0)) > 0
            and ordered == sorted(ordered)
            and commands_sent[-1:] == ["ACTIVE ABORT"]
            and state.get("emergency_aborts_sent") == 1
            and state.get("emergency_abort_latched") is True
        ),
        "capture_transport_clean": (
            all(
                state.get(key) == 0
                for key in (
                    "malformed_utf8",
                    "parser_errors",
                    "reconnect_count",
                    "commands_rejected",
                )
            )
            and state.get("normal_command_batch_limit") == 1
            and state.get("normal_command_max_age_s") == 2.0
            and state.get("write_timeout_s") == 1.0
        ),
        "resource_and_memory_budgets_live": (
            health.get(("resource_registry", "valid")) == "true"
            and health.get(("resource_registry", "complete")) == "true"
            and health.get(("resource_registry", "conflict_count")) == "0"
            and health.get(("resource_registry", "binding_failure_count"))
            == "0"
            and health.get(("memory_budget", "valid")) == "true"
            and int(
                health.get(
                    ("memory_budget", "core0_minimum_free_stack_bytes"), "0"
                )
            )
            >= 1024
            and int(
                health.get(("memory_budget", "minimum_free_heap_bytes"), "0")
            )
            >= 65536
        ),
        "capture_queue_margin_and_observations_present": (
            len(counts) >= 5
            and len(snapshots) >= 6
            and count_values_ok
            and snapshot_capacity > 0
            and 0 < snapshot_high_water < snapshot_capacity
            and all(
                health.get(("pps_gate", key)) == "0"
                for key in (
                    "snapshot_overwrite_count",
                    "snapshot_continuity_loss_count",
                    "snapshot_pio_rxstall_count",
                    "snapshot_dma_error_count",
                    "snapshot_dma_stopped_count",
                )
            )
            and health.get(("capture", "dropped_count")) == "0"
            and health.get(("capture", "pps_count_boundary_dropped_count"))
            == "0"
        ),
        "no_actuation_or_fatal_evidence": (
            not dac_rows and not active_rows and not fatal_rows
        ),
    }
    result = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "analysis_type": "otis_platform_rehearsal_analysis_v1",
        "status": "pass" if all(criteria.values()) else "fail",
        "run_dir": str(run_dir),
        "criteria": criteria,
        "observed": {
            "count_rows": len(counts),
            "snapshot_rows": len(snapshots),
            "snapshot_backlog_high_water": snapshot_high_water,
            "snapshot_ring_capacity": snapshot_capacity,
            "commands_sent": commands_sent,
            "core0_minimum_free_stack_bytes": health.get(
                ("memory_budget", "core0_minimum_free_stack_bytes")
            ),
            "minimum_free_heap_bytes": health.get(
                ("memory_budget", "minimum_free_heap_bytes")
            ),
            "fatal_status_rows": len(fatal_rows),
        },
        "bindings": {
            "matrix_sha256": binding["matrix_sha256"],
            "build_manifest_sha256": binding["build_manifest_sha256"],
            "uf2_sha256": binding["uf2_sha256"],
            "bundle_file_sha256": _sha256_file(run_dir / BUNDLE_PATH),
            "flash_record_sha256": _sha256_file(run_dir / FLASH_RECORD_PATH),
            "transport_report_sha256": _sha256_file(
                run_dir / TRANSPORT_REPORT_PATH
            ),
            "capture_tool_sha256": _sha256_file(CAPTURE_TOOL),
            "serial_commands_tool_sha256": _sha256_file(SERIAL_COMMANDS_TOOL),
            "analyzer_tool_sha256": _sha256_file(Path(__file__)),
        },
        "claims_boundary": (
            "non-actuating platform execution evidence only; no calibrated "
            "frequency, phase, UTC, lock, holdover, or combined uncertainty claim"
        ),
    }
    return result


def _analysis_markdown(result: dict[str, Any]) -> str:
    status = result["status"].upper()
    lines = [
        "# OTIS Platform Stabilization Rehearsal",
        "",
        f"Status: **{status}**",
        "",
        "This was the exact fixed-code, non-actuating platform rehearsal. It is",
        "execution evidence, not a calibration or a campaign progression gate.",
        "",
        "## Gates",
        "",
    ]
    lines.extend(
        f"- {'PASS' if passed else 'FAIL'} — `{name}`"
        for name, passed in result["criteria"].items()
    )
    observed = result["observed"]
    lines.extend(
        [
            "",
            "## Observed margins",
            "",
            f"- count rows: {observed['count_rows']}",
            f"- snapshot rows: {observed['snapshot_rows']}",
            "- snapshot backlog high-water/capacity: "
            f"{observed['snapshot_backlog_high_water']}/{observed['snapshot_ring_capacity']}",
            "- Core 0 minimum observed free stack: "
            f"{observed['core0_minimum_free_stack_bytes']} bytes",
            "- minimum observed free heap: "
            f"{observed['minimum_free_heap_bytes']} bytes",
            f"- host commands sent: {', '.join(observed['commands_sent'])}",
            "",
            "## Claims boundary",
            "",
            result["claims_boundary"] + ".",
            "",
        ]
    )
    return "\n".join(lines)


def _seal(run_dir: Path, analysis: dict[str, Any]) -> dict[str, Any]:
    snapshot_path = run_dir / "evidence_manifest.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    payload = {
        "schema_version": 1,
        "seal_type": SEAL_TYPE,
        "tool": TOOL_ID,
        "status": "pass",
        "sealed_utc": _utc_now(),
        "run_id": run_dir.name,
        "run_dir": str(run_dir.resolve()),
        "analysis": {
            "path": ANALYSIS_PATH.as_posix(),
            "sha256": _sha256_file(run_dir / ANALYSIS_PATH),
            "status": analysis["status"],
        },
        "evidence_snapshot": {
            "path": "evidence_manifest.json",
            "sha256": _sha256_file(snapshot_path),
            "snapshot_digest": snapshot["snapshot_digest"],
            "run_state": snapshot["run_state"],
        },
        "bundle": {
            "path": BUNDLE_PATH.as_posix(),
            "sha256": _sha256_file(run_dir / BUNDLE_PATH),
        },
        "qualification_evidence": False,
        "actuation_authorized": False,
    }
    payload["seal_sha256"] = _canonical_sha256(payload)
    _atomic_new_json(run_dir / SEAL_PATH, payload)
    return payload


def run_rehearsal(
    *,
    device: str,
    run_dir: Path,
    matrix_path: Path,
    build_manifest_path: Path,
    uf2_path: Path,
    duration_s: float,
    evidence_index_path: Path,
    arduino_cli: str,
) -> dict[str, Any]:
    if duration_s < 15.0:
        raise ValueError("platform rehearsal duration must be at least 15 seconds")
    run_dir = run_dir.resolve()
    if run_dir.exists():
        raise FileExistsError(f"rehearsal run already exists: {run_dir}")
    binding = validate_nonactuating_build(
        matrix_path=matrix_path,
        build_manifest_path=build_manifest_path,
        uf2_path=uf2_path,
    )
    run_dir.mkdir(parents=True)
    (run_dir / "reports").mkdir()
    bundle = _bundle(binding=binding, duration_s=duration_s, device=device)
    _atomic_new_json(run_dir / BUNDLE_PATH, bundle)
    flash_record = flash_nonactuating_build(
        device=device,
        binding=binding,
        uf2_path=uf2_path,
        output_path=run_dir / FLASH_RECORD_PATH,
        arduino_cli=arduino_cli,
    )
    manifest = _manifest(
        run_dir=run_dir,
        device=device,
        binding=binding,
        bundle=bundle,
        flash_record=flash_record,
    )
    _atomic_new_json(run_dir / "run_manifest.json", manifest)
    transition_dir = run_dir / HANDOFF_TRANSITION_DIR
    prepare_transition(run_dir / "run_manifest.json", transition_dir)

    normal_fifo = run_dir / "control/normal_commands.fifo"
    emergency_fifo = run_dir / "control/emergency_abort.fifo"
    segment_control_dir = run_dir / SEGMENT_CONTROL_DIR
    segment_capability = f"platform-{bundle['bundle_sha256']}"
    launcher_log = (run_dir / "reports/capture_launcher.log").open(
        "x", encoding="utf-8"
    )
    capture_args = [
        sys.executable,
        "-m",
        "host.otis_tools.capture_device",
        "--device",
        device,
        "--run-dir",
        str(run_dir),
        "--duration-s",
        str(duration_s),
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
    capture = subprocess.Popen(
        capture_args,
        cwd=DEFAULT_MATRIX.parents[2],
        stdout=launcher_log,
        stderr=launcher_log,
        text=True,
    )
    transport: dict[str, Any] | None = None
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
            15.0,
            "capture ownership and both command paths",
        )
        send_timestamped_command_to_fifo(normal_fifo, "CONFIG?")
        _wait_until(
            lambda: _health_has(
                run_dir / "csv/health.csv", "command", "config_snapshot", "end"
            ),
            12.0,
            "complete CONFIG snapshot",
        )
        send_timestamped_command_to_fifo(normal_fifo, "DAC?")
        _wait_until(
            lambda: _health_has(
                run_dir / "csv/health.csv", "dac", "enabled", "false"
            ),
            8.0,
            "disabled-DAC acknowledgement",
        )
        _wait_until(
            lambda: (
                len(_csv_rows(run_dir / "csv/count_observations.csv")) >= 5
                and len(_csv_rows(run_dir / "csv/pps_snapshots.csv")) >= 6
            ),
            12.0,
            "minimum count and aperture observations",
        )
        send_timestamped_command_to_fifo(normal_fifo, "FC0?")
        _wait_until(
            lambda: (
                (
                    "pps_gate",
                    "snapshot_backlog_high_water",
                )
                in _latest_health(
                    _health_rows(run_dir / "csv/health.csv")
                )
            ),
            8.0,
            "explicit live snapshot queue status",
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
            raise RuntimeError("same-owner transition did not preserve serial ownership")
        transport["owner_handoff"] = owner_handoff
        _atomic_new_json(run_dir / TRANSPORT_REPORT_PATH, transport)
        try:
            capture_exit = capture.wait(timeout=duration_s + 20.0)
        except subprocess.TimeoutExpired as exc:
            capture.terminate()
            capture.wait(timeout=5.0)
            raise RuntimeError("capture did not stop within its bounded duration") from exc
        if capture_exit != 0:
            raise RuntimeError(f"capture exited with status {capture_exit}")
    finally:
        launcher_log.close()
        if capture.poll() is None:
            capture.terminate()
            try:
                capture.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                capture.kill()
                capture.wait(timeout=5.0)

    analysis = analyze_rehearsal(
        run_dir,
        matrix_path=matrix_path,
        build_manifest_path=build_manifest_path,
        uf2_path=uf2_path,
    )
    _atomic_new_json(run_dir / ANALYSIS_PATH, analysis)
    (run_dir / ANALYSIS_REPORT_PATH).write_text(
        _analysis_markdown(analysis), encoding="utf-8"
    )
    if analysis["status"] != "pass":
        failed = sorted(
            name for name, passed in analysis["criteria"].items() if not passed
        )
        indexed_failure = register_package(
            index_path=evidence_index_path,
            package_path=run_dir,
            source_revision=binding["git_commit"],
            build_identity=binding["build_manifest_sha256"],
            profile_identity=PROFILE_ID,
            attempt_classification="failed_rehearsal",
            result_or_failure_reason=(
                "platform rehearsal analysis failed: " + ", ".join(failed)
            ),
            analyzer_identity=analysis["bindings"]["analyzer_tool_sha256"],
        )
        raise RuntimeError(
            f"platform rehearsal analysis failed: {run_dir / ANALYSIS_PATH}; "
            f"retained evidence content {indexed_failure['content_sha256']}"
        )
    (run_dir / "COMPLETE").write_text(
        "exact non-actuating platform rehearsal passed\n", encoding="utf-8"
    )
    snapshot_path = create_evidence_snapshot(run_dir)
    loaded_manifest = load_manifest(run_dir)
    failures, warnings = validate_evidence_snapshot(run_dir, loaded_manifest)
    if failures or warnings:
        raise RuntimeError(
            "evidence snapshot validation failed: "
            + json.dumps({"failures": failures, "warnings": warnings})
        )
    if validate_run(run_dir) != 0:
        raise RuntimeError("generic run validation failed after evidence sealing")
    seal = _seal(run_dir, analysis)
    indexed = register_package(
        index_path=evidence_index_path,
        package_path=run_dir,
        source_revision=binding["git_commit"],
        build_identity=binding["build_manifest_sha256"],
        profile_identity=PROFILE_ID,
        attempt_classification="successful_rehearsal",
        result_or_failure_reason="all exact-bundle platform rehearsal gates passed",
        analyzer_identity=analysis["bindings"]["analyzer_tool_sha256"],
    )
    return {
        "status": "pass",
        "run_dir": str(run_dir),
        "analysis": str(run_dir / ANALYSIS_PATH),
        "evidence_snapshot": str(snapshot_path),
        "seal": str(run_dir / SEAL_PATH),
        "seal_sha256": seal["seal_sha256"],
        "evidence_content_sha256": indexed["content_sha256"],
        "evidence_index": str(evidence_index_path.expanduser().resolve()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--build-manifest", type=Path, required=True)
    parser.add_argument("--uf2", type=Path, required=True)
    parser.add_argument("--duration-s", type=float, default=25.0)
    parser.add_argument("--evidence-index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--arduino-cli", default="arduino-cli")
    args = parser.parse_args(argv)
    try:
        result = run_rehearsal(
            device=args.device,
            run_dir=args.run_dir,
            matrix_path=args.matrix,
            build_manifest_path=args.build_manifest,
            uf2_path=args.uf2,
            duration_s=args.duration_s,
            evidence_index_path=args.evidence_index,
            arduino_cli=args.arduino_cli,
        )
    except (
        FileExistsError,
        OSError,
        RuntimeError,
        ValueError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
