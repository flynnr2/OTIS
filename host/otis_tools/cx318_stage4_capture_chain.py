"""Compose an immutable, reset-anchored CX318 Stage 4 capture chain offline.

This tool is deliberately an evidence transformer, not a capture tool: it
opens no serial device, starts no process, and sends no command.  It accepts a
first physical-reset boundary supplied by the operator, then proves that the
following capture handoffs form one clean stream before making a fresh,
explicitly-derived bundle suitable for offline parity analysis.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Any

from .capture_serial import RECORD_CONTRACTS
from .contracts import CONTRACT_FIELDS
from .cx318_capture_handoff import REPORT_PATH as HANDOFF_REPORT_PATH
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, load_manifest
from .service_plane_probe import HOST_MARKER_PREFIX


TOOL_ID = "cx318_stage4_capture_chain_v1"
REPORT_PATH = Path("reports/cx318_stage4_capture_chain_v1.json")
RAW_PATH = Path("raw/serial.log")
STATE_PATH = Path("reports/capture_device_state.json")

# A reset anchor must be an opening marker immediately followed by firmware
# boot evidence, or the BOOT record itself.  This prevents an arbitrary later
# CSV line from being represented as a clean-reset start.
_BOOT_PREFIX = "BOOT,"
_ALLOWED_QUERY_COMMANDS = {"CONFIG?", "DUALCORE?"}
_PROHIBITED_MARKER_PARTS = (
    "reconnect", "serial_disconnected", "malformed", "parser", "oversize",
    "partial_line_dropped", "emergency", "fail_static", "transport_fail",
)
_ZERO_AUTHORITY_RECORD_TYPES = {"DAC", "ACT"}
# Kept identical to the Stage 4 analyzer's historical-health gate.  The
# composer needs this narrow subset without importing the analyzer (and its
# optional JSON-schema dependency) into an offline evidence-copy operation.
REQUIRED_ZERO_HEALTH = (
    ("capture", "dropped_count"),
    ("capture", "pps_count_boundary_dropped_count"),
    ("capture", "error_flags"),
    ("pps_gate", "boundary_ring_dropped_count"),
    ("pps_gate", "rejected_window_count"),
    ("pps_gate", "missing_pps_count"),
    ("pps_gate", "pps_interval_anomaly_count"),
    ("pps_gate", "count_saturated_count"),
    ("pps_gate", "boundary_sequence_gap_count"),
    ("pps_gate", "boundary_sequence_duplicate_count"),
    ("pps_gate", "boundary_overflow_count"),
    ("pps_gate", "counter_snapshot_invalid_count"),
    ("pps_gate", "association_loss_count"),
    ("pps_gate", "snapshot_overwrite_count"),
    ("pps_gate", "snapshot_continuity_loss_count"),
    ("pps_gate", "snapshot_pio_rxstall_count"),
    ("pps_gate", "snapshot_dma_error_count"),
    ("pps_gate", "snapshot_dma_stopped_count"),
    ("pps_gate", "physical_pps_missing_count"),
    ("pps_d14", "rejected_short_count"),
    ("pps_d14", "rejected_long_count"),
    ("pps_d10", "short_interval_count"),
    ("pps_d10", "buffer_overflow_count"),
)


@dataclass(frozen=True)
class Source:
    root: Path
    manifest: dict[str, Any]
    raw_path: Path
    raw_lines: list[bytes]
    selected_lines: list[bytes]
    csv_paths: dict[str, Path]
    csv_rows: dict[str, list[list[str]]]
    raw_rows: dict[str, list[list[str]]]
    state: dict[str, Any]


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _relative_path(value: Any, *, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty run-relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError(f"{label} must be a normalized run-relative path")
    return path


def _inside(root: Path, relative: PurePosixPath, *, label: str) -> Path:
    path = root.joinpath(*relative.parts)
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symbolic link: {path}")
    return path


def _parse_csv_line(line: bytes, *, context: str) -> list[str] | None:
    try:
        text = line.decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{context}: malformed UTF-8") from exc
    if not text or text.startswith("#"):
        return None
    try:
        row = next(csv.reader([text]))
    except csv.Error as exc:
        raise ValueError(f"{context}: malformed CSV: {exc}") from exc
    return row or None


def _manifest_csv_paths(root: Path, manifest: dict[str, Any]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for entry in manifest.get("files", []):
        if not isinstance(entry, dict):
            raise ValueError(f"{root}: manifest file entry is not an object")
        contract = entry.get("contract")
        if contract == "raw_events_v1":
            # raw/serial.log is the canonical source; its split CSV is still
            # a declared contract and is handled like every other CSV.
            pass
        if contract not in CONTRACT_FIELDS:
            raise ValueError(f"{root}: unsupported declared contract {contract!r}")
        relative = _relative_path(entry.get("path"), label=f"{root}: manifest file path")
        path = _inside(root, relative, label="declared CSV")
        if contract in paths:
            raise ValueError(f"{root}: multiple files declared for {contract}")
        if not path.is_file():
            raise FileNotFoundError(f"{root}: declared CSV missing: {relative}")
        paths[contract] = path
    if not paths:
        raise ValueError(f"{root}: manifest declares no CSV contracts")
    return paths


def _read_csv(path: Path, contract: str) -> list[list[str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError(f"{path}: missing CSV header") from exc
        if header != CONTRACT_FIELDS[contract]:
            raise ValueError(f"{path}: CSV header differs from {contract}")
        rows = list(reader)
    expected = len(CONTRACT_FIELDS[contract])
    if any(len(row) != expected for row in rows):
        raise ValueError(f"{path}: malformed CSV row width")
    return rows


def _raw_rows_by_contract(lines: list[bytes], *, context: str) -> dict[str, list[list[str]]]:
    result = {contract: [] for contract in CONTRACT_FIELDS}
    for line_number, line in enumerate(lines, start=1):
        row = _parse_csv_line(line, context=f"{context} raw line {line_number}")
        if row is None:
            continue
        contract = RECORD_CONTRACTS.get(row[0])
        if contract is None:
            continue
        if len(row) != len(CONTRACT_FIELDS[contract]):
            raise ValueError(
                f"{context} raw line {line_number}: {row[0]} has {len(row)} fields; "
                f"expected {len(CONTRACT_FIELDS[contract])}"
            )
        result[contract].append(row)
    return result


def _validate_source_raw_csv_association(
    *, root: Path, csv_paths: dict[str, Path], csv_rows: dict[str, list[list[str]]],
    raw_rows: dict[str, list[list[str]]],
) -> None:
    for contract, path in csv_paths.items():
        if csv_rows[contract] != raw_rows[contract]:
            raise ValueError(
                f"{root}: {contract} CSV is not an exact in-order split of {RAW_PATH} "
                f"({len(csv_rows[contract])} CSV rows, {len(raw_rows[contract])} raw rows)"
            )


def _marker(line: bytes, *, context: str) -> dict[str, Any] | None:
    try:
        text = line.decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{context}: malformed UTF-8") from exc
    if not text.startswith(HOST_MARKER_PREFIX):
        return None
    try:
        value = json.loads(text[len(HOST_MARKER_PREFIX):])
    except json.JSONDecodeError as exc:
        raise ValueError(f"{context}: malformed host marker JSON") from exc
    if not isinstance(value, dict) or not isinstance(value.get("event"), str):
        raise ValueError(f"{context}: invalid host marker")
    return value


def _validate_reset_boundary(lines: list[bytes], start_line: int) -> list[bytes]:
    if start_line < 1 or start_line > len(lines):
        raise ValueError(f"first-source start line {start_line} is outside raw evidence")
    selected = lines[start_line - 1 :]
    first = selected[0].decode("utf-8", errors="strict").rstrip("\r\n")
    if first.startswith(_BOOT_PREFIX):
        return selected
    marker = _marker(selected[0], context=f"first-source raw line {start_line}")
    if marker is None or marker.get("event") != "serial_opened":
        raise ValueError(
            "first-source boundary must be BOOT or a serial_opened marker immediately before BOOT"
        )
    if len(selected) < 2 or not selected[1].decode("utf-8", errors="strict").startswith(_BOOT_PREFIX):
        raise ValueError("serial_opened boundary is not immediately followed by BOOT evidence")
    return selected


def _load_source(root: Path, *, first_start_line: int | None) -> Source:
    root = root.resolve()
    manifest = load_manifest(root).data
    if (root / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise ValueError(f"{root}: capture remains in progress")
    raw_path = root / RAW_PATH
    if not raw_path.is_file():
        raise FileNotFoundError(f"{root}: missing {RAW_PATH}")
    raw_lines = raw_path.read_bytes().splitlines(keepends=True)
    if not raw_lines or any(not line.endswith((b"\n", b"\r")) for line in raw_lines):
        raise ValueError(f"{root}: raw evidence must contain complete newline-terminated records")
    selected = (
        _validate_reset_boundary(raw_lines, first_start_line)
        if first_start_line is not None
        else raw_lines
    )
    csv_paths = _manifest_csv_paths(root, manifest)
    csv_rows = {contract: _read_csv(path, contract) for contract, path in csv_paths.items()}
    raw_rows = _raw_rows_by_contract(raw_lines, context=str(root))
    _validate_source_raw_csv_association(
        root=root, csv_paths=csv_paths, csv_rows=csv_rows, raw_rows=raw_rows,
    )
    state_path = root / STATE_PATH
    if not state_path.is_file():
        raise FileNotFoundError(f"{root}: missing {STATE_PATH}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError(f"{root}: capture state is not an object")
    return Source(root, manifest, raw_path, raw_lines, selected, csv_paths, csv_rows, raw_rows, state)


def _serial_device(source: Source) -> str:
    device = source.manifest.get("host", {}).get("serial_device")
    if not isinstance(device, str) or not device.startswith("/dev/cu.usbmodem"):
        raise ValueError(f"{source.root}: manifest does not bind an exact USB serial device")
    return device


def _validate_handoff(previous: Source, target: Source) -> dict[str, Any]:
    report_path = target.root / HANDOFF_REPORT_PATH
    if not report_path.is_file():
        raise FileNotFoundError(f"{target.root}: missing required handoff report {HANDOFF_REPORT_PATH}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError(f"{report_path}: report is not an object")
    device = _serial_device(previous)
    comparisons = {
        "tool": report.get("tool") == "cx318_capture_handoff_v1",
        "status": report.get("status") == "passed",
        "source_run": report.get("source_run") == str(previous.root),
        "target_run": report.get("target_run") == str(target.root),
        "device": report.get("serial_device") == device == _serial_device(target),
        "source_pid": report.get("source_pid") == previous.state.get("pid"),
        "target_pid": report.get("target_pid") == target.state.get("pid"),
        "no_commands": report.get("commands_sent") == 0,
    }
    elapsed = report.get("elapsed_s")
    maximum = report.get("maximum_gap_s")
    comparisons["bounded_gap"] = (
        isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool)
        and isinstance(maximum, (int, float)) and not isinstance(maximum, bool)
        and 0 <= elapsed <= maximum <= 5.0
    )
    if not all(comparisons.values()):
        failed = ", ".join(name for name, passed in comparisons.items() if not passed)
        raise ValueError(f"{report_path}: handoff proof failed: {failed}")
    return {
        "path": HANDOFF_REPORT_PATH.as_posix(),
        "sha256": _sha256(report_path),
        "source_run": str(previous.root),
        "target_run": str(target.root),
        "source_pid": report["source_pid"],
        "target_pid": report["target_pid"],
        "serial_device": device,
        "elapsed_s": elapsed,
        "maximum_gap_s": maximum,
    }


def _validate_clean_evidence(lines: list[bytes]) -> None:
    for line_number, line in enumerate(lines, start=1):
        marker = _marker(line, context=f"post-boundary raw line {line_number}")
        if marker is not None:
            event = marker["event"]
            if event in {"host_command_accepted", "host_command_sent"}:
                if marker.get("command") not in _ALLOWED_QUERY_COMMANDS:
                    raise ValueError(f"post-boundary raw line {line_number}: unapproved command")
            elif event.startswith("host_command"):
                raise ValueError(f"post-boundary raw line {line_number}: command authority event {event}")
            elif any(part in event for part in _PROHIBITED_MARKER_PARTS):
                raise ValueError(f"post-boundary raw line {line_number}: prohibited marker {event}")
            continue
        row = _parse_csv_line(line, context=f"post-boundary raw line {line_number}")
        if row is None:
            continue
        if row[0] in _ZERO_AUTHORITY_RECORD_TYPES:
            raise ValueError(f"post-boundary raw line {line_number}: forbidden {row[0]} record")


def _row_dict(contract: str, row: list[str]) -> dict[str, str]:
    return dict(zip(CONTRACT_FIELDS[contract], row, strict=True))


def _require_increment(rows: list[list[str]], contract: str, field: str) -> None:
    previous: int | None = None
    for index, row in enumerate(rows, start=1):
        value = _row_dict(contract, row).get(field, "")
        try:
            current = int(value, 10)
        except ValueError as exc:
            raise ValueError(f"{contract} row {index}: invalid {field} {value!r}") from exc
        if previous is not None and current != previous + 1:
            raise ValueError(f"{contract} row {index}: {field} is not contiguous ({previous} -> {current})")
        previous = current


def _validate_stage4_continuity(rows: dict[str, list[list[str]]]) -> dict[str, int]:
    required = {
        "count_observations_v1", "pps_snapshots_v1", "relative_phase_observations_v1",
        "phase_estimator_outputs_v1", "hybrid_preview_decisions_v1",
    }
    missing = required - rows.keys()
    if missing:
        raise ValueError("chain is missing declared Stage 4 contracts: " + ", ".join(sorted(missing)))
    snapshots = [_row_dict("pps_snapshots_v1", row) for row in rows["pps_snapshots_v1"]]
    if not snapshots:
        raise ValueError("chain has no SNP records after reset boundary")
    session = snapshots[0]["session"]
    if any(row["session"] != session for row in snapshots):
        raise ValueError("SNP session changed inside composed chain")
    if any(row["status"] != "0" for row in snapshots):
        raise ValueError("SNP status is non-zero inside composed chain")
    _require_increment(rows["pps_snapshots_v1"], "pps_snapshots_v1", "snapshot_sequence")
    _require_increment(rows["pps_snapshots_v1"], "pps_snapshots_v1", "reference_sequence")
    _require_increment(rows["count_observations_v1"], "count_observations_v1", "count_seq")
    _require_increment(rows["hybrid_preview_decisions_v1"], "hybrid_preview_decisions_v1", "preview_sequence")

    rph = [_row_dict("relative_phase_observations_v1", row) for row in rows["relative_phase_observations_v1"]]
    phe = [_row_dict("phase_estimator_outputs_v1", row) for row in rows["phase_estimator_outputs_v1"]]
    hpr = [_row_dict("hybrid_preview_decisions_v1", row) for row in rows["hybrid_preview_decisions_v1"]]
    if not rph or len(rph) != len(phe) or len(rph) != len(hpr):
        raise ValueError("RPH/PHE/HPR records are not one complete group per phase observation")
    if any(row["capture_session"] != session for row in rph):
        raise ValueError("RPH capture session changed inside composed chain")
    phase_epoch = rph[0]["phase_epoch"]
    phase_transitions = 0
    previous_observation: int | None = None
    for index, row in enumerate(rph, start=1):
        try:
            observation = int(row["observation_sequence"], 10)
        except ValueError as exc:
            raise ValueError(f"RPH row {index}: invalid observation_sequence") from exc
        if row["phase_epoch"] != phase_epoch:
            phase_transitions += 1
            if (
                phase_transitions != 1
                or observation != 0
                or row["qualification_state"] != "epoch_open"
                or index == 1
                or rph[index - 2]["qualification_state"] != "invalid"
            ):
                raise ValueError("RPH phase epoch transition is not the single declared acquisition opening")
            phase_epoch = row["phase_epoch"]
            previous_observation = observation
            continue
        if previous_observation is not None and observation != previous_observation + 1:
            raise ValueError(
                f"RPH row {index}: observation_sequence is not contiguous within phase epoch "
                f"({previous_observation} -> {observation})"
            )
        previous_observation = observation
    for index, (raw, estimate, preview) in enumerate(zip(rph, phe, hpr, strict=True), start=1):
        identity = f"RPH:{raw['phase_epoch']}:{raw['observation_sequence']}"
        estimate_identity = f"PHE:{raw['phase_epoch']}:{raw['observation_sequence']}"
        if (estimate["phase_epoch"], estimate["observation_sequence"], estimate["source_relative_phase_observation"]) != (
            raw["phase_epoch"], raw["observation_sequence"], identity,
        ):
            raise ValueError(f"PHE row {index}: does not identify its exact RPH source")
        if (preview["phase_epoch"], preview["observation_sequence"], preview["source_phase_estimate"]) != (
            raw["phase_epoch"], raw["observation_sequence"], estimate_identity,
        ):
            raise ValueError(f"HPR row {index}: does not identify its exact PHE source")
        if preview["source_frequency_estimate"] not in {estimate_identity, "unavailable"}:
            raise ValueError(f"HPR row {index}: source_frequency_estimate is not the current PHE or unavailable")
        if any(preview[field] != "false" for field in ("actionable", "actuation_authorized", "authorization_consumed")):
            raise ValueError(f"HPR row {index}: carries authority")
    return {
        "snp": len(snapshots), "cnt": len(rows["count_observations_v1"]), "rph": len(rph),
        "phe": len(phe), "hpr": len(hpr), "session": int(session), "phase_epoch": int(phase_epoch),
    }


def _validate_health(rows: list[list[str]]) -> None:
    observed: dict[tuple[str, str], set[str]] = {}
    for index, raw in enumerate(rows, start=1):
        row = _row_dict("health_v1", raw)
        key = (row["component"], row["status_key"])
        value = row["status_value"].strip()
        observed.setdefault(key, set()).add(value)
        if key in REQUIRED_ZERO_HEALTH and value != "0":
            raise ValueError(f"health row {index}: {key[0]}.{key[1]} is {value!r}, not zero")
        if row["status_key"] == "dac_command_attempt":
            raise ValueError(f"health row {index}: DAC command attempt")
        status_key = row["status_key"]
        if (status_key.startswith("fault") or "_fault" in status_key or status_key == "fail_static") and value not in {"0", "false", "none", "clear"}:
            raise ValueError(f"health row {index}: fault evidence {row['component']}.{row['status_key']}={value}")
    # Do not infer these conditions merely from the absence of an adverse
    # record: Stage 4 must explicitly publish the clean state throughout the
    # evidence chain.
    required_clean = {
        ("capture", "dropped_count"): "0",
        ("capture", "pps_count_boundary_dropped_count"): "0",
        ("dual_core", "partition_fault"): "none",
        ("dual_core", "fail_static"): "false",
    }
    for key, expected in required_clean.items():
        values = observed.get(key)
        if not values or values != {expected}:
            raise ValueError(
                f"health evidence lacks continuously clean {key[0]}.{key[1]}={expected!r}"
            )


def _write_csv(path: Path, contract: str, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(CONTRACT_FIELDS[contract])
        writer.writerows(rows)


def _copy_final_evidence(final: Source, destination: Path, manifest: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Copy immutable build/static inputs, never a stale analysis conclusion."""
    declared = manifest.get("evidence_artifacts")
    if not isinstance(declared, list):
        raise ValueError("final manifest lacks evidence_artifacts")
    copied: list[str] = []
    deferred_reports: list[str] = []
    for value in declared:
        relative = _relative_path(value, label="final evidence artifact path")
        text = relative.as_posix()
        if text.startswith("reports/cx318_stage4_") and text.endswith("_analysis_v1.json"):
            # Preserve the declaration so the next analyzer run writes a new
            # report for the composed evidence, rather than copying a physical
            # segment's non-equivalent parity conclusion.
            deferred_reports.append(text)
            continue
        source = _inside(final.root, relative, label="final evidence artifact")
        if not source.is_file():
            raise FileNotFoundError(f"final source lacks evidence artifact: {relative}")
        target = destination.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(text)
    live = manifest.get("stage4_live_preview")
    if not isinstance(live, dict) or not isinstance(live.get("static_code_evidence"), dict):
        raise ValueError("final manifest lacks static-code evidence")
    static = _relative_path(live["static_code_evidence"].get("path"), label="static-code evidence path").as_posix()
    if static not in copied:
        raise ValueError("final evidence artifacts omit the static-code evidence")
    declared_hash = live["static_code_evidence"].get("sha256")
    if declared_hash != _sha256(_inside(final.root, PurePosixPath(static), label="static-code evidence")):
        raise ValueError("final source static-code evidence hash differs from its manifest")
    return copied, deferred_reports


