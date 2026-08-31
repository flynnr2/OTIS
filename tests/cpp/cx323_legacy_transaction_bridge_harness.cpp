#include <assert.h>
#include <stdint.h>
#include <string.h>

#include "otis_cx317_active_transaction.h"
#include "otis_cx323_phase_priority_maintenance.h"

namespace {

constexpr uint16_t kStartCode = 43085u;
constexpr uint64_t kCaptureTicksPerSecond = 16000000ull;
constexpr uint64_t kSetupApplicationTicks = 9937789536ull;
constexpr uint64_t kFirstSelectedObservationTicks = 38425559872ull;
constexpr uint64_t kCadenceBoundaryTicks =
    kSetupApplicationTicks + 1800ull * kCaptureTicksPerSecond;

OtisCx317ActiveBinding binding() {
  return {
      "cx323-run", "cx323-build", "cx323-profile", "frequency-estimator",
      "plant-model", "cx323-policy", "response-policy", "cx323-policy", 1u,
      kStartCode, 0xA800u, 0xAB00u, 21u, 144u, 3024u, true, false, true,
  };
}

OtisCx317ActiveEligibility healthy() {
  return {true, true, true, true, true, true, true, true, true, true,
          true, true, true, true, true, true, true, true, true, true};
}

OtisCx323Observation outside_tight_observation(
    uint64_t timestamp_ticks, uint64_t source_first_sequence) {
  return {
      timestamp_ticks / kCaptureTicksPerSecond,
      1u,
      source_first_sequence,
      source_first_sequence + 600u,
      1u,
      kStartCode,
      2,
      false,
      1u,
      0,
      0xC323u,
      true,
      true,
      true,
      true,
      true,
      timestamp_ticks,
  };
}

}  // namespace

int main() {
  const OtisCx317ActiveBinding expected = binding();
  const OtisCx317ActiveEligibility eligibility = healthy();
  OtisCx317ActiveTransaction transaction = {};
  otis_cx317_active_transaction_init(&transaction, &expected);
  transaction.dac_epoch = 1u;
  transaction.have_last_application = true;
  transaction.last_application_s = static_cast<uint32_t>(
      kSetupApplicationTicks / kCaptureTicksPerSecond);

  const OtisCx323Policy policy = otis_cx323_default_policy();
  OtisCx323Engine controller = {};
  assert(otis_cx323_engine_init(&controller, &policy, kStartCode, 1u));
  assert(otis_cx323_engine_bind_exact_setup_application(
      &controller, kSetupApplicationTicks));
  assert(controller.last_application_available);
  assert(controller.last_application_ticks == kSetupApplicationTicks);
  assert(controller.last_application_s ==
         kSetupApplicationTicks / kCaptureTicksPerSecond);
  assert(otis_cx323_engine_new_policy_activation(&controller));

  const OtisCx323Observation first_selected = outside_tight_observation(
      kFirstSelectedObservationTicks, 1000u);
  OtisCx323Decision cadence_hold = {};
  assert(otis_cx323_engine_decide(&controller, &first_selected,
                                  &cadence_hold));
  assert(strcmp(cadence_hold.reason, "cadence_hold") == 0);
  assert(cadence_hold.requested_delta_codes == 0);
  assert(cadence_hold.cadence_limited);
  assert(!cadence_hold.maintenance_request);
  assert(!controller.request_pending);

  const OtisCx323Observation observation = outside_tight_observation(
      kCadenceBoundaryTicks, 1600u);
  const uint32_t decision_time_s =
      static_cast<uint32_t>(observation.timestamp_s);
  const OtisCx317ArmRequest arm = {
      expected, 1u, 0xC3230001u, decision_time_s + 60u};
  assert(otis_cx317_active_arm(&transaction, &arm, &eligibility,
                               decision_time_s));
  OtisCx323Decision native_decision = {};
  assert(!controller.request_pending);
  assert(otis_cx323_engine_decide(&controller, &observation,
                                  &native_decision));
  assert(strcmp(native_decision.reason,
                "outside_tight_legacy_request_ready") == 0);
  assert(native_decision.requested_delta_codes != 0);
  assert(!native_decision.maintenance_request);
  assert(controller.request_pending);

  const OtisCx317ActiveDecision transaction_decision = {
      static_cast<uint32_t>(native_decision.decision_sequence),
      static_cast<uint32_t>(observation.source_first_sequence),
      static_cast<uint32_t>(observation.source_last_sequence),
      static_cast<uint32_t>(observation.timestamp_s),
      static_cast<uint16_t>(observation.applied_code),
      native_decision.requested_delta_codes,
      static_cast<uint16_t>(native_decision.requested_code),
      0.020,
  };
  OtisCx317ActionableRequest request = {};
  assert(otis_cx317_active_make_request(&transaction, &transaction_decision,
                                        &eligibility, decision_time_s,
                                        &request));
  assert(request.actionable);
  assert(request.requested_delta_codes ==
         native_decision.requested_delta_codes);
  assert(request.requested_code == native_decision.requested_code);

  OtisCx317AcceptedRequest accepted = {};
  assert(otis_cx317_active_accept(&transaction, &request, decision_time_s,
                                  &accepted));
  const OtisCx317AppliedAck applied = {
      request.request_sequence,
      request.authorization_sequence,
      request.nonce,
      request.requested_code,
      accepted.accepted_code,
      request.requested_code,
      1u,
      decision_time_s,
      true,
      false,
      false,
  };
  assert(otis_cx317_active_acknowledge_application(&transaction, &applied));
  assert(transaction.state == OtisCx317ActiveState::AwaitingResponse);

  assert(otis_cx323_engine_note_application_and_first_consumer(
      &controller, &native_decision, transaction.applied_code,
      transaction.dac_epoch, true));
  assert(!controller.request_pending);
  assert(controller.response_pending);
  assert(controller.debt.fll_picocodes == 0);
  assert(controller.debt.pll_picocodes == 0);

  OtisCx317ResponseResult response = {};
  assert(otis_cx317_active_record_response(&transaction, 0.019, true, true,
                                           &response));
  assert(otis_cx323_engine_complete_response(&controller, true));
  assert(transaction.state == OtisCx317ActiveState::Disarmed);
  assert(!controller.response_pending);
  assert(controller.application_count == 1u);
  assert(controller.applied_code == transaction.applied_code);
  assert(controller.dac_epoch == transaction.dac_epoch);
  return 0;
}
