#include <Arduino.h>
#include <hardware/clocks.h>
#include <hardware/gpio.h>

#include "OtisBootConfig.h"
#include "otis_board.h"
#include "otis_boot_diag.h"
#include "otis_protocol.h"
#include "otis_records.h"
#include "otis_status_led.h"

namespace {

struct CapturedEdge {
  uint32_t channel_id;
  bool reference_record;
  char edge;
  uint64_t timestamp_ticks;
  uint32_t flags;
};

constexpr uint8_t kCaptureRingSize = 32;
constexpr uint32_t kStatusPeriodMs = 1000;
constexpr uint32_t kLoopbackTogglePeriodMs = 250;
constexpr uint32_t kTcxoGatePeriodUs = 1000000;
constexpr uint32_t kTcxoMeasurePeriodMs = 1000;

volatile CapturedEdge capture_ring[kCaptureRingSize];
volatile uint8_t capture_head = 0;
volatile uint8_t capture_tail = 0;
volatile uint32_t capture_dropped_count = 0;
volatile uint32_t tcxo_edge_count = 0;

uint32_t event_seq = 1000;
uint32_t status_seq = 1;
uint32_t count_seq = 1;
uint32_t emitted_event_count = 0;
uint32_t last_status_ms = 0;
uint32_t last_loopback_toggle_ms = 0;
uint32_t last_tcxo_measure_ms = 0;
uint32_t tcxo_gate_open_us = 0;
bool loopback_state = false;
BootPhase boot_phase = BootPhase::ResetEntry;

void enter_boot_phase(BootPhase next_phase) {
  boot_phase = next_phase;
}

uint64_t capture_ticks_now(void) {
  return (uint64_t)micros() * 16ull;
}

const char *bringup_mode_name(void) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_SYNTHETIC_USB
  return "SW1_SYNTHETIC_USB";
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
  return "SW1_GPIO_LOOPBACK";
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPS_PPS
  return "SW1_GPS_PPS";
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE
  return "SW1_TCXO_OBSERVE";
#endif
}

void emit_status(const char *component, const char *key, const char *value,
                 const char *severity, uint32_t flags) {
  otis_emit_health(status_seq++, capture_ticks_now(), OTIS_DOMAIN_RP2040_TIMER0,
                   component, key, value, severity, flags);
}

void emit_status_u32(const char *component, const char *key, uint32_t value,
                     const char *severity, uint32_t flags) {
  char buffer[11];
  snprintf(buffer, sizeof(buffer), "%lu", (unsigned long)value);
  emit_status(component, key, buffer, severity, flags);
}

void push_capture(uint32_t channel_id, bool reference_record, char edge) {
  uint8_t next_head = (uint8_t)((capture_head + 1u) % kCaptureRingSize);
  if (next_head == capture_tail) {
    capture_dropped_count++;
    return;
  }

  capture_ring[capture_head].channel_id = channel_id;
  capture_ring[capture_head].reference_record = reference_record;
  capture_ring[capture_head].edge = edge;
  capture_ring[capture_head].timestamp_ticks = capture_ticks_now();
  capture_ring[capture_head].flags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;
  capture_head = next_head;
}

bool pop_capture(CapturedEdge *record) {
  bool have_record = false;
  noInterrupts();
  if (capture_tail != capture_head) {
    record->channel_id = capture_ring[capture_tail].channel_id;
    record->reference_record = capture_ring[capture_tail].reference_record;
    record->edge = capture_ring[capture_tail].edge;
    record->timestamp_ticks = capture_ring[capture_tail].timestamp_ticks;
    record->flags = capture_ring[capture_tail].flags;
    capture_tail = (uint8_t)((capture_tail + 1u) % kCaptureRingSize);
    have_record = true;
  }
  interrupts();
  return have_record;
}

void handle_generic_event_edge(void) {
  char edge = digitalRead(OTIS_PIN_GENERIC_EVENT) ? 'R' : 'F';
  push_capture(OTIS_CHANNEL_GENERIC_EVENT, false, edge);
}

void handle_pps_reference_edge(void) {
  push_capture(OTIS_CHANNEL_PPS_REFERENCE, true, 'R');
}

