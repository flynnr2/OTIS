# Canonical Event Model

## Purpose

The canonical event model defines the raw observation records emitted by OTIS
capture firmware and persisted by the host.

It should be:

- minimal;
- stable;
- explicit;
- lossless;
- application-neutral.

The raw capture layer does not encode events as application conclusions.
Firmware measurement and control layers may derive frequency/phase estimates
and make bounded discipline decisions while retaining canonical observations
unchanged. Host software independently records, replays and interprets evidence.

## Architectural Principle

```text
Firmware capture layer = deterministic canonical observations
Firmware instrument    = explicit measurement, qualification and bounded control
Optional host          = recording, independent replay and analysis
```

## Canonical Observation Records

OTIS currently distinguishes two raw observation record types:

| Conceptual type | Compact tag | Meaning |
|---|---|---|
| `EVENT_CAPTURE` | `EVT` | external/user timing event captured by the timing fabric |
| `REF_CAPTURE` | `REF` | declared reference event captured by the timing fabric |

Both are raw observations. Neither encodes application-specific conclusions.

`EVT` is for user/external event channels such as photogates, comparator
crossings, oscillator comparison pulses, encoder transitions, RF timing pulses,
or laboratory triggers.

`REF` is for declared reference inputs such as GNSS PPS or another reference
event used for discipline, syntonization, synchronization, or later comparison.

Do not encode GNSS PPS as `EVT` plus a semantic flag. Use `REF`.

## Conceptual Record Structure

```text
record_type,
schema_version,
event_seq,
channel_id,
edge,
timestamp_ticks,
capture_domain,
flags
```

`capture_domain` is the native timing domain in which `timestamp_ticks` was
latched. It is not necessarily UTC, and it is not necessarily the same thing as a
reference domain or oscillator source name.

## Examples

```csv
EVT,1,123456,0,R,9876543210,MAIN,0
EVT,1,123457,0,F,9876548120,MAIN,0
REF,1,123458,1,R,9880000000,MAIN,0
```

In this example, the `REF` row is a captured reference event, such as a GNSS PPS
edge, latched in the local `MAIN` capture domain.

## Flags

Flags describe capture status and quality metadata. They must not carry primary
record-type semantics.

For example, use:

```text
REF,...,0
```

not:

```text
EVT,...,PPS_CANDIDATE
```

Reference identity, validity, lock state, and discipline conclusions should be
represented by explicit reference records, configuration/provenance records, or
discipline-state telemetry rather than by overloading `EVENT_CAPTURE`.

## Why this split matters

The same raw observation stream may represent:

- pendulum photogate events;
- GNSS PPS edges;
- oscillator comparison pulses;
- TIC measurements;
- HAM/radio timing experiments;
- encoder transitions;
- laboratory trigger signals.

Interpretation should therefore live host-side.

## Canonical OTIS Run Artifacts

A complete OTIS run should contain:

```text
raw_events.csv
health.csv
run_manifest.json
selected_profile.yaml
```

Everything else should be reproducible from those artifacts.

## Derived Products

Derived outputs may include:

- pendulum cycle tables;
- PPS phase error;
- Allan deviation;
- oscillator stability reports;
- heatmaps;
- FFT analysis;
- impulse classification;
- timing residual analysis.

These are not firmware responsibilities.

## Retired D10 PPS witness experiment

Historical H1 anomaly captures may contain `pps_d10` and
`pps_dual_observer` status rows from a temporary experiment that connected D10
to PPS. Current firmware no longer implements or emits that experiment.

Those historical `STS` records included:

- `pps_d14.raw_edge_count`, `accepted_pps_count`, `rejected_short_count`,
  `rejected_long_count`, `last_raw_timestamp`, `last_raw_interval`,
  `last_accepted_timestamp`, `sampled_high_count`, `sampled_low_count`;
- `pps_d10.raw_edge_count`, `last_edge_timestamp`, `last_interval`,
  `short_interval_count`, `sampled_high_count`, `sampled_low_count`,
  `buffer_overflow_count`;
- `pps_dual_observer.d14_raw_minus_d10_raw`, `agreement_state`,
  `burst_active`, and `burst_count`.

Preserve those rows as historical raw evidence and interpret them only with the
revision and manifest that created them. In the current canonical topology D10
is `CH0`, an external event/edge input to be measured against the disciplined D8
oscillator; D14 alone is `REF`/PPS.

## Instrument operation evidence

The autonomous instrument adds ICM command receipts, IWR internal writes, IAP
application results, IDC controller decisions, IRS response diagnostics and IST
state transitions. These are derived/control records, never replacements for
REF/SNP/CNT/APS/EST source evidence. Their exact schema and domain fields are in
`data_contracts/otis_firmware_host_contract_v1.json` (contract V2).

A record sequence is allocated before optional output publication. Bounded loss
counters and current snapshots distinguish missing delivery from a healthy
complete stream. Detached operation preserves control evidence internally only
for the current bounded operation; it is not a historical archive. Full replay
claims require the relevant retained sources and lifecycle records with exact
session, code, epoch and ordering joins.
