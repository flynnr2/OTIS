"""Instruction-level proof harness for the OTIS PPS snapshot PIO program.

The model executes the real 16-bit RP2040 PIO words emitted by the pinned
``pioasm`` tool.  It intentionally models only the instructions used by the
program: WAIT, JMP and IN/autopush.  Any other opcode fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import argparse
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Iterable


SYS_HZ = 133_000_000
OSC_HZ = 16_000_000
FIFO_DEPTH = 8
PROGRAM_WRAP_TARGET = 0
PROGRAM_WRAP = 14
PROGRAM_INITIAL_PC = 11  # pps_high_wait_high: suppress a mid-pulse start.
PROGRAM_WORDS = (
    0x20A0,
    0x0042,
    0x00C6,
    0x2020,
    0x00CA,
    0x0000,
    0x4020,
    0x2020,
    0x00CB,
    0x0000,
    0x4020,
    0x20A0,
    0x004D,
    0x00C7,
    0x0003,
)


class ProofFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class Snapshot:
    cycle: int
    down_counter: int


@dataclass
class PioMachine:
    pc: int = PROGRAM_INITIAL_PC
    x: int = 0
    fifo_depth: int = 0
    rx_stall: bool = False
    snapshots: list[Snapshot] = field(default_factory=list)

    def _advance(self) -> None:
        self.pc += 1
        if self.pc > PROGRAM_WRAP:
            self.pc = PROGRAM_WRAP_TARGET

    def step(self, cycle: int, oscillator: bool, pps: bool, *, drain_fifo: bool = True) -> None:
        if drain_fifo and self.fifo_depth:
            self.fifo_depth -= 1

        word = PROGRAM_WORDS[self.pc]
        opcode = word >> 13

        if opcode == 0:  # JMP
            condition = (word >> 5) & 0x7
            target = word & 0x1F
            if condition == 0:
                take = True
            elif condition == 2:  # X--: decrement always, branch on old X != 0.
                take = self.x != 0
                self.x = (self.x - 1) & 0xFFFFFFFF
            elif condition == 6:  # PIN: independent EXECCTRL_JMP_PIN (PPS).
                take = pps
            else:
                raise ProofFailure(f"unsupported JMP condition {condition} at PC {self.pc}")
            if take:
                self.pc = target
            else:
                self._advance()
            return

        if opcode == 1:  # WAIT
            polarity = bool((word >> 7) & 1)
            source = (word >> 5) & 0x3
            index = word & 0x1F
            if source != 1 or index != 0:
                raise ProofFailure(f"WAIT at PC {self.pc} is not mapped oscillator PIN 0")
            if oscillator == polarity:
                self._advance()
            return

        if opcode == 2:  # IN X, 32 with autopush threshold 32.
            source = (word >> 5) & 0x7
            bit_count = word & 0x1F
            if source != 1 or bit_count != 0:
                raise ProofFailure(f"unexpected IN encoding at PC {self.pc}: 0x{word:04x}")
            if self.fifo_depth >= FIFO_DEPTH:
                self.rx_stall = True
                return
            self.fifo_depth += 1
            self.snapshots.append(Snapshot(cycle=cycle, down_counter=self.x))
            self._advance()
            return

        raise ProofFailure(f"unsupported opcode {opcode} at PC {self.pc}")


@dataclass
class TwoFlopSynchronizer:
    stage_1: bool
    stage_2: bool

    def sample(self, raw: bool) -> bool:
        observed = self.stage_2
        self.stage_2 = self.stage_1
        self.stage_1 = raw
        return observed


def _physical_oscillator(cycle: int, phase: float, duty: float) -> bool:
    return ((phase + cycle * OSC_HZ / SYS_HZ) % 1.0) < duty


def _physical_pps(cycle: int, start: float, period: float, high_cycles: float) -> bool:
    if cycle < start:
        return False
    return ((cycle - start) % period) < high_cycles


def _physical_edge_count(start: float, end: float, oscillator_phase: float) -> int:
    """Count continuous-time oscillator rises in the half-open interval [start, end)."""

    before_start = math.ceil(oscillator_phase + start * OSC_HZ / SYS_HZ - 1e-12)
    before_end = math.ceil(oscillator_phase + end * OSC_HZ / SYS_HZ - 1e-12)
    return before_end - before_start


def _down_counter_delta(first: int, second: int) -> int:
    return (first - second) & 0xFFFFFFFF


def simulate_case(*, phase_index: int, duty_percent: int, pps_edges: int = 8) -> tuple[int, ...]:
    oscillator_phase = phase_index / 256.0
    duty = duty_percent / 100.0
    pps_start = 101.25
    pps_period = 503.375  # Deliberately asynchronous to the oscillator.
    pps_high_cycles = 79.5
    final_cycle = math.ceil(
        pps_start + (pps_edges - 1) * pps_period + pps_high_cycles + 32
    )

    initial_osc = _physical_oscillator(0, oscillator_phase, duty)
    machine = PioMachine()
    osc_sync = TwoFlopSynchronizer(initial_osc, initial_osc)
    pps_sync = TwoFlopSynchronizer(False, False)

    for cycle in range(final_cycle):
        raw_osc = _physical_oscillator(cycle, oscillator_phase, duty)
        raw_pps = _physical_pps(cycle, pps_start, pps_period, pps_high_cycles)
        machine.step(
            cycle,
            osc_sync.sample(raw_osc),
            pps_sync.sample(raw_pps),
            drain_fifo=True,
        )

    physical_edges = [pps_start + index * pps_period for index in range(pps_edges)]
    if len(machine.snapshots) != len(physical_edges):
        raise ProofFailure(
            f"phase={phase_index}/256 duty={duty_percent}% produced "
            f"{len(machine.snapshots)} snapshots for {len(physical_edges)} PPS edges"
        )

    errors: list[int] = []
    for index in range(1, len(physical_edges)):
        expected = _physical_edge_count(
            physical_edges[index - 1], physical_edges[index], oscillator_phase
        )
        actual = _down_counter_delta(
            machine.snapshots[index - 1].down_counter,
            machine.snapshots[index].down_counter,
        )
        errors.append(actual - expected)
    return tuple(errors)


def verify_timing_paths() -> int:
    """Prove the opposite-level WAIT is reached within four clocks.

    The starting WAIT is considered to have completed at cycle zero.  PPS may
    take either value at every subsequent JMP PIN, which includes rise/fall
    transitions on the longest control paths.
    """

    waits = {0: True, 3: False, 7: False, 11: True}
    maximum = 0
    for start_pc, start_polarity in waits.items():
        frontier = {(start_pc + 1, 0)}
        visited: set[tuple[int, int]] = set()
        found: list[int] = []
        while frontier:
            pc, elapsed = frontier.pop()
            if (pc, elapsed) in visited:
                continue
            visited.add((pc, elapsed))
            if elapsed > 8:
                raise ProofFailure(f"no bounded opposite WAIT path from PC {start_pc}")
            if pc in waits:
                if waits[pc] == start_polarity:
                    raise ProofFailure(f"same-polarity WAIT reached from PC {start_pc} at PC {pc}")
                found.append(elapsed)
                continue

            word = PROGRAM_WORDS[pc]
            opcode = word >> 13
            if opcode == 0:
                condition = (word >> 5) & 0x7
                target = word & 0x1F
                if condition == 0:
                    next_pcs = (target,)
                elif condition == 2:
                    # Both outcomes are the following instruction in this program.
                    next_pcs = tuple({target, pc + 1})
                elif condition == 6:
                    next_pcs = tuple({target, pc + 1})
                else:
                    raise ProofFailure(f"unexpected condition {condition} in timing graph")
            elif opcode == 2:
                next_pcs = (pc + 1,)
            else:
                raise ProofFailure(f"unexpected opcode {opcode} in timing graph")
            for next_pc in next_pcs:
                frontier.add((next_pc, elapsed + 1))

        if not found:
            raise ProofFailure(f"no opposite WAIT reachable from PC {start_pc}")
        maximum = max(maximum, max(found))

    # ``maximum`` counts intervening non-WAIT instructions.  The destination
    # WAIT is fetched/executed on the following clock, so the installation
    # latency measured from the completing WAIT is one clock larger.
    installed_latency = maximum + 1
    if installed_latency != 4:
        raise ProofFailure(f"expected four-cycle bound, got {installed_latency}")
    return installed_latency


def verify_program_structure() -> None:
    if len(PROGRAM_WORDS) != 15:
        raise ProofFailure("program must remain a 15-instruction PIO v0 program")
    waits = {index for index, word in enumerate(PROGRAM_WORDS) if word >> 13 == 1}
    decrements = {
        index
        for index, word in enumerate(PROGRAM_WORDS)
        if word >> 13 == 0 and ((word >> 5) & 0x7) == 2
    }
    snapshots = {index for index, word in enumerate(PROGRAM_WORDS) if word >> 13 == 2}
    if waits != {0, 3, 7, 11} or decrements != {1, 12} or snapshots != {6, 10}:
        raise ProofFailure("WAIT/decrement/snapshot ownership changed")


def verify_fault_paths() -> dict[str, object]:
    # JMP X-- must preserve the natural 32-bit down-counter wrap.  Both branch
    # outcomes target/fall through to the same instruction, so X==0 is not a
    # special control-flow path.
    wrapping = PioMachine(pc=0, x=1)
    wrapping.step(0, True, False)
    wrapping.step(1, True, False)
    if wrapping.x != 0:
        raise ProofFailure("first rising edge did not decrement X from 1 to 0")
    # Reach the low WAIT, recognise low, then recognise the next high.
    for cycle, oscillator in ((2, True), (3, False), (4, False), (5, False), (6, True), (7, True)):
        wrapping.step(cycle, oscillator, False)
    if wrapping.x != 0xFFFFFFFF:
        raise ProofFailure("JMP X-- did not wrap X from 0 to UINT32_MAX")
    if _down_counter_delta(1, 0xFFFFFFFF) != 2:
        raise ProofFailure("down-counter adjacent subtraction failed across zero")

    # Startup deliberately models PPS as already high.  A mid-pulse enable must
    # not create a snapshot; low arms the following clean rise.
    startup = PioMachine()
    for cycle in range(96):
        oscillator = (cycle % 8) < 4
        startup.step(cycle, oscillator, True)
    if startup.snapshots:
        raise ProofFailure("startup while PPS high fabricated a snapshot")
    for cycle in range(96, 192):
        oscillator = (cycle % 8) < 4
        startup.step(cycle, oscillator, False)
    for cycle in range(192, 224):
        oscillator = (cycle % 8) < 4
        startup.step(cycle, oscillator, True)
    if len(startup.snapshots) != 1:
        raise ProofFailure("clean low-to-high PPS after startup did not create exactly one snapshot")

    # Once parked in the opposite-level WAIT, PPS activity cannot move the
    # state machine.  Software must invalidate/rearm on the missing snapshot.
    stopped_low = PioMachine(pc=0, x=0x12345678)
    stopped_high = PioMachine(pc=7, x=0x87654321)
    for cycle in range(512):
        pps = (cycle % 100) < 20
        stopped_low.step(cycle, False, pps)
        stopped_high.step(cycle, True, pps)
    if stopped_low.snapshots or stopped_high.snapshots:
        raise ProofFailure("PPS produced a snapshot while the oscillator was stopped")
    if stopped_low.x != 0x12345678 or stopped_high.x != 0x87654321:
        raise ProofFailure("stopped-oscillator WAIT path changed the cumulative counter")

    # Stoppage can begin while an instruction is already on the finite path
    # between WAITs.  Explore every PC and eight-cycle PPS pattern for both
    # final oscillator levels.  At most one tail snapshot may be emitted, and
    # the machine must then park at a WAIT which the stopped level cannot pass.
    maximum_stop_tail_cycles = 0
    maximum_stop_tail_snapshots = 0
    for stopped_level in (False, True):
        for start_pc in range(len(PROGRAM_WORDS)):
            for pps_pattern in range(256):
                tail = PioMachine(pc=start_pc, x=0x12345678)
                parked_at: int | None = None
                for tail_cycle in range(16):
                    pps = bool((pps_pattern >> (tail_cycle % 8)) & 1)
                    tail.step(tail_cycle, stopped_level, pps)
                    word = PROGRAM_WORDS[tail.pc]
                    if word >> 13 == 1:
                        polarity = bool((word >> 7) & 1)
                        if polarity != stopped_level:
                            parked_at = tail_cycle + 1
                            break
                if parked_at is None:
                    raise ProofFailure(
                        f"stop tail did not park: level={stopped_level} pc={start_pc}"
                    )
                if len(tail.snapshots) > 1:
                    raise ProofFailure(
                        f"stop tail emitted {len(tail.snapshots)} snapshots: "
                        f"level={stopped_level} pc={start_pc}"
                    )
                maximum_stop_tail_cycles = max(maximum_stop_tail_cycles, parked_at)
                maximum_stop_tail_snapshots = max(
                    maximum_stop_tail_snapshots, len(tail.snapshots)
                )

    # A full joined RX FIFO stalls the autopush instruction.  This is an
    # explicitly unbounded fault path, never part of the valid timing envelope.
    stalled = PioMachine()
    for cycle in range(4096):
        oscillator = (cycle % 8) < 4
        pps = cycle >= 40 and ((cycle - 40) % 160) < 24
        stalled.step(cycle, oscillator, pps, drain_fifo=False)
        if stalled.rx_stall:
            break
    if not stalled.rx_stall or stalled.fifo_depth != FIFO_DEPTH:
        raise ProofFailure("undrained FIFO did not enter the expected RXSTALL path")
    stalled_pc = stalled.pc
    stalled_x = stalled.x
    stalled_snapshots = len(stalled.snapshots)
    for cycle in range(cycle + 1, cycle + 257):
        stalled.step(cycle, (cycle % 8) < 4, (cycle % 160) < 24, drain_fifo=False)
    if (
        stalled.pc != stalled_pc
        or stalled.x != stalled_x
        or len(stalled.snapshots) != stalled_snapshots
    ):
        raise ProofFailure("full-FIFO autopush did not remain stalled and fail closed")

    return {
        "counter_wrap": "X 1 -> 0 -> UINT32_MAX; adjacent delta is 2",
        "startup_mid_high": "suppressed until low then next rise",
        "stopped_oscillator": {
            "parked_wait_pps_snapshots": 0,
            "finite_tail_max_cycles": maximum_stop_tail_cycles,
            "finite_tail_max_snapshots": maximum_stop_tail_snapshots,
            "policy": "invalidate session; never retroactively pair a tail/recovery word",
        },
        "full_fifo": f"RXSTALL after {FIFO_DEPTH} unread words; unbounded invalid path",
    }


def verify_assembled_words(pioasm: Path, source: Path) -> None:
    completed = subprocess.run(
        [str(pioasm), "-o", "hex", str(source)],
        check=True,
        capture_output=True,
        text=True,
    )
    assembled = tuple(
        int(match.group(1), 16)
        for line in completed.stdout.splitlines()
        if (match := re.fullmatch(r"([0-9a-fA-F]{4})", line.strip()))
    )
    if assembled != PROGRAM_WORDS:
        raise ProofFailure(
            "assembled program differs from the instruction-level proof: "
            f"expected={PROGRAM_WORDS!r} actual={assembled!r}"
        )


def verify_repository_installation(
    backend_source: Path, generated_header: Path, firmware_matrix: Path
) -> dict[str, object]:
    """Bind the instruction proof to the configuration installed by firmware.

    These assertions are deliberately source-level: they make a review-visible
    proof gate fail if a later edit silently changes a pin path, synchronizer,
    clock, FIFO, DMA, ring, wrap, or initial program counter.
    """

    backend = backend_source.read_text(encoding="utf-8")
    header = generated_header.read_text(encoding="utf-8")
    matrix = json.loads(firmware_matrix.read_text(encoding="utf-8"))

    required_backend_fragments = {
        "pio_block": "backend.pio = pio0;",
        "system_clock_runtime_gate":
            "backend.system_clock_hz != kRequiredSystemClockHz",
        "oscillator_wait_pin_path":
            "sm_config_set_in_pins(&config, OTIS_GPIO_OSC_OBSERVATION);",
        "pps_jmp_pin_path":
            "sm_config_set_jmp_pin(&config, OTIS_PIN_PPS_REFERENCE);",
        "synchronizers_enabled":
            "pio_set_input_sync_bypass_with_mask(\n      backend.pio, 0u,",
        "autopush_32":
            "sm_config_set_in_shift(&config, true, true, 32u);",
        "joined_rx_fifo":
            "sm_config_set_fifo_join(&config, PIO_FIFO_JOIN_RX);",
        "pio_divider_one": "sm_config_set_clkdiv(&config, 1.0f);",
        "initial_pc":
            "static_cast<uint>(backend.program_offset) + otis_pps_snapshot_initial_pc",
        "dma_rx_dreq": "pio_get_dreq(backend.pio, sm, false)",
        "dma_word_size":
            "channel_config_set_transfer_data_size(&dma_config, DMA_SIZE_32);",
        "dma_high_priority":
            "channel_config_set_high_priority(&dma_config, true);",
        "dma_ring_addressing":
            "channel_config_set_ring(&dma_config, true, kSnapshotRingAddressBits);",
        "aligned_ring":
            "alignas(512) volatile uint32_t snapshot_ring[kSnapshotRingCapacity]",
        "rxstall_fatal": "OTIS_PPS_SNAPSHOT_STATUS_PIO_RXSTALL",
        "dma_error_fatal": "OTIS_PPS_SNAPSHOT_STATUS_DMA_ERROR",
        "dma_stopped_fatal": "OTIS_PPS_SNAPSHOT_STATUS_DMA_STOPPED",
    }
    missing = [name for name, fragment in required_backend_fragments.items() if fragment not in backend]
    if missing:
        raise ProofFailure(
            "firmware installation no longer matches proof assumptions: "
            + ", ".join(missing)
        )

    required_header_fragments = (
        f"#define otis_pps_snapshot_wrap_target {PROGRAM_WRAP_TARGET}",
        f"#define otis_pps_snapshot_wrap {PROGRAM_WRAP}",
        f"#define otis_pps_snapshot_initial_pc {PROGRAM_INITIAL_PC}",
        f".length = {len(PROGRAM_WORDS)}",
    )
    if any(fragment not in header for fragment in required_header_fragments):
        raise ProofFailure("generated PIO wrap, start PC, or length differs from proof")
    generated_words = tuple(
        int(match.group(1), 16)
        for line in header.splitlines()
        if (match := re.match(r"\s*0x([0-9a-fA-F]{4}),\s*//", line))
    )
    if generated_words != PROGRAM_WORDS:
        raise ProofFailure("checked-in generated header words differ from proof")

    if matrix.get("target", {}).get("fqbn") != (
        "rp2040:rp2040:arduino_nano_connect:freq=133"
    ):
        raise ProofFailure("firmware matrix does not pin Nano RP2040 clk_sys to 133 MHz")
    pps_profiles = [
        profile["id"]
        for profile in matrix.get("profiles", [])
        if profile.get("defines", {}).get("OTIS_TCXO_COUNTER_BACKEND")
        == "OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO"
        and profile.get("expect") == "pass"
    ]
    if not pps_profiles:
        raise ProofFailure("no passing firmware profile installs the PPS snapshot backend")

    return {
        "backend_source": str(backend_source),
        "generated_header": str(generated_header),
        "matrix_fqbn": matrix["target"]["fqbn"],
        "pps_profiles": pps_profiles,
        "pio_block": 0,
        "in_base_gpio": 20,
        "jmp_pin_gpio": 26,
        "input_synchronizers": "enabled",
        "autopush_bits": 32,
        "joined_rx_fifo_words": FIFO_DEPTH,
        "dma_ring_words": 128,
    }


def verify_dma_ring_model() -> dict[str, object]:
    """Exercise the production ring's producer/consumer arithmetic."""

    capacity = 128
    mask = capacity - 1
    ring = [0] * capacity
    producer = 0
    consumer = 0

    def write(value: int) -> None:
        nonlocal producer
        ring[producer & mask] = value
        producer += 1

    def drain() -> list[int]:
        nonlocal consumer
        depth = producer - consumer
        if depth > capacity:
            consumer = producer
            raise ProofFailure("overwrite_detected")
        values: list[int] = []
        while consumer != producer:
            values.append(ring[consumer & mask])
            consumer += 1
        return values

    # Delayed foreground service remains lossless through exact capacity and
    # crosses the wrapped SRAM address without changing producer ordinals.
    for value in range(capacity):
        write(value)
    if producer - consumer != capacity or drain() != list(range(capacity)):
        raise ProofFailure("exact-capacity DMA ring did not drain losslessly")
    for value in range(capacity, capacity + 17):
        write(value)
    if drain() != list(range(capacity, capacity + 17)):
        raise ProofFailure("DMA ring address wrap changed snapshot values")

    # One word beyond capacity must be detected before any ambiguous slot is
    # consumed. The backend discards all unread words and starts a new session.
    producer = 0
    consumer = 0
    for value in range(capacity + 1):
        write(value)
    overwrite_detected = False
    try:
        drain()
    except ProofFailure as exc:
        if str(exc) != "overwrite_detected":
            raise
        overwrite_detected = True
    if not overwrite_detected or consumer != producer:
        raise ProofFailure("ring overwrite by one did not discard ambiguous data")

    return {
        "capacity_words": capacity,
        "exact_capacity": "lossless",
        "address_wrap": "lossless",
        "overwrite_by_one": "detected; unread words discarded; rearm required",
        "index_ownership": "DMA transfer count produces; foreground alone consumes",
    }


