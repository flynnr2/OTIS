#ifndef OTIS_TIMEBASE_MATH_H
#define OTIS_TIMEBASE_MATH_H

#include <stdint.h>

#define OTIS_RP2040_TIMER0_TICKS_PER_US 16ull

enum OtisPpsIntervalClass {
  OTIS_PPS_INTERVAL_SHORT = 0,
  OTIS_PPS_INTERVAL_NORMAL = 1,
  OTIS_PPS_INTERVAL_LONG = 2,
};

static inline uint64_t otis_timer0_interval_ticks(uint64_t start_ticks,
                                                  uint64_t end_ticks) {
  uint32_t start_us =
      (uint32_t)(start_ticks / OTIS_RP2040_TIMER0_TICKS_PER_US);
  uint32_t end_us =
      (uint32_t)(end_ticks / OTIS_RP2040_TIMER0_TICKS_PER_US);
  return (uint64_t)((uint32_t)(end_us - start_us)) *
         OTIS_RP2040_TIMER0_TICKS_PER_US;
}

static inline OtisPpsIntervalClass otis_classify_pps_interval_ticks(
    uint64_t interval_ticks, uint64_t short_threshold_ticks,
    uint64_t long_threshold_ticks) {
  if (interval_ticks < short_threshold_ticks) {
    return OTIS_PPS_INTERVAL_SHORT;
  }
  if (interval_ticks > long_threshold_ticks) {
    return OTIS_PPS_INTERVAL_LONG;
  }
  return OTIS_PPS_INTERVAL_NORMAL;
}

#endif
