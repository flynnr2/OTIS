#include "otis_timebase.h"

#include <hardware/clocks.h>

bool otis_timebase_begin(void) {
  return clock_get_hz(clk_sys) != 0u;
}
