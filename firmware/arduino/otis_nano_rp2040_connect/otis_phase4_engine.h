#ifndef OTIS_PHASE4_ENGINE_H
#define OTIS_PHASE4_ENGINE_H

#include <stdint.h>

// Pure observe-only discipline engine.  This header deliberately has no
// Arduino, transport, command, Wire, or DAC-driver dependency.

enum OtisPhase4Validity : uint8_t {
  OTIS_PHASE4_UNAVAILABLE = 0,
  OTIS_PHASE4_VALID = 1,
  OTIS_PHASE4_INVALID = 2,
  OTIS_PHASE4_STALE = 3,
};

enum OtisPhase4DiagnosticHealth : uint8_t {
  OTIS_PHASE4_DIAGNOSTIC_UNKNOWN = 0,
  OTIS_PHASE4_DIAGNOSTIC_HEALTHY = 1,
  OTIS_PHASE4_DIAGNOSTIC_DEGRADED = 2,
  OTIS_PHASE4_DIAGNOSTIC_FAULT = 3,
};

enum OtisPhase4State : uint8_t {
  OTIS_PHASE4_BOOT = 0,
  OTIS_PHASE4_WARMUP_INHIBIT,
  OTIS_PHASE4_QUALIFYING,
  OTIS_PHASE4_ACQUIRE_PREVIEW,
  OTIS_PHASE4_SETTLE_PREVIEW,
  OTIS_PHASE4_LOCKED_PREVIEW,
  OTIS_PHASE4_HOLDOVER_PREVIEW,
  OTIS_PHASE4_RECOVER_PREVIEW,
  OTIS_PHASE4_FAULT,
};

enum OtisPhase4Confidence : uint8_t {
  OTIS_PHASE4_CONFIDENCE_UNAVAILABLE = 0,
  OTIS_PHASE4_CONFIDENCE_LOW,
  OTIS_PHASE4_CONFIDENCE_MEDIUM,
  OTIS_PHASE4_CONFIDENCE_HIGH,
};

enum OtisPhase4TransitionReason : uint8_t {
  OTIS_PHASE4_TRANSITION_STARTUP_INHIBIT = 0,
  OTIS_PHASE4_TRANSITION_QUALIFYING,
  OTIS_PHASE4_TRANSITION_STARTUP_QUALIFIED,
  OTIS_PHASE4_TRANSITION_POST_QUALIFICATION_FAULT,
  OTIS_PHASE4_TRANSITION_FAULT_LATCHED,
  OTIS_PHASE4_TRANSITION_REFERENCE_HOLDOVER,
  OTIS_PHASE4_TRANSITION_REFERENCE_RETURN,
  OTIS_PHASE4_TRANSITION_RECOVERY_QUALIFYING,
  OTIS_PHASE4_TRANSITION_RECOVERY_INTERRUPTED,
  OTIS_PHASE4_TRANSITION_RECOVERY_QUALIFIED,
};

