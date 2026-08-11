"""Prepare and request same-owner CX318 logical capture-segment rotation.

This tool writes only local manifest/control files.  It never opens the serial
device and never sends a firmware, DAC, active-control, or GPS command.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
from typing import Any

from .capture_device import (
    SEGMENT_CARRIER_STATE,
    SEGMENT_PROTOCOL_ID,
    SEGMENT_REQUEST,
    SEGMENT_RESPONSE_DIR,
    SEGMENT_TRANSITION_STAGE,
)


PROTOCOL_ID = SEGMENT_PROTOCOL_ID


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite segment artifact: {path}")
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
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


def prepare_transition(source_manifest: Path, run_dir: Path) -> Path:
    source_manifest = source_manifest.resolve()
    run_dir = run_dir.resolve()
    if run_dir.exists() and (not run_dir.is_dir() or any(run_dir.iterdir())):
        raise FileExistsError(f"transition run directory must be new or empty: {run_dir}")
    source = json.loads(source_manifest.read_text(encoding="utf-8"))
    host = source.get("host")
    if not isinstance(host, dict) or not isinstance(host.get("serial_device"), str):
        raise ValueError("source manifest lacks exact serial identity")
    files = source.get("files")
    contracts = source.get("contracts")
    if not isinstance(files, list) or not files or not isinstance(contracts, dict):
        raise ValueError("source manifest lacks capture contracts")
    run_dir.mkdir(parents=True, exist_ok=True)
    now = _utc_now()
    manifest = {
        "schema_version": 1,
        "template": False,
        "run_id": run_dir.name,
        "created_utc": now,
        "started_at_utc": now,
        "stage": SEGMENT_TRANSITION_STAGE,
        "h_phase": source.get("h_phase"),
        "board": source.get("board"),
        "capture_mode": source.get("capture_mode"),
        "actionable": False,
        "actuation_authorized": False,
        "host": {
            "capture_tool": "host.otis_tools.capture_device",
            "serial_device": host["serial_device"],
            "baud": int(host.get("baud", 115200)),
            "sole_serial_owner": True,
            "command_ingress": "forbidden",
            "rotation_protocol": PROTOCOL_ID,
            "source_manifest": {
                "path": str(source_manifest),
                "sha256": _sha256_file(source_manifest),
            },
        },
        "domains": deepcopy(source.get("domains", [])),
        "channels": deepcopy(source.get("channels", [])),
        "contracts": deepcopy(contracts),
        "files": deepcopy(files),
        "expected_artifacts": [
            *(str(item["path"]) for item in files if not item.get("optional")),
            "raw/serial.log",
            "reports/capture_device_state.json",
        ],
        "known_limitations": [
            "No-authority transition drainage only; this segment cannot satisfy a Stage 5 scientific gate."
        ],
    }
    path = run_dir / "run_manifest.json"
    _atomic_new_json(path, manifest)
    return path


def request_rotation(
    *,
    control_dir: Path,
    capability: str,
    to_run: Path,
    mode: str,
    command_fifo: Path | None = None,
    emergency_command_fifo: Path | None = None,
    wait_timeout_s: float = 10.0,
    operation_id: str | None = None,
) -> dict[str, Any]:
    if not capability:
        raise ValueError("segment capability must be non-empty")
    control_dir = control_dir.resolve()
    if operation_id is not None and not operation_id.strip():
        raise ValueError("segment operation_id must be non-empty when supplied")
    request_id = (
        sha256(f"{PROTOCOL_ID}:{operation_id}".encode("utf-8")).hexdigest()[:32]
        if operation_id is not None
        else secrets.token_hex(16)
    )
    response_path = control_dir / SEGMENT_RESPONSE_DIR / f"{request_id}.json"
    if response_path.is_file():
        response = json.loads(response_path.read_text(encoding="utf-8"))
        if response.get("status") != "completed":
            raise ValueError(f"segment rotation rejected: {response.get('error')}")
        if (
            Path(str(response.get("to_run", ""))).resolve() != to_run.resolve()
            or response.get("request_id") != request_id
        ):
            raise ValueError("stored segment rotation response differs from request")
        return response

    carrier_path = control_dir / SEGMENT_CARRIER_STATE
    carrier = json.loads(carrier_path.read_text(encoding="utf-8"))
    if carrier.get("status") != "running" or carrier.get("serial_open") is not True:
        raise ValueError("segment carrier is not running with serial open")
    to_run = to_run.resolve()
    manifest_path = to_run / "run_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("target segment manifest is unavailable")
    request: dict[str, Any] = {
        "schema_version": 1,
        "protocol": PROTOCOL_ID,
        "request_id": request_id,
        "created_utc": _utc_now(),
        "capability": capability,
        "expected_pid": int(carrier["pid"]),
        "expected_generation": int(carrier["transport_generation"]),
        "from_run": str(Path(carrier["current_run"]).resolve()),
        "to_run": str(to_run),
        "mode": mode,
        "expected_manifest_sha256": _sha256_file(manifest_path),
        "command_fifo": str(command_fifo.resolve()) if command_fifo else None,
        "emergency_command_fifo": (
            str(emergency_command_fifo.resolve()) if emergency_command_fifo else None
        ),
    }
    request_path = control_dir / SEGMENT_REQUEST
    if request_path.is_file():
        pending = json.loads(request_path.read_text(encoding="utf-8"))
        comparable = {
            key: value for key, value in request.items() if key != "created_utc"
        }
        observed = {
            key: value for key, value in pending.items() if key != "created_utc"
        }
        if observed != comparable:
            raise FileExistsError("a different segment rotation request is pending")
    else:
        _atomic_new_json(request_path, request)
    deadline = time.monotonic() + wait_timeout_s
    while time.monotonic() < deadline:
        if response_path.is_file():
            response = json.loads(response_path.read_text(encoding="utf-8"))
            if response.get("status") != "completed":
                raise ValueError(f"segment rotation rejected: {response.get('error')}")
            return response
        time.sleep(0.05)
    raise TimeoutError("timed out waiting for same-owner segment rotation")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-transition")
    prepare.add_argument("--source-manifest", type=Path, required=True)
    prepare.add_argument("--run-dir", type=Path, required=True)
    rotate = commands.add_parser("rotate")
    rotate.add_argument("--control-dir", type=Path, required=True)
    rotate.add_argument("--capability", required=True)
    rotate.add_argument("--to-run", type=Path, required=True)
    rotate.add_argument("--mode", choices=("transition", "live"), required=True)
    rotate.add_argument("--command-fifo", type=Path)
    rotate.add_argument("--emergency-command-fifo", type=Path)
    rotate.add_argument("--wait-timeout-s", type=float, default=10.0)
    rotate.add_argument("--operation-id")
    args = parser.parse_args(argv)
    if args.command == "prepare-transition":
        print(prepare_transition(args.source_manifest, args.run_dir))
        return 0
    if args.mode == "live" and (
        args.command_fifo is None or args.emergency_command_fifo is None
    ):
        parser.error("live rotation requires both command FIFOs")
    if args.mode == "transition" and (
        args.command_fifo is not None or args.emergency_command_fifo is not None
    ):
        parser.error("transition rotation forbids command FIFOs")
    response = request_rotation(
        control_dir=args.control_dir,
        capability=args.capability,
        to_run=args.to_run,
        mode=args.mode,
        command_fifo=args.command_fifo,
        emergency_command_fifo=args.emergency_command_fifo,
        wait_timeout_s=args.wait_timeout_s,
        operation_id=args.operation_id,
    )
    print(json.dumps(response, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
