#include "otis_selected_phase_frequency_preview_engine.h"

#include <stddef.h>
#include <string.h>

namespace {

constexpr uint64_t kReferenceTicksPerSecond = 1000000ull;
constexpr uint64_t kReferenceTimestampModulus = 1ull << 32;
constexpr uint64_t kMinimumReferenceTicks = 800000ull;
constexpr uint64_t kMaximumReferenceTicks = 1200000ull;
constexpr uint64_t kCounterModulus = 1ull << 32;
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

void populate_output(
    const OtisSelectedPhaseFrequencyPreviewEngine *engine,
    OtisSelectedPhaseFrequencyPreviewOutput *output, uint32_t dac_epoch,
    OtisReferenceRelativePhaseState phase_state, const char *phase_reason,
    bool phase_accepted, bool interval_available, uint32_t interval_edges,
    int64_t edge_error, uint32_t capture_session,
    uint32_t opening_snapshot_sequence, uint32_t closing_snapshot_sequence,
    uint32_t opening_reference_sequence, uint32_t closing_reference_sequence) {
  *output = {};
  output->phase_epoch = engine->phase_epoch;
  output->observation_sequence = engine->observation_sequence;
  output->capture_session = capture_session;
  output->opening_snapshot_sequence = opening_snapshot_sequence;
  output->closing_snapshot_sequence = closing_snapshot_sequence;
  output->opening_reference_sequence = opening_reference_sequence;
  output->closing_reference_sequence = closing_reference_sequence;
  output->dac_epoch = dac_epoch;
  output->interval_edges = interval_edges;
  output->edge_error_cycles = edge_error;
  output->relative_phase_cycles = engine->cumulative_phase;
  output->relative_phase_time_ns = engine->cumulative_phase * 100ll;
  output->phase_state = phase_state;
  output->phase_reason = phase_reason;
  output->phase_accepted = phase_accepted;
  output->interval_available = interval_available;
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
  if (engine == nullptr || input == nullptr || output == nullptr) return false;

  OtisReferenceRelativePhaseState phase_state =
      OtisReferenceRelativePhaseState::Invalid;
  const char *phase_reason = nullptr;
  bool accepted = false;
  bool interval_available = false;
  uint32_t interval_edges = 0u;
  int64_t edge_error = 0ll;
  const bool had_previous_snapshot =
      engine->have_previous_snapshot && !input->reset;
  const uint32_t previous_snapshot_sequence =
      engine->previous_snapshot_sequence;
  const uint32_t previous_reference_sequence =
      engine->previous_reference_sequence;

  if (input->reset) {
    engine->have_previous_snapshot = false;
    engine->pending_phase_reason = "reset";
    reset_frequency(engine);
  }

  if (input->snapshot_status != 0u || !input->reference_qualified) {
    phase_state = OtisReferenceRelativePhaseState::Invalid;
    phase_reason = input->snapshot_status != 0u ? "snapshot_status_invalid"
                                                : "reference_invalid_or_stale";
    engine->have_previous_snapshot = false;
    engine->pending_phase_reason = phase_reason;
    reset_frequency(engine);
  } else if (!engine->have_previous_snapshot) {
    engine->phase_epoch++;
    engine->observation_sequence = 0u;
    engine->cumulative_phase = 0ll;
    phase_state = OtisReferenceRelativePhaseState::EpochOpen;
    phase_reason = engine->pending_phase_reason;
    engine->pending_phase_reason = nullptr;
  } else if (input->capture_session != engine->previous_capture_session) {
    engine->phase_epoch++;
    engine->observation_sequence = 0u;
    engine->cumulative_phase = 0ll;
    phase_state = OtisReferenceRelativePhaseState::EpochOpen;
    phase_reason = "capture_session_change";
  } else if (input->snapshot_sequence <= engine->previous_snapshot_sequence) {
    phase_reason = "snapshot_reordered_or_duplicate";
  } else if (input->reference_sequence <= engine->previous_reference_sequence) {
    phase_reason = "reference_reordered_or_duplicate";
  } else if (input->snapshot_sequence != engine->previous_snapshot_sequence + 1u ||
             input->reference_sequence != engine->previous_reference_sequence + 1u) {
    engine->phase_epoch++;
    engine->observation_sequence = 0u;
    engine->cumulative_phase = 0ll;
    phase_state = OtisReferenceRelativePhaseState::EpochOpen;
    phase_reason = "snapshot_or_reference_sequence_gap";
  } else {
    const uint64_t reference_delta =
        (input->reference_timestamp_ticks + kReferenceTimestampModulus -
         engine->previous_reference_ticks) %
        kReferenceTimestampModulus;
    if (reference_delta == 0u) {
      phase_reason = "reference_timestamp_reordered";
    } else if (reference_delta > kMaximumReferenceTicks ||
               reference_delta < kMinimumReferenceTicks) {
      engine->phase_epoch++;
      engine->observation_sequence = 0u;
      engine->cumulative_phase = 0ll;
      phase_state = OtisReferenceRelativePhaseState::EpochOpen;
      phase_reason = reference_delta > kMaximumReferenceTicks
                         ? "reference_pps_long_interval"
                         : "reference_pps_short_interval";
    } else {
      interval_edges = static_cast<uint32_t>(
          (static_cast<uint64_t>(engine->previous_counter) + kCounterModulus -
           input->cumulative_down_counter) %
          kCounterModulus);
      if (!input->counted_edges_available ||
          input->counted_edges != interval_edges) {
        engine->phase_epoch++;
        engine->observation_sequence = 0u;
        engine->cumulative_phase = 0ll;
        phase_state = OtisReferenceRelativePhaseState::EpochOpen;
        phase_reason = "snapshot_count_association_mismatch";
      } else {
        edge_error = static_cast<int64_t>(interval_edges) - kNominalEdges;
        engine->cumulative_phase += edge_error;
        engine->observation_sequence++;
        phase_state = OtisReferenceRelativePhaseState::Qualified;
        accepted = true;
        interval_available = true;
      }
    }
  }

  if (phase_state == OtisReferenceRelativePhaseState::Invalid) {
    if (phase_reason == nullptr) phase_reason = "invalid_phase_input";
    engine->have_previous_snapshot = false;
    engine->pending_phase_reason = phase_reason;
    reset_frequency(engine);
  } else {
    engine->have_previous_snapshot = true;
    engine->previous_capture_session = input->capture_session;
    engine->previous_snapshot_sequence = input->snapshot_sequence;
    engine->previous_counter = input->cumulative_down_counter;
    engine->previous_reference_sequence = input->reference_sequence;
    engine->previous_reference_ticks = input->reference_timestamp_ticks;
  }

  const bool opens_at_current =
      phase_state == OtisReferenceRelativePhaseState::EpochOpen ||
      !had_previous_snapshot;
  populate_output(
      engine, output, input->dac_epoch, phase_state, phase_reason, accepted,
      interval_available, interval_edges, edge_error, input->capture_session,
      opens_at_current ? input->snapshot_sequence : previous_snapshot_sequence,
      input->snapshot_sequence,
      opens_at_current ? input->reference_sequence : previous_reference_sequence,
      input->reference_sequence);

  if (phase_state != OtisReferenceRelativePhaseState::Invalid) {
    double frequency = 0.0;
    const bool supported = add_frequency_point(
        engine, engine->phase_epoch, input->dac_epoch, engine->cumulative_phase,
        &frequency);
    if (supported &&
        (!engine->frequency_estimate_available ||
         input->monotonic_timestamp_ticks -
                 engine->frequency_estimate_timestamp_ticks >=
             kFrequencyOutputCadenceTicks)) {
      engine->frequency_estimate_available = true;
      engine->frequency_estimate_timestamp_ticks =
          input->monotonic_timestamp_ticks;
      engine->frequency_error_hz = frequency;
      output->frequency_observation_event = true;
    }
  }
  output->frequency_available = engine->frequency_estimate_available;
  output->frequency_error_hz = engine->frequency_error_hz;
  output->frequency_estimate_age_ticks =
      engine->frequency_estimate_available
          ? input->monotonic_timestamp_ticks -
                engine->frequency_estimate_timestamp_ticks
          : 0u;
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
