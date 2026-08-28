#include "otis_dual_core_partition.h"

#include <string.h>

#include "otis_spsc_queue.h"

namespace {

OtisSpscQueue<OtisServiceMessage, OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH>
    service_to_timing;
OtisSpscQueue<OtisObservationMessage, OTIS_OBSERVATION_QUEUE_DEPTH>
    observation_to_service;
OtisSpscQueue<OtisCriticalRecordMessage, OTIS_CRITICAL_QUEUE_DEPTH>
    critical_to_service;
OtisSpscQueue<OtisEvidenceFrameMessage, OTIS_EVIDENCE_QUEUE_DEPTH>
    evidence_to_service;
OtisSpscQueue<OtisTelemetryMessage, OTIS_TELEMETRY_QUEUE_DEPTH>
    telemetry_to_service;
OtisSpscQueue<OtisPhasePreviewRecordMessage, OTIS_PHASE_PREVIEW_QUEUE_DEPTH>
    phase_preview_to_service;
OtisSpscQueue<OtisMonitorObservationMessage, OTIS_MONITOR_OBSERVATION_QUEUE_DEPTH>
    monitor_observation_to_service;

uint32_t telemetry_dropped = 0u;
uint32_t monitor_observation_dropped = 0u;
uint8_t partition_fault = static_cast<uint8_t>(OtisPartitionFault::None);
bool fail_static = false;
bool timing_owner_active = false;

uint32_t timing_loop_sequence = 0u;
uint8_t timing_progress_phase =
    static_cast<uint8_t>(OtisTimingProgressPhase::Reset);
uint64_t timing_phase_enter_ticks = 0u;
uint64_t timing_last_progress_ticks = 0u;
uint32_t timing_last_snapshot_session = 0u;
uint32_t timing_last_snapshot_sequence = 0u;
uint32_t timing_last_count_sequence = 0u;
uint32_t timing_last_estimate_sequence = 0u;
uint32_t timing_breadcrumb_generation = 0u;

uint32_t service_publish_attempts = 0u;
uint32_t service_publish_successes = 0u;
uint32_t service_publish_failures = 0u;
uint32_t service_take_successes = 0u;
uint8_t service_last_published_kind =
    static_cast<uint8_t>(OtisServiceMessageKind::ReceiverQualification);
uint32_t service_last_published_sequence = 0u;
uint64_t service_last_published_ticks = 0u;
uint8_t service_last_taken_kind =
    static_cast<uint8_t>(OtisServiceMessageKind::ReceiverQualification);
uint32_t service_last_taken_sequence = 0u;
uint64_t service_last_taken_ticks = 0u;

bool service_fault_valid = false;
uint8_t service_fault_kind =
    static_cast<uint8_t>(OtisServiceMessageKind::ReceiverQualification);
uint32_t service_fault_sequence = 0u;
uint64_t service_fault_published_ticks = 0u;
uint32_t service_fault_depth = 0u;
bool service_fault_breadcrumb_coherent = false;
uint32_t service_fault_breadcrumb_generation = 0u;
uint8_t service_fault_last_taken_kind =
    static_cast<uint8_t>(OtisServiceMessageKind::ReceiverQualification);
uint32_t service_fault_last_taken_sequence = 0u;
uint64_t service_fault_last_taken_ticks = 0u;
uint8_t service_fault_timing_phase =
    static_cast<uint8_t>(OtisTimingProgressPhase::Reset);
uint32_t service_fault_timing_loop_sequence = 0u;
uint64_t service_fault_timing_last_progress_ticks = 0u;
uint32_t service_fault_last_snapshot_session = 0u;
uint32_t service_fault_last_snapshot_sequence = 0u;
uint32_t service_fault_last_count_sequence = 0u;
uint32_t service_fault_last_estimate_sequence = 0u;

void increment_saturating(uint32_t *value) {
  uint32_t observed = __atomic_load_n(value, __ATOMIC_RELAXED);
  while (observed != UINT32_MAX &&
         !__atomic_compare_exchange_n(value, &observed, observed + 1u, false,
                                      __ATOMIC_RELAXED,
                                      __ATOMIC_RELAXED)) {
  }
}

bool acknowledgement_matches(const OtisCrossCoreActuatorRequest &request,
                             const OtisCrossCoreActuatorAck &ack) {
  return ack.request_sequence == request.request_sequence &&
         ack.decision_sequence == request.decision_sequence &&
         ack.authorization_sequence == request.authorization_sequence &&
         ack.nonce == request.nonce &&
         ack.requested_code == request.requested_code;
}

uint32_t service_sequence(const OtisServiceMessage &message) {
  switch (message.kind) {
    case OtisServiceMessageKind::ReceiverQualification:
      return message.receiver.sequence;
    case OtisServiceMessageKind::Environment:
      return message.environment.sequence;
    case OtisServiceMessageKind::AppliedDacState:
    case OtisServiceMessageKind::ManualDacApplication:
      return message.dac.sequence;
    case OtisServiceMessageKind::RunControl:
      return message.run_control.sequence;
    case OtisServiceMessageKind::ActuatorAcknowledgement:
      return message.actuator_acknowledgement.request_sequence;
    case OtisServiceMessageKind::SetupApplicationAcknowledgement:
      return message.setup_acknowledgement.command_sequence;
  }
  return 0u;
}

uint64_t service_ticks(const OtisServiceMessage &message) {
  switch (message.kind) {
    case OtisServiceMessageKind::ReceiverQualification:
      return message.receiver.published_ticks;
    case OtisServiceMessageKind::Environment:
      return message.environment.timestamp_ticks;
    case OtisServiceMessageKind::AppliedDacState:
    case OtisServiceMessageKind::ManualDacApplication:
      return message.dac.published_ticks;
    case OtisServiceMessageKind::RunControl:
      return message.run_control.published_ticks;
    case OtisServiceMessageKind::ActuatorAcknowledgement:
      return message.actuator_acknowledgement.acknowledgement_ticks;
    case OtisServiceMessageKind::SetupApplicationAcknowledgement:
      return 0u;
  }
  return 0u;
}

void begin_timing_breadcrumb_write() {
  // Core 1 is the sole writer.  Odd means a multi-field update is in flight.
  __atomic_add_fetch(&timing_breadcrumb_generation, 1u, __ATOMIC_ACQ_REL);
}

void end_timing_breadcrumb_write() {
  // Publish the complete update with the next even generation.
  __atomic_add_fetch(&timing_breadcrumb_generation, 1u, __ATOMIC_RELEASE);
}

void copy_timing_breadcrumb(OtisServiceFaultCapsule *capsule) {
  if (capsule == nullptr) return;
  constexpr uint8_t kMaximumSnapshotAttempts = 3u;
  for (uint8_t attempt = 0u; attempt < kMaximumSnapshotAttempts; ++attempt) {
    const uint32_t before =
        __atomic_load_n(&timing_breadcrumb_generation, __ATOMIC_ACQUIRE);
    if ((before & 1u) != 0u) continue;
    capsule->last_taken_kind = static_cast<OtisServiceMessageKind>(
        __atomic_load_n(&service_last_taken_kind, __ATOMIC_RELAXED));
    capsule->last_taken_sequence =
        __atomic_load_n(&service_last_taken_sequence, __ATOMIC_RELAXED);
    capsule->last_taken_ticks =
        __atomic_load_n(&service_last_taken_ticks, __ATOMIC_RELAXED);
    capsule->timing_phase = static_cast<OtisTimingProgressPhase>(
        __atomic_load_n(&timing_progress_phase, __ATOMIC_RELAXED));
    capsule->timing_loop_sequence =
        __atomic_load_n(&timing_loop_sequence, __ATOMIC_RELAXED);
    capsule->timing_last_progress_ticks =
        __atomic_load_n(&timing_last_progress_ticks, __ATOMIC_RELAXED);
    capsule->last_snapshot_session =
        __atomic_load_n(&timing_last_snapshot_session, __ATOMIC_RELAXED);
    capsule->last_snapshot_sequence =
        __atomic_load_n(&timing_last_snapshot_sequence, __ATOMIC_RELAXED);
    capsule->last_count_sequence =
        __atomic_load_n(&timing_last_count_sequence, __ATOMIC_RELAXED);
    capsule->last_estimate_sequence =
        __atomic_load_n(&timing_last_estimate_sequence, __ATOMIC_RELAXED);
    const uint32_t after =
        __atomic_load_n(&timing_breadcrumb_generation, __ATOMIC_ACQUIRE);
    if (before == after && (after & 1u) == 0u) {
      capsule->breadcrumb_coherent = true;
      capsule->breadcrumb_generation = after;
      return;
    }
  }

  // Never let diagnostics spin behind a timing-core failure.  Preserve a
  // best-effort capsule and say explicitly that the cross-field snapshot was
  // not coherent.
  capsule->last_taken_kind = static_cast<OtisServiceMessageKind>(
      __atomic_load_n(&service_last_taken_kind, __ATOMIC_RELAXED));
  capsule->last_taken_sequence =
      __atomic_load_n(&service_last_taken_sequence, __ATOMIC_RELAXED);
  capsule->last_taken_ticks =
      __atomic_load_n(&service_last_taken_ticks, __ATOMIC_RELAXED);
  capsule->timing_phase = static_cast<OtisTimingProgressPhase>(
      __atomic_load_n(&timing_progress_phase, __ATOMIC_RELAXED));
  capsule->timing_loop_sequence =
      __atomic_load_n(&timing_loop_sequence, __ATOMIC_RELAXED);
  capsule->timing_last_progress_ticks =
      __atomic_load_n(&timing_last_progress_ticks, __ATOMIC_RELAXED);
  capsule->last_snapshot_session =
      __atomic_load_n(&timing_last_snapshot_session, __ATOMIC_RELAXED);
  capsule->last_snapshot_sequence =
      __atomic_load_n(&timing_last_snapshot_sequence, __ATOMIC_RELAXED);
  capsule->last_count_sequence =
      __atomic_load_n(&timing_last_count_sequence, __ATOMIC_RELAXED);
  capsule->last_estimate_sequence =
      __atomic_load_n(&timing_last_estimate_sequence, __ATOMIC_RELAXED);
  capsule->breadcrumb_coherent = false;
  capsule->breadcrumb_generation =
      __atomic_load_n(&timing_breadcrumb_generation, __ATOMIC_ACQUIRE);
}

void freeze_service_fault(const OtisServiceMessage *message) {
  if (__atomic_load_n(&service_fault_valid, __ATOMIC_ACQUIRE)) return;
  const OtisServiceMessageKind kind =
      message == nullptr ? OtisServiceMessageKind::ReceiverQualification
                         : message->kind;
  __atomic_store_n(&service_fault_kind, static_cast<uint8_t>(kind),
                   __ATOMIC_RELAXED);
  __atomic_store_n(&service_fault_sequence,
                   message == nullptr ? 0u : service_sequence(*message),
                   __ATOMIC_RELAXED);
  __atomic_store_n(&service_fault_published_ticks,
                   message == nullptr ? 0u : service_ticks(*message),
                   __ATOMIC_RELAXED);
  __atomic_store_n(&service_fault_depth, service_to_timing.depth(),
                   __ATOMIC_RELAXED);
  OtisServiceFaultCapsule breadcrumb = {};
  copy_timing_breadcrumb(&breadcrumb);
  __atomic_store_n(&service_fault_breadcrumb_coherent,
                   breadcrumb.breadcrumb_coherent, __ATOMIC_RELAXED);
  __atomic_store_n(&service_fault_breadcrumb_generation,
                   breadcrumb.breadcrumb_generation, __ATOMIC_RELAXED);
  __atomic_store_n(&service_fault_last_taken_kind,
                   static_cast<uint8_t>(breadcrumb.last_taken_kind),
                   __ATOMIC_RELAXED);
  __atomic_store_n(&service_fault_last_taken_sequence,
                   breadcrumb.last_taken_sequence, __ATOMIC_RELAXED);
  __atomic_store_n(&service_fault_last_taken_ticks,
                   breadcrumb.last_taken_ticks, __ATOMIC_RELAXED);
  __atomic_store_n(&service_fault_timing_phase,
                   static_cast<uint8_t>(breadcrumb.timing_phase),
                   __ATOMIC_RELAXED);
  __atomic_store_n(&service_fault_timing_loop_sequence,
                   breadcrumb.timing_loop_sequence, __ATOMIC_RELAXED);
  __atomic_store_n(&service_fault_timing_last_progress_ticks,
                   breadcrumb.timing_last_progress_ticks, __ATOMIC_RELAXED);
  __atomic_store_n(&service_fault_last_snapshot_session,
                   breadcrumb.last_snapshot_session, __ATOMIC_RELAXED);
  __atomic_store_n(&service_fault_last_snapshot_sequence,
                   breadcrumb.last_snapshot_sequence, __ATOMIC_RELAXED);
  __atomic_store_n(&service_fault_last_count_sequence,
                   breadcrumb.last_count_sequence, __ATOMIC_RELAXED);
  __atomic_store_n(&service_fault_last_estimate_sequence,
                   breadcrumb.last_estimate_sequence, __ATOMIC_RELAXED);
  __atomic_store_n(&service_fault_valid, true, __ATOMIC_RELEASE);
}

void guard_fault(OtisActuatorTransactionGuard *guard, const char *reason,
                 OtisPartitionFault fault) {
  guard->state = OtisActuatorGuardState::Fault;
  guard->reason = reason;
  otis_dual_core_latch_fault(fault);
}

}  // namespace

