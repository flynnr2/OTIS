#ifndef OTIS_ADAPTIVE_HYBRID_REGULATION_LIVE_H
#define OTIS_ADAPTIVE_HYBRID_REGULATION_LIVE_H

#include <stdint.h>

#include "otis_firmware_host_contract.generated.h"
#include "otis_regulation_transaction.h"
#include "otis_dual_core_contract.h"
#include "otis_status_emit.h"

#define OTIS_ADAPTIVE_HYBRID_ACTIVE_STATUS_SNAPSHOT_CONTRACT \
  OTIS_ACTIVE_STATUS_CONTRACT_ID

constexpr char OTIS_ADAPTIVE_HYBRID_STATUS_COMPONENT[] =
    OTIS_ACTIVE_STATUS_COMPONENT;
static_assert(
    sizeof(OTIS_ADAPTIVE_HYBRID_STATUS_COMPONENT) <=
        sizeof(((OtisTelemetryMessage *)nullptr)->component),
    "active status component must survive the cross-core telemetry record");

struct OtisAdaptiveHybridRegulationLiveHealth {
  uint32_t session_id;
  // Monotonic producer identities.  Metadata qualification must advance
  // first; a causally later exact D14/D8 observation must then advance before
  // control can be rearmed.
  uint32_t gnss_metadata_sequence;
  uint32_t d14_d8_observation_sequence;
  bool gnss_metadata_valid;
  bool gnss_identity_stable;
  bool gnss_3d_evidence;
  bool raw_pps_valid;
  bool reference_integrity_valid;
  bool count_valid;
  bool estimator_valid;
  bool model_applicable;
  bool temperature_valid;
  bool applied_code_confirmed;
  uint16_t applied_code;
  bool abort_path_live;
  uint16_t selected_interval_count;
};

struct OtisAdaptiveHybridRegulationLiveDecision {
  uint32_t decision_sequence;
  uint32_t source_first_sequence;
  uint32_t source_last_sequence;
  uint32_t timestamp_s;
  uint16_t current_applied_code;
  int32_t requested_delta_codes;
  uint16_t requested_code;
  double frequency_error_hz;
  bool measurement_valid;
  bool model_applicable;
  bool control_eligible;
  bool preview_available;
  uint32_t capture_session;
  int32_t accumulated_edge_error_counts;
  const char *tight_state;
  uint32_t dac_epoch;
  uint32_t phase_epoch;
  uint32_t phase_observation_sequence;
  int64_t relative_phase_cycles;
  uint32_t phase_dac_epoch;
  uint16_t phase_applied_code;
  bool phase_continuous;
  bool phase_current;
  bool phase_step_detected;
  bool phase_recorder_published;
};

struct OtisAdaptiveHybridRegulationLiveOutcome {
  bool request_created;
  bool application_attempted;
  bool applied;
  bool response_recorded;
  bool faulted;
  uint16_t requested_code;
  uint16_t applied_code;
  uint32_t request_sequence;
  uint32_t dac_epoch;
  uint64_t application_timestamp_ticks;
  uint32_t capture_session;
  OtisRegulationResponseClass response_class;
  const char *reason;
};

struct OtisAdaptiveHybridRegulationLiveStatus {
  const char *run_identity;
  const char *build_identity;
  const char *image_identity;
  const char *estimator_sha256;
  const char *model_sha256;
  const char *active_policy_sha256;
  const char *response_policy_sha256;
  const char *numerical_policy_sha256;
  const char *natural_frequency_estimator_sha256;
  const char *state;
  const char *reason;
  const char *evidence_state;
  uint32_t session_id;
  uint32_t evidence_request_sequence;
  uint32_t query_nonce;
  uint32_t uptime_s;
  uint16_t expected_setup_code;
  uint16_t applied_code;
  uint16_t correction_count;
  uint16_t cumulative_movement_codes;
  uint32_t dac_epoch;
  uint16_t selected_interval_count;
  bool transaction_bound;
  bool evidence_pending;
  bool confirmed_applied_code_known;
  bool capture_lease_live;
  bool manual_start_confirmed;
  bool arm_eligible;
  bool fail_static;
  bool setup_gnss_eligible;
  bool setup_reference_eligible;
  bool setup_partition_healthy;
  bool gnss_metadata_hold_active;
  bool gnss_metadata_hold_transaction_pending;
  uint32_t gnss_metadata_hold_entry_sequence;
  uint32_t gnss_metadata_requalification_sequence;
  uint32_t gnss_metadata_qualification_frontier;
  uint32_t d14_d8_observation_sequence;
  const char *hybrid_state;
  const char *hybrid_reason;
  uint16_t phase_nonzero_application_count;
  uint16_t phase_material_application_count;
  uint16_t frequency_only_application_count;
  bool first_phase_checkpoint_passed;
};

