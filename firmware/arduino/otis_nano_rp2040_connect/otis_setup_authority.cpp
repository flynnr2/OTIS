#include "otis_setup_authority.h"

#include <ctype.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>

namespace {

bool identity_equal(const char *left, const char *right) {
  if (left == nullptr || right == nullptr) return false;
  while (*left != '\0' && *right != '\0') {
    if (tolower(static_cast<unsigned char>(*left)) !=
        tolower(static_cast<unsigned char>(*right)))
      return false;
    ++left;
    ++right;
  }
  return *left == '\0' && *right == '\0';
}

bool parse_u32_token(const char **cursor, uint32_t *value) {
  if (cursor == nullptr || *cursor == nullptr || value == nullptr)
    return false;
  while (**cursor != '\0' &&
         isspace(static_cast<unsigned char>(**cursor)))
    ++*cursor;
  // strtoul accepts signs. The wire contract does not, and accepting one
  // would make the parsed value depend on the target width.
  if (!isdigit(static_cast<unsigned char>(**cursor))) return false;
  errno = 0;
  char *end = nullptr;
  const unsigned long parsed = strtoul(*cursor, &end, 0);
  if (end == *cursor || errno == ERANGE || parsed > UINT32_MAX) return false;
  *value = static_cast<uint32_t>(parsed);
  *cursor = end;
  return true;
}

bool future_within(uint32_t now_s, uint32_t expires_s, uint32_t limit_s) {
  const int32_t remaining = static_cast<int32_t>(expires_s - now_s);
  return remaining > 0 && static_cast<uint32_t>(remaining) <= limit_s;
}

bool ack_matches(const OtisSetupAuthorityRequest &request,
                 const OtisSetupApplicationAck &ack) {
  return ack.command_sequence == request.command_sequence &&
         ack.authorization_sequence == request.authorization_sequence &&
         ack.status_generation == request.status_generation &&
         ack.query_nonce == request.query_nonce &&
         ack.session_id == request.session_id &&
         ack.requested_code == request.requested_code &&
         ack.one_shot_ordinal == request.one_shot_ordinal;
}

bool authorization_equal(const OtisSetupAuthorization &left,
                         const OtisSetupAuthorization &right) {
  const OtisSetupAuthorityRequest &a = left.request;
  const OtisSetupAuthorityRequest &b = right.request;
  return left.authorized_s == right.authorized_s &&
         a.command_sequence == b.command_sequence &&
         a.authorization_sequence == b.authorization_sequence &&
         a.status_generation == b.status_generation &&
         a.query_nonce == b.query_nonce && a.expires_s == b.expires_s &&
         a.session_id == b.session_id &&
         a.requested_code == b.requested_code &&
         a.one_shot_ordinal == b.one_shot_ordinal &&
         identity_equal(a.configuration_identity,
                        b.configuration_identity);
}

bool generation_is_current_or_later(uint32_t observed,
                                    uint32_t retained) {
  if (observed == 0u || retained == 0u) return false;
  // Status generation identifies the retained observation used by the host;
  // publishing a later observation does not itself change setup authority.
  // Modular ordering preserves the declared uint32 rollover behavior while
  // rejecting a context that is behind or ambiguously distant from the
  // retained generation.
  return static_cast<int32_t>(observed - retained) >= 0;
}

bool authority_matches_context(const OtisSetupAuthorityRequest &request,
                               const OtisSetupAuthorityContext &context) {
  return generation_is_current_or_later(context.status_generation,
                                        request.status_generation) &&
         request.query_nonce == context.query_nonce &&
         request.query_nonce != 0u && request.session_id == context.session_id &&
         request.session_id != 0u &&
         request.requested_code == context.expected_code &&
         request.one_shot_ordinal == 1u &&
         identity_equal(request.configuration_identity,
                        context.configuration_identity) &&
         future_within(context.now_s, request.expires_s,
                       OTIS_SETUP_AUTHORIZATION_MAXIMUM_AGE_S) &&
         context.capture_lease_live && context.gnss_eligible &&
         context.reference_eligible && context.partition_healthy &&
         context.active_disarmed && context.setup_not_applied;
}

bool execution_context_accepts(const OtisSetupAuthorization &authorization,
                               const OtisSetupExecutionContext &context) {
  const OtisSetupAuthorityRequest &request = authorization.request;
  return request.command_sequence != 0u && request.status_generation != 0u &&
         request.query_nonce != 0u && request.session_id != 0u &&
         request.one_shot_ordinal == 1u &&
         request.requested_code == context.expected_code &&
         identity_equal(request.configuration_identity,
                        context.configuration_identity) &&
         future_within(context.now_s, request.expires_s,
                       OTIS_SETUP_AUTHORIZATION_MAXIMUM_AGE_S) &&
         context.partition_healthy && context.actuator_ready;
}

}  // namespace

