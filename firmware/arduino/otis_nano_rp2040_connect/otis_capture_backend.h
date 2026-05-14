#ifndef OTIS_CAPTURE_BACKEND_H
#define OTIS_CAPTURE_BACKEND_H

#include <stdint.h>

#include "otis_capture_ring.h"

enum class OtisCaptureBackendKind : uint8_t {
  None,
  GpioIrq,
  PioEdgeQueue,
};

typedef void (*OtisCaptureEmitFn)(const OtisCapturedEdge &record);

struct OtisCaptureBackendConfig {
  uint32_t gpio;
  uint32_t channel_id;
  bool reference_record;
  int interrupt_mode;
  OtisCaptureEmitFn emit_record;
};

struct OtisCaptureBackendStats {
  uint32_t irq_edges;
  uint32_t pio_edges;
  uint32_t backend_overflows;
  uint32_t ring_drops;
  uint32_t pio_fifo_empty_count;
  uint32_t pio_fifo_max_drain_batch;
};

bool otis_capture_backend_begin(OtisCaptureBackendKind kind,
                                const OtisCaptureBackendConfig &config);
void otis_capture_backend_service(void);
void otis_capture_backend_get_stats(OtisCaptureBackendStats *out);

#endif
