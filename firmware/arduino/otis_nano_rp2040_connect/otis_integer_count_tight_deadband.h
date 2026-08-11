#ifndef OTIS_INTEGER_COUNT_TIGHT_DEADBAND_H
#define OTIS_INTEGER_COUNT_TIGHT_DEADBAND_H

#include <stdint.h>

// A pure, non-authorizing integer-count policy. This component neither
// creates commands nor owns DAC or actuator authority.
constexpr uint32_t kOtisIntegerCountDeadbandAuthoritativeSpanSeconds = 600u;
constexpr uint64_t kOtisIntegerCountDeadbandTightEntryAbsCounts = 2u;
constexpr uint64_t kOtisIntegerCountDeadbandLooseReleaseAbsCounts = 4u;
constexpr uint8_t kOtisIntegerCountDeadbandPersistenceEstimates = 2u;

enum OtisIntegerCountDeadbandTightDeadbandState : uint8_t {
  OTIS_INTEGER_COUNT_DEADBAND_REQUALIFY_OUTSIDE = 0u,
  OTIS_INTEGER_COUNT_DEADBAND_OUTSIDE = 1u,
  OTIS_INTEGER_COUNT_DEADBAND_TIGHT_INSIDE = 2u,
};

enum OtisIntegerCountDeadbandTightDeadbandReason : uint8_t {
  OTIS_INTEGER_COUNT_DEADBAND_SESSION_CHANGED_REQUALIFY = 0u,
  OTIS_INTEGER_COUNT_DEADBAND_DAC_EPOCH_CHANGED_REQUALIFY = 1u,
  OTIS_INTEGER_COUNT_DEADBAND_INVALID_OR_STALE_REQUALIFY = 2u,
  OTIS_INTEGER_COUNT_DEADBAND_TIGHT_ENTRY_PENDING = 3u,
  OTIS_INTEGER_COUNT_DEADBAND_TIGHT_ENTRY_CONFIRMED = 4u,
  OTIS_INTEGER_COUNT_DEADBAND_THREE_COUNT_OUTSIDE_HOLD = 5u,
  OTIS_INTEGER_COUNT_DEADBAND_OUTSIDE_LOOSE_EVIDENCE = 6u,
  OTIS_INTEGER_COUNT_DEADBAND_LOOSE_RELEASE_PENDING = 7u,
  OTIS_INTEGER_COUNT_DEADBAND_LOOSE_RELEASE_CONFIRMED = 8u,
  OTIS_INTEGER_COUNT_DEADBAND_THREE_COUNT_INSIDE_HOLD = 9u,
  OTIS_INTEGER_COUNT_DEADBAND_TIGHT_INSIDE_HOLD = 10u,
};

struct OtisIntegerCountDeadbandTightDeadband {
  OtisIntegerCountDeadbandTightDeadbandState state;
  uint8_t entry_pending_count;
  uint8_t release_pending_count;
  bool session_seen;
  uint64_t session;
  bool dac_epoch_seen;
  uint64_t dac_epoch;
};

struct OtisIntegerCountDeadbandTightDeadbandInput {
  // The authoritative observation is signed accumulated edge error over 600 s.
  int64_t accumulated_edge_error_counts;
  bool accumulated_edge_error_counts_available;
  bool fresh;
  uint64_t session;
  uint64_t dac_epoch;
};

struct OtisIntegerCountDeadbandTightDeadbandDecision {
  const char *policy_id;
  OtisIntegerCountDeadbandTightDeadbandState state_before;
  OtisIntegerCountDeadbandTightDeadbandState state_after;
  OtisIntegerCountDeadbandTightDeadbandReason reason;
  bool absolute_edge_error_counts_available;
  uint64_t absolute_edge_error_counts;
  uint8_t entry_pending_count;
  uint8_t release_pending_count;
  bool frequency_controller_eligible;
  bool requalified;
  bool requalification_reason_available;
  OtisIntegerCountDeadbandTightDeadbandReason requalification_reason;
  // These fields are deliberately always false: this is policy observation only.
  bool actionable;
  bool actuation_authorized;
  bool authorization_consumed;
};

void otis_integer_count_tight_deadband_init(
    OtisIntegerCountDeadbandTightDeadband *deadband);
void otis_integer_count_tight_deadband_requalify(
    OtisIntegerCountDeadbandTightDeadband *deadband);

bool otis_integer_count_tight_deadband_observe(
    OtisIntegerCountDeadbandTightDeadband *deadband,
    const OtisIntegerCountDeadbandTightDeadbandInput *input,
    OtisIntegerCountDeadbandTightDeadbandDecision *decision);

// True only for a settled OUTSIDE result.  It is a pure eligibility signal,
// not an authorization and not a request to create an actuator command.
bool otis_integer_count_deadband_frequency_controller_eligible(
    const OtisIntegerCountDeadbandTightDeadband *deadband);

const char *otis_integer_count_tight_deadband_state_name(
    OtisIntegerCountDeadbandTightDeadbandState state);
const char *otis_integer_count_tight_deadband_reason_name(
    OtisIntegerCountDeadbandTightDeadbandReason reason);

#endif
