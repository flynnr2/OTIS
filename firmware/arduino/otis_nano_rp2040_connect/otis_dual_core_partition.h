#ifndef OTIS_DUAL_CORE_PARTITION_H
#define OTIS_DUAL_CORE_PARTITION_H

#include <stdint.h>

#include "otis_dual_core_contract.h"

constexpr uint32_t OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH = 16u;
constexpr uint32_t OTIS_OBSERVATION_QUEUE_DEPTH = 96u;
constexpr uint32_t OTIS_CRITICAL_QUEUE_DEPTH = 16u;
// A selected CX323 boundary publishes three estimator/deadband frames before
// active control and one control frame after it.  The largest active-control
// request burst is five frames; a response boundary instead publishes a
// three-frame decision burst followed by a three-frame response burst.  Core
// 1 produces each complete boundary synchronously, so the evidence queue must
// absorb the exact largest producer frontier without relying on concurrent
// Core 0 drainage.
constexpr uint32_t OTIS_CX323_SELECTED_EVIDENCE_PREFIX_COUNT = 3u;
constexpr uint32_t OTIS_CX323_SELECTED_EVIDENCE_SUFFIX_COUNT = 1u;
constexpr uint32_t OTIS_CX323_REQUEST_DECISION_EVIDENCE_COUNT = 5u;
constexpr uint32_t OTIS_CX323_RESPONSE_DECISION_EVIDENCE_COUNT = 3u;
constexpr uint32_t OTIS_CX323_RESPONSE_COMPLETION_EVIDENCE_COUNT = 3u;
constexpr uint32_t OTIS_CX323_FAIL_TRANSITION_EVIDENCE_COUNT = 1u;
constexpr uint32_t OTIS_CX323_REQUEST_EVIDENCE_FRONTIER =
    OTIS_CX323_SELECTED_EVIDENCE_PREFIX_COUNT +
    OTIS_CX323_REQUEST_DECISION_EVIDENCE_COUNT +
    OTIS_CX323_SELECTED_EVIDENCE_SUFFIX_COUNT;
constexpr uint32_t OTIS_CX323_RESPONSE_EVIDENCE_FRONTIER =
    OTIS_CX323_SELECTED_EVIDENCE_PREFIX_COUNT +
    OTIS_CX323_RESPONSE_DECISION_EVIDENCE_COUNT +
    OTIS_CX323_RESPONSE_COMPLETION_EVIDENCE_COUNT +
    OTIS_CX323_SELECTED_EVIDENCE_SUFFIX_COUNT;
constexpr uint32_t OTIS_CX323_REQUEST_FAIL_EVIDENCE_FRONTIER =
    OTIS_CX323_SELECTED_EVIDENCE_PREFIX_COUNT +
    OTIS_CX323_REQUEST_DECISION_EVIDENCE_COUNT +
    OTIS_CX323_FAIL_TRANSITION_EVIDENCE_COUNT +
    OTIS_CX323_SELECTED_EVIDENCE_SUFFIX_COUNT;
constexpr uint32_t OTIS_EVIDENCE_QUEUE_DEPTH = 10u;
static_assert(OTIS_CX323_REQUEST_EVIDENCE_FRONTIER == 9u,
              "CX323 selected request frontier must remain exact");
static_assert(OTIS_CX323_RESPONSE_EVIDENCE_FRONTIER == 10u,
              "CX323 selected response frontier must remain exact");
static_assert(OTIS_CX323_REQUEST_FAIL_EVIDENCE_FRONTIER == 10u,
              "CX323 selected request/fail frontier must remain exact");
static_assert(OTIS_EVIDENCE_QUEUE_DEPTH >=
                  OTIS_CX323_REQUEST_EVIDENCE_FRONTIER,
              "evidence queue must absorb one complete CX323 request boundary");
static_assert(OTIS_EVIDENCE_QUEUE_DEPTH >=
                  OTIS_CX323_RESPONSE_EVIDENCE_FRONTIER,
              "evidence queue must absorb one complete CX323 response boundary");
static_assert(OTIS_EVIDENCE_QUEUE_DEPTH >=
                  OTIS_CX323_REQUEST_FAIL_EVIDENCE_FRONTIER,
              "evidence queue must absorb a CX323 request/fail boundary");
constexpr uint32_t OTIS_PHASE_PREVIEW_QUEUE_DEPTH = 32u;
constexpr uint32_t OTIS_MONITOR_OBSERVATION_QUEUE_DEPTH = 16u;
// The non-active portion of Stage 7 timing health reaches 67 telemetry
// messages. ACTIVE status has a maximum 63-field vocabulary across the base,
// sustained-hybrid, and CX321 contracts, plus three complete-generation
// envelope records in both the direct and cross-core publishers. Reserve the
// union because the visitor is shared and compile-time profile fields must not
// make admission smaller than the burst it actually emits. A periodic health
// burst and one ACTIVE? response can align while Core 0 is occupied with
// serial transport.
constexpr uint32_t OTIS_CX317_ACTIVE_STATUS_FIELD_COUNT = 63u;
constexpr uint32_t OTIS_CX317_ACTIVE_STATUS_ENVELOPE_COUNT = 3u;
constexpr uint32_t OTIS_CX317_ACTIVE_STATUS_TELEMETRY_BURST =
    OTIS_CX317_ACTIVE_STATUS_FIELD_COUNT +
    OTIS_CX317_ACTIVE_STATUS_ENVELOPE_COUNT;
