#include <stdio.h>

#include "otis_active_hybrid_decision_format.h"
#include "otis_active_hybrid_decision_types.h"
#include "otis_adaptive_hybrid_regulation_live.h"

int main() {
  constexpr char kSha[] =
      "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
  OtisAdaptiveHybridRegulationLiveDecision source = {};
  source.decision_sequence = 1u;
  source.timestamp_s = 5000u;
  source.current_applied_code = 43068u;
  source.requested_code = 43068u;
  source.frequency_error_hz = 0.00166666694;
  source.measurement_valid = true;
  source.model_applicable = true;
  source.control_eligible = true;
  source.preview_available = true;
  source.capture_session = 1u;
  source.source_acceptance_epoch = 3u;
  source.source_opening_accepted_boundary_ordinal = 1800u;
  source.source_closing_accepted_boundary_ordinal = 2400u;
  source.accumulated_edge_error_counts = 1;
  source.tight_state = "OUTSIDE";
  source.dac_epoch = 1u;
  source.phase_epoch = 1u;
  source.phase_observation_sequence = 2394u;
  source.relative_phase_cycles = 4;
  source.phase_dac_epoch = 1u;
  source.phase_applied_code = 43068u;
  source.phase_continuous = true;
  source.phase_current = true;
  source.phase_recorder_published = true;
  const OtisActiveHybridDecision decision = {
      1u,
      5000u,
      OtisActiveHybridState::FrequencyAcquire,
      OtisActiveHybridState::FrequencyAcquire,
      "minimum_applied_cadence_hold",
      -0.00166666694,
      0.0,
      -0.00166666694,
      0.0,
      0,
      43068u,
      0,
      false,
      false,
      false,
      true,
      false,
      false,
      0u,
      0u,
  };
  const OtisActiveHybridDecisionRecordContext context = {
      1u,
      5000000000ull,
      "adaptive_hybrid_regulation:1",
      "source_sha256:config_sha256",
      "adaptive_hybrid_regulation",
      kSha,
      kSha,
      "ARMED",
      0u,
      0u,
      0u,
      "unavailable",
      true,
      kSha,
      kSha,
      false,
  };
  char output[1536] = "";
  const int used = otis_format_active_hybrid_decision_v3(
      output, sizeof(output), &source, &decision, &context);
  if (used <= 0 || static_cast<size_t>(used) >= sizeof(output)) return 1;
  fputs(output, stdout);
  return 0;
}
