#include <Arduino.h>
#include <ctype.h>
#include <hardware/clocks.h>
#include <hardware/gpio.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "otis_config.h"

#include "OtisBootConfig.h"
#include "otis_board.h"
#include "otis_boot_diag.h"
#include "otis_capture_backend.h"
#include "otis_capture_irq.h"
#include "otis_capture_ring.h"
#include "otis_dac_ad5693r.h"
#include "otis_emit.h"
#include "otis_modes.h"
#include "otis_protocol.h"
#include "otis_runtime_state.h"
#include "otis_status_emit.h"
#include "otis_status_led.h"
#include "otis_timebase.h"
#include "otis_transport_serial.h"

namespace {

constexpr uint32_t kStatusPeriodMs = OTIS_STATUS_PERIOD_MS;
constexpr uint32_t kLoopbackTogglePeriodMs = OTIS_LOOPBACK_TOGGLE_PERIOD_MS;
constexpr uint32_t kTcxoGatePeriodUs = OTIS_TCXO_GATE_PERIOD_US;
constexpr uint32_t kTcxoMeasurePeriodMs = OTIS_TCXO_MEASURE_PERIOD_MS;

OtisRuntimeState runtime_state;
OtisStatusEmitContext status_emit_context;
char serial_command_line[64];
uint8_t serial_command_len = 0;

void enter_boot_phase(BootPhase next_phase) {
  runtime_state.boot.phase = next_phase;
}

void complete_boot_phase(BootPhase completed_phase) {
  otisBootBreadcrumbCompletePhase(completed_phase);
}

void emit_boot_records_if_serial_ready(void) {
  if (runtime_state.boot.summary_emitted || !otis_transport_ready()) {
    return;
  }

  emitOtisBootSummary(Serial, runtime_state.boot.phase);
  if (runtime_state.boot.serial_absent_warn_pending) {
    emitOtisBootWarnSerialAbsent(Serial, kOtisSerialWaitMs);
    runtime_state.boot.serial_absent_warn_pending = false;
  }
  if (runtime_state.boot.safe_mode_warn_pending) {
    emitOtisBootWarnSafeMode(Serial);
    runtime_state.boot.safe_mode_warn_pending = false;
  }
  runtime_state.boot.summary_emitted = true;
}

void wait_for_serial_or_timeout(void) {
  uint32_t serial_wait_start_ms = millis();
  while (!otis_transport_ready() &&
         (uint32_t)(millis() - serial_wait_start_ms) < kOtisSerialWaitMs) {
    delay(1);
  }
  runtime_state.boot.serial_ready = otis_transport_ready();
  runtime_state.boot.serial_absent_warn_pending =
      !runtime_state.boot.serial_ready;
}

void halt_boot(BootFatal fatal, BootPhase failed_phase) {
  enter_boot_phase(BootPhase::Fatal);
  otisBootBreadcrumbSetFatal(fatal);
  otis_status_led_set(OTIS_SYSTEM_STATE_FATAL_CONFIG_FAULT);

  bool fatal_emitted = false;
  if (otis_transport_ready()) {
    emit_boot_records_if_serial_ready();
    emitOtisBootFatal(Serial, fatal, failed_phase);
    fatal_emitted = true;
  }

  while (true) {
    if (otis_transport_ready() && !fatal_emitted) {
      emit_boot_records_if_serial_ready();
      emitOtisBootFatal(Serial, fatal, failed_phase);
      fatal_emitted = true;
    }
    otis_status_led_poll(millis());
    delay(10);
  }
}

void enter_safe_mode(void) {
  runtime_state.boot.safe_mode_active = true;
  runtime_state.boot.safe_mode_warn_pending = true;
  enter_boot_phase(BootPhase::Fatal);
  otisBootBreadcrumbSetSafeModeFatal(BootFatal::RepeatedBootFailure);

  otis_status_led_begin();
  otis_transport_begin(kOtisSerialBaud);
  wait_for_serial_or_timeout();
  otis_status_led_set(OTIS_SYSTEM_STATE_FATAL_CONFIG_FAULT);
  emit_boot_records_if_serial_ready();
}

const char *edge_string(char edge);
const char *osc_observation_domain(void);

void emit_status(const char *component, const char *key, const char *value,
                 const char *severity, uint32_t flags) {
  otis_status_emit(&status_emit_context, component, key, value, severity,
                   flags);
}

void emit_status_u32(const char *component, const char *key, uint32_t value,
                     const char *severity, uint32_t flags) {
  otis_status_emit_u32(&status_emit_context, component, key, value, severity,
                       flags);
}

void emit_status_u16_hex(const char *component, const char *key, uint16_t value,
                         const char *severity, uint32_t flags) {
  char buffer[7];
  snprintf(buffer, sizeof(buffer), "0x%04X", value);
  emit_status(component, key, buffer, severity, flags);
}

void emit_status_u64_decimal(const char *component, const char *key,
                             uint64_t value, const char *severity,
                             uint32_t flags) {
  char buffer[21];
  snprintf(buffer, sizeof(buffer), "%llu",
           static_cast<unsigned long long>(value));
  emit_status(component, key, buffer, severity, flags);
}

void emit_captured_edge(const OtisCapturedEdge &record) {
  otis_emit_raw_event(record.reference_record ? OTIS_RECORD_REF : OTIS_RECORD_EVT,
                      runtime_state.sequences.event_seq++, record.channel_id,
                      edge_string(record.edge), record.timestamp_ticks,
                      OTIS_DOMAIN_RP2040_TIMER0, record.flags);
  runtime_state.capture.emitted_event_count++;
}

const char *edge_string(char edge) {
  if (edge == 'R') {
    return OTIS_EDGE_RISING;
  }
  if (edge == 'F') {
    return OTIS_EDGE_FALLING;
  }
  return OTIS_EDGE_BOTH_OR_UNSPECIFIED;
}

const char *osc_observation_domain(void) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  return OTIS_DOMAIN_H1_OCXO_OPEN_LOOP;
#else
  return OTIS_DOMAIN_H0_TCXO_16MHZ;
#endif
}

