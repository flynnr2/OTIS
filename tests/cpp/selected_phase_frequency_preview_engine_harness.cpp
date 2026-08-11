#include <iomanip>
#include <iostream>

#include "otis_selected_phase_frequency_preview_engine.h"

int main() {
  uint16_t start_code = 0u;
  if (!(std::cin >> start_code)) return 2;
  OtisSelectedPhaseFrequencyPreviewEngine engine;
  if (!otis_selected_phase_frequency_preview_init(&engine, start_code)) return 3;

  std::cout
      << "phase_epoch,observation_sequence,dac_epoch,phase_state,phase_reason,"
         "capture_session,opening_snapshot_sequence,closing_snapshot_sequence,"
         "opening_reference_sequence,closing_reference_sequence,"
         "phase_accepted,interval_available,interval_edges,edge_error_cycles,"
         "relative_phase_cycles,relative_phase_time_ns,frequency_available,"
         "raw_frequency_available,raw_frequency_error_hz,"
         "observed_frequency_error_hz,modeled_relative_phase_cycles,"
         "modeled_frequency_error_hz,frequency_term_hz,phase_bias_hz,"
         "combined_desired_frequency_change_hz,shadow_code_before,"
         "shadow_code_after,actual_applied_code,band_state_before,band_state_after,preview_state,"
         "decision_reason,frequency_observation_event,counterfactual_decision,"
         "counterfactual_correction,raw_delta_available,raw_delta_codes,"
         "limited_delta_codes,step_limited,range_clamped,correction_count,"
         "cumulative_movement_codes,alternating_correction_count,"
         "modeled_not_observed_after_divergence\n";

  OtisSelectedPhaseFrequencyPreviewInput input;
  unsigned counted_available = 0u;
  unsigned reference_qualified = 0u;
  unsigned reset = 0u;
  unsigned phase_step = 0u;
  while (std::cin >> input.capture_session >> input.snapshot_sequence >>
         input.cumulative_down_counter >> input.reference_sequence >>
         input.reference_timestamp_ticks >> input.snapshot_status >>
         input.counted_edges >> input.dac_epoch >> input.timestamp_s >>
         input.actual_applied_code >> counted_available >> reference_qualified >>
         reset >> phase_step) {
    input.counted_edges_available = counted_available != 0u;
    input.reference_qualified = reference_qualified != 0u;
    input.reset = reset != 0u;
    input.phase_step_detected = phase_step != 0u;
    OtisSelectedPhaseFrequencyPreviewOutput output;
    if (!otis_selected_phase_frequency_preview_process(&engine, &input, &output)) return 4;
    std::cout << output.phase_epoch << ',' << output.observation_sequence << ','
              << output.dac_epoch << ','
              << otis_reference_relative_phase_state_name(output.phase_state) << ','
              << (output.phase_reason == nullptr ? "" : output.phase_reason)
              << ',' << output.capture_session << ','
              << output.opening_snapshot_sequence << ','
              << output.closing_snapshot_sequence << ','
              << output.opening_reference_sequence << ','
              << output.closing_reference_sequence
              << ',' << output.phase_accepted << ',' << output.interval_available
              << ',' << output.interval_edges << ',' << output.edge_error_cycles
              << ',' << output.relative_phase_cycles << ','
              << output.relative_phase_time_ns << ',' << output.frequency_available
              << ',' << output.raw_frequency_available << ','
              << std::setprecision(17) << output.raw_frequency_error_hz << ','
              << output.observed_frequency_error_hz << ','
              << output.modeled_relative_phase_cycles << ','
              << output.modeled_frequency_error_hz << ','
              << output.frequency_term_hz << ',' << output.phase_bias_hz << ','
              << output.combined_desired_frequency_change_hz << ','
              << output.shadow_code_before << ',' << output.shadow_code_after
              << ',' << output.actual_applied_code << ','
              << output.band_state_before << ',' << output.band_state_after
              << ',' << output.preview_state << ',' << output.decision_reason
              << ',' << output.frequency_observation_event << ','
              << output.counterfactual_decision << ','
              << output.counterfactual_correction << ','
              << output.raw_delta_available << ',' << output.raw_delta_codes
              << ',' << output.limited_delta_codes << ',' << output.step_limited
              << ',' << output.range_clamped << ',' << output.correction_count
              << ',' << output.cumulative_movement_codes << ','
              << output.alternating_correction_count << ','
              << output.modeled_not_observed_after_divergence << '\n';
  }
  return 0;
}
