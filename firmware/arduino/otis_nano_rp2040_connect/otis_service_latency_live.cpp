#include "otis_service_latency_live.h"
#include "otis_transport_serial.h"
#include <stdio.h>

namespace {
// Six timing-owner streams and four serial-owner streams. No IRQ instrumentation.
OtisServiceLatencyStats streams[10] = {};
bool initialized[10] = {};
OtisServiceLatencyStats mailbox = {};
// Core 0 publishes request; Core 1 publishes ready; Core 0 releases empty.
uint32_t mailbox_state = 0; // 0 empty, 1 requested, 2 ready
uint32_t requested_index = 0;
OtisServiceLatencyStats report = {};
uint32_t report_index = 0, report_generation = 0, report_part = 0;
uint32_t export_drops[10] = {};
uint32_t last_output_ms = 0;
bool report_active = false;
char line[256];

OtisServiceLatencyStats &stream(uint32_t index) {
  if (!initialized[index]) {
    otis_service_latency_reset(streams[index],
        static_cast<OtisServiceLatencyChannel>(index % 2 + 1),
        static_cast<OtisServiceLatencyStage>(index / 2), 1000u);
    initialized[index] = true;
  }
  return streams[index];
}
void drop() {
  if (export_drops[report_index] != UINT32_MAX) ++export_drops[report_index];
}
} // namespace

void otis_service_latency_live_note(const OtisServiceLatencySample &sample) {
  if (sample.channel < OTIS_LATENCY_D14 || sample.channel > OTIS_LATENCY_D8 ||
      sample.stage > OTIS_LATENCY_OUTPUT_PRECOMMIT_TO_FORMATTER_DISPATCH) return;
  const uint32_t index = uint32_t(sample.stage) * 2u + uint32_t(sample.channel) - 1u;
  otis_service_latency_observe(stream(index), sample);
}

void otis_service_latency_live_timing_service() {
  if (__atomic_load_n(&mailbox_state, __ATOMIC_ACQUIRE) != 1u) return;
  // Request is immutable until the ready response is consumed.
  mailbox = stream(requested_index);
  __atomic_store_n(&mailbox_state, 2u, __ATOMIC_RELEASE);
}

void otis_service_latency_live_output_service(uint32_t now_ms) {
  if (uint32_t(now_ms - last_output_ms) < 250u) return;
  last_output_ms = now_ms;
  if (!report_active) {
    if (report_index < 6u) {
      const uint32_t state = __atomic_load_n(&mailbox_state, __ATOMIC_ACQUIRE);
      if (state == 0u) {
        requested_index = report_index;
        __atomic_store_n(&mailbox_state, 1u, __ATOMIC_RELEASE);
        return;
      }
      if (state != 2u) return;
      report = mailbox;
      __atomic_store_n(&mailbox_state, 0u, __ATOMIC_RELEASE);
    } else report = stream(report_index);
    // Saturating sum keeps model-rejected samples and export loss explicit.
    const uint32_t room = UINT32_MAX - report.diagnostic_drops;
    if (export_drops[report_index] > room) {
      report.diagnostic_drops = UINT32_MAX;
      report.counters_saturated = true;
    } else report.diagnostic_drops += export_drops[report_index];
    report_active = true;
    report_part = 0;
    ++report_generation;
  }
  int n = 0;
  if (report_part == 0u) {
    n = snprintf(line, sizeof(line),
        "LAT,v=1,g=%lu,c=%u,s=%u,p=0,e=%lu,m=%lu,a=%lu,x=%lu,d=%lu,t=%lu,sat=%u,hw=0\r\n",
        (unsigned long)report_generation, unsigned(report.channel), unsigned(report.stage),
        (unsigned long)report.eligible, (unsigned long)report.missing,
        (unsigned long)report.ambiguous, (unsigned long)report.threshold_exceeded,
        (unsigned long)report.diagnostic_drops, (unsigned long)report.threshold_us,
        unsigned(report.counters_saturated || export_drops[report_index] == UINT32_MAX));
  } else if (report_part == 1u) {
    n = snprintf(line, sizeof(line),
        "LAT,v=1,g=%lu,c=%u,s=%u,p=1,hv=1,b0=%lu,b1=%lu,b2=%lu,b3=%lu,b4=%lu,b5=%lu,b6=%lu,b7=%lu\r\n",
        (unsigned long)report_generation, unsigned(report.channel), unsigned(report.stage),
        (unsigned long)report.histogram[0], (unsigned long)report.histogram[1],
        (unsigned long)report.histogram[2], (unsigned long)report.histogram[3],
        (unsigned long)report.histogram[4], (unsigned long)report.histogram[5],
        (unsigned long)report.histogram[6], (unsigned long)report.histogram[7]);
  } else {
    const uint32_t which = report_part - 2u;
    const auto &sample = which == 0 ? report.minimum : which == 1 ? report.maximum : (which == 4 ? report.last_noneligible : report.tail[which - 2]);
    const bool present = which < 2 ? report.eligible != 0 : (which == 4 ? report.have_noneligible : which - 2 < report.tail_count);
    n = snprintf(line, sizeof(line),
        "LAT,v=1,g=%lu,c=%u,s=%u,p=%lu,have=%u,session=%lu,seq=%lu,start=%lu,end=%lu,u=%lu,status=%u,domain=%u\r\n",
        (unsigned long)report_generation, unsigned(report.channel), unsigned(report.stage),
        (unsigned long)report_part, unsigned(present), (unsigned long)sample.capture_session,
        (unsigned long)sample.source_sequence, (unsigned long)sample.start_us32,
        (unsigned long)sample.end_us32, (unsigned long)sample.uncertainty_us,
        unsigned(present ? sample.status : OTIS_LATENCY_MISSING),
        unsigned(present ? sample.domain : OTIS_LATENCY_DOMAIN_UNAVAILABLE));
  }
  // Drop whole diagnostic rows before writing; never retain a partial-frame
  // owner, wait, flush, or feed diagnostic pressure into a safety predicate.
  // Core 0 is the sole writer. Leave 64 bytes of USB buffer for normal service.
  if (n <= 0 || size_t(n) >= sizeof(line)) drop();
  else if (!otis_transport_try_write_diagnostic(reinterpret_cast<const uint8_t *>(line), size_t(n))) drop();
  if (++report_part == 7u) {
    report_active = false;
    report_index = (report_index + 1u) % 10u;
  }
}
