#ifndef OTIS_PPS_FIFO_DRAIN_H
#define OTIS_PPS_FIFO_DRAIN_H

#include <stdint.h>

// Work-branch prototype, not linked into an instrument profile. Port must be
// the sole FIFO reader, with bounded, nonblocking operations. stop() disables
// this SM and its FIFO IRQ source; it must not clear retained FIFO contents.
// The caller reserves ring_slots before entry and must retain every returned
// word, including words from a faulted batch. No acceptance decision lives here.
enum OtisPpsFifoDrainFault : uint32_t {
  OTIS_FIFO_DRAIN_NONE = 0u,
  OTIS_FIFO_DRAIN_RXSTALL = 1u << 0,
  OTIS_FIFO_DRAIN_RING_FULL = 1u << 1,
  OTIS_FIFO_DRAIN_BUDGET = 1u << 2,
  OTIS_FIFO_DRAIN_NO_SESSION = 1u << 3,
};

struct OtisPpsFifoWord {
  uint32_t session;
  uint32_t ordinal;
  uint32_t cumulative_down_counter;
  uint32_t service_ticks;  // CPU us32 AFTER reading FIFO; never edge/latch time.
};

struct OtisPpsFifoDrainResult {
  OtisPpsFifoWord words[8];
  uint32_t count;
  uint32_t faults;
  bool timestamp_ambiguous;
  bool stopped;
};

template <typename Port>
OtisPpsFifoDrainResult otis_pps_fifo_drain(
    Port &port, uint32_t session, uint32_t &next_ordinal,
    uint32_t ring_slots) {
  OtisPpsFifoDrainResult result = {};
  auto stop = [&]() {
    if (!result.stopped) {
      port.stop();
      result.stopped = true;
    }
  };
  if (session == 0u) {
    result.faults |= OTIS_FIFO_DRAIN_NO_SESSION;
    stop();
    return result;
  }
  if (port.rxstall()) {
    result.faults |= OTIS_FIFO_DRAIN_RXSTALL;
    stop();  // Freeze before reading: a stalled autopush is not a FIFO word.
  }
  const uint32_t initial_depth = port.depth();
  result.timestamp_ambiguous = initial_depth > 1u;
  const uint32_t budget = ring_slots < 8u ? ring_slots : 8u;
  while (result.count < budget && port.depth() != 0u) {
    const uint32_t raw = port.read();
    const uint32_t service_ticks = port.service_ticks();
    result.words[result.count++] = {session, next_ordinal++, raw, service_ticks};
    if (port.rxstall()) {
      result.faults |= OTIS_FIFO_DRAIN_RXSTALL;
      stop();
    }
  }
  result.timestamp_ambiguous = result.timestamp_ambiguous || result.count > 1u;
  if (port.depth() != 0u) {
    result.faults |= budget < 8u ? OTIS_FIFO_DRAIN_RING_FULL
                               : OTIS_FIFO_DRAIN_BUDGET;
    stop();  // Do not return into an enabled, continually refilling level IRQ.
  }
  // A singleton alone does NOT prove service latency or timestamp sufficiency.
  // The one downstream acceptance gate must assess these source coordinates.
  return result;
}

#endif