void otis_dual_core_partition_reset(void) {
  service_to_timing.reset();
  observation_to_service.reset();
  critical_to_service.reset();
  evidence_to_service.reset();
  telemetry_to_service.reset();
  phase_preview_to_service.reset();
  monitor_observation_to_service.reset();
  __atomic_store_n(&telemetry_dropped, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&monitor_observation_dropped, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&partition_fault,
                   static_cast<uint8_t>(OtisPartitionFault::None),
                   __ATOMIC_RELEASE);
  __atomic_store_n(&fail_static, false, __ATOMIC_RELEASE);
  __atomic_store_n(&timing_owner_active, false, __ATOMIC_RELEASE);
  __atomic_store_n(&timing_loop_sequence, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&timing_progress_phase,
                   static_cast<uint8_t>(OtisTimingProgressPhase::Reset),
                   __ATOMIC_RELAXED);
  __atomic_store_n(&timing_phase_enter_ticks, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&timing_last_progress_ticks, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&timing_last_snapshot_session, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&timing_last_snapshot_sequence, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&timing_last_count_sequence, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&timing_last_estimate_sequence, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&timing_breadcrumb_generation, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&service_publish_attempts, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&service_publish_successes, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&service_publish_failures, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&service_take_successes, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&service_last_published_sequence, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&service_last_published_ticks, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&service_last_taken_sequence, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&service_last_taken_ticks, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&service_fault_valid, false, __ATOMIC_RELAXED);
  __atomic_store_n(&service_fault_breadcrumb_coherent, false,
                   __ATOMIC_RELAXED);
  __atomic_store_n(&service_fault_breadcrumb_generation, 0u,
                   __ATOMIC_RELAXED);
}

