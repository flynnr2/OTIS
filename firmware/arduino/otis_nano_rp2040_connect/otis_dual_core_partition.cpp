#include "otis_dual_core_partition.h"

#include <string.h>

#include "otis_spsc_queue.h"

namespace {

OtisObservationDiagnosticClock observation_diagnostic_clock = nullptr;

OtisSpscQueue<OtisServiceMessage, OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH>
    service_to_timing;
OtisSpscQueue<OtisServiceMessage, 1u> priority_hold_to_timing;
OtisSpscQueue<OtisObservationMessage, OTIS_OBSERVATION_QUEUE_DEPTH>
    observation_to_service;
OtisSpscQueue<OtisCriticalRecordMessage, OTIS_CRITICAL_QUEUE_DEPTH>
    critical_to_service;
OtisSpscQueue<OtisInstrumentWrite, 1u> instrument_write_to_service;
OtisSpscQueue<OtisInstrumentApplication, 1u> instrument_application_to_timing;

// Evidence decisions can comprise several independently formatted records.
// This ring differs from the other SPSC queues only in allowing the sole
// producer to fill several slots and release the new tail once, so Core 0 can
// observe either none or all of a logical burst. Core 0 is the sole consumer;
// concurrent draining can only advance head and increase available capacity.
class OtisEvidenceBurstQueue {
 public:
  OtisEvidenceBurstQueue()
      : head_(0u), tail_(0u), high_water_(0u), staged_tail_(0u),
        staged_expected_(0u), staged_count_(0u), staged_active_(false) {}

  void reset() {
    __atomic_store_n(&head_, 0u, __ATOMIC_RELAXED);
    __atomic_store_n(&tail_, 0u, __ATOMIC_RELAXED);
    __atomic_store_n(&high_water_, 0u, __ATOMIC_RELAXED);
    staged_tail_ = 0u;
    staged_expected_ = 0u;
    staged_count_ = 0u;
    staged_active_ = false;
  }

  bool try_push_burst(const OtisEvidenceFrameMessage *messages,
                      uint32_t message_count) {
    if (staged_active_ || messages == nullptr || message_count == 0u ||
        message_count > OTIS_EVIDENCE_QUEUE_DEPTH)
      return false;

    const uint32_t tail = __atomic_load_n(&tail_, __ATOMIC_RELAXED);
    const uint32_t head = __atomic_load_n(&head_, __ATOMIC_ACQUIRE);
    const uint32_t depth = tail - head;
    if (depth > OTIS_EVIDENCE_QUEUE_DEPTH ||
        message_count > OTIS_EVIDENCE_QUEUE_DEPTH - depth)
      return false;

    for (uint32_t index = 0u; index < message_count; ++index) {
      slots_[(tail + index) % OTIS_EVIDENCE_QUEUE_DEPTH] = messages[index];
    }
    __atomic_store_n(&tail_, tail + message_count, __ATOMIC_RELEASE);
    update_high_water(depth + message_count);
    return true;
  }

  bool begin_staged(uint32_t message_count) {
    if (staged_active_ || message_count == 0u ||
        message_count > OTIS_EVIDENCE_QUEUE_DEPTH)
      return false;
    const uint32_t tail = __atomic_load_n(&tail_, __ATOMIC_RELAXED);
    const uint32_t head = __atomic_load_n(&head_, __ATOMIC_ACQUIRE);
    const uint32_t current_depth = tail - head;
    if (current_depth > OTIS_EVIDENCE_QUEUE_DEPTH ||
        message_count > OTIS_EVIDENCE_QUEUE_DEPTH - current_depth)
      return false;
    staged_tail_ = tail;
    staged_expected_ = message_count;
    staged_count_ = 0u;
    staged_active_ = true;
    return true;
  }

  bool append_staged(const OtisEvidenceFrameMessage &message) {
    if (!staged_active_ || staged_count_ >= staged_expected_) return false;
    slots_[(staged_tail_ + staged_count_) % OTIS_EVIDENCE_QUEUE_DEPTH] =
        message;
    ++staged_count_;
    return true;
  }

