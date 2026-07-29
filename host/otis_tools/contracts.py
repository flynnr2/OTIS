from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import math

from .timebase import RP2040_TIMER0_MICROS_WRAP_TICKS


RAW_EVENT_FIELDS = [
    "record_type",
    "schema_version",
    "event_seq",
    "channel_id",
    "edge",
    "timestamp_ticks",
    "capture_domain",
    "flags",
]

COUNT_OBSERVATION_FIELDS = [
    "record_type",
    "schema_version",
    "count_seq",
    "channel_id",
    "gate_open_ticks",
    "gate_close_ticks",
    "gate_domain",
    "counted_edges",
    "source_edge",
    "source_domain",
    "flags",
]

HEALTH_FIELDS = [
    "record_type",
    "schema_version",
    "status_seq",
    "timestamp_ticks",
    "status_domain",
    "component",
    "status_key",
    "status_value",
    "severity",
    "flags",
]

DAC_STEP_FIELDS = [
    "record_type",
    "schema_version",
    "seq",
    "elapsed_ms",
    "step_index",
    "dac_code_requested",
    "dac_code_applied",
    "dac_code_clamped",
    "dac_voltage_measured_v",
    "ocxo_tune_voltage_measured_v",
    "dwell_ms",
    "event",
    "flags",
]

ENVIRONMENT_FIELDS = [
    "record_type",
    "schema_version",
    "env_seq",
    "timestamp_ticks",
    "observation_domain",
    "source",
    "role",
    "temperature_c",
    "relative_humidity_pct",
    "pressure_pa",
    "flags",
]

DIAGNOSTICS_DRAFT_V0_FIELDS = [
    "record_type",
    "schema_version",
    "diagnostic_seq",
    "diagnostic_id",
    "subsystem",
    "severity",
    "state",
    "transition",
    "diagnostic_confidence",
    "reason_code",
    "first_seen_ticks",
    "last_seen_ticks",
    "time_domain",
    "evidence_refs",
    "algorithm_version",
    "config_version",
    "control_effect",
    "control_eligibility",
]

ESTIMATE_V1_FIELDS = [
    "record_type",
    "schema_version",
    "estimate_seq",
    "estimate_id",
    "estimator_timestamp_ticks",
    "time_domain",
    "source_count_seq",
    "source_count_ref",
    "source_reference_first_seq",
    "source_reference_last_seq",
    "source_status_refs",
    "source_dac_ref",
    "manifest_ref",
    "estimator_version",
    "config_hash",
    "observation_validity",
    "observation_reason_codes",
    "reference_validity",
    "reference_age_s",
    "reference_continuity",
    "count_validity",
    "count_age_s",
    "count_continuity",
    "diagnostic_health",
    "diagnostic_reason_codes",
    "frequency_observation_hz",
    "accepted_sample_count",
    "estimator_confidence",
    "frequency_estimate_hz",
    "frequency_error_hz",
    "frequency_uncertainty_hz",
    "dispersion_hz",
    "drift_enabled",
    "drift_hz_per_s",
    "preview_eligibility",
    "eligibility_reason_codes",
]

CONTROL_PREVIEW_V1_FIELDS = [
    "record_type",
    "schema_version",
    "control_seq",
    "decision_id",
    "decision_timestamp_ticks",
    "time_domain",
    "est_input_ref",
    "plant_model_ref",
    "plant_model_id",
    "plant_model_version",
    "plant_model_hash",
    "policy_version",
    "config_hash",
    "control_state",
    "previous_control_state",
    "state_transition",
    "transition_reason_code",
    "preview_eligibility",
    "eligibility_reason_codes",
    "diagnostic_health",
    "model_applicability",
    "model_reason_codes",
    "current_dac_code",
    "frequency_error_hz",
    "hz_per_code",
    "raw_delta_codes",
    "limited_delta_codes",
    "proposed_dac_code",
    "step_limited",
    "range_clamped",
    "preview_available",
    "preview_only",
    "actuation_authorized",
    "actionable",
    "decision_reason_code",
]

CONTRACT_FIELDS = {
    "raw_events_v1": RAW_EVENT_FIELDS,
    "count_observations_v1": COUNT_OBSERVATION_FIELDS,
    "health_v1": HEALTH_FIELDS,
    "dac_steps_v1": DAC_STEP_FIELDS,
    "environment_v1": ENVIRONMENT_FIELDS,
    "diagnostics_draft_v0": DIAGNOSTICS_DRAFT_V0_FIELDS,
    "estimates_v1": ESTIMATE_V1_FIELDS,
    "control_previews_v1": CONTROL_PREVIEW_V1_FIELDS,
}

