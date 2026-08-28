#ifndef OTIS_CX317_ACTIVE_TRANSACTION_H
#define OTIS_CX317_ACTIVE_TRANSACTION_H

#include <stdint.h>

enum class OtisCx317ActiveState : uint8_t {
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

enum class OtisCx317ResponseClass : uint8_t {
  HealthyDetected,
  HealthyIndeterminateNearResolution,
  InsideDeadband,
  LimitReached,
  WrongSign,
  ExcessResponse,
  GrowingError,
  MeasurementOrActuatorFault,
};

struct OtisCx317ActiveBinding {
  const char *run_identity;
  const char *build_identity;
  const char *profile_identity;
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
  // Historical campaigns classify the V2 float deadband in the response
  // transaction.  CX318 Stage 5 disables that classification because V2 is
  // a zero-authority shadow and tight integer-count residence is owned by the
  // separate Stage 5 state machine.
  bool legacy_response_deadband_enabled;
  // CX322 retains every valid response classification as an observation.
  // Scientific class/sign/magnitude do not become transaction failures;
  // malformed measurement or actuator evidence still fails closed.
  bool response_classification_observational;
};

struct OtisCx317ActiveEligibility {
  bool run_identity_matches;
  bool build_identity_matches;
  bool profile_identity_matches;
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

struct OtisCx317ArmRequest {
  OtisCx317ActiveBinding binding;
  uint32_t authorization_sequence;
  uint32_t nonce;
  uint32_t expires_s;
};

struct OtisCx317ActiveDecision {
  uint32_t decision_sequence;
  uint32_t source_first_sequence;
  uint32_t source_last_sequence;
  uint32_t timestamp_s;
  uint16_t current_applied_code;
  int32_t requested_delta_codes;
  uint16_t requested_code;
  double pre_error_hz;
};

struct OtisCx317ActionableRequest {
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

struct OtisCx317AcceptedRequest {
  uint32_t request_sequence;
  uint32_t authorization_sequence;
  uint32_t nonce;
  uint16_t accepted_code;
  uint32_t accepted_timestamp_s;
  bool actionable;
};

struct OtisCx317AppliedAck {
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

struct OtisCx317ResponseResult {
  OtisCx317ResponseClass classification;
  const char *reason;
  double observed_response_hz;
  double cumulative_response_hz;
  uint8_t consecutive_indeterminate;
};

struct OtisCx317ResponseClassifier {
  bool have_baseline;
  double baseline_error_hz;
  int32_t cumulative_delta_codes;
  uint8_t consecutive_indeterminate;
};

struct OtisCx317ActiveTransaction {
  OtisCx317ActiveState state;
  OtisCx317ActiveState reference_hold_resume_state;
  const char *reason;
  OtisCx317ActiveBinding expected_binding;
  OtisCx317ArmRequest arm;
  OtisCx317ActionableRequest request;
  OtisCx317AcceptedRequest accepted;
  OtisCx317AppliedAck applied;
  OtisCx317ResponseClassifier response_classifier;
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
struct OtisCx317Core0RejectedOutcome {
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

void otis_cx317_active_transaction_init(
    OtisCx317ActiveTransaction *transaction,
    const OtisCx317ActiveBinding *binding);
bool otis_cx317_active_eligibility_valid(
    const OtisCx317ActiveEligibility *eligibility);
bool otis_cx317_active_arm_eligibility_valid(
    const OtisCx317ActiveEligibility *eligibility);
bool otis_cx317_active_response_measurement_valid(
    const OtisCx317ActiveEligibility *eligibility);
bool otis_cx317_active_arm(OtisCx317ActiveTransaction *transaction,
                          const OtisCx317ArmRequest *arm,
                          const OtisCx317ActiveEligibility *eligibility,
                          uint32_t now_s);
bool otis_cx317_active_make_request(
    OtisCx317ActiveTransaction *transaction,
    const OtisCx317ActiveDecision *decision,
    const OtisCx317ActiveEligibility *eligibility, uint32_t now_s,
    OtisCx317ActionableRequest *request);
bool otis_cx317_active_accept(OtisCx317ActiveTransaction *transaction,
                             const OtisCx317ActionableRequest *request,
                             uint32_t now_s,
                             OtisCx317AcceptedRequest *accepted);
bool otis_cx317_active_acknowledge_application(
    OtisCx317ActiveTransaction *transaction,
    const OtisCx317AppliedAck *acknowledgement);
bool otis_cx317_active_discard_released_request_on_metadata_rejection(
    OtisCx317ActiveTransaction *transaction,
    OtisCx317ActionableRequest *pending_request,
    bool *pending_request_valid,
    bool metadata_hold_active,
    bool *metadata_hold_transaction_pending,
    bool request_durably_released,
    uint16_t confirmed_applied_code,
    uint32_t confirmed_dac_epoch,
    const OtisCx317Core0RejectedOutcome *outcome);
// CX321 charges its identification application to the global transaction
// budgets, then starts the natural-controller reversal history empty.
bool otis_cx317_active_rebase_natural_history_after_identification(
    OtisCx317ActiveTransaction *transaction, uint16_t expected_applied_code,
    uint32_t expected_dac_epoch);
bool otis_cx317_active_complete_identification_response(
    OtisCx317ActiveTransaction *transaction, uint16_t expected_applied_code,
    uint32_t expected_dac_epoch);
bool otis_cx317_active_record_response(
    OtisCx317ActiveTransaction *transaction, double post_error_hz,
    bool measurement_healthy, bool control_eligible_after_response,
    OtisCx317ResponseResult *result);
void otis_cx317_active_fault(OtisCx317ActiveTransaction *transaction,
                             const char *reason);
bool otis_cx317_active_reference_hold(
    OtisCx317ActiveTransaction *transaction, const char *reason);
bool otis_cx317_active_reference_requalify(
    OtisCx317ActiveTransaction *transaction, uint32_t session_id);
void otis_cx317_active_abort(OtisCx317ActiveTransaction *transaction,
                             const char *reason);
void otis_cx317_active_note_session(OtisCx317ActiveTransaction *transaction,
                                    uint32_t session_id,
                                    bool actuator_context_established);
const char *otis_cx317_active_state_name(OtisCx317ActiveState state);
const char *otis_cx317_response_class_name(OtisCx317ResponseClass value);

#endif
