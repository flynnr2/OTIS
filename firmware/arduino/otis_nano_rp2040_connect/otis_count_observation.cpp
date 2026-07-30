#include "otis_count_observation.h"

#include <Arduino.h>
#include <hardware/clocks.h>
#include <hardware/gpio.h>
#include <hardware/pio.h>
#include <hardware/pio_instructions.h>
#include <stdint.h>
#include <string.h>

#include "otis_board.h"
#include "otis_capture_irq.h"
#include "otis_config.h"
#include "otis_emit.h"
#include "otis_pio_counter_math.h"
#include "otis_pps_count_boundary.h"
#include "otis_pps_count_boundary_ring.h"
#include "otis_pps_gate_math.h"
#include "otis_protocol.h"
#include "otis_resource_registry.h"
#include "otis_timebase.h"

namespace {

constexpr uint64_t kRp2040Timer0MicrosWrapTicks = (1ull << 32) * 16ull;
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

enum class PpsGateState : uint8_t {
  Idle,
  Armed,
  Open,
  Fault,
};

struct WindowAnomaly {
  const char *reason;
  bool valid;
  bool post_startup_invalid;
  uint32_t flags;
};

#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE || \
    OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
struct H1PioLongGateCounter {
  PIO pio;
  uint sm;
  uint offset;
  bool initialized;
  volatile bool active;
  uint64_t gate_open_ticks;
  uint32_t saturation_count;
};

H1PioLongGateCounter h1_pio_long_gate = {
    pio0, 0, 0, false, false, 0, 0,
};

bool begin_h1_pio_long_gate_counter(void) {
  uint16_t instructions[] = {
      (uint16_t)pio_encode_pull(false, true),
      (uint16_t)pio_encode_mov(pio_x, pio_osr),
      (uint16_t)pio_encode_wait_pin(true, 0),
      (uint16_t)pio_encode_wait_pin(false, 0),
      (uint16_t)pio_encode_jmp_x_dec(2),
  };
  pio_program program = {
      instructions,
      5,
      -1,
  };

  if (h1_pio_long_gate.initialized) {
    return false;
  }

  h1_pio_long_gate.pio = pio0;
  if (!pio_can_add_program(h1_pio_long_gate.pio, &program)) {
    return false;
  }
  int claimed_sm = pio_claim_unused_sm(h1_pio_long_gate.pio, false);
  if (claimed_sm < 0) {
    return false;
  }
  h1_pio_long_gate.sm = static_cast<uint>(claimed_sm);
  h1_pio_long_gate.offset = pio_add_program(h1_pio_long_gate.pio, &program);
  bool ownership_bound =
      otis_resource_registry_bind_pio_state_machine(
          OTIS_OWNER_COUNT_OBSERVATION, 0u,
          static_cast<uint8_t>(h1_pio_long_gate.sm)) &&
      otis_resource_registry_bind_pio_program(
          OTIS_OWNER_COUNT_OBSERVATION, 0u,
          static_cast<uint8_t>(h1_pio_long_gate.offset),
          static_cast<uint8_t>(program.length));
  if (!ownership_bound) {
    return false;
  }

  pio_gpio_init(h1_pio_long_gate.pio, OTIS_GPIO_OSC_OBSERVATION);
  gpio_pull_down(OTIS_GPIO_OSC_OBSERVATION);

  pio_sm_config config = pio_get_default_sm_config();
  sm_config_set_in_pins(&config, OTIS_GPIO_OSC_OBSERVATION);
  sm_config_set_wrap(&config, h1_pio_long_gate.offset + 2,
                     h1_pio_long_gate.offset + 4);
  sm_config_set_clkdiv(&config, 1.0f);
  pio_sm_init(h1_pio_long_gate.pio, h1_pio_long_gate.sm,
              h1_pio_long_gate.offset, &config);
  pio_sm_set_enabled(h1_pio_long_gate.pio, h1_pio_long_gate.sm, false);
  h1_pio_long_gate.initialized = true;
  h1_pio_long_gate.active = false;
  h1_pio_long_gate.gate_open_ticks = 0;
  h1_pio_long_gate.saturation_count = 0;
  return true;
}

#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE
void start_h1_pio_long_gate_counter(uint64_t gate_open_ticks) {
  if (!h1_pio_long_gate.initialized) {
    return;
  }
  pio_sm_set_enabled(h1_pio_long_gate.pio, h1_pio_long_gate.sm, false);
  pio_sm_clear_fifos(h1_pio_long_gate.pio, h1_pio_long_gate.sm);
  pio_sm_restart(h1_pio_long_gate.pio, h1_pio_long_gate.sm);
  pio_sm_clkdiv_restart(h1_pio_long_gate.pio, h1_pio_long_gate.sm);
  pio_sm_put_blocking(h1_pio_long_gate.pio, h1_pio_long_gate.sm,
                      kH1PioCounterInitialX);
  pio_sm_exec_wait_blocking(h1_pio_long_gate.pio, h1_pio_long_gate.sm,
                            pio_encode_jmp(h1_pio_long_gate.offset));
  h1_pio_long_gate.gate_open_ticks = gate_open_ticks;
  h1_pio_long_gate.active = true;
  pio_sm_set_enabled(h1_pio_long_gate.pio, h1_pio_long_gate.sm, true);
}

uint32_t stop_h1_pio_long_gate_counter(void) {
  pio_sm_set_enabled(h1_pio_long_gate.pio, h1_pio_long_gate.sm, false);
  pio_sm_clear_fifos(h1_pio_long_gate.pio, h1_pio_long_gate.sm);
  pio_sm_exec_wait_blocking(h1_pio_long_gate.pio, h1_pio_long_gate.sm,
                            pio_encode_mov(pio_isr, pio_x));
  pio_sm_exec_wait_blocking(h1_pio_long_gate.pio, h1_pio_long_gate.sm,
                            pio_encode_push(false, false));
  uint32_t remaining = pio_sm_get_blocking(h1_pio_long_gate.pio,
                                           h1_pio_long_gate.sm);
  h1_pio_long_gate.active = false;
  return remaining;
}
#endif

#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
bool start_h1_pio_counter_from_pps_isr(uint64_t gate_open_ticks) {
  if (!h1_pio_long_gate.initialized) {
    return false;
  }
  pio_sm_set_enabled(h1_pio_long_gate.pio, h1_pio_long_gate.sm, false);
  pio_sm_clear_fifos(h1_pio_long_gate.pio, h1_pio_long_gate.sm);
  pio_sm_restart(h1_pio_long_gate.pio, h1_pio_long_gate.sm);
  pio_sm_clkdiv_restart(h1_pio_long_gate.pio, h1_pio_long_gate.sm);
  if (pio_sm_is_tx_fifo_full(h1_pio_long_gate.pio,
                             h1_pio_long_gate.sm)) {
    h1_pio_long_gate.active = false;
    return false;
  }
  pio_sm_put(h1_pio_long_gate.pio, h1_pio_long_gate.sm,
             kH1PioCounterInitialX);
  pio_sm_exec(h1_pio_long_gate.pio, h1_pio_long_gate.sm,
              pio_encode_jmp(h1_pio_long_gate.offset));
  if (pio_sm_is_exec_stalled(h1_pio_long_gate.pio,
                             h1_pio_long_gate.sm)) {
    h1_pio_long_gate.active = false;
    return false;
  }
  h1_pio_long_gate.gate_open_ticks = gate_open_ticks;
  h1_pio_long_gate.active = true;
  pio_sm_set_enabled(h1_pio_long_gate.pio, h1_pio_long_gate.sm, true);
  return true;
}

bool stop_and_sample_h1_pio_counter_from_pps_isr(uint32_t *remaining) {
  if (!h1_pio_long_gate.initialized || !h1_pio_long_gate.active ||
      remaining == nullptr) {
    return false;
  }
  pio_sm_set_enabled(h1_pio_long_gate.pio, h1_pio_long_gate.sm, false);
  pio_sm_clear_fifos(h1_pio_long_gate.pio, h1_pio_long_gate.sm);
  pio_sm_exec(h1_pio_long_gate.pio, h1_pio_long_gate.sm,
              pio_encode_mov(pio_isr, pio_x));
  if (pio_sm_is_exec_stalled(h1_pio_long_gate.pio,
                             h1_pio_long_gate.sm)) {
    h1_pio_long_gate.active = false;
    return false;
  }
  pio_sm_exec(h1_pio_long_gate.pio, h1_pio_long_gate.sm,
              pio_encode_push(false, false));
  if (pio_sm_is_exec_stalled(h1_pio_long_gate.pio,
                             h1_pio_long_gate.sm) ||
      pio_sm_is_rx_fifo_empty(h1_pio_long_gate.pio,
                              h1_pio_long_gate.sm)) {
    h1_pio_long_gate.active = false;
    return false;
  }
  *remaining = pio_sm_get(h1_pio_long_gate.pio, h1_pio_long_gate.sm);
  h1_pio_long_gate.active = false;
  return true;
}
#endif
#endif

#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
struct PpsGatedRatioBackend {
  PpsGateState state;
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
};

PpsGatedRatioBackend pps_gated_ratio = {};

volatile uint32_t pps_boundary_next_sequence = 0u;
volatile uint64_t pps_boundary_last_isr_ticks = 0u;
volatile bool pps_boundary_seen = false;

void capture_pps_count_boundary_from_isr(uint64_t timestamp_ticks,
                                         uint32_t capture_flags) {
  OtisPpsCountBoundaryObservation observation = {
      pps_boundary_next_sequence++,
      timestamp_ticks,
      0u,
      capture_flags,
      OTIS_PPS_APERTURE_NONE,
  };

  if (!h1_pio_long_gate.active) {
    observation.aperture_flags |=
        OTIS_PPS_APERTURE_PREVIOUS_BOUNDARY_UNAVAILABLE |
        OTIS_PPS_APERTURE_PHYSICAL_APERTURE_INCOMPLETE;
  } else {
    uint32_t remaining = 0u;
    if (stop_and_sample_h1_pio_counter_from_pps_isr(&remaining)) {
      OtisPioCounterSample sample =
          otis_pio_counter_sample(kH1PioCounterInitialX, remaining);
      observation.interval_count =
          static_cast<uint32_t>(sample.counted_edges);
      if (sample.saturated) {
        observation.aperture_flags |= OTIS_PPS_APERTURE_COUNTER_SATURATED;
      } else if (sample.counted_edges == 0u) {
        observation.aperture_flags |= OTIS_PPS_APERTURE_ZERO_COUNT;
      }
    } else {
      observation.aperture_flags |=
          OTIS_PPS_APERTURE_COUNTER_SNAPSHOT_INVALID |
          OTIS_PPS_APERTURE_PHYSICAL_APERTURE_INCOMPLETE;
    }
  }

  if (!start_h1_pio_counter_from_pps_isr(timestamp_ticks)) {
    observation.aperture_flags |=
        OTIS_PPS_APERTURE_BOUNDARY_CAPTURE_UNAVAILABLE |
        OTIS_PPS_APERTURE_PHYSICAL_APERTURE_INCOMPLETE;
  }

  // Publish only after the timestamp and physical counter boundary are both
  // complete. Overflow is latched into the next deliverable observation.
  otis_pps_count_boundary_ring_push_from_isr(observation);
  pps_boundary_last_isr_ticks = timestamp_ticks;
  pps_boundary_seen = true;
}
#endif

void emit_status(OtisStatusEmitContext *context, const char *component,
                 const char *key, const char *value, const char *severity,
                 uint32_t flags) {
  otis_status_emit(context, component, key, value, severity, flags);
}

void emit_status_u32(OtisStatusEmitContext *context, const char *component,
                     const char *key, uint32_t value, const char *severity,
                     uint32_t flags) {
  otis_status_emit_u32(context, component, key, value, severity, flags);
}

const char *bool_text(bool value) { return value ? "true" : "false"; }

#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
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
    case PpsGateState::Fault:
      return "fault";
  }
  return "unknown";
}

