#include "otis_boot_diag.h"

#if OTIS_ENABLE_RP2040_BOOT_DIAG

#include <inttypes.h>
#include <stdio.h>

#include "hardware/structs/clocks.h"
#include "hardware/structs/pll.h"
#include "hardware/structs/resets.h"
#include "hardware/structs/rosc.h"
#include "hardware/structs/sysinfo.h"
#include "hardware/structs/vreg_and_chip_reset.h"
#include "hardware/structs/watchdog.h"
#include "hardware/structs/xosc.h"

static uint32_t otis_boot_diag_breadcrumb_check(uint32_t code, uint32_t arg0,
                                                uint32_t arg1) {
    return OTIS_BOOT_DIAG_BREADCRUMB_MAGIC ^
           OTIS_BOOT_DIAG_BREADCRUMB_SCHEMA ^ code ^ arg0 ^ arg1;
}

void otis_emit_rp2040_boot_diag(void) {
    printf("BOOTDIAG,v=1"
           ",wd_reason=0x%08" PRIx32
           ",wd_s0=0x%08" PRIx32
           ",wd_s1=0x%08" PRIx32
           ",wd_s2=0x%08" PRIx32
           ",wd_s3=0x%08" PRIx32
           ",wd_s4=0x%08" PRIx32
           ",wd_s5=0x%08" PRIx32
           ",wd_s6=0x%08" PRIx32
           ",wd_s7=0x%08" PRIx32
           ",resets_reset=0x%08" PRIx32
           ",resets_done=0x%08" PRIx32
           ",clk_ref_ctrl=0x%08" PRIx32
           ",clk_ref_div=0x%08" PRIx32
           ",clk_sys_ctrl=0x%08" PRIx32
           ",clk_sys_div=0x%08" PRIx32
           ",clk_peri_ctrl=0x%08" PRIx32
           ",clk_peri_div=0x%08" PRIx32
           ",xosc_status=0x%08" PRIx32
           ",rosc_status=0x%08" PRIx32
           ",rosc_ctrl=0x%08" PRIx32
           ",pll_sys_cs=0x%08" PRIx32
           ",pll_usb_cs=0x%08" PRIx32
           ",vreg=0x%08" PRIx32
           ",bod=0x%08" PRIx32
           ",chip_id=0x%08" PRIx32
#ifdef SYSINFO_PLATFORM_OFFSET
           ",platform=0x%08" PRIx32
#endif
#ifdef SYSINFO_GITREF_RP2040_OFFSET
           ",gitref_rp2040=0x%08" PRIx32
#endif
           "\n",
           (uint32_t)watchdog_hw->reason,
           (uint32_t)watchdog_hw->scratch[0],
           (uint32_t)watchdog_hw->scratch[1],
           (uint32_t)watchdog_hw->scratch[2],
           (uint32_t)watchdog_hw->scratch[3],
           (uint32_t)watchdog_hw->scratch[4],
           (uint32_t)watchdog_hw->scratch[5],
           (uint32_t)watchdog_hw->scratch[6],
           (uint32_t)watchdog_hw->scratch[7],
           (uint32_t)resets_hw->reset,
           (uint32_t)resets_hw->reset_done,
           (uint32_t)clocks_hw->clk[clk_ref].ctrl,
           (uint32_t)clocks_hw->clk[clk_ref].div,
           (uint32_t)clocks_hw->clk[clk_sys].ctrl,
           (uint32_t)clocks_hw->clk[clk_sys].div,
           (uint32_t)clocks_hw->clk[clk_peri].ctrl,
           (uint32_t)clocks_hw->clk[clk_peri].div,
           (uint32_t)xosc_hw->status,
           (uint32_t)rosc_hw->status,
           (uint32_t)rosc_hw->ctrl,
           (uint32_t)pll_sys_hw->cs,
           (uint32_t)pll_usb_hw->cs,
           (uint32_t)vreg_and_chip_reset_hw->vreg,
           (uint32_t)vreg_and_chip_reset_hw->bod,
           (uint32_t)sysinfo_hw->chip_id
#ifdef SYSINFO_PLATFORM_OFFSET
           ,
           (uint32_t)sysinfo_hw->platform
#endif
#ifdef SYSINFO_GITREF_RP2040_OFFSET
           ,
           (uint32_t)sysinfo_hw->gitref_rp2040
#endif
    );
}

void otis_boot_diag_set_breadcrumb(uint32_t code, uint32_t arg0, uint32_t arg1) {
    watchdog_hw->scratch[0] = OTIS_BOOT_DIAG_BREADCRUMB_MAGIC;
    watchdog_hw->scratch[1] = OTIS_BOOT_DIAG_BREADCRUMB_SCHEMA;
    watchdog_hw->scratch[2] = code;
    watchdog_hw->scratch[3] = arg0;
    watchdog_hw->scratch[4] = arg1;
    watchdog_hw->scratch[6] = 0u;
    watchdog_hw->scratch[7] = otis_boot_diag_breadcrumb_check(code, arg0, arg1);
}

void otis_boot_diag_clear_breadcrumb(void) {
    for (uint32_t i = 0u; i < 8u; ++i) {
        watchdog_hw->scratch[i] = 0u;
    }
}

#endif
