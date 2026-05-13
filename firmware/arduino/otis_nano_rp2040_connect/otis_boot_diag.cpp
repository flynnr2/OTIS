#include "otis_boot_diag.h"

#include "hardware/watchdog.h"
#include "hardware/structs/clocks.h"
#include "hardware/structs/pll.h"
#include "hardware/structs/resets.h"
#include "hardware/structs/rosc.h"
#include "hardware/structs/sysinfo.h"
#include "hardware/structs/vreg_and_chip_reset.h"
#include "hardware/structs/watchdog.h"
#include "hardware/structs/xosc.h"

namespace {

constexpr uint8_t kScratchMagic = 0u;
constexpr uint8_t kScratchBootCount = 1u;
constexpr uint8_t kScratchLastPhase = 2u;
constexpr uint8_t kScratchPackedStatus = 3u;

constexpr uint32_t kFatalMask = 0x000000ffu;
constexpr uint32_t kResetReasonShift = 8u;
constexpr uint32_t kResetReasonMask = 0x0000ff00u;
constexpr uint32_t kWatchdogRebootBit = 1u << 16;
constexpr uint32_t kWatchdogEnableRebootBit = 1u << 17;
constexpr uint32_t kFailureCountShift = 18u;
constexpr uint32_t kFailureCountMask = 0x03fc0000u;
constexpr uint32_t kSafeModeRequestedBit = 1u << 26;

OtisBootBreadcrumbSnapshot boot_snapshot = {};

uint32_t pack_boot_status(BootFatal fatal, uint32_t reset_reason,
                          bool watchdog_reboot,
                          bool watchdog_enable_reboot, uint8_t failure_count,
                          bool safe_mode_requested) {
  uint32_t packed = otisBootFatalCode(fatal) & kFatalMask;
  packed |= (reset_reason << kResetReasonShift) & kResetReasonMask;
  packed |= ((uint32_t)failure_count << kFailureCountShift) & kFailureCountMask;
  if (watchdog_reboot) {
    packed |= kWatchdogRebootBit;
  }
  if (watchdog_enable_reboot) {
    packed |= kWatchdogEnableRebootBit;
  }
  if (safe_mode_requested) {
    packed |= kSafeModeRequestedBit;
  }
  return packed;
}

uint8_t unpack_failure_count(uint32_t packed) {
  return (uint8_t)((packed & kFailureCountMask) >> kFailureCountShift);
}

BootPhase unpack_phase(uint32_t value) {
  switch ((uint8_t)value) {
    case 0u:
      return BootPhase::ResetEntry;
    case 1u:
      return BootPhase::EarlyInit;
    case 2u:
      return BootPhase::ClocksInit;
    case 3u:
      return BootPhase::GpioInit;
    case 4u:
      return BootPhase::CaptureInit;
    case 5u:
      return BootPhase::TimerInit;
    case 6u:
      return BootPhase::PpsInputInit;
    case 7u:
      return BootPhase::RingBuffersInit;
    case 8u:
      return BootPhase::SerialInit;
    case 9u:
      return BootPhase::ProtocolBanner;
    case 10u:
      return BootPhase::RunMode;
    case 11u:
      return BootPhase::Fatal;
    default:
      return BootPhase::Fatal;
  }
}

BootFatal unpack_fatal(uint32_t packed) {
  switch ((uint8_t)(packed & kFatalMask)) {
    case 0u:
      return BootFatal::None;
    case 1u:
      return BootFatal::UnsupportedBoard;
    case 2u:
      return BootFatal::InvalidBootConfig;
    case 3u:
      return BootFatal::SerialUnavailable;
    case 4u:
      return BootFatal::CaptureInitFailed;
    case 5u:
      return BootFatal::TimerInitFailed;
    case 6u:
      return BootFatal::PpsInputInitFailed;
    case 7u:
      return BootFatal::ForcedBeforeClocks;
    case 8u:
      return BootFatal::ForcedBeforeCapture;
    case 9u:
      return BootFatal::ForcedBeforeRunMode;
    case 10u:
      return BootFatal::RepeatedBootFailure;
    default:
      return BootFatal::InvalidBootConfig;
  }
}

void print_hex32(Stream &out, uint32_t value) {
  static const char hex[] = "0123456789abcdef";

  out.print("0x");
  for (int8_t shift = 28; shift >= 0; shift -= 4) {
    out.print(hex[(value >> shift) & 0x0fu]);
  }
}

void print_boot_field_hex(Stream &out, const char *name, uint32_t value) {
  out.print(',');
  out.print(name);
  out.print('=');
  print_hex32(out, value);
}

}  // namespace

uint8_t otisBootPhaseCode(BootPhase phase) {
  return (uint8_t)phase;
}

uint8_t otisBootFatalCode(BootFatal fatal) {
  return (uint8_t)fatal;
}

