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

OtisMonitorObservationMessage monitor_observation(uint32_t sequence) {
  OtisMonitorObservationMessage value = {};
  value.kind = OtisMonitorObservationKind::Snapshot;
  value.session = 17u;
  value.reference_session = 23u;
  value.sequence = sequence;
  value.cumulative_down_counter = 0xffff0000u - sequence;
  value.reference_sequence = sequence - 1u;
  value.reference_timestamp_ticks =
      static_cast<uint64_t>(sequence) * 16000000ull;
  value.status = 0x30u;
  value.channel_id = 3u;
  return value;
}

void forwarded_monitor_queue_is_lossy_and_isolated_from_authoritative_path() {
  otis_dual_core_partition_reset();

  const OtisMonitorObservationMessage first = monitor_observation(1u);
  assert(otis_dual_core_publish_monitor_observation(&first));
  OtisMonitorObservationMessage received = {};
  assert(otis_dual_core_take_monitor_observation(&received));
  assert(received.kind == OtisMonitorObservationKind::Snapshot);
  assert(received.session == first.session);
  assert(received.reference_session == first.reference_session);
  assert(received.sequence == first.sequence);
  assert(received.cumulative_down_counter == first.cumulative_down_counter);
  assert(received.reference_sequence == first.reference_sequence);
  assert(received.reference_timestamp_ticks == first.reference_timestamp_ticks);
  assert(received.status == first.status);
  assert(received.channel_id == first.channel_id);

  for (uint32_t sequence = 2u;
       sequence < OTIS_MONITOR_OBSERVATION_QUEUE_DEPTH + 2u; ++sequence) {
    const OtisMonitorObservationMessage value = monitor_observation(sequence);
    assert(otis_dual_core_publish_monitor_observation(&value));
  }

  OtisDualCoreQueueStats stats = {};
  otis_dual_core_get_stats(&stats);
  assert(stats.monitor_observation_depth ==
         OTIS_MONITOR_OBSERVATION_QUEUE_DEPTH);
  assert(stats.monitor_observation_high_water ==
         OTIS_MONITOR_OBSERVATION_QUEUE_DEPTH);
  assert(stats.monitor_observation_dropped == 0u);
  assert(stats.fault == OtisPartitionFault::None);
  assert(!stats.fail_static);

  const OtisMonitorObservationMessage overflow =
      monitor_observation(OTIS_MONITOR_OBSERVATION_QUEUE_DEPTH + 2u);
  assert(!otis_dual_core_publish_monitor_observation(&overflow));
  otis_dual_core_get_stats(&stats);
  assert(stats.monitor_observation_depth ==
         OTIS_MONITOR_OBSERVATION_QUEUE_DEPTH);
  assert(stats.monitor_observation_high_water ==
         OTIS_MONITOR_OBSERVATION_QUEUE_DEPTH);
  assert(stats.monitor_observation_dropped == 1u);
  assert(stats.fault == OtisPartitionFault::None);
  assert(!stats.fail_static);
  assert(!otis_dual_core_fail_static());

  const OtisObservationMessage authoritative = observation(991u);
  assert(otis_dual_core_publish_observation(&authoritative));
  OtisObservationMessage authoritative_received = {};
  assert(otis_dual_core_take_observation(&authoritative_received));
  assert(authoritative_received.kind == authoritative.kind);
  assert(authoritative_received.count.sequence == authoritative.count.sequence);
  assert(authoritative_received.count.counted_edges ==
         authoritative.count.counted_edges);
  assert(authoritative_received.count.channel_id == authoritative.count.channel_id);
  assert(strcmp(authoritative_received.count.source_domain,
                authoritative.count.source_domain) == 0);

  for (uint32_t sequence = 2u;
       sequence < OTIS_MONITOR_OBSERVATION_QUEUE_DEPTH + 2u; ++sequence) {
    assert(otis_dual_core_take_monitor_observation(&received));
    assert(received.sequence == sequence);
  }
  assert(!otis_dual_core_take_monitor_observation(&received));
  otis_dual_core_get_stats(&stats);
  assert(stats.monitor_observation_depth == 0u);
  assert(stats.monitor_observation_high_water ==
         OTIS_MONITOR_OBSERVATION_QUEUE_DEPTH);
  assert(stats.monitor_observation_dropped == 1u);
  assert(stats.fault == OtisPartitionFault::None);
  assert(!stats.fail_static);
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

  static const char kLongestHealthKey[] =
      "boundary_sequence_duplicate_count";
  static_assert(OTIS_TELEMETRY_KEY_CAPACITY >= sizeof(kLongestHealthKey),
                "telemetry contract cannot carry the longest health key");
  OtisTelemetryMessage keyed = {};
  strcpy(keyed.component, "pps_gate");
  strcpy(keyed.key, kLongestHealthKey);
  strcpy(keyed.value, "0");
  strcpy(keyed.severity, "INFO");
  assert(otis_dual_core_publish_telemetry(&keyed));
  assert(otis_dual_core_take_telemetry(&received));
  assert(strcmp(received.key, kLongestHealthKey) == 0);
}

