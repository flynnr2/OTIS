#include <assert.h>
#include <stdint.h>
#include "otis_dual_core_partition.h"
#include "otis_spsc_queue.h"

namespace {
uint64_t now_us;
uint32_t clock_reads;
uint64_t clock_reader() { ++clock_reads; return now_us; }
}

int main() {
  // The precommit callback is capacity-admitted, follows the value copy, and
  // cannot observe its own publication through the consumer before release.
  OtisSpscQueue<uint32_t, 1u> queue;
  uint32_t value = 0u;
  assert(queue.try_push_with_precommit(42u, [&](uint32_t &slot) {
    assert(slot == 42u && !queue.try_pop(&value));
    slot = 43u;
  }));
  assert(!queue.try_push_with_precommit(99u, [](uint32_t &) { assert(false); }));
  assert(queue.try_pop(&value) && value == 43u);

  otis_dual_core_partition_reset();
  otis_dual_core_set_observation_diagnostic_clock(clock_reader);
  OtisObservationMessage source = {};
  source.kind = OtisObservationMessageKind::RawEdge;
  source.raw_edge.sequence = 901u;  // deliberately distinct presentation ID
  source.raw_edge.timestamp_ticks = 15u;
  source.snapshot.session = 7u;
  source.snapshot.sequence = 19u;
  now_us = UINT32_MAX - 2u;
  assert(otis_dual_core_publish_observation(&source));
  assert(clock_reads == 1u && !source.queue_clock_valid);
  now_us = (UINT64_C(1) << 32) + 4u;
  OtisObservationMessage taken = {};
  assert(otis_dual_core_take_observation(&taken));
  assert(clock_reads == 2u && taken.queue_clock_valid);
  assert(taken.queue_precommit_ticks == UINT32_MAX - 2u);
  assert(taken.queue_consumed_ticks == 4u && !taken.queue_clock_ambiguous);
  assert(uint32_t(taken.queue_consumed_ticks - taken.queue_precommit_ticks) == 7u);
  assert(taken.snapshot.session == 7u && taken.snapshot.sequence == 19u);
  assert(taken.raw_edge.sequence == 901u && taken.raw_edge.timestamp_ticks == 15u);
  assert(!otis_dual_core_take_observation(&taken) && clock_reads == 2u);

  // New sessions and duplicate source IDs remain exact, with distinct sampled
  // queue coordinates. Diagnostics do not reinterpret canonical continuity.
  source.kind = OtisObservationMessageKind::PpsSnapshot;
  source.snapshot.session = 8u;
  source.snapshot.sequence = 1u;
  for (uint32_t i = 0u; i < OTIS_OBSERVATION_QUEUE_DEPTH; ++i) {
    now_us = 100u + i;
    assert(otis_dual_core_publish_observation(&source));
  }
  const uint32_t admitted_reads = clock_reads;
  assert(!otis_dual_core_publish_observation(&source));
  assert(clock_reads == admitted_reads);
  // Outbound congestion loses a record without invalidating the capture owner.
  OtisDualCoreQueueStats stats = {};
  otis_dual_core_get_stats(&stats);
  assert(stats.observation_dropped == 1u);
  assert(!otis_dual_core_fail_static());
  for (uint32_t i = 0u; i < OTIS_OBSERVATION_QUEUE_DEPTH; ++i) {
    now_us = 1000u + i;
    assert(otis_dual_core_take_observation(&taken));
    assert(taken.queue_precommit_ticks == 100u + i);
    assert(taken.queue_consumed_ticks == static_cast<uint32_t>(now_us));
    assert(taken.snapshot.session == 8u && taken.snapshot.sequence == 1u);
  }

  otis_dual_core_partition_reset();
  // Low32 subtraction alone aliases complete wraps and clock restarts. The
  // retained hardware high word rejects those and the half-range boundary.
  const uint64_t residence[] = {
      (UINT64_C(1) << 31) - 1u, UINT64_C(1) << 31,
      (UINT64_C(1) << 32) + 7u};
  for (uint32_t i = 0; i < 3u; ++i) {
    now_us = (UINT64_C(3) << 32) + 100u;
    assert(otis_dual_core_publish_observation(&source));
    now_us += residence[i];
    assert(otis_dual_core_take_observation(&taken));
    assert(taken.queue_clock_valid);
    assert(taken.queue_clock_ambiguous == (i != 0u));
    assert(taken.queue_precommit_high == 3u);
    assert(!otis_dual_core_fail_static());
  }
  now_us = (UINT64_C(5) << 32) + 100u;
  assert(otis_dual_core_publish_observation(&source));
  now_us = 107u;
  assert(otis_dual_core_take_observation(&taken));
  assert(taken.queue_clock_valid && taken.queue_clock_ambiguous);
  assert(!otis_dual_core_fail_static());

  otis_dual_core_partition_reset();
  otis_dual_core_set_observation_diagnostic_clock(nullptr);
  source.queue_clock_valid = true; // incoming metadata must not masquerade as ours
  source.queue_precommit_ticks = 123u;
  assert(otis_dual_core_publish_observation(&source));
  assert(otis_dual_core_take_observation(&taken));
  assert(!taken.queue_clock_valid && taken.queue_precommit_ticks == 0u);
  assert(!otis_dual_core_fail_static());
}
