"""Flash one exact zero-authority CX318 Stage 4 artifact and record lineage."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import json
import os
import subprocess
import tempfile
import time
from typing import Any

from tools.firmware_matrix import DEFAULT_MATRIX, load_matrix, source_input_hash


PROFILE_ID = "cx318_stage4_nonactuating_preview"
EXPECTED_SERIAL = "503533748A919118"
EXPECTED_VID = "0x2341"
EXPECTED_PID = "0x005E"
TOOL_ID = "cx318_stage4_exact_flash_v1"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _profile(matrix: dict[str, Any]) -> dict[str, Any]:
    matches = [item for item in matrix["profiles"] if item["id"] == PROFILE_ID]
    if len(matches) != 1 or matches[0].get("expect") != "pass":
        raise ValueError("matrix does not contain exactly one supported Stage 4 profile")
    return matches[0]


def validate_build_inputs(
    *, rebound_matrix_path: Path, build_manifest_path: Path, uf2_path: Path,
) -> dict[str, Any]:
    rebound_matrix_path = rebound_matrix_path.resolve()
    build_manifest_path = build_manifest_path.resolve()
    uf2_path = uf2_path.resolve()
    matrix = load_matrix(rebound_matrix_path)
    derivation = matrix.get("cx318_stage4_rebound_derivation", {})
    if not isinstance(derivation, dict):
        raise ValueError("matrix lacks the Stage 4 rebound derivation")
    tracked_base = DEFAULT_MATRIX.resolve()
    if (
        derivation.get("base_matrix_sha256") != _sha256_file(tracked_base)
        or derivation.get("exact_static_code") != 0xA828
        or derivation.get("exact_dac_epoch") != 1
    ):
        raise ValueError("rebound matrix is not derived from the exact tracked A828/epoch-1 contract")
    profile = _profile(matrix)
    defines = profile["defines"]
    safety = {
        "OTIS_ENABLE_CX318_STAGE4_PREVIEW": "1",
        "OTIS_CX318_STAGE4_STATIC_CODE": "0xA828u",
        "OTIS_CX318_STAGE4_DAC_EPOCH": "1u",
        "OTIS_ENABLE_DAC_AD5693R": "0",
        "OTIS_ENABLE_CX317_I_ONLY_PREVIEW": "0",
        "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": "0",
        "OTIS_ENABLE_H1_DAC_SWEEP": "0",
        "OTIS_GNSS_UART_TX_ENABLED": "0",
    }
    if any(defines.get(key) != value for key, value in safety.items()):
        raise ValueError("rebound profile violates the Stage 4 zero-authority contract")
    build = json.loads(build_manifest_path.read_text(encoding="utf-8"))
    provenance = build["provenance"]
    configuration = provenance["configuration"]
    source = provenance["source"]
    config_payload = {key: value for key, value in configuration.items() if key != "sha256"}
    if (
        configuration.get("profile_id") != PROFILE_ID
        or configuration.get("defines") != defines
        or configuration.get("sha256") != _canonical_sha256(config_payload)
        or source.get("state") != "clean"
        or source.get("sha256") != source_input_hash(matrix_path=rebound_matrix_path)
    ):
        raise ValueError("build provenance is not the exact clean rebound matrix input")
    current_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=DEFAULT_MATRIX.parents[2],
        text=True, capture_output=True, check=True,
    ).stdout.strip()
    current_status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=DEFAULT_MATRIX.parents[2], text=True, capture_output=True, check=True,
    ).stdout
    if source.get("git_commit") != current_commit or current_status:
        raise ValueError("repository no longer matches the exact clean build commit")
    matches = [item for item in build["artifacts"] if item.get("name") == uf2_path.name]
    if len(matches) != 1:
        raise ValueError("build manifest does not bind exactly one supplied UF2")
    artifact = matches[0]
    if (
        artifact.get("sha256") != _sha256_file(uf2_path)
        or artifact.get("size_bytes") != uf2_path.stat().st_size
    ):
        raise ValueError("supplied UF2 differs from the build manifest")
    return {
        "matrix_sha256": _sha256_file(rebound_matrix_path),
        "build_manifest_sha256": _sha256_file(build_manifest_path),
        "uf2_sha256": _sha256_file(uf2_path),
        "uf2_size_bytes": uf2_path.stat().st_size,
        "git_commit": current_commit,
        "source_sha256": source["sha256"],
        "configuration_sha256": configuration["sha256"],
        "fqbn": configuration["fqbn"],
        "build_invocation_id": provenance["invocation"]["id"],
    }


def read_board_identity(device: str, *, arduino_cli: str = "arduino-cli") -> dict[str, str]:
    value = json.loads(subprocess.run(
        [arduino_cli, "board", "list", "--format", "json"],
        text=True, capture_output=True, check=True,
    ).stdout)
    matches = [
        item for item in value.get("detected_ports", [])
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
        "hardware_id": str(item.get("hardware_id", "")),
        "serial_number": str(properties.get("serialNumber", "")),
        "vid": str(properties.get("vid", "")),
        "pid": str(properties.get("pid", "")),
        "product": str(properties.get("product", "")),
        "board_name": str(boards[0].get("name", "")) if len(boards) == 1 else "",
        "board_fqbn": str(boards[0].get("fqbn", "")) if len(boards) == 1 else "",
    }
    if (
        identity["serial_number"] != EXPECTED_SERIAL
        or identity["hardware_id"] != EXPECTED_SERIAL
        or identity["vid"].lower() != EXPECTED_VID.lower()
        or identity["pid"].lower() != EXPECTED_PID.lower()
        or identity["board_fqbn"] != "rp2040:rp2040:arduino_nano_connect"
    ):
        raise ValueError("connected board identity differs from the accepted CX317 bench board")
    return identity


def validate_flash_record(
    record: dict[str, Any], *, rebound_matrix_path: Path,
    build_manifest_path: Path, uf2_path: Path,
) -> dict[str, Any]:
    if record.get("schema_version") != 1 or record.get("tool") != TOOL_ID:
        raise ValueError("flash record schema/tool is invalid")
    if record.get("status") != "passed" or record.get("attempt_count") != 1:
        raise ValueError("flash record is not one successful attempt")
    binding = record.get("artifact_binding")
    expected = {
        "matrix_sha256": _sha256_file(rebound_matrix_path),
        "build_manifest_sha256": _sha256_file(build_manifest_path),
        "uf2_sha256": _sha256_file(uf2_path),
        "uf2_size_bytes": uf2_path.stat().st_size,
    }
    if not isinstance(binding, dict) or any(binding.get(key) != value for key, value in expected.items()):
        raise ValueError("flash record artifact binding differs from supplied build")
    before = record.get("board_before")
    after = record.get("board_after")
    if not isinstance(before, dict) or before != after or before.get("serial_number") != EXPECTED_SERIAL:
        raise ValueError("flash record does not preserve exact board identity")
    command = record.get("command")
    if not isinstance(command, list) or command.count("--input-file") != 1:
        raise ValueError("flash record command does not use one exact input file")
    input_index = command.index("--input-file")
    if input_index + 1 >= len(command) or command[input_index + 1] != str(uf2_path.resolve()):
        raise ValueError("flash record command does not identify the exact supplied UF2")
    return expected


def flash_stage4(
    *, device: str, rebound_matrix_path: Path, build_manifest_path: Path,
    uf2_path: Path, output_path: Path, arduino_cli: str = "arduino-cli",
) -> tuple[Path, dict[str, Any]]:
    output_path = output_path.resolve()
    if output_path.exists():
        raise FileExistsError(f"flash record already exists: {output_path}")
    binding = validate_build_inputs(
        rebound_matrix_path=rebound_matrix_path,
        build_manifest_path=build_manifest_path,
        uf2_path=uf2_path,
    )
    owners = subprocess.run(
        ["lsof", device], text=True, capture_output=True, check=False,
    )
    if owners.returncode == 0 and owners.stdout.strip():
        raise ValueError(f"serial device already has an owner:\n{owners.stdout}")
    if owners.returncode not in {0, 1}:
        raise ValueError(f"lsof failed with exit {owners.returncode}: {owners.stderr}")
    before = read_board_identity(device, arduino_cli=arduino_cli)
    build = json.loads(build_manifest_path.read_text(encoding="utf-8"))
    fqbn = build["provenance"]["configuration"]["fqbn"]
    command = [
        arduino_cli, "upload", "--port", device, "--fqbn", fqbn,
        "--input-file", str(uf2_path.resolve()),
    ]
    started = _utc_now()
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    after: dict[str, str] | None = None
    board_error: str | None = None
    if completed.returncode == 0:
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            try:
                after = read_board_identity(device, arduino_cli=arduino_cli)
                break
            except (ValueError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
                board_error = str(exc)
                time.sleep(0.5)
    passed = completed.returncode == 0 and after == before
    record: dict[str, Any] = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "status": "passed" if passed else "failed",
        "attempt_count": 1,
        "started_utc": started,
        "completed_utc": _utc_now(),
        "device": device,
        "command": command,
        "exit_code": completed.returncode,
        "stdout_sha256": sha256(completed.stdout.encode("utf-8")).hexdigest(),
        "stderr_sha256": sha256(completed.stderr.encode("utf-8")).hexdigest(),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
        "board_before": before,
        "board_after": after,
        "board_reappearance_error": board_error,
        "artifact_binding": binding,
        "continuity_claims_boundary": (
            "stable USB board identity and a single successful MCU upload are captured; "
            "external DAC rail continuity is operationally observed, not electrically measured"
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output_path.parent,
        prefix=f".{output_path.name}.", suffix=".tmp", delete=False,
    ) as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(output_path)
    if not passed:
        raise RuntimeError(f"Stage 4 flash failed; diagnostic record preserved at {output_path}")
    return output_path, record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--rebound-matrix", type=Path, required=True)
    parser.add_argument("--build-manifest", type=Path, required=True)
    parser.add_argument("--uf2", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--arduino-cli", default="arduino-cli")
    args = parser.parse_args(argv)
    path, record = flash_stage4(
        device=args.device,
        rebound_matrix_path=args.rebound_matrix,
        build_manifest_path=args.build_manifest,
        uf2_path=args.uf2,
        output_path=args.output,
        arduino_cli=args.arduino_cli,
    )
    print(json.dumps({"status": record["status"], "output": str(path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
