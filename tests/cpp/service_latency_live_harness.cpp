#include "otis_service_latency_live.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>

static size_t available = 4096;
static size_t writes = 0;
static std::string output;
bool otis_transport_try_write_diagnostic(const uint8_t *data, size_t size) {
  if (size + 64 > available) return false;
  assert(size < 256);
  ++writes;
  output.append(reinterpret_cast<const char *>(data), size);
  return true;
}
static void note(uint32_t channel, uint32_t stage, uint32_t seq, uint32_t delay,
                 OtisServiceLatencyStatus status = OTIS_LATENCY_ELIGIBLE) {
  otis_service_latency_live_note({99, seq, 0xfffffff0u, 0xfffffff0u + delay,
      0, static_cast<OtisServiceLatencyChannel>(channel),
      static_cast<OtisServiceLatencyStage>(stage), status,
      OTIS_LATENCY_RP2040_TIMER_US32});
}
int main(int argc, char **argv) {
  const bool congested = argc > 1 && strcmp(argv[1], "congested") == 0;
  for (uint32_t stage = 0; stage < 5; ++stage)
    for (uint32_t channel = 1; channel <= 2; ++channel) {
      note(channel, stage, 41, 1);
      note(channel, stage, 42, 2000);
      note(channel, stage, 43, 0, OTIS_LATENCY_MISSING);
      note(channel, stage, 44, 0, OTIS_LATENCY_AMBIGUOUS);
    }
  // A request alone produces nothing, nor do repeated serial polls fabricate a
  // timing-owner response. Service after request provides the coherent copy.
  otis_service_latency_live_output_service(249);
  otis_service_latency_live_output_service(250);
  otis_service_latency_live_output_service(499);
  otis_service_latency_live_output_service(500);
  assert(writes == 0);
  otis_service_latency_live_timing_service();
  // Publication copied seq42's maximum. Later updates must not tear its parts.
  note(1, 0, 45, 4000);
  if (congested) available = 64;
  // 152 ticks cover two complete traversals, with no unbounded wait dependency.
  for (uint32_t tick = 3; tick < 155; ++tick) {
    const size_t previous_writes = writes;
    otis_service_latency_live_output_service(tick * 250);
    assert(writes - previous_writes <= 1);
    otis_service_latency_live_output_service(tick * 250);
    otis_service_latency_live_output_service(tick * 250 + 249);
    assert(writes - previous_writes <= 1);
    otis_service_latency_live_timing_service();
    if (congested && tick < 78) assert(writes == 0);
    // First ten complete reports dropped; next traversal retains counts.
    if (congested && tick == 77) available = 4096;
  }
  fwrite(output.data(), 1, output.size(), stdout);
}
