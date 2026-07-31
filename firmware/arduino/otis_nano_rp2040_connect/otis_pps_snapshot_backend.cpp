#include "otis_pps_snapshot_backend.h"

#include <hardware/clocks.h>
#include <hardware/dma.h>
#include <hardware/gpio.h>
#include <hardware/pio.h>
#include <hardware/regs/dma.h>
#include <hardware/sync.h>

#include "otis_board.h"
#include "otis_config.h"
#include "otis_pps_snapshot.pio.h"
#include "otis_resource_registry.h"

namespace {

constexpr uint32_t kRequiredSystemClockHz = 133000000u;
constexpr uint32_t kDmaInitialTransferCount = UINT32_MAX;
constexpr uint32_t kSnapshotRingCapacity = 128u;
constexpr uint32_t kSnapshotRingMask = kSnapshotRingCapacity - 1u;
constexpr uint8_t kSnapshotRingAddressBits = 9u;  // 128 x uint32_t = 512 B.
static_assert((kSnapshotRingCapacity & kSnapshotRingMask) == 0u,
              "snapshot ring capacity must be a power of two");

alignas(512) volatile uint32_t snapshot_ring[kSnapshotRingCapacity] = {};

struct BackendState {
  PIO pio;
  int sm;
  int program_offset;
  int dma_channel;
  bool initialized;
  bool running;
  bool fault_latched;
  bool overwrite_pending;
  uint32_t session;
  uint32_t consumer_ordinal;
  uint32_t backlog_high_water;
  uint32_t overwrite_count;
  uint32_t continuity_loss_count;
  uint32_t pio_rxstall_count;
  uint32_t dma_error_count;
  uint32_t dma_stopped_count;
  uint32_t fault_flags;
  uint32_t system_clock_hz;
};

BackendState backend = {
    pio0, -1, -1, -1, false, false, false, false, 0u, 0u, 0u,
    0u,   0u, 0u, 0u,  0u,    0u,
};

void increment_saturating(uint32_t *counter) {
  if (*counter != UINT32_MAX) {
    *counter += 1u;
  }
}

void add_saturating(uint32_t *counter, uint32_t value) {
  if (UINT32_MAX - *counter < value) {
    *counter = UINT32_MAX;
  } else {
    *counter += value;
  }
}

uint32_t stable_dma_transfer_count(void) {
  if (backend.dma_channel < 0) {
    return kDmaInitialTransferCount;
  }
  dma_channel_hw_t *channel =
      dma_channel_hw_addr(static_cast<uint>(backend.dma_channel));
  uint32_t second = channel->transfer_count;
  for (uint8_t attempt = 0u; attempt < 4u; ++attempt) {
    uint32_t first = second;
    __dmb();
    second = channel->transfer_count;
    if (first == second) {
      __dmb();
      return second;
    }
  }
  __dmb();
  return second;
}

uint32_t producer_ordinal(void) {
  return kDmaInitialTransferCount - stable_dma_transfer_count();
}

void stop_transport(void) {
  if (backend.sm >= 0) {
    pio_sm_set_enabled(backend.pio, static_cast<uint>(backend.sm), false);
  }
  if (backend.dma_channel >= 0) {
    dma_channel_abort(static_cast<uint>(backend.dma_channel));
  }
  backend.running = false;
}

void latch_fatal_fault(uint32_t flag) {
  backend.fault_flags |= flag;
  if (backend.fault_latched) {
    return;
  }
  backend.fault_latched = true;
  increment_saturating(&backend.continuity_loss_count);
  stop_transport();
}

bool configure_session(void) {
  if (backend.sm < 0 || backend.program_offset < 0 ||
      backend.dma_channel < 0) {
    return false;
  }

  uint sm = static_cast<uint>(backend.sm);
  uint dma_channel = static_cast<uint>(backend.dma_channel);
  pio_sm_set_enabled(backend.pio, sm, false);
  dma_channel_abort(dma_channel);
  pio_sm_clear_fifos(backend.pio, sm);
  pio_sm_restart(backend.pio, sm);
  pio_sm_clkdiv_restart(backend.pio, sm);
  backend.pio->fdebug = 1u << sm;  // Clear this SM's sticky RXSTALL flag.

  for (uint32_t index = 0u; index < kSnapshotRingCapacity; ++index) {
    snapshot_ring[index] = 0u;
  }
  __dmb();

  dma_channel_config dma_config = dma_channel_get_default_config(dma_channel);
  channel_config_set_transfer_data_size(&dma_config, DMA_SIZE_32);
  channel_config_set_read_increment(&dma_config, false);
  channel_config_set_write_increment(&dma_config, true);
  channel_config_set_ring(&dma_config, true, kSnapshotRingAddressBits);
  channel_config_set_dreq(
      &dma_config, pio_get_dreq(backend.pio, sm, false));
  channel_config_set_high_priority(&dma_config, true);
  dma_channel_configure(dma_channel, &dma_config,
                        const_cast<uint32_t *>(snapshot_ring),
                        &backend.pio->rxf[sm], kDmaInitialTransferCount, true);

  // X initialisation and the start PC are session setup only.  The first PIO
  // snapshot is an anchor and no interval crosses this CPU-owned setup point.
  pio_sm_exec(backend.pio, sm, pio_encode_mov(pio_x, pio_null));
  pio_sm_exec(
      backend.pio, sm,
      pio_encode_jmp(static_cast<uint>(backend.program_offset) +
                     otis_pps_snapshot_initial_pc));

  backend.consumer_ordinal = 0u;
  backend.backlog_high_water = 0u;
  backend.overwrite_pending = false;
  backend.fault_latched = false;
  backend.fault_flags = OTIS_PPS_SNAPSHOT_STATUS_NONE;
  backend.running = true;
  pio_sm_set_enabled(backend.pio, sm, true);
  return true;
}

}  // namespace

