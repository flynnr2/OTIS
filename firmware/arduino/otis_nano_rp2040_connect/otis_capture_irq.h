#ifndef OTIS_CAPTURE_IRQ_H
#define OTIS_CAPTURE_IRQ_H

#include <stdint.h>

#include "otis_capture_backend.h"

typedef void (*OtisPpsCountBoundaryIsrHandler)(uint64_t timestamp_ticks,
                                                uint32_t capture_flags);

struct OtisCaptureIrqReferenceStats {
  uint32_t d14_raw_edge_count;
  uint32_t d14_accepted_pps_count;
  uint32_t d14_rejected_short_count;
  uint32_t d14_rejected_long_count;
  uint64_t d14_last_raw_timestamp;
  uint64_t d14_last_raw_interval;
  uint64_t d14_last_accepted_timestamp;
  uint32_t d14_sampled_high_count;
  uint32_t d14_sampled_low_count;
};

bool otis_capture_irq_begin(const OtisCaptureBackendConfig &config);
void otis_capture_irq_set_pps_count_boundary_handler(
    OtisPpsCountBoundaryIsrHandler handler);
uint32_t otis_capture_irq_edge_count(void);
void otis_capture_irq_get_reference_stats(OtisCaptureIrqReferenceStats *out);
void otis_capture_irq_begin_tcxo_counter(uint32_t gpio);
uint32_t otis_capture_irq_read_and_reset_tcxo_count(void);

#endif