void drain_capture_ring(void) {
  OtisCapturedEdge record;
  while (otis_capture_ring_pop(&record)) {
    emit_captured_edge(record);
  }
}

void emit_common_boot_status(void) {
  emit_status("system", "boot", "true", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("protocol", "schema_version", OTIS_SCHEMA_VERSION_V1,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "name", OTIS_FIRMWARE_NAME, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "version", OTIS_FIRMWARE_VERSION, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "git_commit", OTIS_FIRMWARE_GIT_COMMIT,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "mode", otis_bringup_mode_name(), OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("capture", "mode", OTIS_CAPTURE_MODE, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
  emit_status("capture", "timestamp_latch", "pio_edge_detect_cpu_timestamped",
              OTIS_SEVERITY_WARN, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status("capture", "limitation",
              "pio_detects_rising_edges_cpu_attaches_drain_timestamp_dma_deferred",
              OTIS_SEVERITY_WARN, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
#else
  emit_status("capture", "timestamp_latch", "irq_micros_reconstructed",
              OTIS_SEVERITY_WARN, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status("capture", "limitation",
              "bench_validation_not_final_pio_dma_metrology",
              OTIS_SEVERITY_WARN, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
#endif
  emit_status_u32("capture", "nominal_capture_clock_hz",
                  OTIS_NOMINAL_CAPTURE_CLOCK_HZ, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("reference", "nominal_pps_hz", OTIS_NOMINAL_PPS_HZ,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("reference", "nominal_tcxo_hz", OTIS_NOMINAL_TCXO_HZ,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("reference", "nominal_ocxo_hz", OTIS_NOMINAL_OCXO_HZ,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("capture", "fc0_measure_period_ms", kTcxoMeasurePeriodMs,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "arduino_core", OTIS_TARGET_ARDUINO_CORE,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "board", OTIS_TARGET_BOARD, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_rp2040_boot_diag",
                  OTIS_ENABLE_RP2040_BOOT_DIAG, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_status_led", OTIS_ENABLE_STATUS_LED,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "capture_backend", otis_capture_backend_name(),
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "tcxo_counter_backend",
              otis_tcxo_counter_backend_name(),
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_dac_ad5693r", OTIS_ENABLE_DAC_AD5693R,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("dac", "i2c_address", OTIS_DAC_AD5693R_I2C_ADDRESS,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u16_hex("dac", "min_code", OTIS_DAC_MIN_CODE,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u16_hex("dac", "max_code", OTIS_DAC_MAX_CODE,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
}

void emit_h0_pin_status(void) {
  emit_status("pins", "ch0_generic_event", "D10", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("pins", "ch1_pps_reference", "D14", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("pins", "ch2_osc_observation", "D8_GPIO20_GPIN0",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
}

void emit_periodic_status(void) {
  uint32_t now_ms = millis();
  if ((uint32_t)(now_ms - runtime_state.periodic.last_status_ms) <
      kStatusPeriodMs) {
    return;
  }
  runtime_state.periodic.last_status_ms = now_ms;

  uint32_t capture_dropped_count = otis_capture_ring_dropped_count();
  uint32_t drop_flag = OTIS_FLAG_NONE;
  if (capture_dropped_count) {
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
    drop_flag = OTIS_FLAG_CAPTURE_OVERFLOW_NEARBY;
#else
    drop_flag = OTIS_FLAG_CAPTURE_RING_OVERRUN;
#endif
  }

  emit_status_u32("system", "uptime_seconds", now_ms / 1000u,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("capture", "event_count",
                  runtime_state.capture.emitted_event_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("capture", "dropped_count", capture_dropped_count,
                  capture_dropped_count ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
                  drop_flag);
  emit_status_u32("capture", "error_flags", drop_flag,
                  capture_dropped_count ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
                  drop_flag);
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
  OtisCaptureBackendStats backend_stats;
  otis_capture_backend_get_stats(&backend_stats);
  emit_status_u32("capture", "pio_fifo_drained_event_count",
                  backend_stats.pio_edges, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("capture", "pio_fifo_empty_count",
                  backend_stats.pio_fifo_empty_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("capture", "pio_fifo_overflow_drop_count",
                  backend_stats.backend_overflows,
                  backend_stats.backend_overflows ? OTIS_SEVERITY_WARN
                                                  : OTIS_SEVERITY_INFO,
                  backend_stats.backend_overflows
                      ? OTIS_FLAG_CAPTURE_OVERFLOW_NEARBY
                      : OTIS_FLAG_NONE);
  emit_status_u32("capture", "pio_fifo_max_drain_batch",
                  backend_stats.pio_fifo_max_drain_batch, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
#endif
}

bool begin_edge_capture_backend(uint32_t gpio, uint32_t channel_id,
                                bool reference_record, int interrupt_mode) {
  OtisCaptureBackendConfig config = {
      gpio,
      channel_id,
      reference_record,
      interrupt_mode,
      emit_captured_edge,
  };
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
  return otis_capture_backend_begin(OtisCaptureBackendKind::PioEdgeQueue,
                                    config);
#else
  return otis_capture_backend_begin(OtisCaptureBackendKind::GpioIrq, config);
#endif
}

void emit_synthetic_fixture(void) {
  otis_emit_raw_event(OTIS_RECORD_EVT, runtime_state.sequences.event_seq++,
                      OTIS_CHANNEL_GENERIC_EVENT, OTIS_EDGE_RISING,
                      1600001234ull, OTIS_DOMAIN_RP2040_TIMER0,
                      OTIS_FLAG_NONE);
  otis_emit_raw_event(OTIS_RECORD_EVT, runtime_state.sequences.event_seq++,
                      OTIS_CHANNEL_GENERIC_EVENT, OTIS_EDGE_FALLING,
                      1600001872ull, OTIS_DOMAIN_RP2040_TIMER0,
                      OTIS_FLAG_NONE);
  otis_emit_raw_event(OTIS_RECORD_REF, runtime_state.sequences.event_seq++,
                      OTIS_CHANNEL_PPS_REFERENCE, OTIS_EDGE_RISING,
                      1616000000ull, OTIS_DOMAIN_RP2040_TIMER0,
                      OTIS_FLAG_NONE);
  otis_emit_raw_event(OTIS_RECORD_REF, runtime_state.sequences.event_seq++,
                      OTIS_CHANNEL_PPS_REFERENCE, OTIS_EDGE_RISING,
                      1632000000ull, OTIS_DOMAIN_RP2040_TIMER0,
                      OTIS_FLAG_NONE);
  otis_emit_count_observation(runtime_state.sequences.count_seq++,
                              OTIS_CHANNEL_OSC_OBSERVATION, 1600000000ull,
                              1616000000ull, OTIS_DOMAIN_RP2040_TIMER0,
                              16000000ull, OTIS_EDGE_RISING,
                              OTIS_DOMAIN_H0_TCXO_16MHZ, OTIS_FLAG_NONE);
  runtime_state.capture.emitted_event_count = 4;
}

void configure_synthetic_usb_mode(void) {
  emit_synthetic_fixture();
}

void configure_gpio_loopback_mode(void) {
  pinMode(OTIS_PIN_GPIO_LOOPBACK_OUTPUT, OUTPUT);
  digitalWrite(OTIS_PIN_GPIO_LOOPBACK_OUTPUT, LOW);
  pinMode(OTIS_PIN_GENERIC_EVENT, INPUT_PULLDOWN);
  emit_status("pins", "gpio_loopback_output", "D7", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("wiring", "gpio_loopback", "D7_to_D10", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  bool ok = begin_edge_capture_backend(OTIS_PIN_GENERIC_EVENT,
                                       OTIS_CHANNEL_GENERIC_EVENT, false,
                                       CHANGE);
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
  emit_status("capture", "pio_init", ok ? "ok" : "failed",
              ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              ok ? OTIS_FLAG_PROFILE_ASSUMPTION : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("capture", "pio_gpio", OTIS_PIN_GENERIC_EVENT,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("capture", "pio_edge", "R", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
}

void configure_gps_pps_mode(void) {
  pinMode(OTIS_PIN_PPS_REFERENCE, INPUT_PULLDOWN);
  bool ok = begin_edge_capture_backend(OTIS_PIN_PPS_REFERENCE,
                                       OTIS_CHANNEL_PPS_REFERENCE, true,
                                       RISING);
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
  emit_status("capture", "pio_init", ok ? "ok" : "failed",
              ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              ok ? OTIS_FLAG_PROFILE_ASSUMPTION : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("capture", "pio_gpio", OTIS_PIN_PPS_REFERENCE,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("capture", "pio_edge", "R", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
}

void configure_tcxo_observe_mode(void) {
  pinMode(OTIS_PIN_PPS_REFERENCE, INPUT_PULLDOWN);
  // In TCXO observe mode the edge-capture backend, including PIO FIFO when
  // enabled, remains on sparse PPS input. Raw CXO input on D8 / GPIO20 / GPIN0
  // must use the FC0/gated-count counter backend below, not FIFO edge records.
  bool ok = begin_edge_capture_backend(OTIS_PIN_PPS_REFERENCE,
                                       OTIS_CHANNEL_PPS_REFERENCE, true,
                                       RISING);
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
  emit_status("capture", "pio_init", ok ? "ok" : "failed",
              ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              ok ? OTIS_FLAG_PROFILE_ASSUMPTION : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("capture", "pio_gpio", OTIS_PIN_PPS_REFERENCE,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("capture", "pio_edge", "R", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
#endif

#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0
  gpio_set_function(OTIS_GPIO_OSC_OBSERVATION, GPIO_FUNC_GPCK);
  emit_status("capture", "tcxo_counter_backend", "rp2040_fc0_gpin0",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ
  pinMode(OTIS_PIN_OSC_OBSERVATION, INPUT_PULLDOWN);
  runtime_state.tcxo.gate_open_us = micros();
  emit_status("capture", "tcxo_counter_backend", "gpio_irq_divided_only",
              OTIS_SEVERITY_WARN, OTIS_FLAG_RATE_TOO_HIGH);
  otis_capture_irq_begin_tcxo_counter(OTIS_PIN_OSC_OBSERVATION);
#endif
}

void emit_dac_status(const char *component) {
  OtisDacAd5693rStatus status;
  otis_dac_ad5693r_get_status(&status);
  emit_status(component, "enabled", status.enabled ? "true" : "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(component, "initialized", status.initialized ? "true" : "false",
              status.initialized ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              status.enabled ? OTIS_FLAG_NONE : OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(component, "last_write_ok", status.last_write_ok ? "true" : "false",
              status.last_write_ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              OTIS_FLAG_NONE);
  emit_status_u32(component, "i2c_address", status.i2c_address,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u16_hex(component, "min_code", status.min_code,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u16_hex(component, "max_code", status.max_code,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u16_hex(component, "last_requested_code",
                      status.last_requested_code, OTIS_SEVERITY_INFO,
                      OTIS_FLAG_NONE);
  emit_status_u16_hex(component, "last_applied_code", status.last_applied_code,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status(component, "gain_mode", status.gain_mode, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(component, "reference_mode", status.reference_mode,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
}

void configure_h1_ocxo_observe_mode(void) {
  emit_status("system", "h1_open_loop", "true", OTIS_SEVERITY_WARN,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("control", "gpsdo_steering", "not_implemented",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  configure_tcxo_observe_mode();

#if OTIS_ENABLE_DAC_AD5693R
  bool ok = otis_dac_ad5693r_begin();
  emit_status("dac", "init", ok ? "ok" : "failed",
              ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              ok ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
#else
  emit_status("dac", "init", "disabled", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
  emit_dac_status("dac");
}

void setup_mode(void) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_SYNTHETIC_USB
  configure_synthetic_usb_mode();
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
  configure_gpio_loopback_mode();
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPS_PPS
  configure_gps_pps_mode();
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE
  configure_tcxo_observe_mode();
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  configure_h1_ocxo_observe_mode();
#endif
}

void boot_phase_reset_entry(void) {
  enter_boot_phase(BootPhase::ResetEntry);
  otisBootBreadcrumbBegin(BootPhase::ResetEntry);
  delay(kOtisBootInitialDelayMs);  // boring but useful during bring-up
  complete_boot_phase(BootPhase::ResetEntry);
}

void boot_phase_early_init(void) {
  enter_boot_phase(BootPhase::EarlyInit);
  complete_boot_phase(BootPhase::EarlyInit);
}

void boot_phase_clocks_init(void) {
  enter_boot_phase(BootPhase::ClocksInit);
#if OTIS_FORCE_BOOT_FAIL_BEFORE_CLOCKS
  halt_boot(BootFatal::ForcedBeforeClocks, BootPhase::ClocksInit);
#endif
  complete_boot_phase(BootPhase::ClocksInit);
}

void boot_phase_gpio_init(void) {
  enter_boot_phase(BootPhase::GpioInit);
  otis_status_led_begin();
  complete_boot_phase(BootPhase::GpioInit);
}

void boot_phase_capture_init(void) {
  enter_boot_phase(BootPhase::CaptureInit);
#if OTIS_FORCE_BOOT_FAIL_BEFORE_CAPTURE
  halt_boot(BootFatal::ForcedBeforeCapture, BootPhase::CaptureInit);
#endif
  complete_boot_phase(BootPhase::CaptureInit);
}

void boot_phase_timer_init(void) {
  enter_boot_phase(BootPhase::TimerInit);
  complete_boot_phase(BootPhase::TimerInit);
}

void boot_phase_pps_input_init(void) {
  enter_boot_phase(BootPhase::PpsInputInit);
  complete_boot_phase(BootPhase::PpsInputInit);
}

void boot_phase_ring_buffers_init(void) {
  enter_boot_phase(BootPhase::RingBuffersInit);
  complete_boot_phase(BootPhase::RingBuffersInit);
}

void boot_phase_serial_init(void) {
  enter_boot_phase(BootPhase::SerialInit);
  otis_transport_begin(kOtisSerialBaud);
  wait_for_serial_or_timeout();

  otis_status_led_boot_test();
  otis_status_led_set(OTIS_SYSTEM_STATE_BOOT_STARTING);
  otis_status_led_poll(millis());
  complete_boot_phase(BootPhase::SerialInit);
}

void boot_phase_protocol_banner(void) {
  enter_boot_phase(BootPhase::ProtocolBanner);
  emit_boot_records_if_serial_ready();

#if OTIS_ENABLE_RP2040_BOOT_DIAG
  emitRp2040BootDiag(Serial);
#endif

  otis_emit_csv_headers();
  emit_common_boot_status();
  emit_h0_pin_status();
  complete_boot_phase(BootPhase::ProtocolBanner);
}

void boot_phase_run_mode(void) {
  enter_boot_phase(BootPhase::RunMode);
#if OTIS_FORCE_BOOT_FAIL_BEFORE_RUN_MODE
  halt_boot(BootFatal::ForcedBeforeRunMode, BootPhase::RunMode);
#endif
  setup_mode();
  runtime_state.periodic.last_status_ms = millis();
  otis_status_led_set(OTIS_SYSTEM_STATE_USB_CONFIG_DEBUG);
  otisBootBreadcrumbMarkRunMode();
}

void service_loopback_output(void) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
  uint32_t now_ms = millis();
  if ((uint32_t)(now_ms - runtime_state.loopback.last_toggle_ms) >=
      kLoopbackTogglePeriodMs) {
    runtime_state.loopback.last_toggle_ms = now_ms;
    runtime_state.loopback.output_high = !runtime_state.loopback.output_high;
    digitalWrite(OTIS_PIN_GPIO_LOOPBACK_OUTPUT,
                 runtime_state.loopback.output_high ? HIGH : LOW);
  }
#endif
}

void service_tcxo_gate(void) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0
  uint32_t now_ms = millis();
  if ((uint32_t)(now_ms - runtime_state.tcxo.last_measure_ms) <
      kTcxoMeasurePeriodMs) {
    return;
  }
  runtime_state.tcxo.last_measure_ms = now_ms;

  uint64_t gate_open_ticks = otis_capture_ticks_now();
  uint32_t measured_khz = frequency_count_khz(CLOCKS_FC0_SRC_VALUE_CLKSRC_GPIN0);
  uint64_t gate_close_ticks = otis_capture_ticks_now();
  uint64_t elapsed_us = (gate_close_ticks - gate_open_ticks) / 16ull;
  uint64_t counted_edges = ((uint64_t)measured_khz * elapsed_us) / 1000ull;
  uint32_t flags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;
  if (measured_khz == 0u) {
    flags |= OTIS_FLAG_INPUT_STUCK_LOW;
  }

  runtime_state.tcxo.last_gate_open_ticks = gate_open_ticks;
  runtime_state.tcxo.last_gate_close_ticks = gate_close_ticks;
  runtime_state.tcxo.last_counted_edges = counted_edges;
  runtime_state.tcxo.last_elapsed_us = (uint32_t)elapsed_us;
  runtime_state.tcxo.last_measured_khz = measured_khz;
  runtime_state.tcxo.last_observation_valid = true;

  otis_emit_count_observation(runtime_state.sequences.count_seq++,
                              OTIS_CHANNEL_OSC_OBSERVATION, gate_open_ticks,
                              gate_close_ticks, OTIS_DOMAIN_RP2040_TIMER0,
                              counted_edges, OTIS_EDGE_RISING,
                              osc_observation_domain(), flags);
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ
  uint32_t now_us = micros();
  if ((uint32_t)(now_us - runtime_state.tcxo.gate_open_us) <
      kTcxoGatePeriodUs) {
    return;
  }

  noInterrupts();
  uint32_t counted_edges = otis_capture_irq_read_and_reset_tcxo_count();
  uint32_t gate_open_us = runtime_state.tcxo.gate_open_us;
  runtime_state.tcxo.gate_open_us = now_us;
  interrupts();

  uint32_t flags = counted_edges == 0 ? OTIS_FLAG_INPUT_STUCK_LOW : OTIS_FLAG_NONE;
  runtime_state.tcxo.last_gate_open_ticks = (uint64_t)gate_open_us * 16ull;
  runtime_state.tcxo.last_gate_close_ticks = (uint64_t)now_us * 16ull;
  runtime_state.tcxo.last_counted_edges = counted_edges;
  runtime_state.tcxo.last_elapsed_us = now_us - gate_open_us;
  runtime_state.tcxo.last_measured_khz = 0;
  runtime_state.tcxo.last_observation_valid = true;
  otis_emit_count_observation(runtime_state.sequences.count_seq++,
                              OTIS_CHANNEL_OSC_OBSERVATION,
                              (uint64_t)gate_open_us * 16ull,
                              (uint64_t)now_us * 16ull, OTIS_DOMAIN_RP2040_TIMER0,
                              counted_edges, OTIS_EDGE_RISING,
                              osc_observation_domain(), flags);
#endif
#endif
}

char *trim_command(char *s) {
  while (*s != '\0' && isspace((unsigned char)*s)) {
    s++;
  }
  char *end = s + strlen(s);
  while (end > s && isspace((unsigned char)*(end - 1))) {
    --end;
    *end = '\0';
  }
  return s;
}

bool parse_u16_code(const char *text, uint16_t *out) {
  if (text == nullptr || out == nullptr || *text == '\0') {
    return false;
  }
  char *end = nullptr;
  unsigned long parsed = strtoul(text, &end, 0);
  if (end == text || *trim_command(end) != '\0' || parsed > 0xFFFFul) {
    return false;
  }
  *out = (uint16_t)parsed;
  return true;
}

void emit_fc0_status(void) {
  emit_status("fc0", "valid",
              runtime_state.tcxo.last_observation_valid ? "true" : "false",
              runtime_state.tcxo.last_observation_valid ? OTIS_SEVERITY_INFO
                                                        : OTIS_SEVERITY_WARN,
              OTIS_FLAG_NONE);
  emit_status_u32("fc0", "measure_period_ms", kTcxoMeasurePeriodMs,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("fc0", "last_measured_khz",
                  runtime_state.tcxo.last_measured_khz, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("fc0", "last_elapsed_us",
                  runtime_state.tcxo.last_elapsed_us, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status_u64_decimal("fc0", "last_counted_edges",
                          runtime_state.tcxo.last_counted_edges,
                          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u64_decimal("fc0", "last_gate_open_ticks",
                          runtime_state.tcxo.last_gate_open_ticks,
                          OTIS_SEVERITY_INFO, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status_u64_decimal("fc0", "last_gate_close_ticks",
                          runtime_state.tcxo.last_gate_close_ticks,
                          OTIS_SEVERITY_INFO, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
}

void handle_dac_set(uint16_t requested_code) {
  emit_status_u16_hex("dac", "requested_code", requested_code,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  if (!otis_dac_ad5693r_is_enabled()) {
    emit_status("dac", "set", "rejected_disabled", OTIS_SEVERITY_WARN,
                OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    return;
  }
  if (!otis_dac_ad5693r_is_initialized()) {
    emit_status("dac", "set", "rejected_not_initialized", OTIS_SEVERITY_WARN,
                OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    return;
  }
  uint16_t clamped = otis_dac_ad5693r_clamp_code(requested_code);
  if (clamped != requested_code) {
    emit_status_u16_hex("dac", "rejected_code", requested_code,
                        OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("dac", "set", "rejected_outside_clamps", OTIS_SEVERITY_WARN,
                OTIS_FLAG_PROFILE_ASSUMPTION);
    return;
  }
  bool ok = otis_dac_ad5693r_set_raw(requested_code);
  emit_status_u16_hex("dac", ok ? "accepted_code" : "failed_code",
                      requested_code,
                      ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
                      ok ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
}

void handle_serial_command(char *line) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  char *command = trim_command(line);
  for (char *p = command; *p != '\0'; ++p) {
    *p = (char)toupper((unsigned char)*p);
  }

  if (strcmp(command, "HELP") == 0) {
    emit_status("command", "h1_help",
                "DAC?_DAC_SET_code_DAC_MID_DAC_ZERO_DAC_LIMITS?_FC0?_HELP",
                OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  } else if (strcmp(command, "DAC?") == 0) {
    emit_dac_status("dac");
  } else if (strcmp(command, "DAC LIMITS?") == 0) {
    emit_status_u16_hex("dac", "min_code", OTIS_DAC_MIN_CODE,
                        OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u16_hex("dac", "max_code", OTIS_DAC_MAX_CODE,
                        OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  } else if (strcmp(command, "DAC MID") == 0) {
    uint16_t mid = (uint16_t)(((uint32_t)OTIS_DAC_MIN_CODE +
                              (uint32_t)OTIS_DAC_MAX_CODE) /
                             2u);
    handle_dac_set(mid);
  } else if (strcmp(command, "DAC ZERO") == 0) {
    handle_dac_set((uint16_t)OTIS_DAC_MIN_CODE);
  } else if (strncmp(command, "DAC SET ", 8) == 0) {
    uint16_t requested_code = 0;
    if (parse_u16_code(command + 8, &requested_code)) {
      handle_dac_set(requested_code);
    } else {
      emit_status("dac", "set", "rejected_parse_error", OTIS_SEVERITY_WARN,
                  OTIS_FLAG_NONE);
    }
  } else if (strcmp(command, "FC0?") == 0) {
    emit_fc0_status();
  } else if (*command != '\0') {
    emit_status("command", "unknown", command, OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
  }
#else
  (void)line;
#endif
}

void service_serial_commands(void) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r' || c == '\n') {
      if (serial_command_len > 0u) {
        serial_command_line[serial_command_len] = '\0';
        handle_serial_command(serial_command_line);
        serial_command_len = 0u;
      }
    } else if (serial_command_len < sizeof(serial_command_line) - 1u) {
      serial_command_line[serial_command_len++] = c;
    } else {
      serial_command_len = 0u;
      emit_status("command", "line", "rejected_too_long", OTIS_SEVERITY_WARN,
                  OTIS_FLAG_NONE);
    }
  }
#endif
}

}  // namespace

void setup() {
  otis_runtime_state_init(&runtime_state);
  otis_status_emit_init(&status_emit_context,
                        &runtime_state.sequences.status_seq);
  boot_phase_reset_entry();
  if (otisBootSafeModeRequested()) {
    enter_safe_mode();
    return;
  }

  boot_phase_early_init();
  boot_phase_clocks_init();
  boot_phase_gpio_init();
  boot_phase_capture_init();
  boot_phase_timer_init();
  boot_phase_pps_input_init();
  boot_phase_ring_buffers_init();
  boot_phase_serial_init();
  boot_phase_protocol_banner();
  boot_phase_run_mode();
}

void loop() {
  if (runtime_state.boot.safe_mode_active) {
    emit_boot_records_if_serial_ready();
    otis_status_led_poll(millis());
    return;
  }

  // Future output-budgeting hook: keep capture service/drain before periodic
  // status emission, then cap max records emitted per loop if host backpressure
  // becomes observable.
  emit_boot_records_if_serial_ready();
  service_serial_commands();
  service_loopback_output();
  service_tcxo_gate();
  otis_capture_backend_service();
  drain_capture_ring();
  emit_periodic_status();
  otis_status_led_poll(millis());
}