void emit_pps_gate_status(OtisStatusEmitContext *status_context,
                          const char *severity, uint32_t flags) {
  emit_status(status_context, "pps_gate", "backend", "pps_gated_ratio",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(status_context, "pps_gate", "boundary_owner", "pps_gpio_irq",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(status_context, "pps_gate", "aperture_backend",
              "pps_isr_stop_sample_restart_v1", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(status_context, "pps_gate", "backend_qualified",
              bool_text(OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED != 0),
              OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED ? OTIS_SEVERITY_INFO
                                                  : OTIS_SEVERITY_WARN,
              OTIS_FLAG_PROFILE_ASSUMPTION);
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
  if (pps_gated_ratio.have_previous_observation) {
    emit_status_u32(status_context, "pps_gate", "boundary_sequence",
                    pps_gated_ratio.previous_observation.sequence,
                    OTIS_SEVERITY_INFO, flags);
  }
  emit_status_u32(status_context, "pps_gate", "boundary_ring_depth",
                  otis_pps_count_boundary_ring_depth(), OTIS_SEVERITY_INFO,
                  flags);
  emit_status_u32(status_context, "pps_gate", "boundary_ring_capacity",
                  otis_pps_count_boundary_ring_capacity(), OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
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
              OTIS_FLAG_PROFILE_ASSUMPTION);
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
  pps_gated_ratio.state = PpsGateState::Fault;
  pps_gated_ratio.rejected_window_count += 1u;
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
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(status_context, "pps_gate", "control_eligible", "false",
              OTIS_SEVERITY_WARN, flags);
  emit_pps_gate_status(status_context, OTIS_SEVERITY_WARN, flags);
}

#endif

void reset_fc0_accum_window(OtisRuntimeState *runtime_state) {
  runtime_state->tcxo.fc0_accum_active = false;
  runtime_state->tcxo.fc0_accum_gate_open_ticks = 0;
  runtime_state->tcxo.fc0_accum_weighted_khz_us = 0;
  runtime_state->tcxo.fc0_accum_elapsed_us = 0;
  runtime_state->tcxo.fc0_accum_sample_count = 0;
  runtime_state->tcxo.fc0_accum_zero_sample_count = 0;
  runtime_state->tcxo.fc0_accum_first_sample_khz = 0;
  runtime_state->tcxo.fc0_accum_last_sample_khz = 0;
  runtime_state->tcxo.fc0_accum_min_sample_khz = 0;
  runtime_state->tcxo.fc0_accum_max_sample_khz = 0;
  runtime_state->tcxo.fc0_accum_flags = OTIS_FLAG_NONE;
}

void start_fc0_accum_window(OtisRuntimeState *runtime_state,
                            uint64_t gate_open_ticks) {
  reset_fc0_accum_window(runtime_state);
  runtime_state->tcxo.fc0_accum_gate_open_ticks = gate_open_ticks;
  runtime_state->tcxo.fc0_accum_flags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;
  runtime_state->tcxo.fc0_accum_active = true;
}

void record_fc0_sample(OtisRuntimeState *runtime_state, uint32_t measured_khz,
                       uint64_t elapsed_us) {
  runtime_state->tcxo.fc0_accum_weighted_khz_us +=
      (uint64_t)measured_khz * elapsed_us;
  runtime_state->tcxo.fc0_accum_elapsed_us += elapsed_us;
  runtime_state->tcxo.fc0_accum_sample_count += 1u;
  if (runtime_state->tcxo.fc0_accum_sample_count == 1u) {
    runtime_state->tcxo.fc0_accum_first_sample_khz = measured_khz;
    runtime_state->tcxo.fc0_accum_min_sample_khz = measured_khz;
    runtime_state->tcxo.fc0_accum_max_sample_khz = measured_khz;
  } else {
    if (measured_khz < runtime_state->tcxo.fc0_accum_min_sample_khz) {
      runtime_state->tcxo.fc0_accum_min_sample_khz = measured_khz;
    }
    if (measured_khz > runtime_state->tcxo.fc0_accum_max_sample_khz) {
      runtime_state->tcxo.fc0_accum_max_sample_khz = measured_khz;
    }
  }
  runtime_state->tcxo.fc0_accum_last_sample_khz = measured_khz;
  if (measured_khz == 0u) {
    runtime_state->tcxo.fc0_accum_zero_sample_count += 1u;
  }
}

void emit_bad_window_diagnostics(OtisRuntimeState *runtime_state,
                                 OtisStatusEmitContext *status_context,
                                 const WindowAnomaly &anomaly) {
  uint32_t flags = runtime_state->tcxo.last_window_flags;
  emit_status(status_context, "fc0", "window_invalid_reason",
              runtime_state->tcxo.last_window_invalid_reason, OTIS_SEVERITY_WARN,
              flags);
  emit_status_u32(status_context, "fc0", "window_sample_count",
                  runtime_state->tcxo.last_sample_count, OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "fc0", "window_zero_sample_count",
                  runtime_state->tcxo.last_zero_sample_count, OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "fc0", "window_valid_sample_count",
                  runtime_state->tcxo.last_valid_sample_count,
                  OTIS_SEVERITY_WARN, flags);
  emit_status_u32(status_context, "fc0", "window_first_sample_khz",
                  runtime_state->tcxo.last_first_sample_khz,
                  OTIS_SEVERITY_WARN, flags);
  emit_status_u32(status_context, "fc0", "window_last_sample_khz",
                  runtime_state->tcxo.last_last_sample_khz, OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "fc0", "window_min_sample_khz",
                  runtime_state->tcxo.last_min_sample_khz, OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "fc0", "window_max_sample_khz",
                  runtime_state->tcxo.last_max_sample_khz, OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "fc0", "window_elapsed_us",
                  runtime_state->tcxo.last_elapsed_us, OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "fc0", "window_flags",
                  runtime_state->tcxo.last_window_flags, OTIS_SEVERITY_WARN,
                  flags);
  emit_status(status_context, "fc0", "post_startup_invalid_window",
              anomaly.post_startup_invalid ? "true" : "false",
              anomaly.post_startup_invalid ? OTIS_SEVERITY_WARN
                                           : OTIS_SEVERITY_INFO,
              flags);
  emit_status_u32(status_context, "fc0", "consecutive_bad_windows",
                  runtime_state->tcxo.consecutive_bad_windows,
                  OTIS_SEVERITY_WARN, flags);
  emit_status_u32(status_context, "fc0", "total_bad_windows",
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
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
  runtime_state->tcxo.valid_for_control =
      runtime_state->tcxo.valid_for_control &&
      OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED;
#endif
  if (runtime_state->tcxo.valid_for_control) {
    runtime_state->tcxo.fault_after_startup = false;
  }
}

void emit_count_observation(OtisRuntimeState *runtime_state,
                            const OtisCountObservationConfig *config,
                            uint64_t counted_edges, uint32_t flags) {
  otis_emit_count_observation(
      runtime_state->sequences.count_seq++, OTIS_CHANNEL_OSC_OBSERVATION,
      runtime_state->tcxo.last_gate_open_ticks,
      runtime_state->tcxo.last_gate_close_ticks, OTIS_DOMAIN_RP2040_TIMER0,
      counted_edges, OTIS_EDGE_RISING, config->source_domain, flags);
}

}  // namespace

void otis_count_observation_begin(OtisRuntimeState *runtime_state,
                                  OtisStatusEmitContext *status_context,
                                  const OtisCountObservationConfig *config) {
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0
  (void)runtime_state;
  (void)config;
  gpio_set_function(OTIS_GPIO_OSC_OBSERVATION, GPIO_FUNC_GPCK);
  emit_status(status_context, "capture", "tcxo_counter_backend",
              "rp2040_fc0_gpin0", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE
  (void)runtime_state;
  bool counter_ok = begin_h1_pio_long_gate_counter();
  emit_status(status_context, "capture", "tcxo_counter_backend",
              "pio_long_gate_gpio20", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(status_context, "capture", "pio_long_gate_init",
              counter_ok ? "ok" : "failed",
              counter_ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              counter_ok ? OTIS_FLAG_PROFILE_ASSUMPTION
                         : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32(status_context, "capture", "pio_long_gate_gpio",
                  OTIS_GPIO_OSC_OBSERVATION, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(status_context, "capture", "pio_long_gate_period_us",
                  config->gate_period_us, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  if (counter_ok) {
    emit_status_u32(status_context, "capture", "pio_long_gate_pio", 0u,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32(status_context, "capture", "pio_long_gate_sm",
                    h1_pio_long_gate.sm, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
  }
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
  (void)runtime_state;
  bool counter_ok = begin_h1_pio_long_gate_counter();
  // D14's GPIO IRQ remains the single PPS authority. It invokes the bounded
  // handler below before foreground or serial service can run.
  otis_pps_count_boundary_ring_reset();
  pps_boundary_next_sequence = 0u;
  pps_boundary_last_isr_ticks = 0u;
  pps_boundary_seen = false;
  // Even an unavailable counter publishes an atomic boundary observation with
  // explicit failure flags; it must not fall back to an unpaired REF stream.
  otis_capture_irq_set_pps_count_boundary_handler(
      capture_pps_count_boundary_from_isr);
  pps_gated_ratio.state = counter_ok ? PpsGateState::Armed
                                     : PpsGateState::Fault;
  pps_gated_ratio.waiting_since_ticks = otis_capture_ticks_now();
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
  emit_status(status_context, "capture", "tcxo_counter_backend",
              "pps_gated_ratio", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(status_context, "capture", "pps_gated_ratio_init",
              counter_ok ? "ok" : "failed",
              counter_ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              counter_ok ? OTIS_FLAG_PROFILE_ASSUMPTION
                         : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32(status_context, "pps_gate", "pps_gpio",
                  OTIS_PIN_PPS_REFERENCE, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "osc_gpio",
                  OTIS_GPIO_OSC_OBSERVATION, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "min_interval_us",
                  OTIS_PPS_GATE_MIN_INTERVAL_US, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "duplicate_max_interval_us",
                  OTIS_PPS_GATE_DUPLICATE_MAX_INTERVAL_US,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "max_interval_us",
                  OTIS_PPS_GATE_MAX_INTERVAL_US, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "missing_timeout_us",
                  OTIS_PPS_GATE_MISSING_TIMEOUT_US, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "count_resolution_edges", 1u,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "boundary_ring_capacity",
                  otis_pps_count_boundary_ring_capacity(), OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(status_context, "pps_gate", "boundary_owner", "pps_gpio_irq",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(status_context, "pps_gate", "aperture_backend",
              "pps_isr_stop_sample_restart_v1", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(status_context, "pps_gate", "backend_qualified",
              bool_text(OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED != 0),
              OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED ? OTIS_SEVERITY_INFO
                                                  : OTIS_SEVERITY_WARN,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(status_context, "pps_gate",
              "counter_aperture_uncertainty_ns", "unavailable",
              OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(status_context, "pps_gate",
              "reference_frequency_uncertainty_ppb", "unavailable",
              OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
  if (counter_ok) {
    emit_status_u32(status_context, "pps_gate", "counter_pio", 0u,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32(status_context, "pps_gate", "counter_sm",
                    h1_pio_long_gate.sm, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
  }
  emit_pps_gate_status(status_context,
                       counter_ok ? OTIS_SEVERITY_INFO
                                  : OTIS_SEVERITY_ERROR,
                       counter_ok ? OTIS_FLAG_PROFILE_ASSUMPTION
                                  : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ
  pinMode(OTIS_PIN_OSC_OBSERVATION, INPUT_PULLDOWN);
  runtime_state->tcxo.gate_open_us = micros();
  emit_status(status_context, "capture", "tcxo_counter_backend",
              "gpio_irq_divided_only", OTIS_SEVERITY_WARN,
              OTIS_FLAG_RATE_TOO_HIGH);
  otis_capture_irq_begin_tcxo_counter(OTIS_PIN_OSC_OBSERVATION);
#endif
}

bool otis_count_observation_on_pps_boundary(
    OtisRuntimeState *runtime_state,
    OtisStatusEmitContext *status_context,
    const OtisCountObservationConfig *config,
    const OtisPpsCountBoundaryObservation *observation) {
#if (OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
     OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE) && \
    OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
  if (observation == nullptr) {
    return false;
  }

  uint32_t now_ms = millis();
  update_startup_inhibit(runtime_state, config, now_ms);
  pps_gated_ratio.missing_before_first_reported = false;
  pps_gated_ratio.missing_after_sequence_reported = false;

  if (!pps_gated_ratio.have_previous_observation) {
    bool boundary_valid =
        (observation->aperture_flags &
         OTIS_PPS_APERTURE_BOUNDARY_CAPTURE_UNAVAILABLE) == 0u;
    pps_gated_ratio.previous_observation = *observation;
    pps_gated_ratio.have_previous_observation = true;
    pps_gated_ratio.previous_boundary_inhibited = !boundary_valid;
    pps_gated_ratio.state =
        boundary_valid ? PpsGateState::Open : PpsGateState::Fault;
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
    pps_gated_ratio.physical_aperture_incomplete_count += 1u;
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
  uint32_t aperture_flags = observation->aperture_flags;
  uint32_t wire_flags =
      previous.capture_flags | observation->capture_flags;
  if ((aperture_flags & OTIS_PPS_APERTURE_OBSERVATION_OVERFLOW) != 0u) {
    pps_gated_ratio.boundary_overflow_count += 1u;
    wire_flags |= OTIS_FLAG_CAPTURE_RING_OVERRUN |
                  OTIS_FLAG_GATE_INCOMPLETE;
  }
  if (sequence_relation == OtisBoundarySequenceRelation::Gap) {
    pps_gated_ratio.boundary_sequence_gap_count += 1u;
    wire_flags |= OTIS_FLAG_EDGE_ORDER_SUSPECT |
                  OTIS_FLAG_CAPTURE_RING_OVERRUN |
                  OTIS_FLAG_GATE_INCOMPLETE;
  } else if (sequence_relation ==
             OtisBoundarySequenceRelation::Duplicate) {
    pps_gated_ratio.boundary_sequence_duplicate_count += 1u;
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
    pps_gated_ratio.counter_snapshot_invalid_count += 1u;
    wire_flags |= OTIS_FLAG_SOURCE_HEALTH_SUSPECT |
                  OTIS_FLAG_GATE_INCOMPLETE;
  }
  if ((aperture_flags &
       OTIS_PPS_APERTURE_PHYSICAL_APERTURE_INCOMPLETE) != 0u) {
    pps_gated_ratio.physical_aperture_incomplete_count += 1u;
    wire_flags |= OTIS_FLAG_GATE_INCOMPLETE;
  }
  if ((aperture_flags & OTIS_PPS_APERTURE_COUNTER_SATURATED) != 0u) {
    pps_gated_ratio.count_saturated_count += 1u;
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
      (uint64_t)OTIS_PPS_GATE_DUPLICATE_MAX_INTERVAL_US *
          OTIS_RP2040_TIMER0_TICKS_PER_US,
      (uint64_t)OTIS_PPS_GATE_MIN_INTERVAL_US *
          OTIS_RP2040_TIMER0_TICKS_PER_US,
      (uint64_t)OTIS_PPS_GATE_MAX_INTERVAL_US *
          OTIS_RP2040_TIMER0_TICKS_PER_US);
  OtisPpsBoundaryAssessment boundary = raw_boundary;
  if (pps_gated_ratio.previous_boundary_inhibited && raw_boundary.valid) {
    boundary.valid = false;
    boundary.reason = OtisPpsBoundaryReason::PreviousBoundaryInvalid;
  }

  OtisPpsCountWindowValidity validity = otis_pps_count_window_validity(
      true, boundary.valid, sequence_relation, aperture_flags,
      OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED != 0, true);
  bool measurement_valid =
      validity.reference_interval_valid &&
      validity.count_boundary_valid &&
      validity.counter_window_valid &&
      validity.observation_pair_valid &&
      validity.fifo_continuous;

  uint64_t observation_span_us =
      otis_timer0_interval_ticks(previous.pps_timestamp_ticks,
                                observation->pps_timestamp_ticks) /
      OTIS_RP2040_TIMER0_TICKS_PER_US;
  uint64_t counted_edges = observation->interval_count;
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
      pps_gated_ratio.pps_interval_anomaly_count += 1u;
    }
  }
  runtime_state->tcxo.last_window_flags = anomaly.flags;
  runtime_state->tcxo.last_window_invalid_reason = anomaly.reason;

  bool prior_control_eligible = runtime_state->tcxo.valid_for_control;
  update_control_gate(runtime_state, config, &anomaly, now_ms);
  record_window_quality(runtime_state, anomaly);
  if (anomaly.valid) {
    pps_gated_ratio.accepted_window_count += 1u;
    pps_gated_ratio.state = PpsGateState::Open;
  } else {
    pps_gated_ratio.rejected_window_count += 1u;
    pps_gated_ratio.state = PpsGateState::Fault;
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
  if (state_transition || reason_transition || !emit_count) {
    emit_pps_gate_window_status(runtime_state, status_context, anomaly,
                                anomaly.valid && counted_edges > 0u);
    if (!anomaly.valid) {
      emit_bad_window_diagnostics(runtime_state, status_context, anomaly);
    }
  }

  return emit_count;
#else
  (void)runtime_state;
  (void)status_context;
  (void)config;
  (void)observation;
  return false;
#endif
}

bool otis_count_observation_service(OtisRuntimeState *runtime_state,
                                    OtisStatusEmitContext *status_context,
                                    const OtisCountObservationConfig *config) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0
  uint32_t now_ms = millis();
  if ((uint32_t)(now_ms - runtime_state->tcxo.last_measure_ms) <
      config->measure_period_ms) {
    return false;
  }
  runtime_state->tcxo.last_measure_ms = now_ms;

  uint64_t gate_open_ticks = otis_capture_ticks_now();
  uint32_t measured_khz = frequency_count_khz(CLOCKS_FC0_SRC_VALUE_CLKSRC_GPIN0);
  uint64_t gate_close_ticks = otis_capture_ticks_now();
  uint64_t elapsed_us = (gate_close_ticks - gate_open_ticks) / 16ull;

  if (!runtime_state->tcxo.fc0_accum_active) {
    start_fc0_accum_window(runtime_state, gate_open_ticks);
  }

  record_fc0_sample(runtime_state, measured_khz, elapsed_us);

  uint64_t emitted_gate_close_ticks = gate_close_ticks;
  if (emitted_gate_close_ticks < runtime_state->tcxo.fc0_accum_gate_open_ticks) {
    emitted_gate_close_ticks += kRp2040Timer0MicrosWrapTicks;
  }
  uint64_t observation_span_us =
      (emitted_gate_close_ticks -
       runtime_state->tcxo.fc0_accum_gate_open_ticks) /
      16ull;
  if (observation_span_us < config->gate_period_us) {
    return false;
  }

  uint32_t averaged_khz = 0;
  if (runtime_state->tcxo.fc0_accum_elapsed_us > 0) {
    averaged_khz =
        (uint32_t)(runtime_state->tcxo.fc0_accum_weighted_khz_us /
                   runtime_state->tcxo.fc0_accum_elapsed_us);
  }
  uint64_t counted_edges =
      ((uint64_t)averaged_khz * observation_span_us) / 1000ull;
  uint32_t window_flags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;
  if (runtime_state->tcxo.fc0_accum_zero_sample_count > 0u) {
    if (runtime_state->tcxo.fc0_accum_zero_sample_count ==
        runtime_state->tcxo.fc0_accum_sample_count) {
      window_flags |= OTIS_FLAG_INPUT_STUCK_LOW;
    } else {
      window_flags |= OTIS_FLAG_SOURCE_HEALTH_SUSPECT;
    }
  }

  runtime_state->tcxo.last_gate_open_ticks =
      runtime_state->tcxo.fc0_accum_gate_open_ticks;
  runtime_state->tcxo.last_gate_close_ticks = emitted_gate_close_ticks;
  runtime_state->tcxo.last_counted_edges = counted_edges;
  runtime_state->tcxo.last_elapsed_us = (uint32_t)observation_span_us;
  runtime_state->tcxo.last_measured_khz = averaged_khz;
  runtime_state->tcxo.last_sampled_elapsed_us =
      (uint32_t)runtime_state->tcxo.fc0_accum_elapsed_us;
  runtime_state->tcxo.last_sample_count =
      runtime_state->tcxo.fc0_accum_sample_count;
  runtime_state->tcxo.last_zero_sample_count =
      runtime_state->tcxo.fc0_accum_zero_sample_count;
  runtime_state->tcxo.last_valid_sample_count =
      runtime_state->tcxo.fc0_accum_sample_count -
      runtime_state->tcxo.fc0_accum_zero_sample_count;
  runtime_state->tcxo.last_first_sample_khz =
      runtime_state->tcxo.fc0_accum_first_sample_khz;
  runtime_state->tcxo.last_last_sample_khz =
      runtime_state->tcxo.fc0_accum_last_sample_khz;
  runtime_state->tcxo.last_min_sample_khz =
      runtime_state->tcxo.fc0_accum_min_sample_khz;
  runtime_state->tcxo.last_max_sample_khz =
      runtime_state->tcxo.fc0_accum_max_sample_khz;
  runtime_state->tcxo.last_window_flags = window_flags;
  WindowAnomaly anomaly = classify_window(runtime_state, config, true, true);
  update_control_gate(runtime_state, config, &anomaly, now_ms);
  record_window_quality(runtime_state, anomaly);

  emit_count_observation(runtime_state, config, counted_edges,
                         runtime_state->tcxo.last_window_flags);

  if (!anomaly.valid) {
    emit_bad_window_diagnostics(runtime_state, status_context, anomaly);
  }

  reset_fc0_accum_window(runtime_state);
  return true;
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE
  if (!h1_pio_long_gate.initialized) {
    return false;
  }

  uint32_t now_ms = millis();
  uint64_t now_ticks = otis_capture_ticks_now();
  if (!h1_pio_long_gate.active) {
    start_h1_pio_long_gate_counter(now_ticks);
    return false;
  }

  uint64_t emitted_gate_close_ticks = now_ticks;
  if (emitted_gate_close_ticks < h1_pio_long_gate.gate_open_ticks) {
    emitted_gate_close_ticks += kRp2040Timer0MicrosWrapTicks;
  }
  uint64_t observation_span_us =
      (emitted_gate_close_ticks - h1_pio_long_gate.gate_open_ticks) / 16ull;
  if (observation_span_us < config->gate_period_us) {
    return false;
  }

  uint32_t remaining = stop_h1_pio_long_gate_counter();
  OtisPioCounterSample counter_sample =
      otis_pio_counter_sample(kH1PioCounterInitialX, remaining);
  uint64_t counted_edges = counter_sample.counted_edges;
  uint32_t measured_khz = 0;
  if (observation_span_us > 0) {
    measured_khz = (uint32_t)((counted_edges * 1000ull) / observation_span_us);
  }
  uint32_t window_flags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;
  bool counted_edges_nonzero = counted_edges > 0ull;

  runtime_state->tcxo.last_gate_open_ticks = h1_pio_long_gate.gate_open_ticks;
  runtime_state->tcxo.last_gate_close_ticks = emitted_gate_close_ticks;
  runtime_state->tcxo.last_counted_edges = counted_edges;
  runtime_state->tcxo.last_elapsed_us = (uint32_t)observation_span_us;
  runtime_state->tcxo.last_measured_khz = measured_khz;
  runtime_state->tcxo.last_sampled_elapsed_us = (uint32_t)observation_span_us;
  runtime_state->tcxo.last_sample_count = 1u;
  runtime_state->tcxo.last_zero_sample_count = counted_edges_nonzero ? 0u : 1u;
  runtime_state->tcxo.last_valid_sample_count = counted_edges_nonzero ? 1u : 0u;
  runtime_state->tcxo.last_first_sample_khz = measured_khz;
  runtime_state->tcxo.last_last_sample_khz = measured_khz;
  runtime_state->tcxo.last_min_sample_khz = measured_khz;
  runtime_state->tcxo.last_max_sample_khz = measured_khz;
  runtime_state->tcxo.last_window_flags = window_flags;
  WindowAnomaly anomaly = classify_window(runtime_state, config, false, true);
  if (counter_sample.saturated) {
    anomaly.reason = kWindowReasonCounterSaturated;
    anomaly.valid = false;
    anomaly.flags |= OTIS_FLAG_COUNT_SATURATED;
    h1_pio_long_gate.saturation_count += 1u;
  }
  runtime_state->tcxo.last_window_flags = anomaly.flags;
  runtime_state->tcxo.last_window_invalid_reason = anomaly.reason;
  update_control_gate(runtime_state, config, &anomaly, now_ms);
  record_window_quality(runtime_state, anomaly);

  emit_count_observation(runtime_state, config, counted_edges,
                         runtime_state->tcxo.last_window_flags);

  if (!anomaly.valid) {
    emit_bad_window_diagnostics(runtime_state, status_context, anomaly);
  }
  emit_status_u32(
      status_context, "capture", "pio_long_gate_count_saturated_count",
      h1_pio_long_gate.saturation_count,
      h1_pio_long_gate.saturation_count == 0u ? OTIS_SEVERITY_INFO
                                              : OTIS_SEVERITY_WARN,
      runtime_state->tcxo.last_window_flags);

  start_h1_pio_long_gate_counter(otis_capture_ticks_now());
  return true;
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
  if (!h1_pio_long_gate.initialized) {
    return false;
  }

  uint32_t now_ms = millis();
  update_startup_inhibit(runtime_state, config, now_ms);
  uint64_t now_ticks = otis_capture_ticks_now();
  noInterrupts();
  bool boundary_seen = pps_boundary_seen;
  uint64_t last_isr_ticks = pps_boundary_last_isr_ticks;
  uint32_t last_isr_sequence = pps_boundary_next_sequence - 1u;
  interrupts();
  uint64_t anchor_ticks =
      boundary_seen ? last_isr_ticks : pps_gated_ratio.waiting_since_ticks;
  uint64_t waiting_ticks =
      otis_timer0_interval_ticks(anchor_ticks, now_ticks);
  uint64_t waiting_us =
      waiting_ticks / OTIS_RP2040_TIMER0_TICKS_PER_US;
  bool missing_already_reported =
      boundary_seen
          ? (pps_gated_ratio.missing_after_sequence_reported &&
             pps_gated_ratio.missing_reported_after_sequence ==
                 last_isr_sequence)
          : pps_gated_ratio.missing_before_first_reported;
  if (waiting_us > OTIS_PPS_GATE_MISSING_TIMEOUT_US &&
      !missing_already_reported) {
    pps_gated_ratio.missing_pps_count += 1u;
    runtime_state->tcxo.last_elapsed_us =
        static_cast<uint32_t>(waiting_us);
    if (boundary_seen) {
      pps_gated_ratio.missing_reported_after_sequence =
          last_isr_sequence;
      pps_gated_ratio.missing_after_sequence_reported = true;
    } else {
      pps_gated_ratio.missing_before_first_reported = true;
    }
    // The counter remains running. Only a future PPS ISR may close or restart
    // its physical aperture; foreground timeout reporting never touches it.
    emit_pps_gate_fault(
        runtime_state, status_context, kWindowReasonMissingPps,
        kReferenceReasonMissingPps, kCountReasonUnavailable,
        OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT |
            OTIS_FLAG_GATE_INCOMPLETE);
  }

  return false;
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ
  uint32_t now_us = micros();
  if ((uint32_t)(now_us - runtime_state->tcxo.gate_open_us) <
      config->gate_period_us) {
    return false;
  }

  noInterrupts();
  uint32_t counted_edges = otis_capture_irq_read_and_reset_tcxo_count();
  uint32_t gate_open_us = runtime_state->tcxo.gate_open_us;
  runtime_state->tcxo.gate_open_us = now_us;
  interrupts();

  uint32_t flags = OTIS_FLAG_NONE;
  bool counted_edges_nonzero = counted_edges > 0u;
  runtime_state->tcxo.last_gate_open_ticks = (uint64_t)gate_open_us * 16ull;
  runtime_state->tcxo.last_gate_close_ticks = (uint64_t)now_us * 16ull;
  runtime_state->tcxo.last_counted_edges = counted_edges;
  runtime_state->tcxo.last_elapsed_us = now_us - gate_open_us;
  runtime_state->tcxo.last_measured_khz = 0;
  runtime_state->tcxo.last_sampled_elapsed_us = runtime_state->tcxo.last_elapsed_us;
  runtime_state->tcxo.last_sample_count = 1u;
  runtime_state->tcxo.last_zero_sample_count = counted_edges_nonzero ? 0u : 1u;
  runtime_state->tcxo.last_valid_sample_count = counted_edges_nonzero ? 1u : 0u;
  runtime_state->tcxo.last_first_sample_khz = 0;
  runtime_state->tcxo.last_last_sample_khz = 0;
  runtime_state->tcxo.last_min_sample_khz = 0;
  runtime_state->tcxo.last_max_sample_khz = 0;
  runtime_state->tcxo.last_window_flags = flags;
  WindowAnomaly anomaly = classify_window(runtime_state, config, false, true);
  update_control_gate(runtime_state, config, &anomaly, millis());
  record_window_quality(runtime_state, anomaly);
  emit_count_observation(runtime_state, config, counted_edges,
                         runtime_state->tcxo.last_window_flags);
  if (!anomaly.valid) {
    emit_bad_window_diagnostics(runtime_state, status_context, anomaly);
  }
  return true;
#endif
#else
  (void)runtime_state;
  (void)status_context;
  (void)config;
  return false;
#endif
}

void otis_count_observation_emit_status(
    OtisRuntimeState *runtime_state,
    OtisStatusEmitContext *status_context) {
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
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
              OTIS_FLAG_PROFILE_ASSUMPTION);
#else
  (void)runtime_state;
  (void)status_context;
#endif
}

const char *otis_count_observation_measurement_mode(void) {
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE
  return "raw_edge_long_gate";
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
  return "pps_gated_ratio";
#else
  return "short_frequency_gate";
#endif
}

const char *otis_count_observation_window_invalid_reason(
    const OtisRuntimeState *runtime_state) {
  return runtime_state->tcxo.last_window_invalid_reason;
}
