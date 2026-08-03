#include "otis_cx317_active_live.h"

#include <stdio.h>
#include <string.h>

#include "otis_config.h"
#include "otis_cx317_active_actuator.h"
#include "otis_protocol.h"
#include "otis_transport_serial.h"

namespace {

constexpr char kEstimatorHash[] =
    "5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c";
constexpr char kModelHash[] =
    "d8fbc3539759be1de60d6b4507a50f029b3eaf830952b65ddb4c9849992ef8dd";
constexpr char kNumericalPolicyHash[] =
    "19cddd7cb169c4c733b7cfd69085f9ecc087ad77a874f265c4c7c0f053aced43";
constexpr char kActivePolicyHash[] =
    "657df688c8e6b1bce1ac8280b46e5388ee1d6dfbe31e34735611c933ca4f261e";
constexpr char kResponsePolicyHash[] =
    "0a7ec7b8f569da4a233c03e56c42bd7bd522ca1c27e97d4028b6c52a2ecfe963";
constexpr uint32_t kCaptureLeaseMaximumAgeS = 30u;
constexpr size_t kFrameCapacity = 1536u;
constexpr size_t kTransportChunkLimit = 192u;

#if OTIS_CX317_ACTIVE_CAMPAIGN == OTIS_CX317_ACTIVE_CAMPAIGN_A
constexpr char kRunIdentity[] = "cx317_bounded_campaign_a:3170001";
constexpr char kExpectedProfile[] = "cx317_bounded_active_campaign_a";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == OTIS_CX317_ACTIVE_CAMPAIGN_B
constexpr char kRunIdentity[] = "cx317_bounded_campaign_b:3170002";
constexpr char kExpectedProfile[] = "cx317_bounded_active_campaign_b";
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

OtisCx317ActiveTransaction transaction;
OtisCx317ActiveLiveHealth latest_health = {};
TransportFrame frame = {};
bool initialized = false;
bool transaction_bound = false;
bool have_health = false;
bool have_capture_lease = false;
bool manual_start_confirmed = false;
bool evidence_pending = false;
uint32_t last_capture_lease_s = 0u;
uint32_t last_capture_lease_sequence = 0u;
uint32_t evidence_request_sequence = 0u;

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
      !evidence_pending,
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

bool queue_frame(const char *event, const OtisCx317ResponseResult *response) {
  if (frame.length != 0u) return false;
  const char *response_name =
      response == nullptr ? "unavailable"
                          : otis_cx317_response_class_name(response->classification);
  const char *reason = response == nullptr ? transaction.reason : response->reason;
  const int used = snprintf(
      frame.data, sizeof(frame.data),
      "ACT,1,%s,%s,%s,%s,%lu,%lu,%lu,%lu,%lu,%u,%ld,%u,%u,%u,%u,%lu,%u,%u,%u,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\r\n",
      event, kRunIdentity, kBuildIdentity, OTIS_BUILD_PROFILE_ID,
      static_cast<unsigned long>(transaction.expected_binding.session_id),
      static_cast<unsigned long>(transaction.request.authorization_sequence),
      static_cast<unsigned long>(transaction.request.nonce),
      static_cast<unsigned long>(transaction.request.request_sequence),
      static_cast<unsigned long>(transaction.request.decision_sequence),
      transaction.request.current_applied_code,
      static_cast<long>(transaction.request.requested_delta_codes),
      transaction.request.requested_code, transaction.accepted.accepted_code,
      transaction.applied.applied_code, transaction.applied.application_sequence,
      static_cast<unsigned long>(transaction.applied.application_timestamp_s),
      transaction.dac_epoch, transaction.correction_count,
      transaction.cumulative_movement_codes,
      otis_cx317_active_state_name(transaction.state), response_name, reason,
      kEstimatorHash, kModelHash, kActivePolicyHash, kResponsePolicyHash,
      kNumericalPolicyHash, transaction.request.actionable ? "true" : "false",
      evidence_pending ? "evidence_pending" : "evidence_clear");
  if (used <= 0 || static_cast<size_t>(used) >= sizeof(frame.data)) {
    frame = {};
    return false;
  }
  frame.length = static_cast<uint16_t>(used);
  frame.sent = 0u;
  return true;
}

bool queue_manual_start_frame(uint16_t code, bool ok, uint32_t now_s) {
  if (frame.length != 0u) return false;
  const int used = snprintf(
      frame.data, sizeof(frame.data),
      "ACT,1,manual_start,%s,%s,%s,%lu,0,0,0,0,%u,0,%u,%u,%u,0,%lu,0,0,0,%s,unavailable,%s,%s,%s,%s,%s,%s,false,evidence_clear\r\n",
      kRunIdentity, kBuildIdentity, OTIS_BUILD_PROFILE_ID,
      static_cast<unsigned long>(transaction_bound
                                     ? transaction.expected_binding.session_id
                                     : 0u),
      code, code, code, code, static_cast<unsigned long>(now_s),
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
  return true;
}

void fault_if_active_continuity_lost(uint32_t now_s) {
  if (!transaction_bound) return;
  if ((transaction.state == OtisCx317ActiveState::Armed ||
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
  evidence_pending = false;
  last_capture_lease_sequence = 0u;
  evidence_request_sequence = 0u;
  frame = {};
  return true;
#else
  return true;
#endif
}

void otis_cx317_active_live_emit_headers(void) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  otis_transport_write_cstr(
      "record_type,schema_version,event,run_identity,build_identity,profile_identity,session_id,authorization_sequence,nonce,request_sequence,decision_sequence,current_applied_code,requested_delta_codes,requested_code,accepted_code,applied_code,application_sequence,application_timestamp_s,dac_epoch,correction_count,cumulative_movement_codes,active_state,response_class,reason,estimator_sha256,model_sha256,active_policy_sha256,response_policy_sha256,numerical_policy_sha256,actionable,evidence_state\r\n");
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
#else
  (void)reason;
#endif
}

bool otis_cx317_active_live_acknowledge_evidence(uint32_t request_sequence) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (!evidence_pending || request_sequence != evidence_request_sequence)
    return false;
  evidence_pending = false;
  return true;
#else
  (void)request_sequence;
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
  const OtisCx317ActiveEligibility health = eligibility(decision->timestamp_s);
  if (transaction.state == OtisCx317ActiveState::AwaitingResponse) {
    OtisCx317ResponseResult response;
    const bool accepted = otis_cx317_active_record_response(
        &transaction, decision->frequency_error_hz,
        decision->preview_available &&
            otis_cx317_active_eligibility_valid(&health),
        &response);
    outcome->response_recorded = true;
    outcome->response_class = response.classification;
    outcome->reason = response.reason;
    outcome->faulted = !accepted;
    evidence_pending = true;
    evidence_request_sequence = transaction.request.request_sequence;
    if (!queue_frame("response", &response)) {
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
  if (!decision->preview_available ||
      !otis_cx317_active_make_request(&transaction, &request_input, &health,
                                      decision->timestamp_s, &request)) {
    outcome->faulted = transaction.state == OtisCx317ActiveState::Fault;
    outcome->reason = transaction.reason;
    return;
  }
  OtisCx317AcceptedRequest accepted;
  if (!otis_cx317_active_accept(&transaction, &request, decision->timestamp_s,
                                &accepted)) {
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  const OtisCx317AppliedAck applied = otis_cx317_active_actuator_apply_once(
      &request, &accepted,
      static_cast<uint16_t>(transaction.correction_count + 1u),
      decision->timestamp_s);
  const bool acknowledged =
      otis_cx317_active_acknowledge_application(&transaction, &applied);
  outcome->request_sequence = request.request_sequence;
  outcome->requested_code = request.requested_code;
  outcome->applied_code = applied.applied_code;
  outcome->applied = acknowledged;
  outcome->faulted = !acknowledged;
  outcome->reason = transaction.reason;
  evidence_pending = true;
  evidence_request_sequence = request.request_sequence;
  if (!queue_frame(acknowledged ? "application" : "application_fault",
                   nullptr)) {
    otis_cx317_active_fault(&transaction, "application_evidence_queue_fault");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
  }
#else
  (void)decision;
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
                   evidence_pending ? "true" : "false",
                   evidence_pending ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
                   OTIS_FLAG_NONE);
  char value[24];
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
  otis_status_emit(context, "cx317_active", "automatic_retry", "false",
                   OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_status_emit(context, "cx317_active", "automatic_restore", "false",
                   OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
#else
  (void)context;
  (void)now_s;
#endif
}

const char *otis_cx317_active_live_run_identity(void) { return kRunIdentity; }

uint16_t otis_cx317_active_live_start_code(void) {
  return static_cast<uint16_t>(OTIS_CX317_ACTIVE_START_CODE);
}
