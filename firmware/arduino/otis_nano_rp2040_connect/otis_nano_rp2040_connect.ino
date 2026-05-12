#include <Arduino.h>

#include "otis_board.h"
#include "otis_boot_diag.h"
#include "otis_protocol.h"
#include "otis_records.h"
#include "otis_status_led.h"

void setup() {
  otis_status_led_begin();

  Serial.begin(115200);
  delay(1500);
  otis_status_led_set(OTIS_SYSTEM_STATE_BOOT_STARTING);
  otis_status_led_poll(millis());

#if OTIS_ENABLE_RP2040_BOOT_DIAG
  emitRp2040BootDiag(Serial);
#endif

  otis_emit_csv_headers();
  otis_emit_health(1u, 1600000000ull, OTIS_DOMAIN_RP2040_TIMER0,
                   "system", "boot", "true", OTIS_SEVERITY_INFO,
                   OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_emit_health(2u, 1600000001ull, OTIS_DOMAIN_RP2040_TIMER0,
                   "system", "arduino_core", OTIS_TARGET_ARDUINO_CORE,
                   OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_emit_health(3u, 1600000002ull, OTIS_DOMAIN_RP2040_TIMER0,
                   "system", "board", OTIS_TARGET_BOARD, OTIS_SEVERITY_INFO,
                   OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_emit_raw_event(OTIS_RECORD_EVT, 1000u, OTIS_CHANNEL_GENERIC_EVENT,
                      OTIS_EDGE_RISING, 1600001234ull,
                      OTIS_DOMAIN_RP2040_TIMER0, OTIS_FLAG_NONE);
  otis_emit_raw_event(OTIS_RECORD_EVT, 1001u, OTIS_CHANNEL_GENERIC_EVENT,
                      OTIS_EDGE_FALLING, 1600001872ull,
                      OTIS_DOMAIN_RP2040_TIMER0, OTIS_FLAG_NONE);
  otis_emit_raw_event(OTIS_RECORD_REF, 1002u, OTIS_CHANNEL_PPS_REFERENCE,
                      OTIS_EDGE_RISING, 1616000000ull,
                      OTIS_DOMAIN_RP2040_TIMER0, OTIS_FLAG_NONE);
  otis_emit_count_observation(1u, OTIS_CHANNEL_OSC_OBSERVATION,
                              1600000000ull, 1616000000ull,
                              OTIS_DOMAIN_RP2040_TIMER0, 16000000ull,
                              OTIS_EDGE_RISING, OTIS_DOMAIN_H0_TCXO_16MHZ,
                              OTIS_FLAG_NONE);
}

void loop() { otis_status_led_poll(millis()); }
