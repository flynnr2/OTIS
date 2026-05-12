#include "otis_protocol.h"
#include "otis_records.h"

#include <inttypes.h>
#include <stdio.h>

void otis_emit_csv_headers(void) {
    puts("record_type,schema_version,event_seq,channel_id,edge,timestamp_ticks,capture_domain,flags");
    puts("record_type,schema_version,count_seq,channel_id,gate_open_ticks,gate_close_ticks,gate_domain,counted_edges,source_edge,source_domain,flags");
    puts("record_type,schema_version,status_seq,timestamp_ticks,status_domain,component,status_key,status_value,severity,flags");
}

void otis_emit_raw_event(const char *record_type,
                         uint32_t event_seq,
                         uint32_t channel_id,
                         const char *edge,
                         uint64_t timestamp_ticks,
                         const char *capture_domain,
                         uint32_t flags) {
    printf("%s,%u,%" PRIu32 ",%" PRIu32 ",%s,%" PRIu64 ",%s,%" PRIu32 "\n",
           record_type,
           OTIS_SCHEMA_VERSION_V1,
           event_seq,
           channel_id,
           edge,
           timestamp_ticks,
           capture_domain,
           flags);
}

void otis_emit_count_observation(uint32_t count_seq,
                                 uint32_t channel_id,
                                 uint64_t gate_open_ticks,
                                 uint64_t gate_close_ticks,
                                 const char *gate_domain,
                                 uint64_t counted_edges,
                                 const char *source_edge,
                                 const char *source_domain,
                                 uint32_t flags) {
    printf("%s,%u,%" PRIu32 ",%" PRIu32 ",%" PRIu64 ",%" PRIu64 ",%s,%" PRIu64 ",%s,%s,%" PRIu32 "\n",
           OTIS_RECORD_CNT,
           OTIS_SCHEMA_VERSION_V1,
           count_seq,
           channel_id,
           gate_open_ticks,
           gate_close_ticks,
           gate_domain,
           counted_edges,
           source_edge,
           source_domain,
           flags);
}

void otis_emit_health(uint32_t status_seq,
                      uint64_t timestamp_ticks,
                      const char *status_domain,
                      const char *component,
                      const char *status_key,
                      const char *status_value,
                      const char *severity,
                      uint32_t flags) {
    printf("%s,%u,%" PRIu32 ",%" PRIu64 ",%s,%s,%s,%s,%s,%" PRIu32 "\n",
           OTIS_RECORD_STS,
           OTIS_SCHEMA_VERSION_V1,
           status_seq,
           timestamp_ticks,
           status_domain,
           component,
           status_key,
           status_value,
           severity,
           flags);
}
