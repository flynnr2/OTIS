#include "otis_cx317_active_live.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "otis_config.h"
#include "otis_active_timing_sidecar.h"
#include "otis_active_hybrid_decision_format.h"
#include "otis_active_hybrid_policy_engine.h"
#include "otis_cx317_active_actuator.h"
#include "otis_cx323_phase_priority_maintenance.h"
#include "otis_cx323_maintenance_format.h"
#include "otis_cx323_maintenance_record.h"
#include "otis_decimal_format.h"
#include "otis_dependent_response_identity.h"
#include "otis_dual_core_partition.h"
#include "otis_cx317_preview_live.h"
#include "otis_cx321_plant_sign.h"
#include "otis_cx321_plant_sign_format.h"
#include "otis_phase_preview_live.h"
#include "otis_protocol.h"
#include "otis_transport_serial.h"

namespace {

#if OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_REHEARSAL
constexpr char kEstimatorHash[] =
    "54173f493cb7dc459e57e7695d98b518a2616ded914898647f459b2325c94977";
#else
constexpr char kEstimatorHash[] =
    "5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c";
#endif
constexpr char kModelHash[] =
    "86c7acd3e22d206b1806c0ee2723b4f9051442d9624f7339982122c6caeaa0b2";
#if OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_REHEARSAL
constexpr char kNumericalPolicyHash[] =
    "d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf";
constexpr char kActivePolicyHash[] =
    "d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf";
#elif OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
constexpr char kNumericalPolicyHash[] =
    "36e16b0553add14f5f3f1ea0cc9753af113964b039551a86d6b5564a89282e24";
constexpr char kActivePolicyHash[] =
    "36e16b0553add14f5f3f1ea0cc9753af113964b039551a86d6b5564a89282e24";
#elif OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION
constexpr char kNumericalPolicyHash[] =
    "015c133d5898e9c5f21dd3de10612cf8d09ff025c1f9f89345bd8fcc3a0d485c";
constexpr char kActivePolicyHash[] =
    "015c133d5898e9c5f21dd3de10612cf8d09ff025c1f9f89345bd8fcc3a0d485c";
#elif OTIS_ENABLE_CX322_DIRECT_HYBRID
constexpr char kNumericalPolicyHash[] =
    "b131a6a96796d6a8ad854fd707e1b531462ce42b50f91650c1103c16289f1c48";
constexpr char kActivePolicyHash[] =
    "b131a6a96796d6a8ad854fd707e1b531462ce42b50f91650c1103c16289f1c48";
#elif OTIS_ENABLE_CX321_ACTIVE_HYBRID
constexpr char kNumericalPolicyHash[] =
    "4c2642cb16335e724d2df669fa5afc188435d52f8023c388ea0a6fac3f9aba5d";
constexpr char kActivePolicyHash[] =
    "c6a8ea81bd77c791428e79c5c815cf67ca49f9506e5ade57ae9b7553c3113ea4";
#elif OTIS_ENABLE_CX320_ACTIVE_HYBRID
constexpr char kNumericalPolicyHash[] =
    "4c2642cb16335e724d2df669fa5afc188435d52f8023c388ea0a6fac3f9aba5d";
constexpr char kActivePolicyHash[] =
    "4c2642cb16335e724d2df669fa5afc188435d52f8023c388ea0a6fac3f9aba5d";
#elif OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW
constexpr char kNumericalPolicyHash[] =
    "7b90ebab300f910476b47e8cecc42276dd0c4d6e1d342e941a39cb7e931cd3c6";
constexpr char kActivePolicyHash[] =
    "352daed21b3063c7d58dd8b266f3639f3cbed2500ff59fd2c530243727a5bb3a";
#elif OTIS_ENABLE_CX318_STAGE5_PREVIEW
constexpr char kNumericalPolicyHash[] =
    "7b90ebab300f910476b47e8cecc42276dd0c4d6e1d342e941a39cb7e931cd3c6";
constexpr char kActivePolicyHash[] =
    "a0dbe59f1b22fda35c1b760b21a03ab906ef683955368db2eeccba092d0cbbfd";
#else
constexpr char kNumericalPolicyHash[] =
    "7b90ebab300f910476b47e8cecc42276dd0c4d6e1d342e941a39cb7e931cd3c6";
constexpr char kActivePolicyHash[] =
    "9fb037a5f435361928d36a2a6bc7a010b74100588cd83692051d6a093da9f27f";
#endif
constexpr char kResponsePolicyHash[] =
    "e1324c335fcc25d8bd7c97dcec4b77488971bdae19f78ef856204991aa83169e";
constexpr char kPhaseEstimatorHash[] =
    "449c828d2affeff858eb91535e81da0bc9c44840369d741dc1f917a8d662acb4";
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
constexpr char kPlantSignGateHash[] =
    "9bbde84471bcea646e8ceb0b732cfa6dd1d81592fa44071d4aab3bc9ddac8d62";
constexpr char kIdentificationEstimatorHash[] =
    "cf5ea727615ea79a7e23258b674798a3215b0f996ac1a4a454eb39afe0d737b1";
constexpr char kIdentificationEstimatorConfigHash[] =
    "8d0c0be3db287accf7c094f576d6a557cd6c60946a909eb423a7afd8865aefd8";
#endif
constexpr uint32_t kCaptureLeaseMaximumAgeS = 30u;
constexpr uint32_t kEvidenceAcknowledgementMaximumAgeS = 30u;
constexpr uint64_t kCaptureTicksPerSecond = 16000000ull;
constexpr size_t kFrameCapacity = 1536u;
constexpr size_t kTransportChunkLimit = 192u;
constexpr uint64_t kCx323SelectedEstimatorIdentity =
    0x5a53b229cabb5a2cull;

#if OTIS_CX317_ACTIVE_CAMPAIGN == OTIS_CX317_ACTIVE_CAMPAIGN_A
constexpr char kRunIdentity[] = "cx317_bounded_campaign_a:3170001";
constexpr char kExpectedProfile[] = "cx317_bounded_active_campaign_a";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == OTIS_CX317_ACTIVE_CAMPAIGN_B
constexpr char kRunIdentity[] = "cx317_bounded_campaign_b:3170002";
constexpr char kExpectedProfile[] = "cx317_bounded_active_campaign_b";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_A
constexpr char kRunIdentity[] = "cx317_stage7_part_a:3170003";
constexpr char kExpectedProfile[] = "cx317_dual_core_active_part_a";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_B
constexpr char kRunIdentity[] = "cx317_stage7_part_b:3170004";
constexpr char kExpectedProfile[] =
    "cx317_dual_core_active_endurance_part_b";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_REHEARSAL
constexpr char kRunIdentity[] = "cx317_stage7_rehearsal:3170005";
constexpr char kExpectedProfile[] = "cx317_dual_core_active_rehearsal";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_CX318_STAGE5_LOWER
constexpr char kRunIdentity[] = "cx318_stage5_tight_lower:3185001";
constexpr char kExpectedProfile[] = "cx318_stage5_tight_lower";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_CX318_STAGE5_UPPER
constexpr char kRunIdentity[] = "cx318_stage5_tight_upper:3185002";
constexpr char kExpectedProfile[] = "cx318_stage5_tight_upper";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_TIGHT_DEADBAND_LOWER
#if OTIS_ENABLE_Q2_TRANSACTION_REHEARSAL
constexpr char kRunIdentity[] = "cx319_q2_inhibited_transaction:3195200";
constexpr char kExpectedProfile[] = "cx319_q2_inhibited_transaction";
#else
constexpr char kRunIdentity[] = "cx319_tight_lower:3195001";
constexpr char kExpectedProfile[] = "cx319_tight_lower";
#endif
#elif OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_TIGHT_DEADBAND_UPPER
constexpr char kRunIdentity[] = "cx319_tight_upper:3195002";
constexpr char kExpectedProfile[] = "cx319_tight_upper";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_D9_D6_FREQUENCY_ONLY_ENDURANCE
constexpr char kRunIdentity[] = "d9_d6_frequency_only_endurance:1";
constexpr char kExpectedProfile[] = "d9_d6_frequency_only_lower";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_D9_D6_72H_SUSTAINED_HYBRID
constexpr char kRunIdentity[] = "cx322_d9_d6_72h_sustained_engineering:1";
constexpr char kExpectedProfile[] = "cx322_d9_d6_72h_sustained_engineering";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_CX323_D9_D6_72H_ADAPTIVE_HYBRID
constexpr char kRunIdentity[] = "cx323_d9_d6_72h_adaptive_hybrid:1";
constexpr char kExpectedProfile[] = "cx323_d9_d6_72h_adaptive_hybrid";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_LOWER
constexpr char kRunIdentity[] = "cx319_range_part_b_lower:3196001";
constexpr char kExpectedProfile[] = "cx319_range_part_b_lower";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_UPPER
constexpr char kRunIdentity[] = "cx319_range_part_b_upper:3196002";
constexpr char kExpectedProfile[] = "cx319_range_part_b_upper";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_UPPER_COMPLETION
constexpr char kRunIdentity[] = "cx319_range_part_b_upper_completion:3196003";
constexpr char kExpectedProfile[] = "cx319_range_part_b_upper_completion";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_CX320_ACTIVE_HYBRID
constexpr char kRunIdentity[] = "cx320_active_hybrid:3200001";
constexpr char kExpectedProfile[] = "cx320_active_hybrid";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_CX321_ACTIVE_HYBRID
constexpr char kRunIdentity[] = "cx321_active_hybrid:3210001";
constexpr char kExpectedProfile[] = "cx321_active_hybrid";
#elif OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_CX322_DIRECT_HYBRID
#if OTIS_ENABLE_FORWARDED_D9_OUTPUT && \
    OTIS_ENABLE_FORWARDED_D6_MONITOR && \
    !OTIS_ENABLE_D9_D6_READINESS_PROFILE
constexpr char kRunIdentity[] = "cx322_d9_d6_integration_engineering:1";
constexpr char kExpectedProfile[] = "cx322_d9_d6_integration_engineering";
#else
constexpr char kRunIdentity[] = "cx322_direct_hybrid:3220001";
constexpr char kExpectedProfile[] = "cx322_direct_hybrid";
#endif
#elif OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_SUSTAINED_HYBRID_REGULATION
constexpr char kRunIdentity[] = "otis_sustained_hybrid_regulation_v1:1";
constexpr char kExpectedProfile[] = "otis_sustained_hybrid_regulation_v1";
#else
constexpr char kRunIdentity[] = "cx317_bounded_active_disabled";
constexpr char kExpectedProfile[] = "disabled";
#endif

#if defined(ARDUINO)
constexpr char kBuildIdentity[] =
    OTIS_BUILD_SOURCE_SHA256 ":" OTIS_BUILD_CONFIG_SHA256;
#else
constexpr char kBuildIdentity[] = "host_non_firmware";
#endif

struct TransportFrame {
  char data[kFrameCapacity];
  uint16_t length;
  uint16_t sent;
};

enum class EvidencePhase : uint8_t {
  None = 0u,
  Request = 1u,
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  Acceptance = 2u,
  Application = 3u,
  Response = 4u,
#else
  Application = 2u,
  Response = 3u,
#endif
};

OtisCx317ActiveTransaction transaction;
OtisCx317ActiveLiveHealth latest_health = {};
TransportFrame frame = {};
bool initialized = false;
bool transaction_bound = false;
bool have_health = false;
bool have_capture_lease = false;
bool manual_start_confirmed = false;
bool periodic_applied_code_confirmation_seen = false;
EvidencePhase evidence_phase = EvidencePhase::None;
uint32_t last_capture_lease_s = 0u;
uint32_t last_capture_lease_sequence = 0u;
uint32_t evidence_request_sequence = 0u;
uint32_t evidence_pending_since_s = 0u;
uint32_t transaction_record_sequence = 0u;
OtisCx317ActionableRequest pending_actionable_request = {};
bool pending_actionable_request_valid = false;
OtisCx317ActiveLiveOutcome deferred_application_outcome = {};
bool deferred_application_outcome_valid = false;
bool last_application_acknowledged = false;
bool estimator_history_reset = false;
uint32_t status_snapshot_generation = 0u;
uint32_t status_query_nonce = 0u;
bool gnss_metadata_hold_active = false;
bool gnss_metadata_hold_transaction_pending = false;
uint32_t gnss_metadata_hold_entry_sequence = 0u;
uint32_t gnss_metadata_requalification_sequence = 0u;
uint32_t gnss_metadata_qualification_frontier = 0u;
uint32_t gnss_metadata_hold_session = 0u;
uint16_t gnss_metadata_hold_applied_code = 0u;
uint32_t gnss_metadata_hold_dac_epoch = 0u;
#if OTIS_ENABLE_EXACT_LONG_RUN_TIMING_SIDECARS
uint32_t timing_record_sequence = 0u;
bool manual_start_timing_recorded = false;
bool health_event_ticks_available = false;
uint64_t health_event_timestamp_ticks = 0u;
#endif
#if OTIS_ENABLE_ACTIVE_TIMER0_EXTENSION
uint64_t pending_application_timestamp_ticks = 0u;
#endif
#if OTIS_ENABLE_CX320_ACTIVE_HYBRID
OtisActiveHybridEngine hybrid_engine = {};
bool hybrid_engine_ready = false;
OtisActiveHybridDecision pending_hybrid_decision = {};
bool pending_hybrid_decision_valid = false;
OtisCx317ResponseClass pending_hybrid_response_class =
    OtisCx317ResponseClass::MeasurementOrActuatorFault;
bool pending_hybrid_response_valid = false;
bool pending_hybrid_predicted_sign_observed = false;
OtisDependentResponseIdentity dependent_response_identity = {};
uint32_t hybrid_record_sequence = 0u;
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
OtisCx321PlantSignEngine plant_sign_engine = {};
bool plant_sign_engine_ready = false;
bool pending_plant_sign_application = false;
bool dispatching_plant_sign_request = false;
uint32_t plant_sign_record_sequence = 0u;
uint32_t pending_response_psq_record_sequence = 0u;
bool plant_sign_handoff_pending = false;
char plant_sign_attestation_sha256[65] = {};
#endif
#if OTIS_ENABLE_CX32X_EXACT_ACTIVE_TIMING
uint64_t setup_application_timestamp_ticks = 0u;
#endif
#endif
#if OTIS_ENABLE_DUAL_CORE_PARTITION
OtisActuatorTransactionGuard timing_actuator_guard = {};
// Core 1 is the sole active-evidence producer. Reuse one module-owned copy
// buffer instead of reserving a complete evidence frame in each call stack.
OtisEvidenceFrameMessage evidence_frame_scratch = {};
#if OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
// One CX323 logical transition can contain AHY, AH2, ACT, AT2, and AHM. Stage
// these directly behind the partition queue's unpublished tail so no second
// full-frame array consumes the frozen RP2040 RAM reserve.
uint8_t cx323_evidence_burst_count = 0u;
uint8_t cx323_declared_evidence_burst_count = 0u;
bool cx323_collecting_evidence_burst = false;
uint32_t cx323_pending_evidence_burst_sequence = 0u;
#endif
#endif

#if OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
OtisCx323Engine cx323_engine = {};
bool cx323_engine_ready = false;
OtisCx323Decision pending_cx323_decision = {};
bool pending_cx323_decision_valid = false;
OtisCx323Observation pending_cx323_observation = {};
OtisCx323MaintenanceHybridJoin pending_cx323_hybrid_join = {};
bool pending_cx323_origin_valid = false;
OtisCx323Observation last_cx323_observation = {};
OtisCx323Decision last_cx323_decision = {};
OtisCx323MaintenanceHybridJoin last_cx323_hybrid_join = {};
bool last_cx323_origin_valid = false;
uint32_t cx323_maintenance_record_sequence = 0u;
uint32_t cx323_evidence_burst_sequence = 0u;
uint16_t cx323_phase_nonzero_application_count = 0u;
uint16_t cx323_phase_material_application_count = 0u;
uint16_t cx323_frequency_only_application_count = 0u;
#endif

bool capture_lease_live(uint32_t now_s) {
  return have_capture_lease &&
         static_cast<uint32_t>(now_s - last_capture_lease_s) <=
             kCaptureLeaseMaximumAgeS;
}

bool exact_sha256_text(const char *value) {
  if (value == nullptr) return false;
  for (uint8_t index = 0u; index < 64u; ++index) {
    const char c = value[index];
    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
  }
  return value[64] == '\0';
}

#if OTIS_ENABLE_DUAL_CORE_PARTITION
bool publish_evidence_message(const OtisEvidenceFrameMessage *message) {
#if OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
  if (cx323_collecting_evidence_burst) {
    if (message == nullptr || message->length == 0u ||
        message->length >= OTIS_EVIDENCE_FRAME_CAPACITY ||
        cx323_evidence_burst_count >= cx323_declared_evidence_burst_count ||
        !otis_dual_core_append_evidence_burst(message))
      return false;
    ++cx323_evidence_burst_count;
    return true;
  }
#endif
  return otis_dual_core_publish_evidence(message);
}

#if OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
bool begin_cx323_evidence_burst(uint8_t expected_record_count) {
  if (cx323_collecting_evidence_burst ||
      cx323_evidence_burst_sequence == UINT32_MAX ||
      expected_record_count == 0u ||
      expected_record_count > OTIS_EVIDENCE_QUEUE_DEPTH)
    return false;
  cx323_evidence_burst_count = 0u;
  cx323_declared_evidence_burst_count = expected_record_count;
  cx323_pending_evidence_burst_sequence =
      cx323_evidence_burst_sequence + 1u;
  if (!otis_dual_core_begin_evidence_burst(expected_record_count)) {
    cx323_declared_evidence_burst_count = 0u;
    cx323_pending_evidence_burst_sequence = 0u;
    return false;
  }
  cx323_collecting_evidence_burst = true;
  return true;
}

void abandon_cx323_evidence_burst(void) {
  if (cx323_collecting_evidence_burst)
    otis_dual_core_cancel_evidence_burst();
  cx323_collecting_evidence_burst = false;
  cx323_evidence_burst_count = 0u;
  cx323_declared_evidence_burst_count = 0u;
  cx323_pending_evidence_burst_sequence = 0u;
}

bool commit_cx323_evidence_burst(void) {
  if (!cx323_collecting_evidence_burst ||
      cx323_evidence_burst_count == 0u ||
      cx323_evidence_burst_count != cx323_declared_evidence_burst_count ||
      cx323_pending_evidence_burst_sequence == 0u)
    return false;
  const uint32_t sequence = cx323_pending_evidence_burst_sequence;
  cx323_collecting_evidence_burst = false;
  cx323_evidence_burst_count = 0u;
  cx323_declared_evidence_burst_count = 0u;
  cx323_pending_evidence_burst_sequence = 0u;
  if (!otis_dual_core_commit_evidence_burst()) {
    otis_dual_core_cancel_evidence_burst();
    return false;
  }
  cx323_evidence_burst_sequence = sequence;
  return true;
}

bool queue_cx323_maintenance_record(
    OtisCx323MaintenanceEvent event, uint64_t event_timestamp_ticks,
    const OtisCx323Engine &engine_before,
    const OtisCx323Engine &engine_after,
    const OtisCx323Observation *observation,
    const OtisCx323Decision *decision,
    const OtisCx323MaintenanceHybridJoin *hybrid_join,
    const OtisCx323MaintenanceTransactionJoin *transaction_join,
    uint32_t evidence_burst_record_ordinal,
    uint32_t evidence_burst_record_count, const char *reason) {
  if (!cx323_collecting_evidence_burst || event_timestamp_ticks == 0u ||
      reason == nullptr || cx323_pending_evidence_burst_sequence == 0u ||
      evidence_burst_record_count != cx323_declared_evidence_burst_count ||
      evidence_burst_record_ordinal !=
          static_cast<uint32_t>(cx323_evidence_burst_count) + 1u ||
      cx323_maintenance_record_sequence == UINT32_MAX)
    return false;
  const uint32_t next_sequence = cx323_maintenance_record_sequence + 1u;
  const OtisCx323MaintenanceIdentityBinding identity = {
      kRunIdentity,
      kBuildIdentity,
      OTIS_BUILD_PROFILE_ID,
      kActivePolicyHash,
      kEstimatorHash,
  };
  const OtisCx323MaintenanceBuildInput input = {
      next_sequence,
      event,
      event_timestamp_ticks,
      identity,
      &engine_before,
      &engine_after,
      observation,
      decision,
      hybrid_join,
      transaction_join,
      cx323_pending_evidence_burst_sequence,
      evidence_burst_record_ordinal,
      evidence_burst_record_count,
      reason,
  };
  OtisCx323MaintenanceRecord record = {};
  evidence_frame_scratch = {};
  if (!otis_cx323_build_maintenance_record(&input, &record)) return false;
  if (event == OtisCx323MaintenanceEvent::GnssMetadataRequalified &&
      (record.requalification_d14_d8_observation_sequence == 0u ||
       record.requalification_d14_d8_observation_sequence !=
           engine_after.requalification_frontier))
    return false;
  const int used = otis_format_cx323_maintenance_v1(
      evidence_frame_scratch.data, sizeof(evidence_frame_scratch.data),
      &record);
  if (used <= 0 ||
      static_cast<size_t>(used) >= sizeof(evidence_frame_scratch.data))
    return false;
  evidence_frame_scratch.sequence = next_sequence;
  evidence_frame_scratch.length = static_cast<uint16_t>(used);
  if (!publish_evidence_message(&evidence_frame_scratch)) return false;
  cx323_maintenance_record_sequence = next_sequence;
  return true;
}

double cx323_picocodes_to_codes(OtisCx323Wide value) {
  char text[OTIS_CX323_WIDE_DECIMAL_CAPACITY] = {};
  if (!otis_cx323_wide_format_decimal(value, text, sizeof(text))) return 0.0;
  return strtod(text, nullptr) / 1000000000000.0;
}

OtisActiveHybridState cx323_project_hybrid_state(
    const OtisCx323Engine &engine, bool phase_valid) {
  if (engine.fail_static_reason != nullptr)
    return OtisActiveHybridState::FailStatic;
  if (!phase_valid)
    return OtisActiveHybridState::PhaseDegradedFrequencyOnly;
  if (engine.request_pending || engine.response_pending)
    return OtisActiveHybridState::FirstPhaseTransaction;
  if (engine.application_count == 0u)
    return OtisActiveHybridState::PhaseQualify;
  return OtisActiveHybridState::HybridTracking;
}

OtisActiveHybridDecision cx323_project_hybrid_decision(
    const OtisCx323Engine &before, const OtisCx323Engine &after,
    const OtisCx323Decision &decision, bool phase_valid,
    uint32_t timestamp_s) {
  constexpr double kConservativePlantGainHzPerCode = 0.000173340101;
  const double raw_fll_codes =
      cx323_picocodes_to_codes(decision.raw_fll_picocodes);
  const double raw_pll_codes =
      cx323_picocodes_to_codes(decision.raw_pll_picocodes);
  const double raw_combined_codes =
      cx323_picocodes_to_codes(decision.raw_combined_picocodes);
  return {
      static_cast<uint32_t>(decision.decision_sequence),
      timestamp_s,
      cx323_project_hybrid_state(before, phase_valid),
      cx323_project_hybrid_state(after, phase_valid),
      decision.reason,
      raw_fll_codes * kConservativePlantGainHzPerCode,
      raw_pll_codes * kConservativePlantGainHzPerCode,
      raw_combined_codes * kConservativePlantGainHzPerCode,
      raw_combined_codes,
      decision.requested_delta_codes,
      static_cast<uint16_t>(decision.requested_code),
      decision.counterfactual_frequency_only_delta_codes,
      decision.phase_materially_influenced,
      decision.step_limited,
      decision.range_clamped,
      decision.cadence_limited,
      decision.count_limited,
      decision.cumulative_budget_limited,
      static_cast<uint16_t>(before.application_count),
      static_cast<uint16_t>(before.cumulative_movement_codes),
  };
}

OtisCx323MaintenanceHybridJoin cx323_current_hybrid_join(
    const OtisCx323Observation &observation,
    const OtisCx323Decision &decision,
    uint32_t phase_observation_sequence) {
  return {
      hybrid_record_sequence,
      timing_record_sequence,
      decision.decision_sequence,
      observation.capture_session,
      observation.source_first_sequence,
      observation.source_last_sequence,
      observation.phase_epoch,
      phase_observation_sequence,
      observation.phase_valid,
  };
}

OtisCx323MaintenanceTransactionJoin cx323_current_transaction_join(
    OtisCx323MaintenanceTransactionEvent event,
    const OtisCx323Observation &observation,
    const OtisCx323Decision &decision, bool include_application,
    bool downstream_epoch_exact) {
  OtisCx323MaintenanceTransactionJoin join = {};
  join.transaction_record_sequence = transaction_record_sequence;
  join.transaction_timing_record_sequence = timing_record_sequence;
  join.transaction_event = event;
  join.request_sequence = transaction.request.request_sequence;
  join.decision_sequence = decision.decision_sequence;
  join.capture_session = observation.capture_session;
  join.source_first_sequence = observation.source_first_sequence;
  join.source_last_sequence = observation.source_last_sequence;
  if (include_application) {
    join.application_sequence = transaction.applied.application_sequence;
    join.actual_applied_code = transaction.applied.applied_code;
    join.actual_dac_epoch = transaction.dac_epoch;
    join.downstream_epoch_exact = downstream_epoch_exact;
  }
  return join;
}

struct Cx323LiveMutationSnapshot {
  OtisCx317ActiveTransaction transaction;
  EvidencePhase evidence_phase;
  uint32_t evidence_request_sequence;
  uint32_t evidence_pending_since_s;
  OtisCx317ActionableRequest pending_actionable_request;
  bool pending_actionable_request_valid;
  uint32_t transaction_record_sequence;
  uint32_t timing_record_sequence;
  uint32_t hybrid_record_sequence;
  uint32_t maintenance_record_sequence;
};

Cx323LiveMutationSnapshot capture_cx323_live_mutation_snapshot(void) {
  return {
      transaction,
      evidence_phase,
      evidence_request_sequence,
      evidence_pending_since_s,
      pending_actionable_request,
      pending_actionable_request_valid,
      transaction_record_sequence,
      timing_record_sequence,
      hybrid_record_sequence,
      cx323_maintenance_record_sequence,
  };
}

void restore_cx323_live_mutation_snapshot(
    const Cx323LiveMutationSnapshot &snapshot) {
  transaction = snapshot.transaction;
  evidence_phase = snapshot.evidence_phase;
  evidence_request_sequence = snapshot.evidence_request_sequence;
  evidence_pending_since_s = snapshot.evidence_pending_since_s;
  pending_actionable_request = snapshot.pending_actionable_request;
  pending_actionable_request_valid =
      snapshot.pending_actionable_request_valid;
  transaction_record_sequence = snapshot.transaction_record_sequence;
  timing_record_sequence = snapshot.timing_record_sequence;
  hybrid_record_sequence = snapshot.hybrid_record_sequence;
  cx323_maintenance_record_sequence = snapshot.maintenance_record_sequence;
  frame = {};
  abandon_cx323_evidence_burst();
}

bool queue_cx323_single_async_transition(
    OtisCx323MaintenanceEvent event, uint64_t event_timestamp_ticks,
    const OtisCx323Engine &engine_before,
    const OtisCx323Engine &engine_after, const char *reason) {
  const Cx323LiveMutationSnapshot snapshot =
      capture_cx323_live_mutation_snapshot();
  const OtisCx323Observation *observation =
      last_cx323_origin_valid ? &last_cx323_observation : nullptr;
  const OtisCx323Decision *decision =
      last_cx323_origin_valid ? &last_cx323_decision : nullptr;
  const OtisCx323MaintenanceHybridJoin *hybrid_join =
      last_cx323_origin_valid ? &last_cx323_hybrid_join : nullptr;
  if (!otis_dual_core_evidence_can_publish(1u) ||
      !begin_cx323_evidence_burst(1u) ||
      !queue_cx323_maintenance_record(
          event, event_timestamp_ticks, engine_before, engine_after,
          observation, decision, hybrid_join, nullptr, 1u, 1u, reason) ||
      !commit_cx323_evidence_burst()) {
    restore_cx323_live_mutation_snapshot(snapshot);
    return false;
  }
  return true;
}
#endif
#endif

#if OTIS_ENABLE_EXACT_LONG_RUN_TIMING_SIDECARS
bool publish_timing_sidecar(const char *data, int used,
                            uint32_t next_timing_sequence) {
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  if (data == nullptr || used <= 0 ||
      static_cast<size_t>(used) >= sizeof(evidence_frame_scratch.data) ||
      next_timing_sequence == 0u)
    return false;
  evidence_frame_scratch = {};
  evidence_frame_scratch.sequence = next_timing_sequence;
  evidence_frame_scratch.length = static_cast<uint16_t>(used);
  memcpy(evidence_frame_scratch.data, data,
         static_cast<size_t>(used) + 1u);
  if (!publish_evidence_message(&evidence_frame_scratch)) return false;
  timing_record_sequence = next_timing_sequence;
  return true;
#else
  (void)data;
  (void)used;
  (void)next_timing_sequence;
  return false;
#endif
}

bool queue_transaction_timing_sidecar(
    const char *event, uint64_t event_timestamp_ticks,
    uint32_t transaction_sequence, uint32_t session_id,
    uint32_t request_sequence, uint32_t decision_sequence,
    uint32_t source_first_sequence, uint32_t source_last_sequence,
    uint32_t authorization_sequence, uint32_t nonce,
    uint16_t accepted_code, uint16_t applied_code,
    uint32_t application_sequence, uint32_t dac_epoch,
    const char *reason) {
  char output[768] = {};
  const uint32_t next_timing_sequence = timing_record_sequence + 1u;
  const OtisActiveTransactionTimingV2 record = {
      next_timing_sequence,
      transaction_sequence,
      event,
      event_timestamp_ticks,
      kRunIdentity,
      kBuildIdentity,
      OTIS_BUILD_PROFILE_ID,
      session_id,
      request_sequence,
      decision_sequence,
      source_first_sequence,
      source_last_sequence,
      authorization_sequence,
      nonce,
      accepted_code,
      applied_code,
      application_sequence,
      dac_epoch,
      reason,
  };
  const int used = otis_format_active_transaction_timing_v2(
      output, sizeof(output), &record);
  return publish_timing_sidecar(output, used, next_timing_sequence);
}

bool queue_current_transaction_timing_sidecar(
    const char *event, uint64_t event_timestamp_ticks,
    const char *reason) {
  return queue_transaction_timing_sidecar(
      event, event_timestamp_ticks, transaction_record_sequence,
      transaction.expected_binding.session_id,
      transaction.request.request_sequence,
      transaction.request.decision_sequence,
      transaction.request.source_first_sequence,
      transaction.request.source_last_sequence,
      transaction.request.authorization_sequence, transaction.request.nonce,
      transaction.accepted.accepted_code, transaction.applied.applied_code,
      transaction.applied.application_sequence, transaction.dac_epoch, reason);
}

#if OTIS_ENABLE_CX320_ACTIVE_HYBRID
bool queue_hybrid_timing_sidecar(
    const OtisCx317ActiveLiveDecision &source,
    const OtisActiveHybridDecision &decision, uint64_t decision_ticks) {
  char output[640] = {};
  const uint32_t next_timing_sequence = timing_record_sequence + 1u;
  const OtisActiveHybridTimingV2 record = {
      next_timing_sequence,
      hybrid_record_sequence,
      decision.decision_sequence,
      decision_ticks,
      kRunIdentity,
      kBuildIdentity,
      OTIS_BUILD_PROFILE_ID,
      source.capture_session,
      source.source_first_sequence,
      source.source_last_sequence,
      decision.reason,
  };
  const int used = otis_format_active_hybrid_timing_v2(
      output, sizeof(output), &record);
  return publish_timing_sidecar(output, used, next_timing_sequence);
}
#endif
#endif

#if OTIS_ENABLE_CX320_ACTIVE_HYBRID
void hybrid_fail_static(const char *reason) {
  hybrid_engine.state = OtisActiveHybridState::FailStatic;
  hybrid_engine.reason = reason;
  hybrid_engine.fault_reason = reason;
  hybrid_engine.transaction_outstanding = false;
  hybrid_engine.outstanding_phase_material = false;
  pending_hybrid_decision_valid = false;
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
  if (plant_sign_engine_ready) {
    plant_sign_engine.state = OtisCx321PlantSignState::FailStatic;
    plant_sign_engine.reason = reason;
    plant_sign_engine.attested = false;
  }
  pending_plant_sign_application = false;
#endif
}
#endif

OtisCx317ActiveBinding expected_binding(uint32_t session_id) {
  return {
      kRunIdentity,
      kBuildIdentity,
      OTIS_BUILD_PROFILE_ID,
      kEstimatorHash,
      kModelHash,
      kActivePolicyHash,
      kResponsePolicyHash,
      kNumericalPolicyHash,
      session_id,
      static_cast<uint16_t>(OTIS_CX317_ACTIVE_START_CODE),
      0xA800u,
      0xAB00u,
      21u,
      static_cast<uint16_t>(OTIS_CX317_ACTIVE_CORRECTION_LIMIT),
      static_cast<uint16_t>(OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES),
#if OTIS_CX317_ACTIVE_CAMPAIGN == OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_B || \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX318_STAGE5_LOWER || \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX318_STAGE5_UPPER || \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_TIGHT_DEADBAND_LOWER || \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_D9_D6_FREQUENCY_ONLY_ENDURANCE || \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_TIGHT_DEADBAND_UPPER || \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_LOWER || \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_UPPER || \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_UPPER_COMPLETION || \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX320_ACTIVE_HYBRID || \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX322_DIRECT_HYBRID || \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_SUSTAINED_HYBRID_REGULATION || \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_D9_D6_72H_SUSTAINED_HYBRID || \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX323_D9_D6_72H_ADAPTIVE_HYBRID
      true,
#elif OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_CX321_ACTIVE_HYBRID
      true,
#else
      false,
#endif
#if OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
      false,
#else
      true,
#endif
#if OTIS_ENABLE_CX322_DIRECT_HYBRID
      true,
#else
      false,
#endif
  };
}

OtisCx317ActiveEligibility eligibility(uint32_t now_s) {
  const bool profile_matches = strcmp(OTIS_BUILD_PROFILE_ID, kExpectedProfile) == 0;
  const bool session_matches =
      transaction_bound && have_health &&
      latest_health.session_id == transaction.expected_binding.session_id;
  return {
      transaction_bound,
      transaction_bound,
      profile_matches,
      transaction_bound,
      transaction_bound,
      transaction_bound,
      transaction_bound,
      session_matches,
      have_health && latest_health.gnss_metadata_valid,
      have_health && latest_health.gnss_identity_stable,
      have_health && latest_health.gnss_3d_evidence,
      have_health && latest_health.raw_pps_valid,
      have_health && latest_health.count_valid,
      have_health && latest_health.estimator_valid,
      have_health && latest_health.model_applicable,
      have_health && latest_health.temperature_valid,
      have_health && latest_health.applied_code_confirmed &&
          transaction_bound &&
          latest_health.applied_code == transaction.applied_code &&
          transaction.applied_code >= transaction.expected_binding.minimum_code &&
          transaction.applied_code <= transaction.expected_binding.maximum_code,
      capture_lease_live(now_s),
      have_health && latest_health.abort_path_live,
      evidence_phase == EvidencePhase::None,
  };
}

bool active_integrity_healthy(uint32_t now_s) {
  if (!have_health || !transaction_bound) return false;
  return
#if OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
         // CX323 routes every recoverable serial-metadata qualification
         // anomaly, including a temporarily unconfirmed receiver identity,
         // into its bounded metadata hold. D14/D8/reference-integrity loss is
         // still terminal and is checked independently below.
         true &&
#else
         latest_health.gnss_identity_stable &&
#endif
         latest_health.reference_integrity_valid &&
         latest_health.applied_code_confirmed &&
         latest_health.applied_code == transaction.applied_code &&
         capture_lease_live(now_s) && latest_health.abort_path_live;
}

bool gnss_metadata_healthy(void) {
  return have_health && latest_health.gnss_metadata_valid &&
         latest_health.gnss_identity_stable &&
         latest_health.gnss_3d_evidence;
}

bool d14_d8_path_healthy(void) {
  return have_health && latest_health.session_id != 0u &&
         latest_health.raw_pps_valid && latest_health.count_valid;
}

bool reference_path_healthy(void) {
  return gnss_metadata_healthy() && d14_d8_path_healthy();
}

bool reference_requalification_healthy(void) {
  return reference_path_healthy() && latest_health.estimator_valid;
}

bool critical_continuity_healthy(uint32_t now_s) {
  const bool reference_healthy = gnss_metadata_hold_active
                                     ? d14_d8_path_healthy()
                                     : reference_path_healthy();
  return active_integrity_healthy(now_s) && reference_healthy &&
         latest_health.session_id == transaction.expected_binding.session_id;
}

const char *evidence_state_name(void) {
  switch (evidence_phase) {
    case EvidencePhase::Request:
      return "request_pending";
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    case EvidencePhase::Acceptance:
      return "acceptance_pending";
#endif
    case EvidencePhase::Application:
      return "application_pending";
    case EvidencePhase::Response:
      return "response_pending";
    case EvidencePhase::None:
      return "evidence_clear";
  }
  return "evidence_clear";
}

#if OTIS_ENABLE_DUAL_CORE_PARTITION
OtisCrossCoreActuatorRequest cross_core_request(
    const OtisCx317ActionableRequest &request, uint32_t now_s) {
  OtisCrossCoreActuatorRequest cross = {};
  cross.request_sequence = request.request_sequence;
  cross.decision_sequence = request.decision_sequence;
  cross.source_first_sequence = request.source_first_sequence;
  cross.source_last_sequence = request.source_last_sequence;
#if OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
  cross.decision_reference_ticks =
      pending_cx323_decision_valid &&
              pending_cx323_decision.decision_sequence ==
                  request.decision_sequence
          ? pending_cx323_decision.decision_timestamp_ticks
          : 0u;
#else
  cross.decision_reference_ticks =
      static_cast<uint64_t>(request.timestamp_s) * kCaptureTicksPerSecond;
#endif
  cross.monotonic_deadline_s =
      now_s + kEvidenceAcknowledgementMaximumAgeS;
  cross.authorization_sequence = request.authorization_sequence;
  cross.nonce = request.nonce;
  cross.session_id = request.session_id;
  cross.correction_ordinal = request.correction_ordinal;
  cross.current_applied_code = request.current_applied_code;
  cross.requested_code = request.requested_code;
  cross.requested_delta_codes = request.requested_delta_codes;
  cross.actionable = request.actionable;
  return cross;
}

bool publish_cross_core_actuator_message(OtisCriticalMessageKind kind,
                                         uint32_t now_s) {
  if (!pending_actionable_request_valid) return false;
  OtisCriticalRecordMessage message = {};
  message.kind = kind;
  message.sequence = pending_actionable_request.request_sequence;
  message.timestamp_ticks =
      static_cast<uint64_t>(now_s) * kCaptureTicksPerSecond;
  snprintf(message.component, sizeof(message.component), "%s",
           "cx317_actuator");
  snprintf(message.reason, sizeof(message.reason), "%s",
           kind == OtisCriticalMessageKind::ActuatorRequest
               ? "durable_request_released_to_core0"
               : "durable_acceptance_released_for_single_application");
  message.request = kind == OtisCriticalMessageKind::ActuatorRequest
                        ? cross_core_request(pending_actionable_request, now_s)
                        : timing_actuator_guard.pending;
  return otis_dual_core_publish_critical(&message);
}
#endif

bool queue_frame(const char *event, const OtisCx317ResponseResult *response,
                 double post_error_hz) {
  if (frame.length != 0u) return false;
  const char *response_name =
      response == nullptr ? "unavailable"
                          : otis_cx317_response_class_name(response->classification);
  const char *reason = response == nullptr ? transaction.reason : response->reason;
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  const uint64_t progress_ticks =
      static_cast<uint64_t>(transaction.request.timestamp_s) *
      kCaptureTicksPerSecond;
  otis_dual_core_note_timing_progress(
      OtisTimingProgressPhase::Cx317ActivePrepare, progress_ticks);
#endif
  char pre_error[32] = "";
  char post_error[32] = "";
  char observed_response[32] = "";
  char cumulative_response[32] = "";
  if (!otis_format_fixed(transaction.request.pre_error_hz, 9u, pre_error,
                         sizeof(pre_error)) ||
      !otis_format_fixed(post_error_hz, 9u, post_error,
                         sizeof(post_error)) ||
      !otis_format_fixed(
          response == nullptr ? 0.0 : response->observed_response_hz, 9u,
          observed_response, sizeof(observed_response)) ||
      !otis_format_fixed(
          response == nullptr ? 0.0 : response->cumulative_response_hz, 9u,
          cumulative_response, sizeof(cumulative_response)))
    return false;
  const uint32_t next_record_sequence = transaction_record_sequence + 1u;
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  otis_dual_core_note_timing_progress(
      OtisTimingProgressPhase::Cx317ActiveFormat, progress_ticks);
#endif
  const int used = snprintf(
      frame.data, sizeof(frame.data),
      "ACT,1,%lu,%s,%s,%s,%s,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%u,%ld,%u,%u,%u,%s,%u,%lu,%u,%u,%lu,%s,%s,%s,%u,%s,%u,%u,%s,%s,%s,%u,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\r\n",
      static_cast<unsigned long>(next_record_sequence), event, kRunIdentity,
      kBuildIdentity, OTIS_BUILD_PROFILE_ID,
      static_cast<unsigned long>(transaction.expected_binding.session_id),
      static_cast<unsigned long>(transaction.request.authorization_sequence),
      static_cast<unsigned long>(transaction.request.nonce),
      static_cast<unsigned long>(transaction.request.request_sequence),
      static_cast<unsigned long>(transaction.request.decision_sequence),
      static_cast<unsigned long>(transaction.request.source_first_sequence),
      static_cast<unsigned long>(transaction.request.source_last_sequence),
      static_cast<unsigned long>(transaction.request.timestamp_s),
      transaction.request.current_applied_code,
      static_cast<long>(transaction.request.requested_delta_codes),
      transaction.request.requested_code, transaction.request.correction_ordinal,
      transaction.request.cumulative_after_codes,
      pre_error,
      transaction.accepted.accepted_code,
      static_cast<unsigned long>(transaction.accepted.accepted_timestamp_s),
      transaction.applied.applied_code, transaction.applied.application_sequence,
      static_cast<unsigned long>(transaction.applied.application_timestamp_s),
      transaction.applied.i2c_ok ? "true" : "false",
      transaction.applied.clamped ? "true" : "false",
      transaction.applied.ambiguous ? "true" : "false",
      transaction.dac_epoch, estimator_history_reset ? "true" : "false",
      transaction.correction_count,
      transaction.cumulative_movement_codes, post_error, observed_response,
      cumulative_response,
      response == nullptr ? 0u : response->consecutive_indeterminate,
      otis_cx317_active_state_name(transaction.state), response_name, reason,
      kEstimatorHash, kModelHash, kActivePolicyHash, kResponsePolicyHash,
      kNumericalPolicyHash,
      // ACT is a durable observation, never a transferable authority token.
      // During the dual-core request_created phase the private pending request
      // remains actionable until Core 0 accepts it, but the serialized copy
      // must stay non-actionable exactly as the frozen evidence contract
      // requires.  The host releases the private request only by acknowledging
      // the durably preserved phase and cannot reconstruct authority from CSV.
      "false", evidence_state_name());
  if (used <= 0 || static_cast<size_t>(used) >= sizeof(frame.data)) {
    frame = {};
    return false;
  }
  frame.length = static_cast<uint16_t>(used);
  frame.sent = 0u;
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  evidence_frame_scratch = {};
  evidence_frame_scratch.sequence = next_record_sequence;
  evidence_frame_scratch.length = frame.length;
  memcpy(evidence_frame_scratch.data, frame.data, frame.length + 1u);
  if (!publish_evidence_message(&evidence_frame_scratch)) {
    frame = {};
    return false;
  }
  frame = {};
#endif
  transaction_record_sequence = next_record_sequence;
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  otis_dual_core_note_timing_progress(
      OtisTimingProgressPhase::Cx317ActivePublish, progress_ticks);
#endif
  return true;
}

bool queue_manual_start_frame(uint16_t code, bool ok, uint32_t now_s) {
  if (frame.length != 0u) return false;
  const uint32_t next_record_sequence = transaction_record_sequence + 1u;
  const int used = snprintf(
      frame.data, sizeof(frame.data),
      "ACT,1,%lu,manual_start,%s,%s,%s,%lu,0,0,0,0,0,0,%lu,%u,0,%u,0,0,0.000000000,%u,%lu,%u,0,%lu,%s,false,false,%u,false,%u,%u,0.000000000,0.000000000,0.000000000,0,%s,unavailable,%s,%s,%s,%s,%s,%s,false,evidence_clear\r\n",
      static_cast<unsigned long>(next_record_sequence), kRunIdentity,
      kBuildIdentity, OTIS_BUILD_PROFILE_ID,
      static_cast<unsigned long>(transaction_bound
                                     ? transaction.expected_binding.session_id
                                     : 0u),
      static_cast<unsigned long>(now_s), code, code, code,
      static_cast<unsigned long>(now_s), code,
      static_cast<unsigned long>(now_s), ok ? "true" : "false",
      transaction_bound ? transaction.dac_epoch : 0u,
      transaction_bound ? transaction.correction_count : 0u,
      transaction_bound ? transaction.cumulative_movement_codes : 0u,
      transaction_bound ? otis_cx317_active_state_name(transaction.state)
                        : "DISARMED",
      ok ? "manual_start_established" : "manual_start_failed", kEstimatorHash,
      kModelHash, kActivePolicyHash, kResponsePolicyHash,
      kNumericalPolicyHash);
  if (used <= 0 || static_cast<size_t>(used) >= sizeof(frame.data)) {
    frame = {};
    return false;
  }
  frame.length = static_cast<uint16_t>(used);
  frame.sent = 0u;
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  evidence_frame_scratch = {};
  evidence_frame_scratch.sequence = next_record_sequence;
  evidence_frame_scratch.length = frame.length;
  memcpy(evidence_frame_scratch.data, frame.data, frame.length + 1u);
  if (!publish_evidence_message(&evidence_frame_scratch)) {
    frame = {};
    return false;
  }
  frame = {};
#endif
  transaction_record_sequence = next_record_sequence;
  return true;
}

#if OTIS_ENABLE_CX320_ACTIVE_HYBRID
bool queue_active_hybrid_decision(
    const OtisCx317ActiveLiveDecision &source,
    const OtisActiveHybridDecision &decision,
    uint64_t decision_timestamp_ticks) {
  const uint32_t next_sequence = hybrid_record_sequence + 1u;
  OtisActiveHybridDecisionRecordContext context = {
      next_sequence,
      kRunIdentity,
      kBuildIdentity,
      OTIS_BUILD_PROFILE_ID,
      kEstimatorHash,
      kPhaseEstimatorHash,
      otis_cx317_active_state_name(transaction.state),
      transaction.have_request ? transaction.request.request_sequence : 0u,
      transaction.have_acceptance ? transaction.request.request_sequence : 0u,
      transaction.have_application ? transaction.applied.application_sequence
                                   : 0u,
      pending_hybrid_response_valid
          ? otis_cx317_response_class_name(pending_hybrid_response_class)
          : "unavailable",
      source.phase_recorder_published &&
          source.phase_dac_epoch == source.dac_epoch &&
          source.phase_applied_code == source.current_applied_code,
      kActivePolicyHash,
      kResponsePolicyHash,
      false,
  };
  const bool carries_dependent_response =
      otis_dependent_response_identity_apply(&dependent_response_identity,
                                             &context);
  const int used = otis_format_active_hybrid_decision_v1(
      frame.data, sizeof(frame.data), &source, &decision, &context);
  if (used <= 0 || static_cast<size_t>(used) >= sizeof(frame.data)) {
    frame = {};
    return false;
  }
  frame.length = static_cast<uint16_t>(used);
  frame.sent = 0u;
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  evidence_frame_scratch = {};
  evidence_frame_scratch.sequence = next_sequence;
  evidence_frame_scratch.length = frame.length;
  memcpy(evidence_frame_scratch.data, frame.data, frame.length + 1u);
  if (!publish_evidence_message(&evidence_frame_scratch)) {
    frame = {};
    return false;
  }
  frame = {};
#endif
  hybrid_record_sequence = next_sequence;
#if OTIS_ENABLE_EXACT_LONG_RUN_TIMING_SIDECARS
  if (!queue_hybrid_timing_sidecar(source, decision,
                                   decision_timestamp_ticks))
    return false;
#else
  (void)decision_timestamp_ticks;
#endif
  if (carries_dependent_response)
    otis_dependent_response_identity_consume(&dependent_response_identity);
  return true;
}
#endif

#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
bool queue_plant_sign_frame(
    const char *event, uint64_t event_ticks, const char *state_before,
    const char *state_after, const char *reason,
    const OtisCx321PlantSignEstimate *estimate, const char *tight_state) {
  if (frame.length != 0u || event == nullptr || state_before == nullptr ||
      state_after == nullptr || reason == nullptr)
    return false;
  frame = {};
  OtisCx321PlantSignFormatRecord record = {};
  record.record_sequence = plant_sign_record_sequence + 1u;
  record.event = event;
  record.event_ticks = event_ticks;
  record.run_identity = kRunIdentity;
  record.build_identity = kBuildIdentity;
  record.profile_identity = OTIS_BUILD_PROFILE_ID;
  record.capture_session = transaction.expected_binding.session_id;
  record.policy_sha256 = kActivePolicyHash;
  record.plant_sign_gate_sha256 = kPlantSignGateHash;
  record.identification_estimator_sha256 = kIdentificationEstimatorHash;
  record.identification_estimator_config_sha256 =
      kIdentificationEstimatorConfigHash;
  record.natural_frequency_estimator_sha256 = kEstimatorHash;
  record.setup_application_ticks = setup_application_timestamp_ticks;
  record.setup_applied_code = OTIS_CX317_ACTIVE_START_CODE;
  record.state_before = state_before;
  record.state_after = state_after;
  record.reason = reason;
  record.have_estimate = estimate != nullptr;
  if (estimate != nullptr) record.estimate = *estimate;
  record.tight_state = tight_state;
  record.decision = plant_sign_engine.pending_decision;
  record.request_sequence = transaction.request.request_sequence;
  record.acceptance_sequence = transaction.accepted.request_sequence;
  record.application_sequence = transaction.applied.application_sequence;
  record.accepted_code = transaction.accepted.accepted_code;
  record.applied_code = transaction.applied.applied_code;
  record.application_ticks = plant_sign_engine.application_ticks;
  record.dac_epoch = transaction.dac_epoch;
  record.response = plant_sign_engine.pending_response;
  record.acknowledged_response_record_sequence =
      pending_response_psq_record_sequence;
  record.host_replay_exact = true;
  record.replay_attestation_sha256 = plant_sign_attestation_sha256;
  record.global_correction_count = hybrid_engine.correction_count;
  record.global_cumulative_movement_codes =
      hybrid_engine.cumulative_movement_codes;
  record.global_last_application_ticks = hybrid_engine.last_application_ticks;
  record.natural_chatter_origin_code = hybrid_engine.natural_chatter_origin_code;
  record.natural_cumulative_movement_codes =
      hybrid_engine.natural_cumulative_movement_codes;
  record.natural_direction_count = hybrid_engine.direction_count;
  record.attested = plant_sign_engine.attested;
  if (!otis_cx321_plant_sign_format_record(
          &record, frame.data, sizeof(frame.data), &frame.length)) {
    frame = {};
    return false;
  }
  frame.sent = 0u;
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  evidence_frame_scratch = {};
  evidence_frame_scratch.sequence = plant_sign_record_sequence + 1u;
  evidence_frame_scratch.length = frame.length;
  memcpy(evidence_frame_scratch.data, frame.data, frame.length + 1u);
  if (!publish_evidence_message(&evidence_frame_scratch)) {
    frame = {};
    return false;
  }
  frame = {};
#endif
  plant_sign_record_sequence++;
  return true;
}
#endif

bool withdraw_private_request_for_gnss_metadata_hold(void) {
  if (transaction.state != OtisCx317ActiveState::RequestPending ||
      evidence_phase != EvidencePhase::Request ||
      !transaction.have_request || transaction.have_acceptance ||
      transaction.have_application || !pending_actionable_request_valid ||
      transaction.request.request_sequence !=
          pending_actionable_request.request_sequence ||
      transaction.request.nonce != pending_actionable_request.nonce)
    return false;
  transaction.request.actionable = false;
  transaction.have_request = false;
  transaction.have_acceptance = false;
  transaction.have_application = false;
  transaction.have_arm = false;
  transaction.state = OtisCx317ActiveState::Disarmed;
  transaction.reason = "gnss_metadata_private_request_withdrawn";
  return true;
}

bool enter_gnss_metadata_hold(void) {
  if (!transaction_bound || !manual_start_confirmed) return false;
  const bool entering_new_hold = !gnss_metadata_hold_active;
  if (entering_new_hold) {
    gnss_metadata_hold_active = true;
    gnss_metadata_hold_transaction_pending = false;
    gnss_metadata_hold_entry_sequence = latest_health.gnss_metadata_sequence;
    gnss_metadata_requalification_sequence = 0u;
    gnss_metadata_qualification_frontier = 0u;
    gnss_metadata_hold_session = transaction.expected_binding.session_id;
    gnss_metadata_hold_applied_code = transaction.applied_code;
    gnss_metadata_hold_dac_epoch = transaction.dac_epoch;
  }

#if OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
  if (!cx323_engine_ready || !health_event_ticks_available ||
      health_event_timestamp_ticks == 0u)
    return false;

  if (cx323_engine.request_pending &&
      transaction.state == OtisCx317ActiveState::RequestPending &&
      evidence_phase == EvidencePhase::Request) {
    if (!pending_cx323_origin_valid ||
        !otis_dual_core_evidence_can_publish(4u))
      return false;
    const Cx323LiveMutationSnapshot rejection_snapshot =
        capture_cx323_live_mutation_snapshot();
    const OtisCx323Engine rejection_before = cx323_engine;
    OtisCx323Engine rejection_after = rejection_before;
    if (!otis_cx323_engine_reject_or_expire_request(&rejection_after) ||
        !withdraw_private_request_for_gnss_metadata_hold()) {
      restore_cx323_live_mutation_snapshot(rejection_snapshot);
      return false;
    }
    pending_actionable_request_valid = false;
    evidence_phase = EvidencePhase::None;
    evidence_request_sequence = 0u;
    evidence_pending_since_s = 0u;
    if (!begin_cx323_evidence_burst(3u) ||
        !queue_frame("request_withdrawn", nullptr, 0.0) ||
        !queue_current_transaction_timing_sidecar(
            "request_withdrawn", health_event_timestamp_ticks,
            transaction.reason)) {
      restore_cx323_live_mutation_snapshot(rejection_snapshot);
      return false;
    }
    const OtisCx323MaintenanceTransactionJoin rejection_join =
        cx323_current_transaction_join(
            OtisCx323MaintenanceTransactionEvent::RequestWithdrawn,
            pending_cx323_observation, pending_cx323_decision, false,
            false);
    if (!queue_cx323_maintenance_record(
            OtisCx323MaintenanceEvent::RequestRejectedOrExpired,
            health_event_timestamp_ticks, rejection_before,
            rejection_after, &pending_cx323_observation,
            &pending_cx323_decision, &pending_cx323_hybrid_join,
            &rejection_join, 3u, 3u, rejection_after.last_reason) ||
        !commit_cx323_evidence_burst()) {
      restore_cx323_live_mutation_snapshot(rejection_snapshot);
      return false;
    }
    cx323_engine = rejection_after;
    pending_cx323_decision_valid = false;
    pending_cx323_origin_valid = false;
  }

  if (cx323_engine.request_pending) {
    // The request has already crossed the durable evidence boundary. Core 0
    // must reject it with the exact identity before the controller can leave
    // REQUEST_PENDING and enter metadata hold.
    gnss_metadata_hold_transaction_pending = true;
    return true;
  }

  if (!cx323_engine.metadata_hold) {
    const OtisCx323Engine hold_before = cx323_engine;
    OtisCx323Engine hold_after = hold_before;
    if (!otis_cx323_engine_enter_metadata_hold(&hold_after) ||
        !queue_cx323_single_async_transition(
            OtisCx323MaintenanceEvent::GnssMetadataHoldEnter,
            health_event_timestamp_ticks, hold_before, hold_after,
            hold_after.last_reason))
      return false;
    cx323_engine = hold_after;
  } else if (!entering_new_hold && cx323_engine.metadata_requalified) {
    // A second metadata anomaly during the two-window gate restarts the same
    // continuous hold without manufacturing another false-to-true AHM event.
    OtisCx323Engine restarted = cx323_engine;
    if (!otis_cx323_engine_enter_metadata_hold(&restarted)) return false;
    cx323_engine = restarted;
  }

  if (transaction.state == OtisCx317ActiveState::RequestPending ||
      transaction.state ==
          OtisCx317ActiveState::AcceptedAwaitingApplication ||
      transaction.state == OtisCx317ActiveState::AwaitingResponse ||
      evidence_phase != EvidencePhase::None) {
    gnss_metadata_hold_transaction_pending = true;
    return true;
  }
  gnss_metadata_hold_transaction_pending = false;
  return transaction.state == OtisCx317ActiveState::ReferenceHold ||
         otis_cx317_active_reference_hold(
             &transaction, "gnss_metadata_unqualified_hold");
#endif

  if (transaction.state == OtisCx317ActiveState::RequestPending &&
      evidence_phase == EvidencePhase::Request) {
#if OTIS_ENABLE_EXACT_LONG_RUN_TIMING_SIDECARS
    if (!health_event_ticks_available) return false;
#endif
    if (!withdraw_private_request_for_gnss_metadata_hold())
      return false;
    pending_actionable_request_valid = false;
#if OTIS_ENABLE_CX320_ACTIVE_HYBRID
    pending_hybrid_decision_valid = false;
#endif
    evidence_phase = EvidencePhase::None;
    evidence_request_sequence = 0u;
    evidence_pending_since_s = 0u;
    if (!queue_frame("request_withdrawn", nullptr, 0.0))
      return false;
#if OTIS_ENABLE_EXACT_LONG_RUN_TIMING_SIDECARS
    if (!queue_current_transaction_timing_sidecar(
            "request_withdrawn", health_event_timestamp_ticks,
            transaction.reason))
      return false;
#endif
  }

  if (transaction.state == OtisCx317ActiveState::RequestPending ||
      transaction.state ==
          OtisCx317ActiveState::AcceptedAwaitingApplication ||
      transaction.state == OtisCx317ActiveState::AwaitingResponse ||
      evidence_phase != EvidencePhase::None) {
    gnss_metadata_hold_transaction_pending = true;
    return true;
  }

  gnss_metadata_hold_transaction_pending = false;
  return otis_cx317_active_reference_hold(
      &transaction, "gnss_metadata_unqualified_hold");
}

bool maybe_complete_gnss_metadata_requalification(void) {
  if (!gnss_metadata_hold_active) return false;
  if (gnss_metadata_hold_transaction_pending) {
    if (transaction.state == OtisCx317ActiveState::AwaitingResponse &&
        transaction.have_application &&
        latest_health.applied_code_confirmed &&
        latest_health.applied_code == transaction.applied_code) {
      // An already released request remains Core-0-owned.  Once its exact
      // application is confirmed, that code/epoch becomes the frozen hold
      // identity while the D14/D8 response completes.
      gnss_metadata_hold_applied_code = transaction.applied_code;
      gnss_metadata_hold_dac_epoch = transaction.dac_epoch;
    }
    if (transaction.state == OtisCx317ActiveState::Disarmed &&
        evidence_phase == EvidencePhase::None) {
      gnss_metadata_hold_transaction_pending = false;
      if (!otis_cx317_active_reference_hold(
              &transaction, "gnss_metadata_unqualified_hold"))
        return false;
    } else {
      return false;
    }
  }
  if (transaction.state != OtisCx317ActiveState::ReferenceHold) return false;
  if (!gnss_metadata_healthy()) {
    gnss_metadata_requalification_sequence = 0u;
    gnss_metadata_qualification_frontier = 0u;
    return false;
  }
#if OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
  if (!cx323_engine_ready || !cx323_engine.metadata_hold ||
      cx323_engine.request_pending || cx323_engine.response_pending)
    return false;
  if (cx323_engine.metadata_requalified) return false;
  if (latest_health.gnss_metadata_sequence <=
          gnss_metadata_hold_entry_sequence ||
      latest_health.d14_d8_observation_sequence == 0u)
    return false;
  if (!health_event_ticks_available || health_event_timestamp_ticks == 0u ||
      latest_health.session_id != gnss_metadata_hold_session ||
      !latest_health.applied_code_confirmed ||
      latest_health.applied_code != gnss_metadata_hold_applied_code ||
      transaction.applied_code != gnss_metadata_hold_applied_code ||
      transaction.dac_epoch != gnss_metadata_hold_dac_epoch) {
    otis_cx317_active_fault(
        &transaction,
        "cx323_metadata_requalification_identity_or_tick_contradiction");
    return false;
  }
  const OtisCx323Engine requalification_before = cx323_engine;
  OtisCx323Engine requalification_after = requalification_before;
  if (!otis_cx323_engine_requalify_metadata(
          &requalification_after,
          latest_health.d14_d8_observation_sequence) ||
      !queue_cx323_single_async_transition(
          OtisCx323MaintenanceEvent::GnssMetadataRequalified,
          health_event_timestamp_ticks, requalification_before,
          requalification_after, requalification_after.last_reason)) {
    otis_cx317_active_fault(
        &transaction, "cx323_metadata_requalification_evidence_fault");
    return false;
  }
  cx323_engine = requalification_after;
  gnss_metadata_requalification_sequence =
      latest_health.gnss_metadata_sequence;
  gnss_metadata_qualification_frontier =
      latest_health.d14_d8_observation_sequence;
  return true;
#endif
  if (gnss_metadata_requalification_sequence == 0u) {
    if (latest_health.gnss_metadata_sequence <=
        gnss_metadata_hold_entry_sequence)
      return false;
    gnss_metadata_requalification_sequence =
        latest_health.gnss_metadata_sequence;
    gnss_metadata_qualification_frontier =
        latest_health.d14_d8_observation_sequence;
    return false;
  }
  if (latest_health.d14_d8_observation_sequence <=
      gnss_metadata_qualification_frontier)
    return false;
  if (latest_health.session_id != gnss_metadata_hold_session ||
      !latest_health.applied_code_confirmed ||
      latest_health.applied_code != gnss_metadata_hold_applied_code ||
      transaction.applied_code != gnss_metadata_hold_applied_code ||
      transaction.dac_epoch != gnss_metadata_hold_dac_epoch) {
    otis_cx317_active_fault(
        &transaction,
        "gnss_metadata_requalification_session_code_or_epoch_contradiction");
    return false;
  }
  if (!otis_cx317_active_reference_requalify(
          &transaction, gnss_metadata_hold_session)) {
    otis_cx317_active_fault(
        &transaction, "gnss_metadata_requalification_transition_failed");
    return false;
  }
  gnss_metadata_hold_active = false;
  gnss_metadata_hold_transaction_pending = false;
  return true;
}

void update_active_reference_and_integrity(uint32_t now_s) {
  // Before the one-shot setup acknowledgement there is no authoritative DAC
  // code to protect, and the host may not yet have established its capture
  // lease. Keep the bound session in SETUP_PENDING until those preconditions
  // are deliberately established; the post-setup integrity predicate below
  // requires both and would otherwise manufacture an unrecoverable boot fault.
  if (!transaction_bound || !manual_start_confirmed) return;
  const bool inactive =
      transaction.state == OtisCx317ActiveState::Fault ||
      transaction.state == OtisCx317ActiveState::Aborted;
  if (inactive) return;
  const bool transaction_in_flight =
      transaction.state == OtisCx317ActiveState::RequestPending ||
      transaction.state ==
          OtisCx317ActiveState::AcceptedAwaitingApplication;
  if ((transaction_in_flight ||
       transaction.state == OtisCx317ActiveState::Armed ||
       transaction.state == OtisCx317ActiveState::AwaitingResponse ||
       transaction.state == OtisCx317ActiveState::ReferenceHold) &&
      !active_integrity_healthy(now_s)) {
    otis_cx317_active_fault(&transaction,
                            "active_integrity_or_capture_lease_lost");
    return;
  }

  const bool session_matches =
      latest_health.session_id == transaction.expected_binding.session_id;
  const bool timing_reference_healthy = d14_d8_path_healthy();
  const bool metadata_healthy = gnss_metadata_healthy();
  if (!session_matches || !timing_reference_healthy) {
    if (transaction_in_flight)
      otis_cx317_active_fault(
          &transaction,
          "d14_d8_or_session_lost_during_unfinished_actuator_transaction");
    else if (!otis_cx317_active_reference_hold(
                 &transaction,
                 session_matches ? "d14_d8_reference_quality_suspect_hold"
                                 : "reference_session_changed_hold"))
      otis_cx317_active_fault(&transaction,
                              "reference_hold_transition_failed");
    return;
  }

  if (!metadata_healthy) {
    if (!enter_gnss_metadata_hold())
      otis_cx317_active_fault(&transaction,
                              "gnss_metadata_hold_transition_failed");
    return;
  }
  if (gnss_metadata_hold_active) {
    maybe_complete_gnss_metadata_requalification();
    return;
  }

  const bool reference_healthy = reference_path_healthy();
  if (transaction_in_flight) {
    if (!session_matches || !reference_healthy)
      otis_cx317_active_fault(
          &transaction,
          "reference_lost_during_unfinished_actuator_transaction");
    return;
  }

  if (transaction.state == OtisCx317ActiveState::ReferenceHold) {
    if (reference_requalification_healthy())
      otis_cx317_active_reference_requalify(&transaction,
                                            latest_health.session_id);
    return;
  }

  if ((transaction.state == OtisCx317ActiveState::Disarmed ||
       transaction.state == OtisCx317ActiveState::Armed ||
       transaction.state == OtisCx317ActiveState::AwaitingResponse ||
       transaction.state == OtisCx317ActiveState::OutOfModelHold) &&
      (!session_matches || !reference_healthy)) {
    if (!otis_cx317_active_reference_hold(
            &transaction,
            session_matches ? "reference_quality_suspect_hold"
                            : "reference_session_changed_hold"))
      otis_cx317_active_fault(&transaction,
                              "reference_hold_transition_failed");
  }
}

}  // namespace

