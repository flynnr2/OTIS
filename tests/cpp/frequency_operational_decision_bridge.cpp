#include <assert.h>

// A separate translation unit lets the native integration use the real
// frequency adapter and real active adapter, including their private state.
#include "../../firmware/arduino/otis_nano_rp2040_connect/otis_frequency_regulation_live.cpp"

void prepare_delayed_selected_response(uint64_t captured_ticks) {
  assert(otis_frequency_regulation_live_begin(0u));
  controller.state = OtisFrequencyRegulationState::Qualifying;
  controller.inhibit_until_s = 0u;
  current_dac_epoch = 2u;
  current_applied_code = 43086u;
  warmup_boundary_seen = true;
  settling_until_s = 0u;
  exact_settling_deadline_available = false;
  assert(otis_monotonic_us_extension_seed(
      &timer_extension, captured_ticks - 1000000u, 7u));
  previous_boundary_available = true;
  previous_boundary_session = 7u;
  previous_boundary_extended_ticks = captured_ticks - 1000000u;
  estimator.selected_count = OTIS_FREQUENCY_ESTIMATOR_SPAN_INTERVALS - 1u;
  estimator.selected_sum =
      static_cast<uint64_t>(OTIS_FREQUENCY_ESTIMATOR_SPAN_INTERVALS - 1u) * 10000000u;
  estimator.selected_first_sequence = 700u;
  estimator.diagnostic_count = OTIS_REGULATION_DIAGNOSTIC_SPAN_INTERVALS;
  estimator.diagnostic_sum =
      static_cast<uint64_t>(OTIS_REGULATION_DIAGNOSTIC_SPAN_INTERVALS) * 10000000u;
  for (auto &count : estimator.diagnostic_counts) count = 10000000u;
}

void produce_delayed_selected_response(
    uint64_t captured_ticks, uint64_t operational_ticks,
    OtisAdaptiveHybridRegulationLiveOutcome *outcome) {
  const OtisPpsCountBoundaryObservation boundary = {
      7u, 1300u, 2300u,
      captured_ticks % OTIS_RP2040_MONOTONIC_US32_MODULUS,
      0u, 10000000u, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED, 0u,
  };
  const OtisRegulationStaticCodeState code = {true, true, true, 43086u};
  otis_frequency_regulation_live_on_boundary(
      &boundary, 10000000u, true, 5000u,
      operational_ticks % OTIS_RP2040_MONOTONIC_US32_MODULUS,
      &code, outcome);
}
