# CX317 RX-Only GNSS Receiver Contract

Status: Stage 2 implementation contract; the 3000 ms freshness candidate must
be confirmed or tightened from the sealed live smoke before active control.

## Scope and authority

This adapter qualifies contemporaneous receiver health beside the existing raw
PPS capture. It does not timestamp PPS from UART arrival time, prove UTC
traceability, calibrate cable or receiver delay, or establish the PA1616S PPS
accuracy in the installed rig.

The adapter has no transmit operation. `OTIS_GNSS_UART_TX_ENABLED=1` is a
compile-time error. The implementation maps only UART0 RX and explicitly leaves
Nano D1/GPIO0 as a high-impedance input. Raw PPS capture continues through its
existing independent D14 path and is serviced before GNSS parsing.

## Frozen physical and protocol mapping

| Item | Stage 2 value | Evidence |
|---|---|---|
| GPS breakout TX | Nano D0 / RP2040 GPIO1 / UART0 RX | Installed Philhower `rp2040` 6.0.0 Nano variant: `D0=(1u)`, `PIN_SERIAL1_RX=D0` |
| Nano TX reservation | Nano D1 / RP2040 GPIO0, high-impedance input, never UART-mapped | Installed variant: `D1=(0u)`, `PIN_SERIAL1_TX=D1`; source-level structural test |
| Installed variant header SHA-256 | `fefffebb1fef775340027d415e0943448bfee3e8a43e0e89a8b9e84041032e3e` | `/Users/richardflynn/Library/Arduino15/packages/rp2040/hardware/rp2040/6.0.0/variants/arduino_nano_connect/pins_arduino.h` |
| UART | UART0, 9600 baud, 8 data bits, no parity, 1 stop bit | PA1616S default is 9600 baud; Adafruit breakout guide says TX defaults to 9600 baud |
| Logic | GPS TX is a 3.3 V logic output; PA1616S TX0 high is 2.4-2.8 V and low is at most 0.4 V | Local Adafruit guide p. 12; PA1616S local datasheet p. 13 |
| Receiver output | 1 Hz default; checksum-terminated NMEA RMC and GGA accepted; other checksum-valid sentences ignored | PA1616S local datasheet pp. 12 and 14-18 |
| PPS | Independent breakout PPS output on D14; UART metadata is never substituted for its timestamp | Adafruit guide p. 12 and OTIS capture architecture |

The local file `docs/datasheets/CD+PA1616S+Datasheet.v03.pdf` has SHA-256
`f041c26af4d3f244a33f8f0c6f6d5286e239173a9ea510346dc9c8c7cd3814c4`.
Its PDF metadata says Revision V03 while the rendered document identifies
itself as V04. The operator referred to V05, but no V05 file was found in the
workspace or user home at Stage 2 execution time. Claims here are therefore
limited to the exact local artifact and the live receiver output.

The local `docs/datasheets/adafruit-ultimate-gps.pdf` has SHA-256
`799ba1670e7eca399d482fc6fecf59fdbc0feda2c01b81e40fac9fab175b2c03` and
identifies itself as updated 2025-07-23.

## Parser and service bounds

- Fixed receiver state; no heap allocation.
- Fixed 96-byte line buffer, including sentence start and terminator space.
- At most 32 UART bytes consumed per main-loop service call.
- RMC requires a checksum-valid sentence, status `A`, syntactically valid UTC,
  and a six-digit date.
- GGA requires a checksum-valid sentence, non-zero fix quality, non-zero
  satellite count, and syntactically valid UTC. HDOP is retained when supplied.
- Both a fresh RMC and fresh GGA must occur after the most recent checksum or
  parser fault before metadata can requalify.
- A partial line, nested `$`, absent/malformed checksum, field failure, or
  oversize sentence increments the parser-fault epoch and inhibits eligibility.
- The initial freshness candidate is 3000 ms: three nominal 1 Hz epochs. Live
  Stage 2 evidence must show the observed RMC/GGA interval distribution and may
  only retain or tighten this value.
- Ten seconds without a recognized RMC/GGA marks a disconnect. The next
  recognized message increments `identity_epoch`. Any epoch other than the
  run-start epoch is non-authoritative until a fresh run explicitly establishes
  identity, so reconnect cannot silently resume actuation.
- Short fix loss without a receiver-identity epoch change may recover only
  after a fresh, checksum-valid RMC/GGA pair.

## Eligibility contract

`gnss_receiver.metadata_control_eligible` is true only when:

1. the receiver is initialized and structurally RX-only;
2. current RMC and GGA messages are both fresh and checksum-valid after the
   latest parser fault;
3. RMC is valid, GGA fix quality and satellite count are non-zero, and UTC/date
   are available; and
4. `identity_epoch` remains the run-start epoch.

`gnss_receiver.control_eligible` additionally requires the independent raw PPS
and count gate to be healthy: a control-ready count stream, at least one
accepted D14 PPS, no rejected-short or rejected-long D14 event, and no capture
or PPS-boundary ring drop. Eligibility is a gate only. It is not a PPS accuracy,
UTC traceability, or holdover claim.

## Telemetry contract

Periodic `STS` records under component `gnss_receiver` expose:

- receiver/configuration, RX/TX pins, RX-only state and NMEA talker;
- RMC/GGA seen state, RMC validity, GGA fix quality, satellites and HDOP;
- UTC/date availability and values;
- metadata age/freshness, checksum requalification, disconnect state,
  identity stability and identity epoch;
- checksum-valid, checksum-failure, parser-drop, truncated, oversize, RMC and
  GGA counters; and
- metadata-only, raw-PPS-only and combined control eligibility.

UTC/date values are diagnostic receiver metadata. They are not used as event
timestamps.

## Deterministic fixtures

`tests/cpp/gnss_receiver_harness.cpp` and `tests/test_gnss_receiver.py` cover:

- valid GGA-before-RMC order and extracted fields;
- checksum failure followed by mandatory RMC/GGA requalification;
- truncated, nested-start and oversize input;
- exact freshness boundary and stale metadata;
- fix loss and fresh-pair recovery;
- invalid UTC;
- a long disconnect, receiver identity epoch increment and continued inhibit;
- source-level proof that GPIO0 is never UART-mapped and no UART write API is
  present; and
- capture-first, statically bounded service ordering.
