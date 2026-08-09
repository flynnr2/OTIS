"""Latch and enqueue the sole authorized CX318 Stage 4 A828 setup attempt."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import csv
import json
import os
import subprocess
from typing import Any

from .run_loader import CAPTURE_IN_PROGRESS_FLAG, load_manifest
from .serial_commands import send_timestamped_command_to_fifo
from .service_plane_probe import HOST_MARKER_PREFIX


EXPECTED_STAGE = "CX318_STAGE4_STATIC_CODE_SETUP"
EXPECTED_PRECOMMANDS = ("CONFIG?", "DUALCORE?", "DAC?")
COMMAND = "DAC SET 0xA828"
LATCH_PATH = Path("control/premise_attempt_latch.json")
CAMPAIGN_LATCH_PATH = Path("CX318_STAGE4_PREMISE_ATTEMPT_LATCH.json")
TOOL_ID = "cx318_stage4_premise_attempt_latch_v1"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _sent_commands(raw_log: Path) -> tuple[str, ...]:
    accepted: list[str] = []
    sent: list[str] = []
    with raw_log.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.rstrip("\r\n")
            if not line.startswith(HOST_MARKER_PREFIX):
                continue
            marker = json.loads(line[len(HOST_MARKER_PREFIX) :])
            event = marker.get("event")
            if event == "host_command_accepted":
                accepted.append(str(marker.get("command", "")))
            elif event == "host_command_sent":
                sent.append(str(marker.get("command", "")))
            elif event in {
                "host_command_rejected", "serial_disconnected", "parser_error",
                "malformed_utf8", "partial_line_dropped",
            }:
                raise ValueError(f"setup capture contains fault marker {event}")
    if accepted != sent:
        raise ValueError("accepted and sent setup command histories differ")
    return tuple(sent)


def _safe_precommand_health(rows: list[dict[str, str]]) -> None:
    latest: dict[tuple[str, str], str] = {}
    for row in rows:
        component = row["component"].strip()
        key = row["status_key"].strip()
        value = row["status_value"].strip()
        latest[(component, key)] = value
        lowered = value.lower()
        if key == "partition_fault" and lowered != "none":
            raise ValueError(f"unsafe precommand health {component}.{key}={value}")
        if key in {
            "fail_static", "actionable", "actuation_authorized",
            "authorization_consumed", "manual_start_confirmed", "arm_eligible",
        } and lowered == "true":
            raise ValueError(f"unsafe precommand health {component}.{key}={value}")
        if "dropped" in key or "overflow" in key or key.endswith("_drop_count"):
            try:
                nonzero = int(value, 0) != 0
            except ValueError:
                nonzero = True
            if nonzero:
                raise ValueError(f"unsafe precommand health {component}.{key}={value}")
    required = {
        ("build", "profile_id"): "cx318_stage4_premise_setup",
        ("build", "enable_cx318_stage4_premise_setup"): "1",
        ("build", "enable_cx318_stage4_preview"): "0",
        ("build", "enable_cx317_i_only_preview"): "0",
        ("build", "enable_cx317_bounded_active"): "0",
        ("build", "enable_dac_ad5693r"): "1",
        ("cx318_premise", "allowed_code"): "0xA828",
        ("cx318_premise", "write_consumed"): "false",
        ("cx318_premise", "actionable"): "false",
        ("cx318_premise", "actuation_authorized"): "false",
        ("cx318_premise", "automatic_authority"): "false",
        ("dac", "applied_code_known"): "false",
        ("dac", "last_write_ok"): "false",
        ("dac", "last_requested_code"): "0x0000",
        ("dac", "last_applied_code"): "unavailable",
    }
    mismatches = {
        f"{component}.{key}": {"expected": expected, "actual": latest.get((component, key))}
        for (component, key), expected in required.items()
        if latest.get((component, key)) != expected
    }
    if mismatches:
        raise ValueError("premise precommand health mismatch: " + json.dumps(mismatches, sort_keys=True))


def _campaign_root(run_dir: Path) -> Path:
    for candidate in (run_dir, *run_dir.parents):
        if (candidate / "PROGRAMME_STATE.md").is_file():
            return candidate
    raise ValueError("setup run is not inside the durable CX318 campaign ledger")


def _write_durable_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def latch_and_send(*, run_dir: Path, command_fifo: Path) -> Path:
    run_dir = run_dir.resolve()
    command_fifo = command_fifo.resolve()
    manifest = load_manifest(run_dir)
    if manifest.is_template or manifest.data.get("stage") != EXPECTED_STAGE:
        raise ValueError(f"run stage must be {EXPECTED_STAGE}")
    if not (run_dir / CAPTURE_IN_PROGRESS_FLAG).is_file():
        raise ValueError("setup capture is not active")
    state = json.loads(
        (run_dir / "reports/capture_device_state.json").read_text(encoding="utf-8")
    )
    required_state: dict[str, Any] = {
        "capture_active": True,
        "serial_open": True,
        "parser_errors": 0,
        "malformed_utf8": 0,
        "reconnect_count": 0,
        "commands_rejected": 0,
        "commands_sent": len(EXPECTED_PRECOMMANDS),
    }
    if any(state.get(key) != value for key, value in required_state.items()):
        raise ValueError("setup capture state is not ready: " + json.dumps(state, sort_keys=True))
    pid = int(state["pid"])
    device = str(manifest.data.get("host", {}).get("serial_device", ""))
    owners = subprocess.run(
        ["lsof", "-t", device], text=True, capture_output=True, check=False,
    )
    owner_pids = {int(value) for value in owners.stdout.split() if value.isdigit()}
    if owners.returncode != 0 or owner_pids != {pid}:
        raise ValueError(f"capture is not the sole serial owner: {sorted(owner_pids)}")
    if _sent_commands(run_dir / "raw/serial.log") != EXPECTED_PRECOMMANDS:
        raise ValueError("setup precommand sequence differs")
    if _rows(run_dir / "csv/dac_steps.csv"):
        raise ValueError("setup already contains a DAC row")
    if _rows(run_dir / "csv/active_transactions_v1.csv"):
        raise ValueError("setup already contains an active transaction")
    _safe_precommand_health(_rows(run_dir / "csv/health.csv"))

    environment = _rows(run_dir / "csv/environment.csv")
    sources = {row["source"].strip().lower() for row in environment}
    if not {"sht4x", "bmp280"} <= sources:
        raise ValueError(f"setup lacks both environment streams: {sorted(sources)}")
    snapshots = _rows(run_dir / "csv/pps_snapshots.csv")
    if len(snapshots) < 2:
        raise ValueError("setup has fewer than two precommand PPS snapshots")
    sessions = {int(row["session"]) for row in snapshots}
    sequences = [int(row["snapshot_sequence"]) for row in snapshots]
    references = [int(row["reference_sequence"]) for row in snapshots]
    if (
        len(sessions) != 1
        or any(row["status"].strip() != "0" for row in snapshots)
        or any(right != left + 1 for left, right in zip(sequences, sequences[1:]))
        or any(right != left + 1 for left, right in zip(references, references[1:]))
    ):
        raise ValueError("setup precommand PPS snapshots are not one qualified continuous session")
    counts = _rows(run_dir / "csv/count_observations.csv")
    count_sequences = [int(row["count_seq"]) for row in counts]
    if len(counts) < 2 or any(
        right != left + 1 for left, right in zip(count_sequences, count_sequences[1:])
    ):
        raise ValueError("setup precommand count stream is not continuous")

    campaign_root = _campaign_root(run_dir)
    existing = [
        path.resolve() for path in campaign_root.glob(f"**/{LATCH_PATH.as_posix()}")
    ]
    latch_path = run_dir / LATCH_PATH
    campaign_latch_path = campaign_root / CAMPAIGN_LATCH_PATH
    if campaign_latch_path.exists() or existing:
        raise FileExistsError(
            "a Stage 4 premise attempt is already latched: "
            + ", ".join(str(path) for path in [campaign_latch_path, *existing] if path.exists())
        )
    if command_fifo != run_dir / "control/commands.fifo":
        raise ValueError("command FIFO is not the exact run-local normal-command FIFO")
    payload = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "status": "attempt_latched_before_enqueue",
        "created_utc": _utc_now(),
        "run_id": run_dir.name,
        "command": COMMAND,
        "maximum_attempts": 1,
        "retry_authorized": False,
        "capture_pid": pid,
        "precommand_sequence": list(EXPECTED_PRECOMMANDS),
        "campaign_id": campaign_root.name,
        "campaign_latch_path": CAMPAIGN_LATCH_PATH.as_posix(),
    }
    campaign_payload = {
        **payload,
        "run_latch_path": latch_path.relative_to(campaign_root).as_posix(),
    }
    _write_durable_exclusive(campaign_latch_path, campaign_payload)
    # Both durable latches are intentionally retained even if enqueue fails.
    _write_durable_exclusive(latch_path, payload)
    send_timestamped_command_to_fifo(command_fifo, COMMAND)
    return latch_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--command-fifo", type=Path, required=True)
    args = parser.parse_args(argv)
    path = latch_and_send(run_dir=args.run_dir, command_fifo=args.command_fifo)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
