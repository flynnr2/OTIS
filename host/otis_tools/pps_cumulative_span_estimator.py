"""Continuity-aware host estimator for raw cumulative PPS snapshots.

``PPS_CUMULATIVE_SNAPSHOT_SPAN_V1`` accumulates each accepted adjacent
modulo-32-bit down-counter difference into a 64-bit-bounded total.  The
authoritative denominator is the declared number of nominal PPS intervals;
RP2040 timer normalization is emitted only as a diagnostic.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
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
from .pps_snapshot_reconstruction import (
    ReconstructionPolicy,
    SnapshotObservation,
    reconstruct_snapshots,
)
from .run_loader import load_manifest
from .time_domains import forward_progress, time_domain


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = (
    REPO_ROOT
    / "profiles"
    / "estimators"
    / "pps_cumulative_snapshot_span_v1.json"
)
OUTPUT_DIR = Path("derived/pps_cumulative_snapshot_span_v1")
OUTPUT_NAME = "span_estimates_v1.json"
METHOD_ID = "PPS_CUMULATIVE_SNAPSHOT_SPAN_V1"
TOOL_VERSION = "pps_cumulative_snapshot_span_estimator_v1"
UINT64_MAX = (1 << 64) - 1

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
COUNT_INVALID_FLAGS = (
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
FAULT_COUNTER_KEYS = frozenset(
    {
        "association_loss_count",
        "binding_failure_count",
        "boundary_overflow_count",
        "boundary_ring_dropped_count",
        "boundary_sequence_duplicate_count",
        "boundary_sequence_gap_count",
        "count_saturated_count",
        "counter_snapshot_invalid_count",
        "dropped_count",
        "error_flags",
        "missing_pps_count",
        "physical_pps_missing_count",
        "pps_count_boundary_dropped_count",
        "pps_interval_anomaly_count",
        "rejected_window_count",
        "snapshot_continuity_loss_count",
        "snapshot_dma_error_count",
        "snapshot_dma_stopped_count",
        "snapshot_overwrite_count",
        "snapshot_pio_rxstall_count",
    }
)


@dataclass(frozen=True)
class SpanEstimatorConfig:
    schema_version: int
    method_id: str
    expected_snapshot_backend: str
    counter_direction: str
    counter_width_bits: int
    accumulator_width_bits: int
    nominal_reference_interval_s: float
    timer_domain: str
    timer_nominal_hz: float
    maximum_captured_edge_rate_hz: float
    candidate_spans_s: tuple[int, ...]
    output_modes: tuple[str, ...]
    uncertainty_policy: str
    criteria_rationale_document: str
    config_hash: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "SpanEstimatorConfig":
        expected = {
            "schema_version",
            "method_id",
            "expected_snapshot_backend",
            "counter_direction",
            "counter_width_bits",
            "accumulator_width_bits",
            "nominal_reference_interval_s",
            "timer_domain",
            "timer_nominal_hz",
            "maximum_captured_edge_rate_hz",
            "candidate_spans_s",
            "output_modes",
            "uncertainty_policy",
            "criteria_rationale_document",
        }
        if set(value) != expected:
            raise ValueError(
                "span estimator config fields differ; "
                f"missing={sorted(expected - set(value))}, "
                f"extra={sorted(set(value) - expected)}"
            )
        if value["schema_version"] != 1 or value["method_id"] != METHOD_ID:
            raise ValueError("unsupported span estimator method/config version")
        if value["counter_direction"] != "down" or value["counter_width_bits"] != 32:
            raise ValueError("v1 requires a wrapping 32-bit down-counter")
        accumulator_width = int(value["accumulator_width_bits"])
        if accumulator_width < 64:
            raise ValueError("accumulator_width_bits must be at least 64")
        nominal = float(value["nominal_reference_interval_s"])
        timer_hz = float(value["timer_nominal_hz"])
        max_rate = float(value["maximum_captured_edge_rate_hz"])
        if not all(math.isfinite(item) and item > 0 for item in (nominal, timer_hz, max_rate)):
            raise ValueError("nominal interval, timer rate, and captured edge rate must be positive")
        if max_rate * nominal >= 1 << 32:
            raise ValueError("adjacent interval can contain an ambiguous full counter wrap")
        domain = time_domain(str(value["timer_domain"]))
        if timer_hz != domain.nominal_hz:
            raise ValueError(
                f"timer_nominal_hz={timer_hz} contradicts "
                f"{domain.name} nominal_hz={domain.nominal_hz}"
            )
        spans = tuple(int(item) for item in value["candidate_spans_s"])
        if not spans or len(set(spans)) != len(spans) or any(item <= 0 for item in spans):
            raise ValueError("candidate_spans_s must be unique positive integers")
        for span_s in spans:
            interval_count = span_s / nominal
            if not interval_count.is_integer():
                raise ValueError("every candidate span must contain an integer nominal interval count")
        modes = tuple(str(item) for item in value["output_modes"])
        if not modes or len(set(modes)) != len(modes) or set(modes) - {
            "non_overlapping",
            "overlapping",
        }:
            raise ValueError("unsupported or duplicate output mode")
        if value["uncertainty_policy"] != "unknown_components_unavailable":
            raise ValueError("v1 uncertainty policy must fail unavailable")
        rationale = str(value["criteria_rationale_document"])
        if not rationale:
            raise ValueError("criteria_rationale_document must be non-empty")
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
        return cls(
            schema_version=1,
            method_id=METHOD_ID,
            expected_snapshot_backend=str(value["expected_snapshot_backend"]),
            counter_direction="down",
            counter_width_bits=32,
            accumulator_width_bits=accumulator_width,
            nominal_reference_interval_s=nominal,
            timer_domain=str(value["timer_domain"]),
            timer_nominal_hz=timer_hz,
            maximum_captured_edge_rate_hz=max_rate,
            candidate_spans_s=spans,
            output_modes=modes,
            uncertainty_policy="unknown_components_unavailable",
            criteria_rationale_document=rationale,
            config_hash=sha256(canonical.encode("utf-8")).hexdigest(),
        )


@dataclass(frozen=True)
class IntervalEvidence:
    session_id: str
    opening_snapshot_sequence: int
    closing_snapshot_sequence: int
    interval_counted_edges: int
    opening_reference_event_sequence: int | None
    closing_reference_event_sequence: int | None
    opening_reference_timestamp_ticks: int
    closing_reference_timestamp_ticks: int
    cnt_sequence: int | None
    valid: bool = True
    reasons: tuple[str, ...] = ()
    control_epoch: str = "static_unknown"
    settling_excluded: bool = False

    @property
    def effective_valid(self) -> bool:
        return self.valid and not self.reasons and not self.settling_excluded


@dataclass(frozen=True)
class SpanEstimate:
    method_id: str
    config_hash: str
    mode: str
    independent_control_decision: bool
    span_seconds: int
    nominal_interval_count: int
    session_id: str
    control_epoch: str
    first_snapshot_sequence: int
    last_snapshot_sequence: int
    first_cnt_sequence: int
    last_cnt_sequence: int
    first_reference_event_sequence: int | None
    last_reference_event_sequence: int | None
    total_contiguous_counted_edges: int
    accumulator_width_bits: int
    count_increment_hz: float
    authoritative_frequency_hz: float
    diagnostic_timer_elapsed_s: float | None
    diagnostic_timer_normalized_frequency_hz: float | None
    uncertainty_status: str
    uncertainty_reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class RunInputs:
    intervals: tuple[IntervalEvidence, ...]
    source_paths: dict[str, Path]
    source_hashes: dict[str, str]
    global_reason_codes: tuple[str, ...]
    raw_snapshot_count: int
    valid_adjacent_interval_count: int
    invalid_interval_count: int


def load_config(path: Path = DEFAULT_CONFIG) -> SpanEstimatorConfig:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("span estimator config must be a JSON object")
    return SpanEstimatorConfig.from_mapping(value)


def _contiguous_segments(
    intervals: Iterable[IntervalEvidence],
) -> tuple[tuple[IntervalEvidence, ...], ...]:
    segments: list[tuple[IntervalEvidence, ...]] = []
    active: list[IntervalEvidence] = []
    for interval in intervals:
        joins = (
            interval.effective_valid
            and (
                not active
                or (
                    active[-1].session_id == interval.session_id
                    and active[-1].closing_snapshot_sequence
                    == interval.opening_snapshot_sequence
                    and active[-1].closing_reference_event_sequence
                    == interval.opening_reference_event_sequence
                    and active[-1].control_epoch == interval.control_epoch
                )
            )
        )
        if not joins:
            if active:
                segments.append(tuple(active))
            active = []
        if interval.effective_valid:
            active.append(interval)
    if active:
        segments.append(tuple(active))
    return tuple(segments)


def estimate_spans(
    intervals: Iterable[IntervalEvidence], config: SpanEstimatorConfig
) -> tuple[SpanEstimate, ...]:
    estimates: list[SpanEstimate] = []
    segments = _contiguous_segments(intervals)
    for mode in config.output_modes:
        for span_s in config.candidate_spans_s:
            required = int(round(span_s / config.nominal_reference_interval_s))
            for segment in segments:
                starts = (
                    range(0, len(segment) - required + 1, required)
                    if mode == "non_overlapping"
                    else range(0, len(segment) - required + 1)
                )
                for start in starts:
                    selected = segment[start : start + required]
                    total = sum(item.interval_counted_edges for item in selected)
                    if total < 0 or total > min(UINT64_MAX, (1 << config.accumulator_width_bits) - 1):
                        raise OverflowError("span count exceeds configured accumulator width")
                    timer_ticks = sum(
                        _timer_interval_ticks(
                            item.opening_reference_timestamp_ticks,
                            item.closing_reference_timestamp_ticks,
                            domain=config.timer_domain,
                        )
                        for item in selected
                    )
                    timer_elapsed = timer_ticks / config.timer_nominal_hz if timer_ticks > 0 else None
                    estimates.append(
                        SpanEstimate(
                            method_id=config.method_id,
                            config_hash=config.config_hash,
                            mode=mode,
                            independent_control_decision=mode == "non_overlapping",
                            span_seconds=span_s,
                            nominal_interval_count=required,
                            session_id=selected[0].session_id,
                            control_epoch=selected[0].control_epoch,
                            first_snapshot_sequence=selected[0].opening_snapshot_sequence,
                            last_snapshot_sequence=selected[-1].closing_snapshot_sequence,
                            first_cnt_sequence=int(selected[0].cnt_sequence),
                            last_cnt_sequence=int(selected[-1].cnt_sequence),
                            first_reference_event_sequence=selected[0].opening_reference_event_sequence,
                            last_reference_event_sequence=selected[-1].closing_reference_event_sequence,
                            total_contiguous_counted_edges=total,
                            accumulator_width_bits=config.accumulator_width_bits,
                            count_increment_hz=1.0 / (required * config.nominal_reference_interval_s),
                            authoritative_frequency_hz=total
                            / (required * config.nominal_reference_interval_s),
                            diagnostic_timer_elapsed_s=timer_elapsed,
                            diagnostic_timer_normalized_frequency_hz=(
                                total / timer_elapsed if timer_elapsed else None
                            ),
                            uncertainty_status="unavailable",
                            uncertainty_reason_codes=(
                                "counter_aperture_uncertainty_unavailable",
                                "reference_uncertainty_unavailable",
                                "calibration_uncertainty_unavailable",
                            ),
                        )
                    )
    return tuple(estimates)


def _timer_interval_ticks(opening: int, closing: int, *, domain: str) -> int:
    progress = forward_progress(opening, closing, domain=domain, allow_equal=False)
    return int(progress.distance_ticks or 0) if progress.valid else 0


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _contract_path(manifest: Any, contract: str) -> Path:
    matches = [
        manifest.root / str(item["path"])
        for item in manifest.files
        if item.get("contract") == contract
    ]
    if len(matches) != 1:
        raise ValueError(
            f"{manifest.run_id}: expected exactly one {contract} source, got {len(matches)}"
        )
    return matches[0]


def _validate_source(path: Path, contract: str, manifest: Any) -> None:
    result = validate_csv(
        path,
        CsvValidationContext(
            contract=contract,
            known_channels=manifest.known_channels,
            known_domains=manifest.known_domains,
            template=manifest.is_template,
        ),
    )
    if result.errors:
        raise ValueError(f"{path}: " + "; ".join(result.errors))
    if result.row_count == 0:
        raise ValueError(f"{path}: required estimator source is empty")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _health_global_reasons(path: Path) -> tuple[str, ...]:
    reasons: set[str] = set()
    for row in _read_rows(path):
        key = row["status_key"]
        value = row["status_value"].strip()
        if key in FAULT_COUNTER_KEYS:
            try:
                if int(value, 0) != 0:
                    reasons.add(f"health_{key}_nonzero")
            except ValueError:
                reasons.add(f"health_{key}_malformed")
        if key in {"actuation_authorized", "actionable"} and value.lower() == "true":
            reasons.add(f"unsafe_{key}_true")
    return tuple(sorted(reasons))


def _transport_global_reasons(path: Path) -> tuple[str, ...]:
    if not path.exists():
        return ()
    reasons: set[str] = set()
    boot_rows = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("BOOT,"):
                boot_rows += 1
            prefix = "# OTIS_HOST "
            if not line.startswith(prefix):
                continue
            try:
                marker = json.loads(line[len(prefix) :])
            except json.JSONDecodeError:
                reasons.add("host_marker_malformed")
                continue
            if marker.get("event") != "capture_stopped":
                continue
            for key in (
                "commands_rejected",
                "malformed_utf8",
                "parser_errors",
                "reconnect_count",
            ):
                try:
                    if int(marker.get(key, 0)) != 0:
                        reasons.add(f"transport_{key}_nonzero")
                except (TypeError, ValueError):
                    reasons.add(f"transport_{key}_malformed")
    if boot_rows > 1:
        reasons.add("reset_during_capture")
    return tuple(sorted(reasons))


def _load_interval_policy(path: Path | None) -> dict[int, tuple[str, bool]]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if set(value) != {"schema_version", "ranges"} or value["schema_version"] != 1:
        raise ValueError("interval policy must contain schema_version=1 and ranges")
    output: dict[int, tuple[str, bool]] = {}
    for item in value["ranges"]:
        expected = {
            "first_closing_snapshot_sequence",
            "last_closing_snapshot_sequence",
            "control_epoch",
            "settling_excluded",
        }
        if set(item) != expected:
            raise ValueError("interval policy range fields differ")
        first = int(item["first_closing_snapshot_sequence"])
        last = int(item["last_closing_snapshot_sequence"])
        epoch = str(item["control_epoch"])
        if first > last or not epoch:
            raise ValueError("invalid interval policy range")
        for sequence in range(first, last + 1):
            if sequence in output:
                raise ValueError("overlapping interval policy ranges")
            output[sequence] = (epoch, bool(item["settling_excluded"]))
    return output


def load_run_inputs(
    run_dir: Path,
    config: SpanEstimatorConfig,
    *,
    interval_policy_path: Path | None = None,
) -> RunInputs:
    manifest = load_manifest(run_dir)
    paths = {
        "manifest": manifest.path,
        "snapshots": _contract_path(manifest, "pps_snapshots_v1"),
        "counts": _contract_path(manifest, "count_observations_v1"),
        "references": _contract_path(manifest, "raw_events_v1"),
        "health": _contract_path(manifest, "health_v1"),
    }
    for name, contract in (
        ("snapshots", "pps_snapshots_v1"),
        ("counts", "count_observations_v1"),
        ("references", "raw_events_v1"),
        ("health", "health_v1"),
    ):
        _validate_source(paths[name], contract, manifest)
    raw_log = run_dir / "raw" / "serial.log"
    if raw_log.exists():
        paths["raw_log"] = raw_log
    source_hashes = {name: _sha256_file(path) for name, path in paths.items()}

    snapshot_rows = _read_rows(paths["snapshots"])
    snapshots = tuple(
        SnapshotObservation(
            sequence=int(row["snapshot_sequence"]),
            session_id=row["session"],
            raw_counter_value=int(row["cumulative_down_counter"]),
            reference_timestamp_ticks=int(row["reference_timestamp_ticks"]),
            reference_sequence=int(row["reference_sequence"]),
            capture_valid=(
                int(row["status"]) == 0
                and row["backend"] == config.expected_snapshot_backend
            ),
            capture_faults=tuple(
                reason
                for reason, active in (
                    ("snapshot_status_nonzero", int(row["status"]) != 0),
                    (
                        "snapshot_backend_mismatch",
                        row["backend"] != config.expected_snapshot_backend,
                    ),
                )
                if active
            ),
        )
        for row in snapshot_rows
    )
    reconstructed = reconstruct_snapshots(
        snapshots,
        ReconstructionPolicy(
            max_oscillator_hz=config.maximum_captured_edge_rate_hz,
            timestamp_ticks_per_second=config.timer_nominal_hz,
            timestamp_domain=config.timer_domain,
        ),
    )

    count_rows_by_sequence: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in _read_rows(paths["counts"]):
        count_rows_by_sequence[int(row["count_seq"])].append(row)
    reference_rows = [
        row
        for row in _read_rows(paths["references"])
        if row["record_type"] == "REF"
        and row["edge"] == "R"
        and int(row["channel_id"]) == 1
    ]
    refs_by_timestamp: dict[int, list[tuple[int, dict[str, str]]]] = defaultdict(list)
    for index, row in enumerate(reference_rows):
        refs_by_timestamp[int(row["timestamp_ticks"])].append((index, row))
    snapshots_by_key = {(item.session_id, item.sequence): item for item in snapshots}
    interval_policy = _load_interval_policy(interval_policy_path)

    has_dac_evidence = any(
        item.get("contract") == "dac_steps_v1"
        and (manifest.root / str(item["path"])).exists()
        and len(_read_rows(manifest.root / str(item["path"]))) > 0
        for item in manifest.files
    )
    global_reasons = set(_health_global_reasons(paths["health"]))
    if "raw_log" in paths:
        global_reasons.update(_transport_global_reasons(paths["raw_log"]))
    if has_dac_evidence and not interval_policy:
        global_reasons.add("dac_transition_policy_unavailable")

    intervals: list[IntervalEvidence] = []
    for result in reconstructed:
        if result.anchor_only:
            continue
        opening = (
            snapshots_by_key.get((result.session_id, result.opening_sequence))
            if result.opening_sequence is not None
            else None
        )
        closing = snapshots_by_key.get((result.session_id, result.closing_sequence))
        reasons = list(result.reasons)
        counted_edges = int(result.interval_count or 0)
        cnt_sequence: int | None = None
        opening_ref_sequence: int | None = None
        closing_ref_sequence: int | None = None
        if opening is None or closing is None:
            reasons.append("snapshot_endpoint_unavailable")
        else:
            opening_matches = refs_by_timestamp.get(opening.reference_timestamp_ticks, [])
            closing_matches = refs_by_timestamp.get(closing.reference_timestamp_ticks, [])
            if len(opening_matches) != 1:
                reasons.append(
                    "reference_missing" if not opening_matches else "reference_duplicate"
                )
            if len(closing_matches) != 1:
                reasons.append(
                    "reference_missing" if not closing_matches else "reference_duplicate"
                )
            if len(opening_matches) == 1 and len(closing_matches) == 1:
                opening_index, opening_ref = opening_matches[0]
                closing_index, closing_ref = closing_matches[0]
                opening_ref_sequence = int(opening_ref["event_seq"])
                closing_ref_sequence = int(closing_ref["event_seq"])
                if closing_index != opening_index + 1:
                    reasons.append("reference_not_adjacent")
                if (
                    int(opening_ref["flags"]) & REFERENCE_INVALID_FLAGS
                    or int(closing_ref["flags"]) & REFERENCE_INVALID_FLAGS
                ):
                    reasons.append("reference_flagged_invalid")
            count_matches = count_rows_by_sequence.get(result.closing_sequence, [])
            if len(count_matches) != 1:
                reasons.append("cnt_missing" if not count_matches else "cnt_duplicate")
            else:
                count = count_matches[0]
                cnt_sequence = int(count["count_seq"])
                if int(count["counted_edges"]) != counted_edges:
                    reasons.append("cnt_arithmetic_mismatch")
                if (
                    int(count["gate_open_ticks"])
                    != opening.reference_timestamp_ticks
                    or int(count["gate_close_ticks"])
                    != closing.reference_timestamp_ticks
                ):
                    reasons.append("cnt_boundary_mismatch")
                if int(count["flags"]) & COUNT_INVALID_FLAGS:
                    reasons.append("cnt_flagged_invalid")
        epoch, settling = interval_policy.get(
            result.closing_sequence,
            (
                ("uncovered", True)
                if has_dac_evidence
                else ("static_unknown", False)
            ),
        )
        all_reasons = tuple(dict.fromkeys([*reasons, *sorted(global_reasons)]))
        intervals.append(
            IntervalEvidence(
                session_id=result.session_id,
                opening_snapshot_sequence=(
                    opening.sequence if opening is not None else result.closing_sequence
                ),
                closing_snapshot_sequence=result.closing_sequence,
                interval_counted_edges=counted_edges,
                opening_reference_event_sequence=opening_ref_sequence,
                closing_reference_event_sequence=closing_ref_sequence,
                opening_reference_timestamp_ticks=(
                    opening.reference_timestamp_ticks if opening is not None else 0
                ),
                closing_reference_timestamp_ticks=(
                    closing.reference_timestamp_ticks if closing is not None else 0
                ),
                cnt_sequence=cnt_sequence,
                valid=result.valid and not all_reasons,
                reasons=all_reasons,
                control_epoch=epoch,
                settling_excluded=settling,
            )
        )
    after_hashes = {name: _sha256_file(path) for name, path in paths.items()}
    if after_hashes != source_hashes:
        raise RuntimeError("source evidence changed during span reconstruction")
    valid_count = sum(item.effective_valid for item in intervals)
    return RunInputs(
        intervals=tuple(intervals),
        source_paths=paths,
        source_hashes=source_hashes,
        global_reason_codes=tuple(sorted(global_reasons)),
        raw_snapshot_count=len(snapshots),
        valid_adjacent_interval_count=valid_count,
        invalid_interval_count=len(intervals) - valid_count,
    )


def _summary(estimates: tuple[SpanEstimate, ...]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[SpanEstimate]] = defaultdict(list)
    for estimate in estimates:
        grouped[(estimate.mode, estimate.span_seconds)].append(estimate)
    output: list[dict[str, Any]] = []
    for (mode, span_s), items in grouped.items():
        frequencies = [item.authoritative_frequency_hz for item in items]
        output.append(
            {
                "mode": mode,
                "span_seconds": span_s,
                "estimate_count": len(items),
                "independent_control_decisions": mode == "non_overlapping",
                "count_increment_hz": items[0].count_increment_hz,
                "mean_authoritative_frequency_hz": statistics.fmean(frequencies),
                "population_stddev_hz": (
                    statistics.pstdev(frequencies) if len(frequencies) > 1 else 0.0
                ),
                "minimum_authoritative_frequency_hz": min(frequencies),
                "maximum_authoritative_frequency_hz": max(frequencies),
            }
        )
    return output


def analyze_run(
    run_dir: Path,
    *,
    config_path: Path = DEFAULT_CONFIG,
    interval_policy_path: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    config = load_config(config_path)
    inputs = load_run_inputs(
        run_dir,
        config,
        interval_policy_path=interval_policy_path,
    )
    estimates = estimate_spans(inputs.intervals, config)
    invalid_reasons = Counter(
        reason
        for interval in inputs.intervals
        if not interval.effective_valid
        for reason in interval.reasons
    )
    destination = output_path or run_dir / OUTPUT_DIR / OUTPUT_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1,
        "method_id": config.method_id,
        "tool_version": TOOL_VERSION,
        "config_path": str(config_path),
        "config_hash": config.config_hash,
        "run_id": load_manifest(run_dir).run_id,
        "source_evidence": {
            name: {
                "path": str(path),
                "sha256": inputs.source_hashes[name],
            }
            for name, path in inputs.source_paths.items()
        },
        "source_immutability_verified": True,
        "raw_snapshot_count": inputs.raw_snapshot_count,
        "valid_adjacent_interval_count": inputs.valid_adjacent_interval_count,
        "invalid_interval_count": inputs.invalid_interval_count,
        "global_reason_codes": list(inputs.global_reason_codes),
        "invalid_reason_counts": dict(sorted(invalid_reasons.items())),
        "authoritative_denominator": (
            "nominal accepted PPS interval count; timer normalization diagnostic-only"
        ),
        "uncertainty_status": "unavailable",
        "uncertainty_reason_codes": [
            "counter_aperture_uncertainty_unavailable",
            "reference_uncertainty_unavailable",
            "calibration_uncertainty_unavailable",
        ],
        "summary": _summary(estimates),
        "estimates": [asdict(item) for item in estimates],
    }
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(destination)
    final_hashes = {
        name: _sha256_file(path) for name, path in inputs.source_paths.items()
    }
    if final_hashes != inputs.source_hashes:
        destination.unlink(missing_ok=True)
        raise RuntimeError("source evidence changed while writing span report")
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reconstruct continuity-aware cumulative PPS snapshot spans with "
            "a nominal authoritative denominator and diagnostic-only timer normalization."
        )
    )
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--interval-policy", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        destination = analyze_run(
            args.run_dir,
            config_path=args.config,
            interval_policy_path=args.interval_policy,
            output_path=args.output,
        )
    except (
        FileNotFoundError,
        ValueError,
        OverflowError,
        RuntimeError,
        json.JSONDecodeError,
    ) as exc:
        parser.error(str(exc))
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
