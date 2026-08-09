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

PPS_SNAPSHOT_FIELDS = [
    "record_type",
    "schema_version",
    "session",
    "snapshot_sequence",
    "cumulative_down_counter",
    "reference_sequence",
    "reference_timestamp_ticks",
    "status",
    "backend",
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

PSEUDO_PPS_TRUTH_FIELDS = [
    "record_type",
    "schema_version",
    "truth_seq",
    "generator_session",
    "profile_id",
    "profile_version",
    "generator_sequence",
    "event",
    "intended_class",
    "scheduled_offset_us",
    "scheduled_interval_us",
    "pulse_width_us",
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

DIAGNOSTICS_V1_FIELDS = [
    "record_type",
    "schema_version",
    "diagnostic_seq",
    "diagnostic_id",
    "episode_id",
    "subsystem",
    "severity",
    "state",
    "transition",
    "diagnostic_confidence",
    "reason_code",
    "clear_reason_code",
    "first_seen_ticks",
    "last_seen_ticks",
    "time_domain",
    "occurrence_count",
    "persistence_state",
    "first_evidence_refs",
    "latest_evidence_refs",
    "algorithm_version",
    "config_hash",
    "observation_effect",
    "reference_effect",
    "model_effect",
    "control_effect",
]

REFERENCE_OBSERVATION_V1_FIELDS = [
    "record_type",
    "schema_version",
    "reference_observation_seq",
    "reference_observation_id",
    "observation_timestamp_ticks",
    "time_domain",
    "source_identity_epoch",
    "source_reference_first_seq",
    "source_reference_last_seq",
    "source_reference_refs",
    "source_metadata_refs",
    "receiver_identity",
    "receiver_firmware",
    "cadence_state",
    "capture_path_state",
    "receiver_authority_state",
    "utc_traceability_state",
    "metadata_freshness",
    "timing_mode",
    "fix_holdover_state",
    "antenna_state",
    "leap_state",
    "sawtooth_correction_ns",
    "cable_delay_ns",
    "pulse_configuration",
    "calibration_ref",
    "reference_standard_uncertainty_s",
    "qualification_state",
    "qualification_reason_codes",
    "algorithm_version",
    "config_hash",
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

ESTIMATE_V2_FIELDS = [
    *ESTIMATE_V1_FIELDS[:30],
    "dispersion_hz",
    "uncertainty_status",
    "uncertainty_reason_codes",
    "count_quantization_standard_uncertainty_hz",
    "counter_aperture_standard_uncertainty_hz",
    "reference_standard_uncertainty_hz",
    "calibration_standard_uncertainty_hz",
    "model_standard_uncertainty_hz",
    "combined_standard_uncertainty_hz",
    "coverage_factor",
    "expanded_uncertainty_hz",
    "correlation_policy",
    "uncertainty_model_ref",
    *ESTIMATE_V1_FIELDS[32:],
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

ACTIVE_TRANSACTION_V1_FIELDS = [
    "record_type",
    "schema_version",
    "transaction_record_sequence",
    "event",
    "run_identity",
    "build_identity",
    "profile_identity",
    "session_id",
    "authorization_sequence",
    "nonce",
    "request_sequence",
    "decision_sequence",
    "source_first_sequence",
    "source_last_sequence",
    "decision_timestamp_s",
    "current_applied_code",
    "requested_delta_codes",
    "requested_code",
    "correction_ordinal",
    "cumulative_after_codes",
    "pre_error_hz",
    "accepted_code",
    "accepted_timestamp_s",
    "applied_code",
    "application_sequence",
    "application_timestamp_s",
    "i2c_ok",
    "clamped",
    "ambiguous",
    "dac_epoch",
    "estimator_history_reset",
    "correction_count",
    "cumulative_movement_codes",
    "post_error_hz",
    "observed_response_hz",
    "cumulative_response_hz",
    "consecutive_indeterminate",
    "active_state",
    "response_class",
    "reason",
    "estimator_sha256",
    "model_sha256",
    "active_policy_sha256",
    "response_policy_sha256",
    "numerical_policy_sha256",
    "actionable",
    "evidence_state",
]

# CX318 Stage 4 telemetry is deliberately separate from the accepted frequency
# control products.  RPH is the immutable raw relative-phase boundary; HPR is
# a candidate-specific, counterfactual hybrid-preview boundary.  Neither
# record is an authority or an actuator request.
RELATIVE_PHASE_OBSERVATION_V1_FIELDS = [
    "record_type",
    "schema_version",
    "phase_epoch",
    "observation_sequence",
    "capture_session",
    "opening_snapshot_sequence",
    "closing_snapshot_sequence",
    "opening_reference_sequence",
    "closing_reference_sequence",
    "dac_epoch",
    "source_backend",
    "source_file_sha256",
    "method_id",
    "configuration_sha256",
    "interval_edges",
    "edge_error_cycles",
    "relative_phase_cycles",
    "relative_phase_time_ns",
    "qualification_state",
    "observation_age_s",
    "discontinuity_reason",
    "calibrated_uncertainty_status",
]

PHASE_ESTIMATOR_OUTPUT_V1_FIELDS = [
    "record_type",
    "schema_version",
    "phase_epoch",
    "observation_sequence",
    "source_relative_phase_observation",
    "raw_relative_phase_cycles",
    "raw_relative_phase_time_ns",
    "filtered_relative_phase_cycles",
    "estimated_frequency_error_hz",
    "estimator_id",
    "configuration_sha256",
    "estimate_age_s",
    "qualification_state",
    "uncertainty_status",
    "reason_codes",
]

HYBRID_PREVIEW_DECISION_V1_FIELDS = [
    "record_type",
    "schema_version",
    "preview_sequence",
    "candidate_id",
    "candidate_configuration_sha256",
    "phase_estimator_id",
    "phase_estimator_configuration_sha256",
    "frequency_estimator_id",
    "frequency_estimator_configuration_sha256",
    "configuration_sha256",
    "phase_epoch",
    "observation_sequence",
    "dac_epoch",
    "decision_timestamp_ticks",
    "time_domain",
    "source_phase_estimate",
    "source_frequency_estimate",
    "raw_relative_phase_cycles",
    "modeled_relative_phase_cycles",
    "observed_frequency_error_hz",
    "modeled_frequency_error_hz",
    "frequency_term_hz",
    "phase_bias_hz",
    "combined_frequency_error_hz",
    "actual_applied_code",
    "shadow_code_before",
    "shadow_code_after",
    "band_state_before",
    "band_state_after",
    "preview_state",
    "decision_reason",
    "frequency_observation_event",
    "counterfactual_decision",
    "counterfactual_correction",
    "raw_counterfactual_delta_codes",
    "counterfactual_delta_codes",
    "counterfactual_code",
    "step_limited",
    "range_clamped",
    "correction_count",
    "cumulative_movement_codes",
    "alternating_correction_count",
    "modeled_not_observed_after_divergence",
    "uncertainty_status",
    "actionable",
    "actuation_authorized",
    "authorization_consumed",
]

CONTRACT_FIELDS = {
    "raw_events_v1": RAW_EVENT_FIELDS,
    "count_observations_v1": COUNT_OBSERVATION_FIELDS,
    "pps_snapshots_v1": PPS_SNAPSHOT_FIELDS,
    "health_v1": HEALTH_FIELDS,
    "dac_steps_v1": DAC_STEP_FIELDS,
    "environment_v1": ENVIRONMENT_FIELDS,
    "pseudo_pps_truth_v1": PSEUDO_PPS_TRUTH_FIELDS,
    "diagnostics_draft_v0": DIAGNOSTICS_DRAFT_V0_FIELDS,
    "diagnostics_v1": DIAGNOSTICS_V1_FIELDS,
    "reference_observations_v1": REFERENCE_OBSERVATION_V1_FIELDS,
    "estimates_v1": ESTIMATE_V1_FIELDS,
    "estimates_v2": ESTIMATE_V2_FIELDS,
    "control_previews_v1": CONTROL_PREVIEW_V1_FIELDS,
    "active_transactions_v1": ACTIVE_TRANSACTION_V1_FIELDS,
    "relative_phase_observations_v1": RELATIVE_PHASE_OBSERVATION_V1_FIELDS,
    "phase_estimator_outputs_v1": PHASE_ESTIMATOR_OUTPUT_V1_FIELDS,
    "hybrid_preview_decisions_v1": HYBRID_PREVIEW_DECISION_V1_FIELDS,
}

CONTRACT_RECORD_TYPES = {
    "raw_events_v1": {"EVT", "REF"},
    "count_observations_v1": {"CNT"},
    "pps_snapshots_v1": {"SNP"},
    "health_v1": {"STS"},
    "dac_steps_v1": {"DAC"},
    "environment_v1": {"ENV"},
    "pseudo_pps_truth_v1": {"PGT"},
    "diagnostics_draft_v0": {"DIAG"},
    "diagnostics_v1": {"DIAG"},
    "reference_observations_v1": {"RFO"},
    "estimates_v1": {"EST"},
    "estimates_v2": {"EST"},
    "control_previews_v1": {"CTL"},
    "active_transactions_v1": {"ACT"},
    "relative_phase_observations_v1": {"RPH"},
    "phase_estimator_outputs_v1": {"PHE"},
    "hybrid_preview_decisions_v1": {"HPR"},
}

CONTRACT_SCHEMA_VERSIONS = {
    "raw_events_v1": 1,
    "count_observations_v1": 1,
    "pps_snapshots_v1": 1,
    "health_v1": 1,
    "dac_steps_v1": 1,
    "environment_v1": 1,
    "pseudo_pps_truth_v1": 1,
    "diagnostics_draft_v0": 0,
    "diagnostics_v1": 1,
    "reference_observations_v1": 1,
    "estimates_v1": 1,
    "estimates_v2": 2,
    "control_previews_v1": 1,
    "active_transactions_v1": 1,
    "relative_phase_observations_v1": 1,
    "phase_estimator_outputs_v1": 1,
    "hybrid_preview_decisions_v1": 1,
}

SEQUENCE_FIELDS = {
    "raw_events_v1": "event_seq",
    "count_observations_v1": "count_seq",
    "pps_snapshots_v1": "snapshot_sequence",
    "health_v1": "status_seq",
    "dac_steps_v1": "seq",
    "environment_v1": "env_seq",
    "pseudo_pps_truth_v1": "truth_seq",
    "diagnostics_draft_v0": "diagnostic_seq",
    "diagnostics_v1": "diagnostic_seq",
    "reference_observations_v1": "reference_observation_seq",
    "estimates_v1": "estimate_seq",
    "estimates_v2": "estimate_seq",
    "control_previews_v1": "control_seq",
    "active_transactions_v1": "transaction_record_sequence",
    "relative_phase_observations_v1": "observation_sequence",
    "phase_estimator_outputs_v1": "observation_sequence",
    "hybrid_preview_decisions_v1": "preview_sequence",
}

TIMESTAMP_FIELDS = {
    "raw_events_v1": ("timestamp_ticks",),
    "count_observations_v1": ("gate_open_ticks", "gate_close_ticks"),
    "pps_snapshots_v1": ("reference_timestamp_ticks",),
    "health_v1": ("timestamp_ticks",),
    "dac_steps_v1": ("elapsed_ms",),
    "environment_v1": ("timestamp_ticks",),
    "pseudo_pps_truth_v1": (),
    "diagnostics_draft_v0": ("first_seen_ticks", "last_seen_ticks"),
    "diagnostics_v1": ("last_seen_ticks",),
    "reference_observations_v1": ("observation_timestamp_ticks",),
    "estimates_v1": ("estimator_timestamp_ticks",),
    "estimates_v2": ("estimator_timestamp_ticks",),
    "control_previews_v1": ("decision_timestamp_ticks",),
    "active_transactions_v1": (),
    "relative_phase_observations_v1": (),
    "phase_estimator_outputs_v1": (),
    "hybrid_preview_decisions_v1": ("decision_timestamp_ticks",),
}

CHANNEL_FIELDS = {
    "raw_events_v1": "channel_id",
    "count_observations_v1": "channel_id",
}

DOMAIN_FIELDS = {
    "raw_events_v1": ("capture_domain",),
    "count_observations_v1": ("gate_domain",),
    "pps_snapshots_v1": (),
    "health_v1": ("status_domain",),
    "dac_steps_v1": (),
    "environment_v1": ("observation_domain",),
    "pseudo_pps_truth_v1": (),
    "diagnostics_draft_v0": ("time_domain",),
    "diagnostics_v1": ("time_domain",),
    "reference_observations_v1": ("time_domain",),
    "estimates_v1": ("time_domain",),
    "estimates_v2": ("time_domain",),
    "control_previews_v1": ("time_domain",),
    "active_transactions_v1": (),
    "relative_phase_observations_v1": (),
    "phase_estimator_outputs_v1": (),
    "hybrid_preview_decisions_v1": ("time_domain",),
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
VALID_DIAGNOSTIC_EFFECTS = {
    "none",
    "invalidate",
    "mark_unavailable",
    "reduce_trust",
    "not_applicable",
    "inhibit",
    "holdover",
    "fail_static",
    "unknown",
}
VALID_PERSISTENCE_STATES = {"candidate", "confirmed", "recovering", "cleared", "latched"}
VALID_CADENCE_STATES = {
    "valid",
    "duplicate",
    "short",
    "long",
    "missing",
    "invalid",
    "unavailable",
}
VALID_CAPTURE_PATH_STATES = {
    "valid",
    "sequence_gap",
    "overflow",
    "resource_failure",
    "invalid",
    "unavailable",
}
VALID_REFERENCE_AUTHORITY_STATES = {
    "qualified",
    "holdover",
    "fix_unavailable",
    "antenna_fault",
    "invalid",
    "unknown",
    "unavailable",
}
VALID_UTC_TRACEABILITY_STATES = {"valid", "invalid", "unknown", "unavailable"}
VALID_METADATA_FRESHNESS = {"current", "stale", "missing", "unavailable"}
VALID_REFERENCE_QUALIFICATION_STATES = {
    "qualified",
    "cadence_valid_authority_unknown",
    "holdover",
    "utc_invalid",
    "antenna_fault",
    "metadata_stale",
    "capture_path_invalid",
    "unqualified",
    "unknown",
}
VALID_UNCERTAINTY_STATUS = {"available", "incomplete", "unavailable"}
VALID_CORRELATION_POLICIES = {
    "independent_root_sum_square",
    "single_component_no_correlation",
    "not_combined_missing_components",
}
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
VALID_RELATIVE_PHASE_QUALIFICATION_STATES = {"epoch_open", "qualified", "invalid"}
VALID_PHASE_ESTIMATOR_QUALIFICATION_STATES = {
    "initializing",
    "qualified",
    "unavailable",
    "invalid",
}
VALID_CALIBRATED_UNCERTAINTY_STATUS = {"available", "unavailable"}
VALID_HYBRID_PREVIEW_STATES = {
    "RELATIVE_PHASE_ACQUIRE",
    "FREQUENCY_ACQUIRED_PREVIEW",
    "HYBRID_TRACKING_PREVIEW",
    "PHASE_STEP_HOLD_PREVIEW",
    "REFERENCE_LOST_PREVIEW",
    "RECOVER_PREVIEW",
    "FAULT_PREVIEW",
}
VALID_HYBRID_BAND_STATES = {"INSIDE", "OUTSIDE"}

VALID_ACTIVE_TRANSACTION_EVENTS = {
    "manual_start",
    "request_created",
    "core0_accepted",
    "request_accepted",
    "application",
    "application_fault",
    "response",
}
VALID_ACTIVE_STATES = {
    "DISARMED",
    "ARMED",
    "REQUEST_PENDING",
    "ACCEPTED_AWAITING_APPLICATION",
    "AWAITING_RESPONSE",
    "OUT_OF_MODEL_HOLD",
    "FAULT",
    "ABORTED",
}
VALID_ACTIVE_RESPONSE_CLASSES = {
    "unavailable",
    "healthy_detected",
    "healthy_indeterminate_near_resolution",
    "inside_deadband",
    "limit_reached",
    "wrong_sign",
    "excess_response",
    "growing_error",
    "measurement_or_actuator_fault",
}
VALID_ACTIVE_EVIDENCE_STATES = {
    "evidence_clear",
    "request_pending",
    "acceptance_pending",
    "application_pending",
    "response_pending",
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
    # Snapshot ordinals restart at zero when the firmware opens a new capture
    # session, and wrap modulo 2^32 inside a sufficiently long session.  The
    # reconstruction layer validates adjacency using both session and ordinal.
    if contract in {
        "pps_snapshots_v1",
        "relative_phase_observations_v1",
        "phase_estimator_outputs_v1",
    }:
        return current if current is not None else previous
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


def _check_pps_snapshot(row: dict[str, str], row_number: int, errors: list[str]) -> None:
    for field_name in (
        "session",
        "snapshot_sequence",
        "cumulative_down_counter",
        "reference_sequence",
        "status",
    ):
        value = _parse_non_negative_int(row.get(field_name, ""), field_name, row_number, errors)
        if value is not None and value > 0xFFFFFFFF:
            errors.append(
                f"row {row_number}: {field_name} must fit in an unsigned 32-bit integer"
            )
    if not row.get("backend"):
        errors.append(f"row {row_number}: backend must not be empty")


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


def _check_pseudo_pps_truth(row: dict[str, str], row_number: int, errors: list[str]) -> None:
    valid_events = {
        "schedule",
        "start",
        "completion",
        "abort",
        "underflow",
        "resource_fault",
    }
    event = row.get("event", "")
    if event not in valid_events:
        errors.append(f"row {row_number}: event must be one of {sorted(valid_events)}")
    for field_name in (
        "generator_session",
        "profile_version",
        "generator_sequence",
        "scheduled_offset_us",
        "scheduled_interval_us",
        "pulse_width_us",
    ):
        _parse_non_negative_int(row.get(field_name, ""), field_name, row_number, errors)
    for field_name in ("profile_id", "intended_class"):
        if not row.get(field_name):
            errors.append(f"row {row_number}: {field_name} must not be empty")
    if event == "schedule":
        if row.get("generator_sequence") == "0":
            errors.append(f"row {row_number}: schedule generator_sequence must be nonzero")
        if row.get("scheduled_interval_us") == "0":
            errors.append(f"row {row_number}: schedule interval must be nonzero")
    else:
        for field_name in (
            "generator_sequence",
            "scheduled_offset_us",
            "scheduled_interval_us",
            "pulse_width_us",
        ):
            if row.get(field_name) != "0":
                errors.append(f"row {row_number}: marker {field_name} must be zero")


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


def _check_diagnostics_v1(row: dict[str, str], row_number: int, errors: list[str]) -> None:
    if row.get("subsystem") not in VALID_DIAGNOSTIC_SUBSYSTEMS:
        errors.append(
            f"row {row_number}: subsystem must be one of "
            f"{sorted(VALID_DIAGNOSTIC_SUBSYSTEMS)}"
        )
    if row.get("severity") not in VALID_DIAGNOSTIC_SEVERITIES:
        errors.append(
            f"row {row_number}: severity must be one of "
            f"{sorted(VALID_DIAGNOSTIC_SEVERITIES)}"
        )
    if row.get("state") not in VALID_DIAGNOSTIC_STATES:
        errors.append(
            f"row {row_number}: state must be one of {sorted(VALID_DIAGNOSTIC_STATES)}"
        )
    if row.get("transition") not in VALID_DIAGNOSTIC_TRANSITIONS:
        errors.append(
            f"row {row_number}: transition must be one of "
            f"{sorted(VALID_DIAGNOSTIC_TRANSITIONS)}"
        )
    confidence = row.get("diagnostic_confidence", "")
    if confidence != "unknown":
        parsed_confidence = _parse_optional_float(
            confidence, "diagnostic_confidence", row_number, errors
        )
        if parsed_confidence is None or not 0.0 <= parsed_confidence <= 1.0:
            errors.append(
                f"row {row_number}: diagnostic_confidence must be between "
                "0.0 and 1.0 or 'unknown'"
            )
    first_seen = _parse_non_negative_int(
        row.get("first_seen_ticks", ""), "first_seen_ticks", row_number, errors
    )
    last_seen = _parse_non_negative_int(
        row.get("last_seen_ticks", ""), "last_seen_ticks", row_number, errors
    )
    if first_seen is not None and last_seen is not None and last_seen < first_seen:
        errors.append(
            f"row {row_number}: last_seen_ticks must be greater than or equal "
            "to first_seen_ticks"
        )
    _check_required_text(
        row,
        row_number,
        errors,
        (
            "diagnostic_id",
            "episode_id",
            "reason_code",
            "persistence_state",
            "first_evidence_refs",
            "latest_evidence_refs",
            "algorithm_version",
            "config_hash",
        ),
    )
    if row.get("persistence_state") not in VALID_PERSISTENCE_STATES:
        errors.append(
            f"row {row_number}: persistence_state must be one of "
            f"{sorted(VALID_PERSISTENCE_STATES)}"
        )
    _parse_non_negative_int(
        row.get("occurrence_count", ""),
        "occurrence_count",
        row_number,
        errors,
    )
    for field_name in (
        "observation_effect",
        "reference_effect",
        "model_effect",
        "control_effect",
    ):
        if row.get(field_name) not in VALID_DIAGNOSTIC_EFFECTS:
            errors.append(
                f"row {row_number}: {field_name} must be one of "
                f"{sorted(VALID_DIAGNOSTIC_EFFECTS)}"
            )
    is_clear = row.get("transition") == "cleared"
    if is_clear and not row.get("clear_reason_code"):
        errors.append(
            f"row {row_number}: cleared transition requires clear_reason_code"
        )
    if not is_clear and row.get("clear_reason_code"):
        errors.append(
            f"row {row_number}: clear_reason_code is only valid for cleared transitions"
        )
    if row.get("subsystem") == "service_plane" and row.get("reference_effect") not in {
        "none",
        "unknown",
    }:
        errors.append(
            f"row {row_number}: service-plane diagnostics must not redefine reference truth"
        )


def _check_reference_observation_v1(
    row: dict[str, str], row_number: int, errors: list[str]
) -> None:
    _check_required_text(
        row,
        row_number,
        errors,
        (
            "reference_observation_id",
            "source_identity_epoch",
            "source_reference_refs",
            "source_metadata_refs",
            "qualification_reason_codes",
            "algorithm_version",
            "config_hash",
        ),
    )
    for field_name in ("source_reference_first_seq", "source_reference_last_seq"):
        if row.get(field_name):
            _parse_non_negative_int(row[field_name], field_name, row_number, errors)
    if row.get("cadence_state") not in VALID_CADENCE_STATES:
        errors.append(
            f"row {row_number}: cadence_state must be one of {sorted(VALID_CADENCE_STATES)}"
        )
    if row.get("capture_path_state") not in VALID_CAPTURE_PATH_STATES:
        errors.append(
            f"row {row_number}: capture_path_state must be one of "
            f"{sorted(VALID_CAPTURE_PATH_STATES)}"
        )
    if row.get("receiver_authority_state") not in VALID_REFERENCE_AUTHORITY_STATES:
        errors.append(
            f"row {row_number}: receiver_authority_state must be one of "
            f"{sorted(VALID_REFERENCE_AUTHORITY_STATES)}"
        )
    if row.get("utc_traceability_state") not in VALID_UTC_TRACEABILITY_STATES:
        errors.append(
            f"row {row_number}: utc_traceability_state must be one of "
            f"{sorted(VALID_UTC_TRACEABILITY_STATES)}"
        )
    if row.get("metadata_freshness") not in VALID_METADATA_FRESHNESS:
        errors.append(
            f"row {row_number}: metadata_freshness must be one of "
            f"{sorted(VALID_METADATA_FRESHNESS)}"
        )
    if row.get("qualification_state") not in VALID_REFERENCE_QUALIFICATION_STATES:
        errors.append(
            f"row {row_number}: qualification_state must be one of "
            f"{sorted(VALID_REFERENCE_QUALIFICATION_STATES)}"
        )
    for field_name in (
        "sawtooth_correction_ns",
        "cable_delay_ns",
        "reference_standard_uncertainty_s",
    ):
        value = _parse_optional_float(row.get(field_name), field_name, row_number, errors)
        if field_name == "reference_standard_uncertainty_s" and value is not None and value < 0:
            errors.append(
                f"row {row_number}: reference_standard_uncertainty_s must be non-negative"
            )
    if (
        row.get("cadence_state") == "valid"
        and row.get("receiver_authority_state") in {"unknown", "unavailable"}
        and row.get("qualification_state") == "qualified"
    ):
        errors.append(
            f"row {row_number}: valid cadence alone must not qualify reference authority"
        )
    if row.get("qualification_state") == "qualified":
        required = {
            "cadence_state": "valid",
            "capture_path_state": "valid",
            "receiver_authority_state": "qualified",
            "utc_traceability_state": "valid",
            "metadata_freshness": "current",
        }
        mismatched = [
            field_name
            for field_name, expected in required.items()
            if row.get(field_name) != expected
        ]
        if mismatched:
            errors.append(
                f"row {row_number}: qualified reference requires evidence-backed "
                f"{', '.join(mismatched)}"
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


def _check_estimate_v2(row: dict[str, str], row_number: int, errors: list[str]) -> None:
    _check_estimate_v1(row, row_number, errors)
    status = row.get("uncertainty_status")
    if status not in VALID_UNCERTAINTY_STATUS:
        errors.append(
            f"row {row_number}: uncertainty_status must be one of "
            f"{sorted(VALID_UNCERTAINTY_STATUS)}"
        )
    _check_required_text(
        row,
        row_number,
        errors,
        ("uncertainty_reason_codes", "correlation_policy", "uncertainty_model_ref"),
    )
    component_fields = (
        "count_quantization_standard_uncertainty_hz",
        "counter_aperture_standard_uncertainty_hz",
        "reference_standard_uncertainty_hz",
        "calibration_standard_uncertainty_hz",
        "model_standard_uncertainty_hz",
        "combined_standard_uncertainty_hz",
        "expanded_uncertainty_hz",
    )
    parsed_components: dict[str, float | None] = {}
    for field_name in component_fields:
        value = _parse_optional_float(row.get(field_name), field_name, row_number, errors)
        parsed_components[field_name] = value
        if value is not None and value < 0:
            errors.append(f"row {row_number}: {field_name} must be non-negative")
    coverage = _parse_optional_float(
        row.get("coverage_factor"), "coverage_factor", row_number, errors
    )
    if coverage is not None and coverage <= 0:
        errors.append(f"row {row_number}: coverage_factor must be positive")
    combined = row.get("combined_standard_uncertainty_hz", "")
    if status == "available" and not combined:
        errors.append(
            f"row {row_number}: available uncertainty requires combined_standard_uncertainty_hz"
        )
    if status != "available" and combined:
        errors.append(
            f"row {row_number}: incomplete or unavailable uncertainty must not claim a combined value"
        )
    if row.get("expanded_uncertainty_hz") and not (
        combined and row.get("coverage_factor")
    ):
        errors.append(
            f"row {row_number}: expanded uncertainty requires combined uncertainty and coverage factor"
        )
    policy = row.get("correlation_policy")
    if policy not in VALID_CORRELATION_POLICIES:
        errors.append(
            f"row {row_number}: correlation_policy must be one of "
            f"{sorted(VALID_CORRELATION_POLICIES)}"
        )
    available_components = [
        value
        for field_name, value in parsed_components.items()
        if field_name
        not in {"combined_standard_uncertainty_hz", "expanded_uncertainty_hz"}
        and value is not None
    ]
    combined_value = parsed_components["combined_standard_uncertainty_hz"]
    expanded_value = parsed_components["expanded_uncertainty_hz"]
    if status == "available":
        if row.get("uncertainty_reason_codes") != "uncertainty_complete":
            errors.append(
                f"row {row_number}: available uncertainty requires "
                "uncertainty_reason_codes=uncertainty_complete"
            )
        if row.get("uncertainty_model_ref", "").startswith("unavailable:"):
            errors.append(
                f"row {row_number}: available uncertainty requires an "
                "evidence-backed uncertainty model reference"
            )
        if policy == "single_component_no_correlation":
            if len(available_components) != 1 or (
                combined_value is not None
                and not math.isclose(
                    combined_value,
                    available_components[0],
                    rel_tol=1e-9,
                    abs_tol=1e-12,
                )
            ):
                errors.append(
                    f"row {row_number}: single-component uncertainty must "
                    "equal its only component"
                )
        elif policy == "independent_root_sum_square":
            expected = math.sqrt(
                sum(value * value for value in available_components)
            )
            if len(available_components) < 2 or (
                combined_value is not None
                and not math.isclose(
                    combined_value, expected, rel_tol=1e-9, abs_tol=1e-12
                )
            ):
                errors.append(
                    f"row {row_number}: independent uncertainty must be the "
                    "root-sum-square of at least two components"
                )
        else:
            errors.append(
                f"row {row_number}: available uncertainty requires an "
                "implemented correlation policy"
            )
    elif policy != "not_combined_missing_components":
        errors.append(
            f"row {row_number}: incomplete or unavailable uncertainty must "
            "declare not_combined_missing_components"
        )
    if status != "available" and (
        coverage is not None or expanded_value is not None
    ):
        errors.append(
            f"row {row_number}: incomplete or unavailable uncertainty must "
            "not claim coverage or expanded uncertainty"
        )
    if (
        expanded_value is not None
        and combined_value is not None
        and coverage is not None
        and not math.isclose(
            expanded_value,
            combined_value * coverage,
            rel_tol=1e-9,
            abs_tol=1e-12,
        )
    ):
        errors.append(
            f"row {row_number}: expanded uncertainty must equal combined "
            "uncertainty multiplied by coverage_factor"
        )


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


def _check_active_transaction_v1(
    row: dict[str, str], row_number: int, errors: list[str]
) -> None:
    _check_required_text(
        row,
        row_number,
        errors,
        (
            "event",
            "run_identity",
            "build_identity",
            "profile_identity",
            "active_state",
            "response_class",
            "reason",
            "estimator_sha256",
            "model_sha256",
            "active_policy_sha256",
            "response_policy_sha256",
            "numerical_policy_sha256",
            "evidence_state",
        ),
    )
    event = row.get("event")
    if event not in VALID_ACTIVE_TRANSACTION_EVENTS:
        errors.append(
            f"row {row_number}: event must be one of {sorted(VALID_ACTIVE_TRANSACTION_EVENTS)}"
        )
    if row.get("active_state") not in VALID_ACTIVE_STATES:
        errors.append(
            f"row {row_number}: active_state must be one of {sorted(VALID_ACTIVE_STATES)}"
        )
    if row.get("response_class") not in VALID_ACTIVE_RESPONSE_CLASSES:
        errors.append(
            f"row {row_number}: response_class must be one of "
            f"{sorted(VALID_ACTIVE_RESPONSE_CLASSES)}"
        )
    if row.get("evidence_state") not in VALID_ACTIVE_EVIDENCE_STATES:
        errors.append(
            f"row {row_number}: evidence_state must be one of "
            f"{sorted(VALID_ACTIVE_EVIDENCE_STATES)}"
        )
    for field_name in (
        "i2c_ok",
        "clamped",
        "ambiguous",
        "estimator_history_reset",
        "actionable",
    ):
        _check_boolean_text(row, field_name, row_number, errors)
    if row.get("actionable") != "false":
        errors.append(
            f"row {row_number}: serialized transaction evidence must never be actionable"
        )

    for field_name in (
        "session_id",
        "authorization_sequence",
        "nonce",
        "request_sequence",
        "decision_sequence",
        "source_first_sequence",
        "source_last_sequence",
        "decision_timestamp_s",
        "current_applied_code",
        "requested_code",
        "correction_ordinal",
        "cumulative_after_codes",
        "accepted_code",
        "accepted_timestamp_s",
        "applied_code",
        "application_sequence",
        "application_timestamp_s",
        "dac_epoch",
        "correction_count",
        "cumulative_movement_codes",
        "consecutive_indeterminate",
    ):
        _parse_non_negative_int(row.get(field_name, ""), field_name, row_number, errors)
    _parse_int(row.get("requested_delta_codes", ""), "requested_delta_codes", row_number, errors)
    for field_name in (
        "pre_error_hz",
        "post_error_hz",
        "observed_response_hz",
        "cumulative_response_hz",
    ):
        _parse_optional_float(row.get(field_name), field_name, row_number, errors)

    for field_name in (
        "estimator_sha256",
        "model_sha256",
        "active_policy_sha256",
        "response_policy_sha256",
        "numerical_policy_sha256",
    ):
        value = row.get(field_name, "")
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            errors.append(f"row {row_number}: {field_name} must be a lowercase SHA-256")

    request_sequence = _parse_non_negative_int(
        row.get("request_sequence", ""), "request_sequence", row_number, []
    )
    if event == "manual_start":
        if request_sequence != 0 or row.get("evidence_state") != "evidence_clear":
            errors.append(
                f"row {row_number}: manual_start must have request_sequence=0 and evidence_clear"
            )
    else:
        if request_sequence in (None, 0):
            errors.append(f"row {row_number}: {event} requires a non-zero request_sequence")
        expected_evidence = {
            "request_created": "request_pending",
            "core0_accepted": "acceptance_pending",
            "request_accepted": "request_pending",
            "application": "application_pending",
            "application_fault": "application_pending",
            "response": "response_pending",
        }.get(event)
        if expected_evidence and row.get("evidence_state") != expected_evidence:
            errors.append(
                f"row {row_number}: {event} requires evidence_state={expected_evidence}"
            )
    if event == "request_created" and row.get("active_state") != "REQUEST_PENDING":
        errors.append(
            f"row {row_number}: request_created requires REQUEST_PENDING"
        )
    if event in {"request_accepted", "core0_accepted"} and row.get("active_state") != "ACCEPTED_AWAITING_APPLICATION":
        errors.append(
            f"row {row_number}: {event} requires ACCEPTED_AWAITING_APPLICATION"
        )
    if event == "application" and (
        row.get("i2c_ok") != "true"
        or row.get("clamped") != "false"
        or row.get("ambiguous") != "false"
        or row.get("estimator_history_reset") != "true"
    ):
        errors.append(
            f"row {row_number}: application requires exact I2C success and estimator reset"
        )
    if event == "response" and row.get("response_class") == "unavailable":
        errors.append(f"row {row_number}: response requires a response classification")


def _check_sha256(row: dict[str, str], field_name: str, row_number: int, errors: list[str]) -> None:
    value = row.get(field_name, "")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        errors.append(f"row {row_number}: {field_name} must be a lowercase SHA-256")


def _check_rph_source_identity(row: dict[str, str], row_number: int, errors: list[str]) -> None:
    """Allow only the live RPH sentinel until the raw serial file is sealed."""
    if row.get("source_file_sha256") != "live_stream_unsealed":
        _check_sha256(row, "source_file_sha256", row_number, errors)


def _check_relative_phase_observation_v1(
    row: dict[str, str], row_number: int, errors: list[str]
) -> None:
    _check_required_text(
        row,
        row_number,
        errors,
        (
            "source_backend",
            "source_file_sha256",
            "method_id",
            "configuration_sha256",
            "qualification_state",
            "calibrated_uncertainty_status",
        ),
    )
    for field_name in (
        "phase_epoch",
        "observation_sequence",
        "capture_session",
        "opening_snapshot_sequence",
        "closing_snapshot_sequence",
        "opening_reference_sequence",
        "closing_reference_sequence",
        "dac_epoch",
    ):
        _parse_non_negative_int(row.get(field_name, ""), field_name, row_number, errors)
    for field_name in ("interval_edges", "edge_error_cycles", "relative_phase_cycles"):
        if row.get(field_name):
            _parse_int(row[field_name], field_name, row_number, errors)
    for field_name in ("relative_phase_time_ns", "observation_age_s"):
        value = _parse_optional_float(row.get(field_name), field_name, row_number, errors)
        if field_name == "observation_age_s" and value is not None and value < 0:
            errors.append(f"row {row_number}: observation_age_s must be non-negative")
    if row.get("qualification_state") not in VALID_RELATIVE_PHASE_QUALIFICATION_STATES:
        errors.append(
            f"row {row_number}: qualification_state must be one of "
            f"{sorted(VALID_RELATIVE_PHASE_QUALIFICATION_STATES)}"
        )
    if row.get("calibrated_uncertainty_status") not in VALID_CALIBRATED_UNCERTAINTY_STATUS:
        errors.append(
            f"row {row_number}: calibrated_uncertainty_status must be one of "
            f"{sorted(VALID_CALIBRATED_UNCERTAINTY_STATUS)}"
        )
    _check_rph_source_identity(row, row_number, errors)
    _check_sha256(row, "configuration_sha256", row_number, errors)
    accepted = row.get("qualification_state") == "qualified"
    interval_fields = ("interval_edges", "edge_error_cycles")
    if accepted and any(not row.get(field_name) for field_name in interval_fields):
        errors.append(f"row {row_number}: qualified RPH requires interval_edges and edge_error_cycles")
    if not accepted and any(row.get(field_name) for field_name in interval_fields):
        errors.append(f"row {row_number}: non-qualified RPH must not claim interval edge values")
    if not accepted and not row.get("discontinuity_reason"):
        errors.append(f"row {row_number}: non-qualified RPH requires discontinuity_reason")


def _check_phase_estimator_output_v1(
    row: dict[str, str], row_number: int, errors: list[str]
) -> None:
    _check_required_text(
        row,
        row_number,
        errors,
        (
            "source_relative_phase_observation",
            "estimator_id",
            "configuration_sha256",
            "qualification_state",
            "uncertainty_status",
            "reason_codes",
        ),
    )
    for field_name in ("phase_epoch", "observation_sequence"):
        _parse_non_negative_int(row.get(field_name, ""), field_name, row_number, errors)
    _parse_int(
        row.get("raw_relative_phase_cycles", ""),
        "raw_relative_phase_cycles",
        row_number,
        errors,
    )
    for field_name in (
        "raw_relative_phase_time_ns",
        "filtered_relative_phase_cycles",
        "estimated_frequency_error_hz",
        "estimate_age_s",
    ):
        value = _parse_optional_float(row.get(field_name), field_name, row_number, errors)
        if field_name == "estimate_age_s" and value is not None and value < 0:
            errors.append(f"row {row_number}: estimate_age_s must be non-negative")
    if row.get("qualification_state") not in VALID_PHASE_ESTIMATOR_QUALIFICATION_STATES:
        errors.append(
            f"row {row_number}: qualification_state must be one of "
            f"{sorted(VALID_PHASE_ESTIMATOR_QUALIFICATION_STATES)}"
        )
    if row.get("uncertainty_status") not in VALID_UNCERTAINTY_STATUS:
        errors.append(
            f"row {row_number}: uncertainty_status must be one of "
            f"{sorted(VALID_UNCERTAINTY_STATUS)}"
        )
    _check_sha256(row, "configuration_sha256", row_number, errors)
    expected_source = (
        f"RPH:{row.get('phase_epoch', '')}:{row.get('observation_sequence', '')}"
    )
    if row.get("source_relative_phase_observation") != expected_source:
        errors.append(
            f"row {row_number}: source_relative_phase_observation must equal "
            f"{expected_source}"
        )
    for field_name in (
        "raw_relative_phase_time_ns",
        "filtered_relative_phase_cycles",
    ):
        if not row.get(field_name):
            errors.append(f"row {row_number}: {field_name} is required")
    frequency_available = bool(row.get("estimated_frequency_error_hz"))
    if row.get("qualification_state") == "qualified":
        if not frequency_available or not row.get("estimate_age_s"):
            errors.append(
                f"row {row_number}: qualified PHE requires frequency and age"
            )
    elif frequency_available or row.get("estimate_age_s"):
        errors.append(
            f"row {row_number}: non-qualified PHE must not claim frequency or age"
        )


def _check_hybrid_preview_decision_v1(
    row: dict[str, str], row_number: int, errors: list[str]
) -> None:
    _check_required_text(
        row,
        row_number,
        errors,
        (
            "candidate_id",
            "candidate_configuration_sha256",
            "phase_estimator_id",
            "phase_estimator_configuration_sha256",
            "frequency_estimator_id",
            "frequency_estimator_configuration_sha256",
            "configuration_sha256",
            "time_domain",
            "source_phase_estimate",
            "source_frequency_estimate",
            "band_state_before",
            "band_state_after",
            "preview_state",
            "decision_reason",
            "uncertainty_status",
        ),
    )
    for field_name in (
        "phase_epoch",
        "observation_sequence",
        "dac_epoch",
        "decision_timestamp_ticks",
        "actual_applied_code",
        "shadow_code_before",
        "shadow_code_after",
        "correction_count",
        "cumulative_movement_codes",
        "alternating_correction_count",
    ):
        _parse_non_negative_int(row.get(field_name, ""), field_name, row_number, errors)
    if row.get("counterfactual_code"):
        _parse_non_negative_int(
            row["counterfactual_code"], "counterfactual_code", row_number, errors
        )
    _parse_int(
        row.get("raw_relative_phase_cycles", ""),
        "raw_relative_phase_cycles",
        row_number,
        errors,
    )
    for field_name in (
        "modeled_relative_phase_cycles",
        "observed_frequency_error_hz",
        "modeled_frequency_error_hz",
        "frequency_term_hz",
        "phase_bias_hz",
        "combined_frequency_error_hz",
        "raw_counterfactual_delta_codes",
        "counterfactual_delta_codes",
    ):
        _parse_optional_float(row.get(field_name), field_name, row_number, errors)
    for field_name in (
        "frequency_observation_event",
        "counterfactual_decision",
        "counterfactual_correction",
        "step_limited",
        "range_clamped",
        "modeled_not_observed_after_divergence",
        "actionable",
        "actuation_authorized",
        "authorization_consumed",
    ):
        _check_boolean_text(row, field_name, row_number, errors)
    if row.get("preview_state") not in VALID_HYBRID_PREVIEW_STATES:
        errors.append(
            f"row {row_number}: preview_state must be one of "
            f"{sorted(VALID_HYBRID_PREVIEW_STATES)}"
        )
    for field_name in ("band_state_before", "band_state_after"):
        if row.get(field_name) not in VALID_HYBRID_BAND_STATES:
            errors.append(
                f"row {row_number}: {field_name} must be one of "
                f"{sorted(VALID_HYBRID_BAND_STATES)}"
            )
    if row.get("uncertainty_status") not in VALID_UNCERTAINTY_STATUS:
        errors.append(
            f"row {row_number}: uncertainty_status must be one of "
            f"{sorted(VALID_UNCERTAINTY_STATUS)}"
        )
    for field_name in (
        "candidate_configuration_sha256",
        "phase_estimator_configuration_sha256",
        "frequency_estimator_configuration_sha256",
        "configuration_sha256",
    ):
        _check_sha256(row, field_name, row_number, errors)
    for field_name in ("actionable", "actuation_authorized", "authorization_consumed"):
        if row.get(field_name) != "false":
            errors.append(f"row {row_number}: {field_name} must remain false for CX318 HPR")
    expected_phase_source = (
        f"PHE:{row.get('phase_epoch', '')}:{row.get('observation_sequence', '')}"
    )
    if row.get("source_phase_estimate") != expected_phase_source:
        errors.append(
            f"row {row_number}: source_phase_estimate must equal "
            f"{expected_phase_source}"
        )
    frequency_fields = (
        "observed_frequency_error_hz",
        "modeled_frequency_error_hz",
        "frequency_term_hz",
        "combined_frequency_error_hz",
    )
    frequency_available = bool(row.get("observed_frequency_error_hz"))
    if any(bool(row.get(field_name)) != frequency_available for field_name in frequency_fields):
        errors.append(
            f"row {row_number}: HPR frequency values must be all present or all empty"
        )
    expected_frequency_source = expected_phase_source if frequency_available else "unavailable"
    if row.get("source_frequency_estimate") != expected_frequency_source:
        errors.append(
            f"row {row_number}: source_frequency_estimate must equal "
            f"{expected_frequency_source}"
        )
    try:
        counterfactual_code = int(row.get("counterfactual_code", ""), 10)
        shadow_code_after = int(row.get("shadow_code_after", ""), 10)
        if counterfactual_code != shadow_code_after:
            errors.append(
                f"row {row_number}: counterfactual_code must equal shadow_code_after"
            )
    except (TypeError, ValueError):
        pass
    try:
        shadow_code_before = int(row.get("shadow_code_before", ""), 10)
        shadow_code_after = int(row.get("shadow_code_after", ""), 10)
        counterfactual_delta = row.get("counterfactual_delta_codes", "")
        if counterfactual_delta and not math.isclose(
            float(counterfactual_delta),
            shadow_code_after - shadow_code_before,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            errors.append(
                f"row {row_number}: counterfactual_delta_codes must equal "
                "shadow_code_after-shadow_code_before"
            )
        actual_applied_code = int(row.get("actual_applied_code", ""), 10)
        modeled_divergence = row.get("modeled_not_observed_after_divergence")
        expected_divergence = shadow_code_after != actual_applied_code
        if modeled_divergence in VALID_BOOLEAN_TEXT and (
            (modeled_divergence == "true") != expected_divergence
        ):
            errors.append(
                f"row {row_number}: modeled_not_observed_after_divergence must "
                "equal shadow_code_after != actual_applied_code"
            )
    except (TypeError, ValueError):
        pass
    if row.get("counterfactual_decision") == "false":
        for field_name in (
            "raw_counterfactual_delta_codes",
            "counterfactual_delta_codes",
        ):
            if row.get(field_name):
                errors.append(
                    f"row {row_number}: {field_name} must be empty without a "
                    "counterfactual decision"
                )


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
            if context.contract == "pps_snapshots_v1":
                _check_pps_snapshot(row, row_count, errors)
            if context.contract == "health_v1":
                _check_health(row, row_count, errors)
            if context.contract == "dac_steps_v1":
                _check_dac_step(row, row_count, errors)
            if context.contract == "environment_v1":
                _check_environment(row, row_count, errors)
            if context.contract == "pseudo_pps_truth_v1":
                _check_pseudo_pps_truth(row, row_count, errors)
            if context.contract == "diagnostics_draft_v0":
                _check_diagnostics_draft_v0(row, row_count, errors)
            if context.contract == "diagnostics_v1":
                _check_diagnostics_v1(row, row_count, errors)
            if context.contract == "reference_observations_v1":
                _check_reference_observation_v1(row, row_count, errors)
            if context.contract == "estimates_v1":
                _check_estimate_v1(row, row_count, errors)
            if context.contract == "estimates_v2":
                _check_estimate_v2(row, row_count, errors)
            if context.contract == "control_previews_v1":
                _check_control_preview_v1(row, row_count, errors)
            if context.contract == "active_transactions_v1":
                _check_active_transaction_v1(row, row_count, errors)
            if context.contract == "relative_phase_observations_v1":
                _check_relative_phase_observation_v1(row, row_count, errors)
            if context.contract == "phase_estimator_outputs_v1":
                _check_phase_estimator_output_v1(row, row_count, errors)
            if context.contract == "hybrid_preview_decisions_v1":
                _check_hybrid_preview_decision_v1(row, row_count, errors)

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