bool otis_cx317_active_live_begin(void) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  initialized = true;
  transaction_bound = false;
  have_health = false;
  have_capture_lease = false;
  manual_start_confirmed = false;
  periodic_applied_code_confirmation_seen = false;
  evidence_phase = EvidencePhase::None;
  last_capture_lease_sequence = 0u;
  evidence_request_sequence = 0u;
  evidence_pending_since_s = 0u;
  transaction_record_sequence = 0u;
  pending_actionable_request_valid = false;
  deferred_application_outcome_valid = false;
  last_application_acknowledged = false;
  estimator_history_reset = false;
  gnss_metadata_hold_active = false;
  gnss_metadata_hold_transaction_pending = false;
  gnss_metadata_hold_entry_sequence = 0u;
  gnss_metadata_requalification_sequence = 0u;
  gnss_metadata_qualification_frontier = 0u;
  gnss_metadata_hold_session = 0u;
  gnss_metadata_hold_applied_code = 0u;
  gnss_metadata_hold_dac_epoch = 0u;
#if OTIS_ENABLE_EXACT_LONG_RUN_TIMING_SIDECARS
  timing_record_sequence = 0u;
  manual_start_timing_recorded = false;
  health_event_ticks_available = false;
  health_event_timestamp_ticks = 0u;
