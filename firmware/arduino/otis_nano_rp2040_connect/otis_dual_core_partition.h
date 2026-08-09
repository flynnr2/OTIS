#ifndef OTIS_DUAL_CORE_PARTITION_H
#define OTIS_DUAL_CORE_PARTITION_H

#include <stdint.h>

#include "otis_dual_core_contract.h"

constexpr uint32_t OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH = 16u;
constexpr uint32_t OTIS_OBSERVATION_QUEUE_DEPTH = 96u;
constexpr uint32_t OTIS_CRITICAL_QUEUE_DEPTH = 16u;
constexpr uint32_t OTIS_EVIDENCE_QUEUE_DEPTH = 8u;
constexpr uint32_t OTIS_CX318_PREVIEW_QUEUE_DEPTH = 32u;
// The Stage 7 timing-health publication reaches a measured 93-message burst.
// ACTIVE? independently publishes 22 active-status messages from Core 1.  The
// two clocks can align during endurance, so keep enough space for both bursts
// plus margin while Core 0 is occupied with the serial transport.
constexpr uint32_t OTIS_STAGE7_CONCURRENT_TELEMETRY_BURST = 115u;
constexpr uint32_t OTIS_TELEMETRY_QUEUE_DEPTH = 128u;
static_assert(OTIS_TELEMETRY_QUEUE_DEPTH >=
                  OTIS_STAGE7_CONCURRENT_TELEMETRY_BURST,
              "telemetry queue must absorb concurrent health and ACTIVE? bursts");

enum class OtisPartitionFault : uint8_t {
  None,
  ServiceToTimingExhausted,
  ObservationExhausted,
  CriticalExhausted,
  EvidenceExhausted,
  Cx318PreviewExhausted,
  Cx318PreviewFault,
  ActuatorTimeout,
  ActuatorAcknowledgementMismatch,
};

// A low-cost Core 1 breadcrumb.  The sketch updates it only in a bounded,
// coarse trace (at most four traced loops per second).  Core 0 samples it and
// freezes the first service-queue fault capsule without asking the failed core
// to publish more telemetry.
enum class OtisTimingProgressPhase : uint8_t {
  Reset,
  LoopEnter,
  ServiceInput,
  PpsObserver,
  CaptureBackend,
  BoundaryDrain,
  CaptureDrain,
  GateService,
  Cx317EstimatePrepare,
  Cx317EstimateFormat,
  Cx317EstimatePublish,
  Cx317ActivePrepare,
  Cx317ActiveFormat,
  Cx317ActivePublish,
  Cx318Preview,
  TimingHealth,
  LoopIdle,
};

struct OtisTimingProgressStats {
  // Number of traced loops, not the unrestricted Core 1 loop count.
  uint32_t loop_sequence;
  OtisTimingProgressPhase phase;
  uint64_t phase_enter_ticks;
  uint64_t last_progress_ticks;
  uint32_t last_snapshot_session;
  uint32_t last_snapshot_sequence;
  uint32_t last_count_sequence;
  uint32_t last_estimate_sequence;
};

struct OtisServiceQueueStats {
  uint32_t publish_attempts;
  uint32_t publish_successes;
  uint32_t publish_failures;
  uint32_t take_successes;
  OtisServiceMessageKind last_published_kind;
  uint32_t last_published_sequence;
  uint64_t last_published_ticks;
  OtisServiceMessageKind last_taken_kind;
  uint32_t last_taken_sequence;
  uint64_t last_taken_ticks;
};

struct OtisServiceFaultCapsule {
  bool valid;
  OtisServiceMessageKind failing_kind;
  uint32_t failing_sequence;
  uint64_t failing_published_ticks;
  uint32_t queue_depth;
  bool breadcrumb_coherent;
  uint32_t breadcrumb_generation;
  OtisServiceMessageKind last_taken_kind;
  uint32_t last_taken_sequence;
  uint64_t last_taken_ticks;
  OtisTimingProgressPhase timing_phase;
  uint32_t timing_loop_sequence;
  uint64_t timing_last_progress_ticks;
  uint32_t last_snapshot_session;
  uint32_t last_snapshot_sequence;
  uint32_t last_count_sequence;
  uint32_t last_estimate_sequence;
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
  uint32_t cx318_preview_depth;
  uint32_t cx318_preview_high_water;
  OtisTimingProgressStats timing_progress;
  OtisServiceQueueStats service_activity;
  OtisServiceFaultCapsule service_fault;
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

// Core 1 producer / Core 0 consumer. Numerical Stage 4 evidence is
// non-droppable and is formatted only after it crosses this value queue.
bool otis_dual_core_publish_cx318_preview(
    const OtisCx318PreviewRecordMessage *message);
bool otis_dual_core_take_cx318_preview(
    OtisCx318PreviewRecordMessage *message);

void otis_dual_core_note_timing_progress(OtisTimingProgressPhase phase,
                                         uint64_t now_ticks);
void otis_dual_core_note_timing_snapshot(uint32_t session, uint32_t sequence);
void otis_dual_core_note_timing_count(uint32_t sequence);
void otis_dual_core_note_timing_estimate(uint32_t sequence);

void otis_dual_core_latch_fault(OtisPartitionFault fault);
bool otis_dual_core_fail_static(void);
void otis_dual_core_get_stats(OtisDualCoreQueueStats *stats);
const char *otis_partition_fault_name(OtisPartitionFault fault);
const char *otis_timing_progress_phase_name(OtisTimingProgressPhase phase);
const char *otis_service_message_kind_name(OtisServiceMessageKind kind);

#endif
