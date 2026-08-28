#include "otis_forwarded_clock_output.h"

#include <hardware/clocks.h>
#include <hardware/gpio.h>
#include <hardware/regs/io_bank0.h>
#include <hardware/structs/clocks.h>
#include <hardware/structs/io_bank0.h>

#include "otis_board.h"
#include "otis_config.h"
#include "otis_timebase.h"

namespace {

constexpr uint32_t kIntegerDivider = 1u;
constexpr uint32_t kFractionalDivider = 0u;
constexpr uint32_t kNominalFrequencyHz = 10000000u;
constexpr uint32_t kDriveStrengthMa = 2u;
constexpr gpio_drive_strength kDriveStrength = GPIO_DRIVE_STRENGTH_2MA;
constexpr gpio_slew_rate kSlewRate = GPIO_SLEW_RATE_SLOW;
constexpr char kContractId[] = "OTIS_D9_D6_READINESS_CONTRACT_V1";
constexpr char kContractSha256[] =
    "a6a08d14a03a87b5e0308880c64799baf2e7afecc23cad22d1532f297960de4d";
constexpr uint32_t kGpout0CtrlAuxsrcMask = CLOCKS_CLK_GPOUT0_CTRL_AUXSRC_BITS;
constexpr uint32_t kGpout0CtrlAuxsrcGpin0 =
    CLOCKS_CLK_GPOUT0_CTRL_AUXSRC_VALUE_CLKSRC_GPIN0;

OtisForwardedClockOutputStatus output_status = {
    false, false, false, false, OTIS_GPIO_OSC_OBSERVATION,
    OTIS_GPIO_FORWARDED_CLOCK_OUTPUT, kIntegerDivider, kFractionalDivider,
    0u, 0u, 0u, 0u, 0u, kNominalFrequencyHz, kDriveStrengthMa, 0u, false,
    false, kContractId, kContractSha256, "disabled"};

bool output_readback_matches_contract(void) {
  const uint32_t ctrl = clocks_hw->clk[clk_gpout0].ctrl;
  const uint32_t div = clocks_hw->clk[clk_gpout0].div;
  const uint32_t auxsrc =
      (ctrl & kGpout0CtrlAuxsrcMask) >> CLOCKS_CLK_GPOUT0_CTRL_AUXSRC_LSB;
  const bool enabled = (ctrl & CLOCKS_CLK_GPOUT0_CTRL_ENABLE_BITS) != 0u;
  // RP2040 and RP2350 place the GPOUT integer/fractional fields at different
  // bit positions.  Read the exact target register contract instead of
  // assuming the RP2350 16-bit fractional layout.
  const uint32_t integer =
      (div & CLOCKS_CLK_GPOUT0_DIV_INT_BITS) >>
      CLOCKS_CLK_GPOUT0_DIV_INT_LSB;
  const uint32_t fractional =
      (div & CLOCKS_CLK_GPOUT0_DIV_FRAC_BITS) >>
      CLOCKS_CLK_GPOUT0_DIV_FRAC_LSB;
  const uint32_t source_function = gpio_get_function(OTIS_GPIO_OSC_OBSERVATION);
  const uint32_t destination_function =
      gpio_get_function(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT);
  const uint32_t output_override =
      (io_bank0_hw->io[OTIS_GPIO_FORWARDED_CLOCK_OUTPUT].ctrl &
       IO_BANK0_GPIO0_CTRL_OUTOVER_BITS) >>
      IO_BANK0_GPIO0_CTRL_OUTOVER_LSB;
  output_status.applied_auxsrc = auxsrc;
  output_status.applied_integer_divider = integer;
  output_status.applied_fractional_divider = fractional;
  output_status.source_gpio_function = source_function;
  output_status.destination_gpio_function = destination_function;
  output_status.inversion =
      output_override == IO_BANK0_GPIO0_CTRL_OUTOVER_VALUE_INVERT;
  output_status.slew_rate_fast =
      gpio_get_slew_rate(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT) ==
      GPIO_SLEW_RATE_FAST;
  return enabled && auxsrc == kGpout0CtrlAuxsrcGpin0 &&
         integer == kIntegerDivider && fractional == kFractionalDivider &&
         source_function == GPIO_FUNC_GPCK &&
         destination_function == GPIO_FUNC_GPCK &&
         output_override == IO_BANK0_GPIO0_CTRL_OUTOVER_VALUE_NORMAL &&
         gpio_get_drive_strength(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT) ==
             kDriveStrength &&
         gpio_get_slew_rate(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT) == kSlewRate;
}

void disable_output_after_contradiction(const char *reason) {
  clock_stop(clk_gpout0);
  gpio_init(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT);
  gpio_set_dir(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT, false);
  gpio_disable_pulls(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT);
  output_status.readback_valid = false;
  output_status.valid = false;
  output_status.reason = reason;
}

}  // namespace

bool otis_forwarded_clock_output_begin(void) {
#if !OTIS_ENABLE_FORWARDED_D9_OUTPUT
  clock_stop(clk_gpout0);
  gpio_init(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT);
  gpio_set_dir(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT, false);
  gpio_disable_pulls(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT);
  output_status.selected = false;
  output_status.configured = false;
  output_status.readback_valid = false;
  output_status.valid = false;
  output_status.destination_gpio_function =
      gpio_get_function(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT);
  output_status.reason = "disabled";
  return true;
#else
  output_status.selected = true;
  output_status.reason = "invalid_or_transitioning";
  // Keep D9 input/high impedance until the fixed source and divider have been
  // configured. clock_gpio_init_int_frac16 writes the clock controls before
  // selecting GPIO_FUNC_GPCK for the destination pin.
  gpio_init(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT);
  gpio_set_dir(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT, false);
  gpio_disable_pulls(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT);
  gpio_set_drive_strength(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT, kDriveStrength);
  gpio_set_slew_rate(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT, kSlewRate);
  gpio_set_outover(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT, GPIO_OVERRIDE_NORMAL);

  // PIO sees the pad independently of its GPIO function. This is deliberately
  // the sole post-PIO GPIO20 mux write in an output-enabled profile.
  gpio_set_function(OTIS_GPIO_OSC_OBSERVATION, GPIO_FUNC_GPCK);
  clock_gpio_init_int_frac16(OTIS_GPIO_FORWARDED_CLOCK_OUTPUT,
                             kGpout0CtrlAuxsrcGpin0, kIntegerDivider,
                             kFractionalDivider);
  output_status.configured = true;
  output_status.readback_valid = output_readback_matches_contract();
  output_status.valid = output_status.readback_valid;
  if (!output_status.valid) {
    disable_output_after_contradiction(
        "invalid_or_transitioning_readback_mismatch");
    return false;
  }
  output_status.first_valid_ticks = otis_capture_ticks_now();
  output_status.reason = "configured_10mhz_forwarded_unqualified";
  return output_status.valid;
#endif
}

void otis_forwarded_clock_output_get_status(OtisForwardedClockOutputStatus *out) {
  if (output_status.selected && output_status.configured &&
      output_status.valid && !output_readback_matches_contract()) {
    disable_output_after_contradiction(
        "invalid_or_transitioning_runtime_readback_contradiction");
  }
  if (out != nullptr) {
    *out = output_status;
  }
}
