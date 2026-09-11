from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import csv
import math
import re

from .time_domains import forward_progress, time_domain
from .firmware_host_contract import (
    RECORD_FIELDS as AUTHORITY_RECORD_FIELDS,
    RECORD_SCHEMA_VERSIONS as AUTHORITY_RECORD_SCHEMA_VERSIONS,
    RECORD_TYPES as AUTHORITY_RECORD_TYPES,
    RECORDS as FIRMWARE_HOST_RECORDS,
    integer_projection_matches,
    validate_record_wire_values,
)


CURRENT_PLANT_MODEL_PATH = (
    Path(__file__).resolve().parents[2]
    / "profiles/plant_models/pps_gated_oscillator_plant_v1.json"
)
CURRENT_PLANT_MODEL_REF = "model:pps_gated_oscillator_plant_v1"
CURRENT_PLANT_MODEL_ID = "OTIS_PPS_GATED_OSCILLATOR_PLANT_V1"


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

# D6 is a locally wired observation of the forwarded D9 output.  It is
# intentionally a separate raw contract from the authoritative D8 SNP stream:
# monitor loss, noise, or absence must never be reinterpreted as a D14/D8
# capture, validity, steering, or terminal condition.
FORWARDED_MONITOR_SNAPSHOT_FIELDS = [
    "record_type",
    "schema_version",
    "session",
    "reference_session",
    "snapshot_sequence",
    "cumulative_down_counter",
    "reference_sequence",
    "reference_timestamp_ticks",
    "status",
    "backend",
    "channel_id",
]

