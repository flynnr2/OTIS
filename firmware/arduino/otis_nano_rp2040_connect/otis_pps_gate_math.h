#ifndef OTIS_PPS_GATE_MATH_H
#define OTIS_PPS_GATE_MATH_H

#include <stdint.h>

#include "otis_protocol.h"
#include "otis_timebase_math.h"

enum class OtisPpsBoundaryReason : uint8_t {
  Valid,
  Duplicate,
  ShortInterval,
  LongInterval,
  CaptureFlagged,
  PreviousBoundaryInvalid,
};

struct OtisPpsBoundaryAssessment {
  bool valid;
  uint64_t interval_ticks;
  OtisPpsBoundaryReason reason;
};

static inline uint32_t otis_pps_reference_invalid_flag_mask(void) {
  return OTIS_FLAG_CAPTURE_OVERFLOW_NEARBY |
         OTIS_FLAG_CAPTURE_RING_OVERRUN |
         OTIS_FLAG_EDGE_ORDER_SUSPECT |
         OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT |
         OTIS_FLAG_SOURCE_HEALTH_SUSPECT |
         OTIS_FLAG_PULSE_TOO_NARROW |
         OTIS_FLAG_PULSE_TOO_WIDE |
         OTIS_FLAG_RATE_TOO_HIGH |
         OTIS_FLAG_INPUT_STUCK_LOW |
         OTIS_FLAG_INPUT_STUCK_HIGH |
         OTIS_FLAG_DEBOUNCE_REJECTED |
         OTIS_FLAG_GATE_INCOMPLETE;
}

static inline OtisPpsBoundaryAssessment otis_pps_gate_assess_boundary(
    uint64_t open_ticks, uint64_t close_ticks, uint32_t boundary_flags,
    uint64_t duplicate_max_interval_ticks, uint64_t minimum_interval_ticks,
    uint64_t maximum_interval_ticks) {
  uint64_t interval_ticks =
      otis_timer0_interval_ticks(open_ticks, close_ticks);
  if ((boundary_flags & otis_pps_reference_invalid_flag_mask()) != 0u) {
    return {
        false,
        interval_ticks,
        OtisPpsBoundaryReason::CaptureFlagged,
    };
  }
  if (interval_ticks <= duplicate_max_interval_ticks) {
    return {
        false,
        interval_ticks,
        OtisPpsBoundaryReason::Duplicate,
    };
  }
  if (interval_ticks < minimum_interval_ticks) {
    return {
        false,
        interval_ticks,
        OtisPpsBoundaryReason::ShortInterval,
    };
  }
  if (interval_ticks > maximum_interval_ticks) {
    return {
        false,
        interval_ticks,
        OtisPpsBoundaryReason::LongInterval,
    };
  }
  return {
      true,
      interval_ticks,
      OtisPpsBoundaryReason::Valid,
  };
}

#endif
