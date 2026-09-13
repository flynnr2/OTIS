#ifndef OTIS_PPS_SNAPSHOT_BACKEND_H
#define OTIS_PPS_SNAPSHOT_BACKEND_H

#include <stdint.h>

enum OtisPpsSnapshotStatus : uint32_t {
  OTIS_PPS_SNAPSHOT_STATUS_NONE = 0u,
  OTIS_PPS_SNAPSHOT_STATUS_OVERWRITE_BEFORE = 1u << 0,
  OTIS_PPS_SNAPSHOT_STATUS_PIO_RXSTALL = 1u << 1,
  OTIS_PPS_SNAPSHOT_STATUS_DMA_ERROR = 1u << 2,
  OTIS_PPS_SNAPSHOT_STATUS_DMA_STOPPED = 1u << 3,
};

struct OtisPpsHardwareSnapshot {
  uint32_t session;
  uint32_t sequence;
  uint32_t cumulative_down_counter;
  uint32_t status;
};

// A fail-closed, non-consuming snapshot of backend state taken before rearm.
// pio_fifo_depth reports words captured by PIO but not committed to the DMA
// ring. Such words have no stable ring ordinal and are never exposed as the
// unassociated front word.
struct OtisPpsSnapshotFrozenDiagnostic {
  bool frozen;
  uint32_t session;
  uint32_t producer_ordinal;
  uint32_t consumer_ordinal;
  uint32_t backlog_depth;
  uint32_t pio_fifo_depth;
  bool front_word_present;
  uint32_t front_word;
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
  uint32_t overwrite_count;
  uint32_t continuity_loss_count;
  uint32_t pio_rxstall_count;
  uint32_t dma_error_count;
  uint32_t dma_stopped_count;
  uint32_t fault_flags;
  uint32_t system_clock_hz;
  uint8_t pio_block;
  uint8_t state_machine;
  uint8_t program_offset;
  uint8_t program_length;
  uint8_t dma_channel;
  uint16_t ring_capacity;
};

bool otis_pps_snapshot_backend_begin(void);
void otis_pps_snapshot_backend_poll(void);
bool otis_pps_snapshot_backend_pop(OtisPpsHardwareSnapshot *snapshot);
void otis_pps_snapshot_backend_freeze_diagnostic(
    OtisPpsSnapshotFrozenDiagnostic *out);
bool otis_pps_snapshot_backend_rearm(void);
void otis_pps_snapshot_backend_get_stats(OtisPpsSnapshotBackendStats *out);

#endif
