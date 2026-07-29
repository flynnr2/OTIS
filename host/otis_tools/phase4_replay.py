from __future__ import annotations

from collections import Counter, deque
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable
import argparse
import csv
import hashlib
import io
import json
import math
import statistics

from .contracts import (
    CONTROL_PREVIEW_V1_FIELDS,
    ESTIMATE_V1_FIELDS,
    CsvValidationContext,
    validate_csv,
)
from .plant_model import PlantModel, load_plant_model
from .run_loader import RunManifest, load_manifest
from .timebase import unwrap_ticks


ESTIMATOR_VERSION = "phase4_frequency_mean_v1"
POLICY_VERSION = "phase4_observe_preview_v1"
OUTPUT_SUBDIRECTORY = Path("derived") / "phase4_replay_v1"
ESTIMATES_FILENAME = "estimates_v1.csv"
PREVIEWS_FILENAME = "control_previews_v1.csv"
REPORT_FILENAME = "replay_report_v1.json"

REFERENCE_INVALID_FLAGS = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 5) | (1 << 12)
COUNT_INVALID_FLAGS = (
    (1 << 0)
    | (1 << 1)
    | (1 << 2)
    | (1 << 3)
    | (1 << 5)
    | (1 << 8)
    | (1 << 9)
    | (1 << 10)
    | (1 << 12)
    | (1 << 13)
)