CONTRACT_RECORD_TYPES = {
    "raw_events_v1": {"EVT", "REF"},
    "count_observations_v1": {"CNT"},
    "health_v1": {"STS"},
    "dac_steps_v1": {"DAC"},
    "environment_v1": {"ENV"},
    "diagnostics_draft_v0": {"DIAG"},
    "estimates_v1": {"EST"},
    "control_previews_v1": {"CTL"},
}

CONTRACT_SCHEMA_VERSIONS = {
    "raw_events_v1": 1,
    "count_observations_v1": 1,
    "health_v1": 1,
    "dac_steps_v1": 1,
    "environment_v1": 1,
    "diagnostics_draft_v0": 0,
    "estimates_v1": 1,
    "control_previews_v1": 1,
}

SEQUENCE_FIELDS = {
    "raw_events_v1": "event_seq",
    "count_observations_v1": "count_seq",
    "health_v1": "status_seq",
    "dac_steps_v1": "seq",
    "environment_v1": "env_seq",
    "diagnostics_draft_v0": "diagnostic_seq",
    "estimates_v1": "estimate_seq",
    "control_previews_v1": "control_seq",
}

TIMESTAMP_FIELDS = {
    "raw_events_v1": ("timestamp_ticks",),
    "count_observations_v1": ("gate_open_ticks", "gate_close_ticks"),
    "health_v1": ("timestamp_ticks",),
    "dac_steps_v1": ("elapsed_ms",),
    "environment_v1": ("timestamp_ticks",),
    "diagnostics_draft_v0": ("first_seen_ticks", "last_seen_ticks"),
    "estimates_v1": ("estimator_timestamp_ticks",),
    "control_previews_v1": ("decision_timestamp_ticks",),
}

CHANNEL_FIELDS = {
    "raw_events_v1": "channel_id",
    "count_observations_v1": "channel_id",
}

DOMAIN_FIELDS = {
    "raw_events_v1": ("capture_domain",),
    "count_observations_v1": ("gate_domain",),
    "health_v1": ("status_domain",),
    "dac_steps_v1": (),
    "environment_v1": ("observation_domain",),
    "diagnostics_draft_v0": ("time_domain",),
    "estimates_v1": ("time_domain",),
    "control_previews_v1": ("time_domain",),
}

FLAG_KNOWN_MASK_V1 = 0xFFFF
VALID_EDGES = {"R", "F", "B"}
VALID_SEVERITIES = {"INFO", "WARN", "ERROR", "FATAL"}
VALID_DIAGNOSTIC_SEVERITIES = {"INFO", "DEGRADED", "WARN", "FAULT", "CRITICAL"}
VALID_DIAGNOSTIC_SUBSYSTEMS = {
    "reference",
    "count_path",
    "oscillator",
    "actuator",
    "estimator",
    "control",
    "environment",
    "service_plane",
    "storage",
}
VALID_DIAGNOSTIC_STATES = {"active", "cleared", "latched", "suppressed", "unknown"}
VALID_DIAGNOSTIC_TRANSITIONS = {"raised", "updated", "cleared", "latched", "suppressed", "snapshot", "unknown"}
VALID_CONTROL_EFFECTS = {
    "none",
    "reduce_trust",
    "inhibit_acquisition",
    "inhibit_actuation",
    "enter_holdover",
    "fail_static",
    "unknown",
}
VALID_CONTROL_ELIGIBILITY = {"eligible", "not_eligible", "not_applicable", "unknown"}
VALID_ENV_SOURCES = {"sht4x", "bmp280"}
VALID_ENV_ROLES = {"vcocxo_near", "ambient_board", "ambient", "pressure_reference"}
VALID_BOOLEAN_TEXT = {"true", "false"}
VALID_OBSERVATION_VALIDITY = {"valid", "invalid", "unavailable"}
VALID_COMPONENT_VALIDITY = {"valid", "invalid", "stale", "unavailable"}
VALID_DIAGNOSTIC_HEALTH = {"healthy", "degraded", "fault", "unknown"}
VALID_ESTIMATOR_CONFIDENCE = {"unavailable", "low", "medium", "high"}
VALID_MODEL_APPLICABILITY = {"applicable", "not_applicable", "unavailable", "invalid"}
VALID_CONTROL_STATES = {
    "BOOT",
    "SAFE_OBSERVE",
    "WARMUP_INHIBIT",
    "QUALIFYING",
    "ACQUIRE_PREVIEW",
    "SETTLE_PREVIEW",
    "LOCKED_PREVIEW",
    "HOLDOVER_PREVIEW",
    "RECOVER_PREVIEW",
    "MANUAL_OPEN_LOOP",
    "FAULT",
}


