#include "otis_q2_transaction_rehearsal.h"

#include <string.h>

#include "otis_cx317_active_transaction.h"
#include "otis_setup_authority.h"

namespace {

constexpr char kConfigurationIdentity[] =
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

OtisSetupAuthorityRequest setup_request() {
  OtisSetupAuthorityRequest value = {};
  value.command_sequence = 9u;
  value.authorization_sequence = 3u;
  value.status_generation = 17u;
  value.query_nonce = 0x12345678u;
  value.expires_s = 1020u;
  value.session_id = 7u;
  value.requested_code = 0xA808u;
  value.one_shot_ordinal = 1u;
  strcpy(value.configuration_identity, kConfigurationIdentity);
  return value;
}

OtisSetupAuthorityContext setup_context() {
  return {
      1000u, 17u, 0x12345678u, 7u, 0xA808u, kConfigurationIdentity,
      true, true, true, true, true, true,
  };
}

OtisSetupExecutionContext execution_context() {
  return {1001u, 0xA808u, kConfigurationIdentity, true, true};
}

OtisSetupApplicationAck setup_ack(
    const OtisSetupAuthorityRequest &request,
    OtisSetupApplicationAck::Kind kind, bool i2c_ok) {
  OtisSetupApplicationAck value = {};
  value.command_sequence = request.command_sequence;
  value.authorization_sequence = request.authorization_sequence;
  value.status_generation = request.status_generation;
  value.query_nonce = request.query_nonce;
  value.session_id = request.session_id;
  value.requested_code = request.requested_code;
  value.applied_code = i2c_ok ? request.requested_code : 0u;
  value.one_shot_ordinal = request.one_shot_ordinal;
  value.kind = kind;
  value.i2c_ok = i2c_ok;
  return value;
}

const char *initial_case_name(uint16_t index) {
  static const char *const names[] = {
      "initial_status_generation_mismatch",
      "initial_query_nonce_mismatch",
      "initial_session_mismatch",
      "initial_expired_authority",
      "initial_requested_code_mismatch",
      "initial_one_shot_ordinal_mismatch",
      "initial_configuration_mismatch",
      "initial_capture_lease_absent",
      "initial_gnss_ineligible",
      "initial_reference_ineligible",
      "initial_partition_unhealthy",
      "initial_active_not_disarmed",
      "initial_setup_already_applied",
  };
  return names[index];
}

void mutate_initial(uint16_t index, OtisSetupAuthorityRequest *request,
                    OtisSetupAuthorityContext *context) {
  switch (index) {
    case 0: request->status_generation++; break;
    case 1: request->query_nonce++; break;
    case 2: request->session_id++; break;
    case 3: request->expires_s = context->now_s; break;
    case 4: request->requested_code++; break;
    case 5: request->one_shot_ordinal++; break;
    case 6: request->configuration_identity[0] = 'f'; break;
    case 7: context->capture_lease_live = false; break;
    case 8: context->gnss_eligible = false; break;
    case 9: context->reference_eligible = false; break;
    case 10: context->partition_healthy = false; break;
    case 11: context->active_disarmed = false; break;
    case 12: context->setup_not_applied = false; break;
  }
}

const char *stale_case_name(uint16_t index) {
  static const char *const names[] = {
      "stale_status_generation",
      "stale_query_nonce",
      "stale_session",
      "stale_expiry",
      "stale_expected_code",
      "stale_configuration",
      "stale_capture_lease",
      "stale_gnss_eligibility",
      "stale_reference_eligibility",
      "stale_partition_health",
      "stale_active_state",
      "stale_setup_applied_state",
  };
  return names[index];
}

void mutate_current(uint16_t index, const OtisSetupAuthorityRequest &request,
                    OtisSetupAuthorityContext *context) {
  switch (index) {
    case 0: context->status_generation++; break;
    case 1: context->query_nonce++; break;
    case 2: context->session_id++; break;
    case 3: context->now_s = request.expires_s; break;
    case 4: context->expected_code++; break;
    case 5: context->configuration_identity = "wrong"; break;
    case 6: context->capture_lease_live = false; break;
    case 7: context->gnss_eligible = false; break;
    case 8: context->reference_eligible = false; break;
    case 9: context->partition_healthy = false; break;
    case 10: context->active_disarmed = false; break;
    case 11: context->setup_not_applied = false; break;
  }
}

const char *execution_case_name(uint16_t index) {
  static const char *const names[] = {
      "execution_expired",
      "execution_expected_code_changed",
      "execution_configuration_changed",
      "execution_partition_unhealthy",
      "execution_actuator_unready",
  };
  return names[index];
}

void mutate_execution(uint16_t index,
                      const OtisSetupAuthorityRequest &request,
                      OtisSetupExecutionContext *context) {
  switch (index) {
    case 0: context->now_s = request.expires_s; break;
    case 1: context->expected_code++; break;
    case 2: context->configuration_identity = "wrong"; break;
    case 3: context->partition_healthy = false; break;
    case 4: context->actuator_ready = false; break;
  }
}

bool advance_setup_to_release(OtisSetupAuthorityGuard *authority_guard,
                              OtisSetupExecutionGuard *execution_guard,
                              const OtisSetupAuthorityRequest &request,
                              const OtisSetupAuthorityContext &authority,
                              const OtisSetupExecutionContext &execution,
                              OtisSetupAuthorization *released,
                              uint16_t *phase_mask) {
  OtisSetupAuthorization authorization = {};
  *phase_mask |= OTIS_Q2_PHASE_RECEIVED;
  if (!otis_setup_authorize(authority_guard, &request, &authority,
                            &authorization))
    return false;
  *phase_mask |= OTIS_Q2_PHASE_AUTHORIZED;
  if (!otis_setup_execution_accept(execution_guard, &authorization,
                                   &execution))
    return false;
  const OtisSetupApplicationAck accepted = setup_ack(
      request, OtisSetupApplicationAck::Kind::Core0Accepted, true);
  if (!otis_setup_authority_acknowledge(authority_guard, &accepted))
    return false;
  *phase_mask |= OTIS_Q2_PHASE_CORE0_ACCEPTED;
  if (!otis_setup_authority_release_execution(authority_guard, &authority,
                                              released))
    return false;
  *phase_mask |= OTIS_Q2_PHASE_RELEASED;
  return true;
}

bool run_initial_rejection(uint16_t index, OtisQ2CaseResult *result) {
  OtisSetupAuthorityGuard guard = {};
  otis_setup_authority_guard_init(&guard);
  OtisSetupAuthorityRequest request = setup_request();
  OtisSetupAuthorityContext context = setup_context();
  mutate_initial(index, &request, &context);
  OtisSetupAuthorization authorization = {};
  result->case_name = initial_case_name(index);
  result->transaction = "setup";
  result->disposition = "rejected_before_authorization";
  result->phase_mask = OTIS_Q2_PHASE_RECEIVED;
  return !otis_setup_authorize(&guard, &request, &context, &authorization) &&
         guard.state == OtisSetupAuthorityState::Idle;
}

bool run_stale_rejection(uint16_t index, OtisQ2CaseResult *result) {
  OtisSetupAuthorityGuard authority_guard = {};
  OtisSetupExecutionGuard execution_guard = {};
  otis_setup_authority_guard_init(&authority_guard);
  otis_setup_execution_guard_init(&execution_guard);
  const OtisSetupAuthorityRequest request = setup_request();
  OtisSetupAuthorityContext current = setup_context();
  const OtisSetupExecutionContext execution = execution_context();
  OtisSetupAuthorization authorization = {};
  result->case_name = stale_case_name(index);
  result->transaction = "setup";
  result->disposition = "rejected_before_release";
  result->phase_mask = OTIS_Q2_PHASE_RECEIVED;
  if (!otis_setup_authorize(&authority_guard, &request, &current,
                            &authorization))
    return false;
  result->phase_mask |= OTIS_Q2_PHASE_AUTHORIZED;
  if (!otis_setup_execution_accept(&execution_guard, &authorization,
                                   &execution))
    return false;
  const OtisSetupApplicationAck accepted = setup_ack(
      request, OtisSetupApplicationAck::Kind::Core0Accepted, true);
  if (!otis_setup_authority_acknowledge(&authority_guard, &accepted))
    return false;
  result->phase_mask |= OTIS_Q2_PHASE_CORE0_ACCEPTED;
  mutate_current(index, request, &current);
  OtisSetupAuthorization released = {};
  const bool rejected = !otis_setup_authority_release_execution(
      &authority_guard, &current, &released);
  result->phase_mask |= OTIS_Q2_PHASE_FAILED;
  OtisSetupAuthorization retry = {};
  result->retry_rejected =
      !otis_setup_authorize(&authority_guard, &request, &current, &retry);
  return rejected && result->retry_rejected &&
         authority_guard.state == OtisSetupAuthorityState::Failed;
}

bool run_execution_rejection(uint16_t index, OtisQ2CaseResult *result) {
  OtisSetupAuthorityGuard authority_guard = {};
  OtisSetupExecutionGuard execution_guard = {};
  otis_setup_authority_guard_init(&authority_guard);
  otis_setup_execution_guard_init(&execution_guard);
  const OtisSetupAuthorityRequest request = setup_request();
  const OtisSetupAuthorityContext authority = setup_context();
  const OtisSetupExecutionContext initial_execution = execution_context();
  OtisSetupAuthorization released = {};
  result->case_name = execution_case_name(index);
  result->transaction = "setup";
  result->disposition = "rejected_before_i2c";
  if (!advance_setup_to_release(&authority_guard, &execution_guard, request,
                                authority, initial_execution, &released,
                                &result->phase_mask))
    return false;
  OtisSetupExecutionContext regressed = initial_execution;
  mutate_execution(index, request, &regressed);
  const bool rejected = !otis_setup_execution_consume(
      &execution_guard, &released, &regressed);
  result->phase_mask |= OTIS_Q2_PHASE_FAILED;
  result->retry_rejected = !otis_setup_execution_consume(
      &execution_guard, &released, &regressed);
  return rejected && result->retry_rejected && !execution_guard.consumed;
}

bool run_interruption(uint16_t phase, OtisQ2CaseResult *result) {
  static const char *const names[] = {
      "interrupt_before_receive",
      "interrupt_after_receive",
      "interrupt_after_authorization",
      "interrupt_after_core0_acceptance",
      "interrupt_after_release",
      "interrupt_after_consumption_before_i2c",
  };
  result->case_name = names[phase];
  result->transaction = "setup";
  result->disposition = "interrupted_fail_static";
  if (phase == 0u) return true;
  result->phase_mask = OTIS_Q2_PHASE_RECEIVED;
  if (phase == 1u) return true;

  OtisSetupAuthorityGuard authority_guard = {};
  OtisSetupExecutionGuard execution_guard = {};
  otis_setup_authority_guard_init(&authority_guard);
  otis_setup_execution_guard_init(&execution_guard);
  const OtisSetupAuthorityRequest request = setup_request();
  const OtisSetupAuthorityContext authority = setup_context();
  const OtisSetupExecutionContext execution = execution_context();
  OtisSetupAuthorization authorization = {};
  if (!otis_setup_authorize(&authority_guard, &request, &authority,
                            &authorization))
    return false;
  result->phase_mask |= OTIS_Q2_PHASE_AUTHORIZED;
  if (phase == 2u) return true;
  if (!otis_setup_execution_accept(&execution_guard, &authorization,
                                   &execution))
    return false;
  const OtisSetupApplicationAck accepted = setup_ack(
      request, OtisSetupApplicationAck::Kind::Core0Accepted, true);
  if (!otis_setup_authority_acknowledge(&authority_guard, &accepted))
    return false;
  result->phase_mask |= OTIS_Q2_PHASE_CORE0_ACCEPTED;
  if (phase == 3u) return true;
  OtisSetupAuthorization released = {};
  if (!otis_setup_authority_release_execution(&authority_guard, &authority,
                                              &released))
    return false;
  result->phase_mask |= OTIS_Q2_PHASE_RELEASED;
  if (phase == 4u) return true;
  if (!otis_setup_execution_consume(&execution_guard, &released, &execution))
    return false;
  result->phase_mask |= OTIS_Q2_PHASE_CONSUMED;
  result->retry_rejected = !otis_setup_execution_consume(
      &execution_guard, &released, &execution);
  return result->retry_rejected;
}

bool run_setup_i2c_failure(OtisQ2CaseResult *result) {
  OtisSetupAuthorityGuard authority_guard = {};
  OtisSetupExecutionGuard execution_guard = {};
  otis_setup_authority_guard_init(&authority_guard);
  otis_setup_execution_guard_init(&execution_guard);
  const OtisSetupAuthorityRequest request = setup_request();
  const OtisSetupAuthorityContext authority = setup_context();
  const OtisSetupExecutionContext execution = execution_context();
  OtisSetupAuthorization released = {};
  result->case_name = "setup_i2c_failure_terminal_then_recovery_ready";
  result->transaction = "setup";
  result->disposition = "failed_once_no_retry_recovery_new_guard";
  if (!advance_setup_to_release(&authority_guard, &execution_guard, request,
                                authority, execution, &released,
                                &result->phase_mask) ||
      !otis_setup_execution_consume(&execution_guard, &released, &execution))
    return false;
  result->phase_mask |= OTIS_Q2_PHASE_CONSUMED;
  result->setup_i2c_attempts = 1u;  // deterministic injected failing attempt
  const OtisSetupApplicationAck failed = setup_ack(
      request, OtisSetupApplicationAck::Kind::Failed, false);
  const bool failed_terminal =
      !otis_setup_authority_acknowledge(&authority_guard, &failed) &&
      authority_guard.state == OtisSetupAuthorityState::Failed;
  result->phase_mask |= OTIS_Q2_PHASE_FAILED;
  result->retry_rejected = !otis_setup_execution_consume(
      &execution_guard, &released, &execution);

  OtisSetupAuthorityGuard recovery_authority = {};
  OtisSetupExecutionGuard recovery_execution = {};
  otis_setup_authority_guard_init(&recovery_authority);
  otis_setup_execution_guard_init(&recovery_execution);
  OtisSetupAuthorization recovery_release = {};
  uint16_t recovery_mask = 0u;
  const bool recovery_ready = advance_setup_to_release(
      &recovery_authority, &recovery_execution, request, authority, execution,
      &recovery_release, &recovery_mask);
  if (recovery_ready) result->phase_mask |= OTIS_Q2_PHASE_RECOVERY_READY;
  return failed_terminal && result->retry_rejected && recovery_ready;
}

OtisCx317ActiveBinding active_binding() {
  return {
      "q2_run", "q2_build", "q2_profile", "estimator", "model",
      "policy", "response", "numerical", 7u, 0xA808u, 0xA808u,
      0xAB00u, 21u, 2u, 42u, false, true, false,
  };
}

OtisCx317ActiveEligibility active_eligibility() {
  return {
      true, true, true, true, true, true, true, true, true, true,
      true, true, true, true, true, true, true, true, true, true,
  };
}

bool run_automatic_ambiguous(OtisQ2CaseResult *result) {
  const OtisCx317ActiveBinding binding = active_binding();
  const OtisCx317ActiveEligibility eligibility = active_eligibility();
  OtisCx317ActiveTransaction transaction = {};
  otis_cx317_active_transaction_init(&transaction, &binding);
  const OtisCx317ArmRequest arm = {binding, 1u, 0xA11CEu, 120u};
  const OtisCx317ActiveDecision decision = {
      1u, 1u, 120u, 100u, 0xA808u, 1, 0xA809u, 0.25,
  };
  OtisCx317ActionableRequest request = {};
  OtisCx317AcceptedRequest accepted = {};
  result->case_name = "automatic_ambiguous_application_terminal_then_recovery_ready";
  result->transaction = "automatic";
  result->disposition = "ambiguous_once_fault_no_retry_recovery_new_transaction";
  result->phase_mask = OTIS_Q2_PHASE_RECEIVED;
  if (!otis_cx317_active_arm(&transaction, &arm, &eligibility, 100u))
    return false;
  result->phase_mask |= OTIS_Q2_PHASE_AUTHORIZED;
  if (!otis_cx317_active_make_request(&transaction, &decision, &eligibility,
                                      100u, &request))
    return false;
  result->phase_mask |= OTIS_Q2_PHASE_RELEASED;
  if (!otis_cx317_active_accept(&transaction, &request, 100u, &accepted))
    return false;
  result->phase_mask |= OTIS_Q2_PHASE_CONSUMED;
  result->automatic_i2c_attempts = 1u;
  const OtisCx317AppliedAck ambiguous = {
      request.request_sequence,
      request.authorization_sequence,
      request.nonce,
      request.requested_code,
      accepted.accepted_code,
      request.requested_code,
      1u,
      100u,
      true,
      false,
      true,
  };
  const bool faulted =
      !otis_cx317_active_acknowledge_application(&transaction, &ambiguous) &&
      transaction.state == OtisCx317ActiveState::Fault;
  result->phase_mask |= OTIS_Q2_PHASE_FAILED;
  result->retry_rejected =
      !otis_cx317_active_acknowledge_application(&transaction, &ambiguous);

  OtisCx317ActiveTransaction recovery = {};
  otis_cx317_active_transaction_init(&recovery, &binding);
  const bool recovery_ready =
      otis_cx317_active_arm(&recovery, &arm, &eligibility, 100u);
  if (recovery_ready) result->phase_mask |= OTIS_Q2_PHASE_RECOVERY_READY;
  return faulted && result->retry_rejected && recovery_ready;
}

}  // namespace

bool otis_q2_transaction_run_case(uint32_t query_nonce, uint16_t case_id,
                                  OtisQ2CaseResult *result) {
  if (result == nullptr || query_nonce == 0u || case_id == 0u ||
      case_id > OTIS_Q2_TRANSACTION_CASE_COUNT)
    return false;
  *result = {};
  result->query_nonce = query_nonce;
  result->case_id = case_id;
  bool passed = false;
  if (case_id <= 13u) {
    passed = run_initial_rejection(case_id - 1u, result);
  } else if (case_id <= 25u) {
    passed = run_stale_rejection(case_id - 14u, result);
  } else if (case_id <= 30u) {
    passed = run_execution_rejection(case_id - 26u, result);
  } else if (case_id <= 36u) {
    passed = run_interruption(case_id - 31u, result);
  } else if (case_id == 37u) {
    passed = run_setup_i2c_failure(result);
  } else {
    passed = run_automatic_ambiguous(result);
  }
  result->passed = passed && result->setup_i2c_attempts <= 1u &&
                   result->automatic_i2c_attempts <= 1u;
  return result->passed;
}
