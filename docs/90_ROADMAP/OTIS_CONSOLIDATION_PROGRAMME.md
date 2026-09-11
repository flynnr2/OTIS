# OTIS consolidation programme

Agreed with the operator on 11 September 2026, after closure of the latest
contingent 72-hour attempt. This is the current execution sequence. The older
`OTIS_CANONICAL_WORK_PROGRAMME.md` is an exploratory catalogue, not an approved
hardware migration or an obligation to implement every suggestion.

## Scope and working baseline

Complete a comprehensible, resilient timing instrument on the existing RP2040
bench. Remove obsolete executable paths as replacements become proven; do not
carry compatibility readers, alternative hardware targets, or generalized
framework scaffolding. Preserve historical evidence unchanged and use its
recorded revision for historical interpretation.

The starting checkout is merge `398b747`, whose tree matches bench revision
`f6c72624f6fed29f6be86ae252247ef075d44e2d`. Source is shared through Git. The
older MacBook Pro remains the flashing, physical acquisition, and monitoring
station. This workstation performs development, review, and offline analysis.
The model available on the bench does not change the required evidence or
authority boundaries.

D14 remains the sole PPS reference, D8 the sole oscillator/count source, D10
an optional external-event input, D9 forwarded output, and D6 a diagnostic.
Receiver serial metadata qualifies the receiver; it supplies no timing
authority. New reference rejection or continuation rules apply prospectively
and cannot turn the already closed attempt into a 72-hour pass.

## Retained bench context

The operator reports that the latest attempt is closed and sealed. The remote
handover reports:

- package: `runs/current_platform_stage0/20260910-f6c7262/contingent_72h_physical_attempt1`;
- content SHA-256: `43a596f175122b632bb40a410b33c3bd956923a89d6d09ef0114c178582d0739`;
- 600,757,463 bytes in 55 files, before transfer compression;
- 35,480 of 259,200 required qualified apertures retained;
- operator abort, last confirmed DAC `0xA846`, four completed corrections;
- a D14 extra edge split one aperture into 246.294 ms and 753.707 ms;
  the corresponding D8 counts sum to exactly 10,000,000;
- firmware recovered eligibility, but the frozen uninterrupted-attempt
  contract required the host hold to remain;
- seal integrity reported `passed`, while registration incorrectly described
  the early-aborted attempt as `completed_campaign`.

The package has now been transferred and its complete regular-file content
identity verified locally against the handover hash. A
[targeted retained-evidence review](../60_EXPERIMENTS/CONTINGENT_72H_ATTEMPT1_REVIEW_2026_09_11.md)
supports the incomplete classification, original seal/source identities, and
reported split-aperture arithmetic. It is not a complete historical analyzer
rerun. Two earlier comparable reference incidents
include an extra edge and a missing edge; they need not share one cause. The
handover cannot distinguish receiver output from electrical or capture-input
disturbance. Preserve the source package, original classification, and original
failure records even when publishing a later classification correction.

## Ordered work and decision gates

