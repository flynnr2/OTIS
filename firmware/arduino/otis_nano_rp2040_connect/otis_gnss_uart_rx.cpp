#include "otis_gnss_uart_rx.h"

#include <string.h>

#if defined(ARDUINO)
#include <pico.h>
#endif

namespace {

__attribute__((always_inline)) inline void compiler_memory_barrier() {
#if defined(__GNUC__)
  __asm volatile("" ::: "memory");
#endif
}

void note_maximum(uint32_t value, uint32_t *maximum) {
  if (value > *maximum) *maximum = value;
}

}  // namespace

void otis_gnss_uart_rx_ring_reset(OtisGnssUartRxRing *ring) {
  if (ring == nullptr) return;
  memset(ring, 0, sizeof(*ring));
}

#if defined(ARDUINO)
OtisGnssUartObservation __not_in_flash_func(
    otis_gnss_uart_observation_from_dr)(uint32_t data) {
#else
OtisGnssUartObservation otis_gnss_uart_observation_from_dr(uint32_t data) {
#endif
  OtisGnssUartObservation observation = {
      static_cast<uint8_t>(data & 0xffu),
      kOtisGnssUartObservationNone,
  };
  // RP2040 UARTDR carries FE/PE/BE/OE beside every received byte. Constants
  // are stated numerically here so this pure decoder remains host-testable.
  if ((data & (1u << 8u)) != 0u)
    observation.flags |= kOtisGnssUartObservationFramingError;
  if ((data & (1u << 9u)) != 0u)
    observation.flags |= kOtisGnssUartObservationParityError;
  if ((data & (1u << 10u)) != 0u)
    observation.flags |= kOtisGnssUartObservationBreakError;
  if ((data & (1u << 11u)) != 0u)
    observation.flags |= kOtisGnssUartObservationOverrunError;
  return observation;
}

#if defined(ARDUINO)
bool __not_in_flash_func(otis_gnss_uart_rx_ring_push_from_isr)(
    OtisGnssUartRxRing *ring, const OtisGnssUartObservation &input) {
#else
bool otis_gnss_uart_rx_ring_push_from_isr(
    OtisGnssUartRxRing *ring, const OtisGnssUartObservation &input) {
#endif
  if (ring == nullptr) return false;
  ring->uart_bytes_observed++;
  if ((input.flags & kOtisGnssUartObservationOverrunError) != 0u)
    ring->hardware_overrun_count++;
  if ((input.flags & kOtisGnssUartObservationFramingError) != 0u)
    ring->hardware_framing_count++;
  if ((input.flags & kOtisGnssUartObservationParityError) != 0u)
    ring->hardware_parity_count++;
  if ((input.flags & kOtisGnssUartObservationBreakError) != 0u)
    ring->hardware_break_count++;

  const uint32_t producer = ring->producer_sequence;
  const uint32_t consumer = ring->consumer_sequence;
  if (static_cast<uint32_t>(producer - consumer) >=
      kOtisGnssUartRxRingCapacity) {
    ring->uart_bytes_dropped_before_retention++;
    ring->loss_marker_pending = true;
    if (!ring->overflow_episode_active) {
      ring->ring_overflow_count++;
      ring->phase_window_ring_overflow_count++;
      ring->overflow_episode_active = true;
    }
    return false;
  }

  OtisGnssUartObservation observation = input;
  if (ring->loss_marker_pending) {
    observation.flags |= kOtisGnssUartObservationLossBefore;
    ring->loss_marker_pending = false;
  }
  if (ring->baud_epoch_marker_pending) {
    observation.flags |= kOtisGnssUartObservationBaudEpochBefore;
    ring->baud_epoch_marker_pending = false;
  }
  ring->overflow_episode_active = false;
  ring->observations[producer & kOtisGnssUartRxRingMask] = observation;
  compiler_memory_barrier();
  ring->producer_sequence = producer + 1u;
  return true;
}

#if defined(ARDUINO)
void __not_in_flash_func(otis_gnss_uart_rx_ring_note_interrupt_from_isr)(
    OtisGnssUartRxRing *ring, uint32_t entry_ticks, uint32_t exit_ticks,
    uint32_t bytes_drained) {
#else
void otis_gnss_uart_rx_ring_note_interrupt_from_isr(
    OtisGnssUartRxRing *ring, uint32_t entry_ticks, uint32_t exit_ticks,
    uint32_t bytes_drained) {
#endif
  if (ring == nullptr) return;
  if (ring->uart_rx_interrupt_count != 0u) {
    const uint32_t gap =
        static_cast<uint32_t>(entry_ticks - ring->last_interrupt_entry_ticks);
    if (gap > ring->maximum_interrupt_gap_ticks)
      ring->maximum_interrupt_gap_ticks = gap;
  }
  ring->last_interrupt_entry_ticks = entry_ticks;
  ring->uart_rx_interrupt_count++;
  if (bytes_drained > ring->maximum_bytes_drained_per_interrupt)
    ring->maximum_bytes_drained_per_interrupt = bytes_drained;
  if (bytes_drained >
      ring->phase_window_maximum_bytes_drained_per_interrupt)
    ring->phase_window_maximum_bytes_drained_per_interrupt = bytes_drained;
  const uint32_t residence = static_cast<uint32_t>(exit_ticks - entry_ticks);
  if (residence > ring->maximum_interrupt_residence_ticks)
    ring->maximum_interrupt_residence_ticks = residence;
  if (ring->phase_window_interrupt_seen) {
    const uint32_t window_gap = static_cast<uint32_t>(
        entry_ticks - ring->phase_window_last_interrupt_entry_ticks);
    if (window_gap > ring->phase_window_maximum_interrupt_gap_ticks)
      ring->phase_window_maximum_interrupt_gap_ticks = window_gap;
  }
  ring->phase_window_interrupt_seen = true;
  ring->phase_window_last_interrupt_entry_ticks = entry_ticks;
  if (residence > ring->phase_window_maximum_interrupt_residence_ticks)
    ring->phase_window_maximum_interrupt_residence_ticks = residence;
}

void otis_gnss_uart_rx_ring_mark_baud_epoch(OtisGnssUartRxRing *ring) {
  if (ring == nullptr) return;
  ring->baud_epoch_marker_pending = true;
}

void otis_gnss_uart_rx_ring_reset_phase_window(OtisGnssUartRxRing *ring) {
  if (ring == nullptr) return;
  ring->phase_window_sequence++;
  if (ring->phase_window_sequence == 0u) ring->phase_window_sequence = 1u;
  ring->phase_window_interrupt_seen = false;
  ring->phase_window_last_interrupt_entry_ticks = 0u;
  ring->phase_window_maximum_bytes_drained_per_interrupt = 0u;
  ring->phase_window_maximum_interrupt_gap_ticks = 0u;
  ring->phase_window_maximum_interrupt_residence_ticks = 0u;
  ring->phase_window_ring_overflow_count = 0u;
  ring->phase_window_consumer_seen = false;
  ring->phase_window_last_consumer_entry_ticks = 0u;
  ring->phase_window_ring_high_water =
      otis_gnss_uart_rx_ring_depth(ring);
  ring->phase_window_maximum_consumer_service_gap_ticks = 0u;
  ring->phase_window_maximum_consumer_drain_batch = 0u;
}

bool otis_gnss_uart_rx_ring_pop(OtisGnssUartRxRing *ring,
                                OtisGnssUartObservation *observation) {
  if (ring == nullptr || observation == nullptr) return false;
  const uint32_t consumer = ring->consumer_sequence;
  compiler_memory_barrier();
  const uint32_t producer = ring->producer_sequence;
  if (consumer == producer) return false;
  // High-water accounting remains outside the ISR, but samples the exact
  // producer frontier before every consumer advance so an interrupt burst
  // arriving during a drain cannot be hidden by that same drain.
  const uint32_t depth = static_cast<uint32_t>(producer - consumer);
  note_maximum(depth > kOtisGnssUartRxRingCapacity
                   ? kOtisGnssUartRxRingCapacity
                   : depth,
               &ring->ring_high_water);
  note_maximum(depth > kOtisGnssUartRxRingCapacity
                   ? kOtisGnssUartRxRingCapacity
                   : depth,
               &ring->phase_window_ring_high_water);
  *observation = ring->observations[consumer & kOtisGnssUartRxRingMask];
  compiler_memory_barrier();
  ring->consumer_sequence = consumer + 1u;
  return true;
}

uint32_t otis_gnss_uart_rx_ring_discard_all(OtisGnssUartRxRing *ring) {
  if (ring == nullptr) return 0u;
  uint32_t discarded = 0u;
  OtisGnssUartObservation observation = {};
  while (otis_gnss_uart_rx_ring_pop(ring, &observation)) discarded++;
  return discarded;
}

uint32_t otis_gnss_uart_rx_bounded_hardware_discard(
    OtisGnssUartRxByteAvailable byte_available,
    OtisGnssUartRxDiscardByte discard_byte, void *context, uint32_t budget) {
  if (byte_available == nullptr || discard_byte == nullptr) return 0u;
  uint32_t discarded = 0u;
  while (discarded < budget && byte_available(context)) {
    discard_byte(context);
    discarded++;
  }
  return discarded;
}

uint32_t otis_gnss_uart_rx_ring_depth(const OtisGnssUartRxRing *ring) {
  if (ring == nullptr) return 0u;
  const uint32_t depth = static_cast<uint32_t>(
      ring->producer_sequence - ring->consumer_sequence);
  return depth > kOtisGnssUartRxRingCapacity
             ? kOtisGnssUartRxRingCapacity
             : depth;
}

void otis_gnss_uart_rx_ring_note_consumer_start(OtisGnssUartRxRing *ring,
                                                uint32_t entry_ticks) {
  if (ring == nullptr) return;
  const uint32_t depth = otis_gnss_uart_rx_ring_depth(ring);
  note_maximum(depth, &ring->ring_high_water);
  note_maximum(depth, &ring->phase_window_ring_high_water);
  if (ring->ring_overflow_count != 0u)
    note_maximum(kOtisGnssUartRxRingCapacity, &ring->ring_high_water);
  if (ring->phase_window_ring_overflow_count != 0u)
    note_maximum(kOtisGnssUartRxRingCapacity,
                 &ring->phase_window_ring_high_water);
  if (ring->consumer_service_call_count != 0u) {
    const uint32_t gap =
        static_cast<uint32_t>(entry_ticks - ring->last_consumer_entry_ticks);
    ring->last_consumer_service_gap_ticks = gap;
    note_maximum(gap, &ring->maximum_consumer_service_gap_ticks);
  } else {
    ring->last_consumer_service_gap_ticks = 0u;
  }
  ring->last_consumer_entry_ticks = entry_ticks;
  ring->consumer_service_call_count++;
  if (ring->phase_window_consumer_seen) {
    const uint32_t window_gap = static_cast<uint32_t>(
        entry_ticks - ring->phase_window_last_consumer_entry_ticks);
    note_maximum(window_gap,
                 &ring->phase_window_maximum_consumer_service_gap_ticks);
  }
  ring->phase_window_consumer_seen = true;
  ring->phase_window_last_consumer_entry_ticks = entry_ticks;
}

void otis_gnss_uart_rx_ring_note_consumer_complete(
    OtisGnssUartRxRing *ring, uint32_t bytes_drained, bool byte_budget_hit,
    bool time_budget_hit) {
  if (ring == nullptr) return;
  ring->consumer_bytes_drained += bytes_drained;
  ring->last_consumer_drain_batch = bytes_drained;
  note_maximum(bytes_drained, &ring->maximum_consumer_drain_batch);
  note_maximum(bytes_drained,
               &ring->phase_window_maximum_consumer_drain_batch);
  const bool nonempty = otis_gnss_uart_rx_ring_depth(ring) != 0u;
  if (byte_budget_hit || time_budget_hit)
    ring->consumer_budget_exhausted_count++;
  if (nonempty && (byte_budget_hit || time_budget_hit))
    ring->ring_nonempty_after_budget_count++;
  note_maximum(otis_gnss_uart_rx_ring_depth(ring), &ring->ring_high_water);
  note_maximum(otis_gnss_uart_rx_ring_depth(ring),
               &ring->phase_window_ring_high_water);
}

void otis_gnss_uart_rx_ring_snapshot(OtisGnssUartRxRing *ring,
                                     OtisGnssUartRxStats *snapshot) {
  if (ring == nullptr || snapshot == nullptr) return;
  const uint32_t depth = otis_gnss_uart_rx_ring_depth(ring);
  note_maximum(depth, &ring->ring_high_water);
  note_maximum(depth, &ring->phase_window_ring_high_water);
  if (ring->ring_overflow_count != 0u)
    note_maximum(kOtisGnssUartRxRingCapacity, &ring->ring_high_water);
  if (ring->phase_window_ring_overflow_count != 0u)
    note_maximum(kOtisGnssUartRxRingCapacity,
                 &ring->phase_window_ring_high_water);
  snapshot->uart_bytes_observed = ring->uart_bytes_observed;
  snapshot->uart_bytes_dropped_before_retention =
      ring->uart_bytes_dropped_before_retention;
  snapshot->uart_rx_interrupt_count = ring->uart_rx_interrupt_count;
  snapshot->maximum_bytes_drained_per_interrupt =
      ring->maximum_bytes_drained_per_interrupt;
  snapshot->maximum_interrupt_gap_ticks = ring->maximum_interrupt_gap_ticks;
  snapshot->maximum_interrupt_residence_ticks =
      ring->maximum_interrupt_residence_ticks;
  snapshot->hardware_overrun_count = ring->hardware_overrun_count;
  snapshot->hardware_framing_count = ring->hardware_framing_count;
  snapshot->hardware_parity_count = ring->hardware_parity_count;
  snapshot->hardware_break_count = ring->hardware_break_count;
  snapshot->ring_current_depth = depth;
  snapshot->ring_high_water = ring->ring_high_water;
  snapshot->ring_overflow_count = ring->ring_overflow_count;
  snapshot->consumer_service_call_count = ring->consumer_service_call_count;
  snapshot->consumer_bytes_drained = ring->consumer_bytes_drained;
  snapshot->maximum_consumer_service_gap_ticks =
      ring->maximum_consumer_service_gap_ticks;
  snapshot->last_consumer_service_gap_ticks =
      ring->last_consumer_service_gap_ticks;
  snapshot->last_consumer_drain_batch = ring->last_consumer_drain_batch;
  snapshot->maximum_consumer_drain_batch =
      ring->maximum_consumer_drain_batch;
  snapshot->consumer_budget_exhausted_count =
      ring->consumer_budget_exhausted_count;
  snapshot->ring_nonempty_after_budget_count =
      ring->ring_nonempty_after_budget_count;
  snapshot->phase_window_sequence = ring->phase_window_sequence;
  snapshot->phase_window_maximum_bytes_drained_per_interrupt =
      ring->phase_window_maximum_bytes_drained_per_interrupt;
  snapshot->phase_window_maximum_interrupt_gap_ticks =
      ring->phase_window_maximum_interrupt_gap_ticks;
  snapshot->phase_window_maximum_interrupt_residence_ticks =
      ring->phase_window_maximum_interrupt_residence_ticks;
  snapshot->phase_window_ring_high_water =
      ring->phase_window_ring_high_water;
  snapshot->phase_window_maximum_consumer_service_gap_ticks =
      ring->phase_window_maximum_consumer_service_gap_ticks;
  snapshot->phase_window_maximum_consumer_drain_batch =
      ring->phase_window_maximum_consumer_drain_batch;
}
