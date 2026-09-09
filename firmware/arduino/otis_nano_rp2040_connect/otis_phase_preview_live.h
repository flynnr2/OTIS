#ifndef OTIS_PHASE_PREVIEW_LIVE_H
#define OTIS_PHASE_PREVIEW_LIVE_H

#include <stdint.h>

#include "otis_pps_count_boundary.h"

struct OtisPhasePreviewLiveStatus {
  bool initialized;
  // The current Core 0-confirmed code context consumed by Core 1. It remains
  // unbound until the setup application is physically confirmed.
  bool applied_code_bound;
  uint16_t applied_code;
  uint32_t dac_epoch;
  uint32_t published_records;
  uint32_t last_phase_epoch;
  uint32_t last_observation_sequence;
};

// Adaptive-hybrid-only same-core handoff. This snapshot is published only
// after the canonical RPH/PHE evidence has entered the recorder queue, so the
// active policy cannot consume phase evidence that the recorder did not accept.
struct OtisPhasePreviewActiveSnapshot {
  bool available;
  bool recorder_published;
  bool phase_continuous;
  bool phase_current;
  bool phase_step_detected;
  uint32_t capture_session;
  uint32_t phase_epoch;
  uint32_t observation_sequence;
  int64_t relative_phase_cycles;
  uint32_t dac_epoch;
  uint16_t applied_code;
};

// Called only on Core 1. This initializes the service without inventing a DAC
// state; the numerical preview remains dormant until the first confirmed
// application arrives through update_applied_code().
bool otis_phase_preview_live_begin(void);
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
bool otis_phase_preview_live_get_active_snapshot(
    OtisPhasePreviewActiveSnapshot *snapshot);

#endif