enum OtisPhase4Reason : uint32_t {
  OTIS_PHASE4_REASON_NONE = 0u,
  OTIS_PHASE4_REASON_REFERENCE_UNAVAILABLE = 1u << 0,
  OTIS_PHASE4_REASON_REFERENCE_STALE = 1u << 1,
  OTIS_PHASE4_REASON_REFERENCE_OUTLIER = 1u << 2,
  OTIS_PHASE4_REASON_REFERENCE_FLAGGED = 1u << 3,
  OTIS_PHASE4_REASON_COUNT_UNAVAILABLE = 1u << 4,
  OTIS_PHASE4_REASON_COUNT_STALE = 1u << 5,
  OTIS_PHASE4_REASON_COUNT_ZERO = 1u << 6,
  OTIS_PHASE4_REASON_COUNT_SATURATED = 1u << 7,
  OTIS_PHASE4_REASON_COUNT_DISCONTINUITY = 1u << 8,
  OTIS_PHASE4_REASON_COUNT_FLAGGED = 1u << 9,
  OTIS_PHASE4_REASON_DIAGNOSTIC_NOT_HEALTHY = 1u << 10,
  OTIS_PHASE4_REASON_ESTIMATOR_UNDERQUALIFIED = 1u << 11,
  OTIS_PHASE4_REASON_ESTIMATOR_DISPERSION = 1u << 12,
  OTIS_PHASE4_REASON_STARTUP_INHIBIT = 1u << 13,
  OTIS_PHASE4_REASON_CLEAN_WINDOW_INCOMPLETE = 1u << 14,
  OTIS_PHASE4_REASON_REFERENCE_HOLDOVER = 1u << 15,
  OTIS_PHASE4_REASON_POST_QUALIFICATION_FAULT = 1u << 16,
  OTIS_PHASE4_REASON_MODEL_UNAVAILABLE = 1u << 17,
  OTIS_PHASE4_REASON_MODEL_INVALID = 1u << 18,
  OTIS_PHASE4_REASON_MODEL_VERSION = 1u << 19,
  OTIS_PHASE4_REASON_MODEL_TOPOLOGY = 1u << 20,
  OTIS_PHASE4_REASON_MODEL_BACKEND = 1u << 21,
  OTIS_PHASE4_REASON_MODEL_INPUT_RANGE = 1u << 22,
  OTIS_PHASE4_REASON_MODEL_EXCLUDED_INPUT = 1u << 23,
  OTIS_PHASE4_REASON_MODEL_GAIN = 1u << 24,
  OTIS_PHASE4_REASON_DAC_UNAVAILABLE = 1u << 25,
  OTIS_PHASE4_REASON_REFERENCE_CONTINUITY_UNAVAILABLE = 1u << 26,
};

struct OtisPhase4EngineConfig {
  double startup_inhibit_s;
  uint8_t clean_window_requirement;
  uint8_t recovery_clean_window_requirement;
  uint8_t estimator_window;
  uint8_t minimum_estimator_samples;
  double maximum_dispersion_hz;
  double nominal_frequency_hz;
};

struct OtisPhase4ModelInput {
  bool available;
  bool valid;
  bool version_3;
  bool topology_match;
  bool backend_match;
  bool input_in_applicability;
  bool excluded_input;
  bool gain_available;
  double hz_per_code;
  bool dac_available;
  uint16_t current_dac_code;
  uint16_t candidate_min_code;
  uint16_t candidate_max_code;
  uint16_t maximum_preview_step_codes;
};

struct OtisPhase4Observation {
  uint64_t timestamp_ticks;
  double elapsed_s;
  bool new_count;
  OtisPhase4Validity reference_validity;
  OtisPhase4Validity count_validity;
  bool reference_continuity;
  bool count_continuity;
  OtisPhase4DiagnosticHealth diagnostic_health;
  uint32_t observation_reason_mask;
  bool frequency_observation_available;
  double frequency_observation_hz;
  OtisPhase4ModelInput model;
};

struct OtisPhase4Decision {
  OtisPhase4State previous_state;
  OtisPhase4State state;
  OtisPhase4TransitionReason transition_reason;
  bool state_transition;
  uint8_t accepted_sample_count;
  OtisPhase4Confidence confidence;
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

struct OtisPhase4Engine {
  OtisPhase4EngineConfig config;
  OtisPhase4State state;
  bool fault_latched;
  uint8_t clean_windows;
  uint8_t recovery_windows;
  double samples[8];
  uint8_t sample_count;
  uint8_t sample_next;
};

void otis_phase4_engine_init(OtisPhase4Engine *engine,
                             const OtisPhase4EngineConfig *config);
void otis_phase4_engine_evaluate(OtisPhase4Engine *engine,
                                 const OtisPhase4Observation *observation,
                                 OtisPhase4Decision *decision);
const char *otis_phase4_state_name(OtisPhase4State state);
const char *otis_phase4_confidence_name(OtisPhase4Confidence confidence);
const char *otis_phase4_transition_reason_name(
    OtisPhase4TransitionReason reason);

#endif
