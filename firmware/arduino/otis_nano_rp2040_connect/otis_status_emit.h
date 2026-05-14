#ifndef OTIS_STATUS_EMIT_H
#define OTIS_STATUS_EMIT_H

#include <stdint.h>

struct OtisStatusEmitContext {
  uint32_t *status_seq;
};

void otis_status_emit_init(OtisStatusEmitContext *context,
                           uint32_t *status_seq);
void otis_status_emit(OtisStatusEmitContext *context,
                      const char *component,
                      const char *key,
                      const char *value,
                      const char *severity,
                      uint32_t flags);
void otis_status_emit_u32(OtisStatusEmitContext *context,
                          const char *component,
                          const char *key,
                          uint32_t value,
                          const char *severity,
                          uint32_t flags);

#endif
