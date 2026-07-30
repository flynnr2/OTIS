#include "otis_capture_irq.h"

#include <Arduino.h>

#include "otis_capture_ring.h"
#include "otis_config.h"
#include "otis_protocol.h"
#include "otis_timebase.h"

namespace {

uint32_t capture_gpio = 0;
uint32_t capture_channel_id = 0;
bool capture_reference_record = false;
volatile uint32_t capture_irq_edge_count = 0;
volatile uint32_t tcxo_edge_count = 0;
volatile uint32_t d14_raw_edge_count = 0;
volatile uint32_t d14_accepted_pps_count = 0;
volatile uint32_t d14_rejected_short_count = 0;
volatile uint32_t d14_rejected_long_count = 0;
volatile uint64_t d14_last_raw_timestamp = 0;
volatile uint64_t d14_last_raw_interval = 0;
volatile uint64_t d14_last_accepted_timestamp = 0;
volatile uint32_t d14_sampled_high_count = 0;
volatile uint32_t d14_sampled_low_count = 0;
OtisPpsCountBoundaryIsrHandler pps_count_boundary_handler = nullptr;

void handle_capture_edge(void) {
  uint64_t timestamp = otis_capture_ticks_now();
  constexpr uint32_t kCaptureFlags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;
  bool pps_boundary_owned =
      capture_reference_record && pps_count_boundary_handler != nullptr;
  if (pps_boundary_owned) {
    // Secure the physical aperture immediately after timestamp capture. D14
    // diagnostics and sampled-level bookkeeping deliberately happen later.
    pps_count_boundary_handler(timestamp, kCaptureFlags);
  }

  int sampled_level = digitalRead(capture_gpio);
  char edge =
      capture_reference_record ? 'R' : (sampled_level ? 'R' : 'F');
  const OtisCapturedEdge captured_event = {
      capture_channel_id,
      capture_reference_record,
      edge,
      timestamp,
      kCaptureFlags,
  };
  if (capture_reference_record) {
    d14_raw_edge_count++;
    if (sampled_level) {
      d14_sampled_high_count++;
    } else {
      d14_sampled_low_count++;
    }
    if (d14_last_raw_timestamp != 0u) {
      uint64_t interval =
          otis_timer0_interval_ticks(d14_last_raw_timestamp, timestamp);
      d14_last_raw_interval = interval;
      switch (otis_classify_pps_interval_ticks(
          interval, OTIS_PPS_DUAL_OBSERVER_SHORT_INTERVAL_TICKS,
          OTIS_PPS_DUAL_OBSERVER_LONG_INTERVAL_TICKS)) {
        case OTIS_PPS_INTERVAL_SHORT:
          d14_rejected_short_count++;
          break;
        case OTIS_PPS_INTERVAL_LONG:
          d14_rejected_long_count++;
          break;
        case OTIS_PPS_INTERVAL_NORMAL:
          break;
      }
    }
    d14_last_raw_timestamp = timestamp;
  }
  if (pps_boundary_owned) {
    capture_irq_edge_count++;
    d14_accepted_pps_count++;
    d14_last_accepted_timestamp = timestamp;
    return;
  }
  if (otis_capture_ring_push_from_isr(captured_event)) {
    capture_irq_edge_count++;
    if (capture_reference_record) {
      d14_accepted_pps_count++;
      d14_last_accepted_timestamp = timestamp;
    }
  }
}

void handle_tcxo_observation_edge(void) {
  tcxo_edge_count++;
}

}  // namespace

bool otis_capture_irq_begin(const OtisCaptureBackendConfig &config) {
  capture_gpio = config.gpio;
  capture_channel_id = config.channel_id;
  capture_reference_record = config.reference_record;
  attachInterrupt(digitalPinToInterrupt(config.gpio), handle_capture_edge,
                  static_cast<PinStatus>(config.interrupt_mode));
  return true;
}

void otis_capture_irq_set_pps_count_boundary_handler(
    OtisPpsCountBoundaryIsrHandler handler) {
  noInterrupts();
  pps_count_boundary_handler = handler;
  interrupts();
}

uint32_t otis_capture_irq_edge_count(void) {
  return capture_irq_edge_count;
}

void otis_capture_irq_get_reference_stats(OtisCaptureIrqReferenceStats *out) {
  if (out == nullptr) {
    return;
  }
  noInterrupts();
  out->d14_raw_edge_count = d14_raw_edge_count;
  out->d14_accepted_pps_count = d14_accepted_pps_count;
  out->d14_rejected_short_count = d14_rejected_short_count;
  out->d14_rejected_long_count = d14_rejected_long_count;
  out->d14_last_raw_timestamp = d14_last_raw_timestamp;
  out->d14_last_raw_interval = d14_last_raw_interval;
  out->d14_last_accepted_timestamp = d14_last_accepted_timestamp;
  out->d14_sampled_high_count = d14_sampled_high_count;
  out->d14_sampled_low_count = d14_sampled_low_count;
  interrupts();
}

void otis_capture_irq_begin_tcxo_counter(uint32_t gpio) {
  attachInterrupt(digitalPinToInterrupt(gpio), handle_tcxo_observation_edge,
                  RISING);
}

uint32_t otis_capture_irq_read_and_reset_tcxo_count(void) {
  uint32_t counted_edges = tcxo_edge_count;
  tcxo_edge_count = 0;
  return counted_edges;
}
