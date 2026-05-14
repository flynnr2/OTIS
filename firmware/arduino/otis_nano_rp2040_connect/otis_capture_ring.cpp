#include "otis_capture_ring.h"

#include <Arduino.h>

#include "otis_config.h"
#include "otis_protocol.h"

namespace {

constexpr uint8_t kCaptureRingSize =
    static_cast<uint8_t>(OTIS_CAPTURE_RING_SIZE);

volatile OtisCapturedEdge capture_ring[kCaptureRingSize];
volatile uint8_t capture_head = 0;
volatile uint8_t capture_tail = 0;
volatile uint32_t capture_dropped_count = 0;

uint64_t capture_ticks_now(void) {
  return (uint64_t)micros() * 16ull;
}

}  // namespace

void otis_capture_ring_reset(void) {
  noInterrupts();
  capture_head = 0;
  capture_tail = 0;
  capture_dropped_count = 0;
  interrupts();
}

bool otis_capture_ring_push_from_isr(uint32_t channel_id,
                                     bool reference_record,
                                     char edge) {
  uint8_t next_head = (uint8_t)((capture_head + 1u) % kCaptureRingSize);
  if (next_head == capture_tail) {
    capture_dropped_count++;
    return false;
  }

  capture_ring[capture_head].channel_id = channel_id;
  capture_ring[capture_head].reference_record = reference_record;
  capture_ring[capture_head].edge = edge;
  capture_ring[capture_head].timestamp_ticks = capture_ticks_now();
  capture_ring[capture_head].flags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;
  capture_head = next_head;
  return true;
}

bool otis_capture_ring_pop(OtisCapturedEdge *record) {
  bool have_record = false;
  noInterrupts();
  if (capture_tail != capture_head) {
    record->channel_id = capture_ring[capture_tail].channel_id;
    record->reference_record = capture_ring[capture_tail].reference_record;
    record->edge = capture_ring[capture_tail].edge;
    record->timestamp_ticks = capture_ring[capture_tail].timestamp_ticks;
    record->flags = capture_ring[capture_tail].flags;
    capture_tail = (uint8_t)((capture_tail + 1u) % kCaptureRingSize);
    have_record = true;
  }
  interrupts();
  return have_record;
}

void otis_capture_ring_note_drop(void) {
  capture_dropped_count++;
}

uint32_t otis_capture_ring_dropped_count(void) {
  return capture_dropped_count;
}

uint8_t otis_capture_ring_depth(void) {
  return kCaptureRingSize;
}