void handle_tcxo_observation_edge(void) {
  tcxo_edge_count++;
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

void drain_capture_ring(void) {
  CapturedEdge record;
  while (pop_capture(&record)) {
    otis_emit_raw_event(record.reference_record ? OTIS_RECORD_REF : OTIS_RECORD_EVT,
                        event_seq++, record.channel_id, edge_string(record.edge),
                        record.timestamp_ticks, OTIS_DOMAIN_RP2040_TIMER0,
                        record.flags);
    emitted_event_count++;
  }
}

void emit_common_boot_status(void) {
  emit_status("system", "boot", "true", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "mode", bringup_mode_name(), OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "arduino_core", OTIS_TARGET_ARDUINO_CORE,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "board", OTIS_TARGET_BOARD, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
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
  if ((uint32_t)(now_ms - last_status_ms) < kStatusPeriodMs) {
    return;
  }
  last_status_ms = now_ms;

  emit_status_u32("system", "uptime_seconds", now_ms / 1000u,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("capture", "event_count", emitted_event_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("capture", "dropped_count", capture_dropped_count,
                  capture_dropped_count ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
                  capture_dropped_count ? OTIS_FLAG_CAPTURE_RING_OVERRUN
                                        : OTIS_FLAG_NONE);
  emit_status_u32("capture", "error_flags",
                  capture_dropped_count ? OTIS_FLAG_CAPTURE_RING_OVERRUN
                                        : OTIS_FLAG_NONE,
                  capture_dropped_count ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
                  capture_dropped_count ? OTIS_FLAG_CAPTURE_RING_OVERRUN
                                        : OTIS_FLAG_NONE);
}

void emit_synthetic_fixture(void) {
  otis_emit_raw_event(OTIS_RECORD_EVT, event_seq++, OTIS_CHANNEL_GENERIC_EVENT,
                      OTIS_EDGE_RISING, 1600001234ull,
                      OTIS_DOMAIN_RP2040_TIMER0, OTIS_FLAG_NONE);
  otis_emit_raw_event(OTIS_RECORD_EVT, event_seq++, OTIS_CHANNEL_GENERIC_EVENT,
                      OTIS_EDGE_FALLING, 1600001872ull,
                      OTIS_DOMAIN_RP2040_TIMER0, OTIS_FLAG_NONE);
  otis_emit_raw_event(OTIS_RECORD_REF, event_seq++, OTIS_CHANNEL_PPS_REFERENCE,
                      OTIS_EDGE_RISING, 1616000000ull,
                      OTIS_DOMAIN_RP2040_TIMER0, OTIS_FLAG_NONE);
  otis_emit_raw_event(OTIS_RECORD_REF, event_seq++, OTIS_CHANNEL_PPS_REFERENCE,
                      OTIS_EDGE_RISING, 1632000000ull,
                      OTIS_DOMAIN_RP2040_TIMER0, OTIS_FLAG_NONE);
  otis_emit_count_observation(count_seq++, OTIS_CHANNEL_OSC_OBSERVATION,
                              1600000000ull, 1616000000ull,
                              OTIS_DOMAIN_RP2040_TIMER0, 16000000ull,
                              OTIS_EDGE_RISING, OTIS_DOMAIN_H0_TCXO_16MHZ,
                              OTIS_FLAG_NONE);
  emitted_event_count = 4;
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
  attachInterrupt(digitalPinToInterrupt(OTIS_PIN_GENERIC_EVENT),
                  handle_generic_event_edge, CHANGE);
}

void configure_gps_pps_mode(void) {
  pinMode(OTIS_PIN_PPS_REFERENCE, INPUT_PULLDOWN);
  attachInterrupt(digitalPinToInterrupt(OTIS_PIN_PPS_REFERENCE),
                  handle_pps_reference_edge, RISING);
}

void configure_tcxo_observe_mode(void) {
  pinMode(OTIS_PIN_PPS_REFERENCE, INPUT_PULLDOWN);
  attachInterrupt(digitalPinToInterrupt(OTIS_PIN_PPS_REFERENCE),
                  handle_pps_reference_edge, RISING);

#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0
  gpio_set_function(OTIS_GPIO_OSC_OBSERVATION, GPIO_FUNC_GPCK);
  emit_status("capture", "tcxo_counter_backend", "rp2040_fc0_gpin0",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ
  pinMode(OTIS_PIN_OSC_OBSERVATION, INPUT_PULLDOWN);
  tcxo_gate_open_us = micros();
  emit_status("capture", "tcxo_counter_backend", "gpio_irq_divided_only",
              OTIS_SEVERITY_WARN, OTIS_FLAG_RATE_TOO_HIGH);
  attachInterrupt(digitalPinToInterrupt(OTIS_PIN_OSC_OBSERVATION),
                  handle_tcxo_observation_edge, RISING);
#endif
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
#endif
}

void boot_phase_reset_entry(void) {
  enter_boot_phase(BootPhase::ResetEntry);
  delay(kOtisBootInitialDelayMs);  // boring but useful during bring-up
}

void boot_phase_early_init(void) {
  enter_boot_phase(BootPhase::EarlyInit);
}

void boot_phase_clocks_init(void) {
  enter_boot_phase(BootPhase::ClocksInit);
}

void boot_phase_gpio_init(void) {
  enter_boot_phase(BootPhase::GpioInit);
  otis_status_led_begin();
}

void boot_phase_capture_init(void) {
  enter_boot_phase(BootPhase::CaptureInit);
}

void boot_phase_timer_init(void) {
  enter_boot_phase(BootPhase::TimerInit);
}

void boot_phase_pps_input_init(void) {
  enter_boot_phase(BootPhase::PpsInputInit);
}

void boot_phase_ring_buffers_init(void) {
  enter_boot_phase(BootPhase::RingBuffersInit);
}

void boot_phase_serial_init(void) {
  enter_boot_phase(BootPhase::SerialInit);
  Serial.begin(kOtisSerialBaud);
  delay(kOtisBootSerialSettleDelayMs);
  otis_status_led_boot_test();
  otis_status_led_set(OTIS_SYSTEM_STATE_BOOT_STARTING);
  otis_status_led_poll(millis());
}

void boot_phase_protocol_banner(void) {
  enter_boot_phase(BootPhase::ProtocolBanner);

#if OTIS_ENABLE_RP2040_BOOT_DIAG
  emitRp2040BootDiag(Serial);
#endif

  otis_emit_csv_headers();
  emit_common_boot_status();
  emit_h0_pin_status();
}

void boot_phase_run_mode(void) {
  enter_boot_phase(BootPhase::RunMode);
  setup_mode();
  last_status_ms = millis();
  otis_status_led_set(OTIS_SYSTEM_STATE_USB_CONFIG_DEBUG);
}

void service_loopback_output(void) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
  uint32_t now_ms = millis();
  if ((uint32_t)(now_ms - last_loopback_toggle_ms) >= kLoopbackTogglePeriodMs) {
    last_loopback_toggle_ms = now_ms;
    loopback_state = !loopback_state;
    digitalWrite(OTIS_PIN_GPIO_LOOPBACK_OUTPUT, loopback_state ? HIGH : LOW);
  }
#endif
}

void service_tcxo_gate(void) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0
  uint32_t now_ms = millis();
  if ((uint32_t)(now_ms - last_tcxo_measure_ms) < kTcxoMeasurePeriodMs) {
    return;
  }
  last_tcxo_measure_ms = now_ms;

  uint64_t gate_open_ticks = capture_ticks_now();
  uint32_t measured_khz = frequency_count_khz(CLOCKS_FC0_SRC_VALUE_CLKSRC_GPIN0);
  uint64_t gate_close_ticks = capture_ticks_now();
  uint64_t elapsed_us = (gate_close_ticks - gate_open_ticks) / 16ull;
  uint64_t counted_edges = ((uint64_t)measured_khz * elapsed_us) / 1000ull;
  uint32_t flags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;
  if (measured_khz == 0u) {
    flags |= OTIS_FLAG_INPUT_STUCK_LOW;
  }

  otis_emit_count_observation(count_seq++, OTIS_CHANNEL_OSC_OBSERVATION,
                              gate_open_ticks, gate_close_ticks,
                              OTIS_DOMAIN_RP2040_TIMER0, counted_edges,
                              OTIS_EDGE_RISING, OTIS_DOMAIN_H0_TCXO_16MHZ,
                              flags);
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ
  uint32_t now_us = micros();
  if ((uint32_t)(now_us - tcxo_gate_open_us) < kTcxoGatePeriodUs) {
    return;
  }

  noInterrupts();
  uint32_t counted_edges = tcxo_edge_count;
  tcxo_edge_count = 0;
  uint32_t gate_open_us = tcxo_gate_open_us;
  tcxo_gate_open_us = now_us;
  interrupts();

  uint32_t flags = counted_edges == 0 ? OTIS_FLAG_INPUT_STUCK_LOW : OTIS_FLAG_NONE;
  otis_emit_count_observation(count_seq++, OTIS_CHANNEL_OSC_OBSERVATION,
                              (uint64_t)gate_open_us * 16ull,
                              (uint64_t)now_us * 16ull,
                              OTIS_DOMAIN_RP2040_TIMER0, counted_edges,
                              OTIS_EDGE_RISING, OTIS_DOMAIN_H0_TCXO_16MHZ,
                              flags);
#endif
#endif
}

}  // namespace

void setup() {
  boot_phase_reset_entry();
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
  service_loopback_output();
  service_tcxo_gate();
  drain_capture_ring();
  emit_periodic_status();
  otis_status_led_poll(millis());
}
