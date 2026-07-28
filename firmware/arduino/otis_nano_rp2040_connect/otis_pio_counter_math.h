#ifndef OTIS_PIO_COUNTER_MATH_H
#define OTIS_PIO_COUNTER_MATH_H

#include <stdint.h>

struct OtisPioCounterSample {
  uint64_t counted_edges;
  bool saturated;
};

static inline OtisPioCounterSample otis_pio_counter_sample(
    uint32_t initial_value, uint32_t remaining_value) {
  return {
      (uint64_t)initial_value - (uint64_t)remaining_value,
      remaining_value == 0u,
  };
}

#endif