| Stage | Deliverable | Exit evidence / dependency |
| --- | --- | --- |
| 1. Evidence and outcome semantics | Separate acquisition closure, integrity, scientific result, and registration. Make early abort explicitly incomplete. | Direct registration and recovery reject unsupported completion; unchanged actual package gets a separately identified reviewed correction. |
| 2. Shared experimental evidence | Compact identities/results in Git; closed archives and receipts delivered separately; local checksum-verified analysis copies. | First approximately 601 MB package transfers byte-exactly; original package and local indexes are retained. |
| 3. Reference acceptance contract | State acquisition, tracking, rejection, loss, and causal requalification rules, with explicit accepted-reference anchor and counter domains. | Deterministic examples cover early/late/extra/missing edges, recovery, rollover, session changes, and ambiguous evidence. |
| 4. Firmware and measurement integration | Repair metadata-driven history loss and queue ownership; verify every derived aperture against raw evidence. | Producer-to-first-consumer regressions, raw counter replay, and exact fixed-image build pass. |
| 5. Operational host simplification | One source for campaign predicates, explicit state transitions, independent operator-abort servicing, integrated monitoring, bounded/deduplicated reporting. | Actual runner topology exercises two transactions, holds, command obstruction, abort delivery, owner-preserving closure, analysis, and registration. |
| 6. Bench readiness | Freeze and rehearse the exact source, image, host tools, contract and launch configuration. | Full current release gate, then genuine I/O rehearsal on bench Mac including startup permission and failure behavior. |
| 7. D14 investigation and qualification | One bounded discriminating receiver/line/capture-path investigation, then the authorized sustained campaign. | Record findings or explicit inconclusive result; qualification uses prospectively frozen policy and full retained evidence. |
| 8. Instrument completion | Safely isolated D10 capture, metrology/analysis products and relevant output characterization. | Advance only after the acquisition/control foundation is dependable; optional features cannot veto D14/D8. |

Stages 1–2 and offline parts of 3–5 may overlap when file ownership and
interfaces are clear. Bench stages depend on the complete integrated candidate;
an isolated unit test is not a firmware or physical qualification claim.

### Reference acceptance design constraints

After acquisition has established a reference, evaluate an edge against a
prospectively declared tolerance relative to the last **accepted** reference
or an explicit predicted reference schedule. A rejected extra edge must not
silently become the next timing anchor. Preserve every raw edge and snapshot,
the rejection reason, and the accepted-edge selection.

A coherent pair of cumulative D8 snapshots may support a reconstructed
aperture spanning a rejected extra edge. That claim requires exact session,
counter, sequence and elapsed-domain continuity. It is not permission to invent
a missing PPS timestamp, bridge an unknown capture gap, or conceal the raw
disturbance. Acquisition/reacquisition, permitted consecutive rejections,
phase continuity, estimator eligibility and control resumption all require
explicit rules. Do not merely clear lifetime error counters to resume.

The numerical tolerance and permitted continuation criteria remain design
work. Use observed evidence and deterministic fault cases to assess them;
freeze them before the next physical result is judged.

### Priority integration defects

The review identified these concrete checks/repairs, to be closed with evidence:

- Keep qualified D14/D8 estimation and accumulated phase alive during a
  recoverable GNSS serial-metadata hold; metadata must gate new actuation.
- Ensure one consumer for each single-producer/single-consumer cross-core
  output queue, including pre-carrier drainage and USB attachment transitions.
- Reconstruct CNT from raw SNP/REF records before comparing selected estimates;
  derived consistency alone cannot establish raw measurement truth.
- Include capture freshness and the read-only monitor in the actual runner
  lifecycle, not only in a rehearsal-specific topology.
- Service explicit operator abort while awaiting a fresh causal snapshot and
  under normal-command/output obstruction; submission and delivery remain
  separate recorded facts.
- Bound the full causal age of receiver qualification across cores. Audit
  actuator deadline rollover in its actual clock domain.
- Make persistent holds report transitions and retained counters rather than
  tens of thousands of identical event messages.

Do not broaden an active physical repair into unrelated architecture work.
The 30-minute discriminating-check rule in `AGENTS.md` still applies to anomaly
investigations. Long-term rewrites require a demonstrated simplification and
an end-to-end gate, not just fewer lines in one file.

## Execution record

11 September: implementation authorized. Development began with offline outcome
classification, independent registration regressions, raw-counter replay, and
closed-package transfer. No hardware state or source experimental evidence was
changed. The initial Python development environment was installed locally from
the declared project dependencies.

The bench package is now present and content-verified; its external original
index/journal was not included. The retained-evidence review records the
classification clarification; formal registry correction remains pending access
to the original external registration. The installed local Arduino core was reported as 6.1.0
while the fixed build pins 6.0.0; do not represent a host test as an exact-image
build or silently substitute the installed core.

