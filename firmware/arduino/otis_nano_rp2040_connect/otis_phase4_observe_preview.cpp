#include "otis_phase4_observe_preview.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "otis_capture_ring.h"
#include "otis_config.h"
#include "otis_diagnostic_catalog.h"
#include "otis_diagnostic_engine.h"
#include "otis_phase4_boundary_estimator.h"
#include "otis_phase4_engine.h"
#include "otis_plant_model_v4_generated.h"
#include "otis_protocol.h"
#include "otis_reference_quality.h"
#include "otis_resource_registry.h"
#include "otis_timebase_math.h"
#include "otis_transport_serial.h"

// This translation unit intentionally has no DAC-driver dependency and exposes
// no function pointer or callback through which a decision can write hardware.
// DAC state arrives as an immutable value from the manual-command owner.

namespace {

constexpr uint64_t kTimerWrapTicks = (1ull << 32) * 16ull;
constexpr uint32_t kReferenceInvalidFlags =
    OTIS_FLAG_CAPTURE_OVERFLOW_NEARBY | OTIS_FLAG_CAPTURE_RING_OVERRUN |
    OTIS_FLAG_EDGE_ORDER_SUSPECT | OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT |
    OTIS_FLAG_SOURCE_HEALTH_SUSPECT | OTIS_FLAG_GATE_INCOMPLETE;
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
// PPS capture flags copied onto CNT describe the reference boundary. Preserve
// them on the reference side rather than collapsing a clean oscillator count
// into count-invalid. Joint observation eligibility still requires both.
constexpr uint32_t kCountInvalidFlags =
    OTIS_FLAG_SOURCE_HEALTH_SUSPECT | OTIS_FLAG_RATE_TOO_HIGH |
    OTIS_FLAG_INPUT_STUCK_LOW | OTIS_FLAG_INPUT_STUCK_HIGH |
    OTIS_FLAG_COUNT_SATURATED;
#else
constexpr uint32_t kCountInvalidFlags =
    OTIS_FLAG_CAPTURE_OVERFLOW_NEARBY | OTIS_FLAG_CAPTURE_RING_OVERRUN |
    OTIS_FLAG_EDGE_ORDER_SUSPECT | OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT |
    OTIS_FLAG_SOURCE_HEALTH_SUSPECT | OTIS_FLAG_RATE_TOO_HIGH |
    OTIS_FLAG_INPUT_STUCK_LOW | OTIS_FLAG_INPUT_STUCK_HIGH |
    OTIS_FLAG_GATE_INCOMPLETE | OTIS_FLAG_COUNT_SATURATED;
#endif
constexpr char kConfigHash[] =
    "10c38248661c46e4b31ed3f77d097ea8b6f668ff8e53784bd357ccbd66dbac85";
constexpr char kEstimatorVersion[] = "LOCAL_PPS_BOUNDARY_INTERPOLATED_V1";
constexpr char kEstimatorMethodHash[] =
    "af4afcb01f9f22b2f1102d278cf17a80d15f37f72da4016666d4278e4fb37e3b";
constexpr char kEstimatorExtrapolationPolicy[] = "prohibited";
constexpr char kPolicyVersion[] = "phase4_observe_preview_v3";
constexpr char kUncertaintyModelRef[] =
    "phase4_uncertainty_budget_v1#sha256:"
    "bf8d6dcb244c27e341a2c59e4500184ca700cfb2913f8733a687f1d2bb7d39a7";
constexpr char kTimeDomain[] = OTIS_DOMAIN_RP2040_TIMER0;
constexpr char kRuntimeApplicabilityMode[] = "observe_only";
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE && \
    OTIS_ENABLE_PPS_DUAL_OBSERVER
constexpr char kRuntimeTopologyId[] =
    "h1_run_020_g17_reworked_d14_d10_pps_witness";
#else
constexpr char kRuntimeTopologyId[] = "unsupported_topology";
#endif
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0
constexpr char kRuntimeMeasurementBackend[] =
    "OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0";
constexpr double kRuntimeConfiguredGateDurationS =
    (double)OTIS_TCXO_GATE_PERIOD_US / 1000000.0;
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ
constexpr char kRuntimeMeasurementBackend[] =
    "OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ";
constexpr double kRuntimeConfiguredGateDurationS =
    (double)OTIS_TCXO_GATE_PERIOD_US / 1000000.0;
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE
constexpr char kRuntimeMeasurementBackend[] =
    "OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE";
constexpr double kRuntimeConfiguredGateDurationS =
    (double)OTIS_H1_LONG_GATE_PERIOD_US / 1000000.0;
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
constexpr char kRuntimeMeasurementBackend[] =
    "OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO";
constexpr double kRuntimeConfiguredGateDurationS = 1.0;
#endif
constexpr size_t kFrameCapacity = 8192u;
constexpr size_t kTransportChunkLimit = 128u;
constexpr double kCaptureDomainHz = 16000000.0;
constexpr uint64_t kMinimumReferenceIntervalTicks =
    (uint64_t)OTIS_PPS_GATE_MIN_INTERVAL_US * 16ull;
constexpr uint64_t kMaximumReferenceIntervalTicks =
    (uint64_t)OTIS_PPS_GATE_MAX_INTERVAL_US * 16ull;
static_assert(
    OTIS_H1_LONG_GATE_PERIOD_US / OTIS_PPS_GATE_MIN_INTERVAL_US + 4u <=
        OTIS_PHASE4_PPS_SUPPORT_CAPACITY,
    "Phase 4 PPS support capacity is too small for the H1 long gate");
static_assert(
    OTIS_PPS_GATE_MIN_INTERVAL_US == 800000u &&
        OTIS_PPS_GATE_MAX_INTERVAL_US == 1200000u &&
        OTIS_PHASE4_REFERENCE_MAX_AGE_US == 1500000u,
    "reference-quality thresholds changed; regenerate its configuration hash");

struct TelemetryFrame {
  char data[kFrameCapacity];
  uint16_t length;
  uint16_t sent;
};

struct PendingCount {
  bool active;
  uint32_t seq;
  uint64_t open_ticks;
  uint64_t close_ticks;
  uint64_t counted_edges;
  OtisPhase4Validity reference_validity;
  OtisPhase4Validity count_validity;
  uint32_t reason_mask;
  OtisPhase4LiveDacState dac;
};

OtisPhase4Engine engine;
OtisPhase4BoundaryEstimator boundary_estimator;
OtisDiagnosticState live_diagnostic_states[OTIS_DIAG_COUNT];
OtisDiagnosticState diagnostic_state_checkpoint[OTIS_DIAG_COUNT];
uint32_t live_diagnostic_seq = 1u;
PendingCount pending_count = {};
TelemetryFrame queue[OTIS_PHASE4_PREVIEW_QUEUE_DEPTH];
// Formatting is foreground-only. Keep the largest frame in static storage so
// first-transition bursts cannot consume the constrained Mbed thread stack.
char format_frame[kFrameCapacity];
uint8_t queue_head = 0u;
uint8_t queue_tail = 0u;
uint8_t queue_count = 0u;
uint8_t queue_high_water = 0u;
uint32_t dropped_pairs = 0u;
uint32_t last_diagnosed_drop_count = 0u;
uint64_t startup_ticks = 0u;
uint64_t tick_wrap_offset = 0u;
uint64_t last_raw_ticks = 0u;
uint64_t last_reference_ticks = 0u;
uint64_t previous_reference_ticks = 0u;
uint32_t last_reference_seq = 0u;
uint32_t previous_reference_seq = 0u;
uint32_t last_reference_flags = 0u;
uint32_t previous_reference_flags = 0u;
uint32_t previous_count_seq = 0u;
uint64_t last_count_ticks = 0u;
bool reference_seen = false;
bool count_seen = false;
uint32_t reference_window_reason_mask = OTIS_PHASE4_REASON_NONE;
bool reference_stale_reported = false;
bool count_stale_reported = false;
uint32_t estimator_reference_first[OTIS_PHASE4_ESTIMATOR_WINDOW];
uint8_t estimator_reference_count = 0u;
uint8_t estimator_reference_next = 0u;
OtisPhase4BoundaryReason last_boundary_reason = OTIS_PHASE4_BOUNDARY_OK;
uint32_t pending_count_overwrite_count = 0u;
bool plant_temperature_observed = false;
bool plant_temperature_valid = false;
double plant_temperature_c = 0.0;
uint64_t plant_temperature_ticks = 0u;
bool plant_dac_write_seen = false;
uint16_t plant_last_dac_code = 0u;
uint64_t plant_last_dac_change_ticks = 0u;
bool plant_gate_open_seen = false;
uint64_t plant_last_gate_open_ticks = 0u;

uint64_t unwrap_ticks(uint64_t ticks) {
  // Count backends may already add one local timer epoch when a gate crosses
  // rollover. Normalize that representation before applying the adapter's
  // run-wide epoch so it cannot be counted twice.
  const uint64_t raw_ticks = ticks % kTimerWrapTicks;
  if (last_raw_ticks != 0u && raw_ticks < last_raw_ticks &&
      last_raw_ticks - raw_ticks > kTimerWrapTicks / 2u) {
    tick_wrap_offset += kTimerWrapTicks;
  }
  last_raw_ticks = raw_ticks;
  return raw_ticks + tick_wrap_offset;
}

const char *validity_name(OtisPhase4Validity validity) {
  switch (validity) {
    case OTIS_PHASE4_VALID: return "valid";
    case OTIS_PHASE4_INVALID: return "invalid";
    case OTIS_PHASE4_STALE: return "stale";
    case OTIS_PHASE4_UNAVAILABLE: return "unavailable";
  }
  return "unavailable";
}

const char *diagnostic_name(OtisPhase4DiagnosticHealth health) {
  switch (health) {
    case OTIS_PHASE4_DIAGNOSTIC_HEALTHY: return "healthy";
    case OTIS_PHASE4_DIAGNOSTIC_DEGRADED: return "degraded";
    case OTIS_PHASE4_DIAGNOSTIC_FAULT: return "fault";
    case OTIS_PHASE4_DIAGNOSTIC_UNKNOWN: return "unknown";
  }
  return "unknown";
}

void append_reason(char *buffer, size_t capacity, const char *reason) {
  if (buffer[0] != '\0') strncat(buffer, ";", capacity - strlen(buffer) - 1u);
  strncat(buffer, reason, capacity - strlen(buffer) - 1u);
}

void reasons_text(uint32_t mask, const char *clear_reason, char *buffer,
                  size_t capacity) {
  buffer[0] = '\0';
  struct Mapping {
    uint32_t bit;
    const char *name;
  };
  static const Mapping mappings[] = {
      {OTIS_PHASE4_REASON_REFERENCE_UNAVAILABLE, "reference_unavailable"},
      {OTIS_PHASE4_REASON_REFERENCE_STALE, "reference_stale"},
      {OTIS_PHASE4_REASON_REFERENCE_OUTLIER, "reference_interval_outlier"},
      {OTIS_PHASE4_REASON_REFERENCE_FLAGGED, "reference_flagged_invalid"},
      {OTIS_PHASE4_REASON_COUNT_UNAVAILABLE, "count_unavailable"},
      {OTIS_PHASE4_REASON_COUNT_STALE, "count_stale"},
      {OTIS_PHASE4_REASON_COUNT_ZERO, "count_zero"},
      {OTIS_PHASE4_REASON_COUNT_SATURATED, "count_saturated"},
      {OTIS_PHASE4_REASON_COUNT_DISCONTINUITY,
       "count_sequence_discontinuity"},
      {OTIS_PHASE4_REASON_COUNT_FLAGGED, "count_flagged_invalid"},
      {OTIS_PHASE4_REASON_DIAGNOSTIC_NOT_HEALTHY,
       "diagnostic_health_not_healthy"},
      {OTIS_PHASE4_REASON_ESTIMATOR_UNDERQUALIFIED,
       "estimator_underqualified_sample_count"},
      {OTIS_PHASE4_REASON_ESTIMATOR_DISPERSION,
       "estimator_dispersion_exceeded"},
      {OTIS_PHASE4_REASON_STARTUP_INHIBIT, "startup_inhibit_active"},
      {OTIS_PHASE4_REASON_CLEAN_WINDOW_INCOMPLETE,
       "clean_window_qualification_incomplete"},
      {OTIS_PHASE4_REASON_REFERENCE_HOLDOVER,
       "reference_not_eligible_holdover"},
      {OTIS_PHASE4_REASON_POST_QUALIFICATION_FAULT,
       "post_qualification_measurement_fault"},
      {OTIS_PHASE4_REASON_MODEL_UNAVAILABLE, "plant_model_unavailable"},
      {OTIS_PHASE4_REASON_MODEL_INVALID, "plant_model_invalid"},
      {OTIS_PHASE4_REASON_MODEL_VERSION, "plant_model_version_not_4"},
      {OTIS_PHASE4_REASON_MODEL_TOPOLOGY, "plant_model_topology_mismatch"},
      {OTIS_PHASE4_REASON_MODEL_BACKEND, "plant_model_backend_mismatch"},
      {OTIS_PHASE4_REASON_MODEL_INPUT_RANGE,
       "input_outside_model_applicability"},
      {OTIS_PHASE4_REASON_MODEL_EXCLUDED_INPUT,
       "plant_model_excluded_count_sequence"},
      {OTIS_PHASE4_REASON_MODEL_GAIN, "plant_model_unknown_gain"},
      {OTIS_PHASE4_REASON_DAC_UNAVAILABLE, "dac_state_unavailable"},
      {OTIS_PHASE4_REASON_REFERENCE_CONTINUITY_UNAVAILABLE,
       "reference_continuity_unavailable"},
      {OTIS_PHASE4_REASON_MODEL_ESTIMATOR_METHOD,
       "plant_model_estimator_method_mismatch"},
      {OTIS_PHASE4_REASON_BOUNDARY_SUPPORT,
       "boundary_pps_support_unavailable"},
      {OTIS_PHASE4_REASON_REFERENCE_SEQUENCE,
       "reference_sequence_nonmonotonic"},
      {OTIS_PHASE4_REASON_SUPPORT_OVERWRITTEN,
       "boundary_pps_support_overwritten"},
      {OTIS_PHASE4_REASON_PENDING_COUNT_OVERWRITTEN,
       "pending_count_overwritten"},
  };
  for (const Mapping &mapping : mappings)
    if (mask & mapping.bit) append_reason(buffer, capacity, mapping.name);
  if (buffer[0] == '\0') append_reason(buffer, capacity, clear_reason);
}

bool nearly_equal(double lhs, double rhs) {
  return isfinite(lhs) && isfinite(rhs) && fabs(lhs - rhs) <= 1e-9;
}

bool observed_gate_duration_acceptable(const OtisRuntimeState *runtime_state) {
  if (runtime_state == nullptr ||
      runtime_state->tcxo.last_gate_close_ticks <=
          runtime_state->tcxo.last_gate_open_ticks)
    return false;
  const uint64_t gate_ticks = otis_timer0_interval_ticks(
      runtime_state->tcxo.last_gate_open_ticks,
      runtime_state->tcxo.last_gate_close_ticks);
  const double observed_s = (double)gate_ticks / kCaptureDomainHz;
  const double tolerance_s =
      (double)OTIS_PHASE4_OBSERVED_GATE_TOLERANCE_US / 1000000.0;
  return isfinite(observed_s) &&
         fabs(observed_s - kRuntimeConfiguredGateDurationS) <= tolerance_s;
}

bool count_sequence_is_excluded(uint32_t count_seq) {
  for (uint32_t index = 0u;
       index < kPlantModelExcludedCountSequenceCount; ++index) {
    if (kPlantModelExcludedCountSequences[index] == count_seq) return true;
  }
  return false;
}

OtisPhase4ModelInput model_input(
    const OtisPhase4LiveDacState *dac,
    uint64_t ticks,
    uint32_t count_seq,
    bool replaying_model_source_evidence) {
  OtisPhase4ModelInput model = {};
  model.available = true;
  model.valid =
      kPlantModelStructurallyValid && kPlantModelSemanticallyValid;
  model.version_4 = kPlantModelVersion == 4u;
  model.topology_match =
      strcmp(kPlantModelApplicabilityMode, kRuntimeApplicabilityMode) == 0 &&
      strcmp(kPlantModelTopologyId, kRuntimeTopologyId) == 0;
  model.estimator_method_match =
      strcmp(kEstimatorVersion, kPlantModelEstimatorVersion) == 0 &&
      strcmp(kEstimatorMethodHash, kPlantModelEstimatorMethodHash) == 0 &&
      strcmp(kTimeDomain, kPlantModelEstimatorTimingDomain) == 0 &&
      strcmp(kEstimatorExtrapolationPolicy,
             kPlantModelEstimatorExtrapolationPolicy) == 0 &&
      nearly_equal(
          (double)OTIS_PPS_GATE_MIN_INTERVAL_US / 1000000.0,
          kPlantModelReferenceIntervalMinS) &&
      nearly_equal(
          (double)OTIS_PPS_GATE_MAX_INTERVAL_US / 1000000.0,
          kPlantModelReferenceIntervalMaxS) &&
      kReferenceInvalidFlags == kPlantModelReferenceInvalidFlagMask;
  model.backend_match =
      strcmp(kPlantModelMeasurementBackend,
             kRuntimeMeasurementBackend) == 0 &&
      nearly_equal(kPlantModelGateDurationS,
                   kRuntimeConfiguredGateDurationS);
  model.gain_available = true;
  model.hz_per_code = kHzPerCode;
  model.dac_available =
      dac != nullptr && dac->available && plant_dac_write_seen &&
      dac->applied_code == plant_last_dac_code;
  model.current_dac_code = model.dac_available ? dac->applied_code : 0u;
  if (model.dac_available &&
      !(model.current_dac_code >= kModelApplicabilityMin &&
        model.current_dac_code <= kModelApplicabilityMax)) {
    model.applicability_detail_mask |=
        OTIS_PHASE4_MODEL_DETAIL_DAC_RANGE;
  }
  if (model.dac_available) {
    if (!plant_gate_open_seen) {
      model.applicability_detail_mask |=
          OTIS_PHASE4_MODEL_DETAIL_DAC_SETTLING_UNVERIFIED;
    } else {
      const double settling_ticks_double =
          kPlantModelSettlingExclusionS * kCaptureDomainHz;
      const uint64_t settling_ticks =
          settling_ticks_double > 0.0
              ? (uint64_t)ceil(settling_ticks_double)
              : 0u;
      const bool cutoff_representable =
          plant_last_dac_change_ticks <= UINT64_MAX - settling_ticks;
      const uint64_t cutoff_ticks =
          cutoff_representable
              ? plant_last_dac_change_ticks + settling_ticks
              : UINT64_MAX;
      if (!cutoff_representable ||
          plant_last_gate_open_ticks < cutoff_ticks) {
        model.applicability_detail_mask |=
            OTIS_PHASE4_MODEL_DETAIL_DAC_SETTLING_ACTIVE;
      }
    }
  } else {
    model.applicability_detail_mask |=
        OTIS_PHASE4_MODEL_DETAIL_DAC_SETTLING_UNVERIFIED;
  }
  if (!plant_temperature_observed || !plant_temperature_valid ||
      ticks < plant_temperature_ticks) {
    model.applicability_detail_mask |=
        OTIS_PHASE4_MODEL_DETAIL_TEMPERATURE_UNAVAILABLE;
  } else {
    const uint64_t temperature_max_age_ticks =
        (uint64_t)OTIS_PHASE4_TEMPERATURE_MAX_AGE_MS * 16000ull;
    if (ticks - plant_temperature_ticks > temperature_max_age_ticks) {
      model.applicability_detail_mask |=
          OTIS_PHASE4_MODEL_DETAIL_TEMPERATURE_STALE;
    } else if (
        plant_temperature_c < kPlantModelTemperatureMinC ||
        plant_temperature_c > kPlantModelTemperatureMaxC) {
      model.applicability_detail_mask |=
          OTIS_PHASE4_MODEL_DETAIL_TEMPERATURE_RANGE;
    }
  }
  model.input_in_applicability =
      model.dac_available &&
      model.applicability_detail_mask == OTIS_PHASE4_MODEL_DETAIL_NONE;
  // Run-specific exclusions apply only while replaying the declared source
  // evidence. A live sequence number that happens to be 77 is unrelated.
  model.excluded_input =
      replaying_model_source_evidence &&
      count_sequence_is_excluded(count_seq);
  model.candidate_min_code = kCandidateMin;
  model.candidate_max_code = kCandidateMax;
  model.maximum_preview_step_codes = kMaximumPreviewStep;
  return model;
}

OtisPhase4DiagnosticHealth diagnostic_health(void) {
  return otis_capture_ring_dropped_count() == 0u &&
                 otis_resource_registry_valid() &&
                 otis_resource_registry_complete()
             ? OTIS_PHASE4_DIAGNOSTIC_HEALTHY
             : OTIS_PHASE4_DIAGNOSTIC_FAULT;
}

bool enqueue(const char *data, size_t length) {
  if (length == 0u || length >= kFrameCapacity ||
      queue_count >= OTIS_PHASE4_PREVIEW_QUEUE_DEPTH) {
    if (dropped_pairs < UINT32_MAX) dropped_pairs++;
    return false;
  }
  TelemetryFrame &frame = queue[queue_tail];
  memcpy(frame.data, data, length);
  frame.length = (uint16_t)length;
  frame.sent = 0u;
  queue_tail =
      (uint8_t)((queue_tail + 1u) % OTIS_PHASE4_PREVIEW_QUEUE_DEPTH);
  queue_count++;
  if (queue_count > queue_high_water) queue_high_water = queue_count;
  return true;
}

int append_reference_observation(
    char *frame, size_t capacity, size_t used, uint32_t sequence,
    uint64_t ticks, const OtisPhase4Observation &observation,
    const char *reference_first_text, const char *reference_last_text) {
  (void)observation;
  const OtisReferenceEvidence previous = {
      previous_reference_seq != 0u, previous_reference_seq,
      previous_reference_ticks, previous_reference_flags};
  const OtisReferenceEvidence current = {
      last_reference_seq != 0u, last_reference_seq, last_reference_ticks,
      last_reference_flags};
  const OtisReferenceQualityConfig config = {
      16000000ull, 3200000ull,
      (uint64_t)OTIS_PHASE4_REFERENCE_MAX_AGE_US * 16ull,
      57600000000ull, kReferenceInvalidFlags};
  const OtisReferenceQualityResult quality = otis_assess_reference_quality(
      &previous, &current, ticks, nullptr, &config);
  char reasons[384];
  otis_reference_quality_reasons(quality.reason_mask, reasons,
                                 sizeof(reasons));
  char source_reference_refs[64];
  if (reference_first_text[0] != '\0' &&
      reference_last_text[0] != '\0') {
    snprintf(source_reference_refs, sizeof(source_reference_refs),
             "live:REF:%s-%s", reference_first_text, reference_last_text);
  } else if (reference_last_text[0] != '\0') {
    snprintf(source_reference_refs, sizeof(source_reference_refs),
             "live:REF:%s", reference_last_text);
  } else {
    snprintf(source_reference_refs, sizeof(source_reference_refs),
             "unavailable:live:REF");
  }
  return snprintf(
      frame + used, capacity - used,
      "RFO,1,%lu,rfo:live:%06lu,%llu,%s,unknown,%s,%s,"
      "%s,unavailable:reference_receiver_metadata,"
      "unknown,unknown,%s,%s,unknown,unknown,missing,"
      "unknown,unknown,unknown,unknown,,,unknown,unknown,,%s,%s,"
      "reference_quality_v1,%s\r\n",
      (unsigned long)sequence, (unsigned long)sequence,
      (unsigned long long)ticks, kTimeDomain, reference_first_text,
      reference_last_text, source_reference_refs,
      quality.cadence_state, quality.capture_path_state,
      quality.qualification_state, reasons,
      kOtisReferenceQualityConfigHash);
}

int append_diagnostic_transitions(
    char *frame, size_t capacity, size_t used, uint32_t evidence_token,
    uint64_t ticks, uint32_t count_seq,
    const OtisPhase4Observation &observation,
    const OtisPhase4Decision &decision) {
  const bool conditions[OTIS_DIAG_COUNT] = {
      observation.reference_validity != OTIS_PHASE4_VALID ||
          !observation.reference_continuity,
      true,  // This hardware path currently has no receiver-authority metadata.
      true,  // No qualified physical counter-aperture model is configured.
      (observation.observation_reason_mask &
       (OTIS_PHASE4_REASON_COUNT_DISCONTINUITY |
        OTIS_PHASE4_REASON_REFERENCE_SEQUENCE)) != 0u,
      (observation.observation_reason_mask &
       OTIS_PHASE4_REASON_BOUNDARY_SUPPORT) != 0u,
      observation.count_validity == OTIS_PHASE4_INVALID,
      observation.diagnostic_health == OTIS_PHASE4_DIAGNOSTIC_FAULT,
      !decision.model_applicable,
      dropped_pairs > last_diagnosed_drop_count,
      (decision.model_reason_mask &
       OTIS_PHASE4_REASON_MODEL_ESTIMATOR_METHOD) != 0u,
  };
  char evidence_refs[OTIS_DIAGNOSTIC_EVIDENCE_REFS_CAPACITY];
  char reference_refs[64];
  char count_refs[48];
  if (last_reference_seq != 0u) {
    if (previous_reference_seq != 0u) {
      snprintf(reference_refs, sizeof(reference_refs), "live:REF:%lu-%lu",
               (unsigned long)previous_reference_seq,
               (unsigned long)last_reference_seq);
    } else {
      snprintf(reference_refs, sizeof(reference_refs), "live:REF:%lu",
               (unsigned long)last_reference_seq);
    }
  } else {
    snprintf(reference_refs, sizeof(reference_refs), "unavailable:live:REF");
  }
  if (count_seq != 0u) {
    snprintf(count_refs, sizeof(count_refs), "live:CNT:%lu",
             (unsigned long)count_seq);
  } else {
    snprintf(count_refs, sizeof(count_refs), "unavailable:live:CNT");
  }
  snprintf(evidence_refs, sizeof(evidence_refs), "%s;%s;"
           "unavailable:live:STS;live:DAC:latest",
           reference_refs, count_refs);
  size_t offset = used;
  for (uint8_t index = 0u; index < OTIS_DIAG_COUNT; ++index) {
    const OtisDiagnosticDefinition &definition =
        kOtisDiagnosticDefinitions[index];
    const OtisDiagnosticResult result = otis_diagnostic_observe(
        &live_diagnostic_states[index], &definition.rule, conditions[index],
        ticks, evidence_token, evidence_refs);
    if (result.transition == OTIS_DIAGNOSTIC_NO_TRANSITION) continue;
    const bool cleared = result.transition == OTIS_DIAGNOSTIC_CLEARED;
    const int added = snprintf(
        frame + offset, capacity - offset,
        "DIAG,1,%lu,%s,%s:episode:%lu,%s,%s,%s,%s,1,%s,%s,"
        "%llu,%llu,%s,%lu,%s,%s,%s,%s,%s,%s,%s,%s,%s\r\n",
        (unsigned long)live_diagnostic_seq++, definition.diagnostic_id,
        definition.diagnostic_id, (unsigned long)result.episode,
        definition.subsystem, definition.severity,
        cleared ? "cleared" : "active",
        otis_diagnostic_transition_name(result.transition), definition.reason,
        cleared ? definition.clear_reason : "",
        (unsigned long long)result.first_seen_ticks,
        (unsigned long long)result.last_seen_ticks, kTimeDomain,
        (unsigned long)result.occurrence_count,
        cleared ? "cleared" : "confirmed", result.first_evidence_refs,
        result.latest_evidence_refs, kOtisDiagnosticAlgorithmVersion,
        kOtisDiagnosticConfigHash, definition.observation_effect,
        definition.reference_effect, definition.model_effect,
        definition.control_effect);
    if (added < 0 || (size_t)added >= capacity - offset) return -1;
    offset += (size_t)added;
  }
  return (int)(offset - used);
}

void format_and_enqueue(uint32_t estimate_seq, uint32_t control_seq,
                        uint32_t count_seq, uint64_t ticks,
                        const OtisPhase4Observation &observation,
                        const OtisPhase4Decision &decision) {
  char observation_reasons[384];
  char eligibility_reasons[512];
  char model_reasons[384];
  reasons_text(observation.observation_reason_mask, "observation_valid",
               observation_reasons, sizeof(observation_reasons));
  if ((observation.observation_reason_mask &
       OTIS_PHASE4_REASON_BOUNDARY_SUPPORT) &&
      last_boundary_reason != OTIS_PHASE4_BOUNDARY_OK)
    append_reason(observation_reasons, sizeof(observation_reasons),
                  otis_phase4_boundary_reason_name(last_boundary_reason));
  reasons_text(decision.eligibility_reason_mask,
               "estimator_preview_eligible", eligibility_reasons,
               sizeof(eligibility_reasons));
  if (!observation.reference_authority_qualified)
    append_reason(eligibility_reasons, sizeof(eligibility_reasons),
                  "reference_authority_unqualified");
  reasons_text(decision.model_reason_mask, "plant_model_applicable",
               model_reasons, sizeof(model_reasons));
  const uint8_t model_detail =
      observation.model.applicability_detail_mask;
  if (model_detail & OTIS_PHASE4_MODEL_DETAIL_DAC_SETTLING_UNVERIFIED)
    append_reason(model_reasons, sizeof(model_reasons),
                  "dac_settling_state_unverified");
  if (model_detail & OTIS_PHASE4_MODEL_DETAIL_DAC_SETTLING_ACTIVE)
    append_reason(model_reasons, sizeof(model_reasons),
                  "count_window_inside_model_settling_exclusion");
  if (model_detail & OTIS_PHASE4_MODEL_DETAIL_TEMPERATURE_UNAVAILABLE)
    append_reason(model_reasons, sizeof(model_reasons),
                  "temperature_not_observed");
  if (model_detail & OTIS_PHASE4_MODEL_DETAIL_TEMPERATURE_STALE) {
    append_reason(model_reasons, sizeof(model_reasons),
                  "temperature_not_observed");
    append_reason(model_reasons, sizeof(model_reasons),
                  "temperature_observation_stale");
  }
  if (model_detail & OTIS_PHASE4_MODEL_DETAIL_TEMPERATURE_RANGE)
    append_reason(model_reasons, sizeof(model_reasons),
                  "input_outside_model_temperature_range");
  const bool observation_valid =
      observation.reference_validity == OTIS_PHASE4_VALID &&
      observation.count_validity == OTIS_PHASE4_VALID &&
      observation.reference_continuity && observation.count_continuity &&
      observation.diagnostic_health != OTIS_PHASE4_DIAGNOSTIC_FAULT;
  const char *observation_validity =
      observation_valid
          ? "valid"
          : (observation.reference_validity == OTIS_PHASE4_UNAVAILABLE ||
                     observation.count_validity == OTIS_PHASE4_UNAVAILABLE
                 ? "unavailable"
                 : "invalid");
  char count_seq_text[16] = "";
  char count_ref[40] = "unavailable:live:CNT";
  char reference_first_text[16] = "";
  char reference_last_text[16] = "";
  char frequency_observation_text[32] = "";
  char frequency_estimate_text[32] = "";
  char frequency_error_text[32] = "";
  char dispersion_text[32] = "";
  const char *uncertainty_status =
      decision.estimate_available ? "incomplete" : "unavailable";
  const char *uncertainty_reasons =
      decision.estimate_available
          ? "count_quantization_model_unavailable;counter_aperture_unavailable;reference_uncertainty_unavailable;calibration_uncertainty_unavailable;model_uncertainty_unavailable"
          : "estimate_unavailable";
  char reference_age_text[32] = "";
  if (count_seq != 0u) {
    snprintf(count_seq_text, sizeof(count_seq_text), "%lu",
             (unsigned long)count_seq);
    snprintf(count_ref, sizeof(count_ref), "live:CNT:%lu",
             (unsigned long)count_seq);
  }
  if (estimator_reference_count > 0u) {
    const uint8_t oldest =
        estimator_reference_count < OTIS_PHASE4_ESTIMATOR_WINDOW
            ? 0u
            : estimator_reference_next;
    snprintf(reference_first_text, sizeof(reference_first_text), "%lu",
             (unsigned long)estimator_reference_first[oldest]);
  }
  if (last_reference_seq != 0u)
    snprintf(reference_last_text, sizeof(reference_last_text), "%lu",
             (unsigned long)last_reference_seq);
  if (observation.frequency_observation_available)
    snprintf(frequency_observation_text, sizeof(frequency_observation_text),
             "%.12g", observation.frequency_observation_hz);
  if (decision.estimate_available) {
    snprintf(frequency_estimate_text, sizeof(frequency_estimate_text), "%.12g",
             decision.frequency_estimate_hz);
    snprintf(frequency_error_text, sizeof(frequency_error_text), "%.12g",
             decision.frequency_error_hz);
    snprintf(dispersion_text, sizeof(dispersion_text), "%.12g",
             decision.dispersion_hz);
  }
  if (reference_seen)
    snprintf(reference_age_text, sizeof(reference_age_text), "%.12g",
             (double)(ticks - last_reference_ticks) / 16000000.0);
  const char *diagnostic_reasons =
      observation.diagnostic_health == OTIS_PHASE4_DIAGNOSTIC_HEALTHY
          ? "diagnostic_healthy"
          : "status_capture_or_host_drop";
  char *frame = format_frame;
  int used = snprintf(
      frame, kFrameCapacity,
      "EST,2,%lu,est:live:%06lu,%llu,%s,%s,%s,%s,%s,"
      "live:STS:snapshot_at:%llu,%s,firmware_config:" OTIS_FIRMWARE_CONFIG_ID
      ";config_hash:%s,%s,%s,%s,%s,"
      "%s,%s,%s,%s,,%s,%s,%s,%s,%u,%s,%s,%s,%s,"
      "%s,%s,,,,,,,,,not_combined_missing_components,"
      "%s,false,,%s,%s\r\n",
      (unsigned long)estimate_seq, (unsigned long)estimate_seq,
      (unsigned long long)ticks, kTimeDomain, count_seq_text, count_ref,
      reference_first_text, reference_last_text, (unsigned long long)ticks,
      observation.model.dac_available ? "live:DAC:latest"
                                      : "unavailable:dac_steps_v1",
      kConfigHash, kEstimatorVersion, kConfigHash, observation_validity,
      observation_reasons, validity_name(observation.reference_validity),
      reference_age_text,
      observation.reference_continuity ? "true" : "false",
      validity_name(observation.count_validity),
      observation.count_continuity ? "true" : "false",
      diagnostic_name(observation.diagnostic_health), diagnostic_reasons,
      frequency_observation_text,
      decision.accepted_sample_count,
      otis_phase4_confidence_name(decision.confidence),
      frequency_estimate_text, frequency_error_text, dispersion_text,
      uncertainty_status, uncertainty_reasons, kUncertaintyModelRef,
      decision.estimator_eligible ? "true" : "false", eligibility_reasons);
  if (used < 0 || (size_t)used >= kFrameCapacity) {
    if (dropped_pairs < UINT32_MAX) dropped_pairs++;
    return;
  }

  char full_eligibility[1024];
  if (decision.preview_eligible) {
    snprintf(full_eligibility, sizeof(full_eligibility), "preview_eligible");
  } else {
    snprintf(full_eligibility, sizeof(full_eligibility), "%s;%s",
             eligibility_reasons, model_reasons);
  }
  char decision_reasons[160] = "";
  append_reason(decision_reasons, sizeof(decision_reasons),
                decision.preview_available ? "preview_available_observe_only"
                                           : "preview_inhibited");
  if (decision.step_limited)
    append_reason(decision_reasons, sizeof(decision_reasons),
                  "preview_step_limited");
  if (decision.range_clamped)
    append_reason(decision_reasons, sizeof(decision_reasons),
                  "preview_range_clamped");
  append_reason(decision_reasons, sizeof(decision_reasons),
                "actuation_prohibited_observe_only_phase");
  char current_dac_text[16] = "";
  char raw_delta_text[32] = "";
  char limited_delta_text[24] = "";
  char proposed_code_text[16] = "";
  char gain_text[32] = "";
  if (observation.model.dac_available)
    snprintf(current_dac_text, sizeof(current_dac_text), "%u",
             observation.model.current_dac_code);
  if (observation.model.gain_available)
    snprintf(gain_text, sizeof(gain_text), "%.12g",
             observation.model.hz_per_code);
  if (decision.preview_available) {
    snprintf(raw_delta_text, sizeof(raw_delta_text), "%.12g",
             decision.raw_delta_codes);
    snprintf(limited_delta_text, sizeof(limited_delta_text), "%ld",
             (long)decision.limited_delta_codes);
    snprintf(proposed_code_text, sizeof(proposed_code_text), "%u",
             decision.proposed_dac_code);
  }

  int added = snprintf(
      frame + used, kFrameCapacity - (size_t)used,
      "CTL,1,%lu,ctl:live:%06lu,%llu,%s,est:live:%06lu,"
      "%s,%s,%lu,%s,%s,%s,%s,%s,"
      "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
      "%s,true,false,false,%s\r\n",
      (unsigned long)control_seq, (unsigned long)control_seq,
      (unsigned long long)ticks, kTimeDomain, (unsigned long)estimate_seq,
      kPlantModelRef, kPlantModelId, (unsigned long)kPlantModelVersion,
      kPlantModelHash, kPolicyVersion, kConfigHash,
      otis_phase4_state_name(decision.state),
      otis_phase4_state_name(decision.previous_state),
      decision.state_transition ? "true" : "false",
      otis_phase4_transition_reason_name(decision.transition_reason),
      decision.preview_eligible ? "true" : "false", full_eligibility,
      diagnostic_name(observation.diagnostic_health),
      decision.model_applicable ? "applicable" : "not_applicable",
      model_reasons, current_dac_text, frequency_error_text, gain_text,
      raw_delta_text, limited_delta_text, proposed_code_text,
      decision.step_limited ? "true" : "false",
      decision.range_clamped ? "true" : "false",
      decision.preview_available ? "true" : "false", decision_reasons);
  if (added < 0 || (size_t)added >= kFrameCapacity - (size_t)used) {
    if (dropped_pairs < UINT32_MAX) dropped_pairs++;
    return;
  }
  used += added;
  added = append_reference_observation(
      frame, kFrameCapacity, (size_t)used, estimate_seq, ticks, observation,
      reference_first_text, reference_last_text);
  if (added < 0 || (size_t)added >= kFrameCapacity - (size_t)used) {
    if (dropped_pairs < UINT32_MAX) dropped_pairs++;
    return;
  }
  used += added;
  memcpy(diagnostic_state_checkpoint, live_diagnostic_states,
         sizeof(live_diagnostic_states));
  const uint32_t diagnostic_seq_checkpoint = live_diagnostic_seq;
  added = append_diagnostic_transitions(
      frame, kFrameCapacity, (size_t)used, estimate_seq, ticks, count_seq,
      observation, decision);
  if (added < 0 || (size_t)added >= kFrameCapacity - (size_t)used) {
    memcpy(live_diagnostic_states, diagnostic_state_checkpoint,
           sizeof(live_diagnostic_states));
    live_diagnostic_seq = diagnostic_seq_checkpoint;
    if (dropped_pairs < UINT32_MAX) dropped_pairs++;
    return;
  }
  if (enqueue(frame, (size_t)(used + added))) {
    last_diagnosed_drop_count = dropped_pairs;
  } else {
    memcpy(live_diagnostic_states, diagnostic_state_checkpoint,
           sizeof(live_diagnostic_states));
    live_diagnostic_seq = diagnostic_seq_checkpoint;
  }
}

void evaluate(uint64_t ticks, bool new_count, uint32_t count_seq,
              OtisRuntimeState *runtime_state,
              const OtisPhase4LiveDacState *dac, OtisPhase4Validity ref_validity,
              OtisPhase4Validity count_validity, uint32_t reasons,
              bool frequency_available, double frequency_hz) {
  OtisPhase4Observation observation = {};
  observation.timestamp_ticks = ticks;
  observation.elapsed_s =
      ticks >= startup_ticks ? (double)(ticks - startup_ticks) / 16000000.0
                             : 0.0;
  observation.new_count = new_count;
  observation.reference_validity = ref_validity;
  observation.count_validity = count_validity;
  observation.reference_continuity =
      reference_seen && previous_reference_seq != 0u &&
      !(reasons & (OTIS_PHASE4_REASON_REFERENCE_OUTLIER |
                   OTIS_PHASE4_REASON_REFERENCE_FLAGGED |
                   OTIS_PHASE4_REASON_REFERENCE_STALE));
  // The current hardware path captures PPS cadence but has no receiver-status
  // evidence. Cadence alone must not qualify reference authority.
  observation.reference_authority_qualified = false;
  observation.count_continuity =
      count_seq == 0u || previous_count_seq == 0u ||
      count_seq == previous_count_seq + 1u;
  observation.diagnostic_health = diagnostic_health();
  if (observation.diagnostic_health != OTIS_PHASE4_DIAGNOSTIC_HEALTHY)
    reasons |= OTIS_PHASE4_REASON_DIAGNOSTIC_NOT_HEALTHY;
  observation.observation_reason_mask = reasons;
  observation.frequency_observation_available = frequency_available;
  observation.frequency_observation_hz = frequency_hz;
  observation.model = model_input(dac, ticks, count_seq, false);

  OtisPhase4Decision decision;
  otis_phase4_engine_evaluate(&engine, &observation, &decision);
  const uint32_t estimate_seq = runtime_state->sequences.estimate_seq++;
  const uint32_t control_seq = runtime_state->sequences.control_seq++;
  format_and_enqueue(estimate_seq, control_seq, count_seq, ticks, observation,
                     decision);
  if (new_count) previous_count_seq = count_seq;
}

void remember_frequency_support(
    const OtisPhase4BoundaryResult &boundary_result) {
  estimator_reference_first[estimator_reference_next] =
      boundary_result.before_open_seq;
  estimator_reference_next = (uint8_t)(
      (estimator_reference_next + 1u) % OTIS_PHASE4_ESTIMATOR_WINDOW);
  if (estimator_reference_count < OTIS_PHASE4_ESTIMATOR_WINDOW)
    estimator_reference_count++;
}

void finalize_pending_count(uint64_t evaluation_ticks,
                            OtisRuntimeState *runtime_state,
                            uint32_t additional_reasons) {
  if (!pending_count.active) return;
  const OtisPhase4BoundaryResult result =
      otis_phase4_boundary_estimator_estimate(
          &boundary_estimator, pending_count.open_ticks,
          pending_count.close_ticks, pending_count.counted_edges,
          kCaptureDomainHz,
          (double)OTIS_PPS_GATE_MAX_INTERVAL_US / 1000000.0);
  if (!result.valid && result.retryable_after_next_reference) return;

  last_boundary_reason = result.reason;
  uint32_t reasons = pending_count.reason_mask | additional_reasons;
  if (!result.valid) reasons |= OTIS_PHASE4_REASON_BOUNDARY_SUPPORT;
  if (boundary_estimator.last_reference_issue ==
      OTIS_PHASE4_REFERENCE_ISSUE_SEQUENCE)
    reasons |= OTIS_PHASE4_REASON_REFERENCE_SEQUENCE;
  if (!result.valid &&
      result.reason == OTIS_PHASE4_BOUNDARY_MISSING_START_SUPPORT &&
      boundary_estimator.support_overwrite_count > 0u)
    reasons |= OTIS_PHASE4_REASON_SUPPORT_OVERWRITTEN;
  if (result.valid) remember_frequency_support(result);
  const OtisPhase4Validity reference_validity =
      result.valid ? pending_count.reference_validity
                   : OTIS_PHASE4_INVALID;

  evaluate(evaluation_ticks, true, pending_count.seq, runtime_state,
           &pending_count.dac, reference_validity,
           pending_count.count_validity, reasons, result.valid,
           result.valid ? result.frequency_hz : 0.0);
  pending_count.active = false;
  reference_window_reason_mask = OTIS_PHASE4_REASON_NONE;
}

}  // namespace

