#include "otis_oscillator_snapshot_estimator.h"

#include <string.h>

void otis_oscillator_snapshot_estimator_init(OtisOscillatorSnapshotEstimator *estimator) {
  otis_oscillator_snapshot_estimator_reset(estimator);
}

void otis_oscillator_snapshot_estimator_reset(OtisOscillatorSnapshotEstimator *estimator) {
  if (estimator != nullptr) memset(estimator, 0, sizeof(*estimator));
}

void otis_oscillator_snapshot_estimator_ingest(
    OtisOscillatorSnapshotEstimator *estimator,
    const OtisReferenceAcceptanceOutcome *selection,
    OtisRegulationSpanEstimate *output) {
  if (estimator == nullptr || selection == nullptr || output == nullptr) return;
  *output = {};
  using Disposition = OtisReferenceAcceptanceDisposition;
  if (selection->disposition == Disposition::EarlyExcluded ||
      selection->disposition == Disposition::Seeded ||
      selection->disposition == Disposition::Acquiring) return;
  if (selection->disposition == Disposition::TrackingEstablished) {
    otis_oscillator_snapshot_estimator_reset(estimator);
    estimator->have_previous = true;
    estimator->previous = selection->closing;
    estimator->acceptance_epoch = selection->acceptance_epoch;
    estimator->accepted_boundary_ordinal = selection->accepted_boundary_ordinal;
    return;
  }
  const auto &opening = selection->opening;
  const auto &closing = selection->closing;
  bool valid = selection->has_span && selection->tracking &&
      selection->disposition == Disposition::AcceptedSpan &&
      selection->acceptance_epoch != 0u && opening.capture_session != 0u &&
      opening.capture_session == closing.capture_session && selection->counted_edges != 0u &&
      uint32_t(opening.cumulative_down_counter - closing.cumulative_down_counter) == selection->counted_edges &&
      uint32_t(closing.snapshot_sequence - opening.snapshot_sequence) == selection->excluded_candidate_count + 1u &&
      uint32_t(closing.reference_sequence - opening.reference_sequence) == selection->excluded_candidate_count + 1u;
  if (estimator->have_previous) {
    const auto &previous = estimator->previous;
    valid = valid && estimator->acceptance_epoch == selection->acceptance_epoch &&
        uint32_t(estimator->accepted_boundary_ordinal + 1u) == selection->accepted_boundary_ordinal &&
        previous.capture_session == opening.capture_session &&
        previous.snapshot_sequence == opening.snapshot_sequence &&
        previous.reference_sequence == opening.reference_sequence &&
        previous.reference_timestamp_ticks == opening.reference_timestamp_ticks &&
        previous.cumulative_down_counter == opening.cumulative_down_counter;
  }
  if (!valid) {
    otis_oscillator_snapshot_estimator_reset(estimator);
    return;
  }
  estimator->have_previous = true;
  estimator->previous = closing;
  estimator->acceptance_epoch = selection->acceptance_epoch;
  estimator->accepted_boundary_ordinal = selection->accepted_boundary_ordinal;
  output->source_continuous = true;
  output->last_sequence = closing.snapshot_sequence;
  output->last_reference_sequence = closing.reference_sequence;
  output->capture_session = closing.capture_session;
  output->acceptance_epoch = selection->acceptance_epoch;
  output->closing_accepted_boundary_ordinal = selection->accepted_boundary_ordinal;
  const uint32_t interval_count = selection->counted_edges;
  const uint16_t position = estimator->diagnostic_next;
  if (estimator->diagnostic_count == OTIS_REGULATION_DIAGNOSTIC_SPAN_INTERVALS)
    estimator->diagnostic_sum -= estimator->diagnostic_counts[position];
  else
    ++estimator->diagnostic_count;
  estimator->diagnostic_counts[position] = interval_count;
  estimator->diagnostic_opening_snapshots[position] = opening.snapshot_sequence;
  estimator->diagnostic_opening_references[position] = opening.reference_sequence;
  estimator->diagnostic_sum += interval_count;
  estimator->diagnostic_next = uint16_t((position + 1u) % OTIS_REGULATION_DIAGNOSTIC_SPAN_INTERVALS);
  if (estimator->diagnostic_count == OTIS_REGULATION_DIAGNOSTIC_SPAN_INTERVALS) {
    output->diagnostic_available = true;
    output->diagnostic_frequency_hz = double(estimator->diagnostic_sum) / OTIS_REGULATION_DIAGNOSTIC_SPAN_INTERVALS;
    output->diagnostic_first_sequence = estimator->diagnostic_opening_snapshots[estimator->diagnostic_next];
    output->diagnostic_first_reference_sequence = estimator->diagnostic_opening_references[estimator->diagnostic_next];
    output->diagnostic_opening_accepted_boundary_ordinal = selection->accepted_boundary_ordinal - OTIS_REGULATION_DIAGNOSTIC_SPAN_INTERVALS;
  }
  if (estimator->selected_count == 0u) {
    estimator->selected_first_sequence = opening.snapshot_sequence;
    estimator->selected_first_reference_sequence = opening.reference_sequence;
    estimator->selected_opening_accepted_boundary_ordinal = selection->accepted_boundary_ordinal - 1u;
  }
  estimator->selected_sum += interval_count;
  ++estimator->selected_count;
  if (estimator->selected_count == OTIS_FREQUENCY_ESTIMATOR_SPAN_INTERVALS) {
    output->selected_available = true;
    output->selected_frequency_hz = double(estimator->selected_sum) / OTIS_FREQUENCY_ESTIMATOR_SPAN_INTERVALS;
    output->selected_accumulated_edge_error_counts = int64_t(estimator->selected_sum) - int64_t(OTIS_FREQUENCY_ESTIMATOR_SPAN_INTERVALS) * 10000000ll;
    output->selected_first_sequence = estimator->selected_first_sequence;
    output->selected_first_reference_sequence = estimator->selected_first_reference_sequence;
    output->selected_opening_accepted_boundary_ordinal = estimator->selected_opening_accepted_boundary_ordinal;
    estimator->selected_sum = 0u;
    estimator->selected_count = 0u;
  }
}
