#include "otis_count_observation.h"

#include <Arduino.h>
#include <hardware/clocks.h>
#include <hardware/gpio.h>
#include <hardware/pio.h>
#include <hardware/pio_instructions.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>

#include "otis_board.h"
#include "otis_capture_irq.h"
#include "otis_config.h"
#include "otis_dual_core_partition.h"
#include "otis_emit.h"
#include "otis_pio_counter_math.h"
#include "otis_pps_count_boundary.h"
#include "otis_pps_count_boundary_ring.h"
#include "otis_pps_diagnostics.h"
#include "otis_pps_gate_math.h"
#include "otis_pps_snapshot_backend.h"
#include "otis_protocol.h"
#include "otis_resource_registry.h"
#include "otis_timebase.h"

#include <pico/platform.h>

namespace {

constexpr uint64_t kRp2040MonotonicUs32Modulus =
    OTIS_RP2040_MONOTONIC_US32_MODULUS;
constexpr uint32_t kH1PioCounterInitialX = 0xffffffffu;
constexpr uint32_t kImplausibleGateDurationMultiplier = 2u;

const char kWindowReasonNone[] = "none";
const char kWindowReasonNoSamples[] = "no_samples";
const char kWindowReasonAllZeroSamples[] = "all_zero_samples";
const char kWindowReasonPartialZeroSamples[] = "partial_zero_samples";
const char kWindowReasonNonPositiveGateDuration[] =
    "non_positive_gate_duration";
const char kWindowReasonImplausibleGateDuration[] =
    "implausible_gate_duration";
const char kWindowReasonCountedEdgesZero[] = "counted_edges_zero";
const char kWindowReasonMissingPps[] = "missing_pps";
const char kWindowReasonPpsIntervalAnomaly[] = "pps_interval_anomaly";
const char kWindowReasonPpsBoundaryFlagged[] = "pps_boundary_flagged";
const char kWindowReasonPpsRecoveryInhibit[] = "pps_recovery_inhibit";
const char kWindowReasonCounterSaturated[] = "counter_saturated";
const char kWindowReasonBoundaryCaptureUnavailable[] =
    "boundary_capture_unavailable";
const char kWindowReasonBoundarySequenceGap[] = "boundary_sequence_gap";
const char kWindowReasonBoundarySequenceDuplicate[] =
    "boundary_sequence_duplicate";
const char kWindowReasonBoundaryObservationOverflow[] =
    "boundary_observation_overflow";
const char kWindowReasonCounterSnapshotInvalid[] =
    "counter_snapshot_invalid";
const char kWindowReasonCounterWrapHandled[] = "counter_wrap_handled";
const char kWindowReasonCounterWrapAmbiguous[] = "counter_wrap_ambiguous";
const char kWindowReasonPhysicalApertureIncomplete[] =
    "physical_aperture_incomplete";
const char kWindowReasonObservationPairInvalid[] =
    "observation_pair_invalid";
const char kWindowReasonAssociationLoss[] = "association_loss";
const char kReferenceReasonUnavailable[] = "reference_unavailable";
const char kReferenceReasonValid[] = "reference_valid";
const char kReferenceReasonMissingPps[] = "reference_missing_pps";
const char kReferenceReasonDuplicatePps[] = "reference_pps_duplicate";
const char kReferenceReasonShortInterval[] =
    "reference_pps_short_interval";
const char kReferenceReasonLongInterval[] =
    "reference_pps_long_interval";
const char kReferenceReasonCaptureFlagged[] =
    "reference_capture_flagged";
const char kReferenceReasonPreviousBoundaryInvalid[] =
    "reference_previous_boundary_invalid";
const char kCountReasonUnavailable[] = "count_unavailable";
const char kCountReasonValid[] = "count_valid";
const char kCountReasonZero[] = "count_zero";
const char kCountReasonSaturated[] = "count_saturated";
const char kCountReasonSnapshotInvalid[] = "count_snapshot_invalid";
const char kCountReasonSnapshotAbsent[] = "count_snapshot_absent";

enum class PpsGateState : uint8_t {
  Idle,
  Armed,
  Open,
  Suspect,
  Requalifying,
  Fault,
};

struct WindowAnomaly {
  const char *reason;
  bool valid;
  bool post_startup_invalid;
  uint32_t flags;
};


struct PpsGatedRatioBackend {
  PpsGateState state;
  bool initialized_ok;
  uint64_t waiting_since_ticks;
  OtisPpsCountBoundaryObservation previous_observation;
  bool have_previous_observation;
  bool previous_boundary_inhibited;
  bool missing_before_first_reported;
  uint32_t missing_reported_after_sequence;
  bool missing_after_sequence_reported;
  bool last_window_state_known;
  bool last_window_valid;
  bool last_control_eligible;
  uint32_t accepted_window_count;
  uint32_t rejected_window_count;
  uint32_t missing_pps_count;
  uint32_t pps_interval_anomaly_count;
  uint32_t count_saturated_count;
  uint32_t boundary_sequence_gap_count;
  uint32_t boundary_sequence_duplicate_count;
  uint32_t boundary_overflow_count;
  uint32_t counter_snapshot_invalid_count;
  uint32_t physical_aperture_incomplete_count;
  uint32_t association_loss_count;
  uint32_t association_recovery_count;
  uint32_t association_loss_reference_sequence;
  bool association_reacquiring;
  const char *last_reference_validity;
  const char *last_count_validity;
  const char *last_boundary_validity;
  const char *last_aperture_validity;
  const char *last_pair_validity;
  const char *last_fifo_continuity;
  const char *last_reference_reason;
  const char *last_count_reason;
  const char *last_boundary_reason;
  const char *last_aperture_reason;
  const char *last_pair_reason;
  const char *last_reason;
  const char *association_state;
  const char *association_loss_reason;
};

PpsGatedRatioBackend pps_gated_ratio = {};
uint32_t pps_gate_status_snapshot_generation = 0u;

OtisPpsDiagnostics pps_diagnostics = {};

void emit_status(OtisStatusEmitContext *context, const char *component,
                 const char *key, const char *value, const char *severity,
                 uint32_t flags) {
  if (otis_dual_core_timing_owner_active() && get_core_num() == 1u) {
    OtisTelemetryMessage message = {};
    message.timestamp_ticks = otis_monotonic_us32_now();
    message.flags = flags;
    snprintf(message.component, sizeof(message.component), "%s", component);
    snprintf(message.key, sizeof(message.key), "%s", key);
    snprintf(message.value, sizeof(message.value), "%s", value);
    snprintf(message.severity, sizeof(message.severity), "%s", severity);
    otis_dual_core_publish_telemetry(&message);
    return;
  }
  otis_status_emit(context, component, key, value, severity, flags);
}

void emit_status_u32(OtisStatusEmitContext *context, const char *component,
                     const char *key, uint32_t value, const char *severity,
                     uint32_t flags) {
  if (otis_dual_core_timing_owner_active() && get_core_num() == 1u) {
    char formatted[24];
    snprintf(formatted, sizeof(formatted), "%lu",
             static_cast<unsigned long>(value));
    emit_status(context, component, key, formatted, severity, flags);
    return;
  }
  otis_status_emit_u32(context, component, key, value, severity, flags);
}

void emit_status_u64(OtisStatusEmitContext *context, const char *component,
                     const char *key, uint64_t value, const char *severity,
                     uint32_t flags) {
  char formatted[24];
  snprintf(formatted, sizeof(formatted), "%llu",
           static_cast<unsigned long long>(value));
  emit_status(context, component, key, formatted, severity, flags);
}

const char *bool_text(bool value) { return value ? "true" : "false"; }

const char *aperture_reason_name(uint32_t flags) {
  if ((flags & OTIS_PPS_APERTURE_OBSERVATION_OVERFLOW) != 0u) {
    return kWindowReasonBoundaryObservationOverflow;
  }
  if ((flags & OTIS_PPS_APERTURE_COUNTER_WRAP_AMBIGUOUS) != 0u) {
    return kWindowReasonCounterWrapAmbiguous;
  }
  if ((flags & OTIS_PPS_APERTURE_COUNTER_SNAPSHOT_INVALID) != 0u) {
    return kWindowReasonCounterSnapshotInvalid;
  }
  if ((flags & OTIS_PPS_APERTURE_COUNTER_SATURATED) != 0u) {
    return kWindowReasonCounterSaturated;
  }
  if ((flags & OTIS_PPS_APERTURE_ZERO_COUNT) != 0u) {
    return kWindowReasonCountedEdgesZero;
  }
  if ((flags & (OTIS_PPS_APERTURE_PREVIOUS_BOUNDARY_UNAVAILABLE |
                OTIS_PPS_APERTURE_PHYSICAL_APERTURE_INCOMPLETE)) != 0u) {
    return kWindowReasonPhysicalApertureIncomplete;
  }
  if ((flags & OTIS_PPS_APERTURE_COUNTER_WRAP_HANDLED) != 0u) {
    return kWindowReasonCounterWrapHandled;
  }
  return kWindowReasonNone;
}

const char *sequence_relation_name(OtisBoundarySequenceRelation relation) {
  switch (relation) {
    case OtisBoundarySequenceRelation::Continuous:
      return "continuous";
    case OtisBoundarySequenceRelation::Duplicate:
      return "duplicate";
    case OtisBoundarySequenceRelation::Gap:
      return "gap";
  }
  return "unavailable";
}

const char *pps_boundary_reason_name(OtisPpsBoundaryReason reason) {
  switch (reason) {
    case OtisPpsBoundaryReason::Valid:
      return kReferenceReasonValid;
    case OtisPpsBoundaryReason::Duplicate:
      return kReferenceReasonDuplicatePps;
    case OtisPpsBoundaryReason::ShortInterval:
      return kReferenceReasonShortInterval;
    case OtisPpsBoundaryReason::LongInterval:
      return kReferenceReasonLongInterval;
    case OtisPpsBoundaryReason::CaptureFlagged:
      return kReferenceReasonCaptureFlagged;
    case OtisPpsBoundaryReason::PreviousBoundaryInvalid:
      return kReferenceReasonPreviousBoundaryInvalid;
  }
  return kReferenceReasonUnavailable;
}

const char *pps_gate_state_name(PpsGateState state) {
  switch (state) {
    case PpsGateState::Idle:
      return "idle";
    case PpsGateState::Armed:
      return "armed";
    case PpsGateState::Open:
      return "open";
    case PpsGateState::Suspect:
      return "suspect";
    case PpsGateState::Requalifying:
      return "requalifying";
    case PpsGateState::Fault:
      return "fault";
  }
  return "unknown";
}

const char *physical_pps_state_name(OtisPhysicalPpsState state) {
  switch (state) {
    case OtisPhysicalPpsState::NeverSeen:
      return "never_seen";
    case OtisPhysicalPpsState::Present:
      return "present";
    case OtisPhysicalPpsState::Missing:
      return "missing";
  }
  return "unknown";
}

void emit_pps_gate_status(OtisStatusEmitContext *status_context,
                          const char *severity, uint32_t flags) {
  pps_gate_status_snapshot_generation++;
  if (pps_gate_status_snapshot_generation == 0u)
    pps_gate_status_snapshot_generation = 1u;
  emit_status(status_context, "pps_gate", "snapshot", "begin",
              OTIS_SEVERITY_INFO, flags);
  emit_status_u32(status_context, "pps_gate", "snapshot_generation",
                  pps_gate_status_snapshot_generation,
                  OTIS_SEVERITY_INFO, flags);
  emit_status(status_context, "pps_gate", "backend", "pps_gated_ratio",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "pps_gate", "boundary_owner", "pio_state_machine",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "pps_gate", "aperture_backend",
              "pio_wait_cumulative_snapshot_dma_v1", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "pps_gate", "backend_qualified",
              "true", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "pps_gate", "valid",
              bool_text(pps_gated_ratio.last_window_state_known &&
                        pps_gated_ratio.last_window_valid),
              pps_gated_ratio.last_window_valid ? OTIS_SEVERITY_INFO
                                                : OTIS_SEVERITY_WARN,
              flags);
  emit_status(status_context, "pps_gate", "control_eligible",
              bool_text(pps_gated_ratio.last_control_eligible),
              pps_gated_ratio.last_control_eligible ? OTIS_SEVERITY_INFO
                                                    : OTIS_SEVERITY_WARN,
              flags);
  emit_status(status_context, "pps_gate", "state",
              pps_gate_state_name(pps_gated_ratio.state), severity, flags);
  emit_status(status_context, "pps_gate", "last_reason",
              pps_gated_ratio.last_reason, severity, flags);
  emit_status(status_context, "pps_gate", "reference_validity",
              pps_gated_ratio.last_reference_validity, severity, flags);
  emit_status(status_context, "pps_gate", "reference_reason",
              pps_gated_ratio.last_reference_reason, severity, flags);
  emit_status(status_context, "pps_gate", "count_validity",
              pps_gated_ratio.last_count_validity, severity, flags);
  emit_status(status_context, "pps_gate", "count_reason",
              pps_gated_ratio.last_count_reason, severity, flags);
  emit_status(status_context, "pps_gate", "boundary_validity",
              pps_gated_ratio.last_boundary_validity, severity, flags);
  emit_status(status_context, "pps_gate", "boundary_reason",
              pps_gated_ratio.last_boundary_reason, severity, flags);
  emit_status(status_context, "pps_gate", "aperture_validity",
              pps_gated_ratio.last_aperture_validity, severity, flags);
  emit_status(status_context, "pps_gate", "aperture_reason",
              pps_gated_ratio.last_aperture_reason, severity, flags);
  emit_status(status_context, "pps_gate", "observation_pair_validity",
              pps_gated_ratio.last_pair_validity, severity, flags);
  emit_status(status_context, "pps_gate", "observation_pair_reason",
              pps_gated_ratio.last_pair_reason, severity, flags);
  emit_status(status_context, "pps_gate", "fifo_continuity",
              pps_gated_ratio.last_fifo_continuity, severity, flags);
  emit_status(status_context, "pps_gate", "association_state",
              pps_gated_ratio.association_state, severity, flags);
  emit_status(status_context, "pps_gate", "association_loss_reason",
              pps_gated_ratio.association_loss_reason, severity, flags);
  if (pps_gated_ratio.have_previous_observation) {
    emit_status_u32(status_context, "pps_gate", "boundary_sequence",
                    pps_gated_ratio.previous_observation.sequence,
                    OTIS_SEVERITY_INFO, flags);
  }
  emit_status_u32(
      status_context, "pps_gate", "boundary_reference_sequence",
      pps_gated_ratio.have_previous_observation
          ? pps_gated_ratio.previous_observation.reference_sequence
          : 0u,
      OTIS_SEVERITY_INFO, flags);
  emit_status_u32(status_context, "pps_gate", "boundary_ring_depth",
                  otis_pps_count_boundary_ring_depth(), OTIS_SEVERITY_INFO,
                  flags);
  emit_status_u32(status_context, "pps_gate", "boundary_ring_capacity",
                  otis_pps_count_boundary_ring_capacity(), OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  uint32_t boundary_ring_dropped_count =
      otis_pps_count_boundary_ring_dropped_count();
  emit_status_u32(status_context, "pps_gate", "boundary_ring_dropped_count",
                  boundary_ring_dropped_count,
                  boundary_ring_dropped_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate", "accepted_window_count",
                  pps_gated_ratio.accepted_window_count, OTIS_SEVERITY_INFO,
                  flags);
  emit_status_u32(status_context, "pps_gate", "rejected_window_count",
                  pps_gated_ratio.rejected_window_count,
                  pps_gated_ratio.rejected_window_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate", "missing_pps_count",
                  pps_gated_ratio.missing_pps_count,
                  pps_gated_ratio.missing_pps_count == 0u ? OTIS_SEVERITY_INFO
                                                          : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate", "pps_interval_anomaly_count",
                  pps_gated_ratio.pps_interval_anomaly_count,
                  pps_gated_ratio.pps_interval_anomaly_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate", "count_saturated_count",
                  pps_gated_ratio.count_saturated_count,
                  pps_gated_ratio.count_saturated_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate", "boundary_sequence_gap_count",
                  pps_gated_ratio.boundary_sequence_gap_count,
                  pps_gated_ratio.boundary_sequence_gap_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate",
                  "boundary_sequence_duplicate_count",
                  pps_gated_ratio.boundary_sequence_duplicate_count,
                  pps_gated_ratio.boundary_sequence_duplicate_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate", "boundary_overflow_count",
                  pps_gated_ratio.boundary_overflow_count,
                  pps_gated_ratio.boundary_overflow_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate",
                  "counter_snapshot_invalid_count",
                  pps_gated_ratio.counter_snapshot_invalid_count,
                  pps_gated_ratio.counter_snapshot_invalid_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate",
                  "physical_aperture_incomplete_count",
                  pps_gated_ratio.physical_aperture_incomplete_count,
                  pps_gated_ratio.physical_aperture_incomplete_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate", "association_loss_count",
                  pps_gated_ratio.association_loss_count,
                  pps_gated_ratio.association_loss_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate", "association_recovery_count",
                  pps_gated_ratio.association_recovery_count,
                  OTIS_SEVERITY_INFO, flags);
  emit_status_u32(status_context, "pps_gate",
                  "association_loss_reference_sequence",
                  pps_gated_ratio.association_loss_reference_sequence,
                  OTIS_SEVERITY_INFO, flags);
  OtisPpsSnapshotBackendStats snapshot_stats;
  otis_pps_snapshot_backend_get_stats(&snapshot_stats);
  emit_status_u32(status_context, "pps_gate", "snapshot_session",
                  snapshot_stats.session, OTIS_SEVERITY_INFO, flags);
  emit_status_u32(status_context, "pps_gate", "snapshot_producer_sequence",
                  snapshot_stats.producer_ordinal, OTIS_SEVERITY_INFO, flags);
  emit_status_u32(status_context, "pps_gate", "snapshot_consumer_sequence",
                  snapshot_stats.consumer_ordinal, OTIS_SEVERITY_INFO, flags);
  emit_status_u32(status_context, "pps_gate", "snapshot_backlog_depth",
                  snapshot_stats.backlog_depth,
                  snapshot_stats.backlog_depth == 0u ? OTIS_SEVERITY_INFO
                                                     : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate", "snapshot_backlog_high_water",
                  snapshot_stats.backlog_high_water, OTIS_SEVERITY_INFO,
                  flags);
  emit_status_u32(status_context, "pps_gate", "snapshot_overwrite_count",
                  snapshot_stats.overwrite_count,
                  snapshot_stats.overwrite_count == 0u ? OTIS_SEVERITY_INFO
                                                       : OTIS_SEVERITY_ERROR,
                  flags);
  emit_status_u32(status_context, "pps_gate", "snapshot_continuity_loss_count",
                  snapshot_stats.continuity_loss_count,
                  snapshot_stats.continuity_loss_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_ERROR,
                  flags);
  emit_status_u32(status_context, "pps_gate", "snapshot_pio_rxstall_count",
                  snapshot_stats.pio_rxstall_count,
                  snapshot_stats.pio_rxstall_count == 0u ? OTIS_SEVERITY_INFO
                                                         : OTIS_SEVERITY_ERROR,
                  flags);
  emit_status_u32(status_context, "pps_gate", "snapshot_dma_error_count",
                  snapshot_stats.dma_error_count,
                  snapshot_stats.dma_error_count == 0u ? OTIS_SEVERITY_INFO
                                                       : OTIS_SEVERITY_ERROR,
                  flags);
  emit_status_u32(status_context, "pps_gate", "snapshot_dma_stopped_count",
                  snapshot_stats.dma_stopped_count,
                  snapshot_stats.dma_stopped_count == 0u ? OTIS_SEVERITY_INFO
                                                         : OTIS_SEVERITY_ERROR,
                  flags);
  emit_status(status_context, "pps_gate", "physical_pps_state",
              physical_pps_state_name(pps_diagnostics.physical_state),
              pps_diagnostics.physical_state == OtisPhysicalPpsState::Present
                  ? OTIS_SEVERITY_INFO
                  : OTIS_SEVERITY_WARN,
              flags);
  emit_status_u32(status_context, "pps_gate", "physical_pps_missing_count",
                  pps_diagnostics.physical_pps_missing_count,
                  pps_diagnostics.physical_pps_missing_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate", "physical_pps_restored_count",
                  pps_diagnostics.physical_pps_restored_count,
                  OTIS_SEVERITY_INFO, flags);
  emit_status_u32(status_context, "pps_gate", "physical_pps_reminder_count",
                  pps_diagnostics.physical_pps_reminder_count,
                  OTIS_SEVERITY_INFO, flags);
  emit_status(status_context, "pps_gate", "snapshot", "end",
              OTIS_SEVERITY_INFO, flags);
}

void emit_pps_gate_window_status(OtisRuntimeState *runtime_state,
                                 OtisStatusEmitContext *status_context,
                                 const WindowAnomaly &anomaly,
                                 bool ratio_available) {
  uint32_t flags = runtime_state->tcxo.last_window_flags;
  emit_status(status_context, "pps_gate", "valid", bool_text(anomaly.valid),
              anomaly.valid ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN, flags);
  emit_status(status_context, "pps_gate", "ratio_available",
              bool_text(ratio_available),
              ratio_available ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              flags);
  emit_status_u32(status_context, "pps_gate", "last_interval_us",
                  runtime_state->tcxo.last_elapsed_us,
                  anomaly.valid ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
                  flags);
  emit_status(status_context, "pps_gate", "startup_inhibit_active",
              bool_text(runtime_state->tcxo.startup_inhibit_active),
              runtime_state->tcxo.startup_inhibit_active ? OTIS_SEVERITY_WARN
                                                         : OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "pps_gate", "control_eligible",
              bool_text(runtime_state->tcxo.valid_for_control),
              runtime_state->tcxo.valid_for_control ? OTIS_SEVERITY_INFO
                                                    : OTIS_SEVERITY_WARN,
              flags);
  emit_status_u32(status_context, "pps_gate", "consecutive_bad_window_count",
                  runtime_state->tcxo.consecutive_bad_windows,
                  runtime_state->tcxo.consecutive_bad_windows == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate", "total_bad_window_count",
                  runtime_state->tcxo.total_bad_windows,
                  runtime_state->tcxo.total_bad_windows == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
  emit_pps_gate_status(status_context,
                       anomaly.valid ? OTIS_SEVERITY_INFO
                                     : OTIS_SEVERITY_WARN,
                       flags);
}

void emit_pps_gate_fault(OtisRuntimeState *runtime_state,
                         OtisStatusEmitContext *status_context,
                         const char *reason,
                         const char *reference_reason,
                         const char *count_reason,
                         uint32_t flags) {
  pps_gated_ratio.last_reason = reason;
  pps_gated_ratio.last_control_eligible = false;
  pps_gated_ratio.last_window_state_known = true;
  pps_gated_ratio.last_window_valid = false;
  pps_gated_ratio.last_reference_validity = "invalid";
  pps_gated_ratio.last_count_validity = "unavailable";
  pps_gated_ratio.last_boundary_validity = "unavailable";
  pps_gated_ratio.last_aperture_validity = "invalid";
  pps_gated_ratio.last_pair_validity = "invalid";
  pps_gated_ratio.last_fifo_continuity = "unavailable";
  pps_gated_ratio.last_reference_reason = reference_reason;
  pps_gated_ratio.last_count_reason = count_reason;
  pps_gated_ratio.last_boundary_reason = kWindowReasonBoundaryCaptureUnavailable;
  pps_gated_ratio.last_aperture_reason = kWindowReasonPhysicalApertureIncomplete;
  pps_gated_ratio.last_pair_reason = kWindowReasonObservationPairInvalid;
  pps_gated_ratio.state = PpsGateState::Suspect;
  otis_pps_diagnostics_increment_saturating(
      &pps_gated_ratio.rejected_window_count);
  runtime_state->tcxo.consecutive_bad_windows += 1u;
  runtime_state->tcxo.total_bad_windows += 1u;
  runtime_state->tcxo.control_clean_window_count = 0u;
  runtime_state->tcxo.valid_for_control = false;
  if (!runtime_state->tcxo.startup_inhibit_active) {
    runtime_state->tcxo.fault_after_startup = true;
  }
  runtime_state->tcxo.last_observation_valid = false;
  runtime_state->tcxo.last_window_invalid_reason = reason;
  runtime_state->tcxo.last_window_flags = flags;
  emit_status(status_context, "pps_gate", "valid", "false",
              OTIS_SEVERITY_WARN, flags);
  emit_status(status_context, "pps_gate", "ratio_available", "false",
              OTIS_SEVERITY_WARN, flags);
  emit_status(status_context, "pps_gate", "startup_inhibit_active",
              bool_text(runtime_state->tcxo.startup_inhibit_active),
              runtime_state->tcxo.startup_inhibit_active ? OTIS_SEVERITY_WARN
                                                         : OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "pps_gate", "control_eligible", "false",
              OTIS_SEVERITY_WARN, flags);
  emit_pps_gate_status(status_context, OTIS_SEVERITY_WARN, flags);
}


void emit_bad_window_diagnostics(OtisRuntimeState *runtime_state,
                                 OtisStatusEmitContext *status_context,
                                 const WindowAnomaly &anomaly) {
  uint32_t flags = runtime_state->tcxo.last_window_flags;
  emit_status(status_context, "count_path", "window_invalid_reason",
              runtime_state->tcxo.last_window_invalid_reason, OTIS_SEVERITY_WARN,
              flags);
  emit_status_u32(status_context, "count_path", "window_sample_count",
                  runtime_state->tcxo.last_sample_count, OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "count_path", "window_zero_sample_count",
                  runtime_state->tcxo.last_zero_sample_count, OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "count_path", "window_valid_sample_count",
                  runtime_state->tcxo.last_valid_sample_count,
                  OTIS_SEVERITY_WARN, flags);
  emit_status_u32(status_context, "count_path", "window_first_sample_khz",
                  runtime_state->tcxo.last_first_sample_khz,
                  OTIS_SEVERITY_WARN, flags);
  emit_status_u32(status_context, "count_path", "window_last_sample_khz",
                  runtime_state->tcxo.last_last_sample_khz, OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "count_path", "window_min_sample_khz",
                  runtime_state->tcxo.last_min_sample_khz, OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "count_path", "window_max_sample_khz",
                  runtime_state->tcxo.last_max_sample_khz, OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "count_path", "window_elapsed_us",
                  runtime_state->tcxo.last_elapsed_us, OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "count_path", "window_flags",
                  runtime_state->tcxo.last_window_flags, OTIS_SEVERITY_WARN,
                  flags);
  emit_status(status_context, "count_path", "post_startup_invalid_window",
              anomaly.post_startup_invalid ? "true" : "false",
              anomaly.post_startup_invalid ? OTIS_SEVERITY_WARN
                                           : OTIS_SEVERITY_INFO,
              flags);
  emit_status_u32(status_context, "count_path", "consecutive_bad_windows",
                  runtime_state->tcxo.consecutive_bad_windows,
                  OTIS_SEVERITY_WARN, flags);
  emit_status_u32(status_context, "count_path", "total_bad_windows",
                  runtime_state->tcxo.total_bad_windows, OTIS_SEVERITY_WARN,
                  flags);
}

bool gate_duration_implausible(uint32_t elapsed_us,
                               const OtisCountObservationConfig *config) {
  if (config->gate_period_us == 0u) {
    return true;
  }
  uint64_t max_gate_us =
      (uint64_t)config->gate_period_us * kImplausibleGateDurationMultiplier;
  return (uint64_t)elapsed_us > max_gate_us;
}

void update_startup_inhibit(OtisRuntimeState *runtime_state,
                            const OtisCountObservationConfig *config,
                            uint32_t now_ms) {
  runtime_state->tcxo.startup_inhibit_elapsed_s =
      (uint32_t)((now_ms - runtime_state->tcxo.startup_inhibit_start_ms) /
                 1000u);
  runtime_state->tcxo.startup_inhibit_active =
      (uint32_t)(now_ms - runtime_state->tcxo.startup_inhibit_start_ms) <
      config->startup_inhibit_ms;
}

WindowAnomaly classify_window(OtisRuntimeState *runtime_state,
                              const OtisCountObservationConfig *config,
                              bool expect_samples,
                              bool expect_counted_edges) {
  WindowAnomaly anomaly = {
      kWindowReasonNone,
      true,
      false,
      runtime_state->tcxo.last_window_flags,
  };

  if (runtime_state->tcxo.last_elapsed_us == 0u) {
    anomaly.reason = kWindowReasonNonPositiveGateDuration;
    anomaly.valid = false;
    anomaly.flags |= OTIS_FLAG_GATE_INCOMPLETE;
  } else if (gate_duration_implausible(runtime_state->tcxo.last_elapsed_us,
                                       config)) {
    anomaly.reason = kWindowReasonImplausibleGateDuration;
    anomaly.valid = false;
    anomaly.flags |= OTIS_FLAG_GATE_INCOMPLETE;
  } else if (expect_samples && runtime_state->tcxo.last_sample_count == 0u) {
    anomaly.reason = kWindowReasonNoSamples;
    anomaly.valid = false;
    anomaly.flags |= OTIS_FLAG_GATE_INCOMPLETE;
  } else if (expect_samples &&
             runtime_state->tcxo.last_zero_sample_count ==
                 runtime_state->tcxo.last_sample_count) {
    anomaly.reason = kWindowReasonAllZeroSamples;
    anomaly.valid = false;
    anomaly.flags |= OTIS_FLAG_INPUT_STUCK_LOW;
  } else if (expect_samples &&
             runtime_state->tcxo.last_zero_sample_count > 0u) {
    anomaly.reason = kWindowReasonPartialZeroSamples;
    anomaly.valid = false;
    anomaly.flags |= OTIS_FLAG_SOURCE_HEALTH_SUSPECT;
  } else if (expect_counted_edges &&
             runtime_state->tcxo.last_counted_edges == 0ull) {
    anomaly.reason = kWindowReasonCountedEdgesZero;
    anomaly.valid = false;
    anomaly.flags |=
        OTIS_FLAG_SOURCE_HEALTH_SUSPECT | OTIS_FLAG_INPUT_STUCK_LOW;
  }

  runtime_state->tcxo.last_window_flags = anomaly.flags;
  runtime_state->tcxo.last_window_invalid_reason = anomaly.reason;
  return anomaly;
}

void record_window_quality(OtisRuntimeState *runtime_state,
                           const WindowAnomaly &anomaly) {
  runtime_state->tcxo.last_observation_valid = anomaly.valid;
  if (anomaly.valid) {
    runtime_state->tcxo.consecutive_bad_windows = 0;
  } else {
    runtime_state->tcxo.consecutive_bad_windows += 1u;
    runtime_state->tcxo.total_bad_windows += 1u;
  }
}

void update_control_gate(OtisRuntimeState *runtime_state,
                         const OtisCountObservationConfig *config,
                         WindowAnomaly *anomaly, uint32_t now_ms) {
  update_startup_inhibit(runtime_state, config, now_ms);

  if (!anomaly->valid) {
    runtime_state->tcxo.control_clean_window_count = 0;
    runtime_state->tcxo.valid_for_control = false;
    if (!runtime_state->tcxo.startup_inhibit_active) {
      runtime_state->tcxo.fault_after_startup = true;
    }
    anomaly->post_startup_invalid = !runtime_state->tcxo.startup_inhibit_active;
    return;
  }

  if (runtime_state->tcxo.startup_inhibit_active) {
    runtime_state->tcxo.control_clean_window_count = 0;
    runtime_state->tcxo.valid_for_control = false;
    return;
  }

  if (runtime_state->tcxo.control_clean_window_count < UINT32_MAX) {
    runtime_state->tcxo.control_clean_window_count += 1u;
  }
  runtime_state->tcxo.valid_for_control =
      runtime_state->tcxo.control_clean_window_count >=
      config->control_ready_clean_windows;
  if (runtime_state->tcxo.valid_for_control) {
    runtime_state->tcxo.fault_after_startup = false;
  }
}

void emit_count_observation(OtisRuntimeState *runtime_state,
                            const OtisCountObservationConfig *config,
                            uint64_t counted_edges, uint32_t flags) {
  if (otis_dual_core_timing_owner_active() && get_core_num() == 1u) {
    OtisObservationMessage message = {};
    message.kind = OtisObservationMessageKind::CountObservation;
    message.count.sequence = runtime_state->sequences.count_seq++;
    message.count.channel_id = OTIS_CHANNEL_OSC_OBSERVATION;
    message.count.gate_open_ticks =
        runtime_state->tcxo.last_gate_open_ticks;
    message.count.gate_close_ticks =
        runtime_state->tcxo.last_gate_close_ticks;
    message.count.counted_edges = counted_edges;
    message.count.flags = flags;
    snprintf(message.count.source_domain,
             sizeof(message.count.source_domain), "%s",
             config->source_domain);
    otis_dual_core_publish_observation(&message);
    return;
  }
  otis_emit_count_observation(
      runtime_state->sequences.count_seq++, OTIS_CHANNEL_OSC_OBSERVATION,
      runtime_state->tcxo.last_gate_open_ticks,
      runtime_state->tcxo.last_gate_close_ticks, OTIS_DOMAIN_RP2040_MONOTONIC_US32,
      counted_edges, OTIS_EDGE_RISING, config->source_domain, flags);
}

}  // namespace

bool otis_count_observation_begin(OtisRuntimeState *runtime_state,
                                  OtisStatusEmitContext *status_context,
                                  const OtisCountObservationConfig *config) {
  (void)runtime_state;
  bool counter_ok = otis_pps_snapshot_backend_begin();
  otis_pps_count_boundary_ring_reset();
  OtisPpsSnapshotBackendStats snapshot_stats;
  otis_pps_snapshot_backend_get_stats(&snapshot_stats);
  OtisPpsDiagnosticsConfig diagnostics_config = {
      static_cast<uint64_t>(OTIS_PPS_GATE_MISSING_TIMEOUT_US),
      0u,
  };
  otis_pps_diagnostics_begin(&pps_diagnostics, diagnostics_config,
                             snapshot_stats.session,
                             otis_monotonic_us32_now());
  pps_gated_ratio.state = counter_ok ? PpsGateState::Armed
                                     : PpsGateState::Fault;
  pps_gated_ratio.initialized_ok = counter_ok;
  pps_gated_ratio.waiting_since_ticks = otis_monotonic_us32_now();
  pps_gated_ratio.previous_observation = {};
  pps_gated_ratio.have_previous_observation = false;
  pps_gated_ratio.previous_boundary_inhibited = false;
  pps_gated_ratio.missing_before_first_reported = false;
  pps_gated_ratio.missing_reported_after_sequence = 0u;
  pps_gated_ratio.missing_after_sequence_reported = false;
  pps_gated_ratio.last_window_state_known = false;
  pps_gated_ratio.last_window_valid = false;
  pps_gated_ratio.last_control_eligible = false;
  pps_gated_ratio.accepted_window_count = 0;
  pps_gated_ratio.rejected_window_count = 0;
  pps_gated_ratio.missing_pps_count = 0;
  pps_gated_ratio.pps_interval_anomaly_count = 0;
  pps_gated_ratio.count_saturated_count = 0;
  pps_gated_ratio.boundary_sequence_gap_count = 0;
  pps_gated_ratio.boundary_sequence_duplicate_count = 0;
  pps_gated_ratio.boundary_overflow_count = 0;
  pps_gated_ratio.counter_snapshot_invalid_count = 0;
  pps_gated_ratio.physical_aperture_incomplete_count = 0;
  pps_gated_ratio.association_loss_count = 0;
  pps_gated_ratio.association_recovery_count = 0;
  pps_gated_ratio.association_loss_reference_sequence = 0u;
  pps_gated_ratio.association_reacquiring = false;
  pps_gated_ratio.last_reference_validity = "unavailable";
  pps_gated_ratio.last_count_validity = "unavailable";
  pps_gated_ratio.last_boundary_validity = "unavailable";
  pps_gated_ratio.last_aperture_validity = "unavailable";
  pps_gated_ratio.last_pair_validity = "unavailable";
  pps_gated_ratio.last_fifo_continuity = "unavailable";
  pps_gated_ratio.last_reference_reason = kReferenceReasonUnavailable;
  pps_gated_ratio.last_count_reason = kCountReasonUnavailable;
  pps_gated_ratio.last_boundary_reason =
      kWindowReasonBoundaryCaptureUnavailable;
  pps_gated_ratio.last_aperture_reason =
      kWindowReasonPhysicalApertureIncomplete;
  pps_gated_ratio.last_pair_reason = kWindowReasonObservationPairInvalid;
  pps_gated_ratio.last_reason = counter_ok ? kWindowReasonNone
                                           : "counter_init_failed";
  pps_gated_ratio.association_state =
      counter_ok ? "awaiting_anchor" : "lost";
  pps_gated_ratio.association_loss_reason = "none";
  emit_status(status_context, "capture", "tcxo_counter_backend",
              "pps_gated_ratio", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "capture", "pps_gated_ratio_init",
              counter_ok ? "ok" : "failed",
              counter_ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              counter_ok ? OTIS_FLAG_CONFIGURATION_ASSUMPTION
                         : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32(status_context, "pps_gate", "pps_gpio",
                  OTIS_PIN_PPS_REFERENCE, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "osc_gpio",
                  OTIS_GPIO_OSC_OBSERVATION, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "min_interval_us",
                  OTIS_PPS_GATE_MIN_INTERVAL_US, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "duplicate_max_interval_us",
                  OTIS_PPS_GATE_DUPLICATE_MAX_INTERVAL_US,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "max_interval_us",
                  OTIS_PPS_GATE_MAX_INTERVAL_US, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "missing_timeout_us",
                  OTIS_PPS_GATE_MISSING_TIMEOUT_US, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "count_resolution_edges", 1u,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "pps_gate", "counter_direction", "down",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "counter_width_bits", 32u,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate",
                  "declared_max_captured_edge_rate_hz",
                  OTIS_PPS_SNAPSHOT_MAX_CAPTURED_EDGE_RATE_HZ,
                  OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "pio_system_clock_hz",
                  snapshot_stats.system_clock_hz, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "pps_gate", "pio_clock_divider", "1.0",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "snapshot_rx_fifo_depth", 8u,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "snapshot_ring_capacity",
                  snapshot_stats.ring_capacity, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "boundary_ring_capacity",
                  otis_pps_count_boundary_ring_capacity(), OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "pps_gate", "boundary_owner", "pio_state_machine",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "pps_gate", "aperture_backend",
              "pio_wait_cumulative_snapshot_dma_v1", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "pps_gate", "backend_qualified",
              "true", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "pps_gate",
              "counter_aperture_uncertainty_ns", "unavailable",
              OTIS_SEVERITY_WARN, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "pps_gate",
              "reference_frequency_uncertainty_ppb", "unavailable",
              OTIS_SEVERITY_WARN, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  if (counter_ok) {
    emit_status_u32(status_context, "pps_gate", "counter_pio",
                    snapshot_stats.pio_block,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
    emit_status_u32(status_context, "pps_gate", "counter_sm",
                    snapshot_stats.state_machine, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_CONFIGURATION_ASSUMPTION);
    emit_status_u32(status_context, "pps_gate", "counter_program_offset",
                    snapshot_stats.program_offset, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_CONFIGURATION_ASSUMPTION);
    emit_status_u32(status_context, "pps_gate", "counter_program_length",
                    snapshot_stats.program_length, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_CONFIGURATION_ASSUMPTION);
    emit_status_u32(status_context, "pps_gate", "snapshot_dma_channel",
                    snapshot_stats.dma_channel, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  }
  emit_pps_gate_status(status_context,
                       counter_ok ? OTIS_SEVERITY_INFO
                                  : OTIS_SEVERITY_ERROR,
                       counter_ok ? OTIS_FLAG_CONFIGURATION_ASSUMPTION
                                  : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  return counter_ok;
}

bool otis_count_observation_on_pps_boundary(
    OtisRuntimeState *runtime_state,
    OtisStatusEmitContext *status_context,
    const OtisCountObservationConfig *config,
    const OtisPpsCountBoundaryObservation *observation) {
  if (observation == nullptr) {
    return false;
  }

  uint64_t boundary_service_ticks = otis_monotonic_us32_now();
  otis_pps_diagnostics_note_snapshot_drained(
      &pps_diagnostics, observation->session, observation->sequence,
      boundary_service_ticks);
  // The raw SNP record is emitted by the caller before this boundary is
  // reconstructed. Keep transport progress distinct from measurement state.
  otis_pps_diagnostics_note_telemetry_emitted(
      &pps_diagnostics, observation->session, observation->sequence,
      boundary_service_ticks);

  uint32_t now_ms = millis();
  update_startup_inhibit(runtime_state, config, now_ms);

  if (pps_gated_ratio.have_previous_observation &&
      pps_gated_ratio.previous_observation.session != observation->session) {
    pps_gated_ratio.have_previous_observation = false;
    pps_gated_ratio.previous_boundary_inhibited = true;
    pps_gated_ratio.association_state = "awaiting_anchor";
    pps_gated_ratio.association_reacquiring = true;
  }

  if (!pps_gated_ratio.have_previous_observation) {
    bool boundary_valid =
        (observation->aperture_flags &
         OTIS_PPS_APERTURE_BOUNDARY_CAPTURE_UNAVAILABLE) == 0u;
    pps_gated_ratio.previous_observation = *observation;
    pps_gated_ratio.have_previous_observation = true;
    pps_gated_ratio.previous_boundary_inhibited = !boundary_valid;
    pps_gated_ratio.state = boundary_valid ? PpsGateState::Requalifying
                                           : PpsGateState::Suspect;
    pps_gated_ratio.last_reference_validity = "unavailable";
    pps_gated_ratio.last_count_validity = "unavailable";
    pps_gated_ratio.last_boundary_validity =
        boundary_valid ? "valid" : "invalid";
    pps_gated_ratio.last_aperture_validity = "invalid";
    pps_gated_ratio.last_pair_validity = "invalid";
    pps_gated_ratio.last_fifo_continuity = "unavailable";
    pps_gated_ratio.last_reference_reason = kReferenceReasonUnavailable;
    pps_gated_ratio.last_count_reason = kCountReasonUnavailable;
    pps_gated_ratio.last_boundary_reason =
        boundary_valid ? "boundary_valid"
                       : kWindowReasonBoundaryCaptureUnavailable;
    pps_gated_ratio.last_aperture_reason =
        kWindowReasonPhysicalApertureIncomplete;
    pps_gated_ratio.last_pair_reason = kWindowReasonObservationPairInvalid;
    pps_gated_ratio.last_reason = kWindowReasonPpsRecoveryInhibit;
    pps_gated_ratio.association_state = "anchor";
    otis_pps_diagnostics_increment_saturating(
        &pps_gated_ratio.physical_aperture_incomplete_count);
    emit_pps_gate_status(status_context, OTIS_SEVERITY_WARN,
                         observation->capture_flags |
                             OTIS_FLAG_GATE_INCOMPLETE);
    return false;
  }

  const OtisPpsCountBoundaryObservation previous =
      pps_gated_ratio.previous_observation;
  OtisBoundarySequenceRelation sequence_relation =
      otis_boundary_sequence_relation(previous.sequence,
                                      observation->sequence);
  OtisBoundarySequenceRelation reference_sequence_relation =
      otis_boundary_sequence_relation(previous.reference_sequence,
                                      observation->reference_sequence);
  if (reference_sequence_relation !=
      OtisBoundarySequenceRelation::Continuous) {
    sequence_relation = reference_sequence_relation;
  }
  uint32_t aperture_flags = observation->aperture_flags;
  constexpr uint32_t kMaximumUnambiguousWindowCount =
      static_cast<uint32_t>(
          (static_cast<uint64_t>(
               OTIS_PPS_SNAPSHOT_MAX_CAPTURED_EDGE_RATE_HZ) *
           OTIS_PPS_GATE_MAX_INTERVAL_US) /
          1000000ull);
  OtisCounterSnapshotDelta snapshot_delta =
      otis_down_counter_snapshot_delta_u32(
          previous.cumulative_down_counter,
          observation->cumulative_down_counter,
          kMaximumUnambiguousWindowCount);
  if (snapshot_delta.wrap_handled) {
    aperture_flags |= OTIS_PPS_APERTURE_COUNTER_WRAP_HANDLED;
  }
  if (snapshot_delta.wrap_ambiguous) {
    aperture_flags |= OTIS_PPS_APERTURE_COUNTER_WRAP_AMBIGUOUS;
  }
  if (snapshot_delta.count == 0u) {
    aperture_flags |= OTIS_PPS_APERTURE_ZERO_COUNT;
  }
  uint32_t wire_flags =
      previous.capture_flags | observation->capture_flags;
  if ((aperture_flags & OTIS_PPS_APERTURE_OBSERVATION_OVERFLOW) != 0u) {
    otis_pps_diagnostics_increment_saturating(
        &pps_gated_ratio.boundary_overflow_count);
    wire_flags |= OTIS_FLAG_CAPTURE_RING_OVERRUN |
                  OTIS_FLAG_GATE_INCOMPLETE;
  }
  if (sequence_relation == OtisBoundarySequenceRelation::Gap) {
    otis_pps_diagnostics_increment_saturating(
        &pps_gated_ratio.boundary_sequence_gap_count);
    wire_flags |= OTIS_FLAG_EDGE_ORDER_SUSPECT |
                  OTIS_FLAG_CAPTURE_RING_OVERRUN |
                  OTIS_FLAG_GATE_INCOMPLETE;
  } else if (sequence_relation ==
             OtisBoundarySequenceRelation::Duplicate) {
    otis_pps_diagnostics_increment_saturating(
        &pps_gated_ratio.boundary_sequence_duplicate_count);
    wire_flags |= OTIS_FLAG_EDGE_ORDER_SUSPECT |
                  OTIS_FLAG_GATE_INCOMPLETE;
  }
  if ((aperture_flags &
       OTIS_PPS_APERTURE_BOUNDARY_CAPTURE_UNAVAILABLE) != 0u) {
    wire_flags |= OTIS_FLAG_SOURCE_HEALTH_SUSPECT |
                  OTIS_FLAG_GATE_INCOMPLETE;
  }
  if ((aperture_flags &
       OTIS_PPS_APERTURE_COUNTER_SNAPSHOT_INVALID) != 0u) {
    otis_pps_diagnostics_increment_saturating(
        &pps_gated_ratio.counter_snapshot_invalid_count);
    wire_flags |= OTIS_FLAG_SOURCE_HEALTH_SUSPECT |
                  OTIS_FLAG_GATE_INCOMPLETE;
  }
  if ((aperture_flags &
       OTIS_PPS_APERTURE_PHYSICAL_APERTURE_INCOMPLETE) != 0u) {
    otis_pps_diagnostics_increment_saturating(
        &pps_gated_ratio.physical_aperture_incomplete_count);
    wire_flags |= OTIS_FLAG_GATE_INCOMPLETE;
  }
  if ((aperture_flags & OTIS_PPS_APERTURE_COUNTER_SATURATED) != 0u) {
    otis_pps_diagnostics_increment_saturating(
        &pps_gated_ratio.count_saturated_count);
    wire_flags |= OTIS_FLAG_COUNT_SATURATED;
  }
  if ((aperture_flags & OTIS_PPS_APERTURE_ZERO_COUNT) != 0u) {
    wire_flags |= OTIS_FLAG_SOURCE_HEALTH_SUSPECT |
                  OTIS_FLAG_INPUT_STUCK_LOW;
  }
  if ((aperture_flags &
       OTIS_PPS_APERTURE_COUNTER_WRAP_AMBIGUOUS) != 0u) {
    wire_flags |= OTIS_FLAG_SOURCE_HEALTH_SUSPECT |
                  OTIS_FLAG_GATE_INCOMPLETE;
  }

  OtisPpsBoundaryAssessment raw_boundary = otis_pps_gate_assess_boundary(
      previous.pps_timestamp_ticks, observation->pps_timestamp_ticks,
      previous.capture_flags | observation->capture_flags,
      (uint64_t)OTIS_PPS_GATE_DUPLICATE_MAX_INTERVAL_US,
      (uint64_t)OTIS_PPS_GATE_MIN_INTERVAL_US,
      (uint64_t)OTIS_PPS_GATE_MAX_INTERVAL_US);
  OtisPpsBoundaryAssessment boundary = raw_boundary;
  if (pps_gated_ratio.previous_boundary_inhibited && raw_boundary.valid) {
    boundary.valid = false;
    boundary.reason = OtisPpsBoundaryReason::PreviousBoundaryInvalid;
  }

  OtisPpsCountWindowValidity validity = otis_pps_count_window_validity(
      true, boundary.valid, sequence_relation, aperture_flags, true);
  bool measurement_valid =
      validity.reference_interval_valid &&
      validity.count_boundary_valid &&
      validity.counter_window_valid &&
      validity.observation_pair_valid &&
      validity.fifo_continuous;

  uint64_t observation_span_us =
      otis_monotonic_us32_interval(previous.pps_timestamp_ticks,
                                   observation->pps_timestamp_ticks);
  uint64_t counted_edges = snapshot_delta.count;
  uint32_t measured_khz = 0u;
  if (observation_span_us > 0u) {
    measured_khz =
        static_cast<uint32_t>((counted_edges * 1000ull) /
                              observation_span_us);
  }
  runtime_state->tcxo.last_gate_open_ticks =
      previous.pps_timestamp_ticks;
  runtime_state->tcxo.last_gate_close_ticks =
      observation->pps_timestamp_ticks;
  runtime_state->tcxo.last_counted_edges = counted_edges;
  runtime_state->tcxo.last_elapsed_us =
      static_cast<uint32_t>(observation_span_us);
  runtime_state->tcxo.last_measured_khz = measured_khz;
  runtime_state->tcxo.last_sampled_elapsed_us =
      static_cast<uint32_t>(observation_span_us);
  runtime_state->tcxo.last_sample_count = 1u;
  runtime_state->tcxo.last_zero_sample_count =
      counted_edges > 0u ? 0u : 1u;
  runtime_state->tcxo.last_valid_sample_count =
      counted_edges > 0u ? 1u : 0u;
  runtime_state->tcxo.last_first_sample_khz = measured_khz;
  runtime_state->tcxo.last_last_sample_khz = measured_khz;
  runtime_state->tcxo.last_min_sample_khz = measured_khz;
  runtime_state->tcxo.last_max_sample_khz = measured_khz;

  pps_gated_ratio.last_reference_validity =
      validity.reference_interval_valid ? "valid" : "invalid";
  pps_gated_ratio.last_reference_reason =
      pps_boundary_reason_name(boundary.reason);
  pps_gated_ratio.last_boundary_validity =
      validity.count_boundary_valid ? "valid" : "invalid";
  pps_gated_ratio.last_boundary_reason =
      validity.count_boundary_valid
          ? "boundary_valid"
          : kWindowReasonBoundaryCaptureUnavailable;
  pps_gated_ratio.last_aperture_validity =
      validity.counter_window_valid ? "valid" : "invalid";
  pps_gated_ratio.last_aperture_reason =
      aperture_reason_name(aperture_flags);
  pps_gated_ratio.last_pair_validity =
      validity.observation_pair_valid ? "valid" : "invalid";
  pps_gated_ratio.last_pair_reason =
      validity.observation_pair_valid
          ? "observation_pair_valid"
          : (sequence_relation == OtisBoundarySequenceRelation::Duplicate
                 ? kWindowReasonBoundarySequenceDuplicate
                 : kWindowReasonBoundarySequenceGap);
  pps_gated_ratio.last_fifo_continuity =
      (aperture_flags & OTIS_PPS_APERTURE_OBSERVATION_OVERFLOW) != 0u
          ? "overflow"
          : sequence_relation_name(sequence_relation);
  bool count_sample_valid =
      counted_edges > 0u &&
      (aperture_flags &
       (OTIS_PPS_APERTURE_COUNTER_SNAPSHOT_INVALID |
        OTIS_PPS_APERTURE_COUNTER_SATURATED |
        OTIS_PPS_APERTURE_COUNTER_WRAP_AMBIGUOUS)) == 0u;
  pps_gated_ratio.last_count_validity =
      count_sample_valid ? "valid" : "invalid";
  pps_gated_ratio.last_count_reason =
      (aperture_flags & OTIS_PPS_APERTURE_COUNTER_SNAPSHOT_INVALID) != 0u
          ? kCountReasonSnapshotInvalid
          : ((aperture_flags & OTIS_PPS_APERTURE_COUNTER_SATURATED) != 0u
                 ? kCountReasonSaturated
                 : (counted_edges == 0u ? kCountReasonZero
                                        : kCountReasonValid));

  WindowAnomaly anomaly = {
      kWindowReasonNone,
      measurement_valid,
      false,
      wire_flags,
  };
  if (!validity.fifo_continuous) {
    anomaly.reason =
        (aperture_flags & OTIS_PPS_APERTURE_OBSERVATION_OVERFLOW) != 0u
            ? kWindowReasonBoundaryObservationOverflow
            : (sequence_relation ==
                       OtisBoundarySequenceRelation::Duplicate
                   ? kWindowReasonBoundarySequenceDuplicate
                   : kWindowReasonBoundarySequenceGap);
  } else if (!validity.observation_pair_valid) {
    anomaly.reason = kWindowReasonObservationPairInvalid;
  } else if (!validity.count_boundary_valid) {
    anomaly.reason = kWindowReasonBoundaryCaptureUnavailable;
  } else if (!validity.counter_window_valid) {
    anomaly.reason = aperture_reason_name(aperture_flags);
  } else if (!validity.reference_interval_valid) {
    anomaly.reason =
        boundary.reason == OtisPpsBoundaryReason::CaptureFlagged
            ? kWindowReasonPpsBoundaryFlagged
            : (boundary.reason ==
                       OtisPpsBoundaryReason::PreviousBoundaryInvalid
                   ? kWindowReasonPpsRecoveryInhibit
                   : kWindowReasonPpsIntervalAnomaly);
  }
  if (!validity.reference_interval_valid) {
    wire_flags |= OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT |
                  OTIS_FLAG_GATE_INCOMPLETE;
    anomaly.flags = wire_flags;
    if (boundary.reason == OtisPpsBoundaryReason::Duplicate ||
        boundary.reason == OtisPpsBoundaryReason::ShortInterval ||
        boundary.reason == OtisPpsBoundaryReason::LongInterval) {
      otis_pps_diagnostics_increment_saturating(
          &pps_gated_ratio.pps_interval_anomaly_count);
    }
  }
  runtime_state->tcxo.last_window_flags = anomaly.flags;
  runtime_state->tcxo.last_window_invalid_reason = anomaly.reason;

  bool prior_control_eligible = runtime_state->tcxo.valid_for_control;
  update_control_gate(runtime_state, config, &anomaly, now_ms);
  record_window_quality(runtime_state, anomaly);
  if (anomaly.valid) {
    otis_pps_diagnostics_increment_saturating(
        &pps_gated_ratio.accepted_window_count);
    pps_gated_ratio.state = runtime_state->tcxo.valid_for_control
                                ? PpsGateState::Open
                                : PpsGateState::Requalifying;
  } else {
    otis_pps_diagnostics_increment_saturating(
        &pps_gated_ratio.rejected_window_count);
    const bool recoverable_reference_anomaly =
        !validity.reference_interval_valid &&
        validity.count_boundary_valid && validity.counter_window_valid &&
        validity.observation_pair_valid && validity.fifo_continuous;
    pps_gated_ratio.state = recoverable_reference_anomaly
                                ? PpsGateState::Suspect
                                : PpsGateState::Fault;
  }
  bool reason_transition =
      strcmp(pps_gated_ratio.last_reason, anomaly.reason) != 0;
  pps_gated_ratio.last_reason = anomaly.reason;

  // A sequence gap has no defensible opening timestamp for the ISR-captured
  // interval count. Preserve the current REF and fault telemetry, but do not
  // fabricate a CNT pair by joining it to an older foreground record.
  bool emit_count =
      sequence_relation == OtisBoundarySequenceRelation::Continuous;
  if (emit_count) {
    // count_seq is the closing PPS boundary sequence for this backend, making
    // dropped boundaries visible without another wire field.
    runtime_state->sequences.count_seq = observation->sequence;
    emit_count_observation(runtime_state, config, counted_edges,
                           runtime_state->tcxo.last_window_flags);
  }

  bool state_transition =
      !pps_gated_ratio.last_window_state_known ||
      pps_gated_ratio.last_window_valid != anomaly.valid ||
      prior_control_eligible != runtime_state->tcxo.valid_for_control;
  pps_gated_ratio.last_window_state_known = true;
  pps_gated_ratio.last_window_valid = anomaly.valid;
  pps_gated_ratio.last_control_eligible =
      runtime_state->tcxo.valid_for_control;
  pps_gated_ratio.previous_boundary_inhibited =
      !raw_boundary.valid || !validity.count_boundary_valid;
  pps_gated_ratio.previous_observation = *observation;
  if (measurement_valid) {
    if (pps_gated_ratio.association_reacquiring) {
      otis_pps_diagnostics_increment_saturating(
          &pps_gated_ratio.association_recovery_count);
    }
    pps_gated_ratio.association_reacquiring = false;
    pps_gated_ratio.association_state = "clean";
    otis_pps_diagnostics_note_measurement_reconstructed(
        &pps_diagnostics, observation->session, observation->sequence,
        otis_monotonic_us32_now());
  } else {
    pps_gated_ratio.association_state = "associated_invalid";
  }
  if (state_transition || reason_transition || !emit_count) {
    emit_pps_gate_window_status(runtime_state, status_context, anomaly,
                                anomaly.valid && counted_edges > 0u);
    if (!anomaly.valid) {
      emit_bad_window_diagnostics(runtime_state, status_context, anomaly);
    }
  }

  return emit_count;
}

void otis_count_observation_note_association_loss(
    OtisRuntimeState *runtime_state,
    OtisStatusEmitContext *status_context,
    uint32_t reference_sequence,
    const char *reason) {
  if (runtime_state == nullptr || status_context == nullptr) {
    return;
  }
  pps_gated_ratio.have_previous_observation = false;
  pps_gated_ratio.previous_boundary_inhibited = true;
  pps_gated_ratio.association_state = "lost";
  pps_gated_ratio.association_reacquiring = true;
  pps_gated_ratio.association_loss_reason =
      reason == nullptr ? "association_loss_unspecified" : reason;
  pps_gated_ratio.association_loss_reference_sequence = reference_sequence;
  otis_pps_diagnostics_increment_saturating(
      &pps_gated_ratio.association_loss_count);
  emit_pps_gate_fault(
      runtime_state, status_context, kWindowReasonAssociationLoss,
      pps_gated_ratio.association_loss_reason, kCountReasonSnapshotAbsent,
      OTIS_FLAG_SOURCE_HEALTH_SUSPECT | OTIS_FLAG_GATE_INCOMPLETE);
}

void otis_count_observation_note_control_consumer(uint32_t session,
                                                  uint32_t sequence) {
  otis_pps_diagnostics_note_control_observed(
      &pps_diagnostics, session, sequence, otis_monotonic_us32_now());
}

bool otis_count_observation_service(OtisRuntimeState *runtime_state,
                                    OtisStatusEmitContext *status_context,
                                    const OtisCountObservationConfig *config) {
  uint32_t now_ms = millis();
  update_startup_inhibit(runtime_state, config, now_ms);
  OtisCaptureIrqReferenceStats reference_stats;
  otis_capture_irq_get_reference_stats(&reference_stats);
  OtisPpsDiagnosticsTransition transition = OtisPpsDiagnosticsTransition::None;
  if (reference_stats.d14_raw_edge_count != 0u) {
    transition = otis_pps_diagnostics_note_physical_pps(
        &pps_diagnostics, reference_stats.d14_raw_edge_count - 1u,
        reference_stats.d14_last_raw_timestamp);
  }
  // Sample "now" only after copying/noting the IRQ mailbox. If a PPS arrives
  // between an earlier now-sample and the mailbox copy, its timestamp is newer
  // than "now" and the modulo interval appears almost one full micros() wrap,
  // manufacturing a false physical-missing transition.
  uint64_t now_ticks = otis_monotonic_us32_now();
  if (transition == OtisPpsDiagnosticsTransition::None) {
    transition = otis_pps_diagnostics_poll(&pps_diagnostics, now_ticks);
  }
  pps_gated_ratio.missing_pps_count =
      pps_diagnostics.physical_pps_missing_count;

  OtisPpsSnapshotBackendStats snapshot_stats;
  otis_pps_snapshot_backend_get_stats(&snapshot_stats);
  if (snapshot_stats.producer_ordinal != 0u) {
    otis_pps_diagnostics_note_snapshot_produced(
        &pps_diagnostics, snapshot_stats.session,
        snapshot_stats.producer_ordinal - 1u, now_ticks);
  }
  otis_pps_diagnostics_note_foreground_backlog(
      &pps_diagnostics, snapshot_stats.backlog_depth,
      snapshot_stats.ring_capacity, now_ticks);

  if (transition == OtisPpsDiagnosticsTransition::PhysicalPpsMissing) {
    uint64_t anchor_ticks = pps_diagnostics.latest_physical_pps.valid
                                ? pps_diagnostics.latest_physical_pps.observed_ticks
                                : pps_diagnostics.monitoring_started_ticks;
    runtime_state->tcxo.last_elapsed_us = static_cast<uint32_t>(
        otis_monotonic_us32_interval(anchor_ticks, now_ticks));
    emit_pps_gate_fault(
        runtime_state, status_context, kWindowReasonMissingPps,
        kReferenceReasonMissingPps, kCountReasonUnavailable,
        OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT |
            OTIS_FLAG_GATE_INCOMPLETE);
  } else if (transition ==
             OtisPpsDiagnosticsTransition::PhysicalPpsRestored) {
    emit_status(status_context, "pps_gate", "physical_pps_restored", "true",
                OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  }
  if (snapshot_stats.fault_latched) {
    pps_gated_ratio.state = PpsGateState::Fault;
    pps_gated_ratio.have_previous_observation = false;
    pps_gated_ratio.previous_boundary_inhibited = true;
  }

  return false;
}

void otis_count_observation_emit_status(
    OtisRuntimeState *runtime_state,
    OtisStatusEmitContext *status_context) {
  emit_pps_gate_status(
      status_context,
      runtime_state->tcxo.last_observation_valid ? OTIS_SEVERITY_INFO
                                                 : OTIS_SEVERITY_WARN,
      runtime_state->tcxo.last_window_flags);
  emit_status(status_context, "pps_gate", "startup_inhibit_active",
              bool_text(runtime_state->tcxo.startup_inhibit_active),
              runtime_state->tcxo.startup_inhibit_active
                  ? OTIS_SEVERITY_WARN
                  : OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
}

void otis_count_observation_emit_runtime_status(
    const OtisRuntimeState *runtime_state,
    OtisStatusEmitContext *status_context,
    const OtisCountObservationConfig *config) {
  if (runtime_state == nullptr || status_context == nullptr ||
      config == nullptr) {
    return;
  }
  const OtisTcxoRuntimeState &count = runtime_state->tcxo;
  emit_status(status_context, "count_path", "observation_valid",
              bool_text(count.last_observation_valid),
              count.last_observation_valid ? OTIS_SEVERITY_INFO
                                           : OTIS_SEVERITY_WARN,
              OTIS_FLAG_NONE);
  emit_status(status_context, "count_path", "measurement_mode",
              otis_count_observation_measurement_mode(), OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "count_path", "gate_period_us",
                  config->gate_period_us, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "count_path", "last_measured_khz",
                  count.last_measured_khz, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32(status_context, "count_path", "last_elapsed_us",
                  count.last_elapsed_us, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status_u32(status_context, "count_path", "last_sampled_elapsed_us",
                  count.last_sampled_elapsed_us, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status_u32(status_context, "count_path", "last_sample_count",
                  count.last_sample_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32(status_context, "count_path", "last_zero_sample_count",
                  count.last_zero_sample_count,
                  count.last_zero_sample_count == 0u ? OTIS_SEVERITY_INFO
                                                      : OTIS_SEVERITY_WARN,
                  count.last_window_flags);
  emit_status_u32(status_context, "count_path", "last_valid_sample_count",
                  count.last_valid_sample_count, OTIS_SEVERITY_INFO,
                  count.last_window_flags);
  emit_status_u32(status_context, "count_path", "last_first_sample_khz",
                  count.last_first_sample_khz, OTIS_SEVERITY_INFO,
                  count.last_window_flags);
  emit_status_u32(status_context, "count_path", "last_last_sample_khz",
                  count.last_last_sample_khz, OTIS_SEVERITY_INFO,
                  count.last_window_flags);
  emit_status_u32(status_context, "count_path", "last_min_sample_khz",
                  count.last_min_sample_khz,
                  count.last_zero_sample_count == 0u ? OTIS_SEVERITY_INFO
                                                      : OTIS_SEVERITY_WARN,
                  count.last_window_flags);
  emit_status_u32(status_context, "count_path", "last_max_sample_khz",
                  count.last_max_sample_khz, OTIS_SEVERITY_INFO,
                  count.last_window_flags);
  emit_status_u32(status_context, "count_path", "last_window_flags",
                  count.last_window_flags,
                  count.last_observation_valid ? OTIS_SEVERITY_INFO
                                               : OTIS_SEVERITY_WARN,
                  count.last_window_flags);
  emit_status(status_context, "count_path", "last_window_invalid_reason",
              otis_count_observation_window_invalid_reason(runtime_state),
              count.last_observation_valid ? OTIS_SEVERITY_INFO
                                           : OTIS_SEVERITY_WARN,
              count.last_window_flags);
  emit_status_u32(status_context, "count_path", "consecutive_bad_windows",
                  count.consecutive_bad_windows,
                  count.consecutive_bad_windows == 0u ? OTIS_SEVERITY_INFO
                                                       : OTIS_SEVERITY_WARN,
                  count.last_window_flags);
  emit_status_u32(status_context, "count_path", "total_bad_windows",
                  count.total_bad_windows,
                  count.total_bad_windows == 0u ? OTIS_SEVERITY_INFO
                                                : OTIS_SEVERITY_WARN,
                  count.last_window_flags);
  emit_status(status_context, "count_path", "startup_inhibit_active",
              bool_text(count.startup_inhibit_active),
              count.startup_inhibit_active ? OTIS_SEVERITY_WARN
                                           : OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "count_path", "startup_inhibit_elapsed_s",
                  count.startup_inhibit_elapsed_s,
                  count.startup_inhibit_active ? OTIS_SEVERITY_WARN
                                               : OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "count_path", "control_eligible",
              bool_text(count.valid_for_control),
              count.valid_for_control ? OTIS_SEVERITY_INFO
                                      : OTIS_SEVERITY_WARN,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "count_path",
                  "control_ready_clean_window_count",
                  count.control_clean_window_count,
                  count.valid_for_control ? OTIS_SEVERITY_INFO
                                          : OTIS_SEVERITY_WARN,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "count_path", "fault_latched",
              bool_text(count.fault_after_startup),
              count.fault_after_startup ? OTIS_SEVERITY_WARN
                                        : OTIS_SEVERITY_INFO,
              count.last_window_flags);
  emit_status_u64(status_context, "count_path", "last_counted_edges",
                  count.last_counted_edges, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u64(status_context, "count_path", "last_gate_open_ticks",
                  count.last_gate_open_ticks, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status_u64(status_context, "count_path", "last_gate_close_ticks",
                  count.last_gate_close_ticks, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
}

void otis_count_observation_emit_configuration_status(
    OtisStatusEmitContext *status_context) {
  OtisPpsSnapshotBackendStats snapshot_stats;
  otis_pps_snapshot_backend_get_stats(&snapshot_stats);
  emit_status(status_context, "capture", "tcxo_counter_backend",
              "pps_gated_ratio", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "capture", "pps_gated_ratio_init",
              pps_gated_ratio.initialized_ok ? "ok" : "failed",
              pps_gated_ratio.initialized_ok ? OTIS_SEVERITY_INFO
                                             : OTIS_SEVERITY_ERROR,
              pps_gated_ratio.initialized_ok
                  ? OTIS_FLAG_CONFIGURATION_ASSUMPTION
                  : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32(status_context, "pps_gate", "min_interval_us",
                  OTIS_PPS_GATE_MIN_INTERVAL_US, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "duplicate_max_interval_us",
                  OTIS_PPS_GATE_DUPLICATE_MAX_INTERVAL_US,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "max_interval_us",
                  OTIS_PPS_GATE_MAX_INTERVAL_US, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "missing_timeout_us",
                  OTIS_PPS_GATE_MISSING_TIMEOUT_US, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "count_resolution_edges", 1u,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "snapshot_ring_capacity",
                  snapshot_stats.ring_capacity, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
}

const char *otis_count_observation_measurement_mode(void) {
  return "pps_gated_ratio";
}

const char *otis_count_observation_window_invalid_reason(
    const OtisRuntimeState *runtime_state) {
  return runtime_state->tcxo.last_window_invalid_reason;
}