#endif
#if OTIS_ENABLE_ACTIVE_TIMER0_EXTENSION
  pending_application_timestamp_ticks = 0u;
#endif
#if OTIS_ENABLE_CX320_ACTIVE_HYBRID
  hybrid_engine = {};
  hybrid_engine_ready = false;
  pending_hybrid_decision = {};
  pending_hybrid_decision_valid = false;
  pending_hybrid_response_class =
      OtisCx317ResponseClass::MeasurementOrActuatorFault;
  pending_hybrid_response_valid = false;
  pending_hybrid_predicted_sign_observed = false;
  otis_dependent_response_identity_reset(&dependent_response_identity);
  hybrid_record_sequence = 0u;
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
  otis_cx321_plant_sign_engine_init(&plant_sign_engine);
  plant_sign_engine_ready = false;
  pending_plant_sign_application = false;
  dispatching_plant_sign_request = false;
  plant_sign_record_sequence = 0u;
  pending_response_psq_record_sequence = 0u;
  plant_sign_handoff_pending = false;
  plant_sign_attestation_sha256[0] = '\0';
#endif
#if OTIS_ENABLE_CX32X_EXACT_ACTIVE_TIMING
  setup_application_timestamp_ticks = 0u;
#endif
#endif
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  otis_actuator_guard_init(&timing_actuator_guard);
#if OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
  cx323_evidence_burst_count = 0u;
  cx323_declared_evidence_burst_count = 0u;
  cx323_collecting_evidence_burst = false;
  cx323_pending_evidence_burst_sequence = 0u;
