#ifndef OTIS_CX323_MAINTENANCE_FORMAT_H
#define OTIS_CX323_MAINTENANCE_FORMAT_H

#include <stddef.h>
#include <stdint.h>

#include "otis_cx323_wide.h"

// Pure wire-format boundary for active_hybrid_maintenance_v1.  This module
// deliberately has no Arduino, transport, queue, controller, or actuator
// dependency.  The caller remains responsible for atomic burst admission.

enum class OtisCx323MaintenanceEvent : uint8_t {
  PolicyActivation = 0,
  Decision,
  RequestRejectedOrExpired,
  ApplicationFirstConsumer,
  ResponseComplete,
  GnssMetadataHoldEnter,
  GnssMetadataRequalified,
  FailStatic,
};

enum class OtisCx323MaintenanceState : uint8_t {
  PolicyInactive = 0,
  Ready,
  PersistenceHold,
  RequestPending,
  ResponsePending,
  MetadataHold,
  FailStatic,
};

enum class OtisCx323FrontierRelation : uint8_t {
  NotApplicable = 0,
  First,
  Contiguous,
  Overlap,
  Gap,
};

enum class OtisCx323MaintenanceTransactionEvent : uint8_t {
  None = 0,
  RequestCreated,
  RequestWithdrawn,
  Application,
  ApplicationFault,
  Response,
};

struct OtisCx323MaintenanceRecord {
  uint64_t maintenance_record_sequence;
  OtisCx323MaintenanceEvent event;
  uint64_t event_timestamp_ticks;
  const char *run_identity;
  const char *build_identity;
  const char *profile_identity;
  const char *active_policy_sha256;
  uint64_t capture_session;
  uint64_t source_first_sequence;
  uint64_t source_last_sequence;
  const char *frequency_estimator_sha256;
  uint64_t phase_epoch;
  uint64_t phase_observation_sequence;
  bool phase_valid;
  uint32_t current_applied_code;
  uint64_t current_dac_epoch;
  uint64_t hybrid_record_sequence;
  uint64_t hybrid_timing_record_sequence;
  uint64_t decision_sequence;
  uint64_t transaction_record_sequence;
  uint64_t transaction_timing_record_sequence;
  OtisCx323MaintenanceTransactionEvent transaction_event;
  uint64_t request_sequence;
  uint64_t application_sequence;
  uint32_t actual_applied_code;
  uint64_t actual_dac_epoch;
  bool downstream_epoch_exact;
  OtisCx323MaintenanceState maintenance_state_before;
  OtisCx323MaintenanceState maintenance_state_after;
  OtisCx323FrontierRelation frontier_relation;
  int8_t interval_sign;
  uint8_t persistence_count_before;
  uint8_t persistence_count_after;
  OtisCx323Wide raw_fll_demand_picocodes;
  OtisCx323Wide raw_pll_demand_picocodes;
  OtisCx323Wide candidate_total_demand_picocodes;
  uint8_t safe_cap_codes;
  int32_t requested_delta_codes;
  uint32_t requested_code;
  int64_t committed_fll_debt_before_picocodes;
  int64_t committed_pll_debt_before_picocodes;
  int64_t committed_fll_debt_after_picocodes;
  int64_t committed_pll_debt_after_picocodes;
  bool request_pending_before;
  bool request_pending_after;
  bool response_pending_before;
  bool response_pending_after;
  bool metadata_hold_before;
  bool metadata_hold_after;
  uint8_t requalification_window_count_before;
  uint8_t requalification_window_count_after;
  uint64_t requalification_d14_d8_observation_sequence;
  uint64_t evidence_burst_sequence;
  uint32_t evidence_burst_record_ordinal;
  uint32_t evidence_burst_record_count;
  const char *reason;
};

// Both functions return the number of bytes written (excluding the terminating
// NUL), or -1 for invalid input or insufficient output capacity.  Successful
// output includes CRLF and is always NUL terminated.
int otis_format_cx323_maintenance_v1_header(char *output, size_t output_size);

int otis_format_cx323_maintenance_v1(
    char *output, size_t output_size,
    const OtisCx323MaintenanceRecord *record);

#endif
