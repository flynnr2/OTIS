#include "otis_regulation_transaction.h"

#include <math.h>

namespace {

constexpr double kGainMinimumHzPerCode = 0.00016357422282453626;
constexpr double kGainMaximumHzPerCode = 0.00017334010044578463;
constexpr double kDetectionFloorHz = 0.0033333317438761396;
constexpr double kWrongSignMinimumHz = 0.0033333317438761396;
constexpr double kGrowthMarginHz = 0.006249995628992717;
constexpr double kExcessMarginHz = 0.006249995628992717;
constexpr uint8_t kMaximumConsecutiveIndeterminate = 2u;

OtisRegulationResponseResult classify_response(
    OtisRegulationResponseClassifier *classifier, double pre_error_hz,
    double post_error_hz, int32_t applied_delta_codes, bool evidence_healthy,
    bool response_classification_observational) {
  OtisRegulationResponseResult result = {
      OtisRegulationResponseClass::MeasurementOrActuatorFault,
      "invalid_response_evidence", 0.0, 0.0,
      classifier->consecutive_indeterminate};
  if (!evidence_healthy || applied_delta_codes == 0 ||
      !isfinite(pre_error_hz) || !isfinite(post_error_hz)) {
    classifier->consecutive_indeterminate = 0u;
    result.consecutive_indeterminate = 0u;
    return result;
  }
  if (!classifier->have_baseline) {
    classifier->have_baseline = true;
    classifier->baseline_error_hz = pre_error_hz;
  }
  const int64_t cumulative_delta = static_cast<int64_t>(classifier->cumulative_delta_codes) + applied_delta_codes;
  if (cumulative_delta < INT32_MIN || cumulative_delta > INT32_MAX) {
    result.reason = "response_accumulator_exhausted";
    return result;
  }
  classifier->cumulative_delta_codes = static_cast<int32_t>(cumulative_delta);
  const double observed = post_error_hz - pre_error_hz;
  const double cumulative = post_error_hz - classifier->baseline_error_hz;
  result.observed_response_hz = observed;
  result.cumulative_response_hz = cumulative;

  if ((observed * applied_delta_codes < 0.0 &&
              fabs(observed) >= kWrongSignMinimumHz) ||
             (cumulative * classifier->cumulative_delta_codes < 0.0 &&
              fabs(cumulative) >= kWrongSignMinimumHz)) {
    classifier->consecutive_indeterminate = 0u;
    result.classification = OtisRegulationResponseClass::WrongSign;
    result.reason = "observed_response_opposes_positive_plant_gain";
  } else if (fabs(post_error_hz) > fabs(pre_error_hz) + kGrowthMarginHz) {
    classifier->consecutive_indeterminate = 0u;
    result.classification = OtisRegulationResponseClass::GrowingError;
    result.reason = "absolute_error_grew_beyond_frozen_margin";
  } else if (fabs(observed) >
             fabs(static_cast<double>(applied_delta_codes)) *
                     kGainMaximumHzPerCode +
                 kExcessMarginHz) {
    classifier->consecutive_indeterminate = 0u;
    result.classification = OtisRegulationResponseClass::ExcessResponse;
    result.reason = "response_exceeds_gain_envelope_plus_empirical_margin";
  } else if ((observed * applied_delta_codes > 0.0 &&
              fabs(observed) >= kDetectionFloorHz) ||
             (cumulative * classifier->cumulative_delta_codes > 0.0 &&
              fabs(cumulative) >= kDetectionFloorHz)) {
    classifier->consecutive_indeterminate = 0u;
    result.classification = OtisRegulationResponseClass::HealthyDetected;
    result.reason = "response_detected_with_commanded_sign";
  } else {
    if (classifier->consecutive_indeterminate < UINT8_MAX)
      classifier->consecutive_indeterminate++;
    const double expected =
        fabs(static_cast<double>(classifier->cumulative_delta_codes)) *
        kGainMinimumHzPerCode;
    if (!response_classification_observational &&
        classifier->consecutive_indeterminate >
            kMaximumConsecutiveIndeterminate &&
        expected >= 2.0 * kDetectionFloorHz) {
      result.classification =
          OtisRegulationResponseClass::MeasurementOrActuatorFault;
      result.reason =
          "persistent_response_absence_after_cumulative_expected_detection";
    } else {
      result.classification =
          OtisRegulationResponseClass::HealthyIndeterminateNearResolution;
      result.reason = "healthy_evidence_below_empirical_detection_floor";
    }
  }
  result.consecutive_indeterminate = classifier->consecutive_indeterminate;
  return result;
}

}  // namespace

OtisRegulationResponseResult otis_regulation_classify_response(
    OtisRegulationResponseClassifier *classifier, double pre_error_hz,
    double post_error_hz, int32_t applied_delta_codes, bool evidence_healthy,
    bool observational) {
  return classify_response(classifier, pre_error_hz, post_error_hz,
                           applied_delta_codes, evidence_healthy, observational);
}

const char *otis_regulation_response_class_name(OtisRegulationResponseClass value) {
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
  return "measurement_or_actuator_fault";
}
