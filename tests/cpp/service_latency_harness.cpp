#include "otis_service_latency.h"
#include <assert.h>
#include <stdio.h>

static OtisServiceLatencySample sample(uint32_t sequence, uint32_t duration,
                                       uint32_t session = 1) {
  return {session, sequence, 100, 100 + duration, 0, OTIS_LATENCY_D8,
          OTIS_LATENCY_FIRST_CONSUMPTION_TO_READY, OTIS_LATENCY_ELIGIBLE,
          OTIS_LATENCY_RP2040_TIMER_US32};
}
static OtisServiceLatencyStats fresh() {
  OtisServiceLatencyStats stats;
  otis_service_latency_reset(stats, OTIS_LATENCY_D8,
                            OTIS_LATENCY_FIRST_CONSUMPTION_TO_READY, 64);
  return stats;
}
int main() {
  auto stats = fresh();
  const uint32_t durations[] = {0, 1, 2, 4, 5, 16, 17, 64, 65, 256,
                               257, 1024, 1025, 4096, 4097, 0x7fffffff};
  for (uint32_t i = 0; i < 16; ++i)
    assert(otis_service_latency_observe(stats, sample(i, durations[i])) ==
           OTIS_LATENCY_ELIGIBLE);
  for (auto count : stats.histogram) assert(count == 2);
  assert(stats.eligible == 16 && stats.threshold_exceeded == 8);
  assert(stats.minimum_us == 0 && stats.minimum.source_sequence == 0);
  assert(stats.maximum_us == 0x7fffffff && stats.maximum.source_sequence == 15);
  assert(stats.tail_count == 2 && stats.tail[0].source_sequence == 15 &&
         stats.tail[1].source_sequence == 14);
  auto ambiguous = sample(16, 0x80000000);
  assert(otis_service_latency_observe(stats, ambiguous) == OTIS_LATENCY_AMBIGUOUS);
  ambiguous = sample(17, 0xffffffff);
  assert(otis_service_latency_observe(stats, ambiguous) == OTIS_LATENCY_AMBIGUOUS);
  assert(stats.have_noneligible);
  assert(stats.last_noneligible.source_sequence == 17);
  assert(stats.last_noneligible.start_us32 == ambiguous.start_us32);
  assert(stats.last_noneligible.end_us32 == ambiguous.end_us32);
  assert(stats.last_noneligible.status == OTIS_LATENCY_AMBIGUOUS);
  auto missing = sample(18, 0);
  missing.status = OTIS_LATENCY_MISSING;
  missing.domain = OTIS_LATENCY_DOMAIN_UNAVAILABLE;
  assert(otis_service_latency_observe(stats, missing) == OTIS_LATENCY_MISSING);
  assert(stats.missing == 1 && stats.ambiguous == 2 && stats.eligible == 16);
  assert(stats.last_noneligible.source_sequence == 18);
  assert(stats.last_noneligible.status == OTIS_LATENCY_MISSING);
  assert(stats.last_noneligible.domain == OTIS_LATENCY_DOMAIN_UNAVAILABLE);

  // Numeric zero is a genuine coordinate, never an implicit missing sentinel.
  stats = fresh();
  auto rollover = sample(UINT32_MAX, 0);
  rollover.start_us32 = UINT32_MAX - 9;
  rollover.end_us32 = 10;
  assert(otis_service_latency_observe(stats, rollover) == OTIS_LATENCY_ELIGIBLE);
  assert(stats.maximum_us == 20 && stats.maximum.start_us32 == UINT32_MAX - 9);
  rollover = sample(0, 0);
  rollover.start_us32 = rollover.end_us32 = 0;
  assert(otis_service_latency_observe(stats, rollover) == OTIS_LATENCY_ELIGIBLE);
  assert(stats.minimum_us == 0);
  // Duplicate and delayed prior source cannot change extrema or distributions.
  assert(otis_service_latency_observe(stats, rollover) == OTIS_LATENCY_AMBIGUOUS);
  assert(otis_service_latency_observe(stats, sample(UINT32_MAX, 500)) ==
         OTIS_LATENCY_AMBIGUOUS);
  assert(stats.eligible == 2 && stats.ambiguous == 2 && stats.maximum_us == 20);
  assert(otis_service_latency_observe(stats, sample(0, 500, 2)) ==
         OTIS_LATENCY_ELIGIBLE);
  assert(stats.maximum.capture_session == 2 && stats.minimum.capture_session == 1);
  assert(stats.last_capture_session == 2 && stats.last_source_sequence == 0);

  assert(otis_service_latency_observe(stats, sample(1, 5, 1)) ==
         OTIS_LATENCY_AMBIGUOUS);
  assert(stats.last_capture_session == 2 && stats.last_source_sequence == 0);
  auto uncertain = sample(1, 5, 2);
  uncertain.uncertainty_us = 1;
  assert(otis_service_latency_observe(stats, uncertain) == OTIS_LATENCY_AMBIGUOUS);
  assert(stats.last_noneligible.uncertainty_us == 1);

  auto wrong_domain = sample(1, 2, 2);
  wrong_domain.domain = OTIS_LATENCY_DOMAIN_UNAVAILABLE;
  assert(otis_service_latency_observe(stats, wrong_domain) == OTIS_LATENCY_AMBIGUOUS);
  auto wrong_identity = sample(2, 3, 2);
  wrong_identity.channel = OTIS_LATENCY_D14;
  assert(otis_service_latency_observe(stats, wrong_identity) == OTIS_LATENCY_AMBIGUOUS);
  assert(stats.diagnostic_drops == 1 && stats.last_source_sequence == 1);
  wrong_identity.channel = OTIS_LATENCY_D8;
  wrong_identity.stage = OTIS_LATENCY_READY_TO_FIRST_ESTIMATOR_CONSUMPTION;
  otis_service_latency_observe(stats, wrong_identity);
  assert(stats.diagnostic_drops == 2);

  // Bounded tail retains the slowest samples and earliest tied identities.
  stats = fresh();
  for (uint32_t i = 0; i < 100000; ++i)
    otis_service_latency_observe(stats, sample(i, i % 101));
  assert(stats.tail_count == 2 && stats.tail[0].source_sequence == 100 &&
         stats.tail[1].source_sequence == 201);
  assert(stats.minimum.source_sequence == 0 && stats.maximum.source_sequence == 100);
  otis_service_latency_note_drop(stats, UINT32_MAX);
  otis_service_latency_note_drop(stats);
  assert(stats.diagnostic_drops == UINT32_MAX && stats.counters_saturated);
  stats.eligible = UINT32_MAX;
  stats.histogram[0] = UINT32_MAX;
  otis_service_latency_observe(stats, sample(100000, 0));
  assert(stats.eligible == UINT32_MAX && stats.histogram[0] == UINT32_MAX);
  otis_service_latency_reset(stats, OTIS_LATENCY_D14,
                            OTIS_LATENCY_FIFO_READ_TO_FOREGROUND, 1000);
  assert(!stats.have_source && !stats.counters_saturated && stats.eligible == 0);
  assert(!stats.have_noneligible);
  printf("sample_bytes=%zu stats_bytes=%zu\n", sizeof(OtisServiceLatencySample),
         sizeof(OtisServiceLatencyStats));
}
