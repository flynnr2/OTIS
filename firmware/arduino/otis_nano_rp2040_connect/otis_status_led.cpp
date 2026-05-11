#include "otis_status_led.h"

#if OTIS_ENABLE_STATUS_LED

#include <Arduino.h>

#if defined(LEDR) && defined(LEDG) && defined(LEDB)
#define OTIS_STATUS_LED_HAS_RGB 1
#else
#define OTIS_STATUS_LED_HAS_RGB 0
#endif

typedef enum OtisStatusLedPattern {
  OTIS_STATUS_LED_OFF = 0,
  OTIS_STATUS_LED_SOLID,
  OTIS_STATUS_LED_SLOW_BLINK,
  OTIS_STATUS_LED_FAST_BLINK,
} OtisStatusLedPattern;

typedef struct OtisStatusLedColor {
  bool red;
  bool green;
  bool blue;
} OtisStatusLedColor;

static OtisSystemState otis_status_led_base_state = OTIS_SYSTEM_STATE_UNKNOWN;
static OtisStatusLedColor otis_status_led_base_color = {false, false, false};
static OtisStatusLedPattern otis_status_led_pattern = OTIS_STATUS_LED_OFF;
static OtisStatusLedColor otis_status_led_overlay_color = {false, false, false};
static uint32_t otis_status_led_overlay_until_ms = 0u;
static uint32_t otis_status_led_boot_flash_until_ms = 0u;

static OtisStatusLedColor otis_status_led_color(bool red, bool green,
                                                bool blue) {
  OtisStatusLedColor color = {red, green, blue};
  return color;
}

static uint8_t otis_status_led_priority(OtisSystemState state) {
  switch (state) {
    case OTIS_SYSTEM_STATE_FATAL_CONFIG_FAULT:
      return 6u;
    case OTIS_SYSTEM_STATE_MISSING_OSCILLATOR:
      return 5u;
    case OTIS_SYSTEM_STATE_WAITING_FOR_PPS_GPS:
      return 4u;
    case OTIS_SYSTEM_STATE_HOLDOVER_DEGRADED:
      return 3u;
    case OTIS_SYSTEM_STATE_PPS_SEEN_ACQUIRING:
    case OTIS_SYSTEM_STATE_USB_CONFIG_DEBUG:
      return 2u;
    case OTIS_SYSTEM_STATE_LOCKED_HEALTHY_LOGGING:
      return 1u;
    case OTIS_SYSTEM_STATE_UNKNOWN:
    case OTIS_SYSTEM_STATE_BOOT_STARTING:
    case OTIS_SYSTEM_STATE_VALID_CAPTURE_HEARTBEAT:
    case OTIS_SYSTEM_STATE_HOST_API_WIFI_ACTIVITY:
    default:
      return 0u;
  }
}

static void otis_status_led_write(OtisStatusLedColor color) {
#if OTIS_STATUS_LED_HAS_RGB
  digitalWrite(LEDR, color.red ? LOW : HIGH);
  digitalWrite(LEDG, color.green ? LOW : HIGH);
  digitalWrite(LEDB, color.blue ? LOW : HIGH);
#else
  (void)color;
#endif
}

static bool otis_status_led_activity_allowed(void) {
  return otis_status_led_priority(otis_status_led_base_state) <=
         otis_status_led_priority(OTIS_SYSTEM_STATE_LOCKED_HEALTHY_LOGGING);
}

static void otis_status_led_set_base(OtisSystemState state,
                                     OtisStatusLedColor color,
                                     OtisStatusLedPattern pattern) {
  otis_status_led_base_state = state;
  otis_status_led_base_color = color;
  otis_status_led_pattern = pattern;
  otis_status_led_overlay_until_ms = 0u;
}

void otis_status_led_begin(void) {
#if OTIS_STATUS_LED_HAS_RGB
  pinMode(LEDR, OUTPUT);
  pinMode(LEDG, OUTPUT);
  pinMode(LEDB, OUTPUT);
#endif
  otis_status_led_write(otis_status_led_color(false, false, false));
}

