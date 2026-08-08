#include "otis_cx317_active_live.h"

#include <stdio.h>
#include <string.h>

#include "otis_config.h"
#include "otis_cx317_active_actuator.h"
#include "otis_dual_core_partition.h"
#include "otis_protocol.h"
#include "otis_transport_serial.h"

namespace {

#if OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_REHEARSAL
constexpr char kEstimatorHash[] =
    "54173f493cb7dc459e57e7695d98b518a2616ded914898647f459b2325c94977";
#else
constexpr char kEstimatorHash[] =
    "5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c";
#endif
constexpr char kModelHash[] =
    "5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1";
#if OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_REHEARSAL
constexpr char kNumericalPolicyHash[] =
    "d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf";
constexpr char kActivePolicyHash[] =
    "d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf";
#else
constexpr char kNumericalPolicyHash[] =
    "a5151f2fa3462e6b7dbd5d0562fd8a7ea94220e72ac2dfaf808f474ded765521";
constexpr char kActivePolicyHash[] =
    "29db33da6a518727b25396f5fa77e26a1f5ca886a7eda232ca32997c5e82ae42";
#endif
constexpr char kResponsePolicyHash[] =
    "f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec";
constexpr uint32_t kCaptureLeaseMaximumAgeS = 30u;
constexpr uint32_t kEvidenceAcknowledgementMaximumAgeS = 30u;
constexpr uint64_t kCaptureTicksPerSecond = 16000000ull;
constexpr size_t kFrameCapacity = 1536u;
constexpr size_t kTransportChunkLimit = 192u;

#if OTIS_CX317_ACTIVE_CAMPAIGN == OTIS_CX317_ACTIVE_CAMPAIGN_A
constexpr char kRunIdentity[] = "cx317_bounded_campaign_a:3170001";
constexpr char kExpectedProfile[] = "cx317_bounded_active_campaign_a";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == OTIS_CX317_ACTIVE_CAMPAIGN_B
constexpr char kRunIdentity[] = "cx317_bounded_campaign_b:3170002";
constexpr char kExpectedProfile[] = "cx317_bounded_active_campaign_b";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_A
constexpr char kRunIdentity[] = "cx317_stage7_part_a:3170003";
constexpr char kExpectedProfile[] = "cx317_dual_core_active_part_a";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_B
constexpr char kRunIdentity[] = "cx317_stage7_part_b:3170004";
constexpr char kExpectedProfile[] =
    "cx317_dual_core_active_endurance_part_b";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_REHEARSAL
constexpr char kRunIdentity[] = "cx317_stage7_rehearsal:3170005";
constexpr char kExpectedProfile[] = "cx317_dual_core_active_rehearsal";
#else
constexpr char kRunIdentity[] = "cx317_bounded_active_disabled";
constexpr char kExpectedProfile[] = "disabled";
#endif

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
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  Acceptance = 2u,
  Application = 3u,
  Response = 4u,
#else
  Application = 2u,
  Response = 3u,
#endif
};

OtisCx317ActiveTransaction transaction;
OtisCx317ActiveLiveHealth latest_health = {};
TransportFrame frame = {};
bool initialized = false;
bool transaction_bound = false;
bool have_health = false;
bool have_capture_lease = false;
bool manual_start_confirmed = false;
EvidencePhase evidence_phase = EvidencePhase::None;
uint32_t last_capture_lease_s = 0u;
uint32_t last_capture_lease_sequence = 0u;
uint32_t evidence_request_sequence = 0u;
uint32_t evidence_pending_since_s = 0u;
uint32_t transaction_record_sequence = 0u;
OtisCx317ActionableRequest pending_actionable_request = {};
bool pending_actionable_request_valid = false;
OtisCx317ActiveLiveOutcome deferred_application_outcome = {};
bool deferred_application_outcome_valid = false;
bool last_application_acknowledged = false;
bool estimator_history_reset = false;
#if OTIS_ENABLE_DUAL_CORE_PARTITION
OtisActuatorTransactionGuard timing_actuator_guard = {};
#endif

bool capture_lease_live(uint32_t now_s) {
  return have_capture_lease &&
         static_cast<uint32_t>(now_s - last_capture_lease_s) <=
             kCaptureLeaseMaximumAgeS;
}

OtisCx317ActiveBinding expected_binding(uint32_t session_id) {
  return {
      kRunIdentity,
      kBuildIdentity,
      OTIS_BUILD_PROFILE_ID,
      kEstimatorHash,
      kModelHash,
      kActivePolicyHash,
      kResponsePolicyHash,
      kNumericalPolicyHash,
      session_id,
      static_cast<uint16_t>(OTIS_CX317_ACTIVE_START_CODE),
      0xA800u,
      0xAB00u,
      21u,
      static_cast<uint16_t>(OTIS_CX317_ACTIVE_CORRECTION_LIMIT),
      static_cast<uint16_t>(OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES),
#if OTIS_CX317_ACTIVE_CAMPAIGN == OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_B
      true,
#else
      false,
#endif
  };
}

