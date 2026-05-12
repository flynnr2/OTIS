#ifndef OTIS_STATUS_LED_H
#define OTIS_STATUS_LED_H

#include <stdint.h>

#ifndef OTIS_ENABLE_STATUS_LED
#define OTIS_ENABLE_STATUS_LED 0
#endif

#ifndef OTIS_STATUS_LED_USE_NINA_RGB
#define OTIS_STATUS_LED_USE_NINA_RGB 0
#endif

typedef enum OtisSystemState {
  OTIS_SYSTEM_STATE_UNKNOWN = 0,
  OTIS_SYSTEM_STATE_BOOT_STARTING,
  OTIS_SYSTEM_STATE_WAITING_FOR_PPS_GPS,
  OTIS_SYSTEM_STATE_PPS_SEEN_ACQUIRING,
  OTIS_SYSTEM_STATE_LOCKED_HEALTHY_LOGGING,
  OTIS_SYSTEM_STATE_VALID_CAPTURE_HEARTBEAT,
  OTIS_SYSTEM_STATE_HOLDOVER_DEGRADED,
  OTIS_SYSTEM_STATE_MISSING_OSCILLATOR,
  OTIS_SYSTEM_STATE_FATAL_CONFIG_FAULT,
  OTIS_SYSTEM_STATE_USB_CONFIG_DEBUG,
  OTIS_SYSTEM_STATE_HOST_API_WIFI_ACTIVITY,
} OtisSystemState;

#if OTIS_ENABLE_STATUS_LED

void otis_status_led_begin(void);
void otis_status_led_set(OtisSystemState state);
void otis_status_led_poll(uint32_t now_ms);

#else

static inline void otis_status_led_begin(void) {}
static inline void otis_status_led_set(OtisSystemState state) {
  (void)state;
}
static inline void otis_status_led_poll(uint32_t now_ms) {
  (void)now_ms;
}

#endif

#endif
