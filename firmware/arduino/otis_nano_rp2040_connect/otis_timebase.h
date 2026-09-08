#ifndef OTIS_TIMEBASE_H
#define OTIS_TIMEBASE_H

#include <Arduino.h>
#include <hardware/structs/timer.h>
#include <stdint.h>

#include "otis_timebase_math.h"

bool otis_timebase_begin(void);

static inline uint64_t otis_monotonic_us32_now(void) {
  return (uint64_t)(uint32_t)micros();
}

// Interrupt paths use the RP2040 timer register directly. This preserves the
// same wrapping 32-bit microsecond domain without Arduino dispatch overhead.
static inline uint64_t otis_monotonic_us32_now_from_isr(void) {
  return (uint64_t)timer_hw->timerawl;
}

#endif
