#include "otis_frequency_regulation_live.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "otis_config.h"
#include "otis_adaptive_hybrid_regulation_live.h"
#include "otis_frequency_regulation_engine.h"
#include "otis_oscillator_snapshot_estimator.h"
#include "otis_decimal_format.h"
#include "otis_dual_core_partition.h"
#include "otis_phase_preview_live.h"
#include "otis_protocol.h"
#include "otis_spsc_queue.h"
#include "otis_monotonic_us_extension.h"
#include "otis_timebase_math.h"
#include "otis_transport_serial.h"

namespace {

constexpr char kEstimatorMethod[] = "PPS_ACCEPTED_SPAN_FREQUENCY_V1";
constexpr char kSelectedEstimatorVersion[] =
    "OTIS_PPS_GATED_FREQUENCY_ESTIMATOR_V1";
constexpr char kSelectedEstimatorReference[] = "pps_gated_frequency";
constexpr char kSelectedEstimatorHash[] =
    OTIS_BUILD_FREQUENCY_ESTIMATOR_SHA256;
constexpr char kPolicyId[] = "OTIS_ADAPTIVE_HYBRID_REGULATION_V1";
constexpr char kPolicyHash[] = OTIS_BUILD_ADAPTIVE_POLICY_SHA256;
constexpr char kPlantModelId[] = "OTIS_PPS_GATED_OSCILLATOR_PLANT_V1";
constexpr char kPlantModelHash[] = OTIS_BUILD_PLANT_MODEL_SHA256;
constexpr char kTimeDomain[] = "rp2040_monotonic_us32";
constexpr double kNominalFrequencyHz = 10000000.0;
constexpr double kNominalGainHzPerCode = 0.00017008467693813145;
static_assert(kNominalGainHzPerCode > 0.0,
              "the selected plant gain must remain positive");
// Deterministic wire representation of the exact selected gain above.
constexpr char kNominalGainHzPerCodeText[] = "0.000170084676938";
constexpr uint32_t kStartupWarmupS = OTIS_ADAPTIVE_HYBRID_STARTUP_WARMUP_S;
constexpr uint32_t kSettlingExclusionS = OTIS_ADAPTIVE_HYBRID_SETTLING_EXCLUSION_S;
constexpr uint64_t kCaptureTicksPerSecond = 1000000ull;
constexpr int32_t kActiveLiveUpdateCodes = 0;
constexpr uint8_t kQueueDepth = 4u;
constexpr size_t kFrameCapacity = 1536u;
constexpr size_t kTransportChunkLimit = 192u;
static_assert(kFrameCapacity == OTIS_EVIDENCE_FRAME_CAPACITY,
              "preview and evidence frame capacities must match");

struct Frame {
  char data[kFrameCapacity];
  uint16_t length;
  uint16_t sent;
};

OtisOscillatorSnapshotEstimator estimator;
OtisFrequencyRegulationEngine controller;
OtisSpscQueue<Frame, kQueueDepth> queue;
// Core 1 is the sole producer for this module and these calls are sequential,
// not re-entrant. Keep both complete-frame buffers out of its bounded stack.
// enqueue() copies formatter_scratch synchronously before another formatter
// can run, so the two buffers cannot alias live data.
char formatter_scratch[kFrameCapacity] = {};
OtisEvidenceFrameMessage evidence_frame_scratch = {};
Frame transport_frame = {};
bool transport_frame_active = false;
uint32_t dropped_frames = 0u;
uint32_t evidence_frame_sequence = 0u;
uint32_t estimate_seq = 0u;
uint32_t control_seq = 0u;
uint32_t startup_s = 0u;
uint32_t settling_until_s = 0u;
uint32_t current_dac_epoch = 0u;
uint16_t current_applied_code = 0u;
uint32_t tight_deadband_seq = 0u;
bool initialized = false;
bool warmup_boundary_seen = false;
bool temperature_available = false;
double temperature_c = 0.0;
bool selected_estimator_valid = false;
bool selected_model_applicable = false;
OtisMonotonicUsExtension timer_extension = {};
uint64_t exact_settling_deadline_ticks = 0u;
uint32_t exact_settling_capture_session = 0u;
bool exact_settling_deadline_available = false;

bool enqueue(const char *data, size_t length);

bool emit_tight_deadband(const OtisFrequencyRegulationDecision &decision,
                         uint32_t source_estimate_seq,
                         uint64_t timestamp_ticks, uint64_t capture_session,
                         uint64_t dac_epoch,
                         int64_t accumulated_edge_error_counts) {
  if (!decision.tight_deadband_decision_available) return false;
  const OtisIntegerCountDeadbandTightDeadbandDecision &tight =
      decision.tight_deadband;
  const bool state_transition = tight.state_before != tight.state_after;
  const bool three_count_band_inside =
      tight.absolute_edge_error_counts_available &&
      tight.absolute_edge_error_counts <= 3u;
  const bool two_count_band_inside =
      tight.absolute_edge_error_counts_available &&
      tight.absolute_edge_error_counts <= 2u;
  char *frame = formatter_scratch;
  constexpr size_t frame_capacity = sizeof(formatter_scratch);
  const int used = snprintf(
      frame, frame_capacity,
      "TDB,1,%lu,est:frequency_regulation:%s:%06lu,%llu,%s,%llu,%llu,%lld,%llu,%s,%s,%u,%u,%s,%s,%s,%s,%s,%s,%s,%s,false,false,false,%s\r\n",
      static_cast<unsigned long>(tight_deadband_seq++),
      kSelectedEstimatorReference,
      static_cast<unsigned long>(source_estimate_seq),
      static_cast<unsigned long long>(timestamp_ticks), kTimeDomain,
      static_cast<unsigned long long>(capture_session),
      static_cast<unsigned long long>(dac_epoch),
      static_cast<long long>(accumulated_edge_error_counts),
      static_cast<unsigned long long>(tight.absolute_edge_error_counts),
      otis_integer_count_tight_deadband_state_name(tight.state_before),
      otis_integer_count_tight_deadband_state_name(tight.state_after),
      tight.entry_pending_count, tight.release_pending_count,
      state_transition ? "true" : "false",
      tight.frequency_controller_eligible ? "true" : "false",
      tight.requalified ? "true" : "false",
      tight.requalification_reason_available
          ? otis_integer_count_tight_deadband_reason_name(
                tight.requalification_reason)
          : "",
      three_count_band_inside ? "true" : "false",
      two_count_band_inside ? "true" : "false", tight.policy_id,
      kPolicyHash,
      otis_integer_count_tight_deadband_reason_name(tight.reason));
  return used > 0 && static_cast<size_t>(used) < frame_capacity &&
         enqueue(frame, static_cast<size_t>(used));
}

bool enqueue(const char *data, size_t length) {
  if (data == nullptr || length == 0u || length >= kFrameCapacity) {
    uint32_t observed = __atomic_load_n(&dropped_frames, __ATOMIC_RELAXED);
    while (observed != UINT32_MAX &&
           !__atomic_compare_exchange_n(&dropped_frames, &observed,
                                        observed + 1u, false,
                                        __ATOMIC_RELAXED,
                                        __ATOMIC_RELAXED)) {
    }
    return false;
  }
  evidence_frame_scratch.sequence = evidence_frame_sequence + 1u;
  evidence_frame_scratch.length = static_cast<uint16_t>(length);
  memcpy(evidence_frame_scratch.data, data, length);
  evidence_frame_scratch.data[length] = '\0';
  if (otis_dual_core_publish_evidence(&evidence_frame_scratch)) {
    evidence_frame_sequence = evidence_frame_scratch.sequence;
    return true;
  }
  uint32_t observed = __atomic_load_n(&dropped_frames, __ATOMIC_RELAXED);
  while (observed != UINT32_MAX &&
         !__atomic_compare_exchange_n(&dropped_frames, &observed,
                                      observed + 1u, false,
                                      __ATOMIC_RELAXED,
                                      __ATOMIC_RELAXED)) {
  }
  return false;
}

bool code_context_valid(const OtisRegulationStaticCodeState *code) {
  return code != nullptr && code->available && code->requested_applied_match &&
         code->i2c_ok && code->applied_code >= 0xA800u &&
         code->applied_code <= 0xAB00u;
}

bool temperature_telemetry_valid(void) {
  return temperature_available && isfinite(temperature_c);
}

OtisFrequencyRegulationInput controller_input(
    uint32_t uptime_s, double error_hz, bool frequency_available,
    bool reference_valid, bool estimator_valid, bool count_valid,
    const OtisRegulationStaticCodeState *code) {
  const bool code_present = code != nullptr && code->available;
  return {
      uptime_s,
      error_hz,
      static_cast<uint16_t>(code_present ? code->applied_code : 0u),
      temperature_c,
      frequency_available,
      reference_valid,
      estimator_valid,
      count_valid,
      current_dac_epoch != 0u,
      code_present,
      code_context_valid(code),
      code != nullptr && code->requested_applied_match,
      code != nullptr && code->i2c_ok,
      temperature_available,
      false,
      false,
  };
}

const char *model_reason(const OtisRegulationStaticCodeState *code) {
  if (code == nullptr || !code->available) return "static_dac_code_unavailable";
  if (!code->requested_applied_match) return "requested_applied_mismatch";
  if (!code->i2c_ok) return "i2c_failure";
  if (code->applied_code < 0xA800u || code->applied_code > 0xAB00u)
    return "current_code_outside_characterized_range";
  return "model_applicable";
}

bool emit_estimate(bool selected, const OtisRegulationSpanEstimate &span,
                   const OtisRegulationStaticCodeState *code,
                   uint64_t timestamp_ticks) {
  const uint32_t seq = estimate_seq++;
  otis_dual_core_note_timing_estimate(seq);
  otis_dual_core_note_timing_progress(
      OtisTimingProgressPhase::FrequencyEstimatePrepare, timestamp_ticks);
  const double frequency =
      selected ? span.selected_frequency_hz : span.diagnostic_frequency_hz;
  const uint32_t first = selected ? span.selected_first_sequence
                                  : span.diagnostic_first_sequence;
  const uint32_t samples = selected ? OTIS_FREQUENCY_ESTIMATOR_SPAN_INTERVALS
                                    : OTIS_REGULATION_DIAGNOSTIC_SPAN_INTERVALS;
  const bool applicable = code_context_valid(code);
  char frequency_text[32] = "";
  char frequency_error_text[32] = "";
  if (!otis_format_fixed(frequency, 12u, frequency_text,
                         sizeof(frequency_text)) ||
      !otis_format_fixed(frequency - kNominalFrequencyHz, 12u,
                         frequency_error_text,
                         sizeof(frequency_error_text))) {
    uint32_t observed = __atomic_load_n(&dropped_frames, __ATOMIC_RELAXED);
    if (observed != UINT32_MAX)
      __atomic_store_n(&dropped_frames, observed + 1u, __ATOMIC_RELAXED);
    return false;
  }
  char *frame = formatter_scratch;
  constexpr size_t frame_capacity = sizeof(formatter_scratch);
  otis_dual_core_note_timing_progress(
      OtisTimingProgressPhase::FrequencyEstimateFormat, timestamp_ticks);
  int used = snprintf(
      frame, frame_capacity,
      "EST,3,%lu,est:frequency_regulation:%s:%06lu,%llu,%s,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,live:APS:%lu:%lu:%lu:%lu,"
      "live:STS:pps_gate,live:DAC:%lu,firmware_config:%s,%s,%s,"
      "valid,contiguous_accepted_reference_span,valid,0,true,valid,0,true,healthy,"
      "diagnostic_healthy,%s,%lu,unavailable,%s,%s,,unavailable,"
      "counter_aperture_uncertainty_unavailable;reference_uncertainty_unavailable;calibration_uncertainty_unavailable,"
      ",,,,,,,,not_combined_missing_components,unavailable:combined_uncertainty,false,,%s,%s\r\n",
      static_cast<unsigned long>(seq),
      selected ? kSelectedEstimatorReference : "diagnostic60",
      static_cast<unsigned long>(seq),
      static_cast<unsigned long long>(timestamp_ticks), kTimeDomain,
      static_cast<unsigned long>(span.capture_session),
      static_cast<unsigned long>(span.acceptance_epoch),
      static_cast<unsigned long>(selected ? span.selected_opening_accepted_boundary_ordinal : span.diagnostic_opening_accepted_boundary_ordinal),
      static_cast<unsigned long>(span.closing_accepted_boundary_ordinal),
      static_cast<unsigned long>(first),
      static_cast<unsigned long>(span.last_sequence),
      static_cast<unsigned long>(selected ? span.selected_first_reference_sequence : span.diagnostic_first_reference_sequence),
      static_cast<unsigned long>(span.last_reference_sequence),
      static_cast<unsigned long>(span.capture_session),
      static_cast<unsigned long>(span.acceptance_epoch),
      static_cast<unsigned long>(selected ? span.selected_opening_accepted_boundary_ordinal : span.diagnostic_opening_accepted_boundary_ordinal),
      static_cast<unsigned long>(span.closing_accepted_boundary_ordinal),
      static_cast<unsigned long>(current_dac_epoch), OTIS_BUILD_IMAGE_ID,
      selected ? kSelectedEstimatorVersion
               : "accepted_reference_frequency_diagnostic_60s_overlap_v1",
      kSelectedEstimatorHash, frequency_text,
      static_cast<unsigned long>(samples), frequency_text,
      frequency_error_text,
      selected && applicable ? "true" : "false",
      selected ? (applicable ? "preview_input"
                             : model_reason(code))
               : "diagnostic_non_authoritative");
  bool published = false;
  if (used > 0 && static_cast<size_t>(used) < frame_capacity)
    published = enqueue(frame, static_cast<size_t>(used));
  else {
    uint32_t observed = __atomic_load_n(&dropped_frames, __ATOMIC_RELAXED);
    if (observed != UINT32_MAX)
      __atomic_store_n(&dropped_frames, observed + 1u, __ATOMIC_RELAXED);
  }
  otis_dual_core_note_timing_progress(
      OtisTimingProgressPhase::FrequencyEstimatePublish, timestamp_ticks);
  return published;
}

void emit_control(const OtisFrequencyRegulationDecision &decision,
                  const OtisRegulationStaticCodeState *code,
                  uint64_t timestamp_ticks, uint32_t source_estimate_seq) {
  char frequency_error[32] = "";
  char raw_delta[32] = "";
  char limited_delta[24] = "";
  char proposed[16] = "";
  if (decision.frequency_available &&
      !otis_format_fixed(decision.frequency_error_hz, 12u, frequency_error,
                         sizeof(frequency_error)))
    return;
  if (decision.preview_available) {
    if (!otis_format_fixed(decision.raw_delta_codes, 12u, raw_delta,
                           sizeof(raw_delta)))
      return;
    snprintf(limited_delta, sizeof(limited_delta), "%ld",
             static_cast<long>(decision.limited_delta_codes));
    snprintf(proposed, sizeof(proposed), "%u", decision.proposed_code);
  }
  char *frame = formatter_scratch;
  constexpr size_t frame_capacity = sizeof(formatter_scratch);
  const uint32_t seq = control_seq++;
  const bool applicable = code_context_valid(code);
  char current_code[16] = "";
  if (applicable)
    snprintf(current_code, sizeof(current_code), "%u", code->applied_code);
  if (decision.state_transition && otis_dual_core_timing_owner_active()) {
    OtisCriticalRecordMessage transition = {};
    transition.kind = OtisCriticalMessageKind::StateTransition;
    transition.sequence = seq;
    transition.timestamp_ticks = timestamp_ticks;
    snprintf(transition.component, sizeof(transition.component), "%s",
             "frequency_regulation");
    snprintf(transition.reason, sizeof(transition.reason), "%s",
             decision.reason);
    otis_dual_core_publish_critical(&transition);
  }
  int used = snprintf(
      frame, frame_capacity,
      "CTL,1,%lu,ctl:frequency_regulation:%06lu,%llu,%s,est:frequency_regulation:%s:%06lu,"
      "model:pps_gated_oscillator_plant_v1,%s,1,%s,%s,%s,%s,%s,%s,%s,"
      "%s,%s,healthy,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,false,false,%s\r\n",
      static_cast<unsigned long>(seq), static_cast<unsigned long>(seq),
      static_cast<unsigned long long>(timestamp_ticks), kTimeDomain,
      kSelectedEstimatorReference,
      static_cast<unsigned long>(source_estimate_seq), kPlantModelId,
      kPlantModelHash, kPolicyId, kPolicyHash,
      otis_regulation_preview_state_name(decision.state),
      otis_regulation_preview_state_name(decision.previous_state),
      decision.state_transition ? "true" : "false", decision.reason,
      decision.preview_available ? "true" : "false",
      decision.preview_available ? "preview_available"
                                 : decision.reason,
      applicable ? "applicable" : "not_applicable", model_reason(code),
      current_code, frequency_error, kNominalGainHzPerCodeText,
      raw_delta,
      limited_delta, proposed, decision.step_limited ? "true" : "false",
      decision.range_clamped ? "true" : "false",
      decision.preview_available ? "true" : "false", decision.reason);
  if (used > 0 && static_cast<size_t>(used) < frame_capacity)
    enqueue(frame, static_cast<size_t>(used));
  else {
    uint32_t observed = __atomic_load_n(&dropped_frames, __ATOMIC_RELAXED);
    if (observed != UINT32_MAX)
      __atomic_store_n(&dropped_frames, observed + 1u, __ATOMIC_RELAXED);
  }
}

}  // namespace

