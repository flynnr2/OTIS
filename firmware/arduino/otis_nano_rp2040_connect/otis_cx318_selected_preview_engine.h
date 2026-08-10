#ifndef OTIS_CX318_SELECTED_PREVIEW_ENGINE_H
#define OTIS_CX318_SELECTED_PREVIEW_ENGINE_H

#include <stdint.h>

// Pure, non-actionable Stage 4 parity engine.  This interface deliberately has
// no authority, transaction, actuator, serial, DAC-driver, or I2C type.

constexpr uint16_t OTIS_CX318_FREQUENCY_SUPPORT_INTERVALS = 600u;
constexpr uint8_t OTIS_CX318_DIRECTION_HISTORY_CAPACITY = 32u;

enum class OtisCx318PhaseState : uint8_t {
  EpochOpen,
  Qualified,
  Invalid,
};

struct OtisCx318SelectedPreviewInput {
  uint32_t capture_session;
  uint32_t snapshot_sequence;
  uint32_t cumulative_down_counter;
  uint32_t reference_sequence;
  uint64_t reference_timestamp_ticks;
  uint32_t snapshot_status;
  uint32_t counted_edges;
  uint32_t dac_epoch;
  double timestamp_s;
  uint16_t actual_applied_code;
  bool counted_edges_available;
  bool reference_qualified;
  bool reset;
  bool phase_step_detected;
};

struct OtisCx318SelectedPreviewOutput {
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
  OtisCx318PhaseState phase_state;
  const char *phase_reason;
  bool phase_accepted;
  bool interval_available;

  bool raw_frequency_available;
  double raw_frequency_error_hz;

  bool frequency_available;
  double observed_frequency_error_hz;
  double modeled_relative_phase_cycles;
  double modeled_frequency_error_hz;
  double frequency_term_hz;
  double phase_bias_hz;
  double combined_desired_frequency_change_hz;
  uint16_t actual_applied_code;
  uint16_t shadow_code_before;
  uint16_t shadow_code_after;
  const char *band_state_before;
  const char *band_state_after;
  const char *preview_state;
  const char *decision_reason;
  bool frequency_observation_event;
  bool counterfactual_decision;
  bool counterfactual_correction;
  bool raw_delta_available;
  double raw_delta_codes;
  int32_t limited_delta_codes;
  bool step_limited;
  bool range_clamped;
  uint16_t correction_count;
  uint16_t cumulative_movement_codes;
  uint16_t alternating_correction_count;
  bool modeled_not_observed_after_divergence;
};

struct OtisCx318SelectedPreviewEngine {
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

  int64_t frequency_phase_points[OTIS_CX318_FREQUENCY_SUPPORT_INTERVALS + 1u];
  uint16_t frequency_point_next;
  uint16_t frequency_point_count;
  uint32_t frequency_phase_epoch;
  uint32_t frequency_dac_epoch;

  bool hybrid_phase_epoch_available;
  uint32_t hybrid_phase_epoch;
  bool hybrid_dac_epoch_available;
  uint32_t hybrid_dac_epoch;
  uint16_t actual_code;
  uint16_t shadow_code;
  uint16_t start_code;
  double modeled_phase;
  int64_t previous_raw_phase;
  bool previous_preview_time_available;
  double previous_preview_time_s;
  bool last_frequency_event_available;
  double last_frequency_event_s;
  bool last_observed_frequency_available;
  double last_observed_frequency_hz;
  bool last_decision_available;
  double last_decision_s;
  bool last_correction_available;
  double last_correction_s;
  bool phase_hold_available;
  double phase_hold_until_s;
  bool band_inside;
  double integrator_codes;
  uint16_t correction_count;
  uint16_t path_codes;
  int8_t directions[OTIS_CX318_DIRECTION_HISTORY_CAPACITY];
  uint8_t direction_count;
  const char *terminal_reason;
  bool had_reference_loss;
};

bool otis_cx318_selected_preview_init(OtisCx318SelectedPreviewEngine *engine,
                                      uint16_t start_code);
bool otis_cx318_selected_preview_process(
    OtisCx318SelectedPreviewEngine *engine,
    const OtisCx318SelectedPreviewInput *input,
    OtisCx318SelectedPreviewOutput *output);

const char *otis_cx318_phase_state_name(OtisCx318PhaseState state);

#endif
