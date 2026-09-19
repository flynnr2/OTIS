#include "otis_pps_snapshot_backend.h"

#include <hardware/clocks.h>
#include <hardware/gpio.h>
#include <hardware/irq.h>
#include <hardware/pio.h>
#include <hardware/regs/pio.h>
#include <hardware/sync.h>
#include <hardware/timer.h>
#include <pico/platform.h>

#include "otis_board.h"
#include "otis_config.h"
#include "otis_pps_fifo_drain.h"
#include "otis_pps_snapshot.pio.h"
#include "otis_resource_registry.h"

namespace {

constexpr uint32_t kRequiredSystemClockHz = 133000000u;
constexpr uint32_t kSnapshotRingCapacity = 128u;
constexpr uint32_t kSnapshotRingMask = kSnapshotRingCapacity - 1u;
constexpr uint32_t kFifoWordsPerForegroundService = 8u;
constexpr uint kPioIrqIndex = 1u;
static_assert((kSnapshotRingCapacity & kSnapshotRingMask) == 0u,
              "snapshot ring capacity must be a power of two");

OtisPpsHardwareSnapshot snapshot_ring[kSnapshotRingCapacity] = {};

struct BackendState {
  PIO pio;
  int sm;
  int program_offset;
  int irq_number;
  bool initialized;
  bool running;
  bool fault_latched;
  bool fault_reported;
  bool have_empty_lower_bound;
  volatile uint32_t session;
  volatile uint32_t producer_ordinal;
  volatile uint32_t consumer_ordinal;
  volatile uint32_t backlog_high_water;
  volatile uint32_t continuity_loss_count;
  volatile uint32_t pio_rxstall_count;
  volatile uint32_t irq_budget_exhausted_count;
  volatile uint32_t ring_full_count;
  volatile uint32_t timestamp_ambiguous_count;
  volatile uint32_t fault_flags;
  volatile uint32_t last_service_ticks;
  uint64_t empty_lower_bound_ticks;
  uint32_t irq_entries_since_poll;
  uint32_t words_since_poll;
  uint32_t system_clock_hz;
};

BackendState backend = {
    pio0, -1, -1, -1, false, false, false, false, false,
    0u,   0u, 0u,  0u,    0u,    0u,    0u,    0u,
    0u,   0u, 0u,  0u,    0u,    0u,    0u,
};

void increment_saturating(volatile uint32_t *counter) {
  if (*counter != UINT32_MAX) *counter += 1u;
}

void add_saturating(volatile uint32_t *counter, uint32_t value) {
  if (UINT32_MAX - *counter < value) {
    *counter = UINT32_MAX;
  } else {
    *counter += value;
  }
}

uint sm_index() {
  return static_cast<uint>(backend.sm);
}

pio_interrupt_source_t rx_source() {
  return pio_get_rx_fifo_not_empty_interrupt_source(sm_index());
}

bool rxstall_latched() {
  if (backend.sm < 0) return false;
  const uint32_t mask = 1u << (PIO_FDEBUG_RXSTALL_LSB + sm_index());
  return (backend.pio->fdebug & mask) != 0u;
}

void set_source_enabled(bool enabled) {
  if (backend.sm >= 0) {
    pio_set_irq1_source_enabled(backend.pio, rx_source(), enabled);
  }
}

void stop_source_and_state_machine() {
  set_source_enabled(false);
  if (backend.sm >= 0) {
    pio_sm_set_enabled(backend.pio, sm_index(), false);
  }
  backend.running = false;
}

struct HardwareFifoPort {
  bool empty() const {
    return pio_sm_is_rx_fifo_empty(backend.pio, sm_index());
  }

  bool rxstall() const {
    return rxstall_latched();
  }

  uint32_t read() {
    return pio_sm_get(backend.pio, sm_index());
  }

  uint64_t now() const {
    return time_us_64();
  }