const char *otisBootPhaseName(BootPhase phase) {
  switch (phase) {
    case BootPhase::ResetEntry:
      return "ResetEntry";
    case BootPhase::EarlyInit:
      return "EarlyInit";
    case BootPhase::ClocksInit:
      return "ClocksInit";
    case BootPhase::GpioInit:
      return "GpioInit";
    case BootPhase::CaptureInit:
      return "CaptureInit";
    case BootPhase::TimerInit:
      return "TimerInit";
    case BootPhase::PpsInputInit:
      return "PpsInputInit";
    case BootPhase::RingBuffersInit:
      return "RingBuffersInit";
    case BootPhase::SerialInit:
      return "SerialInit";
    case BootPhase::ProtocolBanner:
      return "ProtocolBanner";
    case BootPhase::RunMode:
      return "RunMode";
    case BootPhase::Fatal:
      return "Fatal";
    default:
      return "Unknown";
  }
}

const char *otisBootFatalName(BootFatal fatal) {
  switch (fatal) {
    case BootFatal::None:
      return "None";
    case BootFatal::UnsupportedBoard:
      return "UnsupportedBoard";
    case BootFatal::InvalidBootConfig:
      return "InvalidBootConfig";
    case BootFatal::SerialUnavailable:
      return "SerialUnavailable";
    case BootFatal::CaptureInitFailed:
      return "CaptureInitFailed";
    case BootFatal::TimerInitFailed:
      return "TimerInitFailed";
    case BootFatal::PpsInputInitFailed:
      return "PpsInputInitFailed";
    case BootFatal::ForcedBeforeClocks:
      return "ForcedBeforeClocks";
    case BootFatal::ForcedBeforeCapture:
      return "ForcedBeforeCapture";
    case BootFatal::ForcedBeforeRunMode:
      return "ForcedBeforeRunMode";
    case BootFatal::RepeatedBootFailure:
      return "RepeatedBootFailure";
    default:
      return "Unknown";
  }
}

void otisBootBreadcrumbBegin(BootPhase phase) {
  uint32_t previous_packed = watchdog_hw->scratch[kScratchPackedStatus];
  bool previous_valid =
      watchdog_hw->scratch[kScratchMagic] == OTIS_BOOT_BREADCRUMB_MAGIC;

  boot_snapshot.previous_valid = previous_valid;
  boot_snapshot.boot_count =
      previous_valid ? watchdog_hw->scratch[kScratchBootCount] + 1u : 1u;
  boot_snapshot.previous_last_phase =
      previous_valid ? unpack_phase(watchdog_hw->scratch[kScratchLastPhase])
                     : BootPhase::ResetEntry;
  boot_snapshot.previous_fatal =
      previous_valid ? unpack_fatal(previous_packed) : BootFatal::None;
  boot_snapshot.previous_reset_reason =
      previous_valid ? ((previous_packed & kResetReasonMask) >> kResetReasonShift)
                     : 0u;
  boot_snapshot.previous_watchdog_reboot =
      previous_valid && ((previous_packed & kWatchdogRebootBit) != 0u);
  boot_snapshot.previous_watchdog_enable_reboot =
      previous_valid && ((previous_packed & kWatchdogEnableRebootBit) != 0u);
  boot_snapshot.current_reset_reason = watchdog_hw->reason;
  boot_snapshot.current_watchdog_reboot = watchdog_caused_reboot();
  boot_snapshot.current_watchdog_enable_reboot = watchdog_enable_caused_reboot();
  boot_snapshot.previous_failure_count =
      previous_valid ? unpack_failure_count(previous_packed) : 0u;
  boot_snapshot.current_failure_count = boot_snapshot.previous_failure_count;
  boot_snapshot.safe_mode_requested =
      boot_snapshot.current_failure_count >= kOtisSafeModeFailureThreshold;

  watchdog_hw->scratch[kScratchMagic] = OTIS_BOOT_BREADCRUMB_MAGIC;
  watchdog_hw->scratch[kScratchBootCount] = boot_snapshot.boot_count;
  watchdog_hw->scratch[kScratchLastPhase] = otisBootPhaseCode(phase);
  watchdog_hw->scratch[kScratchPackedStatus] =
      pack_boot_status(BootFatal::None, boot_snapshot.current_reset_reason,
                       boot_snapshot.current_watchdog_reboot,
                       boot_snapshot.current_watchdog_enable_reboot,
                       boot_snapshot.current_failure_count,
                       boot_snapshot.safe_mode_requested);
}

void otisBootBreadcrumbCompletePhase(BootPhase phase) {
  watchdog_hw->scratch[kScratchLastPhase] = otisBootPhaseCode(phase);
}

