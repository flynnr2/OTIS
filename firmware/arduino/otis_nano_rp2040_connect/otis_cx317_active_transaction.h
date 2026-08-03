#ifndef OTIS_CX317_ACTIVE_TRANSACTION_H
#define OTIS_CX317_ACTIVE_TRANSACTION_H

#include <stdint.h>

enum class OtisCx317ActiveState : uint8_t {
  Disarmed,
  Armed,
  RequestPending,
  AcceptedAwaitingApplication,
  AwaitingResponse,
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
};

void otis_cx317_active_transaction_init(
    OtisCx317ActiveTransaction *transaction,
    const OtisCx317ActiveBinding *binding);
bool otis_cx317_active_eligibility_valid(
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
bool otis_cx317_active_record_response(
    OtisCx317ActiveTransaction *transaction, double post_error_hz,
    bool evidence_healthy, OtisCx317ResponseResult *result);
void otis_cx317_active_fault(OtisCx317ActiveTransaction *transaction,
                             const char *reason);
void otis_cx317_active_abort(OtisCx317ActiveTransaction *transaction,
                             const char *reason);
void otis_cx317_active_note_session(OtisCx317ActiveTransaction *transaction,
                                    uint32_t session_id);
const char *otis_cx317_active_state_name(OtisCx317ActiveState state);
const char *otis_cx317_response_class_name(OtisCx317ResponseClass value);

#endif