ASSOCIATION_LOSS_DECISION_V1_FIELDS = [
    "record_type",
    "schema_version",
    "decision_sequence",
    "reason",
    "classification",
    "decision_ticks",
    "pending_reference_sequence",
    "pending_reference_ticks",
    "pending_age_ticks",
    "boundary_depth",
    "boundary_dropped_count",
    "next_reference_present",
    "next_reference_sequence",
    "next_reference_ticks",
    "snapshot_initialized",
    "snapshot_running",
    "snapshot_fault_latched",
    "snapshot_fault_flags",
    "snapshot_session",
    "snapshot_producer_ordinal",
    "snapshot_consumer_ordinal",
    "snapshot_backlog_depth",
    "snapshot_backlog_high_water",
    "snapshot_overwrite_count",
    "snapshot_continuity_loss_count",
    "snapshot_pio_rxstall_count",
    "snapshot_dma_error_count",
    "snapshot_dma_stopped_count",
    "core1_loop_sequence",
    "core1_last_snapshot_session",
    "core1_last_snapshot_sequence",
    "core1_phase",
    "core1_phase_enter_ticks",
    "core1_last_progress_ticks",
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

ESTIMATE_COMMON_FIELDS = [
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
    *ESTIMATE_COMMON_FIELDS[:30],
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
    *ESTIMATE_COMMON_FIELDS[32:],
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

ACTIVE_TRANSACTION_V2_FIELDS = [
    "record_type",
    "schema_version",
    "transaction_record_sequence",
    "event",
    "event_timestamp_ticks",
    "time_domain",
    "run_identity",
    "build_identity",
    "image_identity",
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

ACTIVE_HYBRID_DECISION_V2_FIELDS = [
    "record_type",
    "schema_version",
    "hybrid_record_sequence",
    "decision_sequence",
    "decision_timestamp_ticks",
    "time_domain",
    "decision_timestamp_s",
    "run_identity",
    "build_identity",
    "image_identity",
    "capture_session",
    "source_first_sequence",
    "source_last_sequence",
    "frequency_estimator_sha256",
    "frequency_error_hz",
    "accumulated_edge_error_counts",
    "tight_state",
    "phase_estimator_sha256",
    "phase_epoch",
    "phase_observation_sequence",
    "relative_phase_cycles",
    "phase_continuous",
    "phase_current",
    "phase_step_detected",
    "phase_recorder_published",
    "current_applied_code",
    "dac_epoch",
    "phase_applied_code",
    "phase_dac_epoch",
    "state_before",
    "state_after",
    "frequency_term_hz",
    "phase_term_hz",
    "combined_demand_hz",
    "raw_combined_delta_codes",
    "requested_delta_codes",
    "requested_code",
    "counterfactual_frequency_only_delta_codes",
    "phase_materially_influenced",
    "step_limited",
    "range_clamped",
    "cadence_limited",
    "count_limited",
    "cumulative_budget_limited",
    "correction_count_before",
    "cumulative_movement_before_codes",
    "authority_state",
    "request_sequence",
    "acceptance_sequence",
    "application_sequence",
    "response_class",
    "actual_applied_code",
    "actual_dac_epoch",
    "downstream_epoch_exact",
    "reason",
    "active_policy_sha256",
    "response_policy_sha256",
    "actionable",
]

# AHM is decision-bearing controller-state evidence. It is separate from
# AHY controller content so persistence and provenance-tagged correction debt
# remain reconstructable across request,
# application, response, GNSS-hold, and fail-static transitions.
ACTIVE_HYBRID_MAINTENANCE_V1_FIELDS = [
    "record_type",
    "schema_version",
    "maintenance_record_sequence",
    "event",
    "event_timestamp_ticks",
    "time_domain",
    "run_identity",
    "build_identity",
    "image_identity",
    "policy_id",
    "active_policy_sha256",
    "capture_session",
    "source_first_sequence",
    "source_last_sequence",
    "frequency_estimator_sha256",
    "phase_epoch",
    "phase_observation_sequence",
    "phase_valid",
    "current_applied_code",
    "current_dac_epoch",
    "hybrid_record_sequence",
    "decision_sequence",
    "transaction_record_sequence",
    "transaction_event",
    "request_sequence",
    "application_sequence",
    "actual_applied_code",
    "actual_dac_epoch",
    "downstream_epoch_exact",
    "maintenance_state_before",
    "maintenance_state_after",
    "frontier_relation",
    "interval_sign",
    "persistence_count_before",
    "persistence_count_after",
    "raw_fll_demand_picocodes",
    "raw_pll_demand_picocodes",
    "candidate_total_demand_picocodes",
    "safe_cap_codes",
    "requested_delta_codes",
    "requested_code",
    "committed_fll_debt_before_picocodes",
    "committed_pll_debt_before_picocodes",
    "committed_fll_debt_after_picocodes",
    "committed_pll_debt_after_picocodes",
    "request_pending_before",
    "request_pending_after",
    "response_pending_before",
    "response_pending_after",
    "metadata_hold_before",
    "metadata_hold_after",
    "requalification_window_count_before",
    "requalification_window_count_after",
    "requalification_d14_d8_observation_sequence",
    "evidence_burst_sequence",
    "evidence_burst_record_ordinal",
    "evidence_burst_record_count",
    "reason",
    "actionable",
]

# RPH is the immutable raw relative-phase boundary. PHE adds the selected
# retained frequency support without authority or an actuator request.
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

TIGHT_DEADBAND_DECISION_V1_FIELDS = [
    "record_type",
    "schema_version",
    "decision_sequence",
    "estimate_id",
    "decision_timestamp_ticks",
    "time_domain",
    "capture_session",
    "dac_epoch",
    "integer_edge_error_counts",
    "absolute_edge_error_counts",
    "state_before",
    "state_after",
    "entry_counter",
    "release_counter",
    "transition",
    "frequency_controller_eligible",
    "requalified",
    "requalification_reason",
    "three_count_band_inside",
    "two_count_band_inside",
    "policy_id",
    "policy_sha256",
    "actionable",
    "actuation_authorized",
    "authorization_consumed",
    "reason_codes",
]

CONTRACT_FIELDS = {
    "raw_events_v1": RAW_EVENT_FIELDS,
    "count_observations_v1": COUNT_OBSERVATION_FIELDS,
    "pps_snapshots_v1": PPS_SNAPSHOT_FIELDS,
    "forwarded_monitor_snapshots_v1": FORWARDED_MONITOR_SNAPSHOT_FIELDS,
    "association_loss_decisions_v1": ASSOCIATION_LOSS_DECISION_V1_FIELDS,
    "health_v1": HEALTH_FIELDS,
    "dac_steps_v1": DAC_STEP_FIELDS,
    "environment_v1": ENVIRONMENT_FIELDS,
    "estimates_v2": ESTIMATE_V2_FIELDS,
    "control_previews_v1": CONTROL_PREVIEW_V1_FIELDS,
    "active_transactions_v2": ACTIVE_TRANSACTION_V2_FIELDS,
    "active_hybrid_decisions_v2": ACTIVE_HYBRID_DECISION_V2_FIELDS,
    "active_hybrid_maintenance_v1": ACTIVE_HYBRID_MAINTENANCE_V1_FIELDS,
    "relative_phase_observations_v1": RELATIVE_PHASE_OBSERVATION_V1_FIELDS,
    "phase_estimator_outputs_v1": PHASE_ESTIMATOR_OUTPUT_V1_FIELDS,
    "tight_deadband_decisions_v1": TIGHT_DEADBAND_DECISION_V1_FIELDS,
}

CONTRACT_RECORD_TYPES = {
    "raw_events_v1": {"EVT", "REF"},
    "count_observations_v1": {"CNT"},
    "pps_snapshots_v1": {"SNP"},
    "forwarded_monitor_snapshots_v1": {"MNS"},
    "association_loss_decisions_v1": {"ASL"},
    "health_v1": {"STS"},
    "dac_steps_v1": {"DAC"},
    "environment_v1": {"ENV"},
    "estimates_v2": {"EST"},
    "control_previews_v1": {"CTL"},
    "active_transactions_v2": {"ACT"},
    "active_hybrid_decisions_v2": {"AHY"},
    "active_hybrid_maintenance_v1": {"AHM"},
    "relative_phase_observations_v1": {"RPH"},
    "phase_estimator_outputs_v1": {"PHE"},
    "tight_deadband_decisions_v1": {"TDB"},
}

CONTRACT_SCHEMA_VERSIONS = {
    "raw_events_v1": 1,
    "count_observations_v1": 1,
    "pps_snapshots_v1": 1,
    "forwarded_monitor_snapshots_v1": 1,
    "association_loss_decisions_v1": 1,
    "health_v1": 1,
    "dac_steps_v1": 1,
    "environment_v1": 1,
    "estimates_v2": 2,
    "control_previews_v1": 1,
    "active_transactions_v2": 2,
    "active_hybrid_decisions_v2": 2,
    "active_hybrid_maintenance_v1": 1,
    "relative_phase_observations_v1": 1,
    "phase_estimator_outputs_v1": 1,
    "tight_deadband_decisions_v1": 1,
}

# Detailed validators remain explicit below. Their layouts and versions are
# mechanically subordinate to the current firmware/host contract authority.
if CONTRACT_FIELDS != {
    name: list(fields) for name, fields in AUTHORITY_RECORD_FIELDS.items()
}:
    raise RuntimeError(
        "host record layouts differ from otis_firmware_host_contract_v1"
    )
if CONTRACT_RECORD_TYPES != {
    name: set(record_types)
    for name, record_types in AUTHORITY_RECORD_TYPES.items()
}:
    raise RuntimeError(
        "host record tags differ from otis_firmware_host_contract_v1"
    )
if CONTRACT_SCHEMA_VERSIONS != AUTHORITY_RECORD_SCHEMA_VERSIONS:
    raise RuntimeError(
        "host schema versions differ from otis_firmware_host_contract_v1"
    )

SEQUENCE_FIELDS = {
    "raw_events_v1": "event_seq",
    "count_observations_v1": "count_seq",
    "pps_snapshots_v1": "snapshot_sequence",
    "forwarded_monitor_snapshots_v1": "snapshot_sequence",
    "association_loss_decisions_v1": "decision_sequence",
    "health_v1": "status_seq",
    "dac_steps_v1": "seq",
    "environment_v1": "env_seq",
    "estimates_v2": "estimate_seq",
    "control_previews_v1": "control_seq",
    "active_transactions_v2": "transaction_record_sequence",
    "active_hybrid_decisions_v2": "hybrid_record_sequence",
    "active_hybrid_maintenance_v1": "maintenance_record_sequence",
    "relative_phase_observations_v1": "observation_sequence",
    "phase_estimator_outputs_v1": "observation_sequence",
    "tight_deadband_decisions_v1": "decision_sequence",
}

TIMESTAMP_FIELDS = {
    "raw_events_v1": ("timestamp_ticks",),
    "count_observations_v1": ("gate_open_ticks", "gate_close_ticks"),
    "pps_snapshots_v1": ("reference_timestamp_ticks",),
    "forwarded_monitor_snapshots_v1": ("reference_timestamp_ticks",),
    "association_loss_decisions_v1": ("decision_ticks",),
    "health_v1": ("timestamp_ticks",),
    "dac_steps_v1": ("elapsed_ms",),
    "environment_v1": ("timestamp_ticks",),
    "estimates_v2": ("estimator_timestamp_ticks",),
    "control_previews_v1": ("decision_timestamp_ticks",),
    "active_transactions_v2": ("event_timestamp_ticks",),
    "active_hybrid_decisions_v2": ("decision_timestamp_ticks",),
    "active_hybrid_maintenance_v1": ("event_timestamp_ticks",),
    "relative_phase_observations_v1": (),
    "phase_estimator_outputs_v1": (),
    "tight_deadband_decisions_v1": ("decision_timestamp_ticks",),
}

CHANNEL_FIELDS = {
    "raw_events_v1": "channel_id",
    "count_observations_v1": "channel_id",
    "forwarded_monitor_snapshots_v1": "channel_id",
}

DOMAIN_FIELDS = {
    "raw_events_v1": ("capture_domain",),
    "count_observations_v1": ("gate_domain",),
    "pps_snapshots_v1": (),
    "forwarded_monitor_snapshots_v1": (),
    "association_loss_decisions_v1": (),
    "health_v1": ("status_domain",),
    "dac_steps_v1": (),
    "environment_v1": ("observation_domain",),
    "estimates_v2": ("time_domain",),
    "control_previews_v1": ("time_domain",),
    "active_transactions_v2": ("time_domain",),
    "active_hybrid_decisions_v2": ("time_domain",),
    "active_hybrid_maintenance_v1": ("time_domain",),
    "relative_phase_observations_v1": (),
    "phase_estimator_outputs_v1": (),
    "tight_deadband_decisions_v1": ("time_domain",),
}

CONTRACT_IMPLICIT_TIME_DOMAINS = {
    "pps_snapshots_v1": "rp2040_monotonic_us32",
    "forwarded_monitor_snapshots_v1": "rp2040_monotonic_us32",
    "association_loss_decisions_v1": "rp2040_monotonic_us32",
    "dac_steps_v1": "host_elapsed_ms",
}

SESSION_FIELDS = {
    "pps_snapshots_v1": "session",
    "forwarded_monitor_snapshots_v1": "session",
    "tight_deadband_decisions_v1": "capture_session",
    "active_transactions_v2": "session_id",
    "active_hybrid_decisions_v2": "capture_session",
    "active_hybrid_maintenance_v1": "capture_session",
}

if SEQUENCE_FIELDS != {
    name: str(record["sequence_field"])
    for name, record in FIRMWARE_HOST_RECORDS.items()
}:
    raise RuntimeError(
        "host sequence fields differ from otis_firmware_host_contract_v1"
    )
if TIMESTAMP_FIELDS != {
    name: tuple(record["timestamp_fields"])
    for name, record in FIRMWARE_HOST_RECORDS.items()
}:
    raise RuntimeError(
        "host timestamp fields differ from otis_firmware_host_contract_v1"
    )
if DOMAIN_FIELDS != {
    name: tuple(record["domain_fields"])
    for name, record in FIRMWARE_HOST_RECORDS.items()
}:
    raise RuntimeError(
        "host domain fields differ from otis_firmware_host_contract_v1"
    )
if CONTRACT_IMPLICIT_TIME_DOMAINS != {
    name: str(record["implicit_time_domain"])
    for name, record in FIRMWARE_HOST_RECORDS.items()
    if record["implicit_time_domain"] is not None
}:
    raise RuntimeError(
        "host implicit domains differ from otis_firmware_host_contract_v1"
    )
if SESSION_FIELDS != {
    name: str(record["session_field"])
    for name, record in FIRMWARE_HOST_RECORDS.items()
    if record["session_field"] is not None
}:
    raise RuntimeError(
        "host session fields differ from otis_firmware_host_contract_v1"
    )

FLAG_KNOWN_MASK_V1 = 0xFFFF
VALID_EDGES = {"R", "F", "B"}
VALID_SEVERITIES = {"INFO", "WARN", "ERROR", "FATAL"}
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
VALID_TIGHT_DEADBAND_STATES = {"REQUALIFY_OUTSIDE", "OUTSIDE", "TIGHT_INSIDE"}
VALID_TIGHT_DEADBAND_REASONS = {
    "invalid_or_stale_requalify",
    "tight_entry_pending",
    "tight_entry_confirmed",
    "three_count_outside_hold",
    "outside_loose_evidence",
    "loose_release_pending",
    "loose_release_confirmed",
    "three_count_inside_hold",
    "tight_inside_hold",
}
VALID_TIGHT_DEADBAND_REQUALIFICATION_REASONS = {
    "session_changed_requalify",
    "dac_epoch_changed_requalify",
}
TIGHT_DEADBAND_POLICY_ID = "OTIS_ADAPTIVE_HYBRID_REGULATION_V1"

VALID_ACTIVE_TRANSACTION_EVENTS = {
    "manual_start",
    "request_created",
    "request_withdrawn",
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
    "REFERENCE_HOLD",
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

VALID_ACTIVE_HYBRID_STATES = {
    "FREQUENCY_ACQUIRE",
    "PHASE_QUALIFY",
    "FIRST_PHASE_TRANSACTION",
    "HYBRID_TRACKING",
    "PHASE_DEGRADED_FREQUENCY_ONLY",
    "FAIL_STATIC",
}

ADAPTIVE_HYBRID_MAINTENANCE_POLICY_ID = "OTIS_ADAPTIVE_HYBRID_REGULATION_V1"
MAX_COMMITTED_DEBT_PICOCODES = 500_000_000_000
VALID_ACTIVE_HYBRID_MAINTENANCE_EVENTS = {
    "policy_activation",
    "decision",
    "request_rejected_or_expired",
    "application_first_consumer",
    "response_complete",
    "gnss_metadata_hold_enter",
    "gnss_metadata_requalified",
    "fail_static",
}
VALID_ACTIVE_HYBRID_MAINTENANCE_STATES = {
    "POLICY_INACTIVE",
    "READY",
    "PERSISTENCE_HOLD",
    "REQUEST_PENDING",
    "RESPONSE_PENDING",
    "METADATA_HOLD",
    "FAIL_STATIC",
}
VALID_ACTIVE_HYBRID_MAINTENANCE_FRONTIERS = {
    "not_applicable",
    "first",
    "contiguous",
    "overlap",
    "gap",
}
VALID_ACTIVE_HYBRID_MAINTENANCE_TRANSACTION_EVENTS = {
    "none",
    "request_created",
    "request_withdrawn",
    "application",
    "application_fault",
    "response",
}


@dataclass(frozen=True)
class CsvValidationContext:
    contract: str
    known_channels: frozenset[int]
    known_domains: frozenset[str]
    template: bool = False
    # True only when run-level evidence independently establishes multiple
    # capture sessions in this CSV. Sequence resets remain reportable, while
    # domain progression restarts at that same boundary.
    segmented_capture: bool = False
    # Run-level replay supplies the hash from its frozen authoritative input
    # set. Standalone syntax validation has no authority to consult live files.
    expected_policy_sha256: str | None = None


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
        "forwarded_monitor_snapshots_v1",
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
    domain: str,
) -> None:
    parsed: dict[str, int] = {}
    for field_name in TIMESTAMP_FIELDS[contract]:
        value = _parse_non_negative_int(row.get(field_name, ""), field_name, row_number, errors)
        if value is not None:
            parsed[field_name] = value
    if contract == "count_observations_v1" and {"gate_open_ticks", "gate_close_ticks"} <= parsed.keys():
        try:
            progress = forward_progress(
                parsed["gate_open_ticks"],
                parsed["gate_close_ticks"],
                domain=domain,
                allow_equal=False,
            )
        except ValueError as exc:
            errors.append(f"row {row_number}: {exc}")
        else:
            if not progress.valid:
                errors.append(
                    f"row {row_number}: invalid {domain} gate progression "
                    f"{parsed['gate_open_ticks']}->{parsed['gate_close_ticks']}: "
                    f"{progress.reason}"
                )


def _check_timestamp_monotonicity(
    contract: str,
    parsed_timestamps: dict[str, int],
    row_number: int,
    previous_timestamps: dict[tuple[str, str], int],
    errors: list[str],
    *,
    domain: str,
) -> None:
    for field_name in TIMESTAMP_FIELDS[contract]:
        if field_name not in parsed_timestamps:
            continue
        key = (domain, field_name)
        previous = previous_timestamps.get(key)
        current = parsed_timestamps[field_name]
        if previous is not None:
            try:
                progress = forward_progress(previous, current, domain=domain)
            except ValueError as exc:
                errors.append(f"row {row_number}: {exc}")
            else:
                if not progress.valid:
                    errors.append(
                        f"row {row_number}: {field_name} violates {domain} progression; "
                        f"previous={previous}, current={current}, reason={progress.reason}"
                    )
        previous_timestamps[key] = current


def _check_channel(context: CsvValidationContext, row: dict[str, str], row_number: int, errors: list[str]) -> None:
    field_name = CHANNEL_FIELDS.get(context.contract)
    if not field_name:
        return
    channel = _parse_non_negative_int(row.get(field_name, ""), field_name, row_number, errors)
    if channel is not None and context.known_channels and channel not in context.known_channels:
        errors.append(f"row {row_number}: {field_name} {channel} is not declared in manifest channels")
    if context.contract == "raw_events_v1" and channel is not None:
        expected = {"EVT": 0, "REF": 1}.get(row.get("record_type", ""))
        if expected is not None and channel != expected:
            pin = "D10" if expected == 0 else "D14"
            errors.append(
                f"row {row_number}: {row.get('record_type')} must be {pin}/CH{expected}; "
                f"got channel_id={channel}"
            )


def _check_domains(context: CsvValidationContext, row: dict[str, str], row_number: int, errors: list[str]) -> None:
    for field_name in DOMAIN_FIELDS[context.contract]:
        domain = row.get(field_name, "")
        if not domain:
            errors.append(f"row {row_number}: {field_name} is absent")
            continue
        try:
            time_domain(domain)
        except ValueError as exc:
            errors.append(f"row {row_number}: {exc}")
        if context.known_domains and domain not in context.known_domains:
            errors.append(f"row {row_number}: {field_name} {domain!r} is not declared in manifest domains")


def _timestamp_domain(contract: str, row: dict[str, str]) -> str:
    fields = DOMAIN_FIELDS[contract]
    if fields:
        return row.get(fields[0], "")
    return CONTRACT_IMPLICIT_TIME_DOMAINS.get(contract, "")


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


def _check_forwarded_monitor_snapshot(
    row: dict[str, str], row_number: int, errors: list[str]
) -> None:
    _check_pps_snapshot(row, row_number, errors)
    if row.get("backend") != "pio_wait_cumulative_snapshot_cpu_v1":
        errors.append(
            f"row {row_number}: forwarded monitor backend must be "
            "pio_wait_cumulative_snapshot_cpu_v1"
        )
    _parse_non_negative_int(
        row.get("reference_session", ""), "reference_session", row_number, errors
    )
    channel_id = _parse_non_negative_int(
        row.get("channel_id", ""), "channel_id", row_number, errors
    )
    if channel_id is not None and channel_id != 3:
        errors.append(
            f"row {row_number}: forwarded monitor channel_id must be 3 (D6); "
            f"got {channel_id}"
        )


def _check_association_loss_decision_v1(
    row: dict[str, str], row_number: int, errors: list[str]
) -> None:
    classifications = {
        "backend_fault",
        "unread_snapshot_present_when_decision_made",
        "timeout_no_snapshot",
        "no_unread_snapshot_healthy_backend",
    }
    if row.get("classification") not in classifications:
        errors.append(
            f"row {row_number}: classification must be one of "
            f"{sorted(classifications)}"
        )
    for field_name in (
        "next_reference_present",
        "snapshot_initialized",
        "snapshot_running",
        "snapshot_fault_latched",
    ):
        if row.get(field_name) not in {"true", "false"}:
            errors.append(
                f"row {row_number}: {field_name} must be 'true' or 'false'"
            )
    numeric_fields = (
        "pending_reference_sequence",
        "pending_reference_ticks",
        "pending_age_ticks",
        "boundary_depth",
        "boundary_dropped_count",
        "next_reference_sequence",
        "next_reference_ticks",
        "snapshot_fault_flags",
        "snapshot_session",
        "snapshot_producer_ordinal",
        "snapshot_consumer_ordinal",
        "snapshot_backlog_depth",
        "snapshot_backlog_high_water",
        "snapshot_overwrite_count",
        "snapshot_continuity_loss_count",
        "snapshot_pio_rxstall_count",
        "snapshot_dma_error_count",
        "snapshot_dma_stopped_count",
        "core1_loop_sequence",
        "core1_last_snapshot_session",
        "core1_last_snapshot_sequence",
        "core1_phase_enter_ticks",
        "core1_last_progress_ticks",
    )
    parsed = {
        field_name: _parse_non_negative_int(
            row.get(field_name, ""), field_name, row_number, errors
        )
        for field_name in numeric_fields
    }
    for field_name in ("reason", "core1_phase"):
        if not row.get(field_name):
            errors.append(f"row {row_number}: {field_name} must not be empty")
    if row.get("next_reference_present") == "false" and (
        parsed["next_reference_sequence"] not in {None, 0}
        or parsed["next_reference_ticks"] not in {None, 0}
    ):
        errors.append(
            f"row {row_number}: absent next reference must carry zero identity"
        )
    backlog = parsed["snapshot_backlog_depth"]
    classification = row.get("classification")
    if classification == "unread_snapshot_present_when_decision_made" and backlog == 0:
        errors.append(
            f"row {row_number}: unread-snapshot classification requires backlog"
        )
    if classification in {
        "timeout_no_snapshot",
        "no_unread_snapshot_healthy_backend",
    } and backlog not in {None, 0}:
        errors.append(
            f"row {row_number}: no-snapshot classification requires zero backlog"
        )
    if (
        classification == "backend_fault"
        and row.get("snapshot_fault_latched") != "true"
    ):
        errors.append(
            f"row {row_number}: backend_fault requires snapshot_fault_latched=true"
        )


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


def _check_required_text(
    row: dict[str, str], row_number: int, errors: list[str], field_names: tuple[str, ...]
) -> None:
    for field_name in field_names:
        if not row.get(field_name):
            errors.append(f"row {row_number}: {field_name} must not be empty")


def _check_boolean_text(row: dict[str, str], field_name: str, row_number: int, errors: list[str]) -> None:
    if row.get(field_name) not in VALID_BOOLEAN_TEXT:
        errors.append(f"row {row_number}: {field_name} must be 'true' or 'false'")


def _check_estimate_common(row: dict[str, str], row_number: int, errors: list[str]) -> None:
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
        errors.append(f"row {row_number}: drift_enabled must remain false")
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
    _check_estimate_common(row, row_number, errors)
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
    if row.get("plant_model_ref") != CURRENT_PLANT_MODEL_REF:
        errors.append(
            f"row {row_number}: plant_model_ref must identify the current PPS-gated oscillator plant"
        )
    if row.get("plant_model_id") != CURRENT_PLANT_MODEL_ID:
        errors.append(
            f"row {row_number}: plant_model_id must identify the current PPS-gated oscillator plant"
        )
    if row.get("plant_model_version") != "1":
        errors.append(f"row {row_number}: plant_model_version must be 1")
    _check_sha256(row, "plant_model_hash", row_number, errors)
    if CURRENT_PLANT_MODEL_PATH.is_file() and row.get("plant_model_hash") != sha256(
        CURRENT_PLANT_MODEL_PATH.read_bytes()
    ).hexdigest():
        errors.append(
            f"row {row_number}: plant_model_hash must match the current plant profile bytes"
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
        errors.append(f"row {row_number}: preview_only must be true for zero-authority CTL evidence")
    if row.get("actuation_authorized") != "false":
        errors.append(f"row {row_number}: CTL evidence cannot authorize actuation")
    if row.get("actionable") != "false":
        errors.append(f"row {row_number}: CTL evidence cannot be actionable")

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


def _check_active_transaction_v2(
    row: dict[str, str], row_number: int, errors: list[str]
) -> None:
    _check_required_text(
        row,
        row_number,
        errors,
        (
            "event",
            "time_domain",
            "run_identity",
            "build_identity",
            "image_identity",
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
    if row.get("time_domain") != "rp2040_monotonic_us64":
        errors.append(
            f"row {row_number}: ACT event timing requires rp2040_monotonic_us64"
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
        "event_timestamp_ticks",
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
            "request_withdrawn": "evidence_clear",
            "request_accepted": "acceptance_pending",
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
    if event == "request_withdrawn" and row.get("active_state") != "DISARMED":
        errors.append(
            f"row {row_number}: request_withdrawn requires DISARMED"
        )
    if event == "request_accepted" and row.get("active_state") != "ACCEPTED_AWAITING_APPLICATION":
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


def _check_active_hybrid_decision_v2(
    row: dict[str, str], row_number: int, errors: list[str]
) -> None:
    _check_required_text(
        row,
        row_number,
        errors,
        (
            "time_domain",
            "run_identity",
            "build_identity",
            "image_identity",
            "frequency_estimator_sha256",
            "tight_state",
            "phase_estimator_sha256",
            "state_before",
            "state_after",
            "authority_state",
            "response_class",
            "reason",
            "active_policy_sha256",
            "response_policy_sha256",
        ),
    )
    if row.get("time_domain") != "rp2040_monotonic_us64":
        errors.append(
            f"row {row_number}: AHY decision timing requires "
            "rp2040_monotonic_us64"
        )
    for field_name in (
        "phase_continuous",
        "phase_current",
        "phase_step_detected",
        "phase_recorder_published",
        "phase_materially_influenced",
        "step_limited",
        "range_clamped",
        "cadence_limited",
        "count_limited",
        "cumulative_budget_limited",
        "downstream_epoch_exact",
        "actionable",
    ):
        _check_boolean_text(row, field_name, row_number, errors)
    if row.get("actionable") != "false":
        errors.append(
            f"row {row_number}: serialized active-hybrid evidence must never be actionable"
        )
    if row.get("state_before") not in VALID_ACTIVE_HYBRID_STATES:
        errors.append(f"row {row_number}: invalid active-hybrid state_before")
    if row.get("state_after") not in VALID_ACTIVE_HYBRID_STATES:
        errors.append(f"row {row_number}: invalid active-hybrid state_after")
    if row.get("authority_state") not in VALID_ACTIVE_STATES:
        errors.append(f"row {row_number}: invalid transaction authority_state")
    if row.get("response_class") not in VALID_ACTIVE_RESPONSE_CLASSES:
        errors.append(f"row {row_number}: invalid response_class")
    if row.get("tight_state") not in VALID_TIGHT_DEADBAND_STATES:
        errors.append(f"row {row_number}: invalid tight_state")
    for field_name in (
        "decision_sequence",
        "decision_timestamp_ticks",
        "decision_timestamp_s",
        "capture_session",
        "source_first_sequence",
        "source_last_sequence",
        "phase_epoch",
        "phase_observation_sequence",
        "current_applied_code",
        "dac_epoch",
        "phase_applied_code",
        "phase_dac_epoch",
        "requested_code",
        "correction_count_before",
        "cumulative_movement_before_codes",
        "request_sequence",
        "acceptance_sequence",
        "application_sequence",
        "actual_applied_code",
        "actual_dac_epoch",
    ):
        _parse_non_negative_int(row.get(field_name, ""), field_name, row_number, errors)
    try:
        decision_ticks = int(row["decision_timestamp_ticks"], 10)
        decision_seconds = int(row["decision_timestamp_s"], 10)
    except (KeyError, TypeError, ValueError):
        pass
    else:
        if not integer_projection_matches(
            "active_decision_whole_seconds_from_exact_ticks",
            source=decision_ticks,
            target=decision_seconds,
            source_domain=row.get("time_domain", ""),
        ):
            errors.append(
                f"row {row_number}: decision_timestamp_s is not the declared "
                "integer projection of decision_timestamp_ticks"
            )
    for field_name in (
        "accumulated_edge_error_counts",
        "relative_phase_cycles",
        "requested_delta_codes",
        "counterfactual_frequency_only_delta_codes",
    ):
        _parse_int(row.get(field_name, ""), field_name, row_number, errors)
    for field_name in (
        "frequency_error_hz",
        "frequency_term_hz",
        "phase_term_hz",
        "combined_demand_hz",
        "raw_combined_delta_codes",
    ):
        _parse_optional_float(row.get(field_name), field_name, row_number, errors)
    for field_name in (
        "frequency_estimator_sha256",
        "phase_estimator_sha256",
        "active_policy_sha256",
        "response_policy_sha256",
    ):
        _check_sha256(row, field_name, row_number, errors)

    try:
        current_code = int(row["current_applied_code"])
        delta = int(row["requested_delta_codes"])
        requested_code = int(row["requested_code"])
        counterfactual = int(row["counterfactual_frequency_only_delta_codes"])
        phase_term = float(row["phase_term_hz"])
    except (KeyError, TypeError, ValueError):
        return
    if requested_code != current_code + delta:
        errors.append(f"row {row_number}: requested code does not equal current plus delta")
    if not 0xA800 <= requested_code <= 0xAB00:
        errors.append(f"row {row_number}: requested code is outside A800..AB00")
    expected_material: bool | None
    # The exact PLL component is retained in AHM picocodes and can be smaller
    # than AHY's 12-decimal Hz projection. Check the path-local cases that AHY
    # represents exactly and leave lossy zero-demand holds to AHM replay.
    reason = row.get("reason")
    raw_combined = float(row["raw_combined_delta_codes"])
    if reason == "phase_material_ordinary_request_ready":
        expected_material = True
    elif reason == "outside_tight_ordinary_request_ready":
        expected_material = delta != counterfactual
    elif reason == "phase_degraded_frequency_only_request_ready":
        expected_material = False
    elif raw_combined != 0.0:
        expected_material = False
    else:
        expected_material = None
    if (
        expected_material is not None
        and (row.get("phase_materially_influenced") == "true")
        != expected_material
    ):
        errors.append(f"row {row_number}: phase materiality counterfactual differs")
    if row.get("phase_recorder_published") != "true":
        errors.append(f"row {row_number}: active decision lacks prior phase publication")
    if row.get("downstream_epoch_exact") != "true":
        errors.append(f"row {row_number}: active decision lacks exact downstream DAC epoch")
    if delta != 0 and any(
        row.get(field_name) == "true"
        for field_name in ("cadence_limited", "count_limited", "cumulative_budget_limited")
    ):
        errors.append(f"row {row_number}: limited active decision retained a non-zero delta")


def _check_active_hybrid_maintenance_v1(
    row: dict[str, str], row_number: int, errors: list[str]
) -> None:
    """Validate one adaptive-hybrid maintenance lifecycle record.

    Cross-file one-to-one joins are verified by the campaign analyzer. This
    row contract makes every required AHY and ACT key explicit and rejects
    partial identities before analysis.
    """

    _check_required_text(
        row,
        row_number,
        errors,
        (
            "event",
            "time_domain",
            "run_identity",
            "build_identity",
            "image_identity",
            "policy_id",
            "active_policy_sha256",
            "frequency_estimator_sha256",
            "maintenance_state_before",
            "maintenance_state_after",
            "frontier_relation",
            "transaction_event",
            "reason",
        ),
    )
    event = row.get("event", "")
    if event not in VALID_ACTIVE_HYBRID_MAINTENANCE_EVENTS:
        errors.append(
            f"row {row_number}: event must be one of "
            f"{sorted(VALID_ACTIVE_HYBRID_MAINTENANCE_EVENTS)}"
        )
    if row.get("time_domain") != "rp2040_monotonic_us64":
        errors.append(
            f"row {row_number}: AHM event timing requires "
            "rp2040_monotonic_us64"
        )
    if row.get("policy_id") != ADAPTIVE_HYBRID_MAINTENANCE_POLICY_ID:
        errors.append(
            f"row {row_number}: policy_id must equal "
            f"{ADAPTIVE_HYBRID_MAINTENANCE_POLICY_ID}"
        )
    for field_name in ("active_policy_sha256", "frequency_estimator_sha256"):
        _check_sha256(row, field_name, row_number, errors)
    for field_name in (
        "phase_valid",
        "downstream_epoch_exact",
        "request_pending_before",
        "request_pending_after",
        "response_pending_before",
        "response_pending_after",
        "metadata_hold_before",
        "metadata_hold_after",
        "actionable",
    ):
        _check_boolean_text(row, field_name, row_number, errors)
    if row.get("actionable") != "false":
        errors.append(
            f"row {row_number}: serialized AHM evidence must never be actionable"
        )
    for field_name in ("maintenance_state_before", "maintenance_state_after"):
        if row.get(field_name) not in VALID_ACTIVE_HYBRID_MAINTENANCE_STATES:
            errors.append(
                f"row {row_number}: {field_name} must be one of "
                f"{sorted(VALID_ACTIVE_HYBRID_MAINTENANCE_STATES)}"
            )
    if row.get("frontier_relation") not in VALID_ACTIVE_HYBRID_MAINTENANCE_FRONTIERS:
        errors.append(
            f"row {row_number}: frontier_relation must be one of "
            f"{sorted(VALID_ACTIVE_HYBRID_MAINTENANCE_FRONTIERS)}"
        )
    if row.get("transaction_event") not in VALID_ACTIVE_HYBRID_MAINTENANCE_TRANSACTION_EVENTS:
        errors.append(
            f"row {row_number}: transaction_event must be one of "
            f"{sorted(VALID_ACTIVE_HYBRID_MAINTENANCE_TRANSACTION_EVENTS)}"
        )

    unsigned_fields = (
        "maintenance_record_sequence",
        "event_timestamp_ticks",
        "capture_session",
        "source_first_sequence",
        "source_last_sequence",
        "phase_epoch",
        "phase_observation_sequence",
        "current_applied_code",
        "current_dac_epoch",
        "hybrid_record_sequence",
        "decision_sequence",
        "transaction_record_sequence",
        "request_sequence",
        "application_sequence",
        "actual_applied_code",
        "actual_dac_epoch",
        "persistence_count_before",
        "persistence_count_after",
        "safe_cap_codes",
        "requested_code",
        "requalification_window_count_before",
        "requalification_window_count_after",
        "requalification_d14_d8_observation_sequence",
        "evidence_burst_sequence",
        "evidence_burst_record_ordinal",
        "evidence_burst_record_count",
    )
    parsed_unsigned = {
        field_name: _parse_non_negative_int(
            row.get(field_name, ""), field_name, row_number, errors
        )
        for field_name in unsigned_fields
    }
    signed_fields = (
        "interval_sign",
        "raw_fll_demand_picocodes",
        "raw_pll_demand_picocodes",
        "candidate_total_demand_picocodes",
        "requested_delta_codes",
        "committed_fll_debt_before_picocodes",
        "committed_pll_debt_before_picocodes",
        "committed_fll_debt_after_picocodes",
        "committed_pll_debt_after_picocodes",
    )
    parsed_signed = {
        field_name: _parse_int(
            row.get(field_name, ""), field_name, row_number, errors
        )
        for field_name in signed_fields
    }
    if parsed_unsigned["maintenance_record_sequence"] == 0:
        errors.append(
            f"row {row_number}: maintenance_record_sequence must be non-zero"
        )
    if parsed_signed["interval_sign"] not in {-1, 0, 1, None}:
        errors.append(f"row {row_number}: interval_sign must be -1, 0, or 1")
    for field_name in ("persistence_count_before", "persistence_count_after"):
        value = parsed_unsigned[field_name]
        if value is not None and value > 2:
            errors.append(f"row {row_number}: {field_name} must be in 0..2")
    for field_name in (
        "requalification_window_count_before",
        "requalification_window_count_after",
    ):
        value = parsed_unsigned[field_name]
        if value is not None and value > 2:
            errors.append(f"row {row_number}: {field_name} must be in 0..2")
    safe_cap = parsed_unsigned["safe_cap_codes"]
    if safe_cap is not None and safe_cap > 21:
        errors.append(f"row {row_number}: safe_cap_codes must be in 0..21")
    requested_delta = parsed_signed["requested_delta_codes"]
    if requested_delta is not None and abs(requested_delta) > 21:
        errors.append(
            f"row {row_number}: requested_delta_codes must be in -21..21"
        )
    for field_name in (
        "current_applied_code",
        "requested_code",
        "actual_applied_code",
    ):
        value = parsed_unsigned[field_name]
        if value not in {None, 0} and not 0xA800 <= value <= 0xAB00:
            errors.append(
                f"row {row_number}: {field_name} is outside A800..AB00"
            )
    source_first = parsed_unsigned["source_first_sequence"]
    source_last = parsed_unsigned["source_last_sequence"]
    if (
        source_first not in {None, 0}
        and source_last not in {None, 0}
        and source_last <= source_first
    ):
        errors.append(
            f"row {row_number}: source_last_sequence must be greater than "
            "source_first_sequence for (opening, closing] support"
        )
    current_code = parsed_unsigned["current_applied_code"]
    requested_code = parsed_unsigned["requested_code"]
    if (
        current_code not in {None, 0}
        and requested_delta is not None
        and requested_code is not None
        and requested_code != current_code + requested_delta
    ):
        errors.append(
            f"row {row_number}: requested_code must equal current_applied_code "
            "plus requested_delta_codes"
        )

    debt_before = None
    debt_after = None
    if all(
        parsed_signed[field_name] is not None
        for field_name in (
            "committed_fll_debt_before_picocodes",
            "committed_pll_debt_before_picocodes",
            "committed_fll_debt_after_picocodes",
            "committed_pll_debt_after_picocodes",
        )
    ):
        debt_before = (
            parsed_signed["committed_fll_debt_before_picocodes"]
            + parsed_signed["committed_pll_debt_before_picocodes"]
        )
        debt_after = (
            parsed_signed["committed_fll_debt_after_picocodes"]
            + parsed_signed["committed_pll_debt_after_picocodes"]
        )
        for label, value in (("before", debt_before), ("after", debt_after)):
            if abs(value) > MAX_COMMITTED_DEBT_PICOCODES:
                errors.append(
                    f"row {row_number}: committed {label} debt exceeds the "
                    "500000000000 picocode bound"
                )
        for field_name in (
            "committed_fll_debt_before_picocodes",
            "committed_pll_debt_before_picocodes",
            "committed_fll_debt_after_picocodes",
            "committed_pll_debt_after_picocodes",
        ):
            value = parsed_signed[field_name]
            if value is not None and abs(value) > MAX_COMMITTED_DEBT_PICOCODES:
                errors.append(
                    f"row {row_number}: {field_name} exceeds the bounded "
                    "picocode tag range"
                )

    burst_sequence = parsed_unsigned["evidence_burst_sequence"]
    burst_ordinal = parsed_unsigned["evidence_burst_record_ordinal"]
    burst_count = parsed_unsigned["evidence_burst_record_count"]
    if burst_sequence == 0 or burst_ordinal == 0 or burst_count == 0:
        errors.append(
            f"row {row_number}: evidence burst identity and cardinality must be non-zero"
        )
    if (
        burst_ordinal is not None
        and burst_count is not None
        and burst_ordinal > burst_count
    ):
        errors.append(
            f"row {row_number}: evidence_burst_record_ordinal exceeds record count"
        )

    hybrid_join_fields = (
        "hybrid_record_sequence",
        "decision_sequence",
        "source_first_sequence",
        "source_last_sequence",
    )
    transaction_join_fields = (
        "transaction_record_sequence",
        "request_sequence",
    )

    def _require_non_zero(field_names: tuple[str, ...], label: str) -> None:
        missing = [
            field_name
            for field_name in field_names
            if parsed_unsigned[field_name] in {None, 0}
        ]
        if missing:
            errors.append(
                f"row {row_number}: {label} requires non-zero "
                + ", ".join(missing)
            )

    def _require_zero(field_names: tuple[str, ...], label: str) -> None:
        present = [
            field_name
            for field_name in field_names
            if parsed_unsigned[field_name] not in {None, 0}
        ]
        if present:
            errors.append(
                f"row {row_number}: {label} requires zero " + ", ".join(present)
            )

    transaction_events = {
        "request_rejected_or_expired": "request_withdrawn",
        "application_first_consumer": "application",
        "response_complete": "response",
    }
    if event == "policy_activation":
        _require_zero((*hybrid_join_fields, *transaction_join_fields), event)
        if row.get("transaction_event") != "none":
            errors.append(
                f"row {row_number}: policy_activation transaction_event must be none"
            )
        if (
            row.get("maintenance_state_before") != "POLICY_INACTIVE"
            or row.get("maintenance_state_after") != "READY"
        ):
            errors.append(
                f"row {row_number}: policy_activation must transition "
                "POLICY_INACTIVE to READY"
            )
        if debt_after not in {None, 0}:
            errors.append(
                f"row {row_number}: policy_activation must reset both debt tags"
            )
        if any(
            parsed_signed[field_name] not in {None, 0}
            for field_name in (
                "committed_fll_debt_after_picocodes",
                "committed_pll_debt_after_picocodes",
            )
        ):
            errors.append(
                f"row {row_number}: policy_activation must reset each debt tag to zero"
            )
    elif event == "decision":
        _require_non_zero(hybrid_join_fields, event)
        if burst_count is not None and burst_count < 2:
            errors.append(
                f"row {row_number}: decision burst must contain at least AHY and AHM"
            )
        request_created = (
            row.get("request_pending_before") == "false"
            and row.get("request_pending_after") == "true"
        )
        if request_created:
            _require_non_zero(transaction_join_fields, "decision request creation")
            if row.get("transaction_event") != "request_created":
                errors.append(
                    f"row {row_number}: a newly pending request must join ACT "
                    "request_created"
                )
            if burst_count is not None and burst_count < 3:
                errors.append(
                    f"row {row_number}: request decision burst must contain "
                    "AHY, ACT, and AHM"
                )
        else:
            _require_zero(transaction_join_fields, "decision without request creation")
            if row.get("transaction_event") != "none":
                errors.append(
                    f"row {row_number}: decision without request creation must use "
                    "transaction_event=none"
                )
    elif event in transaction_events:
        _require_non_zero(hybrid_join_fields, event)
        _require_non_zero(transaction_join_fields, event)
        if row.get("transaction_event") != transaction_events[event]:
            errors.append(
                f"row {row_number}: {event} must join transaction_event="
                f"{transaction_events[event]}"
            )
        if burst_count is not None and burst_count < 2:
            errors.append(
                f"row {row_number}: {event} burst must contain ACT and AHM"
            )
    elif event == "fail_static" and row.get("transaction_event") == "application_fault":
        _require_non_zero(hybrid_join_fields, event)
        _require_non_zero(transaction_join_fields, event)
        if burst_count is not None and burst_count < 2:
            errors.append(
                f"row {row_number}: fail_static application-fault burst must "
                "contain ACT and AHM"
            )
    else:
        _require_zero(transaction_join_fields, event or "non-transaction event")
        if row.get("transaction_event") not in {"none", "application_fault"}:
            errors.append(
                f"row {row_number}: {event} must not claim a transaction lifecycle join"
            )
        hybrid_values = [parsed_unsigned[field_name] for field_name in hybrid_join_fields]
        if any(value not in {None, 0} for value in hybrid_values) and any(
            value in {None, 0} for value in hybrid_values
        ):
            errors.append(
                f"row {row_number}: last-completed AHY identity must be all zero "
                "or complete"
            )

    preserve_debt_events = {
        "request_rejected_or_expired",
        "response_complete",
        "gnss_metadata_hold_enter",
        "gnss_metadata_requalified",
        "fail_static",
    }
    if event in preserve_debt_events and None not in {debt_before, debt_after}:
        if any(
            parsed_signed[before] != parsed_signed[after]
            for before, after in (
                (
                    "committed_fll_debt_before_picocodes",
                    "committed_fll_debt_after_picocodes",
                ),
                (
                    "committed_pll_debt_before_picocodes",
                    "committed_pll_debt_after_picocodes",
                ),
            )
        ):
            errors.append(
                f"row {row_number}: {event} must preserve both committed debt tags"
            )
    if event == "request_rejected_or_expired":
        if not (
            row.get("request_pending_before") == "true"
            and row.get("request_pending_after") == "false"
            and row.get("response_pending_before") == "false"
            and row.get("response_pending_after") == "false"
        ):
            errors.append(
                f"row {row_number}: request rejection/expiry must clear only a "
                "pending unaccepted request"
            )
    if event == "application_first_consumer":
        if not (
            row.get("request_pending_before") == "true"
            and row.get("request_pending_after") == "false"
            and row.get("response_pending_before") == "false"
            and row.get("response_pending_after") == "true"
            and row.get("downstream_epoch_exact") == "true"
        ):
            errors.append(
                f"row {row_number}: application_first_consumer requires the exact "
                "request-to-response-pending propagation transition"
            )
        _require_non_zero(
            ("application_sequence", "actual_applied_code", "actual_dac_epoch"),
            event,
        )
        actual_applied_code = parsed_unsigned["actual_applied_code"]
        actual_dac_epoch = parsed_unsigned["actual_dac_epoch"]
        current_dac_epoch = parsed_unsigned["current_dac_epoch"]
        if (
            actual_applied_code is not None
            and requested_code is not None
            and actual_applied_code != requested_code
        ):
            errors.append(
                f"row {row_number}: exact application code must equal requested_code"
            )
        if (
            actual_dac_epoch is not None
            and current_dac_epoch is not None
            and actual_dac_epoch != current_dac_epoch + 1
        ):
            errors.append(
                f"row {row_number}: exact application DAC epoch must advance by one"
            )
        if row.get("maintenance_state_after") != "RESPONSE_PENDING":
            errors.append(
                f"row {row_number}: application_first_consumer must enter RESPONSE_PENDING"
            )
    if event == "response_complete" and not (
        row.get("response_pending_before") == "true"
        and row.get("response_pending_after") == "false"
    ):
        errors.append(
            f"row {row_number}: response_complete must clear response_pending"
        )
    if event == "gnss_metadata_hold_enter":
        if not (
            row.get("metadata_hold_before") == "false"
            and row.get("metadata_hold_after") == "true"
            and row.get("maintenance_state_after") == "METADATA_HOLD"
        ):
            errors.append(
                f"row {row_number}: gnss_metadata_hold_enter must enter METADATA_HOLD"
            )
        if parsed_unsigned["persistence_count_after"] not in {None, 0}:
            errors.append(
                f"row {row_number}: GNSS metadata hold must clear persistence"
            )
    if event == "gnss_metadata_requalified":
        if not (
            row.get("metadata_hold_before") == "true"
            and row.get("metadata_hold_after") == "true"
            and parsed_unsigned["requalification_window_count_after"] == 0
            and parsed_unsigned[
                "requalification_d14_d8_observation_sequence"
            ] not in {None, 0}
        ):
            errors.append(
                f"row {row_number}: GNSS metadata requalification must retain the "
                "hold at a zero post-requalification window count and bind a "
                "non-zero D14/D8 observation frontier"
            )
    elif parsed_unsigned["requalification_d14_d8_observation_sequence"] not in {
        None,
        0,
    }:
        errors.append(
            f"row {row_number}: only gnss_metadata_requalified may bind "
            "requalification_d14_d8_observation_sequence"
        )
    if event == "decision" and row.get("metadata_hold_before") == "true":
        requalification_before = parsed_unsigned[
            "requalification_window_count_before"
        ]
        requalification_after = parsed_unsigned[
            "requalification_window_count_after"
        ]
        if row.get("metadata_hold_after") == "true":
            valid_frozen_or_first_window = (
                requalification_before is not None
                and requalification_after is not None
                and (
                    requalification_after == requalification_before == 0
                    or (
                        requalification_before == 0
                        and requalification_after == 1
                    )
                )
            )
            if not valid_frozen_or_first_window:
                errors.append(
                    f"row {row_number}: metadata hold may remain frozen at zero "
                    "or advance only the first post-requalification window"
                )
            if row.get("request_pending_after") != "false":
                errors.append(
                    f"row {row_number}: metadata hold forbids a new request"
                )
        elif not (
            requalification_before == 1 and requalification_after == 2
        ):
            errors.append(
                f"row {row_number}: metadata hold may clear only on the second "
                "complete post-requalification maintenance window"
            )
    if event == "fail_static" and row.get("maintenance_state_after") != "FAIL_STATIC":
        errors.append(f"row {row_number}: fail_static must enter FAIL_STATIC")

    if row.get("maintenance_state_after") == "REQUEST_PENDING" and row.get(
        "request_pending_after"
    ) != "true":
        errors.append(
            f"row {row_number}: REQUEST_PENDING state requires request_pending_after=true"
        )
    if row.get("maintenance_state_after") == "RESPONSE_PENDING" and row.get(
        "response_pending_after"
    ) != "true":
        errors.append(
            f"row {row_number}: RESPONSE_PENDING state requires response_pending_after=true"
        )
    if row.get("maintenance_state_after") == "METADATA_HOLD" and row.get(
        "metadata_hold_after"
    ) != "true":
        errors.append(
            f"row {row_number}: METADATA_HOLD state requires metadata_hold_after=true"
        )


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


def _check_tight_deadband_decision_v1(
    row: dict[str, str],
    row_number: int,
    errors: list[str],
    *,
    expected_policy_sha256: str | None,
) -> None:
    _check_required_text(
        row,
        row_number,
        errors,
        (
            "estimate_id",
            "time_domain",
            "state_before",
            "state_after",
            "policy_id",
            "policy_sha256",
            "reason_codes",
        ),
    )
    for field_name in (
        "capture_session",
        "dac_epoch",
        "absolute_edge_error_counts",
        "entry_counter",
        "release_counter",
    ):
        _parse_non_negative_int(row.get(field_name, ""), field_name, row_number, errors)
    signed_counts = _parse_int(
        row.get("integer_edge_error_counts", ""),
        "integer_edge_error_counts",
        row_number,
        errors,
    )
    if signed_counts is not None and not (-(2**63) <= signed_counts < 2**63):
        errors.append(
            f"row {row_number}: integer_edge_error_counts must fit signed 64-bit firmware storage"
        )
    absolute_counts = _parse_non_negative_int(
        row.get("absolute_edge_error_counts", ""),
        "absolute_edge_error_counts",
        row_number,
        errors,
    )
    if (
        signed_counts is not None
        and absolute_counts is not None
        and absolute_counts != abs(signed_counts)
    ):
        errors.append(
            f"row {row_number}: absolute_edge_error_counts must equal "
            "abs(integer_edge_error_counts)"
        )
    for field_name in (
        "transition",
        "frequency_controller_eligible",
        "requalified",
        "three_count_band_inside",
        "two_count_band_inside",
        "actionable",
        "actuation_authorized",
        "authorization_consumed",
    ):
        _check_boolean_text(row, field_name, row_number, errors)
    for field_name in ("state_before", "state_after"):
        if row.get(field_name) not in VALID_TIGHT_DEADBAND_STATES:
            errors.append(
                f"row {row_number}: {field_name} must be one of "
                f"{sorted(VALID_TIGHT_DEADBAND_STATES)}"
            )
    if row.get("reason_codes") not in VALID_TIGHT_DEADBAND_REASONS:
        errors.append(
            f"row {row_number}: reason_codes must be one of "
            f"{sorted(VALID_TIGHT_DEADBAND_REASONS)}"
        )
    if row.get("transition") in VALID_BOOLEAN_TEXT and (
        (row.get("transition") == "true")
        != (row.get("state_before") != row.get("state_after"))
    ):
        errors.append(
            f"row {row_number}: transition must equal state_before != state_after"
        )
    requalified = row.get("requalified") == "true"
    requalification_reason = row.get("requalification_reason", "")
    if requalified and requalification_reason not in VALID_TIGHT_DEADBAND_REQUALIFICATION_REASONS:
        errors.append(
            f"row {row_number}: requalified decision requires a session or dac "
            "epoch requalification_reason"
        )
    if not requalified and requalification_reason:
        errors.append(
            f"row {row_number}: non-requalified decision must not carry requalification_reason"
        )
    if row.get("policy_id") != TIGHT_DEADBAND_POLICY_ID:
        errors.append(
            f"row {row_number}: policy_id must equal {TIGHT_DEADBAND_POLICY_ID}"
        )
    if not re.fullmatch(r"est:frequency_regulation:[^:]+:[0-9]+", row.get("estimate_id", "")):
        errors.append(
            f"row {row_number}: estimate_id must identify a current frequency-regulation estimate"
        )
    _check_sha256(row, "policy_sha256", row_number, errors)
    if (
        expected_policy_sha256 is not None
        and row.get("policy_sha256") != expected_policy_sha256
    ):
        errors.append(
            f"row {row_number}: policy_sha256 must equal the expected "
            "tight-deadband policy hash"
        )
    for field_name in ("actionable", "actuation_authorized", "authorization_consumed"):
        if row.get(field_name) != "false":
            errors.append(
                f"row {row_number}: {field_name} must remain false for TDB"
            )
    if absolute_counts is not None:
        expected_three_count_band = absolute_counts <= 3
        expected_two_count_band = absolute_counts <= 2
        if row.get("three_count_band_inside") in VALID_BOOLEAN_TEXT and (
            (row.get("three_count_band_inside") == "true")
            != expected_three_count_band
        ):
            errors.append(
                f"row {row_number}: three_count_band_inside must equal "
                "absolute_edge_error_counts <= 3"
            )
        if row.get("two_count_band_inside") in VALID_BOOLEAN_TEXT and (
            (row.get("two_count_band_inside") == "true") != expected_two_count_band
        ):
            errors.append(
                f"row {row_number}: two_count_band_inside must equal "
                "absolute_edge_error_counts <= 2"
            )


def validate_csv(path: Path, context: CsvValidationContext) -> CsvValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    row_count = 0
    previous_seq: int | None = None
    previous_timestamps: dict[tuple[str, str], int] = {}
    previous_session: str | None = None

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
            errors.extend(
                f"row {row_count}: {error}"
                for error in validate_record_wire_values(
                    context.contract,
                    [row.get(field_name) or "" for field_name in expected_fields],
                )
            )
            sequence_value: int | None = None
            try:
                sequence_value = int(
                    row.get(SEQUENCE_FIELDS[context.contract], ""), 10
                )
            except (TypeError, ValueError):
                pass
            if (
                context.segmented_capture
                and previous_seq is not None
                and sequence_value is not None
                and sequence_value <= previous_seq
            ):
                previous_timestamps.clear()
            previous_seq = _check_sequence(context.contract, row, row_count, previous_seq, errors)
            _check_domains(context, row, row_count, errors)
            session_field = SESSION_FIELDS.get(context.contract)
            current_session = row.get(session_field, "") if session_field else None
            if (
                session_field
                and previous_session is not None
                and current_session != previous_session
            ):
                previous_timestamps.clear()
            if session_field:
                previous_session = current_session
            domain = _timestamp_domain(context.contract, row)
            _check_timestamps(
                context.contract,
                row,
                row_count,
                errors,
                domain=domain,
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
                domain=domain,
            )
            _check_channel(context, row, row_count, errors)
            if "flags" in expected_fields:
                _check_flags(row, row_count, errors)
            _check_edges(context.contract, row, row_count, errors)
            if context.contract == "count_observations_v1":
                _check_count_observation(row, row_count, errors)
            if context.contract == "pps_snapshots_v1":
                _check_pps_snapshot(row, row_count, errors)
            if context.contract == "forwarded_monitor_snapshots_v1":
                _check_forwarded_monitor_snapshot(row, row_count, errors)
            if context.contract == "association_loss_decisions_v1":
                _check_association_loss_decision_v1(row, row_count, errors)
            if context.contract == "health_v1":
                _check_health(row, row_count, errors)
            if context.contract == "dac_steps_v1":
                _check_dac_step(row, row_count, errors)
            if context.contract == "environment_v1":
                _check_environment(row, row_count, errors)
            if context.contract == "estimates_v2":
                _check_estimate_v2(row, row_count, errors)
            if context.contract == "control_previews_v1":
                _check_control_preview_v1(row, row_count, errors)
            if context.contract == "active_transactions_v2":
                _check_active_transaction_v2(row, row_count, errors)
            if context.contract == "active_hybrid_decisions_v2":
                _check_active_hybrid_decision_v2(row, row_count, errors)
            if context.contract == "active_hybrid_maintenance_v1":
                _check_active_hybrid_maintenance_v1(row, row_count, errors)
            if context.contract == "relative_phase_observations_v1":
                _check_relative_phase_observation_v1(row, row_count, errors)
            if context.contract == "phase_estimator_outputs_v1":
                _check_phase_estimator_output_v1(row, row_count, errors)
            if context.contract == "tight_deadband_decisions_v1":
                _check_tight_deadband_decision_v1(
                    row,
                    row_count,
                    errors,
                    expected_policy_sha256=context.expected_policy_sha256,
                )

    if row_count == 0:
        warnings.append("CSV has headers but no data rows")

    return CsvValidationResult(path=path, row_count=row_count, errors=tuple(errors), warnings=tuple(warnings))
