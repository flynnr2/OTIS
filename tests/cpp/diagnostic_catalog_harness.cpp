#include <iostream>
#include <string>

#include "otis_diagnostic_catalog.h"
#include "otis_diagnostic_engine.h"

int main() {
  OtisDiagnosticState states[OTIS_DIAG_COUNT];
  for (uint8_t index = 0u; index < OTIS_DIAG_COUNT; ++index)
    otis_diagnostic_state_init(&states[index]);

  const uint16_t masks[] = {
      (1u << OTIS_DIAG_REFERENCE_AUTHORITY) |
          (1u << OTIS_DIAG_APERTURE_UNQUALIFIED) |
          (1u << OTIS_DIAG_MODEL),
      (1u << OTIS_DIAG_REFERENCE_AUTHORITY) |
          (1u << OTIS_DIAG_APERTURE_UNQUALIFIED) |
          (1u << OTIS_DIAG_MODEL),
      (1u << OTIS_DIAG_APERTURE_UNQUALIFIED),
      (1u << OTIS_DIAG_APERTURE_UNQUALIFIED) |
          (1u << OTIS_DIAG_SEQUENCE) | (1u << OTIS_DIAG_COUNT_WINDOW),
      (1u << OTIS_DIAG_APERTURE_UNQUALIFIED),
      (1u << OTIS_DIAG_APERTURE_UNQUALIFIED),
      (1u << OTIS_DIAG_APERTURE_UNQUALIFIED),
      0u,
  };
  uint32_t output_seq = 0u;
  for (uint32_t event = 0u; event < 8u; ++event) {
    const std::string refs =
        "fixture:REF:" + std::to_string(event + 1u) +
        ";fixture:CNT:" + std::to_string(event + 1u) +
        ";unavailable:fixture:STS";
    for (uint8_t index = 0u; index < OTIS_DIAG_COUNT; ++index) {
      const OtisDiagnosticDefinition &definition =
          kOtisDiagnosticDefinitions[index];
      const OtisDiagnosticResult result = otis_diagnostic_observe(
          &states[index], &definition.rule, (masks[event] & (1u << index)) != 0,
          (uint64_t)(event + 1u) * 100u, event + 1u, refs.c_str());
      if (result.transition == OTIS_DIAGNOSTIC_NO_TRANSITION) continue;
      const bool cleared = result.transition == OTIS_DIAGNOSTIC_CLEARED;
      std::cout
          << ++output_seq << "," << definition.diagnostic_id << ","
          << result.episode << "," << definition.subsystem << ","
          << definition.severity << "," << (cleared ? "cleared" : "active")
          << "," << otis_diagnostic_transition_name(result.transition)
          << ",1," << definition.reason << ","
          << (cleared ? definition.clear_reason : "") << ","
          << result.first_seen_ticks << "," << result.last_seen_ticks << ","
          << result.occurrence_count << "," << result.first_evidence_refs
          << "," << result.latest_evidence_refs << ","
          << kOtisDiagnosticAlgorithmVersion << ","
          << kOtisDiagnosticConfigHash << "," << definition.observation_effect
          << "," << definition.reference_effect << ","
          << definition.model_effect << "," << definition.control_effect
          << "\n";
    }
  }
  return 0;
}
