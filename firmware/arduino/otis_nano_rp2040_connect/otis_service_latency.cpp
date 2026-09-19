#include "otis_service_latency.h"

const uint32_t otis_service_latency_histogram_upper_us[8] = {
    1, 4, 16, 64, 256, 1024, 4096, 0x7fffffffu};

namespace {
void add_saturated(uint32_t &value, uint32_t amount, bool &saturated) {
  if (amount > UINT32_MAX - value) {
    value = UINT32_MAX;
    saturated = true;
  } else {
    value += amount;
  }
}
uint32_t elapsed(const OtisServiceLatencySample &sample) {
  return sample.end_us32 - sample.start_us32;
}
}

void otis_service_latency_reset(OtisServiceLatencyStats &stats,
                               OtisServiceLatencyChannel channel,
                               OtisServiceLatencyStage stage,
                               uint32_t threshold_us) {
  stats = {};
  stats.channel = channel;
  stats.stage = stage;
  stats.threshold_us = threshold_us;
}

uint8_t otis_service_latency_histogram_bin(uint32_t elapsed_us) {
  for (uint8_t i = 0; i + 1 < OTIS_SERVICE_LATENCY_HISTOGRAM_BINS; ++i) {
    if (elapsed_us <= otis_service_latency_histogram_upper_us[i]) return i;
  }
  return OTIS_SERVICE_LATENCY_HISTOGRAM_BINS - 1;
}

OtisServiceLatencyStatus otis_service_latency_observe(
    OtisServiceLatencyStats &stats, const OtisServiceLatencySample &sample) {
  OtisServiceLatencyStatus status = sample.status;
  if (sample.channel != stats.channel || sample.stage != stats.stage) {
    otis_service_latency_note_drop(stats);
    return OTIS_LATENCY_AMBIGUOUS;
  }
  const uint32_t advance = sample.source_sequence - stats.last_source_sequence;
  const uint32_t session_advance = sample.capture_session - stats.last_capture_session;
  const bool reordered = stats.have_source &&
      ((session_advance == 0u &&
        (advance == 0u || advance >= OTIS_SERVICE_LATENCY_HALF_RANGE)) ||
       session_advance >= OTIS_SERVICE_LATENCY_HALF_RANGE);
  if (!reordered) {
    stats.have_source = true;
    stats.last_capture_session = sample.capture_session;
    stats.last_source_sequence = sample.source_sequence;
  }
  if (status != OTIS_LATENCY_MISSING &&
      (status != OTIS_LATENCY_ELIGIBLE || reordered ||
       sample.domain != OTIS_LATENCY_RP2040_TIMER_US32 ||
       elapsed(sample) >= OTIS_SERVICE_LATENCY_HALF_RANGE ||
       sample.uncertainty_us != 0u)) {
    status = OTIS_LATENCY_AMBIGUOUS;
  }
  if (status != OTIS_LATENCY_ELIGIBLE) {
    stats.last_noneligible = sample;
    stats.last_noneligible.status = status;
    stats.have_noneligible = true;
  }
  if (status == OTIS_LATENCY_MISSING) {
    add_saturated(stats.missing, 1, stats.counters_saturated);
    return status;
  }
  if (status == OTIS_LATENCY_AMBIGUOUS) {
    add_saturated(stats.ambiguous, 1, stats.counters_saturated);
    return status;
  }
  const uint32_t duration = elapsed(sample);
  const bool first = stats.eligible == 0;
  add_saturated(stats.eligible, 1, stats.counters_saturated);
  add_saturated(stats.histogram[otis_service_latency_histogram_bin(duration)],
                1, stats.counters_saturated);
  if (duration > stats.threshold_us)
    add_saturated(stats.threshold_exceeded, 1, stats.counters_saturated);
  if (first || duration < stats.minimum_us) {
    stats.minimum_us = duration;
    stats.minimum = sample;
  }
  if (first || duration > stats.maximum_us) {
    stats.maximum_us = duration;
    stats.maximum = sample;
  }
  for (uint8_t i = 0; i < OTIS_SERVICE_LATENCY_TAIL_CAPACITY; ++i) {
    if (i >= stats.tail_count || duration > elapsed(stats.tail[i])) {
      for (uint8_t j = OTIS_SERVICE_LATENCY_TAIL_CAPACITY - 1; j > i; --j)
        stats.tail[j] = stats.tail[j - 1];
      stats.tail[i] = sample;
      if (stats.tail_count < OTIS_SERVICE_LATENCY_TAIL_CAPACITY)
        ++stats.tail_count;
      break;
    }
  }
  return status;
}

void otis_service_latency_note_drop(OtisServiceLatencyStats &stats,
                                   uint32_t count) {
  add_saturated(stats.diagnostic_drops, count, stats.counters_saturated);
}
