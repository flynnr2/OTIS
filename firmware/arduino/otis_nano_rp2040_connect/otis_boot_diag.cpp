#include "otis_boot_diag.h"

#if OTIS_ENABLE_RP2040_BOOT_DIAG

#include "hardware/structs/clocks.h"
#include "hardware/structs/pll.h"
#include "hardware/structs/resets.h"
#include "hardware/structs/rosc.h"
#include "hardware/structs/sysinfo.h"
#include "hardware/structs/vreg_and_chip_reset.h"
#include "hardware/structs/watchdog.h"
#include "hardware/structs/xosc.h"

static void otisBootDiagPrintHex32(Stream &out, uint32_t value) {
  static const char hex[] = "0123456789abcdef";

  out.print("0x");
  for (int8_t shift = 28; shift >= 0; shift -= 4) {
    out.print(hex[(value >> shift) & 0x0fu]);
  }
}

static void otisBootDiagPrintField(Stream &out, const char *name,
                                   uint32_t value) {
  out.print(',');
  out.print(name);
  out.print('=');
  otisBootDiagPrintHex32(out, value);
}

static uint32_t otisBootDiagBreadcrumbCheck(uint32_t code, uint32_t arg0,
                                            uint32_t arg1) {
  return OTIS_BOOT_DIAG_BREADCRUMB_MAGIC ^ OTIS_BOOT_DIAG_BREADCRUMB_SCHEMA ^
         code ^ arg0 ^ arg1;
}

void emitRp2040BootDiag(Stream &out) {
  out.print("BOOTDIAG,v=1");
  otisBootDiagPrintField(out, "wd_reason", watchdog_hw->reason);
  otisBootDiagPrintField(out, "wd_s0", watchdog_hw->scratch[0]);
  otisBootDiagPrintField(out, "wd_s1", watchdog_hw->scratch[1]);
  otisBootDiagPrintField(out, "wd_s2", watchdog_hw->scratch[2]);
  otisBootDiagPrintField(out, "wd_s3", watchdog_hw->scratch[3]);
  otisBootDiagPrintField(out, "wd_s4", watchdog_hw->scratch[4]);
  otisBootDiagPrintField(out, "wd_s5", watchdog_hw->scratch[5]);
  otisBootDiagPrintField(out, "wd_s6", watchdog_hw->scratch[6]);
  otisBootDiagPrintField(out, "wd_s7", watchdog_hw->scratch[7]);
  otisBootDiagPrintField(out, "resets_reset", resets_hw->reset);
  otisBootDiagPrintField(out, "resets_done", resets_hw->reset_done);
  otisBootDiagPrintField(out, "clk_ref_ctrl", clocks_hw->clk[clk_ref].ctrl);
  otisBootDiagPrintField(out, "clk_ref_div", clocks_hw->clk[clk_ref].div);
  otisBootDiagPrintField(out, "clk_sys_ctrl", clocks_hw->clk[clk_sys].ctrl);
  otisBootDiagPrintField(out, "clk_sys_div", clocks_hw->clk[clk_sys].div);
  otisBootDiagPrintField(out, "clk_peri_ctrl", clocks_hw->clk[clk_peri].ctrl);
  otisBootDiagPrintField(out, "clk_peri_div", clocks_hw->clk[clk_peri].div);
  otisBootDiagPrintField(out, "xosc_status", xosc_hw->status);
  otisBootDiagPrintField(out, "rosc_status", rosc_hw->status);
  otisBootDiagPrintField(out, "rosc_ctrl", rosc_hw->ctrl);
  otisBootDiagPrintField(out, "pll_sys_cs", pll_sys_hw->cs);
  otisBootDiagPrintField(out, "pll_usb_cs", pll_usb_hw->cs);
  otisBootDiagPrintField(out, "vreg", vreg_and_chip_reset_hw->vreg);
  otisBootDiagPrintField(out, "bod", vreg_and_chip_reset_hw->bod);
  otisBootDiagPrintField(out, "chip_id", sysinfo_hw->chip_id);
#ifdef SYSINFO_PLATFORM_OFFSET
  otisBootDiagPrintField(out, "platform", sysinfo_hw->platform);
#endif
#ifdef SYSINFO_GITREF_RP2040_OFFSET
  otisBootDiagPrintField(out, "gitref_rp2040", sysinfo_hw->gitref_rp2040);
#endif
  out.println();
}

void otisBootDiagSetBreadcrumb(uint32_t code, uint32_t arg0, uint32_t arg1) {
  watchdog_hw->scratch[0] = OTIS_BOOT_DIAG_BREADCRUMB_MAGIC;
  watchdog_hw->scratch[1] = OTIS_BOOT_DIAG_BREADCRUMB_SCHEMA;
  watchdog_hw->scratch[2] = code;
  watchdog_hw->scratch[3] = arg0;
  watchdog_hw->scratch[4] = arg1;
  watchdog_hw->scratch[6] = 0u;
  watchdog_hw->scratch[7] = otisBootDiagBreadcrumbCheck(code, arg0, arg1);
}

void otisBootDiagClearBreadcrumb(void) {
  for (uint32_t i = 0u; i < 8u; ++i) {
    watchdog_hw->scratch[i] = 0u;
  }
}

#endif
