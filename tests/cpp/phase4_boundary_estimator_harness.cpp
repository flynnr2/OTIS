#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "otis_phase4_boundary_estimator.h"

namespace {

std::vector<std::string> split(const std::string &line) {
  std::vector<std::string> fields;
  std::stringstream stream(line);
  std::string field;
  while (std::getline(stream, field, ',')) fields.push_back(field);
  return fields;
}

}  // namespace

int main() {
  OtisPhase4BoundaryEstimator estimator;
  otis_phase4_boundary_estimator_init(&estimator);
  std::string line;
  while (std::getline(std::cin, line)) {
    const std::vector<std::string> fields = split(line);
    if (fields.empty()) continue;
    if (fields[0] == "REF" && fields.size() == 5u) {
      otis_phase4_boundary_estimator_on_reference(
          &estimator, (uint32_t)std::stoul(fields[1]),
          std::stoull(fields[2]), (uint32_t)std::stoul(fields[3]), 4143u,
          800000u, 1200000u, std::stod(fields[4]));
      continue;
    }
    if (fields[0] == "GATE" && fields.size() == 4u) {
      const OtisPhase4BoundaryResult result =
          otis_phase4_boundary_estimator_estimate(
              &estimator, std::stoull(fields[1]), std::stoull(fields[2]),
              std::stoull(fields[3]), 1000000.0, 1.2);
      std::cout << (result.valid ? "true" : "false") << ','
                << otis_phase4_boundary_reason_name(result.reason) << ','
                << (result.retryable_after_next_reference ? "true" : "false")
                << ',' << std::setprecision(15);
      if (result.valid) {
        std::cout << result.gate_seconds << ',' << result.frequency_hz << ','
                  << result.before_open_seq << ',' << result.after_open_seq
                  << ',' << result.before_close_seq << ','
                  << result.after_close_seq << ',' << result.support_count;
      } else {
        std::cout << ",,,,,,";
      }
      std::cout << '\n';
      continue;
    }
    return 2;
  }
  return 0;
}
