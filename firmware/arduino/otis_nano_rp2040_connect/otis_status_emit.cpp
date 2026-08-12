#include "otis_status_emit.h"

#include <Arduino.h>
#include <stdio.h>

#include "otis_config.h"
#include "otis_emit.h"
#include "otis_gnss_receiver.h"
#include "otis_protocol.h"
#include "otis_timebase.h"

void otis_status_emit_init(OtisStatusEmitContext *context,
                           uint32_t *status_seq) {
  context->status_seq = status_seq;
  context->sink_context = nullptr;
  context->sink = nullptr;
}

void otis_status_emit_init_with_sink(OtisStatusEmitContext *context,
                                     void *sink_context,
                                     OtisStatusEmitSink sink) {
  if (context == nullptr) return;
  context->status_seq = nullptr;
  context->sink_context = sink_context;
  context->sink = sink;
}

void otis_status_emit(OtisStatusEmitContext *context,
                      const char *component,
                      const char *key,
                      const char *value,
                      const char *severity,
                      uint32_t flags) {
  if (context == nullptr) return;
  if (context->sink != nullptr) {
    context->sink(context->sink_context, component, key, value, severity,
                  flags);
    return;
  }
  if (context->status_seq == nullptr) return;
  otis_emit_health((*context->status_seq)++, otis_capture_ticks_now(),
                   OTIS_DOMAIN_RP2040_TIMER0, component, key, value, severity,
                   flags);
#if OTIS_ENABLE_GNSS_RECEIVER
  // Synchronous periodic and CONFIG? status bursts must not overflow UART0's
  // receive FIFO. Invoke the existing fixed-byte service once per complete STS
  // frame; capture remains interrupt/PIO driven and main-loop capture-first.
  otis_gnss_receiver_service(millis());
#endif
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