void otis_phase4_observe_preview_on_temperature(bool available,
                                                float temperature_c,
                                                uint64_t timestamp_ticks) {
#if OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW
  plant_temperature_observed = true;
  plant_temperature_valid = available && isfinite(temperature_c);
  plant_temperature_ticks = unwrap_ticks(timestamp_ticks);
  if (plant_temperature_valid)
    plant_temperature_c = (double)temperature_c;
#else
  (void)available;
  (void)temperature_c;
  (void)timestamp_ticks;
#endif
}

void otis_phase4_observe_preview_on_dac_applied(
    uint16_t applied_code, uint64_t timestamp_ticks) {
#if OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW
  const uint64_t applied_ticks = unwrap_ticks(timestamp_ticks);
  if (!plant_dac_write_seen || applied_code != plant_last_dac_code)
    plant_last_dac_change_ticks = applied_ticks;
  plant_dac_write_seen = true;
  plant_last_dac_code = applied_code;
#else
  (void)applied_code;
  (void)timestamp_ticks;
#endif
}

bool otis_phase4_observe_preview_begin(uint64_t initial_ticks) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  constexpr double nominal_frequency_hz = (double)OTIS_NOMINAL_OCXO_HZ;
#else
  constexpr double nominal_frequency_hz = (double)OTIS_NOMINAL_TCXO_HZ;
