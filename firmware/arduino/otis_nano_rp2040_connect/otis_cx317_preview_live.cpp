#include "otis_cx317_preview_live.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "otis_config.h"
#include "otis_cx317_active_live.h"
#include "otis_cx317_i_only_engine.h"
#include "otis_cx321_plant_sign.h"
#include "otis_cx317_snapshot_estimator.h"
#include "otis_decimal_format.h"
#include "otis_dual_core_partition.h"
#include "otis_phase_preview_live.h"
#include "otis_protocol.h"
#include "otis_spsc_queue.h"
#include "otis_timer0_extension.h"
#include "otis_transport_serial.h"

namespace {

constexpr char kEstimatorMethod[] = "PPS_CUMULATIVE_SNAPSHOT_SPAN_V1";
#if OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_REHEARSAL
constexpr char kSelectedEstimatorVersion[] =
    "cx317_rehearsal_selected_120s_nonoverlap_v1";
constexpr char kSelectedEstimatorReference[] = "selected120rehearsal";
constexpr char kSelectedEstimatorHash[] =
    "54173f493cb7dc459e57e7695d98b518a2616ded914898647f459b2325c94977";
constexpr char kPolicyId[] = "CX317_STAGE7_HIL_REHEARSAL_V1";
constexpr char kPolicyHash[] =
    "d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf";
#elif OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW || \
    OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW
constexpr char kSelectedEstimatorVersion[] =
    "cx317_selected_600s_nonoverlap_v1";
constexpr char kSelectedEstimatorReference[] = "selected600";
constexpr char kSelectedEstimatorHash[] =
    "5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c";
constexpr char kPolicyId[] =
    "CX319_STABILIZED_TIGHT_DEADBAND_FREQUENCY_ONLY_V1";
constexpr char kPolicyHash[] =
    "352daed21b3063c7d58dd8b266f3639f3cbed2500ff59fd2c530243727a5bb3a";
#elif OTIS_ENABLE_CX318_STAGE5_PREVIEW
constexpr char kSelectedEstimatorVersion[] =
    "cx317_selected_600s_nonoverlap_v1";
constexpr char kSelectedEstimatorReference[] = "selected600";
constexpr char kSelectedEstimatorHash[] =
    "5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c";
constexpr char kPolicyId[] = "CX318_STAGE5_TIGHT_ACTIVE_FREQUENCY_ONLY_V1";
constexpr char kPolicyHash[] =
    "a0dbe59f1b22fda35c1b760b21a03ab906ef683955368db2eeccba092d0cbbfd";
#else
constexpr char kSelectedEstimatorVersion[] =
    "cx317_selected_600s_nonoverlap_v1";
constexpr char kSelectedEstimatorReference[] = "selected600";
constexpr char kSelectedEstimatorHash[] =
    "5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c";
constexpr char kPolicyId[] = "CX317_POST_CAMPAIGN_FREQUENCY_CONTROL_POLICY_V1";
constexpr char kPolicyHash[] =
    "bd1c8c2fef6239740733316cdfc4aab34ffe14f65e6ece5f76b965d21c42cc0f";
#endif
constexpr char kPlantModelId[] = "cx317_pps_gated_bench";
constexpr char kPlantModelHash[] =
    "86c7acd3e22d206b1806c0ee2723b4f9051442d9624f7339982122c6caeaa0b2";
constexpr char kTimeDomain[] = "rp2040_timer0";
constexpr double kNominalFrequencyHz = 10000000.0;
constexpr double kNominalGainHzPerCode = 0.00017072602587382669;
static_assert(kNominalGainHzPerCode > 0.0,
              "the selected plant gain must remain positive");
// Deterministic wire representation of the exact selected gain above.
constexpr char kNominalGainHzPerCodeText[] = "0.000170726025874";
constexpr uint32_t kStartupWarmupS = OTIS_CX317_STARTUP_WARMUP_S;
constexpr uint32_t kSettlingExclusionS = OTIS_CX317_SETTLING_EXCLUSION_S;
#if OTIS_ENABLE_EXACT_POST_APPLICATION_SETTLING
constexpr uint64_t kCaptureTicksPerSecond = 16000000ull;
#endif
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

OtisCx317SnapshotEstimator estimator;
OtisCx317IOnlyEngine controller;
OtisSpscQueue<Frame, kQueueDepth> queue;
#if OTIS_ENABLE_DUAL_CORE_PARTITION
// Core 1 is the sole producer for this module and these calls are sequential,
// not re-entrant. Keep both complete-frame buffers out of its bounded stack.
// enqueue() copies formatter_scratch synchronously before another formatter
// can run, so the two buffers cannot alias live data.
char formatter_scratch[kFrameCapacity] = {};
OtisEvidenceFrameMessage evidence_frame_scratch = {};
#endif
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
bool recovery_requested = false;
#if OTIS_ENABLE_ACTIVE_TIMER0_EXTENSION
OtisTimer0Extension timer_extension = {};
uint64_t previous_boundary_extended_ticks = 0u;
uint32_t previous_boundary_session = 0u;
bool previous_boundary_available = false;
#endif
#if OTIS_ENABLE_EXACT_POST_APPLICATION_SETTLING
uint64_t exact_settling_deadline_ticks = 0u;
uint32_t exact_settling_capture_session = 0u;
bool exact_settling_deadline_available = false;
#endif
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
OtisCx321PlantSignAccumulator plant_sign_accumulator = {};
bool latest_natural_tight_inside = false;
#endif

bool enqueue(const char *data, size_t length);

#if OTIS_ENABLE_TIGHT_DEADBAND_OBSERVATION
bool emit_tight_deadband(const OtisCx317PreviewDecision &decision,
                         uint32_t source_estimate_seq,
                         uint64_t timestamp_ticks, uint64_t capture_session,
                         uint64_t dac_epoch,
                         int64_t accumulated_edge_error_counts) {
  if (!decision.tight_deadband_decision_available) return false;
  const OtisIntegerCountDeadbandTightDeadbandDecision &tight =
      decision.tight_deadband;
  const bool state_transition = tight.state_before != tight.state_after;
  const bool historical_v2_inside =
      tight.absolute_edge_error_counts_available &&
      tight.absolute_edge_error_counts <= 3u;
  const bool symmetric_two_count_inside =
      tight.absolute_edge_error_counts_available &&
      tight.absolute_edge_error_counts <= 2u;
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  char *frame = formatter_scratch;
  constexpr size_t frame_capacity = sizeof(formatter_scratch);
#else
  char frame[kFrameCapacity];
  constexpr size_t frame_capacity = sizeof(frame);
#endif
  const int used = snprintf(
      frame, frame_capacity,
      "TDB,1,%lu,est:cx317:%s:%06lu,%llu,%s,%llu,%llu,%lld,%llu,%s,%s,%u,%u,%s,%s,%s,%s,%s,%s,%s,%s,false,false,false,%s\r\n",
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
      historical_v2_inside ? "true" : "false",
      symmetric_two_count_inside ? "true" : "false", tight.policy_id,
      kPolicyHash,
      otis_integer_count_tight_deadband_reason_name(tight.reason));
  return used > 0 && static_cast<size_t>(used) < frame_capacity &&
         enqueue(frame, static_cast<size_t>(used));
}
#endif

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
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  evidence_frame_scratch.sequence = evidence_frame_sequence + 1u;
  evidence_frame_scratch.length = static_cast<uint16_t>(length);
  memcpy(evidence_frame_scratch.data, data, length);
  evidence_frame_scratch.data[length] = '\0';
  if (otis_dual_core_publish_evidence(&evidence_frame_scratch)) {
    evidence_frame_sequence = evidence_frame_scratch.sequence;
    return true;
  }
#else
  Frame frame = {};
  memcpy(frame.data, data, length);
  frame.data[length] = '\0';
  frame.length = static_cast<uint16_t>(length);
  frame.sent = 0u;
  if (queue.try_push(frame)) return true;
#endif
  uint32_t observed = __atomic_load_n(&dropped_frames, __ATOMIC_RELAXED);
  while (observed != UINT32_MAX &&
         !__atomic_compare_exchange_n(&dropped_frames, &observed,
                                      observed + 1u, false,
                                      __ATOMIC_RELAXED,
                                      __ATOMIC_RELAXED)) {
  }
  return false;
}

