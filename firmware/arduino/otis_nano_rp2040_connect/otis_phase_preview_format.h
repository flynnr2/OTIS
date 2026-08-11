#ifndef OTIS_PHASE_PREVIEW_FORMAT_H
#define OTIS_PHASE_PREVIEW_FORMAT_H

#include <stddef.h>

#include "otis_dual_core_contract.h"

const char *otis_phase_preview_rph_header(void);
const char *otis_phase_preview_phe_header(void);
const char *otis_phase_preview_hpr_header(void);

bool otis_phase_preview_format_rph(const OtisPhasePreviewRecordMessage *message,
                           char *output, size_t output_size, size_t *length);
bool otis_phase_preview_format_phe(const OtisPhasePreviewRecordMessage *message,
                           char *output, size_t output_size, size_t *length);
bool otis_phase_preview_format_hpr(const OtisPhasePreviewRecordMessage *message,
                           char *output, size_t output_size, size_t *length);

#endif
