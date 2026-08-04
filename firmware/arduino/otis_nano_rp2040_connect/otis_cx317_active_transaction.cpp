#include "otis_cx317_active_transaction.h"

#include <math.h>
#include <string.h>

namespace {

constexpr uint32_t kMaximumArmLifetimeS = 120u;
constexpr uint32_t kMinimumCadenceS = 1800u;
constexpr double kGainMinimumHzPerCode = 0.00016357422282453626;
constexpr double kGainMaximumHzPerCode = 0.00017334010044578463;
constexpr double kDetectionFloorHz = 0.0033333317438761396;
constexpr double kDeadbandHz = 0.006249995628992717;
constexpr double kWrongSignMinimumHz = 0.0033333317438761396;
constexpr double kGrowthMarginHz = 0.006249995628992717;
constexpr double kExcessMarginHz = 0.006249995628992717;
constexpr uint8_t kMaximumConsecutiveIndeterminate = 2u;

bool binding_equal(const OtisCx317ActiveBinding &left,
                   const OtisCx317ActiveBinding &right) {
  return left.run_identity != nullptr && right.run_identity != nullptr &&
         left.build_identity != nullptr && right.build_identity != nullptr &&
         left.profile_identity != nullptr && right.profile_identity != nullptr &&
         left.estimator_sha256 != nullptr && right.estimator_sha256 != nullptr &&
         left.model_sha256 != nullptr && right.model_sha256 != nullptr &&
         left.policy_sha256 != nullptr && right.policy_sha256 != nullptr &&
         left.response_sha256 != nullptr && right.response_sha256 != nullptr &&
         left.numerical_policy_sha256 != nullptr &&
         right.numerical_policy_sha256 != nullptr &&
         strcmp(left.run_identity, right.run_identity) == 0 &&
         strcmp(left.build_identity, right.build_identity) == 0 &&
         strcmp(left.profile_identity, right.profile_identity) == 0 &&
         strcmp(left.estimator_sha256, right.estimator_sha256) == 0 &&
         strcmp(left.model_sha256, right.model_sha256) == 0 &&
         strcmp(left.policy_sha256, right.policy_sha256) == 0 &&
         strcmp(left.response_sha256, right.response_sha256) == 0 &&
         strcmp(left.numerical_policy_sha256,
                right.numerical_policy_sha256) == 0 &&
         left.session_id == right.session_id &&
         left.start_code == right.start_code &&
         left.minimum_code == right.minimum_code &&
         left.maximum_code == right.maximum_code &&
         left.maximum_step_codes == right.maximum_step_codes &&
         left.correction_limit == right.correction_limit &&
         left.cumulative_limit_codes == right.cumulative_limit_codes &&
         left.prospective_dither_stop_enabled ==
             right.prospective_dither_stop_enabled;
}

bool request_equal(const OtisCx317ActionableRequest &left,
                   const OtisCx317ActionableRequest &right) {
  return left.request_sequence == right.request_sequence &&
         left.authorization_sequence == right.authorization_sequence &&
         left.nonce == right.nonce && left.session_id == right.session_id &&
         left.decision_sequence == right.decision_sequence &&
         left.source_first_sequence == right.source_first_sequence &&
         left.source_last_sequence == right.source_last_sequence &&
         left.timestamp_s == right.timestamp_s &&
         left.current_applied_code == right.current_applied_code &&
         left.requested_delta_codes == right.requested_delta_codes &&
         left.requested_code == right.requested_code &&
         left.pre_error_hz == right.pre_error_hz &&
         left.correction_ordinal == right.correction_ordinal &&
         left.cumulative_after_codes == right.cumulative_after_codes &&
         left.actionable == right.actionable;
}

void disarm(OtisCx317ActiveTransaction *transaction, const char *reason) {
  transaction->state = OtisCx317ActiveState::Disarmed;
  transaction->reason = reason;
  transaction->have_arm = false;
}

OtisCx317ResponseResult classify_response(
    OtisCx317ResponseClassifier *classifier, double pre_error_hz,
    double post_error_hz, int32_t applied_delta_codes, uint16_t current_code,
    uint16_t minimum_code, uint16_t maximum_code, bool evidence_healthy) {
  OtisCx317ResponseResult result = {
      OtisCx317ResponseClass::MeasurementOrActuatorFault,
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
  classifier->cumulative_delta_codes += applied_delta_codes;
  const double observed = post_error_hz - pre_error_hz;
  const double cumulative = post_error_hz - classifier->baseline_error_hz;
  result.observed_response_hz = observed;
  result.cumulative_response_hz = cumulative;

  if (fabs(post_error_hz) <= kDeadbandHz) {
    classifier->consecutive_indeterminate = 0u;
    result.classification = OtisCx317ResponseClass::InsideDeadband;
    result.reason = "post_error_inside_frozen_deadband";
  } else if ((current_code <= minimum_code && post_error_hz > kDeadbandHz) ||
             (current_code >= maximum_code && post_error_hz < -kDeadbandHz)) {
    classifier->consecutive_indeterminate = 0u;
    result.classification = OtisCx317ResponseClass::LimitReached;
    result.reason = "hard_code_endpoint_blocks_required_direction";
  } else if ((observed * applied_delta_codes < 0.0 &&
              fabs(observed) >= kWrongSignMinimumHz) ||
             (cumulative * classifier->cumulative_delta_codes < 0.0 &&
              fabs(cumulative) >= kWrongSignMinimumHz)) {
    classifier->consecutive_indeterminate = 0u;
    result.classification = OtisCx317ResponseClass::WrongSign;
    result.reason = "observed_response_opposes_positive_plant_gain";
  } else if (fabs(post_error_hz) > fabs(pre_error_hz) + kGrowthMarginHz) {
    classifier->consecutive_indeterminate = 0u;
    result.classification = OtisCx317ResponseClass::GrowingError;
    result.reason = "absolute_error_grew_beyond_frozen_margin";
  } else if (fabs(observed) >
             fabs(static_cast<double>(applied_delta_codes)) *
                     kGainMaximumHzPerCode +
                 kExcessMarginHz) {
    classifier->consecutive_indeterminate = 0u;
    result.classification = OtisCx317ResponseClass::ExcessResponse;
    result.reason = "response_exceeds_gain_envelope_plus_empirical_margin";
  } else if ((observed * applied_delta_codes > 0.0 &&
              fabs(observed) >= kDetectionFloorHz) ||
             (cumulative * classifier->cumulative_delta_codes > 0.0 &&
              fabs(cumulative) >= kDetectionFloorHz)) {
    classifier->consecutive_indeterminate = 0u;
    result.classification = OtisCx317ResponseClass::HealthyDetected;
    result.reason = "response_detected_with_commanded_sign";
  } else {
    if (classifier->consecutive_indeterminate < UINT8_MAX)
      classifier->consecutive_indeterminate++;
    const double expected =
        fabs(static_cast<double>(classifier->cumulative_delta_codes)) *
        kGainMinimumHzPerCode;
    if (classifier->consecutive_indeterminate >
            kMaximumConsecutiveIndeterminate &&
        expected >= 2.0 * kDetectionFloorHz) {
      result.classification =
          OtisCx317ResponseClass::MeasurementOrActuatorFault;
      result.reason =
          "persistent_response_absence_after_cumulative_expected_detection";
    } else {
      result.classification =
          OtisCx317ResponseClass::HealthyIndeterminateNearResolution;
      result.reason = "healthy_evidence_below_empirical_detection_floor";
    }
  }
  result.consecutive_indeterminate = classifier->consecutive_indeterminate;
  return result;
}

}  // namespace

void otis_cx317_active_transaction_init(
    OtisCx317ActiveTransaction *transaction,
    const OtisCx317ActiveBinding *binding) {
  if (transaction == nullptr || binding == nullptr) return;
  *transaction = {};
  transaction->state = OtisCx317ActiveState::Disarmed;
  transaction->reason = "initialized_disarmed";
  transaction->expected_binding = *binding;
  transaction->applied_code = binding->start_code;
}

bool otis_cx317_active_eligibility_valid(
    const OtisCx317ActiveEligibility *value) {
  return value != nullptr && value->run_identity_matches &&
         value->build_identity_matches && value->profile_identity_matches &&
         value->estimator_identity_matches && value->model_identity_matches &&
         value->policy_identity_matches && value->response_identity_matches &&
         value->session_continuous && value->gnss_metadata_valid &&
         value->gnss_identity_stable && value->gnss_3d_evidence &&
         value->raw_pps_valid && value->count_valid &&
         value->estimator_valid && value->model_applicable &&
         value->applied_code_confirmed &&
         value->capture_owner_live && value->abort_path_live &&
         value->transaction_evidence_available;
}

bool otis_cx317_active_arm_eligibility_valid(
    const OtisCx317ActiveEligibility *value) {
  return value != nullptr && value->run_identity_matches &&
         value->build_identity_matches && value->profile_identity_matches &&
         value->estimator_identity_matches && value->model_identity_matches &&
         value->policy_identity_matches && value->response_identity_matches &&
         value->session_continuous && value->gnss_metadata_valid &&
         value->gnss_identity_stable && value->gnss_3d_evidence &&
         value->raw_pps_valid && value->count_valid &&
         value->applied_code_confirmed &&
         value->capture_owner_live && value->abort_path_live &&
         value->transaction_evidence_available;
}

bool otis_cx317_active_response_measurement_valid(
    const OtisCx317ActiveEligibility *value) {
  return value != nullptr && value->run_identity_matches &&
         value->build_identity_matches && value->profile_identity_matches &&
         value->estimator_identity_matches && value->model_identity_matches &&
         value->policy_identity_matches && value->response_identity_matches &&
         value->session_continuous && value->gnss_metadata_valid &&
         value->gnss_identity_stable && value->gnss_3d_evidence &&
         value->raw_pps_valid && value->count_valid && value->estimator_valid &&
         value->applied_code_confirmed && value->capture_owner_live &&
         value->abort_path_live && value->transaction_evidence_available;
}

void otis_cx317_active_fault(OtisCx317ActiveTransaction *transaction,
                             const char *reason) {
  if (transaction == nullptr) return;
  transaction->state = OtisCx317ActiveState::Fault;
  transaction->reason = reason == nullptr ? "unspecified_fault" : reason;
  transaction->have_arm = false;
  if (transaction->have_request) transaction->request.actionable = false;
}

void otis_cx317_active_abort(OtisCx317ActiveTransaction *transaction,
                             const char *reason) {
  if (transaction == nullptr) return;
  transaction->state = OtisCx317ActiveState::Aborted;
  transaction->reason = reason == nullptr ? "operator_abort" : reason;
  transaction->have_arm = false;
  transaction->have_request = false;
  transaction->have_acceptance = false;
}

bool otis_cx317_active_arm(OtisCx317ActiveTransaction *transaction,
                          const OtisCx317ArmRequest *arm,
                          const OtisCx317ActiveEligibility *eligibility,
                          uint32_t now_s) {
  if (transaction == nullptr || arm == nullptr) return false;
  if (transaction->state == OtisCx317ActiveState::Fault ||
      transaction->state == OtisCx317ActiveState::Aborted)
    return false;
  if (transaction->state == OtisCx317ActiveState::OutOfModelHold) {
    if (!otis_cx317_active_eligibility_valid(eligibility)) return false;
    disarm(transaction, "out_of_model_hold_requalified");
  }
  if (transaction->state != OtisCx317ActiveState::Disarmed ||
      transaction->have_request) {
    otis_cx317_active_fault(transaction, "arm_while_not_disarmed");
    return false;
  }
  if (!otis_cx317_active_arm_eligibility_valid(eligibility)) {
    otis_cx317_active_fault(transaction, "arm_eligibility_failed");
    return false;
  }
  if (!binding_equal(arm->binding, transaction->expected_binding)) {
    otis_cx317_active_fault(transaction, "arm_binding_mismatch");
    return false;
  }
  if (arm->authorization_sequence <= transaction->last_authorization_sequence ||
      arm->nonce == 0u) {
    otis_cx317_active_fault(transaction,
                           "stale_duplicate_or_zero_authorization");
    return false;
  }
  if (arm->expires_s <= now_s ||
      arm->expires_s - now_s > kMaximumArmLifetimeS) {
    otis_cx317_active_fault(transaction,
                           "arming_expiry_outside_short_lived_bound");
    return false;
  }
  if (transaction->correction_count >=
      transaction->expected_binding.correction_limit) {
    otis_cx317_active_fault(transaction, "correction_count_limit_reached");
    return false;
  }
  transaction->arm = *arm;
  transaction->have_arm = true;
  transaction->state = OtisCx317ActiveState::Armed;
  transaction->reason = "exact_binding_armed";
  return true;
}

bool otis_cx317_active_make_request(
    OtisCx317ActiveTransaction *transaction,
    const OtisCx317ActiveDecision *decision,
    const OtisCx317ActiveEligibility *eligibility, uint32_t now_s,
    OtisCx317ActionableRequest *request) {
  if (transaction == nullptr || decision == nullptr || request == nullptr)
    return false;
  if (transaction->state != OtisCx317ActiveState::Armed ||
      !transaction->have_arm) {
    otis_cx317_active_fault(transaction, "request_without_current_arm");
    return false;
  }
  const OtisCx317ArmRequest arm = transaction->arm;
  transaction->have_arm = false;
  if (!otis_cx317_active_eligibility_valid(eligibility)) {
    otis_cx317_active_fault(transaction, "request_eligibility_failed");
    return false;
  }
  if (now_s > arm.expires_s || decision->timestamp_s != now_s) {
    otis_cx317_active_fault(transaction,
                           "authorization_or_decision_timestamp_invalid");
    return false;
  }
  if (decision->decision_sequence <= transaction->last_decision_sequence ||
      decision->source_first_sequence == 0u ||
      decision->source_last_sequence < decision->source_first_sequence) {
    otis_cx317_active_fault(transaction,
                           "duplicate_stale_or_invalid_decision_sources");
    return false;
  }
  if (decision->current_applied_code != transaction->applied_code) {
    otis_cx317_active_fault(transaction, "decision_applied_code_mismatch");
    return false;
  }
  const int32_t delta = decision->requested_delta_codes;
  if (delta == 0) {
    disarm(transaction, "zero_delta_disarmed_without_request");
    return false;
  }
  if (delta > transaction->expected_binding.maximum_step_codes ||
      delta < -static_cast<int32_t>(
                  transaction->expected_binding.maximum_step_codes)) {
    otis_cx317_active_fault(transaction, "step_limit_exceeded");
    return false;
  }
  const int32_t expected_code =
      static_cast<int32_t>(transaction->applied_code) + delta;
  if (expected_code != decision->requested_code) {
    otis_cx317_active_fault(transaction, "requested_code_delta_mismatch");
    return false;
  }
  if (decision->requested_code < transaction->expected_binding.minimum_code ||
      decision->requested_code > transaction->expected_binding.maximum_code) {
    otis_cx317_active_fault(transaction, "requested_code_outside_hard_range");
    return false;
  }
  if (transaction->correction_count + 1u >
      transaction->expected_binding.correction_limit) {
    otis_cx317_active_fault(transaction, "correction_count_limit_exceeded");
    return false;
  }
  const uint32_t movement = delta < 0 ? static_cast<uint32_t>(-delta)
                                      : static_cast<uint32_t>(delta);
  const uint32_t cumulative = transaction->cumulative_movement_codes + movement;
  if (cumulative > transaction->expected_binding.cumulative_limit_codes) {
    otis_cx317_active_fault(transaction,
                           "cumulative_movement_limit_exceeded");
    return false;
  }
  if (transaction->expected_binding.prospective_dither_stop_enabled) {
    const int8_t proposed_direction = delta > 0 ? 1 : -1;
    if (transaction->recent_applied_direction_count >= 3u &&
        transaction->recent_applied_directions[0] !=
            transaction->recent_applied_directions[1] &&
        transaction->recent_applied_directions[1] !=
            transaction->recent_applied_directions[2] &&
        transaction->recent_applied_directions[2] != proposed_direction) {
      otis_cx317_active_fault(
          transaction, "prospective_third_consecutive_reversal_dither_stop");
      return false;
    }
    const int32_t prospective_net =
        static_cast<int32_t>(decision->requested_code) -
        static_cast<int32_t>(transaction->expected_binding.start_code);
    const uint32_t absolute_net =
        prospective_net < 0 ? static_cast<uint32_t>(-prospective_net)
                            : static_cast<uint32_t>(prospective_net);
    if (cumulative >= 168u && absolute_net * 4u <= cumulative) {
      otis_cx317_active_fault(
          transaction, "prospective_low_net_excess_path_dither_stop");
      return false;
    }
  }
  if (transaction->have_last_application &&
      now_s - transaction->last_application_s < kMinimumCadenceS) {
    otis_cx317_active_fault(transaction,
                           "minimum_applied_correction_cadence_violated");
    return false;
  }
  transaction->last_request_sequence++;
  *request = {
      transaction->last_request_sequence,
      arm.authorization_sequence,
      arm.nonce,
      transaction->expected_binding.session_id,
      decision->decision_sequence,
      decision->source_first_sequence,
      decision->source_last_sequence,
      now_s,
      transaction->applied_code,
      delta,
      decision->requested_code,
      decision->pre_error_hz,
      static_cast<uint16_t>(transaction->correction_count + 1u),
      static_cast<uint16_t>(cumulative),
      true,
  };
  transaction->request = *request;
  transaction->last_decision_sequence = decision->decision_sequence;
  transaction->last_authorization_sequence = arm.authorization_sequence;
  transaction->have_request = true;
  transaction->state = OtisCx317ActiveState::RequestPending;
  transaction->reason = "one_actionable_request_created";
  return true;
}

bool otis_cx317_active_accept(OtisCx317ActiveTransaction *transaction,
                             const OtisCx317ActionableRequest *request,
                             uint32_t now_s,
                             OtisCx317AcceptedRequest *accepted) {
  if (transaction == nullptr || request == nullptr || accepted == nullptr)
    return false;
  if (transaction->state != OtisCx317ActiveState::RequestPending ||
      !transaction->have_request || !request->actionable ||
      !request_equal(*request, transaction->request)) {
    otis_cx317_active_fault(transaction,
                           "accepted_request_identity_mismatch");
    return false;
  }
  *accepted = {request->request_sequence,
               request->authorization_sequence,
               request->nonce,
               request->requested_code,
               now_s,
               false};
  transaction->request.actionable = false;
  transaction->accepted = *accepted;
  transaction->applied = {};
  transaction->have_acceptance = true;
  transaction->have_application = false;
  transaction->state = OtisCx317ActiveState::AcceptedAwaitingApplication;
  transaction->reason = "request_consumed_actionable_cleared";
  return true;
}

bool otis_cx317_active_acknowledge_application(
    OtisCx317ActiveTransaction *transaction,
    const OtisCx317AppliedAck *ack) {
  if (transaction == nullptr || ack == nullptr) return false;
  if (transaction->state !=
          OtisCx317ActiveState::AcceptedAwaitingApplication ||
      !transaction->have_request || !transaction->have_acceptance) {
    otis_cx317_active_fault(transaction,
                           "application_ack_without_acceptance");
    return false;
  }
  const bool identity =
      ack->request_sequence == transaction->request.request_sequence &&
      ack->authorization_sequence ==
          transaction->request.authorization_sequence &&
      ack->nonce == transaction->request.nonce &&
      ack->requested_code == transaction->request.requested_code &&
      ack->accepted_code == transaction->accepted.accepted_code;
  const bool outcome =
      ack->i2c_ok && !ack->clamped && !ack->ambiguous &&
      ack->applied_code == transaction->request.requested_code &&
      ack->application_sequence == transaction->correction_count + 1u;
  transaction->applied = *ack;
  transaction->have_application = true;
  if (!identity || !outcome) {
    otis_cx317_active_fault(
        transaction, "application_acknowledgement_mismatch_or_failure");
    return false;
  }
  transaction->applied_code = ack->applied_code;
  transaction->correction_count++;
  transaction->cumulative_movement_codes =
      transaction->request.cumulative_after_codes;
  transaction->last_application_s = ack->application_timestamp_s;
  transaction->have_last_application = true;
  transaction->dac_epoch++;
  const int8_t applied_direction =
      transaction->request.requested_delta_codes > 0 ? 1 : -1;
  if (transaction->recent_applied_direction_count < 3u) {
    transaction->recent_applied_directions[
        transaction->recent_applied_direction_count++] = applied_direction;
  } else {
    transaction->recent_applied_directions[0] =
        transaction->recent_applied_directions[1];
    transaction->recent_applied_directions[1] =
        transaction->recent_applied_directions[2];
    transaction->recent_applied_directions[2] = applied_direction;
  }
  transaction->state = OtisCx317ActiveState::AwaitingResponse;
  transaction->reason = "applied_history_reset_response_required";
  return true;
}

bool otis_cx317_active_record_response(
    OtisCx317ActiveTransaction *transaction, double post_error_hz,
    bool measurement_healthy, bool control_eligible_after_response,
    OtisCx317ResponseResult *result) {
  if (transaction == nullptr || result == nullptr) return false;
  if (transaction->state != OtisCx317ActiveState::AwaitingResponse ||
      !transaction->have_application) {
    otis_cx317_active_fault(transaction,
                           "response_without_applied_transaction");
    return false;
  }
  *result = classify_response(
      &transaction->response_classifier, transaction->request.pre_error_hz,
      post_error_hz, transaction->request.requested_delta_codes,
      transaction->applied_code, transaction->expected_binding.minimum_code,
      transaction->expected_binding.maximum_code, measurement_healthy);
  transaction->have_request = false;
  transaction->have_acceptance = false;
  transaction->have_application = false;
  switch (result->classification) {
    case OtisCx317ResponseClass::WrongSign:
    case OtisCx317ResponseClass::ExcessResponse:
    case OtisCx317ResponseClass::GrowingError:
    case OtisCx317ResponseClass::MeasurementOrActuatorFault:
      otis_cx317_active_fault(transaction, result->reason);
      return false;
    default:
      if (!control_eligible_after_response) {
        transaction->state = OtisCx317ActiveState::OutOfModelHold;
        transaction->reason = "response_valid_out_of_model_hold";
        transaction->have_arm = false;
        return true;
      }
      disarm(transaction, "response_accepted_new_arm_required");
      return true;
  }
}

void otis_cx317_active_note_session(OtisCx317ActiveTransaction *transaction,
                                    uint32_t session_id) {
  if (transaction != nullptr &&
      session_id != transaction->expected_binding.session_id)
    otis_cx317_active_fault(transaction, "session_change_clears_arming");
}

const char *otis_cx317_active_state_name(OtisCx317ActiveState state) {
  switch (state) {
    case OtisCx317ActiveState::Disarmed:
      return "DISARMED";
    case OtisCx317ActiveState::Armed:
      return "ARMED";
    case OtisCx317ActiveState::RequestPending:
      return "REQUEST_PENDING";
    case OtisCx317ActiveState::AcceptedAwaitingApplication:
      return "ACCEPTED_AWAITING_APPLICATION";
    case OtisCx317ActiveState::AwaitingResponse:
      return "AWAITING_RESPONSE";
    case OtisCx317ActiveState::OutOfModelHold:
      return "OUT_OF_MODEL_HOLD";
    case OtisCx317ActiveState::Fault:
      return "FAULT";
    case OtisCx317ActiveState::Aborted:
      return "ABORTED";
  }
  return "FAULT";
}

const char *otis_cx317_response_class_name(OtisCx317ResponseClass value) {
  switch (value) {
    case OtisCx317ResponseClass::HealthyDetected:
      return "healthy_detected";
    case OtisCx317ResponseClass::HealthyIndeterminateNearResolution:
      return "healthy_indeterminate_near_resolution";
    case OtisCx317ResponseClass::InsideDeadband:
      return "inside_deadband";
    case OtisCx317ResponseClass::LimitReached:
      return "limit_reached";
    case OtisCx317ResponseClass::WrongSign:
      return "wrong_sign";
    case OtisCx317ResponseClass::ExcessResponse:
      return "excess_response";
    case OtisCx317ResponseClass::GrowingError:
      return "growing_error";
    case OtisCx317ResponseClass::MeasurementOrActuatorFault:
      return "measurement_or_actuator_fault";
  }
  return "measurement_or_actuator_fault";
}
