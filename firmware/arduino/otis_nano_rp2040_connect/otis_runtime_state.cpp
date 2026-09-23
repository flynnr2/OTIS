#include "otis_runtime_state.h"

#include "otis_config.h"

void otis_runtime_state_init(OtisRuntimeState *state) {
  if (state == nullptr) {
    return;
  }

  state->sequences.event_seq = 1000;
  state->sequences.status_seq = 1;
  state->sequences.count_seq = 1;
  state->sequences.dac_seq = 1;
  state->sequences.env_seq = 1;
  state->sequences.estimate_seq = 1;
  state->sequences.control_seq = 1;

  state->capture.emitted_event_count = 0;

  state->periodic.last_status_ms = 0;
  state->periodic.last_env_sample_ms = 0;

  state->boot.phase = BootPhase::ResetEntry;
  state->boot.serial_ready = false;
  state->boot.summary_emitted = false;
  state->boot.protocol_banner_emitted = false;
  state->boot.serial_absent_warn_pending = false;
  state->boot.safe_mode_active = false;
  state->boot.safe_mode_warn_pending = false;
  state->boot.degraded = false;

  state->tcxo.last_gate_open_ticks = 0;
  state->tcxo.last_gate_close_ticks = 0;
  state->tcxo.last_counted_edges = 0;
  state->tcxo.last_elapsed_us = 0;
  state->tcxo.last_measured_khz = 0;
  state->tcxo.last_sampled_elapsed_us = 0;
  state->tcxo.last_sample_count = 0;
  state->tcxo.last_zero_sample_count = 0;
  state->tcxo.last_valid_sample_count = 0;
  state->tcxo.last_first_sample_khz = 0;
  state->tcxo.last_last_sample_khz = 0;
  state->tcxo.last_min_sample_khz = 0;
  state->tcxo.last_max_sample_khz = 0;
  state->tcxo.last_window_flags = 0;
  state->tcxo.last_window_invalid_reason = "no_samples";
  state->tcxo.consecutive_bad_windows = 0;
  state->tcxo.total_bad_windows = 0;
  state->tcxo.startup_inhibit_start_ms = 0;
  state->tcxo.startup_inhibit_start_ticks = 0;
  state->tcxo.startup_inhibit_elapsed_s = 0;
  state->tcxo.control_clean_window_count = 0;
  state->tcxo.startup_inhibit_active = true;
  state->tcxo.valid_for_control = false;
  state->tcxo.fault_after_startup = false;
  state->tcxo.last_observation_valid = false;

}