  bool commit_staged() {
    if (!staged_active_ || staged_count_ != staged_expected_) return false;
    const uint32_t released_tail = staged_tail_ + staged_expected_;
    const uint32_t head = __atomic_load_n(&head_, __ATOMIC_ACQUIRE);
    const uint32_t released_depth = released_tail - head;
    __atomic_store_n(&tail_, released_tail, __ATOMIC_RELEASE);
    update_high_water(released_depth);
    staged_active_ = false;
    staged_tail_ = 0u;
    staged_expected_ = 0u;
    staged_count_ = 0u;
    return true;
  }

  void cancel_staged() {
    staged_active_ = false;
    staged_tail_ = 0u;
    staged_expected_ = 0u;
    staged_count_ = 0u;
  }

  bool can_push(uint32_t message_count) const {
    if (staged_active_ || message_count == 0u ||
        message_count > OTIS_EVIDENCE_QUEUE_DEPTH)
      return false;
    const uint32_t tail = __atomic_load_n(&tail_, __ATOMIC_RELAXED);
    const uint32_t head = __atomic_load_n(&head_, __ATOMIC_ACQUIRE);
    const uint32_t current_depth = tail - head;
    return current_depth <= OTIS_EVIDENCE_QUEUE_DEPTH &&
           message_count <= OTIS_EVIDENCE_QUEUE_DEPTH - current_depth;
  }

  bool try_pop(OtisEvidenceFrameMessage *message) {
    if (message == nullptr) return false;
    const uint32_t head = __atomic_load_n(&head_, __ATOMIC_RELAXED);
    const uint32_t tail = __atomic_load_n(&tail_, __ATOMIC_ACQUIRE);
    if (head == tail) return false;

    *message = slots_[head % OTIS_EVIDENCE_QUEUE_DEPTH];
    __atomic_store_n(&head_, head + 1u, __ATOMIC_RELEASE);
    return true;
  }

  uint32_t depth() const {
    const uint32_t tail = __atomic_load_n(&tail_, __ATOMIC_ACQUIRE);
    const uint32_t head = __atomic_load_n(&head_, __ATOMIC_ACQUIRE);
    return tail - head;
  }

  uint32_t high_water() const {
    return __atomic_load_n(&high_water_, __ATOMIC_ACQUIRE);
  }

  bool staging() const { return staged_active_; }

 private:
  void update_high_water(uint32_t candidate) {
    uint32_t observed = __atomic_load_n(&high_water_, __ATOMIC_RELAXED);
    while (candidate > observed &&
           !__atomic_compare_exchange_n(&high_water_, &observed, candidate,
                                        false, __ATOMIC_RELAXED,
                                        __ATOMIC_RELAXED)) {
    }
  }

