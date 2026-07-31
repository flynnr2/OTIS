#include "otis_pps_dual_observer.h"

#include <Arduino.h>

#include "otis_config.h"
#include "otis_timebase.h"

namespace {

struct D10WitnessEvent {
  uint64_t timestamp_ticks;
  uint8_t sampled_high;
};

uint32_t d10_gpio = 0;
volatile uint32_t d10_raw_edge_count = 0;
volatile uint64_t d10_last_edge_timestamp = 0;
volatile uint64_t d10_last_interval = 0;
volatile uint32_t d10_short_interval_count = 0;
volatile uint32_t d10_long_interval_count = 0;
volatile uint32_t d10_sampled_high_count = 0;
volatile uint32_t d10_sampled_low_count = 0;
volatile uint32_t d10_buffer_overflow_count = 0;
volatile uint32_t d10_buffered_event_count = 0;
D10WitnessEvent d10_events[OTIS_PPS_DUAL_OBSERVER_BUFFER_SIZE];
volatile uint8_t d10_event_head = 0;
volatile uint8_t d10_event_tail = 0;

uint32_t d10_consumed_event_count = 0;
bool d10_have_processed_timestamp = false;
uint64_t d10_last_processed_timestamp = 0;
uint32_t pps_burst_count = 0;
bool pps_burst_active = false;
uint64_t pps_burst_start = 0;
uint64_t pps_burst_last_event = 0;
uint32_t pps_burst_d10_edges = 0;
uint32_t pps_burst_d10_short = 0;
uint32_t recent_short_intervals = 0;

void push_d10_event_from_isr(const D10WitnessEvent &event) {
  uint8_t next_head =
      (uint8_t)((d10_event_head + 1u) % OTIS_PPS_DUAL_OBSERVER_BUFFER_SIZE);
  if (next_head == d10_event_tail) {
    d10_buffer_overflow_count++;
    return;
  }
  d10_events[d10_event_head] = event;
  d10_event_head = next_head;
  d10_buffered_event_count++;
}

void handle_d10_witness_edge(void) {
  uint64_t timestamp = otis_capture_ticks_now();
  int sampled_level = digitalRead(d10_gpio);
  d10_last_edge_timestamp = timestamp;
  d10_raw_edge_count++;
  if (sampled_level) {
    d10_sampled_high_count++;
  } else {
    d10_sampled_low_count++;
  }
  push_d10_event_from_isr(
      {timestamp, (uint8_t)(sampled_level ? 1u : 0u)});
}

bool pop_d10_event(D10WitnessEvent *out) {
  if (out == nullptr) {
    return false;
  }
  noInterrupts();
  if (d10_event_tail == d10_event_head) {
    interrupts();
    return false;
  }
  *out = d10_events[d10_event_tail];
  d10_event_tail =
      (uint8_t)((d10_event_tail + 1u) % OTIS_PPS_DUAL_OBSERVER_BUFFER_SIZE);
  interrupts();
  return true;
}

}  // namespace

bool otis_pps_dual_observer_begin(uint32_t gpio) {
#if OTIS_ENABLE_PPS_DUAL_OBSERVER
  d10_gpio = gpio;
  pinMode(d10_gpio, INPUT);
  attachInterrupt(digitalPinToInterrupt(d10_gpio), handle_d10_witness_edge,
                  RISING);
  return true;
#else
  (void)gpio;
  return true;
#endif
}

void otis_pps_dual_observer_service(void) {
#if OTIS_ENABLE_PPS_DUAL_OBSERVER
  D10WitnessEvent event;
  uint8_t processed = 0;
  while (processed < 4u && pop_d10_event(&event)) {
    processed++;
    d10_consumed_event_count++;
    uint64_t interval_ticks = 0u;
    if (d10_have_processed_timestamp) {
      interval_ticks = otis_timer0_interval_ticks(
          d10_last_processed_timestamp, event.timestamp_ticks);
      d10_last_interval = interval_ticks;
      switch (otis_classify_pps_interval_ticks(
          interval_ticks, OTIS_PPS_DUAL_OBSERVER_SHORT_INTERVAL_TICKS,
          OTIS_PPS_DUAL_OBSERVER_LONG_INTERVAL_TICKS)) {
        case OTIS_PPS_INTERVAL_SHORT:
          d10_short_interval_count++;
          break;
        case OTIS_PPS_INTERVAL_LONG:
          d10_long_interval_count++;
          break;
        case OTIS_PPS_INTERVAL_NORMAL:
          break;
      }
    }
    d10_last_processed_timestamp = event.timestamp_ticks;
    d10_have_processed_timestamp = true;
    if (interval_ticks > 0u &&
        interval_ticks < OTIS_PPS_DUAL_OBSERVER_SHORT_INTERVAL_TICKS) {
      recent_short_intervals++;
      if (!pps_burst_active &&
          recent_short_intervals >= OTIS_PPS_DUAL_OBSERVER_BURST_SHORT_THRESHOLD) {
        pps_burst_active = true;
        pps_burst_count++;
        pps_burst_start = event.timestamp_ticks;
        pps_burst_d10_edges = 0;
        pps_burst_d10_short = 0;
      }
    } else {
      recent_short_intervals = 0;
      pps_burst_active = false;
    }
    if (pps_burst_active) {
      pps_burst_last_event = event.timestamp_ticks;
      pps_burst_d10_edges++;
      if (interval_ticks > 0u &&
          interval_ticks < OTIS_PPS_DUAL_OBSERVER_SHORT_INTERVAL_TICKS) {
        pps_burst_d10_short++;
      }
    }
  }
#endif
}

void otis_pps_dual_observer_get_stats(OtisPpsDualObserverStats *out) {
  if (out == nullptr) {
    return;
  }
  noInterrupts();
  out->d10_raw_edge_count = d10_raw_edge_count;
  out->d10_last_edge_timestamp = d10_last_edge_timestamp;
  out->d10_last_interval = d10_last_interval;
  out->d10_short_interval_count = d10_short_interval_count;
  out->d10_long_interval_count = d10_long_interval_count;
  out->d10_sampled_high_count = d10_sampled_high_count;
  out->d10_sampled_low_count = d10_sampled_low_count;
  out->d10_buffer_overflow_count = d10_buffer_overflow_count;
  out->d10_buffered_event_count = d10_buffered_event_count;
  interrupts();
  out->d10_consumed_event_count = d10_consumed_event_count;
  out->pps_burst_count = pps_burst_count;
  out->pps_burst_active = pps_burst_active;
  out->pps_burst_start = pps_burst_start;
  out->pps_burst_last_event = pps_burst_last_event;
  out->pps_burst_d10_edges = pps_burst_d10_edges;
  out->pps_burst_d10_short = pps_burst_d10_short;
}
