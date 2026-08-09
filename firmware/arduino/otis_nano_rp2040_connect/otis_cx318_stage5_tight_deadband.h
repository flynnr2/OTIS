#ifndef OTIS_CX318_STAGE5_TIGHT_DEADBAND_H
#define OTIS_CX318_STAGE5_TIGHT_DEADBAND_H

#include <stdint.h>

// A pure, non-authorizing CX318 Stage 5 policy.  This component neither
// creates commands nor owns DAC or actuator authority.
constexpr uint32_t kOtisCx318Stage5AuthoritativeSpanSeconds = 600u;
constexpr uint64_t kOtisCx318Stage5TightEntryAbsCounts = 2u;
constexpr uint64_t kOtisCx318Stage5LooseReleaseAbsCounts = 4u;
constexpr uint8_t kOtisCx318Stage5PersistenceEstimates = 2u;

enum OtisCx318Stage5TightDeadbandState : uint8_t {
  OTIS_CX318_STAGE5_REQUALIFY_OUTSIDE = 0u,
  OTIS_CX318_STAGE5_OUTSIDE = 1u,
  OTIS_CX318_STAGE5_TIGHT_INSIDE = 2u,
};

enum OtisCx318Stage5TightDeadbandReason : uint8_t {
  OTIS_CX318_STAGE5_SESSION_CHANGED_REQUALIFY = 0u,
  OTIS_CX318_STAGE5_DAC_EPOCH_CHANGED_REQUALIFY = 1u,
  OTIS_CX318_STAGE5_INVALID_OR_STALE_REQUALIFY = 2u,
  OTIS_CX318_STAGE5_TIGHT_ENTRY_PENDING = 3u,
  OTIS_CX318_STAGE5_TIGHT_ENTRY_CONFIRMED = 4u,
  OTIS_CX318_STAGE5_THREE_COUNT_OUTSIDE_HOLD = 5u,
  OTIS_CX318_STAGE5_OUTSIDE_LOOSE_EVIDENCE = 6u,
  OTIS_CX318_STAGE5_LOOSE_RELEASE_PENDING = 7u,
  OTIS_CX318_STAGE5_LOOSE_RELEASE_CONFIRMED = 8u,
  OTIS_CX318_STAGE5_THREE_COUNT_INSIDE_HOLD = 9u,
  OTIS_CX318_STAGE5_TIGHT_INSIDE_HOLD = 10u,
};

struct OtisCx318Stage5TightDeadband {
  OtisCx318Stage5TightDeadbandState state;
  uint8_t entry_pending_count;
  uint8_t release_pending_count;
  bool session_seen;
  uint64_t session;
  bool dac_epoch_seen;
  uint64_t dac_epoch;
};

struct OtisCx318Stage5TightDeadbandInput {
  // The authoritative observation is signed accumulated edge error over 600 s.
  int64_t accumulated_edge_error_counts;
  bool accumulated_edge_error_counts_available;
  bool fresh;
  uint64_t session;
  uint64_t dac_epoch;
};

struct OtisCx318Stage5TightDeadbandDecision {
  const char *policy_id;
  OtisCx318Stage5TightDeadbandState state_before;
  OtisCx318Stage5TightDeadbandState state_after;
  OtisCx318Stage5TightDeadbandReason reason;
  bool absolute_edge_error_counts_available;
  uint64_t absolute_edge_error_counts;
  uint8_t entry_pending_count;
  uint8_t release_pending_count;
  bool frequency_controller_eligible;
  bool requalified;
  bool requalification_reason_available;
  OtisCx318Stage5TightDeadbandReason requalification_reason;
  // These fields are deliberately always false: this is policy observation only.
  bool actionable;
  bool actuation_authorized;
  bool authorization_consumed;
};

void otis_cx318_stage5_tight_deadband_init(
    OtisCx318Stage5TightDeadband *deadband);
void otis_cx318_stage5_tight_deadband_requalify(
    OtisCx318Stage5TightDeadband *deadband);

bool otis_cx318_stage5_tight_deadband_observe(
    OtisCx318Stage5TightDeadband *deadband,
    const OtisCx318Stage5TightDeadbandInput *input,
    OtisCx318Stage5TightDeadbandDecision *decision);

// True only for a settled OUTSIDE result.  It is a pure eligibility signal,
// not an authorization and not a request to create an actuator command.
bool otis_cx318_stage5_frequency_controller_eligible(
    const OtisCx318Stage5TightDeadband *deadband);

const char *otis_cx318_stage5_tight_deadband_state_name(
    OtisCx318Stage5TightDeadbandState state);
const char *otis_cx318_stage5_tight_deadband_reason_name(
    OtisCx318Stage5TightDeadbandReason reason);

#endif