@dataclass(frozen=True)
class CsvValidationContext:
    contract: str
    known_channels: frozenset[int]
    known_domains: frozenset[str]
    template: bool = False
    allow_rp2040_timer0_wrap: bool = False


@dataclass(frozen=True)
class CsvValidationResult:
    path: Path
    row_count: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def _parse_non_negative_int(value: str, field_name: str, row_number: int, errors: list[str]) -> int | None:
    try:
        parsed = int(value, 10)
    except (TypeError, ValueError):
        errors.append(f"row {row_number}: {field_name} is not an integer: {value!r}")
        return None
    if parsed < 0:
        errors.append(f"row {row_number}: {field_name} must be non-negative: {parsed}")
        return None
    return parsed


def _parse_int(value: str, field_name: str, row_number: int, errors: list[str]) -> int | None:
    try:
        return int(value, 10)
    except (TypeError, ValueError):
        errors.append(f"row {row_number}: {field_name} is not an integer: {value!r}")
        return None


def _check_schema_version(contract: str, row: dict[str, str], row_number: int, errors: list[str]) -> None:
    version = _parse_non_negative_int(row.get("schema_version", ""), "schema_version", row_number, errors)
    expected = CONTRACT_SCHEMA_VERSIONS[contract]
    if version is not None and version != expected:
        errors.append(f"row {row_number}: unsupported schema_version {version}; expected {expected}")


def _check_record_type(contract: str, row: dict[str, str], row_number: int, errors: list[str]) -> None:
    record_type = row.get("record_type", "")
    expected = CONTRACT_RECORD_TYPES[contract]
    if record_type not in expected:
        errors.append(f"row {row_number}: record_type {record_type!r} not valid for {contract}; expected one of {sorted(expected)}")


def _check_sequence(contract: str, row: dict[str, str], row_number: int, previous: int | None, errors: list[str]) -> int | None:
    field_name = SEQUENCE_FIELDS[contract]
    current = _parse_non_negative_int(row.get(field_name, ""), field_name, row_number, errors)
    if current is not None and previous is not None and current <= previous:
        errors.append(f"row {row_number}: {field_name} must be strictly increasing; previous={previous}, current={current}")
    return current if current is not None else previous


def _check_timestamps(
    contract: str,
    row: dict[str, str],
    row_number: int,
    errors: list[str],
    *,
    allow_rp2040_timer0_wrap: bool,
) -> None:
    parsed: dict[str, int] = {}
    for field_name in TIMESTAMP_FIELDS[contract]:
        value = _parse_non_negative_int(row.get(field_name, ""), field_name, row_number, errors)
        if value is not None:
            parsed[field_name] = value
    if contract == "count_observations_v1" and {"gate_open_ticks", "gate_close_ticks"} <= parsed.keys():
        if parsed["gate_close_ticks"] <= parsed["gate_open_ticks"]:
            crosses_wrap = (
                allow_rp2040_timer0_wrap
                and parsed["gate_open_ticks"] - parsed["gate_close_ticks"]
                > RP2040_TIMER0_MICROS_WRAP_TICKS // 2
            )
            if not crosses_wrap:
                errors.append(
                    f"row {row_number}: gate_close_ticks must be greater than gate_open_ticks; "
                    f"open={parsed['gate_open_ticks']}, close={parsed['gate_close_ticks']}"
                )


