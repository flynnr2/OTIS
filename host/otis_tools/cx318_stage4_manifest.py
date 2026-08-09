"""Create exact manifests for the authorized CX318 setup and Stage 4 live run."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import json
from typing import Any

from .cx318_stage4_flash import (
    read_board_identity,
    validate_build_inputs,
    validate_flash_record,
)
from .cx318_stage4_premise_flash import (
    PROFILE_ID as PREMISE_PROFILE_ID,
    validate_premise_build_artifacts,
    validate_premise_flash_record,
)
from .cx318_stage4_static_code_preflight import (
    EXPECTED_CODE,
    EXPECTED_COMMANDS,
    EXPECTED_DAC_EPOCH,
    validate_static_proof,
)
from .run_paths import default_csv_files


SETUP_STAGE = "CX318_STAGE4_STATIC_CODE_SETUP"
LIVE_STAGE = "CX318_STAGE4_NONACTUATING_LIVE_PREVIEW"
IDENTITY_STAGE = "CX318_STAGE4_POST_FLASH_IDENTITY"
REHEARSAL_STAGE = "CX318_STAGE4_NONACTUATING_REHEARSAL"
PROFILE_ID = "cx318_stage4_nonactuating_preview"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write_manifest(run_dir: Path, manifest: dict[str, Any]) -> Path:
    path = run_dir / "run_manifest.json"
    if path.exists():
        raise FileExistsError(f"run manifest already exists: {path}")
    run_dir.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def _relative_inside(run_dir: Path, path: Path, label: str) -> str:
    try:
        return path.resolve().relative_to(run_dir.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"{label} must be inside its run") from exc


def _files(*, live: bool) -> list[dict[str, Any]]:
    files = default_csv_files()
    required = {
        "count_observations_v1",
        "pps_snapshots_v1",
        "health_v1",
        "dac_steps_v1",
        "environment_v1",
        "active_transactions_v1",
    }
    if live:
        required |= {
            "relative_phase_observations_v1",
            "phase_estimator_outputs_v1",
            "hybrid_preview_decisions_v1",
        }
    for entry in files:
        if entry["contract"] in required:
            entry.pop("optional", None)
    return files


def _common(
    *, run_dir: Path, stage: str, serial_device: str, files: list[dict[str, Any]],
) -> dict[str, Any]:
    now = _utc_now()
    return {
        "schema_version": 1,
        "template": False,
        "run_id": run_dir.name,
        "created_utc": now,
        "started_at_utc": now,
        "stage": stage,
        "board": "arduino_nano_rp2040_connect",
        "actionable": False,
        "phase_hybrid_authority": False,
        "gps_transmit_authorized": False,
        "host": {
            "capture_tool": "host.otis_tools.capture_device",
            "serial_device": serial_device,
            "baud": 115200,
            "sole_serial_owner": True,
            "normal_command_envelope": "OTISQ1_MONOTONIC_NS",
            "normal_command_max_age_s": 2.0,
            "normal_command_batch_limit": 1,
            "capture_write_timeout_s": 1.0,
            "abort_path": "SIGINT exact PID from reports/capture_device_state.json",
        },
        "domains": [
            {"name": "rp2040_timer0", "nominal_hz": 16_000_000},
            {"name": "h0_tcxo_16mhz", "nominal_hz": 10_000_000},
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
        "environment_sources": [
            {"source": "sht4x", "role": "vcocxo_near", "primary_temperature": True},
            {"source": "bmp280", "role": "pressure_reference", "primary_temperature": False},
        ],
        "known_limitations": [
            "CX317 is the connected VCOCXO identity; CX318 is the programme label.",
            "No oscilloscope is available; analog waveform margin is not claimed.",
            "The h0_tcxo_16mhz token is historical; the connected source is nominally 10 MHz.",
            "Relative phase is session-local and is not UTC, absolute time, phase lock, or calibrated delay.",
        ],
    }


def create_setup_manifest(
    *, run_dir: Path, serial_device: str, premise_matrix_path: Path,
    premise_build_manifest_path: Path, premise_uf2_path: Path,
    premise_flash_record_path: Path,
) -> Path:
    run_dir = run_dir.resolve()
    premise_matrix_path = premise_matrix_path.resolve()
    premise_build_manifest_path = premise_build_manifest_path.resolve()
    premise_uf2_path = premise_uf2_path.resolve()
    premise_flash_record_path = premise_flash_record_path.resolve()
    binding = validate_premise_build_artifacts(
        matrix_path=premise_matrix_path,
        build_manifest_path=premise_build_manifest_path,
        uf2_path=premise_uf2_path,
    )
    flash_record = json.loads(premise_flash_record_path.read_text(encoding="utf-8"))
    validate_premise_flash_record(
        flash_record,
        matrix_path=premise_matrix_path,
        build_manifest_path=premise_build_manifest_path,
        uf2_path=premise_uf2_path,
    )
    premise_paths = {
        "matrix": _relative_inside(run_dir, premise_matrix_path, "premise matrix"),
        "build_manifest": _relative_inside(
            run_dir, premise_build_manifest_path, "premise build manifest",
        ),
        "uf2": _relative_inside(run_dir, premise_uf2_path, "premise UF2"),
        "flash_record": _relative_inside(
            run_dir, premise_flash_record_path, "premise flash record",
        ),
    }
    files = _files(live=False)
    manifest = _common(
        run_dir=run_dir, stage=SETUP_STAGE,
        serial_device=serial_device, files=files,
    )
    manifest.update({
        "purpose": "single operator-authorized premise-setting A828 application before zero-authority Stage 4",
        "frequency_actuation_authorized": False,
        "setup_stimulus_authorized": True,
        "stage4_static_setup": {
            "premise_amendment": "operator_authorized_single_setup_write",
            "authorized_code": f"0x{EXPECTED_CODE:04X}",
            "maximum_setup_attempts": 1,
            "maximum_setup_writes": 1,
            "retry_after_failure": False,
            "opening_dac_epoch": 0,
            "resulting_dac_epoch": EXPECTED_DAC_EPOCH,
            "automatic_authority": False,
            "phase_hybrid_authority": False,
            "gps_transmit_authorized": False,
            "exact_command_sequence": list(EXPECTED_COMMANDS),
            "stop_on_any_additional_dac_or_active_record": True,
        },
        "premise_firmware": {
            "profile_id": PREMISE_PROFILE_ID,
            "matrix": {
                "path": premise_paths["matrix"],
                "sha256": _sha256_file(premise_matrix_path),
            },
            "build_manifest": {
                "path": premise_paths["build_manifest"],
                "sha256": _sha256_file(premise_build_manifest_path),
            },
            "uf2": {
                "path": premise_paths["uf2"],
                "sha256": _sha256_file(premise_uf2_path),
                "size_bytes": premise_uf2_path.stat().st_size,
            },
            "flash_record": {
                "path": premise_paths["flash_record"],
                "sha256": _sha256_file(premise_flash_record_path),
            },
            "artifact_binding": binding,
        },
        "evidence_artifacts": [
            *premise_paths.values(),
            "control/premise_attempt_latch.json",
        ],
        "expected_artifacts": [
            *[entry["path"] for entry in files if not entry.get("optional")],
            "raw/serial.log",
            "reports/capture_device_state.json",
            "control/premise_attempt_latch.json",
            *premise_paths.values(),
        ],
    })
    return _write_manifest(run_dir, manifest)


def create_live_manifest(
    *, run_dir: Path, build_manifest_path: Path, uf2_path: Path,
    static_proof_path: Path, rebound_matrix_path: Path,
    serial_device: str, duration_s: int = 7200,
) -> Path:
    if duration_s < 7200:
        raise ValueError("Stage 4 live duration cannot be less than 7200 seconds")
    run_dir = run_dir.resolve()
    build_manifest_path = build_manifest_path.resolve()
    uf2_path = uf2_path.resolve()
    static_proof_path = static_proof_path.resolve()
    rebound_matrix_path = rebound_matrix_path.resolve()
    proof = json.loads(static_proof_path.read_text(encoding="utf-8"))
    setup = validate_static_proof(proof)
    validate_build_inputs(
        rebound_matrix_path=rebound_matrix_path,
        build_manifest_path=build_manifest_path,
        uf2_path=uf2_path,
    )
    build = json.loads(build_manifest_path.read_text(encoding="utf-8"))
    provenance = build["provenance"]
    configuration = provenance["configuration"]
    source = provenance["source"]
    if configuration["profile_id"] != PROFILE_ID:
        raise ValueError("build manifest is not the Stage 4 profile")
    if source["state"] != "clean":
        raise ValueError("Stage 4 live artifact must be built from clean source")
    defines = configuration["defines"]
    rebound = json.loads(rebound_matrix_path.read_text(encoding="utf-8"))
    rebound_profiles = [item for item in rebound["profiles"] if item["id"] == PROFILE_ID]
    if len(rebound_profiles) != 1 or defines != rebound_profiles[0]["defines"]:
        raise ValueError("Stage 4 build define map differs from the complete rebound profile")
    artifacts = [item for item in build["artifacts"] if item.get("name") == uf2_path.name]
    if len(artifacts) != 1:
        raise ValueError("build manifest does not bind exactly one supplied UF2")
    uf2 = artifacts[0]
    if _sha256_file(uf2_path) != uf2["sha256"] or uf2_path.stat().st_size != uf2["size_bytes"]:
        raise ValueError("supplied UF2 differs from the build manifest")
    derivation = json.loads(rebound_matrix_path.read_text(encoding="utf-8"))[
        "cx318_stage4_rebound_derivation"
    ]
    if (
        derivation.get("exact_static_code") != setup.confirmed_code
        or derivation.get("exact_dac_epoch") != setup.dac_epoch
        or derivation.get("setup_source_identities") != setup.source_identities
    ):
        raise ValueError("rebound matrix differs from the sealed setup evidence")

    def relative(path: Path) -> str:
        try:
            return path.relative_to(run_dir).as_posix()
        except ValueError as exc:
            raise ValueError("Stage 4 evidence/build artifacts must be inside the live run") from exc

    proof_relative = relative(static_proof_path)
    matrix_relative = relative(rebound_matrix_path)
    build_relative = relative(build_manifest_path)
    uf2_relative = relative(uf2_path)
    files = _files(live=True)
    manifest = _common(
        run_dir=run_dir, stage=LIVE_STAGE,
        serial_device=serial_device, files=files,
    )
    evidence_artifacts = [
        proof_relative,
        matrix_relative,
        build_relative,
        uf2_relative,
        "reports/cx318_stage4_live_analysis_v1.json",
    ]
    manifest.update({
        "purpose": "finite static-code real-GPS relative-phase and hybrid preview with zero authority",
        "firmware": {
            "name": "otis_nano_rp2040_connect",
            "config_id": PROFILE_ID,
            "git_commit": source["git_commit"],
            "source_state": source["state"],
            "source_sha256": source["sha256"],
            "configuration_sha256": configuration["sha256"],
            "uf2_sha256": uf2["sha256"],
            "uf2_size_bytes": uf2["size_bytes"],
            "build_manifest_path": build_relative,
            "build_manifest_sha256": _sha256_file(build_manifest_path),
            "rebound_matrix_path": matrix_relative,
            "rebound_matrix_sha256": _sha256_file(rebound_matrix_path),
            "build_provenance_required": True,
        },
        "stage4_live_preview": {
            "profile_id": PROFILE_ID,
            "static_code": f"0x{setup.confirmed_code:04X}",
            "dac_epoch": setup.dac_epoch,
            "minimum_authoritative_frequency_estimates": 2,
            "minimum_duration_s": duration_s,
            "planned_duration_s": duration_s,
            "static_code_evidence": {
                "path": proof_relative,
                "sha256": _sha256_file(static_proof_path),
            },
            "permitted_live_commands": ["CONFIG?", "DUALCORE?"],
            "dac_rows_permitted": 0,
            "active_rows_permitted": 0,
            "phase_hybrid_authority": False,
        },
        "evidence_artifacts": evidence_artifacts,
        "expected_artifacts": [
            *[entry["path"] for entry in files if not entry.get("optional")],
            "raw/serial.log",
            "reports/capture_device_state.json",
            *evidence_artifacts,
        ],
    })
    return _write_manifest(run_dir, manifest)


def create_identity_manifest(
    *, run_dir: Path, build_manifest_path: Path, uf2_path: Path,
    rebound_matrix_path: Path, flash_record_path: Path,
    serial_device: str,
) -> Path:
    run_dir = run_dir.resolve()
    build_manifest_path = build_manifest_path.resolve()
    uf2_path = uf2_path.resolve()
    rebound_matrix_path = rebound_matrix_path.resolve()
    flash_record_path = flash_record_path.resolve()
    binding = validate_build_inputs(
        rebound_matrix_path=rebound_matrix_path,
        build_manifest_path=build_manifest_path,
        uf2_path=uf2_path,
    )
    record = json.loads(flash_record_path.read_text(encoding="utf-8"))
    validate_flash_record(
        record,
        rebound_matrix_path=rebound_matrix_path,
        build_manifest_path=build_manifest_path,
        uf2_path=uf2_path,
    )
    board_identity = read_board_identity(serial_device)
    if board_identity != record.get("board_after"):
        raise ValueError("current USB board identity differs from the successfully flashed board")
    try:
        flash_relative = flash_record_path.relative_to(run_dir).as_posix()
    except ValueError as exc:
        raise ValueError("flash record must be inside the post-flash identity run") from exc
    build = json.loads(build_manifest_path.read_text(encoding="utf-8"))
    provenance = build["provenance"]
    source = provenance["source"]
    configuration = provenance["configuration"]
    files = _files(live=False)
    identity_report_path = run_dir / "reports/usb_board_identity.json"
    if identity_report_path.exists():
        raise FileExistsError(f"USB identity report already exists: {identity_report_path}")
    identity_report_path.parent.mkdir(parents=True, exist_ok=True)
    identity_report = {
        "schema_version": 1,
        "tool": "cx318_stage4_post_flash_usb_identity_v1",
        "observed_utc": _utc_now(),
        "device": serial_device,
        "identity": board_identity,
        "flash_record_sha256": _sha256_file(flash_record_path),
    }
    with identity_report_path.open("x", encoding="utf-8") as handle:
        json.dump(identity_report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    identity_relative = identity_report_path.relative_to(run_dir).as_posix()
    manifest = _common(
        run_dir=run_dir,
        stage=IDENTITY_STAGE,
        serial_device=serial_device,
        files=files,
    )
    manifest.update({
        "purpose": "read-only post-flash board/build lineage before the finite Stage 4 run",
        "firmware": {
            "name": "otis_nano_rp2040_connect",
            "config_id": PROFILE_ID,
            "git_commit": source["git_commit"],
            "source_state": source["state"],
            "source_sha256": source["sha256"],
            "configuration_sha256": configuration["sha256"],
            "uf2_sha256": binding["uf2_sha256"],
            "uf2_size_bytes": binding["uf2_size_bytes"],
            "build_manifest_sha256": binding["build_manifest_sha256"],
            "rebound_matrix_sha256": binding["matrix_sha256"],
            "build_provenance_required": True,
        },
        "post_flash_identity": {
            "exact_command_sequence": ["CONFIG?", "DUALCORE?"],
            "expected_static_code": "0xA828",
            "expected_dac_epoch": 1,
            "permitted_dac_rows": 0,
            "permitted_active_rows": 0,
            "flash_record": {
                "path": flash_relative,
                "sha256": _sha256_file(flash_record_path),
            },
            "usb_board_identity": {
                "path": identity_relative,
                "sha256": _sha256_file(identity_report_path),
            },
        },
        "evidence_artifacts": [flash_relative, identity_relative],
        "expected_artifacts": [
            *[entry["path"] for entry in files if not entry.get("optional")],
            "raw/serial.log",
            "reports/capture_device_state.json",
            flash_relative,
            identity_relative,
        ],
    })
    return _write_manifest(run_dir, manifest)


def create_rehearsal_manifest(
    *, run_dir: Path, build_manifest_path: Path, uf2_path: Path,
    static_proof_path: Path, rebound_matrix_path: Path,
    serial_device: str, duration_s: int = 720,
) -> Path:
    if duration_s < 600:
        raise ValueError("Stage 4 rehearsal duration cannot be less than 600 seconds")
    run_dir = run_dir.resolve()
    build_manifest_path = build_manifest_path.resolve()
    uf2_path = uf2_path.resolve()
    static_proof_path = static_proof_path.resolve()
    rebound_matrix_path = rebound_matrix_path.resolve()
    try:
        proof_relative = static_proof_path.relative_to(run_dir).as_posix()
    except ValueError as exc:
        raise ValueError("Stage 4 rehearsal proof must be inside its run") from exc
    proof = json.loads(static_proof_path.read_text(encoding="utf-8"))
    setup = validate_static_proof(proof)
    binding = validate_build_inputs(
        rebound_matrix_path=rebound_matrix_path,
        build_manifest_path=build_manifest_path,
        uf2_path=uf2_path,
    )
    build = json.loads(build_manifest_path.read_text(encoding="utf-8"))
    provenance = build["provenance"]
    source = provenance["source"]
    configuration = provenance["configuration"]
    rebound = json.loads(rebound_matrix_path.read_text(encoding="utf-8"))
    profiles = [item for item in rebound["profiles"] if item["id"] == PROFILE_ID]
    if len(profiles) != 1 or configuration["defines"] != profiles[0]["defines"]:
        raise ValueError("rehearsal build differs from the complete rebound profile")
    analysis_relative = "reports/cx318_stage4_rehearsal_analysis_v1.json"
    files = _files(live=True)
    manifest = _common(
        run_dir=run_dir,
        stage=REHEARSAL_STAGE,
        serial_device=serial_device,
        files=files,
    )
    manifest.update({
        "purpose": "finite exact-profile zero-authority rehearsal required before the long Stage 4 gate run",
        "diagnostic_rehearsal": True,
        "stage4_progression_authority": False,
        "firmware": {
            "name": "otis_nano_rp2040_connect",
            "config_id": PROFILE_ID,
            "git_commit": source["git_commit"],
            "source_state": source["state"],
            "source_sha256": source["sha256"],
            "configuration_sha256": configuration["sha256"],
            "uf2_sha256": binding["uf2_sha256"],
            "uf2_size_bytes": binding["uf2_size_bytes"],
            "build_manifest_path": str(build_manifest_path),
            "build_manifest_sha256": binding["build_manifest_sha256"],
            "rebound_matrix_path": str(rebound_matrix_path),
            "rebound_matrix_sha256": binding["matrix_sha256"],
            "build_provenance_required": True,
        },
        "stage4_live_preview": {
            "profile_id": PROFILE_ID,
            "static_code": f"0x{setup.confirmed_code:04X}",
            "dac_epoch": setup.dac_epoch,
            "minimum_authoritative_frequency_estimates": 1,
            "minimum_duration_s": 600,
            "planned_duration_s": duration_s,
            "static_code_evidence": {
                "path": proof_relative,
                "sha256": _sha256_file(static_proof_path),
            },
            "permitted_live_commands": ["CONFIG?", "DUALCORE?"],
            "dac_rows_permitted": 0,
            "active_rows_permitted": 0,
            "phase_hybrid_authority": False,
        },
        "evidence_artifacts": [proof_relative, analysis_relative],
        "expected_artifacts": [
            *[entry["path"] for entry in files if not entry.get("optional")],
            "raw/serial.log",
            "reports/capture_device_state.json",
            proof_relative,
            analysis_relative,
        ],
    })
    return _write_manifest(run_dir, manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="kind", required=True)
    setup = subparsers.add_parser("setup")
    setup.add_argument("--run-dir", type=Path, required=True)
    setup.add_argument("--serial-device", required=True)
    setup.add_argument("--premise-matrix", type=Path, required=True)
    setup.add_argument("--premise-build-manifest", type=Path, required=True)
    setup.add_argument("--premise-uf2", type=Path, required=True)
    setup.add_argument("--premise-flash-record", type=Path, required=True)
    live = subparsers.add_parser("live")
    live.add_argument("--run-dir", type=Path, required=True)
    live.add_argument("--build-manifest", type=Path, required=True)
    live.add_argument("--uf2", type=Path, required=True)
    live.add_argument("--static-proof", type=Path, required=True)
    live.add_argument("--rebound-matrix", type=Path, required=True)
    live.add_argument("--serial-device", required=True)
    live.add_argument("--duration-s", type=int, default=7200)
    identity = subparsers.add_parser("identity")
    identity.add_argument("--run-dir", type=Path, required=True)
    identity.add_argument("--build-manifest", type=Path, required=True)
    identity.add_argument("--uf2", type=Path, required=True)
    identity.add_argument("--rebound-matrix", type=Path, required=True)
    identity.add_argument("--flash-record", type=Path, required=True)
    identity.add_argument("--serial-device", required=True)
    rehearsal = subparsers.add_parser("rehearsal")
    rehearsal.add_argument("--run-dir", type=Path, required=True)
    rehearsal.add_argument("--build-manifest", type=Path, required=True)
    rehearsal.add_argument("--uf2", type=Path, required=True)
    rehearsal.add_argument("--static-proof", type=Path, required=True)
    rehearsal.add_argument("--rebound-matrix", type=Path, required=True)
    rehearsal.add_argument("--serial-device", required=True)
    rehearsal.add_argument("--duration-s", type=int, default=720)
    args = parser.parse_args(argv)
    if args.kind == "setup":
        path = create_setup_manifest(
            run_dir=args.run_dir,
            serial_device=args.serial_device,
            premise_matrix_path=args.premise_matrix,
            premise_build_manifest_path=args.premise_build_manifest,
            premise_uf2_path=args.premise_uf2,
            premise_flash_record_path=args.premise_flash_record,
        )
    elif args.kind == "live":
        path = create_live_manifest(
            run_dir=args.run_dir,
            build_manifest_path=args.build_manifest,
            uf2_path=args.uf2,
            static_proof_path=args.static_proof,
            rebound_matrix_path=args.rebound_matrix,
            serial_device=args.serial_device,
            duration_s=args.duration_s,
        )
    elif args.kind == "identity":
        path = create_identity_manifest(
            run_dir=args.run_dir,
            build_manifest_path=args.build_manifest,
            uf2_path=args.uf2,
            rebound_matrix_path=args.rebound_matrix,
            flash_record_path=args.flash_record,
            serial_device=args.serial_device,
        )
    else:
        path = create_rehearsal_manifest(
            run_dir=args.run_dir,
            build_manifest_path=args.build_manifest,
            uf2_path=args.uf2,
            static_proof_path=args.static_proof,
            rebound_matrix_path=args.rebound_matrix,
            serial_device=args.serial_device,
            duration_s=args.duration_s,
        )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
