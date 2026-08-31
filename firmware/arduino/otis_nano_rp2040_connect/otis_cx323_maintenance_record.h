#ifndef OTIS_CX323_MAINTENANCE_RECORD_H
#define OTIS_CX323_MAINTENANCE_RECORD_H

#include <stdint.h>

#include "otis_cx323_maintenance_format.h"
#include "otis_cx323_phase_priority_maintenance.h"

// Pure construction boundary between the CX323 policy engine and the AHM wire
// formatter.  It owns no I/O, queue, command, or DAC authority.  Callers pass
// immutable before/after engine snapshots plus the exact causal joins; this
// module rejects partial or contradictory evidence before formatting.

struct OtisCx323MaintenanceIdentityBinding {
  const char *run_identity;
  const char *build_identity;
  const char *profile_identity;
  const char *active_policy_sha256;
  const char *frequency_estimator_sha256;
};

struct OtisCx323MaintenanceHybridJoin {
  uint64_t hybrid_record_sequence;
  uint64_t hybrid_timing_record_sequence;
  uint64_t decision_sequence;
  uint64_t capture_session;
  uint64_t source_first_sequence;
  uint64_t source_last_sequence;
  uint64_t phase_epoch;
  uint64_t phase_observation_sequence;
  bool phase_valid;
};

struct OtisCx323MaintenanceTransactionJoin {
  uint64_t transaction_record_sequence;
  uint64_t transaction_timing_record_sequence;
  OtisCx323MaintenanceTransactionEvent transaction_event;
  uint64_t request_sequence;
  uint64_t decision_sequence;
  uint64_t capture_session;
  uint64_t source_first_sequence;
  uint64_t source_last_sequence;
  uint64_t application_sequence;
  uint32_t actual_applied_code;
  uint64_t actual_dac_epoch;
  bool downstream_epoch_exact;
};

struct OtisCx323MaintenanceBuildInput {
  uint64_t maintenance_record_sequence;
  OtisCx323MaintenanceEvent event;
  uint64_t event_timestamp_ticks;
  OtisCx323MaintenanceIdentityBinding identity;
  const OtisCx323Engine *engine_before;
  const OtisCx323Engine *engine_after;

  // Required for every decision and transaction lifecycle event.  Optional
  // only for asynchronous metadata/fail-static events, where either the last
  // completed identity is supplied in full or all three pointers are null.
  const OtisCx323Observation *originating_observation;
  const OtisCx323Decision *originating_decision;
  const OtisCx323MaintenanceHybridJoin *hybrid_join;
  const OtisCx323MaintenanceTransactionJoin *transaction_join;

  uint64_t evidence_burst_sequence;
  uint32_t evidence_burst_record_ordinal;
  uint32_t evidence_burst_record_count;
  const char *reason;
};

bool otis_cx323_build_maintenance_record(
    const OtisCx323MaintenanceBuildInput *input,
    OtisCx323MaintenanceRecord *record);

#endif