#endif
  OtisPhase4EngineConfig config = {
      (double)OTIS_FC0_STARTUP_INHIBIT_MS / 1000.0,
      (uint8_t)OTIS_FC0_CONTROL_READY_CLEAN_WINDOWS,
      (uint8_t)OTIS_PHASE4_RECOVERY_CLEAN_WINDOWS,
      (uint8_t)OTIS_PHASE4_ESTIMATOR_WINDOW,
      (uint8_t)OTIS_PHASE4_MINIMUM_ESTIMATOR_SAMPLES,
      OTIS_PHASE4_MAXIMUM_DISPERSION_HZ,
      nominal_frequency_hz,
  };
  otis_phase4_engine_init(&engine, &config);
  otis_phase4_boundary_estimator_init(&boundary_estimator);
  for (uint8_t index = 0u; index < OTIS_DIAG_COUNT; ++index)
    otis_diagnostic_state_init(&live_diagnostic_states[index]);
  live_diagnostic_seq = 1u;
  memset(&pending_count, 0, sizeof(pending_count));
  startup_ticks = initial_ticks;
  queue_head = queue_tail = queue_count = queue_high_water = 0u;
  dropped_pairs = 0u;
  last_diagnosed_drop_count = 0u;
  tick_wrap_offset = last_raw_ticks = 0u;
  last_reference_ticks = previous_reference_ticks = 0u;
  last_reference_seq = previous_reference_seq = previous_count_seq = 0u;
  last_reference_flags = previous_reference_flags = 0u;
  last_count_ticks = 0u;
  reference_seen = count_seen = false;
  reference_window_reason_mask = OTIS_PHASE4_REASON_NONE;
  reference_stale_reported = count_stale_reported = false;
  memset(estimator_reference_first, 0, sizeof(estimator_reference_first));
  estimator_reference_count = estimator_reference_next = 0u;
  last_boundary_reason = OTIS_PHASE4_BOUNDARY_OK;
  pending_count_overwrite_count = 0u;
  plant_temperature_observed = false;
  plant_temperature_valid = false;
  plant_temperature_c = 0.0;
  plant_temperature_ticks = 0u;
  plant_dac_write_seen = false;
  plant_last_dac_code = 0u;
  plant_last_dac_change_ticks = 0u;
  plant_gate_open_seen = false;
  plant_last_gate_open_ticks = 0u;
  return true;
}

