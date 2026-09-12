"""Explicit physical entry; the live runtime itself never flashes or resets."""
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from .adaptive_hybrid_contract import (
    BenchAttemptEnvelope,
    validate_bench_attempt_envelope,
)
from .capture_device import _detect_single_device, _serial_owner_pids
from .live_run import run_experiment
from .offline import finish_run
from .run_spec import authorize_entry, create_run_record, load_run_spec


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def read_board_identity(
    device: str,
    *,
    bench_attempt: BenchAttemptEnvelope,
    arduino_cli: str = "arduino-cli",
) -> dict[str, str]:
    """Read and bind the one accepted bench-board identity."""

    value = json.loads(
        subprocess.run(
            [arduino_cli, "board", "list", "--format", "json"],
            text=True,
            capture_output=True,
            check=True,
            timeout=15,
        ).stdout
    )
    matches = [
        item
        for item in value.get("detected_ports", [])
        if item.get("port", {}).get("address") == device
    ]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one board at {device}, got {len(matches)}")
    item = matches[0]
    port = item["port"]
    properties = port.get("properties", {})
    boards = item.get("matching_boards", [])
    identity = {
        "address": str(port.get("address", "")),
        "hardware_id": str(port.get("hardware_id", item.get("hardware_id", ""))),
        "serial_number": str(properties.get("serialNumber", "")),
        "vid": str(properties.get("vid", "")),
        "pid": str(properties.get("pid", "")),
        "product": str(properties.get("product", "")),
        "board_name": str(boards[0].get("name", "")) if len(boards) == 1 else "",
        "board_fqbn": str(boards[0].get("fqbn", "")) if len(boards) == 1 else "",
    }
    expected = bench_attempt.as_dict()["device_identity"]
    observed = {
        "expected_board_serial": identity["serial_number"],
        "expected_hardware_id": identity["hardware_id"],
        "expected_usb_vid": identity["vid"].upper().replace("0X", "0x"),
        "expected_usb_pid": identity["pid"].upper().replace("0X", "0x"),
        "expected_usb_product": identity["product"],
        "expected_board_name": identity["board_name"],
        "expected_base_fqbn": identity["board_fqbn"],
        "expected_compile_fqbn": expected["expected_compile_fqbn"],
    }
    if observed != expected:
        raise ValueError("connected board identity differs from the accepted OTIS bench board")
    return identity


def _upload_once(*, firmware: dict[str, Any], device: str, bench: BenchAttemptEnvelope,
                 run_dir: Path, arduino_cli: str) -> str:
    """One bounded upload with full retained output and exact board reappearance."""
    image = Path(firmware["uf2"]["path"])
    expected = firmware["uf2"]
    if (image.stat().st_size != expected["size_bytes"]
            or sha256(image.read_bytes()).hexdigest() != expected["sha256"]):
        raise ValueError("firmware bytes differ immediately before upload")
    before = read_board_identity(device, bench_attempt=bench, arduino_cli=arduino_cli)
    if _serial_owner_pids(device):
        raise ValueError("the serial device already has an owner")
    command = [arduino_cli, "upload", "--port", device, "--fqbn", firmware["fqbn"], "--input-file", str(image)]
    record: dict[str, Any] = {"command": command, "started_utc": _now(), "board_before": before,
                              "uf2_sha256": expected["sha256"], "flash_count": 1}
    with (run_dir / "reports/firmware_upload.log").open("x", encoding="utf-8") as output:
        try:
            process = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, text=True, timeout=120, check=False)
            record["exit_code"] = process.returncode
            if process.returncode:
                raise RuntimeError(f"firmware upload failed with exit {process.returncode}")
            deadline_ns = time.monotonic_ns() + 30_000_000_000
            last_error = "board did not reappear"
            while time.monotonic_ns() < deadline_ns:
                try:
                    after_device = _detect_single_device()
                    after = read_board_identity(after_device, bench_attempt=bench, arduino_cli=arduino_cli)
                    record.update(status="passed", board_after=after, device_after=after_device)
                    return after_device
                except (OSError, ValueError, subprocess.SubprocessError) as error:
                    last_error = str(error)
                    time.sleep(0.25)
            raise RuntimeError(last_error)
        except Exception as error:
            record.update(status="failed", error_type=type(error).__name__, error=str(error))
            raise
        finally:
            record["completed_utc"] = _now()
            _write_new(run_dir / "reports/firmware_entry.json", record)


def start(*, spec_path: Path, rehearsal_path: Path, run_dir: Path, device: str,
          operator_instruction_ref: str, attempt_reason: str, flash: bool = False,
          arduino_cli: str = "arduino-cli",
          firmware_manifest_path: Path | None = None,
          rehearsal_package_path: Path | None = None) -> dict[str, Any]:
    """Consume one reviewed entry and run one fresh physical acquisition."""
    spec = load_run_spec(spec_path)
    receipt = json.loads(rehearsal_path.read_text(encoding="utf-8"))
    capability = authorize_entry(spec, rehearsal_receipt=receipt,
                                 operator_instruction_ref=operator_instruction_ref,
                                 attempt_reason=attempt_reason,
                                 firmware_manifest_path=firmware_manifest_path,
                                 rehearsal_package_path=rehearsal_package_path)
    bench = validate_bench_attempt_envelope(spec.campaign["bench_attempt"])
    root = run_dir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / "reports").mkdir()
    retained_spec = root / "run_spec.json"
    with retained_spec.open("xb") as target:
        target.write(spec.path.read_bytes())
    consumed = capability.consume(spec.sha256)
    # Entry permission is retained before the first physical operation, including
    # an upload that fails before an acquisition can start.
    _write_new(root / "reports/physical_entry.json", {
        "run_spec_sha256": spec.sha256, "started_utc": _now(), "device_before": device,
        "operator_instruction_ref": operator_instruction_ref, "attempt_reason": attempt_reason,
        "rehearsal_receipt_sha256": receipt["receipt_sha256"], "flash_requested": flash,
    })
    read_board_identity(device, bench_attempt=bench, arduino_cli=arduino_cli)
    if _serial_owner_pids(device):
        raise ValueError("physical entry requires an unowned serial device")
    if flash:
        device = _upload_once(firmware=capability.firmware_artifact.document(), device=device, bench=bench,
                              run_dir=root, arduino_cli=arduino_cli)
    retained = load_run_spec(retained_spec)
    create_run_record(retained, execution_kind="physical", run_id=root.name,
                      started_at_utc=_now(), serial_device=device,
                      output_path=root / "run_manifest.json", consumed_entry=consumed)
    outcome = run_experiment(manifest_path=root / "run_manifest.json", device=device, physical=True)
    if outcome.get("status") == "terminal":
        outcome["evidence"] = finish_run(root)
    return outcome
