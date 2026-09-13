#include <assert.h>
#include <stdint.h>
#include <deque>
#include <initializer_list>
#include "firmware/prototypes/pps_fifo_capture/otis_pps_fifo_drain.h"
#include "firmware/arduino/otis_nano_rp2040_connect/otis_reference_acceptance_live.h"
#include "firmware/arduino/otis_nano_rp2040_connect/otis_reference_acceptance_policy.generated.h"

struct Port {
  std::deque<uint32_t> fifo;
  uint32_t ticks = 0, reads = 0, stops = 0, replenished = 100;
  uint32_t stall_after_read = UINT32_MAX;
  uint32_t depth_calls = 0, arrival_at_depth = UINT32_MAX;
  bool stall_on_arrival = false;
  bool stalled = false, stopped = false, refill = false;
  explicit Port(std::initializer_list<uint32_t> values) : fifo(values) {}
  uint32_t depth() {
    ++depth_calls;
    if (depth_calls == arrival_at_depth && !stopped) {
      fifo.push_back(77u);
      if (stall_on_arrival) {
        while (fifo.size() < 8) fifo.push_back(78u);
        stalled = true;  // Ninth attempted autopush is not committed.
      }
    }
    return static_cast<uint32_t>(fifo.size());
  }
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

// Test-only mapping at the proposed integration seam. Both the FIFO drain and
// selector are real code; this does not implement the instrument adapter/ISR.
// All coordinates/counts below are synthetic, not missing bench evidence.
static void test_fifo_to_real_selector() {
  using D = OtisReferenceAcceptanceDisposition;
  OtisReferenceAcceptanceLive selector(OTIS_REFERENCE_ACCEPTANCE_POLICY);
  uint32_t next = 0;
  auto deliver = [&](uint32_t ticks, uint32_t cumulative) {
    Port port({cumulative});
    port.ticks = ticks;
    const auto batch = otis_pps_fifo_drain(port, 17, next, 128);
    assert(batch.count == 1 && batch.faults == 0 && !batch.timestamp_ambiguous);
    const auto &word = batch.words[0];
    const OtisReferenceAcceptanceObservation observation = {
        word.session, word.ordinal, word.ordinal, word.service_ticks,
        word.cumulative_down_counter, 0, 16};
    return selector.observe(observation, ticks, uint64_t(ticks) + 10, 1000);
  };
  assert(deliver(0, 0).disposition == D::Seeded);
  for (uint32_t second = 1; second <= 8; ++second)
    assert(!deliver(second * 1000000u, 0u - second * 10000000u).has_span);
  assert(selector.status().tracking && selector.status().anchor_current);
  const auto before = selector.status();
  const auto early = deliver(8902367u, 0u - 89023670u);
  assert(early.disposition == D::EarlyExcluded && !early.has_span);
  assert(selector.status().anchor_snapshot_sequence == before.anchor_snapshot_sequence);
  assert(selector.status().accepted_boundary_ordinal == before.accepted_boundary_ordinal);
  const auto normal = deliver(9000000u, 0u - 90000000u);
  assert(normal.disposition == D::AcceptedSpan && normal.has_span);
  assert(normal.counted_edges == 10000000u && normal.interval_ticks == 1000000u);
  assert(normal.excluded_candidate_count == 1u);
  assert(normal.acceptance_epoch == before.acceptance_epoch);
  assert(normal.opening.snapshot_sequence == 8u && normal.closing.snapshot_sequence == 10u);
  assert(normal.opening.reference_sequence == normal.opening.snapshot_sequence);
  assert(normal.closing.reference_sequence == normal.closing.snapshot_sequence);

  // An empty FIFO (including a GPIO-only diagnostic) cannot advance the one
  // authoritative record stream. The next real FIFO boundary remains usable.
  Port no_word({});
  const uint32_t saved_next = next;
  const auto empty = otis_pps_fifo_drain(no_word, 17, next, 128);
  assert(empty.count == 0 && next == saved_next);
  const auto following = deliver(10000000u, 0u - 100000000u);
  assert(following.has_span && following.counted_edges == 10000000u);
  assert(following.excluded_candidate_count == 0u);
  assert(following.acceptance_epoch == before.acceptance_epoch);

  // No timestamp is fabricated for a coalesced batch. Its actual integration
  // must withhold it at the common gate; this seam explicitly invalidates the
  // timing model and verifies that the old accepted anchor loses authority.
  Port coalesced({0u - 110000000u, 0u - 120000000u});
  const auto ambiguous = otis_pps_fifo_drain(coalesced, 17, next, 128);
  assert(ambiguous.count == 2 && ambiguous.timestamp_ambiguous);
  const auto lost = selector.invalidate(OtisReferenceAcceptanceReason::ObservationAgeAmbiguous);
  assert(!lost.has_span && !selector.status().anchor_current);
  assert(!selector.status().tracking);
}

int main() {
  test_fifo_to_real_selector();
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

  // A new word after the loop saw empty belongs to the next level IRQ. It
  // must not be called an exhausted eight-read budget after only one read.
  Port late_arrival({66}); late_arrival.arrival_at_depth = 4; seq = 0;
  out = otis_pps_fifo_drain(late_arrival, 3, seq, 128);
  assert(out.count == 1 && out.faults == 0 && !out.stopped);
  assert(late_arrival.fifo.front() == 77 && seq == 1);
  out = otis_pps_fifo_drain(late_arrival, 3, seq, 128);
  assert(out.count == 1 && out.faults == 0 && seq == 2);
  assert(out.words[0].ordinal == 1 && out.words[0].cumulative_down_counter == 77);

  // A real RXSTALL becoming visible at the exit frontier still freezes the
  // source, preserving the returned word and eight unread committed words.
  Port late_stall({66}); late_stall.arrival_at_depth = 4;
  late_stall.stall_on_arrival = true; seq = 0;
  out = otis_pps_fifo_drain(late_stall, 3, seq, 128);
  assert(out.count == 1 && out.faults == OTIS_FIFO_DRAIN_RXSTALL);
  assert(out.stopped && late_stall.stops == 1 && late_stall.fifo.size() == 8);
  assert(out.words[0].cumulative_down_counter == 66 && seq == 1);

  Port unstarted({99}); seq = 0;
  out = otis_pps_fifo_drain(unstarted, 0, seq, 128);
  assert(out.count == 0 && seq == 0 && unstarted.fifo.front() == 99);
  assert(out.faults == OTIS_FIFO_DRAIN_NO_SESSION && unstarted.stops == 1);
}
