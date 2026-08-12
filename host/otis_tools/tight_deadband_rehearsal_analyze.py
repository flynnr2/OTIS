"""Analyze and externally seal one exact-profile tight-deadband rehearsal."""

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
from .cx317_active_campaign import ACTIVE_CSV, HEALTH_CSV, _read_csv
from .active_status_contract import latest_complete_health
from .tight_deadband_manifest import (
    REHEARSAL_SEAL_TYPE,
    REHEARSAL_STAGE,
    _canonical_digest,
    validate_manifest,
)
from .tight_deadband_supervisor import (
    CONTROL_CSV,
    DAC_CSV,
    ENVIRONMENT_CSV,
    ESTIMATES_CSV,
    HPR_CSV,
    PHE_CSV,
    REHEARSAL_DURATION_S,
    RPH_CSV,
    TDB_CSV,
    load_tight_deadband_spec,
)
from .prewrite_readiness_contract import (
    environment_streams_ready,
    evaluate_prewrite_readiness,
)
from .tight_deadband_replay import replay_tight_deadband
from .evidence import EVIDENCE_MANIFEST, validate_evidence_snapshot
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, COMPLETE_MARKER, load_manifest
from .capture_device import SEGMENT_CLOSURE, SEGMENT_PROTOCOL_ID


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


def _capture_closure(
    run_dir: Path,
    capture_state: dict[str, Any],
    markers: list[dict[str, Any]],
    *,
    allowed_emergency_aborts: int = 0,
    allowed_reconnects: int = 0,
) -> dict[str, Any]:
    starts = [item for item in markers if item.get("event") == "capture_started"]
    stops = [item for item in markers if item.get("event") == "capture_stopped"]
    if len(starts) != 1 or len(stops) != 1:
        return {"ok": False, "mode": "invalid_marker_cardinality"}
    start = starts[0]
    stop = stops[0]
    counters_clean = (
        capture_state.get("capture_active") is False
        and int(capture_state.get("reconnect_count", -1))
        == allowed_reconnects
        and int(capture_state.get("parser_errors", -1)) == 0
        and int(capture_state.get("malformed_utf8", -1)) == 0
        and int(capture_state.get("commands_rejected", -1)) == 0
        and int(capture_state.get("emergency_aborts_sent", -1))
        == allowed_emergency_aborts
    )
    certificate_path = run_dir / SEGMENT_CLOSURE
    try:
        certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        certificate = {}
    owner_check = certificate.get("serial_owner_check")
    if not isinstance(owner_check, dict):
        owner_check = {}
    manifest_sha256 = _sha256_file(run_dir / "run_manifest.json")
    same_owner = (
        isinstance(start.get("owner_pid"), int)
        and start.get("owner_pid") == stop.get("owner_pid")
        and start.get("owner_pid") == capture_state.get("pid")
        and start.get("transport_generation")
        == stop.get("transport_generation")
        == capture_state.get("transport_generation")
    )
    logical_rotation = (
        capture_state.get("logical_segment_closed") is True
        and capture_state.get("serial_open") is True
        and capture_state.get("physical_serial_open") is True
        and stop.get("logical_rotation") is True
        and isinstance(stop.get("next_run"), str)
        and bool(stop.get("next_run"))
        and same_owner
        and certificate.get("closure_mode") == "same_owner_logical_rotation"
        and owner_check.get("performed") is True
        and owner_check.get("owner_pids")
        == [capture_state.get("pid")]
    )
    physical_close = (
        capture_state.get("serial_open") is False
        and capture_state.get("physical_serial_open", False) is False
        and stop.get("logical_rotation") in {None, False}
        and certificate.get("closure_mode") == "physical_serial_close"
    )
    certificate_exact = (
        certificate.get("schema_version") == 1
        and certificate.get("protocol") == SEGMENT_PROTOCOL_ID
        and certificate.get("run") == str(run_dir)
        and certificate.get("run_manifest_sha256") == manifest_sha256
        and certificate.get("owner_pid") == capture_state.get("pid")
        and certificate.get("transport_generation")
        == capture_state.get("transport_generation")
        and certificate.get("logical_segment_closed") is True
        and certificate.get("physical_serial_open")
        == capture_state.get("physical_serial_open", False)
        and certificate.get("serial_reopened") is False
        and certificate.get("next_run") == stop.get("next_run")
        and certificate.get("counters", {}).get("reconnect_count")
        == capture_state.get("reconnect_count")
        and certificate.get("counters", {}).get("parser_errors")
        == capture_state.get("parser_errors")
        and certificate.get("counters", {}).get("malformed_utf8")
        == capture_state.get("malformed_utf8")
        and certificate.get("counters", {}).get("commands_rejected")
        == capture_state.get("commands_rejected")
        and certificate.get("counters", {}).get("emergency_aborts_sent")
        == capture_state.get("emergency_aborts_sent")
    )
    mode = (
        "same_owner_logical_rotation"
        if logical_rotation
        else "physical_serial_close"
        if physical_close
        else "invalid"
    )
    return {
        "ok": (
            counters_clean
            and same_owner
            and certificate_exact
            and (logical_rotation or physical_close)
        ),
        "mode": mode,
        "owner_pid": stop.get("owner_pid"),
        "transport_generation": stop.get("transport_generation"),
        "next_run": stop.get("next_run"),
        "serial_reopened": False if logical_rotation else None,
        "certificate_path": str(SEGMENT_CLOSURE),
        "certificate_sha256": (
            _sha256_file(certificate_path) if certificate_path.is_file() else None
        ),
    }


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
    spec, identities, _ = load_tight_deadband_spec(leg_name)
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
    health = latest_complete_health(run_dir / HEALTH_CSV)
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
    readiness = evaluate_prewrite_readiness(
        health,
        expected_identity=identity,
        planned_live_stimulus_code=spec.start_code,
        active_row_count=len(active_rows),
        dac_row_count=len(dac_rows),
    )
    markers = _host_markers(run_dir / "raw/serial.log")
    duration_s = _capture_duration(markers)
    capture_state = json.loads((run_dir / CAPTURE_STATE).read_text(encoding="utf-8"))
    capture_closure = _capture_closure(run_dir, capture_state, markers)
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
        "zero_association_loss_decisions": validations.get(
            "association_loss_decisions_v1", {}
        ).get("rows")
        == 0,
        "finite_capture_at_least_2700s": duration_s >= REHEARSAL_DURATION_S,
        "capture_closed_cleanly": capture_closure["ok"],
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
        "stage5_prewrite_runtime_contract_exact": readiness.ready,
        "selected_600s_estimate_present": len(estimates) >= 1,
        "tight_deadband_replay_exact": tdb_replay.exact
        and tdb_replay.row_count >= 1,
        "phase_hybrid_and_tdb_zero_authority": all(
            _authority_false(run_dir / relative)
            for relative in (CONTROL_CSV, RPH_CSV, PHE_CSV, HPR_CSV, TDB_CSV)
        ),
        "both_environment_streams_present": environment_streams_ready(sources),
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
        str(SEGMENT_CLOSURE),
        str(SUPERVISOR_STATE),
        str(SUPERVISOR_EVENTS),
        str(EVIDENCE_MANIFEST),
        str(COMPLETE_MARKER),
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
            "capture_closure": capture_closure,
        },
        "runtime_contract": readiness.as_dict(),
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
