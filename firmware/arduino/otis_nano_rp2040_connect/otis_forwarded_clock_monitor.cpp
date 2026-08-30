#include "otis_forwarded_clock_monitor.h"

#include <hardware/clocks.h>
#include <hardware/gpio.h>
#include <hardware/pio.h>

#include "otis_board.h"
#include "otis_config.h"
#include "otis_pps_snapshot.pio.h"
#include "otis_resource_registry.h"

namespace {

constexpr uint32_t kRequiredSystemClockHz = 133000000u;

struct MonitorState {
  PIO pio;
  int sm;
  int program_offset;
  bool selected;
  bool configured;
  bool running;
  bool fault_latched;
  bool read_pending;
  uint32_t session;
  uint32_t next_sequence;
  uint32_t reference_service_count;
  uint32_t snapshot_count;
  uint32_t no_snapshot_count;
  uint32_t fifo_backlog_count;
  uint32_t pio_rxstall_count;
  uint32_t fault_flags;
  uint32_t last_status;
  uint32_t system_clock_hz;
  OtisForwardedClockMonitorSnapshot pending_snapshot;
};

MonitorState monitor = {
    pio0, -1, -1, false, false, false, false, false, 0u, 0u, 0u,
    0u,   0u, 0u, 0u,    0u,    OTIS_FORWARDED_CLOCK_MONITOR_STATUS_DISABLED_PROFILE,
    0u,   {},
};

void increment_saturating(uint32_t *counter) {
  if (*counter != UINT32_MAX) {
    *counter += 1u;
  }
}

void stop_local_monitor(void) {
  if (monitor.sm >= 0) {
    pio_sm_set_enabled(monitor.pio, static_cast<uint>(monitor.sm), false);
  }
  monitor.running = false;
}

void latch_local_fault(uint32_t flag) {
  monitor.fault_flags |= flag;
  monitor.last_status = flag;
  if (!monitor.fault_latched) {
    monitor.fault_latched = true;
    stop_local_monitor();
  }
}

void cleanup_unbound_hardware(void) {
  if (monitor.program_offset >= 0) {
    pio_remove_program(monitor.pio, &otis_pps_snapshot_program,
                       static_cast<uint>(monitor.program_offset));
    monitor.program_offset = -1;
  }
  if (monitor.sm >= 0) {
    pio_sm_unclaim(monitor.pio, static_cast<uint>(monitor.sm));
    monitor.sm = -1;
  }
}

}  // namespace

