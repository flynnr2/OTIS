#ifndef OTIS_OBSERVE_ONLY_DISCIPLINE_LIVE_H
#define OTIS_OBSERVE_ONLY_DISCIPLINE_LIVE_H

#include <stdint.h>

#include "otis_runtime_state.h"
#include "otis_status_emit.h"

struct OtisObserveOnlyDisciplineLiveDacState {
  bool available;
  uint16_t applied_code;
};

bool otis_observe_only_discipline_live_begin(uint64_t startup_ticks);
void otis_observe_only_discipline_live_on_temperature(bool available,
                                                float temperature_c,
                                                uint64_t timestamp_ticks);
void otis_observe_only_discipline_live_on_dac_applied(uint16_t applied_code,
                                               uint64_t timestamp_ticks);
void otis_observe_only_discipline_live_emit_headers(void);
void otis_observe_only_discipline_live_on_reference(uint32_t reference_seq,
                                              uint64_t timestamp_ticks,
                                              uint32_t flags,
                                              OtisRuntimeState *runtime_state,
                                              const OtisObserveOnlyDisciplineLiveDacState *dac);
void otis_observe_only_discipline_live_on_count(
    uint32_t count_seq, OtisRuntimeState *runtime_state,
    const OtisObserveOnlyDisciplineLiveDacState *dac);
void otis_observe_only_discipline_live_poll(uint64_t now_ticks,
                                     OtisRuntimeState *runtime_state,
                                     const OtisObserveOnlyDisciplineLiveDacState *dac);
void otis_observe_only_discipline_live_service_transport(void);
bool otis_observe_only_discipline_live_transport_busy(void);
bool otis_observe_only_discipline_live_transport_pending(void);
void otis_observe_only_discipline_live_emit_status(
    OtisStatusEmitContext *status_context);
uint32_t otis_observe_only_discipline_live_dropped_pair_count(void);
uint8_t otis_observe_only_discipline_live_queue_high_water(void);

#endif
