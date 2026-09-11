#include "otis_active_hybrid_decision_types.h"

const char *otis_active_hybrid_state_name(OtisActiveHybridState state) {
  switch (state) {
    case OtisActiveHybridState::FrequencyAcquire:
      return "FREQUENCY_ACQUIRE";
    case OtisActiveHybridState::PhaseQualify:
      return "PHASE_QUALIFY";
    case OtisActiveHybridState::FirstPhaseTransaction:
      return "FIRST_PHASE_TRANSACTION";
    case OtisActiveHybridState::HybridTracking:
      return "HYBRID_TRACKING";
    case OtisActiveHybridState::PhaseDegradedFrequencyOnly:
      return "PHASE_DEGRADED_FREQUENCY_ONLY";
    case OtisActiveHybridState::FailStatic:
      return "FAIL_STATIC";
  }
  return "FAIL_STATIC";
}