  void stop() {
    stop_source_and_state_machine();
  }
};

void latch_faults(uint32_t faults) {
  if (faults == 0u) return;
  const uint32_t new_faults = faults & ~backend.fault_flags;
  if ((new_faults & OTIS_PPS_SNAPSHOT_STATUS_PIO_RXSTALL) != 0u) {
    increment_saturating(&backend.pio_rxstall_count);
  }
  if ((new_faults & OTIS_PPS_SNAPSHOT_STATUS_RING_FULL) != 0u) {
    increment_saturating(&backend.ring_full_count);
  }
  if ((new_faults &
       OTIS_PPS_SNAPSHOT_STATUS_IRQ_BUDGET_EXHAUSTED) != 0u) {
    increment_saturating(&backend.irq_budget_exhausted_count);
  }
  backend.fault_flags |= faults;
  if (!backend.fault_latched) {
    backend.fault_latched = true;
    backend.fault_reported = false;
    increment_saturating(&backend.continuity_loss_count);
  }
  stop_source_and_state_machine();
}

void publish_drain_result(const OtisPpsFifoDrainResult &result) {
  uint32_t produced = backend.producer_ordinal;
  const uint32_t retained_faults =
      backend.fault_latched ? backend.fault_flags : 0u;
  for (uint32_t index = 0u; index < result.count; ++index) {
    OtisPpsHardwareSnapshot record = result.records[index];
    record.status |= retained_faults;
    snapshot_ring[produced & kSnapshotRingMask] = record;
    __dmb();
    produced++;
    backend.producer_ordinal = produced;
    backend.last_service_ticks = record.service_ticks;
  }
  if (result.timestamp_ambiguous) {
    add_saturating(&backend.timestamp_ambiguous_count, result.count);
  }
  const uint32_t depth = produced - backend.consumer_ordinal;
  if (depth > backend.backlog_high_water) {
    backend.backlog_high_water = depth;
  }
}

void service_fifo(uint32_t word_budget) {
  HardwareFifoPort port;
  const uint32_t depth =
      backend.producer_ordinal - backend.consumer_ordinal;
  const uint32_t ring_slots =
      depth < kSnapshotRingCapacity ? kSnapshotRingCapacity - depth : 0u;
  uint32_t next_sequence = backend.producer_ordinal;
  OtisPpsFifoDrainResult result = otis_pps_fifo_drain(
      port, backend.session, next_sequence, ring_slots, word_budget,
      backend.have_empty_lower_bound, backend.empty_lower_bound_ticks);

  // Preserve every word read before publishing the fault that stopped its
  // source. The helper has already stopped hardware without clearing FIFO.
  publish_drain_result(result);
  backend.words_since_poll += result.count;
  if (result.empty_after && result.faults == 0u) {
    backend.have_empty_lower_bound = true;
    backend.empty_lower_bound_ticks = result.empty_observation_ticks;
  }
  latch_faults(result.faults);
}

void otis_pps_snapshot_fifo_irq_handler() {
  if (!backend.initialized || backend.sm < 0) return;

  HardwareFifoPort port;
  // This shared handler owns only this SM's enabled RX-not-empty source.
  // A different PIO source may share IRQ 1 while our FIFO is nonempty but
  // deliberately gated between foreground service boundaries.
  const uint32_t source_mask = 1u << static_cast<uint32_t>(rx_source());
  if ((backend.pio->ints1 & source_mask) == 0u || port.empty()) return;

  // One non-empty invocation is admitted per foreground poll. Keeping this
  // source disabled until poll bounds both repeated singleton IRQs and words.
  set_source_enabled(false);
  if (!backend.running || backend.fault_latched) return;

  if (backend.irq_entries_since_poll != 0u ||
      backend.words_since_poll >= kFifoWordsPerForegroundService) {
    latch_faults(OTIS_PPS_SNAPSHOT_STATUS_IRQ_BUDGET_EXHAUSTED);
    return;
  }
  backend.irq_entries_since_poll = 1u;
  service_fifo(kFifoWordsPerForegroundService - backend.words_since_poll);
}

void initialise_state_machine_session() {
  const uint sm = sm_index();
  pio_sm_clear_fifos(backend.pio, sm);
  pio_sm_restart(backend.pio, sm);
  pio_sm_clkdiv_restart(backend.pio, sm);
  backend.pio->fdebug = 1u << (PIO_FDEBUG_RXSTALL_LSB + sm);

  // X initialisation and the start PC are session setup only. The first PIO
  // snapshot is an anchor and no interval crosses this CPU-owned setup point.
  pio_sm_exec(backend.pio, sm, pio_encode_mov(pio_x, pio_null));
  pio_sm_exec(
      backend.pio, sm,
      pio_encode_jmp(static_cast<uint>(backend.program_offset) +
                     otis_pps_snapshot_initial_pc));

  backend.producer_ordinal = 0u;
  backend.consumer_ordinal = 0u;
  backend.backlog_high_water = 0u;
  backend.fault_latched = false;
  backend.fault_reported = false;
  backend.fault_flags = OTIS_PPS_SNAPSHOT_STATUS_NONE;
  // The disabled SM and just-cleared FIFO establish a real empty
  // observation. Sample its lower-bound coordinate before enabling the SM so
  // a word committed before the first foreground poll remains bounded.
  backend.have_empty_lower_bound = true;
  backend.empty_lower_bound_ticks = time_us_64();
  backend.irq_entries_since_poll = 0u;
  backend.words_since_poll = 0u;
  backend.last_service_ticks = 0u;
  backend.running = true;
  pio_sm_set_enabled(backend.pio, sm, true);
  // poll() grants the first IRQ credit; it need not invent the first bound.
}

}  // namespace

