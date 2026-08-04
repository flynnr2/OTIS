#include <iomanip>
#include <iostream>

#include "otis_cx317_i_only_engine.h"

namespace {

OtisCx317PreviewInput valid_input(uint32_t timestamp_s, double error_hz) {
  return {
      timestamp_s, error_hz, 0xA82Au, 29.0, true, true, true, true,
      true, true, true, true, false, false, false,
  };
}

void emit(const char *scenario, const OtisCx317PreviewDecision &decision) {
  std::cout << scenario << ',' << decision.timestamp_s << ','
            << static_cast<unsigned>(decision.state) << ',' << decision.reason
            << ',' << decision.preview_available << ',' << std::setprecision(17)
            << decision.raw_delta_codes << ',' << decision.limited_delta_codes
            << ',' << decision.proposed_code << ',' << decision.integrator_codes
            << ',' << decision.step_limited << ',' << decision.range_clamped
            << ',' << decision.actionable << '\n';
}

void evaluate(OtisCx317IOnlyEngine *engine, const char *scenario,
              OtisCx317PreviewInput input) {
  OtisCx317PreviewDecision decision;
  otis_cx317_i_only_engine_evaluate(engine, &input, &decision);
  emit(scenario, decision);
}

}  // namespace

int main() {
  std::cout << "scenario,timestamp_s,state,reason,preview_available,raw_delta_codes,"
               "limited_delta_codes,proposed_code,integrator_codes,step_limited,"
               "range_clamped,actionable\n";

  OtisCx317IOnlyEngine nominal;
  otis_cx317_i_only_engine_init(&nominal, 0u);
  evaluate(&nominal, "nominal", valid_input(0u, 0.02));
  evaluate(&nominal, "nominal", valid_input(1800u, 0.02));
  evaluate(&nominal, "nominal", valid_input(2400u, 0.02));

  OtisCx317IOnlyEngine settling;
  otis_cx317_i_only_engine_init(&settling, 0u);
  evaluate(&settling, "settling", valid_input(0u, 0.02));
  evaluate(&settling, "settling", valid_input(1800u, 0.02));
  evaluate(&settling, "settling", valid_input(2400u, 0.02));
  OtisCx317PreviewInput epoch = valid_input(3000u, 0.02);
  epoch.dac_epoch = true;
  evaluate(&settling, "settling", epoch);
  evaluate(&settling, "settling", valid_input(4499u, 0.02));
  evaluate(&settling, "settling", valid_input(4500u, 0.02));

  OtisCx317IOnlyEngine fault;
  otis_cx317_i_only_engine_init(&fault, 0u);
  evaluate(&fault, "fault", valid_input(0u, 0.02));
  evaluate(&fault, "fault", valid_input(1800u, 0.02));
  evaluate(&fault, "fault", valid_input(2400u, 0.02));
  OtisCx317PreviewInput lost = valid_input(3000u, 0.02);
  lost.reference_valid = false;
  evaluate(&fault, "fault", lost);
  OtisCx317PreviewInput recovery = valid_input(3600u, 0.02);
  recovery.recovery_requested = true;
  evaluate(&fault, "fault", recovery);
  evaluate(&fault, "fault", valid_input(4200u, 0.02));

  OtisCx317IOnlyEngine model_hold;
  otis_cx317_i_only_engine_init(&model_hold, 0u);
  evaluate(&model_hold, "model_hold", valid_input(0u, 0.02));
  evaluate(&model_hold, "model_hold", valid_input(1800u, 0.02));
  evaluate(&model_hold, "model_hold", valid_input(2400u, 0.02));
  OtisCx317PreviewInput outside_model = valid_input(3000u, 0.02);
  outside_model.model_applicable = false;
  outside_model.temperature_available = false;
  evaluate(&model_hold, "model_hold", outside_model);
  evaluate(&model_hold, "model_hold", valid_input(3600u, 0.02));
  evaluate(&model_hold, "model_hold", valid_input(4200u, 0.02));

  OtisCx317IOnlyEngine abort;
  otis_cx317_i_only_engine_init(&abort, 0u);
  OtisCx317PreviewInput stop = valid_input(0u, 0.02);
  stop.operator_abort = true;
  evaluate(&abort, "abort", stop);
  evaluate(&abort, "abort", valid_input(3000u, 0.02));
  return 0;
}
