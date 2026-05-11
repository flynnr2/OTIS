#ifndef OTIS_BOARD_H
#define OTIS_BOARD_H

#include <Arduino.h>

#if !defined(ARDUINO_ARCH_RP2040) || defined(ARDUINO_ARCH_MBED)
#error "OTIS Nano RP2040 firmware targets Earle Philhower arduino-pico, not Arduino Mbed OS Nano Boards."
#endif

#define OTIS_TARGET_ARDUINO_CORE "earlephilhower_arduino_pico"
#define OTIS_TARGET_BOARD "arduino_nano_rp2040_connect"

enum OtisNanoRp2040Pins : uint8_t {
  OTIS_PIN_GENERIC_EVENT = 10u,
  OTIS_PIN_PPS_REFERENCE = 14u,
  OTIS_PIN_OSC_OBSERVATION = 2u,
};

#endif
