#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "otis_dual_core_partition.h"
#include "otis_dual_core_receiver_gate.h"
#include "otis_cx317_dual_core_state.h"

namespace {

OtisObservationMessage observation(uint32_t sequence) {
  OtisObservationMessage value = {};
  value.kind = OtisObservationMessageKind::CountObservation;
  value.count.sequence = sequence;
  value.count.gate_open_ticks = static_cast<uint64_t>(sequence) * 16000000ull;
  value.count.gate_close_ticks = value.count.gate_open_ticks + 16000000ull;
  value.count.counted_edges = 10000000ull;
  value.count.channel_id = 2u;
  strcpy(value.count.source_domain, "h0_tcxo_16mhz");
  return value;
}

OtisTelemetryMessage telemetry(uint32_t sequence) {
  OtisTelemetryMessage value = {};
  value.sequence = sequence;
  strcpy(value.component, "preview");
  strcpy(value.key, "duplicate_summary");
  strcpy(value.value, "healthy");
  strcpy(value.severity, "INFO");
  return value;
}

void full_build_identity_crosses_telemetry_queue_without_truncation() {
  static const char kBuildIdentity[] =
      "73881e344f102ce8b66668f703d12fb453204c63aadc3746efcb9f3de2729aa1:"
      "f3e4ebac336bf6892064f662b77d54698f8c2b5d3c03113749f7a63d843e23f0";
  static_assert(sizeof(kBuildIdentity) == 130u,
                "fixture must contain two SHA-256 digests and a colon");
  static_assert(OTIS_TELEMETRY_VALUE_CAPACITY >= sizeof(kBuildIdentity),
                "telemetry contract cannot carry the build identity");

  otis_dual_core_partition_reset();
  OtisTelemetryMessage published = {};
  published.sequence = 1u;
  strcpy(published.component, "cx317_active");
  strcpy(published.key, "build_identity");
  const int used = snprintf(published.value, sizeof(published.value), "%s",
                            kBuildIdentity);
  assert(used == 129);
  strcpy(published.severity, "INFO");
  assert(otis_dual_core_publish_telemetry(&published));

  OtisTelemetryMessage received = {};
  assert(otis_dual_core_take_telemetry(&received));
  assert(strcmp(received.value, kBuildIdentity) == 0);
}

OtisEvidenceFrameMessage evidence(uint32_t sequence) {
  OtisEvidenceFrameMessage value = {};
  value.sequence = sequence;
  const int used = snprintf(value.data, sizeof(value.data),
                            "ACT,1,%lu,fixture\r\n",
                            static_cast<unsigned long>(sequence));
  assert(used > 0);
  value.length = static_cast<uint16_t>(used);
  return value;
}

OtisServiceMessage receiver_metadata(uint32_t sequence) {
  OtisServiceMessage value = {};
  value.kind = OtisServiceMessageKind::ReceiverQualification;
  value.receiver.sequence = sequence;
  value.receiver.satellites = 10u;
  value.receiver.fix_quality = 2u;
  value.receiver.fix_type = 3u;
  value.receiver.control_eligible = true;
  value.receiver.identity_stable = true;
  value.receiver.gsa_checksum_requalified = true;
  value.receiver.gsa_3d = true;
  return value;
}

void receiver_qualification_age_is_timer_rollover_safe() {
  constexpr uint64_t kTimerWrapTicks = (1ull << 32) * 16ull;
  constexpr uint32_t kMaximumMetadataAgeMs = 1500u;
  OtisReceiverQualificationMessage receiver = receiver_metadata(1u).receiver;
  receiver.published_ticks = kTimerWrapTicks - 4000000ull;
  receiver.metadata_age_ms = 250u;

  assert(otis_dual_core_receiver_qualified_for_control_at(
      &receiver, 12000000ull, kMaximumMetadataAgeMs));
  assert(!otis_dual_core_receiver_qualified_for_control_at(
      &receiver, 28000000ull, kMaximumMetadataAgeMs));

  receiver.published_ticks = 32000000ull;
  assert(otis_dual_core_receiver_qualified_for_control_at(
      &receiver, 36000000ull, kMaximumMetadataAgeMs));
  receiver.metadata_age_ms = kMaximumMetadataAgeMs + 1u;
  assert(!otis_dual_core_receiver_qualified_for_control_at(
      &receiver, 36000000ull, kMaximumMetadataAgeMs));
  receiver.metadata_age_ms = 250u;
  receiver.gsa_3d = false;
  assert(!otis_dual_core_receiver_qualified_for_control_at(
      &receiver, 36000000ull, kMaximumMetadataAgeMs));
}

OtisCrossCoreActuatorRequest request() {
  OtisCrossCoreActuatorRequest value = {};
  value.request_sequence = 7u;
  value.decision_sequence = 19u;
  value.source_first_sequence = 1201u;
  value.source_last_sequence = 1801u;
  value.decision_reference_ticks = 28816000000ull;
  value.deadline_ticks = 28832000000ull;
  value.authorization_sequence = 3u;
  value.nonce = 0x13579bdfu;
  value.current_applied_code = 0xA82Au;
  value.requested_code = 0xA83Fu;
  value.actionable = true;
  return value;
}

OtisCrossCoreActuatorAck acknowledgement(OtisActuatorAckKind kind) {
  const OtisCrossCoreActuatorRequest pending = request();
  OtisCrossCoreActuatorAck value = {};
  value.request_sequence = pending.request_sequence;
  value.decision_sequence = pending.decision_sequence;
  value.authorization_sequence = pending.authorization_sequence;
  value.nonce = pending.nonce;
  value.acknowledgement_ticks = pending.decision_reference_ticks + 1000u;
  value.requested_code = pending.requested_code;
  value.accepted_code = pending.requested_code;
  value.applied_code = pending.requested_code;
  value.kind = kind;
  value.i2c_ok = true;
  return value;
}

void bounded_core0_stall_preserves_raw_evidence() {
  otis_dual_core_partition_reset();
  for (uint32_t sequence = 1u; sequence <= 48u; ++sequence) {
    const OtisObservationMessage raw = observation(sequence);
    assert(otis_dual_core_publish_observation(&raw));
  }
  for (uint32_t sequence = 1u;
       sequence <= OTIS_TELEMETRY_QUEUE_DEPTH + 32u; ++sequence) {
    const OtisTelemetryMessage summary = telemetry(sequence);
    otis_dual_core_publish_telemetry(&summary);
  }

  OtisDualCoreQueueStats stats = {};
  otis_dual_core_get_stats(&stats);
  assert(!stats.fail_static);
  assert(stats.observation_depth == 48u);
  assert(stats.observation_high_water == 48u);
  assert(stats.telemetry_depth == OTIS_TELEMETRY_QUEUE_DEPTH);
  assert(stats.telemetry_dropped == 32u);

  for (uint32_t expected = 1u; expected <= 48u; ++expected) {
    OtisObservationMessage actual = {};
    assert(otis_dual_core_take_observation(&actual));
    assert(actual.kind == OtisObservationMessageKind::CountObservation);
    assert(actual.count.sequence == expected);
    assert(actual.count.counted_edges == 10000000ull);
  }
  OtisObservationMessage empty = {};
  assert(!otis_dual_core_take_observation(&empty));
}

void stage7_concurrent_health_and_active_query_burst_does_not_drop() {
  otis_dual_core_partition_reset();
  for (uint32_t sequence = 1u;
       sequence <= OTIS_STAGE7_CONCURRENT_TELEMETRY_BURST; ++sequence) {
    const OtisTelemetryMessage summary = telemetry(sequence);
    assert(otis_dual_core_publish_telemetry(&summary));
  }

  OtisDualCoreQueueStats stats = {};
  otis_dual_core_get_stats(&stats);
  assert(!stats.fail_static);
  assert(stats.telemetry_depth ==
         OTIS_STAGE7_CONCURRENT_TELEMETRY_BURST);
  assert(stats.telemetry_high_water ==
         OTIS_STAGE7_CONCURRENT_TELEMETRY_BURST);
  assert(stats.telemetry_dropped == 0u);

  for (uint32_t expected = 1u;
       expected <= OTIS_STAGE7_CONCURRENT_TELEMETRY_BURST; ++expected) {
    OtisTelemetryMessage actual = {};
    assert(otis_dual_core_take_telemetry(&actual));
    assert(actual.sequence == expected);
  }
}

void complete_evidence_frames_cross_by_value_in_order() {
  otis_dual_core_partition_reset();
  for (uint32_t sequence = 1u; sequence <= OTIS_EVIDENCE_QUEUE_DEPTH;
       ++sequence) {
    const OtisEvidenceFrameMessage frame = evidence(sequence);
    assert(otis_dual_core_publish_evidence(&frame));
  }
  OtisDualCoreQueueStats stats = {};
  otis_dual_core_get_stats(&stats);
  assert(stats.evidence_depth == OTIS_EVIDENCE_QUEUE_DEPTH);
  assert(stats.evidence_high_water == OTIS_EVIDENCE_QUEUE_DEPTH);
  assert(!stats.fail_static);
  for (uint32_t sequence = 1u; sequence <= OTIS_EVIDENCE_QUEUE_DEPTH;
       ++sequence) {
    OtisEvidenceFrameMessage frame = {};
    assert(otis_dual_core_take_evidence(&frame));
    assert(frame.sequence == sequence);
    assert(frame.length > 0u);
    assert(strncmp(frame.data, "ACT,1,", 6u) == 0);
  }
}

void service_plane_load_matrix_preserves_timing_state() {
  // These modes exercise the common architectural effect of each required
  // Core 0 load: delayed Core 0 draining while Core 1 continues publishing
  // raw observations. GNSS additionally publishes bounded immutable metadata.
  const char *modes[] = {
      "usb_backpressure", "command_burst", "gnss_burst_malformed",
      "environment_i2c_delay", "telemetry_saturation",
  };
  for (const char *mode : modes) {
    otis_dual_core_partition_reset();
    if (strcmp(mode, "gnss_burst_malformed") == 0) {
      for (uint32_t sequence = 1u; sequence <= 8u; ++sequence) {
        const OtisServiceMessage metadata = receiver_metadata(sequence);
        assert(otis_dual_core_publish_service(&metadata));
      }
    }
    for (uint32_t sequence = 1u; sequence <= 60u; ++sequence) {
      const OtisObservationMessage raw = observation(sequence);
      assert(otis_dual_core_publish_observation(&raw));
      const OtisTelemetryMessage summary = telemetry(sequence);
      assert(otis_dual_core_publish_telemetry(&summary));
    }
    for (uint32_t sequence = 61u;
         sequence <= OTIS_TELEMETRY_QUEUE_DEPTH + 24u; ++sequence) {
      const OtisTelemetryMessage summary = telemetry(sequence);
      otis_dual_core_publish_telemetry(&summary);
    }

    uint32_t expected_sequence = 1u;
    uint64_t estimator_edge_sum = 0u;
    OtisObservationMessage raw = {};
    while (otis_dual_core_take_observation(&raw)) {
      assert(raw.count.sequence == expected_sequence++);
      estimator_edge_sum += raw.count.counted_edges;
    }
    assert(expected_sequence == 61u);
    assert(estimator_edge_sum == 600000000ull);

    OtisServiceMessage metadata = {};
    uint32_t metadata_count = 0u;
    while (otis_dual_core_take_service(&metadata)) {
      assert(metadata.kind == OtisServiceMessageKind::ReceiverQualification);
      assert(metadata.receiver.sequence == ++metadata_count);
      assert(metadata.receiver.control_eligible);
    }
    assert(metadata_count ==
           (strcmp(mode, "gnss_burst_malformed") == 0 ? 8u : 0u));

    OtisDualCoreQueueStats stats = {};
    otis_dual_core_get_stats(&stats);
    assert(!stats.fail_static);
    assert(stats.observation_high_water == 60u);
    assert(stats.telemetry_high_water == OTIS_TELEMETRY_QUEUE_DEPTH);
    assert(stats.telemetry_dropped == 24u);
    OtisCriticalRecordMessage critical = {};
    assert(!otis_dual_core_take_critical(&critical));
  }
}

void non_droppable_exhaustion_is_fail_static() {
  otis_dual_core_partition_reset();
  for (uint32_t sequence = 1u;
       sequence <= OTIS_OBSERVATION_QUEUE_DEPTH; ++sequence) {
    const OtisObservationMessage raw = observation(sequence);
    assert(otis_dual_core_publish_observation(&raw));
  }
  const OtisObservationMessage overflow =
      observation(OTIS_OBSERVATION_QUEUE_DEPTH + 1u);
  assert(!otis_dual_core_publish_observation(&overflow));
  OtisDualCoreQueueStats stats = {};
  otis_dual_core_get_stats(&stats);
  assert(stats.fail_static);
  assert(stats.fault == OtisPartitionFault::ObservationExhausted);
}

void every_non_droppable_queue_exhaustion_is_fail_static() {
  otis_dual_core_partition_reset();
  for (uint32_t sequence = 1u;
       sequence <= OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH; ++sequence) {
    const OtisServiceMessage message = receiver_metadata(sequence);
    assert(otis_dual_core_publish_service(&message));
  }
  const OtisServiceMessage service_overflow =
      receiver_metadata(OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH + 1u);
  assert(!otis_dual_core_publish_service(&service_overflow));
  OtisDualCoreQueueStats stats = {};
  otis_dual_core_get_stats(&stats);
  assert(stats.fail_static);
  assert(stats.fault == OtisPartitionFault::ServiceToTimingExhausted);

  otis_dual_core_partition_reset();
  OtisCriticalRecordMessage record = {};
  record.kind = OtisCriticalMessageKind::StateTransition;
  for (uint32_t sequence = 1u; sequence <= OTIS_CRITICAL_QUEUE_DEPTH;
       ++sequence) {
    record.sequence = sequence;
    assert(otis_dual_core_publish_critical(&record));
  }
  record.sequence++;
  assert(!otis_dual_core_publish_critical(&record));
  otis_dual_core_get_stats(&stats);
  assert(stats.fail_static);
  assert(stats.fault == OtisPartitionFault::CriticalExhausted);

  otis_dual_core_partition_reset();
  for (uint32_t sequence = 1u; sequence <= OTIS_EVIDENCE_QUEUE_DEPTH;
       ++sequence) {
    const OtisEvidenceFrameMessage frame = evidence(sequence);
    assert(otis_dual_core_publish_evidence(&frame));
  }
  const OtisEvidenceFrameMessage evidence_overflow =
      evidence(OTIS_EVIDENCE_QUEUE_DEPTH + 1u);
  assert(!otis_dual_core_publish_evidence(&evidence_overflow));
  otis_dual_core_get_stats(&stats);
  assert(stats.fail_static);
  assert(stats.fault == OtisPartitionFault::EvidenceExhausted);
}

void actuator_transaction_requires_exact_two_phase_ack() {
  otis_dual_core_partition_reset();
  OtisActuatorTransactionGuard guard = {};
  otis_actuator_guard_init(&guard);
  const OtisCrossCoreActuatorRequest pending = request();
  assert(otis_actuator_guard_start(
      &guard, &pending, pending.decision_reference_ticks));
  assert(guard.state == OtisActuatorGuardState::AwaitingAcceptance);

  const OtisCrossCoreActuatorAck accepted =
      acknowledgement(OtisActuatorAckKind::Accepted);
  assert(otis_actuator_guard_acknowledge(&guard, &accepted));
  assert(guard.state == OtisActuatorGuardState::AwaitingApplication);

  const OtisCrossCoreActuatorAck applied =
      acknowledgement(OtisActuatorAckKind::Applied);
  assert(otis_actuator_guard_acknowledge(&guard, &applied));
  assert(guard.state == OtisActuatorGuardState::Applied);
  assert(strcmp(guard.reason, "exact_application_confirmed") == 0);
  assert(!otis_dual_core_fail_static());
}

void stale_ack_and_timeout_fault_without_retry() {
  otis_dual_core_partition_reset();
  OtisActuatorTransactionGuard guard = {};
  otis_actuator_guard_init(&guard);
  const OtisCrossCoreActuatorRequest pending = request();
  assert(otis_actuator_guard_start(
      &guard, &pending, pending.decision_reference_ticks));
  OtisCrossCoreActuatorAck wrong =
      acknowledgement(OtisActuatorAckKind::Accepted);
  wrong.nonce++;
  assert(!otis_actuator_guard_acknowledge(&guard, &wrong));
  assert(guard.state == OtisActuatorGuardState::Fault);
  assert(otis_dual_core_fail_static());

  otis_dual_core_partition_reset();
  otis_actuator_guard_init(&guard);
  assert(otis_actuator_guard_start(
      &guard, &pending, pending.decision_reference_ticks));
  assert(!otis_actuator_guard_check_deadline(
      &guard, pending.deadline_ticks + 1u));
  assert(guard.state == OtisActuatorGuardState::Fault);
  OtisDualCoreQueueStats stats = {};
  otis_dual_core_get_stats(&stats);
  assert(stats.fault == OtisPartitionFault::ActuatorTimeout);
}

void applied_ack_advances_stale_periodic_dac_state_before_health() {
  OtisCx317StaticCodeState state = {};
  OtisAppliedDacStateMessage stale = {};
  stale.initialized = true;
  stale.i2c_ok = true;
  stale.requested_applied_match = true;
  stale.requested_code = 0xA800u;
  stale.applied_code = 0xA800u;
  assert(!otis_cx317_dual_core_static_state_on_periodic(&state, &stale));
  assert(state.available);
  assert(state.applied_code == 0xA800u);

  OtisCrossCoreActuatorAck applied =
      acknowledgement(OtisActuatorAckKind::Applied);
  applied.requested_code = 0xA815u;
  applied.accepted_code = 0xA815u;
  applied.applied_code = 0xA815u;
  assert(otis_cx317_dual_core_static_state_on_applied_ack(
      &state, &applied, true));
  assert(state.available);
  assert(state.requested_applied_match);
  assert(state.i2c_ok);
  assert(state.applied_code == 0xA815u);

  OtisCrossCoreActuatorAck rejected = applied;
  rejected.applied_code = 0xA82Au;
  assert(!otis_cx317_dual_core_static_state_on_applied_ack(
      &state, &rejected, false));
  assert(state.applied_code == 0xA815u);
}

}  // namespace

int main() {
  full_build_identity_crosses_telemetry_queue_without_truncation();
  receiver_qualification_age_is_timer_rollover_safe();
  bounded_core0_stall_preserves_raw_evidence();
  stage7_concurrent_health_and_active_query_burst_does_not_drop();
  service_plane_load_matrix_preserves_timing_state();
  complete_evidence_frames_cross_by_value_in_order();
  non_droppable_exhaustion_is_fail_static();
  every_non_droppable_queue_exhaustion_is_fail_static();
  actuator_transaction_requires_exact_two_phase_ack();
  stale_ack_and_timeout_fault_without_retry();
  applied_ack_advances_stale_periodic_dac_state_before_health();
  return 0;
}
