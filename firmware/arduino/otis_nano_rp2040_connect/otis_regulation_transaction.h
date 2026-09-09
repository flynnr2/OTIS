#ifndef OTIS_REGULATION_TRANSACTION_H
#define OTIS_REGULATION_TRANSACTION_H

#include <stdint.h>

enum class OtisRegulationState : uint8_t {
  Disarmed,
  Armed,
  RequestPending,
  AcceptedAwaitingApplication,
  AwaitingResponse,
  ReferenceHold,
  OutOfModelHold,
  Fault,
  Aborted,
};

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

struct OtisRegulationBinding {
  const char *run_identity;
  const char *build_identity;
  const char *image_identity;
  const char *estimator_sha256;
  const char *model_sha256;
  const char *policy_sha256;
  const char *response_sha256;
  const char *numerical_policy_sha256;
  uint32_t session_id;
  uint16_t start_code;
  uint16_t minimum_code;
  uint16_t maximum_code;
  uint16_t maximum_step_codes;
  uint16_t correction_limit;
  uint16_t cumulative_limit_codes;
  bool prospective_dither_stop_enabled;
  // Valid scientific response classes are observations. Malformed measurement
  // or actuator evidence still fails closed.
  bool response_classification_observational;
};

struct OtisRegulationEligibility {
  bool run_identity_matches;
  bool build_identity_matches;
  bool image_identity_matches;
  bool estimator_identity_matches;
  bool model_identity_matches;
  bool policy_identity_matches;
  bool response_identity_matches;
  bool session_continuous;
  bool gnss_metadata_valid;
  bool gnss_identity_stable;
  bool gnss_3d_evidence;
  bool raw_pps_valid;
  bool count_valid;
  bool estimator_valid;
  bool model_applicable;
  bool temperature_valid;
  bool applied_code_confirmed;
  bool capture_owner_live;
  bool abort_path_live;
  bool transaction_evidence_available;
};

struct OtisRegulationArmRequest {
  OtisRegulationBinding binding;
  uint32_t authorization_sequence;
  uint32_t nonce;
  uint32_t expires_s;
};

struct OtisRegulationDecision {
  uint32_t decision_sequence;
  uint32_t source_first_sequence;
  uint32_t source_last_sequence;
  uint32_t timestamp_s;
  uint16_t current_applied_code;
  int32_t requested_delta_codes;
  uint16_t requested_code;
  double pre_error_hz;
};

struct OtisRegulationActionableRequest {
  uint32_t request_sequence;
  uint32_t authorization_sequence;
  uint32_t nonce;
  uint32_t session_id;
  uint32_t decision_sequence;
  uint32_t source_first_sequence;
  uint32_t source_last_sequence;
  uint32_t timestamp_s;
  uint16_t current_applied_code;
  int32_t requested_delta_codes;
  uint16_t requested_code;
  double pre_error_hz;
  uint16_t correction_ordinal;
  uint16_t cumulative_after_codes;
  bool actionable;
};

struct OtisRegulationAcceptedRequest {
  uint32_t request_sequence;
  uint32_t authorization_sequence;
  uint32_t nonce;
  uint16_t accepted_code;
  uint32_t accepted_timestamp_s;
  bool actionable;
};

