#ifndef OTIS_FORWARDED_CLOCK_OUTPUT_H
#define OTIS_FORWARDED_CLOCK_OUTPUT_H

#include <stdint.h>

struct OtisForwardedClockOutputStatus {
  bool selected;
  bool configured;
  bool readback_valid;
  bool valid;
  uint32_t source_gpio;
  uint32_t destination_gpio;
  uint32_t integer_divider;
  uint32_t fractional_divider;
  const char *reason;
};

// Must be called only after the D8 PPS-gated backend has initialized its PIO
// input. It never changes clk_sys, clk_ref, USB, PIO or DMA clocks.
bool otis_forwarded_clock_output_begin(void);
void otis_forwarded_clock_output_get_status(OtisForwardedClockOutputStatus *out);

#endif