OtisCx317ActiveEligibility eligibility(uint32_t now_s) {
  const bool profile_matches = strcmp(OTIS_BUILD_PROFILE_ID, kExpectedProfile) == 0;
  const bool session_matches =
      transaction_bound && have_health &&
      latest_health.session_id == transaction.expected_binding.session_id;
  return {
      transaction_bound,
      transaction_bound,
      profile_matches,
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

bool critical_continuity_healthy(uint32_t now_s) {
  if (!have_health || !transaction_bound) return false;
  return latest_health.session_id == transaction.expected_binding.session_id &&
         latest_health.gnss_metadata_valid &&
         latest_health.gnss_identity_stable &&
         latest_health.gnss_3d_evidence && latest_health.raw_pps_valid &&
         latest_health.count_valid && latest_health.applied_code_confirmed &&
         latest_health.applied_code == transaction.applied_code &&
         capture_lease_live(now_s) && latest_health.abort_path_live;
}

const char *evidence_state_name(void) {
  switch (evidence_phase) {
    case EvidencePhase::Request:
      return "request_pending";
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    case EvidencePhase::Acceptance:
      return "acceptance_pending";
#endif
    case EvidencePhase::Application:
      return "application_pending";
    case EvidencePhase::Response:
      return "response_pending";
    case EvidencePhase::None:
      return "evidence_clear";
  }
  return "evidence_clear";
}

#if OTIS_ENABLE_DUAL_CORE_PARTITION
OtisCrossCoreActuatorRequest cross_core_request(
    const OtisCx317ActionableRequest &request, uint32_t now_s) {
  OtisCrossCoreActuatorRequest cross = {};
  cross.request_sequence = request.request_sequence;
  cross.decision_sequence = request.decision_sequence;
  cross.source_first_sequence = request.source_first_sequence;
  cross.source_last_sequence = request.source_last_sequence;
  cross.decision_reference_ticks =
      static_cast<uint64_t>(request.timestamp_s) * kCaptureTicksPerSecond;
  cross.deadline_ticks =
      static_cast<uint64_t>(now_s + kEvidenceAcknowledgementMaximumAgeS) *
      kCaptureTicksPerSecond;
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
           "cx317_actuator");
  snprintf(message.reason, sizeof(message.reason), "%s",
           kind == OtisCriticalMessageKind::ActuatorRequest
               ? "durable_request_released_to_core0"
               : "durable_acceptance_released_for_single_application");
  message.request = kind == OtisCriticalMessageKind::ActuatorRequest
                        ? cross_core_request(pending_actionable_request, now_s)
                        : timing_actuator_guard.pending;
  return otis_dual_core_publish_critical(&message);
}
#endif

bool queue_frame(const char *event, const OtisCx317ResponseResult *response,
                 double post_error_hz) {
  if (frame.length != 0u) return false;
  const char *response_name =
      response == nullptr ? "unavailable"
                          : otis_cx317_response_class_name(response->classification);
  const char *reason = response == nullptr ? transaction.reason : response->reason;
  const uint32_t next_record_sequence = transaction_record_sequence + 1u;
  const int used = snprintf(
      frame.data, sizeof(frame.data),
      "ACT,1,%lu,%s,%s,%s,%s,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%u,%ld,%u,%u,%u,%.9f,%u,%lu,%u,%u,%lu,%s,%s,%s,%u,%s,%u,%u,%.9f,%.9f,%.9f,%u,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\r\n",
      static_cast<unsigned long>(next_record_sequence), event, kRunIdentity,
      kBuildIdentity, OTIS_BUILD_PROFILE_ID,
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
      transaction.request.pre_error_hz,
      transaction.accepted.accepted_code,
      static_cast<unsigned long>(transaction.accepted.accepted_timestamp_s),
      transaction.applied.applied_code, transaction.applied.application_sequence,
      static_cast<unsigned long>(transaction.applied.application_timestamp_s),
      transaction.applied.i2c_ok ? "true" : "false",
      transaction.applied.clamped ? "true" : "false",
      transaction.applied.ambiguous ? "true" : "false",
      transaction.dac_epoch, estimator_history_reset ? "true" : "false",
      transaction.correction_count,
      transaction.cumulative_movement_codes, post_error_hz,
      response == nullptr ? 0.0 : response->observed_response_hz,
      response == nullptr ? 0.0 : response->cumulative_response_hz,
      response == nullptr ? 0u : response->consecutive_indeterminate,
      otis_cx317_active_state_name(transaction.state), response_name, reason,
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
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  OtisEvidenceFrameMessage message = {};
  message.sequence = next_record_sequence;
  message.length = frame.length;
  memcpy(message.data, frame.data, frame.length + 1u);
  if (!otis_dual_core_publish_evidence(&message)) {
    frame = {};
    return false;
  }
  frame = {};
#endif
  transaction_record_sequence = next_record_sequence;
  return true;
}

bool queue_manual_start_frame(uint16_t code, bool ok, uint32_t now_s) {
  if (frame.length != 0u) return false;
  const uint32_t next_record_sequence = transaction_record_sequence + 1u;
  const int used = snprintf(
      frame.data, sizeof(frame.data),
      "ACT,1,%lu,manual_start,%s,%s,%s,%lu,0,0,0,0,0,0,%lu,%u,0,%u,0,0,0.000000000,%u,%lu,%u,0,%lu,%s,false,false,%u,false,%u,%u,0.000000000,0.000000000,0.000000000,0,%s,unavailable,%s,%s,%s,%s,%s,%s,false,evidence_clear\r\n",
      static_cast<unsigned long>(next_record_sequence), kRunIdentity,
      kBuildIdentity, OTIS_BUILD_PROFILE_ID,
      static_cast<unsigned long>(transaction_bound
                                     ? transaction.expected_binding.session_id
                                     : 0u),
      static_cast<unsigned long>(now_s), code, code, code,
      static_cast<unsigned long>(now_s), code,
      static_cast<unsigned long>(now_s), ok ? "true" : "false",
      transaction_bound ? transaction.dac_epoch : 0u,
      transaction_bound ? transaction.correction_count : 0u,
      transaction_bound ? transaction.cumulative_movement_codes : 0u,
      transaction_bound ? otis_cx317_active_state_name(transaction.state)
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
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  OtisEvidenceFrameMessage message = {};
  message.sequence = next_record_sequence;
  message.length = frame.length;
  memcpy(message.data, frame.data, frame.length + 1u);
  if (!otis_dual_core_publish_evidence(&message)) {
    frame = {};
    return false;
  }
  frame = {};
#endif
  transaction_record_sequence = next_record_sequence;
  return true;
}

void fault_if_active_continuity_lost(uint32_t now_s) {
  if (!transaction_bound) return;
  if ((transaction.state == OtisCx317ActiveState::Armed ||
       transaction.state == OtisCx317ActiveState::RequestPending ||
       transaction.state ==
           OtisCx317ActiveState::AcceptedAwaitingApplication ||
       transaction.state == OtisCx317ActiveState::AwaitingResponse) &&
      !critical_continuity_healthy(now_s))
    otis_cx317_active_fault(&transaction,
                            "active_continuity_or_capture_lease_lost");
}

}  // namespace

bool otis_cx317_active_live_begin(void) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  initialized = true;
  transaction_bound = false;
  have_health = false;
  have_capture_lease = false;
  manual_start_confirmed = false;
  evidence_phase = EvidencePhase::None;
  last_capture_lease_sequence = 0u;
  evidence_request_sequence = 0u;
  evidence_pending_since_s = 0u;
  transaction_record_sequence = 0u;
  pending_actionable_request_valid = false;
  deferred_application_outcome_valid = false;
  last_application_acknowledged = false;
  estimator_history_reset = false;
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  otis_actuator_guard_init(&timing_actuator_guard);
#endif
  frame = {};
  return true;
#else
  return true;
#endif
}

void otis_cx317_active_live_emit_headers(void) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  otis_transport_write_cstr(
      "record_type,schema_version,transaction_record_sequence,event,run_identity,build_identity,profile_identity,session_id,authorization_sequence,nonce,request_sequence,decision_sequence,source_first_sequence,source_last_sequence,decision_timestamp_s,current_applied_code,requested_delta_codes,requested_code,correction_ordinal,cumulative_after_codes,pre_error_hz,accepted_code,accepted_timestamp_s,applied_code,application_sequence,application_timestamp_s,i2c_ok,clamped,ambiguous,dac_epoch,estimator_history_reset,correction_count,cumulative_movement_codes,post_error_hz,observed_response_hz,cumulative_response_hz,consecutive_indeterminate,active_state,response_class,reason,estimator_sha256,model_sha256,active_policy_sha256,response_policy_sha256,numerical_policy_sha256,actionable,evidence_state\r\n");
#endif
}