#endif
#endif
#if OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
  cx323_engine = {};
  cx323_engine_ready = false;
  pending_cx323_decision = {};
  pending_cx323_decision_valid = false;
  pending_cx323_observation = {};
  pending_cx323_hybrid_join = {};
  pending_cx323_origin_valid = false;
  last_cx323_observation = {};
  last_cx323_decision = {};
  last_cx323_hybrid_join = {};
  last_cx323_origin_valid = false;
  cx323_maintenance_record_sequence = 0u;
  cx323_evidence_burst_sequence = 0u;
  cx323_phase_nonzero_application_count = 0u;
  cx323_phase_material_application_count = 0u;
  cx323_frequency_only_application_count = 0u;
#endif
  frame = {};
  return true;
#else
  return true;
#endif
}

void otis_cx317_active_live_emit_headers(void) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  otis_transport_write_cstr(
      "record_type,schema_version,transaction_record_sequence,event,run_identity,build_identity,profile_identity,session_id,authorization_sequence,nonce,request_sequence,decision_sequence,source_first_sequence,source_last_sequence,decision_timestamp_s,current_applied_code,requested_delta_codes,requested_code,correction_ordinal,cumulative_after_codes,pre_error_hz,accepted_code,accepted_timestamp_s,applied_code,application_sequence,application_timestamp_s,i2c_ok,clamped,ambiguous,dac_epoch,estimator_history_reset,correction_count,cumulative_movement_codes,post_error_hz,observed_response_hz,cumulative_response_hz,consecutive_indeterminate,active_state,response_class,reason,estimator_sha256,model_sha256,active_policy_sha256,response_policy_sha256,numerical_policy_sha256,actionable,evidence_state\r\n");
#if OTIS_ENABLE_EXACT_LONG_RUN_TIMING_SIDECARS
  otis_transport_write_cstr(otis_active_transaction_timing_v2_csv_header());
  otis_transport_write_cstr("\r\n");
#endif
#if OTIS_ENABLE_CX320_ACTIVE_HYBRID
  otis_transport_write_cstr(
      "record_type,schema_version,hybrid_record_sequence,decision_sequence,decision_timestamp_s,run_identity,build_identity,profile_identity,capture_session,source_first_sequence,source_last_sequence,frequency_estimator_sha256,frequency_error_hz,accumulated_edge_error_counts,tight_state,phase_estimator_sha256,phase_epoch,phase_observation_sequence,relative_phase_cycles,phase_continuous,phase_current,phase_step_detected,phase_recorder_published,current_applied_code,dac_epoch,phase_applied_code,phase_dac_epoch,state_before,state_after,frequency_term_hz,phase_term_hz,combined_demand_hz,raw_combined_delta_codes,requested_delta_codes,requested_code,counterfactual_frequency_only_delta_codes,phase_materially_influenced,step_limited,range_clamped,cadence_limited,count_limited,cumulative_budget_limited,correction_count_before,cumulative_movement_before_codes,authority_state,request_sequence,acceptance_sequence,application_sequence,response_class,actual_applied_code,actual_dac_epoch,downstream_epoch_exact,reason,active_policy_sha256,response_policy_sha256,actionable\r\n");
#if OTIS_ENABLE_EXACT_LONG_RUN_TIMING_SIDECARS
  otis_transport_write_cstr(otis_active_hybrid_timing_v2_csv_header());
  otis_transport_write_cstr("\r\n");
#endif
#if OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
  char maintenance_header[kFrameCapacity] = {};
  if (otis_format_cx323_maintenance_v1_header(
          maintenance_header, sizeof(maintenance_header)) > 0)
    otis_transport_write_cstr(maintenance_header);
#endif
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
  otis_transport_write_cstr(otis_cx321_plant_sign_csv_header());
  otis_transport_write_cstr("\r\n");
#endif
#endif
#endif
}

void otis_cx317_active_live_update_health(
    const OtisCx317ActiveLiveHealth *health, uint32_t now_s) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (!initialized || health == nullptr) return;
  latest_health = *health;
  have_health = true;
  if (!transaction_bound && health->session_id != 0u) {
    const OtisCx317ActiveBinding binding = expected_binding(health->session_id);
    otis_cx317_active_transaction_init(&transaction, &binding);
    transaction_bound = true;
  } else if (transaction_bound && !manual_start_confirmed) {
    otis_cx317_active_note_session(&transaction, health->session_id,
                                   manual_start_confirmed);
  }
  if (transaction_bound && manual_start_confirmed) {
    // The setup application acknowledgement is the first authoritative
    // confirmation. A periodic health message already in flight may still
    // contain the pre-setup "unknown" state, so absence cannot become loss
    // until periodic health has caught up and confirmed this exact code once.
    if (health->applied_code_confirmed &&
        health->applied_code == transaction.applied_code) {
      periodic_applied_code_confirmation_seen = true;
    } else if (periodic_applied_code_confirmation_seen &&
               !health->applied_code_confirmed) {
      otis_cx317_active_fault(&transaction, "confirmed_applied_code_lost");
    }
  }
  update_active_reference_and_integrity(now_s);
#else
  (void)health;
  (void)now_s;
#endif
}

void otis_cx317_active_live_update_health_at_ticks(
    const OtisCx317ActiveLiveHealth *health, uint32_t now_s,
    uint64_t event_timestamp_ticks) {
#if OTIS_ENABLE_EXACT_LONG_RUN_TIMING_SIDECARS
  uint64_t extended_ticks = 0u;
  health_event_ticks_available =
      otis_cx317_preview_live_extend_timer0_ticks(event_timestamp_ticks,
                                                  &extended_ticks);
  health_event_timestamp_ticks =
      health_event_ticks_available ? extended_ticks : 0u;
  otis_cx317_active_live_update_health(health, now_s);
  health_event_ticks_available = false;
  health_event_timestamp_ticks = 0u;
#else
  (void)event_timestamp_ticks;
  otis_cx317_active_live_update_health(health, now_s);
#endif
}

void otis_cx317_active_live_service(uint32_t now_s) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  update_active_reference_and_integrity(now_s);
  if (transaction_bound && transaction.state == OtisCx317ActiveState::Armed &&
      transaction.have_arm && now_s > transaction.arm.expires_s)
    otis_cx317_active_fault(&transaction, "unused_authorization_expired");
  if (transaction_bound && evidence_phase != EvidencePhase::None &&
      static_cast<uint32_t>(now_s - evidence_pending_since_s) >
          kEvidenceAcknowledgementMaximumAgeS)
    otis_cx317_active_fault(&transaction,
                            "transaction_evidence_acknowledgement_timeout");
#if OTIS_ENABLE_CX320_ACTIVE_HYBRID
  if (transaction_bound &&
      (transaction.state == OtisCx317ActiveState::Fault ||
       transaction.state == OtisCx317ActiveState::Aborted) &&
      (hybrid_engine_ready
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
       || plant_sign_engine_ready
#endif
       ) &&
      hybrid_engine.state != OtisActiveHybridState::FailStatic)
    hybrid_fail_static(transaction.reason);
#endif
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  if (transaction_bound &&
      (!otis_actuator_guard_check_deadline(
           &timing_actuator_guard, now_s) ||
       otis_dual_core_fail_static()))
    otis_cx317_active_fault(&transaction,
                            "cross_core_partition_or_actuator_guard_fault");
#endif
#else
  (void)now_s;
#endif
}

bool otis_cx317_active_live_capture_lease(uint32_t sequence, uint32_t now_s) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (!initialized || sequence == 0u || sequence <= last_capture_lease_sequence)
    return false;
  last_capture_lease_sequence = sequence;
  last_capture_lease_s = now_s;
  have_capture_lease = true;
  return true;
#else
  (void)sequence;
  (void)now_s;
  return false;
#endif
}

bool otis_cx317_active_live_arm(uint32_t sequence, uint32_t nonce,
                               uint32_t expires_s, uint32_t now_s) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (!initialized || !transaction_bound) return false;
  const OtisCx317ArmRequest arm = {
      transaction.expected_binding, sequence, nonce, expires_s};
  const OtisCx317ActiveEligibility health = eligibility(now_s);
  return otis_cx317_active_arm(&transaction, &arm, &health, now_s);
#else
  (void)sequence;
  (void)nonce;
  (void)expires_s;
  (void)now_s;
  return false;
#endif
}

void otis_cx317_active_live_abort(const char *reason) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (transaction_bound) otis_cx317_active_abort(&transaction, reason);
  pending_actionable_request_valid = false;
  evidence_phase = EvidencePhase::None;
  evidence_request_sequence = 0u;
#if OTIS_ENABLE_CX320_ACTIVE_HYBRID
  otis_dependent_response_identity_reset(&dependent_response_identity);
  if (hybrid_engine_ready)
    hybrid_fail_static(reason == nullptr ? "operator_abort" : reason);
#endif
#else
  (void)reason;
#endif
}

bool otis_cx317_active_live_acknowledge_evidence(uint32_t request_sequence,
                                                 uint32_t phase_sequence,
                                                 uint32_t now_s) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (evidence_phase == EvidencePhase::None ||
      request_sequence != evidence_request_sequence ||
      phase_sequence != static_cast<uint32_t>(evidence_phase) ||
      frame.length != 0u)
    return false;
  if (evidence_phase == EvidencePhase::Request) {
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    if (!transaction_bound || !pending_actionable_request_valid ||
        transaction.state != OtisCx317ActiveState::RequestPending ||
#if OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
        !pending_cx323_decision_valid ||
        pending_cx323_decision.decision_timestamp_ticks == 0u ||
#endif
        !critical_continuity_healthy(now_s)) {
      if (transaction_bound)
        otis_cx317_active_fault(
            &transaction, "pre_acceptance_evidence_or_continuity_invalid");
      pending_actionable_request_valid = false;
      return false;
    }
    const OtisCrossCoreActuatorRequest request =
        cross_core_request(pending_actionable_request, now_s);
    if (!otis_actuator_guard_start(&timing_actuator_guard, &request,
                                   now_s) ||
        !publish_cross_core_actuator_message(
            OtisCriticalMessageKind::ActuatorRequest, now_s)) {
      otis_cx317_active_fault(&transaction,
                              "cross_core_actuator_request_queue_fault");
      pending_actionable_request_valid = false;
      return false;
    }
    evidence_phase = EvidencePhase::None;
    evidence_pending_since_s = 0u;
    return true;
#else
    if (!transaction_bound || !pending_actionable_request_valid ||
        transaction.state !=
            OtisCx317ActiveState::AcceptedAwaitingApplication ||
        !critical_continuity_healthy(now_s)) {
      if (transaction_bound)
        otis_cx317_active_fault(
            &transaction, "pre_application_evidence_or_continuity_invalid");
      pending_actionable_request_valid = false;
      return false;
    }
    const OtisCx317AppliedAck applied = otis_cx317_active_actuator_apply_once(
        &pending_actionable_request, &transaction.accepted,
        static_cast<uint16_t>(transaction.correction_count + 1u), now_s);
    pending_actionable_request_valid = false;
    const bool acknowledged =
        otis_cx317_active_acknowledge_application(&transaction, &applied);
    deferred_application_outcome = {};
    deferred_application_outcome.application_attempted = true;
    deferred_application_outcome.request_sequence = request_sequence;
    deferred_application_outcome.requested_code =
        transaction.request.requested_code;
    deferred_application_outcome.applied_code = applied.applied_code;
    deferred_application_outcome.applied = acknowledged;
    deferred_application_outcome.faulted = !acknowledged;
    deferred_application_outcome.reason = transaction.reason;
    deferred_application_outcome_valid = true;
    last_application_acknowledged = acknowledged;
    if (acknowledged) {
      latest_health.applied_code = transaction.applied_code;
      latest_health.applied_code_confirmed = true;
    }
    evidence_phase = EvidencePhase::Application;
    evidence_pending_since_s = now_s;
    return true;
#endif
  }
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  if (evidence_phase == EvidencePhase::Acceptance) {
    if (!transaction_bound || !pending_actionable_request_valid ||
        transaction.state !=
            OtisCx317ActiveState::AcceptedAwaitingApplication ||
        timing_actuator_guard.state !=
            OtisActuatorGuardState::AwaitingApplication ||
        !critical_continuity_healthy(now_s) ||
        !publish_cross_core_actuator_message(
            OtisCriticalMessageKind::ActuatorExecute, now_s)) {
      otis_cx317_active_fault(
          &transaction, "cross_core_application_release_or_continuity_fault");
      pending_actionable_request_valid = false;
      return false;
    }
    evidence_phase = EvidencePhase::None;
    evidence_pending_since_s = 0u;
    return true;
  }
#endif
#if OTIS_ENABLE_CX320_ACTIVE_HYBRID
  if (evidence_phase == EvidencePhase::Response) {
#if OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
    // CX323 commits response state with the atomic ACT/AT2/AHM burst. The
    // host phase-4 acknowledgement proves durable replay of that already
    // completed transition; it must not drive the legacy controller again.
    if (!cx323_engine_ready || cx323_engine.response_pending ||
        pending_cx323_origin_valid) {
      otis_cx317_active_fault(
          &transaction, "cx323_response_evidence_acknowledgement_invalid");
      return false;
    }
#else
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
    if (plant_sign_engine.state ==
        OtisCx321PlantSignState::ResponseAckPending)
      return false;
#endif
    const bool healthy_classification =
        pending_hybrid_response_valid &&
        (
#if OTIS_ENABLE_CX322_DIRECT_HYBRID
         pending_hybrid_response_class !=
             OtisCx317ResponseClass::MeasurementOrActuatorFault
#else
         pending_hybrid_response_class ==
             OtisCx317ResponseClass::HealthyDetected ||
         pending_hybrid_response_class ==
             OtisCx317ResponseClass::HealthyIndeterminateNearResolution ||
         pending_hybrid_response_class ==
             OtisCx317ResponseClass::InsideDeadband
#endif
        );
    const bool predicted_sign_observed =
        pending_hybrid_response_valid &&
        pending_hybrid_predicted_sign_observed;
    const bool applied_epoch_exact =
        latest_health.applied_code_confirmed &&
        latest_health.applied_code == hybrid_engine.applied_code &&
        transaction.dac_epoch == hybrid_engine.dac_epoch;
    // The CX320 response ACK is prospectively restricted to a host that has
    // durably captured and exactly replayed the AHY/ACT response evidence.
    const bool noted = otis_active_hybrid_engine_note_response(
        &hybrid_engine, healthy_classification, predicted_sign_observed,
        true, latest_health.estimator_valid, applied_epoch_exact,
        OTIS_ENABLE_CX322_DIRECT_HYBRID);
    const bool response_identity_retained =
        noted && otis_dependent_response_identity_retain(
                     &dependent_response_identity,
                     transaction.request.request_sequence,
                     transaction.applied.application_sequence,
                     otis_cx317_response_class_name(
                         pending_hybrid_response_class));
    pending_hybrid_response_valid = false;
    pending_hybrid_predicted_sign_observed = false;
    if (!noted || !response_identity_retained ||
        hybrid_engine.state == OtisActiveHybridState::FailStatic)
      otis_cx317_active_fault(
          &transaction, "active_hybrid_response_checkpoint_failed");
#endif
  }
#endif
  evidence_phase = EvidencePhase::None;
  evidence_request_sequence = 0u;
  evidence_pending_since_s = 0u;
  return true;
#else
  (void)request_sequence;
  (void)phase_sequence;
  (void)now_s;
  return false;
#endif
}

