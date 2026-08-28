#ifndef OTIS_GNSS_UART_RX_H
#define OTIS_GNSS_UART_RX_H

#include <stddef.h>
#include <stdint.h>

// The fixed ring holds 2,048 bytes of observations. This is enough for two
// maximum configured RMC/GGA/two-GSA output bursts plus one maximum 256-byte
// PMTK/discovery response, without relying on heap storage.
constexpr uint32_t kOtisGnssUartRxRingCapacity = 1024u;
constexpr uint32_t kOtisGnssUartRxRingMask =
    kOtisGnssUartRxRingCapacity - 1u;
constexpr uint32_t kOtisGnssUartRxHeadroomPassMaximum = 512u;
constexpr uint32_t kOtisGnssUartRxConsumerByteBudget = 128u;
constexpr uint32_t kOtisGnssUartRxConsumerTickBudget = 4000u;
// The RP2040 UART receive FIFO is 32 entries deep. An operational baud-epoch
// handoff may race a continuously transmitting receiver, so the synchronous
// discard must be bounded independently of the external RX-empty condition.
// Any byte arriving beyond this budget is discarded by the immediately
// following UART deinitialization.
constexpr uint32_t kOtisGnssUartRxTransitionHardwareDiscardBudget = 32u;
constexpr uint32_t kOtisGnssRp2040Timer0TicksPerSecond = 16000000u;
// Frozen retention: first occurrence plus up to fifteen subsequent distinct
// fault-class/segment pairs. Repeated events in an already-retained pair are
// represented by monotonic counters rather than duplicate capsules.
constexpr uint32_t kOtisGnssFaultCapsuleCapacity = 16u;

static_assert((kOtisGnssUartRxRingCapacity &
               (kOtisGnssUartRxRingCapacity - 1u)) == 0u,
              "GNSS UART RX ring capacity must be a power of two.");

enum OtisGnssUartObservationFlag : uint8_t {
  kOtisGnssUartObservationNone = 0u,
  kOtisGnssUartObservationFramingError = 1u << 0u,
  kOtisGnssUartObservationParityError = 1u << 1u,
  kOtisGnssUartObservationBreakError = 1u << 2u,
  kOtisGnssUartObservationOverrunError = 1u << 3u,
  kOtisGnssUartObservationLossBefore = 1u << 4u,
  kOtisGnssUartObservationBaudEpochBefore = 1u << 5u,
};

struct OtisGnssUartObservation {
  uint8_t byte;
  uint8_t flags;
};

static_assert(sizeof(OtisGnssUartObservation) == 2u,
              "GNSS UART observation memory budget changed.");

struct OtisGnssUartRxStats {
  uint32_t uart_bytes_observed;
  uint32_t uart_bytes_dropped_before_retention;
  uint32_t uart_rx_interrupt_count;
  uint32_t maximum_bytes_drained_per_interrupt;
  uint32_t maximum_interrupt_gap_ticks;
  uint32_t maximum_interrupt_residence_ticks;
  uint32_t hardware_overrun_count;
  uint32_t hardware_framing_count;
  uint32_t hardware_parity_count;
  uint32_t hardware_break_count;
  uint32_t ring_current_depth;
  uint32_t ring_high_water;
  uint32_t ring_overflow_count;
  uint64_t consumer_service_call_count;
  uint32_t consumer_bytes_drained;
  uint32_t maximum_consumer_service_gap_ticks;
  uint32_t last_consumer_service_gap_ticks;
  uint32_t last_consumer_drain_batch;
  uint32_t maximum_consumer_drain_batch;
  uint32_t consumer_budget_exhausted_count;
  uint32_t ring_nonempty_after_budget_count;
  uint32_t phase_window_sequence;
  uint32_t phase_window_maximum_bytes_drained_per_interrupt;
  uint32_t phase_window_maximum_interrupt_gap_ticks;
  uint32_t phase_window_maximum_interrupt_residence_ticks;
  uint32_t phase_window_ring_high_water;
  uint32_t phase_window_maximum_consumer_service_gap_ticks;
  uint32_t phase_window_maximum_consumer_drain_batch;
};

// UART0 RX is the sole producer and the Core 0 service loop is the sole
// consumer. Sequence arithmetic is unsigned and remains deterministic across
// uint32_t wrap while producer-consumer distance is bounded by the ring.
struct OtisGnssUartRxRing {
  OtisGnssUartObservation observations[kOtisGnssUartRxRingCapacity];
  volatile uint32_t producer_sequence;
  volatile uint32_t consumer_sequence;
  volatile bool loss_marker_pending;
  volatile bool baud_epoch_marker_pending;
  volatile bool overflow_episode_active;