The first integrated change contains prospective outcome classification and
registration checks, byte-exact closed-package transfer, raw SNP/REF-to-CNT-to-
EST replay and physical AHY source binding, the metadata-history/causal-age
repair, and exclusive Core 0 output-queue consumption. Campaign-tier checks now
include the actual operational rehearsal and these affected regressions.

Independent review of the metadata repair identified two additional coupled
requirements: lifecycle decisions must record their production time after
metadata transitions, and a metadata transition plus selected response needs
nine evidence frames without concurrent drainage. The candidate preserves raw
capture times, adds the explicit bounded capture-to-decision relation, and
uses a sixteen-slot power-of-two evidence queue. A native integration links the
actual frequency adapter, active adapter and immutable queue and exercises that
complete delayed-capture/metadata/response boundary. Exact firmware RAM
verification remains a separate gate.

An isolated pinned Arduino environment has been prepared under ignored local
build storage. The manifest binds the official x86 compiler-tree digest; the
native ARM package with the same version has different bytes. The isolated
x86 CLI/toolchain passes the original environment verifier without changing
the shared Arduino installation or relaxing any manifest hash or memory limit.

The operator supplied the completed transfer archive at
`/Users/richardflynn/Documents/OTIS_DATA/contingent_72h_physical_attempt1.tar.gz`.
It is 67,278,492 bytes compressed and contains exactly the reported 55 regular
files and 600,757,463 uncompressed bytes. Local extraction into ignored
`runs/imported/43a596f175122b632bb40a410b33c3bd956923a89d6d09ef0114c178582d0739`
reproduced the prior sender package hash exactly. The ordinary tar also contains
three inert command FIFO entries; these were recorded in the local receipt and
not recreated. All regular files and the source archive remain unchanged.
The observed archive SHA-256 is
`60d0bc5d54e7ef8926f17b15c0c299c937ed4a7d57d3f3ac3620b6dce0622086`;
no separate sender archive digest was supplied. Transfer verification relies on
the independently supplied package identity and does not claim scientific validation.

The integrated host/native suite passed: 512 tests, including the real
process/FIFO rehearsal and the coupled metadata/response native regression.
Exact fixed-image compilation and RAM verification are the next gate; passing
this suite alone does not authorize bench entry.

The candidate is on local branch `codex/otis-consolidation`. Staging was
blocked by this Codex session's filesystem permissions:
`Unable to create .git/index.lock: Operation not permitted`. The operator has
authorized publication through the GitHub API as a remote commit and draft PR.
That publication does not synchronize this local checkout. Before the exact
builder can bind clean operational source, the committed candidate must be
checked out through an authorized Git interface. No firmware build is claimed;
do not bypass the Git restriction or the builder's dirty-source guard.

The GitHub connector's commit tool required approval unavailable in this
session. The operator requested the established push/PR handoff, and the
authenticated GitHub CLI provides the alternative remote publication route.
Publication binds the complete candidate tree to the original parent commit
and verifies the returned Git tree identity without changing protected local
Git metadata. The resulting PR remains draft pending the gates below.

The received physical package exposed an additional raw-replay assumption:
`REF.event_seq` and `SNP.reference_sequence` are different producer counters.
Real evidence had a 1000-count offset, and external events can change that
offset. Replay now requires a unique ordered correspondence of entire session
timestamp sequences, while preserving independent sequence domains and allowing
REF emission gaps caused by external events. Independent review confirms all
52,310 retained SNP/REF associations, including twelve native timer wraps;
44 focused raw-replay/isolation tests passed. The previous 512-test result
does not cover this later correction or the transfer endpoint repair.

The historical first retained CNT has no retained opening SNP. It remains
explicitly unproved, and current strict raw replay does not declare the entire
package exact merely because its other 52,309 adjacent pairs reconstruct.
Before bench readiness, the operational capture-start boundary must provide
the opening anchor for every CNT required by the new seal; synthetic rehearsal
anchors alone do not establish this producer-to-recorder property.

