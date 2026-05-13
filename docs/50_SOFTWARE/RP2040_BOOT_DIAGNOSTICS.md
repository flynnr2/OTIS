# RP2040 Boot Diagnostics

The OTIS Arduino Nano RP2040 Connect firmware has an optional early boot
diagnostics record for RP2040 clock and reset forensics.

Control it at compile time with:

```text
OTIS_ENABLE_RP2040_BOOT_DIAG=1
```

When disabled, the raw `BOOTDIAG` register snapshot is not emitted. Compact
`BOOT` breadcrumbs are separate from `BOOTDIAG` and remain part of normal boot
so reset history survives soft and watchdog resets where the RP2040 scratch
registers are retained.

The output prefix and schema version are:

```text
BOOTDIAG,v=1
```

All register values are emitted as fixed-width 32-bit hexadecimal fields.

The compact boot telemetry prefixes are:

```text
BOOT,v=1
BOOT_WARN,v=1
BOOT_FATAL,v=1
```

`BOOT_FATAL` is reserved for a later safe-mode pass. This pass defines fatal
codes and persistent storage but does not add safe-mode behavior.

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

OTIS uses watchdog scratch registers 0 through 3 for persistent boot
breadcrumbs. Scratch registers 4 through 7 are left untouched by OTIS because
the Pico SDK uses them for watchdog reboot vectors and watchdog-enable reboot
classification.

The scratch register convention is:

| Scratch register | Purpose |
|---|---|
| `scratch[0]` | magic: `0x4f544253` (`OTBS`) |
| `scratch[1]` | boot counter |
| `scratch[2]` | last completed `BootPhase` numeric code |
| `scratch[3]` | packed status: fatal code in bits 0-7, reset reason in bits 8-15, watchdog flags in bits 16-17 |

At reset entry, firmware snapshots the previous scratch contents, increments
the boot counter, records the current RP2040 watchdog reason bits, clears the
current fatal code to `None`, and writes `ResetEntry` as the current phase.
Each successfully completed boot phase then updates `scratch[2]`.

The raw diagnostic dump reads scratch registers after the current boot has
started updating them. The compact `BOOT` record is the preferred decoded view
for normal review.

## Interpretation Limits

`watchdog_hw->reason == 0` generally indicates a hardware or power-style reset
rather than a watchdog-triggered reboot. RP2040 reset forensics are much more
limited than AVR `RSTFR`-style reset causes.

Watchdog scratch registers are useful for breadcrumb-style crash and reboot
diagnostics across soft or watchdog resets. They should not be assumed valid
after power loss.

The boot diagnostics record is a raw register snapshot. It does not decode clock
sources or reset causes, and it must not be treated as a complete forensic log.
