# RP2040 Boot Diagnostics

The OTIS Arduino Nano RP2040 Connect firmware has an optional early boot
diagnostics record for RP2040 clock and reset forensics. It is disabled by
default.

Enable it at compile time with:

```text
OTIS_ENABLE_RP2040_BOOT_DIAG=1
```

When disabled, no boot diagnostic code is called and the `BOOTDIAG` record is
not emitted. When enabled, firmware emits exactly one `BOOTDIAG` record during
startup after USB/serial logging is initialized and before normal OTIS telemetry
headers, status, capture, reference, or count records.

The output prefix and schema version are:

```text
BOOTDIAG,v=1
```

All register values are emitted as fixed-width 32-bit hexadecimal fields.

## Fields

| Field | Source |
|---|---|
| `wd_reason` | `watchdog_hw->reason` |
| `wd_s0` through `wd_s7` | `watchdog_hw->scratch[0]` through `[7]` |
| `resets_reset` | `resets_hw->reset` |
| `resets_done` | `resets_hw->reset_done` |
| `clk_ref_ctrl` | `clocks_hw->clk[clk_ref].ctrl` |
| `clk_ref_div` | `clocks_hw->clk[clk_ref].div` |
| `clk_sys_ctrl` | `clocks_hw->clk[clk_sys].ctrl` |
| `clk_sys_div` | `clocks_hw->clk[clk_sys].div` |
| `clk_peri_ctrl` | `clocks_hw->clk[clk_peri].ctrl` |
| `clk_peri_div` | `clocks_hw->clk[clk_peri].div` |
| `xosc_status` | `xosc_hw->status` |
| `rosc_status` | `rosc_hw->status` |
| `rosc_ctrl` | `rosc_hw->ctrl` |
| `pll_sys_cs` | `pll_sys_hw->cs` |
| `pll_usb_cs` | `pll_usb_hw->cs` |
| `vreg` | `vreg_and_chip_reset_hw->vreg` |
| `bod` | `vreg_and_chip_reset_hw->bod` |
| `chip_id` | `sysinfo_hw->chip_id` |
| `platform` | `sysinfo_hw->platform`, when available in the installed SDK |
| `gitref_rp2040` | `sysinfo_hw->gitref_rp2040`, when available in the installed SDK |

## Breadcrumbs

When diagnostics are enabled, firmware also exposes explicit breadcrumb helpers:

```c
void otis_boot_diag_set_breadcrumb(uint32_t code, uint32_t arg0, uint32_t arg1);
void otis_boot_diag_clear_breadcrumb(void);
```

The Arduino-Pico sketch exposes the same functions using Arduino naming:

```cpp
void otisBootDiagSetBreadcrumb(uint32_t code, uint32_t arg0, uint32_t arg1);
void otisBootDiagClearBreadcrumb();
```

The scratch register convention is:

| Scratch register | Purpose |
|---|---|
| `scratch[0]` | magic: `0x4f544953` (`OTIS`) |
| `scratch[1]` | breadcrumb schema version |
| `scratch[2]` | code/state |
| `scratch[3]` | `arg0` |
| `scratch[4]` | `arg1` |
| `scratch[5]` | reserved for a boot counter or sequence if one is added later |
| `scratch[6]` | reserved |
| `scratch[7]` | simple xor check value |

The diagnostic dump never overwrites scratch registers. Code that wants
breadcrumbs must update or clear them explicitly after the dump if appropriate.

## Interpretation Limits

`watchdog_hw->reason == 0` generally indicates a hardware or power-style reset
rather than a watchdog-triggered reboot. RP2040 reset forensics are much more
limited than AVR `RSTFR`-style reset causes.

Watchdog scratch registers are useful for breadcrumb-style crash and reboot
diagnostics across soft or watchdog resets. They should not be assumed valid
after power loss.

The boot diagnostics record is a raw register snapshot. It does not decode clock
sources or reset causes, and it must not be treated as a complete forensic log.
