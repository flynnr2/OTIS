#include "otis_integer_count_tight_deadband.h"

namespace {

constexpr char kPolicyId[] = "CX318_STAGE5_TIGHT_HYSTERETIC_COUNTS_V1";

void requalify(OtisIntegerCountDeadbandTightDeadband *deadband) {
  deadband->state = OTIS_INTEGER_COUNT_DEADBAND_REQUALIFY_OUTSIDE;
  deadband->entry_pending_count = 0u;
  deadband->release_pending_count = 0u;
}

uint64_t absolute_counts(int64_t counts) {
  // Conversion to unsigned is defined modulo 2^64, including INT64_MIN.
  return counts < 0 ? 0u - static_cast<uint64_t>(counts)
                    : static_cast<uint64_t>(counts);
}

void set_decision(OtisIntegerCountDeadbandTightDeadbandDecision *decision,
                  const OtisIntegerCountDeadbandTightDeadband *deadband,
                  OtisIntegerCountDeadbandTightDeadbandState state_before,
                  OtisIntegerCountDeadbandTightDeadbandReason reason,
                  bool absolute_available, uint64_t absolute,
                  bool requalified = false,
                  OtisIntegerCountDeadbandTightDeadbandReason requalification_reason =
                      OTIS_INTEGER_COUNT_DEADBAND_INVALID_OR_STALE_REQUALIFY) {
  decision->policy_id = kPolicyId;
  decision->state_before = state_before;
  decision->state_after = deadband->state;
  decision->reason = reason;
  decision->absolute_edge_error_counts_available = absolute_available;
  decision->absolute_edge_error_counts = absolute;
  decision->entry_pending_count = deadband->entry_pending_count;
  decision->release_pending_count = deadband->release_pending_count;
  decision->frequency_controller_eligible =
      otis_integer_count_deadband_frequency_controller_eligible(deadband);
  decision->requalified = requalified;
  decision->requalification_reason_available = requalified;
  decision->requalification_reason = requalification_reason;
  decision->actionable = false;
  decision->actuation_authorized = false;
  decision->authorization_consumed = false;
}

}  // namespace

void otis_integer_count_tight_deadband_init(
    OtisIntegerCountDeadbandTightDeadband *deadband) {
  if (deadband == nullptr) return;
  deadband->state = OTIS_INTEGER_COUNT_DEADBAND_REQUALIFY_OUTSIDE;
  deadband->entry_pending_count = 0u;
  deadband->release_pending_count = 0u;
  deadband->session_seen = false;
  deadband->session = 0u;
  deadband->dac_epoch_seen = false;
  deadband->dac_epoch = 0u;
}

void otis_integer_count_tight_deadband_requalify(
    OtisIntegerCountDeadbandTightDeadband *deadband) {
  if (deadband == nullptr) return;
  requalify(deadband);
}

