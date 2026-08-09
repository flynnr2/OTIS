#ifndef OTIS_CX318_PREVIEW_FORMAT_H
#define OTIS_CX318_PREVIEW_FORMAT_H

#include <stddef.h>

#include "otis_dual_core_contract.h"

const char *otis_cx318_rph_header(void);
const char *otis_cx318_phe_header(void);
const char *otis_cx318_hpr_header(void);

bool otis_cx318_format_rph(const OtisCx318PreviewRecordMessage *message,
                           char *output, size_t output_size, size_t *length);
bool otis_cx318_format_phe(const OtisCx318PreviewRecordMessage *message,
                           char *output, size_t output_size, size_t *length);
bool otis_cx318_format_hpr(const OtisCx318PreviewRecordMessage *message,
                           char *output, size_t output_size, size_t *length);

#endif
