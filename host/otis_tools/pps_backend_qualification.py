from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import argparse
import csv
import json
import math
import statistics
from typing import Any

from .contracts import CsvValidationContext, validate_csv
from .evidence import EVIDENCE_MANIFEST, validate_evidence_snapshot
from .run_loader import COMPLETE_MARKER, RunManifest, load_manifest
from .pps_snapshot_reconstruction import (
    ReconstructionPolicy,
    SnapshotObservation,
    reconstruct_snapshots,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = (
    REPO_ROOT / "profiles" / "qualification" / "pps_gated_ratio_v2.json"
)
OUTPUT_DIR = Path("derived/phase5_pps_backend_qualification_v2")
OUTPUT_NAME = "qualification_report_v2.json"
TOOL_VERSION = "pps_backend_qualification_v2"
RP2040_TIMER0_TICKS_PER_US = 16
RP2040_TIMER0_MICROS_MODULUS = 1 << 32
PPS_SNAPSHOT_MAX_CAPTURED_EDGE_RATE_HZ = 133_000_000.0

REFERENCE_INVALID_FLAGS = (
    (1 << 0)
    | (1 << 1)
    | (1 << 2)
    | (1 << 3)
    | (1 << 5)
    | (1 << 6)
    | (1 << 7)
    | (1 << 8)
    | (1 << 9)
    | (1 << 10)
    | (1 << 11)
)
CANDIDATE_COUNT_INVALID_FLAGS = (
    (1 << 0)
    | (1 << 1)
    | (1 << 2)
    | (1 << 5)
    | (1 << 8)
    | (1 << 9)
    | (1 << 10)
    | (1 << 12)
    | (1 << 13)
)
INDEPENDENT_COUNT_INVALID_FLAGS = (
    (1 << 0)
    | (1 << 1)
    | (1 << 2)
    | (1 << 5)
    | (1 << 8)
    | (1 << 9)
    | (1 << 10)
    | (1 << 12)
    | (1 << 13)
)


@dataclass(frozen=True)
class QualificationConfig:
    schema_version: int
    acceptance_scope: str
    criteria_rationale_document: str
    candidate_estimator_type: str
    expected_candidate_backend: str
    allowed_independent_paths: tuple[tuple[str, str], ...]
    nominal_reference_interval_s: float
    reference_interval_tolerance_s: float
    duplicate_max_interval_s: float
    missing_timeout_s: float
    count_resolution_edges: int
    minimum_stable_duration_s: float
    minimum_eligible_windows: int
    minimum_service_plane_windows_per_segment: int
    maximum_absolute_bias_hz: float
    maximum_candidate_jitter_hz: float
    maximum_service_plane_mean_shift_hz: float
    absolute_bias_disposition: str
    candidate_population_jitter_disposition: str
    service_plane_mean_shift_disposition: str
    required_fault_reason_codes: tuple[str, ...]
    synthetic_only_fault_reason_codes: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "QualificationConfig":
        common = {
            "schema_version",
            "candidate_estimator_type",
            "expected_candidate_backend",
            "allowed_independent_paths",
            "nominal_reference_interval_s",
            "reference_interval_tolerance_s",
            "duplicate_max_interval_s",
            "missing_timeout_s",
            "count_resolution_edges",
            "minimum_stable_duration_s",
            "minimum_eligible_windows",
            "minimum_service_plane_windows_per_segment",
            "required_fault_reason_codes",
            "synthetic_only_fault_reason_codes",
        }
        schema_version = value.get("schema_version")
        if schema_version == 1:
            expected = common | {
                "maximum_absolute_bias_hz",
                "maximum_candidate_jitter_hz",
                "maximum_service_plane_mean_shift_hz",
            }
            acceptance_scope = "legacy_full_metrology"
            criteria_rationale_document = ""
            absolute_bias_key = "maximum_absolute_bias_hz"
            candidate_jitter_key = "maximum_candidate_jitter_hz"
            service_shift_key = "maximum_service_plane_mean_shift_hz"
            absolute_bias_disposition = "acceptance_gate"
            candidate_jitter_disposition = "acceptance_gate"
            service_shift_disposition = "acceptance_gate"
        elif schema_version == 2:
            expected = common | {
                "acceptance_scope",
                "criteria_rationale_document",
                "absolute_bias_reference_hz",
                "candidate_population_jitter_reference_hz",
                "service_plane_mean_shift_reference_hz",
                "absolute_bias_disposition",
                "candidate_population_jitter_disposition",
                "service_plane_mean_shift_disposition",
            }
            acceptance_scope = str(value["acceptance_scope"])
            criteria_rationale_document = str(
                value["criteria_rationale_document"]
            )
            absolute_bias_key = "absolute_bias_reference_hz"
            candidate_jitter_key = "candidate_population_jitter_reference_hz"
            service_shift_key = "service_plane_mean_shift_reference_hz"
            absolute_bias_disposition = str(value["absolute_bias_disposition"])
            candidate_jitter_disposition = str(
                value["candidate_population_jitter_disposition"]
            )
            service_shift_disposition = str(
                value["service_plane_mean_shift_disposition"]
            )
        else:
            raise ValueError(
                "qualification config schema_version must be 1 or 2"
            )
        if set(value) != expected:
            missing = sorted(expected - set(value))
            extra = sorted(set(value) - expected)
            raise ValueError(
                f"qualification config fields differ; missing={missing}, extra={extra}"
            )
        if acceptance_scope not in {
            "legacy_full_metrology",
            "digital_architecture",
        }:
            raise ValueError("unsupported acceptance_scope")
        if schema_version == 2:
            if not criteria_rationale_document:
                raise ValueError("criteria_rationale_document must be non-empty")
            if absolute_bias_disposition != "characterization_only":
                raise ValueError(
                    "v2 absolute_bias_disposition must be characterization_only"
                )
            if candidate_jitter_disposition != "blocking_architecture_screen":
                raise ValueError(
                    "v2 candidate_population_jitter_disposition must be "
                    "blocking_architecture_screen"
                )
            if service_shift_disposition != "characterization_only":
                raise ValueError(
                    "v2 service_plane_mean_shift_disposition must be "
                    "characterization_only"
                )
        candidate_type = str(value["candidate_estimator_type"])
        if candidate_type != "pps_gated_ratio_count_v1":
            raise ValueError(
                "candidate_estimator_type must be pps_gated_ratio_count_v1"
            )
        numeric_positive = (
            "nominal_reference_interval_s",
            "duplicate_max_interval_s",
            "missing_timeout_s",
            "minimum_stable_duration_s",
        )
        for key in numeric_positive:
            if (
                not isinstance(value[key], (int, float))
                or isinstance(value[key], bool)
                or not math.isfinite(float(value[key]))
                or float(value[key]) <= 0
            ):
                raise ValueError(f"{key} must be finite and positive")
        numeric_nonnegative = (
            "reference_interval_tolerance_s",
            absolute_bias_key,
            candidate_jitter_key,
            service_shift_key,
        )
        for key in numeric_nonnegative:
            if (
                not isinstance(value[key], (int, float))
                or isinstance(value[key], bool)
                or not math.isfinite(float(value[key]))
                or float(value[key]) < 0
            ):
                raise ValueError(f"{key} must be finite and nonnegative")
        for key in (
            "count_resolution_edges",
            "minimum_eligible_windows",
            "minimum_service_plane_windows_per_segment",
        ):
            if (
                not isinstance(value[key], int)
                or isinstance(value[key], bool)
                or value[key] < 1
            ):
                raise ValueError(f"{key} must be a positive integer")
        minimum_interval_s = (
            float(value["nominal_reference_interval_s"])
            - float(value["reference_interval_tolerance_s"])
        )
        maximum_interval_s = (
            float(value["nominal_reference_interval_s"])
            + float(value["reference_interval_tolerance_s"])
        )
        if minimum_interval_s <= 0:
            raise ValueError(
                "reference interval tolerance must leave a positive minimum"
            )
        if float(value["duplicate_max_interval_s"]) >= minimum_interval_s:
            raise ValueError(
                "duplicate_max_interval_s must be below the minimum interval"
            )
        if float(value["missing_timeout_s"]) <= maximum_interval_s:
            raise ValueError(
                "missing_timeout_s must exceed the maximum interval"
            )
        allowed = value["allowed_independent_paths"]
        required_reasons = value["required_fault_reason_codes"]
        synthetic_reasons = value["synthetic_only_fault_reason_codes"]
        if (
            not isinstance(allowed, list)
            or not allowed
            or any(
                not isinstance(item, dict)
                or set(item) != {"estimator_type", "measurement_backend"}
                or not isinstance(item["estimator_type"], str)
                or not item["estimator_type"]
                or not isinstance(item["measurement_backend"], str)
                or not item["measurement_backend"]
                for item in allowed
            )
        ):
            raise ValueError(
                "allowed_independent_paths must explicitly pair non-empty "
                "estimator_type and measurement_backend strings"
            )
        allowed_pairs = tuple(
            (item["estimator_type"], item["measurement_backend"])
            for item in allowed
        )
        if len(set(allowed_pairs)) != len(allowed_pairs):
            raise ValueError("allowed_independent_paths must be unique")
        if (
            not isinstance(required_reasons, list)
            or not required_reasons
            or any(
                not isinstance(item, str) or not item
                for item in required_reasons
            )
        ):
            raise ValueError(
                "required_fault_reason_codes must be non-empty strings"
            )
        if not isinstance(synthetic_reasons, list) or any(
            not isinstance(item, str) or not item for item in synthetic_reasons
        ):
            raise ValueError(
                "synthetic_only_fault_reason_codes must contain strings"
            )
        return cls(
            schema_version=int(schema_version),
            acceptance_scope=acceptance_scope,
            criteria_rationale_document=criteria_rationale_document,
            candidate_estimator_type=candidate_type,
            expected_candidate_backend=str(value["expected_candidate_backend"]),
            allowed_independent_paths=allowed_pairs,
            nominal_reference_interval_s=float(
                value["nominal_reference_interval_s"]
            ),
            reference_interval_tolerance_s=float(
                value["reference_interval_tolerance_s"]
            ),
            duplicate_max_interval_s=float(
                value["duplicate_max_interval_s"]
            ),
            missing_timeout_s=float(value["missing_timeout_s"]),
            count_resolution_edges=int(value["count_resolution_edges"]),
            minimum_stable_duration_s=float(value["minimum_stable_duration_s"]),
            minimum_eligible_windows=int(value["minimum_eligible_windows"]),
            minimum_service_plane_windows_per_segment=int(
                value["minimum_service_plane_windows_per_segment"]
            ),
            maximum_absolute_bias_hz=float(value[absolute_bias_key]),
            maximum_candidate_jitter_hz=float(
                value[candidate_jitter_key]
            ),
            maximum_service_plane_mean_shift_hz=float(
                value[service_shift_key]
            ),
            absolute_bias_disposition=absolute_bias_disposition,
            candidate_population_jitter_disposition=(
                candidate_jitter_disposition
            ),
            service_plane_mean_shift_disposition=service_shift_disposition,
            required_fault_reason_codes=tuple(required_reasons),
            synthetic_only_fault_reason_codes=tuple(synthetic_reasons),
        )


@dataclass(frozen=True)
class SourceTyping:
    evidence_kind: str
    comparison_interval_id: str
    comparison_started_utc: str
    comparison_ended_utc: str
    comparison_first_count_seq: int
    comparison_last_count_seq: int
    estimator_type: str
    measurement_backend: str
    source_domain: str
    uncertainty: dict[str, float | None]
    service_plane_segments: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class CountWindow:
    seq: int
    channel_id: int
    open_ticks: int
    close_ticks: int
    gate_domain: str
    counted_edges: int
    source_edge: str
    source_domain: str
    flags: int


@dataclass(frozen=True)
class Reference:
    seq: int
    ticks: int
    domain: str
    flags: int


@dataclass(frozen=True)
class RawSnapshot:
    session: int
    sequence: int
    cumulative_down_counter: int
    reference_sequence: int
    reference_timestamp_ticks: int
    status: int
    backend: str


@dataclass(frozen=True)
class CandidateWindow:
    seq: int
    frequency_hz: float | None
    duration_s: float | None
    reference_valid: bool
    count_valid: bool
    eligible: bool
    traceable: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class QualificationResult:
    report_path: Path
    qualification_state: str
    acceptance_passed: bool


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _source_hashes(run_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(run_dir).as_posix(): _sha256_file(path)
        for path in sorted(run_dir.rglob("*"))
        if path.is_file()
        and (
            not path.relative_to(run_dir).parts
            or path.relative_to(run_dir).parts[0] != "derived"
        )
    }


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _contract_path(manifest: RunManifest, contract: str) -> Path:
    matches = [
        manifest.root / str(entry["path"])
        for entry in manifest.files
        if entry.get("contract") == contract
    ]
    if len(matches) != 1:
        raise ValueError(
            f"{manifest.run_id}: expected exactly one {contract} source, "
            f"found {len(matches)}"
        )
    path = matches[0].resolve()
    try:
        relative = path.relative_to(manifest.root.resolve())
    except ValueError as exc:
        raise ValueError(f"{manifest.run_id}: {contract} source escapes run") from exc
    if relative.parts and relative.parts[0] == "derived":
        raise ValueError(
            f"{manifest.run_id}: canonical {contract} source cannot be derived"
        )
    return path


def _validate_source(path: Path, contract: str, manifest: RunManifest) -> None:
    validation = validate_csv(
        path,
        CsvValidationContext(
            contract=contract,
            known_channels=manifest.known_channels,
            known_domains=manifest.known_domains,
            allow_rp2040_timer0_wrap="rp2040_timer0" in manifest.known_domains,
        ),
    )
    if validation.errors:
        raise ValueError(
            f"{path}: contract validation failed: "
            + "; ".join(validation.errors[:8])
        )


def _load_typing(manifest: RunManifest) -> SourceTyping:
    metadata = manifest.data.get("phase5_pps_backend_qualification")
    if not isinstance(metadata, dict):
        raise ValueError(
            f"{manifest.run_id}: missing phase5_pps_backend_qualification metadata"
        )
    required = {
        "evidence_kind",
        "comparison_interval_id",
        "comparison_started_utc",
        "comparison_ended_utc",
        "comparison_first_count_seq",
        "comparison_last_count_seq",
        "estimator_type",
        "measurement_backend",
        "source_domain",
        "uncertainty",
    }
    missing = required - set(metadata)
    if missing:
        raise ValueError(
            f"{manifest.run_id}: qualification metadata missing {sorted(missing)}"
        )
    allowed_metadata = required | {"service_plane_segments"}
    extra = set(metadata) - allowed_metadata
    if extra:
        raise ValueError(
            f"{manifest.run_id}: unsupported qualification metadata "
            f"{sorted(extra)}"
        )
    uncertainty = metadata["uncertainty"]
    if not isinstance(uncertainty, dict):
        raise ValueError(f"{manifest.run_id}: uncertainty must be an object")
    allowed_uncertainty = {
        "count_quantization_standard_uncertainty_hz",
        "counter_aperture_s_1sigma",
        "reference_fractional_1sigma",
        "independent_frequency_hz_1sigma",
    }
    if set(uncertainty) - allowed_uncertainty:
        raise ValueError(
            f"{manifest.run_id}: unsupported uncertainty fields "
            f"{sorted(set(uncertainty) - allowed_uncertainty)}"
        )
    parsed_uncertainty: dict[str, float | None] = {}
    for key in sorted(allowed_uncertainty):
        raw = uncertainty.get(key)
        if raw is None:
            parsed_uncertainty[key] = None
        elif (
            isinstance(raw, (int, float))
            and not isinstance(raw, bool)
            and math.isfinite(float(raw))
            and float(raw) > 0
        ):
            parsed_uncertainty[key] = float(raw)
        else:
            raise ValueError(
                f"{manifest.run_id}: uncertainty {key} must be positive or null"
            )
    segments = metadata.get("service_plane_segments", [])
    if not isinstance(segments, list) or any(
        not isinstance(item, dict) for item in segments
    ):
        raise ValueError(
            f"{manifest.run_id}: service_plane_segments must be an array of objects"
        )
    parsed_segments: list[dict[str, Any]] = []
    segment_labels: set[str] = set()
    segment_ranges: list[tuple[int, int]] = []
    for segment in segments:
        required_segment = {
            "label",
            "mode",
            "first_count_seq",
            "last_count_seq",
        }
        if set(segment) != required_segment:
            raise ValueError(
                f"{manifest.run_id}: service-plane segment fields must be "
                f"{sorted(required_segment)}"
            )
        label = segment["label"]
        mode = segment["mode"]
        first = segment["first_count_seq"]
        last = segment["last_count_seq"]
        if not isinstance(label, str) or not label or label in segment_labels:
            raise ValueError(
                f"{manifest.run_id}: service-plane labels must be unique "
                "non-empty strings"
            )
        if mode not in {"baseline", "load"}:
            raise ValueError(
                f"{manifest.run_id}: service-plane mode must be baseline or load"
            )
        if (
            not isinstance(first, int)
            or isinstance(first, bool)
            or not isinstance(last, int)
            or isinstance(last, bool)
            or first < 1
            or last < first
        ):
            raise ValueError(
                f"{manifest.run_id}: service-plane count ranges must be "
                "positive and ordered"
            )
        if any(not (last < lower or first > upper) for lower, upper in segment_ranges):
            raise ValueError(
                f"{manifest.run_id}: service-plane count ranges must not overlap"
            )
        segment_labels.add(label)
        segment_ranges.append((first, last))
        parsed_segments.append(dict(segment))
    scalar_fields = (
        "evidence_kind",
        "comparison_interval_id",
        "comparison_started_utc",
        "comparison_ended_utc",
        "estimator_type",
        "measurement_backend",
        "source_domain",
    )
    for field in scalar_fields:
        if not isinstance(metadata[field], str) or not metadata[field]:
            raise ValueError(
                f"{manifest.run_id}: qualification {field} must be non-empty"
            )
    parsed_times: dict[str, datetime] = {}
    for field in ("comparison_started_utc", "comparison_ended_utc"):
        try:
            parsed = datetime.fromisoformat(
                metadata[field].replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError(
                f"{manifest.run_id}: qualification {field} must be ISO-8601"
            ) from exc
        if parsed.tzinfo is None:
            raise ValueError(
                f"{manifest.run_id}: qualification {field} must include timezone"
            )
        parsed_times[field] = parsed
    if (
        parsed_times["comparison_ended_utc"]
        <= parsed_times["comparison_started_utc"]
    ):
        raise ValueError(
            f"{manifest.run_id}: comparison end must follow start"
        )
    first_count_seq = metadata["comparison_first_count_seq"]
    last_count_seq = metadata["comparison_last_count_seq"]
    if (
        not isinstance(first_count_seq, int)
        or isinstance(first_count_seq, bool)
        or not isinstance(last_count_seq, int)
        or isinstance(last_count_seq, bool)
        or first_count_seq < 1
        or last_count_seq < first_count_seq
    ):
        raise ValueError(
            f"{manifest.run_id}: comparison count range must be positive "
            "and ordered"
        )
    if any(
        first < first_count_seq or last > last_count_seq
        for first, last in segment_ranges
    ):
        raise ValueError(
            f"{manifest.run_id}: service-plane ranges must lie inside the "
            "comparison count range"
        )
    return SourceTyping(
        evidence_kind=metadata["evidence_kind"],
        comparison_interval_id=metadata["comparison_interval_id"],
        comparison_started_utc=metadata["comparison_started_utc"],
        comparison_ended_utc=metadata["comparison_ended_utc"],
        comparison_first_count_seq=first_count_seq,
        comparison_last_count_seq=last_count_seq,
        estimator_type=metadata["estimator_type"],
        measurement_backend=metadata["measurement_backend"],
        source_domain=metadata["source_domain"],
        uncertainty=parsed_uncertainty,
        service_plane_segments=tuple(parsed_segments),
    )


def _load_counts(manifest: RunManifest) -> tuple[list[CountWindow], Path]:
    path = _contract_path(manifest, "count_observations_v1")
    _validate_source(path, "count_observations_v1", manifest)
    rows = [
        CountWindow(
            seq=int(row["count_seq"]),
            channel_id=int(row["channel_id"]),
            open_ticks=int(row["gate_open_ticks"]),
            close_ticks=int(row["gate_close_ticks"]),
            gate_domain=row["gate_domain"],
            counted_edges=int(row["counted_edges"]),
            source_edge=row["source_edge"],
            source_domain=row["source_domain"],
            flags=int(row["flags"]),
        )
        for row in _read_rows(path)
    ]
    return rows, path


def _load_references(manifest: RunManifest) -> tuple[list[Reference], Path]:
    path = _contract_path(manifest, "raw_events_v1")
    _validate_source(path, "raw_events_v1", manifest)
    rows = [
        Reference(
            seq=int(row["event_seq"]),
            ticks=int(row["timestamp_ticks"]),
            domain=row["capture_domain"],
            flags=int(row["flags"]),
        )
        for row in _read_rows(path)
        if row["record_type"] == "REF"
        and row["edge"] == "R"
        and int(row["channel_id"]) == 1
    ]
    return rows, path


def _load_status(manifest: RunManifest) -> tuple[list[dict[str, str]], Path]:
    path = _contract_path(manifest, "health_v1")
    _validate_source(path, "health_v1", manifest)
    return _read_rows(path), path


def _load_snapshots(manifest: RunManifest) -> tuple[list[RawSnapshot], Path]:
    path = _contract_path(manifest, "pps_snapshots_v1")
    _validate_source(path, "pps_snapshots_v1", manifest)
    rows = [
        RawSnapshot(
            session=int(row["session"]),
            sequence=int(row["snapshot_sequence"]),
            cumulative_down_counter=int(row["cumulative_down_counter"]),
            reference_sequence=int(row["reference_sequence"]),
            reference_timestamp_ticks=int(row["reference_timestamp_ticks"]),
            status=int(row["status"]),
            backend=row["backend"],
        )
        for row in _read_rows(path)
    ]
    if not rows:
        raise ValueError(f"{manifest.run_id}: PPS snapshot source is empty")
    return rows, path


def _snapshot_continuity(
    snapshots: list[RawSnapshot],
    references: list[Reference],
    counts: list[CountWindow],
    manifest: RunManifest,
) -> dict[str, Any]:
    expected_backend = "pio_wait_cumulative_snapshot_dma_v1"
    reference_timestamps = {reference.ticks for reference in references}
    observations = tuple(
        SnapshotObservation(
            sequence=snapshot.sequence,
            session_id=str(snapshot.session),
            raw_counter_value=snapshot.cumulative_down_counter,
            reference_timestamp_ticks=snapshot.reference_timestamp_ticks,
            reference_sequence=snapshot.reference_sequence,
            capture_valid=snapshot.status == 0,
            capture_faults=(
                () if snapshot.status == 0 else ("snapshot_status_nonzero",)
            ),
        )
        for snapshot in snapshots
    )
    reconstructed = reconstruct_snapshots(
        observations,
        ReconstructionPolicy(
            # One PIO X decrement per system-clock tick is an intentionally
            # loose architectural ceiling for full-wrap exclusion. It is not
            # the expected oscillator frequency or an acceptance tolerance.
            max_oscillator_hz=PPS_SNAPSHOT_MAX_CAPTURED_EDGE_RATE_HZ,
            timestamp_ticks_per_second=_domain_hz(
                manifest, "rp2040_timer0"
            ),
            timestamp_modulus=(1 << 32) * RP2040_TIMER0_TICKS_PER_US,
        ),
    )
    counts_by_sequence = {count.seq: count for count in counts}
    observations_by_key = {
        (observation.session_id, observation.sequence): observation
        for observation in observations
    }
    valid_results = [result for result in reconstructed if result.valid]
    arithmetic_matches = []
    for result in valid_results:
        count = counts_by_sequence.get(result.closing_sequence)
        opening = (
            observations_by_key.get(
                (result.session_id, result.opening_sequence)
            )
            if result.opening_sequence is not None
            else None
        )
        arithmetic_matches.append(
            count is not None
            and count.counted_edges == result.interval_count
            and opening is not None
            and count.open_ticks == opening.reference_timestamp_ticks
            and count.close_ticks
            == observations_by_key[
                (result.session_id, result.closing_sequence)
            ].reference_timestamp_ticks
        )

    first_sequences_by_session: dict[int, int] = {}
    for snapshot in snapshots:
        first_sequences_by_session.setdefault(snapshot.session, snapshot.sequence)
    anchor_suppressed = all(
        sequence not in counts_by_sequence
        for sequence in first_sequences_by_session.values()
    )
    reasons = sorted(
        {reason for result in reconstructed for reason in result.reasons}
    )
    invalid_reasons = sorted(
        {
            reason
            for result in reconstructed
            if result.state == "invalid"
            for reason in result.reasons
        }
    )
    return {
        "raw_snapshot_count": len(snapshots),
        "session_count": len(first_sequences_by_session),
        "valid_reconstructed_interval_count": len(valid_results),
        "all_backends_match": all(
            snapshot.backend == expected_backend for snapshot in snapshots
        ),
        "all_capture_status_clear": all(snapshot.status == 0 for snapshot in snapshots),
        "all_reference_timestamps_present": all(
            snapshot.reference_timestamp_ticks in reference_timestamps
            for snapshot in snapshots
        ),
        "first_anchor_suppressed": anchor_suppressed,
        "all_reconstructed_counts_match_cnt": (
            len(arithmetic_matches) == len(counts)
            and all(arithmetic_matches)
        ),
        "reconstruction_reasons": reasons,
        "invalid_reconstruction_reasons": invalid_reasons,
        "continuous": (
            len(first_sequences_by_session) == 1
            and
            len(valid_results) == len(snapshots) - len(first_sequences_by_session)
            and not invalid_reasons
        ),
    }


def _domain_hz(manifest: RunManifest, domain: str) -> float:
    for item in manifest.data.get("domains", []):
        if item.get("name") == domain and isinstance(
            item.get("nominal_hz"), (int, float)
        ):
            value = float(item["nominal_hz"])
            if value > 0 and math.isfinite(value):
                return value
    raise ValueError(f"{manifest.run_id}: domain {domain!r} has no nominal_hz")


def _timer_interval_ticks(open_ticks: int, close_ticks: int, domain: str) -> int:
    if domain != "rp2040_timer0":
        return close_ticks - open_ticks
    open_us = (open_ticks // RP2040_TIMER0_TICKS_PER_US) & 0xFFFFFFFF
    close_us = (close_ticks // RP2040_TIMER0_TICKS_PER_US) & 0xFFFFFFFF
    return (
        (close_us - open_us) % RP2040_TIMER0_MICROS_MODULUS
    ) * RP2040_TIMER0_TICKS_PER_US


def _candidate_windows(
    references: list[Reference],
    counts: list[CountWindow],
    config: QualificationConfig,
) -> list[CandidateWindow]:
    pairs: list[tuple[Reference, Reference]] = list(
        zip(references, references[1:])
    )
    pair_cursor = 0
    output: list[CandidateWindow] = []
    for count in counts:
        match: tuple[Reference, Reference] | None = None
        match_index: int | None = None
        for index in range(pair_cursor, len(pairs)):
            earlier, later = pairs[index]
            if (
                earlier.domain == count.gate_domain
                and later.domain == count.gate_domain
                and earlier.ticks == count.open_ticks
                and later.ticks == count.close_ticks
            ):
                match = (earlier, later)
                match_index = index
                break
        traceable = match is not None
        if match_index is not None:
            pair_cursor = match_index + 1
        reasons: list[str] = []
        interval_s: float | None = None
        reference_valid = traceable
        if not traceable:
            reasons.append("authoritative_ref_boundary_mismatch")
        else:
            earlier, later = match
            domain_hz = (
                16_000_000.0
                if count.gate_domain == "rp2040_timer0"
                else None
            )
            if domain_hz is None:
                reasons.append("reference_interval_domain_rate_unavailable")
                reference_valid = False
            else:
                interval_s = (
                    _timer_interval_ticks(
                        earlier.ticks, later.ticks, count.gate_domain
                    )
                    / domain_hz
                )
                if (
                    abs(interval_s - config.nominal_reference_interval_s)
                    > config.reference_interval_tolerance_s
                ):
                    reasons.append("reference_interval_outlier")
                    reference_valid = False
            if (
                (earlier.flags | later.flags) & REFERENCE_INVALID_FLAGS
                or count.flags & (1 << 3)
            ):
                reasons.append("reference_flagged_invalid")
                reference_valid = False

        count_valid = count.counted_edges > 0 and not (
            count.flags & CANDIDATE_COUNT_INVALID_FLAGS
        )
        if count.counted_edges == 0:
            reasons.append("count_zero")
        elif count.flags & (1 << 13):
            reasons.append("count_saturated")
        elif count.flags & (1 << 12):
            reasons.append("physical_aperture_invalid")
        elif count.flags & ((1 << 0) | (1 << 1) | (1 << 2)):
            reasons.append("boundary_continuity_invalid")
        elif count.flags & CANDIDATE_COUNT_INVALID_FLAGS:
            reasons.append("count_flagged_invalid")
        eligible = reference_valid and count_valid
        frequency = (
            count.counted_edges / config.nominal_reference_interval_s
            if eligible
            else None
        )
        output.append(
            CandidateWindow(
                seq=count.seq,
                frequency_hz=frequency,
                duration_s=interval_s,
                reference_valid=reference_valid,
                count_valid=count_valid,
                eligible=eligible,
                traceable=traceable,
                reasons=tuple(dict.fromkeys(reasons)),
            )
        )
    return output


def _independent_frequencies(
    counts: list[CountWindow],
    manifest: RunManifest,
    first_count_seq: int,
    last_count_seq: int,
) -> tuple[list[float], float]:
    values: list[float] = []
    total_duration_s = 0.0
    for count in counts:
        if not first_count_seq <= count.seq <= last_count_seq:
            continue
        if (
            count.counted_edges <= 0
            or count.flags & INDEPENDENT_COUNT_INVALID_FLAGS
        ):
            continue
        elapsed_ticks = _timer_interval_ticks(
            count.open_ticks, count.close_ticks, count.gate_domain
        )
        if elapsed_ticks <= 0:
            continue
        elapsed_s = elapsed_ticks / _domain_hz(
            manifest, count.gate_domain
        )
        values.append(count.counted_edges / elapsed_s)
        total_duration_s += elapsed_s
    return values, total_duration_s


def _summary(values: list[float]) -> dict[str, float | int | None]:
    return {
        "sample_count": len(values),
        "mean_hz": statistics.fmean(values) if values else None,
        "population_stdev_hz": statistics.pstdev(values)
        if len(values) >= 2
        else None,
        "min_hz": min(values) if values else None,
        "max_hz": max(values) if values else None,
    }


def _multi_span_frequency_metrics(
    windows: list[CandidateWindow],
    *,
    nominal_reference_interval_s: float,
    count_resolution_edges: int,
    spans: tuple[int, ...] = (1, 10, 60),
) -> list[dict[str, Any]]:
    """Summarise non-overlapping clean, sequence-contiguous count spans.

    Averaging official one-boundary frequencies is equivalent to differencing
    the cumulative counter endpoints because every included interval has the
    same declared nominal reference duration.  Resetting the block at every
    ineligible or missing sequence prevents a longer estimate from spanning a
    malformed reference, snapshot gap, or session discontinuity.
    """

    ordered = sorted(windows, key=lambda item: item.seq)
    output: list[dict[str, Any]] = []
    for span in spans:
        if span <= 0:
            raise ValueError("multi-span frequency spans must be positive")
        blocks: list[float] = []
        pending: list[float] = []
        previous_seq: int | None = None
        eligible_windows = 0
        for window in ordered:
            contiguous = (
                previous_seq is not None
                and window.seq == previous_seq + 1
            )
            if (
                not window.eligible
                or window.frequency_hz is None
                or (previous_seq is not None and not contiguous)
            ):
                pending.clear()
            if window.eligible and window.frequency_hz is not None:
                if not contiguous:
                    pending.clear()
                pending.append(float(window.frequency_hz))
                eligible_windows += 1
                if len(pending) == span:
                    blocks.append(statistics.fmean(pending))
                    pending.clear()
            previous_seq = window.seq
        output.append(
            {
                "span_windows": span,
                "nominal_span_s": span * nominal_reference_interval_s,
                "frequency_quantum_hz": (
                    count_resolution_edges
                    / (span * nominal_reference_interval_s)
                ),
                "eligible_window_count": eligible_windows,
                "unused_eligible_window_count": (
                    eligible_windows - len(blocks) * span
                ),
                **_summary(blocks),
            }
        )
    return output


def _status_reason_evidence(
    rows: list[dict[str, str]], required: tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    reason_positions = [
        (index, row["status_value"])
        for index, row in enumerate(rows)
        if row["component"] == "pps_gate"
        and row["status_key"] in {
            "last_reason",
            "reference_reason",
            "count_reason",
        }
    ]
    result: dict[str, dict[str, Any]] = {}
    for reason in required:
        matches = [index for index, value in reason_positions if value == reason]
        inhibited = False
        for index in matches:
            lower = max(0, index - 30)
            upper = min(len(rows), index + 31)
            if any(
                row["component"] == "pps_gate"
                and row["status_key"] == "control_eligible"
                and row["status_value"].strip().lower() == "false"
                for row in rows[lower:upper]
            ):
                inhibited = True
                break
        result[reason] = {
            "detected": bool(matches),
            "inhibition_observed": inhibited,
            "evidence_refs": [
                f"health_v1:STS:{rows[index]['status_seq']}"
                for index in matches
            ],
        }
    return result


def _lifecycle_status(rows: list[dict[str, str]]) -> dict[str, bool]:
    def values(key: str) -> list[tuple[int, str]]:
        return [
            (index, row["status_value"].strip().lower())
            for index, row in enumerate(rows)
            if row["component"] == "pps_gate" and row["status_key"] == key
        ]

    startup = values("startup_inhibit_active")
    control = values("control_eligible")
    reference = values("reference_validity")
    count = values("count_validity")
    fault_positions = [
        index
        for index, row in enumerate(rows)
        if row["component"] == "pps_gate"
        and row["status_key"] in {
            "last_reason",
            "reference_reason",
            "count_reason",
        }
        and row["status_value"]
        not in {
            "none",
            "reference_valid",
            "count_valid",
            "reference_unavailable",
            "count_unavailable",
        }
    ]
    latest_fault = max(fault_positions) if fault_positions else None
    return {
        "startup_inhibit_true_observed": any(
            value == "true" for _, value in startup
        ),
        "startup_inhibit_clear_observed": any(
            value == "false" for _, value in startup
        ),
        "control_eligible_observed": any(
            value == "true" for _, value in control
        ),
        "control_inhibition_observed": any(
            value == "false" for _, value in control
        ),
        "reference_valid_and_invalid_observed": (
            any(value == "valid" for _, value in reference)
            and any(value == "invalid" for _, value in reference)
        ),
        "count_valid_and_invalid_observed": (
            any(value == "valid" for _, value in count)
            and any(value == "invalid" for _, value in count)
        ),
        "recovery_after_latest_fault_observed": (
            latest_fault is not None
            and any(
                index > latest_fault and value == "true"
                for index, value in control
            )
        ),
    }


def _capture_integrity(rows: list[dict[str, str]]) -> dict[str, Any]:
    required = {
        "capture.dropped_count",
        "capture.pps_count_boundary_dropped_count",
        "pps_gate.snapshot_overwrite_count",
        "pps_gate.snapshot_continuity_loss_count",
        "pps_gate.snapshot_pio_rxstall_count",
        "pps_gate.snapshot_dma_error_count",
        "pps_gate.snapshot_dma_stopped_count",
    }
    optional = {
        "capture.capture_drop_count",
        "capture.pio_fifo_overflow_drop_count",
        "capture.parser_error_count",
        "host.dropped_record_count",
    }
    watched = required | optional
    observed: dict[str, list[int | None]] = {}
    for row in rows:
        name = f"{row['component']}.{row['status_key']}"
        if name not in watched:
            continue
        try:
            value: int | None = int(row["status_value"], 0)
        except ValueError:
            value = None
        observed.setdefault(name, []).append(value)
    return {
        "counters": observed,
        "required_counters": sorted(required),
        "required_drop_counter_observed": required <= set(observed),
        "all_observed_counters_zero": (
            bool(observed)
            and all(
                value == 0
                for values in observed.values()
                for value in values
            )
        ),
    }


def _status_plane_metrics(rows: list[dict[str, str]]) -> dict[str, Any]:
    groups = {
        "physical_pps": {
            "pps_gate.missing_pps_count",
            "pps_gate.pps_interval_anomaly_count",
        },
        "capture_storage": {
            "capture.dropped_count",
            "capture.pps_count_boundary_dropped_count",
            "pps_gate.snapshot_overwrite_count",
            "pps_gate.snapshot_continuity_loss_count",
            "pps_gate.snapshot_pio_rxstall_count",
            "pps_gate.snapshot_dma_error_count",
            "pps_gate.snapshot_dma_stopped_count",
        },
        "foreground_backlog": {
            "pps_gate.snapshot_backlog_depth",
            "pps_gate.snapshot_backlog_high_water",
        },
        "telemetry_parser": {
            "capture.parser_error_count",
            "host.dropped_record_count",
        },
    }
    output: dict[str, Any] = {}
    for group, names in groups.items():
        values: dict[str, list[int | None]] = {}
        for row in rows:
            name = f"{row['component']}.{row['status_key']}"
            if name not in names:
                continue
            try:
                parsed: int | None = int(row["status_value"], 0)
            except ValueError:
                parsed = None
            values.setdefault(name, []).append(parsed)
        output[group] = {
            "counters": values,
            "latest": {
                name: observations[-1]
                for name, observations in values.items()
            },
            "maximum": {
                name: max(
                    value for value in observations if value is not None
                )
                if any(value is not None for value in observations)
                else None
                for name, observations in values.items()
            },
        }
    return output


def _runtime_backend_identity(
    rows: list[dict[str, str]],
    config: QualificationConfig,
    manifest: RunManifest,
) -> dict[str, Any]:
    firmware = manifest.data.get("firmware")
    firmware = firmware if isinstance(firmware, dict) else {}
    expected: dict[tuple[str, str], str] = {
        ("firmware", "name"): str(firmware.get("name", "")),
        ("firmware", "version"): str(firmware.get("version", "")),
        ("firmware", "config_id"): str(firmware.get("config_id", "")),
        ("firmware", "git_commit"): str(firmware.get("git_commit", "")),
        ("capture", "tcxo_counter_backend"): "pps_gated_ratio",
        ("capture", "pps_gated_ratio_init"): "ok",
        ("build", "enable_dac_ad5693r"): "0",
        ("build", "enable_h1_dac_sweep"): "0",
        ("build", "enable_phase4_observe_preview"): "0",
        ("phase4_preview", "actuation_authorized"): "false",
        ("pps_gate", "backend"): "pps_gated_ratio",
        ("pps_gate", "boundary_owner"): "pio_state_machine",
        ("pps_gate", "aperture_backend"):
            "pio_wait_cumulative_snapshot_dma_v1",
        ("pps_gate", "backend_qualified"): "false",
        ("pps_gate", "duplicate_max_interval_us"): str(
            round(config.duplicate_max_interval_s * 1_000_000.0)
        ),
        ("pps_gate", "min_interval_us"): str(
            round(
                (
                    config.nominal_reference_interval_s
                    - config.reference_interval_tolerance_s
                )
                * 1_000_000.0
            )
        ),
        ("pps_gate", "max_interval_us"): str(
            round(
                (
                    config.nominal_reference_interval_s
                    + config.reference_interval_tolerance_s
                )
                * 1_000_000.0
            )
        ),
        ("pps_gate", "missing_timeout_us"): str(
            round(config.missing_timeout_s * 1_000_000.0)
        ),
        ("pps_gate", "count_resolution_edges"): str(
            config.count_resolution_edges
        ),
    }
    observed: dict[tuple[str, str], str] = {}
    for row in rows:
        key = (row["component"], row["status_key"])
        if key in expected:
            observed[key] = row["status_value"]
    fields = {
        f"{component}.{key}": {
            "expected": value,
            "observed": observed.get((component, key)),
            "matches": observed.get((component, key)) == value,
        }
        for (component, key), value in expected.items()
    }
    firmware_commit = expected[("firmware", "git_commit")]
    firmware_commit_specific = (
        len(firmware_commit) == 40
        and all(
            character in "0123456789abcdefABCDEF"
            for character in firmware_commit
        )
    )
    return {
        "fields": fields,
        "firmware_commit_specific": firmware_commit_specific,
        "all_required_fields_match": all(
            item["matches"] for item in fields.values()
        )
        and firmware_commit_specific,
    }


def _service_plane_metrics(
    segments: tuple[dict[str, Any], ...],
    windows: list[CandidateWindow],
    minimum_windows_per_segment: int,
    nominal_reference_interval_s: float = 1.0,
    count_resolution_edges: int = 1,
) -> dict[str, Any]:
    by_seq = {
        window.seq: window.frequency_hz
        for window in windows
        if window.frequency_hz is not None
    }
    summaries: list[dict[str, Any]] = []
    for segment in sorted(segments, key=lambda item: int(item["first_count_seq"])):
        required = {"label", "mode", "first_count_seq", "last_count_seq"}
        if not required <= set(segment):
            raise ValueError(
                "service-plane segment requires label, mode, "
                "first_count_seq, and last_count_seq"
            )
        values = [
            value
            for seq, value in by_seq.items()
            if int(segment["first_count_seq"])
            <= seq
            <= int(segment["last_count_seq"])
        ]
        summaries.append(
            {
                "label": str(segment["label"]),
                "mode": str(segment["mode"]),
                "first_count_seq": int(segment["first_count_seq"]),
                "last_count_seq": int(segment["last_count_seq"]),
                **_summary(values),
                "multi_span_frequency": _multi_span_frequency_metrics(
                    [
                        window
                        for window in windows
                        if int(segment["first_count_seq"])
                        <= window.seq
                        <= int(segment["last_count_seq"])
                    ],
                    nominal_reference_interval_s=(
                        nominal_reference_interval_s
                    ),
                    count_resolution_edges=count_resolution_edges,
                ),
            }
        )
    latest_baseline: dict[str, Any] | None = None
    pairs: list[dict[str, Any]] = []
    load_count = 0
    for item in summaries:
        if item["mode"] == "baseline":
            if item["mean_hz"] is not None:
                latest_baseline = item
            continue
        load_count += 1
        if item["mean_hz"] is None or latest_baseline is None:
            continue
        mean_shift_hz = float(item["mean_hz"]) - float(latest_baseline["mean_hz"])
        item["paired_baseline_label"] = latest_baseline["label"]
        item["mean_shift_hz"] = mean_shift_hz
        pairs.append(
            {
                "baseline_label": latest_baseline["label"],
                "load_label": item["label"],
                "mean_shift_hz": mean_shift_hz,
            }
        )
    all_load_segments_paired = bool(pairs) and len(pairs) == load_count
    shift = (
        max(abs(float(item["mean_shift_hz"])) for item in pairs)
        if all_load_segments_paired
        else None
    )
    bracketed_pairs: list[dict[str, Any]] = []
    for index, item in enumerate(summaries):
        if item["mode"] != "load" or item["mean_hz"] is None:
            continue
        preceding = next(
            (
                candidate
                for candidate in reversed(summaries[:index])
                if candidate["mode"] == "baseline"
                and candidate["mean_hz"] is not None
            ),
            None,
        )
        following = next(
            (
                candidate
                for candidate in summaries[index + 1 :]
                if candidate["mode"] == "baseline"
                and candidate["mean_hz"] is not None
            ),
            None,
        )
        if preceding is None or following is None:
            continue
        preceding_center = (
            int(preceding["first_count_seq"])
            + int(preceding["last_count_seq"])
        ) / 2.0
        load_center = (
            int(item["first_count_seq"])
            + int(item["last_count_seq"])
        ) / 2.0
        following_center = (
            int(following["first_count_seq"])
            + int(following["last_count_seq"])
        ) / 2.0
        span = following_center - preceding_center
        if span <= 0 or not preceding_center < load_center < following_center:
            continue
        interpolation_fraction = (load_center - preceding_center) / span
        interpolated_baseline_hz = float(preceding["mean_hz"]) + (
            interpolation_fraction
            * (float(following["mean_hz"]) - float(preceding["mean_hz"]))
        )
        bracketed_pairs.append(
            {
                "preceding_baseline_label": preceding["label"],
                "load_label": item["label"],
                "following_baseline_label": following["label"],
                "interpolation_fraction": interpolation_fraction,
                "interpolated_baseline_hz": interpolated_baseline_hz,
                "bracketed_mean_shift_hz": (
                    float(item["mean_hz"]) - interpolated_baseline_hz
                ),
            }
        )
    maximum_absolute_bracketed_shift_hz = (
        max(
            abs(float(item["bracketed_mean_shift_hz"]))
            for item in bracketed_pairs
        )
        if bracketed_pairs
        else None
    )
    return {
        "segments": summaries,
        "comparison_method": "load_minus_immediately_preceding_baseline",
        "pairs": pairs,
        "all_load_segments_paired": all_load_segments_paired,
        "maximum_absolute_mean_shift_hz": shift,
        "bracketed_comparison_method": (
            "load_minus_linearly_interpolated_preceding_and_following_"
            "baseline_means_at_segment_center"
        ),
        "bracketed_pairs": bracketed_pairs,
        "maximum_absolute_bracketed_mean_shift_hz": (
            maximum_absolute_bracketed_shift_hz
        ),
        "comparison_available": all_load_segments_paired,
        "minimum_windows_per_segment": minimum_windows_per_segment,
        "minimum_windows_met": (
            bool(summaries)
            and any(item["mode"] == "baseline" for item in summaries)
            and any(item["mode"] == "load" for item in summaries)
            and all(
                int(item["sample_count"]) >= minimum_windows_per_segment
                for item in summaries
            )
        ),
    }


def _uncertainty(
    candidate_typing: SourceTyping,
    independent_typing: SourceTyping | None,
    nominal_frequency_hz: float,
    nominal_gate_s: float,
) -> dict[str, Any]:
    components: dict[str, float | None] = {
        "count_quantization_standard_uncertainty_hz": (
            candidate_typing.uncertainty[
                "count_quantization_standard_uncertainty_hz"
            ]
        ),
        "counter_aperture_frequency_hz_1sigma": None,
        "reference_frequency_hz_1sigma": None,
        "independent_frequency_hz_1sigma": None,
    }
    aperture_s = candidate_typing.uncertainty["counter_aperture_s_1sigma"]
    if aperture_s is not None:
        components["counter_aperture_frequency_hz_1sigma"] = (
            nominal_frequency_hz * aperture_s / nominal_gate_s
        )
    reference_fractional = candidate_typing.uncertainty[
        "reference_fractional_1sigma"
    ]
    if reference_fractional is not None:
        components["reference_frequency_hz_1sigma"] = (
            nominal_frequency_hz * reference_fractional
        )
    if independent_typing is not None:
        components["independent_frequency_hz_1sigma"] = (
            independent_typing.uncertainty[
                "independent_frequency_hz_1sigma"
            ]
        )
    unavailable = [
        key for key, value in components.items() if value is None
    ]
    combined = (
        math.sqrt(sum(float(value) ** 2 for value in components.values()))
        if not unavailable
        else None
    )
    return {
        "components": components,
        "unavailable_components": unavailable,
        "combined_standard_uncertainty_hz": combined,
        "coverage_factor": 2.0 if combined is not None else None,
        "expanded_uncertainty_hz": 2.0 * combined
        if combined is not None
        else None,
    }


def _evidence_state(
    run_dir: Path, manifest: RunManifest
) -> dict[str, Any]:
    failures, warnings = validate_evidence_snapshot(run_dir, manifest)
    return {
        "complete_marker": (run_dir / COMPLETE_MARKER).exists(),
        "snapshot_present": (run_dir / EVIDENCE_MANIFEST).exists(),
        "snapshot_valid": not failures and not warnings,
        "failures": failures,
        "warnings": warnings,
    }


def _nominal_frequency(manifest: RunManifest) -> float:
    oscillator = manifest.data.get("oscillator")
    if (
        isinstance(oscillator, dict)
        and isinstance(oscillator.get("nominal_frequency_hz"), (int, float))
        and float(oscillator["nominal_frequency_hz"]) > 0
    ):
        return float(oscillator["nominal_frequency_hz"])
    raise ValueError(
        f"{manifest.run_id}: oscillator.nominal_frequency_hz is unavailable"
    )


def _observe_only_manifest(manifest: RunManifest) -> bool:
    return (
        manifest.data.get("control_mode") == "observe_only"
        and manifest.data.get("closed_loop_control") is False
    )


def _normalized_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _write_deterministic(path: Path, payload: dict[str, Any]) -> None:
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise FileExistsError(
                f"refusing to replace non-identical derived artifact: {path}"
            )
        return
    path.write_bytes(encoded)


def qualify_pps_backend(
    candidate_run: Path,
    *,
    independent_run: Path | None = None,
    config_path: Path = DEFAULT_CONFIG,
) -> QualificationResult:
    candidate_run = candidate_run.resolve()
    independent_run = independent_run.resolve() if independent_run else None
    before_candidate = _source_hashes(candidate_run)
    before_independent = (
        _source_hashes(independent_run) if independent_run else None
    )
    config_bytes = config_path.read_bytes()
    config = QualificationConfig.from_mapping(
        json.loads(config_bytes.decode("utf-8"))
    )

    candidate_manifest = load_manifest(candidate_run)
    candidate_typing = _load_typing(candidate_manifest)
    if candidate_typing.estimator_type != config.candidate_estimator_type:
        raise ValueError("candidate estimator_type does not match qualification config")
    if (
        candidate_typing.measurement_backend
        != config.expected_candidate_backend
    ):
        raise ValueError(
            "candidate measurement_backend does not match PPS-gated backend"
        )
    candidate_counts, candidate_count_path = _load_counts(candidate_manifest)
    candidate_references, candidate_reference_path = _load_references(
        candidate_manifest
    )
    candidate_snapshots, candidate_snapshot_path = _load_snapshots(
        candidate_manifest
    )
    status_rows, candidate_status_path = _load_status(candidate_manifest)
    if any(
        count.source_domain != candidate_typing.source_domain
        for count in candidate_counts
    ):
        raise ValueError(
            "candidate CNT source_domain differs from explicit source typing"
        )
    if any(
        count.channel_id != 2 or count.source_edge != "R"
        for count in candidate_counts
    ):
        raise ValueError(
            "candidate PPS-gated CNT rows must be channel 2 rising-edge counts"
        )
    candidate_windows = _candidate_windows(
        candidate_references, candidate_counts, config
    )
    candidate_comparison_windows = [
        window
        for window in candidate_windows
        if candidate_typing.comparison_first_count_seq
        <= window.seq
        <= candidate_typing.comparison_last_count_seq
    ]
    candidate_values = [
        window.frequency_hz
        for window in candidate_comparison_windows
        if window.frequency_hz is not None
    ]
    candidate_counts_by_sequence = {
        count.seq: count for count in candidate_counts
    }
    diagnostic_timer_normalized_values = [
        candidate_counts_by_sequence[window.seq].counted_edges
        / window.duration_s
        for window in candidate_comparison_windows
        if window.eligible
        and window.duration_s is not None
        and window.duration_s > 0
        and window.seq in candidate_counts_by_sequence
    ]

    independent_manifest: RunManifest | None = None
    independent_typing: SourceTyping | None = None
    independent_counts: list[CountWindow] = []
    independent_values: list[float] = []
    independent_duration_s = 0.0
    independent_paths: dict[str, Any] | None = None
    if independent_run is not None:
        independent_manifest = load_manifest(independent_run)
        independent_typing = _load_typing(independent_manifest)
        independent_path = (
            independent_typing.estimator_type,
            independent_typing.measurement_backend,
        )
        if independent_path not in config.allowed_independent_paths:
            raise ValueError(
                "independent estimator/backend path is not authorised"
            )
        if independent_typing.source_domain != candidate_typing.source_domain:
            raise ValueError(
                "candidate and independent source_domain differ"
            )
        if (
            independent_typing.comparison_interval_id
            != candidate_typing.comparison_interval_id
        ):
            raise ValueError(
                "candidate and independent comparison_interval_id differ"
            )
        if (
            _normalized_utc(independent_typing.comparison_started_utc)
            != _normalized_utc(candidate_typing.comparison_started_utc)
            or _normalized_utc(independent_typing.comparison_ended_utc)
            != _normalized_utc(candidate_typing.comparison_ended_utc)
        ):
            raise ValueError(
                "candidate and independent comparison UTC bounds differ"
            )
        independent_counts, independent_count_path = _load_counts(
            independent_manifest
        )
        if any(
            count.source_domain != independent_typing.source_domain
            for count in independent_counts
        ):
            raise ValueError(
                "independent CNT source_domain differs from explicit source typing"
            )
        independent_values, independent_duration_s = _independent_frequencies(
            independent_counts,
            independent_manifest,
            independent_typing.comparison_first_count_seq,
            independent_typing.comparison_last_count_seq,
        )
        independent_paths = {
            "count_observations": {
                "path": independent_count_path.relative_to(
                    independent_run
                ).as_posix(),
                "sha256": _sha256_file(independent_count_path),
            }
        }

    candidate_summary = _summary(candidate_values)
    diagnostic_timer_normalized_summary = _summary(
        diagnostic_timer_normalized_values
    )
    independent_summary = _summary(independent_values)
    bias = (
        float(candidate_summary["mean_hz"])
        - float(independent_summary["mean_hz"])
        if candidate_summary["mean_hz"] is not None
        and independent_summary["mean_hz"] is not None
        else None
    )
    diagnostics = _status_reason_evidence(
        status_rows, config.required_fault_reason_codes
    )
    lifecycle = _lifecycle_status(status_rows)
    capture_integrity = _capture_integrity(status_rows)
    status_planes = _status_plane_metrics(status_rows)
    runtime_backend_identity = _runtime_backend_identity(
        status_rows, config, candidate_manifest
    )
    comparison_snapshots = [
        snapshot
        for snapshot in candidate_snapshots
        if candidate_typing.comparison_first_count_seq - 1
        <= snapshot.sequence
        <= candidate_typing.comparison_last_count_seq
    ]
    comparison_counts = [
        count
        for count in candidate_counts
        if candidate_typing.comparison_first_count_seq
        <= count.seq
        <= candidate_typing.comparison_last_count_seq
    ]
    snapshot_continuity = _snapshot_continuity(
        comparison_snapshots,
        candidate_references,
        comparison_counts,
        candidate_manifest,
    )
    service_plane = _service_plane_metrics(
        candidate_typing.service_plane_segments,
        candidate_windows,
        config.minimum_service_plane_windows_per_segment,
        nominal_reference_interval_s=(
            config.nominal_reference_interval_s
        ),
        count_resolution_edges=config.count_resolution_edges,
    )
    uncertainty = _uncertainty(
        candidate_typing,
        independent_typing,
        _nominal_frequency(candidate_manifest),
        config.nominal_reference_interval_s,
    )
    candidate_evidence = _evidence_state(
        candidate_run, candidate_manifest
    )
    independent_evidence = (
        _evidence_state(independent_run, independent_manifest)
        if independent_run is not None and independent_manifest is not None
        else None
    )

    traceable_count = sum(
        1 for window in candidate_comparison_windows if window.traceable
    )
    eligible_count = len(candidate_values)
    stable_duration_s = sum(
        float(window.duration_s)
        for window in candidate_comparison_windows
        if window.eligible and window.duration_s is not None
    )
    declared_comparison_duration_s = (
        _normalized_utc(candidate_typing.comparison_ended_utc)
        - _normalized_utc(candidate_typing.comparison_started_utc)
    ).total_seconds()
    reason_counts = Counter(
        reason
        for window in candidate_comparison_windows
        for reason in window.reasons
    )
    checks = {
        "candidate_evidence_is_bench": (
            candidate_typing.evidence_kind == "bench"
        ),
        "candidate_manifest_is_observe_only": (
            _observe_only_manifest(candidate_manifest)
        ),
        "candidate_evidence_complete_and_sealed": (
            candidate_evidence["complete_marker"]
            and candidate_evidence["snapshot_valid"]
        ),
        "independent_evidence_present": independent_manifest is not None,
        "independent_evidence_is_bench": (
            independent_typing is not None
            and independent_typing.evidence_kind == "bench"
        ),
        "independent_manifest_is_observe_only": (
            independent_manifest is not None
            and _observe_only_manifest(independent_manifest)
        ),
        "independent_evidence_complete_and_sealed": (
            independent_evidence is not None
            and independent_evidence["complete_marker"]
            and independent_evidence["snapshot_valid"]
        ),
        "all_candidate_windows_traceable": (
            bool(candidate_comparison_windows)
            and traceable_count == len(candidate_comparison_windows)
        ),
        "candidate_comparison_range_endpoints_present": (
            any(
                count.seq == candidate_typing.comparison_first_count_seq
                for count in candidate_counts
            )
            and any(
                count.seq == candidate_typing.comparison_last_count_seq
                for count in candidate_counts
            )
        ),
        "independent_comparison_range_endpoints_present": (
            independent_typing is not None
            and any(
                count.seq
                == independent_typing.comparison_first_count_seq
                for count in independent_counts
            )
            and any(
                count.seq
                == independent_typing.comparison_last_count_seq
                for count in independent_counts
            )
        ),
        "minimum_eligible_windows": (
            eligible_count >= config.minimum_eligible_windows
        ),
        "minimum_stable_duration": (
            stable_duration_s >= config.minimum_stable_duration_s
        ),
        "candidate_duration_matches_declared_interval": (
            abs(stable_duration_s - declared_comparison_duration_s)
            <= config.reference_interval_tolerance_s
        ),
        "candidate_jitter_within_bound": (
            candidate_summary["population_stdev_hz"] is not None
            and float(candidate_summary["population_stdev_hz"])
            <= config.maximum_candidate_jitter_hz
        ),
        "independent_bias_within_bound": (
            bias is not None
            and abs(bias) <= config.maximum_absolute_bias_hz
        ),
        "independent_stable_duration": (
            independent_duration_s >= config.minimum_stable_duration_s
        ),
        "independent_duration_matches_declared_interval": (
            independent_manifest is not None
            and abs(
                independent_duration_s - declared_comparison_duration_s
            )
            <= config.reference_interval_tolerance_s
        ),
        "all_fault_reasons_detected_and_inhibited": all(
            item["detected"] and item["inhibition_observed"]
            for item in diagnostics.values()
        ),
        "startup_inhibit_and_clear_observed": (
            lifecycle["startup_inhibit_true_observed"]
            and lifecycle["startup_inhibit_clear_observed"]
        ),
        "independent_reference_and_count_validity_observed": (
            lifecycle["reference_valid_and_invalid_observed"]
            and lifecycle["count_valid_and_invalid_observed"]
        ),
        "post_fault_recovery_observed": (
            lifecycle["recovery_after_latest_fault_observed"]
        ),
        "capture_storage_counters_observed_and_zero": (
            capture_integrity["required_drop_counter_observed"]
            and capture_integrity["all_observed_counters_zero"]
        ),
        "runtime_backend_identity_and_config_match": (
            runtime_backend_identity["all_required_fields_match"]
        ),
        "raw_snapshot_continuity_and_cnt_parity": (
            snapshot_continuity["all_backends_match"]
            and snapshot_continuity["all_capture_status_clear"]
            and snapshot_continuity["all_reference_timestamps_present"]
            and snapshot_continuity["first_anchor_suppressed"]
            and snapshot_continuity["all_reconstructed_counts_match_cnt"]
            and snapshot_continuity["continuous"]
        ),
        "service_plane_shift_within_bound": (
            service_plane["maximum_absolute_mean_shift_hz"] is not None
            and float(service_plane["maximum_absolute_mean_shift_hz"])
            <= config.maximum_service_plane_mean_shift_hz
        ),
        "service_plane_minimum_windows_met": (
            service_plane["minimum_windows_met"]
        ),
        "uncertainty_complete": not uncertainty["unavailable_components"],
    }
    characterization_checks = {
        "absolute_bias_within_historical_reference": checks[
            "independent_bias_within_bound"
        ],
        "service_plane_mean_shift_within_historical_reference": checks[
            "service_plane_shift_within_bound"
        ],
        "uncertainty_complete": checks["uncertainty_complete"],
    }
    if config.acceptance_scope == "digital_architecture":
        for characterization_key in (
            "independent_bias_within_bound",
            "service_plane_shift_within_bound",
            "uncertainty_complete",
        ):
            del checks[characterization_key]
        for metrology_key in (
            "independent_evidence_present",
            "independent_evidence_is_bench",
            "independent_manifest_is_observe_only",
            "independent_evidence_complete_and_sealed",
            "independent_comparison_range_endpoints_present",
            "independent_stable_duration",
            "independent_duration_matches_declared_interval",
            "independent_reference_and_count_validity_observed",
        ):
            del checks[metrology_key]
    acceptance_passed = all(checks.values())
    bench_inputs = candidate_typing.evidence_kind == "bench" and (
        config.acceptance_scope == "digital_architecture"
        or (
            independent_typing is not None
            and independent_typing.evidence_kind == "bench"
        )
    )
    qualification_state = (
        (
            "qualified_with_limits"
            if config.synthetic_only_fault_reason_codes
            else "qualified"
        )
        if acceptance_passed
        else ("failed" if bench_inputs else "repository_validation_only")
    )
    limitations = []
    if independent_manifest is None:
        limitations.append("independent_metrology_unavailable")
    if uncertainty["unavailable_components"]:
        limitations.append("uncertainty_components_unavailable")
    if not service_plane["comparison_available"]:
        limitations.append("service_plane_comparison_unavailable")
    if not all(item["detected"] for item in diagnostics.values()):
        limitations.append("fault_injection_evidence_incomplete")
    if candidate_typing.evidence_kind != "bench":
        limitations.append("candidate_is_not_bench_evidence")
    if config.synthetic_only_fault_reason_codes:
        limitations.append(
            "counter_saturation_outside_10_mhz_one_second_applicability_"
            "and_covered_synthetically"
        )
    if config.acceptance_scope == "digital_architecture":
        limitations.extend(
            [
                "candidate_population_jitter_is_a_blocking_architecture_"
                "screen_not_a_component_limit",
                "service_plane_mean_shift_is_characterization_only",
                "absolute_bias_is_characterization_only_pending_system_"
                "error_budget",
            ]
        )

    report = {
        "schema_version": 1,
        "tool_version": TOOL_VERSION,
        "qualification_state": qualification_state,
        "acceptance_passed": acceptance_passed,
        "phase_boundary": {
            "observe_only": True,
            "control_ready": False,
            "actuation_enabled": False,
            "dac_write_authorized": False,
        },
        "config": {
            "path": config_path.name,
            "sha256": sha256(config_bytes).hexdigest(),
            "schema_version": config.schema_version,
            "acceptance_scope": config.acceptance_scope,
            "criteria_rationale_document": (
                config.criteria_rationale_document or None
            ),
            "protocol_requirements": {
                "minimum_stable_duration_s": config.minimum_stable_duration_s,
                "minimum_eligible_windows": config.minimum_eligible_windows,
                "minimum_service_plane_windows_per_segment": (
                    config.minimum_service_plane_windows_per_segment
                ),
                "duplicate_max_interval_s": (
                    config.duplicate_max_interval_s
                ),
                "missing_timeout_s": config.missing_timeout_s,
                "count_resolution_edges": config.count_resolution_edges,
            },
            "architecture_screens": {
                "candidate_population_jitter_hz": {
                    "value": config.maximum_candidate_jitter_hz,
                    "disposition": (
                        config.candidate_population_jitter_disposition
                    ),
                },
            },
            "characterization_references": {
                "absolute_bias_hz": {
                    "value": config.maximum_absolute_bias_hz,
                    "disposition": config.absolute_bias_disposition,
                },
                "service_plane_mean_shift_hz": {
                    "value": config.maximum_service_plane_mean_shift_hz,
                    "disposition": config.service_plane_mean_shift_disposition,
                },
            },
            "required_bench_fault_reason_codes": list(
                config.required_fault_reason_codes
            ),
            "synthetic_only_fault_reason_codes": list(
                config.synthetic_only_fault_reason_codes
            ),
        },
        "candidate": {
            "run_id": candidate_manifest.run_id,
            "manifest": {
                "path": candidate_manifest.path.relative_to(
                    candidate_run
                ).as_posix(),
                "sha256": _sha256_file(candidate_manifest.path),
            },
            "typing": {
                "estimator_type": candidate_typing.estimator_type,
                "measurement_backend": candidate_typing.measurement_backend,
                "source_domain": candidate_typing.source_domain,
                "comparison_interval_id": (
                    candidate_typing.comparison_interval_id
                ),
                "comparison_started_utc": (
                    candidate_typing.comparison_started_utc
                ),
                "comparison_ended_utc": (
                    candidate_typing.comparison_ended_utc
                ),
                "comparison_first_count_seq": (
                    candidate_typing.comparison_first_count_seq
                ),
                "comparison_last_count_seq": (
                    candidate_typing.comparison_last_count_seq
                ),
                "evidence_kind": candidate_typing.evidence_kind,
                "control_mode": candidate_manifest.data.get("control_mode"),
                "closed_loop_control": candidate_manifest.data.get(
                    "closed_loop_control"
                ),
            },
            "sources": {
                "reference": {
                    "path": candidate_reference_path.relative_to(
                        candidate_run
                    ).as_posix(),
                    "sha256": _sha256_file(candidate_reference_path),
                },
                "count_observations": {
                    "path": candidate_count_path.relative_to(
                        candidate_run
                    ).as_posix(),
                    "sha256": _sha256_file(candidate_count_path),
                },
                "status": {
                    "path": candidate_status_path.relative_to(
                        candidate_run
                    ).as_posix(),
                    "sha256": _sha256_file(candidate_status_path),
                },
                "snapshots": {
                    "path": candidate_snapshot_path.relative_to(
                        candidate_run
                    ).as_posix(),
                    "sha256": _sha256_file(candidate_snapshot_path),
                },
            },
            "evidence": candidate_evidence,
            "snapshot_continuity": snapshot_continuity,
            "window_count": len(candidate_windows),
            "comparison_window_count": len(candidate_comparison_windows),
            "traceable_window_count": traceable_count,
            "eligible_window_count": eligible_count,
            "stable_duration_s": stable_duration_s,
            "reference_valid_window_count": sum(
                1 for window in candidate_windows if window.reference_valid
            ),
            "count_valid_window_count": sum(
                1 for window in candidate_windows if window.count_valid
            ),
            "ineligible_reason_counts": dict(sorted(reason_counts.items())),
            "frequency": candidate_summary,
            "official_raw_frequency": {
                **candidate_summary,
                "authoritative": True,
                "estimator": "counted_edges / nominal_reference_interval",
            },
            "multi_span_official_raw_frequency": (
                _multi_span_frequency_metrics(
                    candidate_comparison_windows,
                    nominal_reference_interval_s=(
                        config.nominal_reference_interval_s
                    ),
                    count_resolution_edges=config.count_resolution_edges,
                )
            ),
            "diagnostic_timer_normalized_frequency": {
                **diagnostic_timer_normalized_summary,
                "authoritative": False,
                "estimator": "counted_edges / reconstructed_timer_interval",
                "may_override_official_failure": False,
            },
            "count_resolution_hz": (
                config.count_resolution_edges
                / config.nominal_reference_interval_s
            ),
        },
        "independent": (
            {
                "run_id": independent_manifest.run_id,
                "manifest": {
                    "path": independent_manifest.path.relative_to(
                        independent_run
                    ).as_posix(),
                    "sha256": _sha256_file(independent_manifest.path),
                },
                "typing": {
                    "estimator_type": independent_typing.estimator_type,
                    "measurement_backend": independent_typing.measurement_backend,
                    "source_domain": independent_typing.source_domain,
                    "comparison_interval_id": (
                        independent_typing.comparison_interval_id
                    ),
                    "comparison_started_utc": (
                        independent_typing.comparison_started_utc
                    ),
                    "comparison_ended_utc": (
                        independent_typing.comparison_ended_utc
                    ),
                    "comparison_first_count_seq": (
                        independent_typing.comparison_first_count_seq
                    ),
                    "comparison_last_count_seq": (
                        independent_typing.comparison_last_count_seq
                    ),
                    "evidence_kind": independent_typing.evidence_kind,
                    "control_mode": independent_manifest.data.get(
                        "control_mode"
                    ),
                    "closed_loop_control": independent_manifest.data.get(
                        "closed_loop_control"
                    ),
                },
                "sources": independent_paths,
                "evidence": independent_evidence,
                "stable_duration_s": independent_duration_s,
                "frequency": independent_summary,
            }
            if independent_manifest is not None
            and independent_typing is not None
            else None
        ),
        "comparison": {
            "declared_interval_duration_s": declared_comparison_duration_s,
            "bias_hz": bias,
            "absolute_bias_hz": abs(bias) if bias is not None else None,
        },
        "diagnostics": diagnostics,
        "eligibility_lifecycle": lifecycle,
        "capture_integrity": capture_integrity,
        "status_planes": status_planes,
        "runtime_backend_identity": runtime_backend_identity,
        "service_plane": service_plane,
        "uncertainty": uncertainty,
        "acceptance_checks": checks,
        "characterization_checks": characterization_checks,
        "limitations": limitations,
    }

    report_path = candidate_run / OUTPUT_DIR / OUTPUT_NAME
    if _source_hashes(candidate_run) != before_candidate:
        raise RuntimeError(
            "candidate source evidence changed during qualification"
        )
    if (
        independent_run is not None
        and before_independent is not None
        and _source_hashes(independent_run) != before_independent
    ):
        raise RuntimeError(
            "independent source evidence changed during qualification"
        )
    _write_deterministic(report_path, report)
    if _source_hashes(candidate_run) != before_candidate:
        raise RuntimeError("candidate source evidence changed during qualification")
    if (
        independent_run is not None
        and before_independent is not None
        and _source_hashes(independent_run) != before_independent
    ):
        raise RuntimeError(
            "independent source evidence changed during qualification"
        )
    return QualificationResult(
        report_path=report_path,
        qualification_state=qualification_state,
        acceptance_passed=acceptance_passed,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze a PPS-gated candidate run against explicit Phase 5 "
            "qualification gates without authorizing actuation."
        )
    )
    parser.add_argument("candidate_run", type=Path)
    parser.add_argument("--independent-run", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    try:
        result = qualify_pps_backend(
            args.candidate_run,
            independent_run=args.independent_run,
            config_path=args.config,
        )
    except (
        FileExistsError,
        FileNotFoundError,
        ValueError,
        json.JSONDecodeError,
        RuntimeError,
    ) as exc:
        parser.error(str(exc))
    print(result.report_path)
    print(f"qualification_state={result.qualification_state}")
    print("control_ready=false")
    print("actuation_enabled=false")
    return 0 if result.acceptance_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
