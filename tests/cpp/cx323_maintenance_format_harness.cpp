#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "otis_cx323_maintenance_format.h"

namespace {

constexpr char kSha[] =
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
constexpr char kRunIdentity[] = "cx323_d9_d6_72h_adaptive_hybrid:1";
constexpr char kBuildIdentity[] =
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:"
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
constexpr char kProfileIdentity[] = "cx323_d9_d6_72h_adaptive_hybrid";

bool set_wide(const char *text, OtisCx323Wide *value) {
  return otis_cx323_wide_parse_decimal(text, value);
}

OtisCx323MaintenanceRecord base_record(uint64_t sequence) {
  OtisCx323MaintenanceRecord record = {};
  record.maintenance_record_sequence = sequence;
  record.event = OtisCx323MaintenanceEvent::Decision;
  record.event_timestamp_ticks = sequence * 1000000u;
  record.run_identity = kRunIdentity;
  record.build_identity = kBuildIdentity;
  record.profile_identity = kProfileIdentity;
  record.active_policy_sha256 = kSha;
  record.capture_session = 7u;
  record.source_first_sequence = 1200u;
  record.source_last_sequence = 1800u;
  record.frequency_estimator_sha256 = kSha;
  record.phase_epoch = 3u;
  record.phase_observation_sequence = 1800u;
  record.phase_valid = true;
  record.current_applied_code = 43085u;
  record.current_dac_epoch = 13u;
  record.hybrid_record_sequence = sequence;
  record.hybrid_timing_record_sequence = sequence;
  record.decision_sequence = sequence;
  record.transaction_event = OtisCx323MaintenanceTransactionEvent::None;
  record.maintenance_state_before = OtisCx323MaintenanceState::Ready;
  record.maintenance_state_after =
      OtisCx323MaintenanceState::PersistenceHold;
  record.frontier_relation = OtisCx323FrontierRelation::Contiguous;
  record.interval_sign = 1;
  record.persistence_count_before = 0u;
  record.persistence_count_after = 1u;
  set_wide("5000000000000", &record.raw_fll_demand_picocodes);
  set_wide("475213574925", &record.raw_pll_demand_picocodes);
  set_wide("5475213574925", &record.candidate_total_demand_picocodes);
  record.safe_cap_codes = 6u;
  record.requested_delta_codes = 0;
  record.requested_code = 43085u;
  record.committed_fll_debt_before_picocodes = 250000000000LL;
  record.committed_pll_debt_before_picocodes = 100000000000LL;
  record.committed_fll_debt_after_picocodes = 250000000000LL;
  record.committed_pll_debt_after_picocodes = 100000000000LL;
  record.evidence_burst_sequence = sequence;
  record.evidence_burst_record_ordinal = 3u;
  record.evidence_burst_record_count = 3u;
  record.reason = "persistence_first_interval_hold";
  return record;
}

bool emit_header() {
  char output[2048] = {};
  const int used =
      otis_format_cx323_maintenance_v1_header(output, sizeof(output));
  if (used <= 0 || static_cast<size_t>(used) != strlen(output)) return false;
  fputs(output, stdout);
  return true;
}

bool emit_record(const OtisCx323MaintenanceRecord &record) {
  char output[4096] = {};
  const int used =
      otis_format_cx323_maintenance_v1(output, sizeof(output), &record);
  if (used <= 0 || static_cast<size_t>(used) != strlen(output)) return false;
  fputs(output, stdout);
  return true;
}

bool emit_lifecycle() {
  if (!emit_header()) return false;

  OtisCx323MaintenanceRecord activation = base_record(1u);
  activation.event = OtisCx323MaintenanceEvent::PolicyActivation;
  activation.source_first_sequence = 0u;
  activation.source_last_sequence = 0u;
  activation.hybrid_record_sequence = 0u;
  activation.hybrid_timing_record_sequence = 0u;
  activation.decision_sequence = 0u;
  activation.maintenance_state_before =
      OtisCx323MaintenanceState::PolicyInactive;
  activation.maintenance_state_after = OtisCx323MaintenanceState::Ready;
  activation.frontier_relation = OtisCx323FrontierRelation::NotApplicable;
  activation.persistence_count_after = 0u;
  activation.committed_fll_debt_after_picocodes = 0;
  activation.committed_pll_debt_after_picocodes = 0;
  activation.evidence_burst_record_ordinal = 1u;
  activation.evidence_burst_record_count = 1u;
  activation.reason = "new_policy_activation";
  if (!emit_record(activation)) return false;

  OtisCx323MaintenanceRecord hold = base_record(2u);
  if (!set_wide("-170141183460469231731687303715884105727",
                &hold.raw_fll_demand_picocodes) ||
      !set_wide("170141183460469231731687303715884105727",
                &hold.raw_pll_demand_picocodes) ||
      !set_wide("-170141183460469231731687303715884105727",
                &hold.candidate_total_demand_picocodes) ||
      !emit_record(hold))
    return false;

  OtisCx323MaintenanceRecord request = base_record(3u);
  request.transaction_record_sequence = 103u;
  request.transaction_timing_record_sequence = 203u;
  request.transaction_event =
      OtisCx323MaintenanceTransactionEvent::RequestCreated;
  request.request_sequence = 9u;
  request.maintenance_state_before =
      OtisCx323MaintenanceState::PersistenceHold;
  request.maintenance_state_after =
      OtisCx323MaintenanceState::RequestPending;
  request.persistence_count_before = 1u;
  request.persistence_count_after = 2u;
  request.requested_delta_codes = 5;
  request.requested_code = 43090u;
  request.request_pending_after = true;
  request.evidence_burst_record_ordinal = 5u;
  request.evidence_burst_record_count = 5u;
  request.reason = "maintenance_request_ready";
  if (!emit_record(request)) return false;

  OtisCx323MaintenanceRecord application = base_record(4u);
  application.event =
      OtisCx323MaintenanceEvent::ApplicationFirstConsumer;
  application.transaction_record_sequence = 104u;
  application.transaction_timing_record_sequence = 204u;
  application.transaction_event =
      OtisCx323MaintenanceTransactionEvent::Application;
  application.request_sequence = 9u;
  application.application_sequence = 4u;
  application.actual_applied_code = 43090u;
  application.actual_dac_epoch = 14u;
  application.downstream_epoch_exact = true;
  application.maintenance_state_before =
      OtisCx323MaintenanceState::RequestPending;
  application.maintenance_state_after =
      OtisCx323MaintenanceState::ResponsePending;
  application.requested_delta_codes = 5;
  application.requested_code = 43090u;
  application.request_pending_before = true;
  application.response_pending_after = true;
  application.persistence_count_before = 2u;
  application.persistence_count_after = 0u;
  application.committed_fll_debt_after_picocodes = 307504602373LL;
  application.committed_pll_debt_after_picocodes = 34167178042LL;
  application.reason = "exact_application_and_first_consumer";
  if (!emit_record(application)) return false;

  OtisCx323MaintenanceRecord response = base_record(5u);
  response.event = OtisCx323MaintenanceEvent::ResponseComplete;
  response.transaction_record_sequence = 105u;
  response.transaction_timing_record_sequence = 205u;
  response.transaction_event = OtisCx323MaintenanceTransactionEvent::Response;
  response.request_sequence = 9u;
  response.maintenance_state_before =
      OtisCx323MaintenanceState::ResponsePending;
  response.maintenance_state_after = OtisCx323MaintenanceState::Ready;
  response.requested_delta_codes = 5;
  response.requested_code = 43090u;
  response.response_pending_before = true;
  response.committed_fll_debt_before_picocodes = 307504602373LL;
  response.committed_pll_debt_before_picocodes = 34167178042LL;
  response.committed_fll_debt_after_picocodes = 307504602373LL;
  response.committed_pll_debt_after_picocodes = 34167178042LL;
  response.reason = "fresh_exact_response_complete";
  if (!emit_record(response)) return false;

  OtisCx323MaintenanceRecord metadata_hold = base_record(6u);
  metadata_hold.event = OtisCx323MaintenanceEvent::GnssMetadataHoldEnter;
  metadata_hold.maintenance_state_after =
      OtisCx323MaintenanceState::MetadataHold;
  metadata_hold.frontier_relation = OtisCx323FrontierRelation::NotApplicable;
  metadata_hold.metadata_hold_after = true;
  metadata_hold.persistence_count_after = 0u;
  metadata_hold.evidence_burst_record_ordinal = 1u;
  metadata_hold.evidence_burst_record_count = 1u;
  metadata_hold.reason = "recoverable_gnss_metadata_anomaly";
  if (!emit_record(metadata_hold)) return false;

  OtisCx323MaintenanceRecord requalified = base_record(7u);
  requalified.event = OtisCx323MaintenanceEvent::GnssMetadataRequalified;
  requalified.maintenance_state_before =
      OtisCx323MaintenanceState::MetadataHold;
  requalified.maintenance_state_after =
      OtisCx323MaintenanceState::MetadataHold;
  requalified.frontier_relation = OtisCx323FrontierRelation::NotApplicable;
  requalified.metadata_hold_before = true;
  requalified.metadata_hold_after = true;
  requalified.requalification_d14_d8_observation_sequence = 2400u;
  requalified.evidence_burst_record_ordinal = 1u;
  requalified.evidence_burst_record_count = 1u;
  requalified.reason = "fresh_same_receiver_metadata";
  if (!emit_record(requalified)) return false;

  OtisCx323MaintenanceRecord first_window = base_record(8u);
  first_window.maintenance_state_before =
      OtisCx323MaintenanceState::MetadataHold;
  first_window.maintenance_state_after =
      OtisCx323MaintenanceState::MetadataHold;
  first_window.metadata_hold_before = true;
  first_window.metadata_hold_after = true;
  first_window.requalification_window_count_after = 1u;
  first_window.reason = "post_requalification_first_window_hold";
  if (!emit_record(first_window)) return false;

  OtisCx323MaintenanceRecord second_window = base_record(9u);
  second_window.maintenance_state_before =
      OtisCx323MaintenanceState::MetadataHold;
  second_window.metadata_hold_before = true;
  second_window.requalification_window_count_before = 1u;
  second_window.requalification_window_count_after = 2u;
  second_window.reason = "post_requalification_second_window_complete";
  if (!emit_record(second_window)) return false;

  OtisCx323MaintenanceRecord fail_static = base_record(10u);
  fail_static.event = OtisCx323MaintenanceEvent::FailStatic;
  fail_static.transaction_record_sequence = 110u;
  fail_static.transaction_timing_record_sequence = 210u;
  fail_static.transaction_event =
      OtisCx323MaintenanceTransactionEvent::ApplicationFault;
  fail_static.request_sequence = 9u;
  fail_static.maintenance_state_before =
      OtisCx323MaintenanceState::RequestPending;
  fail_static.maintenance_state_after =
      OtisCx323MaintenanceState::FailStatic;
  fail_static.frontier_relation = OtisCx323FrontierRelation::NotApplicable;
  fail_static.evidence_burst_record_ordinal = 3u;
  fail_static.evidence_burst_record_count = 3u;
  fail_static.reason = "unknown_application_or_dac_epoch";
  return emit_record(fail_static);
}

bool rejects(const OtisCx323MaintenanceRecord &record) {
  char output[4096] = {'x', '\0'};
  const int result =
      otis_format_cx323_maintenance_v1(output, sizeof(output), &record);
  return result == -1 && output[0] == '\0';
}

bool run_selftest() {
  OtisCx323MaintenanceRecord valid = base_record(1u);
  char full[4096] = {};
  if (otis_format_cx323_maintenance_v1(full, sizeof(full), &valid) <= 0)
    return false;
  char short_output[32] = {'x', '\0'};
  if (otis_format_cx323_maintenance_v1(short_output, sizeof(short_output),
                                       &valid) != -1 ||
      short_output[0] != '\0')
    return false;
  if (otis_format_cx323_maintenance_v1(nullptr, sizeof(full), &valid) != -1 ||
      otis_format_cx323_maintenance_v1(full, 0u, &valid) != -1 ||
      otis_format_cx323_maintenance_v1(full, sizeof(full), nullptr) != -1)
    return false;

  OtisCx323MaintenanceRecord invalid = valid;
  invalid.event = static_cast<OtisCx323MaintenanceEvent>(255u);
  if (!rejects(invalid)) return false;
  invalid = valid;
  invalid.maintenance_state_after =
      static_cast<OtisCx323MaintenanceState>(255u);
  if (!rejects(invalid)) return false;
  invalid = valid;
  invalid.frontier_relation = static_cast<OtisCx323FrontierRelation>(255u);
  if (!rejects(invalid)) return false;
  invalid = valid;
  invalid.transaction_event =
      static_cast<OtisCx323MaintenanceTransactionEvent>(255u);
  if (!rejects(invalid)) return false;
  invalid = valid;
  invalid.safe_cap_codes = 22u;
  if (!rejects(invalid)) return false;
  invalid = valid;
  invalid.persistence_count_after = 3u;
  if (!rejects(invalid)) return false;
  invalid = valid;
  invalid.requested_delta_codes = 1;
  if (!rejects(invalid)) return false;
  invalid = valid;
  invalid.current_applied_code = 0xA7FFu;
  if (!rejects(invalid)) return false;
  invalid = valid;
  invalid.active_policy_sha256 = "ABC";
  if (!rejects(invalid)) return false;
  invalid = valid;
  invalid.run_identity = nullptr;
  if (!rejects(invalid)) return false;
  invalid = valid;
  invalid.reason = "comma,is_not_csv_safe";
  if (!rejects(invalid)) return false;
  invalid = valid;
  invalid.committed_fll_debt_before_picocodes = 500000000001LL;
  if (!rejects(invalid)) return false;
  invalid = valid;
  invalid.hybrid_timing_record_sequence = 0u;
  if (!rejects(invalid)) return false;
  invalid = valid;
  invalid.raw_fll_demand_picocodes =
      OtisCx323Wide(0x8000000000000000ull, 0u, false);
  if (!rejects(invalid)) return false;

  char header_short[16] = {'x', '\0'};
  if (otis_format_cx323_maintenance_v1_header(header_short,
                                               sizeof(header_short)) != -1 ||
      header_short[0] != '\0')
    return false;
  return true;
}

}  // namespace

int main(int argc, char **argv) {
  if (argc != 2) return 2;
  if (strcmp(argv[1], "lifecycle") == 0) return emit_lifecycle() ? 0 : 1;
  if (strcmp(argv[1], "selftest") == 0) {
    if (!run_selftest()) return 1;
    puts("selftest_ok");
    return 0;
  }
  return 2;
}
