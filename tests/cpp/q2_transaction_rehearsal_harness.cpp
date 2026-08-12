#include <assert.h>
#include <stdint.h>
#include <string.h>

#include "otis_q2_transaction_rehearsal.h"

int main() {
  uint32_t setup_attempts = 0u;
  uint32_t automatic_attempts = 0u;
  for (uint16_t case_id = 1u;
       case_id <= OTIS_Q2_TRANSACTION_CASE_COUNT; ++case_id) {
    OtisQ2CaseResult result = {};
    assert(otis_q2_transaction_run_case(0x51A20000u + case_id, case_id,
                                        &result));
    assert(result.passed);
    assert(result.case_id == case_id);
    assert(result.query_nonce == 0x51A20000u + case_id);
    assert(result.case_name != nullptr && result.case_name[0] != '\0');
    assert(result.transaction != nullptr && result.transaction[0] != '\0');
    assert(result.disposition != nullptr && result.disposition[0] != '\0');
    setup_attempts += result.setup_i2c_attempts;
    automatic_attempts += result.automatic_i2c_attempts;
    if (case_id <= 30u) {
      assert(result.setup_i2c_attempts == 0u);
      assert(result.automatic_i2c_attempts == 0u);
    }
  }
  assert(setup_attempts == 1u);
  assert(automatic_attempts == 1u);

  OtisQ2CaseResult rejected = {};
  assert(!otis_q2_transaction_run_case(0u, 1u, &rejected));
  assert(!otis_q2_transaction_run_case(1u, 0u, &rejected));
  assert(!otis_q2_transaction_run_case(
      1u, OTIS_Q2_TRANSACTION_CASE_COUNT + 1u, &rejected));
  return 0;
}
