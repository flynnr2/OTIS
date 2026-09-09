#include "otis_adaptive_hybrid_regulation_live.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "otis_config.h"
#include "otis_active_hybrid_decision_format.h"
#include "otis_active_hybrid_policy_engine.h"
#include "otis_regulation_actuator.h"
#include "otis_adaptive_hybrid_regulation.h"
#include "otis_adaptive_hybrid_maintenance_format.h"
#include "otis_adaptive_hybrid_maintenance_record.h"
#include "otis_decimal_format.h"
#include "otis_dependent_response_identity.h"
#include "otis_dual_core_partition.h"
#include "otis_frequency_regulation_live.h"
#include "otis_phase_preview_live.h"
#include "otis_protocol.h"
#include "otis_transport_serial.h"

namespace {

constexpr char kEstimatorHash[] = OTIS_BUILD_FREQUENCY_ESTIMATOR_SHA256;
constexpr char kModelHash[] = OTIS_BUILD_PLANT_MODEL_SHA256;
constexpr char kNumericalPolicyHash[] = OTIS_BUILD_ADAPTIVE_POLICY_SHA256;
constexpr char kActivePolicyHash[] = OTIS_BUILD_ADAPTIVE_POLICY_SHA256;
constexpr char kResponsePolicyHash[] = OTIS_BUILD_RESPONSE_POLICY_SHA256;
constexpr char kPhaseEstimatorHash[] = OTIS_BUILD_PHASE_ESTIMATOR_SHA256;
constexpr uint32_t kCaptureLeaseMaximumAgeS = 30u;
constexpr uint32_t kEvidenceAcknowledgementMaximumAgeS = 30u;
constexpr uint64_t kCaptureTicksPerSecond = 1000000ull;
constexpr size_t kFrameCapacity = 1536u;
constexpr size_t kTransportChunkLimit = 192u;
constexpr uint64_t kAdaptiveHybridEstimatorIdentity =
    OTIS_BUILD_FREQUENCY_ESTIMATOR_TAG_U64;

constexpr char kRunIdentity[] = "adaptive_hybrid_regulation:1";
constexpr char kExpectedImage[] = "adaptive_hybrid_regulation";

#if defined(ARDUINO)
constexpr char kBuildIdentity[] =
    OTIS_BUILD_SOURCE_SHA256 ":" OTIS_BUILD_CONFIG_SHA256;
#else
constexpr char kBuildIdentity[] = "host_non_firmware";
#endif

struct TransportFrame {
  char data[kFrameCapacity];
  uint16_t length;
  uint16_t sent;
};

enum class EvidencePhase : uint8_t {
  None = 0u,
  Request = 1u,
  Acceptance = 2u,
  Application = 3u,
  Response = 4u,
};

OtisRegulationTransaction transaction;
OtisAdaptiveHybridRegulationLiveHealth latest_health = {};
TransportFrame frame = {};
bool initialized = false;
bool transaction_bound = false;
bool have_health = false;
bool have_capture_lease = false;
bool manual_start_confirmed = false;
bool periodic_applied_code_confirmation_seen = false;
EvidencePhase evidence_phase = EvidencePhase::None;
uint32_t last_capture_lease_s = 0u;
uint32_t last_capture_lease_sequence = 0u;
uint32_t evidence_request_sequence = 0u;
uint32_t evidence_pending_since_s = 0u;
uint32_t transaction_record_sequence = 0u;
OtisRegulationActionableRequest pending_actionable_request = {};
bool pending_actionable_request_valid = false;
OtisAdaptiveHybridRegulationLiveOutcome deferred_application_outcome = {};
bool deferred_application_outcome_valid = false;
bool last_application_acknowledged = false;
bool estimator_history_reset = false;
uint32_t status_snapshot_generation = 0u;
uint32_t status_query_nonce = 0u;
bool gnss_metadata_hold_active = false;
bool gnss_metadata_hold_transaction_pending = false;
uint32_t gnss_metadata_hold_entry_sequence = 0u;
uint32_t gnss_metadata_requalification_sequence = 0u;
uint32_t gnss_metadata_qualification_frontier = 0u;
uint32_t gnss_metadata_hold_session = 0u;
uint16_t gnss_metadata_hold_applied_code = 0u;
uint32_t gnss_metadata_hold_dac_epoch = 0u;
bool health_event_ticks_available = false;
uint64_t health_event_timestamp_ticks = 0u;
uint64_t pending_application_timestamp_ticks = 0u;
OtisActiveHybridEngine hybrid_engine = {};
bool hybrid_engine_ready = false;
OtisActiveHybridDecision pending_hybrid_decision = {};
bool pending_hybrid_decision_valid = false;
OtisRegulationResponseClass pending_hybrid_response_class =
    OtisRegulationResponseClass::MeasurementOrActuatorFault;
bool pending_hybrid_response_valid = false;
bool pending_hybrid_predicted_sign_observed = false;
OtisDependentResponseIdentity dependent_response_identity = {};
uint32_t hybrid_record_sequence = 0u;
uint64_t setup_application_timestamp_ticks = 0u;
OtisActuatorTransactionGuard timing_actuator_guard = {};
// Core 1 is the sole active-evidence producer. Reuse one module-owned copy
// buffer instead of reserving a complete evidence frame in each call stack.
OtisEvidenceFrameMessage evidence_frame_scratch = {};
// One ADAPTIVE_HYBRID logical transition can contain AHY, ACT, and AHM. Stage
// these directly behind the partition queue's unpublished tail so no second
// full-frame array consumes the frozen RP2040 RAM reserve.
uint8_t adaptive_hybrid_evidence_burst_count = 0u;
uint8_t adaptive_hybrid_declared_evidence_burst_count = 0u;
bool adaptive_hybrid_collecting_evidence_burst = false;
uint32_t adaptive_hybrid_pending_evidence_burst_sequence = 0u;

OtisAdaptiveHybridEngine adaptive_hybrid_engine = {};
bool adaptive_hybrid_engine_ready = false;
OtisAdaptiveHybridDecision pending_adaptive_hybrid_decision = {};
bool pending_adaptive_hybrid_decision_valid = false;
OtisAdaptiveHybridObservation pending_adaptive_hybrid_observation = {};
OtisAdaptiveHybridMaintenanceHybridJoin pending_adaptive_hybrid_hybrid_join = {};
bool pending_adaptive_hybrid_origin_valid = false;
OtisAdaptiveHybridObservation last_adaptive_hybrid_observation = {};
OtisAdaptiveHybridDecision last_adaptive_hybrid_decision = {};
OtisAdaptiveHybridMaintenanceHybridJoin last_adaptive_hybrid_hybrid_join = {};
bool last_adaptive_hybrid_origin_valid = false;
uint32_t adaptive_hybrid_maintenance_record_sequence = 0u;
uint32_t adaptive_hybrid_evidence_burst_sequence = 0u;
uint16_t adaptive_hybrid_phase_nonzero_application_count = 0u;
uint16_t adaptive_hybrid_phase_material_application_count = 0u;
uint16_t adaptive_hybrid_frequency_only_application_count = 0u;

bool capture_lease_live(uint32_t now_s) {
  return have_capture_lease &&
         static_cast<uint32_t>(now_s - last_capture_lease_s) <=
             kCaptureLeaseMaximumAgeS;
}

bool exact_sha256_text(const char *value) {
  if (value == nullptr) return false;
  for (uint8_t index = 0u; index < 64u; ++index) {
    const char c = value[index];
    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
  }
  return value[64] == '\0';
}

bool publish_evidence_message(const OtisEvidenceFrameMessage *message) {
  if (adaptive_hybrid_collecting_evidence_burst) {
    if (message == nullptr || message->length == 0u ||
        message->length >= OTIS_EVIDENCE_FRAME_CAPACITY ||
        adaptive_hybrid_evidence_burst_count >= adaptive_hybrid_declared_evidence_burst_count ||
        !otis_dual_core_append_evidence_burst(message))
      return false;
    ++adaptive_hybrid_evidence_burst_count;
    return true;
  }
  return otis_dual_core_publish_evidence(message);
}

bool begin_adaptive_hybrid_evidence_burst(uint8_t expected_record_count) {
  if (adaptive_hybrid_collecting_evidence_burst ||
      adaptive_hybrid_evidence_burst_sequence == UINT32_MAX ||
      expected_record_count == 0u ||
      expected_record_count > OTIS_EVIDENCE_QUEUE_DEPTH)
    return false;
  adaptive_hybrid_evidence_burst_count = 0u;
  adaptive_hybrid_declared_evidence_burst_count = expected_record_count;
  adaptive_hybrid_pending_evidence_burst_sequence =
      adaptive_hybrid_evidence_burst_sequence + 1u;
  if (!otis_dual_core_begin_evidence_burst(expected_record_count)) {
    adaptive_hybrid_declared_evidence_burst_count = 0u;
    adaptive_hybrid_pending_evidence_burst_sequence = 0u;
    return false;
  }
  adaptive_hybrid_collecting_evidence_burst = true;
  return true;
}

void abandon_adaptive_hybrid_evidence_burst(void) {
  if (adaptive_hybrid_collecting_evidence_burst)
    otis_dual_core_cancel_evidence_burst();
  adaptive_hybrid_collecting_evidence_burst = false;
  adaptive_hybrid_evidence_burst_count = 0u;
  adaptive_hybrid_declared_evidence_burst_count = 0u;
  adaptive_hybrid_pending_evidence_burst_sequence = 0u;
}

bool commit_adaptive_hybrid_evidence_burst(void) {
  if (!adaptive_hybrid_collecting_evidence_burst ||
      adaptive_hybrid_evidence_burst_count == 0u ||
      adaptive_hybrid_evidence_burst_count != adaptive_hybrid_declared_evidence_burst_count ||
      adaptive_hybrid_pending_evidence_burst_sequence == 0u)
    return false;
  const uint32_t sequence = adaptive_hybrid_pending_evidence_burst_sequence;
  adaptive_hybrid_collecting_evidence_burst = false;
  adaptive_hybrid_evidence_burst_count = 0u;
  adaptive_hybrid_declared_evidence_burst_count = 0u;
  adaptive_hybrid_pending_evidence_burst_sequence = 0u;
  if (!otis_dual_core_commit_evidence_burst()) {
    otis_dual_core_cancel_evidence_burst();
    return false;
  }
  adaptive_hybrid_evidence_burst_sequence = sequence;
  return true;
}

bool queue_adaptive_hybrid_maintenance_record(
    OtisAdaptiveHybridMaintenanceEvent event, uint64_t event_timestamp_ticks,
    const OtisAdaptiveHybridEngine &engine_before,
    const OtisAdaptiveHybridEngine &engine_after,
    const OtisAdaptiveHybridObservation *observation,
    const OtisAdaptiveHybridDecision *decision,
    const OtisAdaptiveHybridMaintenanceHybridJoin *hybrid_join,
    const OtisAdaptiveHybridMaintenanceTransactionJoin *transaction_join,
    uint32_t evidence_burst_record_ordinal,
    uint32_t evidence_burst_record_count, const char *reason) {
  if (!adaptive_hybrid_collecting_evidence_burst || event_timestamp_ticks == 0u ||
      reason == nullptr || adaptive_hybrid_pending_evidence_burst_sequence == 0u ||
      evidence_burst_record_count != adaptive_hybrid_declared_evidence_burst_count ||
      evidence_burst_record_ordinal !=
          static_cast<uint32_t>(adaptive_hybrid_evidence_burst_count) + 1u ||
      adaptive_hybrid_maintenance_record_sequence == UINT32_MAX)
    return false;
  const uint32_t next_sequence = adaptive_hybrid_maintenance_record_sequence + 1u;
  const OtisAdaptiveHybridMaintenanceIdentityBinding identity = {
      kRunIdentity,
      kBuildIdentity,
      OTIS_BUILD_IMAGE_ID,
      kActivePolicyHash,
      kEstimatorHash,
  };
  const OtisAdaptiveHybridMaintenanceBuildInput input = {
      next_sequence,
      event,
      event_timestamp_ticks,
      identity,
      &engine_before,
      &engine_after,
      observation,
      decision,
      hybrid_join,
      transaction_join,
      adaptive_hybrid_pending_evidence_burst_sequence,
      evidence_burst_record_ordinal,
      evidence_burst_record_count,
      reason,
  };
  OtisAdaptiveHybridMaintenanceRecord record = {};
  evidence_frame_scratch = {};
  if (!otis_adaptive_hybrid_build_maintenance_record(&input, &record)) return false;
  if (event == OtisAdaptiveHybridMaintenanceEvent::GnssMetadataRequalified &&
      (record.requalification_d14_d8_observation_sequence == 0u ||
       record.requalification_d14_d8_observation_sequence !=
           engine_after.requalification_frontier))
    return false;
  const int used = otis_format_adaptive_hybrid_maintenance_v1(
      evidence_frame_scratch.data, sizeof(evidence_frame_scratch.data),
      &record);
  if (used <= 0 ||
      static_cast<size_t>(used) >= sizeof(evidence_frame_scratch.data))
    return false;
  evidence_frame_scratch.sequence = next_sequence;
  evidence_frame_scratch.length = static_cast<uint16_t>(used);
  if (!publish_evidence_message(&evidence_frame_scratch)) return false;
  adaptive_hybrid_maintenance_record_sequence = next_sequence;
  return true;
}

double adaptive_hybrid_picocodes_to_codes(OtisAdaptiveHybridWide value) {
  char text[OTIS_ADAPTIVE_HYBRID_WIDE_DECIMAL_CAPACITY] = {};
  if (!otis_adaptive_hybrid_wide_format_decimal(value, text, sizeof(text))) return 0.0;
  return strtod(text, nullptr) / 1000000000000.0;
}

OtisActiveHybridState adaptive_hybrid_project_hybrid_state(
    const OtisAdaptiveHybridEngine &engine, bool phase_valid) {
  if (engine.fail_static_reason != nullptr)
    return OtisActiveHybridState::FailStatic;
  if (!phase_valid)
    return OtisActiveHybridState::PhaseDegradedFrequencyOnly;
  if (engine.request_pending || engine.response_pending)
    return OtisActiveHybridState::FirstPhaseTransaction;
  if (engine.application_count == 0u)
    return OtisActiveHybridState::PhaseQualify;
  return OtisActiveHybridState::HybridTracking;
}

OtisActiveHybridDecision adaptive_hybrid_project_hybrid_decision(
    const OtisAdaptiveHybridEngine &before, const OtisAdaptiveHybridEngine &after,
    const OtisAdaptiveHybridDecision &decision, bool phase_valid,
    uint32_t timestamp_s) {
  constexpr double kConservativePlantGainHzPerCode = 0.000173340101;
  const double raw_fll_codes =
      adaptive_hybrid_picocodes_to_codes(decision.raw_fll_picocodes);
  const double raw_pll_codes =
      adaptive_hybrid_picocodes_to_codes(decision.raw_pll_picocodes);
  const double raw_combined_codes =
      adaptive_hybrid_picocodes_to_codes(decision.raw_combined_picocodes);
  return {
      static_cast<uint32_t>(decision.decision_sequence),
      timestamp_s,
      adaptive_hybrid_project_hybrid_state(before, phase_valid),
      adaptive_hybrid_project_hybrid_state(after, phase_valid),
      decision.reason,
      raw_fll_codes * kConservativePlantGainHzPerCode,
      raw_pll_codes * kConservativePlantGainHzPerCode,
      raw_combined_codes * kConservativePlantGainHzPerCode,
      raw_combined_codes,
      decision.requested_delta_codes,
      static_cast<uint16_t>(decision.requested_code),
      decision.counterfactual_frequency_only_delta_codes,
      decision.phase_materially_influenced,
      decision.step_limited,
      decision.range_clamped,
      decision.cadence_limited,
      decision.count_limited,
      decision.cumulative_budget_limited,
      static_cast<uint16_t>(before.application_count),
      static_cast<uint16_t>(before.cumulative_movement_codes),
  };
}

OtisAdaptiveHybridMaintenanceHybridJoin adaptive_hybrid_current_hybrid_join(
    const OtisAdaptiveHybridObservation &observation,
    const OtisAdaptiveHybridDecision &decision,
    uint32_t phase_observation_sequence) {
  return {
      hybrid_record_sequence,
      decision.decision_sequence,
      observation.capture_session,
      observation.source_first_sequence,
      observation.source_last_sequence,
      observation.phase_epoch,
      phase_observation_sequence,
      observation.phase_valid,
  };
}

OtisAdaptiveHybridMaintenanceTransactionJoin adaptive_hybrid_current_transaction_join(
    OtisAdaptiveHybridMaintenanceTransactionEvent event,
    const OtisAdaptiveHybridObservation &observation,
    const OtisAdaptiveHybridDecision &decision, bool include_application,
    bool downstream_epoch_exact) {
  OtisAdaptiveHybridMaintenanceTransactionJoin join = {};
  join.transaction_record_sequence = transaction_record_sequence;
  join.transaction_event = event;
  join.request_sequence = transaction.request.request_sequence;
  join.decision_sequence = decision.decision_sequence;
  join.capture_session = observation.capture_session;
  join.source_first_sequence = observation.source_first_sequence;
  join.source_last_sequence = observation.source_last_sequence;
  if (include_application) {
    join.application_sequence = transaction.applied.application_sequence;
    join.actual_applied_code = transaction.applied.applied_code;
    join.actual_dac_epoch = transaction.dac_epoch;
    join.downstream_epoch_exact = downstream_epoch_exact;
  }
  return join;
}

struct AdaptiveHybridLiveMutationSnapshot {
  OtisRegulationTransaction transaction;
  EvidencePhase evidence_phase;
  uint32_t evidence_request_sequence;
  uint32_t evidence_pending_since_s;
  OtisRegulationActionableRequest pending_actionable_request;
  bool pending_actionable_request_valid;
  OtisDependentResponseIdentity dependent_response_identity;
  uint32_t transaction_record_sequence;
  uint32_t hybrid_record_sequence;
  uint32_t maintenance_record_sequence;
};

AdaptiveHybridLiveMutationSnapshot capture_adaptive_hybrid_live_mutation_snapshot(void) {
  return {
      transaction,
      evidence_phase,
      evidence_request_sequence,
      evidence_pending_since_s,
      pending_actionable_request,
      pending_actionable_request_valid,
      dependent_response_identity,
      transaction_record_sequence,
      hybrid_record_sequence,
      adaptive_hybrid_maintenance_record_sequence,
  };
}

void restore_adaptive_hybrid_live_mutation_snapshot(
    const AdaptiveHybridLiveMutationSnapshot &snapshot) {
  transaction = snapshot.transaction;
  evidence_phase = snapshot.evidence_phase;
  evidence_request_sequence = snapshot.evidence_request_sequence;
  evidence_pending_since_s = snapshot.evidence_pending_since_s;
  pending_actionable_request = snapshot.pending_actionable_request;
  pending_actionable_request_valid =
      snapshot.pending_actionable_request_valid;
  dependent_response_identity = snapshot.dependent_response_identity;
  transaction_record_sequence = snapshot.transaction_record_sequence;
  hybrid_record_sequence = snapshot.hybrid_record_sequence;
  adaptive_hybrid_maintenance_record_sequence = snapshot.maintenance_record_sequence;
  frame = {};
  abandon_adaptive_hybrid_evidence_burst();
}

bool queue_adaptive_hybrid_single_async_transition(
    OtisAdaptiveHybridMaintenanceEvent event, uint64_t event_timestamp_ticks,
    const OtisAdaptiveHybridEngine &engine_before,
    const OtisAdaptiveHybridEngine &engine_after, const char *reason) {
  const AdaptiveHybridLiveMutationSnapshot snapshot =
      capture_adaptive_hybrid_live_mutation_snapshot();
  const OtisAdaptiveHybridObservation *observation =
      last_adaptive_hybrid_origin_valid ? &last_adaptive_hybrid_observation : nullptr;
  const OtisAdaptiveHybridDecision *decision =
      last_adaptive_hybrid_origin_valid ? &last_adaptive_hybrid_decision : nullptr;
  const OtisAdaptiveHybridMaintenanceHybridJoin *hybrid_join =
      last_adaptive_hybrid_origin_valid ? &last_adaptive_hybrid_hybrid_join : nullptr;
  if (!otis_dual_core_evidence_can_publish(1u) ||
      !begin_adaptive_hybrid_evidence_burst(1u) ||
      !queue_adaptive_hybrid_maintenance_record(
          event, event_timestamp_ticks, engine_before, engine_after,
          observation, decision, hybrid_join, nullptr, 1u, 1u, reason) ||
      !commit_adaptive_hybrid_evidence_burst()) {
    restore_adaptive_hybrid_live_mutation_snapshot(snapshot);
    return false;
  }
  return true;
}

void hybrid_fail_static(const char *reason) {
  hybrid_engine.state = OtisActiveHybridState::FailStatic;
  hybrid_engine.reason = reason;
  hybrid_engine.fault_reason = reason;
  hybrid_engine.transaction_outstanding = false;
  hybrid_engine.outstanding_phase_material = false;
  pending_hybrid_decision_valid = false;
}

OtisRegulationBinding expected_binding(uint32_t session_id) {
  return {
      kRunIdentity,
      kBuildIdentity,
      OTIS_BUILD_IMAGE_ID,
      kEstimatorHash,
      kModelHash,
      kActivePolicyHash,
      kResponsePolicyHash,
      kNumericalPolicyHash,
      session_id,
      static_cast<uint16_t>(OTIS_ADAPTIVE_HYBRID_START_CODE),
      0xA800u,
      0xAB00u,
      21u,
      static_cast<uint16_t>(OTIS_ADAPTIVE_HYBRID_CORRECTION_LIMIT),
      static_cast<uint16_t>(OTIS_ADAPTIVE_HYBRID_CUMULATIVE_LIMIT_CODES),
      true,
      true,
  };
}

OtisRegulationEligibility eligibility(uint32_t now_s) {
  const bool image_matches = strcmp(OTIS_BUILD_IMAGE_ID, kExpectedImage) == 0;
  const bool session_matches =
      transaction_bound && have_health &&
      latest_health.session_id == transaction.expected_binding.session_id;
  return {
      transaction_bound,
      transaction_bound,
      image_matches,
      transaction_bound,
      transaction_bound,
      transaction_bound,
      transaction_bound,
      session_matches,
      have_health && latest_health.gnss_metadata_valid,
      have_health && latest_health.gnss_identity_stable,
      have_health && latest_health.gnss_3d_evidence,
      have_health && latest_health.raw_pps_valid,
      have_health && latest_health.count_valid,
      have_health && latest_health.estimator_valid,
      have_health && latest_health.model_applicable,
      have_health && latest_health.temperature_valid,
      have_health && latest_health.applied_code_confirmed &&
          transaction_bound &&
          latest_health.applied_code == transaction.applied_code &&
          transaction.applied_code >= transaction.expected_binding.minimum_code &&
          transaction.applied_code <= transaction.expected_binding.maximum_code,
      capture_lease_live(now_s),
      have_health && latest_health.abort_path_live,
      evidence_phase == EvidencePhase::None,
  };
}

bool active_integrity_healthy(uint32_t now_s) {
  if (!have_health || !transaction_bound) return false;
  return
         // ADAPTIVE_HYBRID routes every recoverable serial-metadata qualification
         // anomaly, including a temporarily unconfirmed receiver identity,
         // into its bounded metadata hold. D14/D8/reference-integrity loss is
         // still terminal and is checked independently below.
         true &&
         latest_health.reference_integrity_valid &&
         latest_health.applied_code_confirmed &&
         latest_health.applied_code == transaction.applied_code &&
         capture_lease_live(now_s) && latest_health.abort_path_live;
}

bool gnss_metadata_healthy(void) {
  return have_health && latest_health.gnss_metadata_valid &&
         latest_health.gnss_identity_stable &&
         latest_health.gnss_3d_evidence;
}

bool d14_d8_path_healthy(void) {
  return have_health && latest_health.session_id != 0u &&
         latest_health.raw_pps_valid && latest_health.count_valid;
}

bool reference_path_healthy(void) {
  return gnss_metadata_healthy() && d14_d8_path_healthy();
}

bool reference_requalification_healthy(void) {
  return reference_path_healthy() && latest_health.estimator_valid;
}

bool critical_continuity_healthy(uint32_t now_s) {
  const bool reference_healthy = gnss_metadata_hold_active
                                     ? d14_d8_path_healthy()
                                     : reference_path_healthy();
  return active_integrity_healthy(now_s) && reference_healthy &&
         latest_health.session_id == transaction.expected_binding.session_id;
}

const char *evidence_state_name(void) {
  switch (evidence_phase) {
    case EvidencePhase::Request:
      return "request_pending";
    case EvidencePhase::Acceptance:
      return "acceptance_pending";
    case EvidencePhase::Application:
      return "application_pending";
    case EvidencePhase::Response:
      return "response_pending";
    case EvidencePhase::None:
      return "evidence_clear";
  }
  return "evidence_clear";
}

OtisCrossCoreActuatorRequest cross_core_request(
    const OtisRegulationActionableRequest &request, uint32_t now_s) {
  OtisCrossCoreActuatorRequest cross = {};
  cross.request_sequence = request.request_sequence;
  cross.decision_sequence = request.decision_sequence;
  cross.source_first_sequence = request.source_first_sequence;
  cross.source_last_sequence = request.source_last_sequence;
  cross.decision_reference_ticks =
      pending_adaptive_hybrid_decision_valid &&
              pending_adaptive_hybrid_decision.decision_sequence ==
                  request.decision_sequence
          ? pending_adaptive_hybrid_decision.decision_timestamp_ticks
          : 0u;
  cross.monotonic_deadline_s =
      now_s + kEvidenceAcknowledgementMaximumAgeS;
  cross.authorization_sequence = request.authorization_sequence;
  cross.nonce = request.nonce;
  cross.session_id = request.session_id;
  cross.correction_ordinal = request.correction_ordinal;
  cross.current_applied_code = request.current_applied_code;
  cross.requested_code = request.requested_code;
  cross.requested_delta_codes = request.requested_delta_codes;
  cross.actionable = request.actionable;
  return cross;
}

bool publish_cross_core_actuator_message(OtisCriticalMessageKind kind,
                                         uint32_t now_s) {
  if (!pending_actionable_request_valid) return false;
  OtisCriticalRecordMessage message = {};
  message.kind = kind;
  message.sequence = pending_actionable_request.request_sequence;
  message.timestamp_ticks =
      static_cast<uint64_t>(now_s) * kCaptureTicksPerSecond;
  snprintf(message.component, sizeof(message.component), "%s",
           "regulation_actuator");
  snprintf(message.reason, sizeof(message.reason), "%s",
           kind == OtisCriticalMessageKind::ActuatorRequest
               ? "durable_request_released_to_core0"
               : "durable_acceptance_released_for_single_application");
  message.request = kind == OtisCriticalMessageKind::ActuatorRequest
                        ? cross_core_request(pending_actionable_request, now_s)
                        : timing_actuator_guard.pending;
  return otis_dual_core_publish_critical(&message);
}

bool queue_frame(const char *event, uint64_t event_timestamp_ticks,
                 const OtisRegulationResponseResult *response,
                 double post_error_hz) {
  if (frame.length != 0u || event_timestamp_ticks == 0u) return false;
  const char *response_name =
      response == nullptr ? "unavailable"
                          : otis_regulation_response_class_name(response->classification);
  const char *reason = response == nullptr ? transaction.reason : response->reason;
  const uint64_t progress_ticks =
      static_cast<uint64_t>(transaction.request.timestamp_s) *
      kCaptureTicksPerSecond;
  otis_dual_core_note_timing_progress(
      OtisTimingProgressPhase::AdaptiveHybridPrepare, progress_ticks);
  char pre_error[32] = "";
  char post_error[32] = "";
  char observed_response[32] = "";
  char cumulative_response[32] = "";
  if (!otis_format_fixed(transaction.request.pre_error_hz, 9u, pre_error,
                         sizeof(pre_error)) ||
      !otis_format_fixed(post_error_hz, 9u, post_error,
                         sizeof(post_error)) ||
      !otis_format_fixed(
          response == nullptr ? 0.0 : response->observed_response_hz, 9u,
          observed_response, sizeof(observed_response)) ||
      !otis_format_fixed(
          response == nullptr ? 0.0 : response->cumulative_response_hz, 9u,
          cumulative_response, sizeof(cumulative_response)))
    return false;
  const uint32_t next_record_sequence = transaction_record_sequence + 1u;
  otis_dual_core_note_timing_progress(
      OtisTimingProgressPhase::AdaptiveHybridFormat, progress_ticks);
  const int used = snprintf(
      frame.data, sizeof(frame.data),
      "ACT,2,%lu,%s,%llu,rp2040_monotonic_us64,%s,%s,%s,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%u,%ld,%u,%u,%u,%s,%u,%lu,%u,%u,%lu,%s,%s,%s,%u,%s,%u,%u,%s,%s,%s,%u,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\r\n",
      static_cast<unsigned long>(next_record_sequence), event,
      static_cast<unsigned long long>(event_timestamp_ticks), kRunIdentity,
      kBuildIdentity, OTIS_BUILD_IMAGE_ID,
      static_cast<unsigned long>(transaction.expected_binding.session_id),
      static_cast<unsigned long>(transaction.request.authorization_sequence),
      static_cast<unsigned long>(transaction.request.nonce),
      static_cast<unsigned long>(transaction.request.request_sequence),
      static_cast<unsigned long>(transaction.request.decision_sequence),
      static_cast<unsigned long>(transaction.request.source_first_sequence),
      static_cast<unsigned long>(transaction.request.source_last_sequence),
      static_cast<unsigned long>(transaction.request.timestamp_s),
      transaction.request.current_applied_code,
      static_cast<long>(transaction.request.requested_delta_codes),
      transaction.request.requested_code, transaction.request.correction_ordinal,
      transaction.request.cumulative_after_codes,
      pre_error,
      transaction.accepted.accepted_code,
      static_cast<unsigned long>(transaction.accepted.accepted_timestamp_s),
      transaction.applied.applied_code, transaction.applied.application_sequence,
      static_cast<unsigned long>(transaction.applied.application_timestamp_s),
      transaction.applied.i2c_ok ? "true" : "false",
      transaction.applied.clamped ? "true" : "false",
      transaction.applied.ambiguous ? "true" : "false",
      transaction.dac_epoch, estimator_history_reset ? "true" : "false",
      transaction.correction_count,
      transaction.cumulative_movement_codes, post_error, observed_response,
      cumulative_response,
      response == nullptr ? 0u : response->consecutive_indeterminate,
      otis_regulation_state_name(transaction.state), response_name, reason,
      kEstimatorHash, kModelHash, kActivePolicyHash, kResponsePolicyHash,
      kNumericalPolicyHash,
      // ACT is a durable observation, never a transferable authority token.
      // During the dual-core request_created phase the private pending request
      // remains actionable until Core 0 accepts it, but the serialized copy
      // must stay non-actionable exactly as the frozen evidence contract
      // requires.  The host releases the private request only by acknowledging
      // the durably preserved phase and cannot reconstruct authority from CSV.
      "false", evidence_state_name());
  if (used <= 0 || static_cast<size_t>(used) >= sizeof(frame.data)) {
    frame = {};
    return false;
  }
  frame.length = static_cast<uint16_t>(used);
  frame.sent = 0u;
  evidence_frame_scratch = {};
  evidence_frame_scratch.sequence = next_record_sequence;
  evidence_frame_scratch.length = frame.length;
  memcpy(evidence_frame_scratch.data, frame.data, frame.length + 1u);
  if (!publish_evidence_message(&evidence_frame_scratch)) {
    frame = {};
    return false;
  }
  frame = {};
  transaction_record_sequence = next_record_sequence;
  otis_dual_core_note_timing_progress(
      OtisTimingProgressPhase::AdaptiveHybridPublish, progress_ticks);
  return true;
}

bool queue_manual_start_frame(uint16_t code, bool ok, uint32_t now_s,
                              uint64_t event_timestamp_ticks,
                              uint32_t capture_session) {
  if (frame.length != 0u || event_timestamp_ticks == 0u ||
      capture_session == 0u)
    return false;
  const uint32_t next_record_sequence = transaction_record_sequence + 1u;
  const int used = snprintf(
      frame.data, sizeof(frame.data),
      "ACT,2,%lu,manual_start,%llu,rp2040_monotonic_us64,%s,%s,%s,%lu,0,0,0,0,0,0,%lu,%u,0,%u,0,0,0.000000000,%u,%lu,%u,0,%lu,%s,false,false,%u,false,%u,%u,0.000000000,0.000000000,0.000000000,0,%s,unavailable,%s,%s,%s,%s,%s,%s,false,evidence_clear\r\n",
      static_cast<unsigned long>(next_record_sequence),
      static_cast<unsigned long long>(event_timestamp_ticks), kRunIdentity,
      kBuildIdentity, OTIS_BUILD_IMAGE_ID,
      static_cast<unsigned long>(capture_session),
      static_cast<unsigned long>(now_s), code, code, code,
      static_cast<unsigned long>(now_s), code,
      static_cast<unsigned long>(now_s), ok ? "true" : "false",
      transaction_bound ? transaction.dac_epoch : 0u,
      transaction_bound ? transaction.correction_count : 0u,
      transaction_bound ? transaction.cumulative_movement_codes : 0u,
      transaction_bound ? otis_regulation_state_name(transaction.state)
                        : "DISARMED",
      ok ? "manual_start_established" : "manual_start_failed", kEstimatorHash,
      kModelHash, kActivePolicyHash, kResponsePolicyHash,
      kNumericalPolicyHash);
  if (used <= 0 || static_cast<size_t>(used) >= sizeof(frame.data)) {
    frame = {};
    return false;
  }
  frame.length = static_cast<uint16_t>(used);
  frame.sent = 0u;
  evidence_frame_scratch = {};
  evidence_frame_scratch.sequence = next_record_sequence;
  evidence_frame_scratch.length = frame.length;
  memcpy(evidence_frame_scratch.data, frame.data, frame.length + 1u);
  if (!publish_evidence_message(&evidence_frame_scratch)) {
    frame = {};
    return false;
  }
  frame = {};
  transaction_record_sequence = next_record_sequence;
  return true;
}

bool queue_active_hybrid_decision(
    const OtisAdaptiveHybridRegulationLiveDecision &source,
    const OtisActiveHybridDecision &decision,
    uint64_t decision_timestamp_ticks) {
  const uint32_t next_sequence = hybrid_record_sequence + 1u;
  OtisActiveHybridDecisionRecordContext context = {
      next_sequence,
      decision_timestamp_ticks,
      kRunIdentity,
      kBuildIdentity,
      OTIS_BUILD_IMAGE_ID,
      kEstimatorHash,
      kPhaseEstimatorHash,
      otis_regulation_state_name(transaction.state),
      transaction.have_request ? transaction.request.request_sequence : 0u,
      transaction.have_acceptance ? transaction.request.request_sequence : 0u,
      transaction.have_application ? transaction.applied.application_sequence
                                   : 0u,
      pending_hybrid_response_valid
          ? otis_regulation_response_class_name(pending_hybrid_response_class)
          : "unavailable",
      source.phase_recorder_published &&
          source.phase_dac_epoch == source.dac_epoch &&
          source.phase_applied_code == source.current_applied_code,
      kActivePolicyHash,
      kResponsePolicyHash,
      false,
  };
  const bool carries_dependent_response =
      otis_dependent_response_identity_apply(&dependent_response_identity,
                                             &context);
  const int used = otis_format_active_hybrid_decision_v2(
      frame.data, sizeof(frame.data), &source, &decision, &context);
  if (used <= 0 || static_cast<size_t>(used) >= sizeof(frame.data)) {
    frame = {};
    return false;
  }
  frame.length = static_cast<uint16_t>(used);
  frame.sent = 0u;
  evidence_frame_scratch = {};
  evidence_frame_scratch.sequence = next_sequence;
  evidence_frame_scratch.length = frame.length;
  memcpy(evidence_frame_scratch.data, frame.data, frame.length + 1u);
  if (!publish_evidence_message(&evidence_frame_scratch)) {
    frame = {};
    return false;
  }
  frame = {};
  hybrid_record_sequence = next_sequence;
  if (carries_dependent_response)
    otis_dependent_response_identity_consume(&dependent_response_identity);
  return true;
}


bool withdraw_private_request_for_gnss_metadata_hold(void) {
  if (transaction.state != OtisRegulationState::RequestPending ||
      evidence_phase != EvidencePhase::Request ||
      !transaction.have_request || transaction.have_acceptance ||
      transaction.have_application || !pending_actionable_request_valid ||
      transaction.request.request_sequence !=
          pending_actionable_request.request_sequence ||
      transaction.request.nonce != pending_actionable_request.nonce)
    return false;
  transaction.request.actionable = false;
  transaction.have_request = false;
  transaction.have_acceptance = false;
  transaction.have_application = false;
  transaction.have_arm = false;
  transaction.state = OtisRegulationState::Disarmed;
  transaction.reason = "gnss_metadata_private_request_withdrawn";
  return true;
}

bool enter_gnss_metadata_hold(void) {
  if (!transaction_bound || !manual_start_confirmed) return false;
  const bool entering_new_hold = !gnss_metadata_hold_active;
  if (entering_new_hold) {
    gnss_metadata_hold_active = true;
    gnss_metadata_hold_transaction_pending = false;
    gnss_metadata_hold_entry_sequence = latest_health.gnss_metadata_sequence;
    gnss_metadata_requalification_sequence = 0u;
    gnss_metadata_qualification_frontier = 0u;
    gnss_metadata_hold_session = transaction.expected_binding.session_id;
    gnss_metadata_hold_applied_code = transaction.applied_code;
    gnss_metadata_hold_dac_epoch = transaction.dac_epoch;
  }

  if (!adaptive_hybrid_engine_ready || !health_event_ticks_available ||
      health_event_timestamp_ticks == 0u)
    return false;

  if (adaptive_hybrid_engine.request_pending &&
      transaction.state == OtisRegulationState::RequestPending &&
      evidence_phase == EvidencePhase::Request) {
    if (!pending_adaptive_hybrid_origin_valid ||
        !otis_dual_core_evidence_can_publish(3u))
      return false;
    const AdaptiveHybridLiveMutationSnapshot rejection_snapshot =
        capture_adaptive_hybrid_live_mutation_snapshot();
    const OtisAdaptiveHybridEngine rejection_before = adaptive_hybrid_engine;
    OtisAdaptiveHybridEngine rejection_after = rejection_before;
    if (!otis_adaptive_hybrid_engine_reject_or_expire_request(&rejection_after) ||
        !withdraw_private_request_for_gnss_metadata_hold()) {
      restore_adaptive_hybrid_live_mutation_snapshot(rejection_snapshot);
      return false;
    }
    pending_actionable_request_valid = false;
    evidence_phase = EvidencePhase::None;
    evidence_request_sequence = 0u;
    evidence_pending_since_s = 0u;
    if (!begin_adaptive_hybrid_evidence_burst(2u) ||
        !queue_frame("request_withdrawn", health_event_timestamp_ticks,
                     nullptr, 0.0)) {
      restore_adaptive_hybrid_live_mutation_snapshot(rejection_snapshot);
      return false;
    }
    const OtisAdaptiveHybridMaintenanceTransactionJoin rejection_join =
        adaptive_hybrid_current_transaction_join(
            OtisAdaptiveHybridMaintenanceTransactionEvent::RequestWithdrawn,
            pending_adaptive_hybrid_observation, pending_adaptive_hybrid_decision, false,
            false);
    if (!queue_adaptive_hybrid_maintenance_record(
            OtisAdaptiveHybridMaintenanceEvent::RequestRejectedOrExpired,
            health_event_timestamp_ticks, rejection_before,
            rejection_after, &pending_adaptive_hybrid_observation,
            &pending_adaptive_hybrid_decision, &pending_adaptive_hybrid_hybrid_join,
            &rejection_join, 2u, 2u, rejection_after.last_reason) ||
        !commit_adaptive_hybrid_evidence_burst()) {
      restore_adaptive_hybrid_live_mutation_snapshot(rejection_snapshot);
      return false;
    }
    adaptive_hybrid_engine = rejection_after;
    pending_adaptive_hybrid_decision_valid = false;
    pending_adaptive_hybrid_origin_valid = false;
  }

  if (adaptive_hybrid_engine.request_pending) {
    // The request has already crossed the durable evidence boundary. Core 0
    // must reject it with the exact identity before the controller can leave
    // REQUEST_PENDING and enter metadata hold.
    gnss_metadata_hold_transaction_pending = true;
    return true;
  }

  if (!adaptive_hybrid_engine.metadata_hold) {
    const OtisAdaptiveHybridEngine hold_before = adaptive_hybrid_engine;
    OtisAdaptiveHybridEngine hold_after = hold_before;
    if (!otis_adaptive_hybrid_engine_enter_metadata_hold(&hold_after) ||
        !queue_adaptive_hybrid_single_async_transition(
            OtisAdaptiveHybridMaintenanceEvent::GnssMetadataHoldEnter,
            health_event_timestamp_ticks, hold_before, hold_after,
            hold_after.last_reason))
      return false;
    adaptive_hybrid_engine = hold_after;
  } else if (!entering_new_hold && adaptive_hybrid_engine.metadata_requalified) {
    // A second metadata anomaly during the two-window gate restarts the same
    // continuous hold without manufacturing another false-to-true AHM event.
    OtisAdaptiveHybridEngine restarted = adaptive_hybrid_engine;
    if (!otis_adaptive_hybrid_engine_enter_metadata_hold(&restarted)) return false;
    adaptive_hybrid_engine = restarted;
  }

  if (transaction.state == OtisRegulationState::RequestPending ||
      transaction.state ==
          OtisRegulationState::AcceptedAwaitingApplication ||
      transaction.state == OtisRegulationState::AwaitingResponse ||
      evidence_phase != EvidencePhase::None) {
    gnss_metadata_hold_transaction_pending = true;
    return true;
  }
  gnss_metadata_hold_transaction_pending = false;
  return transaction.state == OtisRegulationState::ReferenceHold ||
         otis_regulation_reference_hold(
             &transaction, "gnss_metadata_unqualified_hold");

  if (transaction.state == OtisRegulationState::RequestPending &&
      evidence_phase == EvidencePhase::Request) {
    if (!health_event_ticks_available) return false;
    if (!withdraw_private_request_for_gnss_metadata_hold())
      return false;
    pending_actionable_request_valid = false;
    pending_hybrid_decision_valid = false;
    evidence_phase = EvidencePhase::None;
    evidence_request_sequence = 0u;
    evidence_pending_since_s = 0u;
    if (!queue_frame("request_withdrawn", health_event_timestamp_ticks,
                     nullptr, 0.0))
      return false;
  }

  if (transaction.state == OtisRegulationState::RequestPending ||
      transaction.state ==
          OtisRegulationState::AcceptedAwaitingApplication ||
      transaction.state == OtisRegulationState::AwaitingResponse ||
      evidence_phase != EvidencePhase::None) {
    gnss_metadata_hold_transaction_pending = true;
    return true;
  }

  gnss_metadata_hold_transaction_pending = false;
  return otis_regulation_reference_hold(
      &transaction, "gnss_metadata_unqualified_hold");
}

bool maybe_complete_gnss_metadata_requalification(void) {
  if (!gnss_metadata_hold_active) return false;
  if (gnss_metadata_hold_transaction_pending) {
    if (transaction.state == OtisRegulationState::AwaitingResponse &&
        transaction.have_application &&
        latest_health.applied_code_confirmed &&
        latest_health.applied_code == transaction.applied_code) {
      // An already released request remains Core-0-owned.  Once its exact
      // application is confirmed, that code/epoch becomes the frozen hold
      // identity while the D14/D8 response completes.
      gnss_metadata_hold_applied_code = transaction.applied_code;
      gnss_metadata_hold_dac_epoch = transaction.dac_epoch;
    }
    if (transaction.state == OtisRegulationState::Disarmed &&
        evidence_phase == EvidencePhase::None) {
      gnss_metadata_hold_transaction_pending = false;
      if (!otis_regulation_reference_hold(
              &transaction, "gnss_metadata_unqualified_hold"))
        return false;
    } else {
      return false;
    }
  }
  if (transaction.state != OtisRegulationState::ReferenceHold) return false;
  if (!gnss_metadata_healthy()) {
    gnss_metadata_requalification_sequence = 0u;
    gnss_metadata_qualification_frontier = 0u;
    return false;
  }
  if (!adaptive_hybrid_engine_ready || !adaptive_hybrid_engine.metadata_hold ||
      adaptive_hybrid_engine.request_pending || adaptive_hybrid_engine.response_pending)
    return false;
  if (adaptive_hybrid_engine.metadata_requalified) return false;
  if (latest_health.gnss_metadata_sequence <=
          gnss_metadata_hold_entry_sequence ||
      latest_health.d14_d8_observation_sequence == 0u)
    return false;
  // The ordinary service path deliberately re-evaluates reference state
  // between timestamped health publications.  A healthy polling pass has no
  // event timestamp and therefore cannot publish the causal requalification
  // transition yet; it is not an identity contradiction and must remain in
  // the recoverable hold until the next timestamped health update.
  if (!health_event_ticks_available || health_event_timestamp_ticks == 0u)
    return false;
  if (latest_health.session_id != gnss_metadata_hold_session ||
      !latest_health.applied_code_confirmed ||
      latest_health.applied_code != gnss_metadata_hold_applied_code ||
      transaction.applied_code != gnss_metadata_hold_applied_code ||
      transaction.dac_epoch != gnss_metadata_hold_dac_epoch) {
    otis_regulation_fault(
        &transaction,
        "adaptive_hybrid_metadata_requalification_identity_or_tick_contradiction");
    return false;
  }
  const OtisAdaptiveHybridEngine requalification_before = adaptive_hybrid_engine;
  OtisAdaptiveHybridEngine requalification_after = requalification_before;
  if (!otis_adaptive_hybrid_engine_requalify_metadata(
          &requalification_after,
          latest_health.d14_d8_observation_sequence) ||
      !queue_adaptive_hybrid_single_async_transition(
          OtisAdaptiveHybridMaintenanceEvent::GnssMetadataRequalified,
          health_event_timestamp_ticks, requalification_before,
          requalification_after, requalification_after.last_reason)) {
    otis_regulation_fault(
        &transaction, "adaptive_hybrid_metadata_requalification_evidence_fault");
    return false;
  }
  adaptive_hybrid_engine = requalification_after;
  gnss_metadata_requalification_sequence =
      latest_health.gnss_metadata_sequence;
  gnss_metadata_qualification_frontier =
      latest_health.d14_d8_observation_sequence;
  return true;
  if (gnss_metadata_requalification_sequence == 0u) {
    if (latest_health.gnss_metadata_sequence <=
        gnss_metadata_hold_entry_sequence)
      return false;
    gnss_metadata_requalification_sequence =
        latest_health.gnss_metadata_sequence;
    gnss_metadata_qualification_frontier =
        latest_health.d14_d8_observation_sequence;
    return false;
  }
  if (latest_health.d14_d8_observation_sequence <=
      gnss_metadata_qualification_frontier)
    return false;
  if (latest_health.session_id != gnss_metadata_hold_session ||
      !latest_health.applied_code_confirmed ||
      latest_health.applied_code != gnss_metadata_hold_applied_code ||
      transaction.applied_code != gnss_metadata_hold_applied_code ||
      transaction.dac_epoch != gnss_metadata_hold_dac_epoch) {
    otis_regulation_fault(
        &transaction,
        "gnss_metadata_requalification_session_code_or_epoch_contradiction");
    return false;
  }
  if (!otis_regulation_reference_requalify(
          &transaction, gnss_metadata_hold_session)) {
    otis_regulation_fault(
        &transaction, "gnss_metadata_requalification_transition_failed");
    return false;
  }
  gnss_metadata_hold_active = false;
  gnss_metadata_hold_transaction_pending = false;
  return true;
}

void update_active_reference_and_integrity(uint32_t now_s) {
  // Before the one-shot setup acknowledgement there is no authoritative DAC
  // code to protect, and the host may not yet have established its capture
  // lease. Keep the bound session in SETUP_PENDING until those preconditions
  // are deliberately established; the post-setup integrity predicate below
  // requires both and would otherwise manufacture an unrecoverable boot fault.
  if (!transaction_bound || !manual_start_confirmed) return;
  const bool inactive =
      transaction.state == OtisRegulationState::Fault ||
      transaction.state == OtisRegulationState::Aborted;
  if (inactive) return;
  const bool transaction_in_flight =
      transaction.state == OtisRegulationState::RequestPending ||
      transaction.state ==
          OtisRegulationState::AcceptedAwaitingApplication;
  if ((transaction_in_flight ||
       transaction.state == OtisRegulationState::Armed ||
       transaction.state == OtisRegulationState::AwaitingResponse ||
       transaction.state == OtisRegulationState::ReferenceHold) &&
      !active_integrity_healthy(now_s)) {
    otis_regulation_fault(&transaction,
                            "active_integrity_or_capture_lease_lost");
    return;
  }

  const bool session_matches =
      latest_health.session_id == transaction.expected_binding.session_id;
  const bool timing_reference_healthy = d14_d8_path_healthy();
  const bool metadata_healthy = gnss_metadata_healthy();
  if (!session_matches || !timing_reference_healthy) {
    if (transaction_in_flight)
      otis_regulation_fault(
          &transaction,
          "d14_d8_or_session_lost_during_unfinished_actuator_transaction");
    else if (!otis_regulation_reference_hold(
                 &transaction,
                 session_matches ? "d14_d8_reference_quality_suspect_hold"
                                 : "reference_session_changed_hold"))
      otis_regulation_fault(&transaction,
                              "reference_hold_transition_failed");
    return;
  }

  if (!metadata_healthy) {
    if (!enter_gnss_metadata_hold())
      otis_regulation_fault(&transaction,
                              "gnss_metadata_hold_transition_failed");
    return;
  }
  if (gnss_metadata_hold_active) {
    maybe_complete_gnss_metadata_requalification();
    return;
  }

  const bool reference_healthy = reference_path_healthy();
  if (transaction_in_flight) {
    if (!session_matches || !reference_healthy)
      otis_regulation_fault(
          &transaction,
          "reference_lost_during_unfinished_actuator_transaction");
    return;
  }

  if (transaction.state == OtisRegulationState::ReferenceHold) {
    if (reference_requalification_healthy())
      otis_regulation_reference_requalify(&transaction,
                                            latest_health.session_id);
    return;
  }

  if ((transaction.state == OtisRegulationState::Disarmed ||
       transaction.state == OtisRegulationState::Armed ||
       transaction.state == OtisRegulationState::AwaitingResponse ||
       transaction.state == OtisRegulationState::OutOfModelHold) &&
      (!session_matches || !reference_healthy)) {
    if (!otis_regulation_reference_hold(
            &transaction,
            session_matches ? "reference_quality_suspect_hold"
                            : "reference_session_changed_hold"))
      otis_regulation_fault(&transaction,
                              "reference_hold_transition_failed");
  }
}

}  // namespace

