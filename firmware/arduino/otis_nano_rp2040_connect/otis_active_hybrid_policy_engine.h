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
  uint16_t cumulative_movement_codes;
  bool last_application_available;
  uint32_t last_application_s;
  int8_t direction_history[4];
  uint8_t direction_count;
  bool transaction_outstanding;
  bool outstanding_phase_material;
  bool first_checkpoint_response_passed;
  uint16_t phase_material_application_count;
  uint16_t frequency_only_application_count;
  uint16_t phase_nonzero_application_count;
  bool phase_identity_available;
  uint32_t phase_epoch;
  uint32_t phase_session;
  bool phase_qualification_started;
  uint32_t phase_qualification_started_s;
};

void otis_active_hybrid_engine_init(OtisActiveHybridEngine *engine);
bool otis_active_hybrid_engine_decide(
    OtisActiveHybridEngine *engine,
    const OtisActiveHybridObservation *observation,
    OtisActiveHybridDecision *decision);
bool otis_active_hybrid_engine_note_application(
    OtisActiveHybridEngine *engine,
    const OtisActiveHybridDecision *decision,
    uint16_t applied_code, uint32_t dac_epoch,
    bool downstream_consumers_exact);
bool otis_active_hybrid_engine_note_response(
    OtisActiveHybridEngine *engine,
    bool healthy_classification, bool predicted_sign_observed,
    bool exact_replay, bool support_fresh, bool applied_epoch_exact);
void otis_active_hybrid_engine_degrade_phase(
    OtisActiveHybridEngine *engine, const char *reason);
const char *otis_active_hybrid_state_name(OtisActiveHybridState state);

#endif
