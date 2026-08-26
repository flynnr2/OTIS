# CX317 GNSS Serial Discovery and Runtime RX-Only Contract

Status: current implementation contract. The historical filename is retained
for stable references. The 3000 ms metadata-freshness value remains subject to
the sealed live receiver evidence.

## Scope and authority

This service qualifies contemporaneous receiver health beside the independent
raw D14 PPS capture. UART arrival time never timestamps PPS, establishes UTC
traceability, calibrates receiver/cable delay, or replaces D14 timing authority.

GNSS serial acquisition is not a boot or capture prerequisite. `begin()` only
initializes fixed state and the first UART candidate; discovery, queries and
configuration advance through bounded Core 0 service calls. D14/D8 capture,
host attachment and telemetry continue while the link is `discovering`,
`validating`, `degraded` or `lost`. GNSS-dependent control remains inhibited
until the serial link and required metadata independently qualify.

Nano D1/GPIO0 is owned by the GNSS service. Transmission is limited to four
compile-time fixed PMTK packets:

- `$PMTK605*31` - query receiver firmware identity;
- `$PMTK251,9600*17` - request the frozen target baud;
- `$PMTK414*33` - query NMEA output configuration; and
- `$PMTK314,0,1,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0*29` - enable exactly
  RMC, GGA and GSA once per position fix.

No host command, runtime payload or general receiver-write API exists. Once the
target baud, identity and output configuration are confirmed, the service is
runtime RX-only. In this retained telemetry terminology, `rx_only=true` means
that the fixed configuration transaction is complete and no transmit action is
pending or active. D1 remains UART-mapped and electrically idle-high; it is not
returned to a high-impedance GPIO input.

## Frozen physical and protocol mapping

| Item | Current value | Evidence |
|---|---|---|
| GPS TX | Nano D0 / RP2040 GPIO1 / UART0 RX | Installed Philhower `rp2040` 6.0.0 Nano variant: `D0=(1u)`, `PIN_SERIAL1_RX=D0` |
| GPS RX | Nano D1 / RP2040 GPIO0 / UART0 TX | Installed variant: `D1=(0u)`, `PIN_SERIAL1_TX=D1`; resource registry and source guards |
| Installed variant header SHA-256 | `fefffebb1fef775340027d415e0943448bfee3e8a43e0e89a8b9e84041032e3e` | `/Users/richardflynn/Library/Arduino15/packages/rp2040/hardware/rp2040/6.0.0/variants/arduino_nano_connect/pins_arduino.h` |
| UART framing | UART0, 8 data bits, no parity, 1 stop bit | PA1616S and Nano implementation |
| Discovery baud set | 9600, 115200, 57600, 38400, 19200, 14400, 4800 | MT3339 PMTK251 supported values; target first, then the documented alternatives |
| Frozen operational baud | 9600 | Confirmed checksum-valid PMTK705 after any baud transition |
| Frozen NMEA output | RMC, GGA and GSA once per position fix; all other PMTK314 and receiver-extension fields zero | PMTK514 readback must match one explicitly qualified field shape after acknowledgement |
| PPS | Independent breakout PPS output on D14 | UART metadata never substitutes for the D14 timestamp |

The local `docs/datasheets/CD PA1616S Datasheet.v05.pdf` has SHA-256
`1edf78b565231f887164a52e3ed0e6b001e9c6246cddc21dda7e64291ff8a8f2`.
It identifies the MT3339 solution and 9600 baud as the module default.

The older local `docs/datasheets/CD+PA1616S+Datasheet.v03.pdf` has SHA-256
`f041c26af4d3f244a33f8f0c6f6d5286e239173a9ea510346dc9c8c7cd3814c4`.
Its PDF metadata says Revision V03 while the rendered document identifies
itself as V04. It agrees on the MT3339 solution and default baud.

The local `docs/datasheets/PMTK command packet-Complete-C39-A01.pdf` has
SHA-256 `88318174825c78e27c4f24eb9b205875e5336f1352e5fa2801a724dad6ce1160`.
It documents PMTK acknowledgements, PMTK605/705 identity, PMTK414/514 output
query/readback, all seven candidate baud values, and the temporary/retained
configuration qualifications. The state machine therefore discovers current
state rather than assuming either reset-to-default or backup retention.

