#include <cstring>
#include <iostream>
#include <string>

#include "otis_cx318_preview_format.h"

int main(int argc, char **argv) {
  if (argc != 2) return 2;
  OtisCx318PreviewRecordMessage message = {};
  message.preview_sequence = 600u;
  message.decision_timestamp_ticks = 9600000000ull;
  message.phase_epoch = 1u;
  message.observation_sequence = 600u;
  message.capture_session = 7u;
  message.opening_snapshot_sequence = 600u;
  message.closing_snapshot_sequence = 601u;
  message.opening_reference_sequence = 1600u;
  message.closing_reference_sequence = 1601u;
  message.dac_epoch = 0u;
  message.interval_edges = 10000001u;
  message.edge_error_cycles = 1;
  message.relative_phase_cycles = 24;
  message.relative_phase_time_ns = 2400;
  message.raw_frequency_error_hz = 1.0 / 600.0;
  message.observed_frequency_error_hz = 1.0 / 600.0;
  message.frequency_estimate_age_s = 17.0;
  message.modeled_relative_phase_cycles = 23.75;
  message.modeled_frequency_error_hz = 1.0 / 600.0;
  message.frequency_term_hz = -1.0 / 600.0;
  message.phase_bias_hz = -24.0 / 21600.0;
  message.combined_frequency_error_hz =
      message.frequency_term_hz + message.phase_bias_hz;
  message.raw_counterfactual_delta_codes = -2.25;
  message.counterfactual_delta_codes = -2;
  message.actual_applied_code = 43344u;
  message.shadow_code_before = 43344u;
  message.shadow_code_after = 43342u;
  message.correction_count = 1u;
  message.cumulative_movement_codes = 2u;
  message.alternating_correction_count = 0u;
  message.phase_accepted = true;
  message.interval_available = true;
  message.raw_frequency_available = true;
  message.modeled_frequency_available = true;
  message.frequency_observation_event = true;
  message.counterfactual_decision = true;
  message.counterfactual_correction = true;
  message.raw_counterfactual_delta_available = true;
  message.modeled_not_observed_after_divergence = true;
  std::strcpy(message.phase_qualification_state, "qualified");
  std::strcpy(message.band_state_before, "INSIDE");
  std::strcpy(message.band_state_after, "INSIDE");
  std::strcpy(message.preview_state, "HYBRID_TRACKING_PREVIEW");
  std::strcpy(message.decision_reason, "counterfactual_correction_modeled");

  char output[2048] = {};
  size_t length = 0u;
  const std::string kind(argv[1]);
  const char *header = nullptr;
  bool formatted = false;
  if (kind == "rph") {
    header = otis_cx318_rph_header();
    formatted = otis_cx318_format_rph(&message, output, sizeof(output), &length);
  } else if (kind == "phe") {
    header = otis_cx318_phe_header();
    formatted = otis_cx318_format_phe(&message, output, sizeof(output), &length);
  } else if (kind == "phe_retained") {
    message.frequency_observation_event = false;
    header = otis_cx318_phe_header();
    formatted = otis_cx318_format_phe(&message, output, sizeof(output), &length);
  } else if (kind == "hpr") {
    header = otis_cx318_hpr_header();
    formatted = otis_cx318_format_hpr(&message, output, sizeof(output), &length);
  } else {
    return 3;
  }
  if (!formatted || header == nullptr || length == 0u) return 4;
  std::cout << header << output;
  return 0;
}
