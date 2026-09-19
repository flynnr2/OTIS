# D14 accepted-reference selection

## Status and scope

This is the prospective acceptance contract and integrated measurement candidate for
the existing D14/D8 instrument. Numerical parameters are defined once in
`reference_acceptance_policy_v2.json`. Selection has no direct actuator authority. The candidate connects one selected
span to both firmware measurement consumers and the versioned host path.
Promotion to a physical campaign requires a complete release gate, exact
firmware build and actual operational-path rehearsal.

Raw adjacent apertures remain recorded under their original semantics; APS
records express acceptance separately. This contract does not change any
closed experiment's acceptance criteria or scientific outcome.

## Evidence supporting the initial window

On 11 September 2026 the operator reported that another instrument using the
same GPS breakout board, with similar occasional glitches, has successfully
used a tolerance of ±1.25 ms. This is supporting operator testimony, not an
independently reviewed qualification of the other instrument.

The retained OTIS package
`43a596f175122b632bb40a410b33c3bd956923a89d6d09ef0114c178582d0739`
contains 52,310 REF observations. Its 52,307 ordinary adjacent intervals range
from 999,976 to 1,000,016 microseconds, with median 999,995 microseconds in the
RP2040 local coordinate. The remaining two intervals are 246,294 and 753,707
microseconds. The source REF CSV SHA-256 is
`4cd572e0d995b10859d62d32f334a5631e0b6c1d9ea8a9978b77bad755442589`.
These observations support a starting engineering margin. They do not measure
absolute PPS accuracy or establish behaviour over every temperature, startup
condition, receiver state, or electrical disturbance.

## Capture before selection

Selection consumes one canonical SNP v2 observation per committed PIO FIFO
word. `snapshot_sequence` and `reference_sequence` identify that same word.
There is no independent GPIO-to-PIO association step. The emitted REF row is a
same-owner raw derivative retained for integrity and replay; REF matching does
not grant or veto SNP authority.

Keep every raw REF, SNP and adjacent CNT unchanged, including intervals that
the raw aperture diagnostic rejects. A selected span is a separate derived
observation. It identifies its actual raw endpoints and every excluded interior
candidate. REF event-emission numbers remain distinct from the equal SNP
snapshot/reference ordinal and from accepted-boundary ordinals.

## Acquisition and tracking

The initial seed is one trustworthy paired raw observation. Acquisition then
requires eight consecutive trustworthy raw intervals inside the inclusive
range 998,750–1,001,250 microseconds. An out-of-window interval resets that
consecutive count; a trustworthy current candidate can seed a fresh sequence.
No earlier interval is promoted retrospectively. Completion establishes the
tracking anchor; the first subsequent admitted interval is the first selected
span. This short reference acquisition does not waive estimator history,
actuator settling, receiver metadata, or existing startup requirements.

While tracking, evaluate each candidate relative to the last accepted anchor.
The FIFO CPU service delta is not a D14 edge interval, so selection uses the
complete possible recognition interval:

```text
minimum = service_delta - candidate.timestamp_uncertainty_ticks
maximum = service_delta + anchor.timestamp_uncertainty_ticks
```

A candidate is early only when `maximum < 998750`; it changes neither the
accepted anchor nor the reference-loss deadline. Admission requires
`minimum >= 998750` and `maximum <= 1001250`, complete intervening raw
continuity, and unambiguous cumulative D8 count. An interval that overlaps a
window boundary loses qualification as `observation_age_ambiguous`; it is not
silently classified early or late.

The admitted candidate becomes the new anchor. There is no adaptive tolerance,
retrospective selection of a more favourable edge, or silent estimator-driven
change to this policy. The selected D8 count comes from the cumulative
hardware endpoints; the local microsecond interval is an admission coordinate,
not a substitute frequency reference.

A candidate whose minimum possible interval exceeds 1,001,250 microseconds
cannot close a one-second span. Loss of the expected accepted boundary ends
tracking and requires a new acceptance epoch and fresh acquisition. Do not manufacture a missing PPS
timestamp or classify a two-second span as one nominal second. Raw capture
continues through acquisition, exclusion and loss.

One accepted span may exclude at most eight early candidates. A ninth ends
tracking with an explicit exclusion-budget reason. This is a finite selection
and retained-source bound, not evidence that any particular burst fits the
physical capture queues. FIFO status and continuity checks still apply.

## Continuity and expiry

Every intervening raw SNP must remain available, in sequence and in the same
capture session. Counter movement must satisfy its physical upper bound and
declared rollover semantics. Missing or duplicated single-owner ordinals,
nonzero FIFO status, unknown or half-range timestamp uncertainty, ambiguous
movement, and session changes prevent bridging. Capture-session identity is not an
acceptance epoch or a phase epoch.

Use the current producer's conservative gross count bound: 133 MHz times
1,200,000 local microsecond ticks, or 159,600,000 edges. Apply it to both each
interior counter delta and the complete accepted span. Do not estimate the
physical duration of a very short fragment from interrupt-observed timestamp
differences to impose a tighter rate limit. Such a fragment may legitimately
contain zero D8 edges; a complete acquisition interval or selected one-second
span must contain a positive count. Cadence-ineligible intervals outside the
admission window are not promoted into count measurements by this bound.

