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
#include "otis_config.h"
#include "otis_dual_core_partition.h"
#include "otis_emit.h"
#include "otis_pio_counter_math.h"
#include "otis_pps_count_boundary.h"
#include "otis_pps_diagnostics.h"
#include "otis_pps_gate_math.h"
#include "otis_pps_snapshot_backend.h"
#include "otis_protocol.h"
#include "otis_resource_registry.h"
#include "otis_timebase.h"
#include "otis_reference_acceptance_policy.generated.h"

#include <pico/platform.h>

namespace {

constexpr uint64_t kRp2040MonotonicUs32Modulus =
    OTIS_RP2040_MONOTONIC_US32_MODULUS;
constexpr uint32_t kH1PioCounterInitialX = 0xffffffffu;
const char kWindowReasonNone[] = "none";
const char kWindowReasonCountedEdgesZero[] = "counted_edges_zero";
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
const char kWindowReasonCaptureLoss[] = "capture_loss";
const char kReferenceReasonUnavailable[] = "reference_unavailable";
const char kReferenceReasonValid[] = "reference_valid";
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
  OtisPpsCountBoundaryObservation previous_observation;
  bool have_previous_observation;
  bool previous_boundary_inhibited;
  bool last_window_state_known;
  bool last_window_valid;
  bool last_control_eligible;
  uint32_t accepted_window_count;
  uint32_t rejected_window_count;
  uint32_t pps_interval_anomaly_count;
  uint32_t count_saturated_count;
  uint32_t boundary_sequence_gap_count;
  uint32_t boundary_sequence_duplicate_count;
  uint32_t boundary_overflow_count;
  uint32_t counter_snapshot_invalid_count;
  uint32_t physical_aperture_incomplete_count;
  uint32_t capture_loss_count;
  uint32_t capture_loss_consumer_ordinal;
  bool capture_fault_latched;
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
  const char *capture_state;
  const char *capture_loss_reason;
};

PpsGatedRatioBackend pps_gated_ratio = {};
uint32_t pps_gate_status_snapshot_generation = 0u;

OtisPpsDiagnostics pps_diagnostics = {};
OtisAcceptedReferenceStatus accepted_reference_status = {};

enum class PendingBoundaryStatusKind : uint8_t { None, Opening, Window };
struct PendingBoundaryStatus {
  PendingBoundaryStatusKind kind;
  OtisRuntimeState *runtime_state;
  OtisStatusEmitContext *status_context;
  WindowAnomaly anomaly;
  uint32_t flags;
  bool ratio_available;
};
// Core 1 owns both these pointers and the referenced runtime state. No other
// boundary or reference/count mutation may pass the pending formatter: those
// entry points flush it first. This retains the transition's coherent state
// without copying a large status store or delaying its canonical CNT record.
PendingBoundaryStatus pending_boundary_status = {};

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

