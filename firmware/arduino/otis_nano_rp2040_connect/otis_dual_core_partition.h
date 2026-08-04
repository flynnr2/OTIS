#ifndef OTIS_DUAL_CORE_PARTITION_H
#define OTIS_DUAL_CORE_PARTITION_H

#include <stdint.h>

#include "otis_dual_core_contract.h"

constexpr uint32_t OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH = 16u;
constexpr uint32_t OTIS_OBSERVATION_QUEUE_DEPTH = 96u;
constexpr uint32_t OTIS_CRITICAL_QUEUE_DEPTH = 16u;
constexpr uint32_t OTIS_EVIDENCE_QUEUE_DEPTH = 8u;
constexpr uint32_t OTIS_TELEMETRY_QUEUE_DEPTH = 96u;

enum class OtisPartitionFault : uint8_t {
  None,
  ServiceToTimingExhausted,
  ObservationExhausted,
  CriticalExhausted,
  EvidenceExhausted,
  ActuatorTimeout,
  ActuatorAcknowledgementMismatch,
};

struct OtisDualCoreQueueStats {
  uint32_t service_to_timing_depth;
  uint32_t service_to_timing_high_water;
  uint32_t observation_depth;
  uint32_t observation_high_water;
  uint32_t critical_depth;
  uint32_t critical_high_water;
  uint32_t evidence_depth;
  uint32_t evidence_high_water;
  uint32_t telemetry_depth;
  uint32_t telemetry_high_water;
  uint32_t telemetry_dropped;
  OtisPartitionFault fault;
  bool fail_static;
};

void otis_dual_core_partition_reset(void);
void otis_dual_core_set_timing_owner_active(bool active);
bool otis_dual_core_timing_owner_active(void);

// Core 0 producer / Core 1 consumer. Non-droppable.
bool otis_dual_core_publish_service(const OtisServiceMessage *message);
bool otis_dual_core_take_service(OtisServiceMessage *message);

// Core 1 producer / Core 0 consumer. Raw evidence is non-droppable.
bool otis_dual_core_publish_observation(
    const OtisObservationMessage *message);
bool otis_dual_core_take_observation(OtisObservationMessage *message);

// Core 1 producer / Core 0 consumer. Transaction/state evidence is
// non-droppable.
bool otis_dual_core_publish_critical(const OtisCriticalRecordMessage *message);
bool otis_dual_core_take_critical(OtisCriticalRecordMessage *message);

// Core 1 producer / Core 0 consumer. Complete EST/CTL/ACT frames are
// non-droppable; no mutable formatter buffer is shared between cores.
bool otis_dual_core_publish_evidence(const OtisEvidenceFrameMessage *message);
bool otis_dual_core_take_evidence(OtisEvidenceFrameMessage *message);

// Core 1 producer / Core 0 consumer. Duplicate summaries may drop, always
// with an explicit saturating counter.
bool otis_dual_core_publish_telemetry(const OtisTelemetryMessage *message);
bool otis_dual_core_take_telemetry(OtisTelemetryMessage *message);

void otis_dual_core_latch_fault(OtisPartitionFault fault);
bool otis_dual_core_fail_static(void);
void otis_dual_core_get_stats(OtisDualCoreQueueStats *stats);
const char *otis_partition_fault_name(OtisPartitionFault fault);

#endif
