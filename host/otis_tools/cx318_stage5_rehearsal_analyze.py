"""Analyze and externally seal one exact-profile CX318 Stage 5 rehearsal."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .contracts import CsvValidationContext, validate_csv
from .cx317_active_campaign import ACTIVE_CSV, HEALTH_CSV, _latest_health, _read_csv
from .cx318_stage5_manifest import (
    REHEARSAL_SEAL_TYPE,
    REHEARSAL_STAGE,
    _canonical_digest,
    validate_manifest,
)
from .cx318_stage5_supervisor import (
    CONTROL_CSV,
    DAC_CSV,
    ENVIRONMENT_CSV,
    ESTIMATES_CSV,
    HPR_CSV,
    PHE_CSV,
    REHEARSAL_DURATION_S,
    RPH_CSV,
    TDB_CSV,
    load_stage5_spec,
)
from .cx318_stage5_tight_replay import replay_tight_deadband
from .evidence import EVIDENCE_MANIFEST, validate_evidence_snapshot
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, COMPLETE_MARKER, load_manifest


TOOL_ID = "cx318_stage5_rehearsal_analyze_v1"
OUTPUT = Path("reports/cx318_stage5_rehearsal_seal_v1.json")
SUPERVISOR_STATE = Path("reports/cx317_active_supervisor_state.json")
SUPERVISOR_EVENTS = Path("reports/cx317_active_supervisor_events.jsonl")
CAPTURE_STATE = Path("reports/capture_device_state.json")
HOST_MARKER_PREFIX = "# OTIS_HOST "


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _host_markers(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith(HOST_MARKER_PREFIX):
                result.append(json.loads(line[len(HOST_MARKER_PREFIX) :]))
    return result


def _parse_utc(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _capture_duration(markers: list[dict[str, Any]]) -> float:
    starts = [item for item in markers if item.get("event") == "capture_started"]
    stops = [item for item in markers if item.get("event") == "capture_stopped"]
    if len(starts) != 1 or len(stops) != 1:
        raise ValueError("rehearsal requires exactly one capture start and stop marker")
    return _parse_utc(str(stops[0]["utc"])) - _parse_utc(str(starts[0]["utc"]))


def _contract_path(manifest, contract: str) -> Path:
    matches = [
        manifest.root / str(item["path"])
        for item in manifest.files
        if item.get("contract") == contract
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one {contract} artifact, got {len(matches)}")
    return matches[0]


def _authority_false(path: Path) -> bool:
    rows = _read_csv(path)
    if not rows:
        return False
    for row in rows:
        for field in (
            "actionable",
            "actuation_authorized",
            "authorization_consumed",
        ):
            if field in row and row[field] != "false":
                return False
    return True


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite rehearsal seal: {path}")
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


def analyze(run_dir: Path) -> tuple[Path, dict[str, Any]]:
    run_dir = run_dir.resolve()
    if (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise ValueError("rehearsal capture is still active")
    if not (run_dir / COMPLETE_MARKER).is_file():
        raise ValueError("rehearsal is not marked complete")
    manifest_value = validate_manifest(run_dir / "run_manifest.json")
    if manifest_value.get("stage") != REHEARSAL_STAGE:
        raise ValueError("run is not a Stage 5 rehearsal manifest")
    leg_name = manifest_value["stage5"]["leg"]
    spec, identities, _ = load_stage5_spec(leg_name)
    manifest = load_manifest(run_dir)

    validations: dict[str, dict[str, Any]] = {}
    for contract in manifest_value["contracts"]:
        path = _contract_path(manifest, contract)
        result = validate_csv(
            path,
            CsvValidationContext(
                contract=contract,
                known_channels=manifest.known_channels,
                known_domains=manifest.known_domains,
                allow_rp2040_timer0_wrap=True,
            ),
        )
        validations[contract] = {
            "ok": result.ok,
            "rows": result.row_count,
            "errors": result.errors,
        }

    active_rows = _read_csv(run_dir / ACTIVE_CSV)
    dac_rows = _read_csv(run_dir / DAC_CSV)
    estimates = [
        row
        for row in _read_csv(run_dir / ESTIMATES_CSV)
        if row.get("estimator_version")
        == "cx317_selected_600s_nonoverlap_v1"
    ]
    tdb_replay = replay_tight_deadband(run_dir / TDB_CSV)
    health = _latest_health(run_dir / HEALTH_CSV)
    expected_build = (
        manifest_value["firmware"]["source_sha256"]
        + ":"
        + manifest_value["firmware"]["configuration_sha256"]
    )
    identity = {
        "run_identity": spec.run_identity,
        "build_identity": expected_build,
        "profile_identity": spec.profile,
        **identities,
    }
    identity_exact = all(
        health.get(("cx317_active", key)) == expected
        for key, expected in identity.items()
    )
    markers = _host_markers(run_dir / "raw/serial.log")
    duration_s = _capture_duration(markers)
    capture_state = json.loads((run_dir / CAPTURE_STATE).read_text(encoding="utf-8"))
    supervisor_state = json.loads(
        (run_dir / SUPERVISOR_STATE).read_text(encoding="utf-8")
    )
    supervisor_events = [
        json.loads(line)
        for line in (run_dir / SUPERVISOR_EVENTS)
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    sources = {
        row.get("source", "").lower()
        for row in _read_csv(run_dir / ENVIRONMENT_CSV)
    }
    evidence_failures, evidence_warnings = validate_evidence_snapshot(
        run_dir, manifest
    )
    evidence_path = run_dir / EVIDENCE_MANIFEST
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    checks = {
        "manifest_exact_rehearsal_leg_profile_and_build": True,
        "all_declared_contracts_validate": all(
            item["ok"] for item in validations.values()
        ),
        "finite_capture_at_least_2700s": duration_s >= REHEARSAL_DURATION_S,
        "capture_closed_cleanly": (
            capture_state.get("capture_active") is False
            and capture_state.get("serial_open") is False
            and int(capture_state.get("reconnect_count", -1)) == 0
            and int(capture_state.get("parser_errors", -1)) == 0
            and int(capture_state.get("malformed_utf8", -1)) == 0
            and int(capture_state.get("commands_rejected", -1)) == 0
            and int(capture_state.get("emergency_aborts_sent", -1)) == 0
        ),
        "supervisor_exact_no_write_terminal": (
            supervisor_state.get("stage5_mode") == "rehearsal"
            and supervisor_state.get("stage5_leg") == leg_name
            and supervisor_state.get("manual_start_sent") is False
            and int(supervisor_state.get("authorization_sequence", -1)) == 0
            and supervisor_state.get("terminal", {}).get("result")
            == "healthy_stop"
            and not any(
                item.get("event") in {
                    "stage5_exact_setup_requested",
                    "stage5_one_decision_armed",
                    "stage5_supervisor_fault",
                    "device_abort_submission_failed",
                }
                for item in supervisor_events
            )
        ),
        "zero_dac_or_active_rows": not dac_rows and not active_rows,
        "exact_active_identity_without_setup_or_arm": (
            identity_exact
            and health.get(("cx317_active", "state")) == "DISARMED"
            and health.get(("cx317_active", "manual_start_confirmed")) == "false"
            and health.get(("cx317_active", "arm_eligible")) == "false"
            and health.get(("cx317_active", "dac_epoch")) == "0"
        ),
        "build_bound_pre_setup_a828_epoch0": (
            health.get(("cx318_preview", "static_code")) == "0xA828"
            and health.get(("cx318_preview", "applied_code")) == "0xA828"
            and health.get(("cx318_preview", "dac_epoch")) == "0"
        ),
        "selected_600s_estimate_present": len(estimates) >= 1,
        "tight_deadband_replay_exact": tdb_replay.exact
        and tdb_replay.row_count >= 1,
        "phase_hybrid_and_tdb_zero_authority": all(
            _authority_false(run_dir / relative)
            for relative in (CONTROL_CSV, RPH_CSV, PHE_CSV, HPR_CSV, TDB_CSV)
        ),
        "both_environment_streams_present": {"sht4x", "bmp280"} <= sources,
        "live_health_has_no_drop_or_fault": (
            health.get(("capture", "dropped_count"), "0") == "0"
            and health.get(("capture", "pps_count_boundary_dropped_count"), "0")
            == "0"
            and health.get(("dual_core", "telemetry_dropped"), "0") == "0"
            and health.get(("dual_core", "partition_fault"), "none") == "none"
            and health.get(("dual_core", "fail_static"), "false") == "false"
            and health.get(("cx317_active", "fail_static"), "false") == "false"
            and health.get(("cx317_preview", "telemetry_dropped_frames"), "0")
            == "0"
        ),
        "sealed_evidence_snapshot_valid": (
            evidence.get("run_state") == "complete"
            and not evidence_failures
            and not evidence_warnings
        ),
    }
    status = "passed" if all(checks.values()) else "failed"
    source_paths = {
        "run_manifest.json",
        "raw/serial.log",
        str(CAPTURE_STATE),
        str(SUPERVISOR_STATE),
        str(SUPERVISOR_EVENTS),
        str(EVIDENCE_MANIFEST),
        *(str(item["path"]) for item in manifest.files),
    }
    source_hashes = {
        relative: _sha256_file(run_dir / relative)
        for relative in sorted(source_paths)
    }
    unsigned: dict[str, Any] = {
        "seal_type": REHEARSAL_SEAL_TYPE,
        "tool": TOOL_ID,
        "status": status,
        "leg": leg_name,
        "profile_id": spec.profile,
        "build_manifest_sha256": manifest_value["firmware"]["sha256"],
        "uf2_sha256": manifest_value["firmware"]["uf2"]["sha256"],
        "rehearsal": {
            "capture_duration_s": duration_s,
            "selected_600s_estimates": len(estimates),
            "setup_writes": 0,
            "dac_writes": 0,
            "automatic_writes": 0,
            "accelerated_or_relaxed_limits": False,
        },
        "run": {
            "path": str(run_dir),
            "manifest_sha256": _sha256_file(run_dir / "run_manifest.json"),
        },
        "evidence_snapshot": {
            "path": str(evidence_path),
            "sha256": _sha256_file(evidence_path),
            "snapshot_digest": evidence.get("snapshot_digest"),
        },
        "checks": checks,
        "contract_validation": validations,
        "tight_deadband_replay": tdb_replay.as_dict(),
        "source_artifacts_sha256": source_hashes,
    }
    result = {**unsigned, "seal_sha256": _canonical_digest(unsigned)}
    output = run_dir / OUTPUT
    _atomic_new_json(output, result)
    return output, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        output, result = analyze(args.run_dir)
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({"status": result["status"], "output": str(output)}, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
