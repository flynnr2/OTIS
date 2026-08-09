#ifndef OTIS_CX317_I_ONLY_ENGINE_H
#define OTIS_CX317_I_ONLY_ENGINE_H

#include <stdint.h>

#include "otis_cx318_stage5_tight_deadband.h"

enum class OtisCx317PreviewState : uint8_t {
  WarmupInhibit,
  Qualifying,
  SettlingInhibit,
  Tracking,
  OutOfModelHold,
  Fault,
  Aborted,
};

struct OtisCx317PreviewInput {
  uint32_t timestamp_s;
  double frequency_error_hz;
  uint16_t current_code;
  double temperature_c;
  bool frequency_available;
  bool reference_valid;
  bool estimator_valid;
  bool count_valid;
  bool model_applicable;
  bool applied_code_matches;
  bool i2c_ok;
  bool temperature_available;
  bool recovery_requested;
  bool dac_epoch;
  bool operator_abort;
  int64_t accumulated_edge_error_counts = 0;
  uint64_t capture_session = 0u;
  uint64_t dac_epoch_identity = 0u;
  bool accumulated_edge_error_counts_available = false;
};

struct OtisCx317PreviewDecision {
  OtisCx317PreviewState state;
  OtisCx317PreviewState previous_state;
  const char *reason;
  uint32_t timestamp_s;
  uint16_t current_code;
  double frequency_error_hz;
  double integrator_codes;
  double raw_delta_codes;
  int32_t limited_delta_codes;
  uint16_t proposed_code;
  bool frequency_available;
  bool preview_available;
  bool step_limited;
  bool range_clamped;
  bool state_transition;
  bool preview_only;
  bool control_ready;
  bool actuation_enabled;
  bool actuation_authorized;
  bool actionable;
  int32_t active_update_codes;
  bool tight_deadband_decision_available;
  OtisCx318Stage5TightDeadbandDecision tight_deadband;
};

struct OtisCx317IOnlyEngine {
  OtisCx317PreviewState state;
  double integrator_codes;
  uint32_t startup_s;
  uint32_t inhibit_until_s;
  uint32_t last_decision_s;
  bool have_last_decision;
  const char *reason;
  OtisCx318Stage5TightDeadband tight_deadband;
  OtisCx318Stage5TightDeadbandDecision tight_deadband_decision;
  bool tight_deadband_decision_available;
};

void otis_cx317_i_only_engine_init(OtisCx317IOnlyEngine *engine,
                                   uint32_t startup_s);
void otis_cx317_i_only_engine_note_dac_epoch(OtisCx317IOnlyEngine *engine,
                                             uint32_t timestamp_s);
void otis_cx317_i_only_engine_evaluate(
    OtisCx317IOnlyEngine *engine, const OtisCx317PreviewInput *input,
    OtisCx317PreviewDecision *decision);
const char *otis_cx317_preview_state_name(OtisCx317PreviewState state);

#endif