bool otis_frequency_regulation_live_begin(uint32_t startup_uptime_s) {
  otis_oscillator_snapshot_estimator_init(&estimator);
  otis_frequency_regulation_engine_init(&controller, startup_uptime_s);
  startup_s = startup_uptime_s;
  settling_until_s = startup_uptime_s;
  current_dac_epoch = 0u;
  current_applied_code = 0u;
  tight_deadband_seq = 0u;
  initialized = true;
  queue.reset();
  evidence_frame_sequence = 0u;
  transport_frame = {};
  transport_frame_active = false;
  __atomic_store_n(&dropped_frames, 0u, __ATOMIC_RELAXED);
  selected_estimator_valid = false;
  selected_model_applicable = false;
  otis_monotonic_us_extension_init(&timer_extension);
  exact_settling_deadline_ticks = 0u;
  exact_settling_capture_session = 0u;
  exact_settling_deadline_available = false;
  return true;
}

void otis_frequency_regulation_live_emit_headers(void) {
  otis_transport_write_cstr(
      OTIS_CONTRACT_ESTIMATES_V3_HEADER "\r\n");
  otis_transport_write_cstr(
      OTIS_CONTRACT_CONTROL_PREVIEWS_V1_HEADER "\r\n");
  otis_transport_write_cstr(
      OTIS_CONTRACT_TIGHT_DEADBAND_DECISIONS_V1_HEADER "\r\n");
}