def run_phase_sweep(duties: Iterable[int] = range(35, 66)) -> dict[str, object]:
    duties = tuple(duties)
    error_histogram: dict[int, int] = {}
    case_count = 0
    interval_count = 0
    for duty in duties:
        for phase in range(256):
            errors = simulate_case(phase_index=phase, duty_percent=duty)
            case_count += 1
            interval_count += len(errors)
            for error in errors:
                error_histogram[error] = error_histogram.get(error, 0) + 1
    if not set(error_histogram).issubset({-1, 0, 1}):
        raise ProofFailure(f"boundary error exceeded one oscillator edge: {error_histogram}")
    return {
        "cases": case_count,
        "intervals": interval_count,
        "duty_percent": list(duties),
        "phase_offsets": 256,
        "boundary_error_edges": dict(sorted(error_histogram.items())),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pioasm", type=Path, help="Also prove the checked-in source assembles to PROGRAM_WORDS.")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("firmware/arduino/otis_nano_rp2040_connect/otis_pps_snapshot.pio"),
    )
    parser.add_argument(
        "--backend-source",
        type=Path,
        default=Path(
            "firmware/arduino/otis_nano_rp2040_connect/"
            "otis_pps_snapshot_backend.cpp"
        ),
    )
    parser.add_argument(
        "--generated-header",
        type=Path,
        default=Path(
            "firmware/arduino/otis_nano_rp2040_connect/"
            "otis_pps_snapshot.pio.h"
        ),
    )
    parser.add_argument(
        "--firmware-matrix",
        type=Path,
        default=Path("firmware/arduino/firmware_matrix.json"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    verify_program_structure()
    maximum_wait_latency = verify_timing_paths()
    if args.pioasm:
        verify_assembled_words(args.pioasm, args.source)
    result = run_phase_sweep()
    result["fault_paths"] = verify_fault_paths()
    result["repository_installation"] = verify_repository_installation(
        args.backend_source, args.generated_header, args.firmware_matrix
    )
    result["dma_ring"] = verify_dma_ring_model()
    result.update(
        {
            "program_words": [f"0x{word:04x}" for word in PROGRAM_WORDS],
            "program_length": len(PROGRAM_WORDS),
            "sys_hz": SYS_HZ,
            "oscillator_hz": OSC_HZ,
            "max_clocks_to_opposite_wait": maximum_wait_latency,
            "valid_fifo_model": "continuously drained; a full FIFO is an unbounded invalidating RXSTALL path",
        }
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