bool otis_cx317_active_live_on_cross_core_ack(
    const OtisCrossCoreActuatorAck *acknowledgement, uint32_t now_s) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && OTIS_ENABLE_DUAL_CORE_PARTITION
  if (acknowledgement == nullptr || !transaction_bound ||
      !pending_actionable_request_valid) {
    if (transaction_bound)
      otis_cx317_active_fault(
          &transaction, "cross_core_actuator_acknowledgement_invalid");
    return false;
  }
  const bool exact_metadata_rejection_context =
      acknowledgement->kind == OtisActuatorAckKind::Rejected &&
      acknowledgement->rejection_reason ==
          OtisActuatorRejectionReason::MetadataHoldCancelledBeforeAcceptance &&
      gnss_metadata_hold_active && gnss_metadata_hold_transaction_pending &&
      transaction.state == OtisCx317ActiveState::RequestPending &&
      transaction.have_request && !transaction.have_acceptance &&
      !transaction.have_application && evidence_phase == EvidencePhase::None &&
      timing_actuator_guard.state ==
          OtisActuatorGuardState::AwaitingAcceptance;
  if (exact_metadata_rejection_context) {
#if OTIS_ENABLE_EXACT_LONG_RUN_TIMING_SIDECARS
    uint64_t rejection_ticks = 0u;
    if (!otis_cx317_preview_live_extend_timer0_ticks(
            acknowledgement->acknowledgement_ticks, &rejection_ticks)) {
      otis_cx317_active_fault(
          &transaction, "core0_rejection_timestamp_projection_failed");
      return false;
    }
#endif
#if OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
    if (!cx323_engine_ready || !cx323_engine.request_pending ||
        !pending_cx323_origin_valid ||
        !otis_dual_core_evidence_can_publish(4u)) {
      otis_cx317_active_fault(
          &transaction, "cx323_core0_rejection_origin_or_capacity_fault");
      return false;
    }
    const Cx323LiveMutationSnapshot rejection_snapshot =
        capture_cx323_live_mutation_snapshot();
    const OtisCx323Engine rejection_before = cx323_engine;
    OtisCx323Engine rejection_after = rejection_before;
    if (!otis_cx323_engine_reject_or_expire_request(&rejection_after)) {
      otis_cx317_active_fault(
          &transaction, "cx323_core0_rejection_controller_transition_failed");
      return false;
    }
#endif
    const bool exact_guard_rejection =
        otis_actuator_guard_discard_exact_rejection(
            &timing_actuator_guard, acknowledgement,
            gnss_metadata_hold_applied_code);
    if (!exact_guard_rejection) {
      // Preserve the established fail-static path for a contradictory tuple.
      (void)otis_actuator_guard_acknowledge(&timing_actuator_guard,
                                             acknowledgement);
      otis_cx317_active_fault(
          &transaction, "gnss_metadata_core0_rejection_identity_mismatch");
      return false;
    }
    const OtisCx317Core0RejectedOutcome rejected = {
        acknowledgement->request_sequence,
        acknowledgement->decision_sequence,
        acknowledgement->authorization_sequence,
        acknowledgement->nonce,
        acknowledgement->requested_code,
        acknowledgement->accepted_code,
        acknowledgement->applied_code,
        true,
        acknowledgement->rejection_reason ==
            OtisActuatorRejectionReason::MetadataHoldCancelledBeforeAcceptance,
        acknowledgement->i2c_ok,
        acknowledgement->clamped,
        acknowledgement->ambiguous,
    };
    if (!otis_cx317_active_discard_released_request_on_metadata_rejection(
            &transaction, &pending_actionable_request,
            &pending_actionable_request_valid, gnss_metadata_hold_active,
            &gnss_metadata_hold_transaction_pending, true,
            gnss_metadata_hold_applied_code, gnss_metadata_hold_dac_epoch,
            &rejected)) {
      otis_cx317_active_fault(
          &transaction, "gnss_metadata_core0_rejection_discard_failed");
      return false;
    }
#if OTIS_ENABLE_CX320_ACTIVE_HYBRID
#if !OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
    pending_hybrid_decision_valid = false;
#endif
#endif
    evidence_phase = EvidencePhase::None;
    evidence_request_sequence = 0u;
    evidence_pending_since_s = 0u;
#if OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
    if (!begin_cx323_evidence_burst(3u) ||
        !queue_frame("request_withdrawn", nullptr, 0.0) ||
        !queue_current_transaction_timing_sidecar(
            "request_withdrawn", rejection_ticks, transaction.reason)) {
      restore_cx323_live_mutation_snapshot(rejection_snapshot);
      otis_cx317_active_fault(
          &transaction, "cx323_core0_rejection_evidence_queue_fault");
      return false;
    }
    const OtisCx323MaintenanceTransactionJoin rejection_join =
        cx323_current_transaction_join(
            OtisCx323MaintenanceTransactionEvent::RequestWithdrawn,
            pending_cx323_observation, pending_cx323_decision, false,
            false);
    if (!queue_cx323_maintenance_record(
            OtisCx323MaintenanceEvent::RequestRejectedOrExpired,
            rejection_ticks, rejection_before, rejection_after,
            &pending_cx323_observation, &pending_cx323_decision,
            &pending_cx323_hybrid_join, &rejection_join, 3u, 3u,
            rejection_after.last_reason) ||
        !commit_cx323_evidence_burst()) {
      restore_cx323_live_mutation_snapshot(rejection_snapshot);
      otis_cx317_active_fault(
          &transaction, "cx323_core0_rejection_burst_commit_failed");
      return false;
    }
    cx323_engine = rejection_after;
    pending_cx323_decision_valid = false;
    pending_cx323_origin_valid = false;
    const OtisCx323Engine hold_before = cx323_engine;
    OtisCx323Engine hold_after = hold_before;
    if (!otis_cx323_engine_enter_metadata_hold(&hold_after) ||
        !queue_cx323_single_async_transition(
            OtisCx323MaintenanceEvent::GnssMetadataHoldEnter,
            rejection_ticks, hold_before, hold_after,
            hold_after.last_reason)) {
      otis_cx317_active_fault(
          &transaction, "cx323_core0_rejection_metadata_hold_evidence_fault");
      return false;
    }
    cx323_engine = hold_after;
#else
    if (!queue_frame("request_withdrawn", nullptr, 0.0)) {
      otis_cx317_active_fault(
          &transaction, "core0_rejection_evidence_queue_fault");
      return false;
    }
#if OTIS_ENABLE_EXACT_LONG_RUN_TIMING_SIDECARS
    if (!queue_current_transaction_timing_sidecar(
            "request_withdrawn", rejection_ticks, transaction.reason)) {
      otis_cx317_active_fault(
          &transaction, "core0_rejection_exact_timing_sidecar_queue_fault");
      return false;
    }
#endif
#endif
    if (transaction.state != OtisCx317ActiveState::Disarmed ||
        transaction.applied_code != gnss_metadata_hold_applied_code ||
        transaction.dac_epoch != gnss_metadata_hold_dac_epoch) {
      otis_cx317_active_fault(
          &transaction, "core0_rejection_withdrawal_identity_changed");
      return false;
    }
    if (!otis_cx317_active_reference_hold(
            &transaction, "gnss_metadata_unqualified_hold") ||
        transaction.applied_code != gnss_metadata_hold_applied_code ||
        transaction.dac_epoch != gnss_metadata_hold_dac_epoch) {
      otis_cx317_active_fault(
          &transaction, "core0_rejection_reference_hold_failed");
      return false;
    }
    return true;
  }
  const bool guard_acknowledged = otis_actuator_guard_acknowledge(
      &timing_actuator_guard, acknowledgement);
  if (acknowledgement->kind == OtisActuatorAckKind::Accepted) {
#if OTIS_ENABLE_EXACT_LONG_RUN_TIMING_SIDECARS
    uint64_t acceptance_ticks = 0u;
    if (!otis_cx317_preview_live_extend_timer0_ticks(
            acknowledgement->acknowledgement_ticks, &acceptance_ticks)) {
      otis_cx317_active_fault(
          &transaction, "core0_acceptance_timestamp_projection_failed");
      return false;
    }
#endif
    if (!guard_acknowledged) {
      otis_cx317_active_fault(
          &transaction, "cross_core_acceptance_acknowledgement_invalid");
      return false;
    }
    OtisCx317AcceptedRequest accepted;
    if (!otis_cx317_active_accept(&transaction,
                                  &pending_actionable_request, now_s,
                                  &accepted))
      return false;
    evidence_phase = EvidencePhase::Acceptance;
    evidence_request_sequence = pending_actionable_request.request_sequence;
    evidence_pending_since_s = now_s;
    if (!queue_frame("core0_accepted", nullptr, 0.0)) {
      otis_cx317_active_fault(&transaction,
                              "acceptance_evidence_queue_fault");
      return false;
    }
#if OTIS_ENABLE_EXACT_LONG_RUN_TIMING_SIDECARS
    if (!queue_current_transaction_timing_sidecar(
            "core0_accepted", acceptance_ticks, transaction.reason)) {
      otis_cx317_active_fault(
          &transaction, "acceptance_exact_timing_sidecar_queue_fault");
      return false;
    }
#endif
    return true;
  }
  if (acknowledgement->kind != OtisActuatorAckKind::Applied) {
    otis_cx317_active_fault(&transaction,
                            "cross_core_actuator_rejected_or_bad_phase");
    return false;
  }
  uint64_t application_ticks = acknowledgement->acknowledgement_ticks;
#if OTIS_ENABLE_ACTIVE_TIMER0_EXTENSION
  if (!otis_cx317_preview_live_extend_timer0_ticks(
          acknowledgement->acknowledgement_ticks, &application_ticks)) {
    otis_cx317_active_fault(
        &transaction, "cross_core_application_timestamp_projection_failed");
    return false;
  }
#endif
  const OtisCx317AppliedAck applied = {
      acknowledgement->request_sequence,
      acknowledgement->authorization_sequence,
      acknowledgement->nonce,
      acknowledgement->requested_code,
      acknowledgement->accepted_code,
      acknowledgement->applied_code,
      pending_actionable_request.correction_ordinal,
      now_s,
      acknowledgement->i2c_ok,
      acknowledgement->clamped,
      acknowledgement->ambiguous,
  };
  const bool transaction_acknowledged =
      otis_cx317_active_acknowledge_application(&transaction, &applied);
  const bool acknowledged = guard_acknowledged && transaction_acknowledged;
  if (!guard_acknowledged)
    otis_cx317_active_fault(
        &transaction, "cross_core_application_acknowledgement_invalid");
  deferred_application_outcome = {};
  deferred_application_outcome.application_attempted = true;
  deferred_application_outcome.request_sequence =
      acknowledgement->request_sequence;
  deferred_application_outcome.dac_epoch = transaction.dac_epoch;
  deferred_application_outcome.application_timestamp_ticks =
      application_ticks;
  deferred_application_outcome.capture_session =
      transaction.expected_binding.session_id;
  deferred_application_outcome.requested_code =
      acknowledgement->requested_code;
  deferred_application_outcome.applied_code = acknowledgement->applied_code;
  deferred_application_outcome.applied = acknowledged;
  deferred_application_outcome.faulted = !acknowledged;
  deferred_application_outcome.reason = transaction.reason;
  deferred_application_outcome_valid = true;
  last_application_acknowledged = acknowledged;
#if OTIS_ENABLE_ACTIVE_TIMER0_EXTENSION
  pending_application_timestamp_ticks =
      application_ticks;
#endif
  if (acknowledged) {
    latest_health.applied_code = transaction.applied_code;
    latest_health.applied_code_confirmed = true;
  }
  pending_actionable_request_valid = false;
  evidence_phase = EvidencePhase::Application;
  evidence_pending_since_s = now_s;
  return acknowledged;
#else
  (void)acknowledgement;
  (void)now_s;
  return false;
#endif
}

bool otis_cx317_active_live_manual_start_allowed(uint16_t code) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  return initialized && code == OTIS_CX317_ACTIVE_START_CODE &&
         !manual_start_confirmed &&
#if OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
         transaction_bound &&
#endif
         (!transaction_bound ||
          (transaction.state == OtisCx317ActiveState::Disarmed &&
           transaction.correction_count == 0u && !transaction.have_request));
#else
  (void)code;
  return true;
#endif
}

void otis_cx317_active_live_note_manual_start(uint16_t code, bool i2c_ok,
                                              uint32_t now_s) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (!otis_cx317_active_live_manual_start_allowed(code) || !i2c_ok) {
    if (transaction_bound)
      otis_cx317_active_fault(&transaction, "manual_start_establishment_failed");
    queue_manual_start_frame(code, false, now_s);
    return;
  }
  manual_start_confirmed = true;
  periodic_applied_code_confirmation_seen = false;
  if (transaction_bound) {
    transaction.applied_code = code;
#if OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
    transaction.dac_epoch = 1u;
    transaction.last_application_s = now_s;
    transaction.have_last_application = true;
#endif
  }
  if (!queue_manual_start_frame(code, true, now_s) && transaction_bound)
    otis_cx317_active_fault(&transaction, "manual_start_evidence_queue_fault");
#else
  (void)code;
  (void)i2c_ok;
  (void)now_s;
#endif
}

bool otis_cx317_active_live_note_manual_start_timing(
    uint16_t applied_code, uint32_t dac_epoch,
    uint64_t setup_application_ticks, uint32_t capture_session) {
#if OTIS_ENABLE_EXACT_LONG_RUN_TIMING_SIDECARS
  if (!initialized || !transaction_bound || !manual_start_confirmed ||
      manual_start_timing_recorded || transaction_record_sequence == 0u ||
      capture_session == 0u ||
      capture_session != transaction.expected_binding.session_id ||
      applied_code != transaction.applied_code || dac_epoch == 0u ||
      dac_epoch != transaction.dac_epoch)
    return false;
  if (!queue_transaction_timing_sidecar(
          "manual_start", setup_application_ticks,
          transaction_record_sequence, capture_session, 0u, 0u, 0u, 0u, 0u,
          0u, applied_code, applied_code, 0u, dac_epoch,
          "manual_start_established"))
    return false;
  manual_start_timing_recorded = true;
  return true;
#else
  (void)applied_code;
  (void)dac_epoch;
  (void)setup_application_ticks;
  (void)capture_session;
  return true;
#endif
}

bool otis_cx317_active_live_confirm_setup_consumers(uint16_t applied_code,
                                                    uint32_t dac_epoch) {
#if OTIS_ENABLE_CX320_ACTIVE_HYBRID
#if OTIS_ENABLE_CX32X_EXACT_ACTIVE_TIMING
  (void)applied_code;
  (void)dac_epoch;
  if (transaction_bound)
    otis_cx317_active_fault(
        &transaction, "active_hybrid_setup_requires_exact_application_ticks");
  return false;
#else
  if (!transaction_bound || !manual_start_confirmed ||
      !transaction.have_last_application ||
      applied_code != OTIS_CX317_ACTIVE_START_CODE || dac_epoch != 1u ||
      transaction.applied_code != applied_code ||
      transaction.dac_epoch != dac_epoch ||
      !otis_cx317_preview_live_applied_epoch_exact(applied_code, dac_epoch)) {
    if (transaction_bound)
      otis_cx317_active_fault(
          &transaction, "active_hybrid_setup_consumer_epoch_mismatch");
    return false;
  }
  OtisPhasePreviewLiveStatus phase = {};
  otis_phase_preview_live_get_status(&phase);
  if (!phase.initialized || !phase.applied_code_bound ||
      phase.applied_code != applied_code || phase.dac_epoch != dac_epoch) {
    otis_cx317_active_fault(
        &transaction, "active_hybrid_setup_phase_epoch_mismatch");
    return false;
  }
  otis_active_hybrid_engine_init(&hybrid_engine,
                                 transaction.last_application_s);
  hybrid_engine_ready = true;
  return true;
#endif
#else
  (void)applied_code;
  (void)dac_epoch;
  return true;
#endif
}

bool otis_cx317_active_live_confirm_setup_consumers_exact(
    uint16_t applied_code, uint32_t dac_epoch,
    uint64_t setup_application_ticks, uint32_t capture_session) {
#if OTIS_ENABLE_CX32X_EXACT_ACTIVE_TIMING
  if (!transaction_bound || !manual_start_confirmed ||
      !transaction.have_last_application || setup_application_ticks == 0u ||
      capture_session != transaction.expected_binding.session_id ||
      applied_code != OTIS_CX317_ACTIVE_START_CODE || dac_epoch != 1u ||
      transaction.applied_code != applied_code ||
      transaction.dac_epoch != dac_epoch ||
      !otis_cx317_preview_live_applied_epoch_exact(applied_code, dac_epoch)) {
    if (transaction_bound)
      otis_cx317_active_fault(
          &transaction, "active_hybrid_setup_consumer_epoch_or_tick_mismatch");
    return false;
  }
  OtisPhasePreviewLiveStatus phase = {};
  otis_phase_preview_live_get_status(&phase);
  if (!phase.initialized || !phase.applied_code_bound ||
      phase.applied_code != applied_code || phase.dac_epoch != dac_epoch) {
    otis_cx317_active_fault(&transaction,
                            "active_hybrid_setup_phase_epoch_mismatch");
    return false;
  }
  setup_application_timestamp_ticks = setup_application_ticks;
  transaction.last_application_s = static_cast<uint32_t>(
      setup_application_ticks / kCaptureTicksPerSecond);
#if OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
  const OtisCx323Policy cx323_policy = otis_cx323_default_policy();
  cx323_engine = {};
  if (!otis_cx323_engine_init(
          &cx323_engine, &cx323_policy, applied_code, dac_epoch)) {
    otis_cx317_active_fault(&transaction,
                            "cx323_setup_controller_initialization_failed");
    return false;
  }
  if (!otis_cx323_engine_bind_exact_setup_application(
          &cx323_engine, setup_application_ticks)) {
    otis_cx317_active_fault(
        &transaction, "cx323_setup_application_binding_failed");
    return false;
  }
  const OtisCx323Engine activation_before = cx323_engine;
  OtisCx323Engine activation_after = activation_before;
  if (!otis_cx323_engine_new_policy_activation(&activation_after) ||
      !begin_cx323_evidence_burst(1u) ||
      !queue_cx323_maintenance_record(
          OtisCx323MaintenanceEvent::PolicyActivation,
          setup_application_ticks, activation_before, activation_after,
          nullptr, nullptr, nullptr, nullptr, 1u, 1u,
          activation_after.last_reason) ||
      !commit_cx323_evidence_burst()) {
    abandon_cx323_evidence_burst();
    otis_cx317_active_fault(
        &transaction, "cx323_policy_activation_evidence_queue_fault");
    return false;
  }
  cx323_engine = activation_after;
  cx323_engine_ready = true;
  hybrid_engine = {};
  hybrid_engine_ready = false;
#elif OTIS_ENABLE_CX321_ACTIVE_HYBRID
  otis_cx321_plant_sign_engine_init(&plant_sign_engine);
  plant_sign_engine_ready = true;
  hybrid_engine = {};
  hybrid_engine_ready = false;
#else
  otis_active_hybrid_engine_init_at_ticks(&hybrid_engine,
                                          setup_application_ticks);
  hybrid_engine_ready = true;
#endif
  return true;
#else
  (void)setup_application_ticks;
  (void)capture_session;
  return otis_cx317_active_live_confirm_setup_consumers(applied_code,
                                                        dac_epoch);
#endif
}

