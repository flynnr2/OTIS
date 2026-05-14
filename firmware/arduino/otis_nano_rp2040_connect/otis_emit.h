#ifndef OTIS_EMIT_H
#define OTIS_EMIT_H

#include <stdint.h>

void otis_emit_csv_headers(void);
void otis_emit_raw_event(const char *record_type,
                         uint32_t event_seq,
                         uint32_t channel_id,
                         const char *edge,
                         uint64_t timestamp_ticks,
                         const char *capture_domain,
                         uint32_t flags);
void otis_emit_count_observation(uint32_t count_seq,
                                 uint32_t channel_id,
                                 uint64_t gate_open_ticks,
                                 uint64_t gate_close_ticks,
                                 const char *gate_domain,
                                 uint64_t counted_edges,
                                 const char *source_edge,
                                 const char *source_domain,
                                 uint32_t flags);
void otis_emit_health(uint32_t status_seq,
                      uint64_t timestamp_ticks,
                      const char *status_domain,
                      const char *component,
                      const char *status_key,
                      const char *status_value,
                      const char *severity,
                      uint32_t flags);

#endif
