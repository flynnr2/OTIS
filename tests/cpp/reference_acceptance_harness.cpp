// Native trace adapter only: policy values are supplied from the JSON contract.
// Arguments: nominal tolerance acquisition max_edge_rate allowed_flags max_excluded max_count_span.
// stdin: O session snp_sequence d14_sequence us32 downcounter status flags
//        E now_us32 session last_snp_sequence last_d14_sequence drained_us32 complete
// All output is derived JSONL; this executable has no firmware I/O or authority.
#include "otis_reference_acceptance.h"

#include <cassert>
#include <cstring>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

static uint32_t number(const std::string &text) {
  if (text.empty() || text[0] == '-') throw std::invalid_argument("unsigned integer required");
  size_t consumed = 0;
  const unsigned long long value = std::stoull(text, &consumed, 10);
  if (consumed != text.size() || value > UINT32_MAX) throw std::invalid_argument("uint32 required");
  return uint32_t(value);
}

static uint32_t read_number(std::istringstream &line) {
  std::string text;
  if (!(line >> text)) throw std::invalid_argument("missing field");
  return number(text);
}

static void endpoint(const OtisReferenceAcceptanceObservation &value) {
  std::cout << "{\"session\":" << value.capture_session
            << ",\"snapshot_sequence\":" << value.snapshot_sequence
            << ",\"reference_sequence\":" << value.reference_sequence
            << ",\"ticks\":" << value.reference_timestamp_ticks
            << ",\"down_counter\":" << value.cumulative_down_counter
            << ",\"status\":" << value.snapshot_status
            << ",\"flags\":" << value.reference_flags << "}";
}

static void emit(const OtisReferenceAcceptanceOutcome &value) {
  const char *dispositions[] = {"seeded", "acquiring", "tracking_established", "early_excluded",
      "accepted_span", "qualification_lost", "expiry_pending", "frontier_rejected", "not_tracking", "invalid_policy"};
  const char *reasons[] = {"none", "acquisition_restart", "unknown_session", "session_changed",
      "capture_integrity", "raw_sequence", "raw_timestamp", "raw_count", "late_boundary", "missing_boundary",
      "incomplete_frontier", "stale_frontier", "contradictory_frontier", "exclusion_budget_exhausted",
      "epoch_exhausted", "policy"};
  std::cout << "{\"disposition\":\"" << dispositions[unsigned(value.disposition)]
            << "\",\"reason\":\"" << reasons[unsigned(value.reason)]
            << "\",\"tracking\":" << (value.tracking ? "true" : "false")
            << ",\"has_span\":" << (value.has_span ? "true" : "false")
            << ",\"acquisition_progress\":" << value.acquisition_progress
            << ",\"acceptance_epoch\":" << value.acceptance_epoch
            << ",\"accepted_boundary_ordinal\":" << value.accepted_boundary_ordinal
            << ",\"expiry_ticks\":" << value.expiry_timestamp_ticks
            << ",\"interval_ticks\":" << value.interval_ticks
            << ",\"counted_edges\":" << value.counted_edges
            << ",\"excluded_candidate_count\":" << value.excluded_candidate_count
            << ",\"candidate\":";
  endpoint(value.candidate);
  std::cout << ",\"opening\":";
  endpoint(value.opening);
  std::cout << ",\"closing\":";
  endpoint(value.closing);
  std::cout << "}\n";
}

int main(int argc, char **argv) {
  try {
    if (argc != 8) throw std::invalid_argument("seven frozen policy arguments required");
    const OtisReferenceAcceptancePolicy policy = {
        number(argv[1]), number(argv[2]), number(argv[3]),
        number(argv[4]), number(argv[5]), number(argv[6]), number(argv[7])};
    OtisReferenceAcceptance selector(policy);
    std::vector<OtisReferenceAcceptanceOutcome> retained;
    std::string text;
    while (std::getline(std::cin, text)) {
      if (text.empty() || text[0] == '#') continue;
      std::istringstream line(text);
      char tag;
      line >> tag;
      if (tag == 'O') {
        OtisReferenceAcceptanceObservation observation = {};
        observation.capture_session = read_number(line);
        observation.snapshot_sequence = read_number(line);
        observation.reference_sequence = read_number(line);
        observation.reference_timestamp_ticks = read_number(line);
        observation.cumulative_down_counter = read_number(line);
        observation.snapshot_status = read_number(line);
        observation.reference_flags = read_number(line);
        const auto original = observation;
        retained.push_back(selector.observe(observation));
        assert(std::memcmp(&observation, &original, sizeof(observation)) == 0);
      } else if (tag == 'E') {
        const uint32_t now = read_number(line);
        OtisReferenceAcceptanceDrainFrontier frontier = {};
        frontier.capture_session = read_number(line);
        frontier.snapshot_sequence = read_number(line);
        frontier.reference_sequence = read_number(line);
        frontier.drained_through_ticks = read_number(line);
        const uint32_t complete = read_number(line);
        if (complete > 1u) throw std::invalid_argument("complete must be 0 or 1");
        frontier.complete = complete != 0u;
        retained.push_back(selector.expire(now, frontier));
      } else {
        throw std::invalid_argument("unknown trace operation");
      }
      std::string extra;
      if (line >> extra) throw std::invalid_argument("extra trace field");
    }
    // Serialize retained values only after subsequent observations and losses;
    // earlier results must remain unchanged by later state transitions.
    for (const auto &value : retained) emit(value);
    return 0;
  } catch (const std::exception &error) {
    std::cerr << error.what() << "\n";
    return 2;
  }
}
