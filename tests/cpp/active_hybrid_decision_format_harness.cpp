#include <stdio.h>

#include "otis_active_hybrid_decision_format.h"
#include "otis_active_hybrid_policy_engine.h"
#include "otis_adaptive_hybrid_regulation_live.h"

int main() {
  const OtisAdaptiveHybridRegulationLiveDecision source = {
      1u, 1799u, 2399u, 5000u, 43068u, 0, 43068u, 0.00166666694,
      true, true, true, true, 1u, 1, "OUTSIDE", 1u, 1u, 2394u, 4,
      1u, 43068u, true, true, false, true,
  };
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
      "frequency_estimator_sha256",
      "phase_estimator_sha256",
      "ARMED",
      0u,
      0u,
      0u,
      "unavailable",
      true,
      "active_policy_sha256",
      "response_policy_sha256",
      false,
  };
  char output[1536] = "";
  const int used = otis_format_active_hybrid_decision_v2(
      output, sizeof(output), &source, &decision, &context);
  if (used <= 0 || static_cast<size_t>(used) >= sizeof(output)) return 1;
  fputs(output, stdout);
  return 0;
}