bool otis_adaptive_hybrid_regulation_live_begin(void) {
  initialized = true;
  transaction_bound = false;
  have_health = false;
  have_capture_lease = false;
  manual_start_confirmed = false;
  periodic_applied_code_confirmation_seen = false;
  evidence_phase = EvidencePhase::None;
  last_capture_lease_sequence = 0u;
  evidence_request_sequence = 0u;
  evidence_pending_since_s = 0u;
  transaction_record_sequence = 0u;
  pending_actionable_request_valid = false;
  deferred_application_outcome_valid = false;
  last_application_acknowledged = false;
  estimator_history_reset = false;
  gnss_metadata_hold_active = false;
  gnss_metadata_hold_transaction_pending = false;
  gnss_metadata_hold_entry_sequence = 0u;
  gnss_metadata_requalification_sequence = 0u;
  gnss_metadata_qualification_frontier = 0u;
  gnss_metadata_hold_session = 0u;
  gnss_metadata_hold_applied_code = 0u;
  gnss_metadata_hold_dac_epoch = 0u;
  health_event_ticks_available = false;
  health_event_timestamp_ticks = 0u;
  pending_application_timestamp_ticks = 0u;
  hybrid_engine = {};
  hybrid_engine_ready = false;
  pending_hybrid_decision = {};
  pending_hybrid_decision_valid = false;
  pending_hybrid_response_class =
      OtisRegulationResponseClass::MeasurementOrActuatorFault;
  pending_hybrid_response_valid = false;
  pending_hybrid_predicted_sign_observed = false;
  otis_dependent_response_identity_reset(&dependent_response_identity);
  hybrid_record_sequence = 0u;
  setup_application_timestamp_ticks = 0u;
  otis_actuator_guard_init(&timing_actuator_guard);
  adaptive_hybrid_evidence_burst_count = 0u;
  adaptive_hybrid_declared_evidence_burst_count = 0u;
  adaptive_hybrid_collecting_evidence_burst = false;
  adaptive_hybrid_pending_evidence_burst_sequence = 0u;
  adaptive_hybrid_engine = {};
  adaptive_hybrid_engine_ready = false;
  pending_adaptive_hybrid_decision = {};
  pending_adaptive_hybrid_decision_valid = false;
  pending_adaptive_hybrid_observation = {};
  pending_adaptive_hybrid_hybrid_join = {};
  pending_adaptive_hybrid_origin_valid = false;
  last_adaptive_hybrid_observation = {};
  last_adaptive_hybrid_decision = {};
  last_adaptive_hybrid_hybrid_join = {};
  last_adaptive_hybrid_origin_valid = false;
  adaptive_hybrid_maintenance_record_sequence = 0u;
  adaptive_hybrid_evidence_burst_sequence = 0u;
  adaptive_hybrid_phase_nonzero_application_count = 0u;
  adaptive_hybrid_phase_material_application_count = 0u;
  adaptive_hybrid_frequency_only_application_count = 0u;
  frame = {};
  return true;
}

