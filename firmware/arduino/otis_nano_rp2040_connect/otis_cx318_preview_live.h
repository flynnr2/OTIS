#ifndef OTIS_CX318_PREVIEW_LIVE_H
#define OTIS_CX318_PREVIEW_LIVE_H

#include <stdint.h>

#include "otis_pps_count_boundary.h"

struct OtisCx318PreviewLiveStatus {
  bool initialized;
  bool static_code_bound;
  uint16_t static_code;
  uint32_t dac_epoch;
  uint32_t published_records;
  uint32_t last_phase_epoch;
  uint32_t last_observation_sequence;
};

// Called only on Core 1. The static code must have been confirmed by preflight;
// this function has no mechanism to read or write a DAC.
bool otis_cx318_preview_live_begin(uint16_t confirmed_static_code,
                                   uint32_t dac_epoch);
void otis_cx318_preview_live_on_boundary(
    const OtisPpsCountBoundaryObservation *observation,
    uint32_t snapshot_status, uint32_t counted_edges,
    bool counted_edges_available, bool reference_qualified,
    bool phase_step_detected);
void otis_cx318_preview_live_note_reset(void);
void otis_cx318_preview_live_get_status(OtisCx318PreviewLiveStatus *status);

#endif
