# count_observations_v1.csv

## Purpose

`count_observations_v1.csv` records gated or windowed counts of a high-rate source such as a TCXO, OCXO, VCXO, divided XCXO, or frequency-output module.

It exists because a 10 MHz or 16 MHz oscillator must not be represented as a raw emitted edge stream. The firmware should count edges in hardware or a deterministic capture fabric and emit compact observations.

## Schema

| Field | Type | Meaning |
|---|---|---|
| `record_type` | enum | compact record tag; `CNT` |
| `schema_version` | uint | schema revision; currently `1` |
| `count_seq` | uint64 | monotonic count-observation sequence within the run |
| `channel_id` | uint16 | oscillator/count observation channel |
| `gate_open_ticks` | uint64 | timestamp of gate/window open in `gate_domain` |
| `gate_close_ticks` | uint64 | timestamp of gate/window close in `gate_domain` |
| `gate_domain` | string | timing domain used for gate timestamps |
| `counted_edges` | uint64 | number of observed source edges during the gate |
| `source_edge` | enum | counted source edge: `R`, `F`, or `B` |
| `source_domain` | string | named source being counted, e.g. `h0_tcxo_16mhz` |
| `flags` | uint32 | numeric bitmask from `capture_flags_v1` |

## Example

```csv
record_type,schema_version,count_seq,channel_id,gate_open_ticks,gate_close_ticks,gate_domain,counted_edges,source_edge,source_domain,flags
CNT,1,42,2,1600000000,1616000000,rp2040_timer0,16000000,R,h0_tcxo_16mhz,0
```

## Semantics

A count observation says:

> Between these two gate timestamps, this many edges of this source were counted.

It does not by itself assert that the oscillator is disciplined, accurate, locked, or steerable. Those are higher-level derived or control states.

## H0 Use

For the H0 prototype, `CH2` is the reference TCXO/XCXO observation role. The ECS-TXO-5032-160-TR 16 MHz TCXO may be observed through count windows rather than raw edge emission.

Future GPSDO/XCXO designs may use the same contract for OCXO/VCXO observations, divided outputs, reciprocal counters, or PPS-to-PPS frequency estimates.
