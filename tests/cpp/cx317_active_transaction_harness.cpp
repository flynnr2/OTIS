#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <string.h>

#include "otis_cx317_active_transaction.h"

namespace {

OtisCx317ActiveBinding binding(uint16_t start = 0xA950u,
                              bool dither_stop = false) {
  return {"run-a", "build", "profile", "estimator", "model", "policy",
          "response", "numerical", 1u,
          start, 0xA800u, 0xAB00u, 21u,
          static_cast<uint16_t>(dither_stop ? 32u : 16u),
          static_cast<uint16_t>(dither_stop ? 672u : 336u), dither_stop};
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
  assert(otis_cx317_active_record_response(&transaction, 0.0165, true, true,
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
  assert(!otis_cx317_active_record_response(&transaction, 0.024, true, true,
                                            &response));
  assert(response.classification == OtisCx317ResponseClass::WrongSign);
  assert(transaction.state == OtisCx317ActiveState::Fault);
}

void temperature_covariate_and_out_of_model_hold() {
  const auto expected = binding();
  auto eligibility = healthy();
  eligibility.temperature_valid = false;
  assert(otis_cx317_active_arm_eligibility_valid(&eligibility));
  assert(otis_cx317_active_eligibility_valid(&eligibility));
  assert(otis_cx317_active_response_measurement_valid(&eligibility));

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
  OtisCx317AppliedAck applied = {
      request.request_sequence, request.authorization_sequence, request.nonce,
      request.requested_code, accepted.accepted_code, request.requested_code,
      1u, 2400u, true, false, false};
  assert(otis_cx317_active_acknowledge_application(&transaction, &applied));
  OtisCx317ResponseResult response;
  assert(otis_cx317_active_record_response(&transaction, 0.0165, true, false,
                                           &response));
  assert(response.classification == OtisCx317ResponseClass::HealthyDetected);
  assert(transaction.state == OtisCx317ActiveState::OutOfModelHold);
  assert(!transaction.have_request);

  eligibility.model_applicable = false;
  authorization = arm(expected, 2u, 4200u);
  assert(!otis_cx317_active_arm(&transaction, &authorization, &eligibility,
                                4200u));
  assert(transaction.state == OtisCx317ActiveState::OutOfModelHold);
  eligibility.model_applicable = true;
  assert(otis_cx317_active_arm(&transaction, &authorization, &eligibility,
                               4200u));
  assert(transaction.state == OtisCx317ActiveState::Armed);
}

void complete_dither_step(OtisCx317ActiveTransaction *transaction,
                          const OtisCx317ActiveBinding &expected,
                          OtisCx317ActiveEligibility *eligibility,
                          uint32_t sequence, uint32_t now_s, int32_t delta,
                          double *error_hz) {
  auto authorization = arm(expected, sequence, now_s);
  assert(otis_cx317_active_arm(transaction, &authorization, eligibility,
                               now_s));
  auto numerical = decision(transaction->applied_code, sequence, now_s, delta);
  numerical.pre_error_hz = *error_hz;
  OtisCx317ActionableRequest request;
  assert(otis_cx317_active_make_request(transaction, &numerical, eligibility,
                                        now_s, &request));
  OtisCx317AcceptedRequest accepted;
  assert(otis_cx317_active_accept(transaction, &request, now_s, &accepted));
  OtisCx317AppliedAck applied = {
      request.request_sequence,
      request.authorization_sequence,
      request.nonce,
      request.requested_code,
      accepted.accepted_code,
      request.requested_code,
      request.correction_ordinal,
      now_s,
      true,
      false,
      false,
  };
  assert(otis_cx317_active_acknowledge_application(transaction, &applied));
  *error_hz += delta > 0 ? 0.004 : -0.004;
  OtisCx317ResponseResult response;
  assert(otis_cx317_active_record_response(transaction, *error_hz, true, true,
                                           &response));
}

void prospective_dither_guards_stop_before_write() {
  auto expected = binding(0xA900u, true);
  auto eligibility = healthy();
  OtisCx317ActiveTransaction transaction;
  otis_cx317_active_transaction_init(&transaction, &expected);
  double error_hz = 0.020;
  complete_dither_step(&transaction, expected, &eligibility, 1u, 2400u, 21,
                       &error_hz);
  complete_dither_step(&transaction, expected, &eligibility, 2u, 4200u, -21,
                       &error_hz);
  complete_dither_step(&transaction, expected, &eligibility, 3u, 6000u, 21,
                       &error_hz);
  auto authorization = arm(expected, 4u, 7800u);
  assert(otis_cx317_active_arm(&transaction, &authorization, &eligibility,
                               7800u));
  auto reversal = decision(transaction.applied_code, 4u, 7800u, -21);
  reversal.pre_error_hz = error_hz;
  OtisCx317ActionableRequest request;
  assert(!otis_cx317_active_make_request(&transaction, &reversal,
                                         &eligibility, 7800u, &request));
  assert(transaction.state == OtisCx317ActiveState::Fault);
  assert(transaction.correction_count == 3u);
  assert(strcmp(transaction.reason,
                "prospective_third_consecutive_reversal_dither_stop") == 0);

  otis_cx317_active_transaction_init(&transaction, &expected);
  error_hz = 0.020;
  uint32_t sequence = 1u;
  uint32_t now_s = 2400u;
  for (uint8_t index = 0u; index < 4u; ++index) {
    complete_dither_step(&transaction, expected, &eligibility, sequence++,
                         now_s, 21, &error_hz);
    now_s += 1800u;
  }
  for (uint8_t index = 0u; index < 3u; ++index) {
    complete_dither_step(&transaction, expected, &eligibility, sequence++,
                         now_s, -21, &error_hz);
    now_s += 1800u;
  }
  authorization = arm(expected, sequence, now_s);
  assert(otis_cx317_active_arm(&transaction, &authorization, &eligibility,
                               now_s));
  auto inefficient =
      decision(transaction.applied_code, sequence, now_s, -21);
  inefficient.pre_error_hz = error_hz;
  assert(!otis_cx317_active_make_request(&transaction, &inefficient,
                                         &eligibility, now_s, &request));
  assert(transaction.state == OtisCx317ActiveState::Fault);
  assert(transaction.correction_count == 7u);
  assert(strcmp(transaction.reason,
                "prospective_low_net_excess_path_dither_stop") == 0);
}

}  // namespace

int main() {
  happy_transaction();
  binding_and_health_fail_closed();
  acknowledgement_failure_never_retries_or_restores();
  bounds_abort_and_response_stops();
  temperature_covariate_and_out_of_model_hold();
  prospective_dither_guards_stop_before_write();
  return 0;
}