void otis_phase4_observe_preview_emit_headers(void) {
#if OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW
  otis_transport_write_cstr(
      "record_type,schema_version,estimate_seq,estimate_id,estimator_timestamp_ticks,time_domain,source_count_seq,source_count_ref,source_reference_first_seq,source_reference_last_seq,source_status_refs,source_dac_ref,manifest_ref,estimator_version,config_hash,observation_validity,observation_reason_codes,reference_validity,reference_age_s,reference_continuity,count_validity,count_age_s,count_continuity,diagnostic_health,diagnostic_reason_codes,frequency_observation_hz,accepted_sample_count,estimator_confidence,frequency_estimate_hz,frequency_error_hz,dispersion_hz,uncertainty_status,uncertainty_reason_codes,count_quantization_standard_uncertainty_hz,counter_aperture_standard_uncertainty_hz,reference_standard_uncertainty_hz,calibration_standard_uncertainty_hz,model_standard_uncertainty_hz,combined_standard_uncertainty_hz,coverage_factor,expanded_uncertainty_hz,correlation_policy,uncertainty_model_ref,drift_enabled,drift_hz_per_s,preview_eligibility,eligibility_reason_codes\r\n");
  otis_transport_write_cstr(
      "record_type,schema_version,control_seq,decision_id,decision_timestamp_ticks,time_domain,est_input_ref,plant_model_ref,plant_model_id,plant_model_version,plant_model_hash,policy_version,config_hash,control_state,previous_control_state,state_transition,transition_reason_code,preview_eligibility,eligibility_reason_codes,diagnostic_health,model_applicability,model_reason_codes,current_dac_code,frequency_error_hz,hz_per_code,raw_delta_codes,limited_delta_codes,proposed_dac_code,step_limited,range_clamped,preview_available,preview_only,actuation_authorized,actionable,decision_reason_code\r\n");
  otis_transport_write_cstr(
      "record_type,schema_version,reference_observation_seq,reference_observation_id,observation_timestamp_ticks,time_domain,source_identity_epoch,source_reference_first_seq,source_reference_last_seq,source_reference_refs,source_metadata_refs,receiver_identity,receiver_firmware,cadence_state,capture_path_state,receiver_authority_state,utc_traceability_state,metadata_freshness,timing_mode,fix_holdover_state,antenna_state,leap_state,sawtooth_correction_ns,cable_delay_ns,pulse_configuration,calibration_ref,reference_standard_uncertainty_s,qualification_state,qualification_reason_codes,algorithm_version,config_hash\r\n");
  otis_transport_write_cstr(
      "record_type,schema_version,diagnostic_seq,diagnostic_id,episode_id,subsystem,severity,state,transition,diagnostic_confidence,reason_code,clear_reason_code,first_seen_ticks,last_seen_ticks,time_domain,occurrence_count,persistence_state,first_evidence_refs,latest_evidence_refs,algorithm_version,config_hash,observation_effect,reference_effect,model_effect,control_effect\r\n");
#endif
}

