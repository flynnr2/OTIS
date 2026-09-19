#ifndef OTIS_SERVICE_LATENCY_H
#define OTIS_SERVICE_LATENCY_H

#include <stdint.h>

// Diagnostic only. All operations are bounded, allocation-free and single-owner.
// Callers must not use these results as capture/control/abort predicates.
enum OtisServiceLatencyChannel : uint8_t {
  OTIS_LATENCY_D14 = 1,
  OTIS_LATENCY_D8 = 2,
  OTIS_LATENCY_OUTPUT = 3
};
enum OtisServiceLatencyStage : uint8_t {
  OTIS_LATENCY_FIFO_READ_TO_FOREGROUND = 0,
  OTIS_LATENCY_FIRST_CONSUMPTION_TO_READY = 1,
  OTIS_LATENCY_READY_TO_FIRST_ESTIMATOR_CONSUMPTION = 2,
  OTIS_LATENCY_QUEUE_PRECOMMIT_TO_CONSUMER_RETURN = 3,
  OTIS_LATENCY_OUTPUT_PRECOMMIT_TO_FORMATTER_DISPATCH = 4
};
enum OtisServiceLatencyStatus : uint8_t {
  OTIS_LATENCY_ELIGIBLE = 0,
  OTIS_LATENCY_MISSING = 1,
  OTIS_LATENCY_AMBIGUOUS = 2
};
enum OtisServiceLatencyDomain : uint8_t {
  OTIS_LATENCY_DOMAIN_UNAVAILABLE = 0,
  OTIS_LATENCY_RP2040_TIMER_US32 = 1
};

constexpr uint8_t OTIS_SERVICE_LATENCY_HISTOGRAM_VERSION = 1;
constexpr uint8_t OTIS_SERVICE_LATENCY_HISTOGRAM_BINS = 8;
constexpr uint8_t OTIS_SERVICE_LATENCY_TAIL_CAPACITY = 2;
constexpr uint32_t OTIS_SERVICE_LATENCY_HALF_RANGE = 0x80000000u;
// Inclusive upper bounds; final bin includes every remaining eligible delta.
extern const uint32_t otis_service_latency_histogram_upper_us[8];

struct OtisServiceLatencySample {
  uint32_t capture_session;
  uint32_t source_sequence;
  uint32_t start_us32;
  uint32_t end_us32;
  // Endpoint uncertainty supplied by the producer, separate from quantization.
  uint32_t uncertainty_us;
  OtisServiceLatencyChannel channel;
  OtisServiceLatencyStage stage;
  OtisServiceLatencyStatus status;
  OtisServiceLatencyDomain domain;
};

struct OtisServiceLatencyStats {
  OtisServiceLatencyChannel channel;
  OtisServiceLatencyStage stage;
  uint8_t tail_count;
  bool counters_saturated;
  uint32_t threshold_us;
  uint32_t eligible;
  uint32_t missing;
  uint32_t ambiguous;
  uint32_t threshold_exceeded;
  uint32_t diagnostic_drops;
  uint32_t histogram[OTIS_SERVICE_LATENCY_HISTOGRAM_BINS];
  uint32_t minimum_us;
  uint32_t maximum_us;
  OtisServiceLatencySample minimum;
  OtisServiceLatencySample maximum;
  // Two largest eligible observations, descending; ties retain earliest.
  OtisServiceLatencySample tail[OTIS_SERVICE_LATENCY_TAIL_CAPACITY];
  // Ordering is per stage/channel source sequence, not an unrelated counter.
  uint32_t last_capture_session;
  uint32_t last_source_sequence;
  bool have_source;
  bool have_noneligible;
  // Latest missing/ambiguous sample, with normalized status and raw endpoints.
  OtisServiceLatencySample last_noneligible;
};

void otis_service_latency_reset(OtisServiceLatencyStats &stats,
                               OtisServiceLatencyChannel channel,
                               OtisServiceLatencyStage stage,
                               uint32_t threshold_us);
// The caller establishes same-event endpoint identity and a lifetime below
// 2^31 us. Raw coordinates alone cannot distinguish a full extra timer wrap.
// Unknown domain, nonzero uncertainty, stale session, duplicate/backward sequence
// or a >=half-range delta is
// ambiguous. Session changes establish a new source ordering epoch but retain
// cumulative statistics and extrema identities. Missing samples stay missing.
OtisServiceLatencyStatus otis_service_latency_observe(
    OtisServiceLatencyStats &stats, const OtisServiceLatencySample &sample);
void otis_service_latency_note_drop(OtisServiceLatencyStats &stats,
                                   uint32_t count = 1);
uint8_t otis_service_latency_histogram_bin(uint32_t elapsed_us);

static_assert(sizeof(OtisServiceLatencySample) == 24,
              "Latency samples must remain bounded small copies");
static_assert(sizeof(OtisServiceLatencyStats) <= 224,
              "Latency statistics exceeded their per-stream budget");
#endif