The command set contains no query/data pair for the current NMEA-port baud.
`PMTK251` is set-only. Baud confirmation is therefore an operational
challenge/response fact: after changing the MCU UART to the target baud, require
a fresh checksum-valid `PMTK705` identity response at that baud. `PMTK414` and
`PMTK514` query and report NMEA sentence output frequencies, not UART baud.
Keep baud-transition qualification and output-configuration qualification as
separate recorded facts even when both are required before declaring the full
link online.

The first physical exercise on 2026-08-25 proved repeated post-transition
communication at 115200 but failed the later `PMTK414`/`PMTK514` output-
configuration verification. The attempt-1 implementation's `confirmed_baud`
field was cleared when that later failure restarted discovery, so it did not
preserve the already established baud fact. The corrective revision exposes
the last successful identity-response baud, exact link phase, confirmation
method, command acknowledgement, output-response signature, query timeouts,
and observed sentence masks independently. See
`docs/60_EXPERIMENTS/OTIS_TARGETED_EQUILIBRIUM_CHARACTERIZATION_V1/README.md`.

Attempt 5 subsequently returned the frozen operational target to 9600 so the
targeted open-loop science would not depend on first diagnosing sparse NMEA
frame corruption observed during the 115200 soak. The first attempt-5 artifact
exposed a C++ translation-unit configuration escape: sketch telemetry compiled
the 9600 selector while the receiver implementation compiled the 115200 PMTK251
branch. The receiver implementation now includes the configuration before its
conditional command definition. Campaign bundling also binds the ELF and
requires the selected target command to be present and the opposite target
command absent. Successful source tests or a declared build selector alone are
not accepted as evidence of the emitted receiver command.

Authorized attempt 6 provided the physical closure on 2026-08-26. The receiver
was first identified at its retained 115200 baud, accepted the compiled 9600
transition, and returned a fresh checksum-valid PMTK705 identity at 9600. It
then remained online and exactly configuration-confirmed for the complete
twelve-dwell campaign. Terminal telemetry recorded `confirmed_baud=9600`,
`last_identity_response_baud=9600`, 137028 checksum-valid frames, and zero
checksum, truncation, oversize, configuration, transmit, or link-loss failures.
The 9600 transition is therefore proved and is an ordinary reusable status
fact, not a special gate for future runs whose receiver, wiring, firmware
transition semantics, and other decision-relevant inputs are unchanged.

Some PA1616S firmware may not implement the documented `PMTK414` query. A
missing query response or an explicit unsupported acknowledgement therefore
enters a strict fallback; it is not itself evidence that configuration is
correct. The link sends the exact 19-field `PMTK314` command, requires
`PMTK001,314,3`, retries `PMTK414`, and, only if the query remains unavailable,
observes 2.5 seconds of checksum-valid NMEA output. That observation must
contain RMC, GGA, and GSA and no other NMEA sentence type. The online state
records whether qualification used an exact `PMTK514` response or the
acknowledged-command-plus-exact-observation path.

The authorized attempt-2 physical entry showed that this PA1616S firmware does
implement `PMTK414`, but returns 22 data fields rather than the 19 fields in the
MT3339 A11 document. Its exact response was
`0101100000000000000000`: the commanded 19-field RMC/GGA/GSA-only prefix plus
three disabled extension fields. PMTK documentation across firmware families
also varies in its declared field count. The implementation does not accept an
arbitrary variable-length response: it accepts the documented 19-field form or
the physically observed 22-field form only, requires the entire common prefix
to match, and requires all three extension fields to be zero. Field count and
the full bounded signature remain in telemetry and the campaign contract.

The local `docs/datasheets/adafruit-ultimate-gps.pdf` has SHA-256
`799ba1670e7eca399d482fc6fecf59fdbc0feda2c01b81e40fac9fab175b2c03`
and identifies itself as updated 2025-07-23.

## Discovery and configuration state machine

1. Select a candidate baud without waiting and clear the discovery frame.
2. Listen passively for 1200 ms. Any checksum-valid NMEA/PMTK frame is link
   evidence only; wrong-baud bytes never enter the canonical metadata parser.
3. Send PMTK605 and require a checksum-valid PMTK705 within 750 ms. Silence or
   unrelated NMEA advances to the next candidate.
4. If identity is found away from 9600, send PMTK251 at the identified baud,
   wait for bounded physical transmission completion, switch UART0 to 9600,
   and require a fresh PMTK705 response at the target baud. An acknowledgement
   at the producer boundary is not sufficient.
