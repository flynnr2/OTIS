#ifndef OTIS_TIMEBASE_H
#define OTIS_TIMEBASE_H

#include <Arduino.h>
#include <stdint.h>

#include "otis_timebase_math.h"

bool otis_timebase_begin(void);

static inline uint64_t otis_capture_ticks_now(void) {
  return (uint64_t)micros() * OTIS_RP2040_TIMER0_TICKS_PER_US;
}

#endif
