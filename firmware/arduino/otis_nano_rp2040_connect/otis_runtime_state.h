#ifndef OTIS_RUNTIME_STATE_H
#define OTIS_RUNTIME_STATE_H

#include <stdint.h>

#include "otis_boot_diag.h"

struct OtisSequenceState {
  uint32_t event_seq;
  uint32_t status_seq;
  uint32_t count_seq;
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