def _check_timestamp_monotonicity(
    contract: str,
    parsed_timestamps: dict[str, int],
    row_number: int,
    previous_timestamps: dict[str, int],
    errors: list[str],
    *,
    allow_rp2040_timer0_wrap: bool,
) -> None:
    for field_name in TIMESTAMP_FIELDS[contract]:
        if field_name not in parsed_timestamps:
            continue
        previous = previous_timestamps.get(field_name)
        current = parsed_timestamps[field_name]
        if previous is not None and current < previous:
            if allow_rp2040_timer0_wrap and previous - current > RP2040_TIMER0_MICROS_WRAP_TICKS // 2:
                previous_timestamps[field_name] = current
                continue
            errors.append(f"row {row_number}: {field_name} must be monotonic; previous={previous}, current={current}")
        previous_timestamps[field_name] = current


def _check_channel(context: CsvValidationContext, row: dict[str, str], row_number: int, errors: list[str]) -> None:
    field_name = CHANNEL_FIELDS.get(context.contract)
    if not field_name:
        return
    channel = _parse_non_negative_int(row.get(field_name, ""), field_name, row_number, errors)
    if channel is not None and context.known_channels and channel not in context.known_channels:
        errors.append(f"row {row_number}: {field_name} {channel} is not declared in manifest channels")


def _check_domains(context: CsvValidationContext, row: dict[str, str], row_number: int, errors: list[str]) -> None:
    for field_name in DOMAIN_FIELDS[context.contract]:
        domain = row.get(field_name, "")
        if context.known_domains and domain not in context.known_domains:
            errors.append(f"row {row_number}: {field_name} {domain!r} is not declared in manifest domains")


def _check_flags(row: dict[str, str], row_number: int, errors: list[str]) -> None:
    flags = _parse_non_negative_int(row.get("flags", ""), "flags", row_number, errors)
    if flags is not None and flags & ~FLAG_KNOWN_MASK_V1:
        errors.append(f"row {row_number}: flags uses reserved v1 bits: {flags}")


def _check_edges(contract: str, row: dict[str, str], row_number: int, errors: list[str]) -> None:
    if contract == "raw_events_v1" and row.get("edge") not in VALID_EDGES:
        errors.append(f"row {row_number}: edge must be one of {sorted(VALID_EDGES)}")
    if contract == "count_observations_v1" and row.get("source_edge") not in VALID_EDGES:
        errors.append(f"row {row_number}: source_edge must be one of {sorted(VALID_EDGES)}")


def _check_count_observation(row: dict[str, str], row_number: int, errors: list[str]) -> None:
    if "counted_edges" in row:
        _parse_non_negative_int(row.get("counted_edges", ""), "counted_edges", row_number, errors)


def _check_health(row: dict[str, str], row_number: int, errors: list[str]) -> None:
    if row.get("severity") not in VALID_SEVERITIES:
        errors.append(f"row {row_number}: severity must be one of {sorted(VALID_SEVERITIES)}")
    for field_name in ("component", "status_key", "status_value"):
        if not row.get(field_name):
            errors.append(f"row {row_number}: {field_name} must not be empty")


def _check_dac_step(row: dict[str, str], row_number: int, errors: list[str]) -> None:
    for field_name in (
        "elapsed_ms",
        "dac_code_requested",
        "dac_code_applied",
        "dac_code_clamped",
        "dwell_ms",
        "flags",
    ):
        _parse_non_negative_int(row.get(field_name, ""), field_name, row_number, errors)
    step_index = row.get("step_index", "")
    try:
        int(step_index, 10)
    except (TypeError, ValueError):
        errors.append(f"row {row_number}: step_index is not an integer: {step_index!r}")
    if row.get("dac_code_clamped") not in {"0", "1"}:
        errors.append(f"row {row_number}: dac_code_clamped must be 0 or 1")
    if not row.get("event"):
        errors.append(f"row {row_number}: event must not be empty")


def _parse_optional_float(value: str | None, field_name: str, row_number: int, errors: list[str]) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        errors.append(f"row {row_number}: {field_name} is not a float: {value!r}")
        return None
    if not math.isfinite(parsed):
        errors.append(f"row {row_number}: {field_name} must be finite: {value!r}")
        return None
    return parsed


