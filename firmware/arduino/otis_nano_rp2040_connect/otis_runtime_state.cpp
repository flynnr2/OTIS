#include "otis_runtime_state.h"

#include "otis_config.h"

void otis_runtime_state_init(OtisRuntimeState *state) {
  if (state == nullptr) {
    return;
  }

  state->sequences.event_seq = 1000;
  state->sequences.status_seq = 1;
  state->sequences.count_seq = 1;

  state->capture.emitted_event_count = 0;

  state->periodic.last_status_ms = 0;

  state->boot.phase = BootPhase::ResetEntry;
  state->boot.serial_ready = false;
  state->boot.summary_emitted = false;
  state->boot.serial_absent_warn_pending = false;
  state->boot.safe_mode_active = false;
  state->boot.safe_mode_warn_pending = false;

  state->loopback.last_toggle_ms = 0;
  state->loopback.output_high = false;

  state->tcxo.last_measure_ms = 0;
  state->tcxo.gate_open_us = 0;
  state->tcxo.last_gate_open_ticks = 0;
  state->tcxo.last_gate_close_ticks = 0;
  state->tcxo.last_counted_edges = 0;
  state->tcxo.last_elapsed_us = 0;
  state->tcxo.last_measured_khz = 0;
  state->tcxo.last_observation_valid = false;

  state->active_mode = OTIS_SW1_BRINGUP_MODE;
}