void otis_dual_core_set_timing_owner_active(bool active) {
  __atomic_store_n(&timing_owner_active, active, __ATOMIC_RELEASE);
}

bool otis_dual_core_timing_owner_active(void) {
  return __atomic_load_n(&timing_owner_active, __ATOMIC_ACQUIRE);
}

bool otis_dual_core_publish_service(const OtisServiceMessage *message) {
  increment_saturating(&service_publish_attempts);
  if (message != nullptr && service_to_timing.try_push(*message)) {
    increment_saturating(&service_publish_successes);
    __atomic_store_n(&service_last_published_kind,
                     static_cast<uint8_t>(message->kind), __ATOMIC_RELAXED);
    __atomic_store_n(&service_last_published_sequence,
                     service_sequence(*message), __ATOMIC_RELAXED);
    __atomic_store_n(&service_last_published_ticks, service_ticks(*message),
                     __ATOMIC_RELEASE);
    return true;
  }
  increment_saturating(&service_publish_failures);
  freeze_service_fault(message);
  otis_dual_core_latch_fault(OtisPartitionFault::ServiceToTimingExhausted);
  return false;
}

bool otis_dual_core_take_service(OtisServiceMessage *message) {
  // The empty poll is the Core 1 hot path.  Do not add diagnostic atomic
  // traffic to it; account only actual cross-core transfers.
  if (!service_to_timing.try_pop(message)) return false;
  increment_saturating(&service_take_successes);
  begin_timing_breadcrumb_write();
  __atomic_store_n(&service_last_taken_kind,
                   static_cast<uint8_t>(message->kind), __ATOMIC_RELAXED);
  __atomic_store_n(&service_last_taken_sequence, service_sequence(*message),
                   __ATOMIC_RELAXED);
  __atomic_store_n(&service_last_taken_ticks, service_ticks(*message),
                   __ATOMIC_RELEASE);
  end_timing_breadcrumb_write();
  return true;
}