def _check_environment(row: dict[str, str], row_number: int, errors: list[str]) -> None:
    source = row.get("source", "")
    role = row.get("role", "")
    if source not in VALID_ENV_SOURCES:
        errors.append(f"row {row_number}: source must be one of {sorted(VALID_ENV_SOURCES)}")
    if role not in VALID_ENV_ROLES:
        errors.append(f"row {row_number}: role must be one of {sorted(VALID_ENV_ROLES)}")
    temperature = _parse_optional_float(row.get("temperature_c"), "temperature_c", row_number, errors)
    humidity = _parse_optional_float(row.get("relative_humidity_pct"), "relative_humidity_pct", row_number, errors)
    pressure = _parse_optional_float(row.get("pressure_pa"), "pressure_pa", row_number, errors)
    if temperature is None and humidity is None and pressure is None:
        errors.append(f"row {row_number}: at least one environmental measurement must be present")
    if humidity is not None and not 0.0 <= humidity <= 100.0:
        errors.append(f"row {row_number}: relative_humidity_pct must be between 0 and 100")
    if pressure is not None and pressure <= 0.0:
        errors.append(f"row {row_number}: pressure_pa must be positive")


def _check_diagnostics_draft_v0(row: dict[str, str], row_number: int, errors: list[str]) -> None:
    if row.get("subsystem") not in VALID_DIAGNOSTIC_SUBSYSTEMS:
        errors.append(f"row {row_number}: subsystem must be one of {sorted(VALID_DIAGNOSTIC_SUBSYSTEMS)}")
    if row.get("severity") not in VALID_DIAGNOSTIC_SEVERITIES:
        errors.append(f"row {row_number}: severity must be one of {sorted(VALID_DIAGNOSTIC_SEVERITIES)}")
    if row.get("state") not in VALID_DIAGNOSTIC_STATES:
        errors.append(f"row {row_number}: state must be one of {sorted(VALID_DIAGNOSTIC_STATES)}")
    if row.get("transition") not in VALID_DIAGNOSTIC_TRANSITIONS:
        errors.append(f"row {row_number}: transition must be one of {sorted(VALID_DIAGNOSTIC_TRANSITIONS)}")
    if row.get("control_effect") not in VALID_CONTROL_EFFECTS:
        errors.append(f"row {row_number}: control_effect must be one of {sorted(VALID_CONTROL_EFFECTS)}")
    if row.get("control_eligibility") not in VALID_CONTROL_ELIGIBILITY:
        errors.append(f"row {row_number}: control_eligibility must be one of {sorted(VALID_CONTROL_ELIGIBILITY)}")

    confidence = row.get("diagnostic_confidence", "")
    if confidence != "unknown":
        parsed_confidence = _parse_optional_float(confidence, "diagnostic_confidence", row_number, errors)
        if parsed_confidence is None or not 0.0 <= parsed_confidence <= 1.0:
            errors.append(f"row {row_number}: diagnostic_confidence must be between 0.0 and 1.0 or 'unknown'")

    first_seen = _parse_non_negative_int(row.get("first_seen_ticks", ""), "first_seen_ticks", row_number, errors)
    last_seen = _parse_non_negative_int(row.get("last_seen_ticks", ""), "last_seen_ticks", row_number, errors)
    if first_seen is not None and last_seen is not None and last_seen < first_seen:
        errors.append(f"row {row_number}: last_seen_ticks must be greater than or equal to first_seen_ticks")

    for field_name in ("diagnostic_id", "reason_code", "evidence_refs", "algorithm_version", "config_version"):
        if not row.get(field_name):
            errors.append(f"row {row_number}: {field_name} must not be empty")

    if row.get("subsystem") == "service_plane" and row.get("control_effect") in {"enter_holdover", "fail_static"}:
        errors.append(
            f"row {row_number}: service-plane telemetry diagnostics must not directly enter holdover or fail static"
        )


def _check_required_text(
    row: dict[str, str], row_number: int, errors: list[str], field_names: tuple[str, ...]
) -> None:
    for field_name in field_names:
        if not row.get(field_name):
            errors.append(f"row {row_number}: {field_name} must not be empty")


def _check_boolean_text(row: dict[str, str], field_name: str, row_number: int, errors: list[str]) -> None:
    if row.get(field_name) not in VALID_BOOLEAN_TEXT:
        errors.append(f"row {row_number}: {field_name} must be 'true' or 'false'")


