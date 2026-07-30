#include <iostream>

#include "otis_diagnostic_engine.h"

int main() {
  OtisDiagnosticState state;
  otis_diagnostic_state_init(&state);
  const OtisDiagnosticRule rule = {2u, 2u, 2u};
  const bool active[] = {true, true, true, false, false};
  for (uint32_t index = 0u; index < 5u; ++index) {
    const OtisDiagnosticResult result = otis_diagnostic_observe(
        &state, &rule, active[index], (uint64_t)(index + 1u) * 10u,
        index + 1u, ("fixture:REF:" + std::to_string(index + 1u)).c_str());
    if (result.transition == OTIS_DIAGNOSTIC_NO_TRANSITION) continue;
    std::cout << otis_diagnostic_transition_name(result.transition) << ","
              << result.episode << "," << result.occurrence_count << ","
              << result.first_seen_ticks << "," << result.last_seen_ticks
              << "\n";
  }
  return 0;
}
