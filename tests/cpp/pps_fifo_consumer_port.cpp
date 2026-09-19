#include <assert.h>
#include <stdint.h>

#include <deque>

#include "hardware/irq.h"
#include "hardware/pio.h"

uint32_t mock_system_clock_hz = 133000000u;
uint mock_core_num = 1u;
uint64_t mock_time_us = 1u;
bool mock_interrupts_disabled = false;
pio_hw_t mock_pio = {};
std::deque<uint32_t> mock_pio_fifo;
bool mock_pio_sm_enabled = false;
bool mock_pio_irq1_source_enabled = false;
uint32_t mock_pio_source_enable_count = 0u;
uint32_t mock_pio_source_disable_count = 0u;
irq_handler_t mock_shared_irq_handler = nullptr;
irq_handler_t mock_exclusive_irq_handler = nullptr;
uint mock_shared_irq_number = 0u;
bool mock_irq_enabled = false;

#include "../../firmware/arduino/otis_nano_rp2040_connect/otis_pps_snapshot_backend.cpp"

bool otis_resource_registry_bind_pio_state_machine(
    const char *, uint8_t, uint8_t) {
  return true;
}
bool otis_resource_registry_bind_pio_program(
    const char *, uint8_t, uint8_t, uint8_t) {
  return true;
}

bool otis_resource_registry_bind_pio_irq_source(const char *, uint8_t, uint8_t, uint8_t) { return true; }

static void push_word(uint32_t word) {
  mock_pio_fifo.push_back(word);
  if (mock_pio_irq1_source_enabled) {
    mock_pio.ints1 = 1u << static_cast<uint32_t>(
        pio_get_rx_fifo_not_empty_interrupt_source(0u));
  }
}

static void fire_pio_irq() {
  assert(mock_shared_irq_handler != nullptr);
  mock_shared_irq_handler();
}

static OtisPpsHardwareSnapshot pop_record() {
  OtisPpsHardwareSnapshot record = {};
  assert(otis_pps_snapshot_backend_pop(&record));
  return record;
}

static void assert_empty_ring() {
  OtisPpsHardwareSnapshot unused = {};
  assert(!otis_pps_snapshot_backend_pop(&unused));
}


void native_fifo_begin() {
  assert(otis_pps_snapshot_backend_begin());
  mock_pio.fdebug = 0u;
}
void native_fifo_rearm() {
  assert_empty_ring();
  assert(otis_pps_snapshot_backend_rearm());
  mock_pio.fdebug = 0u;
}
OtisPpsHardwareSnapshot native_fifo_capture(uint32_t count, uint64_t service_ticks) {
  mock_time_us = service_ticks - 10u;
  otis_pps_snapshot_backend_poll();
  assert(mock_pio_irq1_source_enabled);
  // The driver samples once before checking FIFO state, then after the read.
  mock_time_us = service_ticks - 1u;
  push_word(count);
  fire_pio_irq();
  auto snapshot = pop_record();
  assert(snapshot.service_ticks == uint32_t(service_ticks));
  assert(snapshot.timestamp_uncertainty_ticks == 11u);
  assert(snapshot.status == 0u);
  return snapshot;
}