void otis_phase4_observe_preview_on_reference(
    uint32_t reference_seq, uint64_t timestamp_ticks, uint32_t flags,
    OtisRuntimeState *runtime_state, const OtisPhase4LiveDacState *dac) {
#if OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW
  const uint64_t ticks = unwrap_ticks(timestamp_ticks);
  previous_reference_ticks = last_reference_ticks;
  previous_reference_seq = last_reference_seq;
  previous_reference_flags = last_reference_flags;
  last_reference_ticks = ticks;
  last_reference_seq = reference_seq;
  last_reference_flags = flags;
  uint32_t reasons = OTIS_PHASE4_REASON_NONE;
  if (flags & kReferenceInvalidFlags) {
    reasons |= OTIS_PHASE4_REASON_REFERENCE_FLAGGED;
    reference_window_reason_mask |= OTIS_PHASE4_REASON_REFERENCE_FLAGGED;
  }
  if (reference_seen) {
    const uint64_t interval = ticks - previous_reference_ticks;
    if (interval < (uint64_t)OTIS_PPS_GATE_MIN_INTERVAL_US * 16ull ||
        interval > (uint64_t)OTIS_PPS_GATE_MAX_INTERVAL_US * 16ull) {
      reasons |= OTIS_PHASE4_REASON_REFERENCE_OUTLIER;
      reference_window_reason_mask |= OTIS_PHASE4_REASON_REFERENCE_OUTLIER;
    }
  }
  otis_phase4_boundary_estimator_on_reference(
      &boundary_estimator, reference_seq, ticks, flags,
      kReferenceInvalidFlags, kMinimumReferenceIntervalTicks,
      kMaximumReferenceIntervalTicks, 1.0);
  if (boundary_estimator.last_reference_issue ==
      OTIS_PHASE4_REFERENCE_ISSUE_SEQUENCE) {
    reasons |= OTIS_PHASE4_REASON_REFERENCE_SEQUENCE;
    reference_window_reason_mask |= OTIS_PHASE4_REASON_REFERENCE_SEQUENCE;
  }
  reference_seen = true;
  if (pending_count.active) {
    pending_count.reason_mask |= reasons;
    finalize_pending_count(ticks, runtime_state, reasons);
  }
  if (reference_stale_reported) {
    reference_stale_reported = false;
    if (previous_reference_seq == 0u)
      reasons |= OTIS_PHASE4_REASON_REFERENCE_CONTINUITY_UNAVAILABLE;
    evaluate(ticks, false, previous_count_seq, runtime_state, dac,
             reasons == OTIS_PHASE4_REASON_NONE ? OTIS_PHASE4_VALID
                                                : OTIS_PHASE4_INVALID,
             count_seen ? OTIS_PHASE4_VALID : OTIS_PHASE4_UNAVAILABLE,
             reasons | (count_seen ? OTIS_PHASE4_REASON_NONE
                                   : OTIS_PHASE4_REASON_COUNT_UNAVAILABLE),
             false, 0.0);
  }
#else
  (void)reference_seq;
  (void)timestamp_ticks;
  (void)flags;
  (void)runtime_state;
  (void)dac;
#endif
}

