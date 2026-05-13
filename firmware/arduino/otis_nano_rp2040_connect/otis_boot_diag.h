#ifndef OTIS_BOOT_DIAG_H
#define OTIS_BOOT_DIAG_H

#include <stdint.h>

#include "OtisBootConfig.h"

#ifndef OTIS_ENABLE_RP2040_BOOT_DIAG
#define OTIS_ENABLE_RP2040_BOOT_DIAG 1
#endif

#include <Arduino.h>

#define OTIS_BOOT_BREADCRUMB_MAGIC 0x4f544253u

struct OtisBootBreadcrumbSnapshot {
  bool previous_valid;
  uint32_t boot_count;
  BootPhase previous_last_phase;
  BootFatal previous_fatal;
  uint32_t previous_reset_reason;
  bool previous_watchdog_reboot;
  bool previous_watchdog_enable_reboot;
  uint32_t current_reset_reason;
  bool current_watchdog_reboot;
  bool current_watchdog_enable_reboot;
};

void otisBootBreadcrumbBegin(BootPhase phase);
void otisBootBreadcrumbCompletePhase(BootPhase phase);
void otisBootBreadcrumbSetFatal(BootFatal fatal);
const OtisBootBreadcrumbSnapshot &otisBootBreadcrumbSnapshot(void);
const char *otisBootPhaseName(BootPhase phase);
const char *otisBootFatalName(BootFatal fatal);
uint8_t otisBootPhaseCode(BootPhase phase);
uint8_t otisBootFatalCode(BootFatal fatal);
void emitOtisBootSummary(Stream &out, BootPhase current_phase);
void emitOtisBootWarnSerialAbsent(Stream &out, uint32_t wait_ms);
void emitOtisBootFatal(Stream &out, BootFatal fatal, BootPhase phase);

#if OTIS_ENABLE_RP2040_BOOT_DIAG
void emitRp2040BootDiag(Stream &out);
#endif

#endif
