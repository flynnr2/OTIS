#ifndef OTIS_Q2_TRANSACTION_REHEARSAL_H
#define OTIS_Q2_TRANSACTION_REHEARSAL_H

#include <stdint.h>

// Diagnostic-only, finite Q2 transaction cases.  The case engine invokes the
// production setup-authority and active-transaction state machines, but never
// invokes the DAC driver.  The one physical (electrically inhibited) setup
// write is deliberately left to the ordinary ACTIVE SETUP path.
constexpr uint16_t OTIS_Q2_TRANSACTION_CASE_COUNT = 38u;

enum OtisQ2Phase : uint16_t {
  OTIS_Q2_PHASE_RECEIVED = 1u << 0,
  OTIS_Q2_PHASE_AUTHORIZED = 1u << 1,
  OTIS_Q2_PHASE_CORE0_ACCEPTED = 1u << 2,
  OTIS_Q2_PHASE_RELEASED = 1u << 3,
  OTIS_Q2_PHASE_CONSUMED = 1u << 4,
  OTIS_Q2_PHASE_APPLIED = 1u << 5,
  OTIS_Q2_PHASE_FAILED = 1u << 6,
  OTIS_Q2_PHASE_RECOVERY_READY = 1u << 7,
};

struct OtisQ2CaseResult {
  uint32_t query_nonce;
  uint16_t case_id;
  const char *case_name;
  const char *transaction;
  const char *disposition;
  uint16_t phase_mask;
  uint16_t setup_i2c_attempts;
  uint16_t automatic_i2c_attempts;
  bool retry_rejected;
  bool passed;
};

bool otis_q2_transaction_run_case(uint32_t query_nonce, uint16_t case_id,
                                  OtisQ2CaseResult *result);

#endif
