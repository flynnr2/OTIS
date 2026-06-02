#include "otis_count_observation.h"

#include <Arduino.h>
#include <hardware/clocks.h>
#include <hardware/gpio.h>
#include <hardware/pio.h>
#include <hardware/pio_instructions.h>
#include <stdint.h>

#include "otis_board.h"
#include "otis_capture_irq.h"
#include "otis_config.h"
#include "otis_emit.h"
#include "otis_protocol.h"
#include "otis_timebase.h"

namespace {

constexpr uint64_t kRp2040Timer0MicrosWrapTicks = (1ull << 32) * 16ull;
constexpr uint32_t kH1PioCounterInitialX = 0xffffffffu;
constexpr uint32_t kImplausibleGateDurationMultiplier = 2u;

const char kWindowReasonNone[] = "none";
const char kWindowReasonNoSamples[] = "no_samples";
const char kWindowReasonAllZeroSamples[] = "all_zero_samples";
const char kWindowReasonPartialZeroSamples[] = "partial_zero_samples";
const char kWindowReasonNonPositiveGateDuration[] =
    "non_positive_gate_duration";
const char kWindowReasonImplausibleGateDuration[] =
    "implausible_gate_duration";
const char kWindowReasonCountedEdgesZero[] = "counted_edges_zero";
const char kWindowReasonMissingPps[] = "missing_pps";
const char kWindowReasonPpsIntervalAnomaly[] = "pps_interval_anomaly";
const char kWindowReasonCounterSaturated[] = "counter_saturated";

enum class PpsGateState : uint8_t {
  Idle,
  Armed,
  Open,
  Fault,
};

struct WindowAnomaly {
  const char *reason;
  bool valid;
  bool post_startup_invalid;
  uint32_t flags;
};

#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE || \
    OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
struct H1PioLongGateCounter {
  PIO pio;
  uint sm;
  uint offset;
  bool initialized;
  bool active;
  uint64_t gate_open_ticks;
};

H1PioLongGateCounter h1_pio_long_gate = {pio0, 0, 0, false, false, 0};

bool begin_h1_pio_long_gate_counter(void) {
  uint16_t instructions[] = {
      (uint16_t)pio_encode_pull(false, true),
      (uint16_t)pio_encode_mov(pio_x, pio_osr),
      (uint16_t)pio_encode_wait_pin(true, 0),
      (uint16_t)pio_encode_wait_pin(false, 0),
      (uint16_t)pio_encode_jmp_x_dec(2),
  };
  pio_program program = {
      instructions,
      5,
      -1,
  };

  h1_pio_long_gate.pio = pio0;
  h1_pio_long_gate.sm = pio_claim_unused_sm(h1_pio_long_gate.pio, true);
  h1_pio_long_gate.offset = pio_add_program(h1_pio_long_gate.pio, &program);

  pio_gpio_init(h1_pio_long_gate.pio, OTIS_GPIO_OSC_OBSERVATION);
  gpio_pull_down(OTIS_GPIO_OSC_OBSERVATION);

  pio_sm_config config = pio_get_default_sm_config();
  sm_config_set_in_pins(&config, OTIS_GPIO_OSC_OBSERVATION);
  sm_config_set_wrap(&config, h1_pio_long_gate.offset + 2,
                     h1_pio_long_gate.offset + 4);
  sm_config_set_clkdiv(&config, 1.0f);
  pio_sm_init(h1_pio_long_gate.pio, h1_pio_long_gate.sm,
              h1_pio_long_gate.offset, &config);
  pio_sm_set_enabled(h1_pio_long_gate.pio, h1_pio_long_gate.sm, false);
  h1_pio_long_gate.initialized = true;
  h1_pio_long_gate.active = false;
  h1_pio_long_gate.gate_open_ticks = 0;
  return true;
}

void start_h1_pio_long_gate_counter(uint64_t gate_open_ticks) {
  if (!h1_pio_long_gate.initialized) {
    return;
  }
  pio_sm_set_enabled(h1_pio_long_gate.pio, h1_pio_long_gate.sm, false);
  pio_sm_clear_fifos(h1_pio_long_gate.pio, h1_pio_long_gate.sm);
  pio_sm_restart(h1_pio_long_gate.pio, h1_pio_long_gate.sm);
  pio_sm_clkdiv_restart(h1_pio_long_gate.pio, h1_pio_long_gate.sm);
  pio_sm_put_blocking(h1_pio_long_gate.pio, h1_pio_long_gate.sm,
                      kH1PioCounterInitialX);
  pio_sm_exec_wait_blocking(h1_pio_long_gate.pio, h1_pio_long_gate.sm,
                            pio_encode_jmp(h1_pio_long_gate.offset));
  h1_pio_long_gate.gate_open_ticks = gate_open_ticks;
  h1_pio_long_gate.active = true;
  pio_sm_set_enabled(h1_pio_long_gate.pio, h1_pio_long_gate.sm, true);
}

uint32_t stop_h1_pio_long_gate_counter(void) {
  pio_sm_set_enabled(h1_pio_long_gate.pio, h1_pio_long_gate.sm, false);
  pio_sm_clear_fifos(h1_pio_long_gate.pio, h1_pio_long_gate.sm);
  pio_sm_exec_wait_blocking(h1_pio_long_gate.pio, h1_pio_long_gate.sm,
                            pio_encode_mov(pio_isr, pio_x));
  pio_sm_exec_wait_blocking(h1_pio_long_gate.pio, h1_pio_long_gate.sm,
                            pio_encode_push(false, false));
  uint32_t remaining = pio_sm_get_blocking(h1_pio_long_gate.pio,
                                           h1_pio_long_gate.sm);
  h1_pio_long_gate.active = false;
  return remaining;
}
#endif

#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
struct PpsGatedRatioBackend {
  PpsGateState state;
  bool pps_level_high;
  uint64_t last_pps_ticks;
  uint64_t gate_open_ticks;
  uint32_t accepted_window_count;
  uint32_t rejected_window_count;
  uint32_t missing_pps_count;
  uint32_t pps_interval_anomaly_count;
  uint32_t count_saturated_count;
  const char *last_reason;
};

PpsGatedRatioBackend pps_gated_ratio = {
    PpsGateState::Idle,
    false,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    kWindowReasonNone,
};
#endif

void emit_status(OtisStatusEmitContext *context, const char *component,
                 const char *key, const char *value, const char *severity,
                 uint32_t flags) {
  otis_status_emit(context, component, key, value, severity, flags);
}

void emit_status_u32(OtisStatusEmitContext *context, const char *component,
                     const char *key, uint32_t value, const char *severity,
                     uint32_t flags) {
  otis_status_emit_u32(context, component, key, value, severity, flags);
}

const char *bool_text(bool value) { return value ? "true" : "false"; }

#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
const char *pps_gate_state_name(PpsGateState state) {
  switch (state) {
    case PpsGateState::Idle:
      return "idle";
    case PpsGateState::Armed:
      return "armed";
    case PpsGateState::Open:
      return "open";
    case PpsGateState::Fault:
      return "fault";
  }
  return "unknown";
}

void emit_pps_gate_status(OtisStatusEmitContext *status_context,
                          const char *severity, uint32_t flags) {
  emit_status(status_context, "pps_gate", "backend", "pps_gated_ratio",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(status_context, "pps_gate", "state",
              pps_gate_state_name(pps_gated_ratio.state), severity, flags);
  emit_status(status_context, "pps_gate", "last_reason",
              pps_gated_ratio.last_reason, severity, flags);
  emit_status_u32(status_context, "pps_gate", "accepted_window_count",
                  pps_gated_ratio.accepted_window_count, OTIS_SEVERITY_INFO,
                  flags);
  emit_status_u32(status_context, "pps_gate", "rejected_window_count",
                  pps_gated_ratio.rejected_window_count,
                  pps_gated_ratio.rejected_window_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate", "missing_pps_count",
                  pps_gated_ratio.missing_pps_count,
                  pps_gated_ratio.missing_pps_count == 0u ? OTIS_SEVERITY_INFO
                                                          : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate", "pps_interval_anomaly_count",
                  pps_gated_ratio.pps_interval_anomaly_count,
                  pps_gated_ratio.pps_interval_anomaly_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate", "count_saturated_count",
                  pps_gated_ratio.count_saturated_count,
                  pps_gated_ratio.count_saturated_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
}

void emit_pps_gate_window_status(OtisRuntimeState *runtime_state,
                                 OtisStatusEmitContext *status_context,
                                 const WindowAnomaly &anomaly,
                                 bool ratio_available) {
  uint32_t flags = runtime_state->tcxo.last_window_flags;
  emit_status(status_context, "pps_gate", "valid", bool_text(anomaly.valid),
              anomaly.valid ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN, flags);
  emit_status(status_context, "pps_gate", "ratio_available",
              bool_text(ratio_available),
              ratio_available ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              flags);
  emit_status_u32(status_context, "pps_gate", "last_interval_us",
                  runtime_state->tcxo.last_elapsed_us,
                  anomaly.valid ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
                  flags);
  emit_status(status_context, "pps_gate", "startup_inhibit_active",
              bool_text(runtime_state->tcxo.startup_inhibit_active),
              runtime_state->tcxo.startup_inhibit_active ? OTIS_SEVERITY_WARN
                                                         : OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(status_context, "pps_gate", "control_eligible",
              bool_text(runtime_state->tcxo.valid_for_control),
              runtime_state->tcxo.valid_for_control ? OTIS_SEVERITY_INFO
                                                    : OTIS_SEVERITY_WARN,
              flags);
  emit_status_u32(status_context, "pps_gate", "consecutive_bad_window_count",
                  runtime_state->tcxo.consecutive_bad_windows,
                  runtime_state->tcxo.consecutive_bad_windows == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "pps_gate", "total_bad_window_count",
                  runtime_state->tcxo.total_bad_windows,
                  runtime_state->tcxo.total_bad_windows == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  flags);
  emit_pps_gate_status(status_context,
                       anomaly.valid ? OTIS_SEVERITY_INFO
                                     : OTIS_SEVERITY_WARN,
                       flags);
}

void emit_pps_gate_fault(OtisRuntimeState *runtime_state,
                         OtisStatusEmitContext *status_context,
                         const char *reason, uint32_t flags) {
  pps_gated_ratio.last_reason = reason;
  pps_gated_ratio.state = PpsGateState::Fault;
  pps_gated_ratio.rejected_window_count += 1u;
  runtime_state->tcxo.consecutive_bad_windows += 1u;
  runtime_state->tcxo.total_bad_windows += 1u;
  runtime_state->tcxo.control_clean_window_count = 0u;
  runtime_state->tcxo.valid_for_control = false;
  if (!runtime_state->tcxo.startup_inhibit_active) {
    runtime_state->tcxo.fault_after_startup = true;
  }
  runtime_state->tcxo.last_observation_valid = false;
  runtime_state->tcxo.last_window_invalid_reason = reason;
  runtime_state->tcxo.last_window_flags = flags;
  emit_status(status_context, "pps_gate", "valid", "false",
              OTIS_SEVERITY_WARN, flags);
  emit_status(status_context, "pps_gate", "ratio_available", "false",
              OTIS_SEVERITY_WARN, flags);
  emit_status(status_context, "pps_gate", "startup_inhibit_active",
              bool_text(runtime_state->tcxo.startup_inhibit_active),
              runtime_state->tcxo.startup_inhibit_active ? OTIS_SEVERITY_WARN
                                                         : OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(status_context, "pps_gate", "control_eligible", "false",
              OTIS_SEVERITY_WARN, flags);
  emit_pps_gate_status(status_context, OTIS_SEVERITY_WARN, flags);
}

bool pps_interval_valid(uint64_t interval_us) {
  return interval_us >= OTIS_PPS_GATE_MIN_INTERVAL_US &&
         interval_us <= OTIS_PPS_GATE_MAX_INTERVAL_US;
}

bool pps_rising_edge(uint64_t *edge_ticks) {
  bool level_high = digitalRead(OTIS_PIN_PPS_REFERENCE) == HIGH;
  bool rising = level_high && !pps_gated_ratio.pps_level_high;
  pps_gated_ratio.pps_level_high = level_high;
  if (rising) {
    *edge_ticks = otis_capture_ticks_now();
  }
  return rising;
}
#endif

void reset_fc0_accum_window(OtisRuntimeState *runtime_state) {
  runtime_state->tcxo.fc0_accum_active = false;
  runtime_state->tcxo.fc0_accum_gate_open_ticks = 0;
  runtime_state->tcxo.fc0_accum_weighted_khz_us = 0;
  runtime_state->tcxo.fc0_accum_elapsed_us = 0;
  runtime_state->tcxo.fc0_accum_sample_count = 0;
  runtime_state->tcxo.fc0_accum_zero_sample_count = 0;
  runtime_state->tcxo.fc0_accum_first_sample_khz = 0;
  runtime_state->tcxo.fc0_accum_last_sample_khz = 0;
  runtime_state->tcxo.fc0_accum_min_sample_khz = 0;
  runtime_state->tcxo.fc0_accum_max_sample_khz = 0;
  runtime_state->tcxo.fc0_accum_flags = OTIS_FLAG_NONE;
}

void start_fc0_accum_window(OtisRuntimeState *runtime_state,
                            uint64_t gate_open_ticks) {
  reset_fc0_accum_window(runtime_state);
  runtime_state->tcxo.fc0_accum_gate_open_ticks = gate_open_ticks;
  runtime_state->tcxo.fc0_accum_flags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;
  runtime_state->tcxo.fc0_accum_active = true;
}

void record_fc0_sample(OtisRuntimeState *runtime_state, uint32_t measured_khz,
                       uint64_t elapsed_us) {
  runtime_state->tcxo.fc0_accum_weighted_khz_us +=
      (uint64_t)measured_khz * elapsed_us;
  runtime_state->tcxo.fc0_accum_elapsed_us += elapsed_us;
  runtime_state->tcxo.fc0_accum_sample_count += 1u;
  if (runtime_state->tcxo.fc0_accum_sample_count == 1u) {
    runtime_state->tcxo.fc0_accum_first_sample_khz = measured_khz;
    runtime_state->tcxo.fc0_accum_min_sample_khz = measured_khz;
    runtime_state->tcxo.fc0_accum_max_sample_khz = measured_khz;
  } else {
    if (measured_khz < runtime_state->tcxo.fc0_accum_min_sample_khz) {
      runtime_state->tcxo.fc0_accum_min_sample_khz = measured_khz;
    }
    if (measured_khz > runtime_state->tcxo.fc0_accum_max_sample_khz) {
      runtime_state->tcxo.fc0_accum_max_sample_khz = measured_khz;
    }
  }
  runtime_state->tcxo.fc0_accum_last_sample_khz = measured_khz;
  if (measured_khz == 0u) {
    runtime_state->tcxo.fc0_accum_zero_sample_count += 1u;
  }
}

void emit_bad_window_diagnostics(OtisRuntimeState *runtime_state,
                                 OtisStatusEmitContext *status_context,
                                 const WindowAnomaly &anomaly) {
  uint32_t flags = runtime_state->tcxo.last_window_flags;
  emit_status(status_context, "fc0", "window_invalid_reason",
              runtime_state->tcxo.last_window_invalid_reason, OTIS_SEVERITY_WARN,
              flags);
  emit_status_u32(status_context, "fc0", "window_sample_count",
                  runtime_state->tcxo.last_sample_count, OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "fc0", "window_zero_sample_count",
                  runtime_state->tcxo.last_zero_sample_count, OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "fc0", "window_valid_sample_count",
                  runtime_state->tcxo.last_valid_sample_count,
                  OTIS_SEVERITY_WARN, flags);
  emit_status_u32(status_context, "fc0", "window_first_sample_khz",
                  runtime_state->tcxo.last_first_sample_khz,
                  OTIS_SEVERITY_WARN, flags);
  emit_status_u32(status_context, "fc0", "window_last_sample_khz",
                  runtime_state->tcxo.last_last_sample_khz, OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "fc0", "window_min_sample_khz",
                  runtime_state->tcxo.last_min_sample_khz, OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "fc0", "window_max_sample_khz",
                  runtime_state->tcxo.last_max_sample_khz, OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "fc0", "window_elapsed_us",
                  runtime_state->tcxo.last_elapsed_us, OTIS_SEVERITY_WARN,
                  flags);
  emit_status_u32(status_context, "fc0", "window_flags",
                  runtime_state->tcxo.last_window_flags, OTIS_SEVERITY_WARN,
                  flags);
  emit_status(status_context, "fc0", "post_startup_invalid_window",
              anomaly.post_startup_invalid ? "true" : "false",
              anomaly.post_startup_invalid ? OTIS_SEVERITY_WARN
                                           : OTIS_SEVERITY_INFO,
              flags);
  emit_status_u32(status_context, "fc0", "consecutive_bad_windows",
                  runtime_state->tcxo.consecutive_bad_windows,
                  OTIS_SEVERITY_WARN, flags);
  emit_status_u32(status_context, "fc0", "total_bad_windows",
                  runtime_state->tcxo.total_bad_windows, OTIS_SEVERITY_WARN,
                  flags);
}

bool gate_duration_implausible(uint32_t elapsed_us,
                               const OtisCountObservationConfig *config) {
  if (config->gate_period_us == 0u) {
    return true;
  }
  uint64_t max_gate_us =
      (uint64_t)config->gate_period_us * kImplausibleGateDurationMultiplier;
  return (uint64_t)elapsed_us > max_gate_us;
}

void update_startup_inhibit(OtisRuntimeState *runtime_state,
                            const OtisCountObservationConfig *config,
                            uint32_t now_ms) {
  runtime_state->tcxo.startup_inhibit_elapsed_s =
      (uint32_t)((now_ms - runtime_state->tcxo.startup_inhibit_start_ms) /
                 1000u);
  runtime_state->tcxo.startup_inhibit_active =
      (uint32_t)(now_ms - runtime_state->tcxo.startup_inhibit_start_ms) <
      config->startup_inhibit_ms;
}

WindowAnomaly classify_window(OtisRuntimeState *runtime_state,
                              const OtisCountObservationConfig *config,
                              bool expect_samples,
                              bool expect_counted_edges) {
  WindowAnomaly anomaly = {
      kWindowReasonNone,
      true,
      false,
      runtime_state->tcxo.last_window_flags,
  };

  if (runtime_state->tcxo.last_elapsed_us == 0u) {
    anomaly.reason = kWindowReasonNonPositiveGateDuration;
    anomaly.valid = false;
    anomaly.flags |= OTIS_FLAG_GATE_INCOMPLETE;
  } else if (gate_duration_implausible(runtime_state->tcxo.last_elapsed_us,
                                       config)) {
    anomaly.reason = kWindowReasonImplausibleGateDuration;
    anomaly.valid = false;
    anomaly.flags |= OTIS_FLAG_GATE_INCOMPLETE;
  } else if (expect_samples && runtime_state->tcxo.last_sample_count == 0u) {
    anomaly.reason = kWindowReasonNoSamples;
    anomaly.valid = false;
    anomaly.flags |= OTIS_FLAG_GATE_INCOMPLETE;
  } else if (expect_samples &&
             runtime_state->tcxo.last_zero_sample_count ==
                 runtime_state->tcxo.last_sample_count) {
    anomaly.reason = kWindowReasonAllZeroSamples;
    anomaly.valid = false;
    anomaly.flags |= OTIS_FLAG_INPUT_STUCK_LOW;
  } else if (expect_samples &&
             runtime_state->tcxo.last_zero_sample_count > 0u) {
    anomaly.reason = kWindowReasonPartialZeroSamples;
    anomaly.valid = false;
    anomaly.flags |= OTIS_FLAG_SOURCE_HEALTH_SUSPECT;
  } else if (expect_counted_edges &&
             runtime_state->tcxo.last_counted_edges == 0ull) {
    anomaly.reason = kWindowReasonCountedEdgesZero;
    anomaly.valid = false;
    anomaly.flags |= OTIS_FLAG_INPUT_STUCK_LOW;
  }

  runtime_state->tcxo.last_window_flags = anomaly.flags;
  runtime_state->tcxo.last_window_invalid_reason = anomaly.reason;
  return anomaly;
}

void record_window_quality(OtisRuntimeState *runtime_state,
                           const WindowAnomaly &anomaly) {
  runtime_state->tcxo.last_observation_valid = anomaly.valid;
  if (anomaly.valid) {
    runtime_state->tcxo.consecutive_bad_windows = 0;
  } else {
    runtime_state->tcxo.consecutive_bad_windows += 1u;
    runtime_state->tcxo.total_bad_windows += 1u;
  }
}

void update_control_gate(OtisRuntimeState *runtime_state,
                         const OtisCountObservationConfig *config,
                         WindowAnomaly *anomaly, uint32_t now_ms) {
  update_startup_inhibit(runtime_state, config, now_ms);

  if (!anomaly->valid) {
    runtime_state->tcxo.control_clean_window_count = 0;
    runtime_state->tcxo.valid_for_control = false;
    if (!runtime_state->tcxo.startup_inhibit_active) {
      runtime_state->tcxo.fault_after_startup = true;
    }
    anomaly->post_startup_invalid = !runtime_state->tcxo.startup_inhibit_active;
    return;
  }

  if (runtime_state->tcxo.startup_inhibit_active) {
    runtime_state->tcxo.control_clean_window_count = 0;
    runtime_state->tcxo.valid_for_control = false;
    return;
  }

  if (runtime_state->tcxo.control_clean_window_count < UINT32_MAX) {
    runtime_state->tcxo.control_clean_window_count += 1u;
  }
  runtime_state->tcxo.valid_for_control =
      runtime_state->tcxo.control_clean_window_count >=
      config->control_ready_clean_windows;
  if (runtime_state->tcxo.valid_for_control) {
    runtime_state->tcxo.fault_after_startup = false;
  }
}

void emit_count_observation(OtisRuntimeState *runtime_state,
                            const OtisCountObservationConfig *config,
                            uint64_t counted_edges, uint32_t flags) {
  otis_emit_count_observation(
      runtime_state->sequences.count_seq++, OTIS_CHANNEL_OSC_OBSERVATION,
      runtime_state->tcxo.last_gate_open_ticks,
      runtime_state->tcxo.last_gate_close_ticks, OTIS_DOMAIN_RP2040_TIMER0,
      counted_edges, OTIS_EDGE_RISING, config->source_domain, flags);
}

}  // namespace

void otis_count_observation_begin(OtisRuntimeState *runtime_state,
                                  OtisStatusEmitContext *status_context,
                                  const OtisCountObservationConfig *config) {
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0
  (void)runtime_state;
  (void)config;
  gpio_set_function(OTIS_GPIO_OSC_OBSERVATION, GPIO_FUNC_GPCK);
  emit_status(status_context, "capture", "tcxo_counter_backend",
              "rp2040_fc0_gpin0", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE
  (void)runtime_state;
  bool counter_ok = begin_h1_pio_long_gate_counter();
  emit_status(status_context, "capture", "tcxo_counter_backend",
              "pio_long_gate_gpio20", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(status_context, "capture", "pio_long_gate_init",
              counter_ok ? "ok" : "failed",
              counter_ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              counter_ok ? OTIS_FLAG_PROFILE_ASSUMPTION
                         : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32(status_context, "capture", "pio_long_gate_gpio",
                  OTIS_GPIO_OSC_OBSERVATION, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(status_context, "capture", "pio_long_gate_period_us",
                  config->gate_period_us, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
  (void)runtime_state;
  bool counter_ok = begin_h1_pio_long_gate_counter();
  pinMode(OTIS_PIN_PPS_REFERENCE, INPUT_PULLDOWN);
  pps_gated_ratio.state = counter_ok ? PpsGateState::Armed
                                     : PpsGateState::Fault;
  pps_gated_ratio.pps_level_high = digitalRead(OTIS_PIN_PPS_REFERENCE) == HIGH;
  pps_gated_ratio.last_pps_ticks = 0;
  pps_gated_ratio.gate_open_ticks = 0;
  pps_gated_ratio.accepted_window_count = 0;
  pps_gated_ratio.rejected_window_count = 0;
  pps_gated_ratio.missing_pps_count = 0;
  pps_gated_ratio.pps_interval_anomaly_count = 0;
  pps_gated_ratio.count_saturated_count = 0;
  pps_gated_ratio.last_reason = counter_ok ? kWindowReasonNone
                                           : "counter_init_failed";
  emit_status(status_context, "capture", "tcxo_counter_backend",
              "pps_gated_ratio", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(status_context, "capture", "pps_gated_ratio_init",
              counter_ok ? "ok" : "failed",
              counter_ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              counter_ok ? OTIS_FLAG_PROFILE_ASSUMPTION
                         : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32(status_context, "pps_gate", "pps_gpio",
                  OTIS_PIN_PPS_REFERENCE, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "osc_gpio",
                  OTIS_GPIO_OSC_OBSERVATION, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "min_interval_us",
                  OTIS_PPS_GATE_MIN_INTERVAL_US, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "max_interval_us",
                  OTIS_PPS_GATE_MAX_INTERVAL_US, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(status_context, "pps_gate", "missing_timeout_us",
                  OTIS_PPS_GATE_MISSING_TIMEOUT_US, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_pps_gate_status(status_context,
                       counter_ok ? OTIS_SEVERITY_INFO
                                  : OTIS_SEVERITY_ERROR,
                       counter_ok ? OTIS_FLAG_PROFILE_ASSUMPTION
                                  : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ
  pinMode(OTIS_PIN_OSC_OBSERVATION, INPUT_PULLDOWN);
  runtime_state->tcxo.gate_open_us = micros();
  emit_status(status_context, "capture", "tcxo_counter_backend",
              "gpio_irq_divided_only", OTIS_SEVERITY_WARN,
              OTIS_FLAG_RATE_TOO_HIGH);
  otis_capture_irq_begin_tcxo_counter(OTIS_PIN_OSC_OBSERVATION);
#endif
}

bool otis_count_observation_service(OtisRuntimeState *runtime_state,
                                    OtisStatusEmitContext *status_context,
                                    const OtisCountObservationConfig *config) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0
  uint32_t now_ms = millis();
  if ((uint32_t)(now_ms - runtime_state->tcxo.last_measure_ms) <
      config->measure_period_ms) {
    return false;
  }
  runtime_state->tcxo.last_measure_ms = now_ms;

  uint64_t gate_open_ticks = otis_capture_ticks_now();
  uint32_t measured_khz = frequency_count_khz(CLOCKS_FC0_SRC_VALUE_CLKSRC_GPIN0);
  uint64_t gate_close_ticks = otis_capture_ticks_now();
  uint64_t elapsed_us = (gate_close_ticks - gate_open_ticks) / 16ull;

  if (!runtime_state->tcxo.fc0_accum_active) {
    start_fc0_accum_window(runtime_state, gate_open_ticks);
  }

  record_fc0_sample(runtime_state, measured_khz, elapsed_us);

  uint64_t emitted_gate_close_ticks = gate_close_ticks;
  if (emitted_gate_close_ticks < runtime_state->tcxo.fc0_accum_gate_open_ticks) {
    emitted_gate_close_ticks += kRp2040Timer0MicrosWrapTicks;
  }
  uint64_t observation_span_us =
      (emitted_gate_close_ticks -
       runtime_state->tcxo.fc0_accum_gate_open_ticks) /
      16ull;
  if (observation_span_us < config->gate_period_us) {
    return false;
  }

  uint32_t averaged_khz = 0;
  if (runtime_state->tcxo.fc0_accum_elapsed_us > 0) {
    averaged_khz =
        (uint32_t)(runtime_state->tcxo.fc0_accum_weighted_khz_us /
                   runtime_state->tcxo.fc0_accum_elapsed_us);
  }
  uint64_t counted_edges =
      ((uint64_t)averaged_khz * observation_span_us) / 1000ull;
  uint32_t window_flags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;
  if (runtime_state->tcxo.fc0_accum_zero_sample_count > 0u) {
    if (runtime_state->tcxo.fc0_accum_zero_sample_count ==
        runtime_state->tcxo.fc0_accum_sample_count) {
      window_flags |= OTIS_FLAG_INPUT_STUCK_LOW;
    } else {
      window_flags |= OTIS_FLAG_SOURCE_HEALTH_SUSPECT;
    }
  }

  runtime_state->tcxo.last_gate_open_ticks =
      runtime_state->tcxo.fc0_accum_gate_open_ticks;
  runtime_state->tcxo.last_gate_close_ticks = emitted_gate_close_ticks;
  runtime_state->tcxo.last_counted_edges = counted_edges;
  runtime_state->tcxo.last_elapsed_us = (uint32_t)observation_span_us;
  runtime_state->tcxo.last_measured_khz = averaged_khz;
  runtime_state->tcxo.last_sampled_elapsed_us =
      (uint32_t)runtime_state->tcxo.fc0_accum_elapsed_us;
  runtime_state->tcxo.last_sample_count =
      runtime_state->tcxo.fc0_accum_sample_count;
  runtime_state->tcxo.last_zero_sample_count =
      runtime_state->tcxo.fc0_accum_zero_sample_count;
  runtime_state->tcxo.last_valid_sample_count =
      runtime_state->tcxo.fc0_accum_sample_count -
      runtime_state->tcxo.fc0_accum_zero_sample_count;
  runtime_state->tcxo.last_first_sample_khz =
      runtime_state->tcxo.fc0_accum_first_sample_khz;
  runtime_state->tcxo.last_last_sample_khz =
      runtime_state->tcxo.fc0_accum_last_sample_khz;
  runtime_state->tcxo.last_min_sample_khz =
      runtime_state->tcxo.fc0_accum_min_sample_khz;
  runtime_state->tcxo.last_max_sample_khz =
      runtime_state->tcxo.fc0_accum_max_sample_khz;
  runtime_state->tcxo.last_window_flags = window_flags;
  WindowAnomaly anomaly = classify_window(runtime_state, config, true, true);
  update_control_gate(runtime_state, config, &anomaly, now_ms);
  record_window_quality(runtime_state, anomaly);

  emit_count_observation(runtime_state, config, counted_edges,
                         runtime_state->tcxo.last_window_flags);

  if (!anomaly.valid) {
    emit_bad_window_diagnostics(runtime_state, status_context, anomaly);
  }

  reset_fc0_accum_window(runtime_state);
  return true;
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE
  if (!h1_pio_long_gate.initialized) {
    return false;
  }

  uint32_t now_ms = millis();
  uint64_t now_ticks = otis_capture_ticks_now();
  if (!h1_pio_long_gate.active) {
    start_h1_pio_long_gate_counter(now_ticks);
    return false;
  }

  uint64_t emitted_gate_close_ticks = now_ticks;
  if (emitted_gate_close_ticks < h1_pio_long_gate.gate_open_ticks) {
    emitted_gate_close_ticks += kRp2040Timer0MicrosWrapTicks;
  }
  uint64_t observation_span_us =
      (emitted_gate_close_ticks - h1_pio_long_gate.gate_open_ticks) / 16ull;
  if (observation_span_us < config->gate_period_us) {
    return false;
  }

  uint32_t remaining = stop_h1_pio_long_gate_counter();
  uint64_t counted_edges =
      (uint64_t)kH1PioCounterInitialX - (uint64_t)remaining;
  uint32_t measured_khz = 0;
  if (observation_span_us > 0) {
    measured_khz = (uint32_t)((counted_edges * 1000ull) / observation_span_us);
  }
  uint32_t window_flags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;
  bool counted_edges_nonzero = counted_edges > 0ull;

  runtime_state->tcxo.last_gate_open_ticks = h1_pio_long_gate.gate_open_ticks;
  runtime_state->tcxo.last_gate_close_ticks = emitted_gate_close_ticks;
  runtime_state->tcxo.last_counted_edges = counted_edges;
  runtime_state->tcxo.last_elapsed_us = (uint32_t)observation_span_us;
  runtime_state->tcxo.last_measured_khz = measured_khz;
  runtime_state->tcxo.last_sampled_elapsed_us = (uint32_t)observation_span_us;
  runtime_state->tcxo.last_sample_count = 1u;
  runtime_state->tcxo.last_zero_sample_count = counted_edges_nonzero ? 0u : 1u;
  runtime_state->tcxo.last_valid_sample_count = counted_edges_nonzero ? 1u : 0u;
  runtime_state->tcxo.last_first_sample_khz = measured_khz;
  runtime_state->tcxo.last_last_sample_khz = measured_khz;
  runtime_state->tcxo.last_min_sample_khz = measured_khz;
  runtime_state->tcxo.last_max_sample_khz = measured_khz;
  runtime_state->tcxo.last_window_flags = window_flags;
  WindowAnomaly anomaly = classify_window(runtime_state, config, false, true);
  update_control_gate(runtime_state, config, &anomaly, now_ms);
  record_window_quality(runtime_state, anomaly);

  emit_count_observation(runtime_state, config, counted_edges,
                         runtime_state->tcxo.last_window_flags);

  if (!anomaly.valid) {
    emit_bad_window_diagnostics(runtime_state, status_context, anomaly);
  }

  start_h1_pio_long_gate_counter(otis_capture_ticks_now());
  return true;
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
  if (!h1_pio_long_gate.initialized) {
    return false;
  }

  uint32_t now_ms = millis();
  update_startup_inhibit(runtime_state, config, now_ms);

  uint64_t now_ticks = otis_capture_ticks_now();
  if (pps_gated_ratio.state == PpsGateState::Open) {
    uint64_t timeout_ticks = now_ticks;
    if (timeout_ticks < pps_gated_ratio.gate_open_ticks) {
      timeout_ticks += kRp2040Timer0MicrosWrapTicks;
    }
    uint64_t open_us =
        (timeout_ticks - pps_gated_ratio.gate_open_ticks) / 16ull;
    if (open_us > OTIS_PPS_GATE_MISSING_TIMEOUT_US) {
      stop_h1_pio_long_gate_counter();
      pps_gated_ratio.missing_pps_count += 1u;
      pps_gated_ratio.last_pps_ticks = 0;
      pps_gated_ratio.gate_open_ticks = 0;
      pps_gated_ratio.state = PpsGateState::Armed;
      runtime_state->tcxo.last_elapsed_us = (uint32_t)open_us;
      emit_pps_gate_fault(runtime_state, status_context, kWindowReasonMissingPps,
                          OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT |
                              OTIS_FLAG_GATE_INCOMPLETE);
      return false;
    }
  }

  uint64_t pps_ticks = 0;
  if (!pps_rising_edge(&pps_ticks)) {
    return false;
  }

  if (pps_gated_ratio.state != PpsGateState::Open) {
    start_h1_pio_long_gate_counter(pps_ticks);
    pps_gated_ratio.state = PpsGateState::Open;
    pps_gated_ratio.last_pps_ticks = pps_ticks;
    pps_gated_ratio.gate_open_ticks = pps_ticks;
    pps_gated_ratio.last_reason = kWindowReasonNone;
    emit_pps_gate_status(status_context, OTIS_SEVERITY_INFO,
                         OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
    return false;
  }

  uint64_t emitted_gate_close_ticks = pps_ticks;
  if (emitted_gate_close_ticks < pps_gated_ratio.gate_open_ticks) {
    emitted_gate_close_ticks += kRp2040Timer0MicrosWrapTicks;
  }
  uint64_t observation_span_us =
      (emitted_gate_close_ticks - pps_gated_ratio.gate_open_ticks) / 16ull;
  uint32_t remaining = stop_h1_pio_long_gate_counter();
  uint64_t counted_edges =
      (uint64_t)kH1PioCounterInitialX - (uint64_t)remaining;
  bool counter_saturated = remaining == 0u;
  uint32_t measured_khz = 0;
  if (observation_span_us > 0ull) {
    measured_khz = (uint32_t)((counted_edges * 1000ull) / observation_span_us);
  }

  runtime_state->tcxo.last_gate_open_ticks = pps_gated_ratio.gate_open_ticks;
  runtime_state->tcxo.last_gate_close_ticks = emitted_gate_close_ticks;
  runtime_state->tcxo.last_counted_edges = counted_edges;
  runtime_state->tcxo.last_elapsed_us = (uint32_t)observation_span_us;
  runtime_state->tcxo.last_measured_khz = measured_khz;
  runtime_state->tcxo.last_sampled_elapsed_us = (uint32_t)observation_span_us;
  runtime_state->tcxo.last_sample_count = 1u;
  runtime_state->tcxo.last_zero_sample_count = counted_edges > 0ull ? 0u : 1u;
  runtime_state->tcxo.last_valid_sample_count = counted_edges > 0ull ? 1u : 0u;
  runtime_state->tcxo.last_first_sample_khz = measured_khz;
  runtime_state->tcxo.last_last_sample_khz = measured_khz;
  runtime_state->tcxo.last_min_sample_khz = measured_khz;
  runtime_state->tcxo.last_max_sample_khz = measured_khz;
  runtime_state->tcxo.last_window_flags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;

  WindowAnomaly anomaly = classify_window(runtime_state, config, false, true);
  if (!pps_interval_valid(observation_span_us)) {
    anomaly.reason = kWindowReasonPpsIntervalAnomaly;
    anomaly.valid = false;
    anomaly.flags |= OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT |
                     OTIS_FLAG_GATE_INCOMPLETE;
    pps_gated_ratio.pps_interval_anomaly_count += 1u;
  }
  if (counter_saturated) {
    anomaly.reason = kWindowReasonCounterSaturated;
    anomaly.valid = false;
    anomaly.flags |= OTIS_FLAG_COUNT_SATURATED;
    pps_gated_ratio.count_saturated_count += 1u;
  }
  runtime_state->tcxo.last_window_flags = anomaly.flags;
  runtime_state->tcxo.last_window_invalid_reason = anomaly.reason;

  update_control_gate(runtime_state, config, &anomaly, now_ms);
  record_window_quality(runtime_state, anomaly);
  if (anomaly.valid) {
    pps_gated_ratio.accepted_window_count += 1u;
  } else {
    pps_gated_ratio.rejected_window_count += 1u;
  }
  pps_gated_ratio.last_reason = anomaly.reason;

  emit_count_observation(runtime_state, config, counted_edges,
                         runtime_state->tcxo.last_window_flags);
  emit_pps_gate_window_status(runtime_state, status_context, anomaly,
                              anomaly.valid && counted_edges > 0ull);
  if (!anomaly.valid) {
    emit_bad_window_diagnostics(runtime_state, status_context, anomaly);
  }

  start_h1_pio_long_gate_counter(pps_ticks);
  pps_gated_ratio.state = PpsGateState::Open;
  pps_gated_ratio.last_pps_ticks = pps_ticks;
  pps_gated_ratio.gate_open_ticks = pps_ticks;
  return true;
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ
  uint32_t now_us = micros();
  if ((uint32_t)(now_us - runtime_state->tcxo.gate_open_us) <
      config->gate_period_us) {
    return false;
  }

  noInterrupts();
  uint32_t counted_edges = otis_capture_irq_read_and_reset_tcxo_count();
  uint32_t gate_open_us = runtime_state->tcxo.gate_open_us;
  runtime_state->tcxo.gate_open_us = now_us;
  interrupts();

  uint32_t flags = OTIS_FLAG_NONE;
  bool counted_edges_nonzero = counted_edges > 0u;
  runtime_state->tcxo.last_gate_open_ticks = (uint64_t)gate_open_us * 16ull;
  runtime_state->tcxo.last_gate_close_ticks = (uint64_t)now_us * 16ull;
  runtime_state->tcxo.last_counted_edges = counted_edges;
  runtime_state->tcxo.last_elapsed_us = now_us - gate_open_us;
  runtime_state->tcxo.last_measured_khz = 0;
  runtime_state->tcxo.last_sampled_elapsed_us = runtime_state->tcxo.last_elapsed_us;
  runtime_state->tcxo.last_sample_count = 1u;
  runtime_state->tcxo.last_zero_sample_count = counted_edges_nonzero ? 0u : 1u;
  runtime_state->tcxo.last_valid_sample_count = counted_edges_nonzero ? 1u : 0u;
  runtime_state->tcxo.last_first_sample_khz = 0;
  runtime_state->tcxo.last_last_sample_khz = 0;
  runtime_state->tcxo.last_min_sample_khz = 0;
  runtime_state->tcxo.last_max_sample_khz = 0;
  runtime_state->tcxo.last_window_flags = flags;
  WindowAnomaly anomaly = classify_window(runtime_state, config, false, true);
  update_control_gate(runtime_state, config, &anomaly, millis());
  record_window_quality(runtime_state, anomaly);
  emit_count_observation(runtime_state, config, counted_edges,
                         runtime_state->tcxo.last_window_flags);
  if (!anomaly.valid) {
    emit_bad_window_diagnostics(runtime_state, status_context, anomaly);
  }
  return true;
#endif
#else
  (void)runtime_state;
  (void)status_context;
  (void)config;
  return false;
#endif
}

const char *otis_count_observation_measurement_mode(void) {
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE
  return "raw_edge_long_gate";
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
  return "pps_gated_ratio";
#else
  return "short_frequency_gate";
#endif
}

const char *otis_count_observation_window_invalid_reason(
    const OtisRuntimeState *runtime_state) {
  return runtime_state->tcxo.last_window_invalid_reason;
}