void otis_cx317_active_live_update_health(
    const OtisCx317ActiveLiveHealth *health, uint32_t now_s) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (!initialized || health == nullptr) return;
  latest_health = *health;
  have_health = true;
  if (!transaction_bound && health->session_id != 0u) {
    const OtisCx317ActiveBinding binding = expected_binding(health->session_id);
    otis_cx317_active_transaction_init(&transaction, &binding);
    transaction_bound = true;
  } else if (transaction_bound) {
    otis_cx317_active_note_session(&transaction, health->session_id);
  }
  if (transaction_bound && manual_start_confirmed &&
      !health->applied_code_confirmed)
    otis_cx317_active_fault(&transaction, "confirmed_applied_code_lost");
  fault_if_active_continuity_lost(now_s);
#else
  (void)health;
  (void)now_s;
#endif
}

void otis_cx317_active_live_service(uint32_t now_s) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  fault_if_active_continuity_lost(now_s);
  if (transaction_bound && transaction.state == OtisCx317ActiveState::Armed &&
      transaction.have_arm && now_s > transaction.arm.expires_s)
    otis_cx317_active_fault(&transaction, "unused_authorization_expired");
  if (transaction_bound && evidence_phase != EvidencePhase::None &&
      static_cast<uint32_t>(now_s - evidence_pending_since_s) >
          kEvidenceAcknowledgementMaximumAgeS)
    otis_cx317_active_fault(&transaction,
                            "transaction_evidence_acknowledgement_timeout");
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  if (transaction_bound &&
      (!otis_actuator_guard_check_deadline(
           &timing_actuator_guard,
           static_cast<uint64_t>(now_s) * kCaptureTicksPerSecond) ||
       otis_dual_core_fail_static()))
    otis_cx317_active_fault(&transaction,
                            "cross_core_partition_or_actuator_guard_fault");
