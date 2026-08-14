# CX317 dual-core timing/service partition report

Date: 2026-08-04
Programme stage: 6
Result: **PASS**

## Decision

The Arduino-Pico Nano RP2040 Connect implementation now uses one frozen core
convention:

- Core 0 owns USB command/telemetry transport, RX-only GNSS parsing,
  environment service, run control and physical I2C DAC execution.
- Core 1 owns PIO/DMA draining, raw reference/snapshot/count construction,
  sequence and continuity state, the selected/diagnostic estimators and
  preview/control state.

The implementation decision and queue ownership are authoritative in
[`CORE_PARTITIONING.md`](../../10_REFERENCE_ARCHITECTURE/CORE_PARTITIONING.md).
Present-tense DMA and I2C ownership wording is aligned in
[`HARDWARE_RESOURCE_OWNERSHIP.md`](../../50_SOFTWARE/HARDWARE_RESOURCE_OWNERSHIP.md)
and
[`RP2040_CAPTURE_ARCHITECTURE.md`](../../50_SOFTWARE/RP2040_CAPTURE_ARCHITECTURE.md).

## Cross-core contract

Every cross-core value is fixed-size, pointer-free and immutable after
publication. The implemented queues are:

| Direction | Content | Depth | Loss/fault rule |
|---|---|---:|---|
| Core 0 to Core 1 | receiver qualification, environment, applied-DAC state and run control | 16 | non-droppable; exhaustion latches fail-static |
| Core 1 to Core 0 | raw edge, PPS snapshot and count observations | 96 | non-droppable; exhaustion latches fail-static |
| Core 1 to Core 0 | actuator and critical transition/fault records | 16 | non-droppable; exhaustion latches fail-static |
| Core 1 to Core 0 | redundant formatted telemetry | 96 | droppable with a saturating counter |

The actuator guard binds request sequence, decision sequence, source range,
deadline, one-time authorization sequence, nonce and requested code. Acceptance
and application are distinct acknowledgements. Duplicate, stale, mismatched or
late acknowledgement evidence faults fail-static. There is no automatic retry
or restoration write.

The Stage 6 build structurally prohibits bounded active control. Its only DAC
record is an idempotent manual `0xA82A` to `0xA82A` volatile state
acknowledgement; it made no code movement and was not feedback-derived.

## Deterministic isolation evidence

Native and host fixtures exercise:

- ordered service-to-timing and timing-to-service transfer;
- preservation of raw observation and estimator sequences under service load;
- explicit accounting of droppable telemetry saturation;
- fail-static behavior for every non-droppable queue exhaustion;
- exact accepted/applied actuator acknowledgement matching;
- stale, duplicate, mismatched and lost-acknowledgement rejection;
- USB command bursts, GNSS load and malformed input, environment delay and
  transport backpressure;
- exact post-Campaign-B controller replay through receiver invalidation and
  explicit recovery.

The repaired source passed 701 repository tests with two expected
platform-specific skips, plus the pinned firmware matrix: 19 supported builds
passed and seven intended compile guards failed as designed. The final
verification after the live proof also covers the raw-framing validator rule:
an already-buffered, pre-protocol USB-open fragment is outside the OTIS stream,
while any orphaned continuation after the first OTIS header or record remains a
hard error.

## Exact live artifact

| Item | Exact identity |
|---|---|
| Firmware commit | `6ac3ae66861fedf3a90930b16332e5d0368c6dbb` |
| Firmware source SHA-256 | `7e7175422c9c8aac9d61672dd6867d202127eec347f815eec3c43ad4b9ac6fbf` |
| Configuration SHA-256 | `a2d4e934e612682cc47db261a24dc0b50561ca6013338e161f265b5c94b67705` |
| Build-manifest SHA-256 | `2a2a0e7c756335556d02100bb9aee85e2b83bc3d3ad1e0f409c0ce531c1f3a85` |
| UF2 SHA-256 | `ed6f726a56a6efe166208902b96194e300ed8ebe5029d4be727bebbe7d216bd2` |
| Firmware profile | `cx317_pps_gated_i_only_preview` |
| Firmware identity | `CX317_DUAL_CORE_POST_CAMPAIGN_PREVIEW_V1` |