def _check_estimate_v1(row: dict[str, str], row_number: int, errors: list[str]) -> None:
    _check_required_text(
        row,
        row_number,
        errors,
        (
            "estimate_id",
            "source_count_ref",
            "source_status_refs",
            "source_dac_ref",
            "manifest_ref",
            "estimator_version",
            "config_hash",
            "observation_reason_codes",
            "diagnostic_reason_codes",
            "eligibility_reason_codes",
        ),
    )
    if row.get("observation_validity") not in VALID_OBSERVATION_VALIDITY:
        errors.append(
            f"row {row_number}: observation_validity must be one of {sorted(VALID_OBSERVATION_VALIDITY)}"
        )
    for field_name in ("reference_validity", "count_validity"):
        if row.get(field_name) not in VALID_COMPONENT_VALIDITY:
            errors.append(
                f"row {row_number}: {field_name} must be one of {sorted(VALID_COMPONENT_VALIDITY)}"
            )
    if row.get("diagnostic_health") not in VALID_DIAGNOSTIC_HEALTH:
        errors.append(
            f"row {row_number}: diagnostic_health must be one of {sorted(VALID_DIAGNOSTIC_HEALTH)}"
        )
    if row.get("estimator_confidence") not in VALID_ESTIMATOR_CONFIDENCE:
        errors.append(
            f"row {row_number}: estimator_confidence must be one of {sorted(VALID_ESTIMATOR_CONFIDENCE)}"
        )

    for field_name in (
        "reference_continuity",
        "count_continuity",
        "drift_enabled",
        "preview_eligibility",
    ):
        _check_boolean_text(row, field_name, row_number, errors)
    if row.get("drift_enabled") != "false":
        errors.append(f"row {row_number}: drift_enabled must remain false in Phase 4 v1 replay")
    if row.get("drift_hz_per_s"):
        errors.append(f"row {row_number}: drift_hz_per_s must be unavailable when drift_enabled=false")

    for field_name in (
        "reference_age_s",
        "count_age_s",
        "frequency_observation_hz",
        "frequency_estimate_hz",
        "frequency_error_hz",
        "frequency_uncertainty_hz",
        "dispersion_hz",
    ):
        _parse_optional_float(row.get(field_name), field_name, row_number, errors)
    _parse_non_negative_int(row.get("accepted_sample_count", ""), "accepted_sample_count", row_number, errors)
    if row.get("source_count_seq"):
        _parse_non_negative_int(row.get("source_count_seq", ""), "source_count_seq", row_number, errors)
    for field_name in ("source_reference_first_seq", "source_reference_last_seq"):
        if row.get(field_name):
            _parse_non_negative_int(row.get(field_name, ""), field_name, row_number, errors)


def _check_control_preview_v1(row: dict[str, str], row_number: int, errors: list[str]) -> None:
    _check_required_text(
        row,
        row_number,
        errors,
        (
            "decision_id",
            "est_input_ref",
            "plant_model_ref",
            "policy_version",
            "config_hash",
            "control_state",
            "previous_control_state",
            "transition_reason_code",
            "eligibility_reason_codes",
            "model_reason_codes",
            "decision_reason_code",
        ),
    )
    if row.get("control_state") not in VALID_CONTROL_STATES:
        errors.append(f"row {row_number}: control_state must be one of {sorted(VALID_CONTROL_STATES)}")
    if row.get("previous_control_state") not in VALID_CONTROL_STATES:
        errors.append(
            f"row {row_number}: previous_control_state must be one of {sorted(VALID_CONTROL_STATES)}"
        )
    if row.get("model_applicability") not in VALID_MODEL_APPLICABILITY:
        errors.append(
            f"row {row_number}: model_applicability must be one of {sorted(VALID_MODEL_APPLICABILITY)}"
        )
    if row.get("diagnostic_health") not in VALID_DIAGNOSTIC_HEALTH:
        errors.append(
            f"row {row_number}: diagnostic_health must be one of {sorted(VALID_DIAGNOSTIC_HEALTH)}"
        )

    for field_name in (
        "state_transition",
        "preview_eligibility",
        "step_limited",
        "range_clamped",
        "preview_available",
        "preview_only",
        "actuation_authorized",
        "actionable",
    ):
        _check_boolean_text(row, field_name, row_number, errors)
    if row.get("preview_only") != "true":
        errors.append(f"row {row_number}: preview_only must remain true in Phase 4 v1")
    if row.get("actuation_authorized") != "false":
        errors.append(f"row {row_number}: actuation_authorized must remain false in Phase 4 v1")
    if row.get("actionable") != "false":
        errors.append(f"row {row_number}: actionable must remain false in Phase 4 v1")

    for field_name in ("plant_model_version", "current_dac_code", "proposed_dac_code"):
        if row.get(field_name):
            _parse_non_negative_int(row.get(field_name, ""), field_name, row_number, errors)
    if row.get("limited_delta_codes"):
        _parse_int(row.get("limited_delta_codes", ""), "limited_delta_codes", row_number, errors)
    for field_name in ("frequency_error_hz", "hz_per_code", "raw_delta_codes"):
        _parse_optional_float(row.get(field_name), field_name, row_number, errors)

    preview_available = row.get("preview_available") == "true"
    preview_eligible = row.get("preview_eligibility") == "true"
    if preview_available and not preview_eligible:
        errors.append(f"row {row_number}: preview_available requires preview_eligibility=true")
    if preview_available and not row.get("proposed_dac_code"):
        errors.append(f"row {row_number}: preview_available requires proposed_dac_code")
    if not preview_available and row.get("proposed_dac_code"):
        errors.append(f"row {row_number}: inhibited preview must not contain proposed_dac_code")