bool otis_dual_core_publish_observation(
    const OtisObservationMessage *message) {
  if (message != nullptr && observation_to_service.try_push(*message))
    return true;
  otis_dual_core_latch_fault(OtisPartitionFault::ObservationExhausted);
  return false;
}

bool otis_dual_core_take_observation(OtisObservationMessage *message) {
  return observation_to_service.try_pop(message);
}

bool otis_dual_core_publish_monitor_observation(
    const OtisMonitorObservationMessage *message) {
  if (message != nullptr && monitor_observation_to_service.try_push(*message))
    return true;
  increment_saturating(&monitor_observation_dropped);
  return false;
}

bool otis_dual_core_take_monitor_observation(
    OtisMonitorObservationMessage *message) {
  return monitor_observation_to_service.try_pop(message);
}

bool otis_dual_core_publish_critical(
    const OtisCriticalRecordMessage *message) {
  if (message != nullptr && critical_to_service.try_push(*message)) return true;
  otis_dual_core_latch_fault(OtisPartitionFault::CriticalExhausted);
  return false;
}

bool otis_dual_core_take_critical(OtisCriticalRecordMessage *message) {
  return critical_to_service.try_pop(message);
}

bool otis_dual_core_publish_evidence(
    const OtisEvidenceFrameMessage *message) {
  if (message != nullptr && message->length > 0u &&
      message->length < OTIS_EVIDENCE_FRAME_CAPACITY &&
      evidence_to_service.try_push(*message))
    return true;
  otis_dual_core_latch_fault(OtisPartitionFault::EvidenceExhausted);
  return false;
}