The first V2 mechanism run correctly implemented controller behavior but
failed its evidence gate because Core 0 output could interleave with a chunked
Core 1 EST/CTL frame. The V3 artifact serializes each complete preview frame
while Core 1 continues capturing into bounded queues. The host timed-close path
also drains only an in-flight line to its newline. V2 remains preserved as a
failed diagnostic and is not pass evidence.

## V3 live proof

Run:
`runs/cx317_bounded_closed_loop_acquisition/campaign_20260803T080615Z/stage6/dual_core_live_v3_20260804T110756Z`

The 4,801-second proof executed the complete frozen mechanism schedule:

1. exact live identity and one idempotent retained-state acknowledgement;
2. warmup and four selected 600-second estimates;
3. 60 `CONFIG?` requests at approximately 1 Hz under Core 0 service load;
4. controlled receiver-metadata invalidation, five non-actionable fault
   decisions, live metadata requalification and explicit recovery;
5. post-recovery cadence holds and a terminal inside-deadband preview;
6. a final queue/authority status query and complete-line timed close.

Observed evidence:

| Gate | Result |
|---|---:|
| REF/CNT/SNP continuity | 4,801 each; sequences `12..4812`; PASS |
| Raw snapshot/count parity | zero adjacent mismatches; PASS |
| Estimates | 2,877 total, four selected; exact host parity; PASS |
| Control decisions | 11, including five fault decisions, one recovery and two previews; exact host parity; PASS |
| Terminal selected error | `-0.003333333880 Hz`, inside frozen V2 deadband |
| Schedule | 65 exact commands; PASS |
| Host transport | zero parser, UTF-8, reconnect, rejection or partial-line errors |
| Queues | no partition fault; required critical records present; zero telemetry drops |
| Authority | `actionable=false`, `actuation_authorized=false`, active update codes `0` |
| DAC/ACT evidence | one idempotent manual DAC row; zero active transaction rows |

The raw log begins with a partial RP2040 core diagnostic already buffered when
USB serial opened. It precedes the first OTIS protocol header and therefore is
not an interrupted OTIS record. The remainder of the stream, including every
measurement and all loaded-service output, is completely framed. This boundary
case is explicitly distinguished from in-stream interruption by the validator
and its regression tests.

The run-local frozen report is
`reports/STAGE6_DUAL_CORE_LIVE_PROOF.md`; its JSON proof is
`derived/stage6_dual_core_live_proof_v1.json`.

## Immutable evidence

- Snapshot state: `complete`
- Snapshot artifacts: 11
- Snapshot digest:
  `666761e143601f7fa6cefb400c4909d018b2819d7a48f82aae7fe64785622925`
- Evidence-manifest file SHA-256:
  `7dd797698e7f657420af833932845f92fd0816e91919485d973079ac4dde96fe`
- Post-seal generic validation: PASS; the header-only active transaction table
  is the expected explicit no-actuation artifact.

## Scope and limitations

This stage proves timing/control-state isolation from bounded service load,
exact preview parity, receiver invalidation/recovery behavior, queue accounting
and absence of a feedback-derived write. It does not prove calibrated frequency
accuracy, UTC traceability, phase lock, holdover, physical waveform margin or
active cross-core transaction execution. The nearby SHT41 measurement remains
environment context rather than CX317 case or oven temperature.

## Exit decision

Stage 6 passes because timing capture and estimator/control state remained
continuous under the declared Core 0 load, all non-droppable messages were
accounted, the fault/recovery sequence replayed exactly, transport framing was
clean throughout the OTIS stream, and no feedback-derived DAC write occurred.

Stage 7 may begin only from the last confirmed static code `0xA82A`, using the
checked-in revised Stage 7 prompt and retaining the exact authoritative V2
deadband for Parts A and B. The required shadow analysis remains strictly
non-actionable.
