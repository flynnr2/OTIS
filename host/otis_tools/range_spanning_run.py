"""Execute one finite, actively monitored CX319 Part A survey prefix."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any, Callable

from .board_identity import read_board_identity
from .capture_runtime_checks import _capture_state_ready, _serial_owner_pids
from .evidence import create_evidence_snapshot, validate_evidence_snapshot
from .evidence_index import DEFAULT_INDEX, register_package
from .range_spanning_analyze import analyze
from .range_spanning_bundle import (
    _atomic_new_json,
    canonical_sha256,
    sha256_file,
    validate_bundle,
)
from .run_loader import load_manifest
from .run_paths import default_csv_files
from .serial_commands import send_command_to_fifo, send_timestamped_command_to_fifo


TOOL_ID = "cx319_range_spanning_run_v1"
LIVE_STAGE = "CX319_RANGE_SPANNING_PART_A_SEGMENT"
CAPTURE_LOG = Path("reports/range_spanning_capture.log")
EVENTS = Path("reports/range_spanning_supervisor_events.jsonl")
STATE = Path("reports/range_spanning_supervisor_state.json")
ENTRY_RECORD = Path("reports/range_spanning_firmware_entry_v2.json")
ANALYSIS = Path("reports/range_spanning_analysis_v1.json")
SEAL = Path("reports/range_spanning_seal_v1.json")
FINALIZATION_FAILURE = Path("reports/range_spanning_finalization_failure_v1.json")
ACTIVATION = Path("range_spanning_live_activation_v1.json")
POLICY_PATH = Path("profiles/discipline/cx319_stabilized_tight_deadband_v1.json")
TERMINAL_ABORT_DELIVERY_TIMEOUT_S = 15.0
CAPTURE_STATE_MAX_AGE_S = 15.0
RETAINED_SERIAL_MAX_AGE_S = 30.0


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("deadline UTC must include a timezone")
    return parsed.astimezone(timezone.utc)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    try:
        with path.open("r", newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except (OSError, csv.Error):
        return []


def _create_validated_evidence_snapshot(run_dir: Path) -> dict[str, str]:
    snapshot_path = create_evidence_snapshot(run_dir)
    manifest = load_manifest(run_dir)
    evidence_failures, _warnings = validate_evidence_snapshot(run_dir, manifest)
    if evidence_failures:
        raise RuntimeError(
            "evidence snapshot validation failed: "
            + "; ".join(evidence_failures)
        )
    snapshot = _read_json(snapshot_path)
    if snapshot is None or not isinstance(snapshot.get("snapshot_digest"), str):
        raise RuntimeError("evidence snapshot digest is absent or invalid")
    return {
        "path": str(snapshot_path),
        "snapshot_digest": str(snapshot["snapshot_digest"]),
    }


def _append_event(path: Path, value: dict[str, Any]) -> None:
    record = {"recorded_utc": _utc_now(), **value}
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        payload = (
            json.dumps(record, sort_keys=True, allow_nan=False) + "\n"
        ).encode("utf-8")
        if os.write(descriptor, payload) != len(payload):
            raise OSError("short supervisor event write")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _replace_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _locate_board(expected_serial: str, *, arduino_cli: str) -> tuple[str, dict[str, str]]:
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
    return addresses[0], read_board_identity(addresses[0], arduino_cli=arduino_cli)


def _create_activation(
    *, bundle_path: Path, bundle: dict[str, Any], deadline: datetime, run_dir: Path
) -> dict[str, Any]:
    unsigned = {
        "schema_version": 1,
        "activation_type": "cx319_range_spanning_part_a_live_activation_v1",
        "created_utc": _utc_now(),
        "effective": True,
        "operator_authority_instruction_date": bundle["operator_authority"][
            "instruction_date"
        ],
        "bundle": {
            "path": str(bundle_path),
            "sha256": sha256_file(bundle_path),
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "run_dir": str(run_dir),
        "wall_deadline_utc": deadline.isoformat().replace("+00:00", "Z"),
        "firmware_entry_mode": bundle["entry"]["mode"],
        "firmware_flashes_allowed": bundle["entry"]["firmware_flashes_allowed"],
        "board_resets_allowed": bundle["entry"]["board_resets_allowed"],
        "phase_or_hybrid_actuation": False,
        "automatic_restore": False,
    }
    return {**unsigned, "activation_sha256": canonical_sha256(unsigned)}


def _create_manifest(
    *, run_dir: Path, bundle_path: Path, bundle: dict[str, Any], device: str
) -> None:
    files = default_csv_files()
    contracts = {
        entry["contract"]: 2 if entry["contract"] == "estimates_v2" else 1
        for entry in files
    }
    firmware = bundle["firmware"]
    evidence_artifacts = [
        str(CAPTURE_LOG),
        str(EVENTS),
        str(STATE),
        str(ENTRY_RECORD),
        str(ANALYSIS),
        str(SEAL),
        str(ACTIVATION),
        "reports/capture_device_state.json",
        "COMPLETE",
    ]
    focused_campaign = (
        bundle.get("bundle_type") == "cx319_conditional_fine_map_part_a_bundle_v2"
    )
    if focused_campaign:
        evidence_artifacts.append("reports/conditional_part_a_promotion_v2.json")
    manifest = {
        "schema_version": 1,
        "template": False,
        "run_id": run_dir.name,
        "created_utc": _utc_now(),
        "stage": LIVE_STAGE,
        "compatibility_floor": "CX319_EVIDENCE_EPOCH_1",
        "board": "arduino_nano_rp2040_connect",
        "capture_mode": "pio_wait_cumulative_snapshot_with_independent_gpio_ref",
        "actionable": False,
        "actuation_authorized": True,
        "closed_loop_control": False,
        "control_mode": "externally_precommitted_range_map_setup_stimuli",
        "cx319": {
            "profile_id": "cx319_range_map_part_a",
            "mode": (
                "focused_part_a_boundary_map"
                if focused_campaign
                else "part_a_boundary_map"
            ),
            "authority": {
                "effective": True,
                "physical_execution": True,
                "firmware_flash": bundle["entry"]["firmware_flashes_allowed"] == 1,
                "board_reset": bundle["entry"]["board_resets_allowed"] == 1,
                "serial_open": True,
                "dac_setup_stimuli": True,
                "automatic_frequency_control": False,
                "phase_or_hybrid_actionable": False,
            },
        },
        "host": {
            "tool": TOOL_ID,
            "serial_device": device,
            "baud": bundle["device"]["baud"],
            "sole_serial_owner": True,
            "normal_command_ingress": "timestamped_bounded_fifo",
            "priority_abort_ingress": "independent_fifo",
        },
        "firmware": {
            "profile_id": firmware["profile_id"],
            "fqbn": firmware["fqbn"],
            "git_commit": firmware["git_commit"],
            "source_sha256": firmware["source_sha256"],
            "configuration_sha256": firmware["configuration_sha256"],
            "build_invocation_id": firmware["build_invocation_id"],
            "build_manifest": firmware["build_manifest"],
            "uf2": firmware["uf2"],
            "build_provenance_required": True,
        },
        "bundle": {
            "path": str(bundle_path),
            "sha256": sha256_file(bundle_path),
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "entry": bundle["entry"],
        "policy": {
            "path": str((Path(__file__).resolve().parents[2] / POLICY_PATH).resolve()),
            "sha256": sha256_file(Path(__file__).resolve().parents[2] / POLICY_PATH),
        },
        "domains": [
            {
                "name": "rp2040_timer0",
                "nominal_hz": 16_000_000,
                "counter_width_bits": 36,
                "modulus_ticks": 68_719_476_736,
                "rollover": "modular_forward",
                "maximum_unambiguous_forward_ticks": 34_359_738_368,
            },
            {"name": "h1_cx317_ocxo_10mhz", "nominal_hz": 10_000_000},
        ],
        "channels": [
            {
                "channel_id": 1,
                "role": "authoritative_d14_pps_reference",
                "record_family": "raw_events_v1",
            },
            {
                "channel_id": 2,
                "role": "authoritative_d8_pps_gated_oscillator_count",
                "record_family": "count_observations_v1",
            },
        ],
        "contracts": contracts,
        "files": files,
        "expected_artifacts": [
            *(entry["path"] for entry in files if not entry.get("optional")),
            "raw/serial.log",
            *evidence_artifacts,
        ],
        "evidence_artifacts": evidence_artifacts,
        "known_limitations": [
            (
                "Focused Part A decides only conditional frequency-only Part B promotion; "
                "it never authorizes phase or hybrid actuation."
                if focused_campaign
                else "Finite survey prefix only; full Part A map and Part B remain incomplete."
            ),
            "D10 remains an external event input and has no PPS or control role.",
        ],
    }
    _atomic_new_json(run_dir / "run_manifest.json", manifest)


def _flash(
    *, run_dir: Path, bundle: dict[str, Any], device: str, board: dict[str, str], arduino_cli: str
) -> tuple[str, dict[str, str]]:
    command = [
        arduino_cli,
        "upload",
        "--port",
        device,
        "--fqbn",
        bundle["firmware"]["fqbn"],
        "--input-file",
        bundle["firmware"]["uf2"]["path"],
    ]
    started = _utc_now()
    completed = subprocess.run(
        command, text=True, capture_output=True, check=False, timeout=120
    )
    device_after: str | None = None
    board_after: dict[str, str] | None = None
    if completed.returncode == 0:
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            try:
                device_after, board_after = _locate_board(
                    bundle["device"]["expected_board_serial"],
                    arduino_cli=arduino_cli,
                )
                break
            except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
                time.sleep(0.5)
    passed = (
        completed.returncode == 0
        and device_after is not None
        and board_after is not None
        and board.get("serial_number")
        == board_after.get("serial_number")
        == bundle["device"]["expected_board_serial"]
    )
    unsigned = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "operation": "exact_range_map_firmware_flash",
        "status": "passed" if passed else "failed",
        "started_utc": started,
        "completed_utc": _utc_now(),
        "command": command,
        "exit_code": completed.returncode,
        "stdout_sha256": sha256(completed.stdout.encode()).hexdigest(),
        "stderr_sha256": sha256(completed.stderr.encode()).hexdigest(),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
        "device_before": device,
        "device_after": device_after,
        "board_before": board,
        "board_after": board_after,
        "uf2_sha256": bundle["firmware"]["uf2"]["sha256"],
        "profile_id": bundle["firmware"]["profile_id"],
        "firmware_flash_count": 1,
        "dac_value_write_attempts": 0,
    }
    _atomic_new_json(
        run_dir / ENTRY_RECORD,
        {**unsigned, "record_sha256": canonical_sha256(unsigned)},
    )
    if not passed:
        raise RuntimeError("exact firmware upload or board re-enumeration failed")
    return device_after, board_after


def _confirm_running_attachment(
    *, run_dir: Path, bundle: dict[str, Any], device: str, board: dict[str, str]
) -> tuple[str, dict[str, str]]:
    entry = bundle["entry"]
    passed = (
        entry.get("mode") == "state_preserving_running_attach"
        and int(entry.get("firmware_flashes_allowed", -1)) == 0
        and int(entry.get("board_resets_allowed", -1)) == 0
        and board.get("serial_number") == bundle["device"]["expected_board_serial"]
        and board.get("address") == device
    )
    unsigned = {
        "schema_version": 2,
        "tool": TOOL_ID,
        "operation": "confirmed_installed_firmware_running_attachment",
        "status": "passed" if passed else "failed",
        "recorded_utc": _utc_now(),
        "device": device,
        "board": board,
        "profile_id": bundle["firmware"]["profile_id"],
        "uf2_sha256": bundle["firmware"]["uf2"]["sha256"],
        "predecessor_run_id": entry.get("predecessor_run_id"),
        "predecessor_snapshot_digest": entry.get("predecessor_snapshot_digest"),
        "attachment_mode": "running_instrument",
        "firmware_flash_count": 0,
        "board_reset_count": 0,
        "ordinary_restart_count": 0,
        "serial_open_count": 0,
        "dac_value_write_attempts": 0,
    }
    _atomic_new_json(
        run_dir / ENTRY_RECORD,
        {**unsigned, "record_sha256": canonical_sha256(unsigned)},
    )
    if not passed:
        raise RuntimeError("running attachment identity confirmation failed")
    return device, board


def _latest_health(run_dir: Path) -> dict[tuple[str, str], str]:
    values: dict[tuple[str, str], str] = {}
    for row in _read_csv(run_dir / "csv/health.csv"):
        values[(row.get("component", ""), row.get("status_key", ""))] = row.get(
            "status_value", ""
        )
    return values


def _prewrite_ready(run_dir: Path, bundle: dict[str, Any]) -> tuple[bool, list[str]]:
    health = _latest_health(run_dir)
    expected = {
        ("build", "profile_id"): "cx319_range_map_part_a",
        ("firmware", "git_commit"): bundle["firmware"]["git_commit"],
        ("firmware", "source_hash"): bundle["firmware"]["source_sha256"],
        ("firmware", "config_hash"): bundle["firmware"]["configuration_sha256"],
        ("build", "invocation_id"): bundle["firmware"]["build_invocation_id"],
        ("gnss_receiver", "identity_stable"): "true",
        ("gnss_receiver", "metadata_control_eligible"): "true",
        ("gnss_receiver", "raw_pps_control_eligible"): "true",
        ("dual_core", "partition_fault"): "none",
        ("dual_core", "fail_static"): "false",
        ("dual_core", "service_publish_failures"): "0",
        ("dual_core", "telemetry_dropped"): "0",
    }
    missing = [
        f"{component}.{key}={health.get((component, key))!r} expected {value!r}"
        for (component, key), value in expected.items()
        if health.get((component, key)) != value
    ]
    capture = _read_json(run_dir / "reports/capture_device_state.json") or {}
    for key in ("parser_errors", "reconnect_count", "commands_rejected"):
        if int(capture.get(key, 0)) != 0:
            missing.append(f"capture.{key}={capture.get(key)!r} expected 0")
    if len(_read_csv(run_dir / "csv/count_observations.csv")) < 5:
        missing.append("fewer_than_five_current_d8_count_observations")
    hybrid_rows = _read_csv(run_dir / "csv/hybrid_preview_decisions_v1.csv")
    if not hybrid_rows:
        missing.append("hybrid_preview_prewrite_identity_absent")
    elif any(
        hybrid_rows[-1].get(field) != "false"
        for field in ("actionable", "actuation_authorized", "authorization_consumed")
    ):
        missing.append("hybrid_preview_prewrite_authority_contamination")
    entry = bundle.get("entry", {})
    if entry.get("mode") == "state_preserving_running_attach":
        live = entry["expected_live_state"]
        expected_continuation_health = {
            ("dac", "initialized"): "true",
            ("dac", "applied_code_known"): "true",
            ("dac", "last_write_ok"): "true",
            ("dac", "last_requested_code"): live["applied_code_hex"],
            ("dac", "last_applied_code"): live["applied_code_hex"],
            ("cx318_preview", "applied_code"): live["applied_code_hex"],
            ("cx318_preview", "dac_epoch"): str(live["dac_epoch"]),
        }
        missing.extend(
            f"{component}.{key}={health.get((component, key))!r} expected {value!r}"
            for (component, key), value in expected_continuation_health.items()
            if health.get((component, key)) != value
        )
        latest_hybrid = hybrid_rows[-1] if hybrid_rows else {}
        if not (
            latest_hybrid.get("actual_applied_code") == str(live["applied_code"])
            and latest_hybrid.get("dac_epoch") == str(live["dac_epoch"])
            and latest_hybrid.get("band_state_after")
            == live["hybrid_band_state"]
        ):
            missing.append("hybrid_preview_predecessor_state_not_observed")
        tdb_rows = _read_csv(run_dir / "csv/tight_deadband_decisions_v1.csv")
        latest_tdb = tdb_rows[-1] if tdb_rows else {}
        if not (
            latest_tdb.get("dac_epoch") == str(live["dac_epoch"])
            and latest_tdb.get("state_after") == live["band_state"]
            and latest_tdb.get("actionable") == "false"
            and latest_tdb.get("actuation_authorized") == "false"
            and latest_tdb.get("authorization_consumed") == "false"
        ):
            missing.append("tight_deadband_predecessor_state_not_observed")
    return not missing, missing


def _runtime_fault(run_dir: Path, *, require_qualified_health: bool = False) -> str | None:
    capture = _read_json(run_dir / "reports/capture_device_state.json") or {}
    if not capture:
        return None
    try:
        updated = _parse_utc(str(capture["updated_utc"]))
    except (KeyError, TypeError, ValueError):
        return "capture_state_timestamp_invalid"
    age_s = (datetime.now(timezone.utc) - updated).total_seconds()
    if age_s < -1.0 or age_s > CAPTURE_STATE_MAX_AGE_S:
        return f"capture_state_stale_age_{age_s:.3f}s"
    exact_capture = {
        "capture_active": True,
        "serial_open": True,
        "command_fifo_configured": True,
        "emergency_command_fifo_configured": True,
        "state_heartbeat_interval_s": 5.0,
        "normal_command_batch_limit": 1,
        "normal_command_max_age_s": 2.0,
        "write_timeout_s": 1.0,
    }
    for key, expected in exact_capture.items():
        if capture.get(key) != expected:
            return f"capture_{key}_{capture.get(key)!r}"
    for key in (
        "malformed_utf8",
        "parser_errors",
        "reconnect_count",
        "commands_rejected",
        "emergency_aborts_sent",
    ):
        if int(capture.get(key, 0)) != 0:
            return f"capture_{key}_{capture.get(key)}"
    serial_log = run_dir / "raw/serial.log"
    if serial_log.is_file():
        evidence_age_s = time.time() - serial_log.stat().st_mtime
        if evidence_age_s < -1.0 or evidence_age_s > RETAINED_SERIAL_MAX_AGE_S:
            return f"retained_serial_stale_age_{evidence_age_s:.3f}s"
    health = _latest_health(run_dir)
    required_health = {
        ("gnss_receiver", "identity_stable"): "true",
        ("gnss_receiver", "metadata_control_eligible"): "true",
        ("gnss_receiver", "raw_pps_control_eligible"): "true",
        ("dual_core", "partition_fault"): "none",
        ("dual_core", "fail_static"): "false",
        ("dual_core", "service_publish_failures"): "0",
        ("dual_core", "telemetry_dropped"): "0",
        ("capture", "dropped_count"): "0",
        ("capture", "pps_count_boundary_dropped_count"): "0",
    }
    for identity, expected in required_health.items():
        observed = health.get(identity)
        if identity[0] == "gnss_receiver" and not require_qualified_health:
            continue
        if observed is None and not require_qualified_health:
            continue
        if observed != expected:
            return f"health_{identity[0]}_{identity[1]}_{observed!r}"
    return None


def _wait(
    predicate: Callable[[], Any],
    *,
    timeout_s: float,
    description: str,
    run_dir: Path,
    wall_deadline: datetime,
    require_qualified_health: bool = False,
) -> Any:
    deadline = min(
        time.monotonic() + timeout_s,
        time.monotonic() + max(0.0, (wall_deadline - datetime.now(timezone.utc)).total_seconds()),
    )
    next_update = time.monotonic()
    while time.monotonic() < deadline:
        fault = _runtime_fault(
            run_dir, require_qualified_health=require_qualified_health
        )
        if fault is not None:
            raise RuntimeError(f"runtime stop rule: {fault}")
        value = predicate()
        if value:
            return value
        if time.monotonic() >= next_update:
            print(f"STATUS waiting for {description} at {_utc_now()}", flush=True)
            next_update = time.monotonic() + 60.0
        time.sleep(0.2)
    raise TimeoutError(f"timed out waiting for {description}")


def _find_exact_dac(run_dir: Path, *, after_sequence: int, code: int) -> dict[str, str] | None:
    for row in _read_csv(run_dir / "csv/dac_steps.csv"):
        try:
            sequence = int(row.get("seq", ""))
        except ValueError:
            continue
        if sequence <= after_sequence:
            continue
        if (
            row.get("event") == "manual_apply"
            and int(row.get("dac_code_requested", -1)) == code
            and int(row.get("dac_code_applied", -1)) == code
            and row.get("dac_code_clamped") == "0"
        ):
            return row
    return None


def _find_epoch_propagation(
    run_dir: Path, *, after_preview_sequence: int, after_epoch: int, code: int
) -> dict[str, str] | None:
    for row in _read_csv(run_dir / "csv/hybrid_preview_decisions_v1.csv"):
        try:
            sequence = int(row.get("preview_sequence", ""))
        except ValueError:
            continue
        if sequence <= after_preview_sequence:
            continue
        if (
            int(row.get("actual_applied_code", -1)) != code
            or int(row.get("dac_epoch", -1)) <= after_epoch
        ):
            continue
        if any(
            row.get(field) != "false"
            for field in ("actionable", "actuation_authorized", "authorization_consumed")
        ):
            raise RuntimeError("hybrid authority contamination")
        return row
    return None


def _point_tdb_rows(
    run_dir: Path, *, after_sequence: int, epoch: int
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for row in _read_csv(run_dir / "csv/tight_deadband_decisions_v1.csv"):
        try:
            sequence = int(row.get("decision_sequence", ""))
        except ValueError:
            continue
        if sequence <= after_sequence or int(row.get("dac_epoch", -1)) != epoch:
            continue
        if any(
            row.get(field) != "false"
            for field in ("actionable", "actuation_authorized", "authorization_consumed")
        ):
            raise RuntimeError("tight-deadband authority contamination")
        result.append(row)
    return result


def _adaptive_point_rows(
    rows: list[dict[str, str]], *, minimum: int, maximum: int
) -> tuple[list[dict[str, str]] | None, str]:
    """Select the frozen 2/4/6 support without inspecting future records.

    Boundary points stop at four observations when all absolute integer counts
    lie on one side of the TDB entry/outside boundary.  A mix of <=2 and >=3
    extends that same DAC epoch to six observations.  Fixed points have equal
    minimum and maximum sizes.
    """

    if minimum < 2 or maximum < minimum or maximum > 6:
        raise ValueError("invalid frozen point observation bounds")
    if len(rows) < minimum:
        return None, "awaiting_minimum"
    selected = rows[:minimum]
    if minimum == maximum:
        return selected, "fixed_minimum"
    absolute_counts = [abs(int(row["integer_edge_error_counts"])) for row in selected]
    mixed = any(value <= 2 for value in absolute_counts) and any(
        value >= 3 for value in absolute_counts
    )
    if not mixed:
        return selected, "minimum_unmixed"
    if len(rows) < maximum:
        return None, "awaiting_mixed_extension"
    return rows[:maximum], "maximum_mixed_extension"


def _exact_estimates_present(run_dir: Path, rows: list[dict[str, str]]) -> bool:
    estimates = {
        row.get("estimate_id", ""): row
        for row in _read_csv(run_dir / "csv/estimates_v2.csv")
    }
    return all(
        row.get("estimate_id") in estimates
        and estimates[row["estimate_id"]].get("estimator_version")
        == "cx317_selected_600s_nonoverlap_v1"
        and estimates[row["estimate_id"]].get("observation_validity") == "valid"
        and estimates[row["estimate_id"]].get("manifest_ref")
        == "firmware_config:cx319_range_map_part_a"
        for row in rows
    )


def _markers(path: Path) -> list[dict[str, Any]]:
    prefix = "# OTIS_HOST "
    result: list[dict[str, Any]] = []
    if not path.is_file():
        return result
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith(prefix):
                try:
                    result.append(json.loads(line[len(prefix) :]))
                except json.JSONDecodeError:
                    pass
    return result


def _abort_delivery(emergency_fifo: Path, run_dir: Path) -> None:
    send_command_to_fifo(emergency_fifo, "ACTIVE ABORT")
    deadline = time.monotonic() + TERMINAL_ABORT_DELIVERY_TIMEOUT_S
    while time.monotonic() < deadline:
        if any(
            marker.get("event") == "emergency_abort_sent"
            for marker in _markers(run_dir / "raw/serial.log")
        ):
            return
        time.sleep(0.1)
    raise RuntimeError("priority abort delivery was not recorded")


def _write_complete(run_dir: Path, terminal: dict[str, Any]) -> None:
    payload = (
        json.dumps(
            {"completed_utc": _utc_now(), "terminal": terminal}, sort_keys=True
        )
        + "\n"
    ).encode("utf-8")
    descriptor = os.open(run_dir / "COMPLETE", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        if os.write(descriptor, payload) != len(payload):
            raise OSError("short COMPLETE write")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def run(
    *,
    bundle_path: Path,
    run_dir: Path,
    wall_deadline_utc: str,
    evidence_index_path: Path,
    arduino_cli: str,
) -> dict[str, Any]:
    bundle_path = bundle_path.resolve()
    bundle = validate_bundle(bundle_path)
    run_dir = run_dir.resolve()
    deadline = _parse_utc(wall_deadline_utc)
    if (deadline - datetime.now(timezone.utc)).total_seconds() < 2400:
        raise ValueError("live deadline must leave at least 2400 seconds")
    if run_dir.exists():
        raise FileExistsError(f"run directory already exists: {run_dir}")
    run_dir.mkdir(parents=True)
    (run_dir / "reports").mkdir()
    activation = _create_activation(
        bundle_path=bundle_path, bundle=bundle, deadline=deadline, run_dir=run_dir
    )
    _atomic_new_json(run_dir / ACTIVATION, activation)
    state: dict[str, Any] = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "run_id": run_dir.name,
        "bundle_sha256": bundle["bundle_sha256"],
        "activation_sha256": activation["activation_sha256"],
        "wall_deadline_utc": wall_deadline_utc,
        "phase": "bundle_activated",
        "completed_points": [],
        "terminal": None,
    }
    _replace_json(run_dir / STATE, state)
    _append_event(run_dir / EVENTS, {"event": "bundle_activated", **activation})
    print(f"MILESTONE exact bundle activated {activation['activation_sha256']}", flush=True)

    device, board = _locate_board(
        bundle["device"]["expected_board_serial"], arduino_cli=arduino_cli
    )
    owners = _serial_owner_pids(device)
    if owners:
        raise ValueError(f"serial device already has owners: {sorted(owners)}")
    if bundle["entry"]["mode"] == "fresh_exact_firmware_flash":
        device, board = _flash(
            run_dir=run_dir,
            bundle=bundle,
            device=device,
            board=board,
            arduino_cli=arduino_cli,
        )
        print(
            f"MILESTONE firmware flashed profile={bundle['firmware']['profile_id']} "
            f"uf2={bundle['firmware']['uf2']['sha256']}",
            flush=True,
        )
    elif bundle["entry"]["mode"] == "state_preserving_running_attach":
        device, board = _confirm_running_attachment(
            run_dir=run_dir, bundle=bundle, device=device, board=board
        )
        print(
            "MILESTONE exact installed firmware confirmed; no flash or reset performed",
            flush=True,
        )
    else:
        raise ValueError(f"unsupported firmware entry mode: {bundle['entry']['mode']}")
    _create_manifest(
        run_dir=run_dir, bundle_path=bundle_path, bundle=bundle, device=device
    )
    normal_fifo = run_dir / "control/normal_commands.fifo"
    emergency_fifo = run_dir / "control/emergency_abort.fifo"
    capture_log_handle = (run_dir / CAPTURE_LOG).open("x", encoding="utf-8")
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
            str(max(60.0, (deadline - datetime.now(timezone.utc)).total_seconds() + 180.0)),
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
        ],
        cwd=Path(__file__).resolve().parents[2],
        stdout=capture_log_handle,
        stderr=capture_log_handle,
        text=True,
    )
    terminal: dict[str, Any] | None = None
    try:
        _wait(
            lambda: _capture_state_ready(run_dir, capture.pid),
            timeout_s=30,
            description="sole-owner capture start",
            run_dir=run_dir,
            wall_deadline=deadline,
        )
        if _serial_owner_pids(device) != {capture.pid}:
            raise RuntimeError("capture is not the sole serial owner")
        for command in bundle["command_envelope"]["prewrite_queries"]:
            send_timestamped_command_to_fifo(normal_fifo, command)
        print("MILESTONE serial capture established; prewrite gate running", flush=True)
        state["phase"] = "prewrite_gate"
        _replace_json(run_dir / STATE, state)

        def prewrite() -> bool:
            ready, _reasons = _prewrite_ready(run_dir, bundle)
            return ready

        _wait(
            prewrite,
            timeout_s=720,
            description="exact firmware, GNSS, D14, D8, and partition prewrite gate",
            run_dir=run_dir,
            wall_deadline=deadline,
        )
        ready, reasons = _prewrite_ready(run_dir, bundle)
        if not ready:
            raise RuntimeError("prewrite gate regressed: " + "; ".join(reasons))
        _append_event(run_dir / EVENTS, {"event": "prewrite_gate_passed"})
        if bundle["entry"]["mode"] == "state_preserving_running_attach":
            live = bundle["entry"]["expected_live_state"]
            _append_event(
                run_dir / EVENTS,
                {
                    "event": "state_preserving_attachment_passed",
                    "predecessor_run_id": bundle["entry"]["predecessor_run_id"],
                    "applied_code": live["applied_code"],
                    "dac_epoch": live["dac_epoch"],
                    "band_state": live["band_state"],
                    "next_code": live["next_code"],
                    "firmware_flash_count": 0,
                    "board_reset_count": 0,
                },
            )
            print(
                f"MILESTONE preserved state confirmed code={live['applied_code_hex']} "
                f"epoch={live['dac_epoch']} state={live['band_state']}",
                flush=True,
            )
        print("MILESTONE live prewrite gate passed", flush=True)
        state["phase"] = "survey"
        _replace_json(run_dir / STATE, state)

        point_plans = bundle["part_a_segment"].get("point_plans")
        if point_plans is None:
            point_plans = [
                {
                    "code": code,
                    "role": "survey_point",
                    "minimum_observations": bundle["part_a_segment"][
                        "fresh_policy_observations_per_point"
                    ],
                    "maximum_observations": bundle["part_a_segment"][
                        "fresh_policy_observations_per_point"
                    ],
                }
                for code in bundle["part_a_segment"]["survey_prefix"]
            ]
        for point_index, point_plan in enumerate(point_plans):
            code = int(point_plan["code"])
            minimum_observations = int(point_plan["minimum_observations"])
            maximum_observations = int(point_plan["maximum_observations"])
            global_point_index = (
                int(bundle["part_a_segment"].get("global_point_offset", 0))
                + point_index
            )
            remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
            if remaining < bundle["part_a_segment"]["minimum_remaining_wall_before_new_point_s"]:
                terminal = {
                    "event": "terminal",
                    "result": "healthy_stop",
                    "reason": "finite_wall_deadline_before_next_point",
                    "completed_point_count": len(state["completed_points"]),
                }
                break
            dac_rows = _read_csv(run_dir / "csv/dac_steps.csv")
            tdb_rows = _read_csv(run_dir / "csv/tight_deadband_decisions_v1.csv")
            hybrid_rows = _read_csv(run_dir / "csv/hybrid_preview_decisions_v1.csv")
            prior_dac = max((int(row["seq"]) for row in dac_rows), default=-1)
            prior_tdb = max(
                (int(row["decision_sequence"]) for row in tdb_rows), default=-1
            )
            prior_hybrid = max(
                (int(row["preview_sequence"]) for row in hybrid_rows), default=-1
            )
            prior_epoch = max(
                (int(row["dac_epoch"]) for row in hybrid_rows), default=-1
            )
            command = f"DAC SET 0x{code:04X}"
            send_timestamped_command_to_fifo(normal_fifo, command)
            _append_event(
                run_dir / EVENTS,
                {
                    "event": "point_command_sent",
                    "point_index": point_index,
                    "global_point_index": global_point_index,
                    "code": code,
                    "role": point_plan["role"],
                    "minimum_observations": minimum_observations,
                    "maximum_observations": maximum_observations,
                    "command": command,
                },
            )
            print(
                f"MILESTONE point {point_index + 1} command sent code=0x{code:04X}",
                flush=True,
            )
            dac = _wait(
                lambda: _find_exact_dac(run_dir, after_sequence=prior_dac, code=code),
                timeout_s=15,
                description=f"point {point_index + 1} exact DAC acknowledgement",
                run_dir=run_dir,
                wall_deadline=deadline,
                require_qualified_health=True,
            )
            propagation = _wait(
                lambda: _find_epoch_propagation(
                    run_dir,
                    after_preview_sequence=prior_hybrid,
                    after_epoch=prior_epoch,
                    code=code,
                ),
                timeout_s=30,
                description=f"point {point_index + 1} cross-core preview propagation",
                run_dir=run_dir,
                wall_deadline=deadline,
                require_qualified_health=True,
            )
            epoch = int(propagation["dac_epoch"])
            _append_event(
                run_dir / EVENTS,
                {
                    "event": "point_application_acknowledged",
                    "point_index": point_index,
                    "global_point_index": global_point_index,
                    "code": code,
                    "dac_sequence": int(dac["seq"]),
                    "dac_epoch": epoch,
                },
            )
            print(
                f"MILESTONE point {point_index + 1} applied code=0x{code:04X} epoch={epoch}",
                flush=True,
            )

            observation_decision = "awaiting_minimum"

            def selected_rows() -> list[dict[str, str]] | None:
                nonlocal observation_decision
                selected, observation_decision = _adaptive_point_rows(
                    _point_tdb_rows(
                        run_dir, after_sequence=prior_tdb, epoch=epoch
                    ),
                    minimum=minimum_observations,
                    maximum=maximum_observations,
                )
                return selected

            rows = _wait(
                selected_rows,
                timeout_s=bundle["part_a_segment"]["point_wait_timeout_s"],
                description=(
                    f"point {point_index + 1} frozen {minimum_observations}"
                    f"..{maximum_observations} fresh selected600 policy observations"
                ),
                run_dir=run_dir,
                wall_deadline=deadline,
                require_qualified_health=True,
            )
            if not _exact_estimates_present(run_dir, rows):
                raise RuntimeError("selected estimate identity did not reach TDB consumer")
            result = {
                "point_index": point_index,
                "global_point_index": global_point_index,
                "code": code,
                "code_hex": f"0x{code:04X}",
                "role": point_plan["role"],
                "minimum_observations": minimum_observations,
                "maximum_observations": maximum_observations,
                "observation_rule_decision": observation_decision,
                "dac_sequence": int(dac["seq"]),
                "dac_epoch": epoch,
                "tdb_sequences": [int(row["decision_sequence"]) for row in rows],
                "integer_edge_error_counts": [
                    int(row["integer_edge_error_counts"]) for row in rows
                ],
                "state_after": rows[-1]["state_after"],
                "reason": rows[-1]["reason_codes"],
            }
            state["completed_points"].append(result)
            _append_event(run_dir / EVENTS, {"event": "point_completed", **result})
            _replace_json(run_dir / STATE, state)
            print(
                f"MILESTONE point {point_index + 1} complete code=0x{code:04X} "
                f"counts={result['integer_edge_error_counts']} state={result['state_after']}",
                flush=True,
            )
        if terminal is None:
            terminal = {
                "event": "terminal",
                "result": "healthy_stop",
                "reason": "survey_prefix_complete",
                "completed_point_count": len(state["completed_points"]),
            }
    except Exception as exc:
        terminal = {
            "event": "terminal",
            "result": "aborted",
            "reason": str(exc),
            "error_type": type(exc).__name__,
            "completed_point_count": len(state["completed_points"]),
        }
        try:
            _abort_delivery(emergency_fifo, run_dir)
            terminal["priority_abort_delivery"] = "sent"
        except Exception as abort_exc:
            terminal["priority_abort_delivery"] = "failed"
            terminal["priority_abort_error"] = str(abort_exc)
    finally:
        assert terminal is not None
        if capture.poll() is None:
            capture.send_signal(signal.SIGINT)
        try:
            capture.wait(timeout=30)
        except subprocess.TimeoutExpired:
            capture.terminate()
            capture.wait(timeout=10)
        capture_log_handle.close()
        if capture.returncode != 0:
            terminal = {
                "event": "terminal",
                "result": "aborted",
                "reason": f"capture_process_exit_{capture.returncode}",
                "completed_point_count": len(state["completed_points"]),
                "prior_terminal": terminal,
            }
        _append_event(run_dir / EVENTS, terminal)
        state["terminal"] = terminal
        state["phase"] = "terminal"
        _replace_json(run_dir / STATE, state)

    _write_complete(run_dir, terminal)
    analysis = analyze(
        bundle_path=bundle_path,
        run_dir=run_dir,
        output_path=run_dir / ANALYSIS,
        seal_path=run_dir / SEAL,
    )
    promotion: dict[str, Any] | None = None
    if bundle.get("bundle_type") == "cx319_conditional_fine_map_part_a_bundle_v2":
        from .conditional_part_a_promotion import create_promotion

        promotion = create_promotion(
            bundle_path=bundle_path,
            run_dir=run_dir,
            output_path=run_dir / "reports/conditional_part_a_promotion_v2.json",
        )
        print(
            f"MILESTONE Part A promotion decision={promotion['status']} "
            f"identity={promotion['promotion_sha256']}",
            flush=True,
        )
    evidence_finalization: dict[str, Any]
    try:
        snapshot = _create_validated_evidence_snapshot(run_dir)
        evidence_finalization = {
            "status": "passed",
            "snapshot_digest": snapshot["snapshot_digest"],
        }
    except Exception as exc:
        failure_unsigned = {
            "schema_version": 1,
            "tool": TOOL_ID,
            "status": "failed",
            "recorded_utc": _utc_now(),
            "run_id": run_dir.name,
            "error_type": type(exc).__name__,
            "reason": str(exc),
            "raw_capture_preserved": (run_dir / "raw/serial.log").is_file(),
            "analysis_status": analysis["status"],
            "terminal_result": terminal["result"],
            "terminal_reason": terminal["reason"],
        }
        evidence_finalization = {
            **failure_unsigned,
            "record_sha256": canonical_sha256(failure_unsigned),
        }
        _atomic_new_json(run_dir / FINALIZATION_FAILURE, evidence_finalization)
    record = register_package(
        index_path=evidence_index_path.resolve(),
        package_path=run_dir,
        source_revision=bundle["firmware"]["git_commit"],
        build_identity=bundle["firmware"]["build_manifest"]["sha256"],
        profile_identity=bundle["firmware"]["profile_id"],
        attempt_classification=(
            "completed_campaign"
            if terminal["result"] == "healthy_stop" and analysis["status"] == "passed"
            else "interrupted_campaign"
        ),
        result_or_failure_reason=f"CX319 Part A segment: {terminal['reason']}",
        analyzer_identity=sha256_file(Path(__file__).with_name("range_spanning_analyze.py")),
    )
    print(
        f"MILESTONE run terminal result={terminal['result']} reason={terminal['reason']} "
        f"points={len(state['completed_points'])} evidence={record['content_sha256']} "
        f"finalization={evidence_finalization['status']}",
        flush=True,
    )
    return {
        "terminal": terminal,
        "analysis": analysis,
        "promotion": promotion,
        "evidence_finalization": evidence_finalization,
        "evidence_index_record": record,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--wall-deadline-utc", required=True)
    parser.add_argument("--evidence-index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--arduino-cli", default="arduino-cli")
    args = parser.parse_args(argv)
    result = run(
        bundle_path=args.bundle,
        run_dir=args.run_dir,
        wall_deadline_utc=args.wall_deadline_utc,
        evidence_index_path=args.evidence_index,
        arduino_cli=args.arduino_cli,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(
        0
        if result["terminal"]["result"] == "healthy_stop"
        and result["analysis"]["status"] == "passed"
        and result["evidence_finalization"]["status"] == "passed"
        else 1
    )


if __name__ == "__main__":
    main()
