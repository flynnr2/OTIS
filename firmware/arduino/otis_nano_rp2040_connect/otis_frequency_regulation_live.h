#ifndef OTIS_FREQUENCY_REGULATION_LIVE_H
#define OTIS_FREQUENCY_REGULATION_LIVE_H

#include <stdint.h>

#include "otis_pps_count_boundary.h"
#include "otis_adaptive_hybrid_regulation_live.h"
#include "otis_status_emit.h"

struct OtisRegulationStaticCodeState {
  bool available;
  bool requested_applied_match;
  bool i2c_ok;
  uint16_t applied_code;
};

struct OtisFrequencyRegulationAuthorityState {
  bool estimator_valid;
  bool model_applicable;
  bool temperature_valid;
  uint16_t selected_interval_count;
};

bool otis_frequency_regulation_live_begin(uint32_t startup_uptime_s);
void otis_frequency_regulation_live_emit_headers(void);
void otis_frequency_regulation_live_on_temperature(bool available,
                                            float temperature_c,
                                            uint32_t uptime_s);
void otis_frequency_regulation_live_on_dac_applied(uint16_t applied_code,
                                           uint32_t uptime_s);
void otis_frequency_regulation_live_on_dac_applied_epoch(uint16_t applied_code,
                                                 uint32_t dac_epoch,
                                                 uint32_t uptime_s);
void otis_frequency_regulation_live_on_dac_applied_epoch_exact(
    uint16_t applied_code, uint32_t dac_epoch, uint32_t uptime_s,
    uint64_t application_ticks, uint32_t capture_session);
bool otis_frequency_regulation_live_applied_epoch_exact(uint16_t applied_code,
                                                 uint32_t dac_epoch);
// The caller supplies one native operational microsecond sample after its
// control-health refresh. Raw observation/estimate coordinates remain those
// in observation; active decision ticks/seconds derive from this later sample.
void otis_frequency_regulation_live_on_boundary(
    const OtisPpsCountBoundaryObservation *observation,
    uint32_t interval_count, bool interval_valid, uint32_t uptime_s,
    uint64_t operational_decision_raw_ticks,
    const OtisRegulationStaticCodeState *static_code,
    OtisAdaptiveHybridRegulationLiveOutcome *active_outcome);
void otis_frequency_regulation_live_on_capture_fault(const char *reason,
                                             uint32_t uptime_s,
                                             const OtisRegulationStaticCodeState *static_code);
void otis_frequency_regulation_live_service_transport(void);
bool otis_frequency_regulation_live_transport_busy(void);
bool otis_frequency_regulation_live_transport_pending(void);
void otis_frequency_regulation_live_emit_status(OtisStatusEmitContext *context);
void otis_frequency_regulation_live_get_authority_state(
    OtisFrequencyRegulationAuthorityState *state);
bool otis_frequency_regulation_live_extend_monotonic_us(
    uint64_t raw_ticks, uint64_t *extended_ticks);
bool otis_frequency_regulation_live_project_setup_monotonic_us(
    uint64_t raw_ticks, uint32_t capture_session, uint64_t *extended_ticks);

#endif