bool otis_forwarded_clock_monitor_begin(void) {
#if !OTIS_ENABLE_FORWARDED_D6_MONITOR
  monitor.last_status = OTIS_FORWARDED_CLOCK_MONITOR_STATUS_DISABLED_PROFILE;
  return false;
#else
  if (monitor.selected || monitor.configured) {
    return false;
  }

  monitor.selected = true;
  monitor.system_clock_hz = clock_get_hz(clk_sys);
  if (monitor.system_clock_hz != kRequiredSystemClockHz) {
    latch_local_fault(OTIS_FORWARDED_CLOCK_MONITOR_STATUS_SYSTEM_CLOCK_MISMATCH);
    return false;
  }

  monitor.pio = pio0;
  if (!pio_can_add_program(monitor.pio, &otis_pps_snapshot_program)) {
    latch_local_fault(OTIS_FORWARDED_CLOCK_MONITOR_STATUS_RESOURCE_BINDING_FAILED);
    return false;
  }
  monitor.sm = pio_claim_unused_sm(monitor.pio, false);
  if (monitor.sm < 0) {
    latch_local_fault(OTIS_FORWARDED_CLOCK_MONITOR_STATUS_RESOURCE_BINDING_FAILED);
    return false;
  }
  monitor.program_offset =
      static_cast<int>(pio_add_program(monitor.pio, &otis_pps_snapshot_program));

  const bool ownership_bound =
      otis_resource_registry_bind_pio_state_machine(
          OTIS_OWNER_FORWARDED_CLOCK_MONITOR, 0u,
          static_cast<uint8_t>(monitor.sm)) &&
      otis_resource_registry_bind_pio_program(
          OTIS_OWNER_FORWARDED_CLOCK_MONITOR, 0u,
          static_cast<uint8_t>(monitor.program_offset),
          static_cast<uint8_t>(otis_pps_snapshot_program.length));
  if (!ownership_bound) {
    cleanup_unbound_hardware();
    latch_local_fault(OTIS_FORWARDED_CLOCK_MONITOR_STATUS_RESOURCE_BINDING_FAILED);
    return false;
  }

  // D6 is input-only.  D14 is a read-only PIO JMP condition shared with the
  // authoritative D8 backend; no GPIO interrupt, pull, or output mode is
  // changed here for either authoritative pin.
  pio_gpio_init(monitor.pio, OTIS_GPIO_FORWARDED_CLOCK_MONITOR);
  gpio_set_dir(OTIS_GPIO_FORWARDED_CLOCK_MONITOR, false);
  gpio_disable_pulls(OTIS_GPIO_FORWARDED_CLOCK_MONITOR);

  pio_sm_config config = otis_pps_snapshot_program_get_default_config(
      static_cast<uint>(monitor.program_offset));
  sm_config_set_in_pins(&config, OTIS_GPIO_FORWARDED_CLOCK_MONITOR);
  sm_config_set_jmp_pin(&config, OTIS_PIN_PPS_REFERENCE);
  sm_config_set_in_shift(&config, true, true, 32u);
  sm_config_set_fifo_join(&config, PIO_FIFO_JOIN_RX);
  sm_config_set_clkdiv(&config, 1.0f);
  pio_sm_init(
      monitor.pio, static_cast<uint>(monitor.sm),
      static_cast<uint>(monitor.program_offset) + otis_pps_snapshot_initial_pc,
      &config);
  pio_sm_clear_fifos(monitor.pio, static_cast<uint>(monitor.sm));
  pio_sm_restart(monitor.pio, static_cast<uint>(monitor.sm));
  pio_sm_clkdiv_restart(monitor.pio, static_cast<uint>(monitor.sm));
  pio_sm_exec(monitor.pio, static_cast<uint>(monitor.sm),
              pio_encode_mov(pio_x, pio_null));
  pio_sm_exec(monitor.pio, static_cast<uint>(monitor.sm),
              pio_encode_jmp(static_cast<uint>(monitor.program_offset) +
                             otis_pps_snapshot_initial_pc));
  monitor.pio->fdebug = 1u << static_cast<uint>(monitor.sm);

  monitor.configured = true;
  monitor.running = true;
  monitor.fault_latched = false;
  monitor.read_pending = false;
  monitor.session = 1u;
  monitor.next_sequence = 0u;
  monitor.reference_service_count = 0u;
  monitor.snapshot_count = 0u;
  monitor.no_snapshot_count = 0u;
  monitor.fifo_backlog_count = 0u;
  monitor.pio_rxstall_count = 0u;
  monitor.fault_flags = OTIS_FORWARDED_CLOCK_MONITOR_STATUS_NONE;
  monitor.last_status = OTIS_FORWARDED_CLOCK_MONITOR_STATUS_NONE;
  pio_sm_set_enabled(monitor.pio, static_cast<uint>(monitor.sm), true);
  return true;
#endif
}

void otis_forwarded_clock_monitor_poll(void) {
#if OTIS_ENABLE_FORWARDED_D6_MONITOR
  if (!monitor.configured || !monitor.running || monitor.sm < 0) {
    return;
  }
  const uint sm = static_cast<uint>(monitor.sm);
  if (((monitor.pio->fdebug >> sm) & 1u) != 0u) {
    increment_saturating(&monitor.pio_rxstall_count);
    latch_local_fault(OTIS_FORWARDED_CLOCK_MONITOR_STATUS_PIO_RXSTALL);
  }
#endif
}