bool otis_pps_snapshot_backend_begin(void) {
  if (backend.initialized) {
    return false;
  }
  backend.system_clock_hz = clock_get_hz(clk_sys);
  if (backend.system_clock_hz != kRequiredSystemClockHz) {
    return false;
  }

  backend.pio = pio0;
  if (!pio_can_add_program(backend.pio, &otis_pps_snapshot_program)) {
    return false;
  }
  backend.sm = pio_claim_unused_sm(backend.pio, false);
  if (backend.sm < 0) {
    return false;
  }
  backend.program_offset =
      static_cast<int>(pio_add_program(backend.pio, &otis_pps_snapshot_program));
  backend.dma_channel = dma_claim_unused_channel(false);
  if (backend.dma_channel < 0) {
    pio_remove_program(backend.pio, &otis_pps_snapshot_program,
                       static_cast<uint>(backend.program_offset));
    pio_sm_unclaim(backend.pio, static_cast<uint>(backend.sm));
    backend.sm = -1;
    backend.program_offset = -1;
    return false;
  }

  bool ownership_bound =
      otis_resource_registry_bind_pio_state_machine(
          OTIS_OWNER_COUNT_OBSERVATION, 0u,
          static_cast<uint8_t>(backend.sm)) &&
      otis_resource_registry_bind_pio_program(
          OTIS_OWNER_COUNT_OBSERVATION, 0u,
          static_cast<uint8_t>(backend.program_offset),
          static_cast<uint8_t>(otis_pps_snapshot_program.length)) &&
      otis_resource_registry_bind_dma_channel(
          OTIS_OWNER_COUNT_OBSERVATION,
          static_cast<uint8_t>(backend.dma_channel));
  if (!ownership_bound) {
    stop_transport();
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

  backend.initialized = true;
  backend.session = 1u;
  return configure_session();
}

void otis_pps_snapshot_backend_poll(void) {
  if (!backend.initialized || !backend.running) {
    return;
  }
  uint sm = static_cast<uint>(backend.sm);
  uint32_t rxstall = (backend.pio->fdebug >> sm) & 1u;
  if (rxstall != 0u) {
    increment_saturating(&backend.pio_rxstall_count);
    latch_fatal_fault(OTIS_PPS_SNAPSHOT_STATUS_PIO_RXSTALL);
    return;
  }

  dma_channel_hw_t *channel =
      dma_channel_hw_addr(static_cast<uint>(backend.dma_channel));
  if ((channel->ctrl_trig & DMA_CH0_CTRL_TRIG_AHB_ERROR_BITS) != 0u) {
    increment_saturating(&backend.dma_error_count);
    latch_fatal_fault(OTIS_PPS_SNAPSHOT_STATUS_DMA_ERROR);
    return;
  }
  if (!dma_channel_is_busy(static_cast<uint>(backend.dma_channel))) {
    increment_saturating(&backend.dma_stopped_count);
    latch_fatal_fault(OTIS_PPS_SNAPSHOT_STATUS_DMA_STOPPED);
    return;
  }

  uint32_t produced = producer_ordinal();
  uint32_t depth = produced - backend.consumer_ordinal;
  if (depth > backend.backlog_high_water) {
    backend.backlog_high_water = depth;
  }
  if (depth > kSnapshotRingCapacity) {
    add_saturating(&backend.overwrite_count,
                   depth - kSnapshotRingCapacity);
    increment_saturating(&backend.continuity_loss_count);
    backend.consumer_ordinal = produced;
    backend.overwrite_pending = true;
  }
}

bool otis_pps_snapshot_backend_pop(OtisPpsHardwareSnapshot *snapshot) {
  if (snapshot == nullptr || !backend.initialized) {
    return false;
  }
  otis_pps_snapshot_backend_poll();
  if (!backend.running || backend.fault_latched) {
    return false;
  }

  uint32_t produced = producer_ordinal();
  uint32_t depth = produced - backend.consumer_ordinal;
  if (depth == 0u || depth > kSnapshotRingCapacity) {
    return false;
  }

  uint32_t sequence = backend.consumer_ordinal;
  uint32_t index = sequence & kSnapshotRingMask;
  __dmb();
  uint32_t cumulative_down_counter = snapshot_ring[index];
  __dmb();
  backend.consumer_ordinal++;

  uint32_t status = OTIS_PPS_SNAPSHOT_STATUS_NONE;
  if (backend.overwrite_pending) {
    status |= OTIS_PPS_SNAPSHOT_STATUS_OVERWRITE_BEFORE;
    backend.overwrite_pending = false;
  }
  *snapshot = {
      backend.session,
      sequence,
      cumulative_down_counter,
      status,
  };
  return true;
}

bool otis_pps_snapshot_backend_rearm(void) {
  if (!backend.initialized) {
    return false;
  }
  stop_transport();
  backend.session++;
  return configure_session();
}

void otis_pps_snapshot_backend_get_stats(OtisPpsSnapshotBackendStats *out) {
  if (out == nullptr) {
    return;
  }
  otis_pps_snapshot_backend_poll();
  uint32_t produced = backend.initialized ? producer_ordinal() : 0u;
  uint32_t depth = produced - backend.consumer_ordinal;
  if (depth > kSnapshotRingCapacity) {
    depth = kSnapshotRingCapacity;
  }
  *out = {
      backend.initialized,
      backend.running,
      backend.fault_latched,
      backend.session,
      produced,
      backend.consumer_ordinal,
      depth,
      backend.backlog_high_water,
      backend.overwrite_count,
      backend.continuity_loss_count,
      backend.pio_rxstall_count,
      backend.dma_error_count,
      backend.dma_stopped_count,
      backend.fault_flags,
      backend.system_clock_hz,
      0u,
      static_cast<uint8_t>(backend.sm < 0 ? 0xff : backend.sm),
      static_cast<uint8_t>(backend.program_offset < 0 ? 0xff
                                                     : backend.program_offset),
      static_cast<uint8_t>(otis_pps_snapshot_program.length),
      static_cast<uint8_t>(backend.dma_channel < 0 ? 0xff
                                                  : backend.dma_channel),
      static_cast<uint16_t>(kSnapshotRingCapacity),
  };
}
