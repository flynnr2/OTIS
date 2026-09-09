#ifndef OTIS_SELECTED_PHASE_FREQUENCY_PREVIEW_ENGINE_H
#define OTIS_SELECTED_PHASE_FREQUENCY_PREVIEW_ENGINE_H

#include <stdint.h>

// Pure D14-referenced D8 relative-phase and supporting frequency estimator.
// This interface has no authority, transaction, actuator, serial, DAC-driver,
// or I2C type.

constexpr uint16_t OTIS_PHASE_FREQUENCY_SUPPORT_INTERVALS = 600u;

enum class OtisReferenceRelativePhaseState : uint8_t {
  EpochOpen,
  Qualified,
  Invalid,
};

struct OtisSelectedPhaseFrequencyPreviewInput {
  uint32_t capture_session;
  uint32_t snapshot_sequence;
  uint32_t cumulative_down_counter;
  uint32_t reference_sequence;
  uint64_t reference_timestamp_ticks;
  uint64_t monotonic_timestamp_ticks;
  uint32_t snapshot_status;
  uint32_t counted_edges;
  uint32_t dac_epoch;
  bool counted_edges_available;
  bool reference_qualified;
  bool reset;
};

struct OtisSelectedPhaseFrequencyPreviewOutput {
  uint32_t phase_epoch;
  uint32_t observation_sequence;
  uint32_t capture_session;
  uint32_t opening_snapshot_sequence;
  uint32_t closing_snapshot_sequence;
  uint32_t opening_reference_sequence;
  uint32_t closing_reference_sequence;
  uint32_t dac_epoch;
  uint32_t interval_edges;
  int64_t edge_error_cycles;
  int64_t relative_phase_cycles;
  int64_t relative_phase_time_ns;
  OtisReferenceRelativePhaseState phase_state;
  const char *phase_reason;
  bool phase_accepted;
  bool interval_available;
  bool frequency_available;
  bool frequency_observation_event;
  double frequency_error_hz;
  uint64_t frequency_estimate_age_ticks;
};

struct OtisSelectedPhaseFrequencyPreviewEngine {
  bool have_previous_snapshot;
  uint32_t previous_capture_session;
  uint32_t previous_snapshot_sequence;
  uint32_t previous_counter;
  uint32_t previous_reference_sequence;
  uint64_t previous_reference_ticks;
  uint32_t phase_epoch;
  uint32_t observation_sequence;
  int64_t cumulative_phase;
  const char *pending_phase_reason;

  int64_t frequency_phase_points[OTIS_PHASE_FREQUENCY_SUPPORT_INTERVALS + 1u];
  uint16_t frequency_point_next;
  uint16_t frequency_point_count;
  uint32_t frequency_phase_epoch;
  uint32_t frequency_dac_epoch;
  bool frequency_estimate_available;
  uint64_t frequency_estimate_timestamp_ticks;
  double frequency_error_hz;
};

bool otis_selected_phase_frequency_preview_init(
    OtisSelectedPhaseFrequencyPreviewEngine *engine);
bool otis_selected_phase_frequency_preview_process(
    OtisSelectedPhaseFrequencyPreviewEngine *engine,
    const OtisSelectedPhaseFrequencyPreviewInput *input,
    OtisSelectedPhaseFrequencyPreviewOutput *output);

const char *otis_reference_relative_phase_state_name(
    OtisReferenceRelativePhaseState state);

#endif
