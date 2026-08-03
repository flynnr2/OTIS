# PPS Cumulative Snapshot Span Estimator

## Status and scope

`PPS_CUMULATIVE_SNAPSHOT_SPAN_V1` is a host-only, observe-only analysis
contract for the accepted
`pio_wait_cumulative_snapshot_dma_v1` PPS-gated backend. It does not select a
control estimator, controller cadence, DAC step, or firmware behavior. It
never authorizes actuation.

The implementation is
`host/otis_tools/pps_cumulative_span_estimator.py`; its strict configuration is
`profiles/estimators/pps_cumulative_snapshot_span_v1.json` and its schema is
`schemas/pps_cumulative_snapshot_span_config_v1.schema.json`.

## Method contract

For each pair of adjacent, same-session, accepted raw `SNP` records, the
estimator computes the modulo-32-bit down-counter delta. It accepts that delta
only when the reconstruction is unambiguous and the corresponding `CNT` row
has exactly the same count and boundary timestamps. Both snapshot endpoints
must map uniquely to adjacent rising `REF` records.

For a span containing `N` accepted adjacent intervals:

```text
total_contiguous_counted_edges = sum(each accepted adjacent modulo-32-bit delta)
authoritative_frequency_hz = total_contiguous_counted_edges / (N * 1.0 s)
count_increment_hz = 1 / (N * 1.0 s)
```

The total is bounded as an unsigned 64-bit quantity. The implementation does
not subtract only the two span endpoints, because that would silently discard
one or more complete 32-bit wraps. RP2040 timer-normalized frequency is named
and emitted only as a diagnostic; it is not the authoritative denominator.

Every output preserves the session, control epoch, first and last `SNP`,
`CNT`, and `REF` identities, span, method identifier, and configuration hash.
Overlapping windows are explicitly marked as non-independent decisions.

## Fail-closed behavior

No span bridges an invalid interval, session boundary, sequence discontinuity,
reference association failure, snapshot fault, counter zero/saturation,
FIFO/DMA/ring fault, parser/transport loss, reset evidence, DAC control epoch,
or declared settling exclusion. A fault ends current support. A later estimate
requires a fresh pair of endpoints and enough new continuous intervals for its
span. There is no retroactive repair.

If a run contains DAC evidence, an explicit interval-to-control-epoch policy is
required. Without it, all estimates are withheld. Unknown aperture,
reference, calibration, and combined uncertainty components remain
`unavailable`; empirical spread is not relabelled as calibrated uncertainty or
isolated firmware jitter.

## Numerical provenance

The table distinguishes architecture bounds from characterization choices.
Absolute-maximum component ratings are not used as operating targets.

