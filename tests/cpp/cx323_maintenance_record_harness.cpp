#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "otis_cx323_maintenance_format.h"
#include "otis_cx323_maintenance_record.h"

namespace {

constexpr char kSha[] =
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
constexpr char kRunIdentity[] = "cx323_d9_d6_72h_adaptive_hybrid:1";
constexpr char kBuildIdentity[] =
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:"
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
constexpr char kProfileIdentity[] = "cx323_d9_d6_72h_adaptive_hybrid";

struct Scenario {
  OtisCx323Engine before;
  OtisCx323Engine after;
  OtisCx323Observation observation;
  OtisCx323Decision decision;
  OtisCx323MaintenanceHybridJoin hybrid;
  OtisCx323MaintenanceTransactionJoin transaction;
  OtisCx323MaintenanceBuildInput input;
  OtisCx323MaintenanceRecord record;
};

OtisCx323MaintenanceIdentityBinding identity() {
  return {kRunIdentity, kBuildIdentity, kProfileIdentity, kSha, kSha};
}

OtisCx323Observation observation(uint64_t timestamp_s, uint64_t opening,
                                 uint64_t closing,
                                 const OtisCx323Engine &engine) {
  OtisCx323Observation result = {};
  result.timestamp_s = timestamp_s;
  result.timestamp_ticks = timestamp_s * 16000000ull;
  result.capture_session = 7u;
  result.source_first_sequence = opening;
  result.source_last_sequence = closing;
  result.dac_epoch = engine.dac_epoch;
  result.applied_code = engine.applied_code;
  result.accumulated_edge_error_counts = -1;
  result.tight_inside = true;
  result.phase_epoch = 3u;
  result.relative_phase_cycles = -4;
  result.selected_estimator_identity = 11u;
  result.phase_valid = true;
  result.authority_valid = true;
  result.settled = true;
  result.cadence_eligible = true;
  result.metadata_qualified = true;
  return result;
}

OtisCx323MaintenanceHybridJoin hybrid_join(
    const OtisCx323Observation &source, const OtisCx323Decision &decision,
    uint64_t sequence) {
  return {
      sequence,
      sequence + 1000u,
      decision.decision_sequence,
      source.capture_session,
      source.source_first_sequence,
      source.source_last_sequence,
      source.phase_epoch,
      source.source_last_sequence,
      source.phase_valid,
  };
}

OtisCx323MaintenanceTransactionJoin transaction_join(
    OtisCx323MaintenanceTransactionEvent event,
    const OtisCx323Observation &source, const OtisCx323Decision &decision,
    uint64_t sequence, uint64_t request_sequence) {
  OtisCx323MaintenanceTransactionJoin result = {};
  result.transaction_record_sequence = sequence;
  result.transaction_timing_record_sequence = sequence + 1000u;
  result.transaction_event = event;
  result.request_sequence = request_sequence;
  result.decision_sequence = decision.decision_sequence;
  result.capture_session = source.capture_session;
  result.source_first_sequence = source.source_first_sequence;
  result.source_last_sequence = source.source_last_sequence;
  return result;
}

OtisCx323MaintenanceBuildInput build_input(
    uint64_t sequence, OtisCx323MaintenanceEvent event,
    const OtisCx323Engine *before, const OtisCx323Engine *after,
    const OtisCx323Observation *source, const OtisCx323Decision *decision,
    const OtisCx323MaintenanceHybridJoin *hybrid,
    const OtisCx323MaintenanceTransactionJoin *transaction,
    uint32_t burst_count, const char *reason) {
  OtisCx323MaintenanceBuildInput input = {};
  input.maintenance_record_sequence = sequence;
  input.event = event;
  input.event_timestamp_ticks = sequence * 1000000u;
  input.identity = identity();
  input.engine_before = before;
  input.engine_after = after;
  input.originating_observation = source;
  input.originating_decision = decision;
  input.hybrid_join = hybrid;
  input.transaction_join = transaction;
  input.evidence_burst_sequence = sequence;
  input.evidence_burst_record_ordinal = burst_count;
  input.evidence_burst_record_count = burst_count;
  input.reason = reason;
  return input;
}

bool build_and_emit(const OtisCx323MaintenanceBuildInput &input) {
  OtisCx323MaintenanceRecord record = {};
  char output[4096] = {};
  if (!otis_cx323_build_maintenance_record(&input, &record)) return false;
  const int used = otis_format_cx323_maintenance_v1(
      output, sizeof(output), &record);
  if (used <= 0 || static_cast<size_t>(used) != strlen(output)) return false;
  fputs(output, stdout);
  return true;
}

bool emit_header() {
  char output[2048] = {};
  const int used =
      otis_format_cx323_maintenance_v1_header(output, sizeof(output));
  if (used <= 0 || static_cast<size_t>(used) != strlen(output)) return false;
  fputs(output, stdout);
  return true;
}

bool run_lifecycle() {
  OtisCx323Policy policy = otis_cx323_default_policy();
  OtisCx323Engine engine = {};
  if (!otis_cx323_engine_init(&engine, &policy, 43085, 1u) || !emit_header())
    return false;

  OtisCx323Engine before = engine;
  if (!otis_cx323_engine_new_policy_activation(&engine)) return false;
  OtisCx323MaintenanceBuildInput activation = build_input(
      1u, OtisCx323MaintenanceEvent::PolicyActivation, &before, &engine,
      nullptr, nullptr, nullptr, nullptr, 1u, engine.last_reason);
  if (!build_and_emit(activation)) return false;

  OtisCx323Observation first_observation =
      observation(0u, 1u, 601u, engine);
  OtisCx323Decision first_decision = {};
  before = engine;
  if (!otis_cx323_engine_decide(&engine, &first_observation,
                                &first_decision))
    return false;
  OtisCx323MaintenanceHybridJoin first_hybrid =
      hybrid_join(first_observation, first_decision, 2u);
  OtisCx323MaintenanceBuildInput first = build_input(
      2u, OtisCx323MaintenanceEvent::Decision, &before, &engine,
      &first_observation, &first_decision, &first_hybrid, nullptr, 3u,
      engine.last_reason);
  if (!build_and_emit(first)) return false;

  OtisCx323Observation request_observation =
      observation(600u, 601u, 1201u, engine);
  OtisCx323Decision request_decision = {};
  before = engine;
  if (!otis_cx323_engine_decide(&engine, &request_observation,
                                &request_decision) ||
      !engine.request_pending)
    return false;
  OtisCx323MaintenanceHybridJoin request_hybrid =
      hybrid_join(request_observation, request_decision, 3u);
  OtisCx323MaintenanceTransactionJoin request_transaction = transaction_join(
      OtisCx323MaintenanceTransactionEvent::RequestCreated,
      request_observation, request_decision, 103u, 9u);
  OtisCx323MaintenanceBuildInput request = build_input(
      3u, OtisCx323MaintenanceEvent::Decision, &before, &engine,
      &request_observation, &request_decision, &request_hybrid,
      &request_transaction, 5u, engine.last_reason);
  if (!build_and_emit(request)) return false;

  before = engine;
  if (!otis_cx323_engine_note_application_and_first_consumer(
          &engine, &request_decision, request_decision.requested_code, 2u,
          true))
    return false;
  OtisCx323MaintenanceTransactionJoin application_transaction =
      transaction_join(OtisCx323MaintenanceTransactionEvent::Application,
                       request_observation, request_decision, 104u, 9u);
  application_transaction.application_sequence = 4u;
  application_transaction.actual_applied_code =
      static_cast<uint32_t>(engine.applied_code);
  application_transaction.actual_dac_epoch = engine.dac_epoch;
  application_transaction.downstream_epoch_exact = true;
  OtisCx323MaintenanceBuildInput application = build_input(
      4u, OtisCx323MaintenanceEvent::ApplicationFirstConsumer, &before,
      &engine, &request_observation, &request_decision, &request_hybrid,
      &application_transaction, 3u, engine.last_reason);
  if (!build_and_emit(application)) return false;

  before = engine;
  if (!otis_cx323_engine_complete_response(&engine, true)) return false;
  OtisCx323MaintenanceTransactionJoin response_transaction = transaction_join(
      OtisCx323MaintenanceTransactionEvent::Response, request_observation,
      request_decision, 105u, 9u);
  response_transaction.application_sequence = 4u;
  response_transaction.actual_applied_code =
      static_cast<uint32_t>(engine.applied_code);
  response_transaction.actual_dac_epoch = engine.dac_epoch;
  response_transaction.downstream_epoch_exact = true;
  OtisCx323MaintenanceBuildInput response = build_input(
      5u, OtisCx323MaintenanceEvent::ResponseComplete, &before, &engine,
      &request_observation, &request_decision, &request_hybrid,
      &response_transaction, 3u, engine.last_reason);
  if (!build_and_emit(response)) return false;

  before = engine;
  if (!otis_cx323_engine_enter_metadata_hold(&engine)) return false;
  OtisCx323MaintenanceBuildInput metadata_hold = build_input(
      6u, OtisCx323MaintenanceEvent::GnssMetadataHoldEnter, &before, &engine,
      &request_observation, &request_decision, &request_hybrid, nullptr, 1u,
      engine.last_reason);
  if (!build_and_emit(metadata_hold)) return false;

  before = engine;
  if (!otis_cx323_engine_requalify_metadata(&engine, 1501u)) return false;
  OtisCx323MaintenanceBuildInput requalified = build_input(
      7u, OtisCx323MaintenanceEvent::GnssMetadataRequalified, &before,
      &engine, &request_observation, &request_decision, &request_hybrid,
      nullptr, 1u, engine.last_reason);
  if (!build_and_emit(requalified)) return false;

  OtisCx323Observation requalification_first_observation =
      observation(1800u, 1501u, 2101u, engine);
  OtisCx323Decision requalification_first_decision = {};
  before = engine;
  if (!otis_cx323_engine_decide(&engine, &requalification_first_observation,
                                &requalification_first_decision) ||
      !engine.metadata_hold || engine.requalification_window_count != 1u)
    return false;
  OtisCx323MaintenanceHybridJoin requalification_first_hybrid = hybrid_join(
      requalification_first_observation, requalification_first_decision, 8u);
  OtisCx323MaintenanceBuildInput first_window = build_input(
      8u, OtisCx323MaintenanceEvent::Decision, &before, &engine,
      &requalification_first_observation, &requalification_first_decision,
      &requalification_first_hybrid, nullptr, 3u, engine.last_reason);
  if (!build_and_emit(first_window)) return false;

  OtisCx323Observation requalification_second_observation =
      observation(2400u, 2101u, 2701u, engine);
  OtisCx323Decision requalification_second_decision = {};
  before = engine;
  if (!otis_cx323_engine_decide(&engine, &requalification_second_observation,
                                &requalification_second_decision) ||
      engine.metadata_hold || engine.requalification_window_count != 2u)
    return false;
  OtisCx323MaintenanceHybridJoin requalification_second_hybrid = hybrid_join(
      requalification_second_observation, requalification_second_decision,
      9u);
  OtisCx323MaintenanceTransactionJoin second_transaction = transaction_join(
      OtisCx323MaintenanceTransactionEvent::RequestCreated,
      requalification_second_observation, requalification_second_decision,
      109u, 10u);
  const bool second_requested = engine.request_pending;
  OtisCx323MaintenanceBuildInput second_window = build_input(
      9u, OtisCx323MaintenanceEvent::Decision, &before, &engine,
      &requalification_second_observation, &requalification_second_decision,
      &requalification_second_hybrid,
      second_requested ? &second_transaction : nullptr,
      second_requested ? 5u : 3u, engine.last_reason);
  if (!build_and_emit(second_window) || !second_requested) return false;

  before = engine;
  if (!otis_cx323_engine_reject_or_expire_request(&engine)) return false;
  OtisCx323MaintenanceTransactionJoin rejected_transaction = transaction_join(
      OtisCx323MaintenanceTransactionEvent::RequestWithdrawn,
      requalification_second_observation, requalification_second_decision,
      110u, 10u);
  OtisCx323MaintenanceBuildInput rejected = build_input(
      10u, OtisCx323MaintenanceEvent::RequestRejectedOrExpired, &before,
      &engine, &requalification_second_observation,
      &requalification_second_decision, &requalification_second_hybrid,
      &rejected_transaction, 3u, engine.last_reason);
  if (!build_and_emit(rejected)) return false;

  before = engine;
  if (otis_cx323_engine_note_application_and_first_consumer(
          &engine, &requalification_second_decision,
          requalification_second_decision.requested_code, engine.dac_epoch + 1u,
          false) ||
      engine.fail_static_reason == nullptr)
    return false;
  OtisCx323MaintenanceTransactionJoin fault_transaction = transaction_join(
      OtisCx323MaintenanceTransactionEvent::ApplicationFault,
      requalification_second_observation, requalification_second_decision,
      111u, 10u);
  OtisCx323MaintenanceBuildInput fail = build_input(
      11u, OtisCx323MaintenanceEvent::FailStatic, &before, &engine,
      &requalification_second_observation,
      &requalification_second_decision, &requalification_second_hybrid,
      &fault_transaction, 3u, engine.last_reason);
  return build_and_emit(fail);
}

bool rejects(const OtisCx323MaintenanceBuildInput &input) {
  OtisCx323MaintenanceRecord record = {};
  return !otis_cx323_build_maintenance_record(&input, &record);
}

bool run_selftest() {
  OtisCx323Policy policy = otis_cx323_default_policy();
  OtisCx323Engine engine = {};
  if (!otis_cx323_engine_init(&engine, &policy, 43085, 1u)) return false;
  OtisCx323Observation source = observation(0u, 1u, 601u, engine);
  OtisCx323Decision decision = {};
  OtisCx323Engine before = engine;
  if (!otis_cx323_engine_decide(&engine, &source, &decision)) return false;
  OtisCx323MaintenanceHybridJoin hybrid = hybrid_join(source, decision, 1u);
  OtisCx323MaintenanceBuildInput valid = build_input(
      1u, OtisCx323MaintenanceEvent::Decision, &before, &engine, &source,
      &decision, &hybrid, nullptr, 3u, engine.last_reason);
  OtisCx323MaintenanceRecord record = {};
  if (!otis_cx323_build_maintenance_record(&valid, &record)) return false;

  OtisCx323MaintenanceHybridJoin partial_hybrid = hybrid;
  partial_hybrid.hybrid_timing_record_sequence = 0u;
  OtisCx323MaintenanceBuildInput invalid = valid;
  invalid.hybrid_join = &partial_hybrid;
  if (!rejects(invalid)) return false;

  invalid = valid;
  invalid.event = OtisCx323MaintenanceEvent::ResponseComplete;
  if (!rejects(invalid)) return false;

  OtisCx323MaintenanceHybridJoin contradictory_hybrid = hybrid;
  ++contradictory_hybrid.decision_sequence;
  invalid = valid;
  invalid.hybrid_join = &contradictory_hybrid;
  if (!rejects(invalid)) return false;

  OtisCx323Decision overflow_decision = decision;
  if (!otis_cx323_wide_parse_decimal(
          "170141183460469231731687303715884105727",
          &overflow_decision.raw_combined_picocodes))
    return false;
  overflow_decision.committed_debt_picocodes = 1;
  OtisCx323MaintenanceHybridJoin overflow_hybrid =
      hybrid_join(source, overflow_decision, 1u);
  invalid = valid;
  invalid.originating_decision = &overflow_decision;
  invalid.hybrid_join = &overflow_hybrid;
  if (!rejects(invalid)) return false;

  OtisCx323MaintenanceTransactionJoin partial_transaction = transaction_join(
      OtisCx323MaintenanceTransactionEvent::Application, source, decision,
      4u, 1u);
  partial_transaction.application_sequence = 1u;
  invalid = valid;
  invalid.transaction_join = &partial_transaction;
  if (!rejects(invalid)) return false;

  OtisCx323Engine wrapped = engine;
  before.decision_sequence = UINT64_MAX;
  wrapped.decision_sequence = 0u;
  invalid = valid;
  invalid.engine_before = &before;
  invalid.engine_after = &wrapped;
  if (!rejects(invalid)) return false;

  // A failure committed by decide() is represented by two AHM rows in one
  // atomic burst: the mandatory per-decision row and the unique fail-static
  // transition row.  Both retain the same exact AHY/AH2 identity and
  // before/after engine snapshots.
  OtisCx323Engine failure_engine = {};
  if (!otis_cx323_engine_init(&failure_engine, &policy, 43085, 1u))
    return false;
  failure_engine.last_application_available = true;
  failure_engine.last_application_s = 1000u;
  failure_engine.last_application_ticks = 1000u * 16000000ull;
  OtisCx323Observation failure_observation =
      observation(900u, 1u, 601u, failure_engine);
  OtisCx323Engine failure_before = failure_engine;
  OtisCx323Decision failure_decision = {};
  if (!otis_cx323_engine_decide(&failure_engine, &failure_observation,
                                &failure_decision) ||
      failure_engine.fail_static_reason == nullptr)
    return false;
  OtisCx323MaintenanceHybridJoin failure_hybrid =
      hybrid_join(failure_observation, failure_decision, 20u);
  OtisCx323MaintenanceBuildInput failure_decision_input = build_input(
      20u, OtisCx323MaintenanceEvent::Decision, &failure_before,
      &failure_engine, &failure_observation, &failure_decision,
      &failure_hybrid, nullptr, 4u, failure_engine.last_reason);
  failure_decision_input.evidence_burst_record_ordinal = 3u;
  OtisCx323MaintenanceBuildInput failure_latch_input = build_input(
      21u, OtisCx323MaintenanceEvent::FailStatic, &failure_before,
      &failure_engine, &failure_observation, &failure_decision,
      &failure_hybrid, nullptr, 4u, failure_engine.last_reason);
  OtisCx323MaintenanceRecord failure_decision_record = {};
  OtisCx323MaintenanceRecord failure_latch_record = {};
  char formatted[4096] = {};
  if (!otis_cx323_build_maintenance_record(&failure_decision_input,
                                            &failure_decision_record) ||
      !otis_cx323_build_maintenance_record(&failure_latch_input,
                                            &failure_latch_record) ||
      failure_decision_record.maintenance_state_after !=
          OtisCx323MaintenanceState::FailStatic ||
      failure_latch_record.maintenance_state_after !=
          OtisCx323MaintenanceState::FailStatic ||
      otis_format_cx323_maintenance_v1(
          formatted, sizeof(formatted), &failure_decision_record) <= 0 ||
      otis_format_cx323_maintenance_v1(
          formatted, sizeof(formatted), &failure_latch_record) <= 0)
    return false;

  return true;
}

}  // namespace

int main(int argc, char **argv) {
  if (argc != 2) return 2;
  if (strcmp(argv[1], "lifecycle") == 0) return run_lifecycle() ? 0 : 1;
  if (strcmp(argv[1], "selftest") == 0) {
    if (!run_selftest()) return 1;
    puts("selftest_ok");
    return 0;
  }
  return 2;
}