void otis_frequency_regulation_live_on_temperature(bool available,
                                            float value_c,
                                            uint32_t uptime_s) {
  (void)uptime_s;
  temperature_available = available && isfinite(value_c);
  temperature_c = static_cast<double>(value_c);
}

void otis_frequency_regulation_live_on_dac_applied(uint16_t applied_code,
                                           uint32_t uptime_s) {
  (void)applied_code;
  otis_oscillator_snapshot_estimator_reset(&estimator);
  selected_estimator_valid = false;
  selected_model_applicable = false;
  settling_until_s = uptime_s + kSettlingExclusionS;
  exact_settling_deadline_ticks = 0u;
  exact_settling_capture_session = 0u;
  exact_settling_deadline_available = false;
  otis_frequency_regulation_engine_note_dac_epoch(&controller, uptime_s);
}

void otis_frequency_regulation_live_on_dac_applied_epoch(uint16_t applied_code,
                                                 uint32_t dac_epoch,
                                                 uint32_t uptime_s) {
  current_dac_epoch = dac_epoch;
  current_applied_code = applied_code;
  otis_frequency_regulation_live_on_dac_applied(applied_code, uptime_s);
}

void otis_frequency_regulation_live_on_dac_applied_epoch_exact(
    uint16_t applied_code, uint32_t dac_epoch, uint32_t uptime_s,
    uint64_t application_ticks, uint32_t capture_session) {
  otis_frequency_regulation_live_on_dac_applied_epoch(applied_code, dac_epoch,
                                               uptime_s);
  constexpr uint64_t kSettlingExclusionTicks =
      static_cast<uint64_t>(kSettlingExclusionS) * kCaptureTicksPerSecond;
  if (application_ticks != 0u && capture_session != 0u &&
      application_ticks <= UINT64_MAX - kSettlingExclusionTicks) {
    exact_settling_deadline_ticks =
        application_ticks + kSettlingExclusionTicks;
    exact_settling_capture_session = capture_session;
    exact_settling_deadline_available = true;
  }
  if (!timer_extension.available ||
      timer_extension.capture_session != capture_session)
    otis_monotonic_us_extension_seed(
        &timer_extension, application_ticks, capture_session);
  (void)application_ticks;
  (void)capture_session;
}