bool code_context_valid(const OtisCx317StaticCodeState *code) {
  return code != nullptr && code->available && code->requested_applied_match &&
         code->i2c_ok && code->applied_code >= 0xA800u &&
         code->applied_code <= 0xAB00u;
}

bool temperature_telemetry_valid(void) {
  return temperature_available && isfinite(temperature_c);
}

OtisCx317PreviewInput controller_input(
    uint32_t uptime_s, double error_hz, bool frequency_available,
    bool reference_valid, bool estimator_valid, bool count_valid,
    const OtisCx317StaticCodeState *code) {
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
      code_context_valid(code),
      code_present && code->requested_applied_match,
      code != nullptr && code->i2c_ok,
      temperature_available,
      false,
      false,
      false,
  };
}

const char *model_reason(const OtisCx317StaticCodeState *code) {
  if (code == nullptr || !code->available) return "static_dac_code_unavailable";
  if (!code->requested_applied_match) return "requested_applied_mismatch";
  if (!code->i2c_ok) return "i2c_failure";
  if (code->applied_code < 0xA800u || code->applied_code > 0xAB00u)
    return "current_code_outside_characterized_range";
  return "model_applicable_observe_only";
}

void emit_estimate(bool selected, const OtisCx317SpanEstimate &span,
                   const OtisCx317StaticCodeState *code,
                   uint64_t timestamp_ticks) {
  const uint32_t seq = estimate_seq++;
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  otis_dual_core_note_timing_estimate(seq);
  otis_dual_core_note_timing_progress(
      OtisTimingProgressPhase::Cx317EstimatePrepare, timestamp_ticks);
#endif
  const double frequency =
      selected ? span.selected_frequency_hz : span.diagnostic_frequency_hz;
  const uint32_t first = selected ? span.selected_first_sequence
                                  : span.diagnostic_first_sequence;
  const uint32_t samples = selected ? OTIS_CX317_SELECTED_SPAN_INTERVALS
                                    : OTIS_CX317_DIAGNOSTIC_SPAN_INTERVALS;
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
    return;
  }
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  char *frame = formatter_scratch;
  constexpr size_t frame_capacity = sizeof(formatter_scratch);
