#include "otis_selected_phase_frequency_preview_engine.h"

#include <stddef.h>
#include <string.h>

namespace {

constexpr uint64_t kReferenceTicksPerSecond = 1000000ull;
constexpr int64_t kNominalEdges = 10000000ll;
constexpr uint64_t kFrequencyOutputCadenceTicks =
    600ull * kReferenceTicksPerSecond;

void reset_frequency(OtisSelectedPhaseFrequencyPreviewEngine *engine) {
  engine->frequency_point_next = 0u;
  engine->frequency_point_count = 0u;
  engine->frequency_estimate_available = false;
  engine->frequency_estimate_timestamp_ticks = 0u;
  engine->frequency_error_hz = 0.0;
}

bool add_frequency_point(OtisSelectedPhaseFrequencyPreviewEngine *engine,
                         uint32_t phase_epoch, uint32_t dac_epoch,
                         int64_t phase, double *frequency) {
  if (engine->frequency_point_count == 0u ||
      engine->frequency_phase_epoch != phase_epoch ||
      engine->frequency_dac_epoch != dac_epoch) {
    reset_frequency(engine);
    engine->frequency_phase_epoch = phase_epoch;
    engine->frequency_dac_epoch = dac_epoch;
  }
  const uint16_t capacity = OTIS_PHASE_FREQUENCY_SUPPORT_INTERVALS + 1u;
  if (engine->frequency_point_count < capacity) {
    engine->frequency_phase_points[engine->frequency_point_next] = phase;
    engine->frequency_point_next =
        static_cast<uint16_t>((engine->frequency_point_next + 1u) % capacity);
    engine->frequency_point_count++;
  } else {
    engine->frequency_phase_points[engine->frequency_point_next] = phase;
    engine->frequency_point_next =
        static_cast<uint16_t>((engine->frequency_point_next + 1u) % capacity);
  }
  if (engine->frequency_point_count != capacity) return false;
  const int64_t first =
      engine->frequency_phase_points[engine->frequency_point_next];
  *frequency = static_cast<double>(phase - first) /
               OTIS_PHASE_FREQUENCY_SUPPORT_INTERVALS;
  return true;
}

}  // namespace

bool otis_selected_phase_frequency_preview_init(
    OtisSelectedPhaseFrequencyPreviewEngine *engine) {
  if (engine == nullptr) return false;
  memset(engine, 0, sizeof(*engine));
  engine->pending_phase_reason = "initial_epoch";
  return true;
}

