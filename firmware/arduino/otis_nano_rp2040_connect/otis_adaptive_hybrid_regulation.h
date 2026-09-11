#ifndef OTIS_ADAPTIVE_HYBRID_REGULATION_H
#define OTIS_ADAPTIVE_HYBRID_REGULATION_H

#include <stdint.h>

#include "otis_config.h"
#include "otis_adaptive_hybrid_wide.h"

// Accepted boundary ordinals are a declared uint32 modular domain.  An active
// decision only consumes an estimator's complete frozen 600-interval span.
static inline bool otis_exact_selected_accepted_span(
    uint64_t opening_accepted_boundary_ordinal,
    uint64_t closing_accepted_boundary_ordinal) {
  return opening_accepted_boundary_ordinal <= UINT32_MAX &&
         closing_accepted_boundary_ordinal <= UINT32_MAX &&
         static_cast<uint32_t>(closing_accepted_boundary_ordinal) -
                 static_cast<uint32_t>(opening_accepted_boundary_ordinal) ==
             OTIS_FREQUENCY_ESTIMATOR_SPAN_INTERVALS_CONFIG;
}

static inline bool otis_accepted_ordinal_at_or_after(
    uint64_t candidate_accepted_boundary_ordinal,
    uint64_t reference_accepted_boundary_ordinal) {
  if (candidate_accepted_boundary_ordinal > UINT32_MAX ||
      reference_accepted_boundary_ordinal > UINT32_MAX)
    return false;
  return static_cast<uint32_t>(candidate_accepted_boundary_ordinal) -
             static_cast<uint32_t>(reference_accepted_boundary_ordinal) <
         0x80000000u;
}

// Pure ADAPTIVE_HYBRID policy engine.  This file deliberately has no Arduino, device,
// transport, command, DAC, I2C, serial, telemetry, or live-authority surface.
// A non-zero decision is only a proposal for the existing transaction owner.

struct OtisAdaptiveHybridPolicy {
  int32_t maximum_step_codes;
  int32_t minimum_code;
  int32_t maximum_code;
  uint64_t minimum_cadence_s;
  uint32_t maximum_applications;
  uint32_t maximum_cumulative_movement_codes;
  int32_t setup_code;
};

struct OtisAdaptiveHybridIdentity {
  uint64_t capture_session;
  uint64_t source_acceptance_epoch;
  int32_t applied_code;
  uint64_t dac_epoch;
  uint64_t phase_epoch;
  bool phase_valid;
  uint64_t selected_estimator_identity;
};

struct OtisAdaptiveHybridObservation {
  uint64_t timestamp_s;
  uint64_t capture_session;
  uint64_t source_acceptance_epoch;
  uint64_t source_opening_accepted_boundary_ordinal;
  uint64_t source_closing_accepted_boundary_ordinal;
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
  // Authoritative extended rp2040_monotonic_us64 counter. timestamp_s is its
  // floor-divided display projection and never participates in control.
  uint64_t timestamp_ticks;
};

struct OtisAdaptiveHybridDebt {
  int64_t fll_picocodes;
  int64_t pll_picocodes;
};

struct OtisAdaptiveHybridDecision {
  uint64_t decision_sequence;
  const char *reason;
  int32_t requested_delta_codes;
  int32_t requested_code;
  int32_t safe_cap_codes;
  uint8_t persistence_count;
  OtisAdaptiveHybridWide raw_combined_picocodes;
  OtisAdaptiveHybridWide raw_fll_picocodes;
  OtisAdaptiveHybridWide raw_pll_picocodes;
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

struct OtisAdaptiveHybridEngine {
  OtisAdaptiveHybridPolicy policy;
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

  OtisAdaptiveHybridDebt debt;
  int8_t persistence_sign;
  uint8_t persistence_count;
  bool persistence_identity_available;
  OtisAdaptiveHybridIdentity persistence_identity;
  bool last_closing_accepted_boundary_ordinal_available;
  uint64_t last_closing_accepted_boundary_ordinal;

  bool request_pending;
  bool response_pending;
  bool metadata_hold;
  bool metadata_requalified;
  bool requalification_accepted_boundary_ordinal_available;
  uint64_t requalification_accepted_boundary_ordinal;
  uint64_t requalification_acceptance_epoch;
  uint8_t requalification_window_count;
  bool requalification_last_closing_accepted_boundary_ordinal_available;
  uint64_t requalification_last_closing_accepted_boundary_ordinal;
  bool requalification_identity_available;
  OtisAdaptiveHybridIdentity requalification_identity;
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
  OtisAdaptiveHybridWide pending_raw_combined_picocodes;
  OtisAdaptiveHybridWide pending_raw_fll_picocodes;
  OtisAdaptiveHybridWide pending_raw_pll_picocodes;
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

OtisAdaptiveHybridPolicy otis_adaptive_hybrid_default_policy();

bool otis_adaptive_hybrid_engine_init(OtisAdaptiveHybridEngine *engine,
                            const OtisAdaptiveHybridPolicy *policy,
                            int32_t setup_applied_code,
                            uint64_t setup_dac_epoch);

// Bind the exact setup application before policy activation.  The exact
// counter is authoritative; the whole-second value is only its floor-divided
// projection for status consumers.
bool otis_adaptive_hybrid_engine_bind_exact_setup_application(
    OtisAdaptiveHybridEngine *engine, uint64_t setup_application_ticks);

// Frozen exact conversion.  The implementation uses reduced checked
// target-portable quotient/remainder arithmetic and never forms centre*1e24.
bool otis_adaptive_hybrid_centre_to_picocodes(OtisAdaptiveHybridWide centre_units,
                                    OtisAdaptiveHybridWide *picocodes);

bool otis_adaptive_hybrid_round_ratio(OtisAdaptiveHybridWide numerator,
                            OtisAdaptiveHybridWide denominator,
                            OtisAdaptiveHybridWide *rounded);

bool otis_adaptive_hybrid_engine_decide(OtisAdaptiveHybridEngine *engine,
                              const OtisAdaptiveHybridObservation *observation,
                              OtisAdaptiveHybridDecision *decision);

bool otis_adaptive_hybrid_engine_reject_or_expire_request(OtisAdaptiveHybridEngine *engine);

bool otis_adaptive_hybrid_engine_note_application_and_first_consumer(
    OtisAdaptiveHybridEngine *engine, const OtisAdaptiveHybridDecision *decision,
    int32_t actual_applied_code, uint64_t actual_dac_epoch,
    bool first_consumer_exact);

bool otis_adaptive_hybrid_engine_complete_response(OtisAdaptiveHybridEngine *engine,
                                         bool fresh_exact);

bool otis_adaptive_hybrid_engine_enter_metadata_hold(OtisAdaptiveHybridEngine *engine);

bool otis_adaptive_hybrid_engine_requalify_metadata(OtisAdaptiveHybridEngine *engine,
                                          uint64_t acceptance_epoch,
                                          uint64_t accepted_boundary_ordinal);

bool otis_adaptive_hybrid_engine_new_policy_activation(OtisAdaptiveHybridEngine *engine);

#endif