#else
  char frame[kFrameCapacity];
  constexpr size_t frame_capacity = sizeof(frame);
#endif
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  otis_dual_core_note_timing_progress(
      OtisTimingProgressPhase::Cx317EstimateFormat, timestamp_ticks);
#endif
  int used = snprintf(
      frame, frame_capacity,
      "EST,2,%lu,est:cx317:%s:%06lu,%llu,%s,%lu,live:CNT:%lu,%lu,%lu,"
      "live:STS:pps_gate,live:DAC:%lu,firmware_config:%s,%s,%s,"
      "valid,contiguous_snapshot_span,valid,0,true,valid,0,true,healthy,"
      "diagnostic_healthy,%s,%lu,unavailable,%s,%s,,unavailable,"
      "counter_aperture_uncertainty_unavailable;reference_uncertainty_unavailable;calibration_uncertainty_unavailable,"
      ",,,,,,,,not_combined_missing_components,unavailable:combined_uncertainty,false,,%s,%s\r\n",
      static_cast<unsigned long>(seq),
      selected ? kSelectedEstimatorReference : "diagnostic60",
      static_cast<unsigned long>(seq),
      static_cast<unsigned long long>(timestamp_ticks), kTimeDomain,
      static_cast<unsigned long>(span.last_sequence),
      static_cast<unsigned long>(span.last_sequence),
      static_cast<unsigned long>(first),
      static_cast<unsigned long>(span.last_sequence),
      static_cast<unsigned long>(current_dac_epoch), OTIS_FIRMWARE_CONFIG_ID,
      selected ? kSelectedEstimatorVersion
               : "cx317_diagnostic_60s_overlap_v1",
      kSelectedEstimatorHash, frequency_text,
      static_cast<unsigned long>(samples), frequency_text,
      frequency_error_text,
      selected && applicable ? "true" : "false",
      selected ? (applicable ? "preview_input_observe_only"
                             : model_reason(code))
               : "diagnostic_non_authoritative");
  if (used > 0 && static_cast<size_t>(used) < frame_capacity)
    enqueue(frame, static_cast<size_t>(used));
  else {
    uint32_t observed = __atomic_load_n(&dropped_frames, __ATOMIC_RELAXED);
    if (observed != UINT32_MAX)
      __atomic_store_n(&dropped_frames, observed + 1u, __ATOMIC_RELAXED);
  }
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  otis_dual_core_note_timing_progress(
      OtisTimingProgressPhase::Cx317EstimatePublish, timestamp_ticks);
#endif
}

