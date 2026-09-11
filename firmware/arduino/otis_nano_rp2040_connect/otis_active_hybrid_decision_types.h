#ifndef OTIS_ACTIVE_HYBRID_DECISION_TYPES_H
#define OTIS_ACTIVE_HYBRID_DECISION_TYPES_H

#include <stdint.h>

// Wire-record projection of the current adaptive controller.  This owns no
// policy state or authority path.
enum class OtisActiveHybridState : uint8_t {
  FrequencyAcquire,
  PhaseQualify,
  FirstPhaseTransaction,
  HybridTracking,
  PhaseDegradedFrequencyOnly,
  FailStatic,
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

const char *otis_active_hybrid_state_name(OtisActiveHybridState state);

#endif