bool otis_dual_core_take_evidence(OtisEvidenceFrameMessage *message) {
  return evidence_to_service.try_pop(message);
}

bool otis_dual_core_publish_telemetry(const OtisTelemetryMessage *message) {
  if (message != nullptr && telemetry_to_service.try_push(*message)) return true;
  increment_saturating(&telemetry_dropped);
  return false;
}

bool otis_dual_core_telemetry_can_publish(uint32_t message_count) {
  return message_count <= OTIS_TELEMETRY_QUEUE_DEPTH &&
         telemetry_to_service.depth() <=
             OTIS_TELEMETRY_QUEUE_DEPTH - message_count;
}

bool otis_dual_core_publish_boot_telemetry(
    const OtisTelemetryMessage *message) {
  if (message != nullptr && telemetry_to_service.try_push(*message))
    return true;
  increment_saturating(&telemetry_dropped);
  otis_dual_core_latch_fault(OtisPartitionFault::BootTelemetryExhausted);
  return false;
}

bool otis_dual_core_take_telemetry(OtisTelemetryMessage *message) {
  return telemetry_to_service.try_pop(message);
}

bool otis_dual_core_publish_phase_preview(
    const OtisPhasePreviewRecordMessage *message) {
  if (message != nullptr && phase_preview_to_service.try_push(*message))
    return true;
  otis_dual_core_latch_fault(OtisPartitionFault::PhasePreviewQueueExhausted);
  return false;
}

bool otis_dual_core_take_phase_preview(
    OtisPhasePreviewRecordMessage *message) {
  return phase_preview_to_service.try_pop(message);
}

void otis_dual_core_note_timing_progress(OtisTimingProgressPhase phase,
                                         uint64_t now_ticks) {
  begin_timing_breadcrumb_write();
  if (phase == OtisTimingProgressPhase::LoopEnter)
    increment_saturating(&timing_loop_sequence);
  __atomic_store_n(&timing_progress_phase, static_cast<uint8_t>(phase),
                   __ATOMIC_RELAXED);
  __atomic_store_n(&timing_phase_enter_ticks, now_ticks, __ATOMIC_RELAXED);
  __atomic_store_n(&timing_last_progress_ticks, now_ticks, __ATOMIC_RELEASE);
  end_timing_breadcrumb_write();
}

void otis_dual_core_note_timing_snapshot(uint32_t session, uint32_t sequence) {
  begin_timing_breadcrumb_write();
  __atomic_store_n(&timing_last_snapshot_session, session, __ATOMIC_RELAXED);
  __atomic_store_n(&timing_last_snapshot_sequence, sequence,
                   __ATOMIC_RELEASE);
  end_timing_breadcrumb_write();
}

void otis_dual_core_note_timing_count(uint32_t sequence) {
  begin_timing_breadcrumb_write();
  __atomic_store_n(&timing_last_count_sequence, sequence, __ATOMIC_RELEASE);
  end_timing_breadcrumb_write();
}

void otis_dual_core_note_timing_estimate(uint32_t sequence) {
  begin_timing_breadcrumb_write();
  __atomic_store_n(&timing_last_estimate_sequence, sequence, __ATOMIC_RELEASE);
  end_timing_breadcrumb_write();
}

void otis_dual_core_latch_fault(OtisPartitionFault fault) {
  if (fault == OtisPartitionFault::None) return;
  uint8_t expected = static_cast<uint8_t>(OtisPartitionFault::None);
  const uint8_t requested = static_cast<uint8_t>(fault);
  __atomic_compare_exchange_n(&partition_fault, &expected, requested, false,
                              __ATOMIC_RELEASE, __ATOMIC_RELAXED);
  __atomic_store_n(&fail_static, true, __ATOMIC_RELEASE);
}