bool otis_frequency_regulation_live_applied_epoch_exact(uint16_t applied_code,
                                                 uint32_t dac_epoch) {
  return initialized && current_applied_code == applied_code &&
         current_dac_epoch == dac_epoch;
}

void otis_frequency_regulation_live_on_reference_selection(
    const OtisReferenceAcceptanceOutcome *selection,
    uint64_t closing_extended_ticks, uint32_t uptime_s,
    uint64_t operational_decision_raw_ticks,
    const OtisRegulationStaticCodeState *static_code,
    OtisAdaptiveHybridRegulationLiveOutcome *active_outcome) {
  if (active_outcome != nullptr) *active_outcome = {};
  if (!initialized || selection == nullptr || otis_dual_core_fail_static()) return;
  const auto *observation = &selection->closing;
  const uint64_t current_boundary_extended_ticks = closing_extended_ticks;
  const bool boundary_extended = observation->capture_session != 0u &&
      uint32_t(closing_extended_ticks) == observation->reference_timestamp_ticks;
  if (boundary_extended && (!timer_extension.available ||
      timer_extension.capture_session != observation->capture_session ||
      closing_extended_ticks >= timer_extension.extended_us))
    otis_monotonic_us_extension_seed(&timer_extension, closing_extended_ticks, observation->capture_session);
  using Disposition = OtisReferenceAcceptanceDisposition;
  if (selection->disposition == Disposition::EarlyExcluded ||
      selection->disposition == Disposition::Seeded ||
      selection->disposition == Disposition::Acquiring) return;
  if (selection->disposition == Disposition::TrackingEstablished) {
    OtisRegulationSpanEstimate unused = {};
    otis_oscillator_snapshot_estimator_ingest(&estimator, selection, &unused);
    selected_estimator_valid = false;
    selected_model_applicable = false;
    return;
  }
  bool interval_valid = boundary_extended && selection->has_span && selection->tracking &&
      selection->disposition == Disposition::AcceptedSpan;
  if (!interval_valid) {
    otis_frequency_regulation_live_on_capture_fault("accepted_reference_discontinuity", uptime_s, static_code);
    return;
  }
  // Source EST/REF/SNP/CNT timestamps retain the captured D14 coordinate.
  // A control decision is a later operational event: the caller samples it
  // after refreshing metadata health, so an asynchronous lifecycle transition
  // can never be followed by a backdated decision from a delayed capture.
  uint64_t active_decision_timestamp_ticks = 0u;
  if (boundary_extended &&
      operational_decision_raw_ticks < OTIS_RP2040_MONOTONIC_US32_MODULUS) {
    const uint64_t elapsed_since_capture = otis_monotonic_us32_interval(
        observation->reference_timestamp_ticks, operational_decision_raw_ticks);
    if (elapsed_since_capture <= OTIS_ESTIMATE_TO_DECISION_MAXIMUM_LAG_TICKS &&
        current_boundary_extended_ticks <= UINT64_MAX - elapsed_since_capture)
      active_decision_timestamp_ticks =
          current_boundary_extended_ticks + elapsed_since_capture;
  }
  const uint32_t active_decision_timestamp_s = static_cast<uint32_t>(
      active_decision_timestamp_ticks / kCaptureTicksPerSecond);
  const bool interval_opening_exact = boundary_extended &&
      closing_extended_ticks >= selection->interval_ticks &&
      selection->opening.capture_session == observation->capture_session;
  const uint64_t interval_opening_extended_ticks = interval_opening_exact
      ? closing_extended_ticks - selection->interval_ticks : 0u;
  const uint32_t warmup_complete_s = startup_s + kStartupWarmupS;
  if (!warmup_boundary_seen && uptime_s >= warmup_complete_s) {
    warmup_boundary_seen = true;
    otis_oscillator_snapshot_estimator_reset(&estimator);
    selected_estimator_valid = false;
    selected_model_applicable = false;
    if (settling_until_s <= warmup_complete_s)
      otis_frequency_regulation_engine_init(&controller, startup_s);
    OtisFrequencyRegulationInput input = controller_input(
        uptime_s, 0.0, false, interval_valid, interval_valid, interval_valid,
        static_code);
    OtisFrequencyRegulationDecision decision;
    otis_frequency_regulation_engine_evaluate(&controller, &input, &decision);
    emit_control(decision, static_code, observation->reference_timestamp_ticks,
                 estimate_seq);
  }
  // A boundary stamped exactly at settling_until_s closes the oscillator
  // interval that began one second earlier, so it still straddles the
  // excluded settling window.  Admit only boundaries strictly after it; the
  // 600th accepted interval then closes after the full 900 + 600 seconds.
  bool settling_interval_excluded = uptime_s <= settling_until_s;
  if (exact_settling_deadline_available) {
    settling_interval_excluded =
        !interval_opening_exact ||
        observation->capture_session != exact_settling_capture_session ||
        interval_opening_extended_ticks < exact_settling_deadline_ticks;
    if (!settling_interval_excluded)
      exact_settling_deadline_available = false;
  }
  if (uptime_s < warmup_complete_s || settling_interval_excluded) {
    otis_oscillator_snapshot_estimator_reset(&estimator);
    selected_estimator_valid = false;
    selected_model_applicable = false;
    return;
  }
  OtisRegulationSpanEstimate span;
  otis_oscillator_snapshot_estimator_ingest(
      &estimator, selection, &span);
  interval_valid = span.source_continuous;
  if (!interval_valid) {
    selected_estimator_valid = false;
    selected_model_applicable = false;
    OtisFrequencyRegulationInput input = controller_input(
        uptime_s, 0.0, false, false, false, false, static_code);
    OtisFrequencyRegulationDecision decision;
    otis_frequency_regulation_engine_evaluate(&controller, &input, &decision);
    emit_control(decision, static_code, observation->reference_timestamp_ticks,
                 estimate_seq);
    return;
  }
  if (span.diagnostic_available &&
      !emit_estimate(false, span, static_code, observation->reference_timestamp_ticks)) {
    selected_estimator_valid = false;
    selected_model_applicable = false;
    return;
  }
  if (span.selected_available) {
    const uint32_t selected_estimate_seq = estimate_seq;
    if (!emit_estimate(true, span, static_code, observation->reference_timestamp_ticks)) {
      selected_estimator_valid = false;
      selected_model_applicable = false;
      return;
    }
    const bool applicable = code_context_valid(static_code);
    OtisFrequencyRegulationInput input = controller_input(
        uptime_s, span.selected_frequency_hz - kNominalFrequencyHz, true,
        true, true, true, static_code);
    input.model_applicable = applicable;
    input.accumulated_edge_error_counts =
        span.selected_accumulated_edge_error_counts;
    input.capture_session = observation->capture_session;
    input.dac_epoch_identity = current_dac_epoch;
    input.accumulated_edge_error_counts_available = true;
    OtisFrequencyRegulationDecision decision;
    otis_frequency_regulation_engine_evaluate(&controller, &input, &decision);
    selected_estimator_valid = true;
    selected_model_applicable = applicable;
    const bool tight_evidence_queued = emit_tight_deadband(
        decision, selected_estimate_seq, observation->reference_timestamp_ticks,
        observation->capture_session, current_dac_epoch,
        span.selected_accumulated_edge_error_counts);
    OtisAdaptiveHybridRegulationLiveDecision active_decision = {
        control_seq,
        active_decision_timestamp_s,
        decision.current_code,
        decision.limited_delta_codes,
        decision.proposed_code,
        decision.frequency_error_hz,
        true,
        applicable,
        decision.preview_available && tight_evidence_queued &&
            decision.tight_deadband_decision_available &&
            decision.tight_deadband.frequency_controller_eligible,
        decision.preview_available,
    };
    OtisPhasePreviewActiveSnapshot phase_snapshot = {};
    const bool phase_snapshot_available =
        otis_phase_preview_live_get_active_snapshot(&phase_snapshot);
    active_decision.capture_session = observation->capture_session;
    active_decision.source_acceptance_epoch = span.acceptance_epoch;
    active_decision.source_opening_accepted_boundary_ordinal = span.selected_opening_accepted_boundary_ordinal;
    active_decision.source_closing_accepted_boundary_ordinal = span.closing_accepted_boundary_ordinal;
    const bool phase_source_matches = phase_snapshot_available &&
        phase_snapshot.capture_session == span.capture_session &&
        phase_snapshot.acceptance_epoch == span.acceptance_epoch &&
        phase_snapshot.accepted_boundary_ordinal == span.closing_accepted_boundary_ordinal;
    active_decision.accumulated_edge_error_counts =
        span.selected_accumulated_edge_error_counts;
    active_decision.tight_state =
        otis_integer_count_tight_deadband_state_name(
            decision.tight_deadband.state_after);
    active_decision.dac_epoch = current_dac_epoch;
    active_decision.phase_epoch = phase_snapshot.phase_epoch;
    active_decision.phase_observation_sequence =
        phase_snapshot.observation_sequence;
    active_decision.relative_phase_cycles =
        phase_snapshot.relative_phase_cycles;
    active_decision.phase_dac_epoch = phase_snapshot.dac_epoch;
    active_decision.phase_applied_code = phase_snapshot.applied_code;
    active_decision.phase_continuous =
        phase_source_matches && phase_snapshot.phase_continuous;
    active_decision.phase_current =
        phase_source_matches && phase_snapshot.phase_current;
    active_decision.phase_step_detected =
        !phase_snapshot_available || phase_snapshot.phase_step_detected;
    active_decision.phase_recorder_published =
        phase_source_matches && phase_snapshot.recorder_published;
    OtisAdaptiveHybridRegulationLiveOutcome local_active_outcome;
    otis_adaptive_hybrid_regulation_live_on_decision_at_ticks(
        &active_decision, active_decision_timestamp_ticks,
        &local_active_outcome);
    if (active_outcome != nullptr &&
        !(active_outcome->request_created || active_outcome->faulted ||
          active_outcome->response_recorded))
      *active_outcome = local_active_outcome;
    emit_control(decision, static_code, observation->reference_timestamp_ticks,
                 selected_estimate_seq);
  }
}