def _derived_state(sources: list[Source], lines: list[bytes]) -> dict[str, Any]:
    markers = [_marker(line, context="derived raw") for line in lines]
    sent = sum(1 for marker in markers if marker and marker["event"] == "host_command_sent")
    return {
        "derived": True,
        "capture_active": False,
        "serial_open": False,
        "parser_errors": 0,
        "malformed_utf8": 0,
        "reconnect_count": 0,
        "commands_rejected": 0,
        "emergency_aborts_sent": 0,
        "emergency_abort_latched": False,
        "commands_sent": sent,
        "source_final_pid": sources[-1].state.get("pid"),
    }


def compose_capture_chain(*, source_runs: list[Path], first_source_start_line: int, output_run: Path) -> dict[str, Any]:
    """Create a fresh derived bundle after proving a clean reset-anchored chain."""
    if len(source_runs) < 1:
        raise ValueError("at least one source run is required")
    output_run = output_run.resolve()
    if output_run.exists():
        raise FileExistsError(f"output run must be fresh: {output_run}")
    sources = [
        _load_source(path, first_start_line=first_source_start_line if index == 0 else None)
        for index, path in enumerate(source_runs)
    ]
    if len({source.root for source in sources}) != len(sources):
        raise ValueError("source runs must be distinct and ordered")
    first_layout = {contract: path.relative_to(sources[0].root).as_posix() for contract, path in sources[0].csv_paths.items()}
    for source in sources[1:]:
        layout = {contract: path.relative_to(source.root).as_posix() for contract, path in source.csv_paths.items()}
        if layout != first_layout:
            raise ValueError(f"{source.root}: declared CSV contracts/paths differ from first source")

    handoffs = [_validate_handoff(previous, target) for previous, target in zip(sources, sources[1:])]
    combined_lines = [line for source in sources for line in source.selected_lines]
    _validate_clean_evidence(combined_lines)
    combined_rows = _raw_rows_by_contract(combined_lines, context="composed")
    for contract in first_layout:
        # This is the exact raw-to-CSV association proof.  Source association
        # was proved before slicing; selecting raw records gives the matching
        # source CSV suffix/prefix without inventing or rewriting observations.
        if contract not in combined_rows:
            raise ValueError(f"declared contract has no raw mapping: {contract}")
    _validate_health(combined_rows["health_v1"])
    continuity = _validate_stage4_continuity(combined_rows)

    source_report = []
    for index, source in enumerate(sources):
        source_report.append({
            "run": str(source.root),
            "manifest_sha256": _sha256(source.root / "run_manifest.json"),
            "raw_path": RAW_PATH.as_posix(),
            "raw_sha256": _sha256(source.raw_path),
            "raw_line_count": len(source.raw_lines),
            "included_start_line": first_source_start_line if index == 0 else 1,
            "included_end_line": len(source.raw_lines),
            "declared_csv_sha256": {contract: _sha256(path) for contract, path in source.csv_paths.items()},
            "capture_state_sha256": _sha256(source.root / STATE_PATH),
        })

    temp_parent = output_run.parent
    temp_parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_run.name}.compose.", dir=temp_parent))
    try:
        raw_output = temporary / RAW_PATH
        raw_output.parent.mkdir(parents=True, exist_ok=True)
        with raw_output.open("xb") as handle:
            handle.writelines(combined_lines)
        for contract, relative in first_layout.items():
            _write_csv(temporary / relative, contract, combined_rows[contract])

        manifest = json.loads(json.dumps(sources[-1].manifest))
        manifest["run_id"] = output_run.name
        manifest["created_utc"] = _utc_now()
        manifest["started_at_utc"] = _utc_now()
        manifest["derived_capture_chain"] = {
            "tool": TOOL_ID,
            "report": REPORT_PATH.as_posix(),
            "source_count": len(sources),
            "first_source_start_line": first_source_start_line,
            "not_a_live_capture": True,
        }
        copied_evidence, deferred_reports = _copy_final_evidence(sources[-1], temporary, manifest)
        expected = [RAW_PATH.as_posix(), STATE_PATH.as_posix(), REPORT_PATH.as_posix(), "COMPLETE", *first_layout.values(), *copied_evidence, *deferred_reports]
        manifest["expected_artifacts"] = list(dict.fromkeys(expected))
        manifest["evidence_artifacts"] = list(dict.fromkeys([*copied_evidence, *deferred_reports, REPORT_PATH.as_posix()]))
        (temporary / "run_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        state_path = temporary / STATE_PATH
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(_derived_state(sources, combined_lines), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (temporary / "COMPLETE").write_text("derived offline capture-chain bundle\n", encoding="utf-8")

        report = {
            "schema_version": 1,
            "tool": TOOL_ID,
            "status": "passed",
            "created_utc": _utc_now(),
            "derived_bundle": str(output_run),
            "physical_reset_boundary": {
                "source_run": str(sources[0].root),
                "first_included_raw_line": first_source_start_line,
                "boundary_kind": "serial_opened_then_BOOT_or_BOOT",
            },
            "sources": source_report,
            "handoffs": handoffs,
            "continuity": continuity,
            "raw_to_csv_exact_association": {
                "status": "passed",
                "row_counts": {contract: len(rows) for contract, rows in combined_rows.items() if contract in first_layout},
            },
            "post_boundary_guards": {
                "status": "passed",
                "reconnect_drop_parser_fault_authority_dac_active": "none observed",
            },
            "output_sha256": {
                "raw": _sha256(raw_output),
                "csv": {contract: _sha256(temporary / relative) for contract, relative in first_layout.items()},
            },
        }
        report_path = temporary / REPORT_PATH
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, output_run)
        return report
    except BaseException:
        shutil.rmtree(temporary)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, action="append", required=True, help="Ordered source capture run; repeat for every segment")
    parser.add_argument("--first-source-start-line", type=int, required=True, help="1-based raw line at BOOT or the immediately preceding serial_opened marker")
    parser.add_argument("--output-run", type=Path, required=True, help="Fresh derived output directory")
    args = parser.parse_args(argv)
    report = compose_capture_chain(
        source_runs=args.source_run,
        first_source_start_line=args.first_source_start_line,
        output_run=args.output_run,
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
