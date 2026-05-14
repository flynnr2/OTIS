#ifndef OTIS_CAPTURE_IRQ_H
#define OTIS_CAPTURE_IRQ_H

#include <stdint.h>

#include "otis_capture_backend.h"

bool otis_capture_irq_begin(const OtisCaptureBackendConfig &config);
uint32_t otis_capture_irq_edge_count(void);
void otis_capture_irq_begin_tcxo_counter(uint32_t gpio);
uint32_t otis_capture_irq_read_and_reset_tcxo_count(void);

#endif
