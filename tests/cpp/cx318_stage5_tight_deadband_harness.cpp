#include <cstdint>
#include <iostream>

#include "otis_cx318_stage5_tight_deadband.h"

int main() {
  OtisCx318Stage5TightDeadband deadband;
  otis_cx318_stage5_tight_deadband_init(&deadband);

  std::cout << "state_before,state_after,reason,absolute_available,absolute_counts,"
               "entry_pending,release_pending,actionable,actuation_authorized,"
               "authorization_consumed,frequency_controller_eligible,policy_id\n";
  OtisCx318Stage5TightDeadbandInput input;
  unsigned counts_available = 0u;
  unsigned fresh = 0u;
  while (std::cin >> input.accumulated_edge_error_counts >> counts_available >> fresh >>
         input.session >> input.dac_epoch) {
    input.accumulated_edge_error_counts_available = counts_available != 0u;
    input.fresh = fresh != 0u;
    OtisCx318Stage5TightDeadbandDecision decision;
    if (!otis_cx318_stage5_tight_deadband_observe(&deadband, &input, &decision))
      return 2;
    std::cout << otis_cx318_stage5_tight_deadband_state_name(decision.state_before)
              << ','
              << otis_cx318_stage5_tight_deadband_state_name(decision.state_after)
              << ',' << otis_cx318_stage5_tight_deadband_reason_name(decision.reason)
              << ',' << decision.absolute_edge_error_counts_available << ','
              << decision.absolute_edge_error_counts << ','
              << static_cast<unsigned>(decision.entry_pending_count) << ','
              << static_cast<unsigned>(decision.release_pending_count) << ','
              << decision.actionable << ',' << decision.actuation_authorized << ','
              << decision.authorization_consumed << ','
              << decision.frequency_controller_eligible << ',' << decision.policy_id
              << '\n';
  }
  return 0;
}
