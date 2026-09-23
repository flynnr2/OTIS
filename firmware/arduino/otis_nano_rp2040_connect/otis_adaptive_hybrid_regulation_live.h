#ifndef OTIS_ADAPTIVE_HYBRID_REGULATION_LIVE_H
#define OTIS_ADAPTIVE_HYBRID_REGULATION_LIVE_H

#include <stdint.h>

#include "otis_firmware_host_contract.generated.h"
#include "otis_regulation_transaction.h"
#include "otis_instrument.h"
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
  const char *reference_acceptance_policy_sha256;
  const char *reference_acceptance_state;
  // Latest same-core accepted-reference identity.  This is distinct from the
  // capture session and from the raw SNP/reference ordinals.
  uint32_t acceptance_epoch;
  uint32_t accepted_boundary_ordinal;
  bool accepted_anchor_current;
  // Metadata qualification must advance before a causally later accepted
  // boundary can rearm control.
  uint32_t gnss_metadata_sequence;
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
  uint32_t source_acceptance_epoch;
  uint32_t source_opening_accepted_boundary_ordinal;
  uint32_t source_closing_accepted_boundary_ordinal;
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
  bool faulted;
  const char *reason;
};

typedef void (*OtisRegulationStatusVisitor)(void *, const char *, const char *, const char *, uint32_t);

bool otis_adaptive_hybrid_regulation_live_begin(uint64_t session, uint32_t capture_session, uint64_t ticks);
void otis_adaptive_hybrid_regulation_live_emit_headers(void);
void otis_adaptive_hybrid_regulation_live_visit_status(void *, OtisRegulationStatusVisitor, uint32_t now_s);
void otis_adaptive_hybrid_regulation_live_update_health_at_ticks(const OtisAdaptiveHybridRegulationLiveHealth *, uint32_t, uint64_t ticks);
void otis_adaptive_hybrid_regulation_live_service(uint64_t ticks);
OtisInstrumentReceipt otis_adaptive_hybrid_regulation_live_command(const OtisInstrumentCommand &, uint64_t ticks);
bool otis_adaptive_hybrid_regulation_live_application(const OtisInstrumentApplication &);
bool otis_adaptive_hybrid_regulation_live_confirm_consumers(uint16_t code, uint32_t epoch, uint64_t application_ticks);
void otis_adaptive_hybrid_regulation_live_on_decision_at_ticks(const OtisAdaptiveHybridRegulationLiveDecision *, uint64_t, OtisAdaptiveHybridRegulationLiveOutcome *);
void otis_adaptive_hybrid_regulation_live_set_status_query_nonce(uint32_t nonce);
void otis_adaptive_hybrid_regulation_live_applied_snapshot(const OtisAppliedDacStateMessage &);
#endif
