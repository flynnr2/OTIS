#include <assert.h>
#include <stdint.h>

#include "otis_cx317_active_transaction.h"
#include "otis_cx317_dual_core_state.h"
#include "otis_cx317_i_only_engine.h"

namespace {

OtisCx317PreviewInput preview_input(uint32_t timestamp_s, double error_hz,
                                    bool frequency_available,
                                    uint16_t code) {
  return {
      timestamp_s, error_hz, code, 25.0, frequency_available,
      true,        true,     true, true, true,
      true,        true,     true, false, false,
  };
}

OtisCx317ActiveEligibility healthy() {
  return {true, true, true, true, true, true, true, true, true, true,
          true, true, true, true, true, true, true, true, true, true};
}

void complete_rehearsal_sequence() {
  constexpr uint16_t kStart = 0xA800u;
  constexpr uint16_t kApplied = 0xA815u;
  constexpr uint16_t kSecondApplied = 0xA82Au;
  OtisCx317IOnlyEngine engine = {};
  otis_cx317_i_only_engine_init(&engine, 0u);

  OtisCx317PreviewDecision preview = {};
  auto warmup = preview_input(60u, 0.0, false, kStart);
  otis_cx317_i_only_engine_evaluate(&engine, &warmup, &preview);
  assert(!preview.preview_available);
  assert(engine.state == OtisCx317PreviewState::Qualifying);

  auto first_selected =
      preview_input(180u, -0.008333332837, true, kStart);
  otis_cx317_i_only_engine_evaluate(&engine, &first_selected, &preview);
  assert(preview.preview_available);
  assert(preview.limited_delta_codes == 21);
  assert(preview.proposed_code == kApplied);

  const OtisCx317ActiveBinding binding = {
      "cx317_stage7_rehearsal:3170005",
      "build",
      "cx317_dual_core_active_rehearsal",
      "estimator",
      "model",
      "policy",
      "response",
      "numerical",
      1u,
      kStart,
      0xA800u,
      0xAB00u,
      21u,
      2u,
      42u,
      false,
      true,
      false,
  };
  OtisCx317ActiveTransaction transaction = {};
  otis_cx317_active_transaction_init(&transaction, &binding);
  const auto eligibility = healthy();
  const OtisCx317ArmRequest arm = {binding, 1u, 0x12345678u, 200u};
  assert(otis_cx317_active_arm(&transaction, &arm, &eligibility, 175u));

  const OtisCx317ActiveDecision decision = {
      1u,
      60u,
      180u,
      180u,
      kStart,
      preview.limited_delta_codes,
      preview.proposed_code,
      preview.frequency_error_hz,
  };
  OtisCx317ActionableRequest request = {};
  assert(otis_cx317_active_make_request(&transaction, &decision, &eligibility,
                                        180u, &request));
  assert(request.requested_code == kApplied);

  OtisCx317AcceptedRequest accepted = {};
  assert(otis_cx317_active_accept(&transaction, &request, 180u, &accepted));
  const OtisCx317AppliedAck applied = {
      request.request_sequence,
      request.authorization_sequence,
      request.nonce,
      request.requested_code,
      accepted.accepted_code,
      request.requested_code,
      1u,
      180u,
      true,
      false,
      false,
  };
  assert(otis_cx317_active_acknowledge_application(&transaction, &applied));

  // Reproduce the live inter-core ordering: the last periodic state still
  // names A800 when the exact applied acknowledgement arrives.  The applied
  // acknowledgement must advance the cache synchronously before health runs.
  OtisCx317StaticCodeState core1_cache = {};
  OtisAppliedDacStateMessage periodic = {};
  periodic.initialized = true;
  periodic.i2c_ok = true;
  periodic.requested_applied_match = true;
  periodic.requested_code = kStart;
  periodic.applied_code = kStart;
  otis_cx317_dual_core_static_state_on_periodic(&core1_cache, &periodic);
  OtisCrossCoreActuatorAck cross_ack = {};
  cross_ack.kind = OtisActuatorAckKind::Applied;
  cross_ack.requested_code = kApplied;
  cross_ack.accepted_code = kApplied;
  cross_ack.applied_code = kApplied;
  cross_ack.i2c_ok = true;
  assert(otis_cx317_dual_core_static_state_on_applied_ack(
      &core1_cache, &cross_ack, true));
  assert(core1_cache.applied_code == transaction.applied_code);

  otis_cx317_i_only_engine_note_dac_epoch(&engine, 180u);
  auto response_selected =
      preview_input(360u, -0.008333332837, true, kApplied);
  otis_cx317_i_only_engine_evaluate(&engine, &response_selected, &preview);
  assert(preview.preview_available);
  OtisCx317ResponseResult response = {};
  assert(otis_cx317_active_record_response(
      &transaction, response_selected.frequency_error_hz, true, true,
      &response));
  assert(response.classification ==
         OtisCx317ResponseClass::HealthyIndeterminateNearResolution);
  assert(transaction.state == OtisCx317ActiveState::Disarmed);

  auto cadence_hold = preview_input(480u, -0.008333332837, true, kApplied);
  otis_cx317_i_only_engine_evaluate(&engine, &cadence_hold, &preview);
  assert(!preview.preview_available);
  auto second_selected =
      preview_input(600u, -0.008333332837, true, kApplied);
  otis_cx317_i_only_engine_evaluate(&engine, &second_selected, &preview);
  assert(preview.preview_available);
  assert(preview.limited_delta_codes == 21);
  assert(preview.proposed_code == kSecondApplied);

  const OtisCx317ArmRequest second_arm = {
      binding, 2u, 0x87654321u, 680u};
  assert(otis_cx317_active_arm(&transaction, &second_arm, &eligibility,
                              590u));
  const OtisCx317ActiveDecision second_decision = {
      2u,
      181u,
      300u,
      600u,
      kApplied,
      preview.limited_delta_codes,
      preview.proposed_code,
      preview.frequency_error_hz,
  };
  OtisCx317ActionableRequest second_request = {};
  assert(otis_cx317_active_make_request(
      &transaction, &second_decision, &eligibility, 600u, &second_request));
  assert(second_request.requested_code == kSecondApplied);
  assert(transaction.accepted.accepted_code == 0u);
  assert(transaction.accepted.accepted_timestamp_s == 0u);
  assert(transaction.applied.applied_code == 0u);
  assert(transaction.applied.application_sequence == 0u);

  OtisCx317AcceptedRequest second_accepted = {};
  assert(otis_cx317_active_accept(&transaction, &second_request, 600u,
                                  &second_accepted));
  const OtisCx317AppliedAck second_applied = {
      second_request.request_sequence,
      second_request.authorization_sequence,
      second_request.nonce,
      second_request.requested_code,
      second_accepted.accepted_code,
      second_request.requested_code,
      2u,
      600u,
      true,
      false,
      false,
  };
  assert(otis_cx317_active_acknowledge_application(&transaction,
                                                   &second_applied));
  cross_ack.requested_code = kSecondApplied;
  cross_ack.accepted_code = kSecondApplied;
  cross_ack.applied_code = kSecondApplied;
  assert(otis_cx317_dual_core_static_state_on_applied_ack(
      &core1_cache, &cross_ack, true));
  assert(core1_cache.applied_code == kSecondApplied);

  otis_cx317_i_only_engine_note_dac_epoch(&engine, 600u);
  auto second_response_selected =
      preview_input(780u, -0.008333332837, true, kSecondApplied);
  otis_cx317_i_only_engine_evaluate(&engine, &second_response_selected,
                                    &preview);
  assert(preview.preview_available);
  OtisCx317ResponseResult second_response = {};
  assert(otis_cx317_active_record_response(
      &transaction, second_response_selected.frequency_error_hz, true, true,
      &second_response));
  assert(second_response.classification ==
         OtisCx317ResponseClass::HealthyIndeterminateNearResolution);
  assert(transaction.state == OtisCx317ActiveState::Disarmed);

  uint32_t service_queries = 0u;
  for (; service_queries < 60u; ++service_queries) {
  }
  assert(service_queries == 60u);
  auto post_service_hold =
      preview_input(900u, -0.008333332837, true, kSecondApplied);
  otis_cx317_i_only_engine_evaluate(&engine, &post_service_hold, &preview);
  assert(!preview.preview_available);
  auto later_eligible =
      preview_input(1020u, -0.008333332837, true, kSecondApplied);
  otis_cx317_i_only_engine_evaluate(&engine, &later_eligible, &preview);
  assert(preview.preview_available);
  assert(transaction.state == OtisCx317ActiveState::Disarmed);
  assert(core1_cache.applied_code == kSecondApplied);
}

}  // namespace

int main() {
  complete_rehearsal_sequence();
  return 0;
}
