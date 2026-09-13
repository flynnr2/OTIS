from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def _compiler() -> str:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is not available")
    return compiler


def _write_stubs(root: Path) -> None:
    (root / "hardware/regs").mkdir(parents=True)
    (root / "Arduino.h").write_text(
        """
#pragma once
#include <stdint.h>
#define D10 5
#define D14 26
#define D8 20
#define D9 21
#define D6 18
#define PIN_SERIAL1_RX 1
#define PIN_SERIAL1_TX 0
""",
        encoding="utf-8",
    )
    (root / "hardware/clocks.h").write_text(
        """
#pragma once
#include <stdint.h>
using uint = unsigned int;
constexpr int clk_sys = 0;
extern uint32_t mock_system_clock_hz;
inline uint32_t clock_get_hz(int) { return mock_system_clock_hz; }
""",
        encoding="utf-8",
    )
    (root / "hardware/regs/dma.h").write_text(
        """
#pragma once
#include <stdint.h>
#define DMA_CH0_CTRL_TRIG_AHB_ERROR_BITS (1u << 0)
""",
        encoding="utf-8",
    )
    (root / "hardware/sync.h").write_text(
        """
#pragma once
inline void __dmb() {}
""",
        encoding="utf-8",
    )
    (root / "hardware/gpio.h").write_text(
        """
#pragma once
using uint = unsigned int;
inline void gpio_set_dir(uint, bool) {}
inline void gpio_pull_down(uint) {}
""",
        encoding="utf-8",
    )
    (root / "hardware/pio.h").write_text(
        """
#pragma once
#include <stdint.h>
using uint = unsigned int;
struct pio_hw_t { uint32_t fdebug; uint32_t rxf[4]; };
using PIO = pio_hw_t *;
extern pio_hw_t mock_pio;
#define pio0 (&mock_pio)
struct pio_program {
  const uint16_t *instructions;
  uint8_t length;
  int8_t origin;
  uint8_t pio_version;
  uint8_t used_gpio_ranges;
};
struct pio_sm_config {};
constexpr int pio_x = 1;
constexpr int pio_null = 2;
extern uint32_t mock_event_clock;
extern uint32_t mock_pio_disable_order;
extern uint32_t mock_pio_fifo_depth;
inline bool pio_can_add_program(PIO, const pio_program *) { return true; }
inline int pio_claim_unused_sm(PIO, bool) { return 0; }
inline uint pio_add_program(PIO, const pio_program *) { return 0; }
inline void pio_remove_program(PIO, const pio_program *, uint) {}
inline void pio_sm_unclaim(PIO, uint) {}
inline void pio_gpio_init(PIO, uint) {}
inline void pio_set_input_sync_bypass_with_mask(PIO, uint32_t, uint32_t) {}
inline pio_sm_config pio_get_default_sm_config() { return {}; }
inline void sm_config_set_wrap(pio_sm_config *, uint, uint) {}
inline void sm_config_set_in_pins(pio_sm_config *, uint) {}
inline void sm_config_set_jmp_pin(pio_sm_config *, uint) {}
inline void sm_config_set_in_shift(pio_sm_config *, bool, bool, uint) {}
inline void sm_config_set_fifo_join(pio_sm_config *, int) {}
inline void sm_config_set_clkdiv(pio_sm_config *, float) {}
constexpr int PIO_FIFO_JOIN_RX = 0;
inline void pio_sm_init(PIO, uint, uint, const pio_sm_config *) {}
inline void pio_sm_set_enabled(PIO, uint, bool enabled) {
  if (!enabled) mock_pio_disable_order = ++mock_event_clock;
}
inline void pio_sm_clear_fifos(PIO, uint) { mock_pio_fifo_depth = 0; }
inline void pio_sm_restart(PIO, uint) {}
inline void pio_sm_clkdiv_restart(PIO, uint) {}
inline void pio_sm_exec(PIO, uint, uint16_t) {}
inline uint16_t pio_encode_mov(int, int) { return 0; }
inline uint16_t pio_encode_jmp(uint) { return 0; }
inline uint pio_get_dreq(PIO, uint, bool) { return 0; }
inline uint pio_sm_get_rx_fifo_level(PIO, uint) { return mock_pio_fifo_depth; }
""",
        encoding="utf-8",
    )
    (root / "hardware/dma.h").write_text(
        """
#pragma once
#include <stdint.h>
#include <limits.h>
#include "hardware/regs/dma.h"
using uint = unsigned int;
struct dma_channel_hw_t { uint32_t transfer_count; uint32_t ctrl_trig; };
struct dma_channel_config {};
constexpr int DMA_SIZE_32 = 0;
extern dma_channel_hw_t mock_dma_channel;
extern bool mock_dma_busy;
extern bool mock_complete_on_abort;
extern bool mock_error_on_abort;
extern uint32_t mock_inflight_word;
extern volatile uint32_t *mock_dma_write_base;
extern uint32_t mock_event_clock;
extern uint32_t mock_dma_abort_order;
inline dma_channel_hw_t *dma_channel_hw_addr(uint) { return &mock_dma_channel; }
inline int dma_claim_unused_channel(bool) { return 0; }
inline dma_channel_config dma_channel_get_default_config(uint) { return {}; }
inline void channel_config_set_transfer_data_size(dma_channel_config *, int) {}
inline void channel_config_set_read_increment(dma_channel_config *, bool) {}
inline void channel_config_set_write_increment(dma_channel_config *, bool) {}
inline void channel_config_set_ring(dma_channel_config *, bool, uint) {}
inline void channel_config_set_dreq(dma_channel_config *, uint) {}
inline void channel_config_set_high_priority(dma_channel_config *, bool) {}
inline void dma_channel_configure(
    uint, const dma_channel_config *, volatile uint32_t *write_addr,
    volatile uint32_t *, uint32_t count, bool) {
  mock_dma_write_base = write_addr;
  mock_dma_channel.transfer_count = count;
  mock_dma_channel.ctrl_trig = 0;
  mock_dma_busy = true;
}
inline void dma_channel_abort(uint) {
  mock_dma_abort_order = ++mock_event_clock;
  if (mock_complete_on_abort) {
    const uint32_t ordinal = UINT32_MAX - mock_dma_channel.transfer_count;
    mock_dma_write_base[ordinal & 127u] = mock_inflight_word;
    --mock_dma_channel.transfer_count;
    mock_complete_on_abort = false;
  }
  if (mock_error_on_abort) {
    mock_dma_channel.ctrl_trig |= DMA_CH0_CTRL_TRIG_AHB_ERROR_BITS;
    mock_error_on_abort = false;
  }
  mock_dma_busy = false;
}
inline bool dma_channel_is_busy(uint) { return mock_dma_busy; }
""",
        encoding="utf-8",
    )


