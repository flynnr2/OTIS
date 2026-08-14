#include <assert.h>
#include <stdint.h>

#include "otis_cx319_range_map_epoch.h"

int main() {
  OtisCx317StaticCodeState state = {true, true, true, 0xA800u};
  uint32_t epoch = 7u;
  uint16_t propagated_code = 0u;
  uint32_t propagated_epoch = 0u;
  OtisAppliedDacStateMessage application = {};
  application.requested_code = 0xA800u;
  application.applied_code = 0xA800u;
  application.initialized = true;
  application.i2c_ok = true;
  application.requested_applied_match = true;

  assert(otis_cx319_range_map_accept_manual_application(
      &state, &application, &epoch, &propagated_code, &propagated_epoch));
  assert(epoch == 8u);
  assert(propagated_epoch == 8u);
  assert(propagated_code == 0xA800u);

  application.applied_code = 0xA801u;
  assert(!otis_cx319_range_map_accept_manual_application(
      &state, &application, &epoch, &propagated_code, &propagated_epoch));
  assert(epoch == 8u);
  return 0;
}