void otis_adaptive_hybrid_regulation_live_emit_headers(void) {
  otis_transport_write_cstr(
      "record_type,schema_version,transaction_record_sequence,event,event_timestamp_ticks,time_domain,run_identity,build_identity,image_identity,session_id,authorization_sequence,nonce,request_sequence,decision_sequence,source_first_sequence,source_last_sequence,decision_timestamp_s,current_applied_code,requested_delta_codes,requested_code,correction_ordinal,cumulative_after_codes,pre_error_hz,accepted_code,accepted_timestamp_s,applied_code,application_sequence,application_timestamp_s,i2c_ok,clamped,ambiguous,dac_epoch,estimator_history_reset,correction_count,cumulative_movement_codes,post_error_hz,observed_response_hz,cumulative_response_hz,consecutive_indeterminate,active_state,response_class,reason,estimator_sha256,model_sha256,active_policy_sha256,response_policy_sha256,numerical_policy_sha256,actionable,evidence_state\r\n");
  otis_transport_write_cstr(
      "record_type,schema_version,hybrid_record_sequence,decision_sequence,decision_timestamp_ticks,time_domain,decision_timestamp_s,run_identity,build_identity,image_identity,capture_session,source_first_sequence,source_last_sequence,frequency_estimator_sha256,frequency_error_hz,accumulated_edge_error_counts,tight_state,phase_estimator_sha256,phase_epoch,phase_observation_sequence,relative_phase_cycles,phase_continuous,phase_current,phase_step_detected,phase_recorder_published,current_applied_code,dac_epoch,phase_applied_code,phase_dac_epoch,state_before,state_after,frequency_term_hz,phase_term_hz,combined_demand_hz,raw_combined_delta_codes,requested_delta_codes,requested_code,counterfactual_frequency_only_delta_codes,phase_materially_influenced,step_limited,range_clamped,cadence_limited,count_limited,cumulative_budget_limited,correction_count_before,cumulative_movement_before_codes,authority_state,request_sequence,acceptance_sequence,application_sequence,response_class,actual_applied_code,actual_dac_epoch,downstream_epoch_exact,reason,active_policy_sha256,response_policy_sha256,actionable\r\n");
  char maintenance_header[kFrameCapacity] = {};
  if (otis_format_adaptive_hybrid_maintenance_v1_header(
          maintenance_header, sizeof(maintenance_header)) > 0)
    otis_transport_write_cstr(maintenance_header);
}

