#ifndef OTIS_PHASE4_OBSERVE_PREVIEW_H
#define OTIS_PHASE4_OBSERVE_PREVIEW_H

#include <stdint.h>

#include "otis_runtime_state.h"
#include "otis_status_emit.h"

struct OtisPhase4LiveDacState {
  bool available;
  uint16_t applied_code;
};

bool otis_phase4_observe_preview_begin(uint64_t startup_ticks);
void otis_phase4_observe_preview_on_temperature(bool available,
                                                float temperature_c,
                                                uint64_t timestamp_ticks);
void otis_phase4_observe_preview_on_dac_applied(uint16_t applied_code,
                                               uint64_t timestamp_ticks);
void otis_phase4_observe_preview_emit_headers(void);
void otis_phase4_observe_preview_on_reference(uint32_t reference_seq,
                                              uint64_t timestamp_ticks,
                                              uint32_t flags,
                                              OtisRuntimeState *runtime_state,
                                              const OtisPhase4LiveDacState *dac);
void otis_phase4_observe_preview_on_count(
    uint32_t count_seq, OtisRuntimeState *runtime_state,
    const OtisPhase4LiveDacState *dac);
void otis_phase4_observe_preview_poll(uint64_t now_ticks,
                                     OtisRuntimeState *runtime_state,
                                     const OtisPhase4LiveDacState *dac);
void otis_phase4_observe_preview_service_transport(void);
bool otis_phase4_observe_preview_transport_busy(void);
void otis_phase4_observe_preview_emit_status(
    OtisStatusEmitContext *status_context);
uint32_t otis_phase4_observe_preview_dropped_pair_count(void);
uint8_t otis_phase4_observe_preview_queue_high_water(void);

#endif
