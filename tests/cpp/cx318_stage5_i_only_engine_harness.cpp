#include <assert.h>
#include <stdint.h>

#include <iomanip>
#include <iostream>

#include "otis_cx317_i_only_engine.h"

namespace {

OtisCx317PreviewDecision evaluate(OtisCx317IOnlyEngine *engine,
                                  uint32_t timestamp_s, int64_t counts,
                                  uint64_t session = 1u,
                                  uint64_t dac_epoch = 1u,
                                  bool frequency_available = true) {
  OtisCx317PreviewInput input = {};
  input.timestamp_s = timestamp_s;
  input.frequency_error_hz =
      static_cast<double>(counts) / static_cast<double>(600u);
  input.current_code = 0xA828u;
  input.temperature_c = 29.0;
  input.frequency_available = frequency_available;
  input.reference_valid = true;
  input.estimator_valid = true;
  input.count_valid = true;
  input.model_applicable = true;
  input.applied_code_matches = true;
  input.i2c_ok = true;
  input.temperature_available = true;
  input.accumulated_edge_error_counts = counts;
  input.capture_session = session;
  input.dac_epoch_identity = dac_epoch;
  input.accumulated_edge_error_counts_available = frequency_available;
  OtisCx317PreviewDecision decision = {};
  otis_cx317_i_only_engine_evaluate(engine, &input, &decision);
  return decision;
}

void emit(const char *label, const OtisCx317PreviewDecision &decision) {
  const auto &tight = decision.tight_deadband;
  std::cout << label << ',' << decision.timestamp_s << ',' << decision.reason
            << ',' << (decision.preview_available ? 1 : 0) << ','
            << decision.limited_delta_codes << ',' << decision.proposed_code
            << ',' << (decision.tight_deadband_decision_available ? 1 : 0)
            << ','
            << otis_cx318_stage5_tight_deadband_state_name(tight.state_before)
            << ','
            << otis_cx318_stage5_tight_deadband_state_name(tight.state_after)
            << ','
            << otis_cx318_stage5_tight_deadband_reason_name(tight.reason) << ','
            << static_cast<unsigned>(tight.entry_pending_count) << ','
            << static_cast<unsigned>(tight.release_pending_count) << ','
            << (tight.frequency_controller_eligible ? 1 : 0) << ','
            << (tight.requalified ? 1 : 0) << '\n';
}

}  // namespace

int main() {
  OtisCx317IOnlyEngine engine = {};
  otis_cx317_i_only_engine_init(&engine, 0u);
  std::cout << "label,timestamp_s,reason,preview_available,limited_delta_codes,"
               "proposed_code,tight_available,state_before,state_after,"
               "tight_reason,entry_pending,release_pending,controller_eligible,"
               "requalified\n";

  // The warmup boundary starts one fresh 600-second qualification span.
  emit("warmup", evaluate(&engine, 1800u, 0, 1u, 1u, false));
  emit("entry_1", evaluate(&engine, 2400u, 2));
  emit("entry_2", evaluate(&engine, 3000u, -2));
  emit("inside_3", evaluate(&engine, 3600u, 3));
  emit("release_1", evaluate(&engine, 4200u, 4));
  emit("release_2", evaluate(&engine, 4800u, -4));

  otis_cx317_i_only_engine_note_dac_epoch(&engine, 5000u);
  emit("epoch_cadence", evaluate(&engine, 6500u, 3, 1u, 2u));
  emit("epoch_eligible", evaluate(&engine, 7100u, 3, 1u, 2u));
  emit("session_entry_1", evaluate(&engine, 7700u, 2, 2u, 2u));
  emit("session_entry_2", evaluate(&engine, 8300u, 2, 2u, 2u));
  return 0;
}
