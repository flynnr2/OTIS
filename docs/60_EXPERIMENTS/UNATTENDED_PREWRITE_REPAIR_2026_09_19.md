# Pre-write telemetry binding repair — 19 September 2026

The replacement bench attempt reached a protected pre-write hold at 16:19:00Z.
Four host-required keys were absent from the frozen firmware: the two retired
`capture` drop counters and receiver-owned raw-PPS/aggregate eligibility. No
SETUP, ARM or DAC transaction occurred. This is a platform escape into a
campaign, not a scientific rejection. The fixture used by the previous host
rehearsal generated the same invalid expectations and therefore concealed the
producer/consumer mismatch.

The host v2 contract now requires the three emitted capture backend fault and
queue-loss fields to be zero. Receiver metadata remains independently qualified;
firmware's exact GNSS, D14/D8 and partition SETUP gates remain required. The
existing authoritative capture cohort gate still precedes SETUP. Continuous
health checking uses the same current capture fields. Missing current fields
remain a hold. No firmware, controller policy, timing semantics, command cadence,
actuation bounds, wall deadline or closure criterion changes.

The detached launcher also creates the parent directory before checking free
space. This directly covers the earlier fresh-checkout failure and starts no
hardware operation when storage is insufficient.

Verification: 120 focused tests passed, including an independent firmware-emitter
inventory check for required non-ACTIVE keys, fail-closed health/SETUP cases,
startup census, capture cohorts, GNSS and launcher checks. All 168 frozen firmware
input files were checked byte-for-byte against the retained build manifest and
match. The existing Intel build and binary are reused. The new frozen host spec
passed the actual detached PTY operational rehearsal: all nine boundaries,
two progressive transactions, metadata recovery, unanswered review with continued
capture/lease service, transport obstruction, independent simulated abort,
closure, analysis, sealing and registration. The simulated abort is rehearsal
only and does not authorize aborting the physical bench attempt.

Frozen identities:

- Host revision implementing the repair: `43fe448`.
- Run spec: `88d37ca319a085d51904017ccc0cbd5208c14de1409699554088cda440af837c`.
- Host toolset: `fcddf46394b9c269343ca72feab60e66125056192a5c2106ec29a25e8352bb7a`.
- Rehearsal package: `d7406b606c3c33be81a5286ae8386eb31696a5785c8ba116d66dc250dcaec1d7`.
- UF2, unchanged: `d7e35695eeafdf32fe34ff196b1bfcc8cf98dc7e0b6c4184cde5c91fdf19127e`.

The source inventory regression establishes producer declarations; the PTY
establishes the host path. Neither proves actual firmware publication or physical
qualification. Retain the exact live pre-actuation gates.

The existing held run and original reports remain unchanged. Do not hot-reload,
clear the hold, stop capture or restart the run on the strength of this repair.
The campaign allowed one replacement entry, already consumed. An operator must
explicitly authorize orderly closure of that attempt and any new entry. Preserve
abort delivery before capture closure and archive the held evidence even if its
scientific analysis is incomplete. A new attempt uses a fresh directory and its
own fixed window; it must not be represented as continuation of accepted progress.
