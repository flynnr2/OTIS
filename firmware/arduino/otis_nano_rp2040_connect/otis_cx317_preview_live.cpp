#include "otis_cx317_preview_live.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "otis_config.h"
#include "otis_cx317_active_live.h"
#include "otis_cx317_i_only_engine.h"
#include "otis_cx317_snapshot_estimator.h"
#include "otis_decimal_format.h"
#include "otis_dual_core_partition.h"
#include "otis_protocol.h"
#include "otis_spsc_queue.h"
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
#elif OTIS_ENABLE_CX318_STAGE5_PREVIEW
constexpr char kSelectedEstimatorVersion[] =
    "cx317_selected_600s_nonoverlap_v1";
constexpr char kSelectedEstimatorReference[] = "selected600";
constexpr char kSelectedEstimatorHash[] =
    "5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c";
constexpr char kPolicyId[] = "CX318_STAGE5_TIGHT_ACTIVE_FREQUENCY_ONLY_V1";
constexpr char kPolicyHash[] =
    "bd4738dd89266591f143fda1c243615c1e9933799d6d0f0c1f6101c8d8810c4f";
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
    "5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1";
constexpr char kTimeDomain[] = "rp2040_timer0";
constexpr double kNominalFrequencyHz = 10000000.0;
constexpr double kNominalGainHzPerCode = 0.00017072602587382669;
static_assert(kNominalGainHzPerCode > 0.0,
              "the selected plant gain must remain positive");
// Deterministic wire representation of the exact selected gain above.
constexpr char kNominalGainHzPerCodeText[] = "0.000170726025874";
constexpr uint32_t kStartupWarmupS = OTIS_CX317_STARTUP_WARMUP_S;
constexpr uint32_t kSettlingExclusionS = OTIS_CX317_SETTLING_EXCLUSION_S;
constexpr int32_t kActiveLiveUpdateCodes = 0;
constexpr uint8_t kQueueDepth = 4u;
constexpr size_t kFrameCapacity = 1536u;
constexpr size_t kTransportChunkLimit = 192u;

struct Frame {
  char data[kFrameCapacity];
  uint16_t length;
  uint16_t sent;
};

OtisCx317SnapshotEstimator estimator;
OtisCx317IOnlyEngine controller;
OtisSpscQueue<Frame, kQueueDepth> queue;
Frame transport_frame = {};
bool transport_frame_active = false;
uint32_t dropped_frames = 0u;
uint32_t evidence_frame_sequence = 0u;
uint32_t estimate_seq = 0u;
uint32_t control_seq = 0u;
uint32_t startup_s = 0u;
uint32_t settling_until_s = 0u;
uint32_t current_dac_epoch = 0u;
uint32_t tight_deadband_seq = 0u;
bool initialized = false;
bool warmup_boundary_seen = false;
bool temperature_available = false;
double temperature_c = 0.0;
bool selected_estimator_valid = false;
bool selected_model_applicable = false;
bool recovery_requested = false;

bool enqueue(const char *data, size_t length);

