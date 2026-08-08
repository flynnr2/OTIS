# Hardware Resource Ownership

## Status and scope

This document is the ownership ledger for the active Arduino Nano RP2040
Connect firmware. It covers every GPIO, GPIO IRQ source, PIO state machine and
instruction-memory range, DMA channel, timer, and clock resource that OTIS uses
or reserves. It also records the shared I2C controller because its SDA/SCL GPIOs
are part of the same conflict boundary.

The ledger does not assign unused RP2040 peripherals merely to make the table
look complete. An unallocated resource is not an OTIS resource. Profiles using
the PPS-gated ratio backend claim and report exactly the dynamically allocated
DMA channel used by its snapshot ring. Profiles using another count backend
claim no DMA channel and emit that zero claim explicitly at boot.

## Enforced invariants

`otis_resource_registry` derives the claim set from the selected bring-up mode
and capture/count backends before safe-mode or normal-mode hardware setup.

The registry enforces these rules:

1. A physical resource key has one registry entry and one owner.
2. Different functions of the same GPIO cannot be claimed by different OTIS
   subsystems in one build.
3. GPIO IRQ ownership is per GPIO source. The Arduino core remains the owner of
   the shared RP2040 IRQ dispatcher.
4. PIO state machines and program offsets are allocated through the Pico SDK
   and then bound to the predeclared OTIS owner. PIO instruction ranges may be
   adjacent but may not overlap.
5. A resource conflict fails boot with
   `ResourceOwnershipConflict`. A PIO allocation that cannot be completed
   remains visible as a pending registry claim and through the backend's
   existing initialization status.
6. Ownership is fixed for a boot. There is no runtime transfer or multiplexing.

The registry preserves evidence rather than silently choosing a winner.
Additive `STS` rows report registry validity, completeness, total claims,
conflicts, binding failures, per-class counts, and every individual claim. PIO
rows include the state machine and instruction offset actually assigned in that
boot.

## Base ownership

These claims exist in every build:

| Resource | Physical identity | Owner | Role |
|---|---|---|---|
| timer/timebase | RP2040 monotonic timebase exposed by Arduino `micros()` / `millis()` | `arduino_timebase` | scheduling and reconstructed OTIS timestamps |
| system clock tree | `clk_sys` and core-managed derived clocks | `arduino_clock_tree` | CPU, USB, PIO and potential DMA execution clock |
| GPIO | `D9` / GPIO21 | `clock_visibility` | reserved `GPOUT0` visibility pin |
| clock output | `GPOUT0` | `clock_visibility` | reserved internal-clock visibility function |
| GPIO | `D2` / GPIO25 | `diagnostic_clock` | reserved `GPOUT3` diagnostic pin |
| clock output | `GPOUT3` | `diagnostic_clock` | reserved secondary diagnostic-clock function |

When the status LED is enabled, `D13` / GPIO6 is owned by `status_led`. It is
not claimed when that feature is disabled.

The timer entry names the core as owner because OTIS consumes the Arduino
timebase; OTIS does not configure a hardware alarm, repeating timer, or private
timer IRQ. The `rp2040_timer0` value in existing wire contracts remains a
reconstructed OTIS timestamp domain and is not changed by this ownership work.

## Mode-selected GPIO and IRQ ownership

| Build selection | GPIO owner and role | IRQ/PIO owner |
|---|---|---|
| `SW1_SYNTHETIC_USB` | no live capture GPIO | none |
| `SW1_GPIO_LOOPBACK` | `D7` / GPIO19 → `loopback_output`; `D10` / GPIO5 → `edge_capture` | GPIO5 IRQ source → `edge_capture`, or one PIO0 SM/program → `edge_capture` |
| `SW1_GPS_PPS` | `D14` / GPIO26 → `edge_capture` | GPIO26 IRQ source → `edge_capture`, or one PIO0 SM/program → `edge_capture` |
| `SW1_TCXO_OBSERVE` | `D14` / GPIO26 → `edge_capture`; `D8` / GPIO20 → `count_observation` | selected capture and count backend claims below |
| `H1_OCXO_OBSERVE_OPEN_LOOP` | same timing GPIO ownership as TCXO observe | selected capture and count backend claims below |

With the temporary dual PPS observer enabled, `D10` / GPIO5 and its IRQ source
are owned by `pps_witness`. Existing compile guards prohibit enabling that owner
in GPIO-loopback mode or with the PIO edge backend.

For TCXO/OCXO observation, the count backend adds:

| Count backend | Additional resource | Owner |
|---|---|---|
| `FC0_GPIN0` | `GPIN0` clock input and frequency counter 0 | `count_observation` |
| `GPIO_IRQ` | GPIO20 IRQ source; divided inputs only | `count_observation` |
| `PIO_LONG_GATE` | one dynamically allocated PIO0 SM and five-word instruction range | `count_observation` |
| `PPS_GATED_RATIO` | one dynamically allocated PIO0 SM, 15-word instruction range, one DMA channel, and aligned 128-word SRAM snapshot ring | `count_observation` |

The PPS-gated ratio backend has two read-only D14 consumers with distinct
roles. `edge_capture` owns the GPIO26 IRQ only as the independent REF observer;
`count_observation` maps the same input to its PIO state machine as the hardware
snapshot condition. The PIO state machine alone owns the count boundary. The
registry also binds the dynamically claimed DMA channel to
`count_observation`; DMA transports the already-captured word and is not a
boundary owner.

