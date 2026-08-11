#ifndef OTIS_OBSERVE_ONLY_DISCIPLINE_ENGINE_H
#define OTIS_OBSERVE_ONLY_DISCIPLINE_ENGINE_H

#include <stdint.h>

// Pure observe-only discipline engine.  This header deliberately has no
// Arduino, transport, command, Wire, or DAC-driver dependency.

enum OtisObserveOnlyDisciplineValidity : uint8_t {
  OTIS_OBSERVE_ONLY_DISCIPLINE_UNAVAILABLE = 0,
  OTIS_OBSERVE_ONLY_DISCIPLINE_VALID = 1,
  OTIS_OBSERVE_ONLY_DISCIPLINE_INVALID = 2,
  OTIS_OBSERVE_ONLY_DISCIPLINE_STALE = 3,
};

enum OtisObserveOnlyDisciplineDiagnosticHealth : uint8_t {
  OTIS_OBSERVE_ONLY_DISCIPLINE_DIAGNOSTIC_UNKNOWN = 0,
  OTIS_OBSERVE_ONLY_DISCIPLINE_DIAGNOSTIC_HEALTHY = 1,
  OTIS_OBSERVE_ONLY_DISCIPLINE_DIAGNOSTIC_DEGRADED = 2,
  OTIS_OBSERVE_ONLY_DISCIPLINE_DIAGNOSTIC_FAULT = 3,
};

enum OtisObserveOnlyDisciplineState : uint8_t {
  OTIS_OBSERVE_ONLY_DISCIPLINE_BOOT = 0,
  OTIS_OBSERVE_ONLY_DISCIPLINE_WARMUP_INHIBIT,
  OTIS_OBSERVE_ONLY_DISCIPLINE_QUALIFYING,
  OTIS_OBSERVE_ONLY_DISCIPLINE_ACQUIRE_PREVIEW,
  OTIS_OBSERVE_ONLY_DISCIPLINE_SETTLE_PREVIEW,
  OTIS_OBSERVE_ONLY_DISCIPLINE_LOCKED_PREVIEW,
  OTIS_OBSERVE_ONLY_DISCIPLINE_HOLDOVER_PREVIEW,
  OTIS_OBSERVE_ONLY_DISCIPLINE_RECOVER_PREVIEW,
  OTIS_OBSERVE_ONLY_DISCIPLINE_FAULT,
};

enum OtisObserveOnlyDisciplineConfidence : uint8_t {
  OTIS_OBSERVE_ONLY_DISCIPLINE_CONFIDENCE_UNAVAILABLE = 0,
  OTIS_OBSERVE_ONLY_DISCIPLINE_CONFIDENCE_LOW,
  OTIS_OBSERVE_ONLY_DISCIPLINE_CONFIDENCE_MEDIUM,
  OTIS_OBSERVE_ONLY_DISCIPLINE_CONFIDENCE_HIGH,
};

enum OtisObserveOnlyDisciplineTransitionReason : uint8_t {
  OTIS_OBSERVE_ONLY_DISCIPLINE_TRANSITION_STARTUP_INHIBIT = 0,
  OTIS_OBSERVE_ONLY_DISCIPLINE_TRANSITION_QUALIFYING,
  OTIS_OBSERVE_ONLY_DISCIPLINE_TRANSITION_STARTUP_QUALIFIED,
  OTIS_OBSERVE_ONLY_DISCIPLINE_TRANSITION_POST_QUALIFICATION_FAULT,
  OTIS_OBSERVE_ONLY_DISCIPLINE_TRANSITION_FAULT_LATCHED,
  OTIS_OBSERVE_ONLY_DISCIPLINE_TRANSITION_REFERENCE_HOLDOVER,
  OTIS_OBSERVE_ONLY_DISCIPLINE_TRANSITION_REFERENCE_RETURN,
  OTIS_OBSERVE_ONLY_DISCIPLINE_TRANSITION_RECOVERY_QUALIFYING,
  OTIS_OBSERVE_ONLY_DISCIPLINE_TRANSITION_RECOVERY_INTERRUPTED,
  OTIS_OBSERVE_ONLY_DISCIPLINE_TRANSITION_RECOVERY_QUALIFIED,
};

enum OtisObserveOnlyDisciplineReason : uint32_t {
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_NONE = 0u,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_REFERENCE_UNAVAILABLE = 1u << 0,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_REFERENCE_STALE = 1u << 1,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_REFERENCE_OUTLIER = 1u << 2,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_REFERENCE_FLAGGED = 1u << 3,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_COUNT_UNAVAILABLE = 1u << 4,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_COUNT_STALE = 1u << 5,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_COUNT_ZERO = 1u << 6,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_COUNT_SATURATED = 1u << 7,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_COUNT_DISCONTINUITY = 1u << 8,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_COUNT_FLAGGED = 1u << 9,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_DIAGNOSTIC_NOT_HEALTHY = 1u << 10,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_ESTIMATOR_UNDERQUALIFIED = 1u << 11,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_ESTIMATOR_DISPERSION = 1u << 12,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_STARTUP_INHIBIT = 1u << 13,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_CLEAN_WINDOW_INCOMPLETE = 1u << 14,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_REFERENCE_HOLDOVER = 1u << 15,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_POST_QUALIFICATION_FAULT = 1u << 16,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_MODEL_UNAVAILABLE = 1u << 17,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_MODEL_INVALID = 1u << 18,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_MODEL_VERSION = 1u << 19,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_MODEL_TOPOLOGY = 1u << 20,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_MODEL_BACKEND = 1u << 21,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_MODEL_INPUT_RANGE = 1u << 22,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_MODEL_EXCLUDED_INPUT = 1u << 23,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_MODEL_GAIN = 1u << 24,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_DAC_UNAVAILABLE = 1u << 25,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_REFERENCE_CONTINUITY_UNAVAILABLE = 1u << 26,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_MODEL_ESTIMATOR_METHOD = 1u << 27,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_BOUNDARY_SUPPORT = 1u << 28,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_REFERENCE_SEQUENCE = 1u << 29,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_SUPPORT_OVERWRITTEN = 1u << 30,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REASON_PENDING_COUNT_OVERWRITTEN = 1u << 31,
};

