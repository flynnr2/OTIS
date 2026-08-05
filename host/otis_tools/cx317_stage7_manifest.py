"""Create an exact Stage 7 dual-core active run manifest."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import json
from typing import Any

from .cx317_stage7_shadow import CONTRACT_SHA256, DEFAULT_CONTRACT
from .cx317_stage7_part_b_matrix import (
    PART_B_PROFILE,
    STAGE7_PROMPT,
    STAGE7_PROMPT_SHA256,
)
from .cx317_stage7_part_b_rehearsal import SUPERVISOR_PATH, TOOL_PATH
from .cx317_stage7_gate_validation import part_a2_progression_gate_valid
from .cx317_stage7_supervisor import (
    PART_A_QUALIFIED_TIMEOUT_S,
    PART_B_CLEARANCE_GRACE_S,
    PART_B_DURATION_S,
    POLICY_PATH,
    REHEARSAL_POLICY_PATH,
    STAGE7_QUALIFICATION_TIMEOUT_S,
    load_stage7_spec,
    part_b_timeline_preflight,
    rehearsal_timeline_preflight,
    stage7_timing,
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
    part_a1_gate_path: Path | None = None,
    part_a2_gate_path: Path | None = None,
    part_b_rehearsal_gate_path: Path | None = None,
    part_b_matrix_path: Path | None = None,
) -> Path:
    path = run_dir / "run_manifest.json"
    if path.exists():
        raise FileExistsError(f"run manifest already exists in {run_dir}")
    build = json.loads(build_manifest_path.read_text(encoding="utf-8"))
    provenance = build["provenance"]
    spec, identities = load_stage7_spec(part, start_code)
    timing = stage7_timing(part)
    is_rehearsal = part == "rehearsal"
    prerequisite_gates: dict[str, dict[str, Any]] = {}
    part_b_matrix_binding: dict[str, Any] = {}
    if part == "part_b":
        if (
            part_a1_gate_path is None
            or part_a2_gate_path is None
            or part_b_rehearsal_gate_path is None
            or part_b_matrix_path is None
        ):
            raise ValueError(
                "Stage 7 Part B requires A1/A2 gates, the accelerated "
                "Part B rehearsal gate and the derived Part B matrix"
            )
        part_a1_gate = json.loads(
            part_a1_gate_path.read_text(encoding="utf-8")
        )
        part_a2_gate = json.loads(
            part_a2_gate_path.read_text(encoding="utf-8")
        )
        part_b_rehearsal_gate = json.loads(
            part_b_rehearsal_gate_path.read_text(encoding="utf-8")
        )
        rehearsal_bindings = part_b_rehearsal_gate.get("bindings", {})
        if (
            part_a1_gate.get("status") != "pass"
            or part_a1_gate.get("test")
            != "part_a_fixed_code_stability"
            or part_a1_gate.get("applicable") is not True
            or not part_a1_gate.get("criteria")
            or not all(
                value is True
                for value in part_a1_gate["criteria"].values()
            )
        ):
            raise ValueError("Stage 7 Part A1 stability gate is not passed")
        if not part_a2_progression_gate_valid(part_a2_gate):
            raise ValueError("Stage 7 Part A2 transaction gate is not passed")
        if (
            part_b_rehearsal_gate.get("status") != "pass"
            or part_b_rehearsal_gate.get("test")
            != "stage7_part_b_accelerated_control_rehearsal"
            or part_b_rehearsal_gate.get("qualification_evidence") is not False
            or part_b_rehearsal_gate.get("hardware_actuation") is not False
            or part_b_rehearsal_gate.get("serial_or_fifo_authority") is not False
            or not part_b_rehearsal_gate.get("cases")
            or not all(
                value is True
                for value in part_b_rehearsal_gate["cases"].values()
            )
            or not part_b_rehearsal_gate.get(
                "timeline_preflight", {}
            ).get("checks")
            or not all(
                value is True
                for value in part_b_rehearsal_gate[
                    "timeline_preflight"
                ]["checks"].values()
            )
            or rehearsal_bindings.get("supervisor_sha256")
            != sha256(SUPERVISOR_PATH.read_bytes()).hexdigest()
            or rehearsal_bindings.get("rehearsal_tool_sha256")
            != sha256(TOOL_PATH.read_bytes()).hexdigest()
            or rehearsal_bindings.get("stage7_prompt_sha256")
            != STAGE7_PROMPT_SHA256
            or sha256(
                (POLICY_PATH.parents[2] / STAGE7_PROMPT).read_bytes()
            ).hexdigest()
            != STAGE7_PROMPT_SHA256
        ):
            raise ValueError("Stage 7 Part B accelerated rehearsal is not passed")
        final_code = int(
            part_a2_gate.get("transactions", {}).get("final_code", -1)
        )
        if final_code != start_code:
            raise ValueError(
                "Stage 7 Part B start does not equal the passed Part A2 final code"
            )
        part_b_matrix_path = part_b_matrix_path.resolve()
        part_b_matrix = json.loads(
            part_b_matrix_path.read_text(encoding="utf-8")
        )
        derivation = part_b_matrix.get("stage7_part_b_derivation", {})
        part_b_profiles = {
            item.get("id"): item for item in part_b_matrix.get("profiles", [])
        }
        derived_profile = part_b_profiles.get(PART_B_PROFILE, {})
        if (
            derivation.get("stage7_prompt_sha256")
            != STAGE7_PROMPT_SHA256
            or derivation.get("part_a2_gate_sha256")
            != sha256(part_a2_gate_path.read_bytes()).hexdigest()
            or int(derivation.get("exact_part_b_start_code", -1))
            != start_code
            or derived_profile.get("defines", {}).get(
                "OTIS_CX317_ACTIVE_START_CODE"
            )
            != f"0x{start_code:04X}u"
        ):
            raise ValueError("Stage 7 Part B derived matrix binding differs")
        from tools.firmware_matrix import source_input_hash

        if source_input_hash(matrix_path=part_b_matrix_path) != provenance[
            "source"
        ]["sha256"]:
            raise ValueError(
                "Part B build source identity does not match the derived matrix"
            )
        part_b_matrix_binding = {
            "path": str(part_b_matrix_path),
            "sha256": sha256(part_b_matrix_path.read_bytes()).hexdigest(),
            "derivation": derivation,
        }
        prerequisite_gates = {
            "part_a1_fixed_code_stability": {
                "path": str(part_a1_gate_path.resolve()),
                "sha256": sha256(part_a1_gate_path.read_bytes()).hexdigest(),
                "document": part_a1_gate,
            },
            "part_a2_cross_core_transaction": {
                "path": str(part_a2_gate_path.resolve()),
                "sha256": sha256(part_a2_gate_path.read_bytes()).hexdigest(),
                "document": part_a2_gate,
            },
            "part_b_accelerated_control_rehearsal": {
                "path": str(part_b_rehearsal_gate_path.resolve()),
                "sha256": sha256(
                    part_b_rehearsal_gate_path.read_bytes()
                ).hexdigest(),
                "document": part_b_rehearsal_gate,
            },
        }
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
    if is_rehearsal:
        expected_defines.update(
            {
                "OTIS_CX317_SELECTED_SPAN_INTERVALS_CONFIG": "120u",
                "OTIS_FC0_STARTUP_INHIBIT_MS": "60000u",
                "OTIS_FC0_CONTROL_READY_CLEAN_WINDOWS": "3u",
                "OTIS_CX317_STARTUP_WARMUP_S": "60u",
                "OTIS_CX317_SETTLING_EXCLUSION_S": "60u",
                "OTIS_CX317_FULL_HISTORY_RESET_S": "180u",
                "OTIS_CX317_RECOVERY_FRESH_SUPPORT_S": "120u",
                "OTIS_CX317_DECISION_CADENCE_S": "240u",
                "OTIS_CX317_MINIMUM_APPLIED_CADENCE_S": "240u",
            }
        )
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
        "stage": (
            "CX317_STAGE7_DIAGNOSTIC_REHEARSAL"
            if is_rehearsal
            else f"CX317_DUAL_CORE_ACTIVE_{part.upper()}"
        ),
        "closed_loop_control": True,
        "actionable": False,
        "actuation_authorized": True,
        "diagnostic_only": is_rehearsal,
        "qualification_evidence": not is_rehearsal,
        "stage7_progression_authority": not is_rehearsal,
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
            "shadow_tool": (
                None
                if is_rehearsal
                else "host.otis_tools.cx317_stage7_shadow_monitor"
            ),
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
            "minimum_applied_cadence_s": (
                240 if is_rehearsal else 1800
            ),
            "settling_exclusion_s": 60 if is_rehearsal else 900,
            "fresh_authoritative_support_s": 120 if is_rehearsal else 600,
            "selected_interval_s": timing.selected_interval_s,
            "decision_cadence_s": timing.decision_cadence_s,
            "authoritative_deadband_hz": 0.006249995628992717,
            "qualification_timeout_s": timing.qualification_timeout_s,
            "duration_after_qualification_s": (
                timing.qualified_timeout_s
                if is_rehearsal
                else (
                    PART_A_QUALIFIED_TIMEOUT_S
                    if part == "part_a"
                    else PART_B_DURATION_S
                )
            ),
            "post_duration_clearance_grace_s": (
                0 if part in {"part_a", "rehearsal"} else PART_B_CLEARANCE_GRACE_S
            ),
            "maximum_wall_clock_s": (
                timing.qualification_timeout_s
                + (
                    timing.qualified_timeout_s
                    if is_rehearsal
                    else (
                        PART_A_QUALIFIED_TIMEOUT_S
                        if part == "part_a"
                        else PART_B_DURATION_S + PART_B_CLEARANCE_GRACE_S
                    )
                )
            ),
            "timeout_disposition": "fail_static_abort_diagnostic_no_stage_exit",
            **(
                {
                    "cross_layer_timeline_preflight": (
                        rehearsal_timeline_preflight()
                        if is_rehearsal
                        else part_b_timeline_preflight()
                    )
                }
                if is_rehearsal or part == "part_b"
                else {}
            ),
            **identities,
        },
        "shadow_contract": (
            {
                "enabled": False,
                "reason": "diagnostic_rehearsal_has_no_shadow_or_adoption_authority",
                "actionable": False,
                "actuation_authorized": False,
                "may_issue_command": False,
            }
            if is_rehearsal
            else {
                "path": str(
                    DEFAULT_CONTRACT.relative_to(DEFAULT_CONTRACT.parents[2])
                ),
                "sha256": CONTRACT_SHA256,
                "actionable": False,
                "actuation_authorized": False,
                "may_issue_command": False,
            }
        ),
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
            *(
                ["reports/stage7_rehearsal_gate.json"]
                if is_rehearsal
                else [
                    "reports/stage7_authoritative_observations_v1.csv",
                    "reports/stage7_shadow_decisions_v1.csv",
                    "reports/stage7_exit_gate.json",
                ]
            ),
        ],
        "evidence_artifacts": [
            "reports/cx317_active_supervisor_state.json",
            "reports/cx317_active_supervisor_events.jsonl",
            *(
                ["reports/stage7_rehearsal_gate.json"]
                if is_rehearsal
                else [
                    "reports/stage7_authoritative_observations_v1.csv",
                    "reports/stage7_shadow_decisions_v1.csv",
                    "reports/stage7_exit_gate.json",
                ]
            ),
        ],
        "policy": {
            "path": str(
                (REHEARSAL_POLICY_PATH if is_rehearsal else POLICY_PATH).relative_to(
                    POLICY_PATH.parents[2]
                )
            ),
            "sha256": identities["active_policy_sha256"],
        },
        "known_limitations": [
            "No oscilloscope is available; analog waveform margin is not claimed.",
            "The h0_tcxo_16mhz token is historical; the connected CX317 source is nominally 10 MHz.",
            "Stage 7 demonstrates bounded frequency-control endurance, not calibrated UTC, phase lock, or holdover.",
            "Shadow candidates are counterfactual and have no Stage 7 actuation authority.",
            *(
                [
                    "Rehearsal timing and estimator output are diagnostic-only and cannot satisfy a Stage 7A or Stage 7B exit gate."
                ]
                if is_rehearsal
                else []
            ),
        ],
    }
    if prerequisite_gates:
        manifest["prerequisite_gates"] = prerequisite_gates
        manifest["part_b_matrix_binding"] = part_b_matrix_binding
    run_dir.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--part", choices=("part_a", "part_b", "rehearsal"), required=True
    )
    parser.add_argument("--start-code", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--build-manifest", type=Path, required=True)
    parser.add_argument("--serial-device", required=True)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--part-a1-gate", type=Path)
    parser.add_argument("--part-a2-gate", type=Path)
    parser.add_argument("--part-b-rehearsal-gate", type=Path)
    parser.add_argument("--part-b-matrix", type=Path)
    args = parser.parse_args(argv)
    print(
        create_stage7_manifest(
            part=args.part,
            start_code=args.start_code,
            run_dir=args.run_dir,
            build_manifest_path=args.build_manifest,
            serial_device=args.serial_device,
            baud=args.baud,
            part_a1_gate_path=args.part_a1_gate,
            part_a2_gate_path=args.part_a2_gate,
            part_b_rehearsal_gate_path=args.part_b_rehearsal_gate,
            part_b_matrix_path=args.part_b_matrix,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
