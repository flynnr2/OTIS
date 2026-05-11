# capture_flags_v1

## Purpose

`capture_flags_v1` defines the first canonical numeric flag allocation for OTIS capture, count, reference, and health/status records.

CSV records carry numeric bitmasks. Documentation, tooling, and reports may render symbolic names, but emitted records should remain compact and stable.

## General Rules

1. Flags describe quality, provenance, or processing status.
2. Flags must not change the primary semantic class of a record.
3. Unallocated bits must be emitted as zero.
4. A future schema may add flags, but existing bit meanings must not be redefined.
5. Record type remains primary: use `EVT`, `REF`, `CNT`, or `STS` rather than inventing semantic flags that disguise the record family.

## Common Flag Allocation

| Bit | Hex | Symbol | Meaning |
|---:|---:|---|---|
| 0 | `0x00000001` | `CAPTURE_OVERFLOW_NEARBY` | capture occurred near counter overflow or required overflow disambiguation |
| 1 | `0x00000002` | `CAPTURE_RING_OVERRUN` | capture/count/status ring overran before draining |
| 2 | `0x00000004` | `EDGE_ORDER_SUSPECT` | edge order, polarity, or pairing sequence was unexpected |
| 3 | `0x00000008` | `REFERENCE_VALIDITY_SUSPECT` | reference event was captured but source/reference validity was uncertain |
| 4 | `0x00000010` | `TIMESTAMP_RECONSTRUCTED` | timestamp includes deterministic reconstruction beyond a raw hardware latch |
| 5 | `0x00000020` | `SOURCE_HEALTH_SUSPECT` | input source, front end, or conditioning health was suspect |
| 6 | `0x00000040` | `PULSE_TOO_NARROW` | pulse width was below profile minimum |
| 7 | `0x00000080` | `PULSE_TOO_WIDE` | pulse width was above profile maximum |
| 8 | `0x00000100` | `RATE_TOO_HIGH` | observed rate exceeded profile or firmware service assumptions |
| 9 | `0x00000200` | `INPUT_STUCK_LOW` | input appeared stuck low over the relevant observation window |
| 10 | `0x00000400` | `INPUT_STUCK_HIGH` | input appeared stuck high over the relevant observation window |
| 11 | `0x00000800` | `DEBOUNCE_REJECTED` | event was rejected or marked because debounce/dead-time logic applied |
| 12 | `0x00001000` | `GATE_INCOMPLETE` | count observation gate did not complete cleanly |
| 13 | `0x00002000` | `COUNT_SATURATED` | counter saturated or exceeded representable range |
| 14 | `0x00004000` | `HOST_DERIVED` | record was produced by host tooling rather than directly emitted by capture firmware |
| 15 | `0x00008000` | `PROFILE_ASSUMPTION` | result depends on a profile assumption rather than a directly observed fact |

Bits 16-31 are reserved for future v1-compatible allocation.

## Pulse Quality Flags

Pulse-quality flags are intended for generic event inputs, photogates, comparators, open-drain signals, and similar front ends:

- `PULSE_TOO_NARROW`
- `PULSE_TOO_WIDE`
- `EDGE_ORDER_SUSPECT`
- `INPUT_STUCK_LOW`
- `INPUT_STUCK_HIGH`
- `DEBOUNCE_REJECTED`
- `SOURCE_HEALTH_SUSPECT`

A flag should make the row less trusted, not silently remove it from the raw artifact. Rejection/filtering belongs in a derived dataset or a clearly documented firmware policy.

## Count Quality Flags

Count observations commonly use:

- `GATE_INCOMPLETE`
- `COUNT_SATURATED`
- `CAPTURE_OVERFLOW_NEARBY`
- `RATE_TOO_HIGH`
- `SOURCE_HEALTH_SUSPECT`

A count row with a nonzero flag is still scientifically useful if the failure mode is explicit.

## Status Stream Flags

`STS`/health records may use the same flag namespace, but `severity` and `status_key` should carry most status meaning. Do not encode all status meaning solely in `flags`.
