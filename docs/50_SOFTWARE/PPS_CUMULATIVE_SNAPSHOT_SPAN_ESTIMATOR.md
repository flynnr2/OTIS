# PPS accepted-span frequency estimator

## Status and scope

`PPS_ACCEPTED_SPAN_FREQUENCY_V1` is the integer accumulation method in
`OTIS_PPS_GATED_FREQUENCY_ESTIMATOR_V1`. Its profile format remains version 1;
its changed configuration hash binds accepted-span semantics. The current
integration candidate replaces raw adjacent-aperture admission with the shared
D14 selection policy. An exact fixed-image build, complete release gate and
bench rehearsal remain required before physical use.

The selected profile and schema are
`profiles/estimators/pps_gated_frequency_estimator_v1.json` and
`schemas/pps_gated_frequency_estimator_v1.schema.json`. They bind the exact
reference-acceptance policy. That policy is embedded with its original bytes
in the campaign's authoritative inputs, and projected into a checked firmware
header. A current checkout's policy cannot substitute for frozen campaign inputs.

## Raw observations and accepted spans

Raw REF, SNP v2 and adjacent CNT preserve the captured words. The selector
operates once on each immutable PIO-owned record; REF is a derivative display,
not an independent association input. Eight in-window raw intervals establish
an accepted anchor without retrospectively creating accepted spans. The first
subsequent admitted edge closes accepted span 1.

An APS v1 record identifies a same-session, same-acceptance-epoch count between
actual opening and closing cumulative D8 snapshots. Its interior may include
up to eight excluded early candidates. Every interior raw observation must be
structurally trustworthy and adjacent in its own sequence domain. The count
must equal both the endpoint difference and the sum of the retained raw CNT
fragments. Raw fragments can retain cadence-rejection flags while their
complete accepted span remains valid.

The inclusive tracking window is nominally 1,000,000 ± 1,250 local microsecond
ticks from the last accepted anchor. Admission requires the entire possible
PIO-recognition interval (including endpoint uncertainty) inside that window. An excluded candidate changes neither
that anchor nor its deadline. The RP2040 interval is an admission coordinate,
not the frequency denominator. An in-band spurious edge cannot be distinguished
from a genuine PPS by this rule alone.

## Accumulation and source identity

For N consecutive accepted spans in one acceptance epoch:

```text
total_counted_edges = sum(each independently reconstructed APS count)
frequency_hz = total_counted_edges / (N * 1 nominal second)
count_increment_hz = 1 / N
```

The selected estimate uses exactly 600 spans, without overlap. The separate
60-span diagnostic overlaps and has no actuation authority. Integer totals
are unsigned 64-bit values. Subtracting only the endpoints of an entire
600-span estimate is invalid: the D8 counter normally wraps within that span.

EST v3 carries capture session, acceptance epoch, accepted opening/closing
ordinals, actual raw SNP/D14 endpoints and the exact APS range. The selected
600-span delta is in accepted coordinates; raw ordinals can advance farther
when a candidate is excluded. The diagnostic ring retains its actual raw
opening endpoints rather than incrementing a raw ordinal by assumption.

Both phase and frequency consume the same immutable selected span. Phase
publication and accepted-span evidence admission precede the first dependent
active decision. Active records propagate the acceptance epoch and accepted
range, independently of capture session, phase epoch and DAC epoch.

## Holds and requalification

An early excluded edge alone resets neither frequency nor accumulated phase.
Receiver metadata qualification independently gates actuation and preserves
otherwise valid measurement history. CPU lateness causes a diagnostic hold;
it cannot establish physical PPS absence. A later, causally admissible paired
observation determines whether the accepted interval remains continuous.

An actual acceptance loss, unbridgeable source gap, association/capture fault,
or ambiguous coordinate ends support. The next selected estimate requires 600
new spans in one acceptance epoch. No qualification sum crosses those epochs.
A healthy DAC change preserves continuous accumulated raw relative phase,
but resets the selected frequency window and phase's frequency support.

After DAC application, a span contributes to the selected estimate only when
its actual accepted opening is at or beyond the exact settling deadline. An
excluded raw candidate after that deadline cannot hide an earlier accepted
opening. Startup and receiver qualification requirements remain separate.

## Retained evidence and limitations

A recorder attaching mid-run retains any incomplete prefix without granting
it source authority. Its first complete APS has a producer-declared opening
anchor; this does not claim the original acquisition was recorded. Feedback
requires 600 consecutive, completely retained and independently reconstructed
APS records in one capture session and acceptance epoch. Pending raw records
from another output queue cause a wait, not invented source coverage.

The conservative per-fragment and per-span count bound is 159,600,000 edges
(133 MHz times 1.2 local seconds). This excludes ambiguous full-counter wraps;
it is not an electrical input-frequency specification. A very short interior
fragment may have zero counts, but a complete accepted span must be positive.

Reference, cable, capture aperture, calibration and combined uncertainty remain
unavailable. A clean policy state or controller lock is not calibrated accuracy.
The retained split-event replay is counterfactual evidence for this policy;
it cannot change the earlier attempt's frozen uninterrupted qualification.
