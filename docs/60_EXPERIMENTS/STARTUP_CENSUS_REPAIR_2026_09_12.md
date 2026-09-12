# Startup census escape, 12 September 2026

The inhibited zero-write physical attempt at `539ff6a` flashed successfully,
then entered a host review hold before startup authority, SETUP or ARM. The
host selected complete ACTIVE generation 1, nonce 1312243200, before the first
PPS diagnostic block. The identity predicate also required those diagnostics
and reference tracking, so it froze a legitimate startup observation as an
incoherent census. This is a platform escape into physical entry, not evidence
of a D14/D8 failure or a rejected controller.

The diagnostic archive `startup-census-hold-539ff6a-20260912T074349Z.tar.gz`
was independently verified locally: 1,827,917 bytes, SHA-256
`e04bdb3d5bf6db1d87289a517b62a34b374a92383172982f8d91408f808e8ae6`.
All 18 manifest payload entries match their sizes and hashes; the manifest is
the nineteenth file, SHA-256
`1872a95667700308d2e52be98ca908183f7b7b742ff93a06c0eeb6e12f051880`.
It is a separately sampled diagnostic snapshot of an active acquisition,
not a seal or qualification result.

The first ACTIVE snapshot occupies health bytes 34980–40458, before any PPS
block. The first complete PPS diagnostic block subsequently reports accepted
ordinal/epoch/session 1/1/1, as does ACTIVE generation 2. The original census
had ACTIVE 0/1/1 and no PPS tuple: missing information, not numeric
contradiction. At export the reported capture parser/reconnect/rejection and
capture-drop counters were zero. The startup physical-aperture-incomplete
count of one remains evidence; this repair neither deletes nor reinterprets it.

The repair separates instrument identity from reference qualification. Census
uses the complete solicited ACTIVE identity, policy, session and controller
state. Reference and retained-source gates remain explicit at control,
qualification and terminal admission. No additional timer, startup sleep,
census retry or retained-supervisor adoption path is introduced.

The same predicate also compared independently emitted accepted ordinals for
exact equality. That comparison has no simultaneous producer guarantee and
is removed. Both views must qualify independently and agree on session and
policy. Before an origin is frozen, differing acquisition epochs defer origin
admission; after qualification, each view is checked against the retained
epoch. Raw observations and the uninterrupted qualification criterion remain
unchanged.

The escaped ordering is covered by a small byte-exact retained-health fixture
through the actual live reducer and first census/qualification consumers. The
process rehearsal also emits its first ACTIVE response without PPS diagnostics,
then supplies them in later observations. Separate cases retain identity and
session rejection, missing-reference control inhibition, acquisition handling
and independently advancing ordinals.

At the time of the repair, the running bench instance was unchanged. Its
immutable rejected census cannot
be retroactively admitted by this repair. Capture remains the responsibility
of the bench instance; closing it requires explicit operator direction. Any
subsequent physical attempt needs the corrected frozen host bundle and its
rehearsal, with the original hold retained separately.

Development verification: 729 selected tests passed, including the real
activation/manifest preparation roundtrip; the captured replay's three cases
also passed after the final additions. The normal process rehearsal passed
through two progressive transactions, obstruction, priority abort, analysis,
sealing and recovered registration. Delayed-command and exact committed-image
rehearsal results are retained with the delivery, rather than inferred from
these fixture results. Firmware source, configuration and toolchain inputs are
unchanged; the current build contract nevertheless binds the corrected host
revision into new binary provenance.

A delayed-command rehearsal initially failed after its second transaction on
`capture transport state is stale: age_s=143.601`; its total reported monotonic
runtime was 103.55 seconds. The combined failure output is retained. Its
ordinary pytest temporary package was subsequently cleaned up, so the source
of that age discrepancy cannot be established. An isolated repeat with an
explicit retained temporary directory passed in 114.26 seconds and proved
that the admitted census contained no PPS entries. This does not erase or
establish a cause for the original failure.

Inspection identified a separate, definite weakness in that check: it compared
wall UTC timestamps to decide same-host process freshness. The capture owner
now publishes a host-monotonic timestamp and the transport consumer compares
integer nanoseconds against the existing 15-second limit. UTC remains reporting
metadata. There is no compatibility fallback, extra deadline or inferred healthy
state when the timestamp is missing. A direct producer/consumer regression
covers wall-clock jumps, stale, future and malformed monotonic observations.
This change does not claim that every monitor or campaign wall-time diagnostic
is insensitive to civil-clock adjustment, nor establish that such an adjustment
caused the retained rehearsal failure.


## Subsequent operator closure and historical disposition

The operator-authorized attempt is now closed. Capture recorded one
`emergency_abort_sent` at `2026-09-12T10:39:35Z`; retained firmware records show
`queued_to_core1`, `abort_accepted_on_core1`, and a complete ABORTED/fail-static
snapshot. Capture closed at `2026-09-12T10:40:34Z` and exited 0. The bench Mac
reported that all three processes exited and OS inspection found no serial
owner. No new serial query was used to establish that result. No DAC application
was recorded, and the applied code remains explicitly unknown, not assumed zero.

The main checkout had changed while capture was active. Its original runner's
post-close missing-module failure was preserved; shutdown and finalization used
a separate clean checkout at the original `539ff6a`. The frozen analyzer's
review-required seal and append-only registration were completed without
repeating acquisition. This is direct evidence for keeping the running checkout
immutable through closure, including its offline finalization dependencies.

The supplementary archive
`shutdown-supplement-539ff6a-20260912T112946Z.tar.gz` was received on the
development Mac and independently verified: 198,403 bytes, SHA-256
`4ec1ad29d62da5356922d949460a05413530af0a7bdaa181f85cc3bf71403042`,
21 matching manifest entries plus the manifest itself. The raw and health
excerpts, closure, retained states, and shutdown log corroborate the disposition.
The full acquisition was not copied or re-certified with current tools.

The historical analyzer retained one CSV error at row 3920: `count_seq`
3922 to 1. Its D14/D8 reconstruction independently reported exact source
association and arithmetic across the capture sessions. Current-source review
found a CSV validator that incorrectly required a globally increasing CNT
sequence even though the fixed producer uses the closing snapshot ordinal,
which restarts after a new capture-session anchor. That is a reproducible
software-contract mismatch; it does not establish a hardware defect.

The old firmware also recorded one recovered `ref_without_snapshot` association
loss at reference 3923 and a new capture session. This is a diagnosis from the
historical software, not independent proof of an electrical or oscillator fault.
Its physical cause is unestablished. Do not turn this historical label into a
new hardware qualification prerequisite or reinterpret the old run as a pass.
The next decision is a fresh inhibited entry with the corrected, rehearsed
current host and its fixed firmware image.

The current CNT repair removes the standalone CSV's inter-row sequence and
sparse-timestamp comparisons. The existing required SNP/REF/CNT replay already
owns session-qualified adjacency, exact endpoints, duplicates, and ordering.
Per-row domains, numeric bounds, flags, and gate progression remain checked.
A file-backed regression exercises both analyzer CSV validation and actual
measurement replay across ordinal wrap, a later 2-to-1 session restart, and a
long CNT gap with intervening REF chronology. Corrupt source identity still
fails replay, and an invalid gate still fails the CSV check. The full current
suite passed: **674 tests in 95.23 seconds**. Firmware, wire schemas, and the
historical acquisition/seal are unchanged.
