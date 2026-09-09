#ifndef OTIS_RUNTIME_STATE_H
#define OTIS_RUNTIME_STATE_H

#include <stdint.h>

#include "otis_boot_diag.h"

struct OtisSequenceState {
  uint32_t event_seq;
  uint32_t status_seq;
  uint32_t count_seq;
  uint32_t dac_seq;
  uint32_t env_seq;
  uint32_t estimate_seq;
  uint32_t control_seq;
};

struct OtisCaptureRuntimeState {
  uint32_t emitted_event_count;
};

struct OtisPeriodicRuntimeState {
  uint32_t last_status_ms;
  uint32_t last_env_sample_ms;
};

struct OtisBootRuntimeState {
  BootPhase phase;
  bool serial_ready;
  bool summary_emitted;
  bool protocol_banner_emitted;
  bool serial_absent_warn_pending;
  bool safe_mode_active;
  bool safe_mode_warn_pending;
  bool degraded;
};

struct OtisTcxoRuntimeState {
  uint64_t last_gate_open_ticks;
  uint64_t last_gate_close_ticks;
  uint64_t last_counted_edges;
  uint32_t last_elapsed_us;
  uint32_t last_measured_khz;
  uint32_t last_sampled_elapsed_us;
  uint32_t last_sample_count;
  uint32_t last_zero_sample_count;
  uint32_t last_valid_sample_count;
  uint32_t last_first_sample_khz;
  uint32_t last_last_sample_khz;
  uint32_t last_min_sample_khz;
  uint32_t last_max_sample_khz;
  uint32_t last_window_flags;
  const char *last_window_invalid_reason;
  uint32_t consecutive_bad_windows;
  uint32_t total_bad_windows;
  uint32_t startup_inhibit_start_ms;
  uint32_t startup_inhibit_elapsed_s;
  uint32_t control_clean_window_count;
  bool startup_inhibit_active;
  bool valid_for_control;
  bool fault_after_startup;
  bool last_observation_valid;
};

struct OtisRuntimeState {
  OtisSequenceState sequences;
  OtisCaptureRuntimeState capture;
  OtisPeriodicRuntimeState periodic;
  OtisBootRuntimeState boot;
  OtisTcxoRuntimeState tcxo;
};

void otis_runtime_state_init(OtisRuntimeState *state);

#endif
