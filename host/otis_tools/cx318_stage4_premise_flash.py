"""Build-bind and flash the one-shot CX318 Stage 4 premise setup image."""

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

from .cx318_stage4_flash import EXPECTED_SERIAL, read_board_identity


PROFILE_ID = "cx318_stage4_premise_setup"
TOOL_ID = "cx318_stage4_premise_exact_flash_v1"

SAFETY_DEFINES = {
    "OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP": "1",
    "OTIS_CX318_STAGE4_PREMISE_SETUP_CODE": "0xA828u",
    "OTIS_ENABLE_DAC_AD5693R": "1",
    "OTIS_DAC_MIN_CODE": "0xA828u",
    "OTIS_DAC_MAX_CODE": "0xA828u",
    "OTIS_ENABLE_H1_DAC_SWEEP": "0",
    "OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW": "0",
    "OTIS_ENABLE_CX317_I_ONLY_PREVIEW": "0",
    "OTIS_ENABLE_CX318_STAGE4_PREVIEW": "0",
    "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": "0",
    "OTIS_ENABLE_DUAL_CORE_PARTITION": "0",
    "OTIS_ENABLE_PPS_DUAL_OBSERVER": "1",
    "OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED": "1",
    "OTIS_ENABLE_GNSS_RECEIVER": "1",
    "OTIS_GNSS_UART_TX_ENABLED": "0",
    "OTIS_ENABLE_ENV_SENSORS": "1",
    "OTIS_ENABLE_PSEUDO_PPS_GENERATOR": "0",
}


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
        json.dumps(
            value, ensure_ascii=True, separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _premise_profile(matrix: dict[str, Any]) -> dict[str, Any]:
    matches = [item for item in matrix["profiles"] if item["id"] == PROFILE_ID]
    if len(matches) != 1 or matches[0].get("expect") != "pass":
        raise ValueError("matrix does not contain exactly one supported premise profile")
    return matches[0]


def validate_premise_build_artifacts(
    *, matrix_path: Path, build_manifest_path: Path, uf2_path: Path,
) -> dict[str, Any]:
    """Validate immutable premise artifacts without consulting current git state."""
    matrix_path = matrix_path.resolve()
    build_manifest_path = build_manifest_path.resolve()
    uf2_path = uf2_path.resolve()
    matrix = load_matrix(matrix_path)
    tracked = load_matrix(DEFAULT_MATRIX.resolve())
    if matrix != tracked or _sha256_file(matrix_path) != _sha256_file(DEFAULT_MATRIX):
        raise ValueError("premise matrix differs from the exact tracked firmware matrix")
    profile = _premise_profile(matrix)
    defines = profile["defines"]
    if any(defines.get(key) != value for key, value in SAFETY_DEFINES.items()):
        raise ValueError("premise profile violates the exact one-shot zero-authority contract")

    build = json.loads(build_manifest_path.read_text(encoding="utf-8"))
    provenance = build["provenance"]
    configuration = provenance["configuration"]
    source = provenance["source"]
    config_payload = {
        key: value for key, value in configuration.items() if key != "sha256"
    }
    if (
        configuration.get("profile_id") != PROFILE_ID
        or configuration.get("defines") != defines
        or configuration.get("sha256") != _canonical_sha256(config_payload)
        or source.get("state") != "clean"
        or not isinstance(source.get("git_commit"), str)
        or len(source["git_commit"]) != 40
        or not isinstance(source.get("sha256"), str)
        or len(source["sha256"]) != 64
    ):
        raise ValueError("premise build provenance is not the exact clean profile input")
    matches = [item for item in build["artifacts"] if item.get("name") == uf2_path.name]
    if len(matches) != 1:
        raise ValueError("premise build manifest does not bind exactly one supplied UF2")
    artifact = matches[0]
    if (
        artifact.get("sha256") != _sha256_file(uf2_path)
        or artifact.get("size_bytes") != uf2_path.stat().st_size
    ):
        raise ValueError("premise UF2 differs from the build manifest")
    return {
        "matrix_sha256": _sha256_file(matrix_path),
        "build_manifest_sha256": _sha256_file(build_manifest_path),
        "uf2_sha256": _sha256_file(uf2_path),
        "uf2_size_bytes": uf2_path.stat().st_size,
        "git_commit": source["git_commit"],
        "source_sha256": source["sha256"],
        "configuration_sha256": configuration["sha256"],
        "fqbn": configuration["fqbn"],
        "build_invocation_id": provenance["invocation"]["id"],
        "profile_id": PROFILE_ID,
    }


def validate_premise_build_inputs(
    *, matrix_path: Path, build_manifest_path: Path, uf2_path: Path,
) -> dict[str, Any]:
    """Add the live clean-checkout requirement used immediately before flash."""
    binding = validate_premise_build_artifacts(
        matrix_path=matrix_path,
        build_manifest_path=build_manifest_path,
        uf2_path=uf2_path,
    )
    repo_root = DEFAULT_MATRIX.parents[2]
    current_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root,
        text=True, capture_output=True, check=True,
    ).stdout.strip()
    current_status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo_root, text=True, capture_output=True, check=True,
    ).stdout
    if (
        binding["git_commit"] != current_commit
        or binding["source_sha256"] != source_input_hash(matrix_path=matrix_path)
        or current_status
    ):
        raise ValueError("repository no longer matches the exact clean premise build")
    return binding