#if OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
static void cx323_active_live_on_decision_impl(
    const OtisCx317ActiveLiveDecision &source,
    uint64_t decision_timestamp_ticks,
    OtisCx317ActiveLiveOutcome *outcome) {
  if (!cx323_engine_ready) {
    otis_cx317_active_fault(
        &transaction, "cx323_setup_consumers_not_confirmed");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  if (decision_timestamp_ticks == 0u ||
      source.timestamp_s !=
          decision_timestamp_ticks / kCaptureTicksPerSecond) {
    otis_cx317_active_fault(
        &transaction, "cx323_decision_timestamp_domain_mismatch");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }

  OtisCx317ActiveEligibility health = eligibility(source.timestamp_s);
  health.estimator_valid = source.measurement_valid;
  health.model_applicable = source.model_applicable;
  const bool completing_response =
      transaction.state == OtisCx317ActiveState::AwaitingResponse;
  if (completing_response) {
    // Metadata qualifies admission of a new correction. It cannot erase the
    // exact D14/D8 response needed to close an already applied transaction.
    health.gnss_metadata_valid = true;
    health.gnss_identity_stable = true;
    health.gnss_3d_evidence = true;
  }
  const bool phase_valid =
      source.phase_recorder_published && source.phase_continuous &&
      source.phase_current && !source.phase_step_detected &&
      source.phase_dac_epoch == source.dac_epoch &&
      source.phase_applied_code == source.current_applied_code;
  const bool metadata_qualified =
      completing_response ||
      (health.gnss_metadata_valid && health.gnss_identity_stable &&
       health.gnss_3d_evidence);
  const bool authority_valid =
      strcmp(OTIS_BUILD_PROFILE_ID, kExpectedProfile) == 0 &&
      source.capture_session == transaction.expected_binding.session_id &&
      source.measurement_valid && source.model_applicable &&
      health.raw_pps_valid && health.count_valid &&
      health.applied_code_confirmed &&
      latest_health.applied_code == source.current_applied_code &&
      health.capture_owner_live && health.abort_path_live &&
      latest_health.reference_integrity_valid;

  OtisCx323Observation observation = {};
  observation.timestamp_s = source.timestamp_s;
  observation.capture_session = source.capture_session;
  observation.source_first_sequence = source.source_first_sequence;
  observation.source_last_sequence = source.source_last_sequence;
  observation.dac_epoch = source.dac_epoch;
  observation.applied_code = source.current_applied_code;
  observation.accumulated_edge_error_counts =
      source.accumulated_edge_error_counts;
  observation.tight_inside =
      source.tight_state != nullptr &&
      strcmp(source.tight_state, "TIGHT_INSIDE") == 0;
  observation.phase_epoch = source.phase_epoch;
  observation.relative_phase_cycles = source.relative_phase_cycles;
  observation.selected_estimator_identity =
      kCx323SelectedEstimatorIdentity;
  observation.phase_valid = phase_valid;
  observation.authority_valid = authority_valid;
  observation.settled = source.preview_available;
  observation.cadence_eligible =
      transaction.state == OtisCx317ActiveState::Armed &&
      !(gnss_metadata_hold_active && cx323_engine.metadata_requalified);
  observation.metadata_qualified = metadata_qualified;
  observation.timestamp_ticks = decision_timestamp_ticks;

  const OtisCx323Engine engine_before = cx323_engine;
  OtisCx323Engine engine_after = engine_before;
  OtisCx323Decision native_decision = {};
  if (!otis_cx323_engine_decide(
          &engine_after, &observation, &native_decision)) {
    otis_cx317_active_fault(&transaction,
                            "cx323_native_decision_failed");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }

  const bool native_fail_transition =
      engine_before.fail_static_reason == nullptr &&
      engine_after.fail_static_reason != nullptr;
  const bool request_producing_decision =
      native_decision.requested_delta_codes != 0;
  // An AwaitingResponse transaction deliberately makes cadence_eligible
  // false above.  It may close the pending response on this boundary, but it
  // must not create the next request in the same producer frontier.
  if (completing_response && request_producing_decision) {
    otis_cx317_active_fault(
        &transaction, "cx323_response_and_request_overlap_fault");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  if (request_producing_decision !=
      (!engine_before.request_pending && engine_after.request_pending)) {
    otis_cx317_active_fault(&transaction,
                            "cx323_request_transition_invariant_fault");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  const uint8_t decision_burst_count =
      request_producing_decision
          ? OTIS_CX323_REQUEST_DECISION_EVIDENCE_COUNT
          : OTIS_CX323_RESPONSE_DECISION_EVIDENCE_COUNT;
  // A native fail transition is terminal at this boundary and returns before
  // response completion below.  These follow-up bursts are therefore
  // mutually exclusive by control flow, not merely by observed history.
  const uint8_t followup_burst_count =
      native_fail_transition
          ? OTIS_CX323_FAIL_TRANSITION_EVIDENCE_COUNT
          : (completing_response
                 ? OTIS_CX323_RESPONSE_COMPLETION_EVIDENCE_COUNT
                 : 0u);
  const uint8_t total_capacity = static_cast<uint8_t>(
      decision_burst_count + followup_burst_count);
  // Preview has already queued this boundary's three-record prefix.  Reserve
  // the active lifecycle and its guaranteed trailing CTL before committing
  // any part of the lifecycle, so queue pressure cannot reproduce Attempt 7's
  // complete request followed by a missing CTL.
  const uint8_t required_capacity = static_cast<uint8_t>(
      total_capacity + OTIS_CX323_SELECTED_EVIDENCE_SUFFIX_COUNT);
  if (required_capacity > OTIS_EVIDENCE_QUEUE_DEPTH ||
      !otis_dual_core_evidence_can_publish(required_capacity)) {
    otis_dual_core_latch_fault(OtisPartitionFault::EvidenceExhausted);
    otis_cx317_active_fault(&transaction,
                            "cx323_combined_evidence_capacity_fault");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }

  const Cx323LiveMutationSnapshot decision_snapshot =
      capture_cx323_live_mutation_snapshot();
  OtisCx317ActiveLiveDecision projected_source = source;
  projected_source.decision_sequence =
      static_cast<uint32_t>(native_decision.decision_sequence);
  projected_source.requested_delta_codes =
      native_decision.requested_delta_codes;
  projected_source.requested_code =
      static_cast<uint16_t>(native_decision.requested_code);
  projected_source.control_eligible =
      request_producing_decision;
  projected_source.preview_available = true;
  const OtisActiveHybridDecision projected_decision =
      cx323_project_hybrid_decision(
          engine_before, engine_after, native_decision, phase_valid,
          source.timestamp_s);

  if (!begin_cx323_evidence_burst(decision_burst_count) ||
      !queue_active_hybrid_decision(
          projected_source, projected_decision,
          decision_timestamp_ticks)) {
    restore_cx323_live_mutation_snapshot(decision_snapshot);
    otis_cx317_active_fault(&transaction,
                            "cx323_decision_evidence_queue_fault");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  const OtisCx323MaintenanceHybridJoin hybrid_join =
      cx323_current_hybrid_join(
          observation, native_decision,
          source.phase_observation_sequence);

  OtisCx323MaintenanceTransactionJoin request_join = {};
  const OtisCx323MaintenanceTransactionJoin *request_join_pointer = nullptr;
  const OtisCx317ActiveDecision request_input = {
      projected_source.decision_sequence,
      projected_source.source_first_sequence,
      projected_source.source_last_sequence,
      projected_source.timestamp_s,
      projected_source.current_applied_code,
      projected_source.requested_delta_codes,
      projected_source.requested_code,
      projected_source.frequency_error_hz,
  };
  if (request_producing_decision) {
    OtisCx317ActionableRequest request = {};
    if (transaction.state != OtisCx317ActiveState::Armed ||
        !otis_cx317_active_make_request(
            &transaction, &request_input, &health,
            source.timestamp_s, &request)) {
      restore_cx323_live_mutation_snapshot(decision_snapshot);
      otis_cx317_active_fault(&transaction,
                              "cx323_transaction_request_creation_failed");
      outcome->faulted = true;
      outcome->reason = transaction.reason;
      return;
    }
    pending_actionable_request = request;
    pending_actionable_request_valid = true;
    evidence_phase = EvidencePhase::Request;
    evidence_request_sequence = request.request_sequence;
    evidence_pending_since_s = source.timestamp_s;
    if (!queue_frame("request_created", nullptr, 0.0) ||
        !queue_current_transaction_timing_sidecar(
            "request_created", decision_timestamp_ticks,
            transaction.reason)) {
      restore_cx323_live_mutation_snapshot(decision_snapshot);
      otis_cx317_active_fault(&transaction,
                              "cx323_request_evidence_queue_fault");
      outcome->faulted = true;
      outcome->reason = transaction.reason;
      return;
    }
    request_join = cx323_current_transaction_join(
        OtisCx323MaintenanceTransactionEvent::RequestCreated,
        observation, native_decision, false, false);
    request_join_pointer = &request_join;
  } else if (transaction.state == OtisCx317ActiveState::Armed) {
    OtisCx317ActionableRequest unused = {};
    const bool unexpected_request = otis_cx317_active_make_request(
        &transaction, &request_input, &health, source.timestamp_s,
        &unused);
    if (unexpected_request ||
        transaction.state != OtisCx317ActiveState::Disarmed) {
      restore_cx323_live_mutation_snapshot(decision_snapshot);
      otis_cx317_active_fault(
          &transaction, "cx323_zero_delta_arm_consumption_failed");
      outcome->faulted = true;
      outcome->reason = transaction.reason;
      return;
    }
  }

  if (!queue_cx323_maintenance_record(
          OtisCx323MaintenanceEvent::Decision,
          decision_timestamp_ticks, engine_before, engine_after,
          &observation, &native_decision, &hybrid_join,
          request_join_pointer, decision_burst_count,
          decision_burst_count, native_decision.reason) ||
      !commit_cx323_evidence_burst()) {
    restore_cx323_live_mutation_snapshot(decision_snapshot);
    otis_cx317_active_fault(&transaction,
                            "cx323_decision_burst_commit_failed");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }

  cx323_engine = engine_after;
  last_cx323_observation = observation;
  last_cx323_decision = native_decision;
  last_cx323_hybrid_join = hybrid_join;
  last_cx323_origin_valid = true;
  if (engine_before.metadata_hold && !engine_after.metadata_hold) {
    if (!gnss_metadata_hold_active ||
        engine_before.requalification_window_count != 1u ||
        engine_after.requalification_window_count != 2u ||
        transaction.state != OtisCx317ActiveState::ReferenceHold ||
        !otis_cx317_active_reference_requalify(
            &transaction, transaction.expected_binding.session_id)) {
      otis_cx317_active_fault(
          &transaction, "cx323_metadata_two_window_release_failed");
      outcome->faulted = true;
      outcome->reason = transaction.reason;
      return;
    }
    gnss_metadata_hold_active = false;
    gnss_metadata_hold_transaction_pending = false;
  }
  if (request_producing_decision) {
    pending_cx323_decision = native_decision;
    pending_cx323_decision_valid = true;
    pending_cx323_observation = observation;
    pending_cx323_hybrid_join = hybrid_join;
    pending_cx323_origin_valid = true;
    outcome->request_created = true;
    outcome->request_sequence = transaction.request.request_sequence;
    outcome->requested_code = transaction.request.requested_code;
    outcome->applied_code = transaction.applied_code;
  }
  outcome->reason = native_decision.reason;

  if (native_fail_transition) {
    const Cx323LiveMutationSnapshot fail_snapshot =
        capture_cx323_live_mutation_snapshot();
    if (!begin_cx323_evidence_burst(1u) ||
        !queue_cx323_maintenance_record(
            OtisCx323MaintenanceEvent::FailStatic,
            decision_timestamp_ticks, engine_before, engine_after,
            &observation, &native_decision, &hybrid_join, nullptr,
            1u, 1u, engine_after.fail_static_reason) ||
        !commit_cx323_evidence_burst()) {
      restore_cx323_live_mutation_snapshot(fail_snapshot);
      otis_cx317_active_fault(&transaction,
                              "cx323_fail_static_evidence_queue_fault");
      outcome->faulted = true;
      outcome->reason = transaction.reason;
      return;
    }
    const bool controller_inhibit =
        strcmp(engine_after.fail_static_reason,
               "prospective_repeated_alternation") == 0 ||
        strcmp(engine_after.fail_static_reason,
               "prospective_low_efficiency_path") == 0;
    if (!controller_inhibit) {
      otis_cx317_active_fault(&transaction,
                              engine_after.fail_static_reason);
      outcome->faulted = true;
      outcome->reason = transaction.reason;
    }
    return;
  }

  if (!completing_response) return;
  if (!pending_cx323_origin_valid ||
      !cx323_engine.response_pending) {
    otis_cx317_active_fault(
        &transaction, "cx323_response_origin_or_state_missing");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }

  const Cx323LiveMutationSnapshot response_snapshot =
      capture_cx323_live_mutation_snapshot();
  const OtisCx323Engine response_before = cx323_engine;
  OtisCx323Engine response_after = response_before;
  OtisCx317ResponseResult response = {};
  const bool measurement_healthy =
      source.measurement_valid &&
      otis_cx317_active_response_measurement_valid(&health);
  const bool response_accepted = otis_cx317_active_record_response(
      &transaction, source.frequency_error_hz, measurement_healthy,
      otis_cx317_active_eligibility_valid(&health), &response);
  if (!response_accepted ||
      !otis_cx323_engine_complete_response(&response_after, true)) {
    restore_cx323_live_mutation_snapshot(response_snapshot);
    otis_cx317_active_fault(
        &transaction, "cx323_response_checkpoint_failed");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  evidence_phase = EvidencePhase::Response;
  evidence_request_sequence = transaction.request.request_sequence;
  evidence_pending_since_s = source.timestamp_s;
  if (!begin_cx323_evidence_burst(3u) ||
      !queue_frame("response", &response, source.frequency_error_hz) ||
      !queue_current_transaction_timing_sidecar(
          "response", decision_timestamp_ticks, response.reason)) {
    restore_cx323_live_mutation_snapshot(response_snapshot);
    otis_cx317_active_fault(&transaction,
                            "cx323_response_evidence_queue_fault");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  const OtisCx323MaintenanceTransactionJoin response_join =
      cx323_current_transaction_join(
          OtisCx323MaintenanceTransactionEvent::Response,
          pending_cx323_observation, pending_cx323_decision, true, true);
  if (!queue_cx323_maintenance_record(
          OtisCx323MaintenanceEvent::ResponseComplete,
          decision_timestamp_ticks, response_before, response_after,
          &pending_cx323_observation, &pending_cx323_decision,
          &pending_cx323_hybrid_join, &response_join, 3u, 3u,
          response_after.last_reason) ||
      !commit_cx323_evidence_burst()) {
    restore_cx323_live_mutation_snapshot(response_snapshot);
    otis_cx317_active_fault(&transaction,
                            "cx323_response_burst_commit_failed");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  cx323_engine = response_after;
  pending_cx323_decision_valid = false;
  pending_cx323_origin_valid = false;
  outcome->response_recorded = true;
  outcome->response_class = response.classification;
  outcome->reason = response.reason;
}
#endif

static void active_live_on_decision_impl(
    const OtisCx317ActiveLiveDecision *decision,
    bool decision_ticks_available, uint64_t decision_timestamp_ticks,
    OtisCx317ActiveLiveOutcome *outcome) {
  if (outcome != nullptr) *outcome = {};
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (!initialized || !transaction_bound || decision == nullptr ||
      outcome == nullptr)
    return;
#if OTIS_ENABLE_EXACT_LONG_RUN_TIMING_SIDECARS
  if (!decision_ticks_available) {
    otis_cx317_active_fault(
        &transaction, "exact_long_run_decision_timestamp_unavailable");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
#endif
#if OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
  cx323_active_live_on_decision_impl(
      *decision, decision_timestamp_ticks, outcome);
  return;
#endif
  outcome->reason = transaction.reason;
  OtisCx317ActiveEligibility health = eligibility(decision->timestamp_s);
  // The completed selected estimate is created in this boundary callback;
  // the periodic health snapshot necessarily trails it by one service loop.
  health.estimator_valid = decision->measurement_valid;
  health.model_applicable = decision->model_applicable;
  const bool completing_response_during_metadata_hold =
      gnss_metadata_hold_active &&
      transaction.state == OtisCx317ActiveState::AwaitingResponse;
  if (completing_response_during_metadata_hold) {
    // Metadata qualifies admission of a new correction, not the canonical
    // D14/D8 observation needed to finish an already applied transaction.
    health.gnss_metadata_valid = true;
    health.gnss_identity_stable = true;
    health.gnss_3d_evidence = true;
  } else if (gnss_metadata_hold_active) {
    outcome->reason = "gnss_metadata_hold_no_new_request";
    return;
  }
  const OtisCx317ActiveLiveDecision *effective_decision = decision;
#if OTIS_ENABLE_CX320_ACTIVE_HYBRID
  OtisCx317ActiveLiveDecision hybrid_source = *decision;
  OtisActiveHybridDecision hybrid_decision = {};
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
  if (!dispatching_plant_sign_request && !hybrid_engine_ready) {
    outcome->reason = plant_sign_engine.reason;
    return;
  }
  const OtisActiveHybridState hybrid_state_before = hybrid_engine.state;
  if (!dispatching_plant_sign_request) {
#endif
  if (!hybrid_engine_ready) {
    otis_cx317_active_fault(
        &transaction, "active_hybrid_setup_consumers_not_confirmed");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  const bool common_health_clean =
      decision->measurement_valid && decision->model_applicable &&
      (completing_response_during_metadata_hold ||
       (health.gnss_metadata_valid && health.gnss_identity_stable &&
        health.gnss_3d_evidence)) &&
      health.raw_pps_valid && health.count_valid &&
      health.applied_code_confirmed && health.capture_owner_live &&
      health.abort_path_live && latest_health.reference_integrity_valid &&
      decision->phase_recorder_published;
  const bool downstream_phase_epoch_exact =
      decision->phase_recorder_published &&
      decision->phase_dac_epoch == decision->dac_epoch &&
      decision->phase_applied_code == decision->current_applied_code;
  const OtisActiveHybridObservation hybrid_input = {
      decision->timestamp_s,
      decision->capture_session,
      decision->source_first_sequence,
      decision->source_last_sequence,
      decision->dac_epoch,
      decision->current_applied_code,
      decision->frequency_error_hz,
      decision->accumulated_edge_error_counts,
      decision->tight_state,
      decision->phase_epoch,
      decision->phase_observation_sequence,
      decision->relative_phase_cycles,
      decision->phase_dac_epoch,
      decision->phase_applied_code,
      decision->phase_continuous,
      decision->phase_current,
      decision->phase_step_detected,
      strcmp(OTIS_BUILD_PROFILE_ID, kExpectedProfile) == 0 &&
          decision->capture_session ==
              transaction.expected_binding.session_id,
      common_health_clean,
      downstream_phase_epoch_exact,
      hybrid_engine.transaction_outstanding,
      transaction.state == OtisCx317ActiveState::AwaitingResponse,
  };
  const bool hybrid_decided =
#if OTIS_ENABLE_CX32X_EXACT_ACTIVE_TIMING
      decision_ticks_available &&
      otis_active_hybrid_engine_decide_at_ticks(
          &hybrid_engine, &hybrid_input, decision_timestamp_ticks,
          &hybrid_decision);
#else
      otis_active_hybrid_engine_decide(
          &hybrid_engine, &hybrid_input, &hybrid_decision);
#endif
  if (!hybrid_decided) {
    hybrid_fail_static("active_hybrid_decision_timing_or_input_fault");
    otis_cx317_active_fault(
        &transaction, "active_hybrid_decision_timing_or_input_fault");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  if (!queue_active_hybrid_decision(*decision, hybrid_decision,
                                    decision_timestamp_ticks)) {
    hybrid_fail_static("active_hybrid_decision_evidence_queue_fault");
    otis_cx317_active_fault(
        &transaction, "active_hybrid_decision_evidence_queue_fault");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  if (hybrid_engine.state == OtisActiveHybridState::FailStatic) {
    otis_cx317_active_fault(&transaction, hybrid_decision.reason);
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
  if (plant_sign_handoff_pending) {
    if (!queue_plant_sign_frame(
            "handoff", decision_timestamp_ticks,
            otis_active_hybrid_state_name(hybrid_state_before),
            otis_active_hybrid_state_name(hybrid_engine.state),
            "plant_sign_first_natural_consumer_handoff_exact", nullptr,
            nullptr)) {
      hybrid_fail_static("plant_sign_first_consumer_evidence_queue_fault");
      otis_cx317_active_fault(
          &transaction, "plant_sign_first_consumer_evidence_queue_fault");
      outcome->faulted = true;
      outcome->reason = transaction.reason;
      return;
    }
    plant_sign_handoff_pending = false;
    pending_response_psq_record_sequence = 0u;
  }
#endif
  hybrid_source.decision_sequence = hybrid_decision.decision_sequence;
  hybrid_source.requested_delta_codes =
      hybrid_decision.requested_delta_codes;
  hybrid_source.requested_code = hybrid_decision.requested_code;
  hybrid_source.control_eligible =
      hybrid_decision.requested_delta_codes != 0;
  hybrid_source.preview_available = true;
  effective_decision = &hybrid_source;
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
  }
#endif
#endif
  if (transaction.state == OtisCx317ActiveState::AwaitingResponse) {
    OtisCx317ResponseResult response;
    const bool measurement_healthy =
        decision->measurement_valid &&
        otis_cx317_active_response_measurement_valid(&health);
    // A selected response can arrive while the preview engine is still in its
    // post-DAC SETTLE_PREVIEW state.  preview actionability gates a new request,
    // not acceptance of an already-completed response.  The full live health
    // and model-applicability contract is the post-response eligibility gate.
    const bool control_eligible_after_response =
        otis_cx317_active_eligibility_valid(&health);
    const bool accepted = otis_cx317_active_record_response(
        &transaction, decision->frequency_error_hz,
        measurement_healthy, control_eligible_after_response,
        &response);
    outcome->response_recorded = true;
    outcome->response_class = response.classification;
    outcome->reason = response.reason;
    outcome->faulted = !accepted;
    evidence_phase = EvidencePhase::Response;
    evidence_request_sequence = transaction.request.request_sequence;
    evidence_pending_since_s = decision->timestamp_s;
#if OTIS_ENABLE_CX320_ACTIVE_HYBRID
    pending_hybrid_response_class = response.classification;
    pending_hybrid_response_valid = true;
    pending_hybrid_predicted_sign_observed =
        response.observed_response_hz *
            static_cast<double>(transaction.request.requested_delta_codes) >
        0.0;
#endif
    if (!queue_frame("response", &response, decision->frequency_error_hz)) {
      otis_cx317_active_fault(&transaction, "response_evidence_queue_fault");
      outcome->faulted = true;
      outcome->reason = transaction.reason;
    }
#if OTIS_ENABLE_EXACT_LONG_RUN_TIMING_SIDECARS
    else if (!queue_current_transaction_timing_sidecar(
                 "response", decision_timestamp_ticks, response.reason)) {
      otis_cx317_active_fault(
          &transaction, "response_exact_timing_sidecar_queue_fault");
      outcome->faulted = true;
      outcome->reason = transaction.reason;
    }
#endif
    return;
  }
  if (transaction.state != OtisCx317ActiveState::Armed) return;
  const OtisCx317ActiveDecision request_input = {
      effective_decision->decision_sequence,
      effective_decision->source_first_sequence,
      effective_decision->source_last_sequence,
      effective_decision->timestamp_s,
      effective_decision->current_applied_code,
      effective_decision->requested_delta_codes,
      effective_decision->requested_code,
      effective_decision->frequency_error_hz,
  };
  OtisCx317ActionableRequest request;
#if OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
  // A short-lived arm is issued before the next 600 s observation is known.
  // If that observation enters or retains the tight band, the Stage 5 engine
  // emits an exact zero-delta hold.  Consume the one-shot arm by passing that
  // zero through the transaction guard, which disarms without producing a
  // request.  A non-zero ineligible delta would be authority contamination.
  if (!effective_decision->control_eligible &&
      effective_decision->requested_delta_codes != 0) {
    otis_cx317_active_fault(
        &transaction, "tight_deadband_ineligible_nonzero_delta");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  const bool request_created = otis_cx317_active_make_request(
      &transaction, &request_input, &health,
      effective_decision->timestamp_s, &request);
  if (!request_created) {
    outcome->faulted = transaction.state == OtisCx317ActiveState::Fault;
    outcome->reason = transaction.reason;
    return;
  }
#else
  if (!effective_decision->control_eligible ||
      !otis_cx317_active_make_request(&transaction, &request_input, &health,
                                      effective_decision->timestamp_s,
                                      &request)) {
    outcome->faulted = transaction.state == OtisCx317ActiveState::Fault;
    outcome->reason = transaction.reason;
    return;
  }
#endif
  OtisCx317AcceptedRequest accepted;
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  pending_actionable_request = request;
  pending_actionable_request_valid = true;
#else
  if (!otis_cx317_active_accept(&transaction, &request,
                                effective_decision->timestamp_s, &accepted)) {
    outcome->faulted = true;
    outcome->reason = transaction.reason;
    return;
  }
  pending_actionable_request = request;
  pending_actionable_request_valid = true;
#endif
  estimator_history_reset = false;
#if OTIS_ENABLE_CX320_ACTIVE_HYBRID
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
  if (!dispatching_plant_sign_request) {
#endif
  pending_hybrid_decision = hybrid_decision;
  pending_hybrid_decision_valid = true;
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
  }
#endif
#endif
  outcome->request_created = true;
  outcome->request_sequence = request.request_sequence;
  outcome->requested_code = request.requested_code;
  outcome->applied_code = transaction.applied_code;
  outcome->applied = false;
  outcome->faulted = false;
  outcome->reason = transaction.reason;
  evidence_phase = EvidencePhase::Request;
  evidence_request_sequence = request.request_sequence;
  evidence_pending_since_s = effective_decision->timestamp_s;
  if (!queue_frame(
#if OTIS_ENABLE_DUAL_CORE_PARTITION
          "request_created",
#else
          "request_accepted",
#endif
          nullptr, 0.0)) {
    pending_actionable_request_valid = false;
    otis_cx317_active_fault(&transaction, "request_evidence_queue_fault");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
  }
#if OTIS_ENABLE_EXACT_LONG_RUN_TIMING_SIDECARS
  else if (!queue_current_transaction_timing_sidecar(
#if OTIS_ENABLE_DUAL_CORE_PARTITION
               "request_created",
#else
               "request_accepted",
#endif
               decision_timestamp_ticks, transaction.reason)) {
    pending_actionable_request_valid = false;
    otis_cx317_active_fault(
        &transaction, "request_exact_timing_sidecar_queue_fault");
    outcome->faulted = true;
    outcome->reason = transaction.reason;
  }
#endif
#else
  (void)decision;
  (void)decision_ticks_available;
  (void)decision_timestamp_ticks;
#endif
}

void otis_cx317_active_live_on_decision(
    const OtisCx317ActiveLiveDecision *decision,
    OtisCx317ActiveLiveOutcome *outcome) {
  active_live_on_decision_impl(decision, false, 0u, outcome);
}

void otis_cx317_active_live_on_decision_at_ticks(
    const OtisCx317ActiveLiveDecision *decision,
    uint64_t decision_timestamp_ticks, OtisCx317ActiveLiveOutcome *outcome) {
  active_live_on_decision_impl(decision, true, decision_timestamp_ticks,
                               outcome);
}

void otis_cx317_active_live_on_plant_sign_estimate(
    const OtisCx321PlantSignEstimate *estimate, uint16_t current_applied_code,
    bool latest_natural_tight_inside, uint64_t event_timestamp_ticks,
    uint32_t now_s, OtisCx317ActiveLiveOutcome *outcome) {
  if (outcome != nullptr) *outcome = {};
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
  if (!initialized || !transaction_bound || !plant_sign_engine_ready ||
      estimate == nullptr || outcome == nullptr)
    return;
  const OtisCx317ActiveEligibility current = eligibility(now_s);
  const bool common_evidence_exact =
      otis_cx317_active_eligibility_valid(&current) &&
      estimate->capture_session == transaction.expected_binding.session_id &&
      current_applied_code == transaction.applied_code &&
      event_timestamp_ticks == estimate->close_ticks;
  if (plant_sign_engine.state == OtisCx321PlantSignState::FrequencyAcquire) {
    const OtisCx321PlantSignState state_before = plant_sign_engine.state;
    const uint8_t pre_window_count_before =
        plant_sign_engine.pre_window_count;
    OtisCx321PlantSignDecision identification = {};
    const bool request_ready = otis_cx321_plant_sign_engine_on_pre_estimate(
        &plant_sign_engine, estimate, current_applied_code,
        transaction.dac_epoch, transaction.correction_count,
        latest_natural_tight_inside, common_evidence_exact, &identification);
    const char *pre_event = pre_window_count_before == 0u ? "pre1" : "pre2";
    if (!queue_plant_sign_frame(
            pre_event, event_timestamp_ticks,
            otis_cx321_plant_sign_state_name(state_before),
            otis_cx321_plant_sign_state_name(plant_sign_engine.state),
            plant_sign_engine.reason, estimate,
            latest_natural_tight_inside ? "TIGHT_INSIDE" : "TIGHT_OUTSIDE")) {
      otis_cx317_active_fault(&transaction,
                              "plant_sign_pre_evidence_queue_fault");
      outcome->faulted = true;
      outcome->reason = transaction.reason;
      return;
    }
    if (!request_ready) {
      if (plant_sign_engine.state == OtisCx321PlantSignState::NotExercised) {
        otis_cx317_active_fault(&transaction,
                                "plant_sign_qualification_not_exercised");
        outcome->faulted = true;
      } else if (plant_sign_engine.state ==
                 OtisCx321PlantSignState::FailStatic) {
        otis_cx317_active_fault(&transaction, plant_sign_engine.reason);
        outcome->faulted = true;
      }
      outcome->reason = plant_sign_engine.reason;
      return;
    }
    const OtisCx317ActiveLiveDecision request = {
        identification.decision_sequence,
        identification.source_first_sequence,
        identification.source_last_sequence,
        now_s,
        identification.current_code,
        identification.requested_delta_codes,
        identification.requested_code,
        static_cast<double>(identification.pre_error_counts) / 1500.0,
        true,
        true,
        true,
        true,
    };
    dispatching_plant_sign_request = true;
    active_live_on_decision_impl(&request, true, event_timestamp_ticks,
                                 outcome);
    dispatching_plant_sign_request = false;
    pending_plant_sign_application = outcome->request_created;
    if (!pending_plant_sign_application && !outcome->faulted) {
      otis_cx317_active_fault(&transaction,
                              "plant_sign_request_not_created");
      outcome->faulted = true;
      outcome->reason = transaction.reason;
    } else if (!queue_plant_sign_frame(
                   "request", event_timestamp_ticks,
                   otis_cx321_plant_sign_state_name(
                       OtisCx321PlantSignState::PlantSignQualify),
                   otis_cx321_plant_sign_state_name(
                       OtisCx321PlantSignState::PlantSignQualify),
                   "identification_request_created", nullptr, nullptr)) {
      pending_plant_sign_application = false;
      otis_cx317_active_fault(&transaction,
                              "plant_sign_request_evidence_queue_fault");
      outcome->faulted = true;
      outcome->reason = transaction.reason;
    }
    return;
  }
  if (plant_sign_engine.state == OtisCx321PlantSignState::PlantSignQualify &&
      plant_sign_engine.application_ticks != 0u) {
    OtisCx321PlantSignResponse response = {};
    const bool passed = otis_cx321_plant_sign_engine_on_response(
        &plant_sign_engine, estimate, common_evidence_exact,
        latest_natural_tight_inside, &response);
    if (!queue_plant_sign_frame(
            "response", event_timestamp_ticks,
            otis_cx321_plant_sign_state_name(
                OtisCx321PlantSignState::PlantSignQualify),
            otis_cx321_plant_sign_state_name(plant_sign_engine.state),
            plant_sign_engine.reason, estimate,
            latest_natural_tight_inside ? "TIGHT_INSIDE" : "TIGHT_OUTSIDE")) {
      otis_cx317_active_fault(&transaction,
                              "plant_sign_response_evidence_queue_fault");
      outcome->faulted = true;
      outcome->reason = transaction.reason;
      return;
    }
    outcome->response_recorded = true;
    outcome->reason = plant_sign_engine.reason;
    if (!passed) {
      otis_cx317_active_fault(
          &transaction,
          strcmp(plant_sign_engine.reason,
                 "identification_response_evidence_inexact") == 0
              ? plant_sign_engine.reason
              : "plant_sign_qualification_failed");
      outcome->faulted = true;
      return;
    }
    evidence_phase = EvidencePhase::Response;
    evidence_request_sequence = response.request_sequence;
    evidence_pending_since_s = now_s;
    pending_response_psq_record_sequence = plant_sign_record_sequence;
    const OtisCx317ResponseResult active_response = {
        OtisCx317ResponseClass::HealthyDetected,
        "plant_sign_integer_response_passed_host_replay_pending",
        static_cast<double>(response.response_counts) / 1500.0,
        static_cast<double>(response.response_counts) / 1500.0,
        0u,
    };
    if (!queue_frame("response", &active_response,
                     static_cast<double>(estimate->signed_error_counts) /
                         1500.0)) {
      otis_cx317_active_fault(
          &transaction, "plant_sign_active_response_evidence_queue_fault");
      outcome->faulted = true;
      outcome->reason = transaction.reason;
    }
  }
#else
  (void)estimate;
  (void)current_applied_code;
  (void)latest_natural_tight_inside;
  (void)event_timestamp_ticks;
  (void)now_s;
#endif
}

bool otis_cx317_active_live_acknowledge_plant_sign_response(
    uint32_t request_sequence, uint32_t response_psq_record_sequence,
    int64_t response_counts, uint32_t application_sequence,
    uint32_t dac_epoch, uint32_t response_source_last_sequence,
    const char *attestation_sha256, uint64_t acknowledgement_ticks) {
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
  uint64_t extended_acknowledgement_ticks = 0u;
  if (!initialized || !transaction_bound || !plant_sign_engine_ready ||
      evidence_phase != EvidencePhase::Response ||
      request_sequence != evidence_request_sequence ||
      response_psq_record_sequence != pending_response_psq_record_sequence ||
      !exact_sha256_text(attestation_sha256)) {
    if (transaction_bound)
      otis_cx317_active_fault(
          &transaction, "plant_sign_response_ack_identity_mismatch");
    return false;
  }
  if (!otis_cx317_preview_live_extend_timer0_ticks(
          acknowledgement_ticks, &extended_acknowledgement_ticks)) {
    otis_cx317_active_fault(
        &transaction, "plant_sign_response_ack_timestamp_projection_failed");
    return false;
  }
  if (!otis_cx321_plant_sign_engine_acknowledge_response(
          &plant_sign_engine, request_sequence, application_sequence,
          dac_epoch, response_source_last_sequence, response_counts,
          extended_acknowledgement_ticks, true) ||
      !otis_cx317_active_rebase_natural_history_after_identification(
          &transaction, plant_sign_engine.applied_code,
          plant_sign_engine.applied_dac_epoch) ||
      !otis_cx317_active_complete_identification_response(
          &transaction, plant_sign_engine.applied_code,
          plant_sign_engine.applied_dac_epoch) ||
      !otis_cx321_plant_sign_engine_rebase_natural_controller(
          &plant_sign_engine, &hybrid_engine)) {
    otis_cx317_active_fault(&transaction,
                            "plant_sign_response_ack_or_handoff_failed");
    hybrid_fail_static(transaction.reason);
    return false;
  }
  memcpy(plant_sign_attestation_sha256, attestation_sha256, 65u);
  hybrid_engine_ready = true;
  if (!queue_plant_sign_frame(
          "response_ack", extended_acknowledgement_ticks,
          otis_cx321_plant_sign_state_name(
              OtisCx321PlantSignState::ResponseAckPending),
          otis_cx321_plant_sign_state_name(
              OtisCx321PlantSignState::PhaseQualify),
          "identification_response_acknowledged", nullptr, nullptr)) {
    otis_cx317_active_fault(&transaction,
                            "plant_sign_response_ack_evidence_queue_fault");
    hybrid_fail_static(transaction.reason);
    return false;
  }
  plant_sign_handoff_pending = true;
  evidence_phase = EvidencePhase::None;
  evidence_request_sequence = 0u;
  evidence_pending_since_s = 0u;
  return true;
#else
  (void)request_sequence;
  (void)response_psq_record_sequence;
  (void)response_counts;
  (void)application_sequence;
  (void)dac_epoch;
  (void)response_source_last_sequence;
  (void)attestation_sha256;
  (void)acknowledgement_ticks;
  return false;
#endif
}

bool otis_cx317_active_live_take_application_outcome(
    OtisCx317ActiveLiveOutcome *outcome) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (outcome == nullptr || !deferred_application_outcome_valid) return false;
  *outcome = deferred_application_outcome;
  deferred_application_outcome_valid = false;
  return true;
#else
  (void)outcome;
  return false;
#endif
}

bool otis_cx317_active_live_complete_application_evidence(
    uint32_t request_sequence, bool history_reset, uint32_t now_s) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (evidence_phase != EvidencePhase::Application ||
      request_sequence != evidence_request_sequence || frame.length != 0u)
    return false;
  estimator_history_reset = last_application_acknowledged && history_reset;
  if (last_application_acknowledged && !estimator_history_reset)
    otis_cx317_active_fault(&transaction,
                            "estimator_history_reset_not_confirmed");
#if OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
  OtisPhasePreviewLiveStatus cx323_phase = {};
  otis_phase_preview_live_get_status(&cx323_phase);
  const bool cx323_downstream_epoch_exact =
      last_application_acknowledged && estimator_history_reset &&
      otis_cx317_preview_live_applied_epoch_exact(
          transaction.applied_code, transaction.dac_epoch) &&
      cx323_phase.initialized && cx323_phase.applied_code_bound &&
      cx323_phase.applied_code == transaction.applied_code &&
      cx323_phase.dac_epoch == transaction.dac_epoch;
  if (!cx323_engine_ready || !pending_cx323_decision_valid ||
      !pending_cx323_origin_valid) {
    otis_cx317_active_fault(
        &transaction, "cx323_application_origin_or_controller_missing");
    return false;
  }
  const Cx323LiveMutationSnapshot application_snapshot =
      capture_cx323_live_mutation_snapshot();
  const OtisCx323Engine application_before = cx323_engine;
  OtisCx323Engine application_after = application_before;
  const bool application_exact =
      otis_cx323_engine_note_application_and_first_consumer(
          &application_after, &pending_cx323_decision,
          transaction.applied_code, transaction.dac_epoch,
          cx323_downstream_epoch_exact);
  const char *cx323_application_event =
      application_exact ? "application" : "application_fault";
  const OtisCx323MaintenanceEvent maintenance_event =
      application_exact
          ? OtisCx323MaintenanceEvent::ApplicationFirstConsumer
          : OtisCx323MaintenanceEvent::FailStatic;
  const OtisCx323MaintenanceTransactionEvent maintenance_transaction_event =
      application_exact
          ? OtisCx323MaintenanceTransactionEvent::Application
          : OtisCx323MaintenanceTransactionEvent::ApplicationFault;
  const bool enter_metadata_hold_after_application =
      application_exact && gnss_metadata_hold_active &&
      !application_after.metadata_hold;
  const uint8_t application_capacity =
      static_cast<uint8_t>(3u +
                           (enter_metadata_hold_after_application ? 1u : 0u));
  evidence_pending_since_s = now_s;
  if (!otis_dual_core_evidence_can_publish(application_capacity) ||
      !begin_cx323_evidence_burst(3u) ||
      !queue_frame(cx323_application_event, nullptr, 0.0) ||
      !queue_current_transaction_timing_sidecar(
          cx323_application_event, pending_application_timestamp_ticks,
          transaction.reason)) {
    restore_cx323_live_mutation_snapshot(application_snapshot);
    otis_cx317_active_fault(
        &transaction, "cx323_application_evidence_queue_fault");
    return false;
  }
  const OtisCx323MaintenanceTransactionJoin application_join =
      cx323_current_transaction_join(
          maintenance_transaction_event, pending_cx323_observation,
          pending_cx323_decision, true, cx323_downstream_epoch_exact);
  if (!queue_cx323_maintenance_record(
          maintenance_event, pending_application_timestamp_ticks,
          application_before, application_after,
          &pending_cx323_observation, &pending_cx323_decision,
          &pending_cx323_hybrid_join, &application_join, 3u, 3u,
          application_after.last_reason) ||
      !commit_cx323_evidence_burst()) {
    restore_cx323_live_mutation_snapshot(application_snapshot);
    otis_cx317_active_fault(
        &transaction, "cx323_application_burst_commit_failed");
    return false;
  }
  cx323_engine = application_after;
  if (!application_exact) {
    otis_cx317_active_fault(&transaction,
                            application_after.fail_static_reason);
    return false;
  }
  if (!otis_cx323_wide_is_zero(
          pending_cx323_decision.raw_pll_picocodes))
    ++cx323_phase_nonzero_application_count;
  if (pending_cx323_decision.phase_materially_influenced)
    ++cx323_phase_material_application_count;
  else
    ++cx323_frequency_only_application_count;
  if (enter_metadata_hold_after_application) {
    const OtisCx323Engine hold_before = cx323_engine;
    OtisCx323Engine hold_after = hold_before;
    if (!otis_cx323_engine_enter_metadata_hold(&hold_after) ||
        !queue_cx323_single_async_transition(
            OtisCx323MaintenanceEvent::GnssMetadataHoldEnter,
            pending_application_timestamp_ticks, hold_before, hold_after,
            hold_after.last_reason)) {
      otis_cx317_active_fault(
          &transaction, "cx323_post_application_metadata_hold_evidence_fault");
      return false;
    }
    cx323_engine = hold_after;
  }
  return true;
#endif
#if OTIS_ENABLE_CX320_ACTIVE_HYBRID
  if (last_application_acknowledged && estimator_history_reset) {
    OtisPhasePreviewLiveStatus phase = {};
    otis_phase_preview_live_get_status(&phase);
    const bool downstream_epoch_exact =
        otis_cx317_preview_live_applied_epoch_exact(
            transaction.applied_code, transaction.dac_epoch) &&
        phase.initialized && phase.applied_code_bound &&
        phase.applied_code == transaction.applied_code &&
        phase.dac_epoch == transaction.dac_epoch;
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
    if (pending_plant_sign_application) {
      const bool identification_noted =
          otis_cx321_plant_sign_engine_note_application(
              &plant_sign_engine, transaction.request.request_sequence,
              transaction.applied.application_sequence,
              transaction.applied_code, transaction.dac_epoch,
              pending_application_timestamp_ticks, downstream_epoch_exact);
      if (!identification_noted) {
        estimator_history_reset = false;
        otis_cx317_active_fault(
            &transaction, "plant_sign_application_epoch_mismatch");
      } else if (!queue_plant_sign_frame(
                     "application", pending_application_timestamp_ticks,
                     otis_cx321_plant_sign_state_name(
                         OtisCx321PlantSignState::PlantSignQualify),
                     otis_cx321_plant_sign_state_name(
                         OtisCx321PlantSignState::PlantSignQualify),
                     plant_sign_engine.reason, nullptr, nullptr)) {
        estimator_history_reset = false;
        otis_cx317_active_fault(
            &transaction, "plant_sign_application_evidence_queue_fault");
      }
      pending_plant_sign_application = false;
    } else
#endif
#if OTIS_ENABLE_CX32X_EXACT_ACTIVE_TIMING
    if (!otis_active_hybrid_engine_note_application_at_ticks(
                   &hybrid_engine, &pending_hybrid_decision,
                   transaction.applied_code, transaction.dac_epoch,
                   pending_application_timestamp_ticks,
                   pending_hybrid_decision_valid &&
                       downstream_epoch_exact)) {
#else
    if (!otis_active_hybrid_engine_note_application(
            &hybrid_engine, &pending_hybrid_decision,
            transaction.applied_code, transaction.dac_epoch,
            pending_hybrid_decision_valid && downstream_epoch_exact)) {
#endif
      estimator_history_reset = false;
      otis_cx317_active_fault(
          &transaction, "active_hybrid_application_epoch_mismatch");
    }
    pending_hybrid_decision_valid = false;
  }
#endif
  evidence_pending_since_s = now_s;
  const char *application_event =
      last_application_acknowledged && estimator_history_reset
          ? "application"
          : "application_fault";
  if (!queue_frame(application_event, nullptr, 0.0)) {
    otis_cx317_active_fault(&transaction, "application_evidence_queue_fault");
    return false;
  }
#if OTIS_ENABLE_EXACT_LONG_RUN_TIMING_SIDECARS
  if (!queue_current_transaction_timing_sidecar(
          application_event, pending_application_timestamp_ticks,
          transaction.reason)) {
    otis_cx317_active_fault(
        &transaction, "application_exact_timing_sidecar_queue_fault");
    return false;
  }
#endif
  return true;
#else
  (void)request_sequence;
  (void)history_reset;
  (void)now_s;
  return false;
#endif
}

bool otis_cx317_active_live_transport_busy(void) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  return frame.length != 0u;
#else
  return false;
#endif
}

void otis_cx317_active_live_service_transport(void) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  return;
#else
  if (frame.length == 0u) return;
  size_t available = otis_transport_available_for_write();
  if (available == 0u) return;
  size_t remaining = static_cast<size_t>(frame.length - frame.sent);
  size_t chunk = remaining < available ? remaining : available;
  if (chunk > kTransportChunkLimit) chunk = kTransportChunkLimit;
  frame.sent = static_cast<uint16_t>(
      frame.sent + otis_transport_write_bytes(
                       reinterpret_cast<const uint8_t *>(frame.data) + frame.sent,
                       chunk));
  if (frame.sent == frame.length) frame = {};
#endif
#endif
}

void otis_cx317_active_live_visit_status(
    void *context, OtisCx317ActiveStatusVisitor visitor, uint32_t now_s) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (visitor == nullptr) return;
  status_snapshot_generation += 1u;
  if (status_snapshot_generation == 0u) status_snapshot_generation = 1u;
  char snapshot_generation[24];
  snprintf(snapshot_generation, sizeof(snapshot_generation), "%lu",
           static_cast<unsigned long>(status_snapshot_generation));
  visitor(context, "snapshot_generation_begin", snapshot_generation,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  visitor(context, "snapshot_contract",
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
          OTIS_CX317_ACTIVE_STATUS_SNAPSHOT_CONTRACT_V2, OTIS_SEVERITY_INFO,
#elif OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION ||                         \
    OTIS_CX317_ACTIVE_CAMPAIGN ==                                       \
        OTIS_CX317_ACTIVE_CAMPAIGN_D9_D6_72H_SUSTAINED_HYBRID ||        \
    OTIS_CX317_ACTIVE_CAMPAIGN ==                                       \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX323_D9_D6_72H_ADAPTIVE_HYBRID
          OTIS_CX317_ACTIVE_STATUS_SNAPSHOT_CONTRACT_V3, OTIS_SEVERITY_INFO,
#else
          OTIS_CX317_ACTIVE_STATUS_SNAPSHOT_CONTRACT_V1, OTIS_SEVERITY_INFO,
#endif
          OTIS_FLAG_PROFILE_ASSUMPTION);
  OtisCx317ActiveLiveStatus active = {};
  otis_cx317_active_live_get_status(&active, now_s);
  visitor(context, "enabled", "true", OTIS_SEVERITY_INFO,
          OTIS_FLAG_PROFILE_ASSUMPTION);
  visitor(context, "run_identity", active.run_identity, OTIS_SEVERITY_INFO,
          OTIS_FLAG_PROFILE_ASSUMPTION);
  visitor(context, "build_identity", active.build_identity,
          OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  visitor(context, "profile_identity", active.profile_identity,
          OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  visitor(context, "estimator_sha256", active.estimator_sha256,
          OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  visitor(context, "model_sha256", active.model_sha256, OTIS_SEVERITY_INFO,
          OTIS_FLAG_PROFILE_ASSUMPTION);
  visitor(context, "active_policy_sha256", active.active_policy_sha256,
          OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  visitor(context, "response_policy_sha256", active.response_policy_sha256,
          OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  visitor(context, "numerical_policy_sha256",
          active.numerical_policy_sha256, OTIS_SEVERITY_INFO,
          OTIS_FLAG_PROFILE_ASSUMPTION);
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
  visitor(context, "plant_sign_gate_sha256", active.plant_sign_gate_sha256,
          OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  visitor(context, "identification_estimator_sha256",
          active.identification_estimator_sha256, OTIS_SEVERITY_INFO,
          OTIS_FLAG_PROFILE_ASSUMPTION);
  visitor(context, "identification_estimator_config_sha256",
          active.identification_estimator_config_sha256,
          OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  visitor(context, "natural_frequency_estimator_sha256",
          active.natural_frequency_estimator_sha256, OTIS_SEVERITY_INFO,
          OTIS_FLAG_PROFILE_ASSUMPTION);
  visitor(context, "plant_sign_state", active.plant_sign_state,
          active.fail_static ? OTIS_SEVERITY_ERROR : OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  visitor(context, "plant_sign_arm_window_eligible",
          active.plant_sign_arm_window_eligible ? "true" : "false",
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
#endif
  visitor(context, "state", active.state,
          active.fail_static ? OTIS_SEVERITY_ERROR : OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  visitor(context, "reason", active.reason, OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  visitor(context, "evidence_pending",
          active.evidence_pending ? "true" : "false",
          active.evidence_pending ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  visitor(context, "evidence_phase", active.evidence_state,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  visitor(context, "capture_lease_live",
          active.capture_lease_live ? "true" : "false",
          active.capture_lease_live ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
          OTIS_FLAG_NONE);
  visitor(context, "manual_start_confirmed",
          active.manual_start_confirmed ? "true" : "false",
          active.manual_start_confirmed ? OTIS_SEVERITY_INFO
                                        : OTIS_SEVERITY_WARN,
          OTIS_FLAG_NONE);
  visitor(context, "arm_eligible", active.arm_eligible ? "true" : "false",
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  visitor(context, "fail_static", active.fail_static ? "true" : "false",
          active.fail_static ? OTIS_SEVERITY_ERROR : OTIS_SEVERITY_INFO,
          active.fail_static ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                             : OTIS_FLAG_NONE);
  visitor(context, "setup_gnss_eligible",
          active.setup_gnss_eligible ? "true" : "false",
          active.setup_gnss_eligible ? OTIS_SEVERITY_INFO
                                     : OTIS_SEVERITY_WARN,
          OTIS_FLAG_NONE);
  visitor(context, "setup_reference_eligible",
          active.setup_reference_eligible ? "true" : "false",
          active.setup_reference_eligible ? OTIS_SEVERITY_INFO
                                          : OTIS_SEVERITY_WARN,
          OTIS_FLAG_NONE);
  visitor(context, "setup_partition_healthy",
          active.setup_partition_healthy ? "true" : "false",
          active.setup_partition_healthy ? OTIS_SEVERITY_INFO
                                         : OTIS_SEVERITY_ERROR,
          active.setup_partition_healthy
              ? OTIS_FLAG_NONE
              : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  visitor(context, "gnss_metadata_hold_active",
          active.gnss_metadata_hold_active ? "true" : "false",
          active.gnss_metadata_hold_active ? OTIS_SEVERITY_WARN
                                           : OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  visitor(context, "gnss_metadata_hold_transaction_pending",
          active.gnss_metadata_hold_transaction_pending ? "true" : "false",
          active.gnss_metadata_hold_transaction_pending ? OTIS_SEVERITY_WARN
                                                        : OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  char metadata_value[24];
  snprintf(metadata_value, sizeof(metadata_value), "%lu",
           static_cast<unsigned long>(
               active.gnss_metadata_hold_entry_sequence));
  visitor(context, "gnss_metadata_hold_entry_sequence", metadata_value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(metadata_value, sizeof(metadata_value), "%lu",
           static_cast<unsigned long>(
               active.gnss_metadata_requalification_sequence));
  visitor(context, "gnss_metadata_requalification_sequence", metadata_value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(metadata_value, sizeof(metadata_value), "%lu",
           static_cast<unsigned long>(
               active.gnss_metadata_qualification_frontier));
  visitor(context, "gnss_metadata_qualification_frontier", metadata_value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(metadata_value, sizeof(metadata_value), "%lu",
           static_cast<unsigned long>(active.d14_d8_observation_sequence));
  visitor(context, "d14_d8_observation_sequence", metadata_value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  visitor(context, "hybrid_state", active.hybrid_state,
          active.fail_static ? OTIS_SEVERITY_ERROR : OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  visitor(context, "hybrid_reason", active.hybrid_reason,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  visitor(context, "first_phase_checkpoint_passed",
          active.first_phase_checkpoint_passed ? "true" : "false",
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  char value[24];
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
  snprintf(value, sizeof(value), "%u", active.plant_sign_pre_window_count);
  visitor(context, "plant_sign_pre_window_count", value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%u",
           active.plant_sign_accumulator_accepted_intervals);
  visitor(context, "plant_sign_accumulator_accepted_intervals", value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
#endif
  snprintf(value, sizeof(value), "%u",
           active.phase_nonzero_application_count);
  visitor(context, "phase_nonzero_application_count", value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%u",
           active.phase_material_application_count);
  visitor(context, "phase_material_application_count", value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%u",
           active.frequency_only_application_count);
  visitor(context, "frequency_only_application_count", value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%u",
           active.automatic_application_count);
  visitor(context, "automatic_application_count", value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  visitor(context, "natural_reversal_observed",
          active.natural_reversal_observed ? "true" : "false",
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  visitor(context, "deliberate_challenge_applied",
          active.deliberate_challenge_applied ? "true" : "false",
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  visitor(context, "deliberate_challenge_cancelled",
          active.deliberate_challenge_cancelled ? "true" : "false",
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  visitor(context, "deliberate_challenge_unexercised",
          active.deliberate_challenge_unexercised ? "true" : "false",
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  visitor(context, "deliberate_challenge_recovery_applied",
          active.deliberate_challenge_recovery_applied ? "true" : "false",
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%d",
           static_cast<int>(active.deliberate_challenge_direction));
  visitor(context, "deliberate_challenge_direction", value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%u", active.deliberate_challenge_code);
  visitor(context, "deliberate_challenge_code", value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(active.deliberate_challenge_dac_epoch));
  visitor(context, "deliberate_challenge_dac_epoch", value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%llu",
           static_cast<unsigned long long>(
               active.deliberate_challenge_application_ticks));
  visitor(context, "deliberate_challenge_application_ticks", value,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(active.session_id));
  visitor(context, "session_id", value, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(active.query_nonce));
  visitor(context, "query_nonce", value, OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(active.uptime_s));
  visitor(context, "uptime_s", value, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(active.evidence_request_sequence));
  visitor(context, "evidence_request_sequence", value, OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "0x%04X",
           static_cast<unsigned int>(active.expected_setup_code));
  visitor(context, "expected_setup_code", value, OTIS_SEVERITY_INFO,
          OTIS_FLAG_PROFILE_ASSUMPTION);
  visitor(context, "confirmed_applied_code_known",
          active.confirmed_applied_code_known ? "true" : "false",
          active.confirmed_applied_code_known ? OTIS_SEVERITY_INFO
                                              : OTIS_SEVERITY_WARN,
          OTIS_FLAG_NONE);
  if (active.confirmed_applied_code_known)
    snprintf(value, sizeof(value), "%u", active.applied_code);
  else
    snprintf(value, sizeof(value), "%s", "unavailable");
  visitor(context, "confirmed_applied_code", value, OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%u", active.correction_count);
  visitor(context, "correction_count", value, OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%u", active.cumulative_movement_codes);
  visitor(context, "cumulative_movement_codes", value, OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(active.dac_epoch));
  visitor(context, "dac_epoch", value, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%u", active.selected_interval_count);
  visitor(context, "selected_interval_count", value, OTIS_SEVERITY_INFO,
          OTIS_FLAG_NONE);
  visitor(context, "automatic_retry", "false", OTIS_SEVERITY_INFO,
          OTIS_FLAG_PROFILE_ASSUMPTION);
  visitor(context, "automatic_restore", "false", OTIS_SEVERITY_INFO,
          OTIS_FLAG_PROFILE_ASSUMPTION);
  visitor(context, "snapshot_generation_complete", snapshot_generation,
          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
#else
  (void)context;
  (void)visitor;
  (void)now_s;
#endif
}

static void emit_direct_active_status(void *context, const char *key,
                                      const char *value,
                                      const char *severity, uint32_t flags) {
  otis_status_emit(static_cast<OtisStatusEmitContext *>(context),
                   "cx317_active", key, value, severity, flags);
}

void otis_cx317_active_live_emit_status(OtisStatusEmitContext *context,
                                        uint32_t now_s) {
  if (context == nullptr) return;
  otis_cx317_active_live_visit_status(context, emit_direct_active_status,
                                      now_s);
}

void otis_cx317_active_live_get_status(OtisCx317ActiveLiveStatus *status,
                                       uint32_t now_s) {
  if (status == nullptr) return;
  *status = {};
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  const OtisCx317ActiveEligibility current_eligibility = eligibility(now_s);
  status->run_identity = kRunIdentity;
  status->build_identity = kBuildIdentity;
  status->profile_identity = OTIS_BUILD_PROFILE_ID;
  status->estimator_sha256 = kEstimatorHash;
  status->model_sha256 = kModelHash;
  status->active_policy_sha256 = kActivePolicyHash;
  status->response_policy_sha256 = kResponsePolicyHash;
  status->numerical_policy_sha256 = kNumericalPolicyHash;
#if OTIS_ENABLE_CX321_ACTIVE_HYBRID
  status->plant_sign_gate_sha256 = kPlantSignGateHash;
  status->identification_estimator_sha256 = kIdentificationEstimatorHash;
  status->identification_estimator_config_sha256 =
      kIdentificationEstimatorConfigHash;
  status->natural_frequency_estimator_sha256 = kEstimatorHash;
  status->plant_sign_state =
      otis_cx321_plant_sign_state_name(plant_sign_engine.state);
  status->plant_sign_pre_window_count = plant_sign_engine.pre_window_count;
  status->plant_sign_accumulator_accepted_intervals =
      otis_cx317_preview_live_plant_sign_accepted_intervals();
  status->plant_sign_arm_window_eligible =
      plant_sign_engine_ready &&
      plant_sign_engine.state == OtisCx321PlantSignState::FrequencyAcquire &&
      plant_sign_engine.pre_window_count == 1u &&
      status->plant_sign_accumulator_accepted_intervals >= 1400u &&
      transaction.state == OtisCx317ActiveState::Disarmed &&
      evidence_phase == EvidencePhase::None &&
      otis_cx317_active_arm_eligibility_valid(&current_eligibility);
#endif
  status->state = gnss_metadata_hold_active
                      ? "GNSS_METADATA_HOLD"
                      : (transaction_bound
                             ? otis_cx317_active_state_name(transaction.state)
                             : "UNBOUND");
  status->reason = gnss_metadata_hold_active
                       ? (gnss_metadata_hold_transaction_pending
                              ? "gnss_metadata_hold_transaction_resolution_pending"
                              : "gnss_metadata_unqualified_hold")
                       : (transaction_bound ? transaction.reason
                                            : "session_unbound");
  status->evidence_state = evidence_state_name();
  status->session_id = transaction_bound
                           ? transaction.expected_binding.session_id
                           : 0u;
  status->evidence_request_sequence = evidence_request_sequence;
  status->query_nonce = status_query_nonce;
  status->uptime_s = now_s;
  status->expected_setup_code =
      static_cast<uint16_t>(OTIS_CX317_ACTIVE_START_CODE);
  status->applied_code = transaction_bound ? transaction.applied_code : 0u;
  status->correction_count =
      transaction_bound ? transaction.correction_count : 0u;
  status->cumulative_movement_codes =
      transaction_bound ? transaction.cumulative_movement_codes : 0u;
  status->dac_epoch = transaction_bound ? transaction.dac_epoch : 0u;
  status->selected_interval_count =
      have_health ? latest_health.selected_interval_count : 0u;
  status->transaction_bound = transaction_bound;
  status->evidence_pending = evidence_phase != EvidencePhase::None;
  status->confirmed_applied_code_known =
      transaction_bound && manual_start_confirmed;
  status->capture_lease_live = capture_lease_live(now_s);
  status->manual_start_confirmed = manual_start_confirmed;
  status->arm_eligible =
      otis_cx317_active_arm_eligibility_valid(&current_eligibility);
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  status->fail_static =
      otis_dual_core_fail_static() ||
      (transaction_bound &&
       (transaction.state == OtisCx317ActiveState::Fault ||
        transaction.state == OtisCx317ActiveState::Aborted));
#else
  status->fail_static = transaction_bound &&
                        (transaction.state == OtisCx317ActiveState::Fault ||
                         transaction.state == OtisCx317ActiveState::Aborted);
#endif
  status->setup_gnss_eligible =
      have_health && latest_health.gnss_metadata_valid &&
      latest_health.gnss_identity_stable && latest_health.gnss_3d_evidence;
  status->setup_reference_eligible =
      have_health && latest_health.raw_pps_valid && latest_health.count_valid;
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  status->setup_partition_healthy = !otis_dual_core_fail_static();
#else
  status->setup_partition_healthy = true;
#endif
  status->gnss_metadata_hold_active = gnss_metadata_hold_active;
  status->gnss_metadata_hold_transaction_pending =
      gnss_metadata_hold_transaction_pending;
  status->gnss_metadata_hold_entry_sequence =
      gnss_metadata_hold_entry_sequence;
  status->gnss_metadata_requalification_sequence =
      gnss_metadata_requalification_sequence;
  status->gnss_metadata_qualification_frontier =
      gnss_metadata_qualification_frontier;
  status->d14_d8_observation_sequence =
      have_health ? latest_health.d14_d8_observation_sequence : 0u;
#if OTIS_ENABLE_CX320_ACTIVE_HYBRID
#if OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
  const bool cx323_controller_inhibited =
      cx323_engine_ready && cx323_engine.fail_static_reason != nullptr &&
      (strcmp(cx323_engine.fail_static_reason,
              "prospective_repeated_alternation") == 0 ||
       strcmp(cx323_engine.fail_static_reason,
              "prospective_low_efficiency_path") == 0);
  if (!cx323_engine_ready) {
    status->hybrid_state = "SETUP_PENDING";
    status->hybrid_reason = "setup_consumers_pending";
  } else if (gnss_metadata_hold_active) {
    status->hybrid_state = "GNSS_METADATA_HOLD";
    status->hybrid_reason = cx323_engine.last_reason;
  } else if (cx323_controller_inhibited) {
    status->hybrid_state = "CONTROLLER_AUTHORITY_INHIBITED";
    status->hybrid_reason = cx323_engine.fail_static_reason;
  } else {
    status->hybrid_state = otis_active_hybrid_state_name(
        cx323_project_hybrid_state(
            cx323_engine,
            !last_cx323_origin_valid || last_cx323_observation.phase_valid));
    status->hybrid_reason = cx323_engine.last_reason;
  }
  status->phase_nonzero_application_count =
      cx323_phase_nonzero_application_count;
  status->phase_material_application_count =
      cx323_phase_material_application_count;
  status->frequency_only_application_count =
      cx323_frequency_only_application_count;
  status->first_phase_checkpoint_passed =
      cx323_engine_ready && cx323_engine.application_count > 0u &&
      !cx323_engine.response_pending;
  status->automatic_application_count =
      static_cast<uint16_t>(cx323_engine.application_count);
  status->natural_reversal_observed = false;
  for (uint8_t index = 1u; index < cx323_engine.direction_count; ++index) {
    if (cx323_engine.direction_history[index - 1u] !=
        cx323_engine.direction_history[index])
      status->natural_reversal_observed = true;
  }
  status->deliberate_challenge_applied = false;
  status->deliberate_challenge_cancelled = false;
  status->deliberate_challenge_unexercised = true;
  status->deliberate_challenge_recovery_applied = false;
  status->deliberate_challenge_direction = 0;
  status->deliberate_challenge_code = 0u;
  status->deliberate_challenge_dac_epoch = 0u;
  status->deliberate_challenge_application_ticks = 0u;
#elif OTIS_ENABLE_CX321_ACTIVE_HYBRID
  status->hybrid_state =
      hybrid_engine_ready
          ? otis_active_hybrid_state_name(hybrid_engine.state)
          : (plant_sign_engine_ready
                 ? otis_cx321_plant_sign_state_name(plant_sign_engine.state)
                 : "SETUP_PENDING");
  status->hybrid_reason =
      hybrid_engine_ready
          ? hybrid_engine.reason
          : (plant_sign_engine_ready ? plant_sign_engine.reason
                                     : "setup_consumers_pending");
#else
  status->hybrid_state =
      hybrid_engine_ready
          ? otis_active_hybrid_state_name(hybrid_engine.state)
          : "SETUP_PENDING";
  status->hybrid_reason =
      hybrid_engine_ready ? hybrid_engine.reason : "setup_consumers_pending";
#endif
#if !OTIS_ENABLE_CX323_PHASE_PRIORITY_MAINTENANCE
  status->phase_nonzero_application_count =
      hybrid_engine.phase_nonzero_application_count;
  status->phase_material_application_count =
      hybrid_engine.phase_material_application_count;
  status->frequency_only_application_count =
      hybrid_engine.frequency_only_application_count;
  status->first_phase_checkpoint_passed =
      hybrid_engine.first_checkpoint_response_passed;
  status->automatic_application_count =
      hybrid_engine.automatic_application_count;
  status->natural_reversal_observed =
      hybrid_engine.natural_reversal_observed;
  status->deliberate_challenge_applied =
      hybrid_engine.deliberate_challenge_applied;
  status->deliberate_challenge_cancelled =
      hybrid_engine.deliberate_challenge_cancelled;
  status->deliberate_challenge_unexercised =
      hybrid_engine.deliberate_challenge_unexercised;
  status->deliberate_challenge_recovery_applied =
      hybrid_engine.deliberate_challenge_recovery_applied;
  status->deliberate_challenge_direction =
      hybrid_engine.deliberate_challenge_direction;
  status->deliberate_challenge_code =
      hybrid_engine.deliberate_challenge_code;
  status->deliberate_challenge_dac_epoch =
      hybrid_engine.deliberate_challenge_dac_epoch;
  status->deliberate_challenge_application_ticks =
      hybrid_engine.deliberate_challenge_application_ticks;
#endif
#else
  status->hybrid_state = "DISABLED";
  status->hybrid_reason = "active_hybrid_compiled_out";
#endif
#else
  (void)now_s;
  status->state = "DISABLED";
  status->reason = "active_control_compiled_out";
  status->evidence_state = "evidence_clear";
  status->hybrid_state = "DISABLED";
  status->hybrid_reason = "active_control_compiled_out";
#endif
}

void otis_cx317_active_live_set_status_query_nonce(uint32_t query_nonce) {
  status_query_nonce = query_nonce;
}

uint32_t otis_cx317_active_live_status_snapshot_generation(void) {
  return status_snapshot_generation;
}

const char *otis_cx317_active_live_run_identity(void) { return kRunIdentity; }

uint16_t otis_cx317_active_live_start_code(void) {
  return static_cast<uint16_t>(OTIS_CX317_ACTIVE_START_CODE);
}