struct OtisRegulationAppliedAck {
  uint32_t request_sequence;
  uint32_t authorization_sequence;
  uint32_t nonce;
  uint16_t requested_code;
  uint16_t accepted_code;
  uint16_t applied_code;
  uint16_t application_sequence;
  uint32_t application_timestamp_s;
  bool i2c_ok;
  bool clamped;
  bool ambiguous;
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

struct OtisRegulationTransaction {
  OtisRegulationState state;
  OtisRegulationState reference_hold_resume_state;
  const char *reason;
  OtisRegulationBinding expected_binding;
  OtisRegulationArmRequest arm;
  OtisRegulationActionableRequest request;
  OtisRegulationAcceptedRequest accepted;
  OtisRegulationAppliedAck applied;
  OtisRegulationResponseClassifier response_classifier;
  uint16_t applied_code;
  uint16_t correction_count;
  uint16_t cumulative_movement_codes;
  uint16_t dac_epoch;
  uint32_t last_application_s;
  uint32_t last_decision_sequence;
  uint32_t last_request_sequence;
  uint32_t last_authorization_sequence;
  bool have_last_application;
  bool have_arm;
  bool have_request;
  bool have_acceptance;
  bool have_application;
  int8_t recent_applied_directions[3];
  uint8_t recent_applied_direction_count;
};

// Core 1 may consume this outcome without fault only for the narrow case in
// which GNSS metadata became unqualified after the durable request was
// released but before Core 0 accepted it.  The value deliberately repeats the
// full request identity and the unchanged physical DAC state.
struct OtisRegulationCore0RejectedOutcome {
  uint32_t request_sequence;
  uint32_t decision_sequence;
  uint32_t authorization_sequence;
  uint32_t nonce;
  uint16_t requested_code;
  uint16_t accepted_code;
  uint16_t applied_code;
  bool rejected;
  bool metadata_hold_cancelled_before_acceptance;
  bool i2c_ok;
  bool clamped;
  bool ambiguous;
};

void otis_regulation_transaction_init(
    OtisRegulationTransaction *transaction,
    const OtisRegulationBinding *binding);
bool otis_regulation_eligibility_valid(
    const OtisRegulationEligibility *eligibility);
bool otis_regulation_arm_eligibility_valid(
    const OtisRegulationEligibility *eligibility);
bool otis_regulation_response_measurement_valid(
    const OtisRegulationEligibility *eligibility);
bool otis_regulation_arm(OtisRegulationTransaction *transaction,
                          const OtisRegulationArmRequest *arm,
                          const OtisRegulationEligibility *eligibility,
                          uint32_t now_s);
bool otis_regulation_make_request(
    OtisRegulationTransaction *transaction,
    const OtisRegulationDecision *decision,
    const OtisRegulationEligibility *eligibility, uint32_t now_s,
    OtisRegulationActionableRequest *request);
bool otis_regulation_accept(OtisRegulationTransaction *transaction,
                             const OtisRegulationActionableRequest *request,
                             uint32_t now_s,
                             OtisRegulationAcceptedRequest *accepted);
bool otis_regulation_acknowledge_application(
    OtisRegulationTransaction *transaction,
    const OtisRegulationAppliedAck *acknowledgement);
bool otis_regulation_discard_released_request_on_metadata_rejection(
    OtisRegulationTransaction *transaction,
    OtisRegulationActionableRequest *pending_request,
    bool *pending_request_valid,
    bool metadata_hold_active,
    bool *metadata_hold_transaction_pending,
    bool request_durably_released,
    uint16_t confirmed_applied_code,
    uint32_t confirmed_dac_epoch,
    const OtisRegulationCore0RejectedOutcome *outcome);
bool otis_regulation_record_response(
    OtisRegulationTransaction *transaction, double post_error_hz,
    bool measurement_healthy, bool control_eligible_after_response,
    OtisRegulationResponseResult *result);
void otis_regulation_fault(OtisRegulationTransaction *transaction,
                             const char *reason);
bool otis_regulation_reference_hold(
    OtisRegulationTransaction *transaction, const char *reason);
bool otis_regulation_reference_requalify(
    OtisRegulationTransaction *transaction, uint32_t session_id);
void otis_regulation_abort(OtisRegulationTransaction *transaction,
                             const char *reason);
void otis_regulation_note_session(OtisRegulationTransaction *transaction,
                                    uint32_t session_id,
                                    bool actuator_context_established);
const char *otis_regulation_state_name(OtisRegulationState state);
const char *otis_regulation_response_class_name(OtisRegulationResponseClass value);

#endif