def validate_premise_flash_record(
    record: dict[str, Any], *, matrix_path: Path,
    build_manifest_path: Path, uf2_path: Path,
) -> dict[str, Any]:
    binding = validate_premise_build_artifacts(
        matrix_path=matrix_path,
        build_manifest_path=build_manifest_path,
        uf2_path=uf2_path,
    )
    if record.get("schema_version") != 1 or record.get("tool") != TOOL_ID:
        raise ValueError("premise flash record schema/tool is invalid")
    if record.get("status") != "passed" or record.get("attempt_count") != 1:
        raise ValueError("premise flash record is not one successful attempt")
    actual = record.get("artifact_binding")
    if not isinstance(actual, dict) or any(
        actual.get(key) != value for key, value in binding.items()
    ):
        raise ValueError("premise flash record binding differs from supplied build")
    before = record.get("board_before")
    after = record.get("board_after")
    if (
        not isinstance(before, dict)
        or before != after
        or before.get("serial_number") != EXPECTED_SERIAL
    ):
        raise ValueError("premise flash record does not preserve exact board identity")
    command = record.get("command")
    if not isinstance(command, list) or command.count("--input-file") != 1:
        raise ValueError("premise flash did not use one exact input file")
    index = command.index("--input-file")
    if index + 1 >= len(command) or command[index + 1] != str(uf2_path.resolve()):
        raise ValueError("premise flash command does not identify the supplied UF2")
    return binding


def flash_premise(
    *, device: str, matrix_path: Path, build_manifest_path: Path,
    uf2_path: Path, output_path: Path, arduino_cli: str = "arduino-cli",
) -> tuple[Path, dict[str, Any]]:
    output_path = output_path.resolve()
    if output_path.exists():
        raise FileExistsError(f"premise flash record already exists: {output_path}")
    binding = validate_premise_build_inputs(
        matrix_path=matrix_path,
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
    command = [
        arduino_cli, "upload", "--port", device,
        "--fqbn", build["provenance"]["configuration"]["fqbn"],
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
        "authority_boundary": (
            "one exact A828 manual attempt per boot; no preview, controller, "
            "sweep, dual-core or GPS-transmit path"
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
        raise RuntimeError(
            f"Stage 4 premise flash failed; diagnostic record preserved at {output_path}"
        )
    return output_path, record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--build-manifest", type=Path, required=True)
    parser.add_argument("--uf2", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--arduino-cli", default="arduino-cli")
    args = parser.parse_args(argv)
    path, record = flash_premise(
        device=args.device,
        matrix_path=args.matrix,
        build_manifest_path=args.build_manifest,
        uf2_path=args.uf2,
        output_path=args.output,
        arduino_cli=args.arduino_cli,
    )
    print(json.dumps({"status": record["status"], "output": str(path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
