# Hardware resource ownership

## Current instrument

This is the ownership ledger for the one buildable fixed Nano RP2040 Connect image,
`adaptive_hybrid_regulation`. There are no build-mode or backend selectors.
The executable queue ledger is
`firmware/arduino/otis_nano_rp2040_connect/otis_resource_inventory.json`; it is
normative for capacities, producers, consumers, loss policy, and recovery.

The timing roles are fixed:

- D14 / GPIO26 is the sole PPS/reference input.
- D8 / GPIO20 is the sole oscillator/count input. A PIO state machine counts
  D8 edges and snapshots cumulative state at each recognized D14 boundary; a
  bounded Core 1 FIFO IRQ transports the captured words.
- D10 / GPIO5 is the external event/edge input. Its pin identity and host
  evidence seam are retained, but firmware capture is not implemented in this
  image. It therefore owns no IRQ, PIO, DMA, validity, setup, control,
  actuation, or terminal resource.
- D9 / GPIO21 is the exact GPIN0-forwarded GPOUT0 output.
- D6 / GPIO18 is a fail-local diagnostic observation of the forwarded clock.
  It uses a separate PIO state machine and cannot veto D14/D8 operation.

## Fixed claims

| Resource | Owner | Role |
|---|---|---|
| RP2040 timer/timebase | `arduino_timebase` | scheduling and reconstructed monotonic timestamps |
| `clk_sys` tree | `arduino_clock_tree` | CPU, USB, PIO, and DMA execution |
| D14 / GPIO26 | `count_observation` | sole reference input to the count PIO |
| D8 / GPIO20 | `count_observation` | raw oscillator input |
| one dynamic PIO0 state machine and 15 instruction words | `count_observation` | D8 cumulative count snapshotted by D14 |
| PIO0 IRQ1, dynamically bound RX-not-empty source | `count_observation` | bounded transport of committed snapshot words |
| D9 / GPIO21 and GPOUT0 | `forwarded_clock_output` | GPIN0 integer-divide-one forwarded output |
| D6 / GPIO18 | `forwarded_clock_monitor` | fail-local diagnostic input |
| one dynamic PIO0 state machine and 15 instruction words | `forwarded_clock_monitor` | D6 cumulative count snapshotted by D14 |
| I2C0, D18 / GPIO12 SDA, D19 / GPIO13 SCL | `i2c_bus` | shared instrument bus |
| I2C address `0x4c` | `dac_ad5693r` | AD5693R actuator |
| I2C address `0x44` | `environment_sht4x` | optional environment sensor |
| I2C address `0x77` | `environment_bmp280` | optional environment sensor |
| UART0, D0 / GPIO1 RX, D1 / GPIO0 TX | `gnss_receiver` | fixed 115200 GNSS metadata path and bounded configuration write |

The D8/D14 PIO state machine owns the count boundary and raw identity. There
is no D14 GPIO IRQ observer or DMA transport. The FIFO IRQ records CPU service
coordinates with conservative PIO-recognition bounds; it does not create an
electrical-edge timestamp. The D6 monitor has neither a DMA nor GPIO-IRQ claim.

## Registry rules

`otis_resource_registry` constructs this fixed claim set before normal
hardware setup and enforces:

1. one owner per physical resource key;
2. no overlapping OTIS GPIO, PIO state-machine, instruction-memory, PIO IRQ-source,
   timer, clock, UART, I2C-controller, or I2C-address claims;
3. SDK allocation followed by binding for dynamic PIO state-machine, instruction-memory and IRQ-source resources;
4. fixed ownership for the life of a boot; and
5. fail-closed boot for an authoritative conflict or incomplete binding.

D6 is deliberately different: allocation or queue failure disables only that
diagnostic and remains explicit. It cannot invalidate registry completeness for
the D14/D8 path or acquire control or terminal authority.

The registry emits `STS` evidence for validity, completeness, conflicts,
binding failures, per-class counts, and every individual claim, including the
actual dynamically allocated indices. A claim is never silently reassigned.

## Concurrency boundaries

Core 1 owns timing and policy execution. Core 0 owns physical I2C execution,
serial transport, and service work. Immutable bounded queues carry requests,
acknowledgements, observations, and evidence between them; ownership does not
migrate. The inventory JSON records each queue's exact producer, consumer,
capacity, loss behavior, and recovery rule.

Capture occurs independently of host attachment. Authoritative queue or ring
loss is explicit and fail-static. Telemetry and D6 diagnostic loss are
fail-local. D10 traffic, when firmware capture is later implemented, must use
an isolated resource and loss path that cannot compromise D14/D8 capture.

## Verification boundary

No-host source and native tests verify the fixed claim construction, dynamic
binding, collision handling, queue declarations, and the D10 isolation rule.
The canonical firmware build verifies that this exact image links with the
pinned Arduino core. Those checks do not establish physical pin muxing, PIO
allocation behavior under unrelated third-party code, or electrical timing;
those remain bench-verification boundaries for the frozen image.