def test_freeze_preserves_only_unambiguous_committed_front_word(tmp_path: Path) -> None:
    stubs = tmp_path / "stubs"
    _write_stubs(stubs)
    source = tmp_path / "freeze_backend_harness.cpp"
    binary = tmp_path / "freeze_backend_harness"
    source.write_text(
        textwrap.dedent(
            f"""
            #include <assert.h>
            #include <stdint.h>
            #include "hardware/pio.h"
            #include "hardware/dma.h"

            uint32_t mock_system_clock_hz = 133000000u;
            pio_hw_t mock_pio = {{}};
            dma_channel_hw_t mock_dma_channel = {{}};
            bool mock_dma_busy = false;
            bool mock_complete_on_abort = false;
            bool mock_error_on_abort = false;
            uint32_t mock_inflight_word = 0u;
            volatile uint32_t *mock_dma_write_base = nullptr;
            uint32_t mock_event_clock = 0u;
            uint32_t mock_pio_disable_order = 0u;
            uint32_t mock_pio_fifo_depth = 0u;
            uint32_t mock_dma_abort_order = 0u;

            #include "{BACKEND / "otis_pps_snapshot_backend.cpp"}"

            bool otis_resource_registry_bind_pio_state_machine(
                const char *, uint8_t, uint8_t) {{ return true; }}
            bool otis_resource_registry_bind_pio_program(
                const char *, uint8_t, uint8_t, uint8_t) {{ return true; }}
            bool otis_resource_registry_bind_dma_channel(
                const char *, uint8_t) {{ return true; }}

            static void reset_stop_order() {{
              // Hardware FDEBUG is write-one-to-clear; model that side effect.
              mock_pio.fdebug = 0u;
              mock_event_clock = 0u;
              mock_pio_disable_order = 0u;
              mock_dma_abort_order = 0u;
            }}

            int main() {{
              OtisPpsSnapshotFrozenDiagnostic frozen = {{
                  true, 1u, 2u, 3u, 4u, 5u, true, 6u}};
              otis_pps_snapshot_backend_freeze_diagnostic(nullptr);
              otis_pps_snapshot_backend_freeze_diagnostic(&frozen);
              assert(!frozen.frozen && frozen.front_word == 0u);

              assert(otis_pps_snapshot_backend_begin());
              reset_stop_order();
              otis_pps_snapshot_backend_freeze_diagnostic(&frozen);
              assert(frozen.frozen && frozen.session == 1u);
              assert(frozen.producer_ordinal == 0u);
              assert(frozen.consumer_ordinal == 0u);
              assert(frozen.backlog_depth == 0u);
              assert(frozen.pio_fifo_depth == 0u);
              assert(!frozen.front_word_present && frozen.front_word == 0u);
              assert(mock_pio_disable_order < mock_dma_abort_order);
              OtisPpsSnapshotBackendStats stats = {{}};
              otis_pps_snapshot_backend_get_stats(&stats);
              assert(!stats.running && !stats.fault_latched);
              assert(stats.dma_stopped_count == 0u);

              assert(otis_pps_snapshot_backend_rearm());
              assert(mock_dma_busy);
              mock_pio_fifo_depth = 1u;
              mock_complete_on_abort = true;
              mock_inflight_word = 0u;
              reset_stop_order();
              otis_pps_snapshot_backend_freeze_diagnostic(&frozen);
              assert(frozen.session == 2u);
              assert(frozen.producer_ordinal == 1u);
              assert(frozen.consumer_ordinal == 0u);
              assert(frozen.backlog_depth == 1u);
              assert(frozen.pio_fifo_depth == 1u);
              assert(frozen.front_word_present);
              assert(frozen.front_word == 0u);
              assert(mock_pio_disable_order < mock_dma_abort_order);

              assert(otis_pps_snapshot_backend_rearm());
              mock_pio.fdebug = 0u;
              mock_dma_write_base[0] = 0x12345678u;
              mock_dma_channel.transfer_count = UINT32_MAX - 1u;
              mock_pio_fifo_depth = 2u;
              otis_pps_snapshot_backend_freeze_diagnostic(&frozen);
              assert(frozen.session == 3u && frozen.backlog_depth == 1u);
              assert(frozen.pio_fifo_depth == 2u);
              assert(frozen.front_word_present);
              assert(frozen.front_word == 0x12345678u);

              assert(otis_pps_snapshot_backend_rearm());
              mock_pio.fdebug = 0u;
              mock_dma_channel.transfer_count = UINT32_MAX - 129u;
              otis_pps_snapshot_backend_freeze_diagnostic(&frozen);
              assert(frozen.session == 4u && frozen.backlog_depth == 129u);
              assert(!frozen.front_word_present && frozen.front_word == 0u);

              assert(otis_pps_snapshot_backend_rearm());
              mock_pio.fdebug = 0u;
              mock_dma_write_base[0] = 0xabcdef01u;
              mock_dma_channel.transfer_count = UINT32_MAX - 1u;
              mock_error_on_abort = true;
              otis_pps_snapshot_backend_freeze_diagnostic(&frozen);
              assert(frozen.session == 5u && frozen.backlog_depth == 1u);
              assert(!frozen.front_word_present && frozen.front_word == 0u);
              otis_pps_snapshot_backend_get_stats(&stats);
              assert(!stats.fault_latched && stats.dma_error_count == 0u);

              assert(otis_pps_snapshot_backend_rearm());
              // Hardware FDEBUG is write-one-to-clear; model that side effect.
              mock_pio.fdebug = 0u;
              mock_dma_write_base[0] = 0x10203040u;
              mock_dma_channel.transfer_count = UINT32_MAX - 1u;
              mock_dma_channel.ctrl_trig = DMA_CH0_CTRL_TRIG_AHB_ERROR_BITS;
              otis_pps_snapshot_backend_poll();
              otis_pps_snapshot_backend_freeze_diagnostic(&frozen);
              assert(frozen.session == 6u && frozen.backlog_depth == 1u);
              assert(!frozen.front_word_present && frozen.front_word == 0u);
              otis_pps_snapshot_backend_get_stats(&stats);
              assert(stats.fault_latched && stats.dma_error_count == 1u);

              assert(otis_pps_snapshot_backend_rearm());
              mock_pio.fdebug = 0u;
              otis_pps_snapshot_backend_get_stats(&stats);
              assert(stats.session == 7u && stats.running);
              assert(!stats.fault_latched && stats.fault_flags == 0u);
              assert(stats.backlog_depth == 0u);
              return 0;
            }}
            """
        ),
        encoding="utf-8",
    )
    subprocess.run(
        [
            _compiler(),
            "-std=gnu++20",
            "-DARDUINO_ARCH_RP2040=1",
            "-DPICO_NO_HARDWARE=0",
            "-DPICO_PIO_VERSION=0",
            f"-I{stubs}",
            f"-I{BACKEND}",
            str(source),
            "-o",
            str(binary),
        ],
        check=True,
    )
    subprocess.run([str(binary)], check=True)
