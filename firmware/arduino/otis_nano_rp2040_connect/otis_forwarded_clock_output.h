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
  uint32_t applied_auxsrc;
  uint32_t applied_integer_divider;
  uint32_t applied_fractional_divider;
  uint32_t source_gpio_function;
  uint32_t destination_gpio_function;
  uint32_t nominal_frequency_hz;
  uint32_t drive_strength_ma;
  uint64_t first_valid_ticks;
  bool inversion;
  bool slew_rate_fast;
  const char *contract_id;
  const char *contract_sha256;
  const char *reason;
};

// Must be called only after the D8 PPS-gated backend has initialized its PIO
// input. It never changes clk_sys, clk_ref, USB, PIO or DMA clocks.
bool otis_forwarded_clock_output_begin(void);
void otis_forwarded_clock_output_get_status(OtisForwardedClockOutputStatus *out);

#endif