void otisBootBreadcrumbSetFatal(BootFatal fatal) {
  if (boot_snapshot.current_failure_count < 255u) {
    boot_snapshot.current_failure_count++;
  }
  boot_snapshot.safe_mode_requested =
      boot_snapshot.current_failure_count >= kOtisSafeModeFailureThreshold;

  watchdog_hw->scratch[kScratchLastPhase] = otisBootPhaseCode(BootPhase::Fatal);
  watchdog_hw->scratch[kScratchPackedStatus] =
      pack_boot_status(fatal, boot_snapshot.current_reset_reason,
                       boot_snapshot.current_watchdog_reboot,
                       boot_snapshot.current_watchdog_enable_reboot,
                       boot_snapshot.current_failure_count,
                       boot_snapshot.safe_mode_requested);
}

void otisBootBreadcrumbSetSafeModeFatal(BootFatal fatal) {
  boot_snapshot.safe_mode_requested = true;
  watchdog_hw->scratch[kScratchLastPhase] = otisBootPhaseCode(BootPhase::Fatal);
  watchdog_hw->scratch[kScratchPackedStatus] =
      pack_boot_status(fatal, boot_snapshot.current_reset_reason,
                       boot_snapshot.current_watchdog_reboot,
                       boot_snapshot.current_watchdog_enable_reboot,
                       boot_snapshot.current_failure_count,
                       boot_snapshot.safe_mode_requested);
}

void otisBootBreadcrumbMarkRunMode(void) {
  boot_snapshot.current_failure_count = 0u;
  boot_snapshot.safe_mode_requested = false;
  watchdog_hw->scratch[kScratchLastPhase] = otisBootPhaseCode(BootPhase::RunMode);
  watchdog_hw->scratch[kScratchPackedStatus] =
      pack_boot_status(BootFatal::None, boot_snapshot.current_reset_reason,
                       boot_snapshot.current_watchdog_reboot,
                       boot_snapshot.current_watchdog_enable_reboot,
                       boot_snapshot.current_failure_count,
                       boot_snapshot.safe_mode_requested);
}

const OtisBootBreadcrumbSnapshot &otisBootBreadcrumbSnapshot(void) {
  return boot_snapshot;
}

bool otisBootSafeModeRequested(void) {
  return boot_snapshot.safe_mode_requested;
}

void emitOtisBootSummary(Stream &out, BootPhase current_phase) {
  out.print("BOOT,v=1");
  out.print(",boot_count=");
  out.print(boot_snapshot.boot_count);
  out.print(",phase=");
  out.print(otisBootPhaseName(current_phase));
  out.print(",prev_valid=");
  out.print(boot_snapshot.previous_valid ? 1 : 0);
  out.print(",prev_phase=");
  out.print(otisBootPhaseName(boot_snapshot.previous_last_phase));
  out.print(",prev_fatal=");
  out.print(otisBootFatalName(boot_snapshot.previous_fatal));
  print_boot_field_hex(out, "reset_reason", boot_snapshot.current_reset_reason);
  out.print(",watchdog=");
  out.print(boot_snapshot.current_watchdog_reboot ? 1 : 0);
  out.print(",watchdog_enable=");
  out.print(boot_snapshot.current_watchdog_enable_reboot ? 1 : 0);
  out.print(",failure_count=");
  out.print(boot_snapshot.current_failure_count);
  out.print(",safe_mode=");
  out.print(boot_snapshot.safe_mode_requested ? 1 : 0);
  print_boot_field_hex(out, "prev_reset_reason",
                       boot_snapshot.previous_reset_reason);
  out.println();
}

void emitOtisBootWarnSerialAbsent(Stream &out, uint32_t wait_ms) {
  out.print("BOOT_WARN,v=1,key=serial_absent,wait_ms=");
  out.println(wait_ms);
}

void emitOtisBootWarnSafeMode(Stream &out) {
  out.print("BOOT_WARN,v=1,key=safe_mode,reason=repeated_boot_failure");
  out.print(",failure_count=");
  out.print(boot_snapshot.current_failure_count);
  out.print(",threshold=");
  out.print(kOtisSafeModeFailureThreshold);
  out.print(",prev_phase=");
  out.print(otisBootPhaseName(boot_snapshot.previous_last_phase));
  out.print(",prev_fatal=");
  out.println(otisBootFatalName(boot_snapshot.previous_fatal));
}

void emitOtisBootFatal(Stream &out, BootFatal fatal, BootPhase phase) {
  out.print("BOOT_FATAL,v=1,fatal=");
  out.print(otisBootFatalName(fatal));
  out.print(",phase=");
  out.print(otisBootPhaseName(phase));
  out.print(",boot_count=");
  out.print(boot_snapshot.boot_count);
  out.print(",failure_count=");
  out.println(boot_snapshot.current_failure_count);
}

#if OTIS_ENABLE_RP2040_BOOT_DIAG

static void otisBootDiagPrintHex32(Stream &out, uint32_t value) {
  print_hex32(out, value);
}

static void otisBootDiagPrintField(Stream &out, const char *name,
                                   uint32_t value) {
  out.print(',');
  out.print(name);
  out.print('=');
  otisBootDiagPrintHex32(out, value);
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

#endif