def validate_csv(path: Path, context: CsvValidationContext) -> CsvValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    row_count = 0
    previous_seq: int | None = None
    previous_timestamps: dict[str, int] = {}

    if context.contract not in CONTRACT_FIELDS:
        return CsvValidationResult(path=path, row_count=0, errors=(f"unsupported contract {context.contract!r}",))
    if not path.exists():
        return CsvValidationResult(path=path, row_count=0, errors=("file listed in manifest does not exist",))

    expected_fields = CONTRACT_FIELDS[context.contract]
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        actual = reader.fieldnames or []
        if actual != expected_fields:
            errors.append(f"header mismatch: expected {expected_fields}, got {actual}")

        for row_count, row in enumerate(reader, start=1):
            if None in row:
                errors.append(f"row {row_count}: malformed row has too many columns")
            for field_name in expected_fields:
                if row.get(field_name) is None:
                    errors.append(f"row {row_count}: malformed row missing field {field_name}")
            _check_schema_version(context.contract, row, row_count, errors)
            _check_record_type(context.contract, row, row_count, errors)
            previous_seq = _check_sequence(context.contract, row, row_count, previous_seq, errors)
            _check_timestamps(
                context.contract,
                row,
                row_count,
                errors,
                allow_rp2040_timer0_wrap=context.allow_rp2040_timer0_wrap,
            )
            parsed_timestamps: dict[str, int] = {}
            for field_name in TIMESTAMP_FIELDS[context.contract]:
                try:
                    parsed_timestamps[field_name] = int(row.get(field_name, ""), 10)
                except (TypeError, ValueError):
                    continue
            _check_timestamp_monotonicity(
                context.contract,
                parsed_timestamps,
                row_count,
                previous_timestamps,
                errors,
                allow_rp2040_timer0_wrap=context.allow_rp2040_timer0_wrap,
            )
            _check_channel(context, row, row_count, errors)
            _check_domains(context, row, row_count, errors)
            if "flags" in expected_fields:
                _check_flags(row, row_count, errors)
            _check_edges(context.contract, row, row_count, errors)
            if context.contract == "count_observations_v1":
                _check_count_observation(row, row_count, errors)
            if context.contract == "health_v1":
                _check_health(row, row_count, errors)
            if context.contract == "dac_steps_v1":
                _check_dac_step(row, row_count, errors)
            if context.contract == "environment_v1":
                _check_environment(row, row_count, errors)
            if context.contract == "diagnostics_draft_v0":
                _check_diagnostics_draft_v0(row, row_count, errors)
            if context.contract == "estimates_v1":
                _check_estimate_v1(row, row_count, errors)
            if context.contract == "control_previews_v1":
                _check_control_preview_v1(row, row_count, errors)

    if row_count == 0:
        warnings.append("CSV has headers but no data rows")

    return CsvValidationResult(path=path, row_count=row_count, errors=tuple(errors), warnings=tuple(warnings))


def validate_csv_header(path: Path, expected_fields: list[str]) -> CsvValidationResult:
    """Compatibility wrapper for older callers; prefer validate_csv()."""
    contract = next((name for name, fields in CONTRACT_FIELDS.items() if fields == expected_fields), "unknown")
    return validate_csv(
        path,
        CsvValidationContext(contract=contract, known_channels=frozenset(), known_domains=frozenset()),
    )
