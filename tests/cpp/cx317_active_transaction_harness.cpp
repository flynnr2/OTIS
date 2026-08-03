#include <assert.h>
#include <math.h>
#include <stdint.h>

#include "otis_cx317_active_transaction.h"

namespace {

OtisCx317ActiveBinding binding(uint16_t start = 0xA950u) {
  return {"run-a", "build", "profile", "estimator", "model", "policy",
          "response", "numerical", 1u,
          start, 0xA800u, 0xAB00u, 21u, 16u, 336u};
}

OtisCx317ActiveEligibility healthy() {
  return {true, true, true, true, true, true, true, true, true, true,
          true, true, true, true, true, true, true, true, true, true};
}

OtisCx317ArmRequest arm(const OtisCx317ActiveBinding &value,
                       uint32_t sequence = 1u, uint32_t now = 2400u) {
  return {value, sequence, 0xABC00000u + sequence, now + 60u};
}

OtisCx317ActiveDecision decision(uint16_t current, uint32_t sequence = 1u,
                                 uint32_t now = 2400u,
                                 int32_t delta = -21) {
  return {sequence, 1000u + sequence, 1600u + sequence, now, current, delta,
          static_cast<uint16_t>(static_cast<int32_t>(current) + delta), 0.020};
}

void happy_transaction() {
  const auto expected = binding();
  auto eligibility = healthy();
  OtisCx317ActiveTransaction transaction;
  otis_cx317_active_transaction_init(&transaction, &expected);
  auto authorization = arm(expected);
  assert(otis_cx317_active_arm(&transaction, &authorization, &eligibility,
                               2400u));
  assert(transaction.state == OtisCx317ActiveState::Armed);

  auto numerical = decision(transaction.applied_code);
  OtisCx317ActionableRequest request;
  assert(otis_cx317_active_make_request(&transaction, &numerical,
                                        &eligibility, 2400u, &request));
  assert(request.actionable);
  assert(request.requested_code == 0xA950u - 21u);

  OtisCx317AcceptedRequest accepted;
  assert(otis_cx317_active_accept(&transaction, &request, 2400u, &accepted));
  assert(!accepted.actionable);
  assert(!transaction.request.actionable);

  OtisCx317AppliedAck applied = {
      request.request_sequence,
      request.authorization_sequence,
      request.nonce,
      request.requested_code,
      accepted.accepted_code,
      request.requested_code,
      1u,
      2400u,
      true,
      false,
      false,
  };
  assert(otis_cx317_active_acknowledge_application(&transaction, &applied));
  assert(transaction.state == OtisCx317ActiveState::AwaitingResponse);
  assert(transaction.applied_code == request.requested_code);
  assert(transaction.correction_count == 1u);
  assert(transaction.cumulative_movement_codes == 21u);
  assert(transaction.dac_epoch == 1u);

  OtisCx317ResponseResult response;
  assert(otis_cx317_active_record_response(&transaction, 0.0165, true,
                                           &response));
  assert(response.classification == OtisCx317ResponseClass::HealthyDetected);
  assert(transaction.state == OtisCx317ActiveState::Disarmed);
}

void binding_and_health_fail_closed() {
  const auto expected = binding();
  OtisCx317ActiveTransaction transaction;
  otis_cx317_active_transaction_init(&transaction, &expected);
  auto eligibility = healthy();
  eligibility.gnss_metadata_valid = false;
  auto authorization = arm(expected);
  assert(!otis_cx317_active_arm(&transaction, &authorization, &eligibility,
                                2400u));
  assert(transaction.state == OtisCx317ActiveState::Fault);
  assert(transaction.applied_code == 0xA950u);

  otis_cx317_active_transaction_init(&transaction, &expected);
  eligibility = healthy();
  authorization = arm(expected);
  authorization.binding.response_sha256 = "wrong-response";
  assert(!otis_cx317_active_arm(&transaction, &authorization, &eligibility,
                                2400u));
  assert(transaction.state == OtisCx317ActiveState::Fault);
}

void acknowledgement_failure_never_retries_or_restores() {
  const auto expected = binding();
  auto eligibility = healthy();
  OtisCx317ActiveTransaction transaction;
  otis_cx317_active_transaction_init(&transaction, &expected);
  auto authorization = arm(expected);
  assert(otis_cx317_active_arm(&transaction, &authorization, &eligibility,
                               2400u));
  auto numerical = decision(transaction.applied_code);
  OtisCx317ActionableRequest request;
  assert(otis_cx317_active_make_request(&transaction, &numerical,
                                        &eligibility, 2400u, &request));
  OtisCx317AcceptedRequest accepted;
  assert(otis_cx317_active_accept(&transaction, &request, 2400u, &accepted));
  OtisCx317AppliedAck failed = {
      request.request_sequence, request.authorization_sequence, request.nonce,
      request.requested_code, accepted.accepted_code, expected.start_code, 1u,
      2400u, false, false, true};
  assert(!otis_cx317_active_acknowledge_application(&transaction, &failed));
  assert(transaction.state == OtisCx317ActiveState::Fault);
  assert(transaction.applied_code == expected.start_code);
  assert(transaction.correction_count == 0u);
}

void bounds_abort_and_response_stops() {
  const auto expected = binding();
  auto eligibility = healthy();
  OtisCx317ActiveTransaction transaction;
  otis_cx317_active_transaction_init(&transaction, &expected);
  auto authorization = arm(expected);
  assert(otis_cx317_active_arm(&transaction, &authorization, &eligibility,
                               2400u));
  auto too_large = decision(transaction.applied_code, 1u, 2400u, -22);
  OtisCx317ActionableRequest request;
  assert(!otis_cx317_active_make_request(&transaction, &too_large,
                                         &eligibility, 2400u, &request));
  assert(transaction.state == OtisCx317ActiveState::Fault);

  otis_cx317_active_transaction_init(&transaction, &expected);
  authorization = arm(expected);
  assert(otis_cx317_active_arm(&transaction, &authorization, &eligibility,
                               2400u));
  otis_cx317_active_abort(&transaction, "device_abort_command");
  assert(transaction.state == OtisCx317ActiveState::Aborted);
  assert(!transaction.have_arm);

  otis_cx317_active_transaction_init(&transaction, &expected);
  authorization = arm(expected);
  assert(otis_cx317_active_arm(&transaction, &authorization, &eligibility,
                               2400u));
  auto numerical = decision(transaction.applied_code);
  assert(otis_cx317_active_make_request(&transaction, &numerical,
                                        &eligibility, 2400u, &request));
  OtisCx317AcceptedRequest accepted;
  assert(otis_cx317_active_accept(&transaction, &request, 2400u, &accepted));
  OtisCx317AppliedAck applied = {
      request.request_sequence, request.authorization_sequence, request.nonce,
      request.requested_code, accepted.accepted_code, request.requested_code,
      1u, 2400u, true, false, false};
  assert(otis_cx317_active_acknowledge_application(&transaction, &applied));
  OtisCx317ResponseResult response;
  assert(!otis_cx317_active_record_response(&transaction, 0.024, true,
                                            &response));
  assert(response.classification == OtisCx317ResponseClass::WrongSign);
  assert(transaction.state == OtisCx317ActiveState::Fault);
}

}  // namespace

int main() {
  happy_transaction();
  binding_and_health_fail_closed();
  acknowledgement_failure_never_retries_or_restores();
  bounds_abort_and_response_stops();
  return 0;
}
