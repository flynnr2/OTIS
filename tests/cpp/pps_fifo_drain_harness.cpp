#include <assert.h>
#include <stdint.h>
#include <deque>
#include <initializer_list>
#include "firmware/prototypes/pps_fifo_capture/otis_pps_fifo_drain.h"

struct Port {
  std::deque<uint32_t> fifo;
  uint32_t ticks = 0, reads = 0, stops = 0, replenished = 100;
  uint32_t stall_after_read = UINT32_MAX;
  bool stalled = false, stopped = false, refill = false;
  explicit Port(std::initializer_list<uint32_t> values) : fifo(values) {}
  uint32_t depth() { return static_cast<uint32_t>(fifo.size()); }
  bool rxstall() { return stalled; }
  uint32_t service_ticks() { return ticks++; }
  void stop() { stopped = true; ++stops; }
  uint32_t read() {
    assert(!fifo.empty());
    uint32_t value = fifo.front(); fifo.pop_front(); ++reads;
    if (refill && !stopped) fifo.push_back(replenished++);
    if (reads == stall_after_read) stalled = true;
    return value;
  }
};

int main() {
  uint32_t seq = 0;
  Port empty({});
  auto out = otis_pps_fifo_drain(empty, 1, seq, 128);
  assert(out.count == 0 && out.faults == 0 && !out.stopped && seq == 0);

  Port one({0}); one.ticks = UINT32_MAX;
  seq = UINT32_MAX;
  out = otis_pps_fifo_drain(one, 7, seq, 128);
  assert(out.count == 1 && out.faults == 0 && !out.timestamp_ambiguous);
  assert(out.words[0].cumulative_down_counter == 0);
  assert(out.words[0].session == 7 && out.words[0].ordinal == UINT32_MAX);
  assert(out.words[0].service_ticks == UINT32_MAX && seq == 0);

  for (uint32_t depth : {2u, 8u}) {
    Port batch({});
    for (uint32_t i = 0; i < depth; ++i) batch.fifo.push_back(1000 - i);
    seq = 12;
    out = otis_pps_fifo_drain(batch, 9, seq, 128);
    assert(out.count == depth && out.faults == 0 && out.timestamp_ambiguous);
    assert(seq == 12 + depth && batch.fifo.empty());
    for (uint32_t i = 0; i < depth; ++i) {
      assert(out.words[i].ordinal == 12 + i);
      assert(out.words[i].cumulative_down_counter == 1000 - i);
      assert(out.words[i].service_ticks == i);
    }
  }

  Port no_room({44}); seq = 30;
  out = otis_pps_fifo_drain(no_room, 1, seq, 0);
  assert(out.count == 0 && seq == 30 && no_room.fifo.front() == 44);
  assert(out.faults == OTIS_FIFO_DRAIN_RING_FULL && no_room.stops == 1);

  Port partial_room({44, 43});
  out = otis_pps_fifo_drain(partial_room, 1, seq, 1);
  assert(out.count == 1 && out.words[0].cumulative_down_counter == 44);
  assert(out.timestamp_ambiguous && partial_room.fifo.front() == 43);
  assert(out.faults == OTIS_FIFO_DRAIN_RING_FULL && seq == 31);

  // A refill during servicing cannot evade the fixed eight-read limit.
  Port flood({55}); flood.refill = true; seq = 0;
  out = otis_pps_fifo_drain(flood, 1, seq, 128);
  assert(out.count == 8 && flood.reads == 8 && flood.stops == 1 && seq == 8);
  assert(out.faults == OTIS_FIFO_DRAIN_BUDGET && out.timestamp_ambiguous);
  assert(flood.depth() == 1 && out.words[0].cumulative_down_counter == 55);

  // Freeze before draining a latched stall; no fabricated ninth/autopush word.
  Port stalled({1, 2, 3}); stalled.stalled = true; stalled.refill = true;
  seq = 40;
  out = otis_pps_fifo_drain(stalled, 2, seq, 128);
  assert(out.count == 3 && stalled.reads == 3 && seq == 43);
  assert(out.faults == OTIS_FIFO_DRAIN_RXSTALL && stalled.stops == 1);
  assert(stalled.fifo.empty());

  Port stalls_during_read({8, 7}); stalls_during_read.stall_after_read = 1;
  out = otis_pps_fifo_drain(stalls_during_read, 2, seq, 128);
  assert(out.count == 2 && out.faults == OTIS_FIFO_DRAIN_RXSTALL);
  assert(stalls_during_read.stops == 1);

  Port unstarted({99}); seq = 0;
  out = otis_pps_fifo_drain(unstarted, 0, seq, 128);
  assert(out.count == 0 && seq == 0 && unstarted.fifo.front() == 99);
  assert(out.faults == OTIS_FIFO_DRAIN_NO_SESSION && unstarted.stops == 1);
}