bool otis_setup_authority_parse_request(
    const char *text, OtisSetupAuthorityRequest *request) {
  if (text == nullptr || request == nullptr) return false;
  uint32_t values[7] = {};
  const char *cursor = text;
  for (uint8_t index = 0u; index < 7u; ++index) {
    if (!parse_u32_token(&cursor, &values[index])) return false;
  }
  while (*cursor != '\0' && isspace(static_cast<unsigned char>(*cursor)))
    ++cursor;
  const char *identity = cursor;
  while (*cursor != '\0' && !isspace(static_cast<unsigned char>(*cursor))) {
    if (!isxdigit(static_cast<unsigned char>(*cursor))) return false;
    ++cursor;
  }
  const size_t identity_length = static_cast<size_t>(cursor - identity);
  while (*cursor != '\0' && isspace(static_cast<unsigned char>(*cursor)))
    ++cursor;
  if (*cursor != '\0' || identity_length != 64u ||
      values[5] > UINT16_MAX || values[6] > UINT16_MAX)
    return false;
  *request = {};
  request->authorization_sequence = values[0];
  request->status_generation = values[1];
  request->query_nonce = values[2];
  request->expires_s = values[3];
  request->session_id = values[4];
  request->requested_code = static_cast<uint16_t>(values[5]);
  request->one_shot_ordinal = static_cast<uint16_t>(values[6]);
  memcpy(request->configuration_identity, identity, identity_length);
  request->configuration_identity[identity_length] = '\0';
  return request->authorization_sequence != 0u &&
         request->status_generation != 0u && request->query_nonce != 0u &&
         request->session_id != 0u;
}

void otis_setup_authority_guard_init(OtisSetupAuthorityGuard *guard) {
  if (guard == nullptr) return;
  *guard = {};
  guard->state = OtisSetupAuthorityState::Idle;
  guard->reason = "idle";
}

bool otis_setup_authorize(OtisSetupAuthorityGuard *guard,
                          const OtisSetupAuthorityRequest *request,
                          const OtisSetupAuthorityContext *context,
                          OtisSetupAuthorization *authorization) {
  if (guard == nullptr || request == nullptr || context == nullptr ||
      authorization == nullptr)
    return false;
  const bool exact =
      guard->state == OtisSetupAuthorityState::Idle &&
      request->command_sequence != 0u &&
      request->authorization_sequence > guard->last_authorization_sequence &&
      authority_matches_context(*request, *context);
  if (!exact) {
    guard->reason = "current_setup_authority_rejected";
    return false;
  }
  *authorization = {};
  authorization->request = *request;
  authorization->authorized_s = context->now_s;
  guard->pending = *authorization;
  guard->last_authorization_sequence = request->authorization_sequence;
  guard->state = OtisSetupAuthorityState::AuthorizedAwaitingCore0;
  guard->reason = "current_setup_authority_accepted";
  return true;
}

