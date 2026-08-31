#include <stdint.h>

#include <iostream>
#include <string>

#include "otis_cx323_phase_priority_maintenance.h"

namespace {

std::string wide_text(OtisCx323Wide value) {
  char decimal[OTIS_CX323_WIDE_DECIMAL_CAPACITY] = {};
  return otis_cx323_wide_format_decimal(value, decimal, sizeof(decimal))
             ? std::string(decimal)
             : std::string("INVALID");
}

bool parse_wide(const std::string &text, OtisCx323Wide *value) {
  return value != nullptr &&
         otis_cx323_wide_parse_decimal(text.c_str(), value);
}

void emit(const char *command, bool ok, const OtisCx323Engine *engine,
          const OtisCx323Decision *decision, OtisCx323Wide wide_result = 0) {
  const char *reason = decision != nullptr
                           ? decision->reason
                           : (engine != nullptr ? engine->last_reason : "");
  const char *fail = engine != nullptr && engine->fail_static_reason != nullptr
                         ? engine->fail_static_reason
                         : "";
  std::cout
      << command << ',' << ok << ',' << (reason == nullptr ? "" : reason)
      << ',' << (decision == nullptr ? 0 : decision->decision_sequence) << ','
      << (decision == nullptr ? 0 : decision->decision_timestamp_ticks) << ','
      << (decision == nullptr ? 0 : decision->requested_delta_codes) << ','
      << (decision == nullptr ? 0 : decision->requested_code) << ','
      << (decision == nullptr ? 0 : decision->safe_cap_codes) << ','
      << (decision == nullptr ? (engine == nullptr ? 0 : engine->persistence_count)
                              : decision->persistence_count)
      << ','
      << wide_text(decision == nullptr ? 0
                                       : decision->raw_combined_picocodes)
      << ','
      << wide_text(decision == nullptr ? 0 : decision->raw_fll_picocodes)
      << ','
      << wide_text(decision == nullptr ? 0 : decision->raw_pll_picocodes)
      << ','
      << (decision == nullptr
              ? 0
              : decision->counterfactual_frequency_only_delta_codes)
      << ',' << (decision != nullptr && decision->phase_materially_influenced)
      << ',' << (decision != nullptr && decision->step_limited) << ','
      << (decision != nullptr && decision->range_clamped) << ','
      << (decision != nullptr && decision->cadence_limited) << ','
      << (decision != nullptr && decision->count_limited) << ','
      << (decision != nullptr && decision->cumulative_budget_limited)
      << ',' << (engine == nullptr ? 0 : engine->debt.fll_picocodes) << ','
      << (engine == nullptr ? 0 : engine->debt.pll_picocodes) << ','
      << (engine != nullptr && engine->request_pending) << ','
      << (engine != nullptr && engine->response_pending) << ','
      << (engine != nullptr && engine->metadata_hold) << ','
      << (engine == nullptr ? 0 : engine->requalification_window_count) << ','
      << (engine == nullptr || !engine->last_application_available
              ? 0
              : engine->last_application_s)
      << ','
      << (engine == nullptr || !engine->last_application_available
              ? 0
              : engine->last_application_ticks)
      << ',' << fail << ','
      << (engine == nullptr ? 0 : engine->applied_code) << ','
      << (engine == nullptr ? 0 : engine->dac_epoch) << ','
      << (engine == nullptr ? 0 : engine->application_count) << ','
      << (engine == nullptr ? 0 : engine->cumulative_movement_codes) << ','
      << wide_text(wide_result) << '\n';
}

}  // namespace

