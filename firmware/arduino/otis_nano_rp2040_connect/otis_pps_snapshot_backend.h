#ifndef OTIS_PPS_SNAPSHOT_BACKEND_H
#define OTIS_PPS_SNAPSHOT_BACKEND_H

#include <stdint.h>

// These bits describe transport evidence carried by one immutable raw FIFO
// record. Any non-zero value withholds the record from reference acceptance;
// the raw D8 counter word remains canonical evidence.
enum OtisPpsSnapshotStatus : uint32_t {
  OTIS_PPS_SNAPSHOT_STATUS_NONE = 0u,
  OTIS_PPS_SNAPSHOT_STATUS_TIMESTAMP_AMBIGUOUS = 1u << 0,
  OTIS_PPS_SNAPSHOT_STATUS_TIMESTAMP_UNBOUNDED = 1u << 1,
  OTIS_PPS_SNAPSHOT_STATUS_PIO_RXSTALL = 1u << 2,
  OTIS_PPS_SNAPSHOT_STATUS_RING_FULL = 1u << 3,
  OTIS_PPS_SNAPSHOT_STATUS_IRQ_BUDGET_EXHAUSTED = 1u << 4,
};

struct OtisPpsHardwareSnapshot {
  uint32_t session;
  uint32_t sequence;
  uint32_t cumulative_down_counter;
  uint32_t status;
  // RP2040 monotonic us32 sampled after this committed FIFO word was read.
  // It is a FIFO service coordinate, never a D14 hardware-edge timestamp.
  uint32_t service_ticks;
  // Inclusive width of the conservative [last-observed-empty, service]
  // bracket, including the audited 1 us PIO recognition-to-push margin.
  // UINT32_MAX means that no valid empty lower bound was available.
  uint32_t timestamp_uncertainty_ticks;
};

struct OtisPpsSnapshotBackendStats {
  bool initialized;
  bool running;
  bool fault_latched;
  uint32_t session;
  uint32_t producer_ordinal;
  uint32_t consumer_ordinal;
  uint32_t backlog_depth;
  uint32_t backlog_high_water;
  uint32_t continuity_loss_count;
  uint32_t pio_rxstall_count;
  uint32_t irq_budget_exhausted_count;
  uint32_t ring_full_count;
  uint32_t timestamp_ambiguous_count;
  uint32_t fault_flags;
  uint32_t last_service_ticks;
  uint32_t system_clock_hz;
  uint8_t pio_block;
  uint8_t state_machine;
  uint8_t program_offset;
  uint8_t program_length;
  uint16_t ring_capacity;
};

bool otis_pps_snapshot_backend_begin(void);

// The sole foreground service-credit boundary. A call admits at most one
// source-filtered IRQ entry and eight FIFO word reads before the next call.
void otis_pps_snapshot_backend_poll(void);

// Non-consuming calls: neither replenishes IRQ credit nor rearms a source.
// get_stats also samples and latches the sticky RXSTALL hardware fault before
// returning so authority checks cannot use a stale clean snapshot.
bool otis_pps_snapshot_backend_pop(OtisPpsHardwareSnapshot *snapshot);
void otis_pps_snapshot_backend_get_stats(OtisPpsSnapshotBackendStats *out);

// Explicit session transition. Rearm succeeds only after all software-ring
// and retained hardware-FIFO evidence from the old session has been drained.
bool otis_pps_snapshot_backend_rearm(void);

#endif
