#ifndef OTIS_PHASE_PREVIEW_LIVE_H
#define OTIS_PHASE_PREVIEW_LIVE_H

#include <stdint.h>

#include "otis_pps_count_boundary.h"

struct OtisPhasePreviewLiveStatus {
  bool initialized;
  // Stage 4 compatibility: these describe the immutable boot-time premise.
  bool static_code_bound;
  uint16_t static_code;
  // The current Core 0-confirmed code context consumed by Core 1.  It equals
  // static_code for an unchanged Stage 4 preview run.
  bool applied_code_bound;
  uint16_t applied_code;
  uint32_t dac_epoch;
  uint32_t published_records;
  uint32_t last_phase_epoch;
  uint32_t last_observation_sequence;
};

// Called only on Core 1. The static code must have been confirmed by preflight;
// this function has no mechanism to read or write a DAC.
bool otis_phase_preview_live_begin(uint16_t confirmed_static_code,
                                   uint32_t dac_epoch);
// Called by the timing owner only after Core 0's DAC application has been
// confirmed.  This is a one-way observation update: it neither requests nor
// writes a DAC value, and has no path back to an active controller.  Epochs
// must not move backwards; a repeated epoch may only repeat the same code.
bool otis_phase_preview_live_update_applied_code(
    uint16_t confirmed_applied_code, uint32_t dac_epoch);
void otis_phase_preview_live_on_boundary(
    const OtisPpsCountBoundaryObservation *observation,
    uint32_t snapshot_status, uint32_t counted_edges,
    bool counted_edges_available, bool reference_qualified,
    bool phase_step_detected);
void otis_phase_preview_live_note_reset(void);
void otis_phase_preview_live_get_status(OtisPhasePreviewLiveStatus *status);

#endif