void otis_phase4_observe_preview_on_count(
    uint32_t count_seq, OtisRuntimeState *runtime_state,
    const OtisPhase4LiveDacState *dac) {
#if OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW
  uint64_t ticks = unwrap_ticks(runtime_state->tcxo.last_gate_close_ticks);
  if (pending_count.active) {
    last_boundary_reason = OTIS_PHASE4_BOUNDARY_MISSING_END_SUPPORT;
    uint32_t overwritten_reasons =
        pending_count.reason_mask | OTIS_PHASE4_REASON_BOUNDARY_SUPPORT |
        OTIS_PHASE4_REASON_PENDING_COUNT_OVERWRITTEN;
    evaluate(ticks, true, pending_count.seq, runtime_state, &pending_count.dac,
             OTIS_PHASE4_INVALID, pending_count.count_validity,
             overwritten_reasons, false, 0.0);
    pending_count.active = false;
    if (pending_count_overwrite_count < UINT32_MAX)
      pending_count_overwrite_count++;
  }
  last_count_ticks = ticks;
  count_seen = true;
  count_stale_reported = false;
  uint32_t reasons = OTIS_PHASE4_REASON_NONE;
  const uint32_t flags = runtime_state->tcxo.last_window_flags;
  OtisPhase4Validity reference_validity = OTIS_PHASE4_VALID;
  if (!reference_seen) {
    reference_validity = OTIS_PHASE4_UNAVAILABLE;
    reasons |= OTIS_PHASE4_REASON_REFERENCE_UNAVAILABLE;
  } else if (previous_reference_seq == 0u) {
    reference_validity = OTIS_PHASE4_INVALID;
    reasons |= OTIS_PHASE4_REASON_REFERENCE_CONTINUITY_UNAVAILABLE;
  } else if (ticks - last_reference_ticks >
             (uint64_t)OTIS_PHASE4_REFERENCE_MAX_AGE_US * 16ull) {
    reference_validity = OTIS_PHASE4_STALE;
    reasons |= OTIS_PHASE4_REASON_REFERENCE_STALE;
  } else if (reference_window_reason_mask != OTIS_PHASE4_REASON_NONE) {
    reference_validity = OTIS_PHASE4_INVALID;
  }
  if (flags & OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT) {
    reference_validity = OTIS_PHASE4_INVALID;
    reasons |= OTIS_PHASE4_REASON_REFERENCE_FLAGGED;
  }
  reasons |= reference_window_reason_mask;

  OtisPhase4Validity count_validity = OTIS_PHASE4_VALID;
  if (runtime_state->tcxo.last_counted_edges == 0u) {
    count_validity = OTIS_PHASE4_INVALID;
    reasons |= OTIS_PHASE4_REASON_COUNT_ZERO;
  }
  if (flags & OTIS_FLAG_COUNT_SATURATED) {
    count_validity = OTIS_PHASE4_INVALID;
    reasons |= OTIS_PHASE4_REASON_COUNT_SATURATED;
  }
  if (flags & kCountInvalidFlags & ~OTIS_FLAG_COUNT_SATURATED) {
    count_validity = OTIS_PHASE4_INVALID;
    reasons |= OTIS_PHASE4_REASON_COUNT_FLAGGED;
  }
  if (!observed_gate_duration_acceptable(runtime_state)) {
    count_validity = OTIS_PHASE4_INVALID;
    reasons |= OTIS_PHASE4_REASON_COUNT_FLAGGED;
  }
  if (previous_count_seq != 0u && count_seq != previous_count_seq + 1u) {
    count_validity = OTIS_PHASE4_INVALID;
    reasons |= OTIS_PHASE4_REASON_COUNT_DISCONTINUITY;
  }

  const uint64_t gate_ticks = otis_timer0_interval_ticks(
      runtime_state->tcxo.last_gate_open_ticks,
      runtime_state->tcxo.last_gate_close_ticks);
  const uint64_t open_ticks =
      ticks >= gate_ticks ? ticks - gate_ticks : 0u;
  plant_gate_open_seen = true;
  plant_last_gate_open_ticks = open_ticks;
  const OtisPhase4BoundaryResult boundary_result =
      otis_phase4_boundary_estimator_estimate(
          &boundary_estimator, open_ticks, ticks,
          runtime_state->tcxo.last_counted_edges, kCaptureDomainHz,
          (double)OTIS_PPS_GATE_MAX_INTERVAL_US / 1000000.0);
  last_boundary_reason = boundary_result.reason;
  if (boundary_result.valid) {
    remember_frequency_support(boundary_result);
    evaluate(ticks, true, count_seq, runtime_state, dac, reference_validity,
             count_validity, reasons, true, boundary_result.frequency_hz);
  } else if (boundary_result.retryable_after_next_reference) {
    pending_count.active = true;
    pending_count.seq = count_seq;
    pending_count.open_ticks = open_ticks;
    pending_count.close_ticks = ticks;
    pending_count.counted_edges = runtime_state->tcxo.last_counted_edges;
    pending_count.reference_validity = reference_validity;
    pending_count.count_validity = count_validity;
    pending_count.reason_mask = reasons;
    pending_count.dac =
        dac != nullptr ? *dac : OtisPhase4LiveDacState{false, 0u};
  } else {
    reasons |= OTIS_PHASE4_REASON_BOUNDARY_SUPPORT;
    if (boundary_result.reason ==
            OTIS_PHASE4_BOUNDARY_MISSING_START_SUPPORT &&
        boundary_estimator.support_overwrite_count > 0u)
      reasons |= OTIS_PHASE4_REASON_SUPPORT_OVERWRITTEN;
    const OtisPhase4Validity boundary_reference_validity =
        reference_validity == OTIS_PHASE4_UNAVAILABLE ||
                reference_validity == OTIS_PHASE4_STALE
            ? reference_validity
            : OTIS_PHASE4_INVALID;
    evaluate(ticks, true, count_seq, runtime_state, dac,
             boundary_reference_validity,
             count_validity, reasons, false, 0.0);
  }
  reference_window_reason_mask = OTIS_PHASE4_REASON_NONE;
#else
  (void)count_seq;
  (void)runtime_state;
  (void)dac;
#endif
}

