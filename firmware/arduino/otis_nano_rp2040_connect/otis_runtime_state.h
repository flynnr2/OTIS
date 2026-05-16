#ifndef OTIS_RUNTIME_STATE_H
#define OTIS_RUNTIME_STATE_H

#include <stdint.h>

#include "otis_boot_diag.h"

struct OtisSequenceState {
  uint32_t event_seq;
  uint32_t status_seq;
  uint32_t count_seq;
  uint32_t dac_seq;
};

struct OtisCaptureRuntimeState {
  uint32_t emitted_event_count;
};

struct OtisPeriodicRuntimeState {
  uint32_t last_status_ms;
};

struct OtisBootRuntimeState {
  BootPhase phase;
  bool serial_ready;
  bool summary_emitted;
  bool serial_absent_warn_pending;
  bool safe_mode_active;
  bool safe_mode_warn_pending;
};

struct OtisLoopbackRuntimeState {
  uint32_t last_toggle_ms;
  bool output_high;
};

struct OtisTcxoRuntimeState {
  uint32_t last_measure_ms;
  uint32_t gate_open_us;
  uint64_t fc0_accum_gate_open_ticks;
  uint64_t fc0_accum_weighted_khz_us;
  uint64_t fc0_accum_elapsed_us;
  uint32_t fc0_accum_sample_count;
  uint32_t fc0_accum_flags;
  bool fc0_accum_active;
  uint64_t last_gate_open_ticks;
  uint64_t last_gate_close_ticks;
  uint64_t last_counted_edges;
  uint32_t last_elapsed_us;
  uint32_t last_measured_khz;
  uint32_t last_sampled_elapsed_us;
  uint32_t last_sample_count;
  bool last_observation_valid;
};

struct OtisRuntimeState {
  OtisSequenceState sequences;
  OtisCaptureRuntimeState capture;
  OtisPeriodicRuntimeState periodic;
  OtisBootRuntimeState boot;
  OtisLoopbackRuntimeState loopback;
  OtisTcxoRuntimeState tcxo;
  uint8_t active_mode;
};

void otis_runtime_state_init(OtisRuntimeState *state);

#endif
