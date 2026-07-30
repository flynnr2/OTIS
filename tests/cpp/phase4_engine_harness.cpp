#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "otis_phase4_engine.h"

namespace {

std::vector<std::string> split(const std::string &line) {
  std::vector<std::string> fields;
  std::stringstream stream(line);
  std::string field;
  while (std::getline(stream, field, ',')) fields.push_back(field);
  return fields;
}

bool boolean(const std::string &value) {
  return value == "1" || value == "true";
}

}  // namespace

int main() {
  std::string line;
  if (!std::getline(std::cin, line)) return 2;
  std::vector<std::string> config_fields = split(line);
  if (config_fields.size() != 8u || config_fields[0] != "CONFIG") return 3;
  OtisPhase4EngineConfig config = {
      std::stod(config_fields[1]),
      (uint8_t)std::stoul(config_fields[2]),
      (uint8_t)std::stoul(config_fields[3]),
      (uint8_t)std::stoul(config_fields[4]),
      (uint8_t)std::stoul(config_fields[5]),
      std::stod(config_fields[6]),
      std::stod(config_fields[7]),
  };
  OtisPhase4Engine engine;
  otis_phase4_engine_init(&engine, &config);

  std::cout
      << "state,previous,transition,confidence,samples,estimate_eligible,"
         "preview_eligible,preview_available,proposed,limited,step_limited,"
         "range_clamped,eligibility_mask,model_mask,error_hz,dispersion_hz\n";
  while (std::getline(std::cin, line)) {
    if (line.empty()) continue;
    std::vector<std::string> f = split(line);
    if (f.size() != 25u || f[0] != "OBS") return 4;
    OtisPhase4Observation observation = {};
    observation.timestamp_ticks = std::stoull(f[1]);
    observation.elapsed_s = std::stod(f[2]);
    observation.new_count = boolean(f[3]);
    observation.reference_validity =
        (OtisPhase4Validity)std::stoul(f[4]);
    observation.count_validity = (OtisPhase4Validity)std::stoul(f[5]);
    observation.reference_continuity = boolean(f[6]);
    observation.count_continuity = boolean(f[7]);
    observation.diagnostic_health =
        (OtisPhase4DiagnosticHealth)std::stoul(f[8]);
    observation.observation_reason_mask = std::stoul(f[9]);
    observation.frequency_observation_available = boolean(f[10]);
    observation.frequency_observation_hz = std::stod(f[11]);
    observation.model.available = boolean(f[12]);
    observation.model.valid = boolean(f[13]);
    observation.model.version_4 = boolean(f[14]);
    observation.model.topology_match = boolean(f[15]);
    observation.model.backend_match = boolean(f[16]);
    observation.model.estimator_method_match = boolean(f[17]);
    observation.model.input_in_applicability = boolean(f[18]);
    observation.model.excluded_input = boolean(f[19]);
    observation.model.gain_available = boolean(f[20]);
    observation.model.hz_per_code = std::stod(f[21]);
    observation.model.dac_available = boolean(f[22]);
    observation.model.current_dac_code =
        (uint16_t)std::stoul(f[23]);
    observation.reference_authority_qualified = boolean(f[24]);
    observation.model.candidate_min_code = 0xA800u;
    observation.model.candidate_max_code = 0xAB00u;
    observation.model.maximum_preview_step_codes = 0x0300u;

    OtisPhase4Decision decision;
    otis_phase4_engine_evaluate(&engine, &observation, &decision);
    std::cout << otis_phase4_state_name(decision.state) << ','
              << otis_phase4_state_name(decision.previous_state) << ','
              << otis_phase4_transition_reason_name(
                     decision.transition_reason)
              << ',' << otis_phase4_confidence_name(decision.confidence) << ','
              << (unsigned)decision.accepted_sample_count << ','
              << (decision.estimator_eligible ? "true" : "false") << ','
              << (decision.preview_eligible ? "true" : "false") << ','
              << (decision.preview_available ? "true" : "false") << ',';
    if (decision.preview_available) {
      std::cout << decision.proposed_dac_code << ','
                << decision.limited_delta_codes;
    } else {
      std::cout << ',';
    }
    std::cout << ',' << (decision.step_limited ? "true" : "false") << ','
              << (decision.range_clamped ? "true" : "false") << ','
              << decision.eligibility_reason_mask << ','
              << decision.model_reason_mask << ',' << std::setprecision(15);
    if (decision.estimate_available)
      std::cout << decision.frequency_error_hz << ','
                << decision.dispersion_hz;
    else
      std::cout << ',';
    std::cout << '\n';
  }
  return 0;
}
