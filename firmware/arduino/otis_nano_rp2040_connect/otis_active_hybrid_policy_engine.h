#ifndef OTIS_ACTIVE_HYBRID_POLICY_ENGINE_H
#define OTIS_ACTIVE_HYBRID_POLICY_ENGINE_H

#include <stdint.h>

// Pure CX320 policy engine.  It owns no transport, authority token, actuator,
// DAC, I2C, or serial surface.  The existing active transaction path is the
// only consumer permitted to turn a non-zero result into a request.

enum class OtisActiveHybridState : uint8_t {
  FrequencyAcquire,
  PhaseQualify,
  FirstPhaseTransaction,
  HybridTracking,
  PhaseDegradedFrequencyOnly,
  FailStatic,
};

struct OtisActiveHybridObservation {
  uint32_t timestamp_s;
  uint32_t capture_session;
  uint32_t source_first_sequence;
  uint32_t source_last_sequence;
  uint32_t dac_epoch;
  uint16_t applied_code;
  double frequency_error_hz;
  int32_t accumulated_edge_error_counts;
  const char *tight_state;
  uint32_t phase_epoch;
  uint32_t phase_observation_sequence;
  int64_t relative_phase_cycles;
  uint32_t phase_dac_epoch;
  uint16_t phase_applied_code;
  bool phase_continuous;
  bool phase_current;
  bool phase_step_detected;
  bool identity_exact;
  bool common_health_clean;
  bool phase_consumers_exact;
  bool outstanding_request;
  bool outstanding_response;
};

struct OtisActiveHybridDecision {
  uint32_t decision_sequence;
  uint32_t timestamp_s;
  OtisActiveHybridState state_before;
  OtisActiveHybridState state_after;
  const char *reason;
  double frequency_term_hz;
  double phase_term_hz;
  double combined_demand_hz;
  double raw_combined_delta_codes;
  int32_t requested_delta_codes;
  uint16_t requested_code;
  int32_t counterfactual_frequency_only_delta_codes;
  bool phase_materially_influenced;
  bool step_limited;
  bool range_clamped;
  bool cadence_limited;
  bool count_limited;
  bool cumulative_budget_limited;
  uint16_t correction_count_before;
  uint16_t cumulative_movement_before_codes;
};

struct OtisActiveHybridEngine {
  OtisActiveHybridState state;
  const char *reason;
  const char *fault_reason;
  uint32_t decision_sequence;
  uint16_t applied_code;
  uint32_t dac_epoch;
  uint16_t correction_count;
  uint16_t automatic_application_count;
  uint16_t cumulative_movement_codes;
  // Global authority accounting includes every automatic application.  These
  // natural-history fields deliberately exclude a CX321 identification move.
  // CX320 initializes both origins at kStartCode, so its behavior is unchanged.
  uint16_t natural_chatter_origin_code;
  uint16_t natural_cumulative_movement_codes;
  bool last_application_available;
  uint32_t last_application_s;
  // CX321 enters through the exact-tick APIs so neither the 1,800-second
  // cadence nor phase residence can be released early by integer-second
  // truncation.  CX320 continues to use the legacy seconds fields/APIs.
  bool exact_tick_timing_required;
  uint64_t last_application_ticks;
  int8_t direction_history[4];
  uint8_t direction_count;
  bool transaction_outstanding;
  bool outstanding_phase_material;
  bool outstanding_deliberate_challenge;
  bool first_checkpoint_response_passed;
  bool first_checkpoint_observation_only;
  uint16_t phase_material_application_count;
  uint16_t frequency_only_application_count;
  uint16_t phase_nonzero_application_count;
  bool phase_identity_available;
  uint32_t phase_epoch;
  uint32_t phase_session;
  bool phase_qualification_started;
  uint32_t phase_qualification_started_s;
  uint64_t phase_qualification_started_ticks;
  bool qualified_origin_available;
  uint64_t qualified_origin_ticks;
  bool natural_direction_available;
  int8_t natural_initial_direction;
  bool natural_reversal_observed;
  bool deliberate_challenge_applied;
  bool deliberate_challenge_cancelled;
  bool deliberate_challenge_unexercised;
  bool deliberate_challenge_recovery_applied;
  int8_t deliberate_challenge_direction;
  uint16_t deliberate_challenge_code;
  uint32_t deliberate_challenge_dac_epoch;
  uint64_t deliberate_challenge_application_ticks;
};

void otis_active_hybrid_engine_init(OtisActiveHybridEngine *engine,
                                    uint32_t setup_application_s);
void otis_active_hybrid_engine_init_at_ticks(
    OtisActiveHybridEngine *engine, uint64_t setup_application_ticks);
bool otis_active_hybrid_engine_rebase_after_plant_sign(
    OtisActiveHybridEngine *engine, uint16_t applied_code, uint32_t dac_epoch,
    uint16_t global_correction_count,
    uint16_t global_cumulative_movement_codes,
    uint64_t identification_application_ticks,
    uint64_t response_acknowledgement_ticks);
bool otis_active_hybrid_engine_decide(
    OtisActiveHybridEngine *engine,
    const OtisActiveHybridObservation *observation,
    OtisActiveHybridDecision *decision);
bool otis_active_hybrid_engine_decide_at_ticks(
    OtisActiveHybridEngine *engine,
    const OtisActiveHybridObservation *observation,
    uint64_t observation_ticks, OtisActiveHybridDecision *decision);
bool otis_active_hybrid_engine_note_application(
    OtisActiveHybridEngine *engine,
    const OtisActiveHybridDecision *decision,
    uint16_t applied_code, uint32_t dac_epoch,
    bool downstream_consumers_exact);
bool otis_active_hybrid_engine_note_application_at_ticks(
    OtisActiveHybridEngine *engine,
    const OtisActiveHybridDecision *decision,
    uint16_t applied_code, uint32_t dac_epoch, uint64_t application_ticks,
    bool downstream_consumers_exact);
bool otis_active_hybrid_engine_note_response(
    OtisActiveHybridEngine *engine,
    bool healthy_classification, bool predicted_sign_observed,
    bool exact_replay, bool support_fresh, bool applied_epoch_exact,
    bool observation_only = false);
void otis_active_hybrid_engine_degrade_phase(
    OtisActiveHybridEngine *engine, const char *reason);
const char *otis_active_hybrid_state_name(OtisActiveHybridState state);

#endif
