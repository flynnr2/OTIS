#ifndef OTIS_COUNT_OBSERVATION_H
#define OTIS_COUNT_OBSERVATION_H

#include <stdint.h>

#include "otis_pps_count_boundary.h"
#include "otis_runtime_state.h"
#include "otis_status_emit.h"

struct OtisCountObservationConfig {
  uint32_t gate_period_us;
  uint32_t measure_period_ms;
  uint32_t startup_inhibit_ms;
  uint32_t control_ready_clean_windows;
  const char *source_domain;
};

bool otis_count_observation_begin(OtisRuntimeState *runtime_state,
                                  OtisStatusEmitContext *status_context,
                                  const OtisCountObservationConfig *config);
bool otis_count_observation_on_pps_boundary(
    OtisRuntimeState *runtime_state,
    OtisStatusEmitContext *status_context,
    const OtisCountObservationConfig *config,
    const OtisPpsCountBoundaryObservation *observation);
void otis_count_observation_note_association_loss(
    OtisRuntimeState *runtime_state,
    OtisStatusEmitContext *status_context,
    uint32_t reference_sequence,
    const char *reason);
void otis_count_observation_note_control_consumer(uint32_t session,
                                                  uint32_t sequence);
bool otis_count_observation_service(OtisRuntimeState *runtime_state,
                                    OtisStatusEmitContext *status_context,
                                    const OtisCountObservationConfig *config);
void otis_count_observation_emit_status(
    OtisRuntimeState *runtime_state,
    OtisStatusEmitContext *status_context);
const char *otis_count_observation_measurement_mode(void);
const char *otis_count_observation_window_invalid_reason(
    const OtisRuntimeState *runtime_state);

#endif