int main() {
  std::cout << "command,ok,reason,decision_sequence,decision_timestamp_ticks,"
               "requested_delta_codes,"
               "requested_code,safe_cap_codes,persistence_count,"
               "raw_combined_picocodes,raw_fll_picocodes,raw_pll_picocodes,"
               "counterfactual_frequency_only_delta_codes,"
               "phase_materially_influenced,step_limited,range_clamped,"
               "cadence_limited,count_limited,cumulative_budget_limited,"
               "debt_fll_picocodes,debt_pll_picocodes,request_pending,"
               "response_pending,metadata_hold,requalification_window_count,"
               "last_application_s,last_application_ticks,"
               "fail_static_reason,applied_code,"
               "dac_epoch,application_count,cumulative_movement_codes,"
               "wide_result\n";

  OtisCx323Policy policy = otis_cx323_default_policy();
  OtisCx323Engine engine = {};
  OtisCx323Decision last_decision = {};
  OtisCx323Decision pending_decision = {};
  bool have_decision = false;
  bool have_pending_decision = false;
  std::string command;
  while (std::cin >> command) {
    if (command == "INIT") {
      int32_t code = 0;
      uint64_t epoch = 0;
      std::cin >> code >> epoch;
      const bool ok = otis_cx323_engine_init(&engine, &policy, code, epoch);
      have_decision = false;
      have_pending_decision = false;
      emit("INIT", ok, &engine, nullptr);
    } else if (command == "DECIDE") {
      OtisCx323Observation observation = {};
      int tight = 0;
      int phase_valid = 0;
      int authority_valid = 0;
      int settled = 0;
      int cadence = 0;
      int metadata = 0;
      std::cin >> observation.timestamp_s >> observation.timestamp_ticks >>
          observation.capture_session >>
          observation.source_first_sequence >> observation.source_last_sequence >>
          observation.dac_epoch >> observation.applied_code >>
          observation.accumulated_edge_error_counts >> tight >>
          observation.phase_epoch >> observation.relative_phase_cycles >>
          observation.selected_estimator_identity >> phase_valid >>
          authority_valid >> settled >> cadence >> metadata;
      observation.tight_inside = tight != 0;
      observation.phase_valid = phase_valid != 0;
      observation.authority_valid = authority_valid != 0;
      observation.settled = settled != 0;
      observation.cadence_eligible = cadence != 0;
      observation.metadata_qualified = metadata != 0;
      const bool ok =
          otis_cx323_engine_decide(&engine, &observation, &last_decision);
      have_decision = ok;
      if (ok && engine.request_pending &&
          last_decision.requested_delta_codes != 0) {
        pending_decision = last_decision;
        have_pending_decision = true;
      }
      emit("DECIDE", ok, &engine, &last_decision);
    } else if (command == "REJECT") {
      const bool ok = otis_cx323_engine_reject_or_expire_request(&engine);
      have_pending_decision = false;
      emit("REJECT", ok, &engine, nullptr);
    } else if (command == "APPLY" || command == "APPLY_BAD_DECISION" ||
               command == "APPLY_BAD_PROJECTION" ||
               command == "APPLY_PENDING") {
      int32_t code = 0;
      uint64_t epoch = 0;
      int exact = 0;
      std::cin >> code >> epoch >> exact;
      OtisCx323Decision submitted =
          command == "APPLY_PENDING" ? pending_decision : last_decision;
      if (command == "APPLY_BAD_DECISION") ++submitted.decision_sequence;
      if (command == "APPLY_BAD_PROJECTION")
        ++submitted.counterfactual_frequency_only_delta_codes;
      const bool have_submission = command == "APPLY_PENDING"
                                       ? have_pending_decision
                                       : have_decision;
      const bool ok = have_submission &&
          otis_cx323_engine_note_application_and_first_consumer(
              &engine, &submitted, code, epoch, exact != 0);
      have_pending_decision = false;
      emit(command.c_str(), ok, &engine, nullptr);
    } else if (command == "RESPONSE") {
      int exact = 0;
      std::cin >> exact;
      const bool ok =
          otis_cx323_engine_complete_response(&engine, exact != 0);
      emit("RESPONSE", ok, &engine, nullptr);
    } else if (command == "HOLD") {
      const bool ok = otis_cx323_engine_enter_metadata_hold(&engine);
      emit("HOLD", ok, &engine, nullptr);
    } else if (command == "REQUAL") {
      uint64_t frontier = 0;
      std::cin >> frontier;
      const bool ok =
          otis_cx323_engine_requalify_metadata(&engine, frontier);
      emit("REQUAL", ok, &engine, nullptr);
    } else if (command == "ACTIVATE") {
      const bool ok = otis_cx323_engine_new_policy_activation(&engine);
      emit("ACTIVATE", ok, &engine, nullptr);
    } else if (command == "SET_DEBT") {
      std::cin >> engine.debt.fll_picocodes >> engine.debt.pll_picocodes;
      engine.last_reason = "test_debt_set";
      emit("SET_DEBT", true, &engine, nullptr);
    } else if (command == "SET_BUDGET") {
      std::cin >> engine.application_count >>
          engine.cumulative_movement_codes;
      engine.last_reason = "test_budget_set";
      emit("SET_BUDGET", true, &engine, nullptr);
    } else if (command == "SET_LAST_APPLICATION") {
      int available = 0;
      std::cin >> available >> engine.last_application_s;
      engine.last_application_available = available != 0;
      engine.last_application_ticks =
          engine.last_application_s * 16000000ull;
      engine.last_reason = "test_last_application_set";
      emit("SET_LAST_APPLICATION", true, &engine, nullptr);
    } else if (command == "SET_LAST_APPLICATION_TICKS") {
      int available = 0;
      std::cin >> available >> engine.last_application_s >>
          engine.last_application_ticks;
      engine.last_application_available = available != 0;
      engine.last_reason = "test_last_application_ticks_set";
      emit("SET_LAST_APPLICATION_TICKS", true, &engine, nullptr);
    } else if (command == "SET_DIRECTIONS") {
      unsigned count = 0;
      int first = 0;
      int second = 0;
      int third = 0;
      std::cin >> count >> first >> second >> third >>
          engine.chatter_origin_code;
      engine.direction_count = count > 3 ? 3 : static_cast<uint8_t>(count);
      engine.direction_history[0] = static_cast<int8_t>(first);
      engine.direction_history[1] = static_cast<int8_t>(second);
      engine.direction_history[2] = static_cast<int8_t>(third);
      engine.last_reason = "test_directions_set";
      emit("SET_DIRECTIONS", true, &engine, nullptr);
    } else if (command == "CONVERT") {
      std::string text;
      std::cin >> text;
      OtisCx323Wide input = 0;
      OtisCx323Wide result = 0;
      const bool ok = parse_wide(text, &input) &&
                      otis_cx323_centre_to_picocodes(input, &result);
      emit("CONVERT", ok, nullptr, nullptr, result);
    } else if (command == "ROUND") {
      std::string numerator_text;
      std::string denominator_text;
      std::cin >> numerator_text >> denominator_text;
      OtisCx323Wide numerator = 0;
      OtisCx323Wide denominator = 0;
      OtisCx323Wide result = 0;
      const bool ok = parse_wide(numerator_text, &numerator) &&
                      parse_wide(denominator_text, &denominator) &&
                      otis_cx323_round_ratio(numerator, denominator, &result);
      emit("ROUND", ok, nullptr, nullptr, result);
    } else {
      return 2;
    }
  }
  return 0;
}