bool otis_setup_authority_acknowledge(
    OtisSetupAuthorityGuard *guard,
    const OtisSetupApplicationAck *acknowledgement) {
  if (guard == nullptr || acknowledgement == nullptr ||
      guard->state == OtisSetupAuthorityState::Idle ||
      !ack_matches(guard->pending.request, *acknowledgement)) {
    if (guard != nullptr) {
      guard->state = OtisSetupAuthorityState::Failed;
      guard->reason = "setup_application_acknowledgement_mismatch";
    }
    return false;
  }
  if (guard->state == OtisSetupAuthorityState::AuthorizedAwaitingCore0 &&
      acknowledgement->kind ==
          OtisSetupApplicationAck::Kind::Core0Accepted) {
    guard->state = OtisSetupAuthorityState::Core0Accepted;
    guard->reason = "core0_setup_authorization_accepted";
    return true;
  }
  if (acknowledgement->kind ==
          OtisSetupApplicationAck::Kind::Core0Rejected ||
      acknowledgement->kind == OtisSetupApplicationAck::Kind::Failed ||
      !acknowledgement->i2c_ok ||
      (acknowledgement->kind == OtisSetupApplicationAck::Kind::Applied &&
       acknowledgement->applied_code !=
           guard->pending.request.requested_code)) {
    guard->state = OtisSetupAuthorityState::Failed;
    guard->reason = "setup_application_failed";
    return false;
  }
  if (guard->state == OtisSetupAuthorityState::ExecutionReleased &&
      acknowledgement->kind == OtisSetupApplicationAck::Kind::Applied) {
    guard->state = OtisSetupAuthorityState::Applied;
    guard->reason = "setup_application_confirmed";
    return true;
  }
  guard->state = OtisSetupAuthorityState::Failed;
  guard->reason = "setup_application_acknowledgement_phase_mismatch";
  return false;
}

bool otis_setup_authority_release_execution(
    OtisSetupAuthorityGuard *guard,
    const OtisSetupAuthorityContext *current_context,
    OtisSetupAuthorization *authorization) {
  if (guard == nullptr || current_context == nullptr ||
      authorization == nullptr ||
      guard->state != OtisSetupAuthorityState::Core0Accepted ||
      !authority_matches_context(guard->pending.request, *current_context)) {
    if (guard != nullptr) {
      guard->state = OtisSetupAuthorityState::Failed;
      guard->reason = "setup_authority_regressed_before_execution";
    }
    return false;
  }
  *authorization = guard->pending;
  guard->state = OtisSetupAuthorityState::ExecutionReleased;
  guard->reason = "setup_execution_released_after_current_recheck";
  return true;
}

void otis_setup_execution_guard_init(OtisSetupExecutionGuard *guard) {
  if (guard == nullptr) return;
  *guard = {};
  guard->reason = "idle";
}

bool otis_setup_execution_consume(OtisSetupExecutionGuard *guard,
                                  const OtisSetupAuthorization *authorization,
                                  const OtisSetupExecutionContext *context) {
  if (guard == nullptr || authorization == nullptr || context == nullptr)
    return false;
  const bool exact =
      guard->accepted && !guard->consumed &&
      authorization_equal(guard->pending, *authorization) &&
      execution_context_accepts(*authorization, *context);
  if (!exact) {
    guard->reason = "setup_execution_revalidation_rejected";
    return false;
  }
  // Consume before the caller performs I2C. A failed or ambiguous physical
  // attempt cannot be retried in this boot.
  guard->consumed = true;
  guard->last_authorization_sequence =
      authorization->request.authorization_sequence;
  guard->reason = "setup_execution_consumed_before_i2c";
  return true;
}

bool otis_setup_execution_accept(
    OtisSetupExecutionGuard *guard,
    const OtisSetupAuthorization *authorization,
    const OtisSetupExecutionContext *context) {
  if (guard == nullptr || authorization == nullptr || context == nullptr)
    return false;
  const uint32_t sequence = authorization->request.authorization_sequence;
  if (guard->accepted || guard->consumed ||
      sequence <= guard->last_authorization_sequence ||
      !execution_context_accepts(*authorization, *context)) {
    guard->reason = "setup_authorization_rejected_on_core0";
    return false;
  }
  guard->accepted = true;
  guard->pending = *authorization;
  guard->last_authorization_sequence = sequence;
  guard->reason = "setup_authorization_accepted_on_core0";
  return true;
}