void emit_control(const OtisCx317PreviewDecision &decision,
                  const OtisCx317StaticCodeState *code,
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
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  char *frame = formatter_scratch;
  constexpr size_t frame_capacity = sizeof(formatter_scratch);
#else
  char frame[kFrameCapacity];
  constexpr size_t frame_capacity = sizeof(frame);
#endif
  const uint32_t seq = control_seq++;
  const bool applicable = code_context_valid(code);
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  if (decision.state_transition && otis_dual_core_timing_owner_active()) {
    OtisCriticalRecordMessage transition = {};
    transition.kind = OtisCriticalMessageKind::StateTransition;
    transition.sequence = seq;
    transition.timestamp_ticks = timestamp_ticks;
    snprintf(transition.component, sizeof(transition.component), "%s",
             "cx317_preview");
    snprintf(transition.reason, sizeof(transition.reason), "%s",
             decision.reason);
    otis_dual_core_publish_critical(&transition);
  }
#endif
  int used = snprintf(
      frame, frame_capacity,
      "CTL,1,%lu,ctl:cx317:%06lu,%llu,%s,est:cx317:%s:%06lu,"
      "profile:plant_models/cx317_pps_gated_v2.json,%s,2,%s,%s,%s,%s,%s,%s,%s,"
      "%s,%s,healthy,%s,%s,%u,%s,%s,%s,%s,%s,%s,%s,%s,true,false,false,%s\r\n",
      static_cast<unsigned long>(seq), static_cast<unsigned long>(seq),
      static_cast<unsigned long long>(timestamp_ticks), kTimeDomain,
      kSelectedEstimatorReference,
      static_cast<unsigned long>(source_estimate_seq), kPlantModelId,
      kPlantModelHash, kPolicyId, kPolicyHash,
      otis_cx317_preview_state_name(decision.state),
      otis_cx317_preview_state_name(decision.previous_state),
      decision.state_transition ? "true" : "false", decision.reason,
      decision.preview_available ? "true" : "false",
      decision.preview_available ? "preview_available_observe_only"
                                 : decision.reason,
      applicable ? "applicable" : "not_applicable", model_reason(code),
      decision.current_code, frequency_error, kNominalGainHzPerCodeText,
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

bool otis_cx317_preview_live_begin(uint32_t startup_uptime_s) {
#if OTIS_ENABLE_CX317_I_ONLY_PREVIEW
  otis_cx317_snapshot_estimator_init(&estimator);
  otis_cx317_i_only_engine_init(&controller, startup_uptime_s);
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
  recovery_requested = false;
#if OTIS_ENABLE_ACTIVE_TIMER0_EXTENSION
  otis_timer0_extension_init(&timer_extension);
  previous_boundary_extended_ticks = 0u;
  previous_boundary_session = 0u;
  previous_boundary_available = false;
#endif
#if OTIS_ENABLE_EXACT_POST_APPLICATION_SETTLING
  exact_settling_deadline_ticks = 0u;
  exact_settling_capture_session = 0u;
  exact_settling_deadline_available = false;
#endif
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
  plant_sign_accumulator = {};
  latest_natural_tight_inside = false;
#endif
  return true;
#else
  (void)startup_uptime_s;
  return true;
#endif
}

void otis_cx317_preview_live_emit_headers(void) {
#if OTIS_ENABLE_CX317_I_ONLY_PREVIEW
  otis_transport_write_cstr(
      "record_type,schema_version,estimate_seq,estimate_id,estimator_timestamp_ticks,time_domain,source_count_seq,source_count_ref,source_reference_first_seq,source_reference_last_seq,source_status_refs,source_dac_ref,manifest_ref,estimator_version,config_hash,observation_validity,observation_reason_codes,reference_validity,reference_age_s,reference_continuity,count_validity,count_age_s,count_continuity,diagnostic_health,diagnostic_reason_codes,frequency_observation_hz,accepted_sample_count,estimator_confidence,frequency_estimate_hz,frequency_error_hz,dispersion_hz,uncertainty_status,uncertainty_reason_codes,count_quantization_standard_uncertainty_hz,counter_aperture_standard_uncertainty_hz,reference_standard_uncertainty_hz,calibration_standard_uncertainty_hz,model_standard_uncertainty_hz,combined_standard_uncertainty_hz,coverage_factor,expanded_uncertainty_hz,correlation_policy,uncertainty_model_ref,drift_enabled,drift_hz_per_s,preview_eligibility,eligibility_reason_codes\r\n");
  otis_transport_write_cstr(
      "record_type,schema_version,control_seq,decision_id,decision_timestamp_ticks,time_domain,est_input_ref,plant_model_ref,plant_model_id,plant_model_version,plant_model_hash,policy_version,config_hash,control_state,previous_control_state,state_transition,transition_reason_code,preview_eligibility,eligibility_reason_codes,diagnostic_health,model_applicability,model_reason_codes,current_dac_code,frequency_error_hz,hz_per_code,raw_delta_codes,limited_delta_codes,proposed_dac_code,step_limited,range_clamped,preview_available,preview_only,actuation_authorized,actionable,decision_reason_code\r\n");
#if OTIS_ENABLE_TIGHT_DEADBAND_OBSERVATION
  otis_transport_write_cstr(
      "record_type,schema_version,decision_sequence,estimate_id,decision_timestamp_ticks,time_domain,capture_session,dac_epoch,integer_edge_error_counts,absolute_edge_error_counts,state_before,state_after,entry_counter,release_counter,transition,frequency_controller_eligible,requalified,requalification_reason,historical_v2_inside,symmetric_two_count_inside,policy_id,policy_sha256,actionable,actuation_authorized,authorization_consumed,reason_codes\r\n");
#endif
#endif
}

void otis_cx317_preview_live_on_temperature(bool available,
                                            float value_c,
                                            uint32_t uptime_s) {
#if OTIS_ENABLE_CX317_I_ONLY_PREVIEW
  (void)uptime_s;
  temperature_available = available && isfinite(value_c);
  temperature_c = static_cast<double>(value_c);
#else
  (void)available;
  (void)value_c;
  (void)uptime_s;
#endif
}

void otis_cx317_preview_live_on_dac_applied(uint16_t applied_code,
                                           uint32_t uptime_s) {
#if OTIS_ENABLE_CX317_I_ONLY_PREVIEW
  (void)applied_code;
  otis_cx317_snapshot_estimator_reset(&estimator);
  selected_estimator_valid = false;
  selected_model_applicable = false;
  settling_until_s = uptime_s + kSettlingExclusionS;
#if OTIS_ENABLE_EXACT_POST_APPLICATION_SETTLING
  exact_settling_deadline_ticks = 0u;
  exact_settling_capture_session = 0u;
  exact_settling_deadline_available = false;
#endif
  otis_cx317_i_only_engine_note_dac_epoch(&controller, uptime_s);
#else
  (void)applied_code;
  (void)uptime_s;
#endif
}

void otis_cx317_preview_live_on_dac_applied_epoch(uint16_t applied_code,
                                                 uint32_t dac_epoch,
                                                 uint32_t uptime_s) {
#if OTIS_ENABLE_CX317_I_ONLY_PREVIEW
  current_dac_epoch = dac_epoch;
  current_applied_code = applied_code;
  otis_cx317_preview_live_on_dac_applied(applied_code, uptime_s);
#else
  (void)applied_code;
  (void)dac_epoch;
  (void)uptime_s;
#endif
}

void otis_cx317_preview_live_on_dac_applied_epoch_exact(
    uint16_t applied_code, uint32_t dac_epoch, uint32_t uptime_s,
    uint64_t application_ticks, uint32_t capture_session) {
  otis_cx317_preview_live_on_dac_applied_epoch(applied_code, dac_epoch,
                                               uptime_s);
#if OTIS_ENABLE_EXACT_POST_APPLICATION_SETTLING
  constexpr uint64_t kSettlingExclusionTicks =
      static_cast<uint64_t>(kSettlingExclusionS) * kCaptureTicksPerSecond;
  if (application_ticks != 0u && capture_session != 0u &&
      application_ticks <= UINT64_MAX - kSettlingExclusionTicks) {
    exact_settling_deadline_ticks =
        application_ticks + kSettlingExclusionTicks;
    exact_settling_capture_session = capture_session;
    exact_settling_deadline_available = true;
  }
#endif
#if OTIS_ENABLE_ACTIVE_TIMER0_EXTENSION
  if (!timer_extension.available ||
      timer_extension.capture_session != capture_session)
    otis_timer0_extension_seed(
        &timer_extension, application_ticks, capture_session);
#endif
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
  otis_cx321_plant_sign_accumulator_init(
      &plant_sign_accumulator, application_ticks, dac_epoch, capture_session);
#else
  (void)application_ticks;
  (void)capture_session;
#endif
}

bool otis_cx317_preview_live_applied_epoch_exact(uint16_t applied_code,
                                                 uint32_t dac_epoch) {
#if OTIS_ENABLE_CX317_I_ONLY_PREVIEW
  return initialized && current_applied_code == applied_code &&
         current_dac_epoch == dac_epoch;
#else
  (void)applied_code;
  (void)dac_epoch;
  return false;
#endif
}

void otis_cx317_preview_live_on_boundary(
    const OtisPpsCountBoundaryObservation *observation,
    uint32_t interval_count, bool interval_valid, uint32_t uptime_s,
    const OtisCx317StaticCodeState *static_code,
    OtisCx317ActiveLiveOutcome *active_outcome) {
  if (active_outcome != nullptr) *active_outcome = {};
#if OTIS_ENABLE_CX317_I_ONLY_PREVIEW
  if (!initialized || observation == nullptr) return;
#if OTIS_ENABLE_ACTIVE_TIMER0_EXTENSION
  uint64_t current_boundary_extended_ticks = observation->pps_timestamp_ticks;
  const bool boundary_extended = otis_timer0_extension_advance_boundary(
      &timer_extension, observation->pps_timestamp_ticks,
      observation->session, &current_boundary_extended_ticks);
  const bool interval_opening_exact =
      boundary_extended && previous_boundary_available &&
      previous_boundary_session == observation->session;
  const uint64_t interval_opening_extended_ticks =
      previous_boundary_extended_ticks;
#endif
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
  OtisCx321PlantSignEstimate plant_estimate = {};
  bool plant_estimate_ready = false;
  bool plant_estimate_delivered = false;
  if (previous_boundary_available &&
      previous_boundary_session == observation->session &&
      boundary_extended) {
    plant_estimate_ready = otis_cx321_plant_sign_accumulator_on_interval(
        &plant_sign_accumulator, previous_boundary_extended_ticks,
        current_boundary_extended_ticks, observation->sequence,
        interval_count, current_dac_epoch, observation->session,
        interval_valid, &plant_estimate);
  } else {
    otis_cx321_plant_sign_accumulator_invalidate(&plant_sign_accumulator);
  }
#endif
#if OTIS_ENABLE_ACTIVE_TIMER0_EXTENSION
  previous_boundary_extended_ticks = current_boundary_extended_ticks;
  previous_boundary_session = observation->session;
  previous_boundary_available = true;
#endif
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
  const auto deliver_plant_estimate = [&]() {
    if (plant_estimate_ready && !plant_estimate_delivered) {
      otis_cx317_active_live_on_plant_sign_estimate(
          &plant_estimate, current_applied_code, latest_natural_tight_inside,
          current_boundary_extended_ticks, uptime_s, active_outcome);
      plant_estimate_delivered = true;
    }
  };
#endif
  const uint32_t warmup_complete_s = startup_s + kStartupWarmupS;
  if (!warmup_boundary_seen && uptime_s >= warmup_complete_s) {
    warmup_boundary_seen = true;
    otis_cx317_snapshot_estimator_reset(&estimator);
    selected_estimator_valid = false;
    selected_model_applicable = false;
    if (settling_until_s <= warmup_complete_s)
      otis_cx317_i_only_engine_init(&controller, startup_s);
    OtisCx317PreviewInput input = controller_input(
        uptime_s, 0.0, false, interval_valid, interval_valid, interval_valid,
        static_code);
    OtisCx317PreviewDecision decision;
    otis_cx317_i_only_engine_evaluate(&controller, &input, &decision);
    emit_control(decision, static_code, observation->pps_timestamp_ticks,
                 estimate_seq);
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
    deliver_plant_estimate();
#endif
    return;
  }
  // A boundary stamped exactly at settling_until_s closes the oscillator
  // interval that began one second earlier, so it still straddles the
  // excluded settling window.  Admit only boundaries strictly after it; the
  // 600th accepted interval then closes after the full 900 + 600 seconds.
  bool settling_interval_excluded = uptime_s <= settling_until_s;
#if OTIS_ENABLE_EXACT_POST_APPLICATION_SETTLING
  if (exact_settling_deadline_available) {
    settling_interval_excluded =
        !interval_opening_exact ||
        observation->session != exact_settling_capture_session ||
        interval_opening_extended_ticks < exact_settling_deadline_ticks;
    if (!settling_interval_excluded)
      exact_settling_deadline_available = false;
  }
#endif
  if (uptime_s < warmup_complete_s || settling_interval_excluded) {
    otis_cx317_snapshot_estimator_reset(&estimator);
    selected_estimator_valid = false;
    selected_model_applicable = false;
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
    deliver_plant_estimate();
#endif
    return;
  }
  if (recovery_requested && interval_valid) {
    otis_cx317_snapshot_estimator_reset(&estimator);
    selected_estimator_valid = false;
    selected_model_applicable = false;
    OtisCx317PreviewInput input = controller_input(
        uptime_s, 0.0, false, true, true, true, static_code);
    input.recovery_requested = true;
    OtisCx317PreviewDecision decision;
    otis_cx317_i_only_engine_evaluate(&controller, &input, &decision);
    recovery_requested = false;
    emit_control(decision, static_code, observation->pps_timestamp_ticks,
                 estimate_seq);
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
    deliver_plant_estimate();
#endif
    return;
  }
  OtisCx317SpanEstimate span;
  otis_cx317_snapshot_estimator_ingest(
      &estimator, observation->sequence, interval_count, interval_valid, &span);
  if (!interval_valid) {
    selected_estimator_valid = false;
    selected_model_applicable = false;
    OtisCx317PreviewInput input = controller_input(
        uptime_s, 0.0, false, false, false, false, static_code);
    OtisCx317PreviewDecision decision;
    otis_cx317_i_only_engine_evaluate(&controller, &input, &decision);
    emit_control(decision, static_code, observation->pps_timestamp_ticks,
                 estimate_seq);
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
    deliver_plant_estimate();
#endif
    return;
  }
  if (span.diagnostic_available)
    emit_estimate(false, span, static_code, observation->pps_timestamp_ticks);
  if (span.selected_available) {
    const uint32_t selected_estimate_seq = estimate_seq;
    emit_estimate(true, span, static_code, observation->pps_timestamp_ticks);
    const bool applicable = code_context_valid(static_code);
    OtisCx317PreviewInput input = controller_input(
        uptime_s, span.selected_frequency_hz - kNominalFrequencyHz, true,
        true, true, true, static_code);
    input.model_applicable = applicable;
#if OTIS_ENABLE_TIGHT_DEADBAND_OBSERVATION
    input.accumulated_edge_error_counts =
        span.selected_accumulated_edge_error_counts;
    input.capture_session = observation->session;
    input.dac_epoch_identity = current_dac_epoch;
    input.accumulated_edge_error_counts_available = true;
#endif
    OtisCx317PreviewDecision decision;
    otis_cx317_i_only_engine_evaluate(&controller, &input, &decision);
    selected_estimator_valid = true;
    selected_model_applicable = applicable;
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
    latest_natural_tight_inside =
        decision.tight_deadband_decision_available &&
        decision.tight_deadband.state_after ==
            OTIS_INTEGER_COUNT_DEADBAND_TIGHT_INSIDE;
#endif
#if OTIS_ENABLE_TIGHT_DEADBAND_OBSERVATION
    const bool tight_evidence_queued = emit_tight_deadband(
        decision, selected_estimate_seq, observation->pps_timestamp_ticks,
        observation->session, current_dac_epoch,
        span.selected_accumulated_edge_error_counts);
#endif
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
    // A coincident 1,500/600 close must use this boundary's freshly evaluated
    // natural tight state before the identification gate can decide.
    deliver_plant_estimate();
#endif
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
    OtisCx317ActiveLiveDecision active_decision = {
        control_seq,
        span.selected_first_sequence,
        span.last_sequence,
        uptime_s,
        decision.current_code,
        decision.limited_delta_codes,
        decision.proposed_code,
        decision.frequency_error_hz,
        true,
        applicable,
#if OTIS_ENABLE_TIGHT_DEADBAND_OBSERVATION
        decision.preview_available && tight_evidence_queued &&
            decision.tight_deadband_decision_available &&
            decision.tight_deadband.frequency_controller_eligible,
#else
        decision.preview_available,
#endif
        decision.preview_available,
    };
#if OTIS_ENABLE_CX320_ACTIVE_HYBRID
    OtisPhasePreviewActiveSnapshot phase_snapshot = {};
    const bool phase_snapshot_available =
        otis_phase_preview_live_get_active_snapshot(&phase_snapshot);
    active_decision.capture_session = observation->session;
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
        phase_snapshot_available && phase_snapshot.phase_continuous;
    active_decision.phase_current =
        phase_snapshot_available && phase_snapshot.phase_current;
    active_decision.phase_step_detected =
        !phase_snapshot_available || phase_snapshot.phase_step_detected;
    active_decision.phase_recorder_published =
        phase_snapshot_available && phase_snapshot.recorder_published;
#endif
    OtisCx317ActiveLiveOutcome local_active_outcome;
#if OTIS_ENABLE_ACTIVE_TIMER0_EXTENSION
    otis_cx317_active_live_on_decision_at_ticks(
        &active_decision, current_boundary_extended_ticks,
        &local_active_outcome);
#else
    otis_cx317_active_live_on_decision(&active_decision,
                                       &local_active_outcome);
#endif
    if (active_outcome != nullptr &&
        !(active_outcome->request_created || active_outcome->faulted ||
          active_outcome->response_recorded))
      *active_outcome = local_active_outcome;
#endif
    emit_control(decision, static_code, observation->pps_timestamp_ticks,
                 selected_estimate_seq);
  }
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
  deliver_plant_estimate();
#endif
#else
  (void)observation;
  (void)interval_count;
  (void)interval_valid;
  (void)uptime_s;
  (void)static_code;
  (void)active_outcome;
#endif
}

void otis_cx317_preview_live_on_capture_fault(
    const char *reason, uint32_t uptime_s,
    const OtisCx317StaticCodeState *static_code) {
#if OTIS_ENABLE_CX317_I_ONLY_PREVIEW
  (void)reason;
  otis_cx317_snapshot_estimator_reset(&estimator);
  selected_estimator_valid = false;
  selected_model_applicable = false;
  OtisCx317PreviewInput input = controller_input(
      uptime_s, 0.0, false, false, false, false, static_code);
  OtisCx317PreviewDecision decision;
  otis_cx317_i_only_engine_evaluate(&controller, &input, &decision);
  emit_control(decision, static_code, 0u, estimate_seq);
#else
  (void)reason;
  (void)uptime_s;
  (void)static_code;
#endif
}

bool otis_cx317_preview_live_request_recovery(void) {
#if OTIS_ENABLE_CX317_I_ONLY_PREVIEW
  if (!initialized || controller.state != OtisCx317PreviewState::Fault)
    return false;
  recovery_requested = true;
  return true;
#else
  return false;
#endif
}

void otis_cx317_preview_live_get_authority_state(
    OtisCx317PreviewAuthorityState *state) {
  if (state == nullptr) return;
#if OTIS_ENABLE_CX317_I_ONLY_PREVIEW
  state->estimator_valid = selected_estimator_valid;
  state->model_applicable = selected_model_applicable;
  state->temperature_valid = temperature_telemetry_valid();
  state->selected_interval_count = estimator.selected_count;
#else
  *state = {};
#endif
}

uint16_t otis_cx317_preview_live_plant_sign_accepted_intervals(void) {
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
  return plant_sign_accumulator.configured
             ? plant_sign_accumulator.accepted_intervals
             : 0u;
#else
  return 0u;
#endif
}

bool otis_cx317_preview_live_extend_timer0_ticks(
    uint64_t raw_ticks, uint64_t *extended_ticks) {
#if OTIS_ENABLE_ACTIVE_TIMER0_EXTENSION
  constexpr uint64_t kMaximumProjectionTicks = 60ull * 16000000ull;
  return otis_timer0_extension_project_nearest(
      &timer_extension, raw_ticks, timer_extension.capture_session,
      kMaximumProjectionTicks, extended_ticks);
#else
  (void)raw_ticks;
  (void)extended_ticks;
  return false;
#endif
}

bool otis_cx317_preview_live_project_setup_timer0_ticks(
    uint64_t raw_ticks, uint32_t capture_session, uint64_t *extended_ticks) {
#if OTIS_ENABLE_ACTIVE_TIMER0_EXTENSION
  constexpr uint64_t kTimer0ModulusTicks = (1ull << 32) * 16ull;
  if (extended_ticks == nullptr || capture_session == 0u) return false;
  const uint64_t normalized_raw_ticks = raw_ticks % kTimer0ModulusTicks;
  if (!timer_extension.available) {
    *extended_ticks = normalized_raw_ticks;
    return true;
  }
  return otis_timer0_extension_project_nearest(
      &timer_extension, normalized_raw_ticks, capture_session,
      60ull * 16000000ull, extended_ticks);
#else
  (void)raw_ticks;
  (void)capture_session;
  (void)extended_ticks;
  return false;
#endif
}

void otis_cx317_preview_live_service_transport(void) {
#if OTIS_ENABLE_CX317_I_ONLY_PREVIEW
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  return;
#else
  if (!transport_frame_active) {
    if (!queue.try_pop(&transport_frame)) return;
    transport_frame_active = true;
  }
  size_t available = otis_transport_available_for_write();
  if (available == 0u) return;
  Frame &frame = transport_frame;
  size_t remaining = static_cast<size_t>(frame.length - frame.sent);
  size_t chunk = remaining < available ? remaining : available;
  if (chunk > kTransportChunkLimit) chunk = kTransportChunkLimit;
  size_t written = otis_transport_write_bytes(
      reinterpret_cast<const uint8_t *>(frame.data) + frame.sent, chunk);
  frame.sent = static_cast<uint16_t>(frame.sent + written);
  if (frame.sent == frame.length) {
    transport_frame_active = false;
    transport_frame = {};
  }
#endif
#endif
}

bool otis_cx317_preview_live_transport_busy(void) {
#if OTIS_ENABLE_CX317_I_ONLY_PREVIEW
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  return false;
#else
  return transport_frame_active && transport_frame.sent > 0u;
#endif
#else
  return false;
#endif
}

bool otis_cx317_preview_live_transport_pending(void) {
#if OTIS_ENABLE_CX317_I_ONLY_PREVIEW
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  return false;
#else
  return transport_frame_active || queue.depth() != 0u;
#endif
#else
  return false;
#endif
}

void otis_cx317_preview_live_emit_status(OtisStatusEmitContext *context) {
#if OTIS_ENABLE_CX317_I_ONLY_PREVIEW
  otis_status_emit(context, "cx317_preview", "estimator_method",
                   kEstimatorMethod, OTIS_SEVERITY_INFO,
                   OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(context, "cx317_preview", "policy_hash", kPolicyHash,
                   OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(context, "cx317_preview", "plant_model_hash",
                   kPlantModelHash, OTIS_SEVERITY_INFO,
                   OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(context, "cx317_preview", "control_ready", "false",
                   OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(context, "cx317_preview", "actuation_enabled", "false",
                   OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(context, "cx317_preview", "actuation_authorized", "false",
                   OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(context, "cx317_preview", "actionable", "false",
                   OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  char value[16];
  snprintf(value, sizeof(value), "%ld",
           static_cast<long>(kActiveLiveUpdateCodes));
  otis_status_emit(context, "cx317_preview", "active_live_update_codes", value,
                   OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  const uint32_t dropped =
      __atomic_load_n(&dropped_frames, __ATOMIC_ACQUIRE);
  snprintf(value, sizeof(value), "%lu", static_cast<unsigned long>(dropped));
  otis_status_emit(context, "cx317_preview", "telemetry_dropped_frames", value,
                   dropped == 0u ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
                   dropped == 0u ? OTIS_FLAG_NONE
                                  : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  uint32_t queue_high_water = queue.high_water();
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  OtisDualCoreQueueStats queue_stats = {};
  otis_dual_core_get_stats(&queue_stats);
  queue_high_water = queue_stats.evidence_high_water;
#endif
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(queue_high_water));
  otis_status_emit(context, "cx317_preview", "queue_high_water", value,
                   OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
#else
  (void)context;
#endif
}
