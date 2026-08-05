"""Create an exact Stage 7 dual-core active run manifest."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import json

from .cx317_stage7_shadow import CONTRACT_SHA256, DEFAULT_CONTRACT
from .cx317_stage7_supervisor import (
    PART_A_QUALIFIED_TIMEOUT_S,
    PART_B_CLEARANCE_GRACE_S,
    PART_B_DURATION_S,
    POLICY_PATH,
    STAGE7_QUALIFICATION_TIMEOUT_S,
    load_stage7_spec,
)
from .run_paths import default_csv_files


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def create_stage7_manifest(
    *,
    part: str,
    start_code: int,
    run_dir: Path,
    build_manifest_path: Path,
    serial_device: str,
    baud: int = 115200,
) -> Path:
    path = run_dir / "run_manifest.json"
    if path.exists():
        raise FileExistsError(f"run manifest already exists in {run_dir}")
    build = json.loads(build_manifest_path.read_text(encoding="utf-8"))
    provenance = build["provenance"]
    spec, identities = load_stage7_spec(part, start_code)
    configuration = provenance["configuration"]
    defines = configuration["defines"]
    if configuration["profile_id"] != spec.profile:
        raise ValueError("build-manifest profile does not match Stage 7 part")
    if provenance["source"]["state"] != "clean":
        raise ValueError("Stage 7 hardware entry requires a clean artifact")
    expected_defines = {
        "OTIS_CX317_ACTIVE_START_CODE": f"0x{start_code:04X}u",
        "OTIS_CX317_ACTIVE_CORRECTION_LIMIT": f"{spec.correction_limit}u",
        "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES":
            f"{spec.cumulative_limit}u",
        "OTIS_ENABLE_DUAL_CORE_PARTITION": "1",
        "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": "1",
        "OTIS_GNSS_UART_TX_ENABLED": "0",
    }
    for key, expected in expected_defines.items():
        if defines.get(key) != expected:
            raise ValueError(f"Stage 7 build define {key} is not {expected}")
    uf2 = next(
        artifact
        for artifact in build["artifacts"]
        if artifact["name"].endswith(".uf2")
    )
    files = default_csv_files()
    for entry in files:
        if entry["contract"] in {
            "pps_snapshots_v1",
            "dac_steps_v1",
            "environment_v1",
            "estimates_v2",
            "control_previews_v1",
            "active_transactions_v1",
        }:
            entry.pop("optional", None)
    required_files = [entry["path"] for entry in files if not entry.get("optional")]
    now = _utc_now()
    source = provenance["source"]
    manifest = {
        "schema_version": 1,
        "template": False,
        "run_id": run_dir.name,
        "created_utc": now,
        "started_at_utc": now,
        "stage": f"CX317_DUAL_CORE_ACTIVE_{part.upper()}",
        "closed_loop_control": True,
        "actionable": False,
        "actuation_authorized": True,
        "board": "arduino_nano_rp2040_connect",
        "firmware": {
            "name": "otis_nano_rp2040_connect",
            "profile_id": spec.profile,
            "git_commit": source["git_commit"],
            "source_state": source["state"],
            "source_sha256": source["sha256"],
            "configuration_sha256": configuration["sha256"],
            "build_identity": f"{source['sha256']}:{configuration['sha256']}",
            "uf2_sha256": uf2["sha256"],
            "uf2_size_bytes": uf2["size_bytes"],
            "build_manifest_path": str(build_manifest_path.resolve()),
            "build_manifest_sha256": sha256(
                build_manifest_path.read_bytes()
            ).hexdigest(),
        },
        "host": {
            "capture_tool": "host.otis_tools.capture_device",
            "supervisor_tool": "host.otis_tools.cx317_stage7_supervisor",
            "shadow_tool": "host.otis_tools.cx317_stage7_shadow_monitor",
            "serial_device": serial_device,
            "baud": baud,
            "sole_serial_owner": True,
            "independent_abort_fifo_required": True,
            "shadow_has_serial_or_command_authority": False,
        },
        "active_campaign": {
            "part": part,
            "run_identity": spec.run_identity,
            "start_code": spec.start_code,
            "minimum_code": spec.minimum_code,
            "maximum_code": spec.maximum_code,
            "maximum_step_codes": spec.maximum_step,
            "correction_limit": spec.correction_limit,
            "cumulative_limit_codes": spec.cumulative_limit,
            "minimum_applied_cadence_s": 1800,
            "settling_exclusion_s": 900,
            "fresh_authoritative_support_s": 600,
            "authoritative_deadband_hz": 0.006249995628992717,
            "qualification_timeout_s": STAGE7_QUALIFICATION_TIMEOUT_S,
            "duration_after_qualification_s": (
                PART_A_QUALIFIED_TIMEOUT_S
                if part == "part_a"
                else PART_B_DURATION_S
            ),
            "post_duration_clearance_grace_s": (
                0 if part == "part_a" else PART_B_CLEARANCE_GRACE_S
            ),
            "maximum_wall_clock_s": (
                STAGE7_QUALIFICATION_TIMEOUT_S
                + (
                    PART_A_QUALIFIED_TIMEOUT_S
                    if part == "part_a"
                    else PART_B_DURATION_S + PART_B_CLEARANCE_GRACE_S
                )
            ),
            "timeout_disposition": "fail_static_abort_diagnostic_no_stage_exit",
            **identities,
        },
        "shadow_contract": {
            "path": str(DEFAULT_CONTRACT.relative_to(DEFAULT_CONTRACT.parents[2])),
            "sha256": CONTRACT_SHA256,
            "actionable": False,
            "actuation_authorized": False,
            "may_issue_command": False,
        },
        "domains": [
            {"name": "rp2040_timer0", "nominal_hz": 16000000},
            {"name": "h0_tcxo_16mhz", "nominal_hz": 10000000},
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
        "contracts": {
            entry["contract"]: 2 if entry["contract"] == "estimates_v2" else 1
            for entry in files
        },
        "files": files,
        "expected_artifacts": [
            *required_files,
            "raw/serial.log",
            "reports/cx317_active_supervisor_state.json",
            "reports/cx317_active_supervisor_events.jsonl",
            "reports/stage7_authoritative_observations_v1.csv",
            "reports/stage7_shadow_decisions_v1.csv",
            "reports/stage7_exit_gate.json",
        ],
        "policy": {
            "path": str(POLICY_PATH.relative_to(POLICY_PATH.parents[2])),
            "sha256": identities["active_policy_sha256"],
        },
        "known_limitations": [
            "No oscilloscope is available; analog waveform margin is not claimed.",
            "The h0_tcxo_16mhz token is historical; the connected CX317 source is nominally 10 MHz.",
            "Stage 7 demonstrates bounded frequency-control endurance, not calibrated UTC, phase lock, or holdover.",
            "Shadow candidates are counterfactual and have no Stage 7 actuation authority.",
        ],
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", choices=("part_a", "part_b"), required=True)
    parser.add_argument("--start-code", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--build-manifest", type=Path, required=True)
    parser.add_argument("--serial-device", required=True)
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args(argv)
    print(
        create_stage7_manifest(
            part=args.part,
            start_code=args.start_code,
            run_dir=args.run_dir,
            build_manifest_path=args.build_manifest,
            serial_device=args.serial_device,
            baud=args.baud,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
