#include "otis_emit.h"
#include "otis_protocol.h"
#include "otis_transport_serial.h"

static void otis_print_uint64(uint64_t value) {
  char buffer[21];
  char *cursor = &buffer[20];
  *cursor = '\0';

  do {
    *--cursor = (char)('0' + (value % 10u));
    value /= 10u;
  } while (value != 0u);

  otis_transport_write_cstr(cursor);
}

static void otis_emit_comma(void) {
  otis_transport_write_char(',');
}

static void otis_emit_line_end(void) {
  otis_transport_write_cstr("\r\n");
}

static void otis_print_int32(int32_t value) {
  if (value < 0) {
    otis_transport_write_char('-');
    otis_transport_write_uint32((uint32_t)(-value));
    return;
  }
  otis_transport_write_uint32((uint32_t)value);
}

void otis_emit_csv_headers(void) {
  otis_transport_write_cstr(
      "record_type,schema_version,event_seq,channel_id,edge,timestamp_ticks,capture_domain,flags");
  otis_emit_line_end();
  otis_transport_write_cstr(
      "record_type,schema_version,count_seq,channel_id,gate_open_ticks,gate_close_ticks,gate_domain,counted_edges,source_edge,source_domain,flags");
  otis_emit_line_end();
  otis_transport_write_cstr(
      "record_type,schema_version,status_seq,timestamp_ticks,status_domain,component,status_key,status_value,severity,flags");
  otis_emit_line_end();
  otis_transport_write_cstr(
      "record_type,schema_version,seq,elapsed_ms,step_index,dac_code_requested,dac_code_applied,dac_code_clamped,dac_voltage_measured_v,ocxo_tune_voltage_measured_v,dwell_ms,event,flags");
  otis_emit_line_end();
}

void otis_emit_raw_event(const char *record_type, uint32_t event_seq,
                         uint32_t channel_id, const char *edge,
                         uint64_t timestamp_ticks, const char *capture_domain,
                         uint32_t flags) {
  otis_transport_write_cstr(record_type);
  otis_emit_comma();
  otis_transport_write_uint32(OTIS_SCHEMA_VERSION_V1);
  otis_emit_comma();
  otis_transport_write_uint32(event_seq);
  otis_emit_comma();
  otis_transport_write_uint32(channel_id);
  otis_emit_comma();
  otis_transport_write_cstr(edge);
  otis_emit_comma();
  otis_print_uint64(timestamp_ticks);
  otis_emit_comma();
  otis_transport_write_cstr(capture_domain);
  otis_emit_comma();
  otis_transport_write_uint32(flags);
  otis_emit_line_end();
  otis_transport_flush_if_needed();
}

void otis_emit_dac_step(uint32_t seq, uint32_t elapsed_ms, int32_t step_index,
                        uint16_t dac_code_requested,
                        uint16_t dac_code_applied, bool dac_code_clamped,
                        const char *dac_voltage_measured_v,
                        const char *ocxo_tune_voltage_measured_v,
                        uint32_t dwell_ms, const char *event,
                        uint32_t flags) {
  otis_transport_write_cstr(OTIS_RECORD_DAC);
  otis_emit_comma();
  otis_transport_write_uint32(OTIS_SCHEMA_VERSION_V1);
  otis_emit_comma();
  otis_transport_write_uint32(seq);
  otis_emit_comma();
  otis_transport_write_uint32(elapsed_ms);
  otis_emit_comma();
  otis_print_int32(step_index);
  otis_emit_comma();
  otis_transport_write_uint32(dac_code_requested);
  otis_emit_comma();
  otis_transport_write_uint32(dac_code_applied);
  otis_emit_comma();
  otis_transport_write_uint32(dac_code_clamped ? 1u : 0u);
  otis_emit_comma();
  otis_transport_write_cstr(dac_voltage_measured_v != nullptr
                                ? dac_voltage_measured_v
                                : "");
  otis_emit_comma();
  otis_transport_write_cstr(ocxo_tune_voltage_measured_v != nullptr
                                ? ocxo_tune_voltage_measured_v
                                : "");
  otis_emit_comma();
  otis_transport_write_uint32(dwell_ms);
  otis_emit_comma();
  otis_transport_write_cstr(event);
  otis_emit_comma();
  otis_transport_write_uint32(flags);
  otis_emit_line_end();
  otis_transport_flush_if_needed();
}

void otis_emit_count_observation(uint32_t count_seq, uint32_t channel_id,
                                 uint64_t gate_open_ticks,
                                 uint64_t gate_close_ticks,
                                 const char *gate_domain,
                                 uint64_t counted_edges,
                                 const char *source_edge,
                                 const char *source_domain, uint32_t flags) {
  otis_transport_write_cstr(OTIS_RECORD_CNT);
  otis_emit_comma();
  otis_transport_write_uint32(OTIS_SCHEMA_VERSION_V1);
  otis_emit_comma();
  otis_transport_write_uint32(count_seq);
  otis_emit_comma();
  otis_transport_write_uint32(channel_id);
  otis_emit_comma();
  otis_print_uint64(gate_open_ticks);
  otis_emit_comma();
  otis_print_uint64(gate_close_ticks);
  otis_emit_comma();
  otis_transport_write_cstr(gate_domain);
  otis_emit_comma();
  otis_print_uint64(counted_edges);
  otis_emit_comma();
  otis_transport_write_cstr(source_edge);
  otis_emit_comma();
  otis_transport_write_cstr(source_domain);
  otis_emit_comma();
  otis_transport_write_uint32(flags);
  otis_emit_line_end();
  otis_transport_flush_if_needed();
}

void otis_emit_health(uint32_t status_seq, uint64_t timestamp_ticks,
                      const char *status_domain, const char *component,
                      const char *status_key, const char *status_value,
                      const char *severity, uint32_t flags) {
  otis_transport_write_cstr(OTIS_RECORD_STS);
  otis_emit_comma();
  otis_transport_write_uint32(OTIS_SCHEMA_VERSION_V1);
  otis_emit_comma();
  otis_transport_write_uint32(status_seq);
  otis_emit_comma();
  otis_print_uint64(timestamp_ticks);
  otis_emit_comma();
  otis_transport_write_cstr(status_domain);
  otis_emit_comma();
  otis_transport_write_cstr(component);
  otis_emit_comma();
  otis_transport_write_cstr(status_key);
  otis_emit_comma();
  otis_transport_write_cstr(status_value);
  otis_emit_comma();
  otis_transport_write_cstr(severity);
  otis_emit_comma();
  otis_transport_write_uint32(flags);
  otis_emit_line_end();
  otis_transport_flush_if_needed();
}
