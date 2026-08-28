#include "otis_forwarded_clock_output.h"

#include <hardware/clocks.h>
#include <hardware/gpio.h>
#include <hardware/structs/clocks.h>

#include "otis_board.h"
#include "otis_config.h"

namespace {

constexpr uint32_t kIntegerDivider = 1u;
constexpr uint32_t kFractionalDivider = 0u;
constexpr uint32_t kGpout0CtrlAuxsrcMask = CLOCKS_CLK_GPOUT0_CTRL_AUXSRC_BITS;
constexpr uint32_t kGpout0CtrlAuxsrcGpin0 =
    CLOCKS_CLK_GPOUT0_CTRL_AUXSRC_VALUE_CLKSRC_GPIN0;

OtisForwardedClockOutputStatus output_status = {
    false, false, false, false, OTIS_GPIO_OSC_OBSERVATION,
    OTIS_GPIO_FORWARDED_CLOCK_OUTPUT, kIntegerDivider, kFractionalDivider,
    "disabled_profile"};

bool output_readback_matches_contract(void) {
  const uint32_t ctrl = clocks_hw->clk[clk_gpout0].ctrl;
  const uint32_t div = clocks_hw->clk[clk_gpout0].div;
  const uint32_t auxsrc = ctrl & kGpout0CtrlAuxsrcMask;
  const bool enabled = (ctrl & CLOCKS_CLK_GPOUT0_CTRL_ENABLE_BITS) != 0u;
  const uint32_t integer = div >> 16u;
  const uint32_t fractional = div & 0xffffu;
  return enabled && auxsrc == kGpout0CtrlAuxsrcGpin0 &&
         integer == kIntegerDivider && fractional == kFractionalDivider &&
         gpio_get_function(OTIS_GPIO_OSC_OBSERVATION) == GPIO_FUNC_GPCK &&
         gpio_get_function(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT) == GPIO_FUNC_GPCK;
}

}  // namespace

bool otis_forwarded_clock_output_begin(void) {
#if !OTIS_ENABLE_FORWARDED_D9_OUTPUT
  return false;
#else
  output_status.selected = true;
  // Keep D9 input/high impedance until the fixed source and divider have been
  // configured. clock_gpio_init_int_frac16 writes the clock controls before
  // selecting GPIO_FUNC_GPCK for the destination pin.
  gpio_init(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT);
  gpio_set_dir(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT, false);
  gpio_disable_pulls(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT);

  // PIO sees the pad independently of its GPIO function. This is deliberately
  // the sole post-PIO GPIO20 mux write in an output-enabled profile.
  gpio_set_function(OTIS_GPIO_OSC_OBSERVATION, GPIO_FUNC_GPCK);
  clock_gpio_init_int_frac16(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT,
                             kGpout0CtrlAuxsrcGpin0, kIntegerDivider,
                             kFractionalDivider);
  output_status.configured = true;
  output_status.readback_valid = output_readback_matches_contract();
  output_status.valid = output_status.readback_valid;
  output_status.reason = output_status.valid ? "configured_10mhz_forwarded_unqualified"
                                             : "invalid_or_transitioning_readback_mismatch";
  return output_status.valid;
#endif
}

void otis_forwarded_clock_output_get_status(OtisForwardedClockOutputStatus *out) {
  if (out != nullptr) {
    *out = output_status;
  }
}