bool otis_dual_core_fail_static(void) {
  return __atomic_load_n(&fail_static, __ATOMIC_ACQUIRE);
}

void otis_dual_core_get_stats(OtisDualCoreQueueStats *stats) {
  if (stats == nullptr) return;
  *stats = {};
  stats->service_to_timing_depth = service_to_timing.depth();
  stats->service_to_timing_high_water = service_to_timing.high_water();
  stats->observation_depth = observation_to_service.depth();
  stats->observation_high_water = observation_to_service.high_water();
  stats->critical_depth = critical_to_service.depth();
  stats->critical_high_water = critical_to_service.high_water();
  stats->evidence_depth = evidence_to_service.depth();
  stats->evidence_high_water = evidence_to_service.high_water();
  stats->telemetry_depth = telemetry_to_service.depth();
  stats->telemetry_high_water = telemetry_to_service.high_water();
  stats->telemetry_dropped =
      __atomic_load_n(&telemetry_dropped, __ATOMIC_ACQUIRE);
  stats->phase_preview_depth = phase_preview_to_service.depth();
  stats->phase_preview_high_water = phase_preview_to_service.high_water();
  stats->monitor_observation_depth = monitor_observation_to_service.depth();
  stats->monitor_observation_high_water =
      monitor_observation_to_service.high_water();
  stats->monitor_observation_dropped =
      __atomic_load_n(&monitor_observation_dropped, __ATOMIC_ACQUIRE);
  stats->timing_progress = {
      __atomic_load_n(&timing_loop_sequence, __ATOMIC_ACQUIRE),
      static_cast<OtisTimingProgressPhase>(
          __atomic_load_n(&timing_progress_phase, __ATOMIC_ACQUIRE)),
      __atomic_load_n(&timing_phase_enter_ticks, __ATOMIC_ACQUIRE),
      __atomic_load_n(&timing_last_progress_ticks, __ATOMIC_ACQUIRE),
      __atomic_load_n(&timing_last_snapshot_session, __ATOMIC_ACQUIRE),
      __atomic_load_n(&timing_last_snapshot_sequence, __ATOMIC_ACQUIRE),
      __atomic_load_n(&timing_last_count_sequence, __ATOMIC_ACQUIRE),
      __atomic_load_n(&timing_last_estimate_sequence, __ATOMIC_ACQUIRE),
  };
  stats->service_activity = {
      __atomic_load_n(&service_publish_attempts, __ATOMIC_ACQUIRE),
      __atomic_load_n(&service_publish_successes, __ATOMIC_ACQUIRE),
      __atomic_load_n(&service_publish_failures, __ATOMIC_ACQUIRE),
      __atomic_load_n(&service_take_successes, __ATOMIC_ACQUIRE),
      static_cast<OtisServiceMessageKind>(
          __atomic_load_n(&service_last_published_kind, __ATOMIC_ACQUIRE)),
      __atomic_load_n(&service_last_published_sequence, __ATOMIC_ACQUIRE),
      __atomic_load_n(&service_last_published_ticks, __ATOMIC_ACQUIRE),
      static_cast<OtisServiceMessageKind>(
          __atomic_load_n(&service_last_taken_kind, __ATOMIC_ACQUIRE)),
      __atomic_load_n(&service_last_taken_sequence, __ATOMIC_ACQUIRE),
      __atomic_load_n(&service_last_taken_ticks, __ATOMIC_ACQUIRE),
  };
  stats->service_fault = {
      __atomic_load_n(&service_fault_valid, __ATOMIC_ACQUIRE),
      static_cast<OtisServiceMessageKind>(
          __atomic_load_n(&service_fault_kind, __ATOMIC_ACQUIRE)),
      __atomic_load_n(&service_fault_sequence, __ATOMIC_ACQUIRE),
      __atomic_load_n(&service_fault_published_ticks, __ATOMIC_ACQUIRE),
      __atomic_load_n(&service_fault_depth, __ATOMIC_ACQUIRE),
      __atomic_load_n(&service_fault_breadcrumb_coherent, __ATOMIC_ACQUIRE),
      __atomic_load_n(&service_fault_breadcrumb_generation,
                      __ATOMIC_ACQUIRE),
      static_cast<OtisServiceMessageKind>(
          __atomic_load_n(&service_fault_last_taken_kind, __ATOMIC_ACQUIRE)),
      __atomic_load_n(&service_fault_last_taken_sequence, __ATOMIC_ACQUIRE),
      __atomic_load_n(&service_fault_last_taken_ticks, __ATOMIC_ACQUIRE),
      static_cast<OtisTimingProgressPhase>(
          __atomic_load_n(&service_fault_timing_phase, __ATOMIC_ACQUIRE)),
      __atomic_load_n(&service_fault_timing_loop_sequence, __ATOMIC_ACQUIRE),
      __atomic_load_n(&service_fault_timing_last_progress_ticks,
                      __ATOMIC_ACQUIRE),
      __atomic_load_n(&service_fault_last_snapshot_session, __ATOMIC_ACQUIRE),
      __atomic_load_n(&service_fault_last_snapshot_sequence, __ATOMIC_ACQUIRE),
      __atomic_load_n(&service_fault_last_count_sequence, __ATOMIC_ACQUIRE),
      __atomic_load_n(&service_fault_last_estimate_sequence, __ATOMIC_ACQUIRE),
  };
  stats->fault = static_cast<OtisPartitionFault>(
      __atomic_load_n(&partition_fault, __ATOMIC_ACQUIRE));
  stats->fail_static = __atomic_load_n(&fail_static, __ATOMIC_ACQUIRE);
}