The ordinary transferred archive also exposed the runner's retained command
FIFO endpoints. The closed-package publisher now reports and omits only those
three exact runtime endpoints after closure checks, preserving all regular-file
evidence. Unknown special files and active packages still fail closed.

Final integration after these repairs passed all 528 host/native tests in
108.88 seconds, including the actual process/FIFO rehearsal. Canonical
publication of a separate extraction of the real package preserved its exact
55-file content identity and all three source FIFO endpoints, recording their
omission from the files-only archive. The resulting archive is 67,280,704 bytes;
receipt-based receiver verification against the existing verified local copy
also passed. Source evidence and the original supplied archive remain unchanged.
Exact firmware compilation/RAM verification, physical capture-start anchor
coverage, and bench rehearsal remain outstanding. Remote publication does not
make this local working tree clean; the committed candidate must be synchronized
through an authorized Git interface before its exact firmware build.

After commit, the prepared local build invocation from the repository root is:

```sh
export ARDUINO_DIRECTORIES_DATA="$PWD/build/arduino-consolidation/x86/data"
export ARDUINO_DIRECTORIES_DOWNLOADS="$PWD/build/arduino-consolidation/x86/downloads"
export ARDUINO_DIRECTORIES_USER="$PWD/build/arduino-consolidation/x86/user"
.venv/bin/python tools/build_firmware.py \
  --arduino-cli "$PWD/build/arduino-consolidation/x86/cli/arduino-cli" \
  --output-dir "$PWD/build/arduino-consolidation/firmware"
```

PR #173 was merged as `4314e6edbd972d22be29708452f880223631e361`,
and the synchronized clean checkout passed the pinned fixed-image build.
Static RAM is 147,572 bytes, with 114,572 bytes available at runtime and
9,714 bytes of headroom against the declared resource limits. The resulting
UF2 SHA-256 is
`939a97aafac2ccc8a2d5e2271c6a0f243d778404030ac5c59bfbf48d9a46d21c`.
This closes the previously outstanding compilation/resource gate for that
revision; no image was flashed and no physical qualification is claimed.

The next host integration addresses attachment to an already running producer.
A prospectively frozen acquisition-frontier contract retains every raw byte
and canonical row, records the first complete reconstructable opening pair
live, and identifies earlier incomplete observations explicitly. Manual SETUP
requires that recorded pair. Feedback authority additionally requires the
selected estimate's complete 600-interval source in the current capture
session. An estimate that leads raw queue drainage waits for its source;
contradictory evidence or an observer failure holds new authority while the
capture owner continues recording and servicing operator abort.

The historical package does not acquire this new acceptance policy. Its first
unproved aperture and incomplete scientific outcome remain unchanged. The
current tranche changes host tooling, tests and documentation; the exact
firmware build above remains evidence for its recorded firmware revision.
Bench entry still requires a frozen integrated bundle and an actual I/O
rehearsal on the older MacBook.

The integrated acquisition-frontier candidate passed all 552 current
host/native tests in 131.46 seconds. Its actual process/FIFO rehearsal retains
4,800 apertures and exercises two transactions, source admission, independent
abort delivery, analysis, sealing and registration. Separate real-recorder
regressions cover attachment boundaries and a verifier exception after
readiness: recording continues, the error remains latched, and the supervisor
refuses new authority despite an older ready proof.

Live recording and offline analysis now share a lower-level raw reconstruction
module; the dependency graph remains acyclic. Activation, rehearsal and
registration derive transaction identities from the same frozen-input helper.
The complete current offline supersession tool identity also includes these
new dependencies. These results establish the host integration, not the real
firmware/USB boundary or physical PPS rejection policy. The next design stage
is accepted-reference selection and causal requalification; its new criteria
must be frozen before a new physical qualification.

Keep this execution record current at integration boundaries, recording checks
actually run and explicit remaining dependencies. Do not mark a stage complete
because code exists or a fixture passes.
