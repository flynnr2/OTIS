#ifndef OTIS_CX317_PREVIEW_LIVE_H
#define OTIS_CX317_PREVIEW_LIVE_H

#include <stdint.h>

#include "otis_pps_count_boundary.h"
#include "otis_cx317_active_live.h"
#include "otis_status_emit.h"

struct OtisCx317StaticCodeState {
  bool available;
  bool requested_applied_match;
  bool i2c_ok;
  uint16_t applied_code;
};

struct OtisCx317PreviewAuthorityState {
  bool estimator_valid;
  bool model_applicable;
  bool temperature_valid;
  uint16_t selected_interval_count;
};

bool otis_cx317_preview_live_begin(uint32_t startup_uptime_s);
void otis_cx317_preview_live_emit_headers(void);
void otis_cx317_preview_live_on_temperature(bool available,
                                            float temperature_c,
                                            uint32_t uptime_s);
void otis_cx317_preview_live_on_dac_applied(uint16_t applied_code,
                                           uint32_t uptime_s);
void otis_cx317_preview_live_on_boundary(
    const OtisPpsCountBoundaryObservation *observation,
    uint32_t interval_count, bool interval_valid, uint32_t uptime_s,
    const OtisCx317StaticCodeState *static_code,
    OtisCx317ActiveLiveOutcome *active_outcome);
void otis_cx317_preview_live_on_capture_fault(const char *reason,
                                             uint32_t uptime_s,
                                             const OtisCx317StaticCodeState *static_code);
bool otis_cx317_preview_live_request_recovery(void);
void otis_cx317_preview_live_service_transport(void);
bool otis_cx317_preview_live_transport_busy(void);
void otis_cx317_preview_live_emit_status(OtisStatusEmitContext *context);
void otis_cx317_preview_live_get_authority_state(
    OtisCx317PreviewAuthorityState *state);

#endif
