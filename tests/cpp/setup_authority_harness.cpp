#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "otis_setup_authority.h"

namespace {

constexpr char kConfig[] =
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

OtisSetupAuthorityRequest request() {
  OtisSetupAuthorityRequest value = {};
  value.command_sequence = 9u;
  value.authorization_sequence = 3u;
  value.status_generation = 17u;
  value.query_nonce = 0x12345678u;
  value.expires_s = 1020u;
  value.session_id = 7u;
  value.requested_code = 0xA808u;
  value.one_shot_ordinal = 1u;
  strcpy(value.configuration_identity, kConfig);
  return value;
}

OtisSetupAuthorityContext context() {
  return {
      1000u, 17u, 0x12345678u, 7u, 0xA808u, kConfig,
      true, true, true, true, true, true,
  };
}

void parser_rejects_noncanonical_or_out_of_range_wire_values() {
  char valid[256] = {};
  snprintf(valid, sizeof(valid), "3 17 0x12345678 1020 7 0xA808 1 %s",
           kConfig);
  OtisSetupAuthorityRequest parsed = {};
  assert(otis_setup_authority_parse_request(valid, &parsed));
  assert(parsed.authorization_sequence == 3u);
  assert(parsed.query_nonce == 0x12345678u);
  assert(parsed.requested_code == 0xA808u);
  assert(parsed.one_shot_ordinal == 1u);
  assert(strcmp(parsed.configuration_identity, kConfig) == 0);

  const char *invalid[] = {
      "4294967296 17 1 1020 7 43016 1 "
      "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "-3 17 1 1020 7 43016 1 "
      "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "+3 17 1 1020 7 43016 1 "
      "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "3 17 1 1020 7 65536 1 "
      "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "3 17 1 1020 7 43016 65536 "
      "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "0 17 1 1020 7 43016 1 "
      "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "3 17 1 1020 7 43016 1 "
      "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcde",
      "3 17 1 1020 7 43016 1 "
      "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef extra",
      "3 17 1 1020 7 43016 1 "
      "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdeg",
  };
  for (const char *candidate : invalid) {
    parsed = {};
    assert(!otis_setup_authority_parse_request(candidate, &parsed));
  }
}

void every_authority_regression_rejects_before_execution() {
  for (uint32_t case_id = 0u; case_id < 13u; ++case_id) {
    OtisSetupAuthorityGuard guard = {};
    otis_setup_authority_guard_init(&guard);
    OtisSetupAuthorityRequest candidate = request();
    OtisSetupAuthorityContext current = context();
    switch (case_id) {
      case 0: candidate.status_generation++; break;
      case 1: candidate.query_nonce++; break;
      case 2: candidate.session_id++; break;
      case 3: candidate.expires_s = current.now_s; break;
      case 4: candidate.requested_code++; break;
      case 5: candidate.one_shot_ordinal++; break;
      case 6: candidate.configuration_identity[0] = 'f'; break;
      case 7: current.capture_lease_live = false; break;
      case 8: current.gnss_eligible = false; break;
      case 9: current.reference_eligible = false; break;
      case 10: current.partition_healthy = false; break;
      case 11: current.active_disarmed = false; break;
      case 12: current.setup_not_applied = false; break;
    }
    OtisSetupAuthorization authorization = {};
    assert(!otis_setup_authorize(&guard, &candidate, &current,
                                 &authorization));
    assert(guard.state == OtisSetupAuthorityState::Idle);
  }
}

void accepted_authority_is_exact_and_i2c_is_one_shot() {
  OtisSetupAuthorityGuard authority_guard = {};
  otis_setup_authority_guard_init(&authority_guard);
  const OtisSetupAuthorityRequest candidate = request();
  const OtisSetupAuthorityContext current = context();
  OtisSetupAuthorization authorization = {};
  assert(otis_setup_authorize(&authority_guard, &candidate, &current,
                              &authorization));

  OtisSetupExecutionGuard execution_guard = {};
  otis_setup_execution_guard_init(&execution_guard);
  const OtisSetupExecutionContext execution = {
      1001u, 0xA808u, kConfig, true, true,
  };
  assert(otis_setup_execution_accept(&execution_guard, &authorization,
                                     &execution));
  OtisSetupApplicationAck accepted = {};
  accepted.command_sequence = candidate.command_sequence;
  accepted.authorization_sequence = candidate.authorization_sequence;
  accepted.status_generation = candidate.status_generation;
  accepted.query_nonce = candidate.query_nonce;
  accepted.session_id = candidate.session_id;
  accepted.requested_code = candidate.requested_code;
  accepted.one_shot_ordinal = candidate.one_shot_ordinal;
  accepted.kind = OtisSetupApplicationAck::Kind::Core0Accepted;
  accepted.i2c_ok = true;
  assert(otis_setup_authority_acknowledge(&authority_guard, &accepted));
  OtisSetupAuthorization released = {};
  assert(otis_setup_authority_release_execution(
      &authority_guard, &current, &released));
  assert(otis_setup_execution_consume(&execution_guard, &authorization,
                                      &execution));
  assert(execution_guard.consumed);
  assert(!otis_setup_execution_consume(&execution_guard, &authorization,
                                       &execution));

  OtisSetupApplicationAck ack = {};
  ack.command_sequence = candidate.command_sequence;
  ack.authorization_sequence = candidate.authorization_sequence;
  ack.status_generation = candidate.status_generation;
  ack.query_nonce = candidate.query_nonce;
  ack.session_id = candidate.session_id;
  ack.requested_code = candidate.requested_code;
  ack.applied_code = candidate.requested_code;
  ack.one_shot_ordinal = candidate.one_shot_ordinal;
  ack.kind = OtisSetupApplicationAck::Kind::Applied;
  ack.i2c_ok = true;
  assert(otis_setup_authority_acknowledge(&authority_guard, &ack));
  assert(authority_guard.state == OtisSetupAuthorityState::Applied);
}

void later_observation_generation_preserves_exact_current_authority() {
  OtisSetupAuthorityGuard authority_guard = {};
  otis_setup_authority_guard_init(&authority_guard);
  const OtisSetupAuthorityRequest candidate = request();
  OtisSetupAuthorityContext current = context();
  current.status_generation = candidate.status_generation + 1u;
  OtisSetupAuthorization authorization = {};
  assert(otis_setup_authorize(&authority_guard, &candidate, &current,
                              &authorization));
  assert(authorization.request.status_generation ==
         candidate.status_generation);

  OtisSetupApplicationAck accepted = {};
  accepted.command_sequence = candidate.command_sequence;
  accepted.authorization_sequence = candidate.authorization_sequence;
  accepted.status_generation = candidate.status_generation;
  accepted.query_nonce = candidate.query_nonce;
  accepted.session_id = candidate.session_id;
  accepted.requested_code = candidate.requested_code;
  accepted.one_shot_ordinal = candidate.one_shot_ordinal;
  accepted.kind = OtisSetupApplicationAck::Kind::Core0Accepted;
  accepted.i2c_ok = true;
  assert(otis_setup_authority_acknowledge(&authority_guard, &accepted));

  current.status_generation++;
  OtisSetupAuthorization released = {};
  assert(otis_setup_authority_release_execution(
      &authority_guard, &current, &released));
  assert(released.request.status_generation == candidate.status_generation);

  OtisSetupAuthorityGuard future_guard = {};
  otis_setup_authority_guard_init(&future_guard);
  OtisSetupAuthorityContext behind = context();
  behind.status_generation = candidate.status_generation - 1u;
  OtisSetupAuthorization rejected = {};
  assert(!otis_setup_authorize(&future_guard, &candidate, &behind,
                               &rejected));

  OtisSetupAuthorityRequest rollover = candidate;
  rollover.status_generation = UINT32_MAX;
  OtisSetupAuthorityContext after_rollover = context();
  after_rollover.status_generation = 1u;
  OtisSetupAuthorityGuard rollover_guard = {};
  otis_setup_authority_guard_init(&rollover_guard);
  assert(otis_setup_authorize(&rollover_guard, &rollover,
                              &after_rollover, &authorization));
  assert(authorization.request.status_generation == UINT32_MAX);
}

void execution_rechecks_expiry_partition_config_and_actuator() {
  const OtisSetupAuthorityRequest candidate = request();
  const OtisSetupAuthorityContext current = context();
  for (uint32_t case_id = 0u; case_id < 4u; ++case_id) {
    OtisSetupAuthorityGuard authority_guard = {};
    otis_setup_authority_guard_init(&authority_guard);
    OtisSetupAuthorization authorization = {};
    assert(otis_setup_authorize(&authority_guard, &candidate, &current,
                                &authorization));
    OtisSetupExecutionGuard execution_guard = {};
    otis_setup_execution_guard_init(&execution_guard);
    OtisSetupExecutionContext execution = {
        1001u, 0xA808u, kConfig, true, true,
    };
    if (case_id == 0u) execution.now_s = candidate.expires_s;
    if (case_id == 1u) execution.partition_healthy = false;
    if (case_id == 2u) execution.configuration_identity = "wrong";
    if (case_id == 3u) execution.actuator_ready = false;
    if (case_id == 0u) {
      const OtisSetupExecutionContext initially_valid = {
          1001u, 0xA808u, kConfig, true, true,
      };
      assert(otis_setup_execution_accept(&execution_guard, &authorization,
                                         &initially_valid));
      assert(!otis_setup_execution_consume(&execution_guard, &authorization,
                                           &execution));
    } else {
      assert(!otis_setup_execution_accept(&execution_guard, &authorization,
                                          &execution));
    }
    assert(!execution_guard.consumed);
    const uint32_t i2c_call_count = execution_guard.consumed ? 1u : 0u;
    assert(i2c_call_count == 0u);
  }
}

void interruption_at_each_transaction_phase_is_safe_and_one_shot() {
  // Stop after each successive phase. No phase before execution consumption
  // may call I2C; loss after consumption cannot make the authorization
  // consumable a second time.
  for (uint32_t stop_after_phase = 0u; stop_after_phase <= 5u;
       ++stop_after_phase) {
    uint32_t i2c_call_count = 0u;
    OtisSetupAuthorityGuard authority_guard = {};
    OtisSetupExecutionGuard execution_guard = {};
    otis_setup_authority_guard_init(&authority_guard);
    otis_setup_execution_guard_init(&execution_guard);
    const OtisSetupAuthorityRequest candidate = request();
    const OtisSetupAuthorityContext current = context();
    const OtisSetupExecutionContext execution = {
        1001u, 0xA808u, kConfig, true, true,
    };
    OtisSetupAuthorization authorization = {};
    if (stop_after_phase == 0u) {
      assert(i2c_call_count == 0u);
      continue;
    }
    assert(otis_setup_authorize(&authority_guard, &candidate, &current,
                                &authorization));
    if (stop_after_phase == 1u) {
      assert(i2c_call_count == 0u);
      continue;
    }
    assert(otis_setup_execution_accept(&execution_guard, &authorization,
                                       &execution));
    if (stop_after_phase == 2u) {
      assert(i2c_call_count == 0u);
      continue;
    }
    OtisSetupApplicationAck accepted = {};
    accepted.command_sequence = candidate.command_sequence;
    accepted.authorization_sequence = candidate.authorization_sequence;
    accepted.status_generation = candidate.status_generation;
    accepted.query_nonce = candidate.query_nonce;
    accepted.session_id = candidate.session_id;
    accepted.requested_code = candidate.requested_code;
    accepted.one_shot_ordinal = candidate.one_shot_ordinal;
    accepted.kind = OtisSetupApplicationAck::Kind::Core0Accepted;
    accepted.i2c_ok = true;
    assert(otis_setup_authority_acknowledge(&authority_guard, &accepted));
    if (stop_after_phase == 3u) {
      assert(i2c_call_count == 0u);
      continue;
    }
    OtisSetupAuthorization released = {};
    assert(otis_setup_authority_release_execution(
        &authority_guard, &current, &released));
    if (stop_after_phase == 4u) {
      assert(i2c_call_count == 0u);
      continue;
    }
    if (otis_setup_execution_consume(&execution_guard, &released,
                                     &execution))
      ++i2c_call_count;
    assert(i2c_call_count == 1u);
    assert(!otis_setup_execution_consume(&execution_guard, &released,
                                         &execution));
    assert(i2c_call_count == 1u);
  }
}

void failed_i2c_ack_is_terminal_and_not_retryable() {
  OtisSetupAuthorityGuard guard = {};
  otis_setup_authority_guard_init(&guard);
  const OtisSetupAuthorityRequest candidate = request();
  const OtisSetupAuthorityContext current = context();
  OtisSetupAuthorization authorization = {};
  assert(otis_setup_authorize(&guard, &candidate, &current, &authorization));
  OtisSetupExecutionGuard execution_guard = {};
  otis_setup_execution_guard_init(&execution_guard);
  const OtisSetupExecutionContext execution = {
      1001u, 0xA808u, kConfig, true, true,
  };
  assert(otis_setup_execution_accept(&execution_guard, &authorization,
                                     &execution));
  OtisSetupApplicationAck accepted = {};
  accepted.command_sequence = candidate.command_sequence;
  accepted.authorization_sequence = candidate.authorization_sequence;
  accepted.status_generation = candidate.status_generation;
  accepted.query_nonce = candidate.query_nonce;
  accepted.session_id = candidate.session_id;
  accepted.requested_code = candidate.requested_code;
  accepted.one_shot_ordinal = 1u;
  accepted.kind = OtisSetupApplicationAck::Kind::Core0Accepted;
  accepted.i2c_ok = true;
  assert(otis_setup_authority_acknowledge(&guard, &accepted));
  OtisSetupAuthorization released = {};
  assert(otis_setup_authority_release_execution(&guard, &current,
                                                &released));
  assert(otis_setup_execution_consume(&execution_guard, &released,
                                      &execution));
  OtisSetupApplicationAck failed = {};
  failed.command_sequence = candidate.command_sequence;
  failed.authorization_sequence = candidate.authorization_sequence;
  failed.status_generation = candidate.status_generation;
  failed.query_nonce = candidate.query_nonce;
  failed.session_id = candidate.session_id;
  failed.requested_code = candidate.requested_code;
  failed.applied_code = 0u;
  failed.one_shot_ordinal = 1u;
  failed.kind = OtisSetupApplicationAck::Kind::Failed;
  failed.i2c_ok = false;
  assert(!otis_setup_authority_acknowledge(&guard, &failed));
  assert(guard.state == OtisSetupAuthorityState::Failed);
  assert(execution_guard.consumed);
  assert(!otis_setup_execution_consume(&execution_guard, &released,
                                       &execution));
  assert(!otis_setup_authorize(&guard, &candidate, &current, &authorization));
}

}  // namespace

int main() {
  parser_rejects_noncanonical_or_out_of_range_wire_values();
  every_authority_regression_rejects_before_execution();
  accepted_authority_is_exact_and_i2c_is_one_shot();
  later_observation_generation_preserves_exact_current_authority();
  execution_rechecks_expiry_partition_config_and_actuator();
  interruption_at_each_transaction_phase_is_safe_and_one_shot();
  failed_i2c_ack_is_terminal_and_not_retryable();
  return 0;
}