typedef void (*OtisRegulationStatusVisitor)(
    void *context, const char *key, const char *value, const char *severity,
    uint32_t flags);

bool otis_adaptive_hybrid_regulation_live_begin(void);
void otis_adaptive_hybrid_regulation_live_emit_headers(void);
void otis_adaptive_hybrid_regulation_live_visit_status(
    void *context, OtisRegulationStatusVisitor visitor, uint32_t now_s);
void otis_adaptive_hybrid_regulation_live_update_health(
    const OtisAdaptiveHybridRegulationLiveHealth *health, uint32_t now_s);
void otis_adaptive_hybrid_regulation_live_update_health_at_ticks(
    const OtisAdaptiveHybridRegulationLiveHealth *health, uint32_t now_s,
    uint64_t event_timestamp_ticks);
void otis_adaptive_hybrid_regulation_live_service(uint32_t now_s);
bool otis_adaptive_hybrid_regulation_live_capture_lease(uint32_t lease_sequence,
                                         uint32_t now_s);
bool otis_adaptive_hybrid_regulation_live_arm(uint32_t authorization_sequence,
                               uint32_t nonce, uint32_t expires_s,
                               uint32_t now_s);
void otis_adaptive_hybrid_regulation_live_abort(const char *reason);
bool otis_adaptive_hybrid_regulation_live_acknowledge_evidence(uint32_t request_sequence,
                                                 uint32_t phase_sequence,
                                                 uint32_t now_s);
bool otis_adaptive_hybrid_regulation_live_on_cross_core_ack(
    const OtisCrossCoreActuatorAck *acknowledgement, uint32_t now_s);
bool otis_adaptive_hybrid_regulation_live_manual_start_allowed(uint16_t requested_code);
bool otis_adaptive_hybrid_regulation_live_note_manual_start_exact(
    uint16_t applied_code, uint32_t dac_epoch, bool i2c_ok, uint32_t now_s,
    uint64_t setup_application_ticks, uint32_t capture_session);
bool otis_adaptive_hybrid_regulation_live_confirm_setup_consumers_exact(
    uint16_t applied_code, uint32_t dac_epoch,
    uint64_t setup_application_ticks, uint32_t capture_session);
void otis_adaptive_hybrid_regulation_live_on_decision(
    const OtisAdaptiveHybridRegulationLiveDecision *decision,
    OtisAdaptiveHybridRegulationLiveOutcome *outcome);
void otis_adaptive_hybrid_regulation_live_on_decision_at_ticks(
    const OtisAdaptiveHybridRegulationLiveDecision *decision,
    uint64_t decision_timestamp_ticks, OtisAdaptiveHybridRegulationLiveOutcome *outcome);
bool otis_adaptive_hybrid_regulation_live_take_application_outcome(
    OtisAdaptiveHybridRegulationLiveOutcome *outcome);
bool otis_adaptive_hybrid_regulation_live_complete_application_evidence(
    uint32_t request_sequence, bool estimator_history_reset, uint32_t now_s);
bool otis_adaptive_hybrid_regulation_live_transport_busy(void);
void otis_adaptive_hybrid_regulation_live_service_transport(void);
void otis_adaptive_hybrid_regulation_live_emit_status(OtisStatusEmitContext *context,
                                        uint32_t now_s);
void otis_adaptive_hybrid_regulation_live_get_status(OtisAdaptiveHybridRegulationLiveStatus *status,
                                       uint32_t now_s);
void otis_adaptive_hybrid_regulation_live_set_status_query_nonce(uint32_t query_nonce);
uint32_t otis_adaptive_hybrid_regulation_live_status_snapshot_generation(void);
const char *otis_adaptive_hybrid_regulation_live_run_identity(void);
uint16_t otis_adaptive_hybrid_regulation_live_start_code(void);

#endif