5. Query PMTK514. Accept only the exact documented 19-field
   RMC/GGA/GSA-only signature or the exact qualified 22-field PA1616S signature
   with three trailing zeros. Otherwise send the fixed PMTK314 packet, require
   successful PMTK001 acknowledgement, and query again. If query/readback is
   unavailable, use the bounded exact-output observation fallback above.
6. Enter `online` and open the metadata parser only after all preceding gates.
   Ten seconds without any checksum-valid link frame closes it and restarts
   discovery; receiver metadata must requalify under the identity-epoch rules.

The first complete scan is a bounded grace period. Discovery still in progress
after 15 seconds reports `degraded`; it does not stop capture. A previously
online link reports `lost` while reacquisition proceeds.

## Parser and service bounds

- No heap allocation.
- Separate fixed buffers: 256 bytes for PMTK/NMEA discovery and 96 bytes for
  canonical RMC/GGA/GSA metadata.
- At most 32 UART RX bytes and eight UART TX bytes are handled per service call.
- A transmit has one absolute 500 ms horizon; intermittent FIFO progress does
  not extend it. Failure is recorded and discovery restarts.
- UART changes use the documented candidate set only. Each transition resets
  the discovery collector so prior-rate bytes cannot manufacture a frame.
- Every synchronous STS record invokes the same bounded service, preventing
  health bursts from starving UART0 without weakening capture-first ordering.
- GNSS status takes its freshness anchor immediately before snapshot copying,
  after preceding interleaved service.
- RMC requires a valid checksum, status `A`, syntactically valid UTC and a
  six-digit date. GGA requires valid checksum, non-zero fix quality and
  satellites, and valid UTC. GSA Mode 2 independently supplies 3D state.
- Fresh RMC and GGA after the latest metadata parser fault are required.
- Ten seconds without recognized RMC/GGA marks a receiver disconnect. The next
  recognized message increments `identity_epoch`; an epoch other than the
  run-start epoch cannot silently resume control.

## Eligibility contract

`gnss_receiver.metadata_control_eligible` is true only when:

1. the service is initialized;
2. `link_state=online`, `confirmed_baud=115200`, PMTK705 identity is available,
   PMTK514 configuration is exact, and the service has returned to RX-only;
3. RMC and GGA are fresh and checksum-requalified after the latest parser fault;
4. RMC is valid, GGA fix quality and satellite count are non-zero, UTC/date are
   available; and
5. `identity_epoch` remains the run-start epoch.

The active-authority consumer additionally requires fresh checksum-requalified
GSA Mode 2 value 3 as explicit 3D evidence; GGA fix quality does not encode that
dimension.

`gnss_receiver.control_eligible` additionally requires the independent raw D14
PPS and D8/count gates: a control-ready count stream, accepted D14 PPS, clean
capture/boundary queues and no current reference anomaly. Eligibility is a
diagnostic gate, not a PPS-accuracy, UTC-traceability or holdover claim.

## Telemetry contract

Periodic `STS` records under `gnss_receiver` expose:

- service initialization, coarse link state, exact link phase, current
  candidate, confirmed baud, and last successful identity-response baud;
- PMTK release identity, exact-configuration confirmation method, full bounded
  response signature and field count, command acknowledgement, query/response
  and observation counters, observed sentence masks, and runtime RX-only state;
- discovery cycle, last-valid-frame age, candidate rejection, configuration,
  transmit, link-loss, checksum and oversize counters;
- RMC/GGA/GSA state, validity, fix quality/dimension, satellites and HDOP;
- metadata freshness, checksum requalification, disconnect and identity epoch;
  and
- metadata-only, raw-PPS-only and combined control eligibility.

UTC/date values remain diagnostic receiver metadata and are never event
timestamps.

## Deterministic fixtures

`tests/cpp/gnss_receiver_harness.cpp` and `tests/test_gnss_receiver.py` cover:

- passive target-baud discovery and exact configuration confirmation;
- timeout at 115200, discovery at 9600, bounded transition to 115200, identity
  re-query and output reconfiguration/readback;
- wrong-baud/checksum noise isolation, degraded discovery and online loss;
- fixed command checksums, the sole bounded UART write site and absence of a
  generic transmit API;
- constant-time `begin()`, capture-first ordering and bounded RX/TX service;
- valid metadata order variation, parser faults and requalification;
- freshness, fix loss/recovery, GSA dimension, disconnect and identity epoch;
  and
- post-service status freshness anchoring.