Accepted-boundary ordinals have their own modular unsigned 32-bit domain;
they must never be substituted for raw SNP or D14 source ordinals. Acceptance
epochs are separate unsigned 32-bit identities whose exhaustion fails closed
instead of wrapping into a prior epoch's identity.

Reference expiry is anchored conservatively to the earliest possible
recognition coordinate, `anchor_service - anchor_uncertainty`. Continued early rogue
traffic cannot make the accepted reference appear present. However, CPU time
passing a deadline does not prove that no qualifying hardware observation is
queued. A live expiry decision requires an explicit, session-bound producer
frontier proving that earlier captured observations have been drained and
serviced. A delayed or incomplete frontier causes a diagnostic control hold;
it cannot invent physical reference loss or discard an in-window observation.

The native candidate exposes this frontier requirement explicitly. Its caller
must not infer proof from process liveness, an empty host log, or a recent
status generation. The current live owner deliberately does not call that expiry interface. It
holds new authority when the accepted anchor is overdue, preserves history
while evidence is delayed, and lets a later paired candidate establish a
continuity loss. It never manufactures a complete producer frontier. A
source-coordinate ambiguity withdraws model qualification with an explicit
reason, without asserting physical edge absence.

The existing PPS health snapshot retains `reference_acceptance_last_loss_reason`
alongside the loss count and accepted identity. It starts as `none` and remains
sticky through recovery until the next loss replaces it. In particular,
`observation_age_ambiguous` preserves the CPU projection failure that raw
timestamps alone cannot explain. This is the latest loss cause, not a claim
that periodic status preserves every intermediate transition in a burst.

## Limits of timing admission

The first trustworthy candidate inside the window is admitted under this
policy. A spurious edge inside that same window is not distinguishable from a
real PPS by this timing criterion alone. A later edge must not rewrite an
already emitted accepted span. Tests must expose this limitation; they must
not call a plausible interval proof of receiver correctness.

The policy contains gross extra-edge disturbances such as the observed
quarter-second event. It is not an electrical debounce guarantee, a cure for
in-band reference corruption, or a substitute for investigating the receiver,
line and capture path. In-band ambiguity remains a reason to reconsider the
policy or hold control when independent evidence establishes the discrepancy.

## Required source identities and promotion boundary

The derived admission/span evidence must bind the frozen policy, capture
session, acceptance epoch, candidate raw SNP identity (retaining both equal consumer fields), opening
and closing raw identities and timestamps, accepted-boundary ordinals,
excluded-candidate count, exact D8 edge count, one nominal PPS interval,
disposition and reason. Raw-counter and timestamp domains remain explicit.

Frequency and phase must consume the same accepted-span object. A rejected
candidate alone must not be passed to either as an invalid measurement that
erases otherwise continuous history. A genuine lost reference or continuity
break creates explicit requalification boundaries. Preserving phase across an
excluded early candidate requires the complete accepted-span proof; it cannot
be inferred from a recent estimate or small phase error.

The selected estimator must identify exactly 600 accepted spans in one
acceptance epoch. Its current convention of 600 adjacent raw snapshot
intervals cannot silently acquire this meaning. Version the derived EST and
phase source contracts and update producer, formatter, parser, replay,
acquisition-source admission, control health and qualification accounting
together. Settling is evaluated against the accepted span's actual opening
boundary, which may precede its last excluded raw candidate.

The prospective uninterrupted qualification requires one acceptance epoch for
its entire qualified duration. Excluding a provably continuous early candidate
does not itself break that epoch. A genuine acceptance loss does; counts from
different epochs cannot be summed to manufacture an uninterrupted result.
The earlier prefix remains useful evidence, and the host retains its existing
review and explicit-operator-closure boundary.

Promotion is one finite producer-to-consumer integration: single-owner FIFO capture,
raw count reconstruction, selection, frequency and phase consumers, their
emitted records, real recorder, host source checks, control admission, analyzer
and sealing. The native candidate alone establishes none of those unexercised
live boundaries and does not authorize another 72-hour run.

## Current protocol and attachment boundary

The integrated candidate emits APS v1, EST v3, RPH/PHE v2, AHY/ACT v3 and AHM v2.
Raw REF and CNT retain v1; SNP is the current-only v2 service-coordinate contract. The exact wire layouts are in
`otis_firmware_host_contract_v1.json`; ACTIVE snapshot v2 binds the current
acceptance epoch, accepted ordinal, policy and health coherently.

A late-attached recorder may begin after the original reference acquisition.
The first completely retained APS opens at a producer-declared accepted anchor;
it does not prove unrecorded startup acquisition. Any APS whose opening or
interior raw observations predate retention remains unqualified prefix evidence.
Feedback requires 600 fully retained consecutive APS records in one session and
acceptance epoch. Earlier closed experiments do not acquire this attachment or
acceptance contract retrospectively.

The policy bytes are embedded in the authoritative-input set and bound by the
run manifest's `reference_acceptance` identity. The generated firmware policy
header and fixed build check those exact bytes. Numerical policy changes
therefore change firmware/profile/campaign identity together.