void otis_status_led_set(OtisSystemState state) {
  switch (state) {
    case OTIS_SYSTEM_STATE_BOOT_STARTING:
      otis_status_led_set_base(state, otis_status_led_color(true, true, true),
                               OTIS_STATUS_LED_SOLID);
      otis_status_led_boot_flash_until_ms = millis() + 150u;
      break;
    case OTIS_SYSTEM_STATE_WAITING_FOR_PPS_GPS:
      otis_status_led_set_base(state, otis_status_led_color(false, false, true),
                               OTIS_STATUS_LED_SLOW_BLINK);
      break;
    case OTIS_SYSTEM_STATE_PPS_SEEN_ACQUIRING:
      otis_status_led_set_base(state, otis_status_led_color(false, false, true),
                               OTIS_STATUS_LED_SOLID);
      break;
    case OTIS_SYSTEM_STATE_LOCKED_HEALTHY_LOGGING:
      otis_status_led_set_base(state, otis_status_led_color(false, true, false),
                               OTIS_STATUS_LED_SOLID);
      break;
    case OTIS_SYSTEM_STATE_VALID_CAPTURE_HEARTBEAT:
      if (otis_status_led_activity_allowed()) {
        otis_status_led_overlay_color =
            otis_status_led_color(false, true, false);
        otis_status_led_overlay_until_ms = millis() + 80u;
      }
      break;
    case OTIS_SYSTEM_STATE_HOLDOVER_DEGRADED:
      otis_status_led_set_base(state, otis_status_led_color(true, true, false),
                               OTIS_STATUS_LED_SLOW_BLINK);
      break;
    case OTIS_SYSTEM_STATE_MISSING_OSCILLATOR:
      otis_status_led_set_base(state, otis_status_led_color(true, false, false),
                               OTIS_STATUS_LED_FAST_BLINK);
      break;
    case OTIS_SYSTEM_STATE_FATAL_CONFIG_FAULT:
      otis_status_led_set_base(state, otis_status_led_color(true, false, false),
                               OTIS_STATUS_LED_SOLID);
      break;
    case OTIS_SYSTEM_STATE_USB_CONFIG_DEBUG:
      otis_status_led_set_base(state, otis_status_led_color(true, false, true),
                               OTIS_STATUS_LED_SOLID);
      break;
    case OTIS_SYSTEM_STATE_HOST_API_WIFI_ACTIVITY:
      if (otis_status_led_activity_allowed()) {
        otis_status_led_overlay_color = otis_status_led_color(false, true, true);
        otis_status_led_overlay_until_ms = millis() + 80u;
      }
      break;
    case OTIS_SYSTEM_STATE_UNKNOWN:
    default:
      otis_status_led_set_base(OTIS_SYSTEM_STATE_UNKNOWN,
                               otis_status_led_color(false, false, false),
                               OTIS_STATUS_LED_OFF);
      break;
  }
}

void otis_status_led_poll(uint32_t now_ms) {
  if (otis_status_led_boot_flash_until_ms != 0u &&
      (int32_t)(now_ms - otis_status_led_boot_flash_until_ms) >= 0) {
    otis_status_led_boot_flash_until_ms = 0u;
    if (otis_status_led_base_state == OTIS_SYSTEM_STATE_BOOT_STARTING) {
      otis_status_led_set(OTIS_SYSTEM_STATE_UNKNOWN);
    }
  }

  if (otis_status_led_overlay_until_ms != 0u &&
      (int32_t)(now_ms - otis_status_led_overlay_until_ms) < 0) {
    otis_status_led_write(otis_status_led_overlay_color);
    return;
  }
  otis_status_led_overlay_until_ms = 0u;

  bool enabled = false;
  switch (otis_status_led_pattern) {
    case OTIS_STATUS_LED_SOLID:
      enabled = true;
      break;
    case OTIS_STATUS_LED_SLOW_BLINK:
      enabled = ((now_ms / 500u) % 2u) == 0u;
      break;
    case OTIS_STATUS_LED_FAST_BLINK:
      enabled = ((now_ms / 125u) % 2u) == 0u;
      break;
    case OTIS_STATUS_LED_OFF:
    default:
      enabled = false;
      break;
  }

  otis_status_led_write(enabled ? otis_status_led_base_color
                                : otis_status_led_color(false, false, false));
}

#endif
