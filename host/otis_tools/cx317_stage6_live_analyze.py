"""Validate the CX317 Stage 6 long observe-only live-preview run.

The analyzer is deliberately offline: it refuses an in-progress capture and
never opens a serial device.  It recomputes every emitted estimator window
from captured CNT/SNP evidence and replays every controller decision through
the selected host I-only engine.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import argparse
import csv
import json
import math
import statistics
import tempfile
from typing import Any, Iterable

from .contracts import CsvValidationContext, validate_csv
from .cx317_i_only_preview_replay import (
    DEFAULT_POLICY,
    IOnlyPreviewEngine,
    Observation,
    Policy,
    load_policy,
)
from .cx317_pps_plant_characterize import PROVENANCE_FIELDS, _markdown_table
from .pps_cumulative_span_estimator import (
    COUNT_INVALID_FLAGS,
    REFERENCE_INVALID_FLAGS,
    _health_global_reasons,
    _transport_global_reasons,
)
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, load_manifest
from .service_plane_probe import (
    HOST_MARKER_PREFIX,
    REQUIRED_LATEST_HEALTH,
    inspect_raw_log,
)
from .timebase import unwrap_ticks


TOOL_VERSION = "cx317_stage6_live_analyze_v1"
OUTPUT_DIR = Path("derived/cx317_stage6_live_preview_v1")
OUTPUT_NAME = "stage6_live_preview_v1.json"
REPORT_NAME = "STAGE6_LIVE_PREVIEW.md"
TICKS_PER_SECOND = 16_000_000
SERIALIZED_12_DECIMAL_HALF_UNIT = 5e-13
EXPECTED_STAGE = "CX317_PPS_GATED_I_ONLY_PREVIEW"
EXPECTED_BACKEND = "pio_wait_cumulative_snapshot_dma_v1"
EXPECTED_ESTIMATOR_METHOD = "PPS_CUMULATIVE_SNAPSHOT_SPAN_V1"
EXPECTED_DIAGNOSTIC_VERSION = "cx317_diagnostic_60s_overlap_v1"
EXPECTED_SELECTED_VERSION = "cx317_selected_600s_nonoverlap_v1"
AUTHORITY_KEYS = (
    "control_ready",
    "actuation_enabled",
    "actuation_authorized",
    "actionable",
)
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
    ("cx317_preview", "telemetry_dropped_frames"),
)


@dataclass(frozen=True)
class Check:
    identifier: str
    passed: bool
    evidence: str


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
        suffix=".tmp", delete=False,
    ) as handle:
        handle.write(value)
        temporary = Path(handle.name)
    temporary.replace(path)


def _write_json(path: Path, value: Any) -> None:
    _write_atomic(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _utc_seconds(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _bool(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"malformed Boolean {value!r}")


def _serialized_difference(value: str, expected: float) -> float:
    """Compare decimal wire text without losing digits near a large offset."""

    return float(abs(Decimal(value) - Decimal.from_float(expected)))


def _contract_path(manifest: Any, contract: str) -> Path:
    paths = [
        manifest.root / str(item["path"])
        for item in manifest.files
        if item.get("contract") == contract
    ]
    if len(paths) != 1:
        raise ValueError(f"expected one {contract} artifact, got {len(paths)}")
    return paths[0]


def _validate_sources(manifest: Any, paths: dict[str, Path]) -> None:
    for name, contract in (
        ("references", "raw_events_v1"),
        ("counts", "count_observations_v1"),
        ("snapshots", "pps_snapshots_v1"),
        ("health", "health_v1"),
        ("dac", "dac_steps_v1"),
        ("environment", "environment_v1"),
        ("estimates", "estimates_v2"),
        ("controls", "control_previews_v1"),
    ):
        result = validate_csv(
            paths[name],
            CsvValidationContext(
                contract=contract,
                known_channels=manifest.known_channels,
                known_domains=manifest.known_domains,
                template=False,
                allow_rp2040_timer0_wrap=True,
            ),
        )
        if result.errors:
            raise ValueError(f"{paths[name]}: " + "; ".join(result.errors))


def _host_markers(raw_log: Path) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    current_count: int | None = None
    with raw_log.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\r\n")
            if line.startswith("CNT,"):
                try:
                    current_count = int(line.split(",", 4)[2])
                except (IndexError, ValueError):
                    pass
                continue
            if not line.startswith(HOST_MARKER_PREFIX):
                continue
            marker = json.loads(line[len(HOST_MARKER_PREFIX) :])
            if not isinstance(marker, dict):
                raise ValueError("host marker is not a JSON object")
            output.append({**marker, "count_sequence": current_count})
    return output


def _one_marker(markers: list[dict[str, Any]], event: str) -> dict[str, Any]:
    matches = [item for item in markers if item.get("event") == event]
    if len(matches) != 1:
        raise ValueError(f"expected one {event} marker, got {len(matches)}")
    return matches[0]


def _latest_health(rows: Iterable[dict[str, str]]) -> dict[tuple[str, str], str]:
    output: dict[tuple[str, str], str] = {}
    for row in rows:
        output[(row["component"], row["status_key"])] = row["status_value"].strip()
    return output


def _source_evidence(paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        for name, path in paths.items()
    }


def _firmware_build_binding(
    manifest_data: dict[str, Any],
    build_manifest_path: Path | None,
    uf2_path: Path | None,
) -> tuple[Check, dict[str, Any]]:
    """Bind the declared run identity to the exact matrix build and UF2."""

    if build_manifest_path is None or uf2_path is None:
        result = {
            "status": "unavailable",
            "build_manifest_path": (
                str(build_manifest_path) if build_manifest_path is not None else None
            ),
            "uf2_path": str(uf2_path) if uf2_path is not None else None,
            "reason": "both matrix build manifest and UF2 evidence are required",
        }
        return Check(
            "exact_firmware_build_binding",
            False,
            "matrix build manifest and/or exact UF2 evidence unavailable",
        ), result

    try:
        build = _read_json(build_manifest_path)
        firmware = manifest_data["firmware"]
        provenance = build["provenance"]
        configuration = provenance["configuration"]
        source = provenance["source"]
        artifacts = build["artifacts"]
        if not isinstance(artifacts, list):
            raise TypeError("build artifacts must be a list")
        matches = [
            item for item in artifacts
            if isinstance(item, dict) and item.get("name") == uf2_path.name
        ]
        if len(matches) != 1:
            raise ValueError(
                f"expected one {uf2_path.name} artifact in build manifest, got {len(matches)}"
            )
        artifact = matches[0]
        actual_sha256 = _sha256_file(uf2_path)
        actual_size = uf2_path.stat().st_size
        comparisons = {
            "profile_id": configuration["profile_id"] == firmware["config_id"],
            "configuration_sha256": (
                configuration["sha256"] == firmware["configuration_sha256"]
            ),
            "source_sha256": source["sha256"] == firmware["source_sha256"],
            "git_commit": source["git_commit"] == firmware["git_commit"],
            "source_state": source["state"] == firmware["source_state"],
            "artifact_manifest_sha256": (
                artifact["sha256"] == firmware["uf2_sha256"]
            ),
            "artifact_manifest_size": (
                int(artifact["size_bytes"]) == int(firmware["uf2_size_bytes"])
            ),
            "actual_uf2_sha256": actual_sha256 == firmware["uf2_sha256"],
            "actual_uf2_size": actual_size == int(firmware["uf2_size_bytes"]),
        }
        passed = all(comparisons.values())
        result = {
            "status": "pass" if passed else "fail",
            "build_manifest_path": str(build_manifest_path),
            "build_manifest_sha256": _sha256_file(build_manifest_path),
            "uf2_path": str(uf2_path),
            "actual_uf2_sha256": actual_sha256,
            "actual_uf2_size_bytes": actual_size,
            "declared_source_sha256": firmware["source_sha256"],
            "declared_configuration_sha256": firmware["configuration_sha256"],
            "declared_uf2_sha256": firmware["uf2_sha256"],
            "declared_uf2_size_bytes": firmware["uf2_size_bytes"],
            "build_invocation_id": provenance["invocation"]["id"],
            "comparisons": comparisons,
        }
        failed = [key for key, value in comparisons.items() if not value]
        evidence = (
            f"source/config/UF2/size exact; invocation {provenance['invocation']['id']}"
            if passed else "mismatched fields: " + ", ".join(failed)
        )
        return Check("exact_firmware_build_binding", passed, evidence), result
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        result = {
            "status": "fail",
            "build_manifest_path": str(build_manifest_path),
            "uf2_path": str(uf2_path),
            "reason": str(exc),
        }
        return Check(
            "exact_firmware_build_binding",
            False,
            f"firmware build evidence invalid: {exc}",
        ), result


def _check_continuity(
    counts: list[dict[str, str]],
    snapshots: list[dict[str, str]],
    references: list[dict[str, str]],
) -> tuple[list[Check], dict[int, dict[str, str]]]:
    checks: list[Check] = []
    count_sequences = [int(row["count_seq"]) for row in counts]
    snapshot_sequences = [int(row["snapshot_sequence"]) for row in snapshots]
    expected_counts = list(range(count_sequences[0], count_sequences[-1] + 1))
    expected_snapshots = list(
        range(snapshot_sequences[0], snapshot_sequences[-1] + 1)
    )
    checks.append(Check(
        "count_sequence_continuity",
        count_sequences == expected_counts,
        f"observed {count_sequences[0]}..{count_sequences[-1]} / {len(count_sequences)} rows",
    ))
    checks.append(Check(
        "snapshot_sequence_continuity",
        snapshot_sequences == expected_snapshots,
        f"observed {snapshot_sequences[0]}..{snapshot_sequences[-1]} / {len(snapshot_sequences)} rows",
    ))
    count_by_seq = {int(row["count_seq"]): row for row in counts}
    snapshot_by_seq = {int(row["snapshot_sequence"]): row for row in snapshots}
    reference_timestamps = {
        int(row["timestamp_ticks"])
        for row in references
        if row["record_type"] == "REF"
        and row["edge"] == "R"
        and int(row["channel_id"]) == 1
    }
    valid = True
    mismatch_count = 0
    for sequence, closing in snapshot_by_seq.items():
        if int(closing["status"]) != 0 or closing["backend"] != EXPECTED_BACKEND:
            valid = False
        if int(closing["reference_timestamp_ticks"]) not in reference_timestamps:
            valid = False
        opening = snapshot_by_seq.get(sequence - 1)
        count = count_by_seq.get(sequence)
        if opening is None or count is None:
            continue
        reconstructed = (
            int(opening["cumulative_down_counter"])
            - int(closing["cumulative_down_counter"])
        ) & 0xFFFFFFFF
        if reconstructed != int(count["counted_edges"]):
            mismatch_count += 1
        if int(count["flags"]) & COUNT_INVALID_FLAGS:
            valid = False
    if any(int(row["flags"]) & REFERENCE_INVALID_FLAGS for row in references):
        valid = False
    checks.append(Check(
        "raw_snapshot_count_parity",
        valid and mismatch_count == 0,
        f"{mismatch_count} adjacent SNP/CNT mismatches; backend={EXPECTED_BACKEND}",
    ))
    return checks, count_by_seq


def _estimate_parity(
    rows: list[dict[str, str]],
    count_by_seq: dict[int, dict[str, str]],
    manifest: dict[str, Any],
) -> tuple[list[Check], dict[str, Any], dict[str, dict[str, str]]]:
    selected_binding = manifest["selected_estimator"]
    expected_hash = str(selected_binding["profile_sha256"])
    expected_sequences = list(range(len(rows)))
    actual_sequences = [int(row["estimate_seq"]) for row in rows]
    identity_ok = actual_sequences == expected_sequences
    max_frequency_difference = 0.0
    max_error_difference = 0.0
    parity_ok = True
    selected: list[dict[str, str]] = []
    diagnostic: list[dict[str, str]] = []
    by_id: dict[str, dict[str, str]] = {}
    comparisons: list[dict[str, Any]] = []
    for row in rows:
        identifier = row["estimate_id"]
        if identifier in by_id:
            parity_ok = False
        by_id[identifier] = row
        is_selected = row["estimator_version"] == EXPECTED_SELECTED_VERSION
        is_diagnostic = row["estimator_version"] == EXPECTED_DIAGNOSTIC_VERSION
        span = 600 if is_selected else 60 if is_diagnostic else 0
        if is_selected:
            selected.append(row)
        elif is_diagnostic:
            diagnostic.append(row)
        else:
            parity_ok = False
            continue
        first = int(row["source_reference_first_seq"])
        last = int(row["source_reference_last_seq"])
        interval_sequences = list(range(first + 1, last + 1))
        source_rows = [count_by_seq.get(sequence) for sequence in interval_sequences]
        if len(interval_sequences) != span or any(item is None for item in source_rows):
            parity_ok = False
            continue
        total = sum(int(item["counted_edges"]) for item in source_rows if item)
        host_frequency = float(total) / float(span)
        host_error = host_frequency - float(manifest["oscillator"]["nominal_frequency_hz"])
        observed_frequency = float(row["frequency_estimate_hz"])
        frequency_difference = max(
            _serialized_difference(row["frequency_estimate_hz"], host_frequency),
            _serialized_difference(row["frequency_observation_hz"], host_frequency),
        )
        error_difference = _serialized_difference(row["frequency_error_hz"], host_error)
        max_frequency_difference = max(max_frequency_difference, frequency_difference)
        max_error_difference = max(max_error_difference, error_difference)
        fields_ok = (
            int(row["source_count_seq"]) == last
            and row["source_count_ref"] == f"live:CNT:{last}"
            and int(row["accepted_sample_count"]) == span
            and row["config_hash"] == expected_hash
            and row["observation_validity"] == "valid"
            and row["reference_validity"] == "valid"
            and row["reference_continuity"] == "true"
            and row["count_validity"] == "valid"
            and row["count_continuity"] == "true"
            and row["diagnostic_health"] == "healthy"
            and row["uncertainty_status"] == "unavailable"
            and row["combined_standard_uncertainty_hz"] == ""
            and row["expanded_uncertainty_hz"] == ""
            and row["drift_enabled"] == "false"
        )
        parity_ok = parity_ok and fields_ok and (
            frequency_difference <= SERIALIZED_12_DECIMAL_HALF_UNIT
            and error_difference <= SERIALIZED_12_DECIMAL_HALF_UNIT
        )
        comparisons.append({
            "estimate_id": identifier,
            "span_s": span,
            "first_sequence": first,
            "last_sequence": last,
            "total_counted_edges": total,
            "host_frequency_hz": host_frequency,
            "firmware_frequency_hz": observed_frequency,
            "absolute_frequency_difference_hz": frequency_difference,
            "absolute_error_difference_hz": error_difference,
            "pass": fields_ok
            and frequency_difference <= SERIALIZED_12_DECIMAL_HALF_UNIT
            and error_difference <= SERIALIZED_12_DECIMAL_HALF_UNIT,
        })
    selected_last = [int(row["source_reference_last_seq"]) for row in selected]
    selected_nonoverlap = all(
        closing - opening == 600
        for opening, closing in zip(selected_last, selected_last[1:])
    )
    checks = [
        Check(
            "estimate_sequence_and_identity",
            identity_ok and bool(rows),
            f"{len(rows)} contiguous estimate rows; config {expected_hash}",
        ),
        Check(
            "estimator_host_firmware_numeric_parity",
            parity_ok and bool(rows),
            "max frequency/error differences "
            f"{max_frequency_difference:.17g}/{max_error_difference:.17g} Hz "
            f"against {SERIALIZED_12_DECIMAL_HALF_UNIT:.1e} Hz serialization tolerance",
        ),
        Check(
            "selected_estimator_live_execution",
            bool(selected) and selected_nonoverlap,
            f"{len(selected)} 600 s non-overlapping rows; {len(diagnostic)} 60 s diagnostic rows",
        ),
    ]
    frequencies = [float(row["frequency_estimate_hz"]) for row in selected]
    result = {
        "row_count": len(rows),
        "selected_row_count": len(selected),
        "diagnostic_row_count": len(diagnostic),
        "selected_preview_eligible_count": sum(
            _bool(row["preview_eligibility"]) for row in selected
        ),
        "maximum_frequency_difference_hz": max_frequency_difference,
        "maximum_error_difference_hz": max_error_difference,
        "numeric_tolerance_hz": SERIALIZED_12_DECIMAL_HALF_UNIT,
        "selected_frequency_minimum_hz": min(frequencies) if frequencies else None,
        "selected_frequency_maximum_hz": max(frequencies) if frequencies else None,
        "selected_frequency_population_stddev_hz": (
            statistics.pstdev(frequencies) if len(frequencies) > 1 else 0.0
            if frequencies else None
        ),
        "comparisons": comparisons,
    }
    return checks, result, by_id


def _temperature_for_tick(
    rows: list[tuple[dict[str, str], int]], timestamp_ticks: int
) -> float | None:
    candidates = [
        row for row, unwrapped_ticks in rows
        if row["source"] == "sht4x"
        and row["role"] == "vcocxo_near"
        and unwrapped_ticks <= timestamp_ticks
    ]
    return float(candidates[-1]["temperature_c"]) if candidates else None


def _mapped_state(value: str) -> str:
    return {
        "WARMUP_INHIBIT": "WARMUP_INHIBIT",
        "QUALIFYING": "QUALIFYING",
        "SETTLING_INHIBIT": "SETTLE_PREVIEW",
        "TRACKING": "LOCKED_PREVIEW",
        "FAULT": "FAULT",
        "ABORTED": "FAULT",
    }[value]


def _controller_parity(
    rows: list[dict[str, str]],
    estimates_by_id: dict[str, dict[str, str]],
    environment: list[dict[str, str]],
    policy: Policy,
) -> tuple[list[Check], dict[str, Any]]:
    engine = IOnlyPreviewEngine(policy)
    decision_ticks, decision_wrap_count = unwrap_ticks([
        int(row["decision_timestamp_ticks"]) for row in rows
    ])
    environment_ticks, environment_wrap_count = unwrap_ticks([
        int(row["timestamp_ticks"]) for row in environment
    ])
    unwrapped_environment = list(zip(environment, environment_ticks))
    raw_delta_tolerance_codes = (
        abs(policy.integrator_gain) + 1.0
    ) * SERIALIZED_12_DECIMAL_HALF_UNIT
    parity_ok = True
    max_error_difference = 0.0
    max_delta_difference = 0.0
    comparisons: list[dict[str, Any]] = []
    expected_sequences = list(range(len(rows)))
    actual_sequences = [int(row["control_seq"]) for row in rows]
    for row, timestamp_ticks in zip(rows, decision_ticks):
        timestamp_s = timestamp_ticks // TICKS_PER_SECOND
        source = estimates_by_id.get(row["est_input_ref"])
        frequency_error = (
            float(source["frequency_error_hz"]) if source is not None else None
        )
        temperature = _temperature_for_tick(
            unwrapped_environment, timestamp_ticks
        )
        model_applicable = row["model_applicability"] == "applicable"
        previous = engine.state
        host = engine.process(Observation(
            timestamp_s=timestamp_s,
            frequency_error_hz=frequency_error,
            current_code=int(row["current_dac_code"]),
            temperature_c=temperature,
            estimator_valid=True,
            reference_valid=True,
            count_valid=True,
            model_applicable=model_applicable,
            applied_code_matches=True,
            i2c_ok=True,
        ))
        host_error = host["frequency_error_hz"]
        error_difference = (
            0.0 if row["frequency_error_hz"] == "" and host_error is None else
            math.inf if row["frequency_error_hz"] == "" or host_error is None else
            _serialized_difference(row["frequency_error_hz"], float(host_error))
        )
        host_delta = host["raw_delta_codes"]
        delta_difference = (
            0.0 if row["raw_delta_codes"] == "" and host_delta is None else
            math.inf if row["raw_delta_codes"] == "" or host_delta is None else
            _serialized_difference(row["raw_delta_codes"], float(host_delta))
        )
        max_error_difference = max(max_error_difference, error_difference)
        max_delta_difference = max(max_delta_difference, delta_difference)
        expected_model_reason = (
            "model_applicable_observe_only" if model_applicable else
            "temperature_unavailable" if temperature is None else
            "temperature_model_mismatch"
        )
        exact = (
            row["time_domain"] == "rp2040_timer0"
            and row["plant_model_hash"] == policy.plant_model_hash
            and row["policy_version"] == policy.policy_id
            and row["config_hash"] == policy.config_hash
            and row["control_state"] == _mapped_state(str(host["state"]))
            and row["previous_control_state"] == _mapped_state(previous)
            and _bool(row["state_transition"]) == (previous != host["state"])
            and row["transition_reason_code"] == host["reason"]
            and _bool(row["preview_eligibility"]) == bool(host["preview_available"])
            and _bool(row["preview_available"]) == bool(host["preview_available"])
            and row["model_reason_codes"] == expected_model_reason
            and int(row["current_dac_code"]) == policy.fail_static_code
            and row["hz_per_code"] == format(policy.gain_nominal, ".15g")
            and _bool(row["preview_only"])
            and not _bool(row["actuation_authorized"])
            and not _bool(row["actionable"])
            and row["decision_reason_code"] == host["reason"]
            and error_difference <= SERIALIZED_12_DECIMAL_HALF_UNIT
            and delta_difference <= raw_delta_tolerance_codes
        )
        if host["preview_available"]:
            exact = exact and (
                int(row["limited_delta_codes"]) == int(host["limited_delta_codes"])
                and int(row["proposed_dac_code"]) == int(host["proposed_code"])
                and _bool(row["step_limited"]) == bool(host["step_limited"])
                and _bool(row["range_clamped"]) == bool(host["range_clamped"])
            )
        else:
            exact = exact and all(
                row[field] == ""
                for field in ("raw_delta_codes", "limited_delta_codes", "proposed_dac_code")
            )
        parity_ok = parity_ok and exact
        comparisons.append({
            "decision_id": row["decision_id"],
            "timestamp_s": timestamp_s,
            "temperature_c": temperature,
            "model_applicable": model_applicable,
            "host_state": host["state"],
            "live_state": row["control_state"],
            "host_reason": host["reason"],
            "live_reason": row["decision_reason_code"],
            "preview_available": _bool(row["preview_available"]),
            "absolute_error_difference_hz": error_difference,
            "absolute_raw_delta_difference_codes": delta_difference,
            "pass": exact,
        })
    preview_count = sum(_bool(row["preview_available"]) for row in rows)
    checks = [
        Check(
            "controller_sequence_and_identity",
            actual_sequences == expected_sequences and bool(rows),
            f"{len(rows)} contiguous controller rows bound to policy {policy.config_hash}",
        ),
        Check(
            "controller_host_firmware_parity",
            parity_ok and bool(rows),
            "max error/raw-delta differences "
            f"{max_error_difference:.17g} Hz/{max_delta_difference:.17g} codes; "
            "bounds 5e-13 Hz/"
            f"{raw_delta_tolerance_codes:.17g} codes",
        ),
        Check(
            "live_preview_available",
            preview_count > 0,
            f"{preview_count}/{len(rows)} controller rows contain an explainable non-actionable preview",
        ),
    ]
    return checks, {
        "row_count": len(rows),
        "preview_available_count": preview_count,
        "model_applicable_count": sum(
            row["model_applicability"] == "applicable" for row in rows
        ),
        "maximum_error_difference_hz": max_error_difference,
        "maximum_raw_delta_difference_codes": max_delta_difference,
        "frequency_error_numeric_tolerance_hz": SERIALIZED_12_DECIMAL_HALF_UNIT,
        "raw_delta_numeric_tolerance_codes": raw_delta_tolerance_codes,
        "decision_timestamp_wrap_count": decision_wrap_count,
        "environment_timestamp_wrap_count": environment_wrap_count,
        "comparisons": comparisons,
    }


def _provenance(
    policy: Policy,
    *,
    static_duration_s: float,
    service: dict[str, Any],
    estimator: dict[str, Any],
    controller: dict[str, Any],
    firmware_build: dict[str, Any],
    live_firmware_identity: dict[str, Any],
    preflight_identity: dict[str, Any],
    temperature_min: float | None,
    temperature_max: float | None,
) -> list[dict[str, str]]:
    rows = [dict(item) for item in policy.provenance]
    numerical_comparisons_present = (
        estimator["row_count"] > 0 and controller["row_count"] > 0
    )
    raw_delta_tolerance_codes = (
        abs(policy.integrator_gain) + 1.0
    ) * SERIALIZED_12_DECIMAL_HALF_UNIT
    numerical_parity_pass = (
        numerical_comparisons_present
        and estimator["maximum_frequency_difference_hz"]
        <= SERIALIZED_12_DECIMAL_HALF_UNIT
        and estimator["maximum_error_difference_hz"]
        <= SERIALIZED_12_DECIMAL_HALF_UNIT
        and controller["maximum_error_difference_hz"]
        <= SERIALIZED_12_DECIMAL_HALF_UNIT
        and controller["maximum_raw_delta_difference_codes"]
        <= raw_delta_tolerance_codes
    )
    measured_temperature = (
        "unavailable" if temperature_min is None else
        f"{temperature_min:.3f}..{temperature_max:.3f} C; "
        f"{controller['model_applicable_count']}/{controller['row_count']} controller rows applicable"
    )
    rows.extend([
        dict(zip(PROVENANCE_FIELDS, (
            "exact firmware build and UF2 identity",
            "run source/configuration/UF2 hashes and UF2 size must exactly match the supplied matrix build manifest and re-hashed UF2",
            "architecture screen",
            "run_manifest.json firmware binding; firmware_build_manifest.json provenance/artifacts; supplied matrix-built UF2",
            "exact Stage 6 operational profile and artifact; digital identity evidence, not a claim about successful physical flash by hash alone",
            "compare profile ID, source state/commit/hash, configuration hash, UF2 manifest hash/size and direct UF2 hash/size",
            "cryptographic SHA-256 identity; physical flash/readback uncertainty unavailable and live config/backend telemetry is checked separately",
            (
                f"status {firmware_build.get('status')}; source {firmware_build.get('declared_source_sha256')}; "
                f"config {firmware_build.get('declared_configuration_sha256')}; UF2 {firmware_build.get('actual_uf2_sha256')}"
            ),
            "pass" if firmware_build.get("status") == "pass" else (
                "unavailable" if firmware_build.get("status") == "unavailable" else "fail"
            ),
            "Stage 6 cannot pass or seal without exact build evidence; preserve the run as diagnostic/unsealed",
        ), strict=True)),
        dict(zip(PROVENANCE_FIELDS, (
            "live firmware/build/backend identity",
            "CONFIG? telemetry must exactly match the run's firmware version/config/source/commit/hash and the PPS-gated PIO snapshot backend; build invocation must also match when matrix evidence is supplied",
            "architecture screen",
            "firmware CONFIG? emit_build_provenance_status and PPS-gated configuration status; run manifest; matrix build manifest",
            "telemetry emitted by the actually connected firmware through the capture-owned service path; identifies configuration, not physical waveform quality",
            "compare the latest status value for every declared identity field with its exact manifest/build value",
            "exact digital string comparison; flash readback and physical execution uncertainty unavailable",
            f"{live_firmware_identity.get('matched_count')}/{live_firmware_identity.get('expected_count')} identity fields matched; mismatches {live_firmware_identity.get('mismatches')}",
            "pass" if live_firmware_identity.get("status") == "pass" else "fail",
            "Stage 6 cannot bind live telemetry to the exact artifact; no pass, seal, or readiness claim",
        ), strict=True)),
        dict(zip(PROVENANCE_FIELDS, (
            "preflight identity service query, request count",
            "exactly one non-actuating CONFIG? after capture open and before the sole manual A950 command",
            "architecture screen",
            "run manifest controller_preview.preflight_identity_query; firmware CONFIG? provenance emission contract",
            "ensures a run opened after the boot banner contains live build/backend identity before the static interval",
            "count host-command-sent CONFIG? markers before the planned service trigger and compare their marker order with A950",
            "exact digital count/order; host scheduling latency and physical flash readback uncertainty unavailable",
            f"{preflight_identity.get('observed_count')} CONFIG? at CNT {preflight_identity.get('count_sequence')}; before A950={preflight_identity.get('before_a950')}",
            "pass" if preflight_identity.get("status") == "pass" else "fail",
            "live artifact identity is not established before the declared interval; no Stage 6 pass or seal",
        ), strict=True)),
        dict(zip(PROVENANCE_FIELDS, (
            "declared static live-preview duration, s",
            "at least 21600 s after the sole manual A950 acknowledgement",
            "architecture screen",
            "Stage 6 prompt, Live preview campaign item 3; run manifest controller_preview.minimum_declared_duration_s",
            "actual uninterrupted Stage 6 topology/backend capture; evidence-volume requirement, not a control-performance specification",
            "UTC capture-stop marker minus UTC host-command-sent marker for the sole A950 command",
            "host UTC resolution and scheduling uncertainty unavailable; planned 22200 s capture provides a 600 s completion margin before the 18 s command offset",
            f"{static_duration_s:.0f} s",
            "pass" if static_duration_s >= 21600 else "fail",
            "Stage 6 live gate fails; no actuation review",
        ), strict=True)),
        dict(zip(PROVENANCE_FIELDS, (
            "host/firmware serialized numerical parity, Hz and codes",
            f"frequency/error absolute difference <= 5e-13 Hz; raw-delta difference <= {raw_delta_tolerance_codes:.17g} codes",
            "architecture screen",
            "otis_cx317_preview_live.cpp emit_estimate/emit_control %.12f format; otis_cx317_i_only_engine.cpp raw = integrator - Ki * frequency_error; policy integrator_gain_codes_per_hz_per_decision",
            "digital comparison of the same raw CNT spans and I-only calculations; firmware uses its unrounded internal frequency error while host replay necessarily consumes the serialized EST value; not measurement accuracy",
            f"half of one 1e-12 serialization unit = 5e-13; raw-delta bound = abs(Ki) * 5e-13 Hz + 5e-13 codes output rounding = (abs({policy.integrator_gain:.17g}) + 1) * 5e-13 = {raw_delta_tolerance_codes:.17g} codes",
            "serialization propagation bound only; physical reference/aperture/calibration uncertainty remains unavailable",
            (
                f"estimator frequency/error max {max(estimator['maximum_frequency_difference_hz'], estimator['maximum_error_difference_hz']):.17g} Hz; "
                f"controller error {controller['maximum_error_difference_hz']:.17g} Hz; "
                f"controller raw delta {controller['maximum_raw_delta_difference_codes']:.17g} codes"
                if numerical_comparisons_present else
                "no complete estimator/controller comparison set"
            ),
            "pass" if numerical_parity_pass else "fail",
            "parity gate fails closed; firmware output cannot support readiness",
        ), strict=True)),
        dict(zip(PROVENANCE_FIELDS, (
            "bounded service load, request/cadence",
            "exactly 60 CONFIG? requests, planned at 1.0 s cadence, at or after CNT sequence 13001; zero DAC commands",
            "characterization reference",
            "run manifest controller_preview.planned_service_load; sealed same-topology/backend Stage 3 service-plane segment",
            "same capture transport and qualified backend; CONFIG? is non-actuating",
            "manifest-bound service_plane_probe sends the declared request count through the capture-owned FIFO",
            "actual request scheduling/cadence uncertainty unavailable; count and command identity are exact digital evidence",
            f"{service.get('observed_total_probe_commands')} CONFIG?; first/last CNT {service.get('first_probe_marker', {}).get('count_sequence')}/{service.get('last_probe_marker', {}).get('count_sequence')}",
            "pass" if service.get("status") in {"complete", "already_complete"} else "fail",
            "service-load integrity gate fails; no Stage 6 pass",
        ), strict=True)),
        dict(zip(PROVENANCE_FIELDS, (
            "live selected preview execution, row count",
            "at least one 600 s selected estimate must reach one explainable controller preview while every actionability field remains false",
            "architecture screen",
            "Stage 6 prompt, Goal and Live preview campaign items 5-7",
            "minimum direct execution evidence for the selected estimator/controller path; explicitly a conservative engineering assumption, not a physical performance threshold",
            "count selected EST rows and CTL rows with preview_available=true",
            "digital execution evidence; physical combined uncertainty unavailable",
            f"{estimator['selected_row_count']} selected estimates; {controller['preview_available_count']} available previews",
            "pass" if estimator["selected_row_count"] > 0 and controller["preview_available_count"] > 0 else "fail",
            "Stage 6 cannot demonstrate the applicable live preview path; retain observe-only/not-ready disposition",
        ), strict=True)),
        dict(zip(PROVENANCE_FIELDS, (
            "Stage 6 nearby-air model context, degrees C",
            f"{policy.temperature_min_c}..{policy.temperature_max_c} C for model applicability; outside values inhibit preview",
            "model-applicability bound",
            "sealed Stage 5 plant characterization temperature_context; controller policy tolerance_provenance",
            "SHT41 approximately 1 cm from CX317 under the box; nearby-air context only and no causal temperature coefficient claimed",
            "compare the latest preceding SHT41 observation with the finite-run Stage 5 observed range",
            "sensor/spatial/internal-temperature and combined uncertainty unavailable; no margin added",
            measured_temperature,
            "pass" if controller["model_applicable_count"] > 0 else "fail",
            "model mismatch fails closed; no applicable preview or actuation review",
        ), strict=True)),
    ])
    return rows


def render_report(result: dict[str, Any]) -> str:
    lines = [
        "# CX317 Stage 6 Long Live Observe-Only Preview",
        "",
        f"- exit gate: `{result['exit_gate']}`",
        f"- run: `{result['run_id']}`",
        f"- static DAC duration: `{result['capture']['static_duration_s']:.0f} s`",
        f"- estimator rows: `{result['estimator_parity']['row_count']}`; selected `{result['estimator_parity']['selected_row_count']}`",
        f"- controller rows: `{result['controller_parity']['row_count']}`; previews available `{result['controller_parity']['preview_available_count']}`",
        "- authority: `control_ready=false`, `actuation_enabled=false`, `actuation_authorized=false`, `actionable=false`, active update `0` codes",
        "",
        "## Exit checks",
        "",
    ]
    lines.extend(_markdown_table(
        ("Check", "Result", "Evidence"),
        ((item["identifier"], "pass" if item["passed"] else "fail", item["evidence"]) for item in result["checks"]),
        alignments=("left", "left", "left"),
    ))
    lines.extend(["", "## Tolerance provenance", ""])
    lines.extend(_markdown_table(
        (
            "Parameter and units", "Acceptance/rejection threshold", "Disposition",
            "Source document and location", "Source conditions and applicability",
            "Calculation or conversion", "Measurement uncertainty and safety margin",
            "Measured result", "Status", "Consequences of failure",
        ),
        (tuple(item[key] for key in PROVENANCE_FIELDS) for item in result["tolerance_provenance"]),
        alignments=tuple("left" for _ in PROVENANCE_FIELDS),
    ))
    lines.extend([
        "", "## Limitations", "",
        "- The SHT41 is a nearby-air proxy, not the CX317 case or internal oven temperature; the observed range is context, not a demonstrated causal coefficient.",
        "- The oscillator source domain is `h1_cx317_ocxo_10mhz`; its phase origin is arbitrary and no UTC traceability is claimed.",
        "- D10 is a general auxiliary edge input. Its D14 agreement is required only because this run declares the same PPS connected to both.",
        "- Physical phase/duty margin, calibrated absolute accuracy, isolated firmware jitter, connected Vc calibration, t95 and combined uncertainty remain unavailable or untested.",
        "- A passing result is observe-only evidence. It grants no DAC actuation authority.",
        "",
    ])
    return "\n".join(lines)


def analyze(
    run_dir: Path,
    service_probe_path: Path,
    *,
    policy_path: Path = DEFAULT_POLICY,
    firmware_build_manifest_path: Path | None = None,
    firmware_uf2_path: Path | None = None,
    output_dir: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    run_dir = run_dir.resolve()
    if (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise RuntimeError("capture is still in progress; refusing offline Stage 6 analysis")
    manifest = load_manifest(run_dir)
    if manifest.stage != EXPECTED_STAGE or manifest.is_template:
        raise ValueError("run is not an instantiated CX317 Stage 6 live preview")
    policy = load_policy(policy_path)
    raw_log = run_dir / "raw" / "serial.log"
    paths = {
        "manifest": manifest.path,
        "raw_log": raw_log,
        "references": _contract_path(manifest, "raw_events_v1"),
        "counts": _contract_path(manifest, "count_observations_v1"),
        "snapshots": _contract_path(manifest, "pps_snapshots_v1"),
        "health": _contract_path(manifest, "health_v1"),
        "dac": _contract_path(manifest, "dac_steps_v1"),
        "environment": _contract_path(manifest, "environment_v1"),
        "estimates": _contract_path(manifest, "estimates_v2"),
        "controls": _contract_path(manifest, "control_previews_v1"),
        "service_probe": service_probe_path.resolve(),
    }
    if firmware_build_manifest_path is not None:
        paths["firmware_build_manifest"] = firmware_build_manifest_path.resolve()
    if firmware_uf2_path is not None:
        paths["firmware_uf2"] = firmware_uf2_path.resolve()
    _validate_sources(manifest, paths)
    hashes_before = _source_evidence(paths)
    data = manifest.data
    build_check, firmware_build = _firmware_build_binding(
        data,
        paths.get("firmware_build_manifest"),
        paths.get("firmware_uf2"),
    )
    if data["selected_estimator"]["method_id"] != EXPECTED_ESTIMATOR_METHOD:
        raise ValueError("selected estimator method differs")
    if data["controller_preview"]["policy_sha256"] != policy.config_hash:
        raise ValueError("manifest policy hash differs from loaded policy")
    if data["controller_preview"]["plant_model_sha256"] != policy.plant_model_hash:
        raise ValueError("manifest plant model hash differs from policy")

    markers = _host_markers(raw_log)
    capture_started = _one_marker(markers, "capture_started")
    capture_stopped = _one_marker(markers, "capture_stopped")
    planned_complete_matches = [
        item for item in markers
        if item.get("event") == "planned_duration_complete"
    ]
    if len(planned_complete_matches) > 1:
        raise ValueError(
            "expected at most one planned_duration_complete marker, got "
            f"{len(planned_complete_matches)}"
        )
    planned_complete = (
        planned_complete_matches[0] if planned_complete_matches else None
    )
    dac_sent = [
        item for item in markers
        if item.get("event") == "host_command_sent"
        and str(item.get("command", "")).startswith("DAC ")
    ]
    dac_accepted = [
        item for item in markers
        if item.get("event") == "host_command_accepted"
        and str(item.get("command", "")).startswith("DAC ")
    ]
    if len(dac_sent) != 1 or len(dac_accepted) != 1:
        raise ValueError("expected exactly one manual DAC host command")
    static_duration = _utc_seconds(str(capture_stopped["utc"])) - _utc_seconds(str(dac_sent[0]["utc"]))
    minimum_duration = int(data["controller_preview"]["minimum_declared_duration_s"])
    planned_duration = float(data["controller_preview"]["planned_capture_duration_s"])

    counts = _read_rows(paths["counts"])
    snapshots = _read_rows(paths["snapshots"])
    references = _read_rows(paths["references"])
    health = _read_rows(paths["health"])
    dac = _read_rows(paths["dac"])
    environment = _read_rows(paths["environment"])
    estimates = _read_rows(paths["estimates"])
    controls = _read_rows(paths["controls"])
    if not counts or not snapshots or not references or not health:
        raise ValueError("required Stage 6 raw evidence is empty")

    checks = [build_check]
    continuity_checks, count_by_seq = _check_continuity(
        counts, snapshots, references
    )
    checks.extend(continuity_checks)
    estimate_checks, estimator_result, estimates_by_id = _estimate_parity(
        estimates, count_by_seq, data
    )
    checks.extend(estimate_checks)
    controller_checks, controller_result = _controller_parity(
        controls, estimates_by_id, environment, policy
    )
    checks.extend(controller_checks)

    expected_code = policy.fail_static_code
    dac_ok = (
        len(dac) == 1
        and dac[0]["event"] == "manual_apply"
        and int(dac[0]["dac_code_requested"]) == expected_code
        and int(dac[0]["dac_code_applied"]) == expected_code
        and int(dac[0]["dac_code_clamped"]) == 0
        and int(dac[0]["flags"]) == 0
        and dac_sent[0]["command"] == f"DAC SET 0x{expected_code:04X}"
        and dac_accepted[0]["command"] == f"DAC SET 0x{expected_code:04X}"
        and all(int(row["current_dac_code"]) == expected_code for row in controls)
    )
    checks.append(Check(
        "static_exact_fail_code",
        dac_ok,
        f"{len(dac)} DAC row; requested/applied 0x{expected_code:04X}; no feedback-derived command",
    ))
    checks.append(Check(
        "minimum_static_duration",
        static_duration >= minimum_duration
        and planned_complete is not None
        and float(planned_complete["duration_s"]) == planned_duration,
        f"{static_duration:.0f} s after A950 against {minimum_duration} s minimum; "
        f"planned {planned_duration:.0f} s stop marker "
        f"{'present' if planned_complete is not None else 'absent'}",
    ))

    transport_reasons = set(_transport_global_reasons(raw_log))
    stop_zero = all(
        int(capture_stopped.get(key, -1)) == 0
        for key in (
            "malformed_utf8", "parser_errors", "reconnect_count",
            "commands_rejected",
        )
    )
    checks.append(Check(
        "host_transport_integrity",
        not transport_reasons and stop_zero,
        "capture stopped normally with zero malformed/parser/reconnect/rejected-command counters; "
        + ("no reasons" if not transport_reasons else ", ".join(sorted(transport_reasons))),
    ))

    health_reasons = set(_health_global_reasons(paths["health"]))
    latest = _latest_health(health)
    expected_live_identity = {
        ("firmware", "version"): str(data["firmware"]["version"]),
        ("firmware", "config_id"): str(data["firmware"]["config_id"]),
        ("firmware", "git_commit"): str(data["firmware"]["git_commit"]),
        ("firmware", "source_state"): str(data["firmware"]["source_state"]),
        ("firmware", "source_hash"): str(data["firmware"]["source_sha256"]),
        ("firmware", "config_hash"): str(
            data["firmware"]["configuration_sha256"]
        ),
        ("build", "profile_id"): str(data["firmware"]["config_id"]),
        ("build", "tcxo_counter_backend"): "pps_gated_ratio",
        ("pps_gate", "boundary_owner"): "pio_state_machine",
        ("pps_gate", "aperture_backend"): EXPECTED_BACKEND,
        ("pps_gate", "backend_qualified"): "true",
    }
    if firmware_build.get("status") == "pass":
        expected_live_identity[("build", "invocation_id")] = str(
            firmware_build["build_invocation_id"]
        )
    live_identity_mismatches = {
        f"{component}.{key}": {
            "expected": expected,
            "observed": latest.get((component, key)),
        }
        for (component, key), expected in expected_live_identity.items()
        if latest.get((component, key)) != expected
    }
    live_identity_ok = not live_identity_mismatches
    live_firmware_identity = {
        "status": "pass" if live_identity_ok else "fail",
        "expected_count": len(expected_live_identity),
        "matched_count": len(expected_live_identity) - len(live_identity_mismatches),
        "mismatches": live_identity_mismatches,
    }
    checks.append(Check(
        "live_firmware_identity",
        live_identity_ok,
        (
            f"{len(expected_live_identity)}/{len(expected_live_identity)} exact CONFIG? identity fields"
            if live_identity_ok else
            f"mismatched fields: {', '.join(sorted(live_identity_mismatches))}"
        ),
    ))
    required_false = all(
        latest.get(("cx317_preview", key)) == "false" for key in AUTHORITY_KEYS
    )
    authority_rows_false = all(
        row["status_value"] == "false"
        for row in health
        if row["component"] == "cx317_preview"
        and row["status_key"] in AUTHORITY_KEYS
    )
    health_ok = (
        not health_reasons
        and required_false
        and authority_rows_false
        and all(latest.get(key) == expected for key, expected in REQUIRED_LATEST_HEALTH.items())
        and all(latest.get(key) == "0" for key in REQUIRED_ZERO_HEALTH)
        and latest.get(("cx317_preview", "active_live_update_codes")) == "0"
        and latest.get(("cx317_preview", "telemetry_dropped_frames")) == "0"
        and latest.get(("pps_dual_observer", "agreement_state")) == "MATCHING"
        and latest.get(("pps_dual_observer", "d14_raw_minus_d10_raw")) == "0"
    )
    checks.append(Check(
        "firmware_health_and_authority",
        health_ok,
        "zero capture/PPS/DMA/ring/preview drops; D14/general-D10 matching; all authority false and active update zero"
        + ("" if not health_reasons else "; " + ", ".join(sorted(health_reasons))),
    ))

    service = _read_json(paths["service_probe"])
    raw_probe = inspect_raw_log(raw_log)
    preflight_contract = data["controller_preview"].get(
        "preflight_identity_query"
    )
    service_trigger = int(service["trigger_count_sequence"])
    preflight_declared = isinstance(preflight_contract, dict)
    preflight_command = (
        str(preflight_contract.get("command", ""))
        if preflight_declared else "CONFIG?"
    )
    preflight_markers = [
        item for item in markers
        if item.get("event") == "host_command_sent"
        and item.get("command") == preflight_command
        and item.get("count_sequence") is not None
        and int(item["count_sequence"]) < service_trigger
    ]
    expected_preflight_count = (
        int(preflight_contract["request_count"])
        if preflight_declared else None
    )
    preflight_before_a950 = (
        preflight_declared
        and
        len(preflight_markers) == 1
        and markers.index(preflight_markers[0]) < markers.index(dac_sent[0])
    )
    preflight_ok = (
        preflight_declared
        and preflight_command == "CONFIG?"
        and expected_preflight_count == 1
        and len(preflight_markers) == expected_preflight_count
        and preflight_before_a950
    )
    preflight_identity = {
        "status": "pass" if preflight_ok else "fail",
        "command": preflight_command,
        "expected_count": expected_preflight_count,
        "observed_count": len(preflight_markers),
        "count_sequence": (
            preflight_markers[0]["count_sequence"]
            if len(preflight_markers) == 1 else None
        ),
        "before_a950": preflight_before_a950,
        "basis": (
            str(preflight_contract.get("basis", ""))
            if preflight_declared else
            "preflight identity query was not declared in the instantiated run manifest"
        ),
    }
    checks.append(Check(
        "preflight_live_identity_query",
        preflight_ok,
        f"{len(preflight_markers)}/"
        f"{expected_preflight_count if expected_preflight_count is not None else 'unavailable'} "
        "CONFIG? before A950 and service trigger",
    ))
    probe_markers = [
        item for item in raw_probe.sent_markers
        if item.command == "CONFIG?"
        and item.count_sequence is not None
        and item.count_sequence >= int(service["trigger_count_sequence"])
    ]
    service_ok = (
        service.get("status") in {"complete", "already_complete"}
        and int(service["planned_request_count"]) == 60
        and float(service["cadence_period_s"]) == 1.0
        and int(service["trigger_count_sequence"]) == 13001
        and int(service["observed_total_probe_commands"]) == 60
        and not bool(service["dac_command"])
        and len(probe_markers) == 60
        and probe_markers[0].count_sequence == service["first_probe_marker"]["count_sequence"]
        and probe_markers[-1].count_sequence == service["last_probe_marker"]["count_sequence"]
    )
    checks.append(Check(
        "bounded_service_load_integrity",
        service_ok,
        f"{len(probe_markers)} CONFIG? markers; first/last CNT "
        f"{probe_markers[0].count_sequence if probe_markers else None}/"
        f"{probe_markers[-1].count_sequence if probe_markers else None}; no DAC command",
    ))

    temperatures = [
        float(row["temperature_c"]) for row in environment
        if row["source"] == "sht4x" and row["role"] == "vcocxo_near"
    ]
    temperature_min = min(temperatures) if temperatures else None
    temperature_max = max(temperatures) if temperatures else None
    provenance = _provenance(
        policy,
        static_duration_s=static_duration,
        service=service,
        estimator=estimator_result,
        controller=controller_result,
        firmware_build=firmware_build,
        live_firmware_identity=live_firmware_identity,
        preflight_identity=preflight_identity,
        temperature_min=temperature_min,
        temperature_max=temperature_max,
    )
    all_pass = all(item.passed for item in checks)
    result = {
        "schema_version": 1,
        "tool_version": TOOL_VERSION,
        "exit_gate": "pass_observe_only" if all_pass else "fail_closed",
        "run_id": manifest.run_id,
        "identities": {
            "firmware_config_id": data["firmware"]["config_id"],
            "firmware_source_sha256": data["firmware"]["source_sha256"],
            "firmware_configuration_sha256": data["firmware"]["configuration_sha256"],
            "firmware_uf2_sha256": data["firmware"]["uf2_sha256"],
            "estimator_method_id": data["selected_estimator"]["method_id"],
            "selected_estimator_sha256": data["selected_estimator"]["profile_sha256"],
            "policy_id": policy.policy_id,
            "policy_sha256": policy.config_hash,
            "plant_model_sha256": policy.plant_model_hash,
        },
        "firmware_build_binding": firmware_build,
        "live_firmware_identity": live_firmware_identity,
        "preflight_identity_query": preflight_identity,
        "capture": {
            "started_at_utc": capture_started["utc"],
            "static_started_at_utc": dac_sent[0]["utc"],
            "stopped_at_utc": capture_stopped["utc"],
            "static_duration_s": static_duration,
            "minimum_static_duration_s": minimum_duration,
            "planned_capture_duration_s": planned_duration,
            "planned_duration_complete_observed": planned_complete is not None,
            "capture_stopped_counters": {
                key: capture_stopped.get(key)
                for key in (
                    "bytes_written", "lines_seen", "lines_parsed",
                    "malformed_utf8", "parser_errors", "reconnect_count",
                    "commands_sent", "commands_rejected",
                )
            },
        },
        "static_dac": {
            "code": expected_code,
            "hex_code": f"0x{expected_code:04X}",
            "row": dac[0] if dac else None,
            "feedback_derived_commands": False,
        },
        "service_load": service,
        "health": {
            "global_reason_codes": sorted(health_reasons),
            "transport_reason_codes": sorted(transport_reasons),
            "latest_authority": {
                key: latest.get(("cx317_preview", key)) for key in AUTHORITY_KEYS
            },
            "active_live_update_codes": latest.get(("cx317_preview", "active_live_update_codes")),
            "telemetry_dropped_frames": latest.get(("cx317_preview", "telemetry_dropped_frames")),
            "d14_general_d10_difference": latest.get(("pps_dual_observer", "d14_raw_minus_d10_raw")),
            "d14_general_d10_agreement": latest.get(("pps_dual_observer", "agreement_state")),
        },
        "environment": {
            "source": "SHT41 nearby-air proxy approximately 1 cm from CX317",
            "sample_count": len(temperatures),
            "minimum_temperature_c": temperature_min,
            "maximum_temperature_c": temperature_max,
            "model_minimum_temperature_c": policy.temperature_min_c,
            "model_maximum_temperature_c": policy.temperature_max_c,
            "causal_temperature_coefficient_claimed": False,
        },
        "estimator_parity": estimator_result,
        "controller_parity": controller_result,
        "checks": [asdict(item) for item in checks],
        "tolerance_provenance": provenance,
        "authority": {
            "control_ready": False,
            "actuation_enabled": False,
            "actuation_authorized": False,
            "actionable": False,
            "active_live_update_codes": 0,
        },
        "source_evidence": hashes_before,
        "claims_not_made": [
            "calibrated_absolute_accuracy",
            "isolated_firmware_jitter",
            "physical_phase_or_duty_margin",
            "connected_vc_calibration",
            "combined_uncertainty",
            "actuation_authority",
        ],
    }
    destination_dir = output_dir or run_dir / OUTPUT_DIR
    output_path = destination_dir / OUTPUT_NAME
    report_path = run_dir / "reports" / REPORT_NAME
    _write_json(output_path, result)
    _write_atomic(report_path, render_report(result))
    hashes_after = _source_evidence(paths)
    if hashes_after != hashes_before:
        output_path.unlink(missing_ok=True)
        report_path.unlink(missing_ok=True)
        raise RuntimeError("source evidence changed during Stage 6 analysis")
    return output_path, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate offline CX317 Stage 6 live estimator/controller parity."
    )
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--service-probe", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--firmware-build-manifest", type=Path)
    parser.add_argument("--firmware-uf2", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        destination, result = analyze(
            args.run_dir,
            args.service_probe,
            policy_path=args.policy,
            firmware_build_manifest_path=args.firmware_build_manifest,
            firmware_uf2_path=args.firmware_uf2,
            output_dir=args.output_dir,
        )
    except (
        FileNotFoundError, KeyError, IndexError, TypeError, ValueError,
        RuntimeError, csv.Error, json.JSONDecodeError,
    ) as exc:
        parser.error(str(exc))
    print(destination)
    return 0 if result["exit_gate"] == "pass_observe_only" else 2


if __name__ == "__main__":
    raise SystemExit(main())
