#ifndef OTIS_BOARD_H
#define OTIS_BOARD_H

#include <Arduino.h>

#if !defined(ARDUINO_ARCH_RP2040) || defined(ARDUINO_ARCH_MBED)
#error "OTIS Nano RP2040 firmware targets Earle Philhower arduino-pico, not Arduino Mbed OS Nano Boards."
#endif

#define OTIS_TARGET_ARDUINO_CORE "earlephilhower_arduino_pico"
#define OTIS_TARGET_BOARD OTIS_BUILD_BOARD_ID
#define OTIS_TARGET_BOARD_NAME OTIS_BUILD_BOARD_NAME

#define OTIS_GPIO_OSC_OBSERVATION 20u
#define OTIS_GPIO_PSEUDO_PPS_OUTPUT 15u

enum OtisNanoRp2040Pins : uint8_t {
  OTIS_PIN_GENERIC_EVENT = D10,
  OTIS_PIN_PPS_REFERENCE = D14,
  OTIS_PIN_OSC_OBSERVATION = D8,              // GPIO20 / CLOCK GPIN0
  OTIS_PIN_GPIO_LOOPBACK_OUTPUT = D7,
  OTIS_PIN_PSEUDO_PPS_OUTPUT = D3,             // GPIO15, test-only output
  OTIS_PIN_INTERNAL_CLOCK_VISIBILITY = D9,    // GPIO21 / CLOCK GPOUT0
  OTIS_PIN_SECONDARY_DIAGNOSTIC_CLOCK = D2,   // GPIO25 / CLOCK GPOUT3
};

static_assert(OTIS_PIN_PSEUDO_PPS_OUTPUT == OTIS_GPIO_PSEUDO_PPS_OUTPUT,
              "Nano RP2040 Connect D3 must map to RP2040 GPIO15");

#endif
