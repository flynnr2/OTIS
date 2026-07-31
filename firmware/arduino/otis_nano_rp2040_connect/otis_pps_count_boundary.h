#ifndef OTIS_PPS_COUNT_BOUNDARY_H
#define OTIS_PPS_COUNT_BOUNDARY_H

#include <stdint.h>

// These flags describe the physical count aperture ending at one PPS event.
// They are intentionally separate from OtisFlagsV1: foreground code maps them
// to the existing wire flags only after it has assessed the complete pair.
enum OtisPpsCountApertureFlags : uint32_t {
  OTIS_PPS_APERTURE_NONE = 0u,
  OTIS_PPS_APERTURE_PREVIOUS_BOUNDARY_UNAVAILABLE = 1u << 0,
  OTIS_PPS_APERTURE_BOUNDARY_CAPTURE_UNAVAILABLE = 1u << 1,
  OTIS_PPS_APERTURE_OBSERVATION_OVERFLOW = 1u << 2,
  OTIS_PPS_APERTURE_COUNTER_SNAPSHOT_INVALID = 1u << 3,
  OTIS_PPS_APERTURE_COUNTER_WRAP_HANDLED = 1u << 4,
  OTIS_PPS_APERTURE_COUNTER_WRAP_AMBIGUOUS = 1u << 5,
  OTIS_PPS_APERTURE_PHYSICAL_APERTURE_INCOMPLETE = 1u << 6,
  OTIS_PPS_APERTURE_COUNTER_SATURATED = 1u << 7,
  OTIS_PPS_APERTURE_ZERO_COUNT = 1u << 8,
};

// Foreground associates one immutable PIO/DMA snapshot with the corresponding
// independently captured D14 reference observation.  Neither CPU association
// nor the D14 timestamp defines the oscillator-count boundary.
struct OtisPpsCountBoundaryObservation {
  uint32_t session;
  uint32_t sequence;
  uint32_t reference_sequence;
  uint64_t pps_timestamp_ticks;
  uint32_t cumulative_down_counter;
  uint32_t interval_count;
  uint32_t capture_flags;
  uint32_t aperture_flags;
};

enum class OtisBoundarySequenceRelation : uint8_t {
  Continuous,
  Duplicate,
  Gap,
};

struct OtisCounterSnapshotDelta {
  uint32_t count;
  bool valid;
  bool wrap_handled;
  bool wrap_ambiguous;
};

static inline OtisCounterSnapshotDelta otis_down_counter_snapshot_delta_u32(
    uint32_t previous_x, uint32_t current_x,
    uint32_t maximum_window_count) {
  uint32_t count = previous_x - current_x;
  bool wrapped = current_x > previous_x;
  bool ambiguous = count > maximum_window_count;
  return {
      count,
      !ambiguous,
      wrapped && !ambiguous,
      wrapped && ambiguous,
  };
}

struct OtisPpsCountWindowValidity {
  bool reference_interval_valid;
  bool count_boundary_valid;
  bool counter_window_valid;
  bool observation_pair_valid;
  bool fifo_continuous;
  bool backend_qualified;
  bool control_eligible;
};

static inline OtisBoundarySequenceRelation
otis_boundary_sequence_relation(uint32_t previous, uint32_t current) {
  if (current == previous) {
    return OtisBoundarySequenceRelation::Duplicate;
  }
  // Unsigned addition deliberately defines UINT32_MAX -> 0 as continuous.
  return current == previous + 1u ? OtisBoundarySequenceRelation::Continuous
                                  : OtisBoundarySequenceRelation::Gap;
}

// Increasing-counter helper retained for other backends and historical tests.
// The PPS snapshot backend must use otis_down_counter_snapshot_delta_u32.
static inline OtisCounterSnapshotDelta otis_counter_snapshot_delta_u32(
    uint32_t previous, uint32_t current, uint32_t maximum_window_count) {
  uint32_t count = current - previous;
  bool wrapped = current < previous;
  bool ambiguous = count > maximum_window_count;
  return {
      count,
      !ambiguous,
      wrapped && !ambiguous,
      wrapped && ambiguous,
  };
}

static inline OtisPpsCountWindowValidity
otis_pps_count_window_validity(bool have_previous_boundary,
                               bool reference_interval_valid,
                               OtisBoundarySequenceRelation sequence_relation,
                               uint32_t aperture_flags,
                               bool backend_qualified,
                               bool existing_control_gates_valid) {
  constexpr uint32_t kCounterWindowInvalidMask =
      OTIS_PPS_APERTURE_PREVIOUS_BOUNDARY_UNAVAILABLE |
      OTIS_PPS_APERTURE_COUNTER_SNAPSHOT_INVALID |
      OTIS_PPS_APERTURE_COUNTER_WRAP_AMBIGUOUS |
      OTIS_PPS_APERTURE_PHYSICAL_APERTURE_INCOMPLETE |
      OTIS_PPS_APERTURE_COUNTER_SATURATED |
      OTIS_PPS_APERTURE_ZERO_COUNT;
  bool sequence_continuous =
      sequence_relation == OtisBoundarySequenceRelation::Continuous;
  bool boundary_valid =
      (aperture_flags & OTIS_PPS_APERTURE_BOUNDARY_CAPTURE_UNAVAILABLE) == 0u;
  bool counter_window_valid =
      (aperture_flags & kCounterWindowInvalidMask) == 0u;
  bool pair_valid = have_previous_boundary && sequence_continuous;
  bool fifo_continuous =
      sequence_continuous &&
      (aperture_flags & OTIS_PPS_APERTURE_OBSERVATION_OVERFLOW) == 0u;
  bool eligible = reference_interval_valid && boundary_valid &&
                  counter_window_valid && pair_valid && fifo_continuous &&
                  backend_qualified && existing_control_gates_valid;
  return {
      reference_interval_valid,
      boundary_valid,
      counter_window_valid,
      pair_valid,
      fifo_continuous,
      backend_qualified,
      eligible,
  };
}

#endif