bool otis_selected_phase_frequency_preview_process(
    OtisSelectedPhaseFrequencyPreviewEngine *engine,
    const OtisSelectedPhaseFrequencyPreviewInput *input,
    OtisSelectedPhaseFrequencyPreviewOutput *output) {
  if (engine == nullptr || input == nullptr || output == nullptr || input->selection == nullptr) return false;
  *output = {};
  const auto &selection = *input->selection;
  using Disposition = OtisReferenceAcceptanceDisposition;
  if (selection.disposition == Disposition::EarlyExcluded ||
      selection.disposition == Disposition::Seeded ||
      selection.disposition == Disposition::Acquiring) return true;
  if (input->reset) {
    engine->have_previous_snapshot = false;
    engine->pending_phase_reason = "reset";
    reset_frequency(engine);
  }
  const bool anchor = selection.disposition == Disposition::TrackingEstablished;
  const bool span = selection.disposition == Disposition::AcceptedSpan && selection.has_span;
  const auto &opening = anchor ? selection.closing : selection.opening;
  const auto &closing = selection.closing;
  bool valid = (anchor || span) && selection.tracking && selection.acceptance_epoch != 0u &&
      opening.capture_session != 0u && opening.capture_session == closing.capture_session &&
      uint32_t(input->monotonic_timestamp_ticks) == closing.reference_timestamp_ticks;
  if (span) {
    valid = valid && selection.counted_edges != 0u &&
        uint32_t(opening.cumulative_down_counter - closing.cumulative_down_counter) == selection.counted_edges &&
        uint32_t(closing.reference_timestamp_ticks - opening.reference_timestamp_ticks) == selection.interval_ticks &&
        uint32_t(closing.snapshot_sequence - opening.snapshot_sequence) == selection.excluded_candidate_count + 1u &&
        uint32_t(closing.reference_sequence - opening.reference_sequence) == selection.excluded_candidate_count + 1u;
    if (engine->have_previous_snapshot) {
      valid = valid && engine->acceptance_epoch == selection.acceptance_epoch &&
          uint32_t(engine->accepted_boundary_ordinal + 1u) == selection.accepted_boundary_ordinal &&
          engine->previous_capture_session == opening.capture_session &&
          engine->previous_snapshot_sequence == opening.snapshot_sequence &&
          engine->previous_reference_sequence == opening.reference_sequence &&
          engine->previous_counter == opening.cumulative_down_counter &&
          engine->previous_reference_ticks == opening.reference_timestamp_ticks &&
          engine->previous_monotonic_timestamp_ticks <= UINT64_MAX - selection.interval_ticks &&
          engine->previous_monotonic_timestamp_ticks + selection.interval_ticks == input->monotonic_timestamp_ticks;
    }
  }
  output->record_available = true;
  output->capture_session = closing.capture_session;
  output->acceptance_epoch = selection.acceptance_epoch;
  output->accepted_boundary_ordinal = selection.accepted_boundary_ordinal;
  output->opening_snapshot_sequence = opening.snapshot_sequence;
  output->closing_snapshot_sequence = closing.snapshot_sequence;
  output->opening_reference_sequence = opening.reference_sequence;
  output->closing_reference_sequence = closing.reference_sequence;
  output->dac_epoch = input->dac_epoch;
  if (!valid) {
    engine->have_previous_snapshot = false;
    engine->pending_phase_reason = "accepted_reference_discontinuity";
    reset_frequency(engine);
    ++engine->observation_sequence;
    output->phase_state = OtisReferenceRelativePhaseState::Invalid;
    output->phase_reason = engine->pending_phase_reason;
  } else {
    if (anchor || !engine->have_previous_snapshot) {
      if (engine->phase_epoch == UINT32_MAX) return false;
      ++engine->phase_epoch;
      engine->observation_sequence = 0u;
      engine->cumulative_phase = 0;
      reset_frequency(engine);
      // Setup may bind after tracking was established. Seed at the exact
      // accepted opening and retain this first span, rather than losing it.
      double unused_frequency = 0.0;
      add_frequency_point(engine, engine->phase_epoch, input->dac_epoch, 0, &unused_frequency);
    }
    if (span) {
      output->edge_error_cycles = int64_t(selection.counted_edges) - kNominalEdges;
      engine->cumulative_phase += output->edge_error_cycles;
      ++engine->observation_sequence;
      output->interval_edges = selection.counted_edges;
      output->interval_available = true;
      output->phase_accepted = true;
      output->phase_state = OtisReferenceRelativePhaseState::Qualified;
      output->phase_reason = "accepted_reference_span";
    } else {
      output->phase_state = OtisReferenceRelativePhaseState::EpochOpen;
      output->phase_reason = "accepted_reference_anchor";
    }
    engine->have_previous_snapshot = true;
    engine->previous_capture_session = closing.capture_session;
    engine->previous_snapshot_sequence = closing.snapshot_sequence;
    engine->previous_reference_sequence = closing.reference_sequence;
    engine->previous_counter = closing.cumulative_down_counter;
    engine->previous_reference_ticks = closing.reference_timestamp_ticks;
    engine->previous_monotonic_timestamp_ticks = input->monotonic_timestamp_ticks;
    engine->acceptance_epoch = selection.acceptance_epoch;
    engine->accepted_boundary_ordinal = selection.accepted_boundary_ordinal;
    if (span) {
      double frequency = 0.0;
      const bool supported = add_frequency_point(engine, engine->phase_epoch,
          input->dac_epoch, engine->cumulative_phase, &frequency);
      if (supported && (!engine->frequency_estimate_available ||
          input->monotonic_timestamp_ticks - engine->frequency_estimate_timestamp_ticks >= kFrequencyOutputCadenceTicks)) {
        engine->frequency_estimate_available = true;
        engine->frequency_estimate_timestamp_ticks = input->monotonic_timestamp_ticks;
        engine->frequency_error_hz = frequency;
        output->frequency_observation_event = true;
      }
    }
  }
  output->phase_epoch = engine->phase_epoch;
  output->observation_sequence = engine->observation_sequence;
  output->relative_phase_cycles = engine->cumulative_phase;
  output->relative_phase_time_ns = engine->cumulative_phase * 100ll;
  output->frequency_available = engine->frequency_estimate_available;
  output->frequency_error_hz = engine->frequency_error_hz;
  output->frequency_estimate_age_ticks = engine->frequency_estimate_available
      ? input->monotonic_timestamp_ticks - engine->frequency_estimate_timestamp_ticks : 0u;
  return true;
}

const char *otis_reference_relative_phase_state_name(
    OtisReferenceRelativePhaseState state) {
  switch (state) {
    case OtisReferenceRelativePhaseState::EpochOpen:
      return "epoch_open";
    case OtisReferenceRelativePhaseState::Qualified:
      return "qualified";
    case OtisReferenceRelativePhaseState::Invalid:
      return "invalid";
  }
  return "invalid";
}
