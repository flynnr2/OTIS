#include "otis_status_emit.h"

#include <stdio.h>

#include "otis_emit.h"
#include "otis_protocol.h"
#include "otis_timebase.h"

void otis_status_emit_init(OtisStatusEmitContext *context,
                           uint32_t *status_seq) {
  context->status_seq = status_seq;
}

void otis_status_emit(OtisStatusEmitContext *context,
                      const char *component,
                      const char *key,
                      const char *value,
                      const char *severity,
                      uint32_t flags) {
  otis_emit_health((*context->status_seq)++, otis_capture_ticks_now(),
                   OTIS_DOMAIN_RP2040_TIMER0, component, key, value, severity,
                   flags);
}

void otis_status_emit_u32(OtisStatusEmitContext *context,
                          const char *component,
                          const char *key,
                          uint32_t value,
                          const char *severity,
                          uint32_t flags) {
  char buffer[11];
  snprintf(buffer, sizeof(buffer), "%lu", (unsigned long)value);
  otis_status_emit(context, component, key, buffer, severity, flags);
}