  OtisEvidenceFrameMessage slots_[OTIS_EVIDENCE_QUEUE_DEPTH];
  alignas(4) uint32_t head_;
  alignas(4) uint32_t tail_;
  alignas(4) uint32_t high_water_;
  uint32_t staged_tail_;
  uint32_t staged_expected_;
  uint32_t staged_count_;
  bool staged_active_;
};

OtisEvidenceBurstQueue evidence_to_service;
OtisSpscQueue<OtisTelemetryMessage, OTIS_TELEMETRY_QUEUE_DEPTH>
    telemetry_to_service;
OtisSpscQueue<OtisPhasePreviewRecordMessage, OTIS_PHASE_PREVIEW_QUEUE_DEPTH>
    phase_preview_to_service;
OtisSpscQueue<OtisMonitorObservationMessage, OTIS_MONITOR_OBSERVATION_QUEUE_DEPTH>
    monitor_observation_to_service;

uint32_t telemetry_dropped = 0u;
uint32_t monitor_observation_dropped = 0u;
uint32_t observation_dropped = 0u;
uint32_t evidence_dropped_frames = 0u;
uint32_t evidence_dropped_bursts = 0u;
uint32_t phase_preview_dropped = 0u;
uint32_t critical_dropped = 0u;
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

void add_saturating(uint32_t *value, uint32_t count) {
  uint32_t observed = __atomic_load_n(value, __ATOMIC_RELAXED);
  while (observed != UINT32_MAX) {
    const uint32_t next = count > UINT32_MAX - observed
                              ? UINT32_MAX : observed + count;
    if (__atomic_compare_exchange_n(value, &observed, next, false,
                                    __ATOMIC_RELAXED, __ATOMIC_RELAXED))
      return;
  }
}

void note_evidence_drop(uint32_t message_count) {
  add_saturating(&evidence_dropped_frames, message_count);
  increment_saturating(&evidence_dropped_bursts);
}

uint32_t service_sequence(const OtisServiceMessage &message) {
  switch (message.kind) {
    case OtisServiceMessageKind::ReceiverQualification:
      return message.receiver.sequence;
    case OtisServiceMessageKind::Environment:
      return message.environment.sequence;
    case OtisServiceMessageKind::AppliedDacState:
      return message.dac.sequence;
    case OtisServiceMessageKind::RunControl:
      return message.run_control.sequence;
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
      return message.dac.published_ticks;
    case OtisServiceMessageKind::RunControl:
      return message.run_control.published_ticks;
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
  const bool priority_hold = message != nullptr &&
      message->kind == OtisServiceMessageKind::RunControl &&
      message->run_control.kind == OtisRunControlKind::Mode &&
      message->run_control.instrument_command.mode == OtisInstrumentMode::Hold;
  __atomic_store_n(&service_fault_depth,
                   priority_hold ? priority_hold_to_timing.depth()
                                 : service_to_timing.depth(),
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

}  // namespace

void otis_dual_core_partition_reset(void) {
  service_to_timing.reset();
  priority_hold_to_timing.reset();
  observation_to_service.reset();
  critical_to_service.reset();
  instrument_write_to_service.reset();
  instrument_application_to_timing.reset();
  evidence_to_service.reset();
  telemetry_to_service.reset();
  phase_preview_to_service.reset();
  monitor_observation_to_service.reset();
  __atomic_store_n(&telemetry_dropped, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&monitor_observation_dropped, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&observation_dropped, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&evidence_dropped_frames, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&evidence_dropped_bursts, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&phase_preview_dropped, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&critical_dropped, 0u, __ATOMIC_RELAXED);
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
  const bool priority_hold =
      message != nullptr && message->kind == OtisServiceMessageKind::RunControl &&
      message->run_control.kind == OtisRunControlKind::Mode &&
      message->run_control.instrument_command.mode == OtisInstrumentMode::Hold;
  if (message != nullptr &&
      (priority_hold ? priority_hold_to_timing.try_push(*message)
                     : service_to_timing.try_push(*message))) {
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
  if (!priority_hold_to_timing.try_pop(message) &&
      !service_to_timing.try_pop(message)) return false;
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

void otis_dual_core_set_observation_diagnostic_clock(
    OtisObservationDiagnosticClock reader) {
  observation_diagnostic_clock = reader;
}

bool otis_dual_core_publish_observation(
    const OtisObservationMessage *message) {
  if (message != nullptr && observation_to_service.try_push_with_precommit(
          *message, [](OtisObservationMessage &slot) {
            slot.queue_clock_valid = observation_diagnostic_clock != nullptr;
            slot.queue_consumed_ticks = 0u;
            slot.queue_clock_ambiguous = false;
            const uint64_t precommit = slot.queue_clock_valid
                ? observation_diagnostic_clock() : 0u;
            slot.queue_precommit_ticks = static_cast<uint32_t>(precommit);
            slot.queue_precommit_high = static_cast<uint32_t>(precommit >> 32);
          }))
    return true;
  increment_saturating(&observation_dropped);
  return false;
}

bool otis_dual_core_take_observation(OtisObservationMessage *message) {
  if (!observation_to_service.try_pop(message)) return false;
  if (message->queue_clock_valid && observation_diagnostic_clock != nullptr) {
    const uint64_t consumed = observation_diagnostic_clock();
    const uint64_t precommit =
        (static_cast<uint64_t>(message->queue_precommit_high) << 32) |
        message->queue_precommit_ticks;
    message->queue_consumed_ticks = static_cast<uint32_t>(consumed);
    // The full hardware coordinate disambiguates even a complete low32 wrap.
    // Long residence and clock restart are diagnostic-local ambiguity only.
    message->queue_clock_ambiguous = consumed < precommit ||
        consumed - precommit >= (UINT64_C(1) << 31);
  } else {
    message->queue_clock_valid = false;
    message->queue_clock_ambiguous = false;
    message->queue_consumed_ticks = 0u;
  }
  return true;
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
  increment_saturating(&critical_dropped);
  return false;
}

bool otis_dual_core_take_critical(OtisCriticalRecordMessage *message) {
  return critical_to_service.try_pop(message);
}

bool otis_dual_core_publish_instrument_write(const OtisInstrumentWrite *write) {
  if (write != nullptr && instrument_write_to_service.try_push(*write))
    return true;
  otis_dual_core_latch_fault(OtisPartitionFault::InstrumentWriteExhausted);
  return false;
}

bool otis_dual_core_take_instrument_write(OtisInstrumentWrite *write) {
  return instrument_write_to_service.try_pop(write);
}

bool otis_dual_core_publish_instrument_application(
    const OtisInstrumentApplication *application) {
  if (application != nullptr &&
      instrument_application_to_timing.try_push(*application))
    return true;
  otis_dual_core_latch_fault(OtisPartitionFault::ServiceToTimingExhausted);
  return false;
}

bool otis_dual_core_take_instrument_application(
    OtisInstrumentApplication *application) {
  return instrument_application_to_timing.try_pop(application);
}

bool otis_dual_core_publish_evidence(
    const OtisEvidenceFrameMessage *message) {
  return otis_dual_core_publish_evidence_burst(message, 1u);
}

bool otis_dual_core_publish_evidence_burst(
    const OtisEvidenceFrameMessage *messages, uint32_t message_count) {
  bool valid = messages != nullptr && message_count > 0u &&
               message_count <= OTIS_EVIDENCE_QUEUE_DEPTH;
  if (valid) {
    for (uint32_t index = 0u; index < message_count; ++index) {
      if (messages[index].length == 0u ||
          messages[index].length >= OTIS_EVIDENCE_FRAME_CAPACITY) {
        valid = false;
      }
    }
  }
  if (!valid) {
    otis_dual_core_latch_fault(OtisPartitionFault::EvidenceIntegrityFault);
    return false;
  }
  if (evidence_to_service.staging()) {
    otis_dual_core_latch_fault(OtisPartitionFault::EvidenceIntegrityFault);
    return false;
  }
  if (evidence_to_service.try_push_burst(messages, message_count)) return true;
  note_evidence_drop(message_count);
  return false;
}

bool otis_dual_core_evidence_can_publish(uint32_t message_count) {
  return evidence_to_service.can_push(message_count);
}

bool otis_dual_core_begin_evidence_burst(uint32_t message_count) {
  if (message_count == 0u || message_count > OTIS_EVIDENCE_QUEUE_DEPTH) {
    otis_dual_core_latch_fault(OtisPartitionFault::EvidenceIntegrityFault);
    return false;
  }
  if (evidence_to_service.staging()) {
    otis_dual_core_latch_fault(OtisPartitionFault::EvidenceIntegrityFault);
    return false;
  }
  if (evidence_to_service.begin_staged(message_count)) return true;
  note_evidence_drop(message_count);
  return false;
}

bool otis_dual_core_append_evidence_burst(
    const OtisEvidenceFrameMessage *message) {
  if (message != nullptr && message->length > 0u &&
      message->length < OTIS_EVIDENCE_FRAME_CAPACITY &&
      evidence_to_service.append_staged(*message))
    return true;
  otis_dual_core_latch_fault(OtisPartitionFault::EvidenceIntegrityFault);
  return false;
}

bool otis_dual_core_commit_evidence_burst(void) {
  if (evidence_to_service.commit_staged()) return true;
  otis_dual_core_latch_fault(OtisPartitionFault::EvidenceIntegrityFault);
  return false;
}

void otis_dual_core_cancel_evidence_burst(void) {
  evidence_to_service.cancel_staged();
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
  return false;
}

bool otis_dual_core_take_telemetry(OtisTelemetryMessage *message) {
  return telemetry_to_service.try_pop(message);
}

bool otis_dual_core_publish_phase_preview(
    const OtisPhasePreviewRecordMessage *message) {
  if (message != nullptr && phase_preview_to_service.try_push(*message))
    return true;
  increment_saturating(&phase_preview_dropped);
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
  stats->priority_hold_depth = priority_hold_to_timing.depth();
  stats->priority_hold_high_water = priority_hold_to_timing.high_water();
  stats->observation_depth = observation_to_service.depth();
  stats->observation_high_water = observation_to_service.high_water();
  stats->observation_dropped =
      __atomic_load_n(&observation_dropped, __ATOMIC_ACQUIRE);
  stats->critical_depth = critical_to_service.depth();
  stats->critical_high_water = critical_to_service.high_water();
  stats->critical_dropped =
      __atomic_load_n(&critical_dropped, __ATOMIC_ACQUIRE);
  stats->evidence_depth = evidence_to_service.depth();
  stats->evidence_high_water = evidence_to_service.high_water();
  stats->evidence_dropped_frames =
      __atomic_load_n(&evidence_dropped_frames, __ATOMIC_ACQUIRE);
  stats->evidence_dropped_bursts =
      __atomic_load_n(&evidence_dropped_bursts, __ATOMIC_ACQUIRE);
  stats->telemetry_depth = telemetry_to_service.depth();
  stats->telemetry_high_water = telemetry_to_service.high_water();
  stats->telemetry_dropped =
      __atomic_load_n(&telemetry_dropped, __ATOMIC_ACQUIRE);
  stats->phase_preview_depth = phase_preview_to_service.depth();
  stats->phase_preview_high_water = phase_preview_to_service.high_water();
  stats->phase_preview_dropped =
      __atomic_load_n(&phase_preview_dropped, __ATOMIC_ACQUIRE);
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
    case OtisPartitionFault::BootHandshakeTimeout:
      return "boot_handshake_timeout";
    case OtisPartitionFault::ServiceToTimingExhausted:
      return "service_to_timing_queue_exhausted";
    case OtisPartitionFault::InstrumentWriteExhausted:
      return "instrument_write_queue_exhausted";
    case OtisPartitionFault::EvidenceIntegrityFault:
      return "evidence_integrity_fault";
    case OtisPartitionFault::PhasePreviewFault:
      return "phase_frequency_estimate_processing_fault";
    case OtisPartitionFault::InstrumentApplicationMismatch:
      return "instrument_application_mismatch";
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
    case OtisTimingProgressPhase::BoundaryDrain:
      return "boundary_drain";
    case OtisTimingProgressPhase::CaptureDrain:
      return "capture_drain";
    case OtisTimingProgressPhase::GateService:
      return "gate_service";
    case OtisTimingProgressPhase::FrequencyEstimatePrepare:
      return "frequency_estimate_prepare";
    case OtisTimingProgressPhase::FrequencyEstimateFormat:
      return "frequency_estimate_format";
    case OtisTimingProgressPhase::FrequencyEstimatePublish:
      return "frequency_estimate_publish";
    case OtisTimingProgressPhase::AdaptiveHybridPrepare:
      return "adaptive_hybrid_regulation_prepare";
    case OtisTimingProgressPhase::AdaptiveHybridFormat:
      return "adaptive_hybrid_regulation_format";
    case OtisTimingProgressPhase::AdaptiveHybridPublish:
      return "adaptive_hybrid_regulation_publish";
    case OtisTimingProgressPhase::PhasePreview:
      return "phase_frequency_estimate";
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
    case OtisServiceMessageKind::RunControl:
      return "run_control";
  }
  return "unknown";
}
