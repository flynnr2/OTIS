#ifndef OTIS_BOOT_DIAG_H
#define OTIS_BOOT_DIAG_H

#include <stdint.h>

#ifndef OTIS_ENABLE_RP2040_BOOT_DIAG
#define OTIS_ENABLE_RP2040_BOOT_DIAG 1
#endif

#if OTIS_ENABLE_RP2040_BOOT_DIAG

#include <Arduino.h>

#define OTIS_BOOT_DIAG_BREADCRUMB_MAGIC 0x4f544953u
#define OTIS_BOOT_DIAG_BREADCRUMB_SCHEMA 1u

void emitRp2040BootDiag(Stream &out);
void otisBootDiagSetBreadcrumb(uint32_t code, uint32_t arg0, uint32_t arg1);
void otisBootDiagClearBreadcrumb(void);

#endif

#endif
