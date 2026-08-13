#include "otis_capture_irq.h"

#include <Arduino.h>
#include <hardware/gpio.h>

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
bool d14_have_processed_timestamp = false;
uint64_t d14_last_processed_timestamp = 0u;

void handle_capture_edge(void) {
  uint64_t timestamp = otis_capture_ticks_now_from_isr();
  constexpr uint32_t kCaptureFlags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;
  bool sampled_high = gpio_get(capture_gpio);
  char edge =
      capture_reference_record ? 'R' : (sampled_high ? 'R' : 'F');
  const OtisCapturedEdge captured_event = {
      capture_channel_id,
      capture_reference_record ? d14_raw_edge_count : capture_irq_edge_count,
      capture_reference_record,
      edge,
      timestamp,
      kCaptureFlags,
      sampled_high,
  };
  if (capture_reference_record) {
    d14_raw_edge_count++;
  }
  if (otis_capture_ring_push_from_isr(captured_event)) {
    capture_irq_edge_count++;
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

uint32_t otis_capture_irq_edge_count(void) {
  return capture_irq_edge_count;
}

void otis_capture_irq_process_reference_foreground(
    const OtisCapturedEdge &record) {
  if (!record.reference_record) {
    return;
  }
  if (d14_accepted_pps_count != UINT32_MAX) {
    d14_accepted_pps_count++;
  }
  d14_last_raw_timestamp = record.timestamp_ticks;
  d14_last_accepted_timestamp = record.timestamp_ticks;
  if (record.sampled_high) {
    if (d14_sampled_high_count != UINT32_MAX) {
      d14_sampled_high_count++;
    }
  } else if (d14_sampled_low_count != UINT32_MAX) {
    d14_sampled_low_count++;
  }
  if (d14_have_processed_timestamp) {
    uint64_t interval =
        otis_timer0_interval_ticks(d14_last_processed_timestamp,
                                   record.timestamp_ticks);
    d14_last_raw_interval = interval;
    switch (otis_classify_pps_interval_ticks(
        interval, OTIS_PPS_REFERENCE_SHORT_INTERVAL_TICKS,
        OTIS_PPS_REFERENCE_LONG_INTERVAL_TICKS)) {
      case OTIS_PPS_INTERVAL_SHORT:
        if (d14_rejected_short_count != UINT32_MAX) {
          d14_rejected_short_count++;
        }
        break;
      case OTIS_PPS_INTERVAL_LONG:
        if (d14_rejected_long_count != UINT32_MAX) {
          d14_rejected_long_count++;
        }
        break;
      case OTIS_PPS_INTERVAL_NORMAL:
        break;
    }
  }
  d14_last_processed_timestamp = record.timestamp_ticks;
  d14_have_processed_timestamp = true;
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

bool otis_capture_irq_begin_tcxo_counter(uint32_t gpio) {
  attachInterrupt(digitalPinToInterrupt(gpio), handle_tcxo_observation_edge,
                  RISING);
  return true;
}

uint32_t otis_capture_irq_read_and_reset_tcxo_count(void) {
  uint32_t counted_edges = tcxo_edge_count;
  tcxo_edge_count = 0;
  return counted_edges;
}