bool otis_pps_snapshot_backend_begin(void) {
  if (backend.initialized || get_core_num() != 1u) return false;

  backend.system_clock_hz = clock_get_hz(clk_sys);
  if (backend.system_clock_hz != kRequiredSystemClockHz) return false;

  backend.pio = pio0;
  if (!pio_can_add_program(backend.pio, &otis_pps_snapshot_program)) {
    return false;
  }
  backend.sm = pio_claim_unused_sm(backend.pio, false);
  if (backend.sm < 0) return false;

  backend.program_offset =
      static_cast<int>(pio_add_program(backend.pio, &otis_pps_snapshot_program));
  const bool ownership_bound =
      otis_resource_registry_bind_pio_state_machine(
          OTIS_OWNER_COUNT_OBSERVATION, 0u,
          static_cast<uint8_t>(backend.sm)) &&
      otis_resource_registry_bind_pio_program(
          OTIS_OWNER_COUNT_OBSERVATION, 0u,
          static_cast<uint8_t>(backend.program_offset),
          static_cast<uint8_t>(otis_pps_snapshot_program.length)) &&
      otis_resource_registry_bind_pio_irq_source(
          OTIS_OWNER_COUNT_OBSERVATION, 0u,
          static_cast<uint8_t>(kPioIrqIndex),
          static_cast<uint8_t>(rx_source()));
  if (!ownership_bound) {
    pio_remove_program(backend.pio, &otis_pps_snapshot_program,
                       static_cast<uint>(backend.program_offset));
    pio_sm_unclaim(backend.pio, static_cast<uint>(backend.sm));
    backend.sm = -1;
    backend.program_offset = -1;
    return false;
  }

  pio_gpio_init(backend.pio, OTIS_GPIO_OSC_OBSERVATION);
  pio_gpio_init(backend.pio, OTIS_PIN_PPS_REFERENCE);
  pio_set_input_sync_bypass_with_mask(
      backend.pio, 0u,
      (1u << OTIS_GPIO_OSC_OBSERVATION) |
          (1u << OTIS_PIN_PPS_REFERENCE));
  gpio_set_dir(OTIS_GPIO_OSC_OBSERVATION, false);
  gpio_set_dir(OTIS_PIN_PPS_REFERENCE, false);
  gpio_pull_down(OTIS_GPIO_OSC_OBSERVATION);

  pio_sm_config config = otis_pps_snapshot_program_get_default_config(
      static_cast<uint>(backend.program_offset));
  sm_config_set_in_pins(&config, OTIS_GPIO_OSC_OBSERVATION);
  sm_config_set_jmp_pin(&config, OTIS_PIN_PPS_REFERENCE);
  sm_config_set_in_shift(&config, true, true, 32u);
  sm_config_set_fifo_join(&config, PIO_FIFO_JOIN_RX);
  sm_config_set_clkdiv(&config, 1.0f);
  pio_sm_init(
      backend.pio, static_cast<uint>(backend.sm),
      static_cast<uint>(backend.program_offset) + otis_pps_snapshot_initial_pc,
      &config);

  backend.irq_number = pio_get_irq_num(backend.pio, kPioIrqIndex);
  if (irq_get_exclusive_handler(static_cast<uint>(backend.irq_number)) !=
      nullptr) {
    pio_remove_program(backend.pio, &otis_pps_snapshot_program,
                       static_cast<uint>(backend.program_offset));
    pio_sm_unclaim(backend.pio, static_cast<uint>(backend.sm));
    backend.sm = -1;
    backend.program_offset = -1;
    backend.irq_number = -1;
    return false;
  }
  irq_add_shared_handler(static_cast<uint>(backend.irq_number),
                         otis_pps_snapshot_fifo_irq_handler,
                         PICO_SHARED_IRQ_HANDLER_DEFAULT_ORDER_PRIORITY);
  irq_set_enabled(static_cast<uint>(backend.irq_number), true);

  backend.initialized = true;
  backend.session = 1u;
  set_source_enabled(false);
  initialise_state_machine_session();
  return true;
}