#if OTIS_ENABLE_CX318_STAGE5_PREVIEW
bool emit_tight_deadband(const OtisCx317PreviewDecision &decision,
                         uint32_t source_estimate_seq,
                         uint64_t timestamp_ticks, uint64_t capture_session,
                         uint64_t dac_epoch,
                         int64_t accumulated_edge_error_counts) {
  if (!decision.tight_deadband_decision_available) return false;
  const OtisCx318Stage5TightDeadbandDecision &tight =
      decision.tight_deadband;
  const bool state_transition = tight.state_before != tight.state_after;
  const bool historical_v2_inside =
      tight.absolute_edge_error_counts_available &&
      tight.absolute_edge_error_counts <= 3u;
  const bool symmetric_two_count_inside =
      tight.absolute_edge_error_counts_available &&
      tight.absolute_edge_error_counts <= 2u;
  char frame[kFrameCapacity];
  const int used = snprintf(
      frame, sizeof(frame),
      "TDB,1,%lu,est:cx317:%s:%06lu,%llu,%s,%llu,%llu,%lld,%llu,%s,%s,%u,%u,%s,%s,%s,%s,%s,%s,%s,%s,false,false,false,%s\r\n",
      static_cast<unsigned long>(tight_deadband_seq++),
      kSelectedEstimatorReference,
      static_cast<unsigned long>(source_estimate_seq),
      static_cast<unsigned long long>(timestamp_ticks), kTimeDomain,
      static_cast<unsigned long long>(capture_session),
      static_cast<unsigned long long>(dac_epoch),
      static_cast<long long>(accumulated_edge_error_counts),
      static_cast<unsigned long long>(tight.absolute_edge_error_counts),
      otis_cx318_stage5_tight_deadband_state_name(tight.state_before),
      otis_cx318_stage5_tight_deadband_state_name(tight.state_after),
      tight.entry_pending_count, tight.release_pending_count,
      state_transition ? "true" : "false",
      tight.frequency_controller_eligible ? "true" : "false",
      tight.requalified ? "true" : "false",
      tight.requalification_reason_available
          ? otis_cx318_stage5_tight_deadband_reason_name(
                tight.requalification_reason)
          : "",
      historical_v2_inside ? "true" : "false",
      symmetric_two_count_inside ? "true" : "false", tight.policy_id,
      kPolicyHash,
      otis_cx318_stage5_tight_deadband_reason_name(tight.reason));
  return used > 0 && static_cast<size_t>(used) < sizeof(frame) &&
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
  Frame frame = {};
  memcpy(frame.data, data, length);
  frame.data[length] = '\0';
  frame.length = static_cast<uint16_t>(length);
  frame.sent = 0u;
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  OtisEvidenceFrameMessage message = {};
  message.sequence = evidence_frame_sequence + 1u;
  message.length = frame.length;
  memcpy(message.data, frame.data, frame.length + 1u);
  if (otis_dual_core_publish_evidence(&message)) {
    evidence_frame_sequence = message.sequence;
    return true;
  }
#else
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
  char frame[kFrameCapacity];
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  otis_dual_core_note_timing_progress(
      OtisTimingProgressPhase::Cx317EstimateFormat, timestamp_ticks);
#endif
  int used = snprintf(
      frame, sizeof(frame),
      "EST,2,%lu,est:cx317:%s:%06lu,%llu,%s,%lu,live:CNT:%lu,%lu,%lu,"
      "live:STS:pps_gate,live:DAC:static,firmware_config:%s,%s,%s,"
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
      static_cast<unsigned long>(span.last_sequence), OTIS_FIRMWARE_CONFIG_ID,
      selected ? kSelectedEstimatorVersion
               : "cx317_diagnostic_60s_overlap_v1",
      kSelectedEstimatorHash, frequency_text,
      static_cast<unsigned long>(samples), frequency_text,
      frequency_error_text,
      selected && applicable ? "true" : "false",
      selected ? (applicable ? "preview_input_observe_only"
                             : model_reason(code))
               : "diagnostic_non_authoritative");
  if (used > 0 && static_cast<size_t>(used) < sizeof(frame))
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
  char frame[kFrameCapacity];
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
      frame, sizeof(frame),
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
  if (used > 0 && static_cast<size_t>(used) < sizeof(frame))
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
#if OTIS_ENABLE_CX318_STAGE5_PREVIEW
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
  otis_cx317_preview_live_on_dac_applied(applied_code, uptime_s);
#else
  (void)applied_code;
  (void)dac_epoch;
  (void)uptime_s;
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
    return;
  }
  if (uptime_s < warmup_complete_s || uptime_s < settling_until_s) {
    otis_cx317_snapshot_estimator_reset(&estimator);
    selected_estimator_valid = false;
    selected_model_applicable = false;
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
#if OTIS_ENABLE_CX318_STAGE5_PREVIEW
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
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
#if OTIS_ENABLE_CX318_STAGE5_PREVIEW
    const bool tight_evidence_queued = emit_tight_deadband(
        decision, selected_estimate_seq, observation->pps_timestamp_ticks,
        observation->session, current_dac_epoch,
        span.selected_accumulated_edge_error_counts);
#endif
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
#if OTIS_ENABLE_CX318_STAGE5_PREVIEW
        decision.preview_available && tight_evidence_queued &&
            decision.tight_deadband_decision_available &&
            decision.tight_deadband.frequency_controller_eligible,
#else
        decision.preview_available,
#endif
        decision.preview_available,
    };
    OtisCx317ActiveLiveOutcome local_active_outcome;
    otis_cx317_active_live_on_decision(&active_decision,
                                       &local_active_outcome);
    if (active_outcome != nullptr) *active_outcome = local_active_outcome;
#endif
    emit_control(decision, static_code, observation->pps_timestamp_ticks,
                 selected_estimate_seq);
  }
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