## PIO and DMA policy

PIO users call the Pico SDK's non-panicking state-machine and program allocators.
The registry then binds the returned PIO block, state-machine number, program
offset, and program length to the declared owner. This retains compatibility
with core or library PIO users while preventing two OTIS paths from recording
the same allocation as their own.

PIO1 is not used. PIO0 state machines and instruction words not returned by the
SDK allocators are not OTIS-owned.

The PPS-gated snapshot backend dynamically claims one DMA channel, binds it in
the registry before enabling normal operation, and reports the actual channel.
All profiles not using that backend retain zero DMA claims. No channel number is
pre-allocated speculatively.

## Shared I2C ownership

In H1 builds with a DAC or environmental sensor enabled:

| Resource | Owner | Clients |
|---|---|---|
| I2C0 controller | `i2c_bus` | AD5693R, SHT4x, BMP280 |
| `D18` / GPIO12 (`SDA`) | `i2c_bus` | I2C0 controller |
| `D19` / GPIO13 (`SCL`) | `i2c_bus` | I2C0 controller |
| address `0x4C` by default | `dac_ad5693r` | AD5693R driver |
| address `0x44` by default | `environment_sht4x` | SHT4x driver |
| address `0x77` by default | `environment_bmp280` | BMP280 driver |

`otis_i2c_bus` is the only module that calls `Wire.begin()`. Device modules ask
that owner to initialize the bus idempotently, then retain ownership only of
their configured device address. Duplicate enabled addresses are registry
conflicts.

## Boot diagnostics

The following additive `STS` keys are emitted under component
`resource_registry`:

- `version`, `valid`, `complete`;
- `claim_count`, `conflict_count`, `binding_failure_count`;
- `gpio_claim_count`, `irq_claim_count`, `pio_sm_claim_count`,
  `pio_imem_claim_count`, `dma_claim_count`, `timer_claim_count`, and
  `clock_claim_count`;
- deterministic `claim_00`, `claim_01`, ... entries containing resource type,
  instance, index, span, owner, role, and `bound`/`pending` state.

These rows extend `health_v1`; they do not change any CSV columns, record tags,
timestamp domains, sequence rules, or measurement flags. Existing `REF`, `EVT`,
`CNT`, `ENV`, and `DAC` evidence is unchanged.

## Engineering notes

- Fixed PIO state-machine numbers were deliberately not introduced. SDK
  allocation followed by registry binding is compatible with the current core
  and makes the actual allocation observable.
- Ownership is represented at the narrowest exclusive boundary. Thus the
  Arduino core owns the shared IRQ dispatcher while an OTIS capture subsystem
  owns one GPIO IRQ source.
- The I2C correction centralizes controller initialization only. It does not add
  a bus framework, device abstraction, scheduler, or new concurrency model.
- Registry claims are assembled in a fixed order from compile-time mode
  selection. Diagnostic claim numbering is therefore reproducible for the same
  build configuration.

## Compatibility assessment

- Existing wire contracts are unchanged. All resource telemetry is additive
  `STS`.
- Existing mode, pin, capture, count, DAC, and environment behavior is retained.
- Existing boot fatal numeric values `0..10` are unchanged;
  `ResourceOwnershipConflict` is appended as value `11`.
- DAC and environment begin functions remain independently callable. Repeated
  calls converge on the one idempotent I2C bus initializer.
- Host tools that ignore unknown status keys continue to work without changes.

## Risk assessment

| Risk | Assessment | Required check |
|---|---|---|
| Core/library GPIO use outside the OTIS ledger | The registry enforces OTIS ownership, but cannot introspect arbitrary third-party code that directly reconfigures a GPIO. | Compile with the pinned Philhower core and inspect any newly added library before enabling it. |
| Dynamic PIO allocation | SDK allocation prevents hardware double-claiming; actual SM/offset can change when another library uses PIO. Registry telemetry preserves the assigned identity. | On the combined PIO build, confirm distinct SMs and non-overlapping program offsets, then verify both `REF` and `CNT`. |
| PIO allocation exhaustion | A backend can remain uninitialized with a pending claim. Existing backend failure telemetry and registry completeness expose the condition, but current mode setup does not turn every allocation failure into a boot fatal. | Exhaust or reserve PIO resources in a bench test and verify `complete=false`, backend `init=failed`, and no clean measurement is inferred. |
| I2C concurrency | Core 0 is the sole physical I2C execution plane for the DAC and environment sensors. Core 1 never accesses `Wire` or mutable device state; actuator work crosses through bounded immutable request/acknowledgement records. No cross-core I2C lock is required because ownership does not migrate. | Native queue/guard tests and the dual-core live proof must show exact request/acknowledgement accounting, one physical DAC call site, and continued timing capture under service-plane I2C and telemetry load. |
| Hardware mux not exercised in host tests | Host tests cover collision semantics and ownership call paths; compile tests cover supported configurations. | Bench-check pin functions, IRQ activity, PIO allocations, and status evidence on the Nano RP2040 Connect. |

## PPS qualification handoff

PPS ownership work is complete: `edge_capture` remains the one D14 owner, the
optional D10 input remains an independent witness, and the D14 IRQ owns the
physical count boundary before foreground service. Phase 5 qualification must
bound IRQ/restart quantisation, verify atomic boundary traceability and fault
behavior, and retain these ownership assignments. It must not add a second D14
owner, hide rejected evidence, or authorize steering.