void otis_adaptive_hybrid_regulation_live_update_health(
    const OtisAdaptiveHybridRegulationLiveHealth *health, uint32_t now_s) {
  if (!initialized || health == nullptr) return;
  latest_health = *health;
  have_health = true;
  if (!transaction_bound && health->session_id != 0u) {
    const OtisRegulationBinding binding = expected_binding(health->session_id);
    otis_regulation_transaction_init(&transaction, &binding);
    transaction_bound = true;
  } else if (transaction_bound && !manual_start_confirmed) {
    otis_regulation_note_session(&transaction, health->session_id,
                                   manual_start_confirmed);
  }
  if (transaction_bound && manual_start_confirmed) {
    // The setup application acknowledgement is the first authoritative
    // confirmation. A periodic health message already in flight may still
    // contain the pre-setup "unknown" state, so absence cannot become loss
    // until periodic health has caught up and confirmed this exact code once.
    if (health->applied_code_confirmed &&
        health->applied_code == transaction.applied_code) {
      periodic_applied_code_confirmation_seen = true;
    } else if (periodic_applied_code_confirmation_seen &&
               !health->applied_code_confirmed) {
      otis_regulation_fault(&transaction, "confirmed_applied_code_lost");
    }
  }
  update_active_reference_and_integrity(now_s);
}

void otis_adaptive_hybrid_regulation_live_update_health_at_ticks(
    const OtisAdaptiveHybridRegulationLiveHealth *health, uint32_t now_s,
    uint64_t event_timestamp_ticks) {
  uint64_t extended_ticks = 0u;
  health_event_ticks_available =
      otis_frequency_regulation_live_extend_monotonic_us(event_timestamp_ticks,
                                                  &extended_ticks);
  health_event_timestamp_ticks =
      health_event_ticks_available ? extended_ticks : 0u;
  otis_adaptive_hybrid_regulation_live_update_health(health, now_s);
  health_event_ticks_available = false;
  health_event_timestamp_ticks = 0u;
}

void otis_adaptive_hybrid_regulation_live_service(uint32_t now_s) {
  update_active_reference_and_integrity(now_s);
  if (transaction_bound && transaction.state == OtisRegulationState::Armed &&
      transaction.have_arm && now_s > transaction.arm.expires_s)
    otis_regulation_fault(&transaction, "unused_authorization_expired");
  if (transaction_bound && evidence_phase != EvidencePhase::None &&
      static_cast<uint32_t>(now_s - evidence_pending_since_s) >
          kEvidenceAcknowledgementMaximumAgeS)
    otis_regulation_fault(&transaction,
                            "transaction_evidence_acknowledgement_timeout");
  if (transaction_bound &&
      (transaction.state == OtisRegulationState::Fault ||
       transaction.state == OtisRegulationState::Aborted) &&
      (hybrid_engine_ready
       ) &&
      hybrid_engine.state != OtisActiveHybridState::FailStatic)
    hybrid_fail_static(transaction.reason);
  if (transaction_bound &&
      (!otis_actuator_guard_check_deadline(
           &timing_actuator_guard, now_s) ||
       otis_dual_core_fail_static()))
    otis_regulation_fault(&transaction,
                            "cross_core_partition_or_actuator_guard_fault");
}

bool otis_adaptive_hybrid_regulation_live_capture_lease(uint32_t sequence, uint32_t now_s) {
  if (!initialized || sequence == 0u || sequence <= last_capture_lease_sequence)
    return false;
  last_capture_lease_sequence = sequence;
  last_capture_lease_s = now_s;
  have_capture_lease = true;
  return true;
}

bool otis_adaptive_hybrid_regulation_live_arm(uint32_t sequence, uint32_t nonce,
                               uint32_t expires_s, uint32_t now_s) {
  if (!initialized || !transaction_bound) return false;
  const OtisRegulationArmRequest arm = {
      transaction.expected_binding, sequence, nonce, expires_s};
  const OtisRegulationEligibility health = eligibility(now_s);
  return otis_regulation_arm(&transaction, &arm, &health, now_s);
}

void otis_adaptive_hybrid_regulation_live_abort(const char *reason) {
  if (transaction_bound) otis_regulation_abort(&transaction, reason);
  pending_actionable_request_valid = false;
  evidence_phase = EvidencePhase::None;
  evidence_request_sequence = 0u;
  otis_dependent_response_identity_reset(&dependent_response_identity);
  if (hybrid_engine_ready)
    hybrid_fail_static(reason == nullptr ? "operator_abort" : reason);
}

bool otis_adaptive_hybrid_regulation_live_acknowledge_evidence(uint32_t request_sequence,
                                                 uint32_t phase_sequence,
                                                 uint32_t now_s) {
  if (evidence_phase == EvidencePhase::None ||
      request_sequence != evidence_request_sequence ||
      phase_sequence != static_cast<uint32_t>(evidence_phase) ||
      frame.length != 0u)
    return false;
  if (evidence_phase == EvidencePhase::Request) {
    if (!transaction_bound || !pending_actionable_request_valid ||
        transaction.state != OtisRegulationState::RequestPending ||
        !pending_adaptive_hybrid_decision_valid ||
        pending_adaptive_hybrid_decision.decision_timestamp_ticks == 0u ||
        !critical_continuity_healthy(now_s)) {
      if (transaction_bound)
        otis_regulation_fault(
            &transaction, "pre_acceptance_evidence_or_continuity_invalid");
      pending_actionable_request_valid = false;
      return false;
    }
    const OtisCrossCoreActuatorRequest request =
        cross_core_request(pending_actionable_request, now_s);
    if (!otis_actuator_guard_start(&timing_actuator_guard, &request,
                                   now_s) ||
        !publish_cross_core_actuator_message(
            OtisCriticalMessageKind::ActuatorRequest, now_s)) {
      otis_regulation_fault(&transaction,
                              "cross_core_actuator_request_queue_fault");
      pending_actionable_request_valid = false;
      return false;
    }
    evidence_phase = EvidencePhase::None;
    evidence_pending_since_s = 0u;
    return true;
  }
  if (evidence_phase == EvidencePhase::Acceptance) {
    if (!transaction_bound || !pending_actionable_request_valid ||
        transaction.state !=
            OtisRegulationState::AcceptedAwaitingApplication ||
        timing_actuator_guard.state !=
            OtisActuatorGuardState::AwaitingApplication ||
        !critical_continuity_healthy(now_s) ||
        !publish_cross_core_actuator_message(
            OtisCriticalMessageKind::ActuatorExecute, now_s)) {
      otis_regulation_fault(
          &transaction, "cross_core_application_release_or_continuity_fault");
      pending_actionable_request_valid = false;
      return false;
    }
    evidence_phase = EvidencePhase::None;
    evidence_pending_since_s = 0u;
    return true;
  }
  if (evidence_phase == EvidencePhase::Response) {
    // ADAPTIVE_HYBRID commits response state with the atomic ACT/AHM burst. The
    // host phase-4 acknowledgement proves durable replay of that already
    // completed transition; it must not drive the ordinary controller again.
    if (!adaptive_hybrid_engine_ready || adaptive_hybrid_engine.response_pending ||
        pending_adaptive_hybrid_origin_valid) {
      otis_regulation_fault(
          &transaction, "adaptive_hybrid_response_evidence_acknowledgement_invalid");
      return false;
    }
  }
  evidence_phase = EvidencePhase::None;
  evidence_request_sequence = 0u;
  evidence_pending_since_s = 0u;
  return true;
}