void otis_phase4_observe_preview_poll(
    uint64_t now_ticks, OtisRuntimeState *runtime_state,
    const OtisPhase4LiveDacState *dac) {
#if OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW
  const uint64_t ticks = unwrap_ticks(now_ticks);
  if (pending_count.active && reference_seen &&
      ticks - last_reference_ticks >
          (uint64_t)OTIS_PHASE4_REFERENCE_MAX_AGE_US * 16ull) {
    last_boundary_reason = OTIS_PHASE4_BOUNDARY_MISSING_END_SUPPORT;
    evaluate(
        ticks, true, pending_count.seq, runtime_state, &pending_count.dac,
        OTIS_PHASE4_STALE, pending_count.count_validity,
        pending_count.reason_mask | OTIS_PHASE4_REASON_REFERENCE_STALE |
            OTIS_PHASE4_REASON_BOUNDARY_SUPPORT,
        false, 0.0);
    pending_count.active = false;
  }
  if (!reference_seen && !reference_stale_reported &&
      ticks - startup_ticks >
          (uint64_t)OTIS_PHASE4_REFERENCE_MAX_AGE_US * 16ull) {
    reference_stale_reported = true;
    evaluate(ticks, false, previous_count_seq, runtime_state, dac,
             OTIS_PHASE4_UNAVAILABLE,
             count_seen ? OTIS_PHASE4_VALID : OTIS_PHASE4_UNAVAILABLE,
             OTIS_PHASE4_REASON_REFERENCE_UNAVAILABLE |
                 (count_seen ? OTIS_PHASE4_REASON_NONE
                             : OTIS_PHASE4_REASON_COUNT_UNAVAILABLE),
             false, 0.0);
  } else if (reference_seen && !reference_stale_reported &&
             ticks - last_reference_ticks >
                 (uint64_t)OTIS_PHASE4_REFERENCE_MAX_AGE_US * 16ull) {
    reference_stale_reported = true;
    evaluate(ticks, false, previous_count_seq, runtime_state, dac,
             OTIS_PHASE4_STALE,
             count_seen ? OTIS_PHASE4_VALID : OTIS_PHASE4_UNAVAILABLE,
             OTIS_PHASE4_REASON_REFERENCE_STALE |
                 (count_seen ? OTIS_PHASE4_REASON_NONE
                             : OTIS_PHASE4_REASON_COUNT_UNAVAILABLE),
             false, 0.0);
  }
  if (!count_seen && !count_stale_reported &&
      ticks - startup_ticks >
          (uint64_t)OTIS_PHASE4_COUNT_MAX_AGE_US * 16ull) {
    count_stale_reported = true;
    evaluate(ticks, false, 0u, runtime_state, dac,
             reference_seen && !reference_stale_reported
                 ? OTIS_PHASE4_VALID
                 : OTIS_PHASE4_UNAVAILABLE,
             OTIS_PHASE4_UNAVAILABLE,
             OTIS_PHASE4_REASON_COUNT_UNAVAILABLE |
                 (reference_seen ? OTIS_PHASE4_REASON_NONE
                                 : OTIS_PHASE4_REASON_REFERENCE_UNAVAILABLE),
             false, 0.0);
  } else if (count_seen && !count_stale_reported &&
             ticks - last_count_ticks >
                 (uint64_t)OTIS_PHASE4_COUNT_MAX_AGE_US * 16ull) {
    count_stale_reported = true;
    evaluate(ticks, false, previous_count_seq, runtime_state, dac,
             reference_stale_reported ? OTIS_PHASE4_STALE
                                      : OTIS_PHASE4_VALID,
             OTIS_PHASE4_STALE,
             OTIS_PHASE4_REASON_COUNT_STALE |
                 (reference_stale_reported
                      ? OTIS_PHASE4_REASON_REFERENCE_STALE
                      : OTIS_PHASE4_REASON_NONE),
             false, 0.0);
  }
#else
  (void)now_ticks;
  (void)runtime_state;
  (void)dac;
#endif
}