struct OtisObserveOnlyDisciplineEngineConfig {
  double startup_inhibit_s;
  uint8_t clean_window_requirement;
  uint8_t recovery_clean_window_requirement;
  uint8_t estimator_window;
  uint8_t minimum_estimator_samples;
  double maximum_dispersion_hz;
  double nominal_frequency_hz;
};

enum OtisObserveOnlyDisciplineModelApplicabilityDetail : uint8_t {
  OTIS_OBSERVE_ONLY_DISCIPLINE_MODEL_DETAIL_NONE = 0u,
  OTIS_OBSERVE_ONLY_DISCIPLINE_MODEL_DETAIL_DAC_RANGE = 1u << 0,
  OTIS_OBSERVE_ONLY_DISCIPLINE_MODEL_DETAIL_DAC_SETTLING_UNVERIFIED = 1u << 1,
  OTIS_OBSERVE_ONLY_DISCIPLINE_MODEL_DETAIL_DAC_SETTLING_ACTIVE = 1u << 2,
  OTIS_OBSERVE_ONLY_DISCIPLINE_MODEL_DETAIL_TEMPERATURE_UNAVAILABLE = 1u << 3,
  OTIS_OBSERVE_ONLY_DISCIPLINE_MODEL_DETAIL_TEMPERATURE_STALE = 1u << 4,
  OTIS_OBSERVE_ONLY_DISCIPLINE_MODEL_DETAIL_TEMPERATURE_RANGE = 1u << 5,
};

struct OtisObserveOnlyDisciplineModelInput {
  bool available;
  bool valid;
  bool version_4;
  bool topology_match;
  bool backend_match;
  bool estimator_method_match;
  bool input_in_applicability;
  uint8_t applicability_detail_mask;
  bool excluded_input;
  bool gain_available;
  double hz_per_code;
  bool dac_available;
  uint16_t current_dac_code;
  uint16_t candidate_min_code;
  uint16_t candidate_max_code;
  uint16_t maximum_preview_step_codes;
};

struct OtisObserveOnlyDisciplineObservation {
  uint64_t timestamp_ticks;
  double elapsed_s;
  bool new_count;
  OtisObserveOnlyDisciplineValidity reference_validity;
  OtisObserveOnlyDisciplineValidity count_validity;
  bool reference_continuity;
  bool reference_authority_qualified;
  bool count_continuity;
  OtisObserveOnlyDisciplineDiagnosticHealth diagnostic_health;
  uint32_t observation_reason_mask;
  bool frequency_observation_available;
  double frequency_observation_hz;
  OtisObserveOnlyDisciplineModelInput model;
};

struct OtisObserveOnlyDisciplineDecision {
  OtisObserveOnlyDisciplineState previous_state;
  OtisObserveOnlyDisciplineState state;
  OtisObserveOnlyDisciplineTransitionReason transition_reason;
  bool state_transition;
  uint8_t accepted_sample_count;
  OtisObserveOnlyDisciplineConfidence confidence;
  bool estimate_available;
  double frequency_estimate_hz;
  double frequency_error_hz;
  double dispersion_hz;
  bool estimator_eligible;
  uint32_t eligibility_reason_mask;
  bool model_applicable;
  uint32_t model_reason_mask;
  bool preview_eligible;
  bool preview_available;
  double raw_delta_codes;
  int32_t limited_delta_codes;
  uint16_t proposed_dac_code;
  bool step_limited;
  bool range_clamped;
  // These are structural invariants, not configurable permissions.
  bool preview_only;
  bool actuation_authorized;
  bool actionable;
};

struct OtisObserveOnlyDisciplineEngine {
  OtisObserveOnlyDisciplineEngineConfig config;
  OtisObserveOnlyDisciplineState state;
  bool fault_latched;
  uint8_t clean_windows;
  uint8_t recovery_windows;
  double samples[8];
  uint8_t sample_count;
  uint8_t sample_next;
};

void otis_observe_only_discipline_engine_init(OtisObserveOnlyDisciplineEngine *engine,
                             const OtisObserveOnlyDisciplineEngineConfig *config);
void otis_observe_only_discipline_engine_evaluate(OtisObserveOnlyDisciplineEngine *engine,
                                 const OtisObserveOnlyDisciplineObservation *observation,
                                 OtisObserveOnlyDisciplineDecision *decision);
const char *otis_observe_only_discipline_state_name(OtisObserveOnlyDisciplineState state);
const char *otis_observe_only_discipline_confidence_name(OtisObserveOnlyDisciplineConfidence confidence);
const char *otis_observe_only_discipline_transition_reason_name(
    OtisObserveOnlyDisciplineTransitionReason reason);

#endif
