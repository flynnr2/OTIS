#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "otis_adaptive_hybrid_maintenance_format.h"
#include "otis_adaptive_hybrid_maintenance_record.h"

namespace {

constexpr char kSha[] =
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
constexpr char kRunIdentity[] = "adaptive_hybrid_regulation:1";
constexpr char kBuildIdentity[] =
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:"
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
constexpr char kProfileIdentity[] = "adaptive_hybrid_regulation";

struct Scenario {
  OtisAdaptiveHybridEngine before;
  OtisAdaptiveHybridEngine after;
  OtisAdaptiveHybridObservation observation;
  OtisAdaptiveHybridDecision decision;
  OtisAdaptiveHybridMaintenanceHybridJoin hybrid;
  OtisAdaptiveHybridMaintenanceTransactionJoin transaction;
  OtisAdaptiveHybridMaintenanceBuildInput input;
  OtisAdaptiveHybridMaintenanceRecord record;
};

OtisAdaptiveHybridMaintenanceIdentityBinding identity() {
  return {kRunIdentity, kBuildIdentity, kProfileIdentity, kSha, kSha};
}

OtisAdaptiveHybridObservation observation(uint64_t timestamp_s, uint64_t opening,
                                 uint64_t closing,
                                 const OtisAdaptiveHybridEngine &engine) {
  OtisAdaptiveHybridObservation result = {};
  result.timestamp_s = timestamp_s;
  result.timestamp_ticks = timestamp_s * 1000000ull;
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

OtisAdaptiveHybridMaintenanceHybridJoin hybrid_join(
    const OtisAdaptiveHybridObservation &source, const OtisAdaptiveHybridDecision &decision,
    uint64_t sequence) {
  return {
      sequence,
      decision.decision_sequence,
      source.capture_session,
      source.source_first_sequence,
      source.source_last_sequence,
      source.phase_epoch,
      source.source_last_sequence,
      source.phase_valid,
  };
}

OtisAdaptiveHybridMaintenanceTransactionJoin transaction_join(
    OtisAdaptiveHybridMaintenanceTransactionEvent event,
    const OtisAdaptiveHybridObservation &source, const OtisAdaptiveHybridDecision &decision,
    uint64_t sequence, uint64_t request_sequence) {
  OtisAdaptiveHybridMaintenanceTransactionJoin result = {};
  result.transaction_record_sequence = sequence;
  result.transaction_event = event;
  result.request_sequence = request_sequence;
  result.decision_sequence = decision.decision_sequence;
  result.capture_session = source.capture_session;
  result.source_first_sequence = source.source_first_sequence;
  result.source_last_sequence = source.source_last_sequence;
  return result;
}

OtisAdaptiveHybridMaintenanceBuildInput build_input(
    uint64_t sequence, OtisAdaptiveHybridMaintenanceEvent event,
    const OtisAdaptiveHybridEngine *before, const OtisAdaptiveHybridEngine *after,
    const OtisAdaptiveHybridObservation *source, const OtisAdaptiveHybridDecision *decision,
    const OtisAdaptiveHybridMaintenanceHybridJoin *hybrid,
    const OtisAdaptiveHybridMaintenanceTransactionJoin *transaction,
    uint32_t burst_count, const char *reason) {
  OtisAdaptiveHybridMaintenanceBuildInput input = {};
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

bool build_and_emit(const OtisAdaptiveHybridMaintenanceBuildInput &input) {
  OtisAdaptiveHybridMaintenanceRecord record = {};
  char output[4096] = {};
  if (!otis_adaptive_hybrid_build_maintenance_record(&input, &record)) return false;
  const int used = otis_format_adaptive_hybrid_maintenance_v1(
      output, sizeof(output), &record);
  if (used <= 0 || static_cast<size_t>(used) != strlen(output)) return false;
  fputs(output, stdout);
  return true;
}

bool emit_header() {
  char output[2048] = {};
  const int used =
      otis_format_adaptive_hybrid_maintenance_v1_header(output, sizeof(output));
  if (used <= 0 || static_cast<size_t>(used) != strlen(output)) return false;
  fputs(output, stdout);
  return true;
}

bool run_lifecycle() {
  OtisAdaptiveHybridPolicy policy = otis_adaptive_hybrid_default_policy();
  OtisAdaptiveHybridEngine engine = {};
  if (!otis_adaptive_hybrid_engine_init(&engine, &policy, 43085, 1u) || !emit_header())
    return false;

  OtisAdaptiveHybridEngine before = engine;
  if (!otis_adaptive_hybrid_engine_new_policy_activation(&engine)) return false;
  OtisAdaptiveHybridMaintenanceBuildInput activation = build_input(
      1u, OtisAdaptiveHybridMaintenanceEvent::PolicyActivation, &before, &engine,
      nullptr, nullptr, nullptr, nullptr, 1u, engine.last_reason);
  if (!build_and_emit(activation)) return false;

  OtisAdaptiveHybridObservation first_observation =
      observation(0u, 1u, 601u, engine);
  OtisAdaptiveHybridDecision first_decision = {};
  before = engine;
  if (!otis_adaptive_hybrid_engine_decide(&engine, &first_observation,
                                &first_decision))
    return false;
  OtisAdaptiveHybridMaintenanceHybridJoin first_hybrid =
      hybrid_join(first_observation, first_decision, 2u);
  OtisAdaptiveHybridMaintenanceBuildInput first = build_input(
      2u, OtisAdaptiveHybridMaintenanceEvent::Decision, &before, &engine,
      &first_observation, &first_decision, &first_hybrid, nullptr, 2u,
      engine.last_reason);
  if (!build_and_emit(first)) return false;

  OtisAdaptiveHybridObservation request_observation =
      observation(600u, 601u, 1201u, engine);
  OtisAdaptiveHybridDecision request_decision = {};
  before = engine;
  if (!otis_adaptive_hybrid_engine_decide(&engine, &request_observation,
                                &request_decision) ||
      !engine.request_pending)
    return false;
  OtisAdaptiveHybridMaintenanceHybridJoin request_hybrid =
      hybrid_join(request_observation, request_decision, 3u);
  OtisAdaptiveHybridMaintenanceTransactionJoin request_transaction = transaction_join(
      OtisAdaptiveHybridMaintenanceTransactionEvent::RequestCreated,
      request_observation, request_decision, 103u, 9u);
  OtisAdaptiveHybridMaintenanceBuildInput request = build_input(
      3u, OtisAdaptiveHybridMaintenanceEvent::Decision, &before, &engine,
      &request_observation, &request_decision, &request_hybrid,
      &request_transaction, 3u, engine.last_reason);
  if (!build_and_emit(request)) return false;

  before = engine;
  if (!otis_adaptive_hybrid_engine_note_application_and_first_consumer(
          &engine, &request_decision, request_decision.requested_code, 2u,
          true))
    return false;
  OtisAdaptiveHybridMaintenanceTransactionJoin application_transaction =
      transaction_join(OtisAdaptiveHybridMaintenanceTransactionEvent::Application,
                       request_observation, request_decision, 104u, 9u);
  application_transaction.application_sequence = 4u;
  application_transaction.actual_applied_code =
      static_cast<uint32_t>(engine.applied_code);
  application_transaction.actual_dac_epoch = engine.dac_epoch;
  application_transaction.downstream_epoch_exact = true;
  OtisAdaptiveHybridMaintenanceBuildInput application = build_input(
      4u, OtisAdaptiveHybridMaintenanceEvent::ApplicationFirstConsumer, &before,
      &engine, &request_observation, &request_decision, &request_hybrid,
      &application_transaction, 2u, engine.last_reason);
  if (!build_and_emit(application)) return false;

  before = engine;
  if (!otis_adaptive_hybrid_engine_complete_response(&engine, true)) return false;
  OtisAdaptiveHybridMaintenanceTransactionJoin response_transaction = transaction_join(
      OtisAdaptiveHybridMaintenanceTransactionEvent::Response, request_observation,
      request_decision, 105u, 9u);
  response_transaction.application_sequence = 4u;
  response_transaction.actual_applied_code =
      static_cast<uint32_t>(engine.applied_code);
  response_transaction.actual_dac_epoch = engine.dac_epoch;
  response_transaction.downstream_epoch_exact = true;
  OtisAdaptiveHybridMaintenanceBuildInput response = build_input(
      5u, OtisAdaptiveHybridMaintenanceEvent::ResponseComplete, &before, &engine,
      &request_observation, &request_decision, &request_hybrid,
      &response_transaction, 2u, engine.last_reason);
  if (!build_and_emit(response)) return false;

  before = engine;
  if (!otis_adaptive_hybrid_engine_enter_metadata_hold(&engine)) return false;
  OtisAdaptiveHybridMaintenanceBuildInput metadata_hold = build_input(
      6u, OtisAdaptiveHybridMaintenanceEvent::GnssMetadataHoldEnter, &before, &engine,
      &request_observation, &request_decision, &request_hybrid, nullptr, 1u,
      engine.last_reason);
  if (!build_and_emit(metadata_hold)) return false;

  before = engine;
  if (!otis_adaptive_hybrid_engine_requalify_metadata(&engine, 1501u)) return false;
  OtisAdaptiveHybridMaintenanceBuildInput requalified = build_input(
      7u, OtisAdaptiveHybridMaintenanceEvent::GnssMetadataRequalified, &before,
      &engine, &request_observation, &request_decision, &request_hybrid,
      nullptr, 1u, engine.last_reason);
  if (!build_and_emit(requalified)) return false;

  OtisAdaptiveHybridObservation requalification_first_observation =
      observation(1800u, 1501u, 2101u, engine);
  OtisAdaptiveHybridDecision requalification_first_decision = {};
  before = engine;
  if (!otis_adaptive_hybrid_engine_decide(&engine, &requalification_first_observation,
                                &requalification_first_decision) ||
      !engine.metadata_hold || engine.requalification_window_count != 1u)
    return false;
  OtisAdaptiveHybridMaintenanceHybridJoin requalification_first_hybrid = hybrid_join(
      requalification_first_observation, requalification_first_decision, 8u);
  OtisAdaptiveHybridMaintenanceBuildInput first_window = build_input(
      8u, OtisAdaptiveHybridMaintenanceEvent::Decision, &before, &engine,
      &requalification_first_observation, &requalification_first_decision,
      &requalification_first_hybrid, nullptr, 2u, engine.last_reason);
  if (!build_and_emit(first_window)) return false;

  OtisAdaptiveHybridObservation requalification_second_observation =
      observation(2400u, 2101u, 2701u, engine);
  OtisAdaptiveHybridDecision requalification_second_decision = {};
  before = engine;
  if (!otis_adaptive_hybrid_engine_decide(&engine, &requalification_second_observation,
                                &requalification_second_decision) ||
      engine.metadata_hold || engine.requalification_window_count != 2u)
    return false;
  OtisAdaptiveHybridMaintenanceHybridJoin requalification_second_hybrid = hybrid_join(
      requalification_second_observation, requalification_second_decision,
      9u);
  OtisAdaptiveHybridMaintenanceTransactionJoin second_transaction = transaction_join(
      OtisAdaptiveHybridMaintenanceTransactionEvent::RequestCreated,
      requalification_second_observation, requalification_second_decision,
      109u, 10u);
  const bool second_requested = engine.request_pending;
  OtisAdaptiveHybridMaintenanceBuildInput second_window = build_input(
      9u, OtisAdaptiveHybridMaintenanceEvent::Decision, &before, &engine,
      &requalification_second_observation, &requalification_second_decision,
      &requalification_second_hybrid,
      second_requested ? &second_transaction : nullptr,
      second_requested ? 3u : 2u, engine.last_reason);
  if (!build_and_emit(second_window) || !second_requested) return false;

  before = engine;
  if (!otis_adaptive_hybrid_engine_reject_or_expire_request(&engine)) return false;
  OtisAdaptiveHybridMaintenanceTransactionJoin rejected_transaction = transaction_join(
      OtisAdaptiveHybridMaintenanceTransactionEvent::RequestWithdrawn,
      requalification_second_observation, requalification_second_decision,
      110u, 10u);
  OtisAdaptiveHybridMaintenanceBuildInput rejected = build_input(
      10u, OtisAdaptiveHybridMaintenanceEvent::RequestRejectedOrExpired, &before,
      &engine, &requalification_second_observation,
      &requalification_second_decision, &requalification_second_hybrid,
      &rejected_transaction, 2u, engine.last_reason);
  if (!build_and_emit(rejected)) return false;

  before = engine;
  if (otis_adaptive_hybrid_engine_note_application_and_first_consumer(
          &engine, &requalification_second_decision,
          requalification_second_decision.requested_code, engine.dac_epoch + 1u,
          false) ||
      engine.fail_static_reason == nullptr)
    return false;
  OtisAdaptiveHybridMaintenanceTransactionJoin fault_transaction = transaction_join(
      OtisAdaptiveHybridMaintenanceTransactionEvent::ApplicationFault,
      requalification_second_observation, requalification_second_decision,
      111u, 10u);
  OtisAdaptiveHybridMaintenanceBuildInput fail = build_input(
      11u, OtisAdaptiveHybridMaintenanceEvent::FailStatic, &before, &engine,
      &requalification_second_observation,
      &requalification_second_decision, &requalification_second_hybrid,
      &fault_transaction, 2u, engine.last_reason);
  return build_and_emit(fail);
}

bool rejects(const OtisAdaptiveHybridMaintenanceBuildInput &input) {
  OtisAdaptiveHybridMaintenanceRecord record = {};
  return !otis_adaptive_hybrid_build_maintenance_record(&input, &record);
}

bool run_selftest() {
  OtisAdaptiveHybridPolicy policy = otis_adaptive_hybrid_default_policy();
  OtisAdaptiveHybridEngine engine = {};
  if (!otis_adaptive_hybrid_engine_init(&engine, &policy, 43085, 1u)) return false;
  OtisAdaptiveHybridObservation source = observation(0u, 1u, 601u, engine);
  OtisAdaptiveHybridDecision decision = {};
  OtisAdaptiveHybridEngine before = engine;
  if (!otis_adaptive_hybrid_engine_decide(&engine, &source, &decision)) return false;
  OtisAdaptiveHybridMaintenanceHybridJoin hybrid = hybrid_join(source, decision, 1u);
  OtisAdaptiveHybridMaintenanceBuildInput valid = build_input(
      1u, OtisAdaptiveHybridMaintenanceEvent::Decision, &before, &engine, &source,
      &decision, &hybrid, nullptr, 2u, engine.last_reason);
  OtisAdaptiveHybridMaintenanceRecord record = {};
  if (!otis_adaptive_hybrid_build_maintenance_record(&valid, &record)) return false;

  OtisAdaptiveHybridMaintenanceHybridJoin partial_hybrid = hybrid;
  partial_hybrid.hybrid_record_sequence = 0u;
  OtisAdaptiveHybridMaintenanceBuildInput invalid = valid;
  invalid.hybrid_join = &partial_hybrid;
  if (!rejects(invalid)) return false;

  invalid = valid;
  invalid.event = OtisAdaptiveHybridMaintenanceEvent::ResponseComplete;
  if (!rejects(invalid)) return false;

  OtisAdaptiveHybridMaintenanceHybridJoin contradictory_hybrid = hybrid;
  ++contradictory_hybrid.decision_sequence;
  invalid = valid;
  invalid.hybrid_join = &contradictory_hybrid;
  if (!rejects(invalid)) return false;

  OtisAdaptiveHybridDecision overflow_decision = decision;
  if (!otis_adaptive_hybrid_wide_parse_decimal(
          "170141183460469231731687303715884105727",
          &overflow_decision.raw_combined_picocodes))
    return false;
  overflow_decision.committed_debt_picocodes = 1;
  OtisAdaptiveHybridMaintenanceHybridJoin overflow_hybrid =
      hybrid_join(source, overflow_decision, 1u);
  invalid = valid;
  invalid.originating_decision = &overflow_decision;
  invalid.hybrid_join = &overflow_hybrid;
  if (!rejects(invalid)) return false;

  OtisAdaptiveHybridMaintenanceTransactionJoin partial_transaction = transaction_join(
      OtisAdaptiveHybridMaintenanceTransactionEvent::Application, source, decision,
      4u, 1u);
  partial_transaction.application_sequence = 1u;
  invalid = valid;
  invalid.transaction_join = &partial_transaction;
  if (!rejects(invalid)) return false;

  OtisAdaptiveHybridEngine wrapped = engine;
  before.decision_sequence = UINT64_MAX;
  wrapped.decision_sequence = 0u;
  invalid = valid;
  invalid.engine_before = &before;
  invalid.engine_after = &wrapped;
  if (!rejects(invalid)) return false;

  // A failure committed by decide() is represented by the ordinary AHY/AHM
  // decision burst followed by the unique fail-static AHM transition. Both
  // retain the same exact AHY identity and before/after engine snapshots.
  OtisAdaptiveHybridEngine failure_engine = {};
  if (!otis_adaptive_hybrid_engine_init(&failure_engine, &policy, 43085, 1u))
    return false;
  failure_engine.last_application_available = true;
  failure_engine.last_application_s = 1000u;
  failure_engine.last_application_ticks = 1000u * 1000000ull;
  OtisAdaptiveHybridObservation failure_observation =
      observation(900u, 1u, 601u, failure_engine);
  OtisAdaptiveHybridEngine failure_before = failure_engine;
  OtisAdaptiveHybridDecision failure_decision = {};
  if (!otis_adaptive_hybrid_engine_decide(&failure_engine, &failure_observation,
                                &failure_decision) ||
      failure_engine.fail_static_reason == nullptr)
    return false;
  OtisAdaptiveHybridMaintenanceHybridJoin failure_hybrid =
      hybrid_join(failure_observation, failure_decision, 20u);
  OtisAdaptiveHybridMaintenanceBuildInput failure_decision_input = build_input(
      20u, OtisAdaptiveHybridMaintenanceEvent::Decision, &failure_before,
      &failure_engine, &failure_observation, &failure_decision,
      &failure_hybrid, nullptr, 2u, failure_engine.last_reason);
  OtisAdaptiveHybridMaintenanceBuildInput failure_latch_input = build_input(
      21u, OtisAdaptiveHybridMaintenanceEvent::FailStatic, &failure_before,
      &failure_engine, &failure_observation, &failure_decision,
      &failure_hybrid, nullptr, 1u, failure_engine.last_reason);
  OtisAdaptiveHybridMaintenanceRecord failure_decision_record = {};
  OtisAdaptiveHybridMaintenanceRecord failure_latch_record = {};
  char formatted[4096] = {};
  if (!otis_adaptive_hybrid_build_maintenance_record(&failure_decision_input,
                                            &failure_decision_record) ||
      !otis_adaptive_hybrid_build_maintenance_record(&failure_latch_input,
                                            &failure_latch_record) ||
      failure_decision_record.maintenance_state_after !=
          OtisAdaptiveHybridMaintenanceState::FailStatic ||
      failure_latch_record.maintenance_state_after !=
          OtisAdaptiveHybridMaintenanceState::FailStatic ||
      otis_format_adaptive_hybrid_maintenance_v1(
          formatted, sizeof(formatted), &failure_decision_record) <= 0 ||
      otis_format_adaptive_hybrid_maintenance_v1(
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
