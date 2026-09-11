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
                             uint32_t sequence = 1u,
                             uint32_t expires_s = 2460u) {
  return {value, sequence, 0xABC00000u + sequence, expires_s};
}

OtisRegulationDecision decision(uint32_t sequence, uint32_t acceptance_epoch,
                                uint32_t opening_accepted_boundary,
                                uint32_t closing_accepted_boundary,
                                uint32_t timestamp_s, uint16_t current) {
  OtisRegulationDecision result = {};
  result.decision_sequence = sequence;
  result.source_acceptance_epoch = acceptance_epoch;
  result.source_opening_accepted_boundary_ordinal = opening_accepted_boundary;
  result.source_closing_accepted_boundary_ordinal = closing_accepted_boundary;
  result.timestamp_s = timestamp_s;
  result.current_applied_code = current;
  result.requested_delta_codes = -21;
  result.requested_code = static_cast<uint16_t>(current - 21u);
  result.pre_error_hz = 0.020;
  return result;
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

  const auto numerical = decision(1u, 3u, 1001u, 1601u, 2400u,
                                  transaction.applied_code);
  OtisRegulationActionableRequest request;
  assert(otis_regulation_make_request(&transaction, &numerical, &eligibility,
                                      2400u, &request));
  assert(request.actionable);
  assert(request.requested_code == 0xA950u - 21u);
  assert(request.source_acceptance_epoch == 3u);
  assert(request.source_opening_accepted_boundary_ordinal == 1001u);
  assert(request.source_closing_accepted_boundary_ordinal == 1601u);

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

  // A later request/response must retain a distinct accepted-reference
  // identity.  The source tuple is part of the request identity, rather than
  // incidental metadata associated with a completed transaction.
  const auto second_authorization = arm(expected, 2u, 4260u);
  assert(otis_regulation_arm(&transaction, &second_authorization, &eligibility,
                             4200u));
  const auto second = decision(2u, 4u, 1601u, 2201u, 4200u,
                               transaction.applied_code);
  OtisRegulationActionableRequest second_request;
  assert(otis_regulation_make_request(&transaction, &second, &eligibility,
                                      4200u, &second_request));
  assert(second_request.source_acceptance_epoch == 4u);
  assert(second_request.source_opening_accepted_boundary_ordinal == 1601u);
  assert(second_request.source_closing_accepted_boundary_ordinal == 2201u);
  OtisRegulationAcceptedRequest second_accepted;
  assert(otis_regulation_accept(&transaction, &second_request, 4200u,
                                &second_accepted));
  const OtisRegulationAppliedAck second_applied = {
      second_request.request_sequence, second_request.authorization_sequence,
      second_request.nonce, second_request.requested_code,
      second_accepted.accepted_code, second_request.requested_code, 2u, 4200u,
      true, false, false};
  assert(otis_regulation_acknowledge_application(&transaction, &second_applied));
  assert(transaction.request.source_acceptance_epoch == 4u);
  assert(transaction.request.source_opening_accepted_boundary_ordinal == 1601u);
  assert(transaction.request.source_closing_accepted_boundary_ordinal == 2201u);
  assert(otis_regulation_record_response(&transaction, 0.0165, true, true,
                                         &response));
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
  const auto numerical = decision(1u, 3u, 1001u, 1601u, 2400u,
                                  transaction.applied_code);
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

void altered_accepted_source_is_not_the_same_request() {
  const auto expected = binding();
  const auto eligibility = healthy();
  OtisRegulationTransaction transaction;
  otis_regulation_transaction_init(&transaction, &expected);
  const auto authorization = arm(expected);
  assert(otis_regulation_arm(&transaction, &authorization, &eligibility, 2400u));
  const auto numerical = decision(1u, 3u, 1001u, 1601u, 2400u,
                                  transaction.applied_code);
  OtisRegulationActionableRequest request;
  assert(otis_regulation_make_request(&transaction, &numerical, &eligibility,
                                      2400u, &request));
  OtisRegulationActionableRequest altered = request;
  altered.source_closing_accepted_boundary_ordinal++;
  OtisRegulationAcceptedRequest accepted;
  assert(!otis_regulation_accept(&transaction, &altered, 2400u, &accepted));
  assert(transaction.state == OtisRegulationState::Fault);
  assert(strcmp(transaction.reason, "accepted_request_identity_mismatch") == 0);
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
  altered_accepted_source_is_not_the_same_request();
  invalid_authority_fails_closed();
  return 0;
}