void otis_pps_snapshot_backend_poll(void) {
  if (!backend.initialized || get_core_num() != 1u) return;

  const uint32_t interrupt_state = save_and_disable_interrupts();
  set_source_enabled(false);
  backend.irq_entries_since_poll = 0u;
  backend.words_since_poll = 0u;

  if (backend.fault_latched) {
    // A fault freezes the producer, but poll may move its already-committed
    // FIFO words into newly available ring slots. It never clears or rearms.
    if (!pio_sm_is_rx_fifo_empty(backend.pio, sm_index())) {
      service_fifo(kFifoWordsPerForegroundService);
    }
    restore_interrupts(interrupt_state);
    return;
  }

  if (rxstall_latched()) {
    service_fifo(kFifoWordsPerForegroundService);
    restore_interrupts(interrupt_state);
    return;
  }

  // Sample before observing empty so a racing push cannot move the retained
  // lower bound past an unread word.
  const uint64_t empty_candidate = time_us_64();
  if (pio_sm_is_rx_fifo_empty(backend.pio, sm_index())) {
    backend.have_empty_lower_bound = true;
    backend.empty_lower_bound_ticks = empty_candidate;
  }
  if (backend.running) set_source_enabled(true);
  restore_interrupts(interrupt_state);
}

bool otis_pps_snapshot_backend_pop(OtisPpsHardwareSnapshot *snapshot) {
  if (snapshot == nullptr || !backend.initialized ||
      get_core_num() != 1u) {
    return false;
  }

  const uint32_t interrupt_state = save_and_disable_interrupts();
  const uint32_t consumed = backend.consumer_ordinal;
  if (consumed == backend.producer_ordinal) {
    restore_interrupts(interrupt_state);
    return false;
  }
  __dmb();
  *snapshot = snapshot_ring[consumed & kSnapshotRingMask];
  __dmb();
  backend.consumer_ordinal = consumed + 1u;
  restore_interrupts(interrupt_state);
  return true;
}

bool otis_pps_snapshot_backend_rearm(void) {
  if (!backend.initialized || get_core_num() != 1u) return false;

  set_source_enabled(false);
  pio_sm_set_enabled(backend.pio, sm_index(), false);
  const uint32_t interrupt_state = save_and_disable_interrupts();
  backend.running = false;

  const bool evidence_drained =
      backend.producer_ordinal == backend.consumer_ordinal &&
      pio_sm_is_rx_fifo_empty(backend.pio, sm_index());
  if (!evidence_drained || backend.session == UINT32_MAX ||
      (backend.fault_latched && !backend.fault_reported)) {
    restore_interrupts(interrupt_state);
    return false;
  }

  backend.session = backend.session + 1u;
  initialise_state_machine_session();
  restore_interrupts(interrupt_state);
  return true;
}

void otis_pps_snapshot_backend_get_stats(OtisPpsSnapshotBackendStats *out) {
  if (out == nullptr) return;
  if (!backend.initialized || get_core_num() != 1u) {
    *out = {};
    return;
  }

  const uint32_t interrupt_state = save_and_disable_interrupts();
  // Stats are non-consuming, but they are also an authority freshness
  // boundary: sample the sticky hardware fault before copying state.
  if (rxstall_latched()) {
    latch_faults(OTIS_PPS_SNAPSHOT_STATUS_PIO_RXSTALL);
  }
  uint32_t depth =
      backend.producer_ordinal - backend.consumer_ordinal;
  if (depth > kSnapshotRingCapacity) depth = kSnapshotRingCapacity;
  *out = {
      backend.initialized,
      backend.running,
      backend.fault_latched,
      backend.session,
      backend.producer_ordinal,
      backend.consumer_ordinal,
      depth,
      backend.backlog_high_water,
      backend.continuity_loss_count,
      backend.pio_rxstall_count,
      backend.irq_budget_exhausted_count,
      backend.ring_full_count,
      backend.timestamp_ambiguous_count,
      backend.fault_flags,
      backend.last_service_ticks,
      backend.system_clock_hz,
      0u,
      static_cast<uint8_t>(backend.sm < 0 ? 0xff : backend.sm),
      static_cast<uint8_t>(backend.program_offset < 0 ? 0xff
                                                     : backend.program_offset),
      static_cast<uint8_t>(otis_pps_snapshot_program.length),
      static_cast<uint16_t>(kSnapshotRingCapacity),
  };
  if (backend.fault_latched) backend.fault_reported = true;
  restore_interrupts(interrupt_state);
}
