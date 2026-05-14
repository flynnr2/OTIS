#include "otis_capture_irq.h"

#include <Arduino.h>

#include "otis_capture_ring.h"

namespace {

uint32_t capture_gpio = 0;
uint32_t capture_channel_id = 0;
bool capture_reference_record = false;
volatile uint32_t capture_irq_edge_count = 0;
volatile uint32_t tcxo_edge_count = 0;

void handle_capture_edge(void) {
  char edge =
      capture_reference_record ? 'R' : (digitalRead(capture_gpio) ? 'R' : 'F');
  if (otis_capture_ring_push_from_isr(capture_channel_id,
                                      capture_reference_record, edge)) {
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

void otis_capture_irq_begin_tcxo_counter(uint32_t gpio) {
  attachInterrupt(digitalPinToInterrupt(gpio), handle_tcxo_observation_edge,
                  RISING);
}

uint32_t otis_capture_irq_read_and_reset_tcxo_count(void) {
  uint32_t counted_edges = tcxo_edge_count;
  tcxo_edge_count = 0;
  return counted_edges;
}
