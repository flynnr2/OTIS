#ifndef OTIS_PPS_FIFO_DRAIN_H
#define OTIS_PPS_FIFO_DRAIN_H

#include <stdint.h>

#include "otis_pps_snapshot_backend.h"

// Bounded policy shared by the real RP2040 backend and its native hardware
// port. Port is the sole FIFO reader. stop() disables only this state
// machine's RX-not-empty source and the state machine; it never clears FIFO
// contents or another PIO interrupt source.
struct OtisPpsFifoDrainResult {
  OtisPpsHardwareSnapshot records[8];
  uint32_t count;
  uint32_t faults;
  bool timestamp_ambiguous;
  bool stopped;
  bool empty_after;
  uint64_t empty_observation_ticks;
};

static inline uint32_t otis_pps_fifo_uncertainty(
    bool have_empty_lower_bound, uint64_t empty_lower_bound_ticks,
    uint64_t service_ticks) {
  if (!have_empty_lower_bound || service_ticks < empty_lower_bound_ticks) {
    return UINT32_MAX;
  }
  const uint64_t elapsed = service_ticks - empty_lower_bound_ticks;
  // A bracket spanning half the exposed us32 domain is causally ambiguous.
  // UINT32_MAX remains the explicit unknown sentinel.
  return elapsed >= (uint64_t(1u) << 31)
             ? UINT32_MAX
             : static_cast<uint32_t>(elapsed) + 1u;
}

template <typename Port>
OtisPpsFifoDrainResult otis_pps_fifo_drain(
    Port &port, uint32_t session, uint32_t &next_sequence,
    uint32_t ring_slots, uint32_t word_budget,
    bool have_empty_lower_bound, uint64_t empty_lower_bound_ticks) {
  OtisPpsFifoDrainResult result = {};
  auto stop = [&]() {
    if (!result.stopped) {
      port.stop();
      result.stopped = true;
    }
  };

  if (session == 0u) {
    return result;
  }

  if (port.rxstall()) {
    result.faults |= OTIS_PPS_SNAPSHOT_STATUS_PIO_RXSTALL;
    stop();
  }
  // Sample before observing empty. A PIO push racing this pair either makes
  // the subsequent observation non-empty, or occurs after this retained lower
  // bound; the lower bound can therefore never advance past an unread word.
  const uint64_t initial_empty_candidate = port.now();
  if (port.empty()) {
    result.empty_observation_ticks = initial_empty_candidate;
    result.empty_after = true;
    return result;
  }

  uint32_t capacity = ring_slots;
  if (capacity > word_budget) capacity = word_budget;
  if (capacity > 8u) capacity = 8u;
  if (capacity == 0u) {
    result.faults |= ring_slots == 0u
                         ? OTIS_PPS_SNAPSHOT_STATUS_RING_FULL
                         : OTIS_PPS_SNAPSHOT_STATUS_IRQ_BUDGET_EXHAUSTED;
    stop();
  }

  while (result.count < capacity && !port.empty()) {
    const uint32_t raw = port.read();
    const uint64_t service_coordinate = port.now();
    const uint32_t service_ticks = static_cast<uint32_t>(service_coordinate);
    uint32_t uncertainty = otis_pps_fifo_uncertainty(
        have_empty_lower_bound, empty_lower_bound_ticks, service_coordinate);
    uint32_t status = uncertainty == UINT32_MAX
                          ? OTIS_PPS_SNAPSHOT_STATUS_TIMESTAMP_UNBOUNDED
                          : OTIS_PPS_SNAPSHOT_STATUS_NONE;
    result.records[result.count++] = {
        session, next_sequence++, raw, status, service_ticks, uncertainty};
    if (port.rxstall()) {
      result.faults |= OTIS_PPS_SNAPSHOT_STATUS_PIO_RXSTALL;
      stop();
    }
  }

  // The timer sample deliberately precedes the FIFO-empty observation. If a
  // PIO push races this pair, either the FIFO is observed non-empty and the
  // lower bound is not advanced, or this sample still precedes the push.
  result.empty_observation_ticks = port.now();
  result.empty_after = port.empty();

  if (!result.empty_after && result.count == capacity) {
    if (result.count == ring_slots) {
      result.faults |= OTIS_PPS_SNAPSHOT_STATUS_RING_FULL;
    } else {
      result.faults |= OTIS_PPS_SNAPSHOT_STATUS_IRQ_BUDGET_EXHAUSTED;
    }
    stop();
  }
  if (port.rxstall()) {
    result.faults |= OTIS_PPS_SNAPSHOT_STATUS_PIO_RXSTALL;
    stop();
  }

  result.timestamp_ambiguous = result.count > 1u;
  uint32_t record_status = result.faults;
  if (result.timestamp_ambiguous) {
    record_status |= OTIS_PPS_SNAPSHOT_STATUS_TIMESTAMP_AMBIGUOUS;
  }
  for (uint32_t index = 0u; index < result.count; ++index) {
    result.records[index].status |= record_status;
  }
  return result;
}

#endif
