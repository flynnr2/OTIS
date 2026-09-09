#include <assert.h>
#include <stdint.h>
#include <string.h>

#include "otis_regulation_transaction.h"

namespace {

OtisRegulationBinding binding() {
  return {"run-a", "build", "adaptive_hybrid_regulation", "estimator",
          "model", "policy", "response", "numerical", 1u, 0xA950u,
          0xA800u, 0xAB00u, 21u, 144u, 3024u, false, true};
}

OtisRegulationEligibility healthy() {
  return {true, true, true, true, true, true, true, true, true, true,
          true, true, true, true, true, true, true, true, true, true};
}

OtisRegulationArmRequest arm(const OtisRegulationBinding &value,
                             uint32_t sequence = 1u) {
  return {value, sequence, 0xABC00000u + sequence, 2460u};
}

OtisRegulationDecision decision(uint16_t current) {
  return {1u, 1001u, 1601u, 2400u, current, -21,
          static_cast<uint16_t>(current - 21u), 0.020};
}

void happy_transaction() {
  const auto expected = binding();
  const auto eligibility = healthy();
  OtisRegulationTransaction transaction;
  otis_regulation_transaction_init(&transaction, &expected);

  const auto authorization = arm(expected);
  assert(otis_regulation_arm(&transaction, &authorization, &eligibility,
                             2400u));
  assert(transaction.state == OtisRegulationState::Armed);

  const auto numerical = decision(transaction.applied_code);
  OtisRegulationActionableRequest request;
  assert(otis_regulation_make_request(&transaction, &numerical, &eligibility,
                                      2400u, &request));
  assert(request.actionable);
  assert(request.requested_code == 0xA950u - 21u);

  OtisRegulationAcceptedRequest accepted;
  assert(otis_regulation_accept(&transaction, &request, 2400u, &accepted));
  assert(!accepted.actionable);
  assert(!transaction.request.actionable);

  const OtisRegulationAppliedAck applied = {
      request.request_sequence, request.authorization_sequence, request.nonce,
      request.requested_code, accepted.accepted_code, request.requested_code,
      1u, 2400u, true, false, false};
  assert(otis_regulation_acknowledge_application(&transaction, &applied));
  assert(transaction.state == OtisRegulationState::AwaitingResponse);
  assert(transaction.applied_code == request.requested_code);
  assert(transaction.correction_count == 1u);
  assert(transaction.cumulative_movement_codes == 21u);
  assert(transaction.dac_epoch == 1u);

  OtisRegulationResponseResult response;
  assert(otis_regulation_record_response(&transaction, 0.0165, true, true,
                                         &response));
  assert(response.classification == OtisRegulationResponseClass::HealthyDetected);
  assert(transaction.state == OtisRegulationState::Disarmed);
}

void metadata_loss_holds_without_actuation() {
  const auto expected = binding();
  const auto eligibility = healthy();
  OtisRegulationTransaction transaction;
  otis_regulation_transaction_init(&transaction, &expected);
  const auto authorization = arm(expected);
  assert(otis_regulation_arm(&transaction, &authorization, &eligibility,
                             2400u));

  assert(otis_regulation_reference_hold(&transaction, "metadata_hold"));
  assert(transaction.state == OtisRegulationState::ReferenceHold);
  assert(!transaction.have_arm);
  assert(transaction.applied_code == expected.start_code);
  assert(transaction.correction_count == 0u);
  assert(transaction.dac_epoch == 0u);

  assert(otis_regulation_reference_requalify(&transaction, 2u));
  assert(transaction.state == OtisRegulationState::Disarmed);
  assert(transaction.expected_binding.session_id == 2u);
  assert(strcmp(transaction.reason,
                "reference_requalified_fresh_authorization_required") == 0);
}

void failed_application_never_retries_or_restores() {
  const auto expected = binding();
  const auto eligibility = healthy();
  OtisRegulationTransaction transaction;
  otis_regulation_transaction_init(&transaction, &expected);
  const auto authorization = arm(expected);
  assert(otis_regulation_arm(&transaction, &authorization, &eligibility,
                             2400u));
  const auto numerical = decision(transaction.applied_code);
  OtisRegulationActionableRequest request;
  assert(otis_regulation_make_request(&transaction, &numerical, &eligibility,
                                      2400u, &request));
  OtisRegulationAcceptedRequest accepted;
  assert(otis_regulation_accept(&transaction, &request, 2400u, &accepted));

  const OtisRegulationAppliedAck failed = {
      request.request_sequence, request.authorization_sequence, request.nonce,
      request.requested_code, accepted.accepted_code, expected.start_code,
      1u, 2400u, false, false, true};
  assert(!otis_regulation_acknowledge_application(&transaction, &failed));
  assert(transaction.state == OtisRegulationState::Fault);
  assert(transaction.applied_code == expected.start_code);
  assert(transaction.correction_count == 0u);
}

void invalid_authority_fails_closed() {
  const auto expected = binding();
  auto eligibility = healthy();
  eligibility.gnss_metadata_valid = false;
  OtisRegulationTransaction transaction;
  otis_regulation_transaction_init(&transaction, &expected);
  const auto authorization = arm(expected);
  assert(!otis_regulation_arm(&transaction, &authorization, &eligibility,
                              2400u));
  assert(transaction.state == OtisRegulationState::Fault);
  assert(transaction.applied_code == expected.start_code);
}

}  // namespace

int main() {
  happy_transaction();
  metadata_loss_holds_without_actuation();
  failed_application_never_retries_or_restores();
  invalid_authority_fails_closed();
  return 0;
}