@dataclass(frozen=True)
class ReplayConfig:
    schema_version: int = 1
    startup_inhibit_s: float = 600.0
    clean_window_requirement: int = 3
    recovery_clean_window_requirement: int = 3
    estimator_window: int = 5
    minimum_estimator_samples: int = 3
    reference_nominal_interval_s: float = 1.0
    reference_interval_tolerance_s: float = 0.2
    reference_max_age_s: float = 1.5
    count_max_age_s: float = 450.0
    maximum_dispersion_hz: float = 0.25
    drift_estimation_enabled: bool = False

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "ReplayConfig":
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown replay configuration fields: {', '.join(unknown)}")
        config = cls(**value)
        config.validate()
        return config

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError("replay configuration schema_version must be 1")
        if self.drift_estimation_enabled:
            raise ValueError("drift_estimation_enabled must remain false in Phase 4")
        for field_name in (
            "startup_inhibit_s",
            "reference_nominal_interval_s",
            "reference_interval_tolerance_s",
            "reference_max_age_s",
            "count_max_age_s",
            "maximum_dispersion_hz",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{field_name} must be a finite non-negative number")
        for field_name in (
            "clean_window_requirement",
            "recovery_clean_window_requirement",
            "estimator_window",
            "minimum_estimator_samples",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.minimum_estimator_samples > self.estimator_window:
            raise ValueError("minimum_estimator_samples must not exceed estimator_window")

    @property
    def canonical_bytes(self) -> bytes:
        return (_canonical_json(asdict(self)) + "\n").encode("utf-8")

    @property
    def config_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()


@dataclass(frozen=True)
class SourceFiles:
    reference: Path
    reference_ref: str
    count: Path
    count_ref: str
    status: Path | None
    status_ref: str
    dac: Path | None
    dac_ref: str


@dataclass(frozen=True)
class ReferenceRecord:
    seq: int
    ticks: int
    domain: str
    flags: int


@dataclass(frozen=True)
class CountRecord:
    seq: int
    open_ticks: int
    close_ticks: int
    domain: str
    counted_edges: int
    flags: int


@dataclass(frozen=True)
class StatusRecord:
    seq: int
    ticks: int
    domain: str
    component: str
    key: str
    value: str
    severity: str
    flags: int


@dataclass(frozen=True)
class DacRecord:
    seq: int
    ticks: int
    requested_code: int
    applied_code: int
    clamped: bool
    event: str


@dataclass(frozen=True)
class PlantContext:
    requested_ref: str
    model: PlantModel | None
    digest: str | None
    load_state: str
    load_reason: str

    @property
    def record_ref(self) -> str:
        if self.model is not None and self.digest is not None:
            return (
                f"plant_model:{self.model.model_id}:v{self.model.model_version}"
                f"#sha256:{self.digest}"
            )
        return f"{self.load_state}:{self.requested_ref}"


@dataclass(frozen=True)
class ReplayResult:
    output_dir: Path
    estimates_path: Path
    previews_path: Path
    report_path: Path
    estimate_count: int
    preview_count: int
    source_hashes: dict[str, str]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_inventory(run_dir: Path) -> dict[str, str]:
    inventory: dict[str, str] = {}
    for path in sorted(run_dir.rglob("*")):
        relative = path.relative_to(run_dir)
        if not path.is_file() or (relative.parts and relative.parts[0] == "derived"):
            continue
        inventory[relative.as_posix()] = _sha256_path(path)
    return inventory


def _manifest_ref(manifest: RunManifest) -> str:
    return f"{manifest.path.name}#sha256:{_sha256_path(manifest.path)}"


def _find_source_files(manifest: RunManifest) -> SourceFiles:
    by_contract: dict[str, tuple[Path, str]] = {}
    resolved_root = manifest.root.resolve()
    for entry in manifest.files:
        contract = str(entry.get("contract", ""))
        relative = str(entry.get("path", ""))
        if contract and relative and contract not in by_contract:
            source_path = (manifest.root / relative).resolve()
            try:
                source_relative = source_path.relative_to(resolved_root)
            except ValueError as exc:
                raise ValueError(
                    f"manifest source escapes the supplied run directory: {relative}"
                ) from exc
            if source_relative.parts and source_relative.parts[0] == "derived":
                raise ValueError(
                    f"canonical replay source must not come from derived/: {relative}"
                )
            by_contract[contract] = (source_path, relative)

    if "raw_events_v1" not in by_contract:
        raise ValueError("manifest does not declare a raw_events_v1 source for canonical REF records")
    if "count_observations_v1" not in by_contract:
        raise ValueError("manifest does not declare a count_observations_v1 source")

    reference, reference_ref = by_contract["raw_events_v1"]
    count, count_ref = by_contract["count_observations_v1"]
    status_entry = by_contract.get("health_v1")
    dac_entry = by_contract.get("dac_steps_v1")
    return SourceFiles(
        reference=reference,
        reference_ref=reference_ref,
        count=count,
        count_ref=count_ref,
        status=status_entry[0] if status_entry else None,
        status_ref=status_entry[1] if status_entry else "unavailable:health_v1",
        dac=dac_entry[0] if dac_entry else None,
        dac_ref=dac_entry[1] if dac_entry else "unavailable:dac_steps_v1",
    )


def _validate_input_csv(path: Path, contract: str, manifest: RunManifest) -> None:
    result = validate_csv(
        path,
        CsvValidationContext(
            contract=contract,
            known_channels=manifest.known_channels,
            known_domains=manifest.known_domains,
            allow_rp2040_timer0_wrap=manifest.h_phase == "H1",
        ),
    )
    if result.errors:
        detail = "; ".join(result.errors[:8])
        if len(result.errors) > 8:
            detail += f"; ... {len(result.errors) - 8} more"
        raise ValueError(f"{path}: source contract validation failed: {detail}")


def _read_dict_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _load_references(path: Path) -> list[ReferenceRecord]:
    rows = []
    for row in _read_dict_rows(path):
        if row["record_type"] != "REF" or row["edge"] not in {"R", "B"}:
            continue
        rows.append(
            ReferenceRecord(
                seq=int(row["event_seq"]),
                ticks=int(row["timestamp_ticks"]),
                domain=row["capture_domain"],
                flags=int(row["flags"]),
            )
        )
    return rows


def _load_counts(path: Path) -> list[CountRecord]:
    return [
        CountRecord(
            seq=int(row["count_seq"]),
            open_ticks=int(row["gate_open_ticks"]),
            close_ticks=int(row["gate_close_ticks"]),
            domain=row["gate_domain"],
            counted_edges=int(row["counted_edges"]),
            flags=int(row["flags"]),
        )
        for row in _read_dict_rows(path)
    ]


def _load_status(path: Path | None) -> list[StatusRecord]:
    if path is None or not path.exists():
        return []
    return [
        StatusRecord(
            seq=int(row["status_seq"]),
            ticks=int(row["timestamp_ticks"]),
            domain=row["status_domain"],
            component=row["component"],
            key=row["status_key"],
            value=row["status_value"],
            severity=row["severity"],
            flags=int(row["flags"]),
        )
        for row in _read_dict_rows(path)
    ]


def _load_dac(path: Path | None, domain_hz: float) -> list[DacRecord]:
    if path is None or not path.exists():
        return []
    result: list[DacRecord] = []
    for row in _read_dict_rows(path):
        result.append(
            DacRecord(
                seq=int(row["seq"]),
                ticks=int(round(int(row["elapsed_ms"]) * domain_hz / 1000.0)),
                requested_code=int(row["dac_code_requested"]),
                applied_code=int(row["dac_code_applied"]),
                clamped=row["dac_code_clamped"] == "1",
                event=row["event"],
            )
        )
    return result


def _unwrap_sources(
    references: list[ReferenceRecord],
    counts: list[CountRecord],
    status: list[StatusRecord],
    domain: str,
) -> tuple[list[ReferenceRecord], list[CountRecord], list[StatusRecord]]:
    if domain != "rp2040_timer0":
        return references, counts, status

    reference_ticks, _ = unwrap_ticks(
        [row.ticks for row in references if row.domain == domain]
    )
    reference_tick_iter = iter(reference_ticks)
    unwrapped_references = [
        ReferenceRecord(
            row.seq,
            next(reference_tick_iter) if row.domain == domain else row.ticks,
            row.domain,
            row.flags,
        )
        for row in references
    ]

    boundary_values = [
        boundary
        for row in counts
        if row.domain == domain
        for boundary in (row.open_ticks, row.close_ticks)
    ]
    unwrapped_boundaries, _ = unwrap_ticks(boundary_values)
    boundary_iter = iter(unwrapped_boundaries)
    unwrapped_counts = [
        CountRecord(
            row.seq,
            next(boundary_iter) if row.domain == domain else row.open_ticks,
            next(boundary_iter) if row.domain == domain else row.close_ticks,
            row.domain,
            row.counted_edges,
            row.flags,
        )
        for row in counts
    ]

    status_ticks, _ = unwrap_ticks(
        [row.ticks for row in status if row.domain == domain]
    )
    status_tick_iter = iter(status_ticks)
    unwrapped_status = [
        StatusRecord(
            row.seq,
            next(status_tick_iter) if row.domain == domain else row.ticks,
            row.domain,
            row.component,
            row.key,
            row.value,
            row.severity,
            row.flags,
        )
        for row in status
    ]
    return unwrapped_references, unwrapped_counts, unwrapped_status


def _domain_hz(manifest: RunManifest, domain: str) -> float:
    for item in manifest.data.get("domains", []):
        if item.get("name") == domain and isinstance(item.get("nominal_hz"), (int, float)):
            value = float(item["nominal_hz"])
            if value > 0 and math.isfinite(value):
                return value
    raise ValueError(f"manifest domain {domain!r} has no positive nominal_hz")


def _nominal_frequency_hz(manifest: RunManifest, plant: PlantContext) -> float:
    oscillator = manifest.data.get("oscillator")
    if isinstance(oscillator, dict) and isinstance(oscillator.get("nominal_frequency_hz"), (int, float)):
        return float(oscillator["nominal_frequency_hz"])
    nominal = manifest.data.get("nominal_frequencies_hz")
    if isinstance(nominal, dict):
        for key in ("ocxo", "oscillator", "vcocxo", "tcxo"):
            if isinstance(nominal.get(key), (int, float)):
                return float(nominal[key])
    if plant.model is not None:
        return float(plant.model.data["oscillator"]["nominal_frequency_hz"])
    raise ValueError("nominal oscillator frequency is unavailable from manifest and plant model")


def _load_plant_context(path: Path | str) -> PlantContext:
    model_path = Path(path)
    requested_ref = model_path.name or str(path)
    try:
        raw = model_path.read_bytes()
    except OSError:
        return PlantContext(requested_ref, None, None, "unavailable", "plant_model_unavailable")
    digest = _sha256_bytes(raw)
    try:
        model = load_plant_model(model_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return PlantContext(requested_ref, None, digest, "invalid", "plant_model_invalid")
    return PlantContext(requested_ref, model, digest, "available", "plant_model_loaded")


def _reason_text(reasons: Iterable[str], clear_reason: str) -> str:
    ordered = list(dict.fromkeys(reasons))
    return ";".join(ordered) if ordered else clear_reason


def _format_number(value: float | int | None) -> str:
    if value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    return format(value, ".12g")


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _status_snapshot(status: list[StatusRecord], ticks: int, domain: str) -> tuple[dict[tuple[str, str], StatusRecord], str]:
    latest: dict[tuple[str, str], StatusRecord] = {}
    considered: list[StatusRecord] = []
    for record in status:
        if record.domain == domain and record.ticks <= ticks:
            latest[(record.component, record.key)] = record
            considered.append(record)
    if not considered:
        return latest, "unavailable:health_v1"
    return latest, f"health_v1:STS:{considered[-1].seq}"


def _true(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "ok", "valid"}


def _status_diagnostics(snapshot: dict[tuple[str, str], StatusRecord]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    fault = False
    for (component, key), record in snapshot.items():
        normalized = f"{component}.{key}".lower()
        if record.severity in {"ERROR", "FATAL"} and component in {
            "capture",
            "pps",
            "pps_gate",
            "fc0",
            "count",
            "reference",
        }:
            fault = True
            reasons.append("status_timing_path_fault")
        if normalized in {"fc0.fc0_fault", "count.count_fault"} and _true(record.value):
            fault = True
            reasons.append("status_count_fault")
        if normalized in {
            "capture.drop_count",
            "capture.capture_drop_count",
            "capture.parser_error_count",
            "host.dropped_record_count",
        }:
            try:
                if int(record.value, 0) > 0:
                    fault = True
                    reasons.append("status_capture_or_host_drop")
            except ValueError:
                reasons.append("status_value_unparseable")
        if normalized in {
            "pps.reference_valid",
            "reference.reference_valid_for_control",
            "pps_gate.valid",
        } and not _true(record.value):
            reasons.append("status_reference_not_valid")
    if fault:
        return "fault", reasons
    if reasons:
        return "degraded", reasons
    if snapshot:
        return "healthy", []
    return "unknown", ["diagnostic_status_unavailable"]


def _latest_dac(dac: list[DacRecord], ticks: int) -> tuple[DacRecord | None, str]:
    latest: DacRecord | None = None
    for record in dac:
        if record.ticks <= ticks and not record.clamped:
            latest = record
    if latest is None:
        return None, "unavailable:dac_steps_v1"
    return latest, f"dac_steps_v1:DAC:{latest.seq}"


def _reference_state(
    references: list[ReferenceRecord],
    ticks: int,
    domain: str,
    domain_hz: float,
    config: ReplayConfig,
    window_open_ticks: int | None,
) -> tuple[str, float | None, bool, list[str], ReferenceRecord | None, ReferenceRecord | None]:
    eligible = [row for row in references if row.domain == domain and row.ticks <= ticks]
    if not eligible:
        return "unavailable", None, False, ["reference_unavailable"], None, None
    latest = eligible[-1]
    previous = eligible[-2] if len(eligible) >= 2 else None
    age_s = (ticks - latest.ticks) / domain_hz
    reasons: list[str] = []
    continuity = previous is not None
    window_start = window_open_ticks if window_open_ticks is not None else latest.ticks
    first_window_index = 0
    for position, record in enumerate(eligible):
        if record.ticks >= window_start:
            first_window_index = max(0, position - 1)
            break
    window_records = eligible[first_window_index:]
    if any(record.flags & REFERENCE_INVALID_FLAGS for record in window_records):
        reasons.append("reference_flagged_invalid")
    if previous is None:
        reasons.append("reference_continuity_unavailable")
    else:
        for earlier, later in zip(window_records, window_records[1:]):
            interval_s = (later.ticks - earlier.ticks) / domain_hz
            if abs(interval_s - config.reference_nominal_interval_s) > config.reference_interval_tolerance_s:
                continuity = False
                reasons.append("reference_interval_outlier")
            if later.seq <= earlier.seq:
                continuity = False
                reasons.append("reference_sequence_nonmonotonic")
    if age_s > config.reference_max_age_s:
        reasons.append("reference_stale")
        return "stale", age_s, continuity, reasons, previous, latest
    if reasons:
        return "invalid", age_s, continuity, reasons, previous, latest
    return "valid", age_s, True, [], previous, latest


def _count_state(
    count: CountRecord | None,
    ticks: int,
    previous_seq: int | None,
    domain_hz: float,
    config: ReplayConfig,
) -> tuple[str, float | None, bool, list[str]]:
    if count is None:
        return "unavailable", None, False, ["count_unavailable"]
    age_s = (ticks - count.close_ticks) / domain_hz
    reasons: list[str] = []
    continuity = previous_seq is None or count.seq == previous_seq + 1
    if not continuity:
        reasons.append("count_sequence_discontinuity")
    if count.counted_edges == 0:
        reasons.append("count_zero")
    if count.flags & (1 << 13):
        reasons.append("count_saturated")
    count_quality_flags = count.flags & COUNT_INVALID_FLAGS & ~(1 << 13)
    if count.flags & (1 << 3):
        # PPS-gated CNT rows carry reference invalidity on the raw count row.
        # Preserve it on the reference side instead of collapsing a clean
        # oscillator count into count-invalid solely because the same row also
        # carries GATE_INCOMPLETE.
        count_quality_flags &= ~((1 << 3) | (1 << 12))
    if count_quality_flags:
        reasons.append("count_flagged_invalid")
    if age_s > config.count_max_age_s:
        reasons.append("count_stale")
        return "stale", age_s, continuity, reasons
    if reasons:
        return "invalid", age_s, continuity, reasons
    return "valid", age_s, continuity, []


def _frequency_observation(
    count: CountRecord,
    references: list[ReferenceRecord],
    domain_hz: float,
    config: ReplayConfig,
) -> float | None:
    gate_ticks = count.close_ticks - count.open_ticks
    if gate_ticks <= 0 or count.counted_edges <= 0:
        return None
    domain_references = [row for row in references if row.domain == count.domain]
    open_index = next(
        (index for index, row in enumerate(domain_references) if row.ticks == count.open_ticks),
        None,
    )
    close_index = next(
        (index for index, row in enumerate(domain_references) if row.ticks == count.close_ticks),
        None,
    )
    if (
        open_index is not None
        and close_index is not None
        and close_index > open_index
    ):
        gate_reference_time_s = (
            close_index - open_index
        ) * config.reference_nominal_interval_s
        if gate_reference_time_s > 0:
            return count.counted_edges / gate_reference_time_s

    eligible = [row for row in domain_references if row.ticks <= count.close_ticks]
    if len(eligible) >= 2:
        reference_ticks = eligible[-1].ticks - eligible[-2].ticks
        if reference_ticks > 0:
            calibrated_tick_rate_hz = reference_ticks / config.reference_nominal_interval_s
            return count.counted_edges / (gate_ticks / calibrated_tick_rate_hz)
    return count.counted_edges / (gate_ticks / domain_hz)


def _model_applicability(
    plant: PlantContext,
    manifest: RunManifest,
    count: CountRecord | None,
    dac: DacRecord | None,
) -> tuple[str, list[str], float | None]:
    if plant.model is None:
        return plant.load_state, [plant.load_reason], None
    model = plant.model
    reasons: list[str] = []
    if model.model_version != 3:
        reasons.append("plant_model_version_not_3")

    replay_identity = manifest.data.get("phase4_replay")
    if not isinstance(replay_identity, dict):
        reasons.append("plant_model_input_identity_unavailable")
    else:
        topology = replay_identity.get("hardware_topology_id")
        backend = replay_identity.get("measurement_backend")
        expected_topology = model.data["hardware_topology"]["topology_id"]
        expected_backend = model.data["plant_response"]["applicability"]["measurement_backend"]
        if topology != expected_topology:
            reasons.append("plant_model_topology_mismatch")
        if backend != expected_backend:
            reasons.append("plant_model_backend_mismatch")

    applicability_range = model.applicability_range
    if dac is None:
        reasons.append("dac_state_unavailable")
    elif applicability_range is None:
        reasons.append("plant_model_applicability_unavailable")
    elif not applicability_range[0] <= dac.applied_code <= applicability_range[1]:
        reasons.append("input_outside_model_applicability")

    excluded = set(model.data["plant_response"]["applicability"].get("excluded_count_sequences", []))
    source_run_ids = model.data.get("source_evidence", {}).get(
        "source_run_ids", []
    )
    source_identity: object = manifest.run_id
    if isinstance(replay_identity, dict):
        source_identity = replay_identity.get(
            "source_evidence_run_id", manifest.run_id
        )
    source_identity_text = str(source_identity)
    replaying_model_source = any(
        source_identity_text == str(source_run_id)
        or str(source_run_id).endswith(f"/{source_identity_text}")
        or source_identity_text.endswith(f"/{source_run_id}")
        for source_run_id in source_run_ids
    )
    if count is not None and replaying_model_source and count.seq in excluded:
        reasons.append("plant_model_excluded_count_sequence")

    slope = model.data["plant_response"]["local_slope"].get("hz_per_code")
    if not isinstance(slope, (int, float)) or not math.isfinite(float(slope)) or float(slope) == 0:
        reasons.append("plant_model_unknown_gain")
        slope_value = None
    else:
        slope_value = float(slope)
    if reasons:
        return "not_applicable", reasons, slope_value
    return "applicable", [], slope_value


def _next_state(
    previous_state: str,
    elapsed_s: float,
    observation_valid: bool,
    reference_validity: str,
    count_validity: str,
    confidence: str,
    clean_windows: int,
    recovery_windows: int,
    config: ReplayConfig,
    fault_latched: bool,
) -> tuple[str, str, bool]:
    if fault_latched:
        return "FAULT", "fault_latched", True
    if elapsed_s < config.startup_inhibit_s:
        return "WARMUP_INHIBIT", "startup_inhibit_active", False

    qualified_states = {
        "ACQUIRE_PREVIEW",
        "SETTLE_PREVIEW",
        "LOCKED_PREVIEW",
        "HOLDOVER_PREVIEW",
        "RECOVER_PREVIEW",
    }
    was_qualified = previous_state in qualified_states
    if was_qualified and count_validity in {"invalid", "stale", "unavailable"}:
        return "FAULT", "post_qualification_measurement_fault", True
    if was_qualified and reference_validity != "valid":
        return "HOLDOVER_PREVIEW", "reference_not_eligible_holdover", False
    if previous_state == "HOLDOVER_PREVIEW" and observation_valid:
        return "RECOVER_PREVIEW", "reference_return_requalification", False
    if previous_state == "RECOVER_PREVIEW":
        if not observation_valid:
            return "HOLDOVER_PREVIEW", "recovery_interrupted", False
        if recovery_windows < config.recovery_clean_window_requirement:
            return "RECOVER_PREVIEW", "recovery_clean_window_qualification", False
        return "ACQUIRE_PREVIEW", "recovery_qualified", False

    if not observation_valid:
        return "QUALIFYING", "clean_window_qualification_incomplete", False
    if clean_windows < config.clean_window_requirement or confidence != "high":
        return "QUALIFYING", "clean_window_qualification_incomplete", False
    return "ACQUIRE_PREVIEW", "startup_qualification_complete", False


def _preview(
    eligible: bool,
    error_hz: float | None,
    slope_hz_per_code: float | None,
    current_code: int | None,
    model: PlantModel | None,
) -> dict[str, Any]:
    empty = {
        "raw_delta_codes": None,
        "limited_delta_codes": None,
        "proposed_dac_code": None,
        "step_limited": False,
        "range_clamped": False,
        "preview_available": False,
    }
    if not eligible or error_hz is None or slope_hz_per_code is None or current_code is None or model is None:
        return empty

    raw_delta = -error_hz / slope_hz_per_code
    rounded = int(Decimal(str(raw_delta)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    max_step = int(model.data["dac"]["manual_preview_max_step_codes"])
    step_delta = max(-max_step, min(max_step, rounded))
    step_limited = step_delta != rounded
    stepped_code = current_code + step_delta
    range_min, range_max = model.automatic_control_range
    proposed_code = max(range_min, min(range_max, stepped_code))
    range_clamped = proposed_code != stepped_code
    return {
        "raw_delta_codes": raw_delta,
        "limited_delta_codes": proposed_code - current_code,
        "proposed_dac_code": proposed_code,
        "step_limited": step_limited,
        "range_clamped": range_clamped,
        "preview_available": True,
    }


def _csv_bytes(field_names: list[str], rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=field_names, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _write_managed_output(path: Path, content: bytes) -> None:
    if path.is_symlink():
        raise ValueError(f"refusing managed output through symlink: {path}")
    if path.exists():
        if not path.is_file():
            raise ValueError(f"managed output path is not a regular file: {path}")
        if path.read_bytes() != content:
            raise FileExistsError(
                f"refusing to replace existing non-identical derived artifact: {path}"
            )
        return
    path.write_bytes(content)


def replay_phase4(
    run_dir: Path | str,
    *,
    plant_model_path: Path | str,
    config: ReplayConfig | None = None,
) -> ReplayResult:
    root = Path(run_dir).resolve()
    config = config or ReplayConfig()
    config.validate()
    manifest = load_manifest(root)
    sources = _find_source_files(manifest)
    source_before = _source_inventory(root)

    _validate_input_csv(sources.reference, "raw_events_v1", manifest)
    _validate_input_csv(sources.count, "count_observations_v1", manifest)
    if sources.status is not None and sources.status.exists():
        _validate_input_csv(sources.status, "health_v1", manifest)
    if sources.dac is not None and sources.dac.exists():
        _validate_input_csv(sources.dac, "dac_steps_v1", manifest)

    references = _load_references(sources.reference)
    counts = _load_counts(sources.count)
    status = _load_status(sources.status)
    plant = _load_plant_context(plant_model_path)

    if counts:
        domain = counts[0].domain
    elif references:
        domain = references[0].domain
    else:
        raise ValueError("replay requires at least one REF or CNT timestamp")
    if any(row.domain != domain for row in counts):
        raise ValueError("Phase 4 v1 replay requires one count time domain")
    references, counts, status = _unwrap_sources(
        references, counts, status, domain
    )
    domain_hz = _domain_hz(manifest, domain)
    dac_rows = _load_dac(sources.dac, domain_hz)
    nominal_hz = _nominal_frequency_hz(manifest, plant)

    timeline = [row.close_ticks for row in counts]
    terminal_candidates = timeline + [row.ticks for row in references if row.domain == domain]
    terminal_candidates += [row.ticks for row in status if row.domain == domain]
    terminal_candidates += [row.ticks for row in dac_rows]
    if terminal_candidates:
        terminal = max(terminal_candidates)
        if not timeline or terminal > timeline[-1]:
            timeline.append(terminal)
    timeline = sorted(dict.fromkeys(timeline))
    if not timeline:
        raise ValueError("replay input contains no evaluation timestamp")

    rolling: deque[tuple[float, int, int]] = deque(maxlen=config.estimator_window)
    estimate_rows: list[dict[str, str]] = []
    preview_rows: list[dict[str, str]] = []
    state = "BOOT"
    fault_latched = False
    clean_windows = 0
    recovery_windows = 0
    # Startup age is measured from the earliest preserved run evidence, not
    # from the first count close. This matches live firmware startup semantics
    # for long gates and keeps early REF/STS provenance meaningful.
    first_ticks = min(terminal_candidates)
    previous_distinct_count_seq: int | None = None
    latest_count: CountRecord | None = None
    count_index = 0
    manifest_identity = _manifest_ref(manifest)

    for index, ticks in enumerate(timeline, start=1):
        new_count = False
        while count_index < len(counts) and counts[count_index].close_ticks <= ticks:
            candidate = counts[count_index]
            if latest_count is None or candidate.seq != latest_count.seq:
                latest_count = candidate
                new_count = candidate.close_ticks == ticks
            count_index += 1

        reference_validity, reference_age_s, reference_continuity, reference_reasons, first_ref, last_ref = (
            _reference_state(
                references,
                ticks,
                domain,
                domain_hz,
                config,
                latest_count.open_ticks if latest_count is not None else None,
            )
        )
        count_validity, count_age_s, count_continuity, count_reasons = _count_state(
            latest_count,
            ticks,
            previous_distinct_count_seq if new_count else None,
            domain_hz,
            config,
        )
        if (
            latest_count is not None
            and latest_count.flags & (1 << 3)
            and reference_validity not in {"unavailable", "stale"}
        ):
            reference_validity = "invalid"
            if "reference_flagged_invalid" not in reference_reasons:
                reference_reasons.append("reference_flagged_invalid")
        if new_count and latest_count is not None:
            previous_distinct_count_seq = latest_count.seq

        status_snapshot, status_ref = _status_snapshot(status, ticks, domain)
        diagnostic_health, diagnostic_reasons = _status_diagnostics(status_snapshot)
        current_dac, dac_ref = _latest_dac(dac_rows, ticks)

        observation_reasons = [*reference_reasons, *count_reasons]
        observation_valid = reference_validity == "valid" and count_validity == "valid"
        if diagnostic_health == "fault":
            observation_reasons.append("diagnostic_timing_path_fault")
            observation_valid = False
        observation_validity = "valid" if observation_valid else (
            "unavailable"
            if reference_validity == "unavailable" or count_validity == "unavailable"
            else "invalid"
        )

        observation_hz: float | None = None
        if new_count and latest_count is not None and observation_valid:
            observation_hz = _frequency_observation(
                latest_count, references, domain_hz, config
            )
            if observation_hz is not None:
                rolling.append(
                    (
                        observation_hz,
                        first_ref.seq if first_ref is not None else 0,
                        last_ref.seq if last_ref is not None else 0,
                    )
                )

        sample_values = [item[0] for item in rolling]
        estimate_hz = statistics.fmean(sample_values) if sample_values else None
        dispersion_hz = statistics.pstdev(sample_values) if len(sample_values) >= 2 else (
            0.0 if sample_values else None
        )
        estimator_reasons: list[str] = []
        if len(sample_values) < config.minimum_estimator_samples:
            estimator_reasons.append("estimator_underqualified_sample_count")
        if dispersion_hz is not None and dispersion_hz > config.maximum_dispersion_hz:
            estimator_reasons.append("estimator_dispersion_exceeded")
        if not sample_values:
            confidence = "unavailable"
        elif estimator_reasons:
            confidence = "low"
        elif not observation_valid:
            confidence = "medium"
        else:
            confidence = "high"
        frequency_error_hz = estimate_hz - nominal_hz if estimate_hz is not None else None

        elapsed_s = (ticks - first_ticks) / domain_hz
        if elapsed_s < config.startup_inhibit_s:
            clean_windows = 0
        elif new_count:
            clean_windows = clean_windows + 1 if observation_valid else 0
        if state in {"HOLDOVER_PREVIEW", "RECOVER_PREVIEW"}:
            recovery_windows = recovery_windows + 1 if new_count and observation_valid else 0
        else:
            recovery_windows = 0

        previous_state = state
        state, transition_reason, new_fault = _next_state(
            previous_state,
            elapsed_s,
            observation_valid,
            reference_validity,
            count_validity,
            confidence,
            clean_windows,
            recovery_windows,
            config,
            fault_latched,
        )
        fault_latched = fault_latched or new_fault

        estimator_eligible = (
            observation_valid
            and confidence == "high"
            and diagnostic_health == "healthy"
            and state in {"ACQUIRE_PREVIEW", "SETTLE_PREVIEW", "LOCKED_PREVIEW"}
            and not estimator_reasons
        )
        eligibility_reasons: list[str] = []
        if not estimator_eligible:
            eligibility_reasons.extend(estimator_reasons)
            if state == "WARMUP_INHIBIT":
                eligibility_reasons.append("startup_inhibit_active")
            elif state in {"QUALIFYING", "RECOVER_PREVIEW"}:
                eligibility_reasons.append("clean_window_qualification_incomplete")
            elif state == "HOLDOVER_PREVIEW":
                eligibility_reasons.append("reference_not_eligible_holdover")
            elif state == "FAULT":
                eligibility_reasons.append("post_qualification_measurement_fault")
            if diagnostic_health != "healthy":
                eligibility_reasons.append("diagnostic_health_not_healthy")
            eligibility_reasons.extend(observation_reasons)

        estimate_id = f"est:{manifest.run_id}:{index:06d}"
        count_ref = (
            f"{sources.count_ref}:CNT:{latest_count.seq}"
            if latest_count is not None
            else f"unavailable:{sources.count_ref}:CNT"
        )
        estimate_rows.append(
            {
                "record_type": "EST",
                "schema_version": "1",
                "estimate_seq": str(index),
                "estimate_id": estimate_id,
                "estimator_timestamp_ticks": str(ticks),
                "time_domain": domain,
                "source_count_seq": str(latest_count.seq) if latest_count is not None else "",
                "source_count_ref": count_ref,
                "source_reference_first_seq": str(rolling[0][1]) if rolling and rolling[0][1] else "",
                "source_reference_last_seq": str(last_ref.seq) if last_ref is not None else "",
                "source_status_refs": status_ref,
                "source_dac_ref": dac_ref,
                "manifest_ref": manifest_identity,
                "estimator_version": ESTIMATOR_VERSION,
                "config_hash": config.config_hash,
                "observation_validity": observation_validity,
                "observation_reason_codes": _reason_text(observation_reasons, "observation_valid"),
                "reference_validity": reference_validity,
                "reference_age_s": _format_number(reference_age_s),
                "reference_continuity": _bool_text(reference_continuity),
                "count_validity": count_validity,
                "count_age_s": _format_number(count_age_s),
                "count_continuity": _bool_text(count_continuity),
                "diagnostic_health": diagnostic_health,
                "diagnostic_reason_codes": _reason_text(diagnostic_reasons, "diagnostic_healthy"),
                "frequency_observation_hz": _format_number(observation_hz),
                "accepted_sample_count": str(len(sample_values)),
                "estimator_confidence": confidence,
                "frequency_estimate_hz": _format_number(estimate_hz),
                "frequency_error_hz": _format_number(frequency_error_hz),
                "frequency_uncertainty_hz": _format_number(dispersion_hz),
                "dispersion_hz": _format_number(dispersion_hz),
                "drift_enabled": "false",
                "drift_hz_per_s": "",
                "preview_eligibility": _bool_text(estimator_eligible),
                "eligibility_reason_codes": _reason_text(
                    eligibility_reasons, "estimator_preview_eligible"
                ),
            }
        )

        model_state, model_reasons, slope = _model_applicability(
            plant, manifest, latest_count, current_dac
        )
        full_reasons = list(eligibility_reasons)
        full_reasons.extend(model_reasons)
        full_eligible = estimator_eligible and model_state == "applicable" and current_dac is not None
        preview = _preview(
            full_eligible,
            frequency_error_hz,
            slope,
            current_dac.applied_code if current_dac is not None else None,
            plant.model,
        )
        decision_reason = (
            "preview_available_observe_only" if preview["preview_available"] else "preview_inhibited"
        )
        decision_reasons: list[str] = [decision_reason]
        if preview["step_limited"]:
            decision_reasons.append("preview_step_limited")
        if preview["range_clamped"]:
            decision_reasons.append("preview_range_clamped")
        decision_reasons.append("actuation_prohibited_observe_only_phase")
        transition = state != previous_state
        preview_rows.append(
            {
                "record_type": "CTL",
                "schema_version": "1",
                "control_seq": str(index),
                "decision_id": f"ctl:{manifest.run_id}:{index:06d}",
                "decision_timestamp_ticks": str(ticks),
                "time_domain": domain,
                "est_input_ref": estimate_id,
                "plant_model_ref": plant.record_ref,
                "plant_model_id": plant.model.model_id if plant.model is not None else "",
                "plant_model_version": str(plant.model.model_version) if plant.model is not None else "",
                "plant_model_hash": plant.digest or "",
                "policy_version": POLICY_VERSION,
                "config_hash": config.config_hash,
                "control_state": state,
                "previous_control_state": previous_state,
                "state_transition": _bool_text(transition),
                "transition_reason_code": transition_reason,
                "preview_eligibility": _bool_text(full_eligible),
                "eligibility_reason_codes": _reason_text(full_reasons, "preview_eligible"),
                "diagnostic_health": diagnostic_health,
                "model_applicability": model_state,
                "model_reason_codes": _reason_text(model_reasons, "plant_model_applicable"),
                "current_dac_code": str(current_dac.applied_code) if current_dac is not None else "",
                "frequency_error_hz": _format_number(frequency_error_hz),
                "hz_per_code": _format_number(slope),
                "raw_delta_codes": _format_number(preview["raw_delta_codes"]),
                "limited_delta_codes": _format_number(preview["limited_delta_codes"]),
                "proposed_dac_code": _format_number(preview["proposed_dac_code"]),
                "step_limited": _bool_text(preview["step_limited"]),
                "range_clamped": _bool_text(preview["range_clamped"]),
                "preview_available": _bool_text(preview["preview_available"]),
                "preview_only": "true",
                "actuation_authorized": "false",
                "actionable": "false",
                "decision_reason_code": _reason_text(decision_reasons, decision_reason),
            }
        )

    estimates_bytes = _csv_bytes(ESTIMATE_V1_FIELDS, estimate_rows)
    previews_bytes = _csv_bytes(CONTROL_PREVIEW_V1_FIELDS, preview_rows)

    output_dir = root / OUTPUT_SUBDIRECTORY
    derived_root = root / "derived"
    for candidate in (derived_root, output_dir):
        if candidate.is_symlink():
            raise ValueError(f"refusing derived output through symlink: {candidate}")
    output_dir.mkdir(parents=True, exist_ok=True)
    estimates_path = output_dir / ESTIMATES_FILENAME
    previews_path = output_dir / PREVIEWS_FILENAME
    report_path = output_dir / REPORT_FILENAME

    _write_managed_output(estimates_path, estimates_bytes)
    _write_managed_output(previews_path, previews_bytes)
    for path, contract in (
        (estimates_path, "estimates_v1"),
        (previews_path, "control_previews_v1"),
    ):
        validation = validate_csv(
            path,
            CsvValidationContext(
                contract=contract,
                known_channels=frozenset(),
                known_domains=manifest.known_domains,
            ),
        )
        if validation.errors:
            raise RuntimeError(
                f"generated {contract} failed validation: {'; '.join(validation.errors)}"
            )

    source_after_records = _source_inventory(root)
    if source_after_records != source_before:
        raise RuntimeError("source evidence changed during replay")

    estimate_reason_counts = Counter(
        reason
        for row in estimate_rows
        for reason in row["eligibility_reason_codes"].split(";")
        if reason
    )
    decision_reason_counts = Counter(
        reason
        for row in preview_rows
        for reason in row["decision_reason_code"].split(";")
        if reason
    )
    report = {
        "schema_version": 1,
        "record_type": "PHASE4_REPLAY_REPORT",
        "run_id": manifest.run_id,
        "phase_boundary": {
            "observe_only": True,
            "firmware_changed": False,
            "hardware_write_path_present": False,
            "control_ready": False,
            "actuation_enabled": False,
        },
        "estimator": {
            "version": ESTIMATOR_VERSION,
            "configuration_hash": config.config_hash,
            "configuration": asdict(config),
            "record_count": len(estimate_rows),
            "eligibility_reason_counts": dict(sorted(estimate_reason_counts.items())),
        },
        "policy": {
            "version": POLICY_VERSION,
            "record_count": len(preview_rows),
            "preview_available_count": sum(
                row["preview_available"] == "true" for row in preview_rows
            ),
            "actionable_count": sum(row["actionable"] == "true" for row in preview_rows),
            "decision_reason_counts": dict(sorted(decision_reason_counts.items())),
        },
        "state_transitions": [
            {
                "control_seq": int(row["control_seq"]),
                "from": row["previous_control_state"],
                "to": row["control_state"],
                "reason_code": row["transition_reason_code"],
            }
            for row in preview_rows
            if row["state_transition"] == "true"
        ],
        "plant_model": {
            "reference": plant.record_ref,
            "model_id": plant.model.model_id if plant.model is not None else None,
            "model_version": plant.model.model_version if plant.model is not None else None,
            "control_ready": plant.model.control_ready if plant.model is not None else False,
            "actuation_enabled": plant.model.actuation_enabled if plant.model is not None else False,
        },
        "source_evidence": {
            "unchanged": True,
            "files": source_before,
        },
        "derived_products": {
            ESTIMATES_FILENAME: _sha256_bytes(estimates_bytes),
            PREVIEWS_FILENAME: _sha256_bytes(previews_bytes),
        },
    }
    report_bytes = (_canonical_json(report) + "\n").encode("utf-8")
    _write_managed_output(report_path, report_bytes)

    source_after_report = _source_inventory(root)
    if source_after_report != source_before:
        raise RuntimeError("source evidence changed while writing replay report")

    return ReplayResult(
        output_dir=output_dir,
        estimates_path=estimates_path,
        previews_path=previews_path,
        report_path=report_path,
        estimate_count=len(estimate_rows),
        preview_count=len(preview_rows),
        source_hashes=source_before,
    )


def _default_plant_model_path() -> Path:
    return Path(__file__).resolve().parents[2] / "profiles" / "plant_models" / "cx317_h1_bench_v2.json"


def _default_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "profiles" / "discipline" / "phase4_host_replay_v1.json"


def _load_config(path: Path | None) -> ReplayConfig:
    if path is None:
        config = ReplayConfig()
        config.validate()
        return config
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("replay configuration must be a JSON object")
    return ReplayConfig.from_mapping(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay Phase 4 estimates and observe-only correction previews."
    )
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--plant-model", type=Path, default=_default_plant_model_path())
    parser.add_argument("--config", type=Path, default=_default_config_path())
    args = parser.parse_args(argv)

    try:
        result = replay_phase4(
            args.run_dir,
            plant_model_path=args.plant_model,
            config=_load_config(args.config),
        )
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        return 1

    print(
        f"OK {result.output_dir}: {result.estimate_count} EST, "
        f"{result.preview_count} CTL; source evidence unchanged"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
