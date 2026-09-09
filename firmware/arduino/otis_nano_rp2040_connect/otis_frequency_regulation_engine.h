#ifndef OTIS_FREQUENCY_REGULATION_ENGINE_H
#define OTIS_FREQUENCY_REGULATION_ENGINE_H

#include <stdint.h>

#include "otis_integer_count_tight_deadband.h"

enum class OtisFrequencyRegulationState : uint8_t {
  WarmupInhibit,
  SetupInhibit,
  Qualifying,
  SettlingInhibit,
  Tracking,
  OutOfModelHold,
  Fault,
  Aborted,
};

struct OtisFrequencyRegulationInput {
  uint32_t timestamp_s;
  double frequency_error_hz;
  uint16_t current_code;
  double temperature_c;
  bool frequency_available;
  bool reference_valid;
  bool estimator_valid;
  bool count_valid;
  bool actuator_context_established;
  bool applied_code_available;
  bool model_applicable;
  bool applied_code_matches;
  bool i2c_ok;
  bool temperature_available;
  bool dac_epoch;
  bool operator_abort;
  int64_t accumulated_edge_error_counts = 0;
  uint64_t capture_session = 0u;
  uint64_t dac_epoch_identity = 0u;
  bool accumulated_edge_error_counts_available = false;
};

struct OtisFrequencyRegulationDecision {
  OtisFrequencyRegulationState state;
  OtisFrequencyRegulationState previous_state;
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
  OtisIntegerCountDeadbandTightDeadbandDecision tight_deadband;
};

struct OtisFrequencyRegulationEngine {
  OtisFrequencyRegulationState state;
  double integrator_codes;
  uint32_t startup_s;
  uint32_t inhibit_until_s;
  uint32_t last_decision_s;
  bool have_last_decision;
  const char *reason;
  OtisIntegerCountDeadbandTightDeadband tight_deadband;
  OtisIntegerCountDeadbandTightDeadbandDecision tight_deadband_decision;
  bool tight_deadband_decision_available;
};

void otis_frequency_regulation_engine_init(OtisFrequencyRegulationEngine *engine,
                                   uint32_t startup_s);
void otis_frequency_regulation_engine_note_dac_epoch(OtisFrequencyRegulationEngine *engine,
                                             uint32_t timestamp_s);
void otis_frequency_regulation_engine_evaluate(
    OtisFrequencyRegulationEngine *engine, const OtisFrequencyRegulationInput *input,
    OtisFrequencyRegulationDecision *decision);
const char *otis_regulation_preview_state_name(OtisFrequencyRegulationState state);

#endif