bool otis_forwarded_clock_monitor_service(uint32_t reference_session,
                                          uint32_t reference_sequence) {
#if !OTIS_ENABLE_FORWARDED_D6_MONITOR
  (void)reference_session;
  (void)reference_sequence;
  monitor.last_status = OTIS_FORWARDED_CLOCK_MONITOR_STATUS_DISABLED_PROFILE;
  return false;
#else
  otis_forwarded_clock_monitor_poll();
  if (!monitor.configured || !monitor.running || monitor.fault_latched) {
    return false;
  }

  increment_saturating(&monitor.reference_service_count);
  // Do not overwrite an unconsumed raw snapshot.  This is a local consumer
  // fault: stop only the sidecar and leave the previously captured evidence
  // readable.  It cannot delay or alter the D14/D8 association path.
  if (monitor.read_pending) {
    latch_local_fault(OTIS_FORWARDED_CLOCK_MONITOR_STATUS_READ_PENDING);
    return false;
  }
  const uint sm = static_cast<uint>(monitor.sm);
  const uint32_t before = pio_sm_get_rx_fifo_level(monitor.pio, sm);
  if (before == 0u) {
    increment_saturating(&monitor.no_snapshot_count);
    monitor.last_status = OTIS_FORWARDED_CLOCK_MONITOR_STATUS_NO_SNAPSHOT;
    return false;
  }

  // Exactly one PIO FIFO word may be read per associated D14 boundary.
  // A second pending word is retained as explicit local evidence and turns the
  // sidecar off; it never consumes or delays authoritative capture.
  const uint32_t cumulative_down_counter = pio_sm_get(monitor.pio, sm);
  uint32_t status = OTIS_FORWARDED_CLOCK_MONITOR_STATUS_NONE;
  if (before > 1u || pio_sm_get_rx_fifo_level(monitor.pio, sm) != 0u) {
    increment_saturating(&monitor.fifo_backlog_count);
    status |= OTIS_FORWARDED_CLOCK_MONITOR_STATUS_FIFO_BACKLOG;
  }

  monitor.pending_snapshot = {
      monitor.session,
      monitor.next_sequence++,
      cumulative_down_counter,
      reference_session,
      reference_sequence,
      status,
  };
  monitor.read_pending = true;
  increment_saturating(&monitor.snapshot_count);
  monitor.last_status = status;

  if ((status & OTIS_FORWARDED_CLOCK_MONITOR_STATUS_FIFO_BACKLOG) != 0u) {
    latch_local_fault(OTIS_FORWARDED_CLOCK_MONITOR_STATUS_FIFO_BACKLOG);
  }
  return true;
#endif
}

bool otis_forwarded_clock_monitor_read(OtisForwardedClockMonitorSnapshot *out) {
  if (out == nullptr || !monitor.read_pending) {
    return false;
  }
  *out = monitor.pending_snapshot;
  monitor.read_pending = false;
  return true;
}

void otis_forwarded_clock_monitor_get_stats(OtisForwardedClockMonitorStats *out) {
  if (out == nullptr) {
    return;
  }
  otis_forwarded_clock_monitor_poll();
  *out = {
      monitor.selected,
      monitor.configured,
      monitor.running,
      monitor.fault_latched,
      monitor.read_pending,
      monitor.session,
      monitor.reference_service_count,
      monitor.snapshot_count,
      monitor.no_snapshot_count,
      monitor.fifo_backlog_count,
      monitor.pio_rxstall_count,
      monitor.fault_flags,
      monitor.last_status,
      monitor.system_clock_hz,
      0u,
      static_cast<uint8_t>(monitor.sm < 0 ? 0xff : monitor.sm),
      static_cast<uint8_t>(monitor.program_offset < 0 ? 0xff
                                                      : monitor.program_offset),
      static_cast<uint8_t>(otis_pps_snapshot_program.length),
      static_cast<uint8_t>(OTIS_GPIO_FORWARDED_CLOCK_MONITOR),
      static_cast<uint8_t>(OTIS_PIN_PPS_REFERENCE),
  };
}
