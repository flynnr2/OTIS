#include "otis_pps_count_boundary_ring.h"

#include <Arduino.h>

#include "otis_config.h"

namespace {

constexpr uint8_t kBoundaryRingSize =
    static_cast<uint8_t>(OTIS_PPS_COUNT_BOUNDARY_RING_SIZE);
static_assert(kBoundaryRingSize >= 3u,
              "PPS/count boundary ring needs at least two usable slots");

volatile OtisPpsCountBoundaryObservation boundary_ring[kBoundaryRingSize];
volatile uint8_t boundary_head = 0u;
volatile uint8_t boundary_tail = 0u;
volatile uint32_t boundary_dropped_count = 0u;
volatile bool boundary_overflow_pending = false;

void store_observation(
    volatile OtisPpsCountBoundaryObservation *destination,
    const OtisPpsCountBoundaryObservation &source) {
  destination->sequence = source.sequence;
  destination->session = source.session;
  destination->reference_sequence = source.reference_sequence;
  destination->pps_timestamp_ticks = source.pps_timestamp_ticks;
  destination->cumulative_down_counter = source.cumulative_down_counter;
  destination->interval_count = source.interval_count;
  destination->capture_flags = source.capture_flags;
  destination->aperture_flags = source.aperture_flags;
}

void load_observation(
    OtisPpsCountBoundaryObservation *destination,
    const volatile OtisPpsCountBoundaryObservation *source) {
  destination->sequence = source->sequence;
  destination->session = source->session;
  destination->reference_sequence = source->reference_sequence;
  destination->pps_timestamp_ticks = source->pps_timestamp_ticks;
  destination->cumulative_down_counter = source->cumulative_down_counter;
  destination->interval_count = source->interval_count;
  destination->capture_flags = source->capture_flags;
  destination->aperture_flags = source->aperture_flags;
}

}  // namespace

void otis_pps_count_boundary_ring_reset(void) {
  noInterrupts();
  boundary_head = 0u;
  boundary_tail = 0u;
  boundary_dropped_count = 0u;
  boundary_overflow_pending = false;
  interrupts();
}

bool otis_pps_count_boundary_ring_push_from_isr(
    const OtisPpsCountBoundaryObservation &observation) {
  uint8_t next_head =
      static_cast<uint8_t>((boundary_head + 1u) &
                           (kBoundaryRingSize - 1u));
  if (next_head == boundary_tail) {
    if (boundary_dropped_count < UINT32_MAX) {
      boundary_dropped_count++;
    }
    boundary_overflow_pending = true;
    return false;
  }

  OtisPpsCountBoundaryObservation stored = observation;
  if (boundary_overflow_pending) {
    stored.aperture_flags |= OTIS_PPS_APERTURE_OBSERVATION_OVERFLOW;
    boundary_overflow_pending = false;
  }
  store_observation(&boundary_ring[boundary_head], stored);
  boundary_head = next_head;
  return true;
}

bool otis_pps_count_boundary_ring_pop(
    OtisPpsCountBoundaryObservation *observation) {
  if (observation == nullptr) {
    return false;
  }
  bool have_observation = false;
  noInterrupts();
  if (boundary_tail != boundary_head) {
    load_observation(observation, &boundary_ring[boundary_tail]);
    boundary_tail =
        static_cast<uint8_t>((boundary_tail + 1u) &
                             (kBoundaryRingSize - 1u));
    have_observation = true;
  }
  interrupts();
  return have_observation;
}

uint32_t otis_pps_count_boundary_ring_dropped_count(void) {
  noInterrupts();
  uint32_t count = boundary_dropped_count;
  interrupts();
  return count;
}

uint8_t otis_pps_count_boundary_ring_depth(void) {
  noInterrupts();
  uint8_t head = boundary_head;
  uint8_t tail = boundary_tail;
  interrupts();
  return head >= tail ? static_cast<uint8_t>(head - tail)
                      : static_cast<uint8_t>(kBoundaryRingSize - tail + head);
}

uint8_t otis_pps_count_boundary_ring_capacity(void) {
  return static_cast<uint8_t>(kBoundaryRingSize - 1u);
}