const char *capture_service_state_name(OtisPpsCaptureServiceState state) {
  switch (state) {
    case OtisPpsCaptureServiceState::NeverSeen:
      return "never_seen";
    case OtisPpsCaptureServiceState::Present:
      return "present";
    case OtisPpsCaptureServiceState::Stale:
      return "stale";
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
  const auto &accepted = accepted_reference_status;
  emit_status(status_context, "pps_gate", "reference_acceptance_policy_sha256",
              OTIS_REFERENCE_ACCEPTANCE_POLICY_SHA256, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status(status_context, "pps_gate", "reference_acceptance_state",
              accepted.state, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32(status_context, "pps_gate", "reference_acceptance_epoch",
                 accepted.acceptance_epoch, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32(status_context, "pps_gate", "accepted_boundary_ordinal",
                 accepted.accepted_boundary_ordinal, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32(status_context, "pps_gate", "accepted_anchor_snapshot_sequence",
                 accepted.anchor_snapshot_sequence, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32(status_context, "pps_gate", "accepted_anchor_reference_sequence",
                 accepted.anchor_reference_sequence, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32(status_context, "pps_gate", "accepted_anchor_timestamp_ticks",
                 accepted.anchor_timestamp_ticks, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32(status_context, "pps_gate", "reference_acquisition_progress",
                 accepted.acquisition_progress, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32(status_context, "pps_gate", "reference_excluded_candidate_count",
                 accepted.excluded_candidate_count, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32(status_context, "pps_gate", "reference_acceptance_loss_count",
                 accepted.loss_count, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status(status_context, "pps_gate", "reference_acceptance_last_loss_reason",
              accepted.last_loss_reason, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status(status_context, "pps_gate", "accepted_anchor_current",
              bool_text(accepted.anchor_current), OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status(status_context, "pps_gate", "backend", "pps_gated_ratio",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "pps_gate", "boundary_owner", "pio_state_machine",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "pps_gate", "aperture_backend",
              "pio_wait_cumulative_snapshot_fifo_irq_v2", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "pps_gate", "hardware_count_boundary",
              "true", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "pps_gate", "raw_window_valid",
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
  emit_status(status_context, "pps_gate", "raw_window_state",
              pps_gate_state_name(pps_gated_ratio.state), severity, flags);
  emit_status(status_context, "pps_gate", "raw_window_reason",
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
  emit_status(status_context, "pps_gate", "capture_state",
              pps_gated_ratio.capture_state, severity, flags);
  emit_status(status_context, "pps_gate", "capture_loss_reason",
              pps_gated_ratio.capture_loss_reason, severity, flags);
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
  emit_status_u32(status_context, "pps_gate", "accepted_window_count",
                  pps_gated_ratio.accepted_window_count, OTIS_SEVERITY_INFO,
                  flags);
  emit_status_u32(status_context, "pps_gate", "rejected_window_count",
                  pps_gated_ratio.rejected_window_count,
                  pps_gated_ratio.rejected_window_count == 0u
                      ? OTIS_SEVERITY_INFO
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
  emit_status_u32(status_context, "pps_gate", "capture_loss_count",
                  pps_gated_ratio.capture_loss_count,
                  pps_gated_ratio.capture_loss_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate",
                  "capture_loss_consumer_ordinal",
                  pps_gated_ratio.capture_loss_consumer_ordinal,
                  OTIS_SEVERITY_INFO, flags);
  OtisPpsSnapshotBackendStats snapshot_stats;
  otis_pps_snapshot_backend_get_stats(&snapshot_stats);
  emit_status_u32(status_context, "pps_gate", "snapshot_session",
                  snapshot_stats.session, OTIS_SEVERITY_INFO, flags);
  emit_status_u32(status_context, "pps_gate", "snapshot_producer_ordinal",
                  snapshot_stats.producer_ordinal, OTIS_SEVERITY_INFO, flags);
  emit_status_u32(status_context, "pps_gate", "snapshot_consumer_ordinal",
                  snapshot_stats.consumer_ordinal, OTIS_SEVERITY_INFO, flags);
  emit_status_u32(status_context, "pps_gate", "snapshot_backlog_depth",
                  snapshot_stats.backlog_depth,
                  snapshot_stats.backlog_depth == 0u ? OTIS_SEVERITY_INFO
                                                     : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate", "snapshot_backlog_high_water",
                  snapshot_stats.backlog_high_water, OTIS_SEVERITY_INFO,
                  flags);
  emit_status_u32(status_context, "pps_gate", "snapshot_ring_full_count",
                  snapshot_stats.ring_full_count,
                  snapshot_stats.ring_full_count == 0u ? OTIS_SEVERITY_INFO
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
  emit_status_u32(status_context, "pps_gate",
                  "snapshot_irq_budget_exhausted_count",
                  snapshot_stats.irq_budget_exhausted_count,
                  snapshot_stats.irq_budget_exhausted_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_ERROR,
                  flags);
  emit_status_u32(status_context, "pps_gate",
                  "snapshot_timestamp_ambiguous_count",
                  snapshot_stats.timestamp_ambiguous_count,
                  snapshot_stats.timestamp_ambiguous_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate", "snapshot_last_service_ticks",
                  snapshot_stats.last_service_ticks, OTIS_SEVERITY_INFO,
                  flags);
  emit_status(status_context, "pps_gate", "capture_service_state",
              capture_service_state_name(
                  pps_diagnostics.capture_service_state),
              pps_diagnostics.capture_service_state ==
                      OtisPpsCaptureServiceState::Present
                  ? OTIS_SEVERITY_INFO
                  : OTIS_SEVERITY_WARN,
              flags);
  emit_status_u32(status_context, "pps_gate", "capture_service_stale_count",
                  pps_diagnostics.capture_service_stale_count,
                  pps_diagnostics.capture_service_stale_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate", "capture_service_resumed_count",
                  pps_diagnostics.capture_service_resumed_count,
                  OTIS_SEVERITY_INFO, flags);
  emit_status_u32(status_context, "pps_gate", "capture_service_reminder_count",
                  pps_diagnostics.capture_service_reminder_count,
                  OTIS_SEVERITY_INFO, flags);
  emit_status(status_context, "pps_gate", "snapshot", "end",
              OTIS_SEVERITY_INFO, flags);
}

void emit_pps_gate_window_status(OtisRuntimeState *runtime_state,
                                 OtisStatusEmitContext *status_context,
                                 const WindowAnomaly &anomaly,
                                 bool ratio_available) {
  uint32_t flags = runtime_state->tcxo.last_window_flags;
  emit_status(status_context, "pps_gate", "raw_window_valid",
              bool_text(anomaly.valid),
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
  runtime_state->tcxo.valid_for_control =
      !runtime_state->tcxo.startup_inhibit_active &&
      accepted_reference_status.tracking &&
      accepted_reference_status.anchor_current;
  if (!runtime_state->tcxo.startup_inhibit_active) {
    runtime_state->tcxo.fault_after_startup = true;
  }
  runtime_state->tcxo.last_observation_valid = false;
  runtime_state->tcxo.last_window_invalid_reason = reason;
  runtime_state->tcxo.last_window_flags = flags;
  emit_status(status_context, "pps_gate", "raw_window_valid", "false",
              OTIS_SEVERITY_WARN, flags);
  emit_status(status_context, "pps_gate", "ratio_available", "false",
              OTIS_SEVERITY_WARN, flags);
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

void project_common_control_eligibility(
    OtisRuntimeState *runtime_state,
    const OtisCountObservationConfig *config, uint32_t now_ms) {
  update_startup_inhibit(runtime_state, config, now_ms);
  runtime_state->tcxo.valid_for_control =
      !runtime_state->tcxo.startup_inhibit_active &&
      accepted_reference_status.tracking &&
      accepted_reference_status.anchor_current;
  runtime_state->tcxo.control_clean_window_count = 0u;
  pps_gated_ratio.last_control_eligible =
      runtime_state->tcxo.valid_for_control;
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

void otis_count_observation_emit_pending_boundary_status(void) {
  if (pending_boundary_status.kind == PendingBoundaryStatusKind::None) return;
  const PendingBoundaryStatus pending = pending_boundary_status;
  pending_boundary_status = {};
  if (pending.kind == PendingBoundaryStatusKind::Opening) {
    emit_pps_gate_status(pending.status_context, OTIS_SEVERITY_WARN,
                         pending.flags);
  } else if (pending.kind == PendingBoundaryStatusKind::Window) {
    emit_pps_gate_window_status(pending.runtime_state, pending.status_context,
                                pending.anomaly, pending.ratio_available);
    if (!pending.anomaly.valid) {
      emit_bad_window_diagnostics(pending.runtime_state, pending.status_context,
                                  pending.anomaly);
    }
  }
}

void otis_count_observation_update_reference_acceptance(
    const OtisAcceptedReferenceStatus &status) {
  otis_count_observation_emit_pending_boundary_status();
  accepted_reference_status = status;
}

bool otis_count_observation_begin(OtisRuntimeState *runtime_state,
                                  OtisStatusEmitContext *status_context,
                                  const OtisCountObservationConfig *config) {
  otis_count_observation_emit_pending_boundary_status();
  (void)runtime_state;
  bool counter_ok = otis_pps_snapshot_backend_begin();
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
  pps_gated_ratio.previous_observation = {};
  pps_gated_ratio.have_previous_observation = false;
  pps_gated_ratio.previous_boundary_inhibited = false;
  pps_gated_ratio.last_window_state_known = false;
  pps_gated_ratio.last_window_valid = false;
  pps_gated_ratio.last_control_eligible = false;
  pps_gated_ratio.accepted_window_count = 0;
  pps_gated_ratio.rejected_window_count = 0;
  pps_gated_ratio.pps_interval_anomaly_count = 0;
  pps_gated_ratio.count_saturated_count = 0;
  pps_gated_ratio.boundary_sequence_gap_count = 0;
  pps_gated_ratio.boundary_sequence_duplicate_count = 0;
  pps_gated_ratio.boundary_overflow_count = 0;
  pps_gated_ratio.counter_snapshot_invalid_count = 0;
  pps_gated_ratio.physical_aperture_incomplete_count = 0;
  pps_gated_ratio.capture_loss_count = 0;
  pps_gated_ratio.capture_loss_consumer_ordinal = 0u;
  pps_gated_ratio.capture_fault_latched = !counter_ok;
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
  pps_gated_ratio.capture_state = counter_ok ? "clean" : "lost";
  pps_gated_ratio.capture_loss_reason =
      counter_ok ? "none" : "counter_init_failed";
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
  emit_status(status_context, "pps_gate", "boundary_owner", "pio_state_machine",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "pps_gate", "aperture_backend",
              "pio_wait_cumulative_snapshot_fifo_irq_v2", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(status_context, "pps_gate", "hardware_count_boundary",
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
  otis_count_observation_emit_pending_boundary_status();
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
    otis_pps_diagnostics_increment_saturating(
        &pps_gated_ratio.physical_aperture_incomplete_count);
    pending_boundary_status = {
        PendingBoundaryStatusKind::Opening, runtime_state, status_context, {},
        observation->capture_flags | OTIS_FLAG_GATE_INCOMPLETE, false};
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

  const bool prior_control_eligible = runtime_state->tcxo.valid_for_control;
  anomaly.post_startup_invalid =
      !anomaly.valid && !runtime_state->tcxo.startup_inhibit_active;
  project_common_control_eligibility(runtime_state, config, now_ms);
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
    otis_pps_diagnostics_note_measurement_reconstructed(
        &pps_diagnostics, observation->session, observation->sequence,
        otis_monotonic_us32_now());
  }
  if (state_transition || reason_transition || !emit_count) {
    pending_boundary_status = {
        PendingBoundaryStatusKind::Window, runtime_state, status_context,
        anomaly, 0u, anomaly.valid && counted_edges > 0u};
  }

  return emit_count;
}

void otis_count_observation_note_capture_loss(
    OtisRuntimeState *runtime_state,
    OtisStatusEmitContext *status_context,
    uint32_t consumer_ordinal,
    const char *reason) {
  otis_count_observation_emit_pending_boundary_status();
  if (runtime_state == nullptr || status_context == nullptr) {
    return;
  }
  pps_gated_ratio.have_previous_observation = false;
  pps_gated_ratio.previous_boundary_inhibited = true;
  pps_gated_ratio.capture_state = "lost";
  pps_gated_ratio.capture_loss_reason =
      reason == nullptr ? "capture_loss_unspecified" : reason;
  pps_gated_ratio.capture_loss_consumer_ordinal = consumer_ordinal;
  if (!pps_gated_ratio.capture_fault_latched) {
    pps_gated_ratio.capture_fault_latched = true;
    otis_pps_diagnostics_increment_saturating(
        &pps_gated_ratio.capture_loss_count);
  }
  emit_pps_gate_fault(
      runtime_state, status_context, kWindowReasonCaptureLoss,
      pps_gated_ratio.capture_loss_reason, kCountReasonSnapshotAbsent,
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
  otis_count_observation_emit_pending_boundary_status();
  uint32_t now_ms = millis();
  project_common_control_eligibility(runtime_state, config, now_ms);
  OtisPpsSnapshotBackendStats snapshot_stats;
  otis_pps_snapshot_backend_get_stats(&snapshot_stats);
  OtisPpsDiagnosticsTransition transition = OtisPpsDiagnosticsTransition::None;
  if (snapshot_stats.producer_ordinal != 0u) {
    transition = otis_pps_diagnostics_note_capture_service(
        &pps_diagnostics, snapshot_stats.producer_ordinal - 1u,
        snapshot_stats.last_service_ticks);
    otis_pps_diagnostics_note_snapshot_produced(
        &pps_diagnostics, snapshot_stats.session,
        snapshot_stats.producer_ordinal - 1u,
        snapshot_stats.last_service_ticks);
  }
  // The backend mailbox and its service coordinate are copied before now.
  // This watchdog reports stale FIFO service only; it does not claim that the
  // electrical D14 input was absent or reconstruct a physical edge timestamp.
  const uint64_t now_ticks = otis_monotonic_us32_now();
  if (transition == OtisPpsDiagnosticsTransition::None)
    transition = otis_pps_diagnostics_poll(&pps_diagnostics, now_ticks);
  otis_pps_diagnostics_note_foreground_backlog(
      &pps_diagnostics, snapshot_stats.backlog_depth,
      snapshot_stats.ring_capacity, now_ticks);

  if (transition == OtisPpsDiagnosticsTransition::CaptureServiceStale) {
    uint64_t anchor_ticks = pps_diagnostics.latest_capture_service.valid
                                ? pps_diagnostics.latest_capture_service.observed_ticks
                                : pps_diagnostics.monitoring_started_ticks;
    runtime_state->tcxo.last_elapsed_us = static_cast<uint32_t>(
        otis_monotonic_us32_interval(anchor_ticks, now_ticks));
    emit_status(status_context, "pps_gate", "capture_service_stale", "true",
                OTIS_SEVERITY_WARN,
                OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT);
  } else if (transition ==
             OtisPpsDiagnosticsTransition::CaptureServiceResumed) {
    emit_status(status_context, "pps_gate", "capture_service_resumed", "true",
                OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  }
  if (snapshot_stats.fault_latched) {
    pps_gated_ratio.state = PpsGateState::Fault;
    pps_gated_ratio.have_previous_observation = false;
    pps_gated_ratio.previous_boundary_inhibited = true;
    pps_gated_ratio.capture_state = "lost";
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