#endif
#else
  (void)now_s;
#endif
}

bool otis_cx317_active_live_capture_lease(uint32_t sequence, uint32_t now_s) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (!initialized || sequence == 0u || sequence <= last_capture_lease_sequence)
    return false;
  last_capture_lease_sequence = sequence;
  last_capture_lease_s = now_s;
  have_capture_lease = true;
  return true;
#else
  (void)sequence;
  (void)now_s;
  return false;
#endif
}

bool otis_cx317_active_live_arm(uint32_t sequence, uint32_t nonce,
                               uint32_t expires_s, uint32_t now_s) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (!initialized || !transaction_bound) return false;
  const OtisCx317ArmRequest arm = {
      transaction.expected_binding, sequence, nonce, expires_s};
  const OtisCx317ActiveEligibility health = eligibility(now_s);
  return otis_cx317_active_arm(&transaction, &arm, &health, now_s);
#else
  (void)sequence;
  (void)nonce;
  (void)expires_s;
  (void)now_s;
  return false;
#endif
}

void otis_cx317_active_live_abort(const char *reason) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (transaction_bound) otis_cx317_active_abort(&transaction, reason);
  pending_actionable_request_valid = false;
  evidence_phase = EvidencePhase::None;
  evidence_request_sequence = 0u;
#else
  (void)reason;
#endif
}

