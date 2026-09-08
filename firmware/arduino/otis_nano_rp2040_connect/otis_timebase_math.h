#ifndef OTIS_TIMEBASE_MATH_H
#define OTIS_TIMEBASE_MATH_H

#include <stdint.h>

// The local operational coordinate is the native RP2040 microsecond counter.
// It is independent of the D8 oscillator metrology domain and must not be
// presented as a hardware-latched D10 event timestamp.
#define OTIS_RP2040_MONOTONIC_US_PER_SECOND 1000000ul
#define OTIS_RP2040_MONOTONIC_TIMESTAMP_QUANTUM_US 1ul
#define OTIS_RP2040_MONOTONIC_TIMESTAMP_QUANTUM_NS 1000ul
#define OTIS_RP2040_MONOTONIC_US32_MODULUS (1ull << 32)

enum OtisPpsIntervalClass {
  OTIS_PPS_INTERVAL_SHORT = 0,
  OTIS_PPS_INTERVAL_NORMAL = 1,
  OTIS_PPS_INTERVAL_LONG = 2,
};

static inline uint64_t otis_monotonic_us32_interval(uint64_t start_us,
                                                    uint64_t end_us) {
  return (uint64_t)((uint32_t)end_us - (uint32_t)start_us);
}

static inline bool otis_monotonic_us32_project_nearest(
    uint64_t anchor_raw_us, uint64_t anchor_extended_us,
    uint64_t event_raw_us, uint64_t maximum_distance_us,
    uint64_t *event_extended_us) {
  if (event_extended_us == nullptr) return false;
  const uint64_t forward =
      otis_monotonic_us32_interval(anchor_raw_us, event_raw_us);
  if (forward <= maximum_distance_us) {
    *event_extended_us = anchor_extended_us + forward;
    return true;
  }
  const uint64_t backward =
      otis_monotonic_us32_interval(event_raw_us, anchor_raw_us);
  if (backward <= maximum_distance_us &&
      anchor_extended_us >= backward) {
    *event_extended_us = anchor_extended_us - backward;
    return true;
  }
  return false;
}

static inline OtisPpsIntervalClass otis_classify_pps_interval_us(
    uint64_t interval_us, uint64_t short_threshold_us,
    uint64_t long_threshold_us) {
  if (interval_us < short_threshold_us) {
    return OTIS_PPS_INTERVAL_SHORT;
  }
  if (interval_us > long_threshold_us) {
    return OTIS_PPS_INTERVAL_LONG;
  }
  return OTIS_PPS_INTERVAL_NORMAL;
}

#endif
