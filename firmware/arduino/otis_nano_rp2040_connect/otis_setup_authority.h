#ifndef OTIS_SETUP_AUTHORITY_H
#define OTIS_SETUP_AUTHORITY_H

#include <stdint.h>

constexpr uint32_t OTIS_SETUP_AUTHORIZATION_MAXIMUM_AGE_S = 30u;
constexpr uint16_t OTIS_CONFIGURATION_IDENTITY_CAPACITY = 65u;

struct OtisSetupAuthorityRequest {
  uint32_t command_sequence;
  uint32_t authorization_sequence;
  uint32_t status_generation;
  uint32_t query_nonce;
  uint32_t expires_s;
  uint32_t session_id;
  uint16_t requested_code;
  uint16_t one_shot_ordinal;
  char configuration_identity[OTIS_CONFIGURATION_IDENTITY_CAPACITY];
};

struct OtisSetupAuthorityContext {
  uint32_t now_s;
  uint32_t status_generation;
  uint32_t query_nonce;
  uint32_t session_id;
  uint16_t expected_code;
  const char *configuration_identity;
  bool capture_lease_live;
  bool gnss_eligible;
  bool reference_eligible;
  bool partition_healthy;
  bool active_disarmed;
  bool setup_not_applied;
};

struct OtisSetupAuthorization {
  OtisSetupAuthorityRequest request;
  uint32_t authorized_s;
};

enum class OtisSetupAuthorityState : uint8_t {
  Idle,
  AuthorizedAwaitingCore0,
  Core0Accepted,
  ExecutionReleased,
  Applied,
  Failed,
};

struct OtisSetupAuthorityGuard {
  OtisSetupAuthorityState state;
  uint32_t last_authorization_sequence;
  OtisSetupAuthorization pending;
  const char *reason;
};

struct OtisSetupApplicationAck {
  uint32_t command_sequence;
  uint32_t authorization_sequence;
  uint32_t status_generation;
  uint32_t query_nonce;
  uint32_t session_id;
  uint16_t requested_code;
  uint16_t applied_code;
  uint16_t one_shot_ordinal;
  enum class Kind : uint8_t {
    Core0Accepted,
    Core0Rejected,
    Applied,
    Failed,
  } kind;
  bool i2c_ok;
};

struct OtisSetupExecutionContext {
  uint32_t now_s;
  uint16_t expected_code;
  const char *configuration_identity;
  bool partition_healthy;
  bool actuator_ready;
};

struct OtisSetupExecutionGuard {
  bool accepted;
  bool consumed;
  uint32_t last_authorization_sequence;
  OtisSetupAuthorization pending;
  const char *reason;
};

bool otis_setup_authority_parse_request(
    const char *text, OtisSetupAuthorityRequest *request);
void otis_setup_authority_guard_init(OtisSetupAuthorityGuard *guard);
bool otis_setup_authorize(OtisSetupAuthorityGuard *guard,
                          const OtisSetupAuthorityRequest *request,
                          const OtisSetupAuthorityContext *context,
                          OtisSetupAuthorization *authorization);
bool otis_setup_authority_acknowledge(
    OtisSetupAuthorityGuard *guard,
    const OtisSetupApplicationAck *acknowledgement);
bool otis_setup_authority_release_execution(
    OtisSetupAuthorityGuard *guard,
    const OtisSetupAuthorityContext *current_context,
    OtisSetupAuthorization *authorization);

void otis_setup_execution_guard_init(OtisSetupExecutionGuard *guard);
bool otis_setup_execution_accept(
    OtisSetupExecutionGuard *guard,
    const OtisSetupAuthorization *authorization,
    const OtisSetupExecutionContext *context);
bool otis_setup_execution_consume(OtisSetupExecutionGuard *guard,
                                  const OtisSetupAuthorization *authorization,
                                  const OtisSetupExecutionContext *context);

#endif
