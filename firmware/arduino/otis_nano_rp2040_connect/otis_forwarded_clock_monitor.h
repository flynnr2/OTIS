#ifndef OTIS_FORWARDED_CLOCK_MONITOR_H
#define OTIS_FORWARDED_CLOCK_MONITOR_H

#include <stdint.h>

// This monitor is a diagnostic sidecar for the fixed D8 -> D9 forwarding
// topology.  Its snapshots are conditioned by D14 so an interval can be
// associated with an authoritative boundary, but it is not an input to D14/D8
// validity, control eligibility, or actuation.
enum OtisForwardedClockMonitorStatus : uint32_t {
  OTIS_FORWARDED_CLOCK_MONITOR_STATUS_NONE = 0u,
  OTIS_FORWARDED_CLOCK_MONITOR_STATUS_DISABLED_PROFILE = 1u << 0,
  OTIS_FORWARDED_CLOCK_MONITOR_STATUS_NO_SNAPSHOT = 1u << 1,
  OTIS_FORWARDED_CLOCK_MONITOR_STATUS_FIFO_BACKLOG = 1u << 2,
  OTIS_FORWARDED_CLOCK_MONITOR_STATUS_PIO_RXSTALL = 1u << 3,
  OTIS_FORWARDED_CLOCK_MONITOR_STATUS_READ_PENDING = 1u << 4,
  OTIS_FORWARDED_CLOCK_MONITOR_STATUS_RESOURCE_BINDING_FAILED = 1u << 5,
  OTIS_FORWARDED_CLOCK_MONITOR_STATUS_SYSTEM_CLOCK_MISMATCH = 1u << 6,
};

// `sequence` is local to this monitor session. `reference_*` binds the raw
// cumulative count to the D14/D8 boundary at which it was CPU-drained.
struct OtisForwardedClockMonitorSnapshot {
  uint32_t session;
  uint32_t sequence;
  uint32_t cumulative_down_counter;
  uint32_t reference_session;
  uint32_t reference_sequence;
  uint32_t status;
};

struct OtisForwardedClockMonitorStats {
  bool selected;
  bool configured;
  bool running;
  bool fault_latched;
  bool read_pending;
  uint32_t session;
  uint32_t reference_service_count;
  uint32_t snapshot_count;
  uint32_t no_snapshot_count;
  uint32_t fifo_backlog_count;
  uint32_t pio_rxstall_count;
  uint32_t fault_flags;
  uint32_t last_status;
  uint32_t system_clock_hz;
  uint8_t pio_block;
  uint8_t state_machine;
  uint8_t program_offset;
  uint8_t program_length;
  uint8_t source_gpio;
  uint8_t reference_gpio;
};

// Call after the D8 cumulative-count backend and fixed D9 output are ready,
// before D14 edges are associated. It claims an independent PIO0 state
// machine and an independent copy of the existing 15-word snapshot program.
// A failed begin is diagnostic-local and must not prevent D14/D8 capture.
bool otis_forwarded_clock_monitor_begin(void);

// Polls only local PIO health; it never drains the RX FIFO.
void otis_forwarded_clock_monitor_poll(void);

// Performs at most one FIFO read for this D14 reference boundary. False means
// no raw snapshot was available (or the monitor is locally disabled/faulted).
// Calling code must record this as D6-local evidence only and continue the
// authoritative D14/D8 path unchanged.
bool otis_forwarded_clock_monitor_service(uint32_t reference_session,
                                          uint32_t reference_sequence);

// Returns the one snapshot retained by service(), if any. A caller that has
// not consumed it before the next service call receives a local READ_PENDING
// diagnostic; the monitor never blocks or backpressures the D14/D8 path.
bool otis_forwarded_clock_monitor_read(OtisForwardedClockMonitorSnapshot *out);

void otis_forwarded_clock_monitor_get_stats(OtisForwardedClockMonitorStats *out);

#endif
