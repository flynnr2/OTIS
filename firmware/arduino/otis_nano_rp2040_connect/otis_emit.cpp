#include <Arduino.h>

#include "otis_protocol.h"
#include "otis_records.h"

void otis_emit_csv_headers(void) {
  Serial.println(
      "record_type,schema_version,event_seq,channel_id,edge,timestamp_ticks,capture_domain,flags");
  Serial.println(
      "record_type,schema_version,count_seq,channel_id,gate_open_ticks,gate_close_ticks,gate_domain,counted_edges,source_edge,source_domain,flags");
  Serial.println(
      "record_type,schema_version,status_seq,timestamp_ticks,status_domain,component,status_key,status_value,severity,flags");
}

void otis_emit_raw_event(const char *record_type, uint32_t event_seq,
                         uint32_t channel_id, const char *edge,
                         uint64_t timestamp_ticks, const char *capture_domain,
                         uint32_t flags) {
  Serial.print(record_type);
  Serial.print(',');
  Serial.print(OTIS_SCHEMA_VERSION_V1);
  Serial.print(',');
  Serial.print(event_seq);
  Serial.print(',');
  Serial.print(channel_id);
  Serial.print(',');
  Serial.print(edge);
  Serial.print(',');
  Serial.print((unsigned long)timestamp_ticks);
  Serial.print(',');
  Serial.print(capture_domain);
  Serial.print(',');
  Serial.println(flags);
}

void otis_emit_count_observation(uint32_t count_seq, uint32_t channel_id,
                                 uint64_t gate_open_ticks,
                                 uint64_t gate_close_ticks,
                                 const char *gate_domain,
                                 uint64_t counted_edges,
                                 const char *source_edge,
                                 const char *source_domain, uint32_t flags) {
  Serial.print(OTIS_RECORD_CNT);
  Serial.print(',');
  Serial.print(OTIS_SCHEMA_VERSION_V1);
  Serial.print(',');
  Serial.print(count_seq);
  Serial.print(',');
  Serial.print(channel_id);
  Serial.print(',');
  Serial.print((unsigned long)gate_open_ticks);
  Serial.print(',');
  Serial.print((unsigned long)gate_close_ticks);
  Serial.print(',');
  Serial.print(gate_domain);
  Serial.print(',');
  Serial.print((unsigned long)counted_edges);
  Serial.print(',');
  Serial.print(source_edge);
  Serial.print(',');
  Serial.print(source_domain);
  Serial.print(',');
  Serial.println(flags);
}

void otis_emit_health(uint32_t status_seq, uint64_t timestamp_ticks,
                      const char *status_domain, const char *component,
                      const char *status_key, const char *status_value,
                      const char *severity, uint32_t flags) {
  Serial.print(OTIS_RECORD_STS);
  Serial.print(',');
  Serial.print(OTIS_SCHEMA_VERSION_V1);
  Serial.print(',');
  Serial.print(status_seq);
  Serial.print(',');
  Serial.print((unsigned long)timestamp_ticks);
  Serial.print(',');
  Serial.print(status_domain);
  Serial.print(',');
  Serial.print(component);
  Serial.print(',');
  Serial.print(status_key);
  Serial.print(',');
  Serial.print(status_value);
  Serial.print(',');
  Serial.print(severity);
  Serial.print(',');
  Serial.println(flags);
}
