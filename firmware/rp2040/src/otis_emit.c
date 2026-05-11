#include "otis_records.h"
#include "otis_protocol.h"

#include <stdio.h>

static void print_u64(unsigned long long value) {
    printf("%llu", value);
}

void otis_emit_csv_headers(void) {
    puts("# raw_events: record_type,schema_version,event_seq,channel_id,edge,timestamp_ticks,capture_domain,flags");
    puts("# count_observations: record_type,schema_version,count_seq,channel_id,gate_open_ticks,gate_close_ticks,gate_domain,counted_edges,source_edge,source_domain,flags");
    puts("# health: record_type,schema_version,status_seq,timestamp_ticks,status_domain,component,status_key,status_value,severity,flags");
}

void otis_emit_raw_event(const char *record_type,
                         unsigned int event_seq,
                         unsigned int channel_id,
                         const char *edge,
                         unsigned long long timestamp_ticks,
                         const char *capture_domain,
                         unsigned int flags) {
    printf("%s,%u,%u,%u,%s,", record_type, OTIS_SCHEMA_VERSION_V1, event_seq, channel_id, edge);
    print_u64(timestamp_ticks);
    printf(",%s,%u\n", capture_domain, flags);
}

void otis_emit_count_observation(unsigned int count_seq,
                                 unsigned int channel_id,
                                 unsigned long long gate_open_ticks,
                                 unsigned long long gate_close_ticks,
                                 const char *gate_domain,
                                 unsigned long long counted_edges,
                                 const char *source_edge,
                                 const char *source_domain,
                                 unsigned int flags) {
    printf("%s,%u,%u,%u,", OTIS_RECORD_CNT, OTIS_SCHEMA_VERSION_V1, count_seq, channel_id);
    print_u64(gate_open_ticks);
    putchar(',');
    print_u64(gate_close_ticks);
    printf(",%s,", gate_domain);
    print_u64(counted_edges);
    printf(",%s,%s,%u\n", source_edge, source_domain, flags);
}

void otis_emit_health(unsigned int status_seq,
                      unsigned long long timestamp_ticks,
                      const char *status_domain,
                      const char *component,
                      const char *status_key,
                      const char *status_value,
                      const char *severity,
                      unsigned int flags) {
    printf("%s,%u,%u,", OTIS_RECORD_STS, OTIS_SCHEMA_VERSION_V1, status_seq);
    print_u64(timestamp_ticks);
    printf(",%s,%s,%s,%s,%s,%u\n",
           status_domain,
           component,
           status_key,
           status_value,
           severity,
           flags);
}
