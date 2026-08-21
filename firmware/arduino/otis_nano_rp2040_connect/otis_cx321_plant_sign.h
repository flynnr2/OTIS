#ifndef OTIS_CX321_PLANT_SIGN_H
#define OTIS_CX321_PLANT_SIGN_H

#include <stdint.h>

#include "otis_active_hybrid_policy_engine.h"

constexpr uint16_t OTIS_CX321_PLANT_SIGN_SPAN_INTERVALS = 1500u;
constexpr uint64_t OTIS_CX321_NOMINAL_COUNT_PER_INTERVAL = 10000000ull;
constexpr uint64_t OTIS_CX321_TIMER0_TICKS_PER_SECOND = 16000000ull;
constexpr uint64_t OTIS_CX321_SETTLING_EXCLUSION_TICKS =
    900ull * OTIS_CX321_TIMER0_TICKS_PER_SECOND;

struct OtisCx321PlantSignEstimate {
  uint64_t total_count;
  int64_t signed_error_counts;
  uint64_t open_ticks;
  uint64_t close_ticks;
  uint32_t first_sequence;
  uint32_t last_sequence;
  uint32_t capture_session;
  uint32_t dac_epoch;
  uint16_t accepted_intervals;
  bool valid;
};

struct OtisCx321PlantSignAccumulator {
  uint64_t application_ticks;
  uint64_t total_count;
  uint64_t open_ticks;
  uint64_t close_ticks;
  uint32_t dac_epoch;
  uint32_t capture_session;
  uint32_t first_sequence;
  uint32_t last_sequence;
  uint16_t accepted_intervals;
  bool configured;
};

void otis_cx321_plant_sign_accumulator_init(
    OtisCx321PlantSignAccumulator *accumulator, uint64_t application_ticks,
    uint32_t dac_epoch, uint32_t capture_session);
void otis_cx321_plant_sign_accumulator_invalidate(
    OtisCx321PlantSignAccumulator *accumulator);
bool otis_cx321_plant_sign_accumulator_on_interval(
    OtisCx321PlantSignAccumulator *accumulator, uint64_t open_ticks,
    uint64_t close_ticks, uint32_t closing_sequence, uint32_t interval_count,
    uint32_t dac_epoch, uint32_t capture_session, bool interval_valid,
    OtisCx321PlantSignEstimate *estimate);

enum class OtisCx321PlantSignState : uint8_t {
  FrequencyAcquire,
  PlantSignQualify,
  ResponseAckPending,
  PhaseQualify,
  NotExercised,
  FailStatic,
};

struct OtisCx321PlantSignDecision {
  uint32_t decision_sequence;
  int64_t pre_error_counts;
  int32_t requested_delta_codes;
  uint16_t current_code;
  uint16_t requested_code;
  uint32_t source_first_sequence;
  uint32_t source_last_sequence;
  uint32_t dac_epoch;
  bool request_ready;
};

struct OtisCx321PlantSignResponse {
  uint32_t request_sequence;
  uint32_t application_sequence;
  uint32_t dac_epoch;
  uint32_t source_last_sequence;
  uint64_t response_close_ticks;
  int64_t pre_total_count;
  int64_t post_total_count;
  int64_t response_counts;
  bool sign_pass;
  bool magnitude_pass;
  bool exact_evidence_pass;
  bool tight_reentry_pass;
  bool passed;
};

struct OtisCx321PlantSignEngine {
  OtisCx321PlantSignState state;
  const char *reason;
  OtisCx321PlantSignEstimate pre_windows[2];
  uint8_t pre_window_count;
  uint32_t decision_sequence;
  OtisCx321PlantSignDecision pending_decision;
  OtisCx321PlantSignResponse pending_response;
  uint16_t applied_code;
  uint32_t applied_dac_epoch;
  uint32_t capture_session;
  uint64_t application_ticks;
  uint32_t request_sequence;
  uint32_t application_sequence;
  uint64_t response_acknowledgement_ticks;
  bool attested;
};

void otis_cx321_plant_sign_engine_init(OtisCx321PlantSignEngine *engine);
bool otis_cx321_plant_sign_engine_on_pre_estimate(
    OtisCx321PlantSignEngine *engine,
    const OtisCx321PlantSignEstimate *estimate, uint16_t current_code,
    uint32_t current_dac_epoch, uint16_t global_correction_count,
    bool natural_tight_inside, bool common_evidence_exact,
    OtisCx321PlantSignDecision *decision);
bool otis_cx321_plant_sign_engine_note_application(
    OtisCx321PlantSignEngine *engine, uint32_t request_sequence,
    uint32_t application_sequence, uint16_t applied_code,
    uint32_t applied_dac_epoch, uint64_t application_ticks,
    bool application_identity_exact);
bool otis_cx321_plant_sign_engine_on_response(
    OtisCx321PlantSignEngine *engine,
    const OtisCx321PlantSignEstimate *post_estimate,
    bool common_evidence_exact, bool tight_reentry,
    OtisCx321PlantSignResponse *response);
bool otis_cx321_plant_sign_engine_acknowledge_response(
    OtisCx321PlantSignEngine *engine, uint32_t request_sequence,
    uint32_t application_sequence, uint32_t dac_epoch,
    uint32_t response_source_last_sequence, int64_t response_counts,
    uint64_t response_acknowledgement_ticks, bool host_replay_exact);
bool otis_cx321_plant_sign_engine_rebase_natural_controller(
    const OtisCx321PlantSignEngine *plant_sign,
    OtisActiveHybridEngine *natural_controller);
const char *otis_cx321_plant_sign_state_name(OtisCx321PlantSignState state);

#endif
