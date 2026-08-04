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
OtisSpscQueue<OtisTelemetryMessage, OTIS_TELEMETRY_QUEUE_DEPTH>
    telemetry_to_service;

uint32_t telemetry_dropped = 0u;
uint8_t partition_fault = static_cast<uint8_t>(OtisPartitionFault::None);
bool fail_static = false;
bool timing_owner_active = false;

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
  telemetry_to_service.reset();
  __atomic_store_n(&telemetry_dropped, 0u, __ATOMIC_RELAXED);
  __atomic_store_n(&partition_fault,
                   static_cast<uint8_t>(OtisPartitionFault::None),
                   __ATOMIC_RELEASE);
  __atomic_store_n(&fail_static, false, __ATOMIC_RELEASE);
  __atomic_store_n(&timing_owner_active, false, __ATOMIC_RELEASE);
}

void otis_dual_core_set_timing_owner_active(bool active) {
  __atomic_store_n(&timing_owner_active, active, __ATOMIC_RELEASE);
}

bool otis_dual_core_timing_owner_active(void) {
  return __atomic_load_n(&timing_owner_active, __ATOMIC_ACQUIRE);
}

bool otis_dual_core_publish_service(const OtisServiceMessage *message) {
  if (message != nullptr && service_to_timing.try_push(*message)) return true;
  otis_dual_core_latch_fault(OtisPartitionFault::ServiceToTimingExhausted);
  return false;
}

bool otis_dual_core_take_service(OtisServiceMessage *message) {
  return service_to_timing.try_pop(message);
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

bool otis_dual_core_publish_critical(
    const OtisCriticalRecordMessage *message) {
  if (message != nullptr && critical_to_service.try_push(*message)) return true;
  otis_dual_core_latch_fault(OtisPartitionFault::CriticalExhausted);
  return false;
}

bool otis_dual_core_take_critical(OtisCriticalRecordMessage *message) {
  return critical_to_service.try_pop(message);
}

bool otis_dual_core_publish_telemetry(const OtisTelemetryMessage *message) {
  if (message != nullptr && telemetry_to_service.try_push(*message)) return true;
  increment_saturating(&telemetry_dropped);
  return false;
}

bool otis_dual_core_take_telemetry(OtisTelemetryMessage *message) {
  return telemetry_to_service.try_pop(message);
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
  *stats = {
      service_to_timing.depth(),
      service_to_timing.high_water(),
      observation_to_service.depth(),
      observation_to_service.high_water(),
      critical_to_service.depth(),
      critical_to_service.high_water(),
      telemetry_to_service.depth(),
      telemetry_to_service.high_water(),
      __atomic_load_n(&telemetry_dropped, __ATOMIC_ACQUIRE),
      static_cast<OtisPartitionFault>(
          __atomic_load_n(&partition_fault, __ATOMIC_ACQUIRE)),
      __atomic_load_n(&fail_static, __ATOMIC_ACQUIRE),
  };
}

const char *otis_partition_fault_name(OtisPartitionFault fault) {
  switch (fault) {
    case OtisPartitionFault::None:
      return "none";
    case OtisPartitionFault::ServiceToTimingExhausted:
      return "service_to_timing_queue_exhausted";
    case OtisPartitionFault::ObservationExhausted:
      return "raw_observation_queue_exhausted";
    case OtisPartitionFault::CriticalExhausted:
      return "critical_queue_exhausted";
    case OtisPartitionFault::ActuatorTimeout:
      return "actuator_acknowledgement_timeout";
    case OtisPartitionFault::ActuatorAcknowledgementMismatch:
      return "actuator_acknowledgement_mismatch";
  }
  return "unknown_partition_fault";
}

void otis_actuator_guard_init(OtisActuatorTransactionGuard *guard) {
  if (guard == nullptr) return;
  *guard = {};
  guard->state = OtisActuatorGuardState::Idle;
  guard->reason = "idle";
}

bool otis_actuator_guard_start(OtisActuatorTransactionGuard *guard,
                               const OtisCrossCoreActuatorRequest *request,
                               uint64_t now_ticks) {
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
      request->nonce == 0u || request->deadline_ticks <= now_ticks) {
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
                                        uint64_t now_ticks) {
  if (guard == nullptr) return false;
  if ((guard->state == OtisActuatorGuardState::AwaitingAcceptance ||
       guard->state == OtisActuatorGuardState::AwaitingApplication) &&
      now_ticks > guard->pending.deadline_ticks) {
    guard_fault(guard, "actuator_acknowledgement_deadline_expired",
                OtisPartitionFault::ActuatorTimeout);
    return false;
  }
  return guard->state != OtisActuatorGuardState::Fault;
}