void forced_boot_publish_drain_interleavings_are_exactly_once() {
  // Enumerate every order-preserving interleaving of three Core 1 boot
  // publishes and three Core 0 drains. This is the startup schedule that
  // previously tempted the consumer to republish into the producer queue.
  uint32_t valid_schedules = 0u;
  for (uint32_t schedule = 0u; schedule < 64u; ++schedule) {
    uint32_t publish_count = 0u;
    uint32_t take_count = 0u;
    bool valid = true;
    uint32_t received[3] = {};
    otis_dual_core_partition_reset();
    for (uint32_t step = 0u; step < 6u; ++step) {
      const bool publish = (schedule & (1u << step)) != 0u;
      if (publish) {
        if (publish_count == 3u) {
          valid = false;
          break;
        }
        const OtisTelemetryMessage message = telemetry(++publish_count);
        assert(otis_dual_core_publish_boot_telemetry(&message));
      } else {
        if (take_count == publish_count || take_count == 3u) {
          valid = false;
          break;
        }
        OtisTelemetryMessage message = {};
        assert(otis_dual_core_take_telemetry(&message));
        received[take_count++] = message.sequence;
      }
    }
    if (!valid || publish_count != 3u || take_count != 3u) continue;
    ++valid_schedules;
    assert(received[0] == 1u);
    assert(received[1] == 2u);
    assert(received[2] == 3u);
    OtisTelemetryMessage empty = {};
    assert(!otis_dual_core_take_telemetry(&empty));
    OtisDualCoreQueueStats stats = {};
    otis_dual_core_get_stats(&stats);
    assert(stats.telemetry_dropped == 0u);
    assert(!stats.fail_static);
  }
  assert(valid_schedules == 5u);
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

OtisPhasePreviewRecordMessage phase_preview(uint32_t sequence) {
  OtisPhasePreviewRecordMessage value = {};
  value.preview_sequence = sequence;
  value.phase_epoch = 1u;
  value.observation_sequence = sequence;
  value.capture_session = 7u;
  value.relative_phase_cycles = static_cast<int64_t>(sequence);
  value.actual_applied_code = 0xA950u;
  snprintf(value.preview_state, sizeof(value.preview_state), "%s",
           "RELATIVE_PHASE_ACQUIRE");
  return value;
}

OtisServiceMessage receiver_metadata(uint32_t sequence) {
  OtisServiceMessage value = {};
  value.kind = OtisServiceMessageKind::ReceiverQualification;
  value.receiver.sequence = sequence;
  value.receiver.published_ticks = static_cast<uint64_t>(sequence) * 100u;
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

void open_loop_range_map_keeps_d14_d8_support_during_metadata_dips() {
  assert(otis_preview_reference_valid_for_profile(true, false, true));
  assert(otis_preview_reference_valid_for_profile(true, true, true));
  assert(!otis_preview_reference_valid_for_profile(false, true, true));
  assert(!otis_preview_reference_valid_for_profile(false, false, true));

  assert(otis_preview_reference_valid_for_profile(true, true, false));
  assert(!otis_preview_reference_valid_for_profile(true, false, false));
  assert(!otis_preview_reference_valid_for_profile(false, true, false));
}

void diagnostic_queries_cross_poll_mutation_and_fault_boundaries() {
  for (uint32_t boundary = 0u; boundary < 4u; ++boundary) {
    otis_dual_core_partition_reset();
    OtisServiceMessage empty = {};
    assert(!otis_dual_core_take_service(&empty));
    if (boundary >= 1u)
      otis_dual_core_note_timing_progress(
          OtisTimingProgressPhase::CaptureBackend, 100u);

    OtisServiceMessage query = {};
    query.kind = OtisServiceMessageKind::RunControl;
    query.run_control.sequence = 20u + boundary;
    query.run_control.published_ticks = 1000u + boundary;
    query.run_control.nonce = 0xA5000000u + boundary;
    query.run_control.kind = OtisRunControlKind::DiagnosticRuntimeQuery;
    assert(otis_dual_core_publish_service(&query));
    // Overwrite the producer-side object after release. The queued immutable
    // value must not observe this later mutation.
    query.run_control.sequence = 999u;
    query.run_control.nonce = 0u;
    if (boundary >= 2u) otis_dual_core_note_timing_snapshot(7u, 83u);
    if (boundary >= 3u)
      otis_dual_core_note_timing_progress(
          OtisTimingProgressPhase::TimingHealth, 200u);

    OtisServiceMessage received = {};
    assert(otis_dual_core_take_service(&received));
    assert(received.kind == OtisServiceMessageKind::RunControl);
    assert(received.run_control.kind ==
           OtisRunControlKind::DiagnosticRuntimeQuery);
    assert(received.run_control.sequence == 20u + boundary);
    assert(received.run_control.nonce == 0xA5000000u + boundary);
  }

  // A query already released to the queue remains exact when a later Core 0
  // publish crosses capacity and latches the partition fault.
  otis_dual_core_partition_reset();
  OtisServiceMessage query = {};
  query.kind = OtisServiceMessageKind::RunControl;
  query.run_control.sequence = 77u;
  query.run_control.nonce = 0x1234u;
  query.run_control.kind = OtisRunControlKind::DiagnosticConfigQuery;
  assert(otis_dual_core_publish_service(&query));
  for (uint32_t sequence = 1u;
       sequence < OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH; ++sequence) {
    const OtisServiceMessage metadata = receiver_metadata(sequence);
    assert(otis_dual_core_publish_service(&metadata));
  }
  const OtisServiceMessage overflow =
      receiver_metadata(OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH);
  assert(!otis_dual_core_publish_service(&overflow));
  assert(otis_dual_core_fail_static());
  OtisServiceMessage received = {};
  assert(otis_dual_core_take_service(&received));
  assert(received.run_control.sequence == 77u);
  assert(received.run_control.nonce == 0x1234u);
}

OtisCrossCoreActuatorRequest request() {
  OtisCrossCoreActuatorRequest value = {};
  value.request_sequence = 7u;
  value.decision_sequence = 19u;
  value.source_first_sequence = 1201u;
  value.source_last_sequence = 1801u;
  value.decision_reference_ticks = 28816000000ull;
  value.monotonic_deadline_s = 1831u;
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
  value.rejection_reason = OtisActuatorRejectionReason::NotRejected;
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
  static_assert(OTIS_CX317_ACTIVE_STATUS_FIELD_COUNT == 63u,
                "ACTIVE status field vocabulary must remain complete");
  static_assert(OTIS_CX317_ACTIVE_STATUS_ENVELOPE_COUNT == 3u,
                "ACTIVE status must carry a complete-generation envelope");
  static_assert(OTIS_CX317_ACTIVE_STATUS_TELEMETRY_BURST == 66u,
                "ACTIVE status burst must include fields and envelope");
  static_assert(OTIS_TIMING_HEALTH_NONACTIVE_TELEMETRY_BURST == 80u,
                "fixture must bind the measured non-active health burst");
  static_assert(OTIS_TIMING_HEALTH_TELEMETRY_BURST == 146u,
                "health burst must include one complete ACTIVE status");
  static_assert(OTIS_MAXIMUM_CONCURRENT_TELEMETRY_BURST == 212u,
                "fixture must bind health plus one ACTIVE? response");
  static_assert(OTIS_TELEMETRY_QUEUE_DEPTH >=
                    OTIS_MAXIMUM_CONCURRENT_TELEMETRY_BURST,
                "telemetry queue must contain the declared concurrent burst");
  otis_dual_core_partition_reset();
  for (uint32_t sequence = 1u;
       sequence <= OTIS_MAXIMUM_CONCURRENT_TELEMETRY_BURST; ++sequence) {
    const OtisTelemetryMessage summary = telemetry(sequence);
    assert(otis_dual_core_publish_telemetry(&summary));
  }

  OtisDualCoreQueueStats stats = {};
  otis_dual_core_get_stats(&stats);
  assert(!stats.fail_static);
  assert(stats.telemetry_depth ==
         OTIS_MAXIMUM_CONCURRENT_TELEMETRY_BURST);
  assert(stats.telemetry_high_water ==
         OTIS_MAXIMUM_CONCURRENT_TELEMETRY_BURST);
  assert(stats.telemetry_dropped == 0u);

  for (uint32_t expected = 1u;
       expected <= OTIS_MAXIMUM_CONCURRENT_TELEMETRY_BURST; ++expected) {
    OtisTelemetryMessage actual = {};
    assert(otis_dual_core_take_telemetry(&actual));
    assert(actual.sequence == expected);
  }
}

void complete_telemetry_burst_admission_reserves_every_record() {
  otis_dual_core_partition_reset();
  assert(otis_dual_core_telemetry_can_publish(
      OTIS_TIMING_HEALTH_TELEMETRY_BURST));
  const uint32_t exact_prefix =
      OTIS_TELEMETRY_QUEUE_DEPTH - OTIS_TIMING_HEALTH_TELEMETRY_BURST;
  for (uint32_t sequence = 1u; sequence <= exact_prefix; ++sequence) {
    const OtisTelemetryMessage summary = telemetry(sequence);
    assert(otis_dual_core_publish_telemetry(&summary));
  }
  assert(otis_dual_core_telemetry_can_publish(
      OTIS_TIMING_HEALTH_TELEMETRY_BURST));
  const OtisTelemetryMessage one_too_many = telemetry(exact_prefix + 1u);
  assert(otis_dual_core_publish_telemetry(&one_too_many));
  assert(!otis_dual_core_telemetry_can_publish(
      OTIS_TIMING_HEALTH_TELEMETRY_BURST));
  assert(otis_dual_core_telemetry_can_publish(
      OTIS_CX317_ACTIVE_STATUS_TELEMETRY_BURST));

  otis_dual_core_partition_reset();
  const uint32_t active_pressure_prefix =
      OTIS_TELEMETRY_QUEUE_DEPTH -
      OTIS_CX317_ACTIVE_STATUS_TELEMETRY_BURST + 1u;
  for (uint32_t sequence = 1u; sequence <= active_pressure_prefix;
       ++sequence) {
    const OtisTelemetryMessage summary = telemetry(sequence);
    assert(otis_dual_core_publish_telemetry(&summary));
  }
  assert(!otis_dual_core_telemetry_can_publish(
      OTIS_CX317_ACTIVE_STATUS_TELEMETRY_BURST));
  OtisTelemetryMessage drained = {};
  assert(otis_dual_core_take_telemetry(&drained));
  assert(otis_dual_core_telemetry_can_publish(
      OTIS_CX317_ACTIVE_STATUS_TELEMETRY_BURST));
}

void boot_telemetry_exhaustion_is_bounded_and_fail_static() {
  otis_dual_core_partition_reset();
  for (uint32_t sequence = 1u; sequence <= OTIS_TELEMETRY_QUEUE_DEPTH;
       ++sequence) {
    const OtisTelemetryMessage message = telemetry(sequence);
    assert(otis_dual_core_publish_boot_telemetry(&message));
  }
  const OtisTelemetryMessage overflow =
      telemetry(OTIS_TELEMETRY_QUEUE_DEPTH + 1u);
  assert(!otis_dual_core_publish_boot_telemetry(&overflow));

  OtisDualCoreQueueStats stats = {};
  otis_dual_core_get_stats(&stats);
  assert(stats.telemetry_dropped == 1u);
  assert(stats.fail_static);
  assert(stats.fault == OtisPartitionFault::BootTelemetryExhausted);
  assert(strcmp(otis_partition_fault_name(stats.fault),
                "boot_telemetry_queue_exhausted") == 0);
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

void evidence_bursts_are_atomic_ordered_and_bounded() {
  OtisDualCoreQueueStats stats = {};
  OtisEvidenceFrameMessage received = {};

  // A successful burst appears exactly once and in producer order, with one
  // capacity/high-water transition for the complete logical publication.
  otis_dual_core_partition_reset();
  OtisEvidenceFrameMessage burst[3] = {
      evidence(101u), evidence(102u), evidence(103u)};
  assert(otis_dual_core_publish_evidence_burst(burst, 3u));
  otis_dual_core_get_stats(&stats);
  assert(stats.evidence_depth == 3u);
  assert(stats.evidence_high_water == 3u);
  assert(stats.fault == OtisPartitionFault::None);
  assert(!stats.fail_static);
  for (uint32_t sequence = 101u; sequence <= 103u; ++sequence) {
    assert(otis_dual_core_take_evidence(&received));
    assert(received.sequence == sequence);
  }
  assert(!otis_dual_core_take_evidence(&received));

  // A producer-side capacity reservation is non-mutating and cannot become
  // less true while the sole consumer drains. This permits two adjacent
  // logical bursts to retain distinct identities without risking a partial
  // lifecycle after the first burst commits.
  otis_dual_core_partition_reset();
  assert(!otis_dual_core_evidence_can_publish(0u));
  assert(!otis_dual_core_evidence_can_publish(
      OTIS_EVIDENCE_QUEUE_DEPTH + 1u));
  assert(otis_dual_core_evidence_can_publish(
      OTIS_EVIDENCE_QUEUE_DEPTH));
  assert(otis_dual_core_publish_evidence_burst(burst, 3u));
  assert(otis_dual_core_evidence_can_publish(5u));
  assert(!otis_dual_core_evidence_can_publish(6u));
  otis_dual_core_get_stats(&stats);
  assert(stats.fault == OtisPartitionFault::None);
  assert(!stats.fail_static);
  assert(otis_dual_core_take_evidence(&received));
  assert(otis_dual_core_evidence_can_publish(6u));
  while (otis_dual_core_take_evidence(&received)) {
  }

  // In-place construction writes behind the unpublished tail. The consumer
  // sees no prefix; commit reveals the complete ordered burst, while cancel
  // makes a partially formatted suffix unreachable.
  otis_dual_core_partition_reset();
  assert(otis_dual_core_begin_evidence_burst(3u));
  assert(otis_dual_core_append_evidence_burst(&burst[0]));
  assert(!otis_dual_core_take_evidence(&received));
  assert(otis_dual_core_append_evidence_burst(&burst[1]));
  assert(otis_dual_core_append_evidence_burst(&burst[2]));
  assert(!otis_dual_core_take_evidence(&received));
  assert(otis_dual_core_commit_evidence_burst());
  for (uint32_t sequence = 101u; sequence <= 103u; ++sequence) {
    assert(otis_dual_core_take_evidence(&received));
    assert(received.sequence == sequence);
  }
  assert(!otis_dual_core_take_evidence(&received));
  otis_dual_core_partition_reset();
  assert(otis_dual_core_begin_evidence_burst(3u));
  assert(otis_dual_core_append_evidence_burst(&burst[0]));
  otis_dual_core_cancel_evidence_burst();
  assert(!otis_dual_core_take_evidence(&received));
  assert(otis_dual_core_publish_evidence(&burst[1]));
  assert(otis_dual_core_take_evidence(&received));
  assert(received.sequence == 102u);

  // Insufficient capacity near full must not leak a prefix. Existing frames
  // remain intact and ordered; the failed burst changes neither depth nor
  // high-water, and uses the established fail-static evidence fault.
  otis_dual_core_partition_reset();
  for (uint32_t sequence = 1u; sequence <= 6u; ++sequence) {
    const OtisEvidenceFrameMessage frame = evidence(sequence);
    assert(otis_dual_core_publish_evidence(&frame));
  }
  OtisEvidenceFrameMessage too_large_for_remaining[3] = {
      evidence(7u), evidence(8u), evidence(9u)};
  assert(!otis_dual_core_publish_evidence_burst(too_large_for_remaining, 3u));
  otis_dual_core_get_stats(&stats);
  assert(stats.evidence_depth == 6u);
  assert(stats.evidence_high_water == 6u);
  assert(stats.fault == OtisPartitionFault::EvidenceExhausted);
  assert(stats.fail_static);
  for (uint32_t sequence = 1u; sequence <= 6u; ++sequence) {
    assert(otis_dual_core_take_evidence(&received));
    assert(received.sequence == sequence);
  }
  assert(!otis_dual_core_take_evidence(&received));

  // Consumer drainage only increases producer capacity. The next burst can
  // wrap the ring and is still committed as one ordered suffix behind the
  // previously published frames that remain.
  otis_dual_core_partition_reset();
  for (uint32_t sequence = 1u; sequence <= 7u; ++sequence) {
    const OtisEvidenceFrameMessage frame = evidence(sequence);
    assert(otis_dual_core_publish_evidence(&frame));
  }
  assert(otis_dual_core_take_evidence(&received));
  assert(received.sequence == 1u);
  assert(otis_dual_core_take_evidence(&received));
  assert(received.sequence == 2u);
  OtisEvidenceFrameMessage after_drain[3] = {
      evidence(8u), evidence(9u), evidence(10u)};
  assert(otis_dual_core_publish_evidence_burst(after_drain, 3u));
  otis_dual_core_get_stats(&stats);
  assert(stats.evidence_depth == OTIS_EVIDENCE_QUEUE_DEPTH);
  assert(stats.evidence_high_water == OTIS_EVIDENCE_QUEUE_DEPTH);
  for (uint32_t sequence = 3u; sequence <= 10u; ++sequence) {
    assert(otis_dual_core_take_evidence(&received));
    assert(received.sequence == sequence);
  }
  assert(!otis_dual_core_take_evidence(&received));

  // Validation covers every member before queue admission. A malformed
  // middle member therefore cannot publish an otherwise valid prefix.
  otis_dual_core_partition_reset();
  OtisEvidenceFrameMessage malformed[3] = {
      evidence(201u), evidence(202u), evidence(203u)};
  malformed[1].length = 0u;
  assert(!otis_dual_core_publish_evidence_burst(malformed, 3u));
  assert(!otis_dual_core_take_evidence(&received));
  otis_dual_core_get_stats(&stats);
  assert(stats.evidence_depth == 0u);
  assert(stats.evidence_high_water == 0u);
  assert(stats.fault == OtisPartitionFault::EvidenceExhausted);
  assert(stats.fail_static);

  // Zero and oversize counts are invalid. The exact-capacity boundary is
  // valid without changing order.
  otis_dual_core_partition_reset();
  assert(!otis_dual_core_publish_evidence_burst(burst, 0u));
  assert(!otis_dual_core_take_evidence(&received));
  otis_dual_core_partition_reset();
  OtisEvidenceFrameMessage boundary[OTIS_EVIDENCE_QUEUE_DEPTH + 1u] = {};
  for (uint32_t index = 0u; index < OTIS_EVIDENCE_QUEUE_DEPTH + 1u; ++index) {
    boundary[index] = evidence(301u + index);
  }
  assert(!otis_dual_core_publish_evidence_burst(
      boundary, OTIS_EVIDENCE_QUEUE_DEPTH + 1u));
  assert(!otis_dual_core_take_evidence(&received));
  otis_dual_core_partition_reset();
  assert(otis_dual_core_publish_evidence_burst(
      boundary, OTIS_EVIDENCE_QUEUE_DEPTH));
  otis_dual_core_get_stats(&stats);
  assert(stats.evidence_depth == OTIS_EVIDENCE_QUEUE_DEPTH);
  assert(stats.evidence_high_water == OTIS_EVIDENCE_QUEUE_DEPTH);
  assert(!stats.fail_static);
  for (uint32_t index = 0u; index < OTIS_EVIDENCE_QUEUE_DEPTH; ++index) {
    assert(otis_dual_core_take_evidence(&received));
    assert(received.sequence == 301u + index);
  }
  assert(!otis_dual_core_take_evidence(&received));

  // Reset clears both the latched fault and the queue's high-water history.
  const OtisEvidenceFrameMessage after_reset = evidence(401u);
  otis_dual_core_partition_reset();
  otis_dual_core_get_stats(&stats);
  assert(stats.evidence_depth == 0u);
  assert(stats.evidence_high_water == 0u);
  assert(stats.fault == OtisPartitionFault::None);
  assert(!stats.fail_static);
  assert(otis_dual_core_publish_evidence(&after_reset));
  assert(otis_dual_core_take_evidence(&received));
  assert(received.sequence == 401u);
}

void cx318_numerical_records_cross_by_value_in_order() {
  otis_dual_core_partition_reset();
  for (uint32_t sequence = 1u;
       sequence <= OTIS_PHASE_PREVIEW_QUEUE_DEPTH; ++sequence) {
    const OtisPhasePreviewRecordMessage record = phase_preview(sequence);
    assert(otis_dual_core_publish_phase_preview(&record));
  }
  OtisDualCoreQueueStats stats = {};
  otis_dual_core_get_stats(&stats);
  assert(stats.phase_preview_depth == OTIS_PHASE_PREVIEW_QUEUE_DEPTH);
  assert(stats.phase_preview_high_water == OTIS_PHASE_PREVIEW_QUEUE_DEPTH);
  assert(!stats.fail_static);
  for (uint32_t sequence = 1u;
       sequence <= OTIS_PHASE_PREVIEW_QUEUE_DEPTH; ++sequence) {
    OtisPhasePreviewRecordMessage record = {};
    assert(otis_dual_core_take_phase_preview(&record));
    assert(record.preview_sequence == sequence);
    assert(record.observation_sequence == sequence);
    assert(record.relative_phase_cycles == static_cast<int64_t>(sequence));
    assert(strcmp(record.preview_state, "RELATIVE_PHASE_ACQUIRE") == 0);
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

  otis_dual_core_partition_reset();
  for (uint32_t sequence = 1u;
       sequence <= OTIS_PHASE_PREVIEW_QUEUE_DEPTH; ++sequence) {
    const OtisPhasePreviewRecordMessage record = phase_preview(sequence);
    assert(otis_dual_core_publish_phase_preview(&record));
  }
  const OtisPhasePreviewRecordMessage cx318_overflow =
      phase_preview(OTIS_PHASE_PREVIEW_QUEUE_DEPTH + 1u);
  assert(!otis_dual_core_publish_phase_preview(&cx318_overflow));
  otis_dual_core_get_stats(&stats);
  assert(stats.fail_static);
  assert(stats.fault == OtisPartitionFault::PhasePreviewQueueExhausted);
}

void every_non_droppable_queue_has_exact_capacity_boundaries() {
  OtisDualCoreQueueStats stats = {};

  otis_dual_core_partition_reset();
  for (uint32_t sequence = 1u;
       sequence < OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH; ++sequence) {
    const OtisServiceMessage value = receiver_metadata(sequence);
    assert(otis_dual_core_publish_service(&value));
  }
  otis_dual_core_get_stats(&stats);
  assert(stats.service_to_timing_depth ==
         OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH - 1u);
  OtisServiceMessage service =
      receiver_metadata(OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH);
  assert(otis_dual_core_publish_service(&service));
  otis_dual_core_get_stats(&stats);
  assert(stats.service_to_timing_depth ==
         OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH);
  service = receiver_metadata(OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH + 1u);
  assert(!otis_dual_core_publish_service(&service));
  assert(otis_dual_core_fail_static());

  otis_dual_core_partition_reset();
  for (uint32_t sequence = 1u; sequence < OTIS_OBSERVATION_QUEUE_DEPTH;
       ++sequence) {
    const OtisObservationMessage value = observation(sequence);
    assert(otis_dual_core_publish_observation(&value));
  }
  otis_dual_core_get_stats(&stats);
  assert(stats.observation_depth == OTIS_OBSERVATION_QUEUE_DEPTH - 1u);
  OtisObservationMessage observed = observation(OTIS_OBSERVATION_QUEUE_DEPTH);
  assert(otis_dual_core_publish_observation(&observed));
  otis_dual_core_get_stats(&stats);
  assert(stats.observation_depth == OTIS_OBSERVATION_QUEUE_DEPTH);
  observed = observation(OTIS_OBSERVATION_QUEUE_DEPTH + 1u);
  assert(!otis_dual_core_publish_observation(&observed));
  assert(otis_dual_core_fail_static());

  otis_dual_core_partition_reset();
  OtisCriticalRecordMessage critical = {};
  critical.kind = OtisCriticalMessageKind::StateTransition;
  for (uint32_t sequence = 1u; sequence < OTIS_CRITICAL_QUEUE_DEPTH;
       ++sequence) {
    critical.sequence = sequence;
    assert(otis_dual_core_publish_critical(&critical));
  }
  otis_dual_core_get_stats(&stats);
  assert(stats.critical_depth == OTIS_CRITICAL_QUEUE_DEPTH - 1u);
  critical.sequence = OTIS_CRITICAL_QUEUE_DEPTH;
  assert(otis_dual_core_publish_critical(&critical));
  otis_dual_core_get_stats(&stats);
  assert(stats.critical_depth == OTIS_CRITICAL_QUEUE_DEPTH);
  critical.sequence++;
  assert(!otis_dual_core_publish_critical(&critical));
  assert(otis_dual_core_fail_static());

  otis_dual_core_partition_reset();
  for (uint32_t sequence = 1u; sequence < OTIS_EVIDENCE_QUEUE_DEPTH;
       ++sequence) {
    const OtisEvidenceFrameMessage value = evidence(sequence);
    assert(otis_dual_core_publish_evidence(&value));
  }
  otis_dual_core_get_stats(&stats);
  assert(stats.evidence_depth == OTIS_EVIDENCE_QUEUE_DEPTH - 1u);
  OtisEvidenceFrameMessage frame = evidence(OTIS_EVIDENCE_QUEUE_DEPTH);
  assert(otis_dual_core_publish_evidence(&frame));
  otis_dual_core_get_stats(&stats);
  assert(stats.evidence_depth == OTIS_EVIDENCE_QUEUE_DEPTH);
  frame = evidence(OTIS_EVIDENCE_QUEUE_DEPTH + 1u);
  assert(!otis_dual_core_publish_evidence(&frame));
  assert(otis_dual_core_fail_static());

  otis_dual_core_partition_reset();
  for (uint32_t sequence = 1u; sequence < OTIS_PHASE_PREVIEW_QUEUE_DEPTH;
       ++sequence) {
    const OtisPhasePreviewRecordMessage value = phase_preview(sequence);
    assert(otis_dual_core_publish_phase_preview(&value));
  }
  otis_dual_core_get_stats(&stats);
  assert(stats.phase_preview_depth == OTIS_PHASE_PREVIEW_QUEUE_DEPTH - 1u);
  OtisPhasePreviewRecordMessage preview =
      phase_preview(OTIS_PHASE_PREVIEW_QUEUE_DEPTH);
  assert(otis_dual_core_publish_phase_preview(&preview));
  otis_dual_core_get_stats(&stats);
  assert(stats.phase_preview_depth == OTIS_PHASE_PREVIEW_QUEUE_DEPTH);
  preview = phase_preview(OTIS_PHASE_PREVIEW_QUEUE_DEPTH + 1u);
  assert(!otis_dual_core_publish_phase_preview(&preview));
  assert(otis_dual_core_fail_static());
}

void service_exhaustion_freezes_core1_progress_capsule_once() {
  otis_dual_core_partition_reset();
  otis_dual_core_note_timing_progress(OtisTimingProgressPhase::LoopEnter,
                                      1000u);
  otis_dual_core_note_timing_snapshot(7u, 83305u);
  otis_dual_core_note_timing_count(83305u);
  otis_dual_core_note_timing_estimate(278u);

  const OtisServiceMessage first = receiver_metadata(1u);
  assert(otis_dual_core_publish_service(&first));
  OtisServiceMessage consumed = {};
  assert(otis_dual_core_take_service(&consumed));
  assert(consumed.receiver.sequence == 1u);

  otis_dual_core_note_timing_progress(
      OtisTimingProgressPhase::Cx317EstimateFormat, 2000u);
  for (uint32_t sequence = 2u; sequence <= 17u; ++sequence) {
    const OtisServiceMessage message = receiver_metadata(sequence);
    assert(otis_dual_core_publish_service(&message));
  }
  const OtisServiceMessage overflow = receiver_metadata(18u);
  assert(!otis_dual_core_publish_service(&overflow));

  OtisDualCoreQueueStats stats = {};
  otis_dual_core_get_stats(&stats);
  assert(stats.service_activity.publish_attempts == 18u);
  assert(stats.service_activity.publish_successes == 17u);
  assert(stats.service_activity.publish_failures == 1u);
  assert(stats.service_activity.take_successes == 1u);
  assert(stats.service_fault.valid);
  assert(stats.service_fault.failing_kind ==
         OtisServiceMessageKind::ReceiverQualification);
  assert(stats.service_fault.failing_sequence == 18u);
  assert(stats.service_fault.failing_published_ticks == 1800u);
  assert(stats.service_fault.queue_depth ==
         OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH);
  assert(stats.service_fault.breadcrumb_coherent);
  assert(stats.service_fault.breadcrumb_generation == 12u);
  assert(stats.service_fault.last_taken_sequence == 1u);
  assert(stats.service_fault.last_taken_ticks == 100u);
  assert(stats.service_fault.timing_phase ==
         OtisTimingProgressPhase::Cx317EstimateFormat);
  assert(stats.service_fault.timing_loop_sequence == 1u);
  assert(stats.service_fault.timing_last_progress_ticks == 2000u);
  assert(stats.service_fault.last_snapshot_session == 7u);
  assert(stats.service_fault.last_snapshot_sequence == 83305u);
  assert(stats.service_fault.last_count_sequence == 83305u);
  assert(stats.service_fault.last_estimate_sequence == 278u);

  otis_dual_core_note_timing_progress(OtisTimingProgressPhase::LoopIdle,
                                      3000u);
  const OtisServiceMessage later = receiver_metadata(19u);
  assert(!otis_dual_core_publish_service(&later));
  otis_dual_core_get_stats(&stats);
  assert(stats.service_activity.publish_failures == 2u);
  assert(stats.service_fault.failing_sequence == 18u);
  assert(stats.service_fault.timing_phase ==
         OtisTimingProgressPhase::Cx317EstimateFormat);
  assert(stats.service_fault.breadcrumb_generation == 12u);
}

void actuator_transaction_requires_exact_two_phase_ack() {
  otis_dual_core_partition_reset();
  OtisActuatorTransactionGuard guard = {};
  otis_actuator_guard_init(&guard);
  const OtisCrossCoreActuatorRequest pending = request();
  assert(otis_actuator_guard_start(
      &guard, &pending, 1801u));
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

void forwarded_monitor_overflow_does_not_mutate_actuator_transaction() {
  otis_dual_core_partition_reset();
  for (uint32_t sequence = 1u;
       sequence <= OTIS_MONITOR_OBSERVATION_QUEUE_DEPTH; ++sequence) {
    const OtisMonitorObservationMessage value = monitor_observation(sequence);
    assert(otis_dual_core_publish_monitor_observation(&value));
  }
  const OtisMonitorObservationMessage overflow =
      monitor_observation(OTIS_MONITOR_OBSERVATION_QUEUE_DEPTH + 1u);
  assert(!otis_dual_core_publish_monitor_observation(&overflow));

  OtisDualCoreQueueStats stats = {};
  otis_dual_core_get_stats(&stats);
  assert(stats.monitor_observation_dropped == 1u);
  assert(stats.fault == OtisPartitionFault::None);
  assert(!stats.fail_static);

  OtisActuatorTransactionGuard guard = {};
  otis_actuator_guard_init(&guard);
  const OtisCrossCoreActuatorRequest pending = request();
  assert(otis_actuator_guard_start(&guard, &pending, 1801u));
  const OtisCrossCoreActuatorAck accepted =
      acknowledgement(OtisActuatorAckKind::Accepted);
  assert(otis_actuator_guard_acknowledge(&guard, &accepted));
  const OtisCrossCoreActuatorAck applied =
      acknowledgement(OtisActuatorAckKind::Applied);
  assert(otis_actuator_guard_acknowledge(&guard, &applied));
  assert(guard.state == OtisActuatorGuardState::Applied);
  assert(guard.pending.request_sequence == pending.request_sequence);
  assert(guard.pending.decision_sequence == pending.decision_sequence);
  assert(guard.pending.authorization_sequence == pending.authorization_sequence);
  assert(guard.pending.nonce == pending.nonce);
  assert(strcmp(guard.reason, "exact_application_confirmed") == 0);
  assert(!otis_dual_core_fail_static());
}

void stale_ack_and_timeout_fault_without_retry() {
  otis_dual_core_partition_reset();
  OtisActuatorTransactionGuard guard = {};
  otis_actuator_guard_init(&guard);
  const OtisCrossCoreActuatorRequest pending = request();
  assert(otis_actuator_guard_start(
      &guard, &pending, 1801u));
  OtisCrossCoreActuatorAck wrong =
      acknowledgement(OtisActuatorAckKind::Accepted);
  wrong.nonce++;
  assert(!otis_actuator_guard_acknowledge(&guard, &wrong));
  assert(guard.state == OtisActuatorGuardState::Fault);
  assert(otis_dual_core_fail_static());

  otis_dual_core_partition_reset();
  otis_actuator_guard_init(&guard);
  assert(otis_actuator_guard_start(
      &guard, &pending, 1801u));
  assert(!otis_actuator_guard_check_deadline(
      &guard, pending.monotonic_deadline_s + 1u));
  assert(guard.state == OtisActuatorGuardState::Fault);
  OtisDualCoreQueueStats stats = {};
  otis_dual_core_get_stats(&stats);
  assert(stats.fault == OtisPartitionFault::ActuatorTimeout);
}

void actuator_deadline_is_wrap_safe_in_one_named_domain() {
  otis_dual_core_partition_reset();
  OtisActuatorTransactionGuard guard = {};
  otis_actuator_guard_init(&guard);
  OtisCrossCoreActuatorRequest pending = request();
  const uint32_t before_wrap = UINT32_MAX - 10u;
  pending.monotonic_deadline_s = before_wrap + 30u;
  assert(pending.monotonic_deadline_s == 19u);
  assert(otis_actuator_guard_start(&guard, &pending, before_wrap));
  assert(otis_actuator_guard_check_deadline(&guard, 5u));
  assert(!otis_actuator_guard_check_deadline(&guard, 20u));
  assert(guard.state == OtisActuatorGuardState::Fault);

  const uint32_t supported_durations[] = {30u, 600u, 2700u, 5400u, 14400u};
  for (uint32_t duration : supported_durations) {
    const uint32_t start = UINT32_MAX - duration / 2u;
    const uint32_t deadline = start + duration;
    assert(otis_actuator_monotonic_deadline_is_future(start, deadline));
    assert(!otis_actuator_monotonic_deadline_is_expired(
        start + duration, deadline));
    assert(otis_actuator_monotonic_deadline_is_expired(
        start + duration + 1u, deadline));
  }
}

void metadata_hold_exact_rejection_has_one_narrow_nonfaulting_guard_path() {
  const OtisCrossCoreActuatorRequest pending = request();
  auto exact_rejection = acknowledgement(OtisActuatorAckKind::Rejected);
  exact_rejection.accepted_code = pending.current_applied_code;
  exact_rejection.applied_code = pending.current_applied_code;
  exact_rejection.rejection_reason =
      OtisActuatorRejectionReason::MetadataHoldCancelledBeforeAcceptance;
  exact_rejection.i2c_ok = false;

  otis_dual_core_partition_reset();
  OtisActuatorTransactionGuard guard = {};
  otis_actuator_guard_init(&guard);
  assert(otis_actuator_guard_start(&guard, &pending, 1801u));
  assert(otis_actuator_guard_discard_exact_rejection(
      &guard, &exact_rejection, pending.current_applied_code));
  assert(guard.state == OtisActuatorGuardState::Idle);
  assert(guard.pending.request_sequence == 0u);
  assert(guard.pending.requested_code == 0u);
  assert(strcmp(guard.reason,
                "exact_rejection_discarded_without_application") == 0);
  assert(!otis_dual_core_fail_static());

  // The same exact tuple with a platform discriminator is never benign.
  otis_dual_core_partition_reset();
  otis_actuator_guard_init(&guard);
  assert(otis_actuator_guard_start(&guard, &pending, 1801u));
  auto platform_rejection = exact_rejection;
  platform_rejection.rejection_reason =
      OtisActuatorRejectionReason::PlatformFailStatic;
  assert(!otis_actuator_guard_discard_exact_rejection(
      &guard, &platform_rejection, pending.current_applied_code));
  assert(guard.state == OtisActuatorGuardState::AwaitingAcceptance);
  assert(!otis_actuator_guard_acknowledge(&guard, &platform_rejection));
  assert(guard.state == OtisActuatorGuardState::Fault);
  assert(otis_dual_core_fail_static());

  otis_dual_core_partition_reset();
  otis_actuator_guard_init(&guard);
  assert(otis_actuator_guard_start(&guard, &pending, 1801u));
  auto contradictory = exact_rejection;
  contradictory.nonce++;
  assert(!otis_actuator_guard_discard_exact_rejection(
      &guard, &contradictory, pending.current_applied_code));
  assert(guard.state == OtisActuatorGuardState::AwaitingAcceptance);
  assert(!otis_actuator_guard_acknowledge(&guard, &contradictory));
  assert(guard.state == OtisActuatorGuardState::Fault);
  assert(otis_dual_core_fail_static());

  // Outside metadata-hold dispatch, the established acknowledgement path
  // still treats even an exact Rejected outcome as fail-static.
  otis_dual_core_partition_reset();
  otis_actuator_guard_init(&guard);
  assert(otis_actuator_guard_start(&guard, &pending, 1801u));
  assert(!otis_actuator_guard_acknowledge(&guard, &exact_rejection));
  assert(guard.state == OtisActuatorGuardState::Fault);
  assert(otis_dual_core_fail_static());

  // Metadata hold does not relax the independently checked silent deadline.
  otis_dual_core_partition_reset();
  otis_actuator_guard_init(&guard);
  assert(otis_actuator_guard_start(&guard, &pending, 1801u));
  assert(!otis_actuator_guard_check_deadline(
      &guard, pending.monotonic_deadline_s + 1u));
  assert(guard.state == OtisActuatorGuardState::Fault);
  assert(otis_dual_core_fail_static());
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
  forwarded_monitor_queue_is_lossy_and_isolated_from_authoritative_path();
  full_build_identity_crosses_telemetry_queue_without_truncation();
  forced_boot_publish_drain_interleavings_are_exactly_once();
  receiver_qualification_age_is_timer_rollover_safe();
  open_loop_range_map_keeps_d14_d8_support_during_metadata_dips();
  diagnostic_queries_cross_poll_mutation_and_fault_boundaries();
  bounded_core0_stall_preserves_raw_evidence();
  stage7_concurrent_health_and_active_query_burst_does_not_drop();
  complete_telemetry_burst_admission_reserves_every_record();
  boot_telemetry_exhaustion_is_bounded_and_fail_static();
  service_plane_load_matrix_preserves_timing_state();
  complete_evidence_frames_cross_by_value_in_order();
  evidence_bursts_are_atomic_ordered_and_bounded();
  cx318_numerical_records_cross_by_value_in_order();
  non_droppable_exhaustion_is_fail_static();
  every_non_droppable_queue_exhaustion_is_fail_static();
  every_non_droppable_queue_has_exact_capacity_boundaries();
  service_exhaustion_freezes_core1_progress_capsule_once();
  actuator_transaction_requires_exact_two_phase_ack();
  forwarded_monitor_overflow_does_not_mutate_actuator_transaction();
  stale_ack_and_timeout_fault_without_retry();
  actuator_deadline_is_wrap_safe_in_one_named_domain();
  metadata_hold_exact_rejection_has_one_narrow_nonfaulting_guard_path();
  applied_ack_advances_stale_periodic_dac_state_before_health();
  return 0;
}