bool otis_cx317_active_live_acknowledge_evidence(uint32_t request_sequence,
                                                 uint32_t phase_sequence,
                                                 uint32_t now_s) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (evidence_phase == EvidencePhase::None ||
      request_sequence != evidence_request_sequence ||
      phase_sequence != static_cast<uint32_t>(evidence_phase) ||
      frame.length != 0u)
    return false;
  if (evidence_phase == EvidencePhase::Request) {
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    if (!transaction_bound || !pending_actionable_request_valid ||
        transaction.state != OtisCx317ActiveState::RequestPending ||
        !critical_continuity_healthy(now_s)) {
      if (transaction_bound)
        otis_cx317_active_fault(
            &transaction, "pre_acceptance_evidence_or_continuity_invalid");
      pending_actionable_request_valid = false;
      return false;
    }
    const OtisCrossCoreActuatorRequest request =
        cross_core_request(pending_actionable_request, now_s);
    if (!otis_actuator_guard_start(&timing_actuator_guard, &request,
                                   request.decision_reference_ticks) ||
        !publish_cross_core_actuator_message(
            OtisCriticalMessageKind::ActuatorRequest, now_s)) {
      otis_cx317_active_fault(&transaction,
                              "cross_core_actuator_request_queue_fault");
      pending_actionable_request_valid = false;
      return false;
    }
    evidence_phase = EvidencePhase::None;
    evidence_pending_since_s = 0u;
    return true;
#else
    if (!transaction_bound || !pending_actionable_request_valid ||
        transaction.state !=
            OtisCx317ActiveState::AcceptedAwaitingApplication ||
        !critical_continuity_healthy(now_s)) {
      if (transaction_bound)
        otis_cx317_active_fault(
            &transaction, "pre_application_evidence_or_continuity_invalid");
      pending_actionable_request_valid = false;
      return false;
    }
    const OtisCx317AppliedAck applied = otis_cx317_active_actuator_apply_once(
        &pending_actionable_request, &transaction.accepted,
        static_cast<uint16_t>(transaction.correction_count + 1u), now_s);
    pending_actionable_request_valid = false;
    const bool acknowledged =
        otis_cx317_active_acknowledge_application(&transaction, &applied);
    deferred_application_outcome = {};
    deferred_application_outcome.application_attempted = true;
    deferred_application_outcome.request_sequence = request_sequence;
    deferred_application_outcome.requested_code =
        transaction.request.requested_code;
    deferred_application_outcome.applied_code = applied.applied_code;
    deferred_application_outcome.applied = acknowledged;
    deferred_application_outcome.faulted = !acknowledged;
    deferred_application_outcome.reason = transaction.reason;
    deferred_application_outcome_valid = true;
    last_application_acknowledged = acknowledged;
    if (acknowledged) {
      latest_health.applied_code = transaction.applied_code;
      latest_health.applied_code_confirmed = true;
    }
    evidence_phase = EvidencePhase::Application;
    evidence_pending_since_s = now_s;
    return true;
#endif
  }
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  if (evidence_phase == EvidencePhase::Acceptance) {
    if (!transaction_bound || !pending_actionable_request_valid ||
        transaction.state !=
            OtisCx317ActiveState::AcceptedAwaitingApplication ||
        timing_actuator_guard.state !=
            OtisActuatorGuardState::AwaitingApplication ||
        !critical_continuity_healthy(now_s) ||
        !publish_cross_core_actuator_message(
            OtisCriticalMessageKind::ActuatorExecute, now_s)) {
      otis_cx317_active_fault(
          &transaction, "cross_core_application_release_or_continuity_fault");
      pending_actionable_request_valid = false;
      return false;
    }
    evidence_phase = EvidencePhase::None;
    evidence_pending_since_s = 0u;
    return true;
  }
#endif
  evidence_phase = EvidencePhase::None;
  evidence_request_sequence = 0u;
  evidence_pending_since_s = 0u;
  return true;
#else
  (void)request_sequence;
  (void)phase_sequence;
  (void)now_s;
  return false;
#endif
}

bool otis_cx317_active_live_on_cross_core_ack(
    const OtisCrossCoreActuatorAck *acknowledgement, uint32_t now_s) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && OTIS_ENABLE_DUAL_CORE_PARTITION
  if (acknowledgement == nullptr || !transaction_bound ||
      !pending_actionable_request_valid) {
    if (transaction_bound)
      otis_cx317_active_fault(
          &transaction, "cross_core_actuator_acknowledgement_invalid");
    return false;
  }
  const bool guard_acknowledged = otis_actuator_guard_acknowledge(
      &timing_actuator_guard, acknowledgement);
  if (acknowledgement->kind == OtisActuatorAckKind::Accepted) {
    if (!guard_acknowledged) {
      otis_cx317_active_fault(
          &transaction, "cross_core_acceptance_acknowledgement_invalid");
      return false;
    }
    OtisCx317AcceptedRequest accepted;
    if (!otis_cx317_active_accept(&transaction,
                                  &pending_actionable_request, now_s,
                                  &accepted))
      return false;
    evidence_phase = EvidencePhase::Acceptance;
    evidence_request_sequence = pending_actionable_request.request_sequence;
    evidence_pending_since_s = now_s;
    if (!queue_frame("core0_accepted", nullptr, 0.0)) {
      otis_cx317_active_fault(&transaction,
                              "acceptance_evidence_queue_fault");
      return false;
    }
    return true;
  }
  if (acknowledgement->kind != OtisActuatorAckKind::Applied) {
    otis_cx317_active_fault(&transaction,
                            "cross_core_actuator_rejected_or_bad_phase");
    return false;
  }
  const OtisCx317AppliedAck applied = {
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
      otis_cx317_active_acknowledge_application(&transaction, &applied);
  const bool acknowledged = guard_acknowledged && transaction_acknowledged;
  if (!guard_acknowledged)
    otis_cx317_active_fault(
        &transaction, "cross_core_application_acknowledgement_invalid");
  deferred_application_outcome = {};
  deferred_application_outcome.application_attempted = true;
  deferred_application_outcome.request_sequence =
      acknowledgement->request_sequence;
  deferred_application_outcome.requested_code =
      acknowledgement->requested_code;
  deferred_application_outcome.applied_code = acknowledgement->applied_code;
  deferred_application_outcome.applied = acknowledged;
  deferred_application_outcome.faulted = !acknowledged;
  deferred_application_outcome.reason = transaction.reason;
  deferred_application_outcome_valid = true;
  last_application_acknowledged = acknowledged;
  if (acknowledged) {
    latest_health.applied_code = transaction.applied_code;
    latest_health.applied_code_confirmed = true;
  }
  pending_actionable_request_valid = false;
  evidence_phase = EvidencePhase::Application;
  evidence_pending_since_s = now_s;
  return acknowledged;
#else
  (void)acknowledgement;
  (void)now_s;
  return false;
#endif
}