void otis_phase4_observe_preview_service_transport(void) {
#if OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW
  if (queue_count == 0u) return;
  size_t available = otis_transport_available_for_write();
  if (available == 0u) return;
  TelemetryFrame &frame = queue[queue_head];
  size_t remaining = (size_t)frame.length - frame.sent;
  size_t chunk = remaining < available ? remaining : available;
  if (chunk > kTransportChunkLimit) chunk = kTransportChunkLimit;
  const size_t written = otis_transport_write_bytes(
      (const uint8_t *)frame.data + frame.sent, chunk);
  frame.sent = (uint16_t)(frame.sent + written);
  if (frame.sent == frame.length) {
    queue_head =
        (uint8_t)((queue_head + 1u) % OTIS_PHASE4_PREVIEW_QUEUE_DEPTH);
    queue_count--;
  }
#endif
}

bool otis_phase4_observe_preview_transport_busy(void) {
#if OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW
  return queue_count > 0u && queue[queue_head].sent > 0u;
#else
  return false;
#endif
}

void otis_phase4_observe_preview_emit_status(
    OtisStatusEmitContext *status_context) {
#if OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW
  otis_status_emit(status_context, "phase4_preview", "preview_only", "true",
                   OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(status_context, "phase4_preview", "control_ready", "false",
                   OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(status_context, "phase4_preview", "actuation_enabled",
                   "false", OTIS_SEVERITY_INFO,
                   OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(status_context, "phase4_preview", "estimator_method_id",
                   kEstimatorVersion, OTIS_SEVERITY_INFO,
                   OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(status_context, "phase4_preview",
                   "estimator_method_definition_hash",
                   kEstimatorMethodHash, OTIS_SEVERITY_INFO,
                   OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(status_context, "phase4_preview",
                   "boundary_last_reason",
                   otis_phase4_boundary_reason_name(last_boundary_reason),
                   last_boundary_reason == OTIS_PHASE4_BOUNDARY_OK
                       ? OTIS_SEVERITY_INFO
                       : OTIS_SEVERITY_WARN,
                   last_boundary_reason == OTIS_PHASE4_BOUNDARY_OK
                       ? OTIS_FLAG_NONE
                       : OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT);
  otis_status_emit(status_context, "phase4_preview", "state",
                   otis_phase4_state_name(engine.state), OTIS_SEVERITY_INFO,
                   OTIS_FLAG_NONE);
  otis_status_emit_u32(status_context, "phase4_preview",
                       "queued_telemetry_pairs", queue_count,
                       OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  otis_status_emit_u32(status_context, "phase4_preview",
                       "dropped_telemetry_pair_count", dropped_pairs,
                       dropped_pairs ? OTIS_SEVERITY_WARN
                                     : OTIS_SEVERITY_INFO,
                       dropped_pairs ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                                     : OTIS_FLAG_NONE);
  otis_status_emit_u32(status_context, "phase4_preview", "queue_high_water",
                       queue_high_water, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  otis_status_emit_u32(
      status_context, "phase4_preview", "pps_support_overwrite_count",
      boundary_estimator.support_overwrite_count,
      boundary_estimator.support_overwrite_count == 0u ? OTIS_SEVERITY_INFO
                                                       : OTIS_SEVERITY_WARN,
      boundary_estimator.support_overwrite_count == 0u
          ? OTIS_FLAG_NONE
          : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  otis_status_emit_u32(
      status_context, "phase4_preview", "pending_count_overwrite_count",
      pending_count_overwrite_count,
      pending_count_overwrite_count == 0u ? OTIS_SEVERITY_INFO
                                          : OTIS_SEVERITY_WARN,
      pending_count_overwrite_count == 0u
          ? OTIS_FLAG_NONE
          : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
#else
  (void)status_context;
#endif
}

uint32_t otis_phase4_observe_preview_dropped_pair_count(void) {
  return dropped_pairs;
}

uint8_t otis_phase4_observe_preview_queue_high_water(void) {
  return queue_high_water;
}
