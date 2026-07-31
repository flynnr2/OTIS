#ifndef OTIS_TIMEBASE_H
#define OTIS_TIMEBASE_H

#include <Arduino.h>
#include <hardware/structs/timer.h>
#include <stdint.h>

#include "otis_timebase_math.h"

bool otis_timebase_begin(void);

static inline uint64_t otis_capture_ticks_now(void) {
  return (uint64_t)micros() * OTIS_RP2040_TIMER0_TICKS_PER_US;
}

// Interrupt paths use the RP2040 timer register directly. This preserves the
// same wrapping 32-bit microsecond domain without Arduino dispatch overhead.
static inline uint64_t otis_capture_ticks_now_from_isr(void) {
  return (uint64_t)timer_hw->timerawl * OTIS_RP2040_TIMER0_TICKS_PER_US;
}

#endif
