#ifndef OTIS_CAPTURE_PIO_H
#define OTIS_CAPTURE_PIO_H

#include <stdint.h>

#include "otis_capture_backend.h"

struct OtisCapturePioStats {
  uint32_t drained_event_count;
  uint32_t empty_count;
  uint32_t overflow_drop_count;
  uint32_t max_drain_batch;
};

bool otis_capture_pio_begin(const OtisCaptureBackendConfig &config);
void otis_capture_pio_service(void);
void otis_capture_pio_get_stats(OtisCapturePioStats *out);

#endif
