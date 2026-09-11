#include <stdint.h>

#include <iostream>

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

const char *classification_name(OtisRegulationResponseClass value) {
  switch (value) {
    case OtisRegulationResponseClass::HealthyDetected:
      return "healthy_detected";
    case OtisRegulationResponseClass::HealthyIndeterminateNearResolution:
      return "healthy_indeterminate_near_resolution";
    case OtisRegulationResponseClass::InsideDeadband:
      return "inside_deadband";
    case OtisRegulationResponseClass::LimitReached:
      return "limit_reached";
    case OtisRegulationResponseClass::WrongSign:
      return "wrong_sign";
    case OtisRegulationResponseClass::ExcessResponse:
      return "excess_response";
    case OtisRegulationResponseClass::GrowingError:
      return "growing_error";
    case OtisRegulationResponseClass::MeasurementOrActuatorFault:
      return "measurement_or_actuator_fault";
  }
  return "unknown";
}

}  // namespace

int main() {
  const auto expected = binding();
  const auto eligibility = healthy();
  OtisRegulationTransaction transaction;
  otis_regulation_transaction_init(&transaction, &expected);

  double pre_error_hz = 0.0;
  double post_error_hz = 0.0;
  int32_t delta_codes = 0;
  uint32_t sequence = 0u;
  while (std::cin >> pre_error_hz >> post_error_hz >> delta_codes) {
    sequence++;
    const uint32_t now_s = 2000u * sequence;
    const OtisRegulationArmRequest authorization = {
        expected, sequence, 0xABC00000u + sequence, now_s + 60u};
    if (!otis_regulation_arm(&transaction, &authorization, &eligibility,
                             now_s))
      return 2;

    const int32_t requested_code =
        static_cast<int32_t>(transaction.applied_code) + delta_codes;
    if (requested_code < 0 || requested_code > UINT16_MAX) return 3;
    OtisRegulationDecision decision = {};
    decision.decision_sequence = sequence;
    decision.source_acceptance_epoch = sequence;
    decision.source_opening_accepted_boundary_ordinal = sequence * 1000u;
    decision.source_closing_accepted_boundary_ordinal =
        sequence * 1000u + 600u;
    decision.timestamp_s = now_s;
    decision.current_applied_code = transaction.applied_code;
    decision.requested_delta_codes = delta_codes;
    decision.requested_code = static_cast<uint16_t>(requested_code);
    decision.pre_error_hz = pre_error_hz;
    OtisRegulationActionableRequest request;
    if (!otis_regulation_make_request(&transaction, &decision, &eligibility,
                                      now_s, &request))
      return 4;
    OtisRegulationAcceptedRequest accepted;
    if (!otis_regulation_accept(&transaction, &request, now_s, &accepted))
      return 5;
    const OtisRegulationAppliedAck applied = {
        request.request_sequence,
        request.authorization_sequence,
        request.nonce,
        request.requested_code,
        accepted.accepted_code,
        request.requested_code,
        static_cast<uint16_t>(sequence),
        now_s,
        true,
        false,
        false,
    };
    if (!otis_regulation_acknowledge_application(&transaction, &applied))
      return 6;
    OtisRegulationResponseResult response;
    if (!otis_regulation_record_response(&transaction, post_error_hz, true,
                                         true, &response))
      return 7;
    std::cout << classification_name(response.classification) << ','
              << response.reason << '\n';
  }
  return 0;
}