bool otis_cx317_active_live_manual_start_allowed(uint16_t code) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  return initialized && code == OTIS_CX317_ACTIVE_START_CODE &&
         !manual_start_confirmed &&
         (!transaction_bound ||
          (transaction.state == OtisCx317ActiveState::Disarmed &&
           transaction.correction_count == 0u && !transaction.have_request));
#else
  (void)code;
  return true;
#endif
}

void otis_cx317_active_live_note_manual_start(uint16_t code, bool i2c_ok,
                                              uint32_t now_s) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (!otis_cx317_active_live_manual_start_allowed(code) || !i2c_ok) {
    if (transaction_bound)
      otis_cx317_active_fault(&transaction, "manual_start_establishment_failed");
    queue_manual_start_frame(code, false, now_s);
    return;
  }
  manual_start_confirmed = true;
  if (transaction_bound) transaction.applied_code = code;
  if (!queue_manual_start_frame(code, true, now_s) && transaction_bound)
    otis_cx317_active_fault(&transaction, "manual_start_evidence_queue_fault");
#else
  (void)code;
  (void)i2c_ok;
  (void)now_s;
#endif
}

void otis_cx317_active_live_on_decision(
    const OtisCx317ActiveLiveDecision *decision,
    OtisCx317ActiveLiveOutcome *outcome) {
  if (outcome != nullptr) *outcome = {};
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (!initialized || !transaction_bound || decision == nullptr ||
      outcome == nullptr)
    return;
  outcome->reason = transaction.reason;
  OtisCx317ActiveEligibility health = eligibility(decision->timestamp_s);
  // The completed selected estimate is created in this boundary callback;
  // the periodic health snapshot necessarily trails it by one service loop.
  health.estimator_valid = decision->measurement_valid;
  health.model_applicable = decision->model_applicable;
  if (transaction.state == OtisCx317ActiveState::AwaitingResponse) {
    OtisCx317ResponseResult response;
    const bool measurement_healthy =
        decision->measurement_valid &&
        otis_cx317_active_response_measurement_valid(&health);
    // A selected response can arrive while the preview engine is still in its
    // post-DAC SETTLE_PREVIEW state.  preview actionability gates a new request,
    // not acceptance of an already-completed response.  The full live health
    // and model-applicability contract is the post-response eligibility gate.
    const bool control_eligible_after_response =
        otis_cx317_active_eligibility_valid(&health);
    const bool accepted = otis_cx317_active_record_response(
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
    if (!queue_frame("response", &response, decision->frequency_error_hz)) {
      otis_cx317_active_fault(&transaction, "response_evidence_queue_fault");
      outcome->faulted = true;
      outcome->reason = transaction.reason;
    }
    return;
  }
  if (transaction.state != OtisCx317ActiveState::Armed) return;
  const OtisCx317ActiveDecision request_input = {
      decision->decision_sequence,
      decision->source_first_sequence,
      decision->source_last_sequence,
      decision->timestamp_s,
      decision->current_applied_code,
      decision->requested_delta_codes,
      decision->requested_code,
      decision->frequency_error_hz,
  };
  OtisCx317ActionableRequest request;
  if (!decision->control_eligible ||
      !otis_cx317_active_make_request(&transaction, &request_input, &health,
                                      decision->timestamp_s, &request)) {
    outcome->faulted = transaction.state == OtisCx317ActiveState::Fault;
    outcome->reason = transaction.reason;
    return;
  }
  OtisCx317AcceptedRequest accepted;
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  pending_actionable_request = request;
  pending_actionable_request_valid = true;
#else
  if (!otis_cx317_active_accept(&transaction, &request, decision->timestamp_s,
                                &accepted)) {
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  pending_actionable_request = request;
  pending_actionable_request_valid = true;
#endif
  estimator_history_reset = false;
  outcome->request_created = true;
  outcome->request_sequence = request.request_sequence;
  outcome->requested_code = request.requested_code;
  outcome->applied_code = transaction.applied_code;
  outcome->applied = false;
  outcome->faulted = false;
  outcome->reason = transaction.reason;
  evidence_phase = EvidencePhase::Request;
  evidence_request_sequence = request.request_sequence;
  evidence_pending_since_s = decision->timestamp_s;
  if (!queue_frame(
#if OTIS_ENABLE_DUAL_CORE_PARTITION
          "request_created",
#else
          "request_accepted",
#endif
          nullptr, 0.0)) {
    pending_actionable_request_valid = false;
    otis_cx317_active_fault(&transaction, "request_evidence_queue_fault");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
  }
#else
  (void)decision;
#endif
}

bool otis_cx317_active_live_take_application_outcome(
    OtisCx317ActiveLiveOutcome *outcome) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (outcome == nullptr || !deferred_application_outcome_valid) return false;
  *outcome = deferred_application_outcome;
  deferred_application_outcome_valid = false;
  return true;
#else
  (void)outcome;
  return false;
#endif
}

bool otis_cx317_active_live_complete_application_evidence(
    uint32_t request_sequence, bool history_reset, uint32_t now_s) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (evidence_phase != EvidencePhase::Application ||
      request_sequence != evidence_request_sequence || frame.length != 0u)
    return false;
  estimator_history_reset = last_application_acknowledged && history_reset;
  if (last_application_acknowledged && !estimator_history_reset)
    otis_cx317_active_fault(&transaction,
                            "estimator_history_reset_not_confirmed");
  evidence_pending_since_s = now_s;
  if (!queue_frame(last_application_acknowledged && estimator_history_reset
                       ? "application"
                       : "application_fault",
                   nullptr, 0.0)) {
    otis_cx317_active_fault(&transaction, "application_evidence_queue_fault");
    return false;
  }
  return true;
#else
  (void)request_sequence;
  (void)history_reset;
  (void)now_s;
  return false;
#endif
}

