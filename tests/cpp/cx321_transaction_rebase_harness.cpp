#include <assert.h>
#include <stdint.h>
#include <stdio.h>

#include "otis_cx317_active_transaction.h"

int main() {
  OtisCx317ActiveTransaction transaction = {};
  transaction.state = OtisCx317ActiveState::AwaitingResponse;
  transaction.have_request = true;
  transaction.have_acceptance = true;
  transaction.have_application = true;
  transaction.correction_count = 1u;
  transaction.cumulative_movement_codes = 21u;
  transaction.applied_code = 0xA827u;
  transaction.dac_epoch = 2u;
  transaction.recent_applied_directions[0] = -1;
  transaction.recent_applied_direction_count = 1u;

  assert(otis_cx317_active_rebase_natural_history_after_identification(
      &transaction, 0xA827u, 2u));
  assert(transaction.state == OtisCx317ActiveState::AwaitingResponse);
  assert(transaction.correction_count == 1u);
  assert(transaction.cumulative_movement_codes == 21u);
  assert(transaction.recent_applied_direction_count == 0u);
  assert(transaction.recent_applied_directions[0] == 0);
  assert(otis_cx317_active_complete_identification_response(
      &transaction, 0xA827u, 2u));
  assert(transaction.state == OtisCx317ActiveState::Disarmed);
  assert(transaction.correction_count == 1u);
  assert(transaction.cumulative_movement_codes == 21u);

  transaction.state = OtisCx317ActiveState::AwaitingResponse;
  transaction.have_application = true;
  transaction.cumulative_movement_codes = 20u;
  assert(!otis_cx317_active_rebase_natural_history_after_identification(
      &transaction, 0xA827u, 2u));
  assert(transaction.state == OtisCx317ActiveState::Fault);
  puts("cx321_transaction_rebase_harness_passed");
  return 0;
}
