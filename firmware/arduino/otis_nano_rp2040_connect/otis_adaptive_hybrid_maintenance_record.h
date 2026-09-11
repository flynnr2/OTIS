#ifndef OTIS_ADAPTIVE_HYBRID_MAINTENANCE_RECORD_H
#define OTIS_ADAPTIVE_HYBRID_MAINTENANCE_RECORD_H

#include <stdint.h>

#include "otis_adaptive_hybrid_maintenance_format.h"
#include "otis_adaptive_hybrid_regulation.h"

// Pure construction boundary between the ADAPTIVE_HYBRID policy engine and the AHM wire
// formatter.  It owns no I/O, queue, command, or DAC authority.  Callers pass
// immutable before/after engine snapshots plus the exact causal joins; this
// module rejects partial or contradictory evidence before formatting.

struct OtisAdaptiveHybridMaintenanceIdentityBinding {
  const char *run_identity;
  const char *build_identity;
  const char *image_identity;
  const char *active_policy_sha256;
  const char *frequency_estimator_sha256;
};

struct OtisAdaptiveHybridMaintenanceHybridJoin {
  uint64_t hybrid_record_sequence;
  uint64_t decision_sequence;
  uint64_t capture_session;
  uint64_t source_acceptance_epoch;
  uint64_t source_opening_accepted_boundary_ordinal;
  uint64_t source_closing_accepted_boundary_ordinal;
  uint64_t phase_epoch;
  uint64_t phase_observation_sequence;
  bool phase_valid;
};

struct OtisAdaptiveHybridMaintenanceTransactionJoin {
  uint64_t transaction_record_sequence;
  OtisAdaptiveHybridMaintenanceTransactionEvent transaction_event;
  uint64_t request_sequence;
  uint64_t decision_sequence;
  uint64_t capture_session;
  uint64_t source_acceptance_epoch;
  uint64_t source_opening_accepted_boundary_ordinal;
  uint64_t source_closing_accepted_boundary_ordinal;
  uint64_t application_sequence;
  uint32_t actual_applied_code;
  uint64_t actual_dac_epoch;
  bool downstream_epoch_exact;
};

struct OtisAdaptiveHybridMaintenanceBuildInput {
  uint64_t maintenance_record_sequence;
  OtisAdaptiveHybridMaintenanceEvent event;
  uint64_t event_timestamp_ticks;
  OtisAdaptiveHybridMaintenanceIdentityBinding identity;
  const OtisAdaptiveHybridEngine *engine_before;
  const OtisAdaptiveHybridEngine *engine_after;

  // Required for every decision and transaction lifecycle event.  Optional
  // only for asynchronous metadata/fail-static events, where either the last
  // completed identity is supplied in full or all three pointers are null.
  const OtisAdaptiveHybridObservation *originating_observation;
  const OtisAdaptiveHybridDecision *originating_decision;
  const OtisAdaptiveHybridMaintenanceHybridJoin *hybrid_join;
  const OtisAdaptiveHybridMaintenanceTransactionJoin *transaction_join;

  uint64_t evidence_burst_sequence;
  uint32_t evidence_burst_record_ordinal;
  uint32_t evidence_burst_record_count;
  const char *reason;
};

bool otis_adaptive_hybrid_build_maintenance_record(
    const OtisAdaptiveHybridMaintenanceBuildInput *input,
    OtisAdaptiveHybridMaintenanceRecord *record);

#endif
