#include "otis_capture_irq.h"

#include <Arduino.h>
#include <hardware/gpio.h>

#include "otis_board.h"
#include "otis_capture_ring.h"
#include "otis_config.h"
#include "otis_protocol.h"
#include "otis_timebase.h"

namespace {

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
  uint64_t timestamp = otis_monotonic_us32_now_from_isr();
  constexpr uint32_t kCaptureFlags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;
  bool sampled_high = gpio_get(OTIS_PIN_PPS_REFERENCE);
  const OtisCapturedEdge captured_event = {
      OTIS_CHANNEL_PPS_REFERENCE,
      d14_raw_edge_count,
      true,
      'R',
      timestamp,
      kCaptureFlags,
      sampled_high,
  };
  d14_raw_edge_count++;
  otis_capture_ring_push_from_isr(captured_event);
}

}  // namespace

bool otis_capture_irq_begin_d14_reference(void) {
  attachInterrupt(digitalPinToInterrupt(OTIS_PIN_PPS_REFERENCE),
                  handle_capture_edge, RISING);
  return true;
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
        otis_monotonic_us32_interval(d14_last_processed_timestamp,
                                   record.timestamp_ticks);
    d14_last_raw_interval = interval;
    switch (otis_classify_pps_interval_us(
        interval, OTIS_PPS_REFERENCE_SHORT_INTERVAL_US,
        OTIS_PPS_REFERENCE_LONG_INTERVAL_US)) {
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
