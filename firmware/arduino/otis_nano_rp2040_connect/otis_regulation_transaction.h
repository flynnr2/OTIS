#ifndef OTIS_REGULATION_TRANSACTION_H
#define OTIS_REGULATION_TRANSACTION_H

#include <stdint.h>

// Numerical plant-response classification is independent of instrument mode,
// command authorization, and actuator transaction ownership.
enum class OtisRegulationResponseClass : uint8_t {
  HealthyDetected,
  HealthyIndeterminateNearResolution,
  InsideDeadband,
  LimitReached,
  WrongSign,
  ExcessResponse,
  GrowingError,
  MeasurementOrActuatorFault,
};

struct OtisRegulationResponseResult {
  OtisRegulationResponseClass classification;
  const char *reason;
  double observed_response_hz;
  double cumulative_response_hz;
  uint8_t consecutive_indeterminate;
};

struct OtisRegulationResponseClassifier {
  bool have_baseline;
  double baseline_error_hz;
  int32_t cumulative_delta_codes;
  uint8_t consecutive_indeterminate;
};

OtisRegulationResponseResult otis_regulation_classify_response(
    OtisRegulationResponseClassifier *, double pre_error_hz, double post_error_hz,
    int32_t applied_delta_codes, bool evidence_healthy, bool observational);
const char *otis_regulation_response_class_name(OtisRegulationResponseClass value);

#endif