void otis_frequency_regulation_live_on_capture_fault(
    const char *reason, uint32_t uptime_s,
    const OtisRegulationStaticCodeState *static_code) {
  (void)reason;
  otis_oscillator_snapshot_estimator_reset(&estimator);
  selected_estimator_valid = false;
  selected_model_applicable = false;
  OtisFrequencyRegulationInput input = controller_input(
      uptime_s, 0.0, false, false, false, false, static_code);
  OtisFrequencyRegulationDecision decision;
  otis_frequency_regulation_engine_evaluate(&controller, &input, &decision);
  emit_control(decision, static_code, 0u, estimate_seq);
}

void otis_frequency_regulation_live_get_authority_state(
    OtisFrequencyRegulationAuthorityState *state) {
  if (state == nullptr) return;
  state->estimator_valid = selected_estimator_valid;
  state->model_applicable = selected_model_applicable;
  state->temperature_valid = temperature_telemetry_valid();
  state->selected_interval_count = estimator.selected_count;
}

bool otis_frequency_regulation_live_extend_monotonic_us(
    uint64_t raw_ticks, uint64_t *extended_ticks) {
  constexpr uint64_t kMaximumProjectionUs =
      OTIS_ESTIMATE_TO_DECISION_MAXIMUM_LAG_TICKS;
  return otis_monotonic_us_extension_project_nearest(
      &timer_extension, raw_ticks, timer_extension.capture_session,
      kMaximumProjectionUs, extended_ticks);
}

