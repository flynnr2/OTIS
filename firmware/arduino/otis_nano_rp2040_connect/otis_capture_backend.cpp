#include "otis_capture_backend.h"

#include "otis_capture_irq.h"
#include "otis_capture_pio.h"
#include "otis_capture_ring.h"

namespace {

OtisCaptureBackendKind active_backend = OtisCaptureBackendKind::None;

}  // namespace

bool otis_capture_backend_begin(OtisCaptureBackendKind kind,
                                const OtisCaptureBackendConfig &config) {
  active_backend = kind;
  switch (kind) {
    case OtisCaptureBackendKind::None:
      return true;
    case OtisCaptureBackendKind::GpioIrq:
      return otis_capture_irq_begin(config);
    case OtisCaptureBackendKind::PioEdgeQueue:
      return otis_capture_pio_begin(config);
  }
  return false;
}

void otis_capture_backend_service(void) {
  if (active_backend == OtisCaptureBackendKind::PioEdgeQueue) {
    otis_capture_pio_service();
  }
}

void otis_capture_backend_get_stats(OtisCaptureBackendStats *out) {
  if (out == nullptr) {
    return;
  }

  out->irq_edges = otis_capture_irq_edge_count();
  out->pio_edges = 0;
  out->backend_overflows = 0;
  out->ring_drops = otis_capture_ring_dropped_count();
  out->pio_fifo_empty_count = 0;
  out->pio_fifo_max_drain_batch = 0;

  OtisCapturePioStats pio_stats;
  otis_capture_pio_get_stats(&pio_stats);
  out->pio_edges = pio_stats.drained_event_count;
  out->backend_overflows = pio_stats.overflow_drop_count;
  out->pio_fifo_empty_count = pio_stats.empty_count;
  out->pio_fifo_max_drain_batch = pio_stats.max_drain_batch;
}
