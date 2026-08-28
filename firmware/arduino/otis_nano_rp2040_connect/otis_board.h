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
#define OTIS_GPIO_FORWARDED_CLOCK_OUTPUT 21u
#define OTIS_GPIO_FORWARDED_CLOCK_MONITOR 18u
#define OTIS_GPIO_EXTERNAL_EVENT_INPUT 5u
#define OTIS_GPIO_PPS_REFERENCE 26u
#define OTIS_GPIO_PSEUDO_PPS_OUTPUT 15u
#define OTIS_GPIO_GNSS_RX 1u
#define OTIS_GPIO_GNSS_TX 0u

enum OtisNanoRp2040Pins : uint8_t {
  OTIS_PIN_GENERIC_EVENT = D10,
  OTIS_PIN_PPS_REFERENCE = D14,
  OTIS_PIN_OSC_OBSERVATION = D8,              // GPIO20 / CLOCK GPIN0
  OTIS_PIN_GPIO_LOOPBACK_OUTPUT = D7,
  OTIS_PIN_PSEUDO_PPS_OUTPUT = D3,             // GPIO15, test-only output
  OTIS_PIN_FORWARDED_CLOCK_OUTPUT = D9,       // GPIO21 / CLOCK GPOUT0
  OTIS_PIN_FORWARDED_CLOCK_MONITOR = D6,      // GPIO18, diagnostic-only input
  OTIS_PIN_SECONDARY_DIAGNOSTIC_CLOCK = D2,   // GPIO25 / CLOCK GPOUT3
  OTIS_PIN_GNSS_RX = PIN_SERIAL1_RX,           // D0 / GPIO1 / UART0 RX
  OTIS_PIN_GNSS_TX = PIN_SERIAL1_TX,           // D1 / GPIO0 / UART0 TX
};

static_assert(OTIS_PIN_PSEUDO_PPS_OUTPUT == OTIS_GPIO_PSEUDO_PPS_OUTPUT,
              "Nano RP2040 Connect D3 must map to RP2040 GPIO15");
static_assert(OTIS_PIN_GENERIC_EVENT == OTIS_GPIO_EXTERNAL_EVENT_INPUT,
              "Nano RP2040 Connect D10 must remain GPIO5 external-event input");
static_assert(OTIS_PIN_PPS_REFERENCE == OTIS_GPIO_PPS_REFERENCE,
              "Nano RP2040 Connect D14 must remain GPIO26 PPS authority");
static_assert(OTIS_PIN_OSC_OBSERVATION == OTIS_GPIO_OSC_OBSERVATION,
              "Nano RP2040 Connect D8 must remain GPIO20 oscillator authority");
static_assert(OTIS_PIN_FORWARDED_CLOCK_OUTPUT == OTIS_GPIO_FORWARDED_CLOCK_OUTPUT,
              "Nano RP2040 Connect D9 must map to GPIO21 GPOUT0");
static_assert(OTIS_PIN_FORWARDED_CLOCK_MONITOR == OTIS_GPIO_FORWARDED_CLOCK_MONITOR,
              "Nano RP2040 Connect D6 must map to GPIO18 monitor input");
static_assert(OTIS_PIN_GNSS_RX == OTIS_GPIO_GNSS_RX,
              "Nano RP2040 Connect Serial1 RX/D0 must map to GPIO1");
static_assert(OTIS_PIN_GNSS_TX == OTIS_GPIO_GNSS_TX,
              "Nano RP2040 Connect Serial1 TX/D1 must map to GPIO0");

#endif
