#ifndef OTIS_TIMEBASE_MATH_H
#define OTIS_TIMEBASE_MATH_H

#include <stdint.h>

// TIMER0 timestamps retain the historical 16,000,000-unit-per-second
// coordinate, but their source is the RP2040 1 MHz microsecond counter.  The
// multiply-by-16 encoding does not create 62.5 ns capture resolution: legal
// values advance in 16-unit (1 us) quanta.
#define OTIS_RP2040_TIMER0_SOURCE_COUNTER_HZ 1000000ul
#define OTIS_RP2040_TIMER0_TICKS_PER_US 16ull
#define OTIS_RP2040_TIMER0_TIMESTAMP_QUANTUM_TICKS 16ul
#define OTIS_RP2040_TIMER0_TIMESTAMP_QUANTUM_NS 1000ul

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

static inline bool otis_timer0_project_nearest_ticks(
    uint64_t anchor_raw_ticks, uint64_t anchor_extended_ticks,
    uint64_t event_raw_ticks, uint64_t maximum_distance_ticks,
    uint64_t *event_extended_ticks) {
  if (event_extended_ticks == nullptr) return false;
  const uint64_t forward =
      otis_timer0_interval_ticks(anchor_raw_ticks, event_raw_ticks);
  if (forward <= maximum_distance_ticks) {
    *event_extended_ticks = anchor_extended_ticks + forward;
    return true;
  }
  const uint64_t backward =
      otis_timer0_interval_ticks(event_raw_ticks, anchor_raw_ticks);
  if (backward <= maximum_distance_ticks &&
      anchor_extended_ticks >= backward) {
    *event_extended_ticks = anchor_extended_ticks - backward;
    return true;
  }
  return false;
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