const char *otis_partition_fault_name(OtisPartitionFault fault) {
  switch (fault) {
    case OtisPartitionFault::None:
      return "none";
    case OtisPartitionFault::BootTelemetryExhausted:
      return "boot_telemetry_queue_exhausted";
    case OtisPartitionFault::BootHandshakeTimeout:
      return "boot_handshake_timeout";
    case OtisPartitionFault::ServiceToTimingExhausted:
      return "service_to_timing_queue_exhausted";
    case OtisPartitionFault::ObservationExhausted:
      return "raw_observation_queue_exhausted";
    case OtisPartitionFault::CriticalExhausted:
      return "critical_queue_exhausted";
    case OtisPartitionFault::EvidenceExhausted:
      return "evidence_queue_exhausted";
    case OtisPartitionFault::PhasePreviewQueueExhausted:
      return "cx318_preview_queue_exhausted";
    case OtisPartitionFault::PhasePreviewFault:
      return "cx318_preview_processing_fault";
    case OtisPartitionFault::TransportObstructed:
      return "transport_obstructed";
    case OtisPartitionFault::ActuatorTimeout:
      return "actuator_acknowledgement_timeout";
    case OtisPartitionFault::ActuatorAcknowledgementMismatch:
      return "actuator_acknowledgement_mismatch";
  }
  return "unknown_partition_fault";
}

const char *otis_timing_progress_phase_name(OtisTimingProgressPhase phase) {
  switch (phase) {
    case OtisTimingProgressPhase::Reset:
      return "reset";
    case OtisTimingProgressPhase::LoopEnter:
      return "loop_enter";
    case OtisTimingProgressPhase::ServiceInput:
      return "service_input";
    case OtisTimingProgressPhase::CaptureBackend:
      return "capture_backend";
    case OtisTimingProgressPhase::BoundaryDrain:
      return "boundary_drain";
    case OtisTimingProgressPhase::CaptureDrain:
      return "capture_drain";
    case OtisTimingProgressPhase::GateService:
      return "gate_service";
    case OtisTimingProgressPhase::Cx317EstimatePrepare:
      return "cx317_estimate_prepare";
    case OtisTimingProgressPhase::Cx317EstimateFormat:
      return "cx317_estimate_format";
    case OtisTimingProgressPhase::Cx317EstimatePublish:
      return "cx317_estimate_publish";
    case OtisTimingProgressPhase::Cx317ActivePrepare:
      return "cx317_active_prepare";
    case OtisTimingProgressPhase::Cx317ActiveFormat:
      return "cx317_active_format";
    case OtisTimingProgressPhase::Cx317ActivePublish:
      return "cx317_active_publish";
    case OtisTimingProgressPhase::PhasePreview:
      return "cx318_preview";
    case OtisTimingProgressPhase::TimingHealth:
      return "timing_health";
    case OtisTimingProgressPhase::LoopIdle:
      return "loop_idle";
  }
  return "unknown";
}