  volatile uint32_t uart_bytes_observed;
  volatile uint32_t uart_bytes_dropped_before_retention;
  volatile uint32_t uart_rx_interrupt_count;
  volatile uint32_t maximum_bytes_drained_per_interrupt;
  volatile uint32_t last_interrupt_entry_ticks;
  volatile uint32_t maximum_interrupt_gap_ticks;
  volatile uint32_t maximum_interrupt_residence_ticks;
  volatile uint32_t hardware_overrun_count;
  volatile uint32_t hardware_framing_count;
  volatile uint32_t hardware_parity_count;
  volatile uint32_t hardware_break_count;
  volatile uint32_t ring_overflow_count;

  volatile uint32_t phase_window_sequence;
  volatile bool phase_window_interrupt_seen;
  volatile uint32_t phase_window_last_interrupt_entry_ticks;
  volatile uint32_t phase_window_maximum_bytes_drained_per_interrupt;
  volatile uint32_t phase_window_maximum_interrupt_gap_ticks;
  volatile uint32_t phase_window_maximum_interrupt_residence_ticks;
  volatile uint32_t phase_window_ring_overflow_count;

  uint32_t ring_high_water;
  uint64_t consumer_service_call_count;
  uint32_t consumer_bytes_drained;
  uint32_t last_consumer_entry_ticks;
  uint32_t maximum_consumer_service_gap_ticks;
  uint32_t last_consumer_service_gap_ticks;
  uint32_t last_consumer_drain_batch;
  uint32_t maximum_consumer_drain_batch;
  uint32_t consumer_budget_exhausted_count;
  uint32_t ring_nonempty_after_budget_count;
  bool phase_window_consumer_seen;
  uint32_t phase_window_last_consumer_entry_ticks;
  uint32_t phase_window_ring_high_water;
  uint32_t phase_window_maximum_consumer_service_gap_ticks;
  uint32_t phase_window_maximum_consumer_drain_batch;
};

void otis_gnss_uart_rx_ring_reset(OtisGnssUartRxRing *ring);
OtisGnssUartObservation otis_gnss_uart_observation_from_dr(uint32_t data);
bool otis_gnss_uart_rx_ring_push_from_isr(
    OtisGnssUartRxRing *ring, const OtisGnssUartObservation &observation);
void otis_gnss_uart_rx_ring_note_interrupt_from_isr(
    OtisGnssUartRxRing *ring, uint32_t entry_ticks, uint32_t exit_ticks,
    uint32_t bytes_drained);
void otis_gnss_uart_rx_ring_mark_baud_epoch(OtisGnssUartRxRing *ring);
// The caller must exclude the UART0 producer while resetting a phase window.
// Lifetime counters and maxima are intentionally retained.
void otis_gnss_uart_rx_ring_reset_phase_window(OtisGnssUartRxRing *ring);
bool otis_gnss_uart_rx_ring_pop(OtisGnssUartRxRing *ring,
                                OtisGnssUartObservation *observation);
// Caller must exclude the producer. Returns the exact retained observations
// discarded at an intentional baud-epoch boundary.
uint32_t otis_gnss_uart_rx_ring_discard_all(OtisGnssUartRxRing *ring);
using OtisGnssUartRxByteAvailable = bool (*)(void *context);
using OtisGnssUartRxDiscardByte = void (*)(void *context);
// Calls byte_available no more than budget + 1 times and discard_byte no more
// than budget times. This remains finite even if the producer never stops.
uint32_t otis_gnss_uart_rx_bounded_hardware_discard(
    OtisGnssUartRxByteAvailable byte_available,
    OtisGnssUartRxDiscardByte discard_byte, void *context, uint32_t budget);
uint32_t otis_gnss_uart_rx_ring_depth(const OtisGnssUartRxRing *ring);
void otis_gnss_uart_rx_ring_note_consumer_start(OtisGnssUartRxRing *ring,
                                                uint32_t entry_ticks);
void otis_gnss_uart_rx_ring_note_consumer_complete(
    OtisGnssUartRxRing *ring, uint32_t bytes_drained, bool byte_budget_hit,
    bool time_budget_hit);
void otis_gnss_uart_rx_ring_snapshot(OtisGnssUartRxRing *ring,
                                     OtisGnssUartRxStats *snapshot);

#endif
