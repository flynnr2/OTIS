#ifndef OTIS_TIMEBASE_H
#define OTIS_TIMEBASE_H

#include <Arduino.h>
#include <stdint.h>

static inline uint64_t otis_capture_ticks_now(void) {
  return (uint64_t)micros() * 16ull;
}

#endif
