#include <Arduino.h>

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
uint32_t tcxo_gate_open_us = 0;
bool loopback_state = false;

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

void setup_mode(void) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_SYNTHETIC_USB
  emit_synthetic_fixture();
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
  pinMode(OTIS_PIN_GPIO_LOOPBACK_OUTPUT, OUTPUT);
  digitalWrite(OTIS_PIN_GPIO_LOOPBACK_OUTPUT, LOW);
  pinMode(OTIS_PIN_GENERIC_EVENT, INPUT_PULLDOWN);
  emit_status("pins", "gpio_loopback_output", "D7", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("wiring", "gpio_loopback", "D7_to_D10", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  attachInterrupt(digitalPinToInterrupt(OTIS_PIN_GENERIC_EVENT),
                  handle_generic_event_edge, CHANGE);
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPS_PPS
  pinMode(OTIS_PIN_PPS_REFERENCE, INPUT_PULLDOWN);
  attachInterrupt(digitalPinToInterrupt(OTIS_PIN_PPS_REFERENCE),
                  handle_pps_reference_edge, RISING);
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE
  pinMode(OTIS_PIN_PPS_REFERENCE, INPUT_PULLDOWN);
  pinMode(OTIS_PIN_OSC_OBSERVATION, INPUT_PULLDOWN);
  tcxo_gate_open_us = micros();
  attachInterrupt(digitalPinToInterrupt(OTIS_PIN_PPS_REFERENCE),
                  handle_pps_reference_edge, RISING);
  attachInterrupt(digitalPinToInterrupt(OTIS_PIN_OSC_OBSERVATION),
                  handle_tcxo_observation_edge, RISING);
#endif
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
}

}  // namespace

void setup() {
  otis_status_led_begin();

  Serial.begin(115200);
  delay(1500);
  otis_status_led_boot_test();
  otis_status_led_set(OTIS_SYSTEM_STATE_BOOT_STARTING);
  otis_status_led_poll(millis());

#if OTIS_ENABLE_RP2040_BOOT_DIAG
  emitRp2040BootDiag(Serial);
#endif

  otis_emit_csv_headers();
  emit_common_boot_status();
  emit_h0_pin_status();
  setup_mode();
  last_status_ms = millis();
  otis_status_led_set(OTIS_SYSTEM_STATE_USB_CONFIG_DEBUG);
}

void loop() {
  service_loopback_output();
  service_tcxo_gate();
  drain_capture_ring();
  emit_periodic_status();
  otis_status_led_poll(millis());
}
