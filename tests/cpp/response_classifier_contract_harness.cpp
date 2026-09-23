#include <stdint.h>

#include <cassert>
#include <cstring>
#include <iostream>

#include "otis_regulation_transaction.h"

int main() {
  OtisRegulationResponseClassifier classifier{};
  double pre_error_hz = 0.0;
  double post_error_hz = 0.0;
  int32_t delta_codes = 0;
  while (std::cin >> pre_error_hz >> post_error_hz >> delta_codes) {
    const OtisRegulationResponseResult response =
        otis_regulation_classify_response(&classifier, pre_error_hz,
                                          post_error_hz, delta_codes,
                                          true, true);
    std::cout << otis_regulation_response_class_name(response.classification)
              << ',' << response.reason << '\n';
  }
  OtisRegulationResponseClassifier strict{};
  OtisRegulationResponseResult response{};
  for (int i = 0; i < 3; ++i)
    response = otis_regulation_classify_response(
        &strict, -0.01, -0.009, 20, true, false);
  assert(response.classification ==
         OtisRegulationResponseClass::MeasurementOrActuatorFault);
  assert(std::strcmp(response.reason,
                     "persistent_response_absence_after_cumulative_expected_detection") == 0);
  assert(std::strcmp(otis_regulation_response_class_name(
                         OtisRegulationResponseClass::InsideDeadband),
                     "inside_deadband") == 0);
  assert(std::strcmp(otis_regulation_response_class_name(
                         OtisRegulationResponseClass::LimitReached),
                     "limit_reached") == 0);
}