bool otis_integer_count_tight_deadband_observe(
    OtisIntegerCountDeadbandTightDeadband *deadband,
    const OtisIntegerCountDeadbandTightDeadbandInput *input,
    OtisIntegerCountDeadbandTightDeadbandDecision *decision) {
  if (deadband == nullptr || input == nullptr || decision == nullptr) return false;

  const OtisIntegerCountDeadbandTightDeadbandState state_before = deadband->state;
  bool identity_requalified = false;
  OtisIntegerCountDeadbandTightDeadbandReason identity_requalification_reason =
      OTIS_INTEGER_COUNT_DEADBAND_INVALID_OR_STALE_REQUALIFY;
  if (deadband->session_seen && input->session != deadband->session) {
    deadband->session = input->session;
    deadband->session_seen = true;
    deadband->dac_epoch = input->dac_epoch;
    deadband->dac_epoch_seen = true;
    requalify(deadband);
    identity_requalified = true;
    identity_requalification_reason =
        OTIS_INTEGER_COUNT_DEADBAND_SESSION_CHANGED_REQUALIFY;
  } else if (deadband->dac_epoch_seen && input->dac_epoch != deadband->dac_epoch) {
    deadband->session = input->session;
    deadband->session_seen = true;
    deadband->dac_epoch = input->dac_epoch;
    deadband->dac_epoch_seen = true;
    requalify(deadband);
    identity_requalified = true;
    identity_requalification_reason =
        OTIS_INTEGER_COUNT_DEADBAND_DAC_EPOCH_CHANGED_REQUALIFY;
  } else {
    deadband->session = input->session;
    deadband->session_seen = true;
    deadband->dac_epoch = input->dac_epoch;
    deadband->dac_epoch_seen = true;
  }

  if (!input->fresh || !input->accumulated_edge_error_counts_available) {
    requalify(deadband);
    set_decision(decision, deadband, state_before,
                 OTIS_INTEGER_COUNT_DEADBAND_INVALID_OR_STALE_REQUALIFY, false, 0u,
                 identity_requalified, identity_requalification_reason);
    return true;
  }

  const uint64_t absolute = absolute_counts(input->accumulated_edge_error_counts);
  if (deadband->state == OTIS_INTEGER_COUNT_DEADBAND_REQUALIFY_OUTSIDE)
    deadband->state = OTIS_INTEGER_COUNT_DEADBAND_OUTSIDE;

  if (deadband->state == OTIS_INTEGER_COUNT_DEADBAND_OUTSIDE) {
    deadband->release_pending_count = 0u;
    if (absolute <= kOtisIntegerCountDeadbandTightEntryAbsCounts) {
      ++deadband->entry_pending_count;
      if (deadband->entry_pending_count >= kOtisIntegerCountDeadbandPersistenceEstimates) {
        deadband->state = OTIS_INTEGER_COUNT_DEADBAND_TIGHT_INSIDE;
        deadband->entry_pending_count = 0u;
        set_decision(decision, deadband, state_before,
                     OTIS_INTEGER_COUNT_DEADBAND_TIGHT_ENTRY_CONFIRMED, true, absolute,
                     identity_requalified, identity_requalification_reason);
        return true;
      }
      set_decision(decision, deadband, state_before,
                   OTIS_INTEGER_COUNT_DEADBAND_TIGHT_ENTRY_PENDING, true, absolute,
                   identity_requalified, identity_requalification_reason);
      return true;
    }
    deadband->entry_pending_count = 0u;
    set_decision(decision, deadband, state_before,
                 absolute == 3u ? OTIS_INTEGER_COUNT_DEADBAND_THREE_COUNT_OUTSIDE_HOLD
                                : OTIS_INTEGER_COUNT_DEADBAND_OUTSIDE_LOOSE_EVIDENCE,
                 true, absolute, identity_requalified,
                 identity_requalification_reason);
    return true;
  }

  deadband->entry_pending_count = 0u;
  if (absolute >= kOtisIntegerCountDeadbandLooseReleaseAbsCounts) {
    ++deadband->release_pending_count;
    if (deadband->release_pending_count >= kOtisIntegerCountDeadbandPersistenceEstimates) {
      deadband->state = OTIS_INTEGER_COUNT_DEADBAND_OUTSIDE;
      deadband->release_pending_count = 0u;
      set_decision(decision, deadband, state_before,
                   OTIS_INTEGER_COUNT_DEADBAND_LOOSE_RELEASE_CONFIRMED, true, absolute,
                   identity_requalified, identity_requalification_reason);
      return true;
    }
    set_decision(decision, deadband, state_before,
                 OTIS_INTEGER_COUNT_DEADBAND_LOOSE_RELEASE_PENDING, true, absolute,
                 identity_requalified, identity_requalification_reason);
    return true;
  }
  deadband->release_pending_count = 0u;
  set_decision(decision, deadband, state_before,
               absolute == 3u ? OTIS_INTEGER_COUNT_DEADBAND_THREE_COUNT_INSIDE_HOLD
                              : OTIS_INTEGER_COUNT_DEADBAND_TIGHT_INSIDE_HOLD,
               true, absolute, identity_requalified,
               identity_requalification_reason);
  return true;
}

bool otis_integer_count_deadband_frequency_controller_eligible(
    const OtisIntegerCountDeadbandTightDeadband *deadband) {
  return deadband != nullptr && deadband->state == OTIS_INTEGER_COUNT_DEADBAND_OUTSIDE &&
         deadband->entry_pending_count == 0u &&
         deadband->release_pending_count == 0u;
}

const char *otis_integer_count_tight_deadband_state_name(
    OtisIntegerCountDeadbandTightDeadbandState state) {
  switch (state) {
    case OTIS_INTEGER_COUNT_DEADBAND_REQUALIFY_OUTSIDE:
      return "REQUALIFY_OUTSIDE";
    case OTIS_INTEGER_COUNT_DEADBAND_OUTSIDE:
      return "OUTSIDE";
    case OTIS_INTEGER_COUNT_DEADBAND_TIGHT_INSIDE:
      return "TIGHT_INSIDE";
  }
  return "UNKNOWN";
}

const char *otis_integer_count_tight_deadband_reason_name(
    OtisIntegerCountDeadbandTightDeadbandReason reason) {
  switch (reason) {
    case OTIS_INTEGER_COUNT_DEADBAND_SESSION_CHANGED_REQUALIFY:
      return "session_changed_requalify";
    case OTIS_INTEGER_COUNT_DEADBAND_DAC_EPOCH_CHANGED_REQUALIFY:
      return "dac_epoch_changed_requalify";
    case OTIS_INTEGER_COUNT_DEADBAND_INVALID_OR_STALE_REQUALIFY:
      return "invalid_or_stale_requalify";
    case OTIS_INTEGER_COUNT_DEADBAND_TIGHT_ENTRY_PENDING:
      return "tight_entry_pending";
    case OTIS_INTEGER_COUNT_DEADBAND_TIGHT_ENTRY_CONFIRMED:
      return "tight_entry_confirmed";
    case OTIS_INTEGER_COUNT_DEADBAND_THREE_COUNT_OUTSIDE_HOLD:
      return "three_count_outside_hold";
    case OTIS_INTEGER_COUNT_DEADBAND_OUTSIDE_LOOSE_EVIDENCE:
      return "outside_loose_evidence";
    case OTIS_INTEGER_COUNT_DEADBAND_LOOSE_RELEASE_PENDING:
      return "loose_release_pending";
    case OTIS_INTEGER_COUNT_DEADBAND_LOOSE_RELEASE_CONFIRMED:
      return "loose_release_confirmed";
    case OTIS_INTEGER_COUNT_DEADBAND_THREE_COUNT_INSIDE_HOLD:
      return "three_count_inside_hold";
    case OTIS_INTEGER_COUNT_DEADBAND_TIGHT_INSIDE_HOLD:
      return "tight_inside_hold";
  }
  return "unknown";
}
