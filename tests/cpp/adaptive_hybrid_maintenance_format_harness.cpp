#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "otis_adaptive_hybrid_maintenance_format.h"

namespace {

constexpr char kSha[] =
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
constexpr char kRunIdentity[] = "adaptive_hybrid_regulation:1";
constexpr char kBuildIdentity[] =
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:"
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
constexpr char kImageIdentity[] = "adaptive_hybrid_regulation";

bool set_wide(const char *text, OtisAdaptiveHybridWide *value) {
  return otis_adaptive_hybrid_wide_parse_decimal(text, value);
}

OtisAdaptiveHybridMaintenanceRecord base_record(uint64_t sequence) {
  OtisAdaptiveHybridMaintenanceRecord record = {};
  record.maintenance_record_sequence = sequence;
  record.event = OtisAdaptiveHybridMaintenanceEvent::Decision;
  record.event_timestamp_ticks = sequence * 1000000u;
  record.run_identity = kRunIdentity;
  record.build_identity = kBuildIdentity;
  record.image_identity = kImageIdentity;
  record.active_policy_sha256 = kSha;
  record.capture_session = 7u;
  record.source_acceptance_epoch = 3u;
  record.source_opening_accepted_boundary_ordinal = 1200u;
  record.source_closing_accepted_boundary_ordinal = 1800u;
  record.frequency_estimator_sha256 = kSha;
  record.phase_epoch = 3u;
  record.phase_observation_sequence = 1800u;
  record.phase_valid = true;
  record.current_applied_code = 43085u;
  record.current_dac_epoch = 13u;
  record.hybrid_record_sequence = sequence;
  record.decision_sequence = sequence;
  record.transaction_event = OtisAdaptiveHybridMaintenanceTransactionEvent::None;
  record.maintenance_state_before = OtisAdaptiveHybridMaintenanceState::Ready;
  record.maintenance_state_after =
      OtisAdaptiveHybridMaintenanceState::PersistenceHold;
  record.frontier_relation = OtisAdaptiveHybridFrontierRelation::Contiguous;
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
  record.evidence_burst_record_ordinal = 2u;
  record.evidence_burst_record_count = 2u;
  record.reason = "persistence_first_interval_hold";
  return record;
}

bool emit_header() {
  char output[2048] = {};
  const int used =
      otis_format_adaptive_hybrid_maintenance_v2_header(output, sizeof(output));
  if (used <= 0 || static_cast<size_t>(used) != strlen(output)) return false;
  fputs(output, stdout);
  return true;
}

bool emit_record(const OtisAdaptiveHybridMaintenanceRecord &record) {
  char output[4096] = {};
  const int used =
      otis_format_adaptive_hybrid_maintenance_v2(output, sizeof(output), &record);
  if (used <= 0 || static_cast<size_t>(used) != strlen(output)) return false;
  fputs(output, stdout);
  return true;
}

bool emit_lifecycle() {
  if (!emit_header()) return false;

  OtisAdaptiveHybridMaintenanceRecord activation = base_record(1u);
  activation.event = OtisAdaptiveHybridMaintenanceEvent::PolicyActivation;
  activation.source_acceptance_epoch = 0u;
  activation.source_opening_accepted_boundary_ordinal = 0u;
  activation.source_closing_accepted_boundary_ordinal = 0u;
  activation.hybrid_record_sequence = 0u;
  activation.decision_sequence = 0u;
  activation.maintenance_state_before =
      OtisAdaptiveHybridMaintenanceState::PolicyInactive;
  activation.maintenance_state_after = OtisAdaptiveHybridMaintenanceState::Ready;
  activation.frontier_relation = OtisAdaptiveHybridFrontierRelation::NotApplicable;
  activation.persistence_count_after = 0u;
  activation.committed_fll_debt_after_picocodes = 0;
  activation.committed_pll_debt_after_picocodes = 0;
  activation.evidence_burst_record_ordinal = 1u;
  activation.evidence_burst_record_count = 1u;
  activation.reason = "new_policy_activation";
  if (!emit_record(activation)) return false;

  OtisAdaptiveHybridMaintenanceRecord hold = base_record(2u);
  if (!set_wide("-170141183460469231731687303715884105727",
                &hold.raw_fll_demand_picocodes) ||
      !set_wide("170141183460469231731687303715884105727",
                &hold.raw_pll_demand_picocodes) ||
      !set_wide("-170141183460469231731687303715884105727",
                &hold.candidate_total_demand_picocodes) ||
      !emit_record(hold))
    return false;

  OtisAdaptiveHybridMaintenanceRecord request = base_record(3u);
  request.transaction_record_sequence = 103u;
  request.transaction_event =
      OtisAdaptiveHybridMaintenanceTransactionEvent::RequestCreated;
  request.request_sequence = 9u;
  request.maintenance_state_before =
      OtisAdaptiveHybridMaintenanceState::PersistenceHold;
  request.maintenance_state_after =
      OtisAdaptiveHybridMaintenanceState::RequestPending;
  request.persistence_count_before = 1u;
  request.persistence_count_after = 2u;
  request.requested_delta_codes = 5;
  request.requested_code = 43090u;
  request.request_pending_after = true;
  request.evidence_burst_record_ordinal = 3u;
  request.evidence_burst_record_count = 3u;
  request.reason = "maintenance_request_ready";
  if (!emit_record(request)) return false;

  OtisAdaptiveHybridMaintenanceRecord application = base_record(4u);
  application.event =
      OtisAdaptiveHybridMaintenanceEvent::ApplicationFirstConsumer;
  application.transaction_record_sequence = 104u;
  application.transaction_event =
      OtisAdaptiveHybridMaintenanceTransactionEvent::Application;
  application.request_sequence = 9u;
  application.application_sequence = 4u;
  application.actual_applied_code = 43090u;
  application.actual_dac_epoch = 14u;
  application.downstream_epoch_exact = true;
  application.maintenance_state_before =
      OtisAdaptiveHybridMaintenanceState::RequestPending;
  application.maintenance_state_after =
      OtisAdaptiveHybridMaintenanceState::ResponsePending;
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

  OtisAdaptiveHybridMaintenanceRecord response = base_record(5u);
  response.event = OtisAdaptiveHybridMaintenanceEvent::ResponseComplete;
  response.transaction_record_sequence = 105u;
  response.transaction_event = OtisAdaptiveHybridMaintenanceTransactionEvent::Response;
  response.request_sequence = 9u;
  response.maintenance_state_before =
      OtisAdaptiveHybridMaintenanceState::ResponsePending;
  response.maintenance_state_after = OtisAdaptiveHybridMaintenanceState::Ready;
  response.requested_delta_codes = 5;
  response.requested_code = 43090u;
  response.response_pending_before = true;
  response.committed_fll_debt_before_picocodes = 307504602373LL;
  response.committed_pll_debt_before_picocodes = 34167178042LL;
  response.committed_fll_debt_after_picocodes = 307504602373LL;
  response.committed_pll_debt_after_picocodes = 34167178042LL;
  response.reason = "fresh_exact_response_complete";
  if (!emit_record(response)) return false;

  OtisAdaptiveHybridMaintenanceRecord metadata_hold = base_record(6u);
  metadata_hold.event = OtisAdaptiveHybridMaintenanceEvent::GnssMetadataHoldEnter;
  metadata_hold.maintenance_state_after =
      OtisAdaptiveHybridMaintenanceState::MetadataHold;
  metadata_hold.frontier_relation = OtisAdaptiveHybridFrontierRelation::NotApplicable;
  metadata_hold.metadata_hold_after = true;
  metadata_hold.persistence_count_after = 0u;
  metadata_hold.evidence_burst_record_ordinal = 1u;
  metadata_hold.evidence_burst_record_count = 1u;
  metadata_hold.reason = "recoverable_gnss_metadata_anomaly";
  if (!emit_record(metadata_hold)) return false;

  OtisAdaptiveHybridMaintenanceRecord requalified = base_record(7u);
  requalified.event = OtisAdaptiveHybridMaintenanceEvent::GnssMetadataRequalified;
  requalified.maintenance_state_before =
      OtisAdaptiveHybridMaintenanceState::MetadataHold;
  requalified.maintenance_state_after =
      OtisAdaptiveHybridMaintenanceState::MetadataHold;
  requalified.frontier_relation = OtisAdaptiveHybridFrontierRelation::NotApplicable;
  requalified.metadata_hold_before = true;
  requalified.metadata_hold_after = true;
  requalified.requalification_accepted_boundary_ordinal = 2400u;
  requalified.evidence_burst_record_ordinal = 1u;
  requalified.evidence_burst_record_count = 1u;
  requalified.reason = "fresh_same_receiver_metadata";
  if (!emit_record(requalified)) return false;

  OtisAdaptiveHybridMaintenanceRecord first_window = base_record(8u);
  first_window.maintenance_state_before =
      OtisAdaptiveHybridMaintenanceState::MetadataHold;
  first_window.maintenance_state_after =
      OtisAdaptiveHybridMaintenanceState::MetadataHold;
  first_window.metadata_hold_before = true;
  first_window.metadata_hold_after = true;
  first_window.requalification_window_count_after = 1u;
  first_window.reason = "post_requalification_first_window_hold";
  if (!emit_record(first_window)) return false;

  OtisAdaptiveHybridMaintenanceRecord second_window = base_record(9u);
  second_window.maintenance_state_before =
      OtisAdaptiveHybridMaintenanceState::MetadataHold;
  second_window.metadata_hold_before = true;
  second_window.requalification_window_count_before = 1u;
  second_window.requalification_window_count_after = 2u;
  second_window.reason = "post_requalification_second_window_complete";
  if (!emit_record(second_window)) return false;

  OtisAdaptiveHybridMaintenanceRecord fail_static = base_record(10u);
  fail_static.event = OtisAdaptiveHybridMaintenanceEvent::FailStatic;
  fail_static.transaction_record_sequence = 110u;
  fail_static.transaction_event =
      OtisAdaptiveHybridMaintenanceTransactionEvent::ApplicationFault;
  fail_static.request_sequence = 9u;
  fail_static.maintenance_state_before =
      OtisAdaptiveHybridMaintenanceState::RequestPending;
  fail_static.maintenance_state_after =
      OtisAdaptiveHybridMaintenanceState::FailStatic;
  fail_static.frontier_relation = OtisAdaptiveHybridFrontierRelation::NotApplicable;
  fail_static.evidence_burst_record_ordinal = 2u;
  fail_static.evidence_burst_record_count = 2u;
  fail_static.reason = "unknown_application_or_dac_epoch";
  return emit_record(fail_static);
}

bool rejects(const OtisAdaptiveHybridMaintenanceRecord &record) {
  char output[4096] = {'x', '\0'};
  const int result =
      otis_format_adaptive_hybrid_maintenance_v2(output, sizeof(output), &record);
  return result == -1 && output[0] == '\0';
}

bool run_selftest() {
  OtisAdaptiveHybridMaintenanceRecord valid = base_record(1u);
  char full[4096] = {};
  if (otis_format_adaptive_hybrid_maintenance_v2(full, sizeof(full), &valid) <= 0)
    return false;
  char short_output[32] = {'x', '\0'};
  if (otis_format_adaptive_hybrid_maintenance_v2(short_output, sizeof(short_output),
                                       &valid) != -1 ||
      short_output[0] != '\0')
    return false;
  if (otis_format_adaptive_hybrid_maintenance_v2(nullptr, sizeof(full), &valid) != -1 ||
      otis_format_adaptive_hybrid_maintenance_v2(full, 0u, &valid) != -1 ||
      otis_format_adaptive_hybrid_maintenance_v2(full, sizeof(full), nullptr) != -1)
    return false;

  OtisAdaptiveHybridMaintenanceRecord invalid = valid;
  invalid.event = static_cast<OtisAdaptiveHybridMaintenanceEvent>(255u);
  if (!rejects(invalid)) return false;
  invalid = valid;
  invalid.maintenance_state_after =
      static_cast<OtisAdaptiveHybridMaintenanceState>(255u);
  if (!rejects(invalid)) return false;
  invalid = valid;
  invalid.frontier_relation = static_cast<OtisAdaptiveHybridFrontierRelation>(255u);
  if (!rejects(invalid)) return false;
  invalid = valid;
  invalid.transaction_event =
      static_cast<OtisAdaptiveHybridMaintenanceTransactionEvent>(255u);
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
  invalid.hybrid_record_sequence = 0u;
  if (!rejects(invalid)) return false;
  invalid = valid;
  invalid.raw_fll_demand_picocodes =
      OtisAdaptiveHybridWide(0x8000000000000000ull, 0u, false);
  if (!rejects(invalid)) return false;

  char header_short[16] = {'x', '\0'};
  if (otis_format_adaptive_hybrid_maintenance_v2_header(header_short,
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
