#include <assert.h>
#include <stdint.h>

#include <deque>
#include <initializer_list>

#include "firmware/arduino/otis_nano_rp2040_connect/otis_pps_fifo_drain.h"

struct Port {
  std::deque<uint32_t> fifo;
  uint64_t ticks = 10u;
  bool stalled = false;
  bool stopped = false;
  bool inject_word_on_now = false;

  Port(std::initializer_list<uint32_t> words) : fifo(words) {}

  bool empty() const { return fifo.empty(); }
  bool rxstall() const { return stalled; }
  uint32_t read() {
    const uint32_t word = fifo.front();
    fifo.pop_front();
    return word;
  }
  uint64_t now() {
    if (inject_word_on_now) {
      inject_word_on_now = false;
      fifo.push_back(0xfeedu);
    }
    return ticks++;
  }
  void stop() { stopped = true; }
};

int main() {
  uint32_t sequence = 0u;
  Port unbounded({11u});
  auto result =
      otis_pps_fifo_drain(unbounded, 1u, sequence, 128u, 8u, false, 0u);
  assert(result.count == 1u && sequence == 1u);
  assert(result.records[0].cumulative_down_counter == 11u);
  assert(result.records[0].timestamp_uncertainty_ticks == UINT32_MAX);
  assert((result.records[0].status &
          OTIS_PPS_SNAPSHOT_STATUS_TIMESTAMP_UNBOUNDED) != 0u);

  Port batch({22u, 21u});
  batch.ticks = 101u;
  result = otis_pps_fifo_drain(batch, 1u, sequence, 128u, 8u, true, 100u);
  assert(result.count == 2u && result.timestamp_ambiguous);
  assert(result.records[0].sequence == 1u);
  assert(result.records[1].sequence == 2u);
  assert((result.records[0].status &
          OTIS_PPS_SNAPSHOT_STATUS_TIMESTAMP_AMBIGUOUS) != 0u);
  assert((result.records[1].status &
          OTIS_PPS_SNAPSHOT_STATUS_TIMESTAMP_AMBIGUOUS) != 0u);

  Port no_room({33u});
  result =
      otis_pps_fifo_drain(no_room, 1u, sequence, 0u, 8u, true, 100u);
  assert(result.count == 0u && no_room.fifo.size() == 1u);
  assert(result.faults == OTIS_PPS_SNAPSHOT_STATUS_RING_FULL);
  assert(no_room.stopped);

  Port burst({1u, 2u, 3u, 4u, 5u, 6u, 7u, 8u, 9u});
  result = otis_pps_fifo_drain(
      burst, 1u, sequence, 128u, 8u, true, 100u);
  assert(result.count == 8u && burst.fifo.size() == 1u);
  assert((result.faults &
          OTIS_PPS_SNAPSHOT_STATUS_IRQ_BUDGET_EXHAUSTED) != 0u);
  assert(burst.stopped);
  for (uint32_t index = 0u; index < result.count; ++index) {
    assert((result.records[index].status &
            OTIS_PPS_SNAPSHOT_STATUS_IRQ_BUDGET_EXHAUSTED) != 0u);
  }

  // A push racing an initially empty drain is observed after the timer sample
  // and must be drained; it cannot be hidden behind a lower bound sampled
  // after the empty observation.
  Port initial_empty_race({});
  initial_empty_race.inject_word_on_now = true;
  result = otis_pps_fifo_drain(
      initial_empty_race, 2u, sequence, 128u, 8u, true, 100u);
  assert(result.count == 1u);
  assert(result.records[0].cumulative_down_counter == 0xfeedu);
  assert(initial_empty_race.fifo.empty());

  Port empty_stall({});
  empty_stall.stalled = true;
  result = otis_pps_fifo_drain(
      empty_stall, 2u, sequence, 128u, 8u, true, 100u);
  assert(result.count == 0u);
  assert((result.faults & OTIS_PPS_SNAPSHOT_STATUS_PIO_RXSTALL) != 0u);
  assert(empty_stall.stopped);

  Port stalled({44u, 43u});
  stalled.stalled = true;
  result = otis_pps_fifo_drain(
      stalled, 2u, sequence, 128u, 8u, true, 100u);
  assert(result.count == 2u && stalled.fifo.empty());
  assert((result.faults & OTIS_PPS_SNAPSHOT_STATUS_PIO_RXSTALL) != 0u);
  assert(stalled.stopped);
  assert((result.records[0].status &
          OTIS_PPS_SNAPSHOT_STATUS_PIO_RXSTALL) != 0u);

  assert(otis_pps_fifo_uncertainty(
             true, UINT64_C(0xffffffff), UINT64_C(0x100000000)) == 2u);
  assert(otis_pps_fifo_uncertainty(
             true, 100u, (UINT64_C(1) << 32) + 100u) == UINT32_MAX);
  return 0;
}