bool otis_cx317_active_live_transport_busy(void) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  return frame.length != 0u;
#else
  return false;
#endif
}

void otis_cx317_active_live_service_transport(void) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  return;
#else
  if (frame.length == 0u) return;
  size_t available = otis_transport_available_for_write();
  if (available == 0u) return;
  size_t remaining = static_cast<size_t>(frame.length - frame.sent);
  size_t chunk = remaining < available ? remaining : available;
  if (chunk > kTransportChunkLimit) chunk = kTransportChunkLimit;
  frame.sent = static_cast<uint16_t>(
      frame.sent + otis_transport_write_bytes(
                       reinterpret_cast<const uint8_t *>(frame.data) + frame.sent,
                       chunk));
  if (frame.sent == frame.length) frame = {};
#endif
#endif
}

void otis_cx317_active_live_emit_status(OtisStatusEmitContext *context,
                                        uint32_t now_s) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (context == nullptr) return;
  const char *state = transaction_bound
                          ? otis_cx317_active_state_name(transaction.state)
                          : "UNBOUND";
  otis_status_emit(context, "cx317_active", "enabled", "true",
                   OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(context, "cx317_active", "run_identity", kRunIdentity,
                   OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(context, "cx317_active", "build_identity", kBuildIdentity,
                   OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(context, "cx317_active", "profile_identity",
                   OTIS_BUILD_PROFILE_ID, OTIS_SEVERITY_INFO,
                   OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(context, "cx317_active", "estimator_sha256", kEstimatorHash,
                   OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(context, "cx317_active", "model_sha256", kModelHash,
                   OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(context, "cx317_active", "active_policy_sha256",
                   kActivePolicyHash, OTIS_SEVERITY_INFO,
                   OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(context, "cx317_active", "response_policy_sha256",
                   kResponsePolicyHash, OTIS_SEVERITY_INFO,
                   OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(context, "cx317_active", "numerical_policy_sha256",
                   kNumericalPolicyHash, OTIS_SEVERITY_INFO,
                   OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(context, "cx317_active", "state", state,
                   transaction_bound &&
                           transaction.state == OtisCx317ActiveState::Fault
                       ? OTIS_SEVERITY_ERROR
                       : OTIS_SEVERITY_INFO,
                   OTIS_FLAG_NONE);
  otis_status_emit(context, "cx317_active", "reason",
                   transaction_bound ? transaction.reason : "session_unbound",
                   OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  otis_status_emit(context, "cx317_active", "capture_lease_live",
                   capture_lease_live(now_s) ? "true" : "false",
                   capture_lease_live(now_s) ? OTIS_SEVERITY_INFO
                                             : OTIS_SEVERITY_WARN,
                   OTIS_FLAG_NONE);
  otis_status_emit(context, "cx317_active", "manual_start_confirmed",
                   manual_start_confirmed ? "true" : "false",
                   manual_start_confirmed ? OTIS_SEVERITY_INFO
                                          : OTIS_SEVERITY_WARN,
                   OTIS_FLAG_NONE);
  otis_status_emit(context, "cx317_active", "evidence_pending",
                   evidence_phase != EvidencePhase::None ? "true" : "false",
                   evidence_phase != EvidencePhase::None ? OTIS_SEVERITY_WARN
                                                         : OTIS_SEVERITY_INFO,
                   OTIS_FLAG_NONE);
  otis_status_emit(context, "cx317_active", "evidence_phase",
                   evidence_state_name(), OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  char value[24];
  snprintf(value, sizeof(value), "%lu", static_cast<unsigned long>(now_s));
  otis_status_emit(context, "cx317_active", "uptime_s", value,
                   OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(transaction_bound
                                          ? transaction.expected_binding.session_id
                                          : 0u));
  otis_status_emit(context, "cx317_active", "session_id", value,
                   OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  const OtisCx317ActiveEligibility current_eligibility = eligibility(now_s);
  otis_status_emit(
      context, "cx317_active", "arm_eligible",
      otis_cx317_active_arm_eligibility_valid(&current_eligibility) ? "true"
                                                                    : "false",
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%u",
           transaction_bound ? transaction.applied_code : 0u);
  otis_status_emit(context, "cx317_active", "confirmed_applied_code", value,
                   OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%u",
           transaction_bound ? transaction.correction_count : 0u);
  otis_status_emit(context, "cx317_active", "correction_count", value,
                   OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%u",
           transaction_bound ? transaction.cumulative_movement_codes : 0u);
  otis_status_emit(context, "cx317_active", "cumulative_movement_codes", value,
                   OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%u",
           have_health ? latest_health.selected_interval_count : 0u);
  otis_status_emit(context, "cx317_active", "selected_interval_count", value,
                   OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  otis_status_emit(context, "cx317_active", "automatic_retry", "false",
                   OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(context, "cx317_active", "automatic_restore", "false",
                   OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
#else
  (void)context;
  (void)now_s;
#endif
}

void otis_cx317_active_live_get_status(OtisCx317ActiveLiveStatus *status,
                                       uint32_t now_s) {
  if (status == nullptr) return;
  *status = {};
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  const OtisCx317ActiveEligibility current_eligibility = eligibility(now_s);
  status->run_identity = kRunIdentity;
  status->build_identity = kBuildIdentity;
  status->profile_identity = OTIS_BUILD_PROFILE_ID;
  status->estimator_sha256 = kEstimatorHash;
  status->model_sha256 = kModelHash;
  status->active_policy_sha256 = kActivePolicyHash;
  status->response_policy_sha256 = kResponsePolicyHash;
  status->numerical_policy_sha256 = kNumericalPolicyHash;
  status->state = transaction_bound
                      ? otis_cx317_active_state_name(transaction.state)
                      : "UNBOUND";
  status->reason = transaction_bound ? transaction.reason : "session_unbound";
  status->evidence_state = evidence_state_name();
  status->session_id = transaction_bound
                           ? transaction.expected_binding.session_id
                           : 0u;
  status->evidence_request_sequence = evidence_request_sequence;
  status->uptime_s = now_s;
  status->applied_code = transaction_bound ? transaction.applied_code : 0u;
  status->correction_count =
      transaction_bound ? transaction.correction_count : 0u;
  status->cumulative_movement_codes =
      transaction_bound ? transaction.cumulative_movement_codes : 0u;
  status->selected_interval_count =
      have_health ? latest_health.selected_interval_count : 0u;
  status->transaction_bound = transaction_bound;
  status->capture_lease_live = capture_lease_live(now_s);
  status->manual_start_confirmed = manual_start_confirmed;
  status->arm_eligible =
      otis_cx317_active_arm_eligibility_valid(&current_eligibility);
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  status->fail_static =
      otis_dual_core_fail_static() ||
      (transaction_bound &&
       (transaction.state == OtisCx317ActiveState::Fault ||
        transaction.state == OtisCx317ActiveState::Aborted));
#else
  status->fail_static = transaction_bound &&
                        (transaction.state == OtisCx317ActiveState::Fault ||
                         transaction.state == OtisCx317ActiveState::Aborted);
#endif
#else
  (void)now_s;
  status->state = "DISABLED";
  status->reason = "active_control_compiled_out";
  status->evidence_state = "evidence_clear";
#endif
}

const char *otis_cx317_active_live_run_identity(void) { return kRunIdentity; }

uint16_t otis_cx317_active_live_start_code(void) {
  return static_cast<uint16_t>(OTIS_CX317_ACTIVE_START_CODE);
}
