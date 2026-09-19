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
bool otis_resource_registry_bind_pio_irq_source(
    const char *, uint8_t, uint8_t, uint8_t) {
  return true;
}

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

int main() {
  mock_core_num = 0u;
  assert(!otis_pps_snapshot_backend_begin());
  mock_core_num = 1u;
  assert(otis_pps_snapshot_backend_begin());
  assert(mock_shared_irq_handler != nullptr);
  assert(mock_shared_irq_number == 8u);
  assert(mock_irq_enabled);
  assert(mock_pio_sm_enabled);
  assert(!mock_pio_irq1_source_enabled);
  assert(backend.have_empty_lower_bound);
  mock_pio.fdebug = 0u;  // Model the initialization W1C of sticky RXSTALL.

  // FIFO clear while the SM was disabled is a known-empty observation. A
  // word committed before the first foreground poll must therefore retain a
  // finite bracket instead of manufacturing a startup UNBOUNDED record.
  push_word(0x01010101u);
  otis_pps_snapshot_backend_poll();
  fire_pio_irq();
  OtisPpsHardwareSnapshot record = pop_record();
  assert(record.session == 1u && record.sequence == 0u);
  assert(record.cumulative_down_counter == 0x01010101u);
  assert(record.status == OTIS_PPS_SNAPSHOT_STATUS_NONE);
  assert(record.timestamp_uncertainty_ticks == 4u);
  assert_empty_ring();

  // A shared IRQ belonging to another PIO source must be left untouched and
  // must consume no local source credit.
  const uint32_t disables_before_empty_irq = mock_pio_source_disable_count;
  fire_pio_irq();
  assert(mock_pio_source_disable_count == disables_before_empty_irq);
  assert_empty_ring();

  // poll() refreshes the empty lower bound and grants one IRQ entry.
  mock_pio.fdebug = 0u;  // Model FDEBUG write-one-to-clear.
  mock_time_us = 100u;
  otis_pps_snapshot_backend_poll();
  assert(mock_pio_irq1_source_enabled);
  push_word(0x11111111u);
  fire_pio_irq();
  assert(!mock_pio_irq1_source_enabled);
  assert(mock_pio_sm_enabled);

  record = pop_record();
  assert(record.session == 1u && record.sequence == 1u);
  assert(record.cumulative_down_counter == 0x11111111u);
  assert(record.status == OTIS_PPS_SNAPSHOT_STATUS_NONE);
  assert(record.service_ticks == 102u);
  assert(record.timestamp_uncertainty_ticks == 3u);
  assert_empty_ring();

  // Every word in a multiword service batch is marked timestamp-ambiguous.
  otis_pps_snapshot_backend_poll();
  push_word(0x22222222u);
  push_word(0x33333333u);
  fire_pio_irq();
  OtisPpsHardwareSnapshot first = pop_record();
  OtisPpsHardwareSnapshot second = pop_record();
  assert(first.sequence == 2u && second.sequence == 3u);
  assert(first.cumulative_down_counter == 0x22222222u);
  assert(second.cumulative_down_counter == 0x33333333u);
  assert((first.status & OTIS_PPS_SNAPSHOT_STATUS_TIMESTAMP_AMBIGUOUS) != 0u);
  assert((second.status & OTIS_PPS_SNAPSHOT_STATUS_TIMESTAMP_AMBIGUOUS) != 0u);
  assert((first.status & OTIS_PPS_SNAPSHOT_STATUS_TIMESTAMP_UNBOUNDED) == 0u);
  assert_empty_ring();

  // A stale pending shared IRQ after an empty observation does not disable
  // this source or consume the foreground credit.
  otis_pps_snapshot_backend_poll();
  const uint32_t disables_before_stale = mock_pio_source_disable_count;
  fire_pio_irq();
  assert(mock_pio_irq1_source_enabled);
  assert(mock_pio_source_disable_count == disables_before_stale);

  // A different shared source cannot drain our FIFO while our own source is
  // gated off, even though a committed word is waiting.
  pio_set_irq1_source_enabled(
      pio0, pio_get_rx_fifo_not_empty_interrupt_source(0u), false);
  push_word(0x3f3f3f3fu);
  fire_pio_irq();
  assert(mock_pio_fifo.size() == 1u);
  assert_empty_ring();
  pio_set_irq1_source_enabled(
      pio0, pio_get_rx_fifo_not_empty_interrupt_source(0u), true);
  fire_pio_irq();
  record = pop_record();
  assert(record.sequence == 4u);
  assert(record.cumulative_down_counter == 0x3f3f3f3fu);
  assert_empty_ring();

  // RXSTALL freezes the source/SM first, then preserves every committed word.
  otis_pps_snapshot_backend_poll();
  push_word(0x44444444u);
  push_word(0x55555555u);
  mock_pio.fdebug = 1u;
  fire_pio_irq();
  assert(!mock_pio_sm_enabled);
  first = pop_record();
  second = pop_record();
  assert((first.status & OTIS_PPS_SNAPSHOT_STATUS_PIO_RXSTALL) != 0u);
  assert((second.status & OTIS_PPS_SNAPSHOT_STATUS_PIO_RXSTALL) != 0u);
  assert_empty_ring();
  OtisPpsSnapshotBackendStats stats = {};
  otis_pps_snapshot_backend_get_stats(&stats);
  assert(stats.fault_latched && !stats.running);
  assert(stats.pio_rxstall_count == 1u);
  assert(stats.continuity_loss_count == 1u);

  assert(otis_pps_snapshot_backend_rearm());
  mock_pio.fdebug = 0u;
  otis_pps_snapshot_backend_get_stats(&stats);
  assert(stats.session == 2u && stats.running && !stats.fault_latched);
  assert(stats.producer_ordinal == 0u && stats.consumer_ordinal == 0u);

  // Fill all 128 software slots without consuming. The next committed FIFO
  // word is left unread when ring exhaustion freezes the source and SM.
  for (uint32_t index = 0u; index < 128u; ++index) {
    otis_pps_snapshot_backend_poll();
    push_word(0x10000000u + index);
    fire_pio_irq();
  }
  otis_pps_snapshot_backend_poll();
  push_word(0xabcdef01u);
  fire_pio_irq();
  assert(mock_pio_fifo.size() == 1u);
  assert(!mock_pio_sm_enabled);
  otis_pps_snapshot_backend_get_stats(&stats);
  assert(stats.fault_latched);
  assert(stats.ring_full_count == 1u);
  assert(stats.producer_ordinal == 128u);
  assert(!otis_pps_snapshot_backend_rearm());

  // Free one ring slot, then poll moves the frozen committed word without
  // clearing the retained fault or re-enabling the source.
  record = pop_record();
  assert(record.sequence == 0u);
  otis_pps_snapshot_backend_poll();
  assert(mock_pio_fifo.empty());
  assert(!mock_pio_irq1_source_enabled);
  for (uint32_t index = 1u; index < 128u; ++index) {
    record = pop_record();
    assert(record.sequence == index);
  }
  record = pop_record();
  assert(record.sequence == 128u);
  assert(record.cumulative_down_counter == 0xabcdef01u);
  assert((record.status & OTIS_PPS_SNAPSHOT_STATUS_RING_FULL) != 0u);
  assert_empty_ring();
  otis_pps_snapshot_backend_get_stats(&stats);
  assert(otis_pps_snapshot_backend_rearm());
  mock_pio.fdebug = 0u;

  // A refilling source cannot exceed eight reads in one admitted IRQ.
  otis_pps_snapshot_backend_poll();
  for (uint32_t index = 0u; index < 9u; ++index) {
    push_word(0x20000000u + index);
  }
  fire_pio_irq();
  assert(mock_pio_fifo.size() == 1u);
  otis_pps_snapshot_backend_get_stats(&stats);
  assert(stats.fault_latched && !stats.running);
  assert(stats.irq_budget_exhausted_count == 1u);
  for (uint32_t index = 0u; index < 8u; ++index) {
    record = pop_record();
    assert(record.sequence == index);
    assert((record.status &
            OTIS_PPS_SNAPSHOT_STATUS_IRQ_BUDGET_EXHAUSTED) != 0u);
  }
  otis_pps_snapshot_backend_poll();
  assert(mock_pio_fifo.empty());
  record = pop_record();
  assert(record.sequence == 8u);
  assert((record.status &
          OTIS_PPS_SNAPSHOT_STATUS_IRQ_BUDGET_EXHAUSTED) != 0u);
  assert_empty_ring();

  // Rearm is refused until fault state has been observed and every record is
  // drained. It increments the session and stale pending IRQ cannot publish.
  otis_pps_snapshot_backend_get_stats(&stats);
  assert(otis_pps_snapshot_backend_rearm());
  mock_pio.fdebug = 0u;
  fire_pio_irq();
  assert_empty_ring();
  otis_pps_snapshot_backend_poll();
  push_word(0x30303030u);
  fire_pio_irq();
  record = pop_record();
  assert(record.session == 4u && record.sequence == 0u);
  assert(record.cumulative_down_counter == 0x30303030u);

  // Rearm also establishes a known-empty bound before enabling the SM, so a
  // singleton committed before the next poll remains bounded.
  assert_empty_ring();
  assert(otis_pps_snapshot_backend_rearm());
  mock_pio.fdebug = 0u;
  push_word(0x40404040u);
  otis_pps_snapshot_backend_poll();
  fire_pio_irq();
  record = pop_record();
  assert(record.session == 5u && record.sequence == 0u);
  assert(record.timestamp_uncertainty_ticks == 4u);
  assert(record.status == OTIS_PPS_SNAPSHOT_STATUS_NONE);

  // A lower bound more than one full us32 wrap old cannot alias into an
  // apparently fresh singleton. The internal wide timer makes it unknown.
  assert_empty_ring();
  assert(otis_pps_snapshot_backend_rearm());
  mock_pio.fdebug = 0u;
  mock_time_us = 100u;
  otis_pps_snapshot_backend_poll();
  mock_time_us = (uint64_t(1u) << 32) + 105u;
  push_word(0x50505050u);
  fire_pio_irq();
  record = pop_record();
  assert(record.timestamp_uncertainty_ticks == UINT32_MAX);
  assert((record.status &
          OTIS_PPS_SNAPSHOT_STATUS_TIMESTAMP_UNBOUNDED) != 0u);

  // Crossing the low 32-bit timer boundary remains bounded when the wide
  // elapsed interval is small.
  assert(otis_pps_snapshot_backend_rearm());
  mock_pio.fdebug = 0u;
  mock_time_us = UINT32_MAX;
  otis_pps_snapshot_backend_poll();
  push_word(0x60606060u);
  fire_pio_irq();
  record = pop_record();
  assert(record.service_ticks == 1u);
  assert(record.timestamp_uncertainty_ticks == 3u);
  assert(record.status == OTIS_PPS_SNAPSHOT_STATUS_NONE);

  // A sticky RXSTALL is fatal even if the FIFO has become empty before the
  // foreground health observation.
  mock_pio.fdebug = 1u;
  otis_pps_snapshot_backend_get_stats(&stats);
  assert(stats.fault_latched && !stats.running);
  assert((stats.fault_flags & OTIS_PPS_SNAPSHOT_STATUS_PIO_RXSTALL) != 0u);

  // A wrapped session would become the reserved no-session identity.
  assert_empty_ring();
  backend.session = UINT32_MAX;
  assert(!otis_pps_snapshot_backend_rearm());
  assert(!mock_pio_sm_enabled);
  return 0;
}
