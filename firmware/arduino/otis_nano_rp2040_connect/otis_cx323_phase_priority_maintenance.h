#ifndef OTIS_CX323_PHASE_PRIORITY_MAINTENANCE_H
#define OTIS_CX323_PHASE_PRIORITY_MAINTENANCE_H

#include <stdint.h>

#include "otis_cx323_wide.h"

// Pure CX323 policy engine.  This file deliberately has no Arduino, device,
// transport, command, DAC, I2C, serial, telemetry, or live-authority surface.
// A non-zero decision is only a proposal for the existing transaction owner.

struct OtisCx323Policy {
  int32_t maximum_step_codes;
  int32_t minimum_code;
  int32_t maximum_code;
  uint64_t minimum_cadence_s;
  uint32_t maximum_applications;
  uint32_t maximum_cumulative_movement_codes;
  int32_t setup_code;
};

struct OtisCx323Identity {
  uint64_t capture_session;
  int32_t applied_code;
  uint64_t dac_epoch;
  uint64_t phase_epoch;
  bool phase_valid;
  uint64_t selected_estimator_identity;
};

struct OtisCx323Observation {
  uint64_t timestamp_s;
  uint64_t capture_session;
  uint64_t source_first_sequence;
  uint64_t source_last_sequence;
  uint64_t dac_epoch;
  int32_t applied_code;
  int64_t accumulated_edge_error_counts;
  bool tight_inside;
  uint64_t phase_epoch;
  int64_t relative_phase_cycles;
  uint64_t selected_estimator_identity;
  bool phase_valid;
  bool authority_valid;
  bool settled;
  bool cadence_eligible;
  bool metadata_qualified;
  // Authoritative extended rp2040_timer0 counter.  timestamp_s is its
  // floor-divided display projection and never participates in control.
  uint64_t timestamp_ticks;
};

struct OtisCx323Debt {
  int64_t fll_picocodes;
  int64_t pll_picocodes;
};

struct OtisCx323Decision {
  uint64_t decision_sequence;
  const char *reason;
  int32_t requested_delta_codes;
  int32_t requested_code;
  int32_t safe_cap_codes;
  uint8_t persistence_count;
  OtisCx323Wide raw_combined_picocodes;
  OtisCx323Wide raw_fll_picocodes;
  OtisCx323Wide raw_pll_picocodes;
  int64_t committed_debt_picocodes;
  bool maintenance_request;
  uint64_t decision_timestamp_ticks;
  int32_t counterfactual_frequency_only_delta_codes;
  bool phase_materially_influenced;
  bool step_limited;
  bool range_clamped;
  bool cadence_limited;
  bool count_limited;
  bool cumulative_budget_limited;
};

struct OtisCx323Engine {
  OtisCx323Policy policy;
  int32_t applied_code;
  uint64_t dac_epoch;
  uint32_t application_count;
  uint32_t cumulative_movement_codes;
  bool last_application_available;
  uint64_t last_application_s;
  uint64_t last_application_ticks;
  int32_t chatter_origin_code;
  int8_t direction_history[3];
  uint8_t direction_count;

  OtisCx323Debt debt;
  int8_t persistence_sign;
  uint8_t persistence_count;
  bool persistence_identity_available;
  OtisCx323Identity persistence_identity;
  bool last_closing_frontier_available;
  uint64_t last_closing_frontier;

  bool request_pending;
  bool response_pending;
  bool metadata_hold;
  bool metadata_requalified;
  bool requalification_frontier_available;
  uint64_t requalification_frontier;
  uint8_t requalification_window_count;
  bool requalification_last_closing_frontier_available;
  uint64_t requalification_last_closing_frontier;
  bool requalification_identity_available;
  OtisCx323Identity requalification_identity;
  const char *fail_static_reason;
  const char *last_reason;
  uint64_t decision_sequence;
  uint64_t current_timestamp_s;
  uint64_t current_timestamp_ticks;

  // Immutable proposal snapshot.  Application/debt commit is rejected unless
  // the caller returns this exact decision identity through the first
  // dependent consumer.
  uint64_t pending_decision_sequence;
  int32_t pending_requested_delta_codes;
  int32_t pending_requested_code;
  OtisCx323Wide pending_raw_combined_picocodes;
  OtisCx323Wide pending_raw_fll_picocodes;
  OtisCx323Wide pending_raw_pll_picocodes;
  bool pending_maintenance_request;
  uint64_t pending_observation_timestamp_s;
  uint64_t pending_observation_timestamp_ticks;
  int32_t pending_counterfactual_frequency_only_delta_codes;
  bool pending_phase_materially_influenced;
  bool pending_step_limited;
  bool pending_range_clamped;
  bool pending_cadence_limited;
  bool pending_count_limited;
  bool pending_cumulative_budget_limited;
};

OtisCx323Policy otis_cx323_default_policy();

bool otis_cx323_engine_init(OtisCx323Engine *engine,
                            const OtisCx323Policy *policy,
                            int32_t setup_applied_code,
                            uint64_t setup_dac_epoch);

// Bind the exact setup application before policy activation.  The exact
// counter is authoritative; the whole-second value is only its floor-divided
// projection for legacy/status consumers.
bool otis_cx323_engine_bind_exact_setup_application(
    OtisCx323Engine *engine, uint64_t setup_application_ticks);

// Frozen exact conversion.  The implementation uses reduced checked
// target-portable quotient/remainder arithmetic and never forms centre*1e24.
bool otis_cx323_centre_to_picocodes(OtisCx323Wide centre_units,
                                    OtisCx323Wide *picocodes);

bool otis_cx323_round_ratio(OtisCx323Wide numerator,
                            OtisCx323Wide denominator,
                            OtisCx323Wide *rounded);

bool otis_cx323_engine_decide(OtisCx323Engine *engine,
                              const OtisCx323Observation *observation,
                              OtisCx323Decision *decision);

bool otis_cx323_engine_reject_or_expire_request(OtisCx323Engine *engine);

bool otis_cx323_engine_note_application_and_first_consumer(
    OtisCx323Engine *engine, const OtisCx323Decision *decision,
    int32_t actual_applied_code, uint64_t actual_dac_epoch,
    bool first_consumer_exact);

bool otis_cx323_engine_complete_response(OtisCx323Engine *engine,
                                         bool fresh_exact);

bool otis_cx323_engine_enter_metadata_hold(OtisCx323Engine *engine);

bool otis_cx323_engine_requalify_metadata(OtisCx323Engine *engine,
                                          uint64_t evidence_frontier);

bool otis_cx323_engine_new_policy_activation(OtisCx323Engine *engine);

#endif