bool otis_adaptive_hybrid_regulation_live_on_cross_core_ack(
    const OtisCrossCoreActuatorAck *acknowledgement, uint32_t now_s) {
  if (acknowledgement == nullptr || !transaction_bound ||
      !pending_actionable_request_valid) {
    if (transaction_bound)
      otis_regulation_fault(
          &transaction, "cross_core_actuator_acknowledgement_invalid");
    return false;
  }
  const bool exact_metadata_rejection_context =
      acknowledgement->kind == OtisActuatorAckKind::Rejected &&
      acknowledgement->rejection_reason ==
          OtisActuatorRejectionReason::MetadataHoldCancelledBeforeAcceptance &&
      gnss_metadata_hold_active && gnss_metadata_hold_transaction_pending &&
      transaction.state == OtisRegulationState::RequestPending &&
      transaction.have_request && !transaction.have_acceptance &&
      !transaction.have_application && evidence_phase == EvidencePhase::None &&
      timing_actuator_guard.state ==
          OtisActuatorGuardState::AwaitingAcceptance;
  if (exact_metadata_rejection_context) {
    uint64_t rejection_ticks = 0u;
    if (!otis_frequency_regulation_live_extend_monotonic_us(
            acknowledgement->acknowledgement_ticks, &rejection_ticks)) {
      otis_regulation_fault(
          &transaction, "core0_rejection_timestamp_projection_failed");
      return false;
    }
    if (!adaptive_hybrid_engine_ready || !adaptive_hybrid_engine.request_pending ||
        !pending_adaptive_hybrid_origin_valid ||
        !otis_dual_core_evidence_can_publish(3u)) {
      otis_regulation_fault(
          &transaction, "adaptive_hybrid_core0_rejection_origin_or_capacity_fault");
      return false;
    }
    const AdaptiveHybridLiveMutationSnapshot rejection_snapshot =
        capture_adaptive_hybrid_live_mutation_snapshot();
    const OtisAdaptiveHybridEngine rejection_before = adaptive_hybrid_engine;
    OtisAdaptiveHybridEngine rejection_after = rejection_before;
    if (!otis_adaptive_hybrid_engine_reject_or_expire_request(&rejection_after)) {
      otis_regulation_fault(
          &transaction, "adaptive_hybrid_core0_rejection_controller_transition_failed");
      return false;
    }
    const bool exact_guard_rejection =
        otis_actuator_guard_discard_exact_rejection(
            &timing_actuator_guard, acknowledgement,
            gnss_metadata_hold_applied_code);
    if (!exact_guard_rejection) {
      // Preserve the established fail-static path for a contradictory tuple.
      (void)otis_actuator_guard_acknowledge(&timing_actuator_guard,
                                             acknowledgement);
      otis_regulation_fault(
          &transaction, "gnss_metadata_core0_rejection_identity_mismatch");
      return false;
    }
    const OtisRegulationCore0RejectedOutcome rejected = {
        acknowledgement->request_sequence,
        acknowledgement->decision_sequence,
        acknowledgement->authorization_sequence,
        acknowledgement->nonce,
        acknowledgement->requested_code,
        acknowledgement->accepted_code,
        acknowledgement->applied_code,
        true,
        acknowledgement->rejection_reason ==
            OtisActuatorRejectionReason::MetadataHoldCancelledBeforeAcceptance,
        acknowledgement->i2c_ok,
        acknowledgement->clamped,
        acknowledgement->ambiguous,
    };
    if (!otis_regulation_discard_released_request_on_metadata_rejection(
            &transaction, &pending_actionable_request,
            &pending_actionable_request_valid, gnss_metadata_hold_active,
            &gnss_metadata_hold_transaction_pending, true,
            gnss_metadata_hold_applied_code, gnss_metadata_hold_dac_epoch,
            &rejected)) {
      otis_regulation_fault(
          &transaction, "gnss_metadata_core0_rejection_discard_failed");
      return false;
    }
    evidence_phase = EvidencePhase::None;
    evidence_request_sequence = 0u;
    evidence_pending_since_s = 0u;
    if (!begin_adaptive_hybrid_evidence_burst(2u) ||
        !queue_frame("request_withdrawn", rejection_ticks, nullptr, 0.0)) {
      restore_adaptive_hybrid_live_mutation_snapshot(rejection_snapshot);
      otis_regulation_fault(
          &transaction, "adaptive_hybrid_core0_rejection_evidence_queue_fault");
      return false;
    }
    const OtisAdaptiveHybridMaintenanceTransactionJoin rejection_join =
        adaptive_hybrid_current_transaction_join(
            OtisAdaptiveHybridMaintenanceTransactionEvent::RequestWithdrawn,
            pending_adaptive_hybrid_observation, pending_adaptive_hybrid_decision, false,
            false);
    if (!queue_adaptive_hybrid_maintenance_record(
            OtisAdaptiveHybridMaintenanceEvent::RequestRejectedOrExpired,
            rejection_ticks, rejection_before, rejection_after,
            &pending_adaptive_hybrid_observation, &pending_adaptive_hybrid_decision,
            &pending_adaptive_hybrid_hybrid_join, &rejection_join, 2u, 2u,
            rejection_after.last_reason) ||
        !commit_adaptive_hybrid_evidence_burst()) {
      restore_adaptive_hybrid_live_mutation_snapshot(rejection_snapshot);
      otis_regulation_fault(
          &transaction, "adaptive_hybrid_core0_rejection_burst_commit_failed");
      return false;
    }
    adaptive_hybrid_engine = rejection_after;
    pending_adaptive_hybrid_decision_valid = false;
    pending_adaptive_hybrid_origin_valid = false;
    const OtisAdaptiveHybridEngine hold_before = adaptive_hybrid_engine;
    OtisAdaptiveHybridEngine hold_after = hold_before;
    if (!otis_adaptive_hybrid_engine_enter_metadata_hold(&hold_after) ||
        !queue_adaptive_hybrid_single_async_transition(
            OtisAdaptiveHybridMaintenanceEvent::GnssMetadataHoldEnter,
            rejection_ticks, hold_before, hold_after,
            hold_after.last_reason)) {
      otis_regulation_fault(
          &transaction, "adaptive_hybrid_core0_rejection_metadata_hold_evidence_fault");
      return false;
    }
    adaptive_hybrid_engine = hold_after;
    if (transaction.state != OtisRegulationState::Disarmed ||
        transaction.applied_code != gnss_metadata_hold_applied_code ||
        transaction.dac_epoch != gnss_metadata_hold_dac_epoch) {
      otis_regulation_fault(
          &transaction, "core0_rejection_withdrawal_identity_changed");
      return false;
    }
    if (!otis_regulation_reference_hold(
            &transaction, "gnss_metadata_unqualified_hold") ||
        transaction.applied_code != gnss_metadata_hold_applied_code ||
        transaction.dac_epoch != gnss_metadata_hold_dac_epoch) {
      otis_regulation_fault(
          &transaction, "core0_rejection_reference_hold_failed");
      return false;
    }
    return true;
  }
  const bool guard_acknowledged = otis_actuator_guard_acknowledge(
      &timing_actuator_guard, acknowledgement);
  if (acknowledgement->kind == OtisActuatorAckKind::Accepted) {
    uint64_t acceptance_ticks = 0u;
    if (!otis_frequency_regulation_live_extend_monotonic_us(
            acknowledgement->acknowledgement_ticks, &acceptance_ticks)) {
      otis_regulation_fault(
          &transaction, "core0_acceptance_timestamp_projection_failed");
      return false;
    }
    if (!guard_acknowledged) {
      otis_regulation_fault(
          &transaction, "cross_core_acceptance_acknowledgement_invalid");
      return false;
    }
    OtisRegulationAcceptedRequest accepted;
    if (!otis_regulation_accept(&transaction,
                                  &pending_actionable_request, now_s,
                                  &accepted))
      return false;
    evidence_phase = EvidencePhase::Acceptance;
    evidence_request_sequence = pending_actionable_request.request_sequence;
    evidence_pending_since_s = now_s;
    if (!queue_frame("request_accepted", acceptance_ticks, nullptr, 0.0)) {
      otis_regulation_fault(&transaction,
                              "acceptance_evidence_queue_fault");
      return false;
    }
    return true;
  }
  if (acknowledgement->kind != OtisActuatorAckKind::Applied) {
    otis_regulation_fault(&transaction,
                            "cross_core_actuator_rejected_or_bad_phase");
    return false;
  }
  uint64_t application_ticks = acknowledgement->acknowledgement_ticks;
  if (!otis_frequency_regulation_live_extend_monotonic_us(
          acknowledgement->acknowledgement_ticks, &application_ticks)) {
    otis_regulation_fault(
        &transaction, "cross_core_application_timestamp_projection_failed");
    return false;
  }
  const OtisRegulationAppliedAck applied = {
      acknowledgement->request_sequence,
      acknowledgement->authorization_sequence,
      acknowledgement->nonce,
      acknowledgement->requested_code,
      acknowledgement->accepted_code,
      acknowledgement->applied_code,
      pending_actionable_request.correction_ordinal,
      now_s,
      acknowledgement->i2c_ok,
      acknowledgement->clamped,
      acknowledgement->ambiguous,
  };
  const bool transaction_acknowledged =
      otis_regulation_acknowledge_application(&transaction, &applied);
  const bool acknowledged = guard_acknowledged && transaction_acknowledged;
  if (!guard_acknowledged)
    otis_regulation_fault(
        &transaction, "cross_core_application_acknowledgement_invalid");
  deferred_application_outcome = {};
  deferred_application_outcome.application_attempted = true;
  deferred_application_outcome.request_sequence =
      acknowledgement->request_sequence;
  deferred_application_outcome.dac_epoch = transaction.dac_epoch;
  deferred_application_outcome.application_timestamp_ticks =
      application_ticks;
  deferred_application_outcome.capture_session =
      transaction.expected_binding.session_id;
  deferred_application_outcome.requested_code =
      acknowledgement->requested_code;
  deferred_application_outcome.applied_code = acknowledgement->applied_code;
  deferred_application_outcome.applied = acknowledged;
  deferred_application_outcome.faulted = !acknowledged;
  deferred_application_outcome.reason = transaction.reason;
  deferred_application_outcome_valid = true;
  last_application_acknowledged = acknowledged;
  pending_application_timestamp_ticks =
      application_ticks;
  if (acknowledged) {
    latest_health.applied_code = transaction.applied_code;
    latest_health.applied_code_confirmed = true;
  }
  pending_actionable_request_valid = false;
  evidence_phase = EvidencePhase::Application;
  evidence_pending_since_s = now_s;
  return acknowledged;
}

bool otis_adaptive_hybrid_regulation_live_manual_start_allowed(uint16_t code) {
  return initialized && code == OTIS_ADAPTIVE_HYBRID_START_CODE &&
         !manual_start_confirmed &&
         transaction_bound &&
         (!transaction_bound ||
          (transaction.state == OtisRegulationState::Disarmed &&
           transaction.correction_count == 0u && !transaction.have_request));
}

bool otis_adaptive_hybrid_regulation_live_note_manual_start_exact(
    uint16_t code, uint32_t dac_epoch, bool i2c_ok, uint32_t now_s,
    uint64_t setup_application_ticks, uint32_t capture_session) {
  if (!otis_adaptive_hybrid_regulation_live_manual_start_allowed(code) || !i2c_ok ||
      dac_epoch != 1u || setup_application_ticks == 0u || capture_session == 0u ||
      capture_session != transaction.expected_binding.session_id ||
      now_s != setup_application_ticks / kCaptureTicksPerSecond) {
    if (transaction_bound)
      otis_regulation_fault(&transaction, "manual_start_establishment_failed");
    return false;
  }
  const OtisRegulationTransaction prior_transaction = transaction;
  manual_start_confirmed = true;
  periodic_applied_code_confirmation_seen = false;
  transaction.applied_code = code;
  transaction.dac_epoch = dac_epoch;
  transaction.last_application_s = now_s;
  transaction.have_last_application = true;
  if (!queue_manual_start_frame(code, true, now_s, setup_application_ticks,
                                capture_session)) {
    transaction = prior_transaction;
    manual_start_confirmed = false;
    otis_regulation_fault(&transaction, "manual_start_evidence_queue_fault");
    return false;
  }
  return true;
}

bool otis_adaptive_hybrid_regulation_live_confirm_setup_consumers_exact(
    uint16_t applied_code, uint32_t dac_epoch,
    uint64_t setup_application_ticks, uint32_t capture_session) {
  if (!transaction_bound || !manual_start_confirmed ||
      !transaction.have_last_application || setup_application_ticks == 0u ||
      capture_session != transaction.expected_binding.session_id ||
      applied_code != OTIS_ADAPTIVE_HYBRID_START_CODE || dac_epoch != 1u ||
      transaction.applied_code != applied_code ||
      transaction.dac_epoch != dac_epoch ||
      !otis_frequency_regulation_live_applied_epoch_exact(applied_code, dac_epoch)) {
    if (transaction_bound)
      otis_regulation_fault(
          &transaction, "active_hybrid_setup_consumer_epoch_or_tick_mismatch");
    return false;
  }
  OtisPhasePreviewLiveStatus phase = {};
  otis_phase_preview_live_get_status(&phase);
  if (!phase.initialized || !phase.applied_code_bound ||
      phase.applied_code != applied_code || phase.dac_epoch != dac_epoch) {
    otis_regulation_fault(&transaction,
                            "active_hybrid_setup_phase_epoch_mismatch");
    return false;
  }
  setup_application_timestamp_ticks = setup_application_ticks;
  transaction.last_application_s = static_cast<uint32_t>(
      setup_application_ticks / kCaptureTicksPerSecond);
  const OtisAdaptiveHybridPolicy adaptive_hybrid_policy = otis_adaptive_hybrid_default_policy();
  adaptive_hybrid_engine = {};
  if (!otis_adaptive_hybrid_engine_init(
          &adaptive_hybrid_engine, &adaptive_hybrid_policy, applied_code, dac_epoch)) {
    otis_regulation_fault(&transaction,
                            "adaptive_hybrid_setup_controller_initialization_failed");
    return false;
  }
  if (!otis_adaptive_hybrid_engine_bind_exact_setup_application(
          &adaptive_hybrid_engine, setup_application_ticks)) {
    otis_regulation_fault(
        &transaction, "adaptive_hybrid_setup_application_binding_failed");
    return false;
  }
  const OtisAdaptiveHybridEngine activation_before = adaptive_hybrid_engine;
  OtisAdaptiveHybridEngine activation_after = activation_before;
  if (!otis_adaptive_hybrid_engine_new_policy_activation(&activation_after) ||
      !begin_adaptive_hybrid_evidence_burst(1u) ||
      !queue_adaptive_hybrid_maintenance_record(
          OtisAdaptiveHybridMaintenanceEvent::PolicyActivation,
          setup_application_ticks, activation_before, activation_after,
          nullptr, nullptr, nullptr, nullptr, 1u, 1u,
          activation_after.last_reason) ||
      !commit_adaptive_hybrid_evidence_burst()) {
    abandon_adaptive_hybrid_evidence_burst();
    otis_regulation_fault(
        &transaction, "adaptive_hybrid_policy_activation_evidence_queue_fault");
    return false;
  }
  adaptive_hybrid_engine = activation_after;
  adaptive_hybrid_engine_ready = true;
  hybrid_engine = {};
  hybrid_engine_ready = false;
  return true;
}