bool otis_frequency_regulation_live_project_setup_monotonic_us(
    uint64_t raw_ticks, uint32_t capture_session, uint64_t *extended_ticks) {
  constexpr uint64_t kMonotonicUs32Modulus =
      OTIS_RP2040_MONOTONIC_US32_MODULUS;
  if (extended_ticks == nullptr || capture_session == 0u) return false;
  const uint64_t normalized_raw_ticks = raw_ticks % kMonotonicUs32Modulus;
  if (!timer_extension.available) {
    *extended_ticks = normalized_raw_ticks;
    return true;
  }
  return otis_monotonic_us_extension_project_nearest(
      &timer_extension, normalized_raw_ticks, capture_session,
      60ull * 1000000ull, extended_ticks);
}

void otis_frequency_regulation_live_service_transport(void) {
  return;
}

bool otis_frequency_regulation_live_transport_busy(void) {
  return false;
}

bool otis_frequency_regulation_live_transport_pending(void) {
  return false;
}

void otis_frequency_regulation_live_emit_status(OtisStatusEmitContext *context) {
  otis_status_emit(context, "frequency_regulation", "estimator_method",
                   kEstimatorMethod, OTIS_SEVERITY_INFO,
                   OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  otis_status_emit(context, "frequency_regulation", "policy_hash", kPolicyHash,
                   OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  otis_status_emit(context, "frequency_regulation", "plant_model_hash",
                   kPlantModelHash, OTIS_SEVERITY_INFO,
                   OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  otis_status_emit(context, "frequency_regulation", "control_ready", "false",
                   OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  otis_status_emit(context, "frequency_regulation", "actuation_enabled", "false",
                   OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  otis_status_emit(context, "frequency_regulation", "actuation_authorized", "false",
                   OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  otis_status_emit(context, "frequency_regulation", "actionable", "false",
                   OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  char value[16];
  snprintf(value, sizeof(value), "%ld",
           static_cast<long>(kActiveLiveUpdateCodes));
  otis_status_emit(context, "frequency_regulation", "active_live_update_codes", value,
                   OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  const uint32_t dropped =
      __atomic_load_n(&dropped_frames, __ATOMIC_ACQUIRE);
  snprintf(value, sizeof(value), "%lu", static_cast<unsigned long>(dropped));
  otis_status_emit(context, "frequency_regulation", "telemetry_dropped_frames", value,
                   dropped == 0u ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
                   dropped == 0u ? OTIS_FLAG_NONE
                                  : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  uint32_t queue_high_water = queue.high_water();
  OtisDualCoreQueueStats queue_stats = {};
  otis_dual_core_get_stats(&queue_stats);
  queue_high_water = queue_stats.evidence_high_water;
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(queue_high_water));
  otis_status_emit(context, "frequency_regulation", "queue_high_water", value,
                   OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
}