constexpr uint32_t OTIS_FORWARDED_MONITOR_HEALTH_TELEMETRY_BURST = 13u;
constexpr uint32_t OTIS_TIMING_HEALTH_NONACTIVE_TELEMETRY_BURST =
    67u + OTIS_FORWARDED_MONITOR_HEALTH_TELEMETRY_BURST;
constexpr uint32_t OTIS_TIMING_HEALTH_TELEMETRY_BURST =
    OTIS_TIMING_HEALTH_NONACTIVE_TELEMETRY_BURST +
    OTIS_CX317_ACTIVE_STATUS_TELEMETRY_BURST;
constexpr uint32_t OTIS_MAXIMUM_CONCURRENT_TELEMETRY_BURST =
    OTIS_TIMING_HEALTH_TELEMETRY_BURST +
    OTIS_CX317_ACTIVE_STATUS_TELEMETRY_BURST;
static_assert(OTIS_MAXIMUM_CONCURRENT_TELEMETRY_BURST == 212u,
              "Stage 7 health plus one ACTIVE? response must remain exact");
// Retain the already-proven conservative split-boot capacity after removing
// the obsolete D10 witness records; a smaller exact startup count is not
// needed to protect the finite queue.
constexpr uint32_t OTIS_MAXIMUM_BOOT_TELEMETRY_BURST = 169u;
constexpr uint32_t OTIS_TELEMETRY_QUEUE_DEPTH = 212u;
static_assert(OTIS_TELEMETRY_QUEUE_DEPTH >=
                  OTIS_MAXIMUM_CONCURRENT_TELEMETRY_BURST,
              "telemetry queue must absorb concurrent health and ACTIVE? bursts");
static_assert(OTIS_TELEMETRY_QUEUE_DEPTH >= OTIS_MAXIMUM_BOOT_TELEMETRY_BURST,
              "telemetry queue must absorb the Stage 4 split-boot burst");

enum class OtisPartitionFault : uint8_t {
  None,
  BootTelemetryExhausted,
  BootHandshakeTimeout,
  ServiceToTimingExhausted,
  ObservationExhausted,
  CriticalExhausted,
  EvidenceExhausted,
  PhasePreviewQueueExhausted,
  PhasePreviewFault,
  TransportObstructed,
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
  PhasePreview,
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
  uint32_t phase_preview_depth;
  uint32_t phase_preview_high_water;
  uint32_t monitor_observation_depth;
  uint32_t monitor_observation_high_water;
  uint32_t monitor_observation_dropped;
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

// Core 1 producer / Core 0 consumer. D6 diagnostic evidence is additive and
// drop-new; queue failure is recorded locally and never latches fail-static.
bool otis_dual_core_publish_monitor_observation(
    const OtisMonitorObservationMessage *message);
bool otis_dual_core_take_monitor_observation(
    OtisMonitorObservationMessage *message);

// Core 1 producer / Core 0 consumer. Transaction/state evidence is
// non-droppable.
bool otis_dual_core_publish_critical(const OtisCriticalRecordMessage *message);
bool otis_dual_core_take_critical(OtisCriticalRecordMessage *message);

// Core 1 producer / Core 0 consumer. Complete EST/CTL/ACT frames are
// non-droppable; no mutable formatter buffer is shared between cores.
bool otis_dual_core_publish_evidence(const OtisEvidenceFrameMessage *message);
// Publish one preformatted logical evidence burst with a single commit. Every
// member and capacity for the complete burst are checked before any frame is
// visible to Core 0. Failure publishes no prefix and latches EvidenceExhausted.
bool otis_dual_core_publish_evidence_burst(
    const OtisEvidenceFrameMessage *messages, uint32_t message_count);
// In-place atomic burst construction avoids a second full-frame staging
// array. No appended member is visible to Core 0 until commit releases the
// reserved tail; cancel discards the unpublished suffix.
bool otis_dual_core_begin_evidence_burst(uint32_t message_count);
bool otis_dual_core_append_evidence_burst(
    const OtisEvidenceFrameMessage *message);
bool otis_dual_core_commit_evidence_burst(void);
void otis_dual_core_cancel_evidence_burst(void);
// Read-only reservation predicate for two causally adjacent logical bursts.
// Core 1 is the sole producer, while concurrent Core 0 drainage can only add
// capacity, so a successful check remains sufficient until those bursts are
// published back-to-back without another evidence producer call.
bool otis_dual_core_evidence_can_publish(uint32_t message_count);
bool otis_dual_core_take_evidence(OtisEvidenceFrameMessage *message);

// Core 1 producer / Core 0 consumer. Duplicate summaries may drop, always
// with an explicit saturating counter.
bool otis_dual_core_publish_telemetry(const OtisTelemetryMessage *message);
// Admission check for an all-or-nothing logical telemetry burst. The sole
// Core 1 producer calls this immediately before publishing the burst.
bool otis_dual_core_telemetry_can_publish(uint32_t message_count);
// Boot publication is non-blocking. The queue is statically sized for the
// declared startup burst; exceeding that budget is an explicit fail-static
// partition fault rather than an unbounded timing-core wait.
bool otis_dual_core_publish_boot_telemetry(
    const OtisTelemetryMessage *message);
bool otis_dual_core_take_telemetry(OtisTelemetryMessage *message);

// Core 1 producer / Core 0 consumer. Numerical Stage 4 evidence is
// non-droppable and is formatted only after it crosses this value queue.
bool otis_dual_core_publish_phase_preview(
    const OtisPhasePreviewRecordMessage *message);
bool otis_dual_core_take_phase_preview(
    OtisPhasePreviewRecordMessage *message);

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