static void adaptive_hybrid_active_live_on_decision_impl(
    const OtisAdaptiveHybridRegulationLiveDecision &source,
    uint64_t decision_timestamp_ticks,
    OtisAdaptiveHybridRegulationLiveOutcome *outcome) {
  if (!adaptive_hybrid_engine_ready) {
    otis_regulation_fault(
        &transaction, "adaptive_hybrid_setup_consumers_not_confirmed");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  if (decision_timestamp_ticks == 0u ||
      source.timestamp_s !=
          decision_timestamp_ticks / kCaptureTicksPerSecond) {
    otis_regulation_fault(
        &transaction, "adaptive_hybrid_decision_timestamp_domain_mismatch");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }

  OtisRegulationEligibility health = eligibility(source.timestamp_s);
  health.estimator_valid = source.measurement_valid;
  health.model_applicable = source.model_applicable;
  const bool completing_response =
      transaction.state == OtisRegulationState::AwaitingResponse;
  if (completing_response) {
    // Metadata qualifies admission of a new correction. It cannot erase the
    // exact D14/D8 response needed to close an already applied transaction.
    health.gnss_metadata_valid = true;
    health.gnss_identity_stable = true;
    health.gnss_3d_evidence = true;
  }
  const bool phase_valid =
      source.phase_recorder_published && source.phase_continuous &&
      source.phase_current && !source.phase_step_detected &&
      source.phase_dac_epoch == source.dac_epoch &&
      source.phase_applied_code == source.current_applied_code;
  const bool metadata_qualified =
      completing_response ||
      (health.gnss_metadata_valid && health.gnss_identity_stable &&
       health.gnss_3d_evidence);
  const bool authority_valid =
      strcmp(OTIS_BUILD_IMAGE_ID, kExpectedImage) == 0 &&
      source.capture_session == transaction.expected_binding.session_id &&
      source.measurement_valid && source.model_applicable &&
      health.raw_pps_valid && health.count_valid &&
      health.applied_code_confirmed &&
      latest_health.applied_code == source.current_applied_code &&
      health.capture_owner_live && health.abort_path_live &&
      latest_health.reference_integrity_valid;

  OtisAdaptiveHybridObservation observation = {};
  observation.timestamp_s = source.timestamp_s;
  observation.capture_session = source.capture_session;
  observation.source_first_sequence = source.source_first_sequence;
  observation.source_last_sequence = source.source_last_sequence;
  observation.dac_epoch = source.dac_epoch;
  observation.applied_code = source.current_applied_code;
  observation.accumulated_edge_error_counts =
      source.accumulated_edge_error_counts;
  observation.tight_inside =
      source.tight_state != nullptr &&
      strcmp(source.tight_state, "TIGHT_INSIDE") == 0;
  observation.phase_epoch = source.phase_epoch;
  observation.relative_phase_cycles = source.relative_phase_cycles;
  observation.selected_estimator_identity =
      kAdaptiveHybridEstimatorIdentity;
  observation.phase_valid = phase_valid;
  observation.authority_valid = authority_valid;
  observation.settled = source.preview_available;
  observation.cadence_eligible =
      transaction.state == OtisRegulationState::Armed &&
      !(gnss_metadata_hold_active && adaptive_hybrid_engine.metadata_requalified);
  observation.metadata_qualified = metadata_qualified;
  observation.timestamp_ticks = decision_timestamp_ticks;

  const OtisAdaptiveHybridEngine engine_before = adaptive_hybrid_engine;
  OtisAdaptiveHybridEngine engine_after = engine_before;
  OtisAdaptiveHybridDecision native_decision = {};
  if (!otis_adaptive_hybrid_engine_decide(
          &engine_after, &observation, &native_decision)) {
    otis_regulation_fault(&transaction,
                            "adaptive_hybrid_native_decision_failed");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }

  const bool native_fail_transition =
      engine_before.fail_static_reason == nullptr &&
      engine_after.fail_static_reason != nullptr;
  const bool request_producing_decision =
      native_decision.requested_delta_codes != 0;
  // An AwaitingResponse transaction deliberately makes cadence_eligible
  // false above.  It may close the pending response on this boundary, but it
  // must not create the next request in the same producer frontier.
  if (completing_response && request_producing_decision) {
    otis_regulation_fault(
        &transaction, "adaptive_hybrid_response_and_request_overlap_fault");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  if (request_producing_decision !=
      (!engine_before.request_pending && engine_after.request_pending)) {
    otis_regulation_fault(&transaction,
                            "adaptive_hybrid_request_transition_invariant_fault");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  const uint8_t decision_burst_count =
      request_producing_decision
          ? OTIS_ADAPTIVE_HYBRID_REQUEST_DECISION_EVIDENCE_COUNT
          : OTIS_ADAPTIVE_HYBRID_RESPONSE_DECISION_EVIDENCE_COUNT;
  // A native fail transition is terminal at this boundary and returns before
  // response completion below.  These follow-up bursts are therefore
  // mutually exclusive by control flow, not merely by observed history.
  const uint8_t followup_burst_count =
      native_fail_transition
          ? OTIS_ADAPTIVE_HYBRID_FAIL_TRANSITION_EVIDENCE_COUNT
          : (completing_response
                 ? OTIS_ADAPTIVE_HYBRID_RESPONSE_COMPLETION_EVIDENCE_COUNT
                 : 0u);
  const uint8_t total_capacity = static_cast<uint8_t>(
      decision_burst_count + followup_burst_count);
  // Preview has already queued this boundary's three-record prefix.  Reserve
  // the active lifecycle and its guaranteed trailing CTL before committing
  // any part of the lifecycle, so queue pressure cannot reproduce Attempt 7's
  // complete request followed by a missing CTL.
  const uint8_t required_capacity = static_cast<uint8_t>(
      total_capacity + OTIS_ADAPTIVE_HYBRID_SELECTED_EVIDENCE_SUFFIX_COUNT);
  if (required_capacity > OTIS_EVIDENCE_QUEUE_DEPTH ||
      !otis_dual_core_evidence_can_publish(required_capacity)) {
    otis_dual_core_latch_fault(OtisPartitionFault::EvidenceExhausted);
    otis_regulation_fault(&transaction,
                            "adaptive_hybrid_combined_evidence_capacity_fault");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }

  const AdaptiveHybridLiveMutationSnapshot decision_snapshot =
      capture_adaptive_hybrid_live_mutation_snapshot();
  OtisAdaptiveHybridRegulationLiveDecision projected_source = source;
  projected_source.decision_sequence =
      static_cast<uint32_t>(native_decision.decision_sequence);
  projected_source.requested_delta_codes =
      native_decision.requested_delta_codes;
  projected_source.requested_code =
      static_cast<uint16_t>(native_decision.requested_code);
  projected_source.control_eligible =
      request_producing_decision;
  projected_source.preview_available = true;
  const OtisActiveHybridDecision projected_decision =
      adaptive_hybrid_project_hybrid_decision(
          engine_before, engine_after, native_decision, phase_valid,
          source.timestamp_s);

  if (!begin_adaptive_hybrid_evidence_burst(decision_burst_count) ||
      !queue_active_hybrid_decision(
          projected_source, projected_decision,
          decision_timestamp_ticks)) {
    restore_adaptive_hybrid_live_mutation_snapshot(decision_snapshot);
    otis_regulation_fault(&transaction,
                            "adaptive_hybrid_decision_evidence_queue_fault");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  const OtisAdaptiveHybridMaintenanceHybridJoin hybrid_join =
      adaptive_hybrid_current_hybrid_join(
          observation, native_decision,
          source.phase_observation_sequence);

  OtisAdaptiveHybridMaintenanceTransactionJoin request_join = {};
  const OtisAdaptiveHybridMaintenanceTransactionJoin *request_join_pointer = nullptr;
  const OtisRegulationDecision request_input = {
      projected_source.decision_sequence,
      projected_source.source_first_sequence,
      projected_source.source_last_sequence,
      projected_source.timestamp_s,
      projected_source.current_applied_code,
      projected_source.requested_delta_codes,
      projected_source.requested_code,
      projected_source.frequency_error_hz,
  };
  if (request_producing_decision) {
    OtisRegulationActionableRequest request = {};
    if (transaction.state != OtisRegulationState::Armed ||
        !otis_regulation_make_request(
            &transaction, &request_input, &health,
            source.timestamp_s, &request)) {
      restore_adaptive_hybrid_live_mutation_snapshot(decision_snapshot);
      otis_regulation_fault(&transaction,
                              "adaptive_hybrid_transaction_request_creation_failed");
      outcome->faulted = true;
      outcome->reason = transaction.reason;
      return;
    }
    pending_actionable_request = request;
    pending_actionable_request_valid = true;
    evidence_phase = EvidencePhase::Request;
    evidence_request_sequence = request.request_sequence;
    evidence_pending_since_s = source.timestamp_s;
    if (!queue_frame("request_created", decision_timestamp_ticks,
                     nullptr, 0.0)) {
      restore_adaptive_hybrid_live_mutation_snapshot(decision_snapshot);
      otis_regulation_fault(&transaction,
                              "adaptive_hybrid_request_evidence_queue_fault");
      outcome->faulted = true;
      outcome->reason = transaction.reason;
      return;
    }
    request_join = adaptive_hybrid_current_transaction_join(
        OtisAdaptiveHybridMaintenanceTransactionEvent::RequestCreated,
        observation, native_decision, false, false);
    request_join_pointer = &request_join;
  } else if (transaction.state == OtisRegulationState::Armed) {
    OtisRegulationActionableRequest unused = {};
    const bool unexpected_request = otis_regulation_make_request(
        &transaction, &request_input, &health, source.timestamp_s,
        &unused);
    if (unexpected_request ||
        transaction.state != OtisRegulationState::Disarmed) {
      restore_adaptive_hybrid_live_mutation_snapshot(decision_snapshot);
      otis_regulation_fault(
          &transaction, "adaptive_hybrid_zero_delta_arm_consumption_failed");
      outcome->faulted = true;
      outcome->reason = transaction.reason;
      return;
    }
  }

  if (!queue_adaptive_hybrid_maintenance_record(
          OtisAdaptiveHybridMaintenanceEvent::Decision,
          decision_timestamp_ticks, engine_before, engine_after,
          &observation, &native_decision, &hybrid_join,
          request_join_pointer, decision_burst_count,
          decision_burst_count, native_decision.reason) ||
      !commit_adaptive_hybrid_evidence_burst()) {
    restore_adaptive_hybrid_live_mutation_snapshot(decision_snapshot);
    otis_regulation_fault(&transaction,
                            "adaptive_hybrid_decision_burst_commit_failed");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }

  adaptive_hybrid_engine = engine_after;
  last_adaptive_hybrid_observation = observation;
  last_adaptive_hybrid_decision = native_decision;
  last_adaptive_hybrid_hybrid_join = hybrid_join;
  last_adaptive_hybrid_origin_valid = true;
  if (engine_before.metadata_hold && !engine_after.metadata_hold) {
    if (!gnss_metadata_hold_active ||
        engine_before.requalification_window_count != 1u ||
        engine_after.requalification_window_count != 2u ||
        transaction.state != OtisRegulationState::ReferenceHold ||
        !otis_regulation_reference_requalify(
            &transaction, transaction.expected_binding.session_id)) {
      otis_regulation_fault(
          &transaction, "adaptive_hybrid_metadata_two_window_release_failed");
      outcome->faulted = true;
      outcome->reason = transaction.reason;
      return;
    }
    gnss_metadata_hold_active = false;
    gnss_metadata_hold_transaction_pending = false;
  }
  if (request_producing_decision) {
    pending_adaptive_hybrid_decision = native_decision;
    pending_adaptive_hybrid_decision_valid = true;
    pending_adaptive_hybrid_observation = observation;
    pending_adaptive_hybrid_hybrid_join = hybrid_join;
    pending_adaptive_hybrid_origin_valid = true;
    outcome->request_created = true;
    outcome->request_sequence = transaction.request.request_sequence;
    outcome->requested_code = transaction.request.requested_code;
    outcome->applied_code = transaction.applied_code;
  }
  outcome->reason = native_decision.reason;

  if (native_fail_transition) {
    const AdaptiveHybridLiveMutationSnapshot fail_snapshot =
        capture_adaptive_hybrid_live_mutation_snapshot();
    if (!begin_adaptive_hybrid_evidence_burst(1u) ||
        !queue_adaptive_hybrid_maintenance_record(
            OtisAdaptiveHybridMaintenanceEvent::FailStatic,
            decision_timestamp_ticks, engine_before, engine_after,
            &observation, &native_decision, &hybrid_join, nullptr,
            1u, 1u, engine_after.fail_static_reason) ||
        !commit_adaptive_hybrid_evidence_burst()) {
      restore_adaptive_hybrid_live_mutation_snapshot(fail_snapshot);
      otis_regulation_fault(&transaction,
                              "adaptive_hybrid_fail_static_evidence_queue_fault");
      outcome->faulted = true;
      outcome->reason = transaction.reason;
      return;
    }
    const bool controller_inhibit =
        strcmp(engine_after.fail_static_reason,
               "prospective_repeated_alternation") == 0 ||
        strcmp(engine_after.fail_static_reason,
               "prospective_low_efficiency_path") == 0;
    if (!controller_inhibit) {
      otis_regulation_fault(&transaction,
                              engine_after.fail_static_reason);
      outcome->faulted = true;
      outcome->reason = transaction.reason;
    }
    return;
  }

  if (!completing_response) return;
  if (!pending_adaptive_hybrid_origin_valid ||
      !adaptive_hybrid_engine.response_pending) {
    otis_regulation_fault(
        &transaction, "adaptive_hybrid_response_origin_or_state_missing");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }

  const AdaptiveHybridLiveMutationSnapshot response_snapshot =
      capture_adaptive_hybrid_live_mutation_snapshot();
  const OtisAdaptiveHybridEngine response_before = adaptive_hybrid_engine;
  OtisAdaptiveHybridEngine response_after = response_before;
  OtisRegulationResponseResult response = {};
  const bool measurement_healthy =
      source.measurement_valid &&
      otis_regulation_response_measurement_valid(&health);
  const bool response_accepted = otis_regulation_record_response(
      &transaction, source.frequency_error_hz, measurement_healthy,
      otis_regulation_eligibility_valid(&health), &response);
  if (!response_accepted ||
      !otis_adaptive_hybrid_engine_complete_response(&response_after, true)) {
    restore_adaptive_hybrid_live_mutation_snapshot(response_snapshot);
    otis_regulation_fault(
        &transaction, "adaptive_hybrid_response_checkpoint_failed");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  evidence_phase = EvidencePhase::Response;
  evidence_request_sequence = transaction.request.request_sequence;
  evidence_pending_since_s = source.timestamp_s;
  if (!begin_adaptive_hybrid_evidence_burst(2u) ||
      !queue_frame("response", decision_timestamp_ticks, &response,
                   source.frequency_error_hz)) {
    restore_adaptive_hybrid_live_mutation_snapshot(response_snapshot);
    otis_regulation_fault(&transaction,
                            "adaptive_hybrid_response_evidence_queue_fault");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  const OtisAdaptiveHybridMaintenanceTransactionJoin response_join =
      adaptive_hybrid_current_transaction_join(
          OtisAdaptiveHybridMaintenanceTransactionEvent::Response,
          pending_adaptive_hybrid_observation, pending_adaptive_hybrid_decision, true, true);
  if (!queue_adaptive_hybrid_maintenance_record(
          OtisAdaptiveHybridMaintenanceEvent::ResponseComplete,
          decision_timestamp_ticks, response_before, response_after,
          &pending_adaptive_hybrid_observation, &pending_adaptive_hybrid_decision,
          &pending_adaptive_hybrid_hybrid_join, &response_join, 2u, 2u,
          response_after.last_reason) ||
      !otis_dependent_response_identity_retain(
          &dependent_response_identity, transaction.request.request_sequence,
          transaction.applied.application_sequence,
          otis_regulation_response_class_name(response.classification)) ||
      !commit_adaptive_hybrid_evidence_burst()) {
    restore_adaptive_hybrid_live_mutation_snapshot(response_snapshot);
    otis_regulation_fault(&transaction,
                            "adaptive_hybrid_response_burst_commit_failed");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  adaptive_hybrid_engine = response_after;
  pending_adaptive_hybrid_decision_valid = false;
  pending_adaptive_hybrid_origin_valid = false;
  outcome->response_recorded = true;
  outcome->response_class = response.classification;
  outcome->reason = response.reason;
}

static void active_live_on_decision_impl(
    const OtisAdaptiveHybridRegulationLiveDecision *decision,
    bool decision_ticks_available, uint64_t decision_timestamp_ticks,
    OtisAdaptiveHybridRegulationLiveOutcome *outcome) {
  if (outcome != nullptr) *outcome = {};
  if (!initialized || !transaction_bound || decision == nullptr ||
      outcome == nullptr)
    return;
  if (!decision_ticks_available) {
    otis_regulation_fault(
        &transaction, "exact_long_run_decision_timestamp_unavailable");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  adaptive_hybrid_active_live_on_decision_impl(
      *decision, decision_timestamp_ticks, outcome);
  return;
  outcome->reason = transaction.reason;
  OtisRegulationEligibility health = eligibility(decision->timestamp_s);
  // The completed selected estimate is created in this boundary callback;
  // the periodic health snapshot necessarily trails it by one service loop.
  health.estimator_valid = decision->measurement_valid;
  health.model_applicable = decision->model_applicable;
  const bool completing_response_during_metadata_hold =
      gnss_metadata_hold_active &&
      transaction.state == OtisRegulationState::AwaitingResponse;
  if (completing_response_during_metadata_hold) {
    // Metadata qualifies admission of a new correction, not the canonical
    // D14/D8 observation needed to finish an already applied transaction.
    health.gnss_metadata_valid = true;
    health.gnss_identity_stable = true;
    health.gnss_3d_evidence = true;
  } else if (gnss_metadata_hold_active) {
    outcome->reason = "gnss_metadata_hold_no_new_request";
    return;
  }
  const OtisAdaptiveHybridRegulationLiveDecision *effective_decision = decision;
  OtisAdaptiveHybridRegulationLiveDecision hybrid_source = *decision;
  OtisActiveHybridDecision hybrid_decision = {};
  if (!hybrid_engine_ready) {
    otis_regulation_fault(
        &transaction, "active_hybrid_setup_consumers_not_confirmed");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  const bool common_health_clean =
      decision->measurement_valid && decision->model_applicable &&
      (completing_response_during_metadata_hold ||
       (health.gnss_metadata_valid && health.gnss_identity_stable &&
        health.gnss_3d_evidence)) &&
      health.raw_pps_valid && health.count_valid &&
      health.applied_code_confirmed && health.capture_owner_live &&
      health.abort_path_live && latest_health.reference_integrity_valid &&
      decision->phase_recorder_published;
  const bool downstream_phase_epoch_exact =
      decision->phase_recorder_published &&
      decision->phase_dac_epoch == decision->dac_epoch &&
      decision->phase_applied_code == decision->current_applied_code;
  const OtisActiveHybridObservation hybrid_input = {
      decision->timestamp_s,
      decision->capture_session,
      decision->source_first_sequence,
      decision->source_last_sequence,
      decision->dac_epoch,
      decision->current_applied_code,
      decision->frequency_error_hz,
      decision->accumulated_edge_error_counts,
      decision->tight_state,
      decision->phase_epoch,
      decision->phase_observation_sequence,
      decision->relative_phase_cycles,
      decision->phase_dac_epoch,
      decision->phase_applied_code,
      decision->phase_continuous,
      decision->phase_current,
      decision->phase_step_detected,
      strcmp(OTIS_BUILD_IMAGE_ID, kExpectedImage) == 0 &&
          decision->capture_session ==
              transaction.expected_binding.session_id,
      common_health_clean,
      downstream_phase_epoch_exact,
      hybrid_engine.transaction_outstanding,
      transaction.state == OtisRegulationState::AwaitingResponse,
  };
  const bool hybrid_decided =
      decision_ticks_available &&
      otis_active_hybrid_engine_decide_at_ticks(
          &hybrid_engine, &hybrid_input, decision_timestamp_ticks,
          &hybrid_decision);
  if (!hybrid_decided) {
    hybrid_fail_static("active_hybrid_decision_timing_or_input_fault");
    otis_regulation_fault(
        &transaction, "active_hybrid_decision_timing_or_input_fault");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  if (!queue_active_hybrid_decision(*decision, hybrid_decision,
                                    decision_timestamp_ticks)) {
    hybrid_fail_static("active_hybrid_decision_evidence_queue_fault");
    otis_regulation_fault(
        &transaction, "active_hybrid_decision_evidence_queue_fault");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  if (hybrid_engine.state == OtisActiveHybridState::FailStatic) {
    otis_regulation_fault(&transaction, hybrid_decision.reason);
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  hybrid_source.decision_sequence = hybrid_decision.decision_sequence;
  hybrid_source.requested_delta_codes =
      hybrid_decision.requested_delta_codes;
  hybrid_source.requested_code = hybrid_decision.requested_code;
  hybrid_source.control_eligible =
      hybrid_decision.requested_delta_codes != 0;
  hybrid_source.preview_available = true;
  effective_decision = &hybrid_source;
  if (transaction.state == OtisRegulationState::AwaitingResponse) {
    OtisRegulationResponseResult response;
    const bool measurement_healthy =
        decision->measurement_valid &&
        otis_regulation_response_measurement_valid(&health);
    // A selected response can arrive while the preview engine is still in its
    // post-application SETTLE_PREVIEW state. Preview actionability gates a new request,
    // not acceptance of an already-completed response.  The full live health
    // and model-applicability contract is the post-response eligibility gate.
    const bool control_eligible_after_response =
        otis_regulation_eligibility_valid(&health);
    const bool accepted = otis_regulation_record_response(
        &transaction, decision->frequency_error_hz,
        measurement_healthy, control_eligible_after_response,
        &response);
    outcome->response_recorded = true;
    outcome->response_class = response.classification;
    outcome->reason = response.reason;
    outcome->faulted = !accepted;
    evidence_phase = EvidencePhase::Response;
    evidence_request_sequence = transaction.request.request_sequence;
    evidence_pending_since_s = decision->timestamp_s;
    pending_hybrid_response_class = response.classification;
    pending_hybrid_response_valid = true;
    pending_hybrid_predicted_sign_observed =
        response.observed_response_hz *
            static_cast<double>(transaction.request.requested_delta_codes) >
        0.0;
    if (!queue_frame("response", decision_timestamp_ticks, &response,
                     decision->frequency_error_hz)) {
      otis_regulation_fault(&transaction, "response_evidence_queue_fault");
      outcome->faulted = true;
      outcome->reason = transaction.reason;
    }
    return;
  }
  if (transaction.state != OtisRegulationState::Armed) return;
  const OtisRegulationDecision request_input = {
      effective_decision->decision_sequence,
      effective_decision->source_first_sequence,
      effective_decision->source_last_sequence,
      effective_decision->timestamp_s,
      effective_decision->current_applied_code,
      effective_decision->requested_delta_codes,
      effective_decision->requested_code,
      effective_decision->frequency_error_hz,
  };
  OtisRegulationActionableRequest request;
  // A short-lived arm is issued before the next 600 s observation is known.
  // If that observation enters or retains the tight band, the regulator
  // emits an exact zero-delta hold.  Consume the one-shot arm by passing that
  // zero through the transaction guard, which disarms without producing a
  // request.  A non-zero ineligible delta would be authority contamination.
  if (!effective_decision->control_eligible &&
      effective_decision->requested_delta_codes != 0) {
    otis_regulation_fault(
        &transaction, "tight_deadband_ineligible_nonzero_delta");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  const bool request_created = otis_regulation_make_request(
      &transaction, &request_input, &health,
      effective_decision->timestamp_s, &request);
  if (!request_created) {
    outcome->faulted = transaction.state == OtisRegulationState::Fault;
    outcome->reason = transaction.reason;
    return;
  }
  OtisRegulationAcceptedRequest accepted;
  pending_actionable_request = request;
  pending_actionable_request_valid = true;
  estimator_history_reset = false;
  pending_hybrid_decision = hybrid_decision;
  pending_hybrid_decision_valid = true;
  outcome->request_created = true;
  outcome->request_sequence = request.request_sequence;
  outcome->requested_code = request.requested_code;
  outcome->applied_code = transaction.applied_code;
  outcome->applied = false;
  outcome->faulted = false;
  outcome->reason = transaction.reason;
  evidence_phase = EvidencePhase::Request;
  evidence_request_sequence = request.request_sequence;
  evidence_pending_since_s = effective_decision->timestamp_s;
  if (!queue_frame("request_created", decision_timestamp_ticks,
                   nullptr, 0.0)) {
    pending_actionable_request_valid = false;
    otis_regulation_fault(&transaction, "request_evidence_queue_fault");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
  }
}

void otis_adaptive_hybrid_regulation_live_on_decision(
    const OtisAdaptiveHybridRegulationLiveDecision *decision,
    OtisAdaptiveHybridRegulationLiveOutcome *outcome) {
  active_live_on_decision_impl(decision, false, 0u, outcome);
}

void otis_adaptive_hybrid_regulation_live_on_decision_at_ticks(
    const OtisAdaptiveHybridRegulationLiveDecision *decision,
    uint64_t decision_timestamp_ticks, OtisAdaptiveHybridRegulationLiveOutcome *outcome) {
  active_live_on_decision_impl(decision, true, decision_timestamp_ticks,
                               outcome);
}

bool otis_adaptive_hybrid_regulation_live_take_application_outcome(
    OtisAdaptiveHybridRegulationLiveOutcome *outcome) {
  if (outcome == nullptr || !deferred_application_outcome_valid) return false;
  *outcome = deferred_application_outcome;
  deferred_application_outcome_valid = false;
  return true;
}

bool otis_adaptive_hybrid_regulation_live_complete_application_evidence(
    uint32_t request_sequence, bool history_reset, uint32_t now_s) {
  if (evidence_phase != EvidencePhase::Application ||
      request_sequence != evidence_request_sequence || frame.length != 0u)
    return false;
  estimator_history_reset = last_application_acknowledged && history_reset;
  if (last_application_acknowledged && !estimator_history_reset)
    otis_regulation_fault(&transaction,
                            "estimator_history_reset_not_confirmed");
  OtisPhasePreviewLiveStatus adaptive_hybrid_phase = {};
  otis_phase_preview_live_get_status(&adaptive_hybrid_phase);
  const bool adaptive_hybrid_downstream_epoch_exact =
      last_application_acknowledged && estimator_history_reset &&
      otis_frequency_regulation_live_applied_epoch_exact(
          transaction.applied_code, transaction.dac_epoch) &&
      adaptive_hybrid_phase.initialized && adaptive_hybrid_phase.applied_code_bound &&
      adaptive_hybrid_phase.applied_code == transaction.applied_code &&
      adaptive_hybrid_phase.dac_epoch == transaction.dac_epoch;
  if (!adaptive_hybrid_engine_ready || !pending_adaptive_hybrid_decision_valid ||
      !pending_adaptive_hybrid_origin_valid) {
    otis_regulation_fault(
        &transaction, "adaptive_hybrid_application_origin_or_controller_missing");
    return false;
  }
  const AdaptiveHybridLiveMutationSnapshot application_snapshot =
      capture_adaptive_hybrid_live_mutation_snapshot();
  const OtisAdaptiveHybridEngine application_before = adaptive_hybrid_engine;
  OtisAdaptiveHybridEngine application_after = application_before;
  const bool application_exact =
      otis_adaptive_hybrid_engine_note_application_and_first_consumer(
          &application_after, &pending_adaptive_hybrid_decision,
          transaction.applied_code, transaction.dac_epoch,
          adaptive_hybrid_downstream_epoch_exact);
  const char *adaptive_hybrid_application_event =
      application_exact ? "application" : "application_fault";
  const OtisAdaptiveHybridMaintenanceEvent maintenance_event =
      application_exact
          ? OtisAdaptiveHybridMaintenanceEvent::ApplicationFirstConsumer
          : OtisAdaptiveHybridMaintenanceEvent::FailStatic;
  const OtisAdaptiveHybridMaintenanceTransactionEvent maintenance_transaction_event =
      application_exact
          ? OtisAdaptiveHybridMaintenanceTransactionEvent::Application
          : OtisAdaptiveHybridMaintenanceTransactionEvent::ApplicationFault;
  const bool enter_metadata_hold_after_application =
      application_exact && gnss_metadata_hold_active &&
      !application_after.metadata_hold;
  const uint8_t application_capacity =
      static_cast<uint8_t>(2u +
                           (enter_metadata_hold_after_application ? 1u : 0u));
  evidence_pending_since_s = now_s;
  if (!otis_dual_core_evidence_can_publish(application_capacity) ||
      !begin_adaptive_hybrid_evidence_burst(2u) ||
      !queue_frame(adaptive_hybrid_application_event,
                   pending_application_timestamp_ticks, nullptr, 0.0)) {
    restore_adaptive_hybrid_live_mutation_snapshot(application_snapshot);
    otis_regulation_fault(
        &transaction, "adaptive_hybrid_application_evidence_queue_fault");
    return false;
  }
  const OtisAdaptiveHybridMaintenanceTransactionJoin application_join =
      adaptive_hybrid_current_transaction_join(
          maintenance_transaction_event, pending_adaptive_hybrid_observation,
          pending_adaptive_hybrid_decision, true, adaptive_hybrid_downstream_epoch_exact);
  if (!queue_adaptive_hybrid_maintenance_record(
          maintenance_event, pending_application_timestamp_ticks,
          application_before, application_after,
          &pending_adaptive_hybrid_observation, &pending_adaptive_hybrid_decision,
          &pending_adaptive_hybrid_hybrid_join, &application_join, 2u, 2u,
          application_after.last_reason) ||
      !commit_adaptive_hybrid_evidence_burst()) {
    restore_adaptive_hybrid_live_mutation_snapshot(application_snapshot);
    otis_regulation_fault(
        &transaction, "adaptive_hybrid_application_burst_commit_failed");
    return false;
  }
  adaptive_hybrid_engine = application_after;
  if (!application_exact) {
    otis_regulation_fault(&transaction,
                            application_after.fail_static_reason);
    return false;
  }
  if (!otis_adaptive_hybrid_wide_is_zero(
          pending_adaptive_hybrid_decision.raw_pll_picocodes))
    ++adaptive_hybrid_phase_nonzero_application_count;
  if (pending_adaptive_hybrid_decision.phase_materially_influenced)
    ++adaptive_hybrid_phase_material_application_count;
  else
    ++adaptive_hybrid_frequency_only_application_count;
  if (enter_metadata_hold_after_application) {
    const OtisAdaptiveHybridEngine hold_before = adaptive_hybrid_engine;
    OtisAdaptiveHybridEngine hold_after = hold_before;
    if (!otis_adaptive_hybrid_engine_enter_metadata_hold(&hold_after) ||
        !queue_adaptive_hybrid_single_async_transition(
            OtisAdaptiveHybridMaintenanceEvent::GnssMetadataHoldEnter,
            pending_application_timestamp_ticks, hold_before, hold_after,
            hold_after.last_reason)) {
      otis_regulation_fault(
          &transaction, "adaptive_hybrid_post_application_metadata_hold_evidence_fault");
      return false;
    }
    adaptive_hybrid_engine = hold_after;
  }
  return true;
}

bool otis_adaptive_hybrid_regulation_live_transport_busy(void) {
  return frame.length != 0u;
}

void otis_adaptive_hybrid_regulation_live_service_transport(void) {
  return;
}

void otis_adaptive_hybrid_regulation_live_visit_status(
    void *context, OtisRegulationStatusVisitor visitor, uint32_t now_s) {
  if (visitor == nullptr) return;
  status_snapshot_generation += 1u;
  if (status_snapshot_generation == 0u) status_snapshot_generation = 1u;
  char snapshot_generation[24];
  snprintf(snapshot_generation, sizeof(snapshot_generation), "%lu",
           static_cast<unsigned long>(status_snapshot_generation));
  visitor(context, "snapshot_generation_begin", snapshot_generation,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  visitor(context, "snapshot_contract",
          OTIS_ADAPTIVE_HYBRID_ACTIVE_STATUS_SNAPSHOT_CONTRACT,
          OTIS_SEVERITY_INFO,
          OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  OtisAdaptiveHybridRegulationLiveStatus active = {};
  otis_adaptive_hybrid_regulation_live_get_status(&active, now_s);
  visitor(context, "enabled", "true", OTIS_SEVERITY_INFO,
          OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  visitor(context, "run_identity", active.run_identity, OTIS_SEVERITY_INFO,
          OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  visitor(context, "build_identity", active.build_identity,
          OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  visitor(context, "image_identity", active.image_identity,
          OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  visitor(context, "estimator_sha256", active.estimator_sha256,
          OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  visitor(context, "model_sha256", active.model_sha256, OTIS_SEVERITY_INFO,
          OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  visitor(context, "active_policy_sha256", active.active_policy_sha256,
          OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  visitor(context, "response_policy_sha256", active.response_policy_sha256,
          OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  visitor(context, "numerical_policy_sha256",
          active.numerical_policy_sha256, OTIS_SEVERITY_INFO,
          OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  visitor(context, "state", active.state,
          active.fail_static ? OTIS_SEVERITY_ERROR : OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  visitor(context, "reason", active.reason, OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  visitor(context, "evidence_pending",
          active.evidence_pending ? "true" : "false",
          active.evidence_pending ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  visitor(context, "evidence_phase", active.evidence_state,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  visitor(context, "capture_lease_live",
          active.capture_lease_live ? "true" : "false",
          active.capture_lease_live ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
          OTIS_FLAG_NONE);
  visitor(context, "manual_start_confirmed",
          active.manual_start_confirmed ? "true" : "false",
          active.manual_start_confirmed ? OTIS_SEVERITY_INFO
                                        : OTIS_SEVERITY_WARN,
          OTIS_FLAG_NONE);
  visitor(context, "arm_eligible", active.arm_eligible ? "true" : "false",
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  visitor(context, "fail_static", active.fail_static ? "true" : "false",
          active.fail_static ? OTIS_SEVERITY_ERROR : OTIS_SEVERITY_INFO,
          active.fail_static ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                             : OTIS_FLAG_NONE);
  visitor(context, "setup_gnss_eligible",
          active.setup_gnss_eligible ? "true" : "false",
          active.setup_gnss_eligible ? OTIS_SEVERITY_INFO
                                     : OTIS_SEVERITY_WARN,
          OTIS_FLAG_NONE);
  visitor(context, "setup_reference_eligible",
          active.setup_reference_eligible ? "true" : "false",
          active.setup_reference_eligible ? OTIS_SEVERITY_INFO
                                          : OTIS_SEVERITY_WARN,
          OTIS_FLAG_NONE);
  visitor(context, "setup_partition_healthy",
          active.setup_partition_healthy ? "true" : "false",
          active.setup_partition_healthy ? OTIS_SEVERITY_INFO
                                         : OTIS_SEVERITY_ERROR,
          active.setup_partition_healthy
              ? OTIS_FLAG_NONE
              : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  visitor(context, "gnss_metadata_hold_active",
          active.gnss_metadata_hold_active ? "true" : "false",
          active.gnss_metadata_hold_active ? OTIS_SEVERITY_WARN
                                           : OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  visitor(context, "gnss_metadata_hold_transaction_pending",
          active.gnss_metadata_hold_transaction_pending ? "true" : "false",
          active.gnss_metadata_hold_transaction_pending ? OTIS_SEVERITY_WARN
                                                        : OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  char metadata_value[24];
  snprintf(metadata_value, sizeof(metadata_value), "%lu",
           static_cast<unsigned long>(
               active.gnss_metadata_hold_entry_sequence));
  visitor(context, "gnss_metadata_hold_entry_sequence", metadata_value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(metadata_value, sizeof(metadata_value), "%lu",
           static_cast<unsigned long>(
               active.gnss_metadata_requalification_sequence));
  visitor(context, "gnss_metadata_requalification_sequence", metadata_value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(metadata_value, sizeof(metadata_value), "%lu",
           static_cast<unsigned long>(
               active.gnss_metadata_qualification_frontier));
  visitor(context, "gnss_metadata_qualification_frontier", metadata_value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(metadata_value, sizeof(metadata_value), "%lu",
           static_cast<unsigned long>(active.d14_d8_observation_sequence));
  visitor(context, "d14_d8_observation_sequence", metadata_value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  visitor(context, "hybrid_state", active.hybrid_state,
          active.fail_static ? OTIS_SEVERITY_ERROR : OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  visitor(context, "hybrid_reason", active.hybrid_reason,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  visitor(context, "first_phase_checkpoint_passed",
          active.first_phase_checkpoint_passed ? "true" : "false",
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  char value[24];
  snprintf(value, sizeof(value), "%u",
           active.phase_nonzero_application_count);
  visitor(context, "phase_nonzero_application_count", value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%u",
           active.phase_material_application_count);
  visitor(context, "phase_material_application_count", value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%u",
           active.frequency_only_application_count);
  visitor(context, "frequency_only_application_count", value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(active.session_id));
  visitor(context, "session_id", value, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(active.query_nonce));
  visitor(context, "query_nonce", value, OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(active.uptime_s));
  visitor(context, "uptime_s", value, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(active.evidence_request_sequence));
  visitor(context, "evidence_request_sequence", value, OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "0x%04X",
           static_cast<unsigned int>(active.expected_setup_code));
  visitor(context, "expected_setup_code", value, OTIS_SEVERITY_INFO,
          OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  visitor(context, "confirmed_applied_code_known",
          active.confirmed_applied_code_known ? "true" : "false",
          active.confirmed_applied_code_known ? OTIS_SEVERITY_INFO
                                              : OTIS_SEVERITY_WARN,
          OTIS_FLAG_NONE);
  if (active.confirmed_applied_code_known)
    snprintf(value, sizeof(value), "%u", active.applied_code);
  else
    snprintf(value, sizeof(value), "%s", "unavailable");
  visitor(context, "confirmed_applied_code", value, OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%u", active.correction_count);
  visitor(context, "correction_count", value, OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%u", active.cumulative_movement_codes);
  visitor(context, "cumulative_movement_codes", value, OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(active.dac_epoch));
  visitor(context, "dac_epoch", value, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%u", active.selected_interval_count);
  visitor(context, "selected_interval_count", value, OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  visitor(context, "automatic_retry", "false", OTIS_SEVERITY_INFO,
          OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  visitor(context, "automatic_restore", "false", OTIS_SEVERITY_INFO,
          OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  visitor(context, "snapshot_generation_complete", snapshot_generation,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
}

static void emit_direct_active_status(void *context, const char *key,
                                      const char *value,
                                      const char *severity, uint32_t flags) {
  otis_status_emit(static_cast<OtisStatusEmitContext *>(context),
                   "adaptive_hybrid", key, value, severity, flags);
}

void otis_adaptive_hybrid_regulation_live_emit_status(OtisStatusEmitContext *context,
                                        uint32_t now_s) {
  if (context == nullptr) return;
  otis_adaptive_hybrid_regulation_live_visit_status(context, emit_direct_active_status,
                                      now_s);
}

void otis_adaptive_hybrid_regulation_live_get_status(OtisAdaptiveHybridRegulationLiveStatus *status,
                                       uint32_t now_s) {
  if (status == nullptr) return;
  *status = {};
  const OtisRegulationEligibility current_eligibility = eligibility(now_s);
  status->run_identity = kRunIdentity;
  status->build_identity = kBuildIdentity;
  status->image_identity = OTIS_BUILD_IMAGE_ID;
  status->estimator_sha256 = kEstimatorHash;
  status->model_sha256 = kModelHash;
  status->active_policy_sha256 = kActivePolicyHash;
  status->response_policy_sha256 = kResponsePolicyHash;
  status->numerical_policy_sha256 = kNumericalPolicyHash;
  const bool transaction_terminal =
      transaction_bound &&
      (transaction.state == OtisRegulationState::Fault ||
       transaction.state == OtisRegulationState::Aborted);
  status->state = transaction_terminal
                      ? otis_regulation_state_name(transaction.state)
                      : (gnss_metadata_hold_active
                             ? "GNSS_METADATA_HOLD"
                             : (transaction_bound
                                    ? otis_regulation_state_name(
                                          transaction.state)
                                    : "UNBOUND"));
  status->reason = transaction_terminal
                       ? transaction.reason
                       : (gnss_metadata_hold_active
                              ? (gnss_metadata_hold_transaction_pending
                                     ? "gnss_metadata_hold_transaction_resolution_pending"
                                     : "gnss_metadata_unqualified_hold")
                              : (transaction_bound ? transaction.reason
                                                   : "session_unbound"));
  status->evidence_state = evidence_state_name();
  status->session_id = transaction_bound
                           ? transaction.expected_binding.session_id
                           : 0u;
  status->evidence_request_sequence = evidence_request_sequence;
  status->query_nonce = status_query_nonce;
  status->uptime_s = now_s;
  status->expected_setup_code =
      static_cast<uint16_t>(OTIS_ADAPTIVE_HYBRID_START_CODE);
  status->applied_code = transaction_bound ? transaction.applied_code : 0u;
  status->correction_count =
      transaction_bound ? transaction.correction_count : 0u;
  status->cumulative_movement_codes =
      transaction_bound ? transaction.cumulative_movement_codes : 0u;
  status->dac_epoch = transaction_bound ? transaction.dac_epoch : 0u;
  status->selected_interval_count =
      have_health ? latest_health.selected_interval_count : 0u;
  status->transaction_bound = transaction_bound;
  status->evidence_pending = evidence_phase != EvidencePhase::None;
  status->confirmed_applied_code_known =
      transaction_bound && manual_start_confirmed;
  status->capture_lease_live = capture_lease_live(now_s);
  status->manual_start_confirmed = manual_start_confirmed;
  status->arm_eligible =
      otis_regulation_arm_eligibility_valid(&current_eligibility);
  status->fail_static =
      otis_dual_core_fail_static() ||
      (transaction_bound &&
       (transaction.state == OtisRegulationState::Fault ||
        transaction.state == OtisRegulationState::Aborted));
  status->setup_gnss_eligible =
      have_health && latest_health.gnss_metadata_valid &&
      latest_health.gnss_identity_stable && latest_health.gnss_3d_evidence;
  status->setup_reference_eligible =
      have_health && latest_health.raw_pps_valid && latest_health.count_valid;
  status->setup_partition_healthy = !otis_dual_core_fail_static();
  status->gnss_metadata_hold_active = gnss_metadata_hold_active;
  status->gnss_metadata_hold_transaction_pending =
      gnss_metadata_hold_transaction_pending;
  status->gnss_metadata_hold_entry_sequence =
      gnss_metadata_hold_entry_sequence;
  status->gnss_metadata_requalification_sequence =
      gnss_metadata_requalification_sequence;
  status->gnss_metadata_qualification_frontier =
      gnss_metadata_qualification_frontier;
  status->d14_d8_observation_sequence =
      have_health ? latest_health.d14_d8_observation_sequence : 0u;
  const bool adaptive_hybrid_controller_inhibited =
      adaptive_hybrid_engine_ready && adaptive_hybrid_engine.fail_static_reason != nullptr &&
      (strcmp(adaptive_hybrid_engine.fail_static_reason,
              "prospective_repeated_alternation") == 0 ||
       strcmp(adaptive_hybrid_engine.fail_static_reason,
              "prospective_low_efficiency_path") == 0);
  if (transaction_terminal) {
    status->hybrid_state = otis_regulation_state_name(transaction.state);
    status->hybrid_reason = transaction.reason;
  } else if (!adaptive_hybrid_engine_ready) {
    status->hybrid_state = "SETUP_PENDING";
    status->hybrid_reason = "setup_consumers_pending";
  } else if (gnss_metadata_hold_active) {
    status->hybrid_state = "GNSS_METADATA_HOLD";
    status->hybrid_reason = adaptive_hybrid_engine.last_reason;
  } else if (adaptive_hybrid_controller_inhibited) {
    status->hybrid_state = "CONTROLLER_AUTHORITY_INHIBITED";
    status->hybrid_reason = adaptive_hybrid_engine.fail_static_reason;
  } else {
    status->hybrid_state = otis_active_hybrid_state_name(
        adaptive_hybrid_project_hybrid_state(
            adaptive_hybrid_engine,
            !last_adaptive_hybrid_origin_valid || last_adaptive_hybrid_observation.phase_valid));
    status->hybrid_reason = adaptive_hybrid_engine.last_reason;
  }
  status->phase_nonzero_application_count =
      adaptive_hybrid_phase_nonzero_application_count;
  status->phase_material_application_count =
      adaptive_hybrid_phase_material_application_count;
  status->frequency_only_application_count =
      adaptive_hybrid_frequency_only_application_count;
  status->first_phase_checkpoint_passed =
      adaptive_hybrid_engine_ready && adaptive_hybrid_engine.application_count > 0u &&
      !adaptive_hybrid_engine.response_pending;
}

void otis_adaptive_hybrid_regulation_live_set_status_query_nonce(uint32_t query_nonce) {
  status_query_nonce = query_nonce;
}

uint32_t otis_adaptive_hybrid_regulation_live_status_snapshot_generation(void) {
  return status_snapshot_generation;
}

const char *otis_adaptive_hybrid_regulation_live_run_identity(void) { return kRunIdentity; }

uint16_t otis_adaptive_hybrid_regulation_live_start_code(void) {
  return static_cast<uint16_t>(OTIS_ADAPTIVE_HYBRID_START_CODE);
}