| Parameter and units | Acceptance/rejection threshold | Disposition | Source and location | Conditions/applicability | Calculation/conversion | Uncertainty and safety margin | Measured result | Result | Consequence of failure |
|---|---:|---|---|---|---|---|---|---|---|
| Accepted reference interval, s | nominal `1.0` for each accepted PPS interval | architecture screen | `docs/datasheets/adafruit-ultimate-gps.pdf`, p. 13, PPS output described as once per second; accepted backend contract in `docs/50_SOFTWARE/PPS_GATED_RATIO_BACKEND_DESIGN.md`, §§3–5 | Actual rig uses the GPS PPS path; exact fitted receiver revision and calibrated timing uncertainty are not established | `N` accepted PPS intervals give nominal duration `N × 1.0 s` | Reference/cable/aperture uncertainty unavailable; no calibrated-accuracy claim | Stage 1: 1,234 adjacent accepted intervals; diagnostic timer mean 0.999995469 s | pass for estimator architecture; characterization-only for timing | Reject the affected interval and every span crossing it |
| Snapshot counter width, bits | exactly `32`, down-counting and modulo-wrapping | architecture screen | `docs/50_SOFTWARE/PPS_HARDWARE_SNAPSHOT_REPLACEMENT_ARCHITECTURE.md`, §§4–5; `firmware/arduino/otis_nano_rp2040_connect/otis_pps_snapshot_backend.*` | Exact accepted PIO backend only | Adjacent delta is `(opening - closing) mod 2^32` | Width is architectural; ambiguity remains if an adjacent interval could contain a full wrap | Stage 1 raw backend and all 1,234 reconstructed deltas matched `CNT` | pass | Reject backend mismatch or ambiguous interval; no estimate |
| Adjacent full-wrap exclusion envelope, captured edges/s | `< 133,000,000` used as a loose upper envelope, not a supported input-frequency claim | architecture screen | `docs/50_SOFTWARE/PPS_PIO_PROOF_AND_VERIFICATION.md`, §§1, 7; accepted firmware macro `OTIS_PPS_SNAPSHOT_MAX_CAPTURED_EDGE_RATE_HZ`; RP2040 datasheet, §2.15.6.1 maximum system clock | Applies only to proving that one nominal PPS interval is far below `2^32` edges; it is not an electrical or throughput specification for D8 | `133,000,000 × 1.0 = 133,000,000 < 4,294,967,296` | More than 32× arithmetic headroom at nominal 1 s; physical phase/duty margin remains untested | Stage 1 maximum adjacent count 9,999,993 | pass as architecture screen | Mark interval `counter_full_wrap_cannot_be_excluded`; no span may cross it |
| Span accumulator width, bits | at least `64` | architecture screen | documented calculation from the accepted 133 MHz loose envelope and 600 s candidate span | Applies to host integer total only | `133,000,000 × 600 = 79,800,000,000`, below `2^64 − 1 = 18,446,744,073,709,551,615` | Arithmetic headroom about `2.31 × 10^8`; does not address metrology uncertainty | Synthetic 600 s and multi-wrap cases exact | pass | Raise overflow and emit no result |
| 10 MHz 32-bit wrap time, s | characterization reference `429.4967296` | characterization reference | CX317 bulletin `docs/datasheets/cx317.pdf`, p. 2, nominal 10 MHz; documented calculation | Applies to nominal CX317 frequency, not an accuracy guarantee | `2^32 / 10,000,000 = 429.4967296 s` | Nominal calculation only | 600 s synthetic and Stage 1 windows use adjacent accumulation, never endpoint-only subtraction | pass | Endpoint-only span subtraction is prohibited |
| Candidate spans, s | `1, 5, 10, 30, 60, 120, 300, 600` | characterization reference | Stage 2 programme prompt, “Candidate spans and comparisons” | Analysis grid only; no span is selected for control | Count increments are respectively `1, 0.2, 0.1, 1/30, 1/60, 1/120, 1/300, 1/600 Hz` | Programme-defined conservative characterization grid; no physical sufficiency or control bandwidth is implied | Stage 1 supports every candidate; ECS comparison supports every candidate | characterization-only | A missing span is a Stage 2 implementation failure, not a plant rejection |
| Span uncertainty, Hz | all required components must be known before claiming calibrated uncertainty; otherwise unavailable | model-applicability bound | master programme rules; Stage 2 prompt, “Required estimator semantics” | Current rig lacks a complete aperture/reference/calibration uncertainty budget | No conversion is permitted from empirical spread to calibrated uncertainty | Counter aperture, reference, calibration, and correlation components unavailable | Output reason codes name each missing component | unavailable | Do not use results as calibrated accuracy or an uncertainty-qualified controller input |

## Verification and evidence use

Focused tests cover exact integer and fractional results, zero/one/multiple
wraps, accumulation exactly once, startup and recovery, session and DAC
boundaries, raw-source cross-checks, every fault class, nominal versus timer
denominators, determinism, and source immutability.

The sealed Phase 5 ECS run is used only for deterministic anti-regression. Its
16 MHz spread is not a CX317 performance specification. The Stage 1 CX317
smoke is a topology-appropriate sanity fixture, but its short-term spread does
not by itself select an estimator span or control policy.
