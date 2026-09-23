#include <assert.h>

// A separate translation unit lets the native integration use the real
// frequency adapter and real active adapter, including their private state.
#include "../../firmware/arduino/otis_nano_rp2040_connect/otis_frequency_regulation_live.cpp"
#include "../../firmware/arduino/otis_nano_rp2040_connect/otis_reference_acceptance_format.h"
#include "../../firmware/arduino/otis_nano_rp2040_connect/otis_reference_acceptance_policy.generated.h"

void publish_accepted_span(const OtisReferenceAcceptanceOutcome &selection) {
  OtisEvidenceFrameMessage frame = {};
  assert(otis_reference_acceptance_format_span(
      selection, OTIS_REFERENCE_ACCEPTANCE_POLICY_SHA256, frame.data,
      sizeof(frame.data), &frame.length));
  assert(otis_dual_core_publish_evidence(&frame));
}

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
  estimator.selected_count = OTIS_FREQUENCY_ESTIMATOR_SPAN_INTERVALS - 1u;
  estimator.selected_sum =
      static_cast<uint64_t>(OTIS_FREQUENCY_ESTIMATOR_SPAN_INTERVALS - 1u) * 10000000u;
  estimator.selected_first_sequence = 700u;
  estimator.selected_first_reference_sequence = 1700u;
  estimator.selected_opening_accepted_boundary_ordinal = 700u;
  estimator.diagnostic_count = OTIS_REGULATION_DIAGNOSTIC_SPAN_INTERVALS;
  estimator.diagnostic_sum =
      static_cast<uint64_t>(OTIS_REGULATION_DIAGNOSTIC_SPAN_INTERVALS) * 10000000u;
  for (auto &count : estimator.diagnostic_counts) count = 10000000u;
}

void produce_delayed_selected_response(
    uint64_t captured_ticks, uint64_t operational_ticks,
    OtisAdaptiveHybridRegulationLiveOutcome *outcome) {
  OtisReferenceAcceptanceOutcome selection = {};
  selection.disposition = OtisReferenceAcceptanceDisposition::AcceptedSpan;
  selection.tracking = selection.has_span = true;
  selection.acceptance_epoch = 3u;
  selection.accepted_boundary_ordinal = 1300u;
  selection.interval_ticks = 1000000u;
  selection.counted_edges = 10000000u;
  selection.opening = {7u, 1299u, 2299u, uint32_t(captured_ticks - 1000000u), 10000000u, 0u, 16u};
  selection.closing = {7u, 1300u, 2300u, uint32_t(captured_ticks), 0u, 0u, 16u};
  const OtisRegulationStaticCodeState code = {true, true, true, 43086u};
  // Match the Core-1 boundary order: APS is durably published before either
  // dependent preview/decision consumer observes this selection.
  publish_accepted_span(selection);
  otis_frequency_regulation_live_on_reference_selection(
      &selection, captured_ticks, 5000u,
      operational_ticks,
      &code, outcome);
}