const char *otis_service_message_kind_name(OtisServiceMessageKind kind) {
  switch (kind) {
    case OtisServiceMessageKind::ReceiverQualification:
      return "receiver_qualification";
    case OtisServiceMessageKind::Environment:
      return "environment";
    case OtisServiceMessageKind::AppliedDacState:
      return "applied_dac_state";
    case OtisServiceMessageKind::ManualDacApplication:
      return "manual_dac_application";
    case OtisServiceMessageKind::RunControl:
      return "run_control";
    case OtisServiceMessageKind::ActuatorAcknowledgement:
      return "actuator_acknowledgement";
    case OtisServiceMessageKind::SetupApplicationAcknowledgement:
      return "setup_application_acknowledgement";
  }
  return "unknown";
}

void otis_actuator_guard_init(OtisActuatorTransactionGuard *guard) {
  if (guard == nullptr) return;
  *guard = {};
  guard->state = OtisActuatorGuardState::Idle;
  guard->reason = "idle";
}

bool otis_actuator_guard_start(OtisActuatorTransactionGuard *guard,
                               const OtisCrossCoreActuatorRequest *request,
                               OtisActuatorMonotonicSeconds now_s) {
  if (guard == nullptr || request == nullptr) return false;
  if (guard->state != OtisActuatorGuardState::Idle &&
      guard->state != OtisActuatorGuardState::Applied) {
    guard_fault(guard, "request_while_transaction_pending",
                OtisPartitionFault::ActuatorAcknowledgementMismatch);
    return false;
  }
  if (!request->actionable || request->request_sequence == 0u ||
      request->request_sequence <= guard->last_request_sequence ||
      request->authorization_sequence <= guard->last_authorization_sequence ||
      request->nonce == 0u ||
      !otis_actuator_monotonic_deadline_is_future(
          now_s, request->monotonic_deadline_s)) {
    guard_fault(guard, "stale_duplicate_or_unauthorized_request",
                OtisPartitionFault::ActuatorAcknowledgementMismatch);
    return false;
  }
  guard->pending = *request;
  guard->last_request_sequence = request->request_sequence;
  guard->last_authorization_sequence = request->authorization_sequence;
  guard->state = OtisActuatorGuardState::AwaitingAcceptance;
  guard->reason = "awaiting_exact_acceptance";
  return true;
}

bool otis_actuator_guard_acknowledge(
    OtisActuatorTransactionGuard *guard,
    const OtisCrossCoreActuatorAck *acknowledgement) {
  if (guard == nullptr || acknowledgement == nullptr) return false;
  if (!acknowledgement_matches(guard->pending, *acknowledgement)) {
    if (guard->rejected_acknowledgements < UINT32_MAX)
      guard->rejected_acknowledgements++;
    guard_fault(guard, "nonmatching_actuator_acknowledgement",
                OtisPartitionFault::ActuatorAcknowledgementMismatch);
    return false;
  }
  if (guard->state == OtisActuatorGuardState::AwaitingAcceptance &&
      acknowledgement->kind == OtisActuatorAckKind::Accepted &&
      acknowledgement->accepted_code == guard->pending.requested_code) {
    guard->state = OtisActuatorGuardState::AwaitingApplication;
    guard->reason = "accepted_awaiting_exact_application";
    return true;
  }
  if (guard->state == OtisActuatorGuardState::AwaitingApplication &&
      acknowledgement->kind == OtisActuatorAckKind::Applied &&
      acknowledgement->i2c_ok && !acknowledgement->clamped &&
      !acknowledgement->ambiguous &&
      acknowledgement->accepted_code == guard->pending.requested_code &&
      acknowledgement->applied_code == guard->pending.requested_code) {
    guard->state = OtisActuatorGuardState::Applied;
    guard->reason = "exact_application_confirmed";
    return true;
  }
  if (guard->rejected_acknowledgements < UINT32_MAX)
    guard->rejected_acknowledgements++;
  guard_fault(guard, "actuator_acknowledgement_phase_or_value_mismatch",
              OtisPartitionFault::ActuatorAcknowledgementMismatch);
  return false;
}

bool otis_actuator_guard_check_deadline(OtisActuatorTransactionGuard *guard,
                                        OtisActuatorMonotonicSeconds now_s) {
  if (guard == nullptr) return false;
  if ((guard->state == OtisActuatorGuardState::AwaitingAcceptance ||
      guard->state == OtisActuatorGuardState::AwaitingApplication) &&
      otis_actuator_monotonic_deadline_is_expired(
          now_s, guard->pending.monotonic_deadline_s)) {
    guard_fault(guard, "actuator_acknowledgement_deadline_expired",
                OtisPartitionFault::ActuatorTimeout);
    return false;
  }
  return guard->state != OtisActuatorGuardState::Fault;
}
